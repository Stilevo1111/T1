import asyncio
import aiohttp
import io
import os
import logging

from datetime import datetime
from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

BACKGROUND_PATH = "background_new.png"

FONT_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/arial.ttf",
]

FONT_PATH = None
for path in FONT_PATHS:
    if os.path.exists(path):
        FONT_PATH = path
        break


def detect_hero_position(hero_roles):
    """
    Automatic hero position detection based on roles.
    Support без Disabler → POS5
    Support + Disabler → POS4
    Durable или Initiator → POS3
    Nuker или Escape → POS2
    Carry → POS1
    """
    hero_roles = set(hero_roles)

    if "Support" in hero_roles and "Disabler" not in hero_roles:
        return 5
    if "Support" in hero_roles and "Disabler" in hero_roles:
        return 4
    if "Durable" in hero_roles or "Initiator" in hero_roles:
        return 3
    if "Nuker" in hero_roles or "Escape" in hero_roles:
        return 2
    if "Carry" in hero_roles:
        return 1
    return None


def apply_fancy_style(img, size=None, radius=15, border_width=3):
    """Закругление и золотая обводка"""
    if size:
        img = img.resize(size, Image.Resampling.LANCZOS)

    width, height = img.size
    mask = Image.new("L", (width, height), 0)
    draw_mask = ImageDraw.Draw(mask)
    draw_mask.rounded_rectangle((0, 0, width, height), radius=radius, fill=255)

    outer_size = (width + 2 * border_width, height + 2 * border_width)
    output = Image.new("RGBA", outer_size, (0, 0, 0, 0))
    output.paste(img, (border_width, border_width), mask=mask)

    draw_border = ImageDraw.Draw(output)
    draw_border.rounded_rectangle(
        (0, 0) + outer_size, radius=radius, outline=(255, 215, 0, 255), width=2
    )
    return output


async def fetch_hero_icon(session, hero_img):
    """Асинхронная загрузка иконки героя из Steam CDN"""
    if not hero_img.startswith("/"):
        hero_img = "/" + hero_img
    url = f"https://cdn.cloudflare.steamstatic.com{hero_img}"

    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            resp.raise_for_status()
            content = await resp.read()
            return Image.open(io.BytesIO(content)).convert("RGBA")
    except Exception as e:
        logger.warning(f"Failed to load icon {url}: {e}")
        raise


async def get_dota_data():
    """Загрузка heroStats из OpenDota"""
    url = "https://api.opendota.com/api/heroStats"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    logger.info(f"Loaded {len(data)} heroes from heroStats")
                    return data
                else:
                    logger.error(f"heroStats HTTP {resp.status}")
                    return None
    except Exception as e:
        logger.error(f"heroStats error: {e}")
        return None


def _build_position_grid(hero_stats):
    """
    Строит сетку 5x5: каждый герой на своей ОСНОВНОЙ позиции.
    Основная позиция = та, где максимум pro_pick.
    Без дублей — каждый герой только в одном столбце.
    Минимум 20 pro_pick.
    """
    hero_main_pos = {}
    for hero in hero_stats:
        best_pos = None
        best_picks = 0
        for pos in range(1, 6):
            pk = hero.get(f"{pos}_pick", 0)
            if pk > best_picks:
                best_picks = pk
                best_pos = pos
        if best_pos and best_picks >= 1:
            hero_main_pos[hero["id"]] = best_pos

    by_position = {1: [], 2: [], 3: [], 4: [], 5: []}
    for hero in hero_stats:
        hid = hero["id"]
        if hid not in hero_main_pos:
            continue
        pos = hero_main_pos[hid]
        picks = hero.get(f"{pos}_pick", 0)
        if picks < 1:
            continue
        wins = hero.get(f"{pos}_win", 0)
        wr = (wins / picks * 100) if picks > 0 else 0
        by_position[pos].append({
            "id": hid,
            "name": hero.get("localized_name", f"Hero {hid}"),
            "img": hero.get("img", ""),
            "icon": hero.get("icon", ""),
            "wr": round(wr, 1),
            "picks": picks,
            "wins": wins,
        })

    grid = {}
    for pos in range(1, 6):
        grid[pos] = sorted(by_position[pos], key=lambda h: -h["wr"])[:5]

    return grid


