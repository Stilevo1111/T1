# -*- coding: utf-8 -*-
import re
import time
import requests
import logging
import aiohttp
from pathlib import Path
from datetime import datetime, timedelta, timezone
from database import get_user, update_user_fields_batch

logger = logging.getLogger(__name__)

OPENDOTA_API_URL = "https://api.opendota.com/api"
STEAM_OFFSET = 76561197960265728

# Rate limiting для OpenDota API
_api_rate_limit = {"last_request": 0, "requests_count": 0, "window_start": 0}
API_RATE_LIMIT = 20  # максимум запросов в минуту (OpenDota允许30/мин)
API_RATE_WINDOW = 60  # окно в секундах
API_MIN_INTERVAL = 3  # минимум 3 секунды между запросами

# Простой кеш для запросов (5 минут)
_cache = {}
CACHE_TTL = 300  # 5 минут
CACHE_MAX_SIZE = 100  # максимальное количество записей в кеше


def _check_rate_limit():
    """Проверить и обновить rate limiting"""
    import time
    now = time.time()
    
    # Сброс окна если прошла минута
    if now - _api_rate_limit["window_start"] >= API_RATE_WINDOW:
        _api_rate_limit["window_start"] = now
        _api_rate_limit["requests_count"] = 0
    
    # Проверка лимита
    if _api_rate_limit["requests_count"] >= API_RATE_LIMIT:
        wait_time = API_RATE_WINDOW - (now - _api_rate_limit["window_start"])
        if wait_time > 0:
            time.sleep(wait_time)
            _api_rate_limit["window_start"] = time.time()
            _api_rate_limit["requests_count"] = 0
    
    # Минимальный интервал между запросами
    time_since_last = now - _api_rate_limit["last_request"]
    if time_since_last < API_MIN_INTERVAL:
        time.sleep(API_MIN_INTERVAL - time_since_last)
    
    _api_rate_limit["requests_count"] += 1
    _api_rate_limit["last_request"] = time.time()


def _get_cached(key):
    """Получить значение из кеша с ограничением размера"""
    if key in _cache:
        value, timestamp = _cache[key]
        if time.time() - timestamp < CACHE_TTL:
            return value
        del _cache[key]
    return None


def _set_cached(key, value):
    """Сохранить значение в кеш с ограничением размера"""
    # Очистка старых записей если кеш переполнен
    if len(_cache) >= CACHE_MAX_SIZE:
        # Удаляем 20% самых старых записей
        sorted_cache = sorted(_cache.items(), key=lambda x: x[1][1])
        for key_to_remove in sorted_cache[:CACHE_MAX_SIZE // 5]:
            del _cache[key_to_remove[0]]
    
    _cache[key] = (value, time.time())


def _clear_cache():
    """Очистить весь кеш (для освобождения памяти)"""
    global _cache
    _cache = {}


def _api_get(url: str, params: dict = None) -> dict:
    """Универсальная функция для API-запросов с обработкой ошибок и кешем"""
    _check_rate_limit()  # Применяем rate limiting
    try:
        r = requests.get(url, params=params or {}, timeout=10)
        if r.status_code == 200:
            return r.json()
        elif r.status_code == 429:
            logger.warning(f"Rate limited by OpenDota API, waiting...")
            time.sleep(60)  # Ждём минуту при 429
            return None
        return None
    except Exception as e:
        logger.error(f"API request error: {e}", exc_info=True)
        return None


_async_rate_limit = {"last_request": 0, "requests_count": 0, "window_start": 0}

async def _check_rate_limit_async():
    """Async версия rate limiting"""
    import asyncio
    now = time.time()
    
    if now - _async_rate_limit["window_start"] >= API_RATE_WINDOW:
        _async_rate_limit["window_start"] = now
        _async_rate_limit["requests_count"] = 0
    
    if _async_rate_limit["requests_count"] >= API_RATE_LIMIT:
        wait_time = API_RATE_WINDOW - (now - _async_rate_limit["window_start"])
        if wait_time > 0:
            await asyncio.sleep(wait_time)
            _async_rate_limit["window_start"] = time.time()
            _async_rate_limit["requests_count"] = 0
    
    time_since_last = now - _async_rate_limit["last_request"]
    if time_since_last < API_MIN_INTERVAL:
        await asyncio.sleep(API_MIN_INTERVAL - time_since_last)
    
    _async_rate_limit["requests_count"] += 1
    _async_rate_limit["last_request"] = time.time()


async def _api_get_async(url: str, params: dict = None) -> dict:
    """Асинхронная функция для API-запросов"""
    await _check_rate_limit_async()
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params or {}, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    return await resp.json()
                elif resp.status == 429:
                    logger.warning(f"Rate limited by OpenDota API, waiting...")
                    import asyncio
                    await asyncio.sleep(60)
                    return None
                return None
    except Exception as e:
        logger.error(f"API request error: {e}", exc_info=True)
        return None


# ========================
# 🎮 MATCHES
# ========================

# ========================
# 🦸 HEROES
# ========================

HERO_IMAGE_BASE = "https://cdn.cloudflare.steamstatic.com/apps/dota2/images/dota_react/heroes"
HERO_ICON_BASE = "https://cdn.cloudflare.steamstatic.com/apps/dota2/images/dota_react/heroes/icons"
# Фон полоски «любимые герои» (стата): страница https://ibb.co/kgCqy6cL
# Полноразмер 1744×592 — i.ibb.co/.../image.png с id из «Full image», не превью 180×180.
HEROES_STRIP_BG_URL = "https://i.ibb.co/4Zr4fgNb/image.png"
HEROES_STRIP_BG_CACHE = "heroes_strip_stat_1744.png"


def get_hero_icon_cached(hero_short_name: str, timeout: int = 3) -> bytes | None:
    """Get hero icon with caching"""
    try:
        from image_cache import get_cached_hero_icon
        return get_cached_hero_icon(hero_short_name)
    except ImportError:
        pass
    
    cache_file = Path(__file__).parent / "hero_cache" / f"{hero_short_name}.png"
    if cache_file.exists():
        try:
            return cache_file.read_bytes()
        except Exception:
            pass
    
    try:
        url = f"{HERO_ICON_BASE}/{hero_short_name}.png"
        resp = requests.get(url, timeout=timeout)
        if resp.status_code == 200:
            data = resp.content
            try:
                cache_file.parent.mkdir(exist_ok=True)
                cache_file.write_bytes(data)
            except Exception:
                pass
            return data
    except Exception:
        pass
    return None


def get_hero_portrait_cached(hero_short_name: str, timeout: int = 5) -> bytes | None:
    """Портрет героя (dota_react/heroes/*.png) — выше разрешение, чем icons/*.png."""
    if not hero_short_name:
        return None
    cache_dir = Path(__file__).parent / "hero_cache" / "portraits"
    cache_file = cache_dir / f"{hero_short_name}.png"
    if cache_file.exists():
        try:
            return cache_file.read_bytes()
        except Exception:
            pass
    try:
        url = f"{HERO_IMAGE_BASE}/{hero_short_name}.png"
        resp = requests.get(url, timeout=timeout)
        if resp.status_code == 200:
            data = resp.content
            try:
                cache_dir.mkdir(parents=True, exist_ok=True)
                cache_file.write_bytes(data)
            except Exception:
                pass
            return data
    except Exception:
        pass
    return None


def _heroes_strip_gradient(canvas_width: int, canvas_height: int):
    """Запасной градиент под полоску героев."""
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (canvas_width, canvas_height), color=(35, 25, 50))
    draw = ImageDraw.Draw(img)
    for y in range(canvas_height):
        c = tuple(min(255, int((35 + y / 9, 25 + y / 12, 50 + y / 7)[i])) for i in range(3))
        draw.line([(0, y), (canvas_width, y)], fill=c)
    return img


