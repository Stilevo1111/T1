import asyncio
import aiohttp
import io
import os
import logging

from datetime import datetime, timezone, timedelta
from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

BACKGROUND_PATH = "background_new.png"

FONT_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/TTF/DejaVuSans.ttf",
    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/System/Library/Fonts/Arial.ttf",
    "/Library/Fonts/Arial.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "C:/Windows/Fonts/Arial.ttf",
]

FONT_PATH = None
for path in FONT_PATHS:
    try:
        ImageFont.truetype(path, 12)
        FONT_PATH = path
        logger.info("Using font: %s", path)
        break
    except Exception:
        continue

if FONT_PATH is None:
    FONT_PATH = ImageFont.load_default()
    logger.warning("Using default PIL font as no system fonts found")


# =========================================================
# ROLE DETECTION
# =========================================================

def detect_hero_position(hero_roles):
    """
    Automatic hero position detection based on roles.
    Role priority: Carry > Nuker/Escape > Durable/Initiator > Support+Disabler > Support
    """
    roles = set(hero_roles)

    if "Carry" in roles:
        return 1
    if "Nuker" in roles or "Escape" in roles:
        return 2
    if "Durable" in roles or "Initiator" in roles:
        return 3
    if "Support" in roles and "Disabler" in roles:
        return 4
    if "Support" in roles and "Disabler" not in roles:
        return 5
    return None


# =========================================================
# IMAGE STYLE
# =========================================================

def apply_fancy_style(img, size=(188, 100), radius=15, border_width=3):
    """Закругление и золотая обводка"""
    outer_size = (size[0] + 2 * border_width, size[1] + 2 * border_width)
    img_scaled = img.resize(size, Image.Resampling.LANCZOS)
    mask = Image.new('L', size, 0)
    draw_mask = ImageDraw.Draw(mask)
    draw_mask.rounded_rectangle((0, 0) + size, radius=radius, fill=255)
    output = Image.new('RGBA', outer_size, (0, 0, 0, 0))
    output.paste(img_scaled, (border_width, border_width), mask=mask)
    draw_border = ImageDraw.Draw(output)
    draw_border.rounded_rectangle(
        (0, 0) + outer_size, radius=radius,
        outline=(255, 215, 0, 255), width=2
    )
    return output


# =========================================================
# HERO ICON DOWNLOAD
# =========================================================

