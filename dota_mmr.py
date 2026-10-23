import asyncio
import base64
import contextvars
import functools
import io
import json
import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import aiohttp
import httpx
import requests
from PIL import Image

from cache import cache as redis_cache
from cache_service import (
    api_cache,
    hero_cache,
    negative_cache,
    opendota_circuit_breaker,
    opendota_rate_limiter,
)
from constants import (
    PROFILE_CARD_H,
    PROFILE_CARD_LADDER_TOTAL,
    PROFILE_CARD_RANKS_PER_TIER,
    PROFILE_CARD_SS,
    PROFILE_CARD_W,
    get_banner_path,
)
from database import get_aiohttp_session, get_user, get_user_by_steam_id, update_user_fields_batch
from hero_names import get_cdn_hero_name

logger = logging.getLogger(__name__)

_USE_LOCAL_AIOHTTP_SESSION: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "use_local_aiohttp_session", default=False
)

# Thread pool for running async code from sync contexts (avoids event loop conflicts)
_async_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="async_sync_bridge")

def _run_async(coro, timeout: int = 60):
    """Run async coroutine from sync context safely.
    
    Uses a dedicated thread pool with its own event loop to avoid
    "Event loop is closed" and "RuntimeError: asyncio.run() cannot be called from a running event loop" errors.
    
    Automatically isolates aiohttp sessions so global session from main loop
    is not reused across event loops.
    
    Note: on timeout, the background thread continues running asyncio.run() to completion.
    Under sustained load this can strand threads. If that becomes an issue, refactor the
    caller to be async end-to-end instead of using this sync bridge.
    """
    def run_in_new_loop():
        token = _USE_LOCAL_AIOHTTP_SESSION.set(True)
        try:
            return asyncio.run(coro)
        finally:
            _USE_LOCAL_AIOHTTP_SESSION.reset(token)

    future = _async_executor.submit(run_in_new_loop)
    return future.result(timeout=timeout)

# Hero list cache (uses unified cache)
_HEROES_CACHE_TTL = 86400  # 24 hours

async def get_hero_list():
    """Get list of heroes from OpenDota API with caching."""
    cached = hero_cache.get("hero_list")
    if cached is not None:
        return cached
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
            async with session.get("https://api.opendota.com/api/heroes", headers={"User-Agent": "FissureBot/1.0 (Dota2 Telegram Bot)"}) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data:
                        hero_cache.set("hero_list", data, ttl=_HEROES_CACHE_TTL)
                        return data
    except Exception as e:
        logger.warning(f"Failed to fetch heroes: {e}")
    return []

OPENDOTA_API_URL = "https://api.opendota.com/api"
STEAM_OFFSET = 76561197960265728

# Legacy synchronous rate limiter retained for helper functions that still use
# the sync bridge. Async OpenDota calls use the shared token limiter above.
_api_rate_limit = {"last_request": 0, "requests_count": 0, "window_start": 0}
API_RATE_LIMIT = 20
API_RATE_WINDOW = 60
API_MIN_INTERVAL = 0

# Глобальное состояние rate limit для сообщений об ошибках (fallback)
_opendota_rate_limited_until = 0

# Rank icons cache (fallback if image_cache fails)
_rank_icons_cache = {}

# Heroes image cache for profile stats
_heroes_image_cache = {}
_heroes_image_cache_ttl = 3600  # 1 hour

# Cached background for start card to avoid repeated downloads
_START_CARD_BACKGROUND_RESIZED = None
_START_CARD_BACKGROUND_CACHED = False

def _get_start_card_background():
    global _START_CARD_BACKGROUND_RESIZED, _START_CARD_BACKGROUND_CACHED
    if _START_CARD_BACKGROUND_CACHED:
        return _START_CARD_BACKGROUND_RESIZED
    try:
        local_bg = get_banner_path("background")
        if isinstance(local_bg, Path) and local_bg.exists():
            bg_image = Image.open(local_bg).convert("RGB")
            bg_image = bg_image.resize((1024, 500), Image.LANCZOS)
            _START_CARD_BACKGROUND_RESIZED = bg_image
            _START_CARD_BACKGROUND_CACHED = True
            return bg_image
        logger.warning(f"Start card background not found at {local_bg}")
    except Exception as e:
        logger.error(f"Failed to load start card background: {e}")
    return None

def reset_circuit_breaker():
    """Принудительно сбросить circuit breaker (для отладки/восстановления)"""
    opendota_circuit_breaker.reset()
    logger.info("Circuit breaker manually reset to CLOSED")


AVATAR_CACHE_TTL = 30 * 86400  # 30 days


async def _cache_avatar(steam_id: int, avatar_url: str) -> None:
    """Download and cache player avatar in Redis."""
    if not avatar_url or not steam_id:
        return
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
            async with session.get(avatar_url, headers={"User-Agent": "FissureBot/1.0"}) as resp:
                if resp.status == 200:
                    data = await resp.read()
                    if data:
                        import base64
                        encoded = base64.b64encode(data).decode()
                        await redis_cache.set(f"avatar:{steam_id}", encoded, ttl=AVATAR_CACHE_TTL)
                        logger.debug(f"Cached avatar for steam_id={steam_id}")
    except Exception as e:
        logger.debug(f"Failed to cache avatar for {steam_id}: {e}")


async def cache_avatar_bytes(steam_id: int, data: bytes) -> None:
    """Store already-downloaded avatar bytes in Redis.

    Used when the avatar was resolved from Telegram or a direct URL, so the
    next read hits the cache instead of falling through to OpenDota (which
    may be rate limited).
    """
    if not data or not steam_id:
        return
    try:
        import base64
        encoded = base64.b64encode(data).decode()
        await redis_cache.set(f"avatar:{steam_id}", encoded, ttl=AVATAR_CACHE_TTL)
        logger.debug(f"Cached avatar bytes for steam_id={steam_id}")
    except Exception as e:
        logger.debug(f"Failed to cache avatar bytes for {steam_id}: {e}")


async def get_cached_avatar(steam_id: int) -> bytes | None:
    """Get cached avatar bytes from Redis."""
    if not steam_id:
        return None
    try:
        cached = await redis_cache.get(f"avatar:{steam_id}")
        if cached:
            import base64
            return base64.b64decode(cached)
    except Exception as e:
        logger.debug(f"Failed to get cached avatar for {steam_id}: {e}")
    return None


# Background retry task for circuit breaker recovery# Background retry task for circuit breaker recovery
_retry_task = None

def start_background_retry(max_retries=3, retry_interval=30):
    """Start background task for circuit breaker recovery."""
    global _retry_task

    def retry_loop():
        while True:
            time.sleep(retry_interval)
            if opendota_circuit_breaker.state == "OPEN":
                logger.info("Background retry: attempting circuit breaker recovery")
                # The circuit breaker will automatically transition to HALF_OPEN

    if _retry_task is None:
        _retry_task = threading.Thread(target=retry_loop, daemon=True)
        _retry_task.start()
        logger.info("Background retry task started")

def _circuit_breaker_can_execute() -> bool:
    """Проверить можно ли выполнять запрос (Circuit Breaker pattern)"""
    return opendota_circuit_breaker.can_execute()

def _circuit_breaker_record_success():
    """Записать успешный запрос"""
    opendota_circuit_breaker.record_success()

def _circuit_breaker_record_failure():
    """Записать неудачный запрос"""
    opendota_circuit_breaker.record_failure()

# Простой кеш для запросов (5 минут)
_CACHE = {}
CACHE_TTL = 300  # 5 минут
CACHE_MAX_SIZE = 100  # максимальное количество записей в кеше

# Negative cache: аккаунты/эндпоинты, которые точно не найдены (404).
# Позволяет не дёргать API повторно и не spin-ить retry-цикл на несуществующих игроках.
_NEG_CACHE = {}
_NEG_TTL = 3600  # 1 час


def _mark_not_found(url: str):
    """Запомнить, что эндпоинт вернул 404 (аккаунт не существует / профиль скрыт)."""
    negative_cache.set(url)


def _is_not_found(url: str) -> bool:
    """Проверить, был ли уже кеширован 404 ответ."""
    return negative_cache.get(url)


def _clear_not_found(url: str):
    """Удалить запись о 404 из кеша."""
    negative_cache.delete(url)

# Кеш матчей пользователей (30 минут - экономим API).
#
# Ключ — только steam_id, а не (steam_id, limit): страница матчей
# просит 8 матчей, апдейт профиля и OBS — другие числа, и при старом
# ключе они каждый раз качали одно и то же заново. Теперь в кеш
# лежит максимум уже скачанного, а лимит режется по месту.
_user_matches_cache = {}
USER_MATCHES_CACHE_TTL = 1800  # 30 минут




def is_opendota_rate_limited():
    """Проверить, находится ли OpenDota API в состоянии rate limit.
    Учитывает как ручное ограничение (429), так и состояние UnifiedRateLimiter."""
    if time.time() < _opendota_rate_limited_until:
        return True
    if opendota_rate_limiter.get_available() < 1:
        return True
    return False

def get_opendota_rate_limit_time_remaining():
    """Получить оставшееся время до восстановления API в секундах"""
    global _opendota_rate_limited_until
    ts_remaining = max(0, int(_opendota_rate_limited_until - time.time()))
    rl_remaining = int(opendota_rate_limiter.wait_time(1))
    return max(ts_remaining, rl_remaining)

def get_opendota_rate_limit_message():
    """Получить сообщение об ошибке"""
    return "⚠️ OpenDota API временно недоступен. Вернётся, когда кто-то купит варды 👁️"

def set_opendota_rate_limited(wait_seconds=60):
    """Установить время до которого OpenDota API недоступен"""
    global _opendota_rate_limited_until
    _opendota_rate_limited_until = time.time() + wait_seconds
    opendota_rate_limiter._tokens = 0
    opendota_rate_limiter._last_update = time.monotonic() - wait_seconds

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
    """Получить значение из кеша с ограничением размера (using unified cache)"""
    value = api_cache.get(key)
    if value is None:
        return None
    if len(api_cache._cache) > CACHE_MAX_SIZE:
        api_cache._evict_lru()
    return value


def _set_cached(key, value):
    """Сохранить значение в кеш с ограничением размера (using unified cache)"""
    api_cache.set(key, value, ttl=CACHE_TTL)


def _clear_cache():
    """Очистить весь кеш (для освобождения памяти)"""
    api_cache.clear()


async def _check_rate_limit_async():
    """Async версия rate limiting - using unified rate limiter."""
    if not opendota_rate_limiter.try_acquire(1):
        wait = opendota_rate_limiter.wait_time(1)
        await asyncio.sleep(wait)


async def _api_get_async(url: str, params: dict = None, use_session: bool = True, timeout: int = 20, max_retries: int = 3) -> dict:
    """Асинхронная функция для API-запросов с переиспользуемой сессией, retry и rate limiting"""
    if not _circuit_breaker_can_execute():
        logger.warning("Circuit breaker: skipping async request, API unavailable")
        return None

    if is_opendota_rate_limited():
        remaining = get_opendota_rate_limit_time_remaining()
        # Один лог на паузу, а не по строке на каждый запрос: при
        # параллельном обновлении игроков это десятки одинаковых строк.
        _log_upstream_outage()
        await asyncio.sleep(remaining + 1)

    await _check_rate_limit_async()

    if params is None:
        params = {}

    if params is None:
        params = {}

    if _USE_LOCAL_AIOHTTP_SESSION.get():
        session = None
    elif use_session:
        session = await get_aiohttp_session()
    else:
        session = None

    for attempt in range(max_retries + 1):
        current_timeout = timeout if attempt == 0 else timeout + 10
        try:
            if session:
                async with session.get(url, params=params, headers={"User-Agent": "FissureBot/1.0 (Dota2 Telegram Bot)"}, timeout=aiohttp.ClientTimeout(total=current_timeout)) as resp:
                    return await _handle_api_response(resp, url, attempt, max_retries)
            else:
                async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=current_timeout)) as sess:
                    async with sess.get(url, params=params, headers={"User-Agent": "FissureBot/1.0 (Dota2 Telegram Bot)"}) as resp:
                        return await _handle_api_response(resp, url, attempt, max_retries)
        except TimeoutError:
            logger.warning(f"API request timeout ({current_timeout}s), retrying... ({attempt + 1}/{max_retries + 1})")
            if attempt < max_retries:
                await asyncio.sleep(3 + attempt * 2)
                continue
            _circuit_breaker_record_failure()
            return None
        except RuntimeError as e:
            if "Event loop is closed" in str(e):
                logger.warning(f"Async API error ({e}), retrying... ({attempt + 1}/{max_retries + 1})")
                if attempt < max_retries:
                    await asyncio.sleep(3 + attempt * 2)
                    continue
                _circuit_breaker_record_failure()
                return None
            logger.error(f"Async API request error: {e}", exc_info=True)
            if attempt < max_retries:
                await asyncio.sleep(3 + attempt * 2)
                continue
            _circuit_breaker_record_failure()
            return None
        except Exception as e:
            logger.error(f"Async API request error: {e}", exc_info=True)
            if attempt < max_retries:
                await asyncio.sleep(3 + attempt * 2)
                continue
            _circuit_breaker_record_failure()
            return None

    logger.error(f"Async API request failed after {max_retries + 1} retries: {url[:80]}")
    return None


_outage_log_at = 0.0
OUTAGE_LOG_EVERY = 300.0  # не чаще раза в 5 минут


def _log_upstream_outage(status: int = 0):
    """Сообщить о недоступности OpenDota, но не засорить лог.

    Когда лежит сам фронт, одинаковые 521 прилетают на каждый из
    десятков запросов подряд. Раньше это давало сотни строк в минуту
    и полностью забивало журнал, поэтому здесь счётчик времени.
    """
    global _outage_log_at
    now = time.monotonic()
    if now - _outage_log_at < OUTAGE_LOG_EVERY:
        return
    _outage_log_at = now
    reason = f"HTTP {status}" if status else "пауза после ошибок"
    logger.warning(
        f"OpenDota недоступен ({reason}). Ставим паузу 120с, "
        f"остальные ошибки того же вида в лог не пишем."
    )


