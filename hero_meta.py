import asyncio
import aiohttp
import io
import os
import logging

from datetime import datetime
from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

# =========================================================
# CONFIG
# =========================================================

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

# =========================================================
# ROLE DETECTION
# =========================================================

def detect_hero_position(hero_roles):
    """
    Automatic hero position detection based on roles
    """

    hero_roles = set(hero_roles)

    # POS 5
    if "Support" in hero_roles and "Disabler" not in hero_roles:
        return "POS 5"

    # POS 4
    if "Support" in hero_roles and "Disabler" in hero_roles:
        return "POS 4"

    # POS 3
    if "Durable" in hero_roles or "Initiator" in hero_roles:
        return "POS 3"

    # POS 2
    if "Nuker" in hero_roles or "Escape" in hero_roles:
        return "POS 2"

    # POS 1
    if "Carry" in hero_roles:
        return "POS 1"

    return None

# =========================================================
# IMAGE STYLE
# =========================================================

def apply_fancy_style(img, radius=14, border_width=3):

    width, height = img.size

    mask = Image.new("L", (width, height), 0)

    mask_draw = ImageDraw.Draw(mask)

    mask_draw.rounded_rectangle(
        (0, 0, width, height),
        radius=radius,
        fill=255
    )

    rounded = Image.new("RGBA", (width, height), (0, 0, 0, 0))

    rounded.paste(img, (0, 0), mask)

    border_canvas = Image.new(
        "RGBA",
        (width + border_width * 2, height + border_width * 2),
        (0, 0, 0, 0)
    )

    border_draw = ImageDraw.Draw(border_canvas)

    border_draw.rounded_rectangle(
        (
            0,
            0,
            width + border_width * 2 - 1,
            height + border_width * 2 - 1
        ),
        radius=radius + 1,
        outline=(255, 215, 0),
        width=border_width
    )

    border_canvas.paste(
        rounded,
        (border_width, border_width),
        rounded
    )

    return border_canvas

# =========================================================
# FETCH HERO ICON
# =========================================================

async def fetch_hero_icon(session, hero_img):

    if not hero_img.startswith("/"):
        hero_img = "/" + hero_img

    url = f"https://cdn.cloudflare.steamstatic.com{hero_img}"

    try:

        async with session.get(
            url,
            timeout=aiohttp.ClientTimeout(total=10)
        ) as response:

            response.raise_for_status()

            content = await response.read()

            image = Image.open(io.BytesIO(content)).convert("RGBA")

            return image

    except Exception as e:

        logger.warning(f"Failed to load hero icon {url}: {e}")

        return None

# =========================================================
# FETCH HERO STATS — heroStats API
# =========================================================

async def get_dota_data():

    url = "https://api.opendota.com/api/heroStats"

    try:

        async with aiohttp.ClientSession() as session:

            async with session.get(
                url,
                timeout=aiohttp.ClientTimeout(total=15)
            ) as response:

                response.raise_for_status()

                data = await response.json()

                logger.info(f"Loaded {len(data)} heroes")

                return data

    except Exception as e:

        logger.error(f"OpenDota error: {e}")

        return None

# =========================================================
# CREATE INFOGRAPHIC
# =========================================================

