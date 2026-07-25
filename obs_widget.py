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

CARD_SIZE = 64
CARD_SPACING = 6

WIDGET_WIDTH = 5 * CARD_SIZE + 4 * CARD_SPACING
WIDGET_HEIGHT = CARD_SIZE

WIN_COLOR = (34, 197, 94, 255)
LOSS_COLOR = (239, 68, 68, 255)
UNKNOWN_COLOR = (120, 120, 120, 255)
BG_COLOR = (0, 0, 0, 0)
WIDGET_BORDER_RADIUS = 10
ICON_MARGIN = 4
FALLBACK_FONT_RATIO = 0.55

THEME_COLORS = {
    "default": {
        "win": (34, 197, 94, 255),
        "loss": (239, 68, 68, 255),
        "unknown": (120, 120, 120, 255),
    },
    "minimal": {
        "win": (34, 197, 94, 255),
        "loss": (239, 68, 68, 255),
        "unknown": (0, 0, 0, 0),
    },
    "ranked": {
        "win": (34, 197, 94, 255),
        "loss": (239, 68, 68, 255),
        "unknown": (60, 60, 60, 255),
    },
}
DEFAULT_THEME = "default"
_CARD_BASE_FONT_SIZE = 20

logger = logging.getLogger(__name__)

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


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/Arial-Bold.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _build_icon_mask(icon: Image.Image):
    """Create paste mask from icon alpha/brightness without modifying the source image."""
    rgba = icon.convert("RGBA")
    w, h = rgba.size
    if w < 4 or h < 4:
        return rgba.split()[-1]

    corners = [
        rgba.getpixel((0, 0)),
        rgba.getpixel((w - 1, 0)),
        rgba.getpixel((0, h - 1)),
        rgba.getpixel((w - 1, h - 1)),
    ]
    avg_r = sum(p[0] for p in corners) / 4.0
    avg_g = sum(p[1] for p in corners) / 4.0
    avg_b = sum(p[2] for p in corners) / 4.0
    max_dist = 0
    for p in corners:
        dist = ((p[0] - avg_r) ** 2 + (p[1] - avg_g) ** 2 + (p[2] - avg_b) ** 2) ** 0.5
        if dist > max_dist:
            max_dist = dist

    alpha = rgba.split()[-1]
    if max_dist > 35:
        return alpha

    threshold = max(18, max_dist * 1.8)
    mask = Image.new("L", (w, h), 0)
    for y in range(h):
        for x in range(w):
            r, g, b, a = rgba.getpixel((x, y))
            dist = ((r - avg_r) ** 2 + (g - avg_g) ** 2 + (b - avg_b) ** 2) ** 0.5
            new_a = 0 if dist < threshold else a
            mask.putpixel((x, y), new_a)
    return mask


async def _fetch_hero_icon(hero_info: dict | None, session: aiohttp.ClientSession) -> Image.Image | None:
    """Download hero icon with disk cache. Returns raw RGBA Image without modifications."""
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
            icon_url, timeout=aiohttp.ClientTimeout(total=6), headers={"User-Agent": "Mozilla/5.0 (compatible; FissureBot/1.0)"}
        ) as resp:
            if resp.status != 200:
                return None
            content_type = resp.headers.get("Content-Type", "")
            if not content_type.startswith("image/"):
                logger.debug("Unexpected Content-Type for obs icon %s: %s", icon_url, content_type)
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
    matches = await get_recent_matches_async(steam_id, limit=limit)
    if not matches:
        matches = []

    heroes_data = get_heroes_data() or {}

    session = None
    try:
        from database import get_aiohttp_session
        session = await get_aiohttp_session()
    except Exception:
        pass

    img = Image.new("RGBA", (WIDGET_WIDTH, WIDGET_HEIGHT), BG_COLOR)
    draw = ImageDraw.Draw(img)

    for i in range(limit):
        if i < len(matches):
            match = matches[i]
            hero_id = match.get("hero_id")
            hero_info = heroes_data.get(hero_id)
            player_slot = match.get("player_slot", 0)
            radiant_win = bool(match.get("radiant_win", False))
            is_win = (player_slot < 128) == radiant_win
        else:
            hero_id = None
            hero_info = None
            is_win = None

        x = i * (CARD_SIZE + CARD_SPACING)
        y = 0

        if is_win is True:
            border = WIN_COLOR
        elif is_win is False:
            border = LOSS_COLOR
        else:
            border = UNKNOWN_COLOR

        draw.rounded_rectangle(
            [x, y, x + CARD_SIZE - 1, y + CARD_SIZE - 1],
            radius=10,
            fill=border,
        )

        icon = None
        if hero_info:
            icon = await _fetch_hero_icon(hero_info, session)

        if icon:
            icon_rgba = icon.convert("RGBA")
            icon_resized = icon_rgba.resize((CARD_SIZE - 8, CARD_SIZE - 8), Image.Resampling.LANCZOS)
            mask = _build_icon_mask(icon_resized)
            img.paste(icon_resized, (x + 4, y + 4), mask)
        else:
            label = "?"
            if hero_info:
                label = (hero_info.get("name") or "?")[:1].upper()
            font = _load_font(int(CARD_SIZE * 0.55))
            bbox = draw.textbbox((0, 0), label, font=font)
            text_w = bbox[2] - bbox[0]
            text_h = bbox[3] - bbox[1]
            text_x = x + (CARD_SIZE - text_w) / 2
            text_y = y + (CARD_SIZE - text_h) / 2 - int(CARD_SIZE * 0.05)
            draw.text((text_x, text_y), label, font=font, fill=(255, 255, 255, 255))

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    data = buf.getvalue()

    _widget_cache[_cache_key(steam_id, limit)] = (data, time.time())
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

