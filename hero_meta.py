"""Hero Meta — защищённый модуль генерации инфографики героев.

Этот модуль отвечает за еженедельную картинку «лучшие герои»: сбор
статистики, выбор героев по позициям, загрузку портретов героев и аватаров
игроков, компоновку PNG и многоуровневое кэширование.

ВАЖНО: Hero Meta считается стабильной и рабочей. Не меняйте поток данных,
fallback-цепочки, таймауты, ключи кэша или обработку изображений без регрессионных
тестов и ручной проверки готовой картинки.

Поток выполнения
-----------------
1. ``get_hero_meta_banner(bot)`` сначала читает PNG из Redis по ключу
   ``hero_meta_banner_v2``. Значение хранится в base64, TTL — 12 часов.
2. При промахе вызывается ``get_hero_meta_image(bot)``.
3. ``get_hero_meta_image`` получает данные через ``get_dota_data`` и создаёт
   картинку через ``create_infographic``; готовый PNG также сохраняется в Redis.
4. ``get_dota_data`` проверяет память (12 часов), затем конфиг БД
   ``hero_meta_data`` (7 дней), после чего читает локальную таблицу
   ``public_player_matches`` и обогащает строки именами и изображениями героев.
5. ``create_infographic`` строит сетку 5 позиций по 5 героев, загружает
   портреты героев и аватары лучших игроков, затем запускает тяжёлую сборку PIL
   через ``asyncio.to_thread``.

Типы изображений нельзя смешивать
---------------------------------
* Портрет героя — большое изображение героя. Его загружает
  ``fetch_hero_portrait`` через ``dota_mmr.get_cached_hero_portrait``.
* Иконка героя — маленький локальный файл из ``assets/heroes_webp``. Его
  загружает ``fetch_hero_icon``.
* Аватар игрока — Telegram/OpenDota/Steam-изображение. HTTP-аватары загружает
  только ``_download_image_async`` через общий ``aiohttp.ClientSession``.
* Не передавайте HTTP-URL аватара в ``fetch_hero_icon`` или
  ``fetch_hero_portrait``: это локальные загрузчики героев, а не downloader.
* ``_extract_hero_name`` нормализует локальный путь, Windows-слэши, CDN-путь и
  query-параметры до имени героя. Не заменяйте его самодельным разбором строки.
* Все ``Image.open`` должны использовать контекстный менеджер, ``image.load()``
  и ``convert("RGBA")`` до возврата изображения.

Цепочка аватара игрока в ``create_infographic`` обязательна
------------------------------------------------------------
1. Telegram profile photo через экземпляр бота.
2. Telegram profile photo через raw Bot API.
3. Telegram avatar file_id через raw Bot API.
4. Прямой HTTP-URL аватара через ``_download_image_async``.
5. OpenDota avatar по ``steam_id`` через ``fetch_avatar_by_steam_id``.
6. Серый placeholder, если все источники недоступны.

Кэш и инвалидация
-----------------
* ``_hero_meta_cache`` — память, TTL 12 часов.
* ``hero_meta_data`` — конфиг БД, TTL 7 дней.
* ``hero_meta_banner`` — устаревший ключ PNG в конфиге БД.
* ``hero_meta_banner_v2`` — актуальный Redis-ключ PNG.
* В асинхронном коде используйте ``clear_hero_meta_cache_async``.
* ``clear_hero_meta_cache`` оставлена только для совместимости с синхронными
  вызовами; она выбирает ``asyncio.run`` или ``create_task`` по контексту.
* После изменения статистики, источников изображений или вёрстки обязательно
  очищайте память, оба ключа БД и Redis одним вызовом очистителя.

Правила безопасного изменения
-----------------------------
* Сохраняйте порядок fallback-источников: потеря одного источника не должна
  ломать всю инфографику.
* Токен бота берите только через ``_get_bot_token()``: в ``config`` он лежит в
  ``settings.BOT_TOKEN``, поэтому ``from config import BOT_TOKEN`` падает с
  ``ImportError`` и молча отключает raw Bot API источники аватарок.
* Сохраняйте общий aiohttp-session для параллельной загрузки аватаров и
  закрывайте только созданную внутри функцию сессию.
* Не убирайте таймауты внешних запросов и ``return_exceptions=True`` у
  параллельных загрузок.
* Не убирайте ``asyncio.to_thread`` для тяжёлой PIL-компоновки и DB-запросов.
* Не меняйте размеры сетки, отступы и формат PNG без проверки на реальных
  данных и ручной проверки изображения.
* Перед изменением запускайте:
  ``pytest tests/test_local_assets.py tests/test_audit_fixes.py -q``
  и критический lint:
  ``ruff check --select E9,F63,F7,F82 hero_meta.py``.
"""

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

