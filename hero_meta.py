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


# Primary role mapping for Dota 2 heroes
ROLE_MAP = {
    # Position 1 - Carry
    "Anti-Mage": 1,
    "Bloodseeker": 1,
    "Bounty Hunter": 1,
    "Broodmother": 1,
    "Clinkz": 1,
    "Drow Ranger": 1,
    "Faceless Void": 1,
    "Gyrocopter": 1,
    "Juggernaut": 1,
    "Lone Druid": 1,
    "Luna": 1,
    "Medusa": 1,
    "Meepo": 1,
    "Mirana": 1,
    "Monkey King": 1,
    "Morphling": 1,
    "Naga Siren": 1,
    "Phantom Assassin": 1,
    "Phantom Lancer": 1,
    "Razor": 1,
    "Riki": 1,
    "Slark": 1,
    "Sniper": 1,
    "Spectre": 1,
    "Templar Assassin": 1,
    "Terrorblade": 1,
    "Troll Warlord": 1,
    "Ursa": 1,
    "Vengeful Spirit": 1,
    "Venomancer": 1,
    "Viper": 1,
    "Weaver": 1,

    # Position 2 - Mid
    "Alchemist": 2,
    "Arc Warden": 2,
    "Batrider": 2,
    "Death Prophet": 2,
    "Dragon Knight": 2,
    "Ember Spirit": 2,
    "Huskar": 2,
    "Invoker": 2,
    "Kunkka": 2,
    "Leshrac": 2,
    "Lina": 2,
    "Lycan": 2,
    "Magnus": 2,
    "Necrophos": 2,
    "Outworld Destroyer": 2,
    "Puck": 2,
    "Queen of Pain": 2,
    "Shadow Fiend": 2,
    "Storm Spirit": 2,
    "Tinker": 2,
    "Void Spirit": 2,
    "Zeus": 2,

    # Position 3 - Offlane
    "Axe": 3,
    "Beastmaster": 3,
    "Brewmaster": 3,
    "Centaur Warrunner": 3,
    "Chaos Knight": 3,
    "Clockwerk": 3,
    "Dark Seer": 3,
    "Dawnbreaker": 3,
    "Doom": 3,
    "Earth Spirit": 3,
    "Earthshaker": 3,
    "Elder Titan": 3,
    "Enigma": 3,
    "Legion Commander": 3,
    "Mars": 3,
    "Night Stalker": 3,
    "Omniknight": 3,
    "Primal Beast": 3,
    "Pudge": 3,
    "Sand King": 3,
    "Slardar": 3,
    "Spirit Breaker": 3,
    "Sven": 3,
    "Tidehunter": 3,
    "Timbersaw": 3,
    "Treant Protector": 3,
    "Tusk": 3,
    "Underlord": 3,
    "Wraith King": 3,

    # Position 4 - Soft Support
    "Abaddon": 4,
    "Ancient Apparition": 4,
    "Bane": 4,
    "Bristleback": 4,
    "Chen": 4,
    "Crystal Maiden": 4,
    "Dark Willow": 4,
    "Dazzle": 4,
    "Disruptor": 4,
    "Enchantress": 4,
    "Grimstroke": 4,
    "Hoodwink": 4,
    "Io": 4,
    "Jakiro": 4,
    "Keeper of the Light": 4,
    "Lich": 4,
    "Lina": 4,
    "Lion": 4,
    "Nature's Prophet": 4,
    "Necrophos": 4,
    "Ogre Magi": 4,
    "Oracle": 4,
    "Phoenix": 4,
    "Pugna": 4,
    "Rubick": 4,
    "Shadow Demon": 4,
    "Silencer": 4,
    "Skywrath Mage": 4,
    "Snapfire": 4,
    "Techies": 4,
    "Tinker": 4,
    "Tiny": 4,
    "Venomancer": 4,
    "Viper": 4,
    "Warlock": 4,
    "Windranger": 4,
    "Winter Wyvern": 4,
    "Witch Doctor": 4,
    "Zeus": 4,

    # Position 5 - Hard Support (Tanky supports)
    "Abaddon": 5,
    "Earthshaker": 5,
    "Omniknight": 5,
    "Phoenix": 5,
    "Treant Protector": 5,
    "Undying": 5,
    "Witch Doctor": 5,
    "Oracle": 5,
    "Silencer": 5,
    "Venomancer": 5,
}

def detect_hero_position(hero_data):
    """Get hero position from ROLE_MAP, fallback to max pick detection."""
    hero_name = hero_data.get("localized_name", "")
    if hero_name in ROLE_MAP:
        return ROLE_MAP[hero_name]

    # Fallback: use max pick position
    max_picks = 0
    best_position = 2
    for pos in range(1, 6):
        picks = hero_data.get(f"{pos}_pick", 0)
        if picks > max_picks:
            max_picks = picks
            best_position = pos
    return best_position


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
    Сетка 5 колонок с лучшими героями по позициям за неделю.
    1) Для каждого героя определяем bestPosition по максимальным пикам.
    2) Рассчитываем score = winrate * log10(matches).
    3) Фильтруем героев с < 5000 матчей.
    4) Выбираем топ-5 по score для каждой позиции.
    """
    # Process heroes
    processed_heroes = []

    for hero in hero_stats:
        # Use pub data
        matches = hero.get("pub_pick", hero.get("pro_pick", 0))

        # Calculate winrate
        wins = hero.get("pub_win", hero.get("pro_win", 0))
        winrate = (wins / matches) if matches > 0 else 0

        # Use winrate as score (higher winrate = better)
        score = winrate

        # Use position from role detection (not max picks)
        pos = detect_hero_position(hero)

        processed_heroes.append({
            'id': hero["id"],
            'name': hero.get("localized_name", 'Hero %d' % hero["id"]),
            'img': hero.get("img", ""),
            'position': pos,
            'score': score,
            'winrate': winrate,
            'matches': matches,
        })

    # Group by position and sort by score
    by_position = {1: [], 2: [], 3: [], 4: [], 5: []}
    for hero in processed_heroes:
        by_position[hero['position']].append(hero)

    # Take top 5 by score for each position
    grid = {}
    for pos in range(1, 6):
        heroes = sorted(by_position[pos], key=lambda h: -h['score'])
        grid[pos] = heroes[:5]

    return grid
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

            wr_text = "%d%%" % round(hero['winrate'] * 100)

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