def _compose_heroes_strip_background(canvas_width: int, canvas_height: int):
    """
    Холст фиксированный (иконки как раньше). Фон ImgBB — оригинальные пиксели, без resize.
    Совпадение с холстом — один в один; больше — центр-обрезка; меньше — центр на градиенте.
    """
    from PIL import Image
    import io

    data = None
    cache_file = Path(__file__).parent / "hero_cache" / HEROES_STRIP_BG_CACHE
    try:
        if cache_file.exists():
            try:
                data = cache_file.read_bytes()
            except Exception:
                pass
        if not data:
            resp = requests.get(HEROES_STRIP_BG_URL, timeout=12)
            if resp.status_code == 200 and resp.content:
                data = resp.content
                try:
                    cache_file.parent.mkdir(parents=True, exist_ok=True)
                    cache_file.write_bytes(data)
                except Exception:
                    pass
        if not data:
            return _heroes_strip_gradient(canvas_width, canvas_height)

        nat = Image.open(io.BytesIO(data)).convert("RGB")
        w, h = nat.size

        if w == canvas_width and h == canvas_height:
            return nat.copy()

        if w >= canvas_width and h >= canvas_height:
            left = (w - canvas_width) // 2
            top = (h - canvas_height) // 2
            return nat.crop((left, top, left + canvas_width, top + canvas_height))

        img = nat
        w, h = img.size
        while w > canvas_width:
            left = (w - canvas_width) // 2
            img = img.crop((left, 0, left + canvas_width, h))
            w, h = img.size
        while h > canvas_height:
            top = (h - canvas_height) // 2
            img = img.crop((0, top, w, top + canvas_height))
            w, h = img.size

        canvas = _heroes_strip_gradient(canvas_width, canvas_height)
        w, h = img.size
        canvas.paste(img, ((canvas_width - w) // 2, (canvas_height - h) // 2))
        return canvas
    except Exception as e:
        logger.debug(f"heroes strip background: {e}")
        return _heroes_strip_gradient(canvas_width, canvas_height)


def get_heroes_data() -> dict:
    """Получить данные всех героев из OpenDota (с кешированием)"""
    cached = _get_cached("heroes_data")
    if cached:
        return cached
    
    try:
        url = f"{OPENDOTA_API_URL}/heroes"
        data = _api_get(url)
        if not data:
            return {}
        
        heroes = {}
        for hero in data:
            hero_id = hero["id"]
            # npc_dota_hero_antimage -> antimage
            short_name = hero["name"].replace("npc_dota_hero_", "")
            heroes[hero_id] = {
                "id": hero_id,
                "name": hero["localized_name"],
                "short_name": short_name,
                "image_url": f"{HERO_IMAGE_BASE}/{short_name}.png",
                "icon_url": f"{HERO_ICON_BASE}/{short_name}.png",
            }
        
        _set_cached("heroes_data", heroes)
        logger.info(f"Loaded {len(heroes)} heroes from OpenDota")
        return heroes
    except Exception as e:
        logger.error(f"get_heroes_data error: {e}", exc_info=True)
        return {}


def get_top_heroes(steam_id: int, last_n: int = 10, top_k: int = 3) -> list:
    """Получить топ-{top_k} популярных героев за последние {last_n} игр"""
    import time
    
    _TOP_HEROES_TTL = 3600  # 1 час
    
    cache_key = f"top_heroes_{steam_id}_{last_n}_{top_k}"
    cached = _heroes_image_cache.get(cache_key)
    if cached:
        cached_data, cached_time = cached
        if time.time() - cached_time < _TOP_HEROES_TTL:
            return cached_data
    
    try:
        matches = get_recent_matches(steam_id, limit=last_n)
        if not matches:
            return []
        
        heroes_data = get_heroes_data()
        if not heroes_data:
            return []
        
        from collections import Counter
        hero_counts = Counter()
        for match in matches:
            hero_id = match.get("hero_id")
            if hero_id:
                hero_counts[hero_id] += 1
        
        result = []
        for hero_id, count in hero_counts.most_common(top_k):
            hero_info = heroes_data.get(hero_id)
            if hero_info:
                result.append({
                    "id": hero_id,
                    "name": hero_info["name"],
                    "short_name": hero_info.get("short_name", ""),
                    "image_url": hero_info["image_url"],
                    "icon_url": hero_info["icon_url"],
                    "picks": count,
                })
        
        _heroes_image_cache[cache_key] = (result, time.time())
        return result
    except Exception as e:
        logger.error(f"get_top_heroes error: {e}", exc_info=True)
        return []


async def get_top_heroes_async(steam_id: int, last_n: int = 10, top_k: int = 3) -> list:
    """Асинхронно получить топ-{top_k} популярных героев за последние {last_n} игр"""
    import time
    
    _TOP_HEROES_TTL = 3600  # 1 час
    
    cache_key = f"top_heroes_{steam_id}_{last_n}_{top_k}"
    cached = _heroes_image_cache.get(cache_key)
    if cached:
        cached_data, cached_time = cached
        if time.time() - cached_time < _TOP_HEROES_TTL:
            return cached_data
    
    try:
        matches = await get_recent_matches_async(steam_id, limit=last_n)
        if not matches:
            return []
        
        heroes_data = get_heroes_data()
        if not heroes_data:
            return []
        
        from collections import Counter
        hero_counts = Counter()
        for match in matches:
            hero_id = match.get("hero_id")
            if hero_id:
                hero_counts[hero_id] += 1
        
        result = []
        for hero_id, count in hero_counts.most_common(top_k):
            hero_info = heroes_data.get(hero_id)
            if hero_info:
                result.append({
                    "id": hero_id,
                    "name": hero_info["name"],
                    "short_name": hero_info.get("short_name", ""),
                    "image_url": hero_info["image_url"],
                    "icon_url": hero_info["icon_url"],
                    "picks": count,
                })
        
        _heroes_image_cache[cache_key] = (result, time.time())
        return result
    except Exception as e:
        logger.error(f"get_top_heroes_async error: {e}", exc_info=True)
        return []


def generate_event_icon(hero_url: str, label: str = None) -> bytes | None:
    """Сгенерировать иконку героя (стиль профиля: 63×63, тёмный фон, синяя рамка)"""
    try:
        from PIL import Image, ImageDraw, ImageFont
        import io
        import requests as req
        
        icon_size = 63
        padding = 5
        label_height = 16 if label else 0
        width = icon_size + padding * 2
        height = icon_size + padding * 2 + label_height
        
        img = Image.new("RGB", (width, height), color=(40, 55, 70))
        draw = ImageDraw.Draw(img)
        
        # Загружаем иконку
        try:
            resp = requests.get(hero_url, timeout=5)
            if resp.status_code == 200:
                icon = Image.open(io.BytesIO(resp.content)).convert("RGBA")
                icon = icon.resize((icon_size, icon_size), Image.LANCZOS)
                img.paste(icon, (padding, padding), icon)
        except Exception:
            draw.rectangle([padding, padding, padding + icon_size, padding + icon_size], fill=(80, 95, 110))
        
        # Синяя рамка
        draw.rectangle(
            [padding - 1, padding - 1, padding + icon_size, padding + icon_size],
            outline=(120, 170, 210), width=1
        )
        
        # Подпись
        if label:
            try:
                font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 10)
            except Exception:
                font = ImageFont.load_default()
            bbox = draw.textbbox((0, 0), label, font=font)
            tw = bbox[2] - bbox[0]
            tx = (width - tw) // 2
            ty = icon_size + padding * 2
            draw.text((tx, ty), label, fill=(200, 220, 240), font=font)
        
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        buf.seek(0)
        return buf.read()
    except Exception as e:
        logger.error(f"generate_event_icon error: {e}")
        return None


from concurrent.futures import ThreadPoolExecutor, as_completed


_heroes_image_cache = {}
_heroes_image_cache_ttl = 86400


def _fetch_hero_portrait(hero_short: str) -> tuple[str, bytes | None]:
    """Загрузить портрет героя (для параллельной загрузки)"""
    data = get_hero_portrait_cached(hero_short) or get_hero_icon_cached(hero_short)
    return hero_short, data


def generate_heroes_image(top_heroes: list) -> bytes | None:
    """Сгенерировать картинку с иконками топ-героев: центральный крупнее, к краям меньше."""
    global _heroes_image_cache
    
    try:
        import time
        cache_key = ",".join(str(h.get("id", "")) for h in sorted(top_heroes, key=lambda x: x.get("id", "")))
        if cache_key in _heroes_image_cache:
            cached_data, cached_time = _heroes_image_cache[cache_key]
            if time.time() - cached_time < _heroes_image_cache_ttl:
                return cached_data
        
        from PIL import Image, ImageDraw, ImageFont
        import io
        import requests as req
        
        if not top_heroes:
            return None
        
        target_width = 1744
        target_height = 592
        img = _compose_heroes_strip_background(target_width, target_height)
        padding = 100
        gap = 18
        min_side, max_side = 210, 368
        
        n = len(top_heroes)
        
        top_heroes = sorted(top_heroes, key=lambda h: h.get("picks", 0), reverse=True)
        
        center = (n - 1) / 2.0
        max_dist = max(abs(i - center) for i in range(n))
        if max_dist < 1e-9:
            max_dist = 1.0
        sizes = []
        for i in range(n):
            dist = abs(i - center)
            ratio = 1.0 - (dist / max_dist)
            sz = int(round(min_side + (max_side - min_side) * ratio))
            sizes.append(max(96, sz))
        
        available = target_width - 2 * padding
        total_w = sum(sizes) + gap * max(0, n - 1)
        if total_w > available > 0:
            scale = available / total_w
            sizes = [max(88, int(round(s * scale))) for s in sizes]
            gap = max(8, int(round(gap * scale)))
            total_w = sum(sizes) + gap * max(0, n - 1)
        
        start_x = max(padding, (target_width - total_w) // 2)
        
        draw = ImageDraw.Draw(img)
        
        hero_short_names = [h.get("short_name", "") for h in top_heroes]
        icon_data_map = {}
        
        with ThreadPoolExecutor(max_workers=min(5, n)) as executor:
            futures = {executor.submit(_fetch_hero_portrait, sh): sh for sh in hero_short_names if sh}
            for future in as_completed(futures):
                try:
                    sh, data = future.result()
                    if data:
                        icon_data_map[sh] = data
                except Exception:
                    pass
        
        x = start_x
        for i, hero in enumerate(top_heroes):
            icon_size = sizes[i]
            y = (target_height - icon_size) // 2
            
            hero_short = hero.get("short_name", "")
            icon_data = icon_data_map.get(hero_short)
            
            if icon_data:
                try:
                    icon = Image.open(io.BytesIO(icon_data)).convert("RGBA")
                    w, h = icon.size
                    side = min(w, h)
                    left = (w - side) // 2
                    top = (h - side) // 2
                    icon = icon.crop((left, top, left + side, top + side))
                    icon = icon.resize((icon_size, icon_size), Image.Resampling.LANCZOS)
                    img.paste(icon, (x, y), icon)
                except Exception as e:
                    logger.debug(f"Could not load hero icon: {e}")
                    draw.rectangle([x, y, x + icon_size, y + icon_size], fill=(55, 45, 70))
            else:
                draw.rectangle([x, y, x + icon_size, y + icon_size], fill=(55, 45, 70))
            
            draw.rectangle([x - 2, y - 2, x + icon_size, y + icon_size], outline=(215, 175, 85), width=2)
            x += icon_size + gap
        
        buf = io.BytesIO()
        img_rgb = img.convert("RGB")
        img_rgb.save(buf, format="JPEG", quality=85)
        buf.seek(0)
        result = buf.read()
        
        _heroes_image_cache[cache_key] = (result, time.time())
        return result
    except Exception as e:
        logger.error(f"generate_heroes_image error: {e}", exc_info=True)
        return None

def steam64_to_account_id(steam_id: int) -> int:
    return steam_id - STEAM_OFFSET


def account_id_to_steam64(account_id: int) -> int:
    return account_id + STEAM_OFFSET


def parse_steam_identifier(identifier: str) -> int:
    """
    Возвращает SteamID64 из:
    - SteamID64 (17-20 цифр, 7656119...)
    - Account ID (короткий)
    - Dotabuff-ссылки (https://www.dotabuff.com/players/123456789)
    - Никнейм (возвращает None, обработаем позже)
    """
    identifier = identifier.strip()
    
    # Dotabuff ссылка
    match = re.search(r"players/(\d+)", identifier)
    if match:
        account_id = int(match.group(1))
        return account_id_to_steam64(account_id)
    
    # Чистые цифры
    if identifier.isdigit():
        number = int(identifier)
        if 17 <= len(identifier) <= 20:  # SteamID64 с защитой от случайных чисел
            return number
        else:  # короткий Account ID
            return account_id_to_steam64(number)
    
    # Никнейм (не цифры) → вернем None, обработаем позже
    return None


def safe_winrate(wins: int, games: int) -> float:
    return round((wins / games * 100), 1) if games > 0 else 0


# ========================
# 🎯 MMR (примерный)
# ========================

def rank_to_mmr(rank_tier: int) -> int:
    if not rank_tier:
        return 0

    tier = min(rank_tier // 10, 8)
    star = rank_tier % 10

    return tier * 700 + star * 150


def rank_to_string(rank_tier: int) -> str:
    """Конвертировать rank_tier в читаемый вид (например: "Герой 2", "Титан")"""
    if not rank_tier:
        return "Не калиброван"
    
    ranks = ["Рекрут", "Страж", "Рыцарь", "Герой", "Легенда", "Властелин", "Божество", "Титан"]
    tier = rank_tier // 10
    star = rank_tier % 10
    
    if tier < 1 or tier > 8:
        return "Неизвестно"
    
    rank_name = ranks[tier - 1]
    
    # Титан не имеет звёзд
    if tier == 8:
        return rank_name
    
    return f"{rank_name} {star}"


# ========================
# 🔍 SEARCH PLAYER
# ========================

def search_player(nickname: str) -> dict:
    try:
        url = f"{OPENDOTA_API_URL}/search"
        
        data = _api_get(url, {"q": nickname})
        if not data:
            return None

        player = data[0]
        account_id = player.get("account_id")

        if not account_id:
            return None

        steam_id = account_id_to_steam64(account_id)
        stats = get_player_stats(steam_id)

        if not stats:
            return None

        # Обновляем никнейм из результатов поиска
        stats["nickname"] = player.get("personaname", stats.get("nickname", "Unknown"))
        
        return {
            "steam_id": steam_id,
            **stats
        }

    except Exception as e:
        logger.error("search error", exc_info=True)
        return None


# ========================
# 🎮 MATCHES
# ========================

def get_recent_matches(steam_id: int, limit: int = 5) -> list:
    """Получить последние матчи игрока"""
    try:
        account_id = steam64_to_account_id(steam_id)
        url = f"{OPENDOTA_API_URL}/players/{account_id}/matches"
        
        # Сортируем по start_time (по умолчанию по возрастанию - старые первыми)
        matches = _api_get(url, {"limit": limit, "sort": "start_time"})
        return matches or []
    except Exception as e:
        logger.error(f"get_recent_matches error: {e}", exc_info=True)
        return []


async def get_recent_matches_async(steam_id: int, limit: int = 5) -> list:
    """Асинхронно получить последние матчи игрока"""
    if steam_id is None:
        return []
    try:
        account_id = steam64_to_account_id(steam_id)
        url = f"{OPENDOTA_API_URL}/players/{account_id}/matches"
        
        matches = await _api_get_async(url, {"limit": limit, "sort": "start_time"})
        return matches or []
    except Exception as e:
        logger.error(f"get_recent_matches_async error: {e}", exc_info=True)
        return []


def is_win(match: dict, steam_id: int) -> bool:
    """Определить, выиграл ли игрок матч по данным матча"""
    try:
        return bool(match.get("win", False))
    except Exception as e:
        logger.error(f"is_win error: {e}", exc_info=True)
        return False


def is_win_api(match_id: int, steam_id: int) -> bool:
    """Определить, выиграл ли игрок в матче по ID матча (через API)"""
    try:
        account_id = steam64_to_account_id(steam_id)
        url = f"{OPENDOTA_API_URL}/matches/{match_id}"
        
        match_data = _api_get(url)
        if not match_data:
            return False
        
        players = match_data.get("players", [])
        
        for player in players:
            if player.get("account_id") == account_id:
                return player.get("win", 0) == 1
        
        return False
    except Exception as e:
        logger.error(f"is_win_api error: {e}", exc_info=True)
        return False


# ========================
# 📊 GET STATS
# ========================

def get_player_stats(steam_id: int, use_cache: bool = True) -> dict:
    try:
        # Проверяем кеш
        cache_key = f"player_{steam_id}"
        if use_cache:
            cached = _get_cached(cache_key)
            if cached:
                return cached
            
        account_id = steam64_to_account_id(steam_id)
        
        # Получаем основную информацию об игроке
        player_data = _api_get(f"{OPENDOTA_API_URL}/players/{account_id}")
        if not player_data:
            logger.warning(f"Player data not found for account_id: {account_id}")
            return None

        profile = player_data.get("profile", {})
        rank_tier = player_data.get("rank_tier") or 0
        
        # Получаем статистику побед/поражений
        wl_data = _api_get(f"{OPENDOTA_API_URL}/players/{account_id}/wl")
        if wl_data:
            wins = wl_data.get("win", 0)
            losses = wl_data.get("lose", 0)
            total_games = wins + losses
        else:
            logger.warning(f"Win/Loss data not found for account_id: {account_id}")
            total_games = 0
            wins = 0
            losses = 0
        
        # Используем mmr_estimate для более точного MMR
        mmr_estimate = player_data.get("mmr_estimate", {}).get("estimate", 0)
        mmr = mmr_estimate or rank_to_mmr(rank_tier)
        
        # Вычисляем винрейт
        winrate = safe_winrate(wins, total_games)

        result = {
            "nickname": profile.get("personaname", "Unknown"),
            "avatar": profile.get("avatarfull") or profile.get("avatar"),
            "mmr": mmr,
            "rank_tier": rank_tier,
            "total_games": total_games,
            "wins": wins,
            "losses": losses,
            "winrate": winrate,
        }
        
        # Сохраняем в кеш
        _set_cached(cache_key, result)
        
        return result

    except Exception as e:
        logger.error(f"stats error: {e}", exc_info=True)
        return None


# ========================
# 🔗 REGISTER
# ========================

def register_steam(telegram_id: int, identifier: str) -> dict:
    try:
        # Создаем пользователя если не существует
        from database import get_user
        user = get_user(telegram_id)
        if not user:
            return {"success": False, "message": "❌ Пользователь не найден. Сначала отправьте /start или /fissure"}
        
        steam_id = parse_steam_identifier(identifier)

        if steam_id:
            # если получилось получить steam_id → stats по ID
            stats = get_player_stats(steam_id)
            if not stats:
                return {"success": False, "message": "❌ Игрок не найден"}
        else:
            # иначе ищем по никнейму через OpenDota
            data = search_player(identifier)
            if not data:
                return {"success": False, "message": "❌ Игрок не найден"}
            steam_id = data["steam_id"]
            stats = data

        # сохраняем все поля одним запросом
        update_user_fields_batch(telegram_id, {
            "steam_id": steam_id,
            "steam_nickname": stats["nickname"],
            "mmr": stats["mmr"],
            "rank_tier": stats.get("rank_tier", 0),
            "wins": stats.get("wins", 0),
            "losses": stats.get("losses", 0),
            "week_start_date": datetime.now(timezone.utc).date().isoformat()
        })
        
        # Обновляем недельную статистику сразу после привязки
        update_user_mmr(telegram_id)

        # Формируем строку ранга
        rank_tier = stats.get("rank_tier", 0)
        rank_str = rank_to_string(rank_tier)
        wins = stats.get("wins", 0)
        losses = stats.get("losses", 0)
        total = wins + losses
        winrate = stats.get("winrate", 0)
        
        return {
            "success": True,
            "message": f"✅ {stats['nickname']} | {rank_str}\n📊 {total} игр | ✅ {wins} | ❌ {losses} | {winrate}%"
        }

    except Exception as e:
        logger.error(f"register error: {e}", exc_info=True)
        return {"success": False, "message": "❌ Ошибка"}


# ========================
# 🔄 UPDATE MMR
# ========================

def update_user_mmr(telegram_id: int) -> dict:
    try:
        user = get_user(telegram_id)
        if not user or not user.get("steam_id"):
            return {"success": False, "rank_up": None}

        logger.info(f"topmmr: calling get_player_stats for steam_id={user['steam_id']}")
        stats = get_player_stats(user["steam_id"], use_cache=False)
        logger.info(f"topmmr: get_player_stats returned: {stats}")
        if not stats:
            return {"success": False, "rank_up": None}

        # Получаем последние матчи для расчёта недельной статистики
        # Фиксированная неделя: с понедельника по воскресенье
        # Используем МСК (UTC+3) для расчёта начала недели
        MSK = timezone(timedelta(hours=3))
        today_msk = datetime.now(MSK)
        monday_msk = today_msk - timedelta(days=today_msk.weekday())
        week_start_msk = monday_msk.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start_utc = week_start_msk.astimezone(timezone.utc)
        logger.info(f"topmmr: week start (MSK) = {week_start_msk} (Monday)")
        logger.info(f"topmmr: week start (UTC) = {week_start_utc} (Monday)")
        
        # Получаем последние 50 матчей
        matches = get_recent_matches(user["steam_id"], limit=50)
        
        # Логируем все полученные матчи
        if matches:
            logger.info(f"topmmr: total matches received from API: {len(matches)}")
            for i, match in enumerate(matches):
                match_date = datetime.fromtimestamp(match.get("start_time", 0), tz=timezone.utc)
                in_week = match_date >= week_start_utc
                logger.info(f"topmmr: match[{i}] id={match.get('match_id')} start_time={match.get('start_time')} date={match_date} week_start={week_start_utc} in_week={in_week}")
                if in_week:
                    # Детальное логирование только для первых 3 матчей в неделе
                    if i < 3:
                        radiant_win = match.get("radiant_win", False)
                        player_is_radiant = match.get("radiant", True)
                        is_win = (player_is_radiant and radiant_win) or (not player_is_radiant and not radiant_win)
                        logger.info(f"topmmr:   -> radiant={player_is_radiant}, radiant_win={radiant_win}, is_win={is_win}")
        else:
            logger.warning("topmmr: no matches received from API")
        
        week_games = 0
        week_wins = 0
        current_streak = 0
        max_streak = 0
        week_current_streak = 0
        
        if matches:
            # Идём от старых к новым, чтобы current_streak в конце = текущий стрик
            for match in reversed(matches):
                try:
                    match_date = datetime.fromtimestamp(match.get("start_time", 0), tz=timezone.utc)
                    if match_date >= week_start_utc:
                        week_games += 1
                        
                        # Определяем победу используя player_slot и radiant_win
                        player_slot = match.get("player_slot")
                        radiant_win = match.get("radiant_win", False)
                        
                        # Логируем ВСЕ значения для отладки (первые 3 матча)
                        if week_games <= 3:
                            logger.info(f"topmmr: DEBUG match {match.get('match_id')} player_slot={player_slot} radiant_win={radiant_win}")
                        
                        # player_slot: 0-4 = Radiant, 128-132 = Dire
                        if player_slot is not None:
                            player_was_radiant = player_slot < 127
                        else:
                            player_was_radiant = True
                        
                        # Победа: игрок был на стороне победившей команды
                        if radiant_win and player_was_radiant:
                            is_win = True
                        elif not radiant_win and not player_was_radiant:
                            is_win = True
                        else:
                            is_win = False
                        
                        # Логируем только для отладки (можно убрать после проверки)
                        if week_games <= 3:
                            logger.info(f"topmmr: match {match.get('match_id')} - player_was_radiant={player_was_radiant}, is_win={is_win}")
                        if is_win:
                            week_wins += 1
                            current_streak += 1
                            week_current_streak = current_streak
                            if current_streak > max_streak:
                                max_streak = current_streak
                        else:
                            current_streak = 0
                            week_current_streak = 0
                except Exception:
                    pass
        
        logger.info(f"Week stats from matches for {telegram_id}: week_games={week_games}, week_wins={week_wins}, week_streak={max_streak}")
        
        # Проверяем смену недели - если неделя изменилась, сбрасываем статистику
        user_week_start = user.get('week_start_date')
        current_week_start = week_start_msk.strftime("%Y-%m-%d")
        
        if user_week_start and user_week_start != current_week_start:
            logger.info(f"Week changed for {telegram_id}: {user_week_start} -> {current_week_start}, resetting week stats")
            week_games = 0
            week_wins = 0
            max_streak = 0
        
        # Проверяем повышение ранга
        new_rank_tier = stats.get("rank_tier", 0)
        old_rank_tier = user.get("rank_tier", 0)
        rank_up = None
        if new_rank_tier > old_rank_tier:
            logger.info(f"Rank UP for {telegram_id}: {old_rank_tier} -> {new_rank_tier}")
            rank_up = {"old_rank": rank_to_string(old_rank_tier), "new_rank": rank_to_string(new_rank_tier)}
        
        # ВАЖНО: Всегда обновляем недельную статистику из матчей
        logger.info(f"Saved week stats to DB: {week_games} games, {week_wins} wins, week_streak={max_streak}, week_start={week_start_utc}")
        
        # Обновляем ВСЕ поля одним запросом
        update_user_fields_batch(telegram_id, {
            "week_games": week_games,
            "week_wins": week_wins,
            "week_best_streak": max_streak,
            "week_current_streak": week_current_streak,
            "week_start_date": current_week_start,
            "rank_tier": new_rank_tier,
            "wins": stats.get("wins", 0),
            "losses": stats.get("losses", 0),
            "mmr": stats["mmr"]
        })

        return {"success": True, "rank_up": rank_up}

    except Exception as e:
        logger.error(f"update error: {e}", exc_info=True)
        return {"success": False, "rank_up": None}


# ========================
# 🏆 TOP MMR (без API!)
# ========================

def get_mmr_top(limit=10):
    from database import get_dota_mmr_top
    return get_dota_mmr_top(limit)


def get_week_top(limit=10, force_refresh=False):
    from database import get_dota_week_top
    return get_dota_week_top(limit, force_refresh)


# ========================
# 🃏 START CARD (новый пользователь в боте)
# ========================

def generate_start_card(
    avatar_url: str = None,
    message_count: int = 0,
    username: str = None,
    steam_nickname: str = None,
    rank_tier: int = 0,
    weekly_mvp: int = 0,
    weekly_top2: int = 0,
    weekly_top3: int = 0
) -> bytes | None:
    """Сгенерировать карточку для /start существующего пользователя"""
    try:
        from PIL import Image, ImageDraw, ImageFont
        import io
        import requests as req
        import os

        # Компактный размер - увеличенный для Retina
        width = 1024
        height = 500
        scale = 1.8  # коэффициент масштабирования
        
        # Центрирование аватара по вертикали
        avatar_y = int((height - avatar_size) // 2 - 10)
        
        # Фон - градиент
        img = Image.new("RGB", (width, height), (15, 20, 35))
        draw = ImageDraw.Draw(img)
        
        for y in range(height):
            r = int(15 + (25 - 15) * (y / height))
            g = int(20 + (35 - 20) * (y / height))
            b = int(35 + (55 - 35) * (y / height))
            draw.line([(0, y), (width, y)], fill=(r, g, b))
        
        # Рамка - золотая как в профиле
        draw.rectangle([0, 0, width-1, height-1], outline=(215, 175, 85), width=2)
        
        # Аватарка - квадратная с обводкой
        avatar_size = int(130 * scale)
        avatar_x = int(20 * scale)
        
        if avatar_url:
            try:
                if os.path.isfile(avatar_url):
                    avatar = Image.open(avatar_url).convert("RGBA")
                else:
                    resp = requests.get(avatar_url, timeout=8)
                    avatar = Image.open(io.BytesIO(resp.content)).convert("RGBA") if resp.status_code == 200 else None
                if avatar:
                    # Resize and crop to square
                    w, h = avatar.size
                    side = min(w, h)
                    left = (w - side) // 2
                    top = (h - side) // 2
                    avatar = avatar.crop((left, top, left + side, top + side))
                    avatar = avatar.resize((avatar_size, avatar_size), Image.LANCZOS)
                    # Обводка - золотая
                    draw.rectangle([avatar_x, avatar_y, avatar_x + avatar_size, avatar_y + avatar_size], outline=(215, 175, 85), width=int(4*scale))
                    img.paste(avatar, (avatar_x, avatar_y))
            except Exception:
                pass
        
        if not avatar_url:
            draw.rectangle([avatar_x, avatar_y, avatar_x + avatar_size, avatar_y + avatar_size], fill=(40, 55, 80), outline=(215, 175, 85), width=int(4*scale))
            # Default icon placeholder
            draw.ellipse([avatar_x + int(45*scale), avatar_y + int(35*scale), avatar_x + int(95*scale), avatar_y + int(105*scale)], fill=(80, 100, 130))
        
# Шрифты - увеличенные для Retina
        try:
            font_title = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", int(36 * scale))
            font_text = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", int(32 * scale))
            font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", int(24 * scale))
        except Exception:
            font_title = font_text = font_small = ImageFont.load_default()
        
        # Иконки - открытые источники
        icon_size = int(32 * scale)
        
        icon_urls = {
            'msg': 'https://upload.wikimedia.org/wikipedia/commons/8/83/Telegram_icon_%282021%29.svg',
            'trophy': 'https://upload.wikimedia.org/wikipedia/commons/a/a2/Trophy_icon.svg',
        }
        
        icons = {}
        for name, url in icon_urls.items():
            try:
                resp = requests.get(url, timeout=4)
                if resp.status_code == 200:
                    ic = Image.open(io.BytesIO(resp.content)).convert("RGBA")
                    icons[name] = ic.resize((icon_size, icon_size), Image.LANCZOS)
            except Exception:
                pass
        
        # Генерируем медали программно (прозрачные PNG с цифрами)
        def create_medal_image(number, color, text_color):
            img = Image.new("RGBA", (icon_size, icon_size), (0, 0, 0, 0))
            draw = ImageDraw.Draw(img)
            draw.ellipse([4, 4, icon_size-4, icon_size-4], fill=color)
            try:
                font_medal = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 20)
            except Exception:
                font_medal = ImageFont.load_default()
            bbox = draw.textbbox((0, 0), str(number), font=font_medal)
            text_width = bbox[2] - bbox[0]
            text_height = bbox[3] - bbox[1]
            x = (icon_size - text_width) // 2
            y = (icon_size - text_height) // 2 - 2
            draw.text((x, y), str(number), fill=text_color, font=font_medal)
            return img
        
        icons['gold'] = create_medal_image(1, (255, 215, 0, 255), (184, 134, 11, 255))
        icons['silver'] = create_medal_image(2, (192, 192, 192, 255), (128, 128, 128, 255))
        icons['bronze'] = create_medal_image(3, (205, 127, 50, 255), (139, 69, 19, 255))
        
        # Dota 2 rank icon - прямые ссылки с gamepedia.cursecdn.com (работают)
        rank_icon = None
        rank_icon_size = int(80 * scale)  # увеличен в 2 раза
        if rank_tier > 0:
            tier = rank_tier // 10  # 1-7
            star = rank_tier % 10   # 1-5 stars within tier
            if star == 0:
                star = 5
            
            # Прямые рабочие ссылки на иконки рангов
            rank_urls = {
                (1, 1): "https://gamepedia.cursecdn.com/dota2_gamepedia/thumb/8/85/SeasonalRank1-1.png/140px-SeasonalRank1-1.png?version=ce7c6eea36971495cdad1f06e7ef3709",
                (1, 2): "https://gamepedia.cursecdn.com/dota2_gamepedia/thumb/e/ee/SeasonalRank1-2.png/140px-SeasonalRank1-2.png?version=094dc352040053ea02f1bbb82a4591f1",
                (1, 3): "https://gamepedia.cursecdn.com/dota2_gamepedia/thumb/0/05/SeasonalRank1-3.png/140px-SeasonalRank1-3.png?version=529b1f8ac23899b14bb30b03036d277e",
                (1, 4): "https://gamepedia.cursecdn.com/dota2_gamepedia/thumb/6/6d/SeasonalRank1-4.png/140px-SeasonalRank1-4.png?version=e5fa236efcfc108987fac807d890771d",
                (1, 5): "https://gamepedia.cursecdn.com/dota2_gamepedia/thumb/2/2b/SeasonalRank1-5.png/140px-SeasonalRank1-5.png?version=c33004c635c667fa661fad0e2593869e",
                
                (2, 1): "https://gamepedia.cursecdn.com/dota2_gamepedia/thumb/c/c7/SeasonalRank2-1.png/140px-SeasonalRank2-1.png?version=832ba8a7042450ebf2cee3209e2cfac8",
                (2, 2): "https://gamepedia.cursecdn.com/dota2_gamepedia/thumb/2/2c/SeasonalRank2-2.png/140px-SeasonalRank2-2.png?version=be558245d8ddcb6479204bd99ca177cc9",
                (2, 3): "https://gamepedia.cursecdn.com/dota2_gamepedia/thumb/f/f5/SeasonalRank2-3.png/140px-SeasonalRank2-3.png?version=38233a7123c0b90df8872a6b9a04a87c",
                (2, 4): "https://gamepedia.cursecdn.com/dota2_gamepedia/thumb/b/b4/SeasonalRank2-4.png/140px-SeasonalRank2-4.png?version=879bc97952e7acbbb4cb76df1618757a",
                (2, 5): "https://gamepedia.cursecdn.com/dota2_gamepedia/thumb/3/32/SeasonalRank2-5.png/140px-SeasonalRank2-5.png?version=5b99be61ba7db96bfdc03a9fef6f1fb4",
                
                (3, 1): "https://gamepedia.cursecdn.com/dota2_gamepedia/thumb/8/82/SeasonalRank3-1.png/140px-SeasonalRank3-1.png?version=b9a19f0189fe0236ee00fb94cc97a693",
                (3, 2): "https://gamepedia.cursecdn.com/dota2_gamepedia/thumb/6/6e/SeasonalRank3-2.png/140px-SeasonalRank3-2.png?version=8e03bbb7be665bcadcb0913eaecee2c0",
                (3, 3): "https://gamepedia.cursecdn.com/dota2_gamepedia/thumb/6/67/SeasonalRank3-3.png/140px-SeasonalRank3-3.png?version=59df65f46dbfc05c7dcb5d877aa2f37c",
                (3, 4): "https://gamepedia.cursecdn.com/dota2_gamepedia/thumb/8/87/SeasonalRank3-4.png/140px-SeasonalRank3-4.png?version=8582a808c060a4df95385c98844e666b",
                (3, 5): "https://gamepedia.cursecdn.com/dota2_gamepedia/thumb/b/b1/SeasonalRank3-5.png/140px-SeasonalRank3-5.png?version=4f0db8503ae24ddd488374b6e5968daf",
                
                (4, 1): "https://gamepedia.cursecdn.com/dota2_gamepedia/thumb/7/76/SeasonalRank4-1.png/140px-SeasonalRank4-1.png?version=7a9db7f22e02de4a58923f40da38b9db",
                (4, 2): "https://gamepedia.cursecdn.com/dota2_gamepedia/thumb/8/87/SeasonalRank4-2.png/140px-SeasonalRank4-2.png?version=358a9043ef264bcb2ea3424339ac671a",
                (4, 3): "https://gamepedia.cursecdn.com/dota2_gamepedia/thumb/6/60/SeasonalRank4-3.png/140px-SeasonalRank4-3.png?version=3e5c81e69f244b6028ef27beb0fc3ec6",
                (4, 4): "https://gamepedia.cursecdn.com/dota2_gamepedia/thumb/4/4a/SeasonalRank4-4.png/140px-SeasonalRank4-4.png?version=aacf3fb098fb8de1c514d73b7a0f63c7",
                (4, 5): "https://gamepedia.cursecdn.com/dota2_gamepedia/thumb/a/a3/SeasonalRank4-5.png/140px-SeasonalRank4-5.png?version=7b207bd7de3fe423117f6ea7331dfc88",
                
                (5, 1): "https://gamepedia.cursecdn.com/dota2_gamepedia/thumb/7/79/SeasonalRank5-1.png/140px-SeasonalRank5-1.png?version=7742371d2571ee59b59c6ac14e5688fa",
                (5, 2): "https://gamepedia.cursecdn.com/dota2_gamepedia/thumb/5/52/SeasonalRank5-2.png/140px-SeasonalRank5-2.png?version=204da548015c1947ce514c8ac81c99ea",
                (5, 3): "https://gamepedia.cursecdn.com/dota2_gamepedia/thumb/8/88/SeasonalRank5-3.png/140px-SeasonalRank5-3.png?version=990f1323b00256eb84002ab050b9188b",
                (5, 4): "https://gamepedia.cursecdn.com/dota2_gamepedia/thumb/2/25/SeasonalRank5-4.png/140px-SeasonalRank5-4.png?version=0248fc56651cc810ddceca901386322a",
                (5, 5): "https://gamepedia.cursecdn.com/dota2_gamepedia/thumb/8/8e/SeasonalRank5-5.png/140px-SeasonalRank5-5.png?version=14dc5ce669daf93b178350a0b3ee27e1",
                
                (6, 1): "https://gamepedia.cursecdn.com/dota2_gamepedia/thumb/e/e0/SeasonalRank6-1.png/140px-SeasonalRank6-1.png?version=56f4415e7d8fc83168c03f374e7babbc",
                (6, 2): "https://gamepedia.cursecdn.com/dota2_gamepedia/thumb/1/1c/SeasonalRank6-2.png/140px-SeasonalRank6-2.png?version=87515796db90be81886c62cad9faf87f",
                (6, 3): "https://gamepedia.cursecdn.com/dota2_gamepedia/thumb/d/da/SeasonalRank6-3.png/140px-SeasonalRank6-3.png?version=190512e1572f037b0936f8b1a4bb55b6",
                (6, 4): "https://gamepedia.cursecdn.com/dota2_gamepedia/thumb/d/db/SeasonalRank6-4.png/140px-SeasonalRank6-4.png?version=aba16fcff849cb2495f1ddc25bfefd74",
                (6, 5): "https://gamepedia.cursecdn.com/dota2_gamepedia/thumb/4/47/SeasonalRank6-5.png/140px-SeasonalRank6-5.png?version=1ae82223757486aa55461a82fa09ac6a",
                
                (7, 1): "https://gamepedia.cursecdn.com/dota2_gamepedia/thumb/b/b7/SeasonalRank7-1.png/140px-SeasonalRank7-1.png?version=8cd74e57b63ceb730d7b36a8f6589b9f",
                (7, 2): "https://gamepedia.cursecdn.com/dota2_gamepedia/thumb/8/8f/SeasonalRank7-2.png/140px-SeasonalRank7-2.png?version=59d74d77a554732a99debd54d1b1b641",
                (7, 3): "https://gamepedia.cursecdn.com/dota2_gamepedia/thumb/f/fd/SeasonalRank7-3.png/140px-SeasonalRank7-3.png?version=12f7e65e8c858b1d39e2a4a17bc85522",
                (7, 4): "https://gamepedia.cursecdn.com/dota2_gamepedia/thumb/1/13/SeasonalRank7-4.png/140px-SeasonalRank7-4.png?version=247aba452307e17cd6f647321450b8a5",
                (7, 5): "https://gamepedia.cursecdn.com/dota2_gamepedia/thumb/3/33/SeasonalRank7-5.png/140px-SeasonalRank7-5.png?version=0db40597d94b70e3619c2a3e80317e94",
            }
            
            rank_url = rank_urls.get((tier, star))
            if rank_url:
                try:
                    resp = requests.get(rank_url, timeout=4)
                    if resp.status_code == 200:
                        rank_icon = Image.open(io.BytesIO(resp.content)).convert("RGBA")
                        rank_icon = rank_icon.resize((rank_icon_size, rank_icon_size), Image.LANCZOS)
                except:
                    pass
        
        # Основной блок справа от аватара
        info_x = avatar_x + avatar_size + int(25 * scale)
        info_y = int(75 * scale)
        
        # Messages - только число, сдвинуто вправо
        draw.text((info_x + int(200 * scale), info_y + 4), f"{message_count}", fill=(255, 255, 255), font=font_text)
        
        # Ранг - иконка ранга (увеличена в 2 раза) + никнейм Steam
        rank_y = info_y + int(80 * scale)
        if rank_icon:
            img.paste(rank_icon, (info_x, rank_y - 10), rank_icon)
        # Показываем steam_nickname рядом с рангом
        if steam_nickname:
            draw.text((info_x + int(100 * scale), rank_y + 10), f"{steam_nickname}", fill=(100, 160, 240), font=font_title)
        
        # Медали - только числа (надписи будут на фоне)
        rewards_y = rank_y + int(80 * scale)
        medal_y = rewards_y + int(60 * scale)
        medal_spacing = int(140 * scale)
        
        draw.text((info_x, medal_y + 8), f"{weekly_mvp}", fill=(255, 215, 0), font=font_title)
        draw.text((info_x + medal_spacing, medal_y + 8), f"{weekly_top2}", fill=(200, 200, 210), font=font_title)
        draw.text((info_x + medal_spacing * 2, medal_y + 8), f"{weekly_top3}", fill=(205, 127, 50), font=font_title)
        
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=90)
        buf.seek(0)
        return buf.read()
        
    except Exception as e:
        import logging
        logging.exception("generate_start_card error")
        return None