from bot_utils import get_user_avatar_url
from constants import get_banner_path
from dota_mmr import get_player_stats_async
from hero_positions import hero_positions

logger = logging.getLogger(__name__)

# Rate limit cache
_explorer_cache = {"data": None, "timestamp": 0, "fallback_used": False}


def _extract_hero_name(icon_path: str) -> str | None:
    icon_path = str(icon_path).split("?")[0].rstrip("/")
    normalized_path = icon_path.replace("\\", "/")

    if "/apps/dota2/images/dota/heroes/" in normalized_path:
        match = re.search(r"/heroes/([a-zA-Z0-9_]+)_sb\.png", normalized_path)
        if match:
            return match.group(1)

    filename = os.path.basename(normalized_path)
    if not filename:
        return None

    return (
        filename.replace("_sb.png", "")
        .replace(".png", "")
        .replace(".webp", "")
        .replace(".jpg", "")
        .replace(".jpeg", "")
    )


async def _download_image_async(
    image_url: str,
    session: aiohttp.ClientSession | None = None,
    timeout: int = 10,
) -> Image.Image | None:
    if not image_url:
        return None

    parsed_url = urlparse(image_url)
    if parsed_url.scheme not in ("http", "https") or not parsed_url.netloc:
        return None

    close_session = False
    if session is None:
        session = aiohttp.ClientSession()
        close_session = True

    try:
        async with session.get(
            image_url,
            timeout=aiohttp.ClientTimeout(total=timeout),
            headers={"User-Agent": "fissure-bot/1.0"},
        ) as resp:
            if resp.status != 200:
                logger.debug(f"Image download failed for {image_url}: HTTP {resp.status}")
                return None
            data = await resp.read()
            if not data:
                return None
            with Image.open(io.BytesIO(data)) as image:
                image.load()
                return image.convert("RGBA")
    except Exception as e:
        logger.debug(f"Image download failed for {image_url}: {e}")
        return None
    finally:
        if close_session:
            await session.close()


async def fetch_avatar_by_steam_id(
    steam_id: int,
    session: aiohttp.ClientSession | None = None,
) -> Image.Image | None:
    """Fetch player avatar directly from OpenDota API by Steam ID.

    Used as fallback when player is not linked to a user account. Успешные
    загрузки кладутся в дисковый кэш, чтобы временные rate-limit'ы OpenDota
    не приводили к потере аватарок в инфографике.
    """
    if not steam_id:
        return None
    cached_avatar = await asyncio.to_thread(_load_cached_avatar, f"steam_{steam_id}")
    if cached_avatar is not None:
        return cached_avatar
    try:
        stats = await get_player_stats_async(steam_id, use_cache=True, timeout=5)
        if stats:
            avatar_url = stats.get("avatar") or stats.get("avatarfull")
            if avatar_url:
                img = await _download_image_async(avatar_url, session=session)
                if img:
                    await asyncio.to_thread(_save_cached_avatar, f"steam_{steam_id}", img)
                    return img
        return None
    except Exception as e:
        logger.debug(f"Failed to fetch avatar by steam_id {steam_id}: {e}")
        return None