async def create_infographic(hero_stats):

    logger.info("Creating infographic")

    # =====================================================
    # BACKGROUND
    # =====================================================

    if os.path.exists(BACKGROUND_PATH):

        base = Image.open(BACKGROUND_PATH).convert("RGBA")

        base = base.resize((1500, 900))

    else:

        base = Image.new(
            "RGBA",
            (1500, 900),
            (20, 20, 30)
        )

    draw = ImageDraw.Draw(base)

    # =====================================================
    # FONTS
    # =====================================================

    try:

        wr_font = ImageFont.truetype(FONT_PATH, 24)

    except Exception:

        wr_font = ImageFont.load_default()

    # =====================================================
    # PREPARE HEROES — filter by pro_pick >= 20
    # =====================================================

    all_heroes = []

    for hero in hero_stats:

        pro_pick = hero.get("pro_pick", 0)
        pro_win = hero.get("pro_win", 0)

        if pro_pick < 20:
            continue

        if pro_pick <= 0:
            continue

        wr = (pro_win / pro_pick) * 100

        hero["wr"] = wr

        all_heroes.append(hero)

    # =====================================================
    # AUTO POSITION DETECTION
    # =====================================================

    role_heroes = {
        "POS 1": [],
        "POS 2": [],
        "POS 3": [],
        "POS 4": [],
        "POS 5": [],
    }

    for hero in all_heroes:

        roles = hero.get("roles", [])

        position = detect_hero_position(roles)

        if not position:
            continue

        role_heroes[position].append(hero)

    # =====================================================
    # SORT HEROES
    # =====================================================

    for role in role_heroes:

        role_heroes[role] = sorted(
            role_heroes[role],
            key=lambda x: x["wr"],
            reverse=True
        )[:5]

    # =====================================================
    # DOWNLOAD ICONS (async, parallel)
    # =====================================================

    icon_cache = {}

    async with aiohttp.ClientSession() as session:

        tasks = []
        task_keys = []

        for role in role_heroes:

            for hero in role_heroes[role]:

                hero_img = hero.get("img")

                if not hero_img:
                    continue

                task_keys.append(hero_img)

                tasks.append(
                    fetch_hero_icon(session, hero_img)
                )

        results = await asyncio.gather(
            *tasks,
            return_exceptions=True
        )

        for key, result in zip(task_keys, results):

            if isinstance(result, Exception):
                icon_cache[key] = None
            else:
                icon_cache[key] = result

    # =====================================================
    # DRAW GRID — old layout, no labels
    # =====================================================

    # Position keys in display order
    roles = ["POS 1", "POS 2", "POS 3", "POS 4", "POS 5"]

    start_x = 40
    start_y = 130

    col_width = 280
    row_height = 140

    icon_width = 200
    icon_height = 110

    for col_index, role in enumerate(roles):

        col_x = start_x + (col_index * col_width)

        # NO role title drawn — removed as requested

        heroes = role_heroes[role]

        for row_index, hero in enumerate(heroes):

            row_y = start_y + (row_index * row_height)

            hero_icon = icon_cache.get(hero.get("img"))

            if hero_icon is None:
                continue

            hero_icon = hero_icon.resize(
                (icon_width, icon_height),
                Image.Resampling.LANCZOS
            )

            hero_icon = apply_fancy_style(hero_icon)

            base.paste(
                hero_icon,
                (col_x + 10, row_y),
                hero_icon
            )

            # WR text
            wr_text = f"{hero['wr']:.1f}%"

            bbox = draw.textbbox(
                (0, 0),
                wr_text,
                font=wr_font
            )

            text_width = bbox[2] - bbox[0]

            draw.text(
                (
                    col_x + 110 - text_width // 2,
                    row_y + 115
                ),
                wr_text,
                fill=(255, 255, 255),
                font=wr_font
            )

    # =====================================================
    # EXPORT IMAGE
    # =====================================================

    buffer = io.BytesIO()

    base.save(buffer, format="PNG")

    return buffer.getvalue()

# =========================================================
# MAIN ENTRY POINT
# =========================================================

async def get_hero_meta_image():
    """Generate hero meta image — public API called by main.py"""

    try:

        hero_stats = await get_dota_data()

        if not hero_stats:

            logger.error("No hero stats")

            return _static_fallback()

        image = await create_infographic(hero_stats)

        return image

    except Exception as e:

        logger.error(f"Meta image generation failed: {e}")

        return _static_fallback()


def _static_fallback():
    """Static fallback banner when API is unavailable"""

    logger.info("Generating static fallback banner")

    try:

        base = Image.new("RGBA", (1500, 900), (20, 20, 30))

        draw = ImageDraw.Draw(base)

        try:
            font = ImageFont.truetype(FONT_PATH, 36)
        except Exception:
            font = ImageFont.load_default()

        draw.text(
            (50, 30),
            "DOTA 2 HERO META",
            fill=(255, 215, 0),
            font=font
        )

        draw.text(
            (50, 100),
            "API temporarily unavailable",
            fill=(150, 150, 150),
            font=font
        )

        buf = io.BytesIO()

        base.save(buf, format="PNG")

        return buf.getvalue()

    except Exception as e:

        logger.error(f"Static banner error: {e}")

        return None