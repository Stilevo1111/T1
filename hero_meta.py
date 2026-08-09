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
from constants import get_banner_path
from cache_service import explorer_circuit_breaker

logger = logging.getLogger(__name__)

# Rate limit cache
_explorer_cache = {"data": None, "timestamp": 0, "fallback_used": False}

BACKGROUND_PATH = get_banner_path("heroes_strip")

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
    if not icon_path:
        return None

    close_session = False
    if session is None:
        session = aiohttp.ClientSession()
        close_session = True

    try:
        # ==========================================
        # BUILD URL
        # ==========================================

        icon_url = None

        # Handle numeric IDs (convert to hero name lookup)
        if icon_path and icon_path.isdigit():
            from dota_mmr import get_hero_list
            from hero_names import get_cdn_hero_name
            heroes = await get_hero_list()
            hero_name = None
            for h in heroes:
                if h.get("id") == int(icon_path):
                    internal_name = h.get("name", "").replace("npc_dota_hero_", "")
                    hero_name = get_cdn_hero_name(internal_name)
                    break
            if hero_name:
                icon_url = f"https://cdn.cloudflare.steamstatic.com/apps/dota2/images/dota_react/heroes/{hero_name}.png"
            else:
                return None
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

        if cache_path.exists() and not cache_path.is_dir():

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
                timeout=aiohttp.ClientTimeout(total=8),
                headers={"User-Agent": "Mozilla/5.0 (compatible; FissureBot/1.0)"}
            ) as resp:

                resp.raise_for_status()

                content_type = resp.headers.get("Content-Type", "")
                if not content_type.startswith("image/"):
                    logger.warning("Unexpected Content-Type for hero icon %s: %s", icon_url, content_type)
                    return None

                content = await resp.read()

                if filename and not cache_path.is_dir():
                    try:
                        with open(cache_path, "wb") as f:
                            f.write(content)
                    except Exception:
                        logger.exception("Failed to write cached icon")

                try:
                    return Image.open(
                        io.BytesIO(content)
                    ).convert("RGBA")
                except Exception as e:
                    logger.error("Failed to decode hero icon %s: %s", icon_url, e)
                    return None

        except Exception as e:

            logger.error("Failed to load icon from CDN: %s", e)

            # Fallback to local assets
            filename = os.path.basename(urlparse(icon_url).path)
            hero_name = filename.replace("_sb.png", "").replace(".png", "").replace(".webp", "")

            # Try local asset first with CDN name
            local_path = Path("assets/heroes_webp") / f"{hero_name}.webp"
            if not local_path.exists():
                # Try with reverse CDN mapping (e.g., "doom" -> "doom_bringer")
                from hero_names import get_local_hero_name
                local_name = get_local_hero_name(hero_name)
                if local_name != hero_name:
                    local_path = Path("assets/heroes_webp") / f"{local_name}.webp"

            if local_path.exists():
                try:
                    return Image.open(local_path).convert("RGBA")
                except Exception:
                    pass

            # Try alternative local paths
            alt_paths = [
                Path("assets/heroes_webp") / f"{hero_name}.png",
                Path("assets/heroes/") / f"{hero_name}.png",
                Path("assets/") / f"{hero_name}.png",
            ]
            for alt_path in alt_paths:
                if alt_path.exists():
                    try:
                        return Image.open(alt_path).convert("RGBA")
                    except Exception:
                        continue

            return None

    finally:
        if close_session:
            await session.close()


async def _enrich_hero_icons(hero_stats):
    from dota_mmr import get_heroes_data
    heroes_data = get_heroes_data()
    if not heroes_data:
        return None
    for hs in hero_stats:
        hero_id = hs.get("hero_id", hs.get("id"))
        hero_info = heroes_data.get(hero_id)
        if hero_info:
            hs["img"] = hero_info.get("img", "")
    return hero_stats


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