async def _handle_api_response(resp, url: str, attempt: int, max_retries: int):
    """Handle API response and return parsed JSON or None."""
    if resp.status == 200:
        _circuit_breaker_record_success()
        try:
            from analytics_dashboard import record_opendota_tokens
            record_opendota_tokens(1)
        except Exception as e:
            logger.debug(f"Failed to record OpenDota tokens: {e}")
        return await resp.json()
    elif resp.status == 429:
        logger.warning("Rate limited by OpenDota API, waiting...")
        set_opendota_rate_limited(60)
        wait_time = 3 * (attempt + 1)
        await asyncio.sleep(wait_time)
        return None
    elif resp.status in (521, 522):
        # Cloudflare сообщает, что OpenDota лежит (5xx от самого фронта).
        # Повторять каждый запрос четыре раза бессмысленно: за это время
        # прилетит столько же ошибок от других игроков и лог забьётся
        # одинаковыми строками. Ставим общую паузу вместо ретраев.
        set_opendota_rate_limited(120)
        _log_upstream_outage(resp.status)
        _circuit_breaker_record_failure()
        return None
    elif resp.status >= 500:
        _log_upstream_outage(resp.status)
        _circuit_breaker_record_failure()
        await asyncio.sleep(1 + attempt)
        return None
    else:
        logger.error(f"API error {resp.status} for {url[:80]}")
        if resp.status == 404:
            _mark_not_found(url)
        return None


# ========================
# 🎮 MATCHES
# ========================

# ========================
# 🦸 HEROES
# ========================

HERO_IMAGE_BASE = str(Path(__file__).parent / "assets" / "heroes_webp" / "portraits")

HERO_CACHE_DIR = Path(__file__).parent / "assets" / "heroes_webp"
HERO_CACHE_DIR.mkdir(parents=True, exist_ok=True)
HERO_PORTRAIT_DIR = HERO_CACHE_DIR / "portraits"
HERO_PORTRAIT_DIR.mkdir(parents=True, exist_ok=True)
HERO_ICON_BASE = str(HERO_CACHE_DIR)
HEROES_STRIP_BG_URL = get_banner_path("heroes_profil")
HEROES_STRIP_BG_CACHE = "heroes_profil.webp"

# Static hero catalog shipped with the bot. The API copy lives in a plain dict
# in memory, so after every deploy the first /heroes call is exposed to the
# OpenDota rate limit - and when it is refused, callers get no hero names, no
# roles and no image paths, which renders an empty hero meta infographic.
HERO_CATALOG_PATH = Path(__file__).parent / "assets" / "heroes_catalog.json"
_local_hero_catalog: dict | None = None


def _build_hero_entry(hero: dict) -> dict:
    """Shape one hero into the structure the rest of the code expects."""
    short_name = hero["short_name"]
    cdn_name = get_cdn_hero_name(short_name)
    return {
        "id": hero["id"],
        "name": hero["name"],
        "short_name": short_name,
        "image_url": str(Path(HERO_IMAGE_BASE) / f"{cdn_name}.webp"),
        "icon_url": str(Path(HERO_ICON_BASE) / f"{cdn_name}.webp"),
        "img": str(Path(HERO_IMAGE_BASE) / f"{cdn_name}.webp"),
        "roles": hero.get("roles", []),
    }


def get_local_heroes_data() -> dict:
    """Hero metadata from the bundled catalog, keyed by hero id.

    The keys are ints to match the API response and the ids stored in
    public_player_matches.
    """
    global _local_hero_catalog
    if _local_hero_catalog is None:
        try:
            raw = json.loads(HERO_CATALOG_PATH.read_text(encoding="utf-8"))
        except Exception as e:
            logger.error(f"Could not read local hero catalog: {e}")
            raw = {}
        _local_hero_catalog = {
            int(hero_id): _build_hero_entry({**hero, "id": int(hero_id)})
            for hero_id, hero in raw.items()
        }
    return _local_hero_catalog


def get_hero_icon_cached(hero_short_name: str, timeout: int = 3) -> bytes | None:
    """Get hero icon from local assets only."""
    cdn_name = get_cdn_hero_name(hero_short_name)
    
    cache_file = HERO_CACHE_DIR / f"{cdn_name}.webp"
    if cache_file.exists():
        try:
            return cache_file.read_bytes()
        except Exception:
            pass
    
    if hero_short_name != cdn_name:
        cache_file_local = HERO_CACHE_DIR / f"{hero_short_name}.webp"
        if cache_file_local.exists():
            try:
                return cache_file_local.read_bytes()
            except Exception:
                pass

    # Special fallback: doom_bringer has the same icon as doom
    if hero_short_name == "doom" or cdn_name == "doom":
        cache_file_doombringer = HERO_CACHE_DIR / "doom_bringer.webp"
        if cache_file_doombringer.exists():
            try:
                return cache_file_doombringer.read_bytes()
            except Exception:
                pass

    # Special fallback: magnataur has the same icon as magnus
    if hero_short_name == "magnus" or cdn_name == "magnus":
        cache_file_magnataur = HERO_CACHE_DIR / "magnataur.webp"
        if cache_file_magnataur.exists():
            try:
                return cache_file_magnataur.read_bytes()
            except Exception:
                pass

    return None


def get_hero_portrait_cached(hero_short_name: str, timeout: int = 5) -> bytes | None:
    """Портрет героя (локальный) — выше разрешение, чем icons/*.png."""
    if not hero_short_name:
        return None
    cdn_name = get_cdn_hero_name(hero_short_name)
    cache_dir = HERO_PORTRAIT_DIR
    cache_file = cache_dir / f"{cdn_name}.webp"
    if cache_file.exists():
        try:
            return cache_file.read_bytes()
        except Exception:
            pass

    if hero_short_name != cdn_name:
        cache_file_local = cache_dir / f"{hero_short_name}.webp"
        if cache_file_local.exists():
            try:
                return cache_file_local.read_bytes()
            except Exception:
                pass

    # Special fallback: doom_bringer has the same portrait as doom
    if hero_short_name == "doom" or cdn_name == "doom":
        cache_file_doombringer = cache_dir / "doom_bringer.webp"
        if cache_file_doombringer.exists():
            try:
                return cache_file_doombringer.read_bytes()
            except Exception:
                pass

    # Special fallback: magnataur has the same portrait as magnus
    if hero_short_name == "magnus" or cdn_name == "magnus":
        cache_file_magnataur = cache_dir / "magnataur.webp"
        if cache_file_magnataur.exists():
            try:
                return cache_file_magnataur.read_bytes()
            except Exception:
                pass

    return None


async def get_cached_hero_portrait(hero_short_name: str) -> Image.Image | None:
    """Async load hero portrait with disk cache."""
    if not hero_short_name:
        return None

    cdn_name = get_cdn_hero_name(hero_short_name)
    cache_file = HERO_PORTRAIT_DIR / f"{cdn_name}.webp"

    if cache_file.exists():
        try:
            return Image.open(cache_file).convert("RGBA")
        except Exception:
            logger.exception("Failed to load cached hero portrait")
    
    if hero_short_name != cdn_name:
        cache_file_local = HERO_PORTRAIT_DIR / f"{hero_short_name}.webp"
        if cache_file_local.exists():
            try:
                return Image.open(cache_file_local).convert("RGBA")
            except Exception:
                logger.exception("Failed to load cached hero portrait (local)")

    # Special fallback: doom_bringer has the same portrait as doom
    if hero_short_name == "doom" or cdn_name == "doom":
        cache_file_doombringer = HERO_PORTRAIT_DIR / "doom_bringer.webp"
        if cache_file_doombringer.exists():
            try:
                return Image.open(cache_file_doombringer).convert("RGBA")
            except Exception:
                logger.exception("Failed to load cached hero portrait (doom_bringer fallback)")

    # Special fallback: magnataur has the same portrait as magnus
    if hero_short_name == "magnus" or cdn_name == "magnus":
        cache_file_magnataur = HERO_PORTRAIT_DIR / "magnataur.webp"
        if cache_file_magnataur.exists():
            try:
                return Image.open(cache_file_magnataur).convert("RGBA")
            except Exception:
                logger.exception("Failed to load cached hero portrait (magnataur fallback)")

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
    Холст фиксированный (иконки как ранье). Фон ImgBB — оригинальные пиксели, без resize.
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
            bg_path = get_banner_path("heroes_profil")
            if isinstance(bg_path, Path) and bg_path.exists():
                data = bg_path.read_bytes()
            else:
                try:
                    resp = httpx.get(str(bg_path), timeout=12)
                    if resp.status_code == 200 and resp.content:
                        data = resp.content
                        try:
                            cache_file.parent.mkdir(parents=True, exist_ok=True)
                            cache_file.write_bytes(data)
                        except Exception:
                            pass
                except Exception:
                    pass

        if not data:
            return _heroes_strip_gradient(canvas_width, canvas_height)

        nat = Image.open(io.BytesIO(data)).convert("RGB")
        nat = nat.resize((canvas_width, canvas_height), Image.LANCZOS)
        return nat
    except Exception as e:
        logger.debug(f"heroes strip background: {e}")
        return _heroes_strip_gradient(canvas_width, canvas_height)


async def get_heroes_data_async() -> dict:
    """Получить данные всех героев из OpenDota (с кешированием)"""
    cached = _get_cached("heroes_data")
    if cached:
        return cached

    local = get_local_heroes_data()

    try:
        url = f"{OPENDOTA_API_URL}/heroes"
        data = await _api_get_async(url)
        if not data:
            # Rate limited or offline. The bundled catalog keeps hero names,
            # roles and image paths available, so the UI still renders.
            logger.warning(
                "OpenDota /heroes unavailable, using local catalog "
                f"({len(local)} heroes)"
            )
            return local

        heroes = {}
        for hero in data:
            hero_id = hero["id"]
            short_name = hero["name"].replace("npc_dota_hero_", "")
            cdn_name = get_cdn_hero_name(short_name)
            heroes[hero_id] = {
                "id": hero_id,
                "name": hero["localized_name"],
                "short_name": short_name,
                "image_url": str(Path(HERO_IMAGE_BASE) / f"{cdn_name}.webp"),
                "icon_url": str(Path(HERO_ICON_BASE) / f"{cdn_name}.webp"),
                "img": str(Path(HERO_IMAGE_BASE) / f"{cdn_name}.webp"),
                # Roles drive position detection for heroes missing from the
                # manual table, so keep them rather than dropping them.
                "roles": hero.get("roles", []),
            }

        _set_cached("heroes_data", heroes)
        logger.info(f"Loaded {len(heroes)} heroes from OpenDota")
        return heroes
    except Exception as e:
        logger.error(f"get_heroes_data_async error: {e}", exc_info=True)
        if local:
            logger.warning(f"Falling back to local hero catalog ({len(local)} heroes)")
            return local
        return {}


def get_heroes_data() -> dict:
    """Синхронная обёртка для обратной совместимости"""
    try:
        return _run_async(get_heroes_data_async())
    except TimeoutError:
        # Must not return an empty dict: callers derive hero names, roles and
        # image paths from this, and empty roles collapse every hero into
        # SUPPORT, which empties four of the five infographic columns.
        logger.warning("get_heroes_data timeout")
        return get_local_heroes_data()


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

        heroes_data = await asyncio.to_thread(get_heroes_data)
        if not heroes_data:
            return []

        from collections import Counter
        hero_counts = Counter()
        for match in matches:
            hero_id = match.get("hero_id")
            if hero_id:
                hero_counts[hero_id] += 1

        result = []
        for hero_id, count in hero_counts.most_common():
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
                if len(result) >= top_k:
                    break

        _heroes_image_cache[cache_key] = (result, time.time())
        return result
    except Exception as e:
        logger.error(f"get_top_heroes_async error: {e}", exc_info=True)
        return []


def _get_week_start_utc():
    """Понедельник 00:00 MSK — начало игровой недели (UTC)."""
    from datetime import datetime, timedelta, timezone
    MSK = timezone(timedelta(hours=3))
    UTC = timezone.utc
    today_msk = datetime.now(MSK)
    monday_msk = today_msk - timedelta(days=today_msk.weekday())
    week_start_msk = monday_msk.replace(hour=0, minute=0, second=0, microsecond=0)
    return week_start_msk.astimezone(UTC)


def _get_week_start_str() -> str:
    """Возвращает понедельник текущей недели как 'YYYY-MM-DD' (в часовом поясе МСК).

    Используется для week_start_date в БД, чтобы запросы в
    announce_weekly_mmr_winner находили игроков текущей недели.
    """
    from datetime import datetime, timedelta, timezone
    MSK = timezone(timedelta(hours=3))
    today_msk = datetime.now(MSK)
    monday_msk = today_msk - timedelta(days=today_msk.weekday())
    return monday_msk.replace(hour=0, minute=0, second=0, microsecond=0).strftime("%Y-%m-%d")


def get_week_top_heroes(steam_id: int, top_k: int = 5, match_limit: int = 50) -> list:
    """Топ героев игрока за текущую неделю (по числу игр)."""
    from collections import Counter
    from datetime import datetime

    try:
        week_start_utc = _get_week_start_utc()
        matches = get_recent_matches(steam_id, limit=match_limit)
        if not matches:
            return []

        heroes_data = get_heroes_data()
        if not heroes_data:
            return []

        hero_counts = Counter()
        for match in matches:
            match_date = datetime.fromtimestamp(match.get("start_time", 0), tz=UTC)
            if match_date >= week_start_utc:
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
        return result
    except Exception as e:
        logger.error(f"get_week_top_heroes error: {e}", exc_info=True)
        return []


