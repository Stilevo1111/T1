# hero_meta.py — heroStats API + role-based positions, layout = dc5d7a5 (a32f3e8)

import asyncio
import aiohttp
import io
import os
import logging
from urllib.parse import urlparse

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


def detect_hero_position(hero_roles):
    """Определяет позицию (1-5) по ролям из heroStats. Case-insensitive.
    Более гибкая логика для равномерного распределения.
    """
    roles = set((r or "").lower().strip() for r in hero_roles)

    # Position 1 (Carry): Primary carry heroes
    if "carry" in roles and "support" not in roles:
        return 1

    # Position 5 (Soft Support): Support without disabler or complex support
    if "support" in roles and ("disabler" not in roles or len(roles) > 3):
        return 5

    # Position 4 (Hard Support): Support + Disabler
    if "support" in roles and "disabler" in roles and len(roles) <= 3:
        return 4

    # Position 3 (Offlane): Durable/Initiator focused
    if ("durable" in roles or "initiator" in roles) and "carry" not in roles:
        return 3

    # Position 2 (Mid): Nuker/Escape or fallback for complex heroes
    if "nuker" in roles or "escape" in roles:
        return 2

    # Additional assignments for better distribution
    if "carry" in roles:
        return 1  # Carry heroes that also support go to position 1

    if "support" in roles:
        return 5  # Support heroes that are complex go to position 5

    if "disabler" in roles:
        return 4  # Disablers without support go to position 4

    if "durable" in roles or "initiator" in roles:
        return 3  # Tanky heroes go to position 3

    # Final fallback: distribute remaining heroes by priority
    # Many heroes have multiple roles, assign based on most common usage
    if len(roles) > 2:  # Complex heroes
        return 2  # Default to mid for complex heroes
    elif "pusher" in roles:
        return 1  # Pushers often carry
    else:
        return 2  # Default to mid


def apply_fancy_style(img, size=(188, 100), radius=15, border_width=3):
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


