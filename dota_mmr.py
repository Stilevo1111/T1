import asyncio
import functools
import io
import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import aiohttp
from PIL import Image

from database import get_user, update_user_fields_batch
from constants import get_banner_path
from cache_service import api_cache, negative_cache, image_cache, hero_cache, opendota_rate_limiter, opendota_circuit_breaker

logger = logging.getLogger(__name__)

# Thread pool for running async code from sync contexts (avoids event loop conflicts)
_async_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="async_sync_bridge")

def _run_async(coro):
    """Run async coroutine from sync context safely.
    
    Uses a dedicated thread pool with its own event loop to avoid
    "Event loop is closed" and "RuntimeError: asyncio.run() cannot be called from a running event loop" errors.
    """
    def run_in_new_loop():
        return asyncio.run(coro)
    
    future = _async_executor.submit(run_in_new_loop)
    return future.result(timeout=30)

# Hero list cache (uses unified cache)
_HEROES_CACHE_TTL = 86400  # 24 hours

async def get_hero_list():
    """Get list of heroes from OpenDota API with caching."""
    cached = hero_cache.get("hero_list")
    if cached is not None:
        return cached
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
            async with session.get("https://api.opendota.com/api/heroes") as resp:
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

# Rate limiter helper functions using unified rate limiter
def is_opendota_rate_limited():
    """Проверить, находится ли OpenDota API в состоянии rate limit"""
    if not opendota_rate_limiter.try_acquire(1):
        return True
    return False


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
    opendota_rate_limiter._tokens = 0
    opendota_rate_limiter._last_update = time.monotonic() - wait_seconds


# Background retry task for circuit breaker recovery
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


async def _api_get_async(url: str, params: dict = None, use_session: bool = True, timeout: int = 15, max_retries: int = 3) -> dict:
    """Асинхронная функция для API-запросов с собственной сессией, retry и rate limiting"""
    if not _circuit_breaker_can_execute():
        logger.warning("Circuit breaker: skipping async request, API unavailable")
        return None

    if is_opendota_rate_limited():
        remaining = get_opendota_rate_limit_time_remaining()
        logger.warning(f"OpenDota still rate limited, waiting {remaining}s...")
        await asyncio.sleep(remaining + 1)

    await _check_rate_limit_async()

    if params is None:
        params = {}

    for attempt in range(max_retries + 1):
        current_timeout = timeout if attempt == 0 else timeout + 5
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=current_timeout)) as session:
                async with session.get(url, params=params) as resp:
                    if resp.status == 200:
                        _circuit_breaker_record_success()
                        try:
                            from analytics_dashboard import record_opendota_tokens
                            record_opendota_tokens(1)
                        except Exception:
                            pass
                        return await resp.json()
                    elif resp.status == 429:
                        logger.warning("Rate limited by OpenDota API, waiting...")
                        set_opendota_rate_limited(60)
                        wait_time = 3 * (attempt + 1)
                        await asyncio.sleep(wait_time)
                        continue
                    elif resp.status >= 500:
                        logger.warning(f"Server error {resp.status} for {url[:60]}, attempt {attempt + 1}/{max_retries + 1}")
                        _circuit_breaker_record_failure()
                        await asyncio.sleep(1 + attempt)
                        continue
                    else:
                        logger.error(f"API error {resp.status} for {url[:80]}")
                        if resp.status == 404:
                            _mark_not_found(url)
                        return None
        except asyncio.TimeoutError:
            logger.warning(f"API request timeout ({current_timeout}s), retrying... ({attempt + 1}/{max_retries + 1})")
            if attempt < max_retries:
                await asyncio.sleep(1 + attempt)
                continue
            _circuit_breaker_record_failure()
            return None
        except RuntimeError as e:
            if "Event loop is closed" in str(e) or "Timeout context manager" in str(e):
                logger.warning(f"Async API error ({e}), retrying... ({attempt + 1}/{max_retries + 1})")
                if attempt < max_retries:
                    await asyncio.sleep(1 + attempt)
                    continue
                return None
            logger.error(f"Async API request error: {e}", exc_info=True)
            if attempt < max_retries:
                await asyncio.sleep(1 + attempt)
                continue
            _circuit_breaker_record_failure()
            return None
        except Exception as e:
            logger.error(f"Async API request error: {e}", exc_info=True)
            if attempt < max_retries:
                await asyncio.sleep(1 + attempt)
                continue
            _circuit_breaker_record_failure()
            return None

    logger.error(f"Async API request failed after {max_retries + 1} retries: {url[:80]}")
    return None


