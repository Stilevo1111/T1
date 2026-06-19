# hero_meta.py — heroStats API + role-based positions, layout = dc5d7a5 (a32f3e8)

import asyncio
import io
import json
import logging
import math
import os
import re
import time

from pathlib import Path
from urllib.parse import urlparse

import aiohttp
from PIL import Image, ImageDraw, ImageFont

from hero_positions import hero_positions

# Circuit breaker for OpenDota explorer API
_explorer_circuit_breaker = {
    "state": "CLOSED",
    "failure_count": 0,
    "last_failure_time": 0,
    "failure_threshold": 3,
    "recovery_timeout": 300,  # 5 minutes
}

# Rate limit cache
_explorer_cache = {"data": None, "timestamp": 0, "fallback_used": False}

logger = logging.getLogger(__name__)

BACKGROUND_PATH = "background_new.png"

ICON_CACHE_DIR = Path("cache/meta_icons")
ICON_CACHE_DIR.mkdir(parents=True, exist_ok=True)

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




def detect_hero_position(hero_data):

    name = hero_data.get("localized_name")
    if name and name in hero_positions:
        return hero_positions[name]

    # Fallback to old logic if not in manual list
    roles = set(hero_data.get("roles", []))

    # Use OpenDota role logic similar to weekly_analytics
    if "Support" in roles or "Disabler" in roles:
        base_role = "SUPPORT"
    elif "Nuker" in roles and "Escape" in roles:
        base_role = "MID"
    elif "Durable" in roles and "Initiator" in roles:
        base_role = "OFFLANE"
    elif "Carry" in roles:
        base_role = "CARRY"
    else:
        base_role = "SUPPORT"

    # Map to positions
    role_to_pos = {
        "CARRY": 1,
        "MID": 2,
        "OFFLANE": 3,
        "SUPPORT": 4
    }

    pos = role_to_pos.get(base_role, 4)

    # For support, distinguish hard/soft based on position picks
    if base_role == "SUPPORT":
        p4_picks = hero_data.get("4_pick", 0)
        p5_picks = hero_data.get("5_pick", 0)
        if p5_picks > p4_picks:
            pos = 5
        else:
            pos = 4

    return pos


def apply_fancy_style(img, size=(188, 100), radius=15, border_width=3, border_color=(255, 215, 0, 255)):
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
        outline=border_color, width=border_width
    )
    return output


async def fetch_hero_icon(session, icon_path):

    # ==========================================
    # BUILD URL
    # ==========================================

    icon_url = None

    # Handle numeric IDs (convert to hero name lookup)
    if icon_path and icon_path.isdigit():
        from dota_mmr import get_hero_list
        heroes = await get_hero_list()
        hero_name = None
        for h in heroes:
            if h.get("id") == int(icon_path):
                hero_name = h.get("name", "").replace("npc_dota_hero_", "")
                break
        if hero_name:
            icon_url = f"https://cdn.cloudflare.steamstatic.com/apps/dota2/images/dota_react/heroes/{hero_name}.png"
        else:
            icon_url = f"https://cdn.cloudflare.steamstatic.com/apps/dota2/images/dota_react/heroes/{icon_path}.png"
    else:
        # Clean the path - remove trailing ? or query params that might cause issues
        icon_path = icon_path.split("?")[0].rstrip("/")

        # Convert old format /apps/dota2/images/dota/heroes/{name}_sb.png to new format
        # New format: /apps/dota2/images/dota_react/heroes/{name}.png
        if "/apps/dota2/images/dota/heroes/" in icon_path:
            match = re.search(r'/heroes/([a-zA-Z0-9_]+)_sb\.png', icon_path)
            if match:
                hero_name = match.group(1)
                icon_url = f"https://cdn.cloudflare.steamstatic.com/apps/dota2/images/dota_react/heroes/{hero_name}.png"
            else:
                icon_url = f"https://cdn.cloudflare.steamstatic.com{icon_path}"
        elif icon_path.startswith('/'):
            icon_url = f"https://cdn.cloudflare.steamstatic.com{icon_path}"

        elif not icon_path.startswith('http'):
            icon_url = f"https://cdn.cloudflare.steamstatic.com/{icon_path}"

        else:
            icon_url = icon_path

    # ==========================================
    # CACHE FILE NAME
    # ==========================================

    filename = os.path.basename(
        urlparse(icon_url).path
    )

    cache_path = ICON_CACHE_DIR / filename

    # ==========================================
    # LOAD FROM CACHE
    # ==========================================

    if cache_path.exists():

        try:
            return Image.open(cache_path).convert("RGBA")

        except Exception:
            logger.exception("Failed open cached icon")

    # ==========================================
    # DOWNLOAD
    # ==========================================

    try:

        async with session.get(
            icon_url,
            timeout=aiohttp.ClientTimeout(total=5)
        ) as resp:

            resp.raise_for_status()

            content = await resp.read()

            with open(cache_path, "wb") as f:
                f.write(content)

            return Image.open(
                io.BytesIO(content)
            ).convert("RGBA")

    except Exception as e:

        logger.error("Failed to load icon from CDN: %s", e)

        filename = os.path.basename(urlparse(icon_url).path)
        hero_name = filename.replace("_sb.png", "").replace(".png", "")
        local_path = Path("assets/heroes") / f"{hero_name}.png"
        if local_path.exists():
            try:
                return Image.open(local_path).convert("RGBA")
            except Exception:
                pass

        return None