def get_best_players_per_hero(limit_per_hero=1, days=7):
    """Get best players per hero from public_player_matches joined with users."""
    conn = None
    try:
        from database import get_connection, release_connection, get_db_type
        conn = get_connection()
        cursor = conn.cursor()
        scheme = get_db_type()
        week_ago = int(time.time()) - (days * 24 * 3600)

        if "postgres" in scheme:
            query = """
                SELECT 
                    ppm.hero_id,
                    ppm.steam_id,
                    COUNT(*) as games,
                    SUM(CASE WHEN (ppm.player_slot < 128 AND ppm.radiant_win = 1) OR (ppm.player_slot >= 128 AND ppm.radiant_win = 0) THEN 1 ELSE 0 END) as wins,
                    u.mmr,
                    u.steam_nickname,
                    u.avatar,
                    u.telegram_id
                FROM public_player_matches ppm
                LEFT JOIN users u ON ppm.steam_id = u.steam_id
                WHERE ppm.start_time > %s
                GROUP BY ppm.hero_id, ppm.steam_id, u.mmr, u.steam_nickname, u.avatar, u.telegram_id
                ORDER BY ppm.hero_id, wins DESC, games DESC
            """
            cursor.execute(query, (week_ago,))
        else:
            query = """
                SELECT 
                    ppm.hero_id,
                    ppm.steam_id,
                    COUNT(*) as games,
                    SUM(CASE WHEN (ppm.player_slot < 128 AND ppm.radiant_win = 1) OR (ppm.player_slot >= 128 AND ppm.radiant_win = 0) THEN 1 ELSE 0 END) as wins,
                    u.mmr,
                    u.steam_nickname,
                    u.avatar,
                    u.telegram_id
                FROM public_player_matches ppm
                LEFT JOIN users u ON ppm.steam_id = u.steam_id
                WHERE ppm.start_time > ?
                GROUP BY ppm.hero_id, ppm.steam_id, u.mmr, u.steam_nickname, u.avatar, u.telegram_id
                ORDER BY ppm.hero_id, wins DESC, games DESC
            """
            cursor.execute(query, (week_ago,))

        rows = cursor.fetchall()
        cursor.close()

        best_players = {}
        for row in rows:
            hero_id = row[0]
            if hero_id not in best_players:
                best_players[hero_id] = []
            if len(best_players[hero_id]) < limit_per_hero:
                best_players[hero_id].append({
                    'hero_id': hero_id,
                    'steam_id': row[1],
                    'games': row[2],
                    'wins': row[3],
                    'mmr': row[4] or 0,
                    'nickname': row[5] or f"Player {row[1]}",
                    'avatar': row[6],
                    'telegram_id': row[7],
                    'winrate': (row[3] / row[2] * 100) if row[2] > 0 else 0
                })

        return best_players
    except Exception as e:
        logger.error(f"get_best_players_per_hero error: {e}")
        return {}
    finally:
        if conn:
            release_connection(conn)


def _draw_avatar_circle(icon_image, avatar_img, size=40, border=3):
    """Draw circular avatar with white border onto hero icon at top-right corner."""
    if avatar_img is None:
        return icon_image

    total = size + border * 2
    icon_w, icon_h = icon_image.size
    x = icon_w - total - 8
    y = 8

    scale = 4
    big = size * scale
    circular = avatar_img.resize((big, big), Image.Resampling.LANCZOS)

    mask = Image.new("L", (big, big), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, big - 1, big - 1], fill=255)
    mask = mask.resize((size, size), Image.Resampling.LANCZOS)
    circular = circular.resize((size, size), Image.Resampling.LANCZOS)
    circular.putalpha(mask)

    border_layer = Image.new("RGBA", (total, total), (0, 0, 0, 0))
    big_total = total * scale
    border_mask = Image.new("L", (big_total, big_total), 0)
    ImageDraw.Draw(border_mask).ellipse([0, 0, big_total - 1, big_total - 1], fill=255)
    border_mask = border_mask.resize((total, total), Image.Resampling.LANCZOS)
    white = Image.new("RGBA", (total, total), (255, 255, 255, 255))
    white.putalpha(border_mask)
    border_layer.paste(white, (0, 0), white)
    border_layer.paste(circular, (border, border), circular)

    result = icon_image.copy()
    result.paste(border_layer, (x, y), border_layer)
    return result