def _get_bot_token() -> str:
    """Resolve Telegram bot token from ``config.settings`` or environment.

    ``config`` exposes the token only as ``settings.BOT_TOKEN`` (pydantic
    settings), so ``from config import BOT_TOKEN`` raises ``ImportError`` and
    silently disables the raw Bot API avatar fallbacks.
    """
    try:
        from config import settings
        token = getattr(settings, "BOT_TOKEN", None)
        if token:
            return str(token)
    except Exception as e:
        logger.debug(f"Could not read BOT_TOKEN from config.settings: {e}")
    return os.environ.get("BOT_TOKEN", "") or ""


AVATAR_CACHE_DIR = Path("cache/meta_avatars")


def _avatar_disk_cache_path(cache_key: str) -> Path:
    return AVATAR_CACHE_DIR / f"{re.sub(r'[^0-9a-zA-Z_-]', '', str(cache_key))}.png"


def _load_cached_avatar(cache_key: str) -> Image.Image | None:
    """Read a previously downloaded avatar from the disk cache (if any)."""
    try:
        path = _avatar_disk_cache_path(cache_key)
        if not path.exists():
            return None
        with Image.open(path) as image:
            image.load()
            return image.convert("RGBA")
    except Exception as e:
        logger.debug(f"Avatar disk cache read failed for {cache_key}: {e}")
        return None


def _save_cached_avatar(cache_key: str, image: Image.Image) -> None:
    """Persist a downloaded avatar so OpenDota rate limits cannot lose it."""
    try:
        AVATAR_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        image.save(_avatar_disk_cache_path(cache_key), format="PNG")
    except Exception as e:
        logger.debug(f"Avatar disk cache write failed for {cache_key}: {e}")


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


async def fetch_hero_portrait(session, icon_path):
    if not icon_path:
        return None

    icon_path = str(icon_path)
    hero_name = None

    if icon_path.isdigit():
        from dota_mmr import get_hero_list
        from hero_names import get_cdn_hero_name
        heroes = await get_hero_list()
        for h in heroes:
            if h.get("id") == int(icon_path):
                internal_name = h.get("name", "").replace("npc_dota_hero_", "")
                hero_name = get_cdn_hero_name(internal_name)
                break
        if not hero_name:
            return None
    else:
        hero_name = _extract_hero_name(icon_path)

    if not hero_name:
        return None

    try:
        from dota_mmr import get_cached_hero_portrait
        return await get_cached_hero_portrait(hero_name)
    except Exception:
        return None


async def fetch_hero_icon(session, icon_path):
    if not icon_path:
        return None

    icon_path = str(icon_path)
    hero_name = None

    if icon_path.isdigit():
        from dota_mmr import get_hero_list
        from hero_names import get_cdn_hero_name
        heroes = await get_hero_list()
        for h in heroes:
            if h.get("id") == int(icon_path):
                internal_name = h.get("name", "").replace("npc_dota_hero_", "")
                hero_name = get_cdn_hero_name(internal_name)
                break
        if not hero_name:
            return None
    else:
        hero_name = _extract_hero_name(icon_path)

    if not hero_name:
        return None

    local_path = Path("assets/heroes_webp") / f"{hero_name}.webp"
    if not local_path.exists():
        from hero_names import get_local_hero_name
        mapped_name = get_local_hero_name(hero_name)
        if mapped_name != hero_name:
            local_path = Path("assets/heroes_webp") / f"{mapped_name}.webp"

    if local_path.exists():
        try:
            with Image.open(local_path) as image:
                image.load()
                return image.convert("RGBA")
        except Exception:
            pass

    alt_paths = [
        Path("assets/heroes_webp") / f"{hero_name}.png",
        Path("assets/heroes/") / f"{hero_name}.png",
        Path("assets/") / f"{hero_name}.png",
    ]
    for alt_path in alt_paths:
        if alt_path.exists():
            try:
                with Image.open(alt_path) as image:
                    image.load()
                    return image.convert("RGBA")
            except Exception:
                continue

    return None


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
                    with Image.open(io.BytesIO(data)) as image:
                        image.load()
                        return image.convert("RGBA")
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


STEAM_DEFAULT_AVATAR = str(get_banner_path("default_avatar"))


