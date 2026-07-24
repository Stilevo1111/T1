"""
OBS widget: transparent PNG with last 5 Dota 2 matches for website/OBS overlay.

Endpoint:
    /api/obs-last5?steam_id=... or /api/obs-last5?telegram_id=...

Behavior:
    - Fetches last 5 matches from OpenDota
    - Downloads hero icons (with local cache)
    - Draws 5 cards in a row, each with colored border:
        green = win
        red  = loss
    - Returns PNG with transparent background, suitable for OBS
"""

from __future__ import annotations

import io
import logging
import os
import time
from pathlib import Path

import aiohttp
from PIL import Image, ImageDraw, ImageFont

from dota_mmr import get_heroes_data, get_recent_matches_async
from database import get_user

logger = logging.getLogger(__name__)

# ============================================================
# CONFIG
# ============================================================

CARD_SIZE = 72
CARD_SPACING = 10
BORDER_WIDTH = 3
PADDING_X = 14
PADDING_Y = 14

WIDGET_WIDTH = (
    PADDING_X * 2
    + 5 * CARD_SIZE
    + 4 * CARD_SPACING
)
WIDGET_HEIGHT = (
    PADDING_Y * 2
    + CARD_SIZE
)

WIN_COLOR = (34, 197, 94, 255)      # solid green
LOSS_COLOR = (239, 68, 68, 255)     # solid red
BG_COLOR = (0, 0, 0, 0)             # fully transparent for OBS

# ============================================================
# CACHES
# ============================================================

_widget_cache: dict[str, tuple[bytes, float]] = {}
_WIDGET_CACHE_TTL = 180  # 3 minutes

_icon_cache: dict[str, Image.Image] = {}
_ICON_CACHE_TTL = 3600  # 1 hour

_ICON_CACHE_DIR = Path("cache/obs_icons")
_ICON_CACHE_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================
# HELPERS
# ============================================================


def _cache_key(steam_id: int, limit: int) -> str:
    return f"obs_widget_{steam_id}_{limit}"


async def _fetch_hero_icon(hero_info: dict | None, session: aiohttp.ClientSession) -> Image.Image | None:
    """Download hero icon with disk cache. Returns RGBA Image or None."""
    if not hero_info:
        return None

    icon_url = hero_info.get("icon_url") or hero_info.get("image_url") or ""
    if not icon_url:
        return None

    cache_key = icon_url
    now = time.time()

    cached = _icon_cache.get(cache_key)
    if cached and (now - cached[1]) < _ICON_CACHE_TTL:
        return cached[0]

    filename = os.path.basename(icon_url.split("?")[0])
    cache_path = _ICON_CACHE_DIR / filename

    if cache_path.exists() and not cache_path.is_dir():
        try:
            img = Image.open(cache_path).convert("RGBA")
            _icon_cache[cache_key] = (img, now)
            return img
        except Exception:
            logger.debug("Failed to open cached obs icon: %s", cache_path)

    try:
        async with session.get(
            icon_url, timeout=aiohttp.ClientTimeout(total=6)
        ) as resp:
            if resp.status != 200:
                return None
            data = await resp.read()

        img = Image.open(io.BytesIO(data)).convert("RGBA")

        try:
            with open(cache_path, "wb") as f:
                f.write(data)
        except Exception:
            logger.debug("Failed to write obs icon cache: %s", cache_path)

        _icon_cache[cache_key] = (img, now)
        return img
    except Exception as e:
        logger.debug("Failed to load obs hero icon %s: %s", icon_url, e)
        return None


# ============================================================
# MAIN
# ============================================================


async def generate_obs_widget(
    steam_id: int,
    limit: int = 5,
) -> bytes | None:
    """Generate transparent PNG widget for last `limit` matches."""
    cache_key = _cache_key(steam_id, limit)
    cached = _widget_cache.get(cache_key)
    if cached and (time.time() - cached[1]) < _WIDGET_CACHE_TTL:
        return cached[0]

    matches = await get_recent_matches_async(steam_id, limit=limit)
    if not matches:
        matches = []

    heroes_data = get_heroes_data() or {}

    try:
        from database import get_aiohttp_session
        session = await get_aiohttp_session()
    except Exception:
        session = None

    img = Image.new("RGBA", (WIDGET_WIDTH, WIDGET_HEIGHT), BG_COLOR)
    draw = ImageDraw.Draw(img)

    wins = 0
    for i, match in enumerate(matches[:limit]):
        hero_id = match.get("hero_id")
        hero_info = heroes_data.get(hero_id)
        player_slot = match.get("player_slot", 0)
        radiant_win = bool(match.get("radiant_win", False))
        is_win = (player_slot < 128) == radiant_win
        if is_win:
            wins += 1

        x = PADDING_X + i * (CARD_SIZE + CARD_SPACING)
        y = PADDING_Y

        border = WIN_COLOR if is_win else LOSS_COLOR
        draw.rounded_rectangle(
            [x, y, x + CARD_SIZE - 1, y + CARD_SIZE - 1],
            radius=8,
            fill=border,
        )

        icon = None
        if session:
            icon = await _fetch_hero_icon(hero_info, session)

        if icon:
            icon_resized = icon.resize((CARD_SIZE, CARD_SIZE), Image.Resampling.LANCZOS)
            img.paste(icon_resized, (x, y), icon_resized)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    data = buf.getvalue()

    _widget_cache[cache_key] = (data, time.time())
    return data


async def get_steam_id_from_telegram(telegram_id: int) -> int | None:
    """Resolve steam_id from telegram_id via DB."""
    try:
        user = await asyncio.to_thread(get_user, telegram_id)
        if not user:
            return None
        steam_id = user.get("steam_id")
        if not steam_id:
            return None
        return int(steam_id)
    except Exception as e:
        logger.debug("obs_widget: failed to resolve steam_id for %s: %s", telegram_id, e)
        return None


async def get_default_steam_id() -> int | None:
    """Get steam_id for default OBS widget from config."""
    try:
        from config import settings
        obs_steam_id = getattr(settings, 'OBS_WIDGET_STEAM_ID', None)
        if obs_steam_id:
            logger.info("obs_widget: using OBS_WIDGET_STEAM_ID=%s", obs_steam_id)
            return int(obs_steam_id)

        admin_chat_id = getattr(settings, 'ADMIN_CHAT_ID', None)
        if admin_chat_id:
            logger.info("obs_widget: ADMIN_CHAT_ID=%s, resolving steam_id...", admin_chat_id)
            steam_id = await get_steam_id_from_telegram(int(admin_chat_id))
            if steam_id:
                logger.info("obs_widget: resolved steam_id=%s from ADMIN_CHAT_ID", steam_id)
            else:
                logger.warning("obs_widget: ADMIN_CHAT_ID=%s has no linked steam_id", admin_chat_id)
            return steam_id

        logger.warning("obs_widget: no OBS_WIDGET_STEAM_ID and no ADMIN_CHAT_ID configured")
        return None
    except Exception as e:
        logger.error("obs_widget: failed to get default steam_id: %s", e)
        return None