async def create_infographic(hero_stats):
    """Баннер 1500x900: 5 колонок (позиции), по 5 героев."""
    logger.info("Starting create_infographic")

    if os.path.exists(BACKGROUND_PATH):
        base = Image.open(BACKGROUND_PATH).convert("RGBA")
        base = base.resize((1500, 900))
        bg_width, bg_height = base.size
    else:
        bg_width, bg_height = 1500, 900
        base = Image.new("RGBA", (bg_width, bg_height), (25, 25, 35, 255))

    draw = ImageDraw.Draw(base)

    # Дата
    try:
        date_font = ImageFont.truetype(FONT_PATH, 24)
    except Exception:
        date_font = ImageFont.load_default()

    now_text = datetime.now().strftime("%d.%m.%Y %H:%M")
    try:
        bbox = draw.textbbox((0, 0), now_text, font=date_font)
        tw = bbox[2] - bbox[0]
    except Exception:
        tw = 0
    draw.text((bg_width - tw - 20, 15), now_text, fill=(200, 200, 200), font=date_font)

    margin_x = 30
    margin_y = 70
    gap_cols = 10
    col_width = (bg_width - 2 * margin_x - 6 * gap_cols) // 5
    row_height = (bg_height - margin_y - 20) // 5

    base_icon_h = row_height - 30
    icon_h = min(int(base_icon_h * 1.163), row_height - 10)

    # WR font
    try:
        font_wr = ImageFont.truetype(FONT_PATH, 22)
    except Exception:
        font_wr = ImageFont.load_default()

    # Строим сетку
    grid = _build_position_grid(hero_stats)

    # Уникальные герои
    all_heroes = []
    seen = set()
    for pos in range(1, 6):
        for h in grid[pos]:
            if h["id"] not in seen:
                seen.add(h["id"])
                all_heroes.append(h)

    # Асинхронная загрузка иконок
    async with aiohttp.ClientSession() as session:
        tasks = [fetch_hero_icon(session, h.get("icon", h.get("img", ""))) for h in all_heroes]
        icons = {}
        for i, hero in enumerate(all_heroes):
            try:
                icons[hero["id"]] = await tasks[i]
            except Exception:
                icons[hero["id"]] = None

    # Отрисовка
    for col_idx in range(5):
        pos = col_idx + 1
        heroes = grid[pos]

        for row_idx, hero in enumerate(heroes[:5]):
            x = margin_x + col_idx * (col_width + gap_cols)
            y = margin_y + row_idx * row_height

            icon_raw = icons.get(hero["id"])
            if icon_raw is None:
                draw.rounded_rectangle(
                    [x + 5, y + 5, x + col_width - 5, y + icon_h],
                    radius=10, fill=(80, 80, 80)
                )
                try:
                    ph_font = ImageFont.truetype(FONT_PATH, 14)
                except Exception:
                    ph_font = ImageFont.load_default()
                draw.text((x + 10, y + icon_h // 2 - 8), "N/A", fill=(120, 120, 120), font=ph_font)
                continue

            # Масштабирование
            scale = icon_h / icon_raw.height
            nw = int(icon_raw.width * scale)
            nh = icon_h
            if nw > col_width:
                scale = col_width / icon_raw.width
                nw = col_width
                nh = int(icon_raw.height * scale)

            icon_scaled = icon_raw.resize((nw, nh), Image.Resampling.LANCZOS)
            icon_proc = apply_fancy_style(icon_scaled, radius=max(8, nh // 12), border_width=2)

            pw = nw + 4
            icon_x = x + (col_width - pw) // 2
            icon_y = y + 5

            base.paste(icon_proc, (icon_x, icon_y), icon_proc)

            # WR текст
            wr_text = f"{round(hero['wr'])}%"
            try:
                bb = draw.textbbox((0, 0), wr_text, font=font_wr)
                tw = bb[2] - bb[0]
                th = bb[3] - bb[1]
                tx = icon_x + pw // 2 - tw // 2
                ty = icon_y + nh + 2 - 12 - th
                draw.text((tx, ty), wr_text, fill=(255, 255, 255), font=font_wr)
            except Exception:
                draw.text((icon_x + pw // 2 - 20, icon_y + nh - 30),
                          wr_text, fill=(255, 255, 255), font=font_wr)

    buf = io.BytesIO()
    base.save(buf, format="PNG")
    return buf.getvalue()


async def get_hero_meta_image():
    """Generate hero meta image"""
    logger.info("get_hero_meta_image called")
    try:
        data = await get_dota_data()
        if not data:
            logger.error("No hero stats from OpenDota")
            return _static_fallback()
        banner = await create_infographic(data)
        if banner:
            return banner
        return _static_fallback()
    except Exception as e:
        logger.warning(f"Hero meta generation failed: {e!r}")
        return _static_fallback()


def _static_fallback():
    """Статичный баннер если API недоступен"""
    logger.info("Generating static fallback banner")
    try:
        base = Image.new("RGBA", (1500, 900), (25, 25, 35, 255))
        draw = ImageDraw.Draw(base)
        try:
            font = ImageFont.truetype(FONT_PATH, 36)
        except Exception:
            font = ImageFont.load_default()
        draw.text((50, 30), "DOTA 2 HERO META", fill=(255, 215, 0), font=font)
        draw.text((50, 100), "API временно недоступен", fill=(150, 150, 150), font=font)
        buf = io.BytesIO()
        base.save(buf, format="PNG")
        return buf.getvalue()
    except Exception as e:
        logger.error(f"Static banner error: {e!r}")
        return None