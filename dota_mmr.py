import asyncio
import functools
import io
import logging
import re
import time
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import aiohttp
import requests
from PIL import Image

from database import get_user, update_user_fields_batch

# Hero list cache
_heroes_cache = None
_heroes_cache_time = 0
_HEROES_CACHE_TTL = 86400  # 24 hours

# Heroes image cache
_heroes_image_cache = {}
_heroes_image_cache_ttl = 86400  # 24 hours

async def get_hero_list():
    """Get list of heroes from OpenDota API with caching."""
    global _heroes_cache, _heroes_cache_time
    if _heroes_cache is not None and time.time() - _heroes_cache_time < _HEROES_CACHE_TTL:
        return _heroes_cache
    try:
        from database import get_aiohttp_session
        session = await get_aiohttp_session()
        async with session.get("https://api.opendota.com/api/heroes", timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status == 200:
                data = await resp.json()
                if data:
                    _heroes_cache = data
                    _heroes_cache_time = time.time()
                    return data
    except Exception as e:
        logger.warning(f"Failed to fetch heroes: {e}")
    return []

# Cached background for start card to avoid repeated downloads
_START_CARD_BACKGROUND_RESIZED = None
_START_CARD_BACKGROUND_CACHED = False

def _get_start_card_background():
    global _START_CARD_BACKGROUND_RESIZED, _START_CARD_BACKGROUND_CACHED
    if _START_CARD_BACKGROUND_CACHED:
        return _START_CARD_BACKGROUND_RESIZED
    try:
        resp = requests.get("https://i.ibb.co/ZzWpzWN0/photo-2026-04-18-22-24-21.png", timeout=30)
        if resp.status_code == 200:
            bg_image = Image.open(io.BytesIO(resp.content)).convert("RGB")
            bg_image = bg_image.resize((1024, 500), Image.LANCZOS)
            _START_CARD_BACKGROUND_RESIZED = bg_image
            _START_CARD_BACKGROUND_CACHED = True
            return bg_image
    except Exception as e:
        logger.error(f"Failed to load start card background: {e}")
    return None

logger = logging.getLogger(__name__)

OPENDOTA_API_URL = "https://api.opendota.com/api"
STEAM_OFFSET = 76561197960265728

# Rate limiting для OpenDota API
_api_rate_limit = {"last_request": 0, "requests_count": 0, "window_start": 0}
API_RATE_LIMIT = 20  # максимум запросов в минуту (OpenDota允许30/мин)
API_RATE_WINDOW = 60  # окно в секундах
API_MIN_INTERVAL = 3  # минимум 3 секунды между запросами

# Глобальное состояние rate limit для сообщений об ошибках
_opendota_rate_limited_until = 0  # Unix timestamp, пока API недоступен

# Circuit Breaker для защиты от длительной недоступности
_circuit_breaker = {
    "state": "CLOSED",  # CLOSED, OPEN, HALF_OPEN
    "failure_count": 0,
    "last_failure_time": 0,
    "failure_threshold": 3,  # Быстрее реагируем
    "recovery_timeout": 60,    # 1 минута до попытки восстановления
}

def reset_circuit_breaker():
    """Принудительно сбросить circuit breaker (для отладки/восстановления)"""
    _circuit_breaker["state"] = "CLOSED"
    _circuit_breaker["failure_count"] = 0
    _circuit_breaker["last_failure_time"] = 0
    logger.info("Circuit breaker manually reset to CLOSED")


# Background retry task
_retry_task = None

def start_background_retry(max_retries=3, retry_interval=30):
    """Start background task for circuit breaker recovery."""
    global _retry_task
    
    def retry_loop():
        while True:
            time.sleep(retry_interval)
            if _circuit_breaker["state"] == "OPEN":
                now = time.time()
                if now - _circuit_breaker.get("last_failure_time", 0) > _circuit_breaker["recovery_timeout"]:
                    logger.info("Background retry: attempting circuit breaker recovery")
                    _circuit_breaker["state"] = "HALF_OPEN"
    
    if _retry_task is None:
        _retry_task = threading.Thread(target=retry_loop, daemon=True)
        _retry_task.start()
        logger.info("Background retry task started")

def _circuit_breaker_can_execute() -> bool:
    """Проверить можно ли выполнять запрос (Circuit Breaker pattern)"""
    cb = _circuit_breaker
    now = time.time()

    if cb["state"] == "CLOSED":
        return True

    if cb["state"] == "OPEN":
        # Проверяем таймаут восстановления
        if now - cb["last_failure_time"] > cb["recovery_timeout"]:
            cb["state"] = "HALF_OPEN"
            logger.info("Circuit breaker: HALF_OPEN - attempting recovery")
            return True
        logger.warning(f"Circuit breaker OPEN, waiting {cb['recovery_timeout'] - (now - cb['last_failure_time']):.0f}s")
        return False

    if cb["state"] == "HALF_OPEN":
        return True
    
    # Unknown state, treat as closed for safety
    return False

def _circuit_breaker_record_success():
    """Записать успешный запрос"""
    cb = _circuit_breaker
    if cb["state"] == "HALF_OPEN":
        cb["state"] = "CLOSED"
        logger.info("Circuit breaker: CLOSED - recovery successful")
    cb["failure_count"] = 0

def _circuit_breaker_record_failure():
    """Записать неудачный запрос"""
    cb = _circuit_breaker
    cb["failure_count"] += 1

    if cb["state"] == "CLOSED":
        if cb["failure_count"] >= cb["failure_threshold"]:
            cb["state"] = "OPEN"
            cb["last_failure_time"] = time.time()
            logger.warning(f"Circuit breaker: OPEN - too many failures ({cb['failure_count']})")
    elif cb["state"] == "HALF_OPEN":
        # Failure in half-open state -> immediately open again
        cb["state"] = "OPEN"
        cb["last_failure_time"] = time.time()
        logger.warning("Circuit breaker: OPEN - failure in half-open state")
    # If already OPEN, do nothing - keep the original open time for timeout calculation

# Простой кеш для запросов (5 минут)
_cache = {}
CACHE_TTL = 300  # 5 минут
CACHE_MAX_SIZE = 100  # максимальное количество записей в кеше

# Кеш матчей пользователей (30 минут - экономим API)
_user_matches_cache = {}
USER_MATCHES_CACHE_TTL = 1800  # 30 минут




def is_opendota_rate_limited():
    """Проверить, находится ли OpenDota API в состоянии rate limit"""
    global _opendota_rate_limited_until
    return time.time() < _opendota_rate_limited_until

def get_opendota_rate_limit_time_remaining():
    """Получить оставшееся время до восстановления API в секундах"""
    global _opendota_rate_limited_until
    remaining = _opendota_rate_limited_until - time.time()
    return max(0, int(remaining))

def get_opendota_rate_limit_message():
    """Получить сообщение об ошибке"""
    return "⚠️ OpenDota API временно недоступен. Вернётся, когда кто-то купит варды 👁️"

def set_opendota_rate_limited(wait_seconds=60):
    """Установить время до которого OpenDota API недоступен"""
    global _opendota_rate_limited_until
    _opendota_rate_limited_until = time.time() + wait_seconds

def _check_rate_limit():
    """Проверить и обновить rate limiting (sync версия)"""
    now = time.time()

    if now - _api_rate_limit["window_start"] >= API_RATE_WINDOW:
        _api_rate_limit["window_start"] = now
        _api_rate_limit["requests_count"] = 0

    if _api_rate_limit["requests_count"] >= API_RATE_LIMIT:
        wait_time = API_RATE_WINDOW - (now - _api_rate_limit["window_start"])
        if wait_time > 0:
            raise RateLimitWaitError(wait_time)

    time_since_last = now - _api_rate_limit["last_request"]
    if time_since_last < API_MIN_INTERVAL:
        raise RateLimitWaitError(API_MIN_INTERVAL - time_since_last)

    _api_rate_limit["requests_count"] += 1
    _api_rate_limit["last_request"] = now


class RateLimitWaitError(Exception):
    def __init__(self, wait_seconds: float):
        self.wait_seconds = wait_seconds
        super().__init__(f"Rate limit wait: {wait_seconds}s")


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


def _api_get(url: str, params: dict = None, max_retries: int = 2, timeout: int = 8) -> dict:
    """Универсальная функция для API-запросов с обработкой ошибок, кешем и повторными попытками"""
    cached = _get_cached(url)
    if cached is not None:
        return cached
    
    if not _circuit_breaker_can_execute():
        logger.warning("Circuit breaker: skipping request, API unavailable")
        return None
    
    if is_opendota_rate_limited():
        remaining = get_opendota_rate_limit_time_remaining()
        logger.warning(f"OpenDota still rate limited, waiting {remaining}s...")
        time.sleep(remaining + 1)
    
    try:
        _check_rate_limit()
    except RateLimitWaitError as e:
        logger.warning(f"Rate limited, waiting {e.wait_seconds:.1f}s...")
        time.sleep(e.wait_seconds)
        _api_rate_limit["window_start"] = time.time()
        _api_rate_limit["requests_count"] = 0

    for attempt in range(max_retries + 1):
        current_timeout = timeout if attempt == 0 else timeout + 5
        try:
            r = requests.get(url, params=params or {}, timeout=current_timeout)
            if r.status_code == 200:
                _circuit_breaker_record_success()
                # Record OpenDota token usage
                try:
                    from analytics_dashboard import record_opendota_tokens
                    record_opendota_tokens(1)
                except Exception:
                    pass
                return r.json()
            elif r.status_code == 429:
                wait_time = 5 * (attempt + 1)
                logger.warning(f"Rate limited by OpenDota API, waiting {wait_time}s...")
                set_opendota_rate_limited(60)
                _circuit_breaker_record_failure()
                time.sleep(wait_time)
                if attempt < max_retries:
                    continue
                return None
            elif r.status_code >= 500:
                _circuit_breaker_record_failure()
                if attempt < max_retries:
                    logger.warning(f"Server error {r.status_code}, retrying in {attempt + 1}s...")
                    time.sleep(attempt + 1)
                    continue
                return None
            elif r.status_code >= 400:
                if r.status_code == 403:
                    _circuit_breaker_record_failure()
                    logger.warning(f"OpenDota API returned 403 Forbidden - possible API key issue or ban")
                else:
                    logger.error(f"API error {r.status_code} for URL: {url}")
                return None
            return None
        except requests.exceptions.ReadTimeout as e:
            if attempt < max_retries:
                logger.warning(f"API request timeout ({current_timeout}s), retrying... ({attempt + 1}/{max_retries + 1})")
                continue
            else:
                logger.error(f"API request timeout ({current_timeout}s) after {max_retries + 1} attempts: {e}")
                return None
        except Exception as e:
            logger.error(f"API request error: {e}", exc_info=True)
            return None

    return None


_async_rate_limit = {"last_request": 0, "requests_count": 0, "window_start": 0}

async def _check_rate_limit_async():
    """Async версия rate limiting"""
    now = time.time()

    if now - _async_rate_limit["window_start"] >= API_RATE_WINDOW:
        _async_rate_limit["window_start"] = now
        _async_rate_limit["requests_count"] = 0

    if _async_rate_limit["requests_count"] >= API_RATE_LIMIT:
        wait_time = API_RATE_WINDOW - (now - _async_rate_limit["window_start"])
        if wait_time > 0:
            await asyncio.sleep(wait_time)
            # Don't reset window here - let it continue naturally after sleep

    time_since_last = now - _async_rate_limit["last_request"]
    if time_since_last < API_MIN_INTERVAL:
        await asyncio.sleep(API_MIN_INTERVAL - time_since_last)

    _async_rate_limit["requests_count"] += 1
    _async_rate_limit["last_request"] = now


async def _api_get_async(url: str, params: dict = None, use_session: bool = True, timeout: int = 15, max_retries: int = 3) -> dict:
    """Асинхронная функция для API-запросов с переиспользованием сессии, retry и rate limiting"""
    if not _circuit_breaker_can_execute():
        logger.warning("Circuit breaker: skipping async request, API unavailable")
        return None
    
    if is_opendota_rate_limited():
        remaining = get_opendota_rate_limit_time_remaining()
        logger.warning(f"OpenDota still rate limited, waiting {remaining}s...")
        await asyncio.sleep(remaining + 1)
    
    await _check_rate_limit_async()

    for attempt in range(max_retries):
        try:
            from database import get_aiohttp_session
            session = await get_aiohttp_session()
            async with session.get(url, params=params or {}, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
                if resp.status == 200:
                    _circuit_breaker_record_success()
                    return await resp.json()
                elif resp.status == 429:
                    logger.warning("Rate limited by OpenDota API, waiting...")
                    set_opendota_rate_limited(60)
                    _circuit_breaker_record_failure()
                    wait_time = 3 * (attempt + 1)
                    await asyncio.sleep(wait_time)
                    continue
                elif resp.status >= 500:
                    logger.warning(f"Server error {resp.status} for {url[:60]}, attempt {attempt + 1}/{max_retries}")
                    _circuit_breaker_record_failure()
                    await asyncio.sleep(1 + attempt)
                    continue
                else:
                    logger.error(f"API error {resp.status} for {url[:80]}")
                    _circuit_breaker_record_failure()
                    return None
        except TimeoutError:
            logger.warning(f"API request timeout for {url[:80]}, attempt {attempt + 1}/{max_retries}")
            _circuit_breaker_record_failure()
            if attempt < max_retries - 1:
                await asyncio.sleep(1 + attempt)
                continue
            return None
        except Exception as e:
            logger.error(f"Async API request error: {e}", exc_info=True)
            _circuit_breaker_record_failure()
            if attempt < max_retries - 1:
                await asyncio.sleep(1 + attempt)
                continue
            return None

    logger.error(f"Async API request failed after {max_retries} retries: {url[:80]}")
    return None


# ========================
# 🎮 MATCHES
# ========================

# ========================
# 🦸 HEROES
# ========================

HERO_IMAGE_BASE = "https://cdn.cloudflare.steamstatic.com/apps/dota2/images/dota_react/heroes"

HERO_CACHE_DIR = Path(__file__).parent / "hero_cache" / "portraits"
HERO_CACHE_DIR.mkdir(parents=True, exist_ok=True)
HERO_ICON_BASE = "https://cdn.cloudflare.steamstatic.com/apps/dota2/images/dota_react/heroes/icons"
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
        resp = requests.get(url, timeout=3)
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


async def get_cached_hero_portrait(hero_short_name: str) -> Image.Image | None:
    """Async load hero portrait with disk cache."""
    if not hero_short_name:
        return None

    cache_file = HERO_CACHE_DIR / f"{hero_short_name}.png"

    # Load from cache
    if cache_file.exists():
        try:
            return Image.open(cache_file).convert("RGBA")
        except Exception:
            logger.exception("Failed to load cached hero portrait")

    # Download and cache
    url = f"{HERO_IMAGE_BASE}/{hero_short_name}.png"
    try:
        from database import get_aiohttp_session
        session = await get_aiohttp_session()
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
            if resp.status != 200:
                return None
            data = await resp.read()

        # Save to cache
        try:
            cache_file.write_bytes(data)
        except Exception:
            logger.exception("Failed to save hero portrait to cache")

        # Return PIL image
        return Image.open(io.BytesIO(data)).convert("RGBA")

    except Exception:
        logger.exception("Failed to download hero portrait")
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
    import io

    from PIL import Image

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
        import io

        from PIL import Image, ImageDraw, ImageFont

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


def generate_heroes_image(top_heroes: list) -> bytes | None:
    """Сгенерировать картинку с иконками топ-героев: центральный крупнее, к краям меньше."""
    global _heroes_image_cache

    try:
        cache_key = ",".join(str(h.get("id", "")) for h in sorted(top_heroes, key=lambda x: x.get("id", "")))
        if cache_key in _heroes_image_cache:
            cached_data, cached_time = _heroes_image_cache[cache_key]
            if time.time() - cached_time < _heroes_image_cache_ttl:
                return cached_data

        from PIL import Image, ImageDraw

        if not top_heroes:
            logger.warning("generate_heroes_image: top_heroes is empty")
            return None

        # Limit number of heroes to prevent memory issues
        if len(top_heroes) > 10:
            logger.info(f"Limiting heroes from {len(top_heroes)} to 10")
            top_heroes = top_heroes[:10]

        logger.info(f"generate_heroes_image: generating for {len(top_heroes)} heroes")
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

        for sh in hero_short_names:
            if sh:
                data = get_hero_portrait_cached(sh) or get_hero_icon_cached(sh)
                if data:
                    icon_data_map[sh] = data

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
                    icon = icon.resize((icon_size, icon_size), Image.LANCZOS)
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


@functools.lru_cache(maxsize=256)
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

    except Exception:
        logger.error("search error", exc_info=True)
        return None


# ========================
# 🎮 MATCHES
# ========================

def get_recent_matches(steam_id: int, limit: int = 5) -> list:
    """Получить последние матчи игрока"""
    if steam_id in _user_matches_cache:
        cached_data, cached_time = _user_matches_cache[steam_id]
        if time.time() - cached_time < USER_MATCHES_CACHE_TTL:
            return cached_data
    
    try:
        account_id = steam64_to_account_id(steam_id)
        url = f"{OPENDOTA_API_URL}/players/{account_id}/matches"
        
        # Keep trying until we get matches (up to 60s to handle rate limits)
        start_time = time.time()
        max_wait = 60
        matches = None
        while matches is None and (time.time() - start_time) < max_wait:
            matches = _api_get(url, {"limit": limit, "sort": "-start_time"}, max_retries=2)
            if matches is None:
                time.sleep(10)
        
        matches = matches or []
        
        _user_matches_cache[steam_id] = (matches, time.time())
        
        return matches
    except Exception as e:
        logger.error(f"get_recent_matches error: {e}", exc_info=True)
        return []


async def get_recent_matches_async(steam_id: int, limit: int = 5) -> list:
    """Асинхронно получить последние матчи игрока"""
    if steam_id is None:
        return []
    
    if steam_id in _user_matches_cache:
        cached_data, cached_time = _user_matches_cache[steam_id]
        if time.time() - cached_time < USER_MATCHES_CACHE_TTL:
            return cached_data
    
    try:
        account_id = steam64_to_account_id(steam_id)
        url = f"{OPENDOTA_API_URL}/players/{account_id}/matches"
        
        start_time = time.time()
        max_wait = 60
        matches = None
        while matches is None and (time.time() - start_time) < max_wait:
            matches = await _api_get_async(url, {"limit": limit, "sort": "-start_time"})
            if matches is None:
                await asyncio.sleep(10)
        
        matches = matches or []
        
        _user_matches_cache[steam_id] = (matches, time.time())
        
        return matches
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

def get_player_stats(steam_id: int, use_cache: bool = True, timeout: int = 8) -> dict:
    try:
        # Проверяем кеш
        cache_key = f"player_{steam_id}"
        if use_cache:
            cached = _get_cached(cache_key)
            if cached:
                # Возвращаем кешированные данные мгновенно
                return cached

        account_id = steam64_to_account_id(steam_id)

        # Получаем основную информацию об игроке
        player_data = _api_get(f"{OPENDOTA_API_URL}/players/{account_id}", timeout=timeout)
        if not player_data:
            logger.warning(f"Player data not found for account_id: {account_id}")
            logger.warning(f"API URL used: {OPENDOTA_API_URL}/players/{account_id}")
            # Возвращаем кешированные данные если есть, даже если API недоступен
            if use_cache:
                cached = _get_cached(cache_key)
                if cached:
                    logger.info(f"Returning cached stats for {steam_id} due to API failure")
                    return cached
            return None

        profile = player_data.get("profile", {})
        rank_tier = player_data.get("rank_tier") or 0

        # Получаем статистику побед/поражений
        wl_data = _api_get(f"{OPENDOTA_API_URL}/players/{account_id}/wl", timeout=timeout)
        if wl_data:
            wins = wl_data.get("win", 0)
            losses = wl_data.get("lose", 0)
            total_games = wins + losses
        else:
            logger.warning(f"Win/Loss data not found for account_id: {account_id}")
            # Пытаемся получить винрейт из кеша если API недоступен
            if use_cache:
                cached = _get_cached(cache_key)
                if cached:
                    logger.info(f"Using cached win/loss data for {steam_id} due to API failure")
                    wins = cached.get("wins", 0)
                    losses = cached.get("losses", 0)
                    total_games = wins + losses
                else:
                    total_games = 0
                    wins = 0
                    losses = 0
            else:
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
        # При любой ошибке возвращаем кешированные данные если есть
        if use_cache:
            cached = _get_cached(cache_key)
            if cached:
                logger.info(f"Returning cached stats for {steam_id} due to exception: {e}")
                return cached
        return None


# ========================
# 🔗 REGISTER
# ========================

def register_steam(telegram_id: int, identifier: str) -> dict:
    try:
        logger.info(f"Registering Steam for user {telegram_id} with identifier: {identifier}")

        # Создаем пользователя если не существует
        from database import get_user, _save_user_to_db_immediately, user_cache
        user = get_user(telegram_id)
        if not user:
            logger.info(f"User not found in register_steam, creating new user: {telegram_id}")
            from database import Database
            Database().add_user(telegram_id, "", "", "")
            user = get_user(telegram_id)
            if user:
                user_cache.set(telegram_id, user)
                _save_user_to_db_immediately(telegram_id, user)

        steam_id = parse_steam_identifier(identifier)
        logger.info(f"Parsed steam_id: {steam_id}")

        if steam_id:
            # если получилось получить steam_id → stats по ID
            logger.info(f"Getting player stats for steam_id: {steam_id}")
            account_id = steam64_to_account_id(steam_id)
            logger.info(f"Using account_id: {account_id} for API call")

            stats = get_player_stats(steam_id)
            logger.info(f"Player stats result: {stats is not None}")

            if not stats:
                # Try to verify SteamID exists via Steam API or allow placeholder linking
                # This handles cases where profile is private but SteamID is valid
                try:
                    from database import get_user_by_steam_id
                    existing_user = get_user_by_steam_id(steam_id)
                    if existing_user and existing_user.get('telegram_id') == telegram_id:
                        return {"success": True, "message": "✅ Аккаунт уже привязан к вам"}
                    if existing_user:
                        return {"success": False, "message": "❌ Этот Steam аккаунт уже привязан к другому пользователю"}
                except Exception:
                    pass

                # Allow linking with placeholder data - stats will be fetched when profile becomes public
                stats = {
                    "nickname": "Неизвестный игрок",
                    "avatar": None,
                    "mmr": 0,
                    "rank_tier": 0,
                    "wins": 0,
                    "losses": 0,
                    "winrate": 0.0
                }
                update_user_fields_batch(telegram_id, {
                    "steam_id": steam_id,
                    "steam_nickname": "Неизвестный игрок",
                    "mmr": 0,
                    "rank_tier": 0,
                    "wins": 0,
                    "losses": 0,
                    "week_start_date": datetime.now(UTC).date().isoformat()
                })
                return {"success": True, "message": "✅ Аккаунт привязан! Статистика будет доступна, когда профиль станет публичным (Steam → Settings → Privacy → Game Details → Public)"}
        else:
            # иначе ищем по никнейму через OpenDota
            logger.info(f"Searching player by nickname: {identifier}")
            data = search_player(identifier)
            logger.info(f"Search result: {data is not None}")
            if not data:
                return {"success": False, "message": "❌ Игрок с таким ником не найден\n\n💡 Попробуйте:\n• Использовать Steam ID вместо ника\n• Проверить правильность написания\n• Убедиться, что игрок играет в Dota 2"}
            steam_id = data["steam_id"]
            stats = data

        # Проверяем, не привязан ли уже этот steam_id к другому аккаунту
        from database import get_user_by_steam_id
        existing_user = get_user_by_steam_id(steam_id)
        if existing_user and existing_user.get('telegram_id') != telegram_id:
            existing_username = existing_user.get('username') or existing_user.get('steam_nickname') or 'другой игрок'
            return {"success": False, "message": f"❌ Этот Steam аккаунт уже привязан к {existing_username}"}

        # сохраняем все поля одним запросом
        update_user_fields_batch(telegram_id, {
            "steam_id": steam_id,
            "steam_nickname": stats["nickname"],
            "avatar": stats.get("avatar"),
            "mmr": stats["mmr"],
            "rank_tier": stats.get("rank_tier", 0),
            "wins": stats.get("wins", 0),
            "losses": stats.get("losses", 0),
            "week_start_date": datetime.now(UTC).date().isoformat()
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

def update_user_mmr(telegram_id: int, update_top_cache: bool = True) -> dict:
    # Force reset all API state to ensure we attempt API calls
    global _circuit_breaker, _api_rate_limit, _opendota_rate_limited_until
    if _circuit_breaker["state"] != "CLOSED":
        logger.info(f"update_user_mmr: resetting circuit breaker from {_circuit_breaker['state']}")
        _circuit_breaker = {
            "state": "CLOSED",
            "failure_count": 0,
            "last_failure_time": 0,
            "failure_threshold": 5,
            "recovery_timeout": 120,
        }
    # Also reset rate limit state
    _api_rate_limit = {"last_request": 0, "requests_count": 0, "window_start": 0}
    _opendota_rate_limited_until = 0
    try:
        user = get_user(telegram_id)
        if not user or not user.get("steam_id"):
            return {"success": False, "rank_up": None}

        # Simple per-process cache: skip heavy work if we updated this user recently (helps on restart + repeated calls)
        last_updated = user.get('mmr_last_updated')
        if last_updated and isinstance(last_updated, (int, float)):
            if time.time() - last_updated < 4 * 3600:  # 4 hours
                return {"success": True, "rank_up": None}

        # Keep trying API until we get data (with delays to avoid rate limit spam)
        stats = None
        start_time = time.time()
        max_wait = 120  # Maximum wait time in seconds
        while not stats and (time.time() - start_time) < max_wait:
            stats = get_player_stats(user["steam_id"], use_cache=False)
            if stats:
                break
            wait_time = 10
            logger.info(f"topmmr: waiting for API, sleeping {wait_time}s...")
            time.sleep(wait_time)
        logger.info(f"topmmr: get_player_stats returned: {stats}")
        
        if not stats:
            logger.warning(f"topmmr: API failed for user {telegram_id} after retries, using cached data")
            cached = _get_cached(f"player_{user['steam_id']}")
            if cached:
                stats = cached
            else:
                stats = {
                    "nickname": user.get("steam_nickname", "Unknown"),
                    "avatar": user.get("avatar"),
                    "mmr": user.get("mmr", 0),
                    "rank_tier": user.get("rank_tier", 0),
                    "total_games": 0,
                    "wins": 0,
                    "losses": 0,
                    "winrate": 0.0,
                }

        # Получаем последние матчи для расчёта недельной статистики
        # Фиксированная неделя: с понедельника по воскресенье
        # Используем МСК (UTC+3) для расчёта начала недели
        MSK = timezone(timedelta(hours=3))
        today_msk = datetime.now(MSK)
        monday_msk = today_msk - timedelta(days=today_msk.weekday())
        week_start_msk = monday_msk.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start_utc = week_start_msk.astimezone(UTC)
        logger.info(f"topmmr: week start (MSK) = {week_start_msk} (Monday)")
        logger.info(f"topmmr: week start (UTC) = {week_start_utc} (Monday)")

        # Получаем последние матчи недели (максимум 10)
        matches = get_recent_matches(user["steam_id"], limit=10)

        # Логируем все полученные матчи
        if matches:
            logger.info(f"topmmr: total matches received from API: {len(matches)}")
            for i, match in enumerate(matches[:5]):
                match_date = datetime.fromtimestamp(match.get("start_time", 0), tz=UTC)
                in_week = match_date >= week_start_utc
                logger.info(f"topmmr: match[{i}] id={match.get('match_id')} start_time={match.get('start_time')} date={match_date} week_start={week_start_utc} in_week={in_week}")
            for i, match in enumerate(matches):
                match_date = datetime.fromtimestamp(match.get("start_time", 0), tz=UTC)
                in_week = match_date >= week_start_utc
                if in_week:
                    if i < 3:
                        radiant_win = match.get("radiant_win", False)
                        player_is_radiant = match.get("radiant")
                        if player_is_radiant is None:
                            player_is_radiant = match.get("player_slot", 0) < 128
                        is_win = (player_is_radiant and radiant_win) or (not player_is_radiant and not radiant_win)
                        logger.info(f"topmmr:   -> radiant={player_is_radiant}, radiant_win={radiant_win}, is_win={is_win}")
                pass
        else:
            logger.warning("topmmr: no matches received from API")

        week_games = 0
        week_wins = 0
        current_streak = 0
        max_streak = 0
        week_current_streak = 0

        if matches:
            # Идём от новых к старым, чтобы current_streak в конце = текущий стрик
            for match in matches:
                try:
                    match_date = datetime.fromtimestamp(match.get("start_time", 0), tz=UTC)
                    if match_date >= week_start_utc:
                        week_games += 1

                        # Определяем победу используя radiant поле из API (приоритет) или player_slot
                        player_slot = match.get("player_slot")
                        radiant_win = match.get("radiant_win", False)
                        
                        # API уже предоставляет radiant булево поле - используем его
                        player_is_radiant = match.get("radiant")
                        if player_is_radiant is None and player_slot is not None:
                            player_is_radiant = player_slot < 128
                        elif player_is_radiant is None:
                            player_is_radiant = True

                        # Победа: игрок был на стороне победившей команды
                        is_win = (player_is_radiant and radiant_win) or (not player_is_radiant and not radiant_win)

                        if week_games <= 3:
                            logger.info(f"topmmr: match {match.get('match_id')} - player_is_radiant={player_is_radiant}, is_win={is_win}")
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

# Save matches to public_player_matches for hero meta
        if matches:
            try:
                from database import get_connection, DATABASE_URL, urlparse
                conn = get_connection()
                url = urlparse.urlparse(DATABASE_URL)
                scheme = url.scheme
                cursor = conn.cursor()
                if "postgres" in scheme:
                    cursor.execute("""
                        CREATE TABLE IF NOT EXISTS public_player_matches (
                            match_id BIGINT UNIQUE,
                            hero_id INTEGER,
                            player_slot INTEGER,
                            radiant_win BOOLEAN,
                            start_time INTEGER,
                            steam_id BIGINT
                        )
                    """)
                    for match in matches:
                        match_id = match.get("match_id")
                        hero_id = match.get("hero_id")
                        player_slot = match.get("player_slot")
                        radiant_win = match.get("radiant_win")
                        start_time = match.get("start_time")
                        steam_id = user.get("steam_id")
                        if match_id and hero_id is not None:
                            cursor.execute("""
                                INSERT INTO public_player_matches (match_id, hero_id, player_slot, radiant_win, start_time, steam_id)
                                VALUES (%s, %s, %s, %s, %s, %s)
                                ON CONFLICT DO NOTHING
                            """, (match_id, hero_id, player_slot, radiant_win, start_time, steam_id))
                else:
                    cursor.execute("""
                        CREATE TABLE IF NOT EXISTS public_player_matches (
                            match_id INTEGER UNIQUE,
                            hero_id INTEGER,
                            player_slot INTEGER,
                            radiant_win INTEGER,
                            start_time INTEGER,
                            steam_id INTEGER
                        )
                    """)
                    for match in matches:
                        match_id = match.get("match_id")
                        hero_id = match.get("hero_id")
                        player_slot = match.get("player_slot")
                        radiant_win = match.get("radiant_win")
                        start_time = match.get("start_time")
                        steam_id = user.get("steam_id")
                        if match_id and hero_id is not None:
                            cursor.execute("""
                                INSERT OR IGNORE INTO public_player_matches (match_id, hero_id, player_slot, radiant_win, start_time, steam_id)
                                VALUES (?, ?, ?, ?, ?, ?)
                            """, (match_id, hero_id, player_slot, radiant_win, start_time, steam_id))
                conn.commit()
            except Exception as e:
                logger.warning(f"Failed to save matches to public_player_matches: {e}")
        
        logger.info(f"Week stats from matches for {telegram_id}: week_games={week_games}, week_wins={week_wins}, week_streak={max_streak}")
        
        # If no matches in week, check if we have any recent matches at all (debug)
        if week_games == 0 and matches:
            latest_match_time = matches[0].get("start_time", 0) if matches else 0
            oldest_match_time = matches[-1].get("start_time", 0) if matches else 0
            logger.info(f"topmmr: DEBUG - no matches in week, latest={latest_match_time}, oldest={oldest_match_time}, week_start={int(week_start_utc.timestamp())}")

        # Проверяем смену недели - если неделя изменилась, сбрасываем статистику
        user_week_start = user.get('week_start_date')
        current_week_start = week_start_msk.strftime("%Y-%m-%d")
        
        # Normalize user_week_start to string for comparison
        if user_week_start:
            if hasattr(user_week_start, 'strftime'):
                user_week_start_str = user_week_start.strftime("%Y-%m-%d")
            else:
                user_week_start_str = str(user_week_start)
        else:
            user_week_start_str = None
        
        if user_week_start_str and user_week_start_str != current_week_start:
            logger.info(f"Week changed for {telegram_id}: {user_week_start_str} -> {current_week_start}, resetting week stats")
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

        # Only update week stats if we have matches
        if matches:
            logger.info(f"Saved week stats to DB: {week_games} games, {week_wins} wins, week_streak={max_streak}, week_start={week_start_utc}")
            
            update_user_fields_batch(telegram_id, {
                "week_games": week_games,
                "week_wins": week_wins,
                "week_best_streak": max_streak,
                "week_current_streak": week_current_streak,
                "week_start_date": current_week_start,
                "rank_tier": new_rank_tier,
                "wins": stats.get("wins", 0),
                "losses": stats.get("losses", 0),
                "mmr": stats["mmr"],
                "avatar": stats.get("avatar"),
                "steam_nickname": stats.get("nickname"),
                "mmr_last_updated": time.time()
            }, update_top_cache=update_top_cache)
        else:
            # No matches - only update non-week stats
            logger.info("No matches this week, skipping week stats update")
            update_user_fields_batch(telegram_id, {
                "rank_tier": new_rank_tier,
                "wins": stats.get("wins", 0),
                "losses": stats.get("losses", 0),
                "mmr": stats["mmr"],
                "avatar": stats.get("avatar"),
                "steam_nickname": stats.get("nickname"),
                "mmr_last_updated": time.time()
            }, update_top_cache=update_top_cache)

        return {"success": True, "rank_up": rank_up, "mmr": stats.get("mmr"), "week_games": week_games, "week_wins": week_wins, "week_best_streak": max_streak, "week_current_streak": week_current_streak, "week_start_date": current_week_start}

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
    weekly_top3: int = 0,
    week_wins: int = 0,
    week_losses: int = 0
) -> bytes | None:
    """Сгенерировать карточку для /start существующего пользователя"""
    try:
        import io
        import os

        from PIL import Image, ImageDraw, ImageFont

        # Компактный размер - увеличенный для Retina
        width = 1024
        height = 500
        scale = 1.8  # коэффициент масштабирования

        # Фон и draw
        try:
            bg_image = _get_start_card_background()
            if bg_image is not None:
                img = bg_image.copy()
                logger.info("Background image loaded successfully (cached)")
            else:
                # Fallback to the original color
                logger.info("Background image HTTP error: using fallback")
                img = Image.new("RGB", (width, height), (15, 20, 35))
        except Exception as e:
            logger.error(f"Failed to load background image: {e}")
            img = Image.new("RGB", (width, height), (15, 20, 35))
        draw = ImageDraw.Draw(img)

        avatar_x_offset = -100  # Shift avatar 100px left
        avatar_size = int(140 * scale)  # Avatar size
        avatar_x = int(120 * scale) + avatar_x_offset  # 20 - 100 + offset
        # Центрирование авататная
        avatar_y = int((height - avatar_size) // 2 - 10)

        avatar_loaded = False
        if avatar_url:
            try:
                logger.info(f"Loading avatar from: {avatar_url}")
                if os.path.isfile(avatar_url):
                    avatar = Image.open(avatar_url).convert("RGBA")
                else:
                    resp = requests.get(
                        avatar_url,
                        timeout=10,
                        headers={"User-Agent": "fissure-bot/1.0"},
                    )
                    logger.info(f"Avatar request status: {resp.status_code} url={avatar_url[:80]}")
                    if resp.status_code == 200 and resp.content:
                        avatar = Image.open(io.BytesIO(resp.content)).convert("RGBA")
                    else:
                        logger.warning(f"Avatar download failed: status={resp.status_code}, url={avatar_url[:80]}")
                        avatar = None
                if avatar:
                    # Check image size to prevent memory issues - max 512px
                    w, h = avatar.size
                    if w > 512 or h > 512:
                        logger.info(f"Resizing avatar from {w}x{h} to 512x512 max")
                        avatar = avatar.resize((min(w, 512), min(h, 512)), Image.LANCZOS)
                    # Resize and crop to square
                    w, h = avatar.size
                    side = min(w, h)
                    left = (w - side) // 2
                    top = (h - side) // 2
                    avatar = avatar.crop((left, top, left + side, top + side))
                    avatar = avatar.resize((avatar_size, avatar_size), Image.LANCZOS)
                    # Gold border like /profil
                    draw.rectangle([avatar_x, avatar_y, avatar_x + avatar_size, avatar_y + avatar_size], outline=(215, 175, 85), width=int(4*scale))
                    if avatar.mode == "RGBA":
                        img.paste(avatar, (avatar_x, avatar_y), avatar)
                    else:
                        img.paste(avatar, (avatar_x, avatar_y))
                    avatar_loaded = True
                else:
                    logger.warning(f"Avatar download returned no image: {avatar_url}")
            except Exception as e:
                logger.warning(f"Exception loading avatar: {e}")

        if not avatar_loaded:
            draw.rectangle([avatar_x, avatar_y, avatar_x + avatar_size, avatar_y + avatar_size], fill=(40, 55, 80), outline=(215, 175, 85), width=int(4*scale))
            # Default icon placeholder
            draw.ellipse([avatar_x + int(45*scale), avatar_y + int(35*scale), avatar_x + int(95*scale), avatar_y + int(105*scale)], fill=(80, 100, 130))

        # Координаты для текстовой информации (справа от аватара)
        info_x = avatar_x + avatar_size + int(30 * scale)
        info_y = avatar_y + int(20 * scale)

        # Шрифты - увеличенные для Retina
        try:
            font_title = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", int(40 * scale))
            font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", int(26 * scale))
        except Exception:
            font_title = ImageFont.load_default()
            font_small = ImageFont.load_default()

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

        rank_icon = None
        rank_icon_size = int(80 * scale)
        if rank_tier > 0:
            tier = rank_tier // 10
            star = rank_tier % 10
            if star == 0:
                star = 5

            rank_urls = {
                (1, 1): "https://static.wikia.nocookie.net/dota2_gamepedia/images/8/85/SeasonalRank1-1.png",
                (1, 2): "https://static.wikia.nocookie.net/dota2_gamepedia/images/e/ee/SeasonalRank1-2.png",
                (1, 3): "https://static.wikia.nocookie.net/dota2_gamepedia/images/0/05/SeasonalRank1-3.png",
                (1, 4): "https://static.wikia.nocookie.net/dota2_gamepedia/images/6/6d/SeasonalRank1-4.png",
                (1, 5): "https://static.wikia.nocookie.net/dota2_gamepedia/images/2/2b/SeasonalRank1-5.png",

                (2, 1): "https://static.wikia.nocookie.net/dota2_gamepedia/images/c/c7/SeasonalRank2-1.png",
                (2, 2): "https://static.wikia.nocookie.net/dota2_gamepedia/images/2/2c/SeasonalRank2-2.png",
                (2, 3): "https://static.wikia.nocookie.net/dota2_gamepedia/images/f/f5/SeasonalRank2-3.png",
                (2, 4): "https://static.wikia.nocookie.net/dota2_gamepedia/images/b/b4/SeasonalRank2-4.png",
                (2, 5): "https://static.wikia.nocookie.net/dota2_gamepedia/images/3/32/SeasonalRank2-5.png",

                (3, 1): "https://static.wikia.nocookie.net/dota2_gamepedia/images/8/82/SeasonalRank3-1.png",
                (3, 2): "https://static.wikia.nocookie.net/dota2_gamepedia/images/6/6e/SeasonalRank3-2.png",
                (3, 3): "https://static.wikia.nocookie.net/dota2_gamepedia/images/6/67/SeasonalRank3-3.png",
                (3, 4): "https://static.wikia.nocookie.net/dota2_gamepedia/images/8/87/SeasonalRank3-4.png",
                (3, 5): "https://static.wikia.nocookie.net/dota2_gamepedia/images/b/b1/SeasonalRank3-5.png",

                (4, 1): "https://static.wikia.nocookie.net/dota2_gamepedia/images/7/76/SeasonalRank4-1.png",
                (4, 2): "https://static.wikia.nocookie.net/dota2_gamepedia/images/8/87/SeasonalRank4-2.png",
                (4, 3): "https://static.wikia.nocookie.net/dota2_gamepedia/images/6/60/SeasonalRank4-3.png",
                (4, 4): "https://static.wikia.nocookie.net/dota2_gamepedia/images/4/4a/SeasonalRank4-4.png",
                (4, 5): "https://static.wikia.nocookie.net/dota2_gamepedia/images/a/a3/SeasonalRank4-5.png",

                (5, 1): "https://static.wikia.nocookie.net/dota2_gamepedia/images/7/79/SeasonalRank5-1.png",
                (5, 2): "https://static.wikia.nocookie.net/dota2_gamepedia/images/5/52/SeasonalRank5-2.png",
                (5, 3): "https://static.wikia.nocookie.net/dota2_gamepedia/images/8/88/SeasonalRank5-3.png",
                (5, 4): "https://static.wikia.nocookie.net/dota2_gamepedia/images/2/25/SeasonalRank5-4.png",
                (5, 5): "https://static.wikia.nocookie.net/dota2_gamepedia/images/8/8e/SeasonalRank5-5.png",

                (6, 1): "https://static.wikia.nocookie.net/dota2_gamepedia/images/e/e0/SeasonalRank6-1.png",
                (6, 2): "https://static.wikia.nocookie.net/dota2_gamepedia/images/1/1c/SeasonalRank6-2.png",
                (6, 3): "https://static.wikia.nocookie.net/dota2_gamepedia/images/d/da/SeasonalRank6-3.png",
                (6, 4): "https://static.wikia.nocookie.net/dota2_gamepedia/images/d/db/SeasonalRank6-4.png",
                (6, 5): "https://static.wikia.nocookie.net/dota2_gamepedia/images/4/47/SeasonalRank6-5.png",

                (7, 1): "https://static.wikia.nocookie.net/dota2_gamepedia/images/b/b7/SeasonalRank7-1.png",
                (7, 2): "https://static.wikia.nocookie.net/dota2_gamepedia/images/8/8f/SeasonalRank7-2.png",
                (7, 3): "https://static.wikia.nocookie.net/dota2_gamepedia/images/f/fd/SeasonalRank7-3.png",
                (7, 4): "https://static.wikia.nocookie.net/dota2_gamepedia/images/1/13/SeasonalRank7-4.png",
                (7, 5): "https://static.wikia.nocookie.net/dota2_gamepedia/images/3/33/SeasonalRank7-5.png",
            }

            rank_url = rank_urls.get((tier, star))
            if rank_url:
                try:
                    resp = requests.get(rank_url, timeout=4)
                    if resp.status_code == 200:
                        rank_icon = Image.open(io.BytesIO(resp.content)).convert("RGBA")
                        rank_icon = rank_icon.resize((rank_icon_size, rank_icon_size), Image.LANCZOS)
                except Exception:
                    pass

        username_y = info_y
        username_x_offset = 0
        if steam_nickname:
            draw.text((info_x + username_x_offset, username_y), f"{steam_nickname}", fill=(255, 255, 255), font=font_title)
        elif username:
            draw.text((info_x + username_x_offset, username_y), f"@{username}", fill=(255, 255, 255), font=font_title)

        msg_label_y = username_y + int(50 * scale)
        if week_wins is not None and week_losses is not None:
            draw.text((info_x + username_x_offset, msg_label_y), "За неделю:", fill=(255, 255, 255), font=font_small)
        else:
            draw.text((info_x + username_x_offset, msg_label_y), "Всего сообщений:", fill=(255, 255, 255), font=font_small)

        msg_num_y = msg_label_y + int(28 * scale)
        if week_wins is not None and week_losses is not None:
            wr = round((week_wins / (week_wins + week_losses) * 100), 1) if (week_wins + week_losses) > 0 else 0
            draw.text((info_x + username_x_offset, msg_num_y), f"{week_wins}W/{week_losses}L/{wr}%", fill=(255, 255, 255), font=font_title)
        else:
            draw.text((info_x + username_x_offset, msg_num_y), f"{message_count}", fill=(255, 255, 255), font=font_title)

        if rank_tier > 0 and rank_icon:
            rank_x = avatar_x + avatar_size // 2 - rank_icon_size // 2
            rank_y = avatar_y + avatar_size - rank_icon_size // 2
            img.paste(rank_icon, (rank_x, rank_y), rank_icon)

        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=90)
        buf.seek(0)
        return buf.read()

    except Exception:
        import logging
        logging.exception("generate_start_card error")
        return None


def generate_top_card(
    avatar_url: str = None,
    username: str = None,
    telegram_id: int = None,
    fissure: float = 0.0,
    extra_text: str = None,
    rank_tier: int = 0,
    show_avatar: bool = True
) -> bytes | None:
    """Generate top banner matching start card style"""
    try:
        import io
        import os

        import requests
        from PIL import Image, ImageDraw, ImageFont

        width = 1024
        height = 500
        scale = 1.8

        try:
            bg_image = _get_start_card_background()
            if bg_image is not None:
                img = bg_image.copy()
            else:
                img = Image.new("RGB", (width, height), (15, 20, 35))
        except Exception:
            img = Image.new("RGB", (width, height), (15, 20, 35))
        draw = ImageDraw.Draw(img)

        avatar_x_offset = -100
        avatar_size = int(140 * scale)
        avatar_x = int(120 * scale) + avatar_x_offset
        avatar_y = int((height - avatar_size) // 2 - 10)

        avatar_loaded = False
        logger.info(f"generate_top_card: avatar_url={avatar_url[:50] if avatar_url else None}, show_avatar={show_avatar}")
        if avatar_url and show_avatar and str(avatar_url).strip().lower().startswith(('http://', 'https://')):
            try:
                if os.path.isfile(avatar_url):
                    avatar = Image.open(avatar_url).convert("RGBA")
                else:
                    resp = requests.get(avatar_url, timeout=10, headers={"User-Agent": "fissure-bot/1.0"})
                    if resp.status_code == 200 and resp.content:
                        avatar = Image.open(io.BytesIO(resp.content)).convert("RGBA")
                    else:
                        avatar = None
                if avatar:
                    w, h = avatar.size
                    side = min(w, h)
                    left = (w - side) // 2
                    top = (h - side) // 2
                    avatar = avatar.crop((left, top, left + side, top + side))
                    avatar = avatar.resize((avatar_size, avatar_size), Image.LANCZOS)
                    draw.rectangle([avatar_x, avatar_y, avatar_x + avatar_size, avatar_y + avatar_size], outline=(215, 175, 85), width=int(4*scale))
                    if avatar.mode == "RGBA":
                        img.paste(avatar, (avatar_x, avatar_y), avatar)
                    else:
                        img.paste(avatar, (avatar_x, avatar_y))
                    avatar_loaded = True
            except Exception as e:
                logger.warning(f"Exception loading avatar: {e}")

        if not avatar_loaded:
            draw.rectangle([avatar_x, avatar_y, avatar_x + avatar_size, avatar_y + avatar_size], fill=(40, 55, 80), outline=(215, 175, 85), width=int(4*scale))
            draw.ellipse([avatar_x + int(45*scale), avatar_y + int(35*scale), avatar_x + int(95*scale), avatar_y + int(105*scale)], fill=(80, 100, 130))

        info_x = avatar_x + avatar_size + int(30 * scale)
        info_y = avatar_y + int(20 * scale)

        try:
            font_title = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", int(40 * scale))
            font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", int(26 * scale))
            font_fissure = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", int(36 * scale))
        except Exception:
            font_title = font_small = font_fissure = ImageFont.load_default()

        display_name = f"@{username}" if username else str(telegram_id) if telegram_id else "Unknown"
        draw.text((info_x, info_y), display_name, fill=(255, 255, 255), font=font_title)

if fissure > 0:
            fissure_label_y = info_y + int(50 * scale)
            draw.text((info_x, fissure_label_y), "Длина фиссуры:", fill=(255, 255, 255), font=font_small)
            fissure_y = fissure_label_y + int(28 * scale) + 5
            fissure_text = f"{fissure:.0f} см"
            draw.text((info_x, fissure_y), fissure_text, fill=(255, 255, 255), font=font_title)

        if extra_text:
            if fissure > 0:
                extra_y = fissure_y + int(35 * scale) + 5
            else:
                extra_y = info_y + int(55 * scale) + 5
            draw.text((info_x, extra_y), extra_text, fill=(255, 255, 255), font=font_small)

        rank_icon_size = int(80 * scale)
        rank_icon = None
        if rank_tier > 0:
            tier = rank_tier // 10
            star = rank_tier % 10
            if star == 0:
                star = 5

            rank_urls = {
                (1, 1): "https://static.wikia.nocookie.net/dota2_gamepedia/images/8/85/SeasonalRank1-1.png",
                (1, 2): "https://static.wikia.nocookie.net/dota2_gamepedia/images/e/ee/SeasonalRank1-2.png",
                (1, 3): "https://static.wikia.nocookie.net/dota2_gamepedia/images/0/05/SeasonalRank1-3.png",
                (1, 4): "https://static.wikia.nocookie.net/dota2_gamepedia/images/6/6d/SeasonalRank1-4.png",
                (1, 5): "https://static.wikia.nocookie.net/dota2_gamepedia/images/2/2b/SeasonalRank1-5.png",
                (2, 1): "https://static.wikia.nocookie.net/dota2_gamepedia/images/c/c7/SeasonalRank2-1.png",
                (2, 2): "https://static.wikia.nocookie.net/dota2_gamepedia/images/2/2c/SeasonalRank2-2.png",
                (2, 3): "https://static.wikia.nocookie.net/dota2_gamepedia/images/f/f5/SeasonalRank2-3.png",
                (2, 4): "https://static.wikia.nocookie.net/dota2_gamepedia/images/b/b4/SeasonalRank2-4.png",
                (2, 5): "https://static.wikia.nocookie.net/dota2_gamepedia/images/3/32/SeasonalRank2-5.png",
                (3, 1): "https://static.wikia.nocookie.net/dota2_gamepedia/images/8/82/SeasonalRank3-1.png",
                (3, 2): "https://static.wikia.nocookie.net/dota2_gamepedia/images/6/6e/SeasonalRank3-2.png",
                (3, 3): "https://static.wikia.nocookie.net/dota2_gamepedia/images/6/67/SeasonalRank3-3.png",
                (3, 4): "https://static.wikia.nocookie.net/dota2_gamepedia/images/8/87/SeasonalRank3-4.png",
                (3, 5): "https://static.wikia.nocookie.net/dota2_gamepedia/images/b/b1/SeasonalRank3-5.png",
                (4, 1): "https://static.wikia.nocookie.net/dota2_gamepedia/images/7/76/SeasonalRank4-1.png",
                (4, 2): "https://static.wikia.nocookie.net/dota2_gamepedia/images/8/87/SeasonalRank4-2.png",
                (4, 3): "https://static.wikia.nocookie.net/dota2_gamepedia/images/6/60/SeasonalRank4-3.png",
                (4, 4): "https://static.wikia.nocookie.net/dota2_gamepedia/images/4/4a/SeasonalRank4-4.png",
                (4, 5): "https://static.wikia.nocookie.net/dota2_gamepedia/images/a/a3/SeasonalRank4-5.png",
                (5, 1): "https://static.wikia.nocookie.net/dota2_gamepedia/images/7/79/SeasonalRank5-1.png",
                (5, 2): "https://static.wikia.nocookie.net/dota2_gamepedia/images/5/52/SeasonalRank5-2.png",
                (5, 3): "https://static.wikia.nocookie.net/dota2_gamepedia/images/8/88/SeasonalRank5-3.png",
                (5, 4): "https://static.wikia.nocookie.net/dota2_gamepedia/images/2/25/SeasonalRank5-4.png",
                (5, 5): "https://static.wikia.nocookie.net/dota2_gamepedia/images/8/8e/SeasonalRank5-5.png",
                (6, 1): "https://static.wikia.nocookie.net/dota2_gamepedia/images/e/e0/SeasonalRank6-1.png",
                (6, 2): "https://static.wikia.nocookie.net/dota2_gamepedia/images/1/1c/SeasonalRank6-2.png",
                (6, 3): "https://static.wikia.nocookie.net/dota2_gamepedia/images/d/da/SeasonalRank6-3.png",
                (6, 4): "https://static.wikia.nocookie.net/dota2_gamepedia/images/d/db/SeasonalRank6-4.png",
                (6, 5): "https://static.wikia.nocookie.net/dota2_gamepedia/images/4/47/SeasonalRank6-5.png",
                (7, 1): "https://static.wikia.nocookie.net/dota2_gamepedia/images/b/b7/SeasonalRank7-1.png",
                (7, 2): "https://static.wikia.nocookie.net/dota2_gamepedia/images/8/8f/SeasonalRank7-2.png",
                (7, 3): "https://static.wikia.nocookie.net/dota2_gamepedia/images/f/fd/SeasonalRank7-3.png",
                (7, 4): "https://static.wikia.nocookie.net/dota2_gamepedia/images/1/13/SeasonalRank7-4.png",
                (7, 5): "https://static.wikia.nocookie.net/dota2_gamepedia/images/3/33/SeasonalRank7-5.png",
            }

            rank_url = rank_urls.get((tier, star))
            if rank_url:
                try:
                    resp = requests.get(rank_url, timeout=4)
                    if resp.status_code == 200:
                        rank_icon = Image.open(io.BytesIO(resp.content)).convert("RGBA")
                        rank_icon = rank_icon.resize((rank_icon_size, rank_icon_size), Image.LANCZOS)
                        rank_x = avatar_x + avatar_size // 2 - rank_icon_size // 2
                        rank_y = avatar_y + avatar_size - rank_icon_size // 2
                        img.paste(rank_icon, (rank_x, rank_y), rank_icon)
                except Exception as e:
                    logger.warning(f"Exception loading rank icon: {e}")

        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=90)
        buf.seek(0)
        return buf.read()

    except Exception:
        import logging
        logging.exception("generate_top_card error")
        return None