async def fetch_hero_icon(session, icon_path):
    """Асинхронная загрузка иконки героя из Steam CDN"""
    if not icon_path.startswith("http"):
        if not icon_path.startswith("/"):
            icon_path = "/" + icon_path
        icon_url = "https://cdn.cloudflare.steamstatic.com%s" % icon_path
    else:
        icon_url = icon_path

    try:
        async with session.get(icon_url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
            resp.raise_for_status()
            content = await resp.read()
            return Image.open(io.BytesIO(content)).convert("RGBA")
    except Exception as e:
        logger.error("Failed to load icon %s: %s", icon_path, e)
        raise


# =========================================================
# HERO STATS — heroStats API
# =========================================================

async def get_dota_data():
    """Загрузка heroStats из OpenDota API"""
    url = "https://api.opendota.com/api/heroStats"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status != 200:
                    raise Exception("HTTP %d" % resp.status)
                data = await resp.json()
                logger.info("Loaded %d heroes from heroStats", len(data))
                return data
    except Exception as e:
        logger.error("heroStats error: %s", e)
        return None


# =========================================================
# BUILD GRID — role-based, no duplicates
# =========================================================

def _build_grid(hero_stats):
    """
    Строит сетку 5 колонок.
    Позиция определяется через hero["roles"] → detect_hero_position.
    Каждый герой только в одной колонке (основная позиция).
    Минимум 20 pro_pick. Топ-5 по WR на позицию.
    """
    by_position = {1: [], 2: [], 3: [], 4: [], 5: []}

    for hero in hero_stats:
        pro_pick = hero.get("pro_pick", 0)
        if pro_pick < 20:
            continue

        pos = detect_hero_position(hero.get("roles", []))
        if not pos:
            continue

        pro_win = hero.get("pro_win", 0)
        wr = (pro_win / pro_pick * 100) if pro_pick > 0 else 0

        by_position[pos].append({
            "id": hero["id"],
            "name": hero.get("localized_name", "Hero %d" % hero["id"]),
            "img": hero.get("img", ""),
            "wr": round(wr, 1),
            "picks": pro_pick,
            "wins": pro_win,
        })

    grid = {}
    for pos in range(1, 6):
        grid[pos] = sorted(by_position[pos], key=lambda h: -h["wr"])[:5]
    return grid


# =========================================================
# INFOGRAPHIC — 1200x800, old layout
# =========================================================

async def create_infographic(hero_stats):
    """Баннер 1200x800: 5 колонок (позиции), по 5 героев. Без дублей, без подписей."""
    logger.info("Starting create_infographic")

    if os.path.exists(BACKGROUND_PATH):
        base = Image.open(BACKGROUND_PATH).convert("RGBA")
        bg_width, bg_height = base.size
    else:
        bg_width, bg_height = 1200, 800
        base = Image.new("RGBA", (bg_width, bg_height), (25, 25, 35, 255))

    draw = ImageDraw.Draw(base)

    # Дата (только если есть фон)
    if os.path.exists(BACKGROUND_PATH):
        MSK = timezone(timedelta(hours=3))
        date_text = datetime.now(MSK).strftime("%d.%m.%Y %H:%M")
        try:
            date_font = ImageFont.truetype(FONT_PATH, 24)
        except Exception:
            date_font = ImageFont.load_default()
        try:
            bbox = draw.textbbox((0, 0), date_text, font=date_font)
            tw = bbox[2] - bbox[0]
        except Exception:
            tw = 0
        draw.text((bg_width - tw - 20, 20), date_text, fill=(255, 255, 255), font=date_font)

    margin_x = 50
    margin_y = 215
    gap_between_cols = 15

    col_width = (bg_width - 2 * margin_x - 6 * gap_between_cols) // 5
    row_height = (bg_height - margin_y - 10) // 5

    base_icon_height = row_height - 25
    icon_height = min(int(base_icon_height * 1.163), row_height - 5)

    try:
        font_wr = ImageFont.truetype(FONT_PATH, 27)
        for bn in ['arialbd.ttf', 'Arial-Bold.ttf', 'DejaVuSans-Bold.ttf']:
            try:
                font_wr = ImageFont.truetype("C:/Windows/Fonts/%s" % bn, 20)
                break
            except Exception:
                continue
    except Exception:
        font_wr = ImageFont.load_default()

    # Сетка
    grid = _build_grid(hero_stats)

    # Уникальные герои
    all_heroes = []
    seen_ids = set()
    for pos in range(1, 6):
        for h in grid[pos]:
            if h["id"] not in seen_ids:
                seen_ids.add(h["id"])
                all_heroes.append(h)

    # Асинхронная загрузка иконок
    async with aiohttp.ClientSession() as session:
        tasks = [fetch_hero_icon(session, h["img"]) for h in all_heroes]
        icons = {}
        for i, hero in enumerate(all_heroes):
            try:
                icons[hero["id"]] = await tasks[i]
            except Exception:
                icons[hero["id"]] = None

    # Отрисовка: колонка = позиция, строки = топ героев позиции
    for col_idx in range(5):
        pos = col_idx + 1
        heroes = grid[pos]

        for row_idx, hero in enumerate(heroes[:5]):
            x = margin_x + col_idx * (col_width + gap_between_cols)
            y = margin_y + row_idx * row_height

            icon_raw = icons.get(hero["id"])
            if icon_raw is None:
                draw.rounded_rectangle(
                    [x + 5, y + 5, x + col_width - 5, y + icon_height],
                    radius=10, fill=(80, 80, 80)
                )
                try:
                    ph_font = ImageFont.truetype(FONT_PATH, 16)
                except Exception:
                    ph_font = ImageFont.load_default()
                draw.text((x + 10, y + icon_height // 2 - 8), "N/A", fill=(120, 120, 120), font=ph_font)
                continue

            # Масштабирование
            scale = icon_height / icon_raw.height
            nw = int(icon_raw.width * scale)
            nh = icon_height
            if nw > col_width:
                scale = col_width / icon_raw.width
                nw = col_width
                nh = int(icon_raw.height * scale)

            icon_scaled = icon_raw.resize((nw, nh), Image.Resampling.LANCZOS)
            icon_proc = apply_fancy_style(icon_scaled, size=(nw, nh),
                                          radius=max(8, nh // 12), border_width=2)

            pw = nw + 4
            icon_x = x + (col_width - pw) // 2
            icon_y = y + 5

            base.paste(icon_proc, (icon_x, icon_y), icon_proc)

            # WR текст
            wr_text = "%d%%" % round(hero["wr"])

            try:
                font_lg = ImageFont.truetype(FONT_PATH, 28)
                for bn in ['arialbd.ttf', 'Arial-Bold.ttf', 'DejaVuSans-Bold.ttf']:
                    try:
                        font_lg = ImageFont.truetype("C:/Windows/Fonts/%s" % bn, 28)
                        break
                    except Exception:
                        continue
            except Exception:
                font_lg = ImageFont.load_default()

            try:
                bb = draw.textbbox((0, 0), wr_text, font=font_lg)
                tw = bb[2] - bb[0]
                th = bb[3] - bb[1]
                tx = icon_x + pw // 2 - tw // 2
                ty = icon_y + nh + 2 - 12 - th
                draw.text((tx, ty), wr_text, fill=(255, 255, 255), font=font_lg)
            except Exception:
                draw.text((icon_x + pw // 2 - 20, icon_y + nh - 30),
                          wr_text, fill=(255, 255, 255), font=font_lg)

    buf = io.BytesIO()
    base.save(buf, format='PNG')
    return buf.getvalue()


# =========================================================
# MAIN ENTRY POINT
# =========================================================

async def get_hero_meta_image():
    """Generate hero meta image"""
    logger.info("get_hero_meta_image called")
    try:
        data = await get_dota_data()
        if not data:
            logger.error("No data from OpenDota")
            return get_static_fallback_banner()
        banner = await create_infographic(data)
        if banner:
            return banner
        return get_static_fallback_banner()
    except Exception as e:
        logger.warning("Hero meta generation failed: %s", e)
        return get_static_fallback_banner()


def get_static_fallback_banner():
    """Статичный баннер когда API недоступен"""
    logger.info("Generating static fallback banner")
    try:
        base = Image.new("RGBA", (1200, 800), (25, 25, 35, 255))
        draw = ImageDraw.Draw(base)
        MSK = timezone(timedelta(hours=3))
        date_text = datetime.now(MSK).strftime("%d.%m.%Y %H:%M")
        try:
            font = ImageFont.truetype(FONT_PATH, 32)
        except Exception:
            font = ImageFont.load_default()
        draw.text((20, 20), "Dota 2 Hero Meta", fill=(255, 215, 0), font=font)
        draw.text((20, 70), "Updated: %s" % date_text, fill=(200, 200, 200), font=font)
        draw.text((20, 120), "API unavailable", fill=(150, 150, 150), font=font)
        buf = io.BytesIO()
        base.save(buf, format='PNG')
        return buf.getvalue()
    except Exception as e:
        logger.error("Static banner error: %s", e)
        return None