async def fetch_hero_icon(session, icon_path):
    if icon_path.startswith('/'):
        icon_url = "https://cdn.cloudflare.steamstatic.com%s" % icon_path
    elif not icon_path.startswith('http'):
        icon_url = "https://cdn.cloudflare.steamstatic.com/%s" % icon_path
    else:
        icon_url = icon_path
    try:
        async with session.get(icon_url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
            resp.raise_for_status()
            content = await resp.read()
            return Image.open(io.BytesIO(content)).convert("RGBA")
    except Exception as e:
        logger.error("Failed to load icon: %s", e)
        raise


async def get_dota_data(days=7):
    url = "https://api.opendota.com/api/heroStats"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    logger.info("Loaded %d heroes from heroStats", len(data))
                    return data
                else:
                    logger.error("heroStats HTTP %d", resp.status)
                    return None
    except Exception as e:
        logger.error("heroStats error: %s", e)
        return None


def _build_grid(hero_stats):
    """
    Сетка 5 колонок с героями на своих позициях по ролям.
    1) Определяем позицию героя по его ролям.
    2) Используем винрейт героя на этой конкретной позиции.
    3) Сортируем по винрейту на позиции и берем топ героев.
    """
    by_position = {1: [], 2: [], 3: [], 4: [], 5: []}

    for hero in hero_stats:
        pro_pick = hero.get("pro_pick", 0)
        if pro_pick < 20:
            continue

        hero_id = hero["id"]

        # Определяем позицию по ролям
        pos = detect_hero_position(hero.get("roles", []))
        if not pos:
            continue

        # Используем винрейт героя именно на этой позиции
        pk = hero.get("%d_pick" % pos, 0)
        wk = hero.get("%d_win" % pos, 0)

        # Минимальный порог пиков для надежности (снижен для Position 2 и 5)
        min_picks = 500 if pos in [2, 5] else 1000
        if pk < min_picks:
            continue

        wr = (wk / pk * 100) if pk > 0 else 0

        by_position[pos].append({
            'id': hero_id,
            'name': hero.get("localized_name", 'Hero %d' % hero_id),
            'img': hero.get("img", ""),
            'wr': wr,
            'picks': pk,
            'wins': wk,
        })

    grid = {}
    for pos in range(1, 6):
        heroes = sorted(by_position[pos], key=lambda h: -h['wr'])
        grid[pos] = heroes

    # Balance positions: ensure minimum 3 heroes per position
    # If a position has too few heroes, take from positions with excess
    target_min = 3

    # First pass: collect positions that need more heroes
    needs_heroes = []
    excess_heroes = []

    for pos in range(1, 6):
        count = len(grid[pos])
        if count < target_min and count > 0:
            needs_heroes.append((pos, target_min - count))
        elif count > 5:
            excess_heroes.append((pos, count - 5))

    # Redistribute heroes from positions with excess to positions that need them
    for need_pos, need_count in needs_heroes:
        for excess_pos, excess_count in excess_heroes:
            if excess_count <= 0:
                continue

            # Take heroes from excess position (lowest WR first)
            to_move = min(need_count, excess_count)
            moved_heroes = grid[excess_pos][-to_move:]
            grid[excess_pos] = grid[excess_pos][:-to_move]
            grid[need_pos].extend(moved_heroes)

            need_count -= to_move
            excess_count -= to_move

            if need_count <= 0:
                break

    # Final pass: limit to 5 heroes per position, sorted by WR
    final_grid = {}
    for pos in range(1, 6):
        heroes = sorted(grid[pos], key=lambda h: -h['wr'])
        final_grid[pos] = heroes[:5] if len(heroes) >= 3 else heroes

    return final_grid
    return grid


async def create_infographic(hero_stats):
    logger.info("Starting create_infographic")

    if not os.path.exists(BACKGROUND_PATH):
        base = Image.new("RGBA", (1200, 800), (25, 25, 35, 255))
        bg_width, bg_height = 1200, 800
    else:
        base = Image.open(BACKGROUND_PATH).convert("RGBA")
        bg_width, bg_height = base.size

    draw = ImageDraw.Draw(base)

    from datetime import datetime, timezone, timedelta
    MSK = timezone(timedelta(hours=3))
    now_msk = datetime.now(MSK)
    date_text = now_msk.strftime("%d.%m.%Y %H:%M")

    try:
        date_font = ImageFont.truetype(FONT_PATH, 24)
    except:
        date_font = ImageFont.load_default()
    try:
        bbox = draw.textbbox((0, 0), date_text, font=date_font)
        tw = bbox[2] - bbox[0]
    except:
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
        font_lg = ImageFont.truetype(FONT_PATH, 28)
        for bn in ['arialbd.ttf', 'Arial-Bold.ttf', 'DejaVuSans-Bold.ttf']:
            try:
                font_lg = ImageFont.truetype("C:/Windows/Fonts/%s" % bn, 28)
                break
            except:
                continue
    except:
        font_lg = ImageFont.load_default()

    grid = _build_grid(hero_stats)

    all_heroes = []
    seen_ids = set()
    for pos in range(1, 6):
        for h in grid[pos]:
            if h['id'] not in seen_ids:
                seen_ids.add(h['id'])
                all_heroes.append(h)

    async with aiohttp.ClientSession() as session:
        tasks = [fetch_hero_icon(session, h['img']) for h in all_heroes]
        icons = {}
        for i, hero in enumerate(all_heroes):
            try:
                icons[hero['id']] = await tasks[i]
            except Exception:
                icons[hero['id']] = None

    for col_idx in range(5):
        pos = col_idx + 1
        heroes = grid[pos]

        for row_idx, hero in enumerate(heroes[:5]):
            x = margin_x + col_idx * (col_width + gap_between_cols)
            y = margin_y + row_idx * row_height

            icon_raw = icons.get(hero['id'])

            if icon_raw is None:
                draw.rounded_rectangle(
                    [x + 20, y + 5, x + col_width - 5, y + icon_height],  # Shift rectangle right by 15
                    radius=10, fill=(80, 80, 80)
                )
                try:
                    ph_font = ImageFont.truetype(FONT_PATH, 16)
                except:
                    ph_font = ImageFont.load_default()
                draw.text((x + 25, y + icon_height // 2 - 8), "N/A", fill=(120, 120, 120), font=ph_font)  # Shift text right by 15
                continue

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
            icon_x = x + (col_width - pw) // 2 + 15  # Shift right by 15 pixels
            icon_y = y + 5

            base.paste(icon_proc, (icon_x, icon_y), icon_proc)

            wr_text = "%d%%" % round(hero['wr'])

            try:
                bb = draw.textbbox((0, 0), wr_text, font=font_lg)
                tw = bb[2] - bb[0]
                th = bb[3] - bb[1]
                tx = icon_x + pw // 2 - tw // 2  # Also shifted right due to icon_x change
                ty = icon_y + nh + 2 - 12 - th
                draw.text((tx, ty), wr_text, fill=(255, 255, 255), font=font_lg)
            except Exception:
                draw.text((icon_x + pw // 2 - 20, icon_y + nh - 30),
                          wr_text, fill=(255, 255, 255), font=font_lg)

    buf = io.BytesIO()
    base.save(buf, format='PNG')
    return buf.getvalue()


async def get_hero_meta_image():
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
    logger.info("Generating static fallback banner")
    try:
        base = Image.new("RGBA", (1200, 200), (25, 25, 35, 255))
        draw = ImageDraw.Draw(base)
        from datetime import datetime, timezone, timedelta
        MSK = timezone(timedelta(hours=3))
        date_text = datetime.now(MSK).strftime("%d.%m.%Y %H:%M")
        try:
            font = ImageFont.truetype(FONT_PATH, 32)
        except:
            font = ImageFont.load_default()
        # Removed "Dota 2 Hero Meta" label as requested
        draw.text((20, 20), "Updated: %s" % date_text, fill=(200, 200, 200), font=font)
        draw.text((20, 70), "API unavailable", fill=(150, 150, 150), font=font)
        buf = io.BytesIO()
        base.save(buf, format='PNG')
        return buf.getvalue()
    except Exception as e:
        logger.error("Static banner error: %s", e)
        return None