async def _enrich_with_hero_data(hero_stats):
    from dota_mmr import get_hero_list
    heroes_info = await get_hero_list()
    if not heroes_info:
        return hero_stats
    hero_map = {h.get("id"): h for h in heroes_info}
    for hs in hero_stats:
        hero_id = hs.get("hero_id")
        if hero_id in hero_map:
            info = hero_map[hero_id]
            hs["localized_name"] = info.get("localized_name", hs.get("name", ""))
            hs["roles"] = info.get("roles", [])
    return hero_stats


def _build_grid(hero_stats):
    MIN_MATCHES = 1  # Need at least 1 game
    hero_best_position = {}
    for hero in hero_stats:
        matches = hero.get("pub_pick", hero.get("pro_pick", 0))
        wins = hero.get("pub_win", hero.get("pro_win", 0))
        winrate = (wins / matches) if matches > 0 else 0
        if matches < MIN_MATCHES:
            continue
        score = winrate * math.log10(matches + 1)
        pos = hero.get("position", detect_hero_position(hero))
        hero_id = hero.get("hero_id", hero.get("id"))
        if hero_id not in hero_best_position or winrate > hero_best_position[hero_id]["winrate"]:
            hero_best_position[hero_id] = {
                'id': hero_id,
                'name': hero.get("localized_name", 'Hero %d' % hero_id),
                'img': hero.get("img", ""),
                'position': pos,
                'score': score,
                'winrate': winrate,
                'matches': matches,
                'roles': hero.get("roles", []),
            }
    processed_heroes = list(hero_best_position.values())
    by_position = {1: [], 2: [], 3: [], 4: [], 5: []}
    for hero in processed_heroes:
        by_position[hero['position']].append(hero)
    grid = {}
    for pos in range(1, 6):
        heroes = sorted(by_position[pos], key=lambda h: -h['winrate'])
        grid[pos] = heroes[:5]
    all_heroes_sorted = sorted(processed_heroes, key=lambda h: -h['winrate'])
    pos_role_map = {1: ["Carry"], 2: ["Mid"], 3: ["Offlane"], 4: ["Support", "Soft Support"], 5: ["Hard Support"]}
    for pos in range(1, 6):
        if len(grid[pos]) < 5:
            needed_roles = pos_role_map[pos]
            needed_roles_set = set(needed_roles)
            for h in all_heroes_sorted:
                if h['id'] not in {hero['id'] for pos_list in grid.values() for hero in pos_list}:
                    # Используем пересечение множеств вместо substring check
                    hero_roles = set(h.get('roles', []))
                    if hero_roles & needed_roles_set:
                        grid[pos].append(h)
                        if len(grid[pos]) >= 5:
                            break
            grid[pos] = sorted(grid[pos], key=lambda h: -h['winrate'])
    return grid