async def get_week_top_heroes_async(steam_id: int, top_k: int = 5, match_limit: int = 50) -> list:
    """Асинхронно получить топ героев игрока за текущую неделю."""
    from collections import Counter
    from datetime import datetime

    try:
        week_start_utc = _get_week_start_utc()
        matches = await get_recent_matches_async(steam_id, limit=match_limit)
        if not matches:
            return []

        heroes_data = await asyncio.to_thread(get_heroes_data)
        if not heroes_data:
            return []

        hero_counts = Counter()
        for match in matches:
            match_date = datetime.fromtimestamp(match.get("start_time", 0), tz=UTC)
            if match_date >= week_start_utc:
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
        return result
    except Exception as e:
        logger.error(f"get_week_top_heroes_async error: {e}", exc_info=True)
        return []


def _draw_hero_squares_on_card(img, draw, top_heroes: list, base_height: int, width: int):
    """Добавить квадратики героев внизу карточки без расширения изображения."""
    from PIL import Image
    import io

    if not top_heroes:
        return img, draw

    heroes = sorted(top_heroes, key=lambda h: h.get("picks", 0), reverse=True)[:5]
    n = len(heroes)
    icon_size = 82
    gap = 12
    total_w = n * icon_size + max(0, n - 1) * gap
    start_x = max(10, (width - total_w) // 2) + 175
    y = base_height - icon_size - 28

    for hero in heroes:
        hero_short = hero.get("short_name", "")
        icon_data = None
        if hero_short:
            icon_data = get_hero_portrait_cached(hero_short) or get_hero_icon_cached(hero_short)

        if icon_data:
            try:
                icon = Image.open(io.BytesIO(icon_data)).convert("RGBA")
                w, h = icon.size
                side = min(w, h)
                left = (w - side) // 2
                top = (h - side) // 2
                icon = icon.crop((left, top, left + side, top + side))
                icon = icon.resize((icon_size, icon_size), Image.LANCZOS)
                img.paste(icon, (start_x, y), icon)
            except Exception:
                draw.rectangle([start_x, y, start_x + icon_size, y + icon_size], fill=(55, 45, 70))
        else:
            draw.rectangle([start_x, y, start_x + icon_size, y + icon_size], fill=(55, 45, 70))

        draw.rectangle(
            [start_x - 1, y - 1, start_x + icon_size + 1, y + icon_size + 1],
            outline=(215, 175, 85),
            width=2,
        )

        start_x += icon_size + gap

    return img, draw


def generate_heroes_image(top_heroes: list) -> bytes | None:
    """Сгенерировать картинку с иконками топ-героев: иконки как раньше, но фиксированная сетка 10 позиций."""
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

        target_width = 1744
        target_height = 592
        img = _compose_heroes_strip_background(target_width, target_height)

        icon_size = 210
        gap = 18
        padding = 100

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
            sz = int(round(icon_size + (icon_size // 2) * ratio))
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
    return round(wins / games * 100) if games > 0 else 0


# ========================
# 🎯 MMR (примерный)
# ========================

def rank_to_mmr(rank_tier: int) -> int:
    if not rank_tier:
        return 0

    tier = min(rank_tier // 10, 8)
    star = rank_tier % 10

    _MMR_TABLE = {
        1: [0, 150, 300, 460, 610, 760, 0, 0, 0, 0],
        2: [0, 920, 1080, 1230, 1400, 1570, 0, 0, 0, 0],
        3: [0, 1700, 1850, 2000, 2150, 2300, 0, 0, 0, 0],
        4: [0, 2450, 2610, 2770, 2930, 3090, 0, 0, 0, 0],
        5: [0, 3230, 3390, 3540, 3700, 3860, 0, 0, 0, 0],
        6: [0, 4000, 4150, 4300, 4460, 4620, 0, 0, 0, 0],
        7: [0, 4820, 5020, 5220, 5420, 5620, 0, 0, 0, 0],
        8: [0, 5620, 5620, 5620, 5620, 5620, 0, 0, 0, 0],
    }

    row = _MMR_TABLE.get(tier)
    if not row:
        return 0
    return row[star] if star < len(row) else row[-1]


MMR_RANK_THRESHOLDS = [
    (150, 11), (300, 12), (460, 13), (610, 14), (760, 15),
    (920, 21), (1080, 22), (1230, 23), (1400, 24), (1570, 25),
    (1700, 31), (1850, 32), (2000, 33), (2150, 34), (2300, 35),
    (2450, 41), (2610, 42), (2770, 43), (2930, 44), (3090, 45),
    (3230, 51), (3390, 52), (3540, 53), (3700, 54), (3860, 55),
    (4000, 61), (4150, 62), (4300, 63), (4460, 64), (4620, 65),
    (4820, 71), (5020, 72), (5220, 73), (5420, 74), (5620, 75),
    (5620, 81), (5620, 82), (5620, 83), (5620, 84), (5620, 85),
]


def mmr_to_rank_tier(mmr: int) -> int:
    """Convert MMR to rank_tier using the exact MMR table."""
    if not mmr or mmr <= 0:
        return 0

    best_rank = 0
    for threshold, rank in MMR_RANK_THRESHOLDS:
        if mmr >= threshold:
            best_rank = rank
        else:
            break
    return best_rank


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

async def search_player_async(nickname: str) -> dict:
    try:
        url = f"{OPENDOTA_API_URL}/search"

        data = await _api_get_async(url, {"q": nickname})
        if not data:
            return None

        player = data[0]
        account_id = player.get("account_id")

        if not account_id:
            return None

        steam_id = account_id_to_steam64(account_id)
        stats = await get_player_stats_async(steam_id)

        if not stats:
            return None

        # Обновляем никнейм из результатов поиска
        stats["nickname"] = player.get("personaname", stats.get("nickname", "Unknown"))

        return {
            "steam_id": steam_id,
            **stats
        }

    except Exception:
        logger.error("search_player_async error", exc_info=True)
        return None


def search_player(nickname: str) -> dict:
    """Синхронная обёртка для обратной совместимости"""
    try:
        return _run_async(search_player_async(nickname))
    except TimeoutError:
        logger.warning(f"search_player timeout for {nickname}")
        return None


# ========================
# 🎮 MATCHES
# ========================

def get_recent_matches(steam_id: int, limit: int = 5) -> list:
    """Синхронная обёртка для обратной совместимости"""
    try:
        return _run_async(get_recent_matches_async(steam_id, limit))
    except TimeoutError:
        logger.warning(f"get_recent_matches timeout for steam_id={steam_id}, returning empty list")
        return []


RANKED_LOBBY_TYPE = 7
TURBO_GAME_MODE = 23


def is_ranked_match(match: dict) -> bool:
    """True for ranked All Pick / Turbo-excluded matchmaking games.

    Turbo is matched inside the ranked lobby (lobby_type 7) but is not ranked
    play, so it has to be dropped separately or it pollutes hero meta and the
    weekly top-MMR win rate. A missing lobby_type is treated as ranked: the
    OpenDota query already asked for lobby_type=7, so such a row still came
    back from the ranked pool.
    """
    if match.get("game_mode") == TURBO_GAME_MODE:
        return False
    return match.get("lobby_type") in (None, RANKED_LOBBY_TYPE)


async def get_recent_matches_async(steam_id: int, limit: int = 5) -> list:
    """Асинхронно получить последние РЕЙТИНГОВЫЕ матчи игрока."""
    if steam_id is None:
        return []

    cached = _user_matches_cache.get(steam_id)
    if cached:
        cached_data, cached_time = cached
        # Отдаём срезу кэша, только если в нём не меньше матчей,
        # чем просят: иначе пришлось бы качать заново.
        if (time.time() - cached_time < USER_MATCHES_CACHE_TTL
                and len(cached_data) >= limit):
            return cached_data[:limit]

    try:
        account_id = steam64_to_account_id(steam_id)
        url = f"{OPENDOTA_API_URL}/players/{account_id}/matches"

        # Use negative cache to avoid retrying on transient failures within 60s
        if _is_not_found(url):
            logger.debug(f"Recent matches: {steam_id} in negative cache, returning empty")
            return []

        start_time = time.time()
        max_wait = 25
        matches = None
        while matches is None and (time.time() - start_time) < max_wait:
            # lobby_type=7 restricts the response to ranked games server-side;
            # is_ranked_match then drops Turbo, which shares that lobby type.
            matches = await _api_get_async(url, {
                "limit": limit,
                "sort": "-start_time",
                "lobby_type": RANKED_LOBBY_TYPE,
            })
            if matches is None:
                await asyncio.sleep(5)

        if matches is None:
            # Отличаем «игрока нет» от «сервис лежит»: при 521/522
            # запрос помечался как not-found, и страница истории
            # оставалась пустой, пока OpenDota не поднимался.
            if is_opendota_rate_limited() or not _circuit_breaker_can_execute():
                logger.debug(
                    "Recent matches: OpenDota недоступен, не помечаем "
                    f"игрока {steam_id} как отсутствующего"
                )
                return []
            # Настоящий 404: не будем дёргать API ещё минуту.
            _mark_not_found(url)
            return []

        ranked = [m for m in matches if is_ranked_match(m)]
        dropped = len(matches) - len(ranked)
        if dropped:
            logger.info(
                f"get_recent_matches_async: steam_id={steam_id} dropped {dropped} "
                f"non-ranked matches out of {len(matches)}"
            )

        # В кеш кладём максимум из нового и уже лежавшего: запрос с
        # маленьким лимитом не должен вытеснять выкачанное раньше.
        prev = _user_matches_cache.get(steam_id)
        if prev and len(prev[0]) > len(ranked):
            return prev[0][:limit]
        _user_matches_cache[steam_id] = (ranked, time.time())
        return ranked
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


async def is_win_api_async(match_id: int, steam_id: int) -> bool:
    """Определить, выиграл ли игрок в матче по ID матча (через API)"""
    try:
        account_id = steam64_to_account_id(steam_id)
        url = f"{OPENDOTA_API_URL}/matches/{match_id}"

        match_data = await _api_get_async(url)
        if not match_data:
            return False

        players = match_data.get("players", [])

        for player in players:
            if player.get("account_id") == account_id:
                return player.get("win", 0) == 1

        return False
    except Exception as e:
        logger.error(f"is_win_api_async error: {e}", exc_info=True)
        return False


def is_win_api(match_id: int, steam_id: int) -> bool:
    """Синхронная обёртка для обратной совместимости"""
    try:
        return _run_async(is_win_api_async(match_id, steam_id))
    except TimeoutError:
        logger.warning(f"is_win_api timeout for match_id={match_id}, steam_id={steam_id}")
        return False


# ========================
# 📊 GET STATS
# ========================

async def get_player_stats_async(steam_id: int, use_cache: bool = True, timeout: int = 5, max_retries: int = 1) -> dict:
    """Асинхронно получить статистику игрока (последние матчи, герои, винрейт) из OpenDota с кэшем."""
    try:
        cache_key = f"player_{steam_id}"
        if use_cache:
            cached = _get_cached(cache_key)
            if cached:
                return cached

        account_id = steam64_to_account_id(steam_id)
        players_url = f"{OPENDOTA_API_URL}/players/{account_id}"

        if _is_not_found(players_url):
            logger.debug(f"Player {account_id} known not found (negative cache), skipping API")
            if use_cache:
                cached = _get_cached(cache_key)
                if cached:
                    return cached
            return None

        player_data, wl_data = await asyncio.gather(
            _api_get_async(players_url, timeout=timeout, max_retries=max_retries),
            _api_get_async(f"{OPENDOTA_API_URL}/players/{account_id}/wl", timeout=timeout, max_retries=max_retries),
        )
        if not player_data or not isinstance(player_data, dict):
            logger.warning(f"Player data not found for account_id: {account_id}")
            logger.warning(f"API URL used: {OPENDOTA_API_URL}/players/{account_id}")
            if use_cache:
                cached = _get_cached(cache_key)
                if cached:
                    logger.info(f"Returning cached stats for {steam_id} due to API failure")
                    return cached
            return None

        profile = player_data.get("profile") or {}
        rank_tier = player_data.get("rank_tier") or 0

        if wl_data and isinstance(wl_data, dict):
            wins = wl_data.get("win", 0)
            losses = wl_data.get("lose", 0)
            total_games = wins + losses
        else:
            logger.warning(f"Win/Loss data not found for account_id: {account_id}")
            wins = 0
            losses = 0
            total_games = 0

        solo_mmr = player_data.get("solo_competitive_mmr")
        mmr_estimate = player_data.get("mmr_estimate") or {}
        computed_mmr = player_data.get("computed_mmr")
        if solo_mmr and solo_mmr > 0:
            mmr = solo_mmr
        elif computed_mmr and computed_mmr > 0:
            mmr = int(round(computed_mmr))
        elif mmr_estimate.get("estimate"):
            mmr = mmr_estimate.get("estimate", 0)
        elif rank_tier:
            mmr = rank_to_mmr(rank_tier)
        else:
            mmr = 0

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

        # Cache avatar for hero meta infographic
        avatar_url = result.get("avatar")
        if avatar_url:
            await _cache_avatar(steam_id, avatar_url)

        _set_cached(cache_key, result)
        return result

    except Exception as e:
        logger.error(f"stats error: {e}", exc_info=True)
        if use_cache:
            cached = _get_cached(cache_key)
            if cached:
                logger.info(f"Returning cached stats for {steam_id} due to exception: {e}")
                return cached
        return None


def get_player_stats(steam_id: int, use_cache: bool = True, timeout: int = 5) -> dict:
    """Синхурная обёртка для обратной совместимости"""
    try:
        return _run_async(get_player_stats_async(steam_id, use_cache, timeout), timeout=50)
    except TimeoutError:
        logger.warning(f"get_player_stats timeout for steam_id={steam_id}")
        return None


# ========================
# 🔗 REGISTER
# ========================

def _ensure_user_exists(telegram_id: int) -> dict | None:
    from database import Database, _save_user_to_db_immediately, get_user, user_cache

    user = get_user(telegram_id)
    if user:
        return user

    Database().register_user(telegram_id, None, None, source="register_steam")
    user = get_user(telegram_id)
    if user:
        user_cache.set(telegram_id, user)
        _save_user_to_db_immediately(telegram_id, user)
    return user


def _fetch_player_stats(steam_id: int) -> dict | None:
    account_id = steam64_to_account_id(steam_id)
    _clear_not_found(f"{OPENDOTA_API_URL}/players/{account_id}")
    stats = get_player_stats(steam_id)
    if not stats:
        return None

    total_games = stats.get("total_games") or 0
    mmr = stats.get("mmr") or 0
    if total_games == 0 and mmr == 0:
        return None

    return stats


def _classify_stats(stats: dict) -> tuple[bool, bool]:
    is_private = (stats.get("total_games") or 0) == 0 and (stats.get("mmr") or 0) == 0
    is_invalid = stats.get("nickname") == "Unknown"
    return is_invalid, is_private


def _transfer_existing_binding(telegram_id: int, steam_id: int, existing_user: dict) -> str:
    existing_tid = existing_user.get("telegram_id")
    existing_username = (
        existing_user.get("username") or existing_user.get("steam_nickname") or "другой игрок"
    )

    logger.info(f"Transferring Steam {steam_id} from user {existing_tid} to {telegram_id}")

    from database import user_cache

    update_user_fields_batch(
        existing_tid,
        {"steam_id": None, "steam_nickname": None, "avatar": None},
        update_top_cache=False,
    )
    with user_cache._lock:
        if steam_id in user_cache._steam_index:
            del user_cache._steam_index[steam_id]

    return existing_username


def _apply_private_profile_binding(telegram_id: int, steam_id: int, stats: dict) -> dict:
    update_user_fields_batch(telegram_id, {
        "steam_id": steam_id,
        "steam_nickname": stats.get("nickname"),
        "avatar": stats.get("avatar"),
        "mmr": 0,
        "rank_tier": 0,
        "wins": 0,
        "losses": 0,
        "week_start_date": _get_week_start_str(),
    })
    return {
        "success": True,
        "private_profile": True,
        "message": "✅ Аккаунт привязан! Но история матчей в Dota 2 закрыта.\n\nЧтобы бот видел ваши матчи, MMR и обновлял статистику:\n⚙️ Настройки → Сообщество → Настройки → Общедоступная история матчей → Включить",
    }


def _apply_normal_binding(telegram_id: int, steam_id: int, stats: dict) -> dict:
    update_user_fields_batch(telegram_id, {
        "steam_id": steam_id,
        "steam_nickname": stats["nickname"],
        "avatar": stats.get("avatar"),
        "mmr": stats.get("mmr", 0),
        "rank_tier": stats.get("rank_tier", 0),
        "wins": stats.get("wins", 0),
        "losses": stats.get("losses", 0),
        "week_start_date": _get_week_start_str(),
    })
    update_user_mmr(telegram_id)

    rank_tier = stats.get("rank_tier", 0)
    rank_str = rank_to_string(rank_tier)
    wins = stats.get("wins", 0)
    losses = stats.get("losses", 0)
    total = wins + losses
    winrate = round(stats.get("winrate", 0))

    return {
        "success": True,
        "message": f"✅ {stats['nickname']} | {rank_str}\n📊 {total} игр | ✅ {wins} | ❌ {losses} | {winrate}%",
    }


def _handle_existing_binding(
    telegram_id: int,
    steam_id: int,
    existing_user: dict,
    private_profile: bool,
) -> dict | None:
    from database import user_cache

    existing_user = get_user_by_steam_id(steam_id)
    if not existing_user or existing_user.get("telegram_id") != telegram_id:
        return None

    existing_username = _transfer_existing_binding(telegram_id, steam_id, existing_user)

    if private_profile:
        return {
            "success": True,
            "message": (
                f"⚠️ Steam аккаунт был привязан к {existing_username}\n"
                "Автоматически перенесён на ваш аккаунт.\n\n"
                "Ваш Dota 2 профиль закрыт. Чтобы бот мог обновлять статистику:\n"
                "⚠️ В игре: \nнастройки → сообщество → настройки → общедоступная история матчей → включить"
            ),
        }

    return {
        "success": True,
        "message": (
            f"⚠️ Steam аккаунт был привязан к {existing_username}\n"
            "Автоматически перенесён на ваш аккаунт.\n"
            "Старые данные утрачены."
        ),
    }


def register_steam(telegram_id: int, identifier: str) -> dict:
    """Привязать Steam-аккаунт к пользователю: парсит identifier, сохраняет steam_id/nickname, делает первый апдейт MMR."""
    try:
        logger.info(f"Registering Steam for user {telegram_id} with identifier: {identifier}")

        _ensure_user_exists(telegram_id)

        steam_id = parse_steam_identifier(identifier)
        logger.info(f"Parsed steam_id: {steam_id}")

        if steam_id:
            stats = _fetch_player_stats(steam_id)
            logger.info(f"Player stats result: {stats is not None}")

            if not stats:
                private_profile = True
                invalid_stats = True
            else:
                invalid_stats, private_profile = _classify_stats(stats)

            if invalid_stats or private_profile:
                existing_result = _handle_existing_binding(
                    telegram_id, steam_id, {}, private_profile
                )
                if existing_result:
                    return existing_result

                if private_profile:
                    update_user_fields_batch(telegram_id, {
                        "steam_id": steam_id,
                        "mmr": 0,
                        "rank_tier": 0,
                        "wins": 0,
                        "losses": 0,
                        "week_start_date": _get_week_start_str(),
                    })
                    return {
                        "success": True,
                        "private_profile": True,
                        "message": "✅ Аккаунт привязан! Но история матчей в Dota 2 закрыта.\n\nЧтобы бот видел ваши матчи, MMR и обновлял статистику:\n⚙️ Настройки → Сообщество → Настройки → Общедоступная история матчей → Включить",
                    }
                return {
                    "success": True,
                    "message": "✅ Аккаунт привязан! Статистика OpenDota временно недоступна для этого игрока. Попробуйте позже.",
                }

            # Проверяем, не привязан ли уже этот steam_id к другому аккаунту
            existing_user = get_user_by_steam_id(steam_id)
            if existing_user and existing_user.get("telegram_id") != telegram_id:
                existing_username = _transfer_existing_binding(telegram_id, steam_id, existing_user)
                return {
                    "success": True,
                    "message": (
                        f"⚠️ Steam аккаунт был привязан к {existing_username}\n"
                        "Автоматически перенесён на ваш аккаунт.\n"
                        "Старые данные утрачены."
                    ),
                }

            return _apply_normal_binding(telegram_id, steam_id, stats)

        # иначе ищем по никнейму через OpenDota
        logger.info(f"Searching player by nickname: {identifier}")
        data = search_player(identifier)
        logger.info(f"Search result: {data is not None}")
        if not data:
            return {
                "success": False,
                "message": "❌ Игрок с таким ником не найден\n\n💡 Попробуйте:\n• Использовать Steam ID вместо ника\n• Проверить правильность написания\n• Убедиться, что игрок играет в Dota 2",
            }

        steam_id = data["steam_id"]
        stats = data
        private_profile_search = False

        if stats:
            total_games = stats.get("total_games") or 0
            mmr = stats.get("mmr") or 0
            if total_games == 0 and mmr == 0:
                private_profile_search = True

        if private_profile_search:
            return _apply_private_profile_binding(telegram_id, steam_id, stats)

        return _apply_normal_binding(telegram_id, steam_id, stats)

    except Exception as e:
        logger.error(f"register error: {e}", exc_info=True)
        return {"success": False, "message": "❌ Ошибка"}


def unlink_steam(telegram_id: int) -> dict:
    """Раз-prивязать Steam-аккаунт от пользователя.
    
    Позволяет пользователю отвязать свой Steam-аккаунт, чтобы потом привязать другой.
    Например, если пользователь потерял доступ к старому Telegram-аккаунту, который был привязан к Steam.
    """
    try:
        from database import get_user, update_user_fields_batch, user_cache
        user = get_user(telegram_id)

        if not user or not user.get('steam_id'):
            return {"success": False, "message": "❌ Steam-аккаунт не был привязан к вашему аккаунту"}

        steam_id = user.get('steam_id')

        # Очищаем кэш пользователя
        user_cache.invalidate_user_top_caches(telegram_id)
        user_cache.remove(telegram_id)

        # Обнуляем поля, связанные со Steam
        update_user_fields_batch(telegram_id, {
            "steam_id": None,
            "steam_nickname": None,
            "avatar": None,
            "mmr": 0,
            "rank_tier": 0,
            "wins": 0,
            "losses": 0,
            "week_games": 0,
            "week_wins": 0,
        })

        logger.info(f"Steam account {steam_id} unlinked from user {telegram_id}")
        return {
            "success": True,
            "message": "✅ Steam-аккаунт успешно отвязан от вашего Telegram-аккаунта.\nТеперь вы можете привязать другой Steam-аккаунт."
        }
    except Exception as e:
        logger.error(f"unlink_steam error: {e}", exc_info=True)
        return {"success": False, "message": f"❌ Ошибка при отвязке Steam-аккаунта: {e}"}


def get_user_by_telegram_username(username: str) -> dict | None:
    """Найти пользователя по Telegram username (без @)."""
    from database import get_user_by_username
    return get_user_by_username(username)


def admin_unlink_steam(steam_id: int) -> dict:
    """Административная функция: раз-prивязать Steam-аккаунт по его ID.
    
    Используется когда пользователь потерял доступ к старому Telegram-аккаунту,
    который был привязан к Steam.
    
    Args:
        steam_id: Steam ID64 для раз-prивязки
        
    Returns:
        dict с полями success, message, telegram_id (если найден)
    """
    try:
        from database import user_cache

        user = get_user_by_steam_id(steam_id)

        if not user:
            return {"success": False, "message": f"❌ Steam-аккаунт {steam_id} не найден в базе"}

        telegram_id = user.get('telegram_id')

        # Очищаем кэш пользователя
        user_cache.invalidate_user_top_caches(telegram_id)
        user_cache.remove(telegram_id)

        # Обнуляем поля, связанные со Steam
        update_user_fields_batch(telegram_id, {
            "steam_id": None,
            "steam_nickname": None,
            "avatar": None,
            "mmr": 0,
            "rank_tier": 0,
            "wins": 0,
            "losses": 0,
            "week_games": 0,
            "week_wins": 0,
        })

        logger.info(f"Admin: Steam account {steam_id} unlinked from user {telegram_id}")
        return {
            "success": True,
            "message": f"✅ Steam-аккаунт {steam_id} успешно отвязан от Telegram-аккаунта {telegram_id}",
            "telegram_id": telegram_id
        }
    except Exception as e:
        logger.error(f"admin_unlink_steam error: {e}", exc_info=True)
        return {"success": False, "message": f"❌ Ошибка при отвязке Steam-аккаунта: {e}"}


# ========================
# 🔄 UPDATE MMR
# ========================

def update_user_mmr(telegram_id: int, update_top_cache: bool = True) -> dict:
    """Обновить MMR/ранг/недельную статистику пользователя из OpenDota. Возвращает dict с ключами success/mmr/rank_up/steam_nickname/week_*."""
    try:
        user = get_user(telegram_id)
        if not user or not user.get("steam_id"):
            return {"success": False, "rank_up": None}

        steam_id = user["steam_id"]
        last_updated = user.get("mmr_last_updated")
        if last_updated and isinstance(last_updated, (int, float)) and time.time() - last_updated < 12 * 3600:
            recent_check = get_recent_matches(steam_id, limit=1)
            if not recent_check:
                return {"success": True, "skipped": True, "mmr": user.get("mmr", 0)}

        matches = get_recent_matches(user["steam_id"], limit=50)
        logger.info(f"topmmr: Got {len(matches)} matches for hero meta from steam_id={user.get('steam_id')}")

        # Skip heavy player stats API calls (2 requests) if MMR was refreshed recently.
        # We still need matches for weekly stats, but player profile data rarely changes
        # in 4 hours. Use DB values instead of 2 OpenDota API calls.
        last_updated = user.get('mmr_last_updated')
        recently_updated = last_updated and isinstance(last_updated, (int, float)) and time.time() - last_updated < 4 * 3600

        if recently_updated:
            logger.info(f"topmmr: recently updated (<4h) for user {telegram_id}, using DB stats (saving 2 API calls)")
            stats = {
                "nickname": user.get("username") or user.get("steam_nickname") or "Unknown",
                "avatar": user.get("avatar"),
                "mmr": user.get("mmr", 0),
                "rank_tier": user.get("rank_tier", 0),
                "total_games": 0,
                "wins": 0,
                "losses": 0,
                "winrate": 0,
            }
        else:
            players_url = f"{OPENDOTA_API_URL}/players/{steam64_to_account_id(user['steam_id'])}"
            if _is_not_found(players_url):
                logger.info(f"topmmr: player {user['steam_id']} known not found, skipping")
            elif not _circuit_breaker_can_execute():
                logger.info(f"topmmr: circuit breaker open for {user['steam_id']}, skipping")
            else:
                stats = get_player_stats(user["steam_id"], use_cache=False)
                logger.info(f"topmmr: get_player_stats returned: steam32={user.get('steam_id')}, success={stats is not None}")

        if not stats:
            logger.warning(f"topmmr: API failed for user {telegram_id}, using cached data")
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
                    else:
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

                        # Определяем победу используя radiant_win (приоритет) или player_slot
                        player_slot = match.get("player_slot")
                        radiant_win = match.get("radiant_win", False)

                        # Игрок находится в Radiant, если player_slot < 128
                        player_is_radiant = player_slot < 128 if player_slot is not None else True

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
                except Exception as e:
                    logger.debug(f"Error processing match {match.get('match_id')}: {e}")

        # Save matches to public_player_matches for hero meta
        if matches:
            logger.info(f"topmmr: Saving {len(matches)} matches to public_player_matches for hero meta (steam_id={user.get('steam_id')})")
            conn = None
            try:
                from database import DATABASE_URL, get_connection, release_pg_connection, urlparse
                conn = get_connection()
                url = urlparse.urlparse(DATABASE_URL)
                scheme = url.scheme
                cursor = conn.cursor()
                if "postgres" in scheme:
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
                    cursor.execute("""
                        CREATE TABLE IF NOT EXISTS public_player_matches (
                            match_id BIGINT UNIQUE,
                            hero_id INTEGER,
                            player_slot INTEGER,
                            radiant_win INTEGER,
                            start_time INTEGER,
                            steam_id BIGINT,
                            lane_role SMALLINT
                        )
                        """)
                    # CREATE TABLE IF NOT EXISTS is a no-op on a table that
                    # already exists, so lane_role never reaches databases
                    # created before the column was added - which is every
                    # deployed one. Without this ALTER every hero-meta INSERT
                    # fails with: column "lane_role" does not exist.
                    cursor.execute("""
                        ALTER TABLE public_player_matches
                            ADD COLUMN IF NOT EXISTS lane_role SMALLINT
                        """)
                    # KDA и длительность нужны странице истории игр: она читает эту же
                    # таблицу вместо повторного запроса в OpenDota.
                    cursor.execute("""
                        ALTER TABLE public_player_matches
                            ADD COLUMN IF NOT EXISTS kills INTEGER
                    """)
                    cursor.execute("""
                        ALTER TABLE public_player_matches
                            ADD COLUMN IF NOT EXISTS deaths INTEGER
                    """)
                    cursor.execute("""
                        ALTER TABLE public_player_matches
                            ADD COLUMN IF NOT EXISTS assists INTEGER
                    """)
                    cursor.execute("""
                        ALTER TABLE public_player_matches
                            ADD COLUMN IF NOT EXISTS duration INTEGER
                    """)
                    for match in matches:
                        match_id = match.get("match_id")
                        hero_id = match.get("hero_id", 0)
                        player_slot = match.get("player_slot")
                        radiant_win_api = match.get("radiant_win")
                        # Store API radiant_win as-is (Radiant team won = 1/True, Dire won = 0/False)
                        # player_slot is saved separately; hero meta SQL derives player win from both
                        radiant_win_int = 1 if radiant_win_api else 0
                        start_time = match.get("start_time")
                        steam_id = user.get("steam_id")
                        logger.info(f"topmmr: Hero meta saving - match_id={match_id}, hero_id={hero_id}, radiant_win={radiant_win_int} (api_radiant_win={radiant_win_api}, player_slot={player_slot}), steam_id={steam_id}")
                        lane_role = match.get("lane_role")
                        kda = (match.get("kills"), match.get("deaths"),
                               match.get("assists"), match.get("duration"))
                        if match_id and hero_id is not None and player_slot is not None:
                            # ON CONFLICT DO NOTHING оставлял бы старые строки
                            # без KDA, поэтому обновляем по match_id.
                            cursor.execute("""
                                INSERT INTO public_player_matches
                                    (match_id, hero_id, player_slot, radiant_win,
                                     start_time, steam_id, lane_role,
                                     kills, deaths, assists, duration)
                                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                                ON CONFLICT (match_id) DO UPDATE SET
                                    kills = EXCLUDED.kills,
                                    deaths = EXCLUDED.deaths,
                                    assists = EXCLUDED.assists,
                                    duration = EXCLUDED.duration,
                                    lane_role = EXCLUDED.lane_role
                            """, (match_id, hero_id, player_slot, radiant_win_int,
                                  start_time, steam_id, lane_role, *kda))
                else:
                    cursor.execute("""
                        CREATE TABLE IF NOT EXISTS public_player_matches (
                            match_id INTEGER UNIQUE,
                            hero_id INTEGER,
                            player_slot INTEGER,
                            radiant_win INTEGER,
                            start_time INTEGER,
                            steam_id INTEGER,
                            lane_role INTEGER
                        )
                        """)
                    # SQLite has no ADD COLUMN IF NOT EXISTS, and CREATE TABLE
                    # IF NOT EXISTS skips an existing table entirely - so both
                    # the fresh-file and the legacy-file case need a guarded
                    # ALTER, otherwise the INSERT below names a missing column.
                    cursor.execute("PRAGMA table_info(public_player_matches)")
                    ppm_columns = [c[1] for c in cursor.fetchall()]
                    if ppm_columns and 'lane_role' not in ppm_columns:
                        cursor.execute(
                            "ALTER TABLE public_player_matches ADD COLUMN lane_role INTEGER"
                        )
                    # KDA и длительность нужны странице истории игр.
                    for _col in ("kills", "deaths", "assists", "duration"):
                        if ppm_columns and _col not in ppm_columns:
                            cursor.execute(
                                f"ALTER TABLE public_player_matches "
                                f"ADD COLUMN {_col} INTEGER"
                            )
                    for match in matches:
                        match_id = match.get("match_id")
                        hero_id = match.get("hero_id", 0)
                        player_slot = match.get("player_slot")
                        radiant_win_api = match.get("radiant_win")
                        radiant_win_int = 1 if radiant_win_api else 0
                        start_time = match.get("start_time")
                        steam_id = user.get("steam_id")
                        lane_role = match.get("lane_role")
                        logger.info(f"topmmr: Hero meta saving (SQLite) - match_id={match_id}, hero_id={hero_id}, lane_role={lane_role}, steam_id={steam_id}")
                        kda = (match.get("kills"), match.get("deaths"),
                               match.get("assists"), match.get("duration"))
                        if match_id and hero_id is not None and player_slot is not None:
                            # INSERT OR IGNORE оставлял бы старые строки без KDA,
                            # поэтому дополняем уже записанные.
                            cursor.execute("""
                                INSERT OR IGNORE INTO public_player_matches
                                    (match_id, hero_id, player_slot, radiant_win,
                                     start_time, steam_id, lane_role,
                                     kills, deaths, assists, duration)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """, (match_id, hero_id, player_slot, radiant_win_int,
                                  start_time, steam_id, lane_role, *kda))
                            cursor.execute("""
                                UPDATE public_player_matches SET
                                    kills = ?, deaths = ?, assists = ?,
                                    duration = ?, lane_role = ?
                                WHERE match_id = ?
                            """, (*kda, lane_role, match_id))
                conn.commit()
            except Exception as e:
                logger.warning(f"Failed to save matches to public_player_matches: {e}")
            finally:
                if conn is not None:
                    release_pg_connection(conn)
            # Invalidate hero meta cache so next read gets fresh data
            if matches:
                try:
                    from hero_meta import clear_hero_meta_cache
                    clear_hero_meta_cache()
                except Exception as e:
                    logger.debug(f"Failed to invalidate hero meta cache: {e}")

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

        _ret = None
        if matches:
            logger.info(f"Saved week stats to DB: {week_games} games, {week_wins} wins, week_streak={max_streak}, week_start={week_start_utc}")

            _ret = update_user_fields_batch(telegram_id, {
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
            }, save_to_db=False, update_top_cache=update_top_cache)
        else:
            logger.info("No matches this week, skipping week stats update")
            _ret = update_user_fields_batch(telegram_id, {
                "rank_tier": new_rank_tier,
                "wins": stats.get("wins", 0),
                "losses": stats.get("losses", 0),
                "mmr": stats["mmr"],
                "avatar": stats.get("avatar"),
                "steam_nickname": stats.get("nickname"),
                "mmr_last_updated": time.time()
            }, save_to_db=False, update_top_cache=update_top_cache)

        if rank_up:
            update_user_fields_batch(telegram_id, {"rank_tier": new_rank_tier, "mmr_last_updated": time.time()}, save_to_db=True, update_top_cache=update_top_cache)

        _wg = _ret.get('week_games') if isinstance(_ret, dict) else week_games
        _ww = _ret.get('week_wins') if isinstance(_ret, dict) else week_wins
        _wbs = _ret.get('week_best_streak') if isinstance(_ret, dict) else max_streak
        _wcs = _ret.get('week_current_streak') if isinstance(_ret, dict) else week_current_streak
        return {"success": True, "rank_up": rank_up, "mmr": stats.get("mmr"), "week_games": _wg or 0, "week_wins": _ww or 0, "week_best_streak": _wbs, "week_current_streak": _wcs, "week_start_date": current_week_start}

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
    week_losses: int = 0,
    top_heroes: list = None,
    is_champion: bool = False,
) -> bytes | None:
    """Сгенерировать карточку для /start или чемпиона недели."""
    logger.info(
        f"generate_start_card INPUT: username={username} steam_nickname={steam_nickname} "
        f"rank_tier={rank_tier} week_wins={week_wins} week_losses={week_losses} "
        f"weekly_mvp={weekly_mvp} heroes={len(top_heroes or [])} champion={is_champion}"
    )
    try:
        import io
        import os

        import requests
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

        if is_champion:
            banner_h = 44
            draw.rectangle([0, 0, width, banner_h], fill=(175, 130, 35))
            draw.line([(0, banner_h), (width, banner_h)], fill=(235, 195, 95), width=2)
            try:
                font_banner = ImageFont.truetype(
                    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 28
                )
            except Exception:
                font_banner = ImageFont.load_default()
            banner_text = "ЧЕМПИОН НЕДЕЛИ MMR"
            bbox = draw.textbbox((0, 0), banner_text, font=font_banner)
            text_w = bbox[2] - bbox[0]
            draw.text(
                ((width - text_w) // 2, 8),
                banner_text,
                fill=(255, 248, 220),
                font=font_banner,
            )

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
                    resp = httpx.get(
                        avatar_url,
                        timeout=10,
                        headers={"User-Agent": "fissure-bot/1.0"},
                    )
                    logger.info(f"Avatar request status: {resp.status_code} url={str(avatar_url)[:80]}")
                    if resp.status_code == 200 and resp.content:
                        avatar = Image.open(io.BytesIO(resp.content)).convert("RGBA")
                    else:
                        logger.warning(f"Avatar download failed: status={resp.status_code}, url={str(avatar_url)[:80]}")
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

        rank_icon = None
        rank_icon_size = int(100 * scale)
        if rank_tier > 0:
            tier = rank_tier // 10
            star = rank_tier % 10
            if star == 0:
                star = 5
            if tier == 8:
                star = 5

            cache_key = (tier, star)
            if cache_key in _rank_icons_cache:
                rank_icon = _rank_icons_cache[cache_key].copy()
            else:
                rank_file = Path(__file__).parent / "images" / "ranks" / f"rank_{tier}_{star}.webp"
                if not rank_file.exists():
                    rank_file = Path(__file__).parent / "images" / "ranks" / f"rank_{tier}_{star}.png"
                if rank_file.exists():
                    try:
                        rank_icon = Image.open(rank_file).convert("RGBA")
                        _rank_icons_cache[cache_key] = rank_icon.copy()
                        rank_icon = rank_icon.copy()
                    except Exception:
                        pass

        if rank_icon:
            rank_icon = rank_icon.resize((rank_icon_size, rank_icon_size), Image.LANCZOS)

        username_y = info_y
        username_x_offset = 0
        if username:
            draw.text((info_x + username_x_offset, username_y), f"@{username}", fill=(255, 255, 255), font=font_title)
        elif steam_nickname:
            draw.text((info_x + username_x_offset, username_y), f"{steam_nickname}", fill=(255, 255, 255), font=font_title)

        msg_label_y = username_y + int(50 * scale)
        if week_wins is not None and week_losses is not None:
            draw.text((info_x + username_x_offset, msg_label_y), "За неделю:", fill=(255, 255, 255), font=font_small)
        else:
            draw.text((info_x + username_x_offset, msg_label_y), "Всего сообщений:", fill=(255, 255, 255), font=font_small)

        msg_num_y = msg_label_y + int(28 * scale)
        if week_wins is not None and week_losses is not None:
            wr = round(week_wins / (week_wins + week_losses) * 100) if (week_wins + week_losses) > 0 else 0
            draw.text((info_x + username_x_offset, msg_num_y), f"{week_wins}W/{week_losses}L/{wr}%", fill=(255, 255, 255), font=font_title)
            logger.info(f"generate_start_card: drew week stats {week_wins}W/{week_losses}L/{wr}% for {username or steam_nickname}")
        else:
            draw.text((info_x + username_x_offset, msg_num_y), f"{message_count}", fill=(255, 255, 255), font=font_title)

        if rank_tier > 0 and rank_icon:
            rank_x = avatar_x + avatar_size // 2 - rank_icon_size // 2
            rank_y = avatar_y + avatar_size - rank_icon_size // 2
            img.paste(rank_icon, (rank_x, rank_y), rank_icon)

        if top_heroes:
            img, draw = _draw_hero_squares_on_card(img, draw, top_heroes, height, width)

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
        logger.info(f"generate_top_card: avatar_url={str(avatar_url)[:50] if avatar_url else None}, show_avatar={show_avatar}")
        if avatar_url and show_avatar and str(avatar_url).strip().lower().startswith(('http://', 'https://')):
            try:
                if os.path.isfile(avatar_url):
                    avatar = Image.open(avatar_url).convert("RGBA")
                else:
                    resp = httpx.get(avatar_url, timeout=10, headers={"User-Agent": "fissure-bot/1.0"})
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
            fissure_y = fissure_label_y + int(28 * scale)
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
            if tier == 8:
                star = 5

            cache_key = (tier, star)
            if cache_key in _rank_icons_cache:
                rank_icon = _rank_icons_cache[cache_key].copy()
            else:
                rank_file = Path(__file__).parent / "images" / "ranks" / f"rank_{tier}_{star}.webp"
                if not rank_file.exists():
                    rank_file = Path(__file__).parent / "images" / "ranks" / f"rank_{tier}_{star}.png"
                if rank_file.exists():
                    try:
                        rank_icon = Image.open(rank_file).convert("RGBA")
                        _rank_icons_cache[cache_key] = rank_icon.copy()
                        rank_icon = rank_icon.copy()
                    except Exception as e:
                        logger.warning(f"Exception loading rank icon: {e}")

        if rank_icon:
            rank_icon = rank_icon.resize((rank_icon_size, rank_icon_size), Image.LANCZOS)
            rank_x = avatar_x + avatar_size // 2 - rank_icon_size // 2
            rank_y = avatar_y + avatar_size - rank_icon_size // 2
            img.paste(rank_icon, (rank_x, rank_y), rank_icon)

        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=90)
        buf.seek(0)
        return buf.read()

    except Exception:
        import logging
        logging.exception("generate_top_card error")
        return None


# ========================
# 🎴 ПРОФИЛЬНАЯ КАРТОЧКА — звание, статы, герои недели и награды
# ========================

# Палитра: те же акценты, что на сайте и в утверждённых макетах
_PC_GOLD = (215, 175, 85)
_PC_GOLD_LIGHT = (250, 226, 160)
_PC_ORANGE = (255, 140, 66)
_PC_WHITE = (242, 242, 248)
_PC_GREY = (152, 158, 178)
_PC_PANEL = (22, 26, 42)
_PC_GREEN = (86, 200, 130)
_PC_SILVER = (200, 208, 222)
_PC_BRONZE = (200, 132, 82)
_PC_PURPLE = (168, 130, 255)
_PC_PINK = (240, 120, 170)
_PC_BLUE_GREY = (150, 190, 255)
_PC_DARK = (12, 15, 26)

_profile_font_cache: dict = {}
_profile_bg_cache = None
_profile_hero_cache: dict = {}


def _profile_font(role: str, size: int):
    """Шрифт с поддержкой кириллицы: NotoSans (assets/fonts) → Arial/DejaVu → default."""
    from PIL import ImageFont

    key = (role, int(size))
    cached = _profile_font_cache.get(key)
    if cached is not None:
        return cached

    base = Path(__file__).parent
    noto_regular = base / "assets" / "fonts" / "NotoSans-Regular.ttf"
    noto_bold = base / "assets" / "fonts" / "NotoSans-Bold.ttf"
    if role == "bold":
        candidates = [
            noto_bold,
            Path(r"C:\Windows\Fonts\arialbd.ttf"),
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        ]
    else:
        candidates = [
            noto_regular,
            Path(r"C:\Windows\Fonts\arial.ttf"),
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        ]
    candidates.append(noto_regular)

    font = None
    for path in candidates:
        try:
            if path.exists():
                font = ImageFont.truetype(str(path), int(size))
                break
        except Exception:
            continue
    if font is None:
        font = ImageFont.load_default()
    _profile_font_cache[key] = font
    return font


_profile_glyph_cache: dict = {}


def _profile_supports_glyph(font, char: str) -> bool:
    """Есть ли у шрифта глиф для символа.

    У NotoSans нет, например, «★» (U+2605) — Pillow рисует вместо него .notdef
    («тофу»-квадрат), поэтому такие символы вычищаются из текста карточки.
    """
    key = (id(font), char)
    cached = _profile_glyph_cache.get(key)
    if cached is not None:
        return cached[1]

    supported = True
    try:
        notdef = bytes(font.getmask("\ue001"))
        if notdef:
            supported = bytes(font.getmask(char)) != notdef
    except Exception:
        supported = True
    # Шрифт держим в значении: id() не должен переиспользоваться после GC
    _profile_glyph_cache[key] = (font, supported)
    return supported


def _profile_clean_text(text, font) -> str:
    """Убрать символы, которых нет в шрифте (иначе на карточке «тофу»-квадраты)."""
    text = "" if text is None else str(text)
    if not text:
        return ""
    return "".join(ch for ch in text if not ch.strip() or _profile_supports_glyph(font, ch))


def _profile_radial_mask(width: int, height: int, cx: float, cy: float, radius: float,
                         sharpness: float = 1.0):
    """Мягкая радиальная маска (L). Считается в 1/4 размера и растягивается LANCZOS."""
    small_w = max(8, width // 4)
    small_h = max(8, height // 4)
    s_cx = cx * small_w / max(1, width)
    s_cy = cy * small_h / max(1, height)
    s_radius = max(1.0, radius * small_w / max(1, width))

    data = []
    for y in range(small_h):
        dy = (y - s_cy) / s_radius
        for x in range(small_w):
            dx = (x - s_cx) / s_radius
            dist = (dx * dx + dy * dy) ** 0.5
            value = 1.0 - dist
            data.append(0 if value <= 0 else int(255 * min(1.0, value ** sharpness)))

    mask = Image.new("L", (small_w, small_h))
    mask.putdata(data)
    return mask.resize((width, height), Image.LANCZOS)


def _profile_background():
    """Фон карточки: градиент + 3 свечения + звёздная пыль + винетка (кешируется)."""
    global _profile_bg_cache
    if _profile_bg_cache is not None:
        return _profile_bg_cache

    import random

    from PIL import ImageDraw

    width, height = PROFILE_CARD_W, PROFILE_CARD_H
    img = Image.new("RGB", (width, height), _PC_DARK)
    draw = ImageDraw.Draw(img)

    # Вертикальный градиент (тёмный фэнтези-фон сайта #0a0a0f → #161c2f)
    for y in range(height):
        t = y / max(1, height - 1)
        draw.line([(0, y), (width, y)],
                  fill=(int(10 + 10 * t), int(11 + 13 * t), int(20 + 24 * t)))

    # Свечения: оранжевое (акцент сайта), золотое и синее
    for fx, fy, fr, color, alpha, sharp in (
        (0.10, 0.00, 0.90, _PC_ORANGE, 80, 1.35),
        (0.92, 0.04, 0.58, _PC_GOLD, 44, 1.55),
        (1.02, 1.12, 0.90, (72, 112, 224), 72, 1.35),
    ):
        mask = _profile_radial_mask(width, height, fx * width, fy * height, fr * width, sharp)
        if alpha < 255:
            mask = mask.point(lambda a, alpha=alpha: int(a * alpha / 255))
        img = Image.composite(Image.new("RGB", (width, height), color), img, mask)

    # Опциональная текстура из баннера репозитория (если файл есть) — низкая прозрачность
    try:
        from constants import PROFILE_CARD_BG_FALLBACK

        if PROFILE_CARD_BG_FALLBACK.exists():
            texture = Image.open(PROFILE_CARD_BG_FALLBACK).convert("RGB")
            tw, th = texture.size
            scale = max(width / tw, height / th)
            texture = texture.resize((max(1, int(tw * scale)), max(1, int(th * scale))), Image.LANCZOS)
            tx = (texture.width - width) // 2
            ty = (texture.height - height) // 2
            texture = texture.crop((tx, ty, tx + width, ty + height))
            mask = _profile_radial_mask(width, height, width * 0.5, height * 0.5, width * 0.85)
            mask = mask.point(lambda a: int(a * 42 / 255))
            img = Image.composite(texture, img, mask)
    except Exception as e:
        logger.debug(f"profile card background texture skipped: {e}")

    # Звёздная пыль (детерминированная — карточка стабильна между рендерами)
    rnd = random.Random(20240920)
    stars = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    star_draw = ImageDraw.Draw(stars)
    for _ in range(150):
        sx = rnd.uniform(0, width)
        sy = rnd.uniform(0, height)
        size = rnd.choice([1, 1, 1, 2])
        star_draw.ellipse([sx, sy, sx + size, sy + size],
                          fill=(255, 250, 235, rnd.randint(26, 105)))
    img = Image.alpha_composite(img.convert("RGBA"), stars).convert("RGB")

    # Винетка по краям
    vig = _profile_radial_mask(width, height, width * 0.5, height * 0.42, width * 0.98)
    vig = vig.point(lambda a: int((255 - a) * 0.42))
    img = Image.composite(Image.new("RGB", (width, height), (6, 7, 14)), img, vig)

    _profile_bg_cache = img
    return img
def generate_achievement_banner(key: str, label: str = "", mention: str = "") -> bytes | None:
    """Баннер выдачи ачивки: фон из images/banners/achiv_bg.png + центрированная иконка ачивки.

    - Фон масштабируется `cover` до PROFILE_CARD_W x PROFILE_CARD_H (без искажений, crop).
    - Иконка ачивки (assets/awards/<key>.png) накладывается в ОРИГИНАЛЬНОМ размере,
      смещённая на 5 px влево от центра. Никаких текстовых подписей.
    """
    try:
        import io
        from constants import BANNER_DIR, PROFILE_CARD_W, PROFILE_CARD_H
        from PIL import Image

        width, height = PROFILE_CARD_W, PROFILE_CARD_H

        # 1. Фон — оригинальный размер, cover-crop до 1200x600.
        bg_path = BANNER_DIR / "achiv_bg.png"
        bg = Image.open(bg_path).convert("RGBA")
        bw, bh = bg.size
        scale = max(width / bw, height / bh)
        bw2, bh2 = max(1, int(bw * scale)), max(1, int(bh * scale))
        bg = bg.resize((bw2, bh2), Image.LANCZOS)
        bx = (bw2 - width) // 2
        by = (bh2 - height) // 2
        bg = bg.crop((max(0, bx), max(0, by), max(0, bx) + width, max(0, by) + height))
        canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        canvas.paste(bg, (0, 0), bg)

        # 2. Иконка ачивки — оригинальный размер, центр + 5px влево.
        icon_path = Path(__file__).parent / "assets" / "awards" / f"{key}.webp"
        icon = Image.open(icon_path).convert("RGBA")
        x = (width - icon.width) // 2 - 5
        y = (height - icon.height) // 2
        canvas.paste(icon, (x, y), icon)

        buf = io.BytesIO()
        canvas.convert("RGB").save(buf, format="WEBP", quality=95, method=6)
        return buf.getvalue()
    except Exception as e:
        logger.warning(f"generate_achievement_banner failed: {e}")
        return None




def rank_mmr_threshold(rank_tier: int) -> int:
    """MMR-порог для конкретного звания (МС: «Легенда IV» → rank_tier 54 → 3700).

    Берётся из той же таблицы, что и mmr_to_rank_tier(), поэтому round-trip корректен.
    Звание вида «50» (нулевая звезда) приводится к V-й звезде, как везде в боте.
    """
    try:
        rank_tier = int(rank_tier or 0)
    except (TypeError, ValueError):
        return 0
    if rank_tier <= 0:
        return 0

    tier = min(max(rank_tier // 10, 1), 8)
    star = rank_tier % 10 or PROFILE_CARD_RANKS_PER_TIER
    star = min(star, PROFILE_CARD_RANKS_PER_TIER)
    target = tier * 10 + star
    for threshold, rank in MMR_RANK_THRESHOLDS:
        if rank == target:
            return threshold
    return 0


def rank_progress(rank_tier: int = 0, mmr: int = 0) -> dict:
    """Прогресс по лестнице ЗВАНИЙ (7 тиров × 5 звёзд = 35 шагов) + MMR до следующего звания.

    Возвращает dict:
      tier/star/step/total/frac/left — позиция на лестнице звёзд (полоска «B»);
      name/next                     — текущее и следующее звание (русские названия бота);
      calibrated/maxed              — не калиброван / Титан (вершина);
      mmr/mmr_base/mmr_next/mmr_frac/mmr_left — MMR-прогресс внутри текущего звания (игла «A»).
    """
    try:
        rank_tier = int(rank_tier or 0)
    except (TypeError, ValueError):
        rank_tier = 0
    try:
        mmr = int(mmr or 0)
    except (TypeError, ValueError):
        mmr = 0

    if rank_tier <= 0 and mmr > 0:
        rank_tier = mmr_to_rank_tier(mmr)

    total = PROFILE_CARD_LADDER_TOTAL
    per_tier = PROFILE_CARD_RANKS_PER_TIER
    calibrated = rank_tier > 0 or mmr > 0

    if rank_tier > 0:
        tier = min(max(rank_tier // 10, 1), 8)
        star = rank_tier % 10 or per_tier
        star = min(star, per_tier)
    else:
        tier, star = 0, 0

    if tier >= 8:
        step, frac, left = total, 1.0, 0
        next_name = None
        mmr_base = rank_mmr_threshold(rank_tier)
        mmr_next = None
        mmr_frac = 1.0
    else:
        step = min((tier - 1) * per_tier + star, total) if tier >= 1 else 0
        frac = step / total
        left = max(0, total - step)
        if tier == 0:
            next_rank_tier = 11                      # Рекрут I
        elif star < per_tier:
            next_rank_tier = rank_tier + 1
        else:
            next_rank_tier = (tier + 1) * 10 + 1
        next_name = rank_to_string(next_rank_tier)
        mmr_base = rank_mmr_threshold(rank_tier) if rank_tier > 0 else 0
        mmr_next = rank_mmr_threshold(next_rank_tier)
        if mmr_next <= mmr_base:
            mmr_frac = 1.0
        else:
            mmr_frac = min(1.0, max(0.0, (mmr - mmr_base) / (mmr_next - mmr_base)))

    if mmr_next is None:
        mmr_left = 0
    else:
        mmr_left = max(0, mmr_next - mmr)

    return {
        "rank_tier": rank_tier,
        "tier": tier,
        "star": star,
        "step": step,
        "total": total,
        "frac": frac,
        "left": left,
        "name": rank_to_string(rank_tier),
        "next": next_name,
        "calibrated": calibrated,
        "maxed": tier >= 8,
        "mmr": mmr,
        "mmr_base": mmr_base,
        "mmr_next": mmr_next,
        "mmr_frac": mmr_frac,
        "mmr_left": mmr_left,
    }


def _profile_num(value) -> str:
    """1234567 → «1 234 567» (узкие пробелы вместо запятых)."""
    try:
        return f"{int(value):,}".replace(",", " ")
    except (TypeError, ValueError):
        return "—"


def _profile_percent(wins: int, games: int) -> str:
    """Винрейт в процентах; 0 игр → «—»."""
    try:
        games = int(games or 0)
        wins = int(wins or 0)
    except (TypeError, ValueError):
        return "—"
    if games <= 0:
        return "—"
    return f"{round(wins / games * 100)}%"


def _profile_streak_sub(current_streak, best_streak) -> str | None:
    """Подпись к плитке «СТРИК»: рекорд с учётом текущей серии (иначе «лучший 0»)."""
    def _num(value):
        try:
            return max(0, int(value or 0))
        except (TypeError, ValueError):
            return 0

    best = max(_num(current_streak), _num(best_streak))
    return f"лучший {best}" if best > 0 else None


def _profile_ellipsis(draw, text: str, font, max_width: float) -> str:
    """Обрезать текст с «…», чтобы он гарантированно влез в max_width рендера."""
    text = "" if text is None else str(text)
    if not text:
        return ""
    if max_width <= 0:
        return ""
    if draw.textlength(text, font=font) <= max_width:
        return text
    cut = text
    while cut and draw.textlength(cut + "…", font=font) > max_width:
        cut = cut[:-1]
    return (cut + "…") if cut else "…"


def _profile_wrap_two(draw, text: str, font, max_width: float, max_lines: int = 2) -> list:
    """Разбить текст на строки (не более max_lines), последнюю — с «…» при переполнении."""
    words = ("" if text is None else str(text)).split()
    if not words:
        return []
    lines = []
    current = ""
    for word in words:
        probe = f"{current} {word}".strip()
        if draw.textlength(probe, font=font) <= max_width or not current:
            current = probe
        else:
            lines.append(current)
            current = word
            if len(lines) == max_lines - 1:
                break
    if current and len(lines) < max_lines:
        lines.append(current)
    if not lines:
        return []
    if len(lines) == max_lines:
        lines[-1] = _profile_ellipsis(draw, lines[-1], font, max_width)
    return lines


def _profile_load_avatar(avatar_url, size: int):
    """Аватар → квадрат по центру (RGBA). Понимает URL, локальный файл и bytes."""
    if not avatar_url or size <= 0:
        return None
    try:
        import os

        src = None
        if isinstance(avatar_url, (bytes, bytearray)):
            src = Image.open(io.BytesIO(bytes(avatar_url)))
        elif isinstance(avatar_url, str):
            if os.path.isfile(avatar_url):
                src = Image.open(avatar_url)
            elif avatar_url.startswith(("http://", "https://")):
                content = None
                try:
                    import httpx

                    resp = httpx.get(avatar_url, timeout=8,
                                        headers={"User-Agent": "fissure-bot/1.0"})
                    if resp.status_code == 200 and resp.content:
                        content = resp.content
                except ImportError:
                    from urllib.request import Request, urlopen

                    with urlopen(Request(avatar_url, headers={"User-Agent": "fissure-bot/1.0"}),
                                 timeout=8) as resp:
                        if resp.status == 200:
                            content = resp.read()
                if content:
                    src = Image.open(io.BytesIO(content))
        if src is None:
            return None

        img = src.convert("RGBA")
        w, h = img.size
        side = min(w, h)
        img = img.crop(((w - side) // 2, (h - side) // 2, (w - side) // 2 + side, (h - side) // 2 + side))
        return img.resize((int(size), int(size)), Image.LANCZOS)
    except Exception as e:
        logger.warning(f"_profile_load_avatar failed: {e}")
        return None


def _profile_rank_medal(rank_tier: int, size: int):
    """Медаль звания: images/ranks/rank_T_S.webp (Титан — только 5-я звезда, как в generate_start_card)."""
    try:
        rank_tier = int(rank_tier or 0)
    except (TypeError, ValueError):
        return None
    if rank_tier <= 0 or size <= 0:
        return None

    tier = min(max(rank_tier // 10, 1), 8)
    star = rank_tier % 10 or PROFILE_CARD_RANKS_PER_TIER
    if tier == 8:
        star = PROFILE_CARD_RANKS_PER_TIER
    star = min(star, PROFILE_CARD_RANKS_PER_TIER)

    key = (tier, star)
    icon = _rank_icons_cache.get(key)
    if icon is None:
        base = Path(__file__).parent / "images" / "ranks"
        for ext in (".webp", ".png"):
            path = base / f"rank_{tier}_{star}{ext}"
            if not path.exists():
                continue
            try:
                icon = Image.open(path).convert("RGBA")
                _rank_icons_cache[key] = icon
                break
            except Exception:
                continue
    if icon is None:
        return None
    try:
        return icon.resize((int(size), int(size)), Image.LANCZOS)
    except Exception:
        return None


def _profile_hero_image(name: str, size: int, image_url: str | None = None):
    """Портрет героя: прямой image_url → assets/heroes_webp(+portraits)/<name>.webp (кешируется)."""
    if (not name and not image_url) or size <= 0:
        return None
    if name:
        name = str(name).replace("npc_dota_hero_", "").strip().lower()
    key = (str(name), int(size), str(image_url))
    cached = _profile_hero_cache.get(key)
    if cached is not None:
        return cached

    base = Path(__file__).parent / "assets" / "heroes_webp"
    candidates = []
    if image_url:
        candidates.append(Path(str(image_url)))
    if name:
        candidates.extend([
            base / "portraits" / f"{name}.webp",
            base / f"{name}.webp",
            base / "portraits" / f"{name}.png",
        ])

    img = None
    for path in candidates:
        try:
            if path.is_file():
                img = Image.open(path).convert("RGB")
                break
        except Exception:
            continue
    if img is None:
        return None

    w, h = img.size
    side = min(w, h)
    img = img.crop(((w - side) // 2, (h - side) // 2, (w - side) // 2 + side, (h - side) // 2 + side))
    img = img.resize((int(size), int(size)), Image.LANCZOS)
    _profile_hero_cache[key] = img
    return img


_profile_icon_cache: dict = {}


_award_png_cache: dict = {}


def _profile_award_png(kind: str, size: int):
    """Load an existing transparent award asset and preserve its alpha."""
    if not kind:
        return None
    kind = str(kind)
    cached = _award_png_cache.get((kind, size))
    if cached is not None:
        return cached.copy()
    award_dir = Path(__file__).parent / "assets" / "awards"
    candidates = [award_dir / f"{kind}.webp", award_dir / f"{kind}.png"]
    for path in candidates:
        if not path.exists():
            continue
        try:
            with Image.open(path) as source:
                icon = source.convert("RGBA")
            icon = icon.resize((max(1, int(size)), max(1, int(size))), Image.Resampling.LANCZOS)
            _award_png_cache[(kind, size)] = icon.copy()
            return icon
        except Exception as e:
            logger.warning("Could not load award asset %s: %s", path, e)
    logger.warning("Award asset not found: %s", kind)
    return None


def _profile_award_icon(kind: str, size: int, color):
    """Картинка награды: рисуется фигурами под нужный размер (кешируется по виду и цвету)."""
    from PIL import ImageDraw

    size = int(size)
    if size <= 0:
        return None
    rgb = tuple(int(v) for v in (color or _PC_GOLD)[:3])
    key = (str(kind or "star").lower(), size, rgb)
    cached = _profile_icon_cache.get(key)
    if cached is not None:
        return cached

    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img, "RGBA")
    s = float(size)
    main = (*rgb, 255)
    light = tuple(min(255, int(v + (255 - v) * 0.5)) for v in rgb) + (255,)
    soft = (*rgb, 135)
    dark = (12, 15, 26, 225)

    def poly(pairs, fill):
        draw.polygon([(s * px, s * py) for px, py in pairs], fill=fill)

    def star(cx, cy, radius, fill, ratio: float = 0.46):
        import math

        points = []
        for i in range(10):
            angle = -math.pi / 2 + i * math.pi / 5
            rad = radius if i % 2 == 0 else radius * ratio
            points.append((cx + rad * math.cos(angle), cy + rad * math.sin(angle)))
        draw.polygon(points, fill=fill)

    kind = str(kind or "star").lower()
    if kind == "crown":
        poly([(0.08, 0.72), (0.10, 0.28), (0.30, 0.52), (0.50, 0.14),
              (0.70, 0.52), (0.90, 0.28), (0.92, 0.72)], main)
        draw.rounded_rectangle([s * 0.08, s * 0.68, s * 0.92, s * 0.87],
                               radius=s * 0.05, fill=light)
        for jx in (0.30, 0.50, 0.70):
            draw.ellipse([s * (jx - 0.045), s * 0.55, s * (jx + 0.045), s * 0.64], fill=light)
    elif kind == "medal":
        poly([(0.30, 0.05), (0.49, 0.05), (0.45, 0.54), (0.26, 0.54)], soft)
        poly([(0.70, 0.05), (0.51, 0.05), (0.55, 0.54), (0.74, 0.54)], soft)
        draw.ellipse([s * 0.23, s * 0.41, s * 0.77, s * 0.95], fill=dark)
        draw.ellipse([s * 0.27, s * 0.45, s * 0.73, s * 0.91], fill=main)
        star(s * 0.5, s * 0.68, s * 0.13, light)
    elif kind == "diamond":
        poly([(0.50, 0.07), (0.89, 0.40), (0.50, 0.95), (0.11, 0.40)], main)
        poly([(0.50, 0.07), (0.66, 0.40), (0.50, 0.95), (0.34, 0.40)], light)
    elif kind == "shield":
        poly([(0.50, 0.05), (0.91, 0.22), (0.83, 0.63), (0.50, 0.95),
              (0.17, 0.63), (0.09, 0.22)], main)
        draw.line([(s * 0.5, s * 0.16), (s * 0.5, s * 0.85)],
                  fill=dark, width=max(1, int(s * 0.055)))
    elif kind == "flame":
        poly([(0.50, 0.04), (0.68, 0.30), (0.87, 0.54), (0.76, 0.81),
              (0.50, 0.97), (0.24, 0.81), (0.13, 0.54), (0.36, 0.28)], main)
        poly([(0.50, 0.34), (0.62, 0.60), (0.50, 0.86), (0.38, 0.60)], light)
    elif kind == "dice":
        draw.rounded_rectangle([s * 0.11, s * 0.11, s * 0.89, s * 0.89],
                               radius=s * 0.16, fill=main)
        for dx, dy in ((0.30, 0.30), (0.70, 0.30), (0.50, 0.50), (0.30, 0.70), (0.70, 0.70)):
            draw.ellipse([s * (dx - 0.07), s * (dy - 0.07), s * (dx + 0.07), s * (dy + 0.07)],
                         fill=dark)
    elif kind == "trophy":
        draw.arc([s * 0.03, s * 0.10, s * 0.34, s * 0.48], start=90, end=270,
                 fill=soft, width=max(1, int(s * 0.07)))
        draw.arc([s * 0.66, s * 0.10, s * 0.97, s * 0.48], start=-90, end=90,
                 fill=soft, width=max(1, int(s * 0.07)))
        poly([(0.26, 0.10), (0.74, 0.10), (0.67, 0.58), (0.33, 0.58)], main)
        draw.rectangle([s * 0.45, s * 0.56, s * 0.55, s * 0.78], fill=main)
        draw.rounded_rectangle([s * 0.28, s * 0.78, s * 0.72, s * 0.92],
                               radius=s * 0.06, fill=light)
        star(s * 0.5, s * 0.30, s * 0.12, light)
    elif kind == "chat":
        draw.rounded_rectangle([s * 0.07, s * 0.13, s * 0.93, s * 0.72],
                               radius=s * 0.19, fill=main)
        poly([(0.28, 0.68), (0.47, 0.68), (0.30, 0.95)], main)
        for dx in (0.30, 0.50, 0.70):
            draw.ellipse([s * (dx - 0.06), s * 0.37, s * (dx + 0.06), s * 0.49], fill=dark)
    else:
        star(s * 0.5, s * 0.52, s * 0.44, main, ratio=0.42)

    _profile_icon_cache[key] = img
    return img


def _profile_awards(tags=None, counts=None, *, mmr: int = 0, total_rolls: int = 0,
                    best_streak: int = 0, message_count: int = 0,
                    achievements: dict | None = None, position: int | None = None) -> list:
    """Return persisted tags, award counters, and awarded writer badges."""
    meta = {
        "weekly_mvp": ("MVP", None, "mvp"),
        "weekly_top1": ("Top-1", None, "top1"),
        "weekly_top2": ("MMR Top-2", None, "top2"),
        "weekly_top3": ("MMR Top-3", None, "top3"),
        "F1": ("Fissure Gold", None, "gold"),
        "F2": ("Fissure Silver", None, "silver"),
        "F3": ("Fissure Bronze", None, "bronze"),
        "VIP": ("VIP", None, "vip"),
    }
    counts = counts or {}
    tags = set(tags or [])
    achievements = achievements or {}
    result = []
    seen = set()

    def add(key, label, color, count=None, icon="star"):
        if key in seen:
            return
        seen.add(key)
        result.append({"key": key, "label": label, "color": color,
                       "count": count, "icon": icon})

    # Fissure medal follows the current rank, not a possibly stale stored F-tag.
    # Only when rank is unavailable do we use the tag fallback.
    fissure_key = None
    try:
        rank = int(position) if position is not None else 0
    except (TypeError, ValueError):
        rank = 0
    if rank == 1:
        fissure_key = "F1"
    elif rank == 2:
        fissure_key = "F2"
    elif 3 <= rank <= 15:
        fissure_key = "F3"
    else:
        fissure_tags = [key for key in ("F1", "F2", "F3") if key in tags]
        if fissure_tags:
            fissure_key = fissure_tags[0]
    if fissure_key:
        label, color, icon = meta[fissure_key]
        add(fissure_key, label, color, None, icon)

    # Only one live MMR placement is a current award. Historical medal counts
    # remain in the profile text and must not create extra image tiles.
    mmr_live_tags = [key for key in ("weekly_top1", "weekly_top2", "weekly_top3") if key in tags]
    if mmr_live_tags:
        key = mmr_live_tags[0]
        label, color, icon = meta[key]
        add(key, label, color, None, icon)

    try:
        mvp_count = int(counts.get("weekly_mvp") or 0)
    except (TypeError, ValueError):
        mvp_count = 0
    if "weekly_mvp" in tags or mvp_count > 0:
        label, color, icon = meta["weekly_mvp"]
        add("weekly_mvp", label, color, mvp_count or None, icon)
    for key in ("VIP",):
        if key in tags or int(counts.get(key) or 0) > 0:
            label, color, icon = meta[key]
            add(key, label, color, counts.get(key), icon)

    # Writer profile shows only the highest awarded level. Chat notifications
    # are still emitted separately by achievements.check_and_award().
    from achievements import ACHIEVEMENTS as _writer_achievements
    awarded_writers = [
        (int(spec.get("target", 0)), key)
        for key, spec in _writer_achievements.items()
        if achievements.get(key)
    ]
    if awarded_writers:
        highest_target, highest_key = max(awarded_writers)
        add(highest_key, f"ПИСАТЕЛЬ {highest_target}", None, icon=highest_key)

    return result


_PROFILE_AWARDS_PER_ROW = 5
_PROFILE_AWARDS_ROWS = 1
_PROFILE_AWARDS_MAX = _PROFILE_AWARDS_PER_ROW * _PROFILE_AWARDS_ROWS


def _profile_awards_cap(total) -> tuple:
    """Сколько значков наград влезает в блок и подпись к нему («9 шт.» / «5 из 12»)."""
    try:
        total = max(0, int(total or 0))
    except (TypeError, ValueError):
        total = 0
    shown = min(total, _PROFILE_AWARDS_MAX)
    return shown, (f"{total} шт." if shown == total else f"{shown} из {total}")


def _profile_awards_layout(count) -> dict:
    """Геометрия значков наград: один ряд плиток в центральной области карточки."""
    tile, gap, per_row, top = 120.0, 4.0, _PROFILE_AWARDS_PER_ROW, 245.0
    try:
        count = max(0, int(count or 0))
    except (TypeError, ValueError):
        count = 0
    rows = 1 if count > 0 else 0
    return {
        "tile": tile,
        "gap": gap,
        "per_row": per_row,
        "top": top,
        "row_gap": 0.0,
        "rows": max(1, rows),
        "bottom": top + tile if count > 0 else top,
    }


def _profile_apply_circle_mask(img):
    """Применить круглую маску к изображению (modifies in place)."""
    from PIL import Image, ImageDraw

    w, h = img.size
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, w, h], fill=255)
    img.putalpha(mask)


def _profile_apply_rounded_square_mask(img, radius: float = 0.0):
    """Применить маску с закругленными краями к изображению (modifies in place)."""
    from PIL import Image, ImageDraw

    w, h = img.size
    r = max(0, int(radius))
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, w, h], radius=r, fill=255)
    img.putalpha(mask)


class _ProfileCanvas:
    """Хелпер рисования карточки в суперсэмплинге: координаты задаются в логических px."""

    def __init__(self, img, ss: int = PROFILE_CARD_SS):
        from PIL import ImageDraw

        self.img = img
        self.ss = max(1, int(ss))
        self.draw = ImageDraw.Draw(img, "RGBA")

    def p(self, value) -> int:
        return int(round(float(value) * self.ss))

    def font(self, size: int, role: str = "regular"):
        return _profile_font(role, max(1, int(round(size * self.ss))))

    def text(self, xy, text, size, color, role: str = "regular", anchor: str = "la"):
        text = _profile_clean_text(text, self.font(size, role))
        if not text:
            return
        self.draw.text((self.p(xy[0]), self.p(xy[1])), text,
                       font=self.font(size, role), fill=color, anchor=anchor)

    def text_width(self, text, size, role: str = "regular") -> float:
        text = _profile_clean_text(text, self.font(size, role))
        if not text:
            return 0.0
        return self.draw.textlength(text, font=self.font(size, role)) / self.ss

    def text_tracked(self, xy, text, size, color, role: str = "bold",
                     tracking: float = 1.2, anchor: str = "la"):
        """Капс-заголовок с разрядкой между буквами."""
        text = _profile_clean_text(text, self.font(size, role))
        if not text:
            return
        x = float(xy[0])
        if anchor == "ra":
            x -= self.text_width(text, size, role) + tracking * max(0, len(text) - 1)
        for ch in text:
            self.draw.text((self.p(x), self.p(xy[1])), ch,
                           font=self.font(size, role), fill=color, anchor="la")
            x += self.text_width(ch, size, role) + tracking

    def fit(self, text, size, role, max_w) -> str:
        font = self.font(size, role)
        return _profile_ellipsis(self.draw, _profile_clean_text(text, font), font, self.p(max_w))

    def wrap(self, text, size, role, max_w, max_lines: int = 2) -> list:
        font = self.font(size, role)
        return _profile_wrap_two(self.draw, _profile_clean_text(text, font), font,
                                 self.p(max_w), max_lines)

    def line(self, x1, y1, x2, y2, color, width: float = 1):
        self.draw.line([(self.p(x1), self.p(y1)), (self.p(x2), self.p(y2))],
                       fill=color, width=max(1, self.p(width)))

    def rect(self, x, y, w, h, radius: float = 12, fill=None, outline=None, width: float = 1):
        self.draw.rounded_rectangle([self.p(x), self.p(y), self.p(x + w), self.p(y + h)],
                                    radius=self.p(radius), fill=fill, outline=outline,
                                    width=max(1, self.p(width)))

    def circle(self, cx, cy, r, fill=None, outline=None, width: float = 1):
        self.draw.ellipse([self.p(cx - r), self.p(cy - r), self.p(cx + r), self.p(cy + r)],
                          fill=fill, outline=outline, width=max(1, self.p(width)))

    def paste(self, image, x, y, mask=None):
        self.img.paste(image, (self.p(x), self.p(y)), mask)

    def star(self, cx, cy, r, color, inner_ratio: float = 0.46):
        """Пятиконечная звезда (рисуется полигоном: не зависит от глифа «★» в шрифте)."""
        import math

        points = []
        for i in range(10):
            angle = -math.pi / 2 + i * math.pi / 5
            radius = r if i % 2 == 0 else r * inner_ratio
            points.append((self.p(cx + radius * math.cos(angle)), self.p(cy + radius * math.sin(angle))))
        self.draw.polygon(points, fill=color)


# Короткие подписи тиров для ленты званий (8 тиров)
_PC_TIER_SHORT = ["РЕКРУТ", "СТРАЖ", "РЫЦАРЬ", "ГЕРОЙ", "ЛЕГЕНДА", "ВЛАСТЕЛИН", "БОЖЕСТВО", "ТИТАН"]


def _profile_round_mask(size: int, radius: float):
    from PIL import ImageDraw

    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, size - 1, size - 1],
                                            radius=max(1, int(radius)), fill=255)
    return mask


def _profile_masked(image, mask):
    """Наложить маску на изображение, сохранив его собственную прозрачность."""
    layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    layer.paste(image, (0, 0), mask)
    return layer


def generate_profile_card(
    avatar_url: str = None,
    username: str = None,
    steam_nickname: str = None,
    steam_id: int = None,
    rank_tier: int = 0,
    mmr: int = 0,
    fissure: float = 0.0,
    message_count: int = 0,
    total_rolls: int = 0,
    weekly_rolls: int = 0,
    current_streak: int = 0,
    best_streak: int = 0,
    week_games: int = 0,
    week_wins: int = 0,
    week_losses: int = 0,
    dota_total_games: int = 0,
    dota_wins: int = 0,
    dota_losses: int = 0,
    top_heroes: list = None,
    tags: list = None,
    award_counts: dict = None,
    achievements: dict = None,
    position: int = None,
) -> bytes | None:
    """Карточка /profile — точная копия /start (фон, аватар, медаль, ник) + герои (если Steam)
    и награды внизу. Без Steam — карточка как в /start (только сообщения вместо героев)."""
    logger.info(
        f"generate_profile_card INPUT: username={username} steam_id={steam_id} "
        f"rank_tier={rank_tier} mmr={mmr} message_count={message_count} "
        f"top_heroes={len(top_heroes or [])} has_tags={bool(tags)}"
    )
    try:
        import io
        import os

        import requests
        from PIL import Image, ImageDraw, ImageFont

        # ===== Точные параметры из generate_start_card: 1024x500, scale=1.8 =====
        width = 1024
        height = 500
        scale = 1.8

        # ===== Фон как в /start (яркий, без тёмной пелёнки) =====
        try:
            bg_image = _get_start_card_background()
            if bg_image is not None:
                img = bg_image.copy()
            else:
                img = Image.new("RGB", (width, height), (15, 20, 35))
        except Exception as e:
            logger.error(f"Profile background error: {e}")
            img = Image.new("RGB", (width, height), (15, 20, 35))
        draw = ImageDraw.Draw(img)

        # --- Награды ---
        awards = _profile_awards(
            tags, award_counts, mmr=mmr, total_rolls=total_rolls,
            best_streak=best_streak, message_count=message_count,
            achievements=achievements, position=position,
        )

        # --- Аватар + золотая рамка (как в /start) -----
        avatar_x_offset = -100
        avatar_size = int(140 * scale)                 # 252
        avatar_x = int(120 * scale) + avatar_x_offset  # 116
        avatar_y = int((height - avatar_size) // 2 - 10)  # 114

        avatar_loaded = False
        if avatar_url:
            try:
                logger.info(f"Profile avatar: {avatar_url[:80]}")
                if os.path.isfile(avatar_url):
                    avatar = Image.open(avatar_url).convert("RGBA")
                else:
                    resp = httpx.get(
                        avatar_url,
                        timeout=10,
                        headers={"User-Agent": "fissure-bot/1.0"},
                    )
                    if resp.status_code == 200 and resp.content:
                        from io import BytesIO
                        avatar = Image.open(BytesIO(resp.content)).convert("RGBA")
                    else:
                        avatar = None
                if avatar:
                    w, h = avatar.size
                    side = min(w, h)
                    left = (w - side) // 2
                    top = (h - side) // 2
                    avatar = avatar.crop((left, top, left + side, top + side))
                    avatar = avatar.resize((avatar_size, avatar_size), Image.LANCZOS)
                    draw.rectangle(
                        [avatar_x, avatar_y, avatar_x + avatar_size, avatar_y + avatar_size],
                        outline=(215, 175, 85), width=int(4 * scale),
                    )
                    img.paste(avatar, (avatar_x, avatar_y))
                    avatar_loaded = True
            except Exception as e:
                logger.warning(f"Profile avatar error: {e}")

        if not avatar_loaded:
            draw.rectangle(
                [avatar_x, avatar_y, avatar_x + avatar_size, avatar_y + avatar_size],
                fill=(40, 55, 80), outline=(215, 175, 85), width=int(4 * scale),
            )
            draw.ellipse(
                [avatar_x + int(45 * scale), avatar_y + int(35 * scale),
                 avatar_x + int(95 * scale), avatar_y + int(105 * scale)],
                fill=(80, 100, 130),
            )

        # ===== Ник + шрифты — точно как в /start =====
        info_x = avatar_x + avatar_size + int(30 * scale)  # 116 + 252 + 54 = 422
        info_y = avatar_y + int(20 * scale)  # 114 + 36 = 150

        try:
            font_title = ImageFont.truetype(
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", int(40 * scale),
            )
            font_small = ImageFont.truetype(
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", int(26 * scale),
            )
            font_fissure = ImageFont.truetype(
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", int(36 * scale),
            )
            font_count = ImageFont.truetype(
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", int(18 * scale),
            )
        except Exception:
            font_title = font_small = font_fissure = font_count = ImageFont.load_default()

        display_name = f"@{username}" if username else (steam_nickname or "Unknown")


        # --- Медаль звания — наполовину заходит на аватар (как в /start) ---
        medal_size = 180
        medal_y = avatar_y + avatar_size
        medal = _profile_rank_medal(rank_tier, medal_size)
        if medal is not None:
            cx = avatar_x + avatar_size // 2
            img.paste(medal, (cx - medal_size // 2, medal_y - medal_size // 2), medal)

        # --- Ник: белый цвет (как в /start) ---
        draw.text((info_x, info_y), display_name, fill=_PC_WHITE, font=font_title)

        msg_label_y = info_y + int(50 * scale)

        # --- Награды в центральной области, где раньше был текст ---
        if awards:
            shown, _caption = _profile_awards_cap(len(awards))
            awards = awards[:shown]
            layout = _profile_awards_layout(len(awards))
            tile = int(layout["tile"])
            gap = int(layout["gap"])
            per_row = int(layout["per_row"])
            awards_width = len(awards) * tile + max(0, len(awards) - 1) * gap
            # Keep the award row slightly closer to the avatar column.
            tile_x = info_x - 5
            tile_y = int(layout["top"])
            for award in awards[:per_row]:
                accent = award["color"]
                icon = _profile_award_png(award.get("icon"), tile)
                if icon is not None:
                    img.paste(icon, (tile_x, tile_y), icon)
                else:
                    draw.ellipse(
                        [tile_x, tile_y, tile_x + tile, tile_y + tile],
                        fill=(20, 24, 38), outline=accent, width=2)

                # Цифры только у MVP - в правом верхнем углу
                if award.get("count") and award["key"] == "weekly_mvp":
                    draw.text((tile_x + tile - 10, tile_y + 5), f"x{award['count']}",
                            fill=_PC_WHITE, font=font_count)

                tile_x += tile + gap
        else:
            if week_wins is not None and week_losses is not None:
                wr = round(week_wins / (week_wins + week_losses) * 100) if (week_wins + week_losses) > 0 else 0
                draw.text((info_x, msg_label_y), "За неделю:", fill=_PC_WHITE, font=font_small)
                draw.text((info_x, msg_label_y + int(28 * scale)),
                          f"{week_wins}W/{week_losses}L/{wr}%", fill=_PC_WHITE, font=font_title)
            else:
                draw.text((info_x, msg_label_y), "Всего сообщений:", fill=_PC_WHITE, font=font_small)
                draw.text((info_x, msg_label_y + int(28 * scale)),
                          str(message_count), fill=_PC_WHITE, font=font_title)

        # --- Герои недели: рендеринг из /start (квадраты 82px) ---
        if top_heroes:
            clean_heroes = [h for h in top_heroes if h and isinstance(h, dict)]
            if clean_heroes:
                img, draw = _draw_hero_squares_on_card(img, draw, clean_heroes, height, width)

        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        buf.seek(0)
        return buf.read()

    except Exception:
        logger.exception("generate_profile_card error")
        return None

