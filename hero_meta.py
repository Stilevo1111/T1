# -*- coding: utf-8 -*-
"""
Генерация изображений Hero Meta (еженедельная статистика героев Dota 2).

Модуль отвечает за:
- Получение данных из OpenDota (heroStats + explorer)
- Определение позиции героев
- Построение инфографики с топ-героями по позициям
- Генерацию красивых PNG-изображений

Публичный API:
- get_hero_meta_image
- get_static_fallback_banner
- apply_fancy_style
- detect_hero_position

Все изменения в этом файле должны сохранять точный визуальный результат
и поведение генерации изображений.
"""

from __future__ import annotations

import asyncio
import aiohttp
import io
import os
import math
import logging
from pathlib import Path
from urllib.parse import urlparse
from typing import Any
from PIL import Image, ImageDraw, ImageFont
from hero_positions import hero_positions

# Type aliases
HeroStat = dict[str, Any]
HeroStats = list[HeroStat]


def _load_font(size: int, windows_basenames: list[str] | None = None):
    """Load a TrueType font preferring FONT_PATH, fallback to common Windows fonts, finally default.

    Returns a PIL ImageFont instance. This helper preserves original fallback order used in the module.
    """
    # If FONT_PATH is a path string, prefer it
    try:
        if isinstance(FONT_PATH, str):
            try:
                return ImageFont.truetype(FONT_PATH, size)
            except Exception:
                pass
        else:
            # FONT_PATH might already be a loaded font object (ImageFont instance)
            return FONT_PATH
    except Exception:
        pass

    if windows_basenames is None:
        windows_basenames = ['arialbd.ttf', 'Arial-Bold.ttf', 'DejaVuSans-Bold.ttf']

    for bn in windows_basenames:
        try:
            return ImageFont.truetype(f"C:/Windows/Fonts/{bn}", size)
        except Exception:
            continue

    # Last resort - default PIL font
    return ImageFont.load_default()

logger = logging.getLogger(__name__)

__all__ = [
    "get_hero_meta_image",
    "get_static_fallback_banner",
    "apply_fancy_style",
    "detect_hero_position",
]

BACKGROUND_PATH: str = "background_new.png"

ICON_CACHE_DIR: Path = Path("cache/meta_icons")
try:
    ICON_CACHE_DIR.mkdir(parents=True, exist_ok=True)
except Exception:
    # If we cannot create cache directory (e.g., read-only FS), continue without failing
    pass

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


def detect_hero_position(hero_data: dict[str, Any]) -> int:
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


def apply_fancy_style(img: Image.Image, size: tuple[int, int] = (188, 100), radius: int = 15, border_width: int = 3) -> Image.Image:
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


async def fetch_hero_icon(session: aiohttp.ClientSession, icon_path: str) -> Image.Image | None:
    """Fetch hero icon from CDN or cache.

    Returns a Pillow Image in RGBA mode on success, or None on failure.
    This function does not raise; failures are logged and None is returned.
    """
    

    # ==========================================
    # BUILD URL
    # ==========================================

    # Clean the path - remove trailing ? or query params that might cause issues
    icon_path = icon_path.split("?")[0].rstrip("/")

    if icon_path.startswith('/'):
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


async def get_dota_data(days: int = 7) -> HeroStats | None:
    """Fetch weekly hero statistics from OpenDota (explorer fallback).

    Returns a list of hero stat dicts or None on failure.
    """
    import time
    now = int(time.time())
    week_ago = now - (days * 24 * 60 * 60)
    
    sql = f"""
        SELECT 
            hero_id,
            COUNT(*) as pub_pick,
            SUM(
                CASE 
                    WHEN (radiant_win = TRUE AND player_slot < 128) OR 
                         (radiant_win = FALSE AND player_slot >= 128) 
                    THEN 1 ELSE 0 
                END
            ) as pub_win
        FROM public_player_matches 
        WHERE start_time >= {week_ago}
        GROUP BY hero_id
        HAVING COUNT(*) >= 10
    """
    
    try:
        from database import get_aiohttp_session
        session = await get_aiohttp_session()
        async with session.post(
            "https://api.opendota.com/api/explorer",
            data={"sql": sql},
            timeout=aiohttp.ClientTimeout(total=30)
        ) as resp:
            if resp.status == 200:
                data = await resp.json()
                if data and "rows" in data and data["rows"]:
                    hero_stats: HeroStats = []
                    for row in data["rows"]:
                        hero_stats.append({
                            "id": row["hero_id"],
                            "localized_name": f"Hero {row['hero_id']}",
                            "roles": [],
                            "pub_pick": row["pub_pick"],
                            "pub_win": row["pub_win"],
                            "img": f"/apps/dota2/images/dota/heroes/{row['hero_id']}_sb.png"
                        })
                    return await _enrich_with_hero_data(hero_stats)
    except Exception as e:
        logger.warning("Explorer failed: %s", e)
    
    try:
        from database import get_aiohttp_session
        session = await get_aiohttp_session()
        async with session.get("https://api.opendota.com/api/heroStats", timeout=aiohttp.ClientTimeout(total=5)) as resp:
            if resp.status == 200:
                return await resp.json()
    except Exception as e:
        logger.error("heroStats error: %s", e)
    return None