async def _fetch_telegram_avatar(bot_token, avatar_field):
    """Fallback: download Telegram avatar by file_id or direct URL."""
    if not avatar_field:
        return None
    try:
        async with aiohttp.ClientSession() as session:
            if avatar_field.startswith('http'):
                async with session.get(avatar_field, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status != 200:
                        return None
                    data = await resp.read()
                    return Image.open(io.BytesIO(data)).convert("RGBA")
            else:
                async with session.get(
                    f"https://api.telegram.org/bot{bot_token}/getFile",
                    params={"file_id": avatar_field},
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    if resp.status != 200:
                        return None
                    result = await resp.json()
                    if not result.get("ok"):
                        return None
                    file_path = result["result"]["file_path"]
                    async with session.get(
                        f"https://api.telegram.org/file/bot{bot_token}/{file_path}",
                        timeout=aiohttp.ClientTimeout(total=10)
                    ) as resp:
                        if resp.status != 200:
                            return None
                        data = await resp.read()
                        return Image.open(io.BytesIO(data)).convert("RGBA")
    except Exception as e:
        logger.debug(f"_fetch_telegram_avatar failed: {e}")
        return None


async def _fetch_telegram_profile_photo(bot_token, user_id):
    """Fallback: download Telegram profile photo by user_id."""
    if not user_id:
        return None
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"https://api.telegram.org/bot{bot_token}/getUserProfilePhotos",
                params={"user_id": int(user_id), "limit": 1},
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status != 200:
                    return None
                result = await resp.json()
                if not result.get("ok") or not result.get("result", {}).get("photos"):
                    return None
                photo = result["result"]["photos"][0][-1]
                file_id = photo["file_id"]
                async with session.get(
                    f"https://api.telegram.org/bot{bot_token}/getFile",
                    params={"file_id": file_id},
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as resp2:
                    if resp2.status != 200:
                        return None
                    file_result = await resp2.json()
                    if not file_result.get("ok"):
                        return None
                    file_path = file_result["result"]["file_path"]
                    async with session.get(
                        f"https://api.telegram.org/file/bot{bot_token}/{file_path}",
                        timeout=aiohttp.ClientTimeout(total=10)
                    ) as resp3:
                        if resp3.status != 200:
                            return None
                        data = await resp3.read()
                        return Image.open(io.BytesIO(data)).convert("RGBA")
    except Exception as e:
        logger.debug(f"_fetch_telegram_profile_photo failed for user {user_id}: {e}")
        return None


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
        hero_id = hero.get("hero_id", hero.get("id"))
        # Priority: hero_positions > position from data > detect from roles
        hero_name = hero.get("localized_name", hero.get("name", ""))
        if hero_name and hero_name in hero_positions:
            pos = hero_positions[hero_name]  # Use manual position first
        elif hero.get("position"):
            pos = hero.get("position")  # Use position from data
        else:
            pos = detect_hero_position(hero)  # Fallback to role detection
        if hero_id not in hero_best_position or winrate > hero_best_position[hero_id]["winrate"]:
            hero_best_position[hero_id] = {
                'id': hero_id,
                'name': hero_name,
                'img': hero.get("img", ""),
                'position': pos,
                'score': score,
                'winrate': winrate,
                'pub_pick': matches,
                'pub_win': wins,
                'pub_losses': matches - wins,
                'matches': matches,
                'roles': hero.get("roles", []),
            }
    processed_heroes = list(hero_best_position.values())
    by_position = {1: [], 2: [], 3: [], 4: [], 5: []}
    for hero in processed_heroes:
        by_position[hero['position']].append(hero)
    grid = {}
    for pos in range(1, 6):
        heroes = sorted(by_position[pos], key=lambda h: -h['score'])
        grid[pos] = heroes[:5]
    all_heroes_sorted = sorted(processed_heroes, key=lambda h: -h['score'])
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
            grid[pos] = sorted(grid[pos], key=lambda h: -h['score'])
    return grid


def _get_hero_stats_from_db(days=7):
    """Get hero statistics from local database instead of OD explorer API."""
    from database import get_connection, urlparse, DATABASE_URL
    from dota_mmr import get_hero_list

    now = int(time.time())
    week_ago = now - (days * 24 * 60 * 60)
    logger.info(f"_get_hero_stats_from_db: querying matches since {week_ago} (now={now})")

    conn = get_connection()
    url = urlparse.urlparse(DATABASE_URL)
    scheme = url.scheme

    cursor = conn.cursor()

    try:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS public_player_matches (
                match_id BIGINT UNIQUE,
                hero_id INTEGER,
                player_slot INTEGER,
                radiant_win INTEGER,
                start_time INTEGER,
                steam_id BIGINT
            )
            """)
        try:
            cursor.execute("""
                DO $$
                BEGIN
                    IF EXISTS (SELECT 1 FROM information_schema.columns
                               WHERE table_name = 'public_player_matches'
                               AND column_name = 'radiant_win'
                               AND data_type = 'boolean') THEN
                        ALTER TABLE public_player_matches ALTER COLUMN radiant_win TYPE INTEGER USING (CASE WHEN radiant_win THEN 1 ELSE 0 END);
                    END IF;
                END $$
                """)
        except Exception as e:
            logger.warning(f"hero_meta migration warning: {e}")
    except Exception:
        pass

    if "postgres" in scheme:
        cursor.execute("""
            SELECT
                hero_id,
                COUNT(*) as pub_pick,
                SUM(CASE
                    WHEN (radiant_win = 1 AND player_slot < 128) OR (radiant_win = 0 AND player_slot >= 128) THEN 1
                    ELSE 0
                END) as pub_win
            FROM public_player_matches
            WHERE start_time >= %s AND steam_id IS NOT NULL
            GROUP BY hero_id
        """, (week_ago,))
    else:
        cursor.execute("""
            SELECT
                hero_id,
                COUNT(*) as pub_pick,
                SUM(CASE
                    WHEN (radiant_win = 1 AND player_slot < 128) OR (radiant_win = 0 AND player_slot >= 128) THEN 1
                    ELSE 0
                END) as pub_win
            FROM public_player_matches
            WHERE start_time >= ? AND steam_id IS NOT NULL
            GROUP BY hero_id
        """, (week_ago,))

    rows = cursor.fetchall()
    logger.info(f"_get_hero_stats_from_db: found {len(rows)} hero rows")

    from dota_mmr import get_heroes_data
    heroes_data = get_heroes_data()

    hero_stats = []
    for row in rows:
        hero_id = row[0]
        pub_pick = row[1] or 0
        pub_win = row[2] or 0
        pub_win = int(pub_win) if pub_win else 0
        logger.info(f"_get_hero_stats_from_db: hero_id={hero_id}, pub_pick={pub_pick}, pub_win={pub_win}")

        hero_info = heroes_data.get(hero_id, {}) if heroes_data else {}
        hero_name = hero_info.get("name", f"Hero {hero_id}")

        if hero_name and hero_name in hero_positions:
            position = hero_positions[hero_name]
        else:
            position = detect_hero_position({"roles": hero_info.get("roles", [])})

        winrate = pub_win / pub_pick if pub_pick > 0 else 0
        pub_losses = pub_pick - pub_win

        hero_stats.append({
            "hero_id": hero_id,
            "position": position,
            "pub_pick": pub_pick,
            "pub_win": pub_win,
            "pub_losses": pub_losses,
            "winrate": winrate,
            "localized_name": hero_name,
            "img": hero_info.get("img", ""),
            "roles": hero_info.get("roles", []),
        })

    return hero_stats


async def create_infographic(hero_stats):
    logger.info("Starting create_infographic")
    if not BACKGROUND_PATH.exists():
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
    except Exception as e:
        logger.debug(f"Could not load date font: {e}")
        date_font = ImageFont.load_default()
    try:
        bbox = draw.textbbox((0, 0), date_text, font=date_font)
        tw = bbox[2] - bbox[0]
    except Exception as e:
        logger.debug(f"Could not calculate text bbox: {e}")
        tw = 0
    draw.text((bg_width - tw - 20, 20), date_text, fill=(255, 255, 255), font=date_font)
    margin_x = 50
    margin_y = 215
    gap_between_cols = 15
    col_width = (bg_width - 2 * margin_x - 6 * gap_between_cols) // 5
    row_height = (bg_height - margin_y - 10) // 5
    icon_height = min(int((row_height - 25) * 1.163), row_height - 10)
    try:
        font_lg = ImageFont.truetype(FONT_PATH, 22)
        for bn in ['arialbd.ttf', 'Arial-Bold.ttf', 'DejaVuSans-Bold.ttf']:
            try:
                font_lg = ImageFont.truetype("C:/Windows/Fonts/%s" % bn, 22)
                break
            except Exception as e:
                logger.debug(f"Could not load font {bn}: {e}")
                continue
    except Exception as e:
        logger.debug(f"Could not load large font: {e}")
        font_lg = ImageFont.load_default()
    grid = _build_grid(hero_stats)
    all_heroes = []
    seen_ids = set()
    for pos in range(1, 6):
        for h in grid[pos]:
            if h['id'] not in seen_ids:
                seen_ids.add(h['id'])
                all_heroes.append(h)

    best_players = {}
    try:
        best_players = get_best_players_per_hero(limit_per_hero=1, days=7)
    except Exception as e:
        logger.warning(f"Failed to load best players for hero meta avatars: {e}")

    avatar_cache = {}
    async def fetch_avatar_for_hero(hero_id):
        if hero_id in avatar_cache:
            return avatar_cache[hero_id]
        player = best_players.get(hero_id, [{}])[0]
        avatar_url = player.get('avatar')
        telegram_id = player.get('telegram_id')
        img = None
        
        # 1. Try Steam/direct avatar URL
        if avatar_url:
            img = await fetch_hero_icon(None, avatar_url)
        
        # 2. Fallback to Telegram avatar via file_id or direct URL
        if not img and avatar_url:
            try:
                from config import BOT_TOKEN
                img = await _fetch_telegram_avatar(BOT_TOKEN, avatar_url)
            except Exception as e:
                logger.debug(f"Telegram avatar fallback failed for hero {hero_id}: {e}")
        
        # 3. Fallback to Telegram profile photo by telegram_id
        if not img and telegram_id:
            try:
                from config import BOT_TOKEN
                img = await _fetch_telegram_profile_photo(BOT_TOKEN, telegram_id)
            except Exception as e:
                logger.debug(f"Telegram profile photo fallback failed for hero {hero_id}: {e}")
        
        avatar_cache[hero_id] = img
        return img

    tasks = [fetch_hero_icon(None, h['img']) for h in all_heroes]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    icons = {}
    for hero, result in zip(all_heroes, results):
        if isinstance(result, Exception):
            icons[hero['id']] = None
        else:
            icons[hero['id']] = result

    avatar_tasks = [fetch_avatar_for_hero(h['id']) for h in all_heroes]
    avatar_results = await asyncio.gather(*avatar_tasks, return_exceptions=True)
    avatars = {}
    for hero, result in zip(all_heroes, avatar_results):
        if isinstance(result, Exception):
            avatars[hero['id']] = None
        else:
            avatars[hero['id']] = result

    # Fallback: для героев без аватарки создаём серый placeholder-кружок
    placeholder_avatar = Image.new("RGBA", (40, 40), (60, 60, 70, 255))
    ph_mask = Image.new("L", (40, 40), 0)
    ImageDraw.Draw(ph_mask).ellipse([0, 0, 39, 39], fill=255)
    placeholder_avatar.putalpha(ph_mask)
    for hero in all_heroes:
        if hero['id'] not in avatars or avatars[hero['id']] is None:
            avatars[hero['id']] = placeholder_avatar

    return await asyncio.to_thread(
        _compose_infographic, base, draw, grid, icons, font_lg, margin_x, margin_y,
        gap_between_cols, col_width, row_height, icon_height, avatars
    )


"""
Hero meta cache for reducing image generation load
"""
_hero_meta_cache = {"data": None, "timestamp": 0}
_HERO_META_CACHE_TTL = 12 * 3600  # 12 hours
HERO_META_CONFIG_KEY = 'hero_meta_data'
HERO_META_CONFIG_TTL = 7 * 24 * 3600  # 7 days
HERO_META_BANNER_KEY = 'hero_meta_banner'  # Cached PNG bytes


def clear_hero_meta_cache():
    _hero_meta_cache["data"] = None
    _hero_meta_cache["timestamp"] = 0
    try:
        from database import set_config
        set_config(HERO_META_CONFIG_KEY, "")
        set_config(HERO_META_BANNER_KEY, "")
    except Exception as e:
        logger.debug(f"Failed to clear hero meta DB cache: {e}")


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
                logger.info("Using cached hero meta from DB config, re-enriching")
                _hero_meta_cache["data"] = cached_data
                _hero_meta_cache["timestamp"] = cached_ts
                enriched = await _enrich_hero_icons(cached_data)
                if enriched:
                    return enriched
                return cached_data
    except Exception as e:
        logger.warning(f"Failed to read hero meta from DB config: {e}")

    # Get data from local database instead of OD explorer
    try:
        hero_stats = await asyncio.to_thread(_get_hero_stats_from_db, days)
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
                         col_width, row_height, icon_height, avatars=None):
    """Heavy PIL composition — runs in a thread pool to avoid blocking the event loop."""
    if avatars is None:
        avatars = {}
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
                except Exception as e:
                    logger.debug(f"Could not load small font: {e}")
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

            avatar_img = avatars.get(hero['id'])
            if avatar_img is not None:
                icon_proc = _draw_avatar_circle(icon_proc, avatar_img, size=40, border=3)

            base.paste(icon_proc, (icon_x, icon_y), icon_proc)

            wr_text = "%dW/%dL/%d%%" % (hero['pub_win'], hero['pub_losses'], hero['winrate'] * 100)

            try:
                bb = draw.textbbox((0, 0), wr_text, font=font_lg)
                tw = bb[2] - bb[0]
                th = bb[3] - bb[1]
                tx = icon_x + pw // 2 - tw // 2
                ty = icon_y + nh + 2 - 4 - th
                draw.text((tx, ty), wr_text, fill=(255, 255, 255), font=font_lg)
            except Exception:
                draw.text((icon_x + pw // 2 - 30, icon_y + nh - 24),
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
        except Exception as e:
            logger.debug(f"Could not load fallback font: {e}")
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