async def create_infographic(hero_stats, bot=None):
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

    bot_token = _get_bot_token()
    if not bot_token:
        logger.warning(
            "Hero meta avatars: BOT_TOKEN not resolved — raw Telegram API fallbacks are disabled"
        )

    avatar_cache = {}
    avatar_sources = {}

    async def fetch_avatar_for_hero(hero_id, session):
        if hero_id in avatar_cache:
            return avatar_cache[hero_id]
        player = best_players.get(hero_id, [{}])[0]
        avatar_url = player.get('avatar')
        telegram_id = player.get('telegram_id')
        img = None
        source = None

        # 1. Try Telegram profile photo first (via bot instance if available)
        if telegram_id and bot:
            try:
                tg_avatar_url = await get_user_avatar_url(bot, telegram_id)
                if tg_avatar_url:
                    img = await _download_image_async(tg_avatar_url, session=session)
                    if img:
                        source = "telegram_bot"
                        logger.debug(f"Telegram avatar via bot for hero {hero_id}")
            except Exception as e:
                logger.debug(f"Telegram avatar via bot failed for hero {hero_id}: {e}")
        
        # 2. If bot not available, try raw API calls
        if not img and telegram_id and bot_token:
            try:
                img = await _fetch_telegram_profile_photo(bot_token, telegram_id)
                if img:
                    source = "telegram_api"
            except Exception as e:
                logger.debug(f"Telegram profile photo failed for hero {hero_id}: {e}")
        
        # 3. Try Telegram avatar file_id (not http URLs)
        if not img and avatar_url and not str(avatar_url).startswith('http') and bot_token:
            try:
                img = await _fetch_telegram_avatar(bot_token, avatar_url)
                if img:
                    source = "telegram_file_id"
            except Exception as e:
                logger.debug(f"Telegram avatar fallback failed for hero {hero_id}: {e}")
        
        # 4. Fallback to Steam/direct avatar URL (http URLs only)
        if not img and avatar_url:
            img = await _download_image_async(avatar_url, session=session)
            if img:
                source = "db_url"
        
        # 5. Fallback: fetch avatar directly from OpenDota by steam_id
        if not img:
            steam_id = player.get('steam_id')
            if steam_id:
                img = await fetch_avatar_by_steam_id(steam_id, session=session)
                if img:
                    source = "opendota"
        
        avatar_cache[hero_id] = img
        avatar_sources[hero_id] = source or "placeholder"
        return img

    tasks = [fetch_hero_portrait(None, h['img']) for h in all_heroes]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    icons = {}
    for hero, result in zip(all_heroes, results):
        if isinstance(result, Exception):
            icons[hero['id']] = None
        else:
            icons[hero['id']] = result

    async with aiohttp.ClientSession() as avatar_session:
        avatar_tasks = [fetch_avatar_for_hero(h['id'], avatar_session) for h in all_heroes]
        avatar_results = await asyncio.gather(*avatar_tasks, return_exceptions=True)
    avatars = {}
    for hero, result in zip(all_heroes, avatar_results):
        if isinstance(result, Exception):
            avatars[hero['id']] = None
        else:
            avatars[hero['id']] = result

    resolved_avatars = sum(1 for hero in all_heroes if avatars.get(hero['id']) is not None)
    source_counts = {}
    for hero in all_heroes:
        source_key = avatar_sources.get(hero['id'], "unknown")
        source_counts[source_key] = source_counts.get(source_key, 0) + 1
    logger.info(
        "create_infographic: avatars resolved=%s/%s, sources=[%s]",
        resolved_avatars,
        len(all_heroes),
        ", ".join(f"{key}={value}" for key, value in sorted(source_counts.items())),
    )

    # Fallback: для героев без аватарки используем Steam default avatar
    def _get_steam_default_avatar():
        """Синхронно создаём placeholder-аватар с цветом Steam gray."""
        try:
            img = Image.new("RGBA", (40, 40), (130, 130, 130, 255))  # Steam gray
            mask = Image.new("L", (40, 40), 0)
            ImageDraw.Draw(mask).ellipse([0, 0, 39, 39], fill=255)
            img.putalpha(mask)
            return img
        except Exception as e:
            logger.debug(f"Could not create Steam default avatar: {e}")
            return None
    
    steam_default_avatar = await asyncio.to_thread(_get_steam_default_avatar)
    
    placeholder_avatar = Image.new("RGBA", (40, 40), (60, 60, 70, 255))
    ph_mask = Image.new("L", (40, 40), 0)
    ImageDraw.Draw(ph_mask).ellipse([0, 0, 39, 39], fill=255)
    placeholder_avatar.putalpha(ph_mask)
    
    for hero in all_heroes:
        if hero['id'] not in avatars or avatars[hero['id']] is None:
            if steam_default_avatar:
                avatars[hero['id']] = steam_default_avatar
            else:
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
HERO_META_REDIS_KEY = 'hero_meta_banner_v2'  # Redis cache key for banner image bytes