async def _enrich_with_hero_data(hero_stats: list[dict]) -> list[dict]:
    """Fetches hero metadata and enriches hero_stats in place (name, roles, img).

    Returns the same list (possibly modified) for convenience.
    """
    
    try:
        from database import get_aiohttp_session
        session = await get_aiohttp_session()
        async with session.get("https://api.opendota.com/api/heroes", timeout=aiohttp.ClientTimeout(total=5)) as resp:
            if resp.status == 200:
                heroes = await resp.json()
                hero_map = {h["id"]: h for h in heroes}
                for hs in hero_stats:
                    if hs["id"] in hero_map:
                        hero = hero_map[hs["id"]]
                        hs["localized_name"] = hero["localized_name"]
                        hs["roles"] = hero.get("roles", [])
                        hs["img"] = hero.get("img", hs["img"])
    except Exception as e:
        logger.warning("Could not enrich hero data: %s", e)
    return hero_stats


def _build_grid(hero_stats: list[dict]) -> dict:
    """Builds a 5-column grid of top-5 heroes per role based on winrate and matches.

    This function preserves the original behavior and selection criteria.
    """
    
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

        score = (
            winrate *
            math.log10(matches + 1)
        )

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
            'roles': hero.get("roles", []),
        })

    # Group by position and sort by winrate (highest first)
    by_position = {1: [], 2: [], 3: [], 4: [], 5: []}
    for hero in processed_heroes:
        by_position[hero['position']].append(hero)

    # Take top 5 by winrate for each position (highest at top)
    grid = {}
    for pos in range(1, 6):
        heroes = sorted(by_position[pos], key=lambda h: -h['winrate'])
        grid[pos] = heroes[:5]

    # Ensure we have enough heroes - fill with heroes that can play the role if needed
    all_heroes_sorted = sorted(processed_heroes, key=lambda h: -h['winrate'])

    pos_role_map = {
        1: ["Carry"],
        2: ["Mid"],
        3: ["Offlane"],
        4: ["Support", "Soft Support"],
        5: ["Hard Support"]
    }

    for pos in range(1, 6):
        if len(grid[pos]) < 5:
            # Fill remaining slots with top heroes that have the role
            needed_roles = pos_role_map[pos]
            for h in all_heroes_sorted:
                if h['id'] not in {hero['id'] for pos_list in grid.values() for hero in pos_list}:
                    hero_roles = h.get('roles', [])
                    if any(role in needed_roles for role in hero_roles):
                        grid[pos].append(h)
                        if len(grid[pos]) >= 5:
                            break

    return grid


async def create_infographic(hero_stats: list[dict]) -> bytes | None:
    """Render the hero meta infographic as PNG bytes.

    The rendering layout and pixel coordinates are preserved exactly to avoid any
    change in visual appearance. Returns PNG bytes on success, or None on failure.
    """
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

    date_font = _load_font(24)
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

    font_lg = _load_font(28)


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
    
    tasks = [
        fetch_hero_icon(session, h['img'])
        for h in all_heroes
    ]

    results = await asyncio.gather(
        *tasks,
        return_exceptions=True
    )

    icons = {}

    for hero, result in zip(all_heroes, results):

        if isinstance(result, Exception):

            logger.exception(
                "Failed load hero icon"
            )

            icons[hero['id']] = None

        else:

            icons[hero['id']] = result

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
                ph_font = _load_font(16)

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


async def get_hero_meta_image() -> bytes | None:
    """Main public entrypoint. Returns PNG bytes for hero meta infographic (or fallback)."""
    logger.info("get_hero_meta_image called")
    try:
        data = await get_dota_data()
        if not data:
            logger.error("No data from OpenDota")
            logger.info("Using fallback banner")
            return get_static_fallback_banner()
        banner = await create_infographic(data)
        if banner:
            return banner
        logger.warning("create_infographic returned None, using fallback")
        return get_static_fallback_banner()
    except Exception as e:
        logger.warning("Hero meta generation failed: %s", e)
        return get_static_fallback_banner()


def get_static_fallback_banner() -> bytes | None:
    """Returns a static fallback PNG banner when live data is unavailable."""
    logger.info("Generating static fallback banner")
    try:
        base = Image.new("RGBA", (1200, 200), (25, 25, 35, 255))
        draw = ImageDraw.Draw(base)
        from datetime import datetime, timezone, timedelta
        MSK = timezone(timedelta(hours=3))
        date_text = datetime.now(MSK).strftime("%d.%m.%Y %H:%M")
        font = _load_font(32)

        # Removed "Dota 2 Hero Meta" label as requested
        draw.text((20, 20), "Updated: %s" % date_text, fill=(200, 200, 200), font=font)
        draw.text((20, 70), "API unavailable", fill=(150, 150, 150), font=font)

        buf = io.BytesIO()
        base.save(buf, format='PNG')
        return buf.getvalue()
    except Exception as e:
        logger.error("Static banner error: %s", e)
        return None