# ========================
# 🎮 MATCHES
# ========================

# ========================
# 🦸 HEROES
# ========================

HERO_IMAGE_BASE = "https://cdn.cloudflare.steamstatic.com/apps/dota2/images/dota_react/heroes"

HERO_CACHE_DIR = Path(__file__).parent / "assets" / "heroes_webp"
HERO_CACHE_DIR.mkdir(parents=True, exist_ok=True)
HERO_ICON_BASE = "https://cdn.cloudflare.steamstatic.com/apps/dota2/images/dota_react/heroes/icons"
HEROES_STRIP_BG_URL = get_banner_path("heroes_profil")
HEROES_STRIP_BG_CACHE = "heroes_profil.webp"

from hero_names import HERO_NAME_TO_CDN, get_cdn_hero_name


def get_hero_icon_cached(hero_short_name: str, timeout: int = 3) -> bytes | None:
    """Get hero icon with caching"""
    try:
        from image_cache import get_cached_hero_icon
        return get_cached_hero_icon(hero_short_name)
    except ImportError:
        pass

    cdn_name = get_cdn_hero_name(hero_short_name)
    cache_file = HERO_CACHE_DIR / f"{cdn_name}.webp"
    if cache_file.exists():
        try:
            return cache_file.read_bytes()
        except Exception:
            pass

    try:
        url = f"{HERO_ICON_BASE}/{cdn_name}.png"
        resp = requests.get(url, timeout=timeout, headers={"User-Agent": "Mozilla/5.0 (compatible; FissureBot/1.0)"})
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
    cdn_name = get_cdn_hero_name(hero_short_name)
    cache_dir = HERO_CACHE_DIR
    cache_file = cache_dir / f"{cdn_name}.webp"
    if cache_file.exists():
        try:
            return cache_file.read_bytes()
        except Exception:
            pass
    try:
        url = f"{HERO_IMAGE_BASE}/{cdn_name}.png"
        resp = requests.get(url, timeout=3, headers={"User-Agent": "Mozilla/5.0 (compatible; FissureBot/1.0)"})
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

    cdn_name = get_cdn_hero_name(hero_short_name)
    cache_file = HERO_CACHE_DIR / f"{cdn_name}.webp"

    if cache_file.exists():
        try:
            return Image.open(cache_file).convert("RGBA")
        except Exception:
            logger.exception("Failed to load cached hero portrait")

    url = f"{HERO_IMAGE_BASE}/{cdn_name}.png"
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as session:
            async with session.get(url, headers={"User-Agent": "Mozilla/5.0 (compatible; FissureBot/1.0)"}) as resp:
                if resp.status != 200:
                    return None
                content_type = resp.headers.get("Content-Type", "")
                if not content_type.startswith("image/"):
                    logger.warning("Unexpected Content-Type for hero portrait %s: %s", url, content_type)
                    return None
                data = await resp.read()

        try:
            cache_file.write_bytes(data)
        except Exception:
            logger.exception("Failed to save hero portrait to cache")

        try:
            return Image.open(io.BytesIO(data)).convert("RGBA")
        except Exception as e:
            logger.error("Failed to decode hero portrait %s: %s", url, e)
            return None

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
                    resp = requests.get(str(bg_path), timeout=12)
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

    try:
        url = f"{OPENDOTA_API_URL}/heroes"
        data = await _api_get_async(url)
        if not data:
            return {}

        heroes = {}
        for hero in data:
            hero_id = hero["id"]
            short_name = hero["name"].replace("npc_dota_hero_", "")
            cdn_name = get_cdn_hero_name(short_name)
            heroes[hero_id] = {
                "id": hero_id,
                "name": hero["localized_name"],
                "short_name": short_name,
                "image_url": f"{HERO_IMAGE_BASE}/{cdn_name}.png",
                "icon_url": f"{HERO_ICON_BASE}/{cdn_name}.png",
                "img": f"{HERO_IMAGE_BASE}/{cdn_name}.png",
            }

        _set_cached("heroes_data", heroes)
        logger.info(f"Loaded {len(heroes)} heroes from OpenDota")
        return heroes
    except Exception as e:
        logger.error(f"get_heroes_data_async error: {e}", exc_info=True)
        return {}