async def get_hero_meta_banner(bot=None):
    """Get hero meta banner from Redis cache or generate new one.
    
    Args:
        bot: Telegram bot instance for fetching user profile photos. If None, uses raw API calls.
    
    Returns:
        bytes: PNG image bytes
    """
    import base64
    
    # Try Redis cache first
    try:
        from cache import cache
        cached = await cache.get(HERO_META_REDIS_KEY)
        if cached:
            logger.info("Hero meta banner loaded from Redis cache")
            return base64.b64decode(cached) if isinstance(cached, str) else cached
    except Exception as e:
        logger.debug(f"Redis cache read failed: {e}")
    
    # Generate or load from DB cache
    try:
        banner = await get_hero_meta_image(bot)
        if banner:
            # Save to Redis
            try:
                encoded = base64.b64encode(banner).decode()
                await cache.set(HERO_META_REDIS_KEY, encoded, ttl=_HERO_META_CACHE_TTL)
                logger.info(f"Hero meta banner saved to Redis cache (TTL={_HERO_META_CACHE_TTL}s)")
            except Exception as e:
                logger.debug(f"Redis cache write failed: {e}")
            return banner
    except Exception as e:
        logger.warning(f"Hero meta banner generation failed: {e}")
    
    # Fallback to default banner
    return get_static_fallback_banner()


async def clear_hero_meta_cache_async():
    _hero_meta_cache["data"] = None
    _hero_meta_cache["timestamp"] = 0
    try:
        from database import set_config
        set_config(HERO_META_CONFIG_KEY, "")
        set_config(HERO_META_BANNER_KEY, "")
    except Exception as e:
        logger.debug(f"Failed to clear hero meta DB cache: {e}")

    try:
        from cache import cache
        await cache.delete(HERO_META_REDIS_KEY)
    except Exception as e:
        logger.debug(f"Failed to clear Redis cache: {e}")


def clear_hero_meta_cache():
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(clear_hero_meta_cache_async())
    else:
        asyncio.create_task(clear_hero_meta_cache_async())


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


async def get_hero_meta_image(bot=None):
    """Generate hero meta infographic. Uses Redis cache for 12h.
    
    Args:
        bot: Telegram bot instance for fetching user profile photos.
    """
    import base64
    
    # Try Redis cache first
    try:
        from cache import cache
        cached = await cache.get(HERO_META_REDIS_KEY)
        if cached:
            logger.info("Hero meta banner loaded from Redis cache")
            if isinstance(cached, str):
                return base64.b64decode(cached)
            return cached
    except Exception as e:
        logger.debug(f"Redis cache read failed: {e}")
    
    try:
        # Get fresh data
        data = await get_dota_data()
        if not data:
            logger.error("No data from OpenDota")
            return get_static_fallback_banner()
        
        # Generate new banner
        banner = await create_infographic(data, bot)
        if banner:
            # Save to Redis
            try:
                encoded = base64.b64encode(banner).decode()
                await cache.set(HERO_META_REDIS_KEY, encoded, ttl=_HERO_META_CACHE_TTL)
                logger.info(f"Hero meta banner cached in Redis for {_HERO_META_CACHE_TTL}s")
            except Exception as e:
                logger.debug(f"Could not save to Redis: {e}")
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