async def _get_hero_stats_from_db(days=7):
    """Get hero statistics from local database instead of OD explorer API."""
    from database import get_connection, urlparse, DATABASE_URL
    from dota_mmr import get_hero_list

    now = int(time.time())
    week_ago = now - (days * 24 * 60 * 60)
    
    conn = get_connection()
    url = urlparse.urlparse(DATABASE_URL)
    scheme = url.scheme
    
    cursor = conn.cursor()
    
    # Ensure table exists
    try:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS public_player_matches (
                match_id BIGINT UNIQUE,
                hero_id INTEGER,
                player_slot INTEGER,
                radiant_win INTEGER,
                start_time INTEGER,
                steam_id INTEGER
            )
        """)
    except Exception:
        pass
    
    # Query hero stats grouped by hero_id and position
    if "postgres" in scheme:
        cursor.execute("""
            SELECT 
                hero_id,
                player_slot,
                COUNT(*) as pub_pick,
                SUM(CASE 
                    WHEN (radiant_win = TRUE AND player_slot < 128) OR
                         (radiant_win = FALSE AND player_slot >= 128)
                    THEN 1 ELSE 0 
                END) as pub_win
            FROM public_player_matches
            WHERE start_time >= %s
            GROUP BY hero_id, player_slot
        """, (week_ago,))
    else:
        cursor.execute("""
            SELECT 
                hero_id,
                player_slot,
                COUNT(*) as pub_pick,
                SUM(CASE 
                    WHEN (radiant_win = 1 AND player_slot < 128) OR
                         (radiant_win = 0 AND player_slot >= 128)
                    THEN 1 ELSE 0 
                END) as pub_win
            FROM public_player_matches
            WHERE start_time >= ?
            GROUP BY hero_id, player_slot
        """, (week_ago,))
    
    rows = cursor.fetchall()
    
    hero_position_stats = {}
    for row in rows:
        hero_id = row[0]
        player_slot = row[1] if row[1] is not None else 0
        
        if player_slot < 0:
            continue
            
        # Calculate position (0-4 -> 1-5)
        position = player_slot % 5 if player_slot < 128 else (player_slot - 128) % 5
        pos_map = {0: 1, 1: 2, 2: 3, 3: 4, 4: 5}
        actual_pos = pos_map.get(position, 1)
        
        key = (hero_id, actual_pos)
        if key not in hero_position_stats:
            hero_position_stats[key] = {
                "hero_id": hero_id, 
                "position": actual_pos, 
                "pub_pick": 0, 
                "pub_win": 0
            }
        hero_position_stats[key]["pub_pick"] += row[2] or 0
        hero_position_stats[key]["pub_win"] += row[3] or 0
    
    hero_stats = list(hero_position_stats.values())
    
# Enrich with hero data (names, icons)
    heroes_info = await get_hero_list()
    if heroes_info:
        hero_map = {h.get("id"): h for h in heroes_info}
        for hs in hero_stats:
            hero_id = hs.get("hero_id")
            if hero_id in hero_map:
                info = hero_map[hero_id]
                hs["localized_name"] = info.get("localized_name", f"Hero {hero_id}")
                img_value = info.get("img", "")
                if img_value and "/apps/dota2/images/dota/heroes/" in img_value:
                    import re
                    match = re.search(r'/heroes/([a-zA-Z0-9_]+)_sb\.png', img_value)
                    if match:
                        hero_name = match.group(1)
                        hs["img"] = f"https://cdn.cloudflare.steamstatic.com/apps/dota2/images/dota_react/heroes/{hero_name}.png"
                    else:
                        hs["img"] = img_value
                elif img_value and img_value.isdigit():
                    hero_name = info.get("name", "").replace("npc_dota_hero_", "")
                    hs["img"] = f"https://cdn.cloudflare.steamstatic.com/apps/dota2/images/dota_react/heroes/{hero_name}.png"
                else:
                    hero_name = info.get("name", "").replace("npc_dota_hero_", "")
                    hs["img"] = img_value or f"https://cdn.cloudflare.steamstatic.com/apps/dota2/images/dota_react/heroes/{hero_name}.png"
                hs["roles"] = info.get("roles", [])
            # Calculate winrate always
            if hs["pub_pick"] > 0:
                hs["winrate"] = hs["pub_win"] / hs["pub_pick"]
            else:
                hs["winrate"] = 0

    return hero_stats


async def create_infographic(hero_stats):
    logger.info("Starting create_infographic")
    if not os.path.exists(BACKGROUND_PATH):
        base = Image.new("RGBA", (1200, 800), (25, 25, 35, 255))
        bg_width, bg_height = 1200, 800
    else:
        base = Image.open(BACKGROUND_PATH).convert("RGBA")
        bg_width, bg_height = base.size
    draw = ImageDraw.Draw(base)
    from datetime import datetime, timedelta, timezone
    MSK = timezone(timedelta(hours=3))
    date_text = datetime.now(MSK).strftime("%d.%m.%Y %H:%M")
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
    icon_height = min(int((row_height - 25) * 1.163), row_height - 5)
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
    from database import get_aiohttp_session
    session = await get_aiohttp_session()
    tasks = [fetch_hero_icon(session, h['img']) for h in all_heroes]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    icons = {}
    for hero, result in zip(all_heroes, results):
        if isinstance(result, Exception):
            icons[hero['id']] = None
        else:
            icons[hero['id']] = result
    return await asyncio.to_thread(_compose_infographic, base, draw, grid, icons, font_lg, margin_x, margin_y, gap_between_cols, col_width, row_height, icon_height)


"""
Hero meta cache for reducing image generation load
"""
_hero_meta_cache = {"data": None, "timestamp": 0}
_HERO_META_CACHE_TTL = 12 * 3600  # 12 hours
HERO_META_CONFIG_KEY = 'hero_meta_data'
HERO_META_CONFIG_TTL = 7 * 24 * 3600  # 7 days
HERO_META_BANNER_KEY = 'hero_meta_banner'  # Cached PNG bytes


async def get_dota_data(days=7, force_refresh=False):
    now = int(time.time())

    # Check cache first
    if not force_refresh and _hero_meta_cache["data"] and now - _hero_meta_cache["timestamp"] < _HERO_META_CACHE_TTL:
        logger.info("Using cached hero meta data")
        return _hero_meta_cache["data"]

    # Try DB config cache
    try:
        from database import get_config
        cached_str = get_config(HERO_META_CONFIG_KEY)
        if cached_str:
            cache_dict = json.loads(cached_str)
            cached_data = cache_dict.get("data")
            cached_ts = cache_dict.get("timestamp", 0)
            if cached_data and (now - cached_ts) < HERO_META_CONFIG_TTL:
                logger.info("Using cached hero meta from DB config")
                _hero_meta_cache["data"] = cached_data
                _hero_meta_cache["timestamp"] = cached_ts
                return cached_data
    except Exception as e:
        logger.warning(f"Failed to read hero meta from DB config: {e}")

    # Get data from local database instead of OD explorer
    try:
        hero_stats = await _get_hero_stats_from_db(days)
        if hero_stats:
            _hero_meta_cache["data"] = hero_stats
            _hero_meta_cache["timestamp"] = now
            try:
                from database import set_config
                cache_dict = {"data": hero_stats, "timestamp": now}
                set_config(HERO_META_CONFIG_KEY, json.dumps(cache_dict))
            except Exception as e:
                logger.warning(f"Failed to cache hero meta to DB: {e}")
            return hero_stats
    except Exception as e:
        logger.error(f"Failed to get hero stats from DB: {e}")

    logger.warning("No hero meta data available - using fallback banner")
    return None
def _compose_infographic(base, draw, grid, icons, font_lg, margin_x, margin_y, gap_between_cols,
                         col_width, row_height, icon_height):
    """Heavy PIL composition — runs in a thread pool to avoid blocking the event loop."""
    for col_idx in range(5):
        pos = col_idx + 1
        heroes = grid[pos]

        for row_idx, hero in enumerate(heroes[:5]):
            x = margin_x + col_idx * (col_width + gap_between_cols)
            y = margin_y + row_idx * row_height

            icon_raw = icons.get(hero['id'])

            if icon_raw is None:
                draw.rounded_rectangle(
                    [x + 20, y + 5, x + col_width - 5, y + icon_height],
                    radius=10, fill=(80, 80, 80)
                )
                try:
                    ph_font = ImageFont.truetype(FONT_PATH, 16)
                except:
                    ph_font = ImageFont.load_default()
                draw.text((x + 25, y + icon_height // 2 - 8), "N/A", fill=(120, 120, 120), font=ph_font)
                continue

            scale = icon_height / icon_raw.height
            nw = int(icon_raw.width * scale)
            nh = icon_height
            if nw > col_width:
                scale = col_width / icon_raw.width
                nw = col_width
                nh = int(icon_raw.height * scale)

            icon_scaled = icon_raw.resize((nw, nh), Image.Resampling.LANCZOS)
            winrate = hero.get('winrate', 0)
            if winrate >= 0.55:
                border_color = (0, 255, 100, 255)
            elif winrate >= 0.50:
                border_color = (255, 210, 0, 255)
            else:
                border_color = (255, 80, 80, 255)

            icon_proc = apply_fancy_style(icon_scaled, size=(nw, nh),
                                          radius=max(8, nh // 12), border_width=4,
                                          border_color=border_color)

            pw = nw + 4
            icon_x = x + (col_width - pw) // 2 + 15
            icon_y = y + 5

            base.paste(icon_proc, (icon_x, icon_y), icon_proc)

            wr_text = "%d%%" % round(hero['winrate'] * 100)

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


async def get_hero_meta_image():
    """Generate hero meta infographic. Falls back to cached banner if no data."""
    try:
        # Get fresh data first
        data = await get_dota_data()
        if not data:
            logger.error("No data from OpenDota")
            # Try cached banner as fallback
            try:
                from database import get_config
                cached_banner = get_config(HERO_META_BANNER_KEY)
                if cached_banner:
                    import base64
                    logger.info("Using cached hero meta banner from DB (no fresh data)")
                    return base64.b64decode(cached_banner)
            except Exception as e:
                logger.debug(f"Failed to read cached banner: {e}")
            return get_static_fallback_banner()
        
        # Data available, generate new banner
        banner = await create_infographic(data)
        if banner:
            # Save banner to DB for next time
            try:
                from database import set_config
                import base64
                set_config(HERO_META_BANNER_KEY, base64.b64encode(banner).decode())
            except Exception as e:
                logger.warning(f"Failed to cache hero meta banner: {e}")
            return banner
        logger.warning("create_infographic returned None, using fallback")
        return get_static_fallback_banner()
    except Exception as e:
        logger.warning("Hero meta generation failed: %s", e)
        return get_static_fallback_banner()


def get_static_fallback_banner():
    logger.info("Generating static fallback banner")
    try:
        base = Image.new("RGBA", (1200, 200), (25, 25, 35, 255))
        draw = ImageDraw.Draw(base)
        from datetime import datetime, timedelta, timezone
        MSK = timezone(timedelta(hours=3))
        date_text = datetime.now(MSK).strftime("%d.%m.%Y %H:%M")
        try:
            font = ImageFont.truetype(FONT_PATH, 32)
        except:
            font = ImageFont.load_default()
        # Removed "Dota 2 Hero Meta" label as requested
        draw.text((20, 20), "Updated: %s" % date_text, fill=(200, 200, 200), font=font)
        draw.text((20, 70), "OpenDota API недоступен", fill=(150, 150, 150), font=font)
        draw.text((20, 110), "Подождите, пока API восстановится", fill=(120, 120, 120), font=font)
        buf = io.BytesIO()
        base.save(buf, format='PNG')
        return buf.getvalue()
    except Exception as e:
        logger.error("Static banner error: %s", e)
        return None