def get_heroes_data() -> dict:
    """Синхронная обёртка для обратной совместимости"""
    return _run_async(get_heroes_data_async())


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


def get_week_top_heroes(steam_id: int, top_k: int = 5, match_limit: int = 50) -> list:
    """Топ героев игрока за текущую неделю (по числу игр)."""
    from collections import Counter
    from datetime import datetime, timezone

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
            match_date = datetime.fromtimestamp(match.get("start_time", 0), tz=timezone.utc)
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
    from datetime import datetime, timezone

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
            match_date = datetime.fromtimestamp(match.get("start_time", 0), tz=timezone.utc)
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
    from PIL import Image, ImageDraw, ImageFont

    if not top_heroes:
        return img, draw

    heroes = sorted(top_heroes, key=lambda h: h.get("picks", 0), reverse=True)[:5]
    n = len(heroes)
    icon_size = 82
    gap = 12
    total_w = n * icon_size + max(0, n - 1) * gap
    start_x = max(10, (width - total_w) // 2) + 155
    y = base_height - icon_size - 18

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
    return round((wins / games * 100)) if games > 0 else 0


# ========================
# 🎯 MMR (примерный)
# ========================

def rank_to_mmr(rank_tier: int) -> int:
    if not rank_tier:
        return 0

    tier = min(rank_tier // 10, 8)
    star = rank_tier % 10

    _MMR_TABLE = {
        1: [0, 0, 0, 0, 0, 150, 300, 460, 610, 760],
        2: [0, 0, 0, 0, 0, 920, 1080, 1230, 1400, 1570],
        3: [0, 0, 0, 0, 0, 1700, 1850, 2000, 2150, 2300],
        4: [0, 0, 0, 0, 0, 2450, 2610, 2770, 2930, 3090],
        5: [0, 0, 0, 0, 0, 3230, 3390, 3540, 3700, 3860],
        6: [0, 0, 0, 0, 0, 4000, 4150, 4300, 4460, 4620],
        7: [0, 0, 0, 0, 0, 4820, 5020, 5220, 5420, 5620],
        8: [0, 0, 0, 0, 0, 5620, 5620, 5620, 5620, 5620],
    }

    row = _MMR_TABLE.get(tier)
    if not row:
        return 0
    return row[star] if star < len(row) else row[-1]


def mmr_to_rank_tier(mmr: int) -> int:
    """Convert MMR to rank_tier using the exact MMR table."""
    if not mmr or mmr <= 0:
        return 0

    _MMR_RANKS = [
        (150, 11), (300, 12), (460, 13), (610, 14), (760, 15),
        (920, 21), (1080, 22), (1230, 23), (1400, 24), (1570, 25),
        (1700, 31), (1850, 32), (2000, 33), (2150, 34), (2300, 35),
        (2450, 41), (2610, 42), (2770, 43), (2930, 44), (3090, 45),
        (3230, 51), (3390, 52), (3540, 53), (3700, 54), (3860, 55),
        (4000, 61), (4150, 62), (4300, 63), (4460, 64), (4620, 65),
        (4820, 71), (5020, 72), (5220, 73), (5420, 74), (5620, 75),
        (5620, 81), (5620, 82), (5620, 83), (5620, 84), (5620, 85),
    ]

    best_rank = 0
    for threshold, rank in _MMR_RANKS:
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
    return _run_async(search_player_async(nickname))


# ========================
# 🎮 MATCHES
# ========================

def get_recent_matches(steam_id: int, limit: int = 5) -> list:
    """Синхронная обёртка для обратной совместимости"""
    return _run_async(get_recent_matches_async(steam_id, limit))


async def get_recent_matches_async(steam_id: int, limit: int = 5) -> list:
    """Асинхронно получить последние матчи игрока"""
    if steam_id is None:
        return []
    
    cache_key = (steam_id, limit)
    if cache_key in _user_matches_cache:
        cached_data, cached_time = _user_matches_cache[cache_key]
        if time.time() - cached_time < USER_MATCHES_CACHE_TTL:
            return cached_data
    
    try:
        account_id = steam64_to_account_id(steam_id)
        url = f"{OPENDOTA_API_URL}/players/{account_id}/matches"
        
        start_time = time.time()
        max_wait = 25
        matches = None
        while matches is None and (time.time() - start_time) < max_wait:
            matches = await _api_get_async(url, {"limit": limit, "sort": "-start_time", "radiant_win": 1})
            if matches is None:
                await asyncio.sleep(5)
        
        matches = matches or []
        
        # Don't cache empty results - might be due to rate limits
        if matches:
            _user_matches_cache[cache_key] = (matches, time.time())
        
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
    return _run_async(is_win_api_async(match_id, steam_id))


# ========================
# 📊 GET STATS
# ========================

async def get_player_stats_async(steam_id: int, use_cache: bool = True, timeout: int = 8) -> dict:
    """Асинхронно получить статистику игрока (последние матчи, герои, винрейт) из OpenDota с кэшем."""
    try:
        cache_key = f"player_{steam_id}"
        if use_cache:
            cached = _get_cached(cache_key)
            if cached:
                return cached

        account_id = steam64_to_account_id(steam_id)
        players_url = f"{OPENDOTA_API_URL}/players/{account_id}"

        # Если аккаунт уже известен как несуществующий (404), пропускаем обращение к API.
        if _is_not_found(players_url):
            logger.debug(f"Player {account_id} known not found (negative cache), skipping API")
            if use_cache:
                cached = _get_cached(cache_key)
                if cached:
                    return cached
            return None

        player_data = await _api_get_async(players_url, timeout=timeout)
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

        wl_data = await _api_get_async(f"{OPENDOTA_API_URL}/players/{account_id}/wl", timeout=timeout)
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


def get_player_stats(steam_id: int, use_cache: bool = True, timeout: int = 8) -> dict:
    """Синхурная обёртка для обратной совместимости"""
    return _run_async(get_player_stats_async(steam_id, use_cache, timeout))


# ========================
# 🔗 REGISTER
# ========================

def register_steam(telegram_id: int, identifier: str) -> dict:
    """Привязать Steam-аккаунт к пользователю: парсит identifier, сохраняет steam_id/nickname, делает первый апдейт MMR."""
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
            # Сбрасываем negative cache на случай, если аккаунт ранее не находился
            _clear_not_found(f"{OPENDOTA_API_URL}/players/{account_id}")

            stats = get_player_stats(steam_id)
            logger.info(f"Player stats result: {stats is not None}")

            invalid_stats = not stats or stats.get("nickname") == "Unknown"
            private_profile = False
            if stats and not invalid_stats:
                total_games = stats.get("total_games") or 0
                mmr = stats.get("mmr") or 0
                if total_games == 0 and mmr == 0:
                    private_profile = True

            if invalid_stats or private_profile:
                try:
                    from database import get_user_by_steam_id, get_user, update_user_fields_batch, user_cache
                    existing_user = get_user_by_steam_id(steam_id)
                    if existing_user and existing_user.get('telegram_id') == telegram_id:
                        if private_profile:
                            return {
                                "success": True,
                                "message": "✅ Аккаунт уже привязан к вам\n\nВаш Dota 2 профиль закрыт. Чтобы бот мог обновлять статистику:\n⚠️ В игре: \nнастройки → сообщество → настройки → общедоступная история матчей → включить"
                            }
                        return {"success": True, "message": "✅ Аккаунт уже привязан к вам"}
                    if existing_user:
                        existing_tid = existing_user.get('telegram_id')
                        existing_username = existing_user.get('username') or existing_user.get('steam_nickname') or 'другой игрок'
                        
                        # Автоматически переносим Steam аккаунт на нового пользователя
                        logger.info(f"Transferring Steam {steam_id} from user {existing_tid} to {telegram_id}")
                        update_user_fields_batch(existing_tid, {"steam_id": None, "steam_nickname": None, "avatar": None}, update_top_cache=False)
                        with user_cache._lock:
                            if steam_id in user_cache._steam_index:
                                del user_cache._steam_index[steam_id]
                        
                        if private_profile:
                            return {
                                "success": True,
                                "message": f"⚠️ Steam аккаунт был привязан к {existing_username}\nАвтоматически перенесён на ваш аккаунт.\n\nВаш Dota 2 профиль закрыт. Чтобы бот мог обновлять статистику:\n⚠️ В игре: \nнастройки → сообщество → настройки → общедоступная история матчей → включить"
                            }
                        return {
                            "success": True,
                            "message": f"⚠️ Steam аккаунт был привязан к {existing_username}\nАвтоматически перенесён на ваш аккаунт.\nСтарые данные утрачены."
                        }
                except Exception:
                    pass

                if private_profile:
                    update_user_fields_batch(telegram_id, {
                        "steam_id": steam_id,
                        "mmr": 0,
                        "rank_tier": 0,
                        "wins": 0,
                        "losses": 0,
                        "week_start_date": datetime.now(UTC).date().isoformat()
                    })
                    return {
                        "success": True,
                        "message": "✅ Аккаунт привязан! Ваш Dota 2 профиль закрыт. Чтобы бот мог обновлять статистику:\n⚠️ В игре: \nнастройки → сообщество → настройки → общедоступная история матчей → включить"
                    }
                update_user_fields_batch(telegram_id, {
                    "steam_id": steam_id,
                    "mmr": 0,
                    "rank_tier": 0,
                    "wins": 0,
                    "losses": 0,
                    "week_start_date": datetime.now(UTC).date().isoformat()
                })
                return {"success": True, "message": "✅ Аккаунт привязан! Статистика OpenDota временно недоступна для этого игрока. Попробуйте позже."}
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
        from database import get_user_by_steam_id, get_user, update_user_fields_batch, user_cache
        existing_user = get_user_by_steam_id(steam_id)
        if existing_user and existing_user.get('telegram_id') != telegram_id:
            existing_tid = existing_user.get('telegram_id')
            existing_username = existing_user.get('username') or existing_user.get('steam_nickname') or 'другой игрок'
            
            # Автоматически переносим Steam аккаунт на нового пользователя
            logger.info(f"Transferring Steam {steam_id} from user {existing_tid} to {telegram_id}")
            
            # Удаляем steam_id у старого пользователя (раз-prивязываем)
            update_user_fields_batch(existing_tid, {
                "steam_id": None,
                "steam_nickname": None,
                "avatar": None,
            }, update_top_cache=False)
            
            # Обновляем reverse index в кеше
            with user_cache._lock:
                if steam_id in user_cache._steam_index:
                    del user_cache._steam_index[steam_id]
            
            return {
                "success": True,
                "message": f"⚠️ Steam аккаунт был привязан к {existing_username}\nАвтоматически перенесён на ваш аккаунт.\nСтарые данные утрачены."
            }

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
        winrate = round(stats.get("winrate", 0))

        return {
            "success": True,
            "message": f"✅ {stats['nickname']} | {rank_str}\n📊 {total} игр | ✅ {wins} | ❌ {losses} | {winrate}%"
        }

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
        from database import get_user_by_steam_id, update_user_fields_batch, user_cache
        
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

        # Simple per-process cache: skip heavy API call if we updated this user recently (helps on restart + repeated calls)
        # But still process week stats from matches
        last_updated = user.get('mmr_last_updated')
        if last_updated and isinstance(last_updated, (int, float)):
            if time.time() - last_updated < 4 * 3600:  # 4 hours (OpenDota API limit: 3000 tokens/day)
                logger.info(f"topmmr: Cache hit for MMR - will use cached stats but still process week from matches")

        # Keep trying API until we get data (with delays to avoid rate limit spam)
        stats = None
        start_time = time.time()
        max_wait = 10  # Maximum wait time in seconds
        while not stats and (time.time() - start_time) < max_wait:
            # Если аккаунт точно не существует (404) — не spin-им retry-цикл, выходим сразу.
            players_url = f"{OPENDOTA_API_URL}/players/{steam64_to_account_id(user['steam_id'])}"
            if _is_not_found(players_url):
                logger.info(f"topmmr: player {user['steam_id']} known not found, skipping retries")
                break
            # Если circuit breaker открыт — пропускаем ожидание
            if not _circuit_breaker_can_execute():
                logger.info(f"topmmr: circuit breaker open for {user['steam_id']}, skipping retry")
                break
            stats = get_player_stats(user["steam_id"], use_cache=False)
            if stats:
                break
            wait_time = 2
            logger.info(f"topmmr: waiting for API, sleeping {wait_time}s...")
            time.sleep(wait_time)
        logger.info(f"topmmr: get_player_stats returned: steam32={user.get('steam_id')}, success={stats is not None}")
        
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
                from database import get_connection, release_pg_connection, DATABASE_URL, urlparse
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
                            steam_id BIGINT
                        )
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
                        if match_id and hero_id is not None and player_slot is not None:
                            cursor.execute("""
                                INSERT INTO public_player_matches (match_id, hero_id, player_slot, radiant_win, start_time, steam_id)
                                VALUES (%s, %s, %s, %s, %s, %s)
                                ON CONFLICT DO NOTHING
                            """, (match_id, hero_id, player_slot, radiant_win_int, start_time, steam_id))
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
                        hero_id = match.get("hero_id", 0)
                        player_slot = match.get("player_slot")
                        radiant_win_api = match.get("radiant_win")
                        radiant_win_int = 1 if radiant_win_api else 0
                        start_time = match.get("start_time")
                        steam_id = user.get("steam_id")
                        logger.info(f"topmmr: Hero meta saving (SQLite) - match_id={match_id}, hero_id={hero_id}, radiant_win={radiant_win_int} (api_radiant_win={radiant_win_api}, player_slot={player_slot}), steam_id={steam_id}")
                        if match_id and hero_id is not None and player_slot is not None:
                            cursor.execute("""
                                INSERT OR IGNORE INTO public_player_matches (match_id, hero_id, player_slot, radiant_win, start_time, steam_id)
                                VALUES (?, ?, ?, ?, ?, ?)
                            """, (match_id, hero_id, player_slot, radiant_win_int, start_time, steam_id))
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
                    resp = requests.get(
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
            wr = round((week_wins / (week_wins + week_losses) * 100)) if (week_wins + week_losses) > 0 else 0
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

