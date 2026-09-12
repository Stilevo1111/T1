from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
import urllib.parse as urlparse
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import timezone
from typing import Any

import psycopg2
import psycopg2.extras

from utils import _telegram_error_contains

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@dataclass
class User:
    telegram_id: int
    username: str | None = None
    steam_id: int | None = None
    steam_nickname: str | None = None
    fissure: float = 0.0
    mmr: int = 0
    rank_tier: int = 0
    total_rolls: int = 0
    current_streak: int = 0
    best_streak: int = 0
    current_win_streak: int = 0
    current_lose_streak: int = 0
    best_lose_streak: int = 0
    message_count: int = 0
    user_tags: str | None = None

    @classmethod
    def from_row(cls, row: tuple | dict, db_type: str = "sqlite") -> User:
        if db_type == "postgresql":
            return cls(
                telegram_id=row["telegram_id"],
                username=row.get("username"),
                steam_id=row.get("steam_id"),
                steam_nickname=row.get("steam_nickname"),
                fissure=float(row.get("fissure", 0)),
                mmr=row.get("mmr", 0),
                rank_tier=row.get("rank_tier", 0),
                total_rolls=row.get("total_rolls", 0),
                current_streak=row.get("current_streak", 0),
                best_streak=row.get("best_streak", 0),
                current_win_streak=row.get("current_win_streak", 0),
                current_lose_streak=row.get("current_lose_streak", 0),
                best_lose_streak=row.get("best_lose_streak", 0),
                message_count=row.get("message_count", 0),
                user_tags=row.get("user_tags"),
            )
        return cls(
            telegram_id=row[1] if len(row) > 1 else 0,
            username=row[2] if len(row) > 2 else None,
            steam_id=row[19] if len(row) > 19 else None,
            steam_nickname=row[20] if len(row) > 20 else None,
            fissure=float(row[3]) if len(row) > 3 else 0,
            mmr=row[21] if len(row) > 21 else 0,
            rank_tier=row[30] if len(row) > 30 else 0,
            total_rolls=row[7] if len(row) > 7 else 0,
            current_streak=row[9] if len(row) > 9 else 0,
            best_streak=row[10] if len(row) > 10 else 0,
            current_win_streak=row[41] if len(row) > 41 else 0,
            current_lose_streak=row[42] if len(row) > 42 else 0,
            best_lose_streak=row[43] if len(row) > 43 else 0,
            message_count=row[39] if len(row) > 39 else 0,
            user_tags=row[45] if len(row) > 45 else None,
        )


@dataclass
class MatchStats:
    telegram_id: int
    week_games: int = 0
    week_wins: int = 0
    week_current_streak: int = 0


class UserRepository:
    """Repository for user-related database operations"""

    def __init__(self, db_pool):
        self.db_pool = db_pool

    @contextmanager
    def _get_connection(self) -> Generator:
        conn = get_connection()
        try:
            yield conn
        finally:
            release_connection(conn)


def _mask_db_url(url: str) -> str:
    try:
        parsed = urlparse.urlparse(url)
        if parsed.password:
            return f"{parsed.scheme}://{parsed.username}:****@{parsed.hostname}:{parsed.port or 5432}{parsed.path}"
        return url
    except Exception:
        return url

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    DATABASE_URL = "sqlite:///fissure_bot.db"
    logger.info(f"💡 Используется: {DATABASE_URL}")
else:
    logger.info(f"Using DATABASE_URL: {_mask_db_url(DATABASE_URL)}")


class UserCache:
    """Кеш данных пользователей в памяти с записью в БД раз в сутки"""

    MAX_CACHE_SIZE = 3000  # Максимум пользователей в кеше

    def __init__(self) -> None:
        self._cache: dict[int, dict[str, Any]] = {}  # telegram_id -> user_data
        self._dirty: dict[int, bool] = {}  # telegram_id -> True
        self._lock = threading.Lock()
        self._steam_index: dict[int, int] = {}  # steam_id -> telegram_id reverse index

    def invalidate_user_top_caches(self, telegram_id: int):
        keys_to_remove = []
        with self._lock:
            for k in self._cache.keys():
                if isinstance(k, str) and k.startswith(('fissure_top_', 'mmr_top_', 'dota_week_top_', 'user_rank_', 'fissure_rank_', 'digest_stats', 'dota_digest_stats', 'weekly_digest_stats')):
                    keys_to_remove.append(k)
            for k in keys_to_remove:
                self._cache.pop(k, None)

    def get(self, telegram_id: int) -> dict[str, Any] | None:
        with self._lock:
            data = self._cache.get(telegram_id)
            if data is None:
                return None
            if isinstance(data, dict):
                return dict(data)
            if isinstance(data, list):
                return list(data)
            return data

    def set(self, telegram_id, data, skip_dirty=False):
        """Установить данные пользователя в кеш"""
        # Handle string keys for non-user caches (like 'dota_week_top')
        if isinstance(telegram_id, str):
            with self._lock:
                if len(self._cache) >= self.MAX_CACHE_SIZE:
                    self._evict_lru()
                self._cache[telegram_id] = data
            return

        # Prevent SteamID64 from being used as telegram_id key
        if isinstance(telegram_id, int) and telegram_id > 76561190000000000:
            logger.warning(f"UserCache.set: rejecting SteamID64 as telegram_id key={telegram_id}")
            return
        with self._lock:
            if len(self._cache) >= self.MAX_CACHE_SIZE:
                self._evict_lru()
            self._cache[telegram_id] = data
            self._dirty[telegram_id] = not skip_dirty
            # Update steam index
            steam_id = data.get('steam_id')
            if steam_id and isinstance(steam_id, int):
                self._steam_index[steam_id] = telegram_id
            elif telegram_id in self._steam_index.values():
                for sid, tid in list(self._steam_index.items()):
                    if tid == telegram_id:
                        del self._steam_index[sid]
                        break

    def set_without_dirty(self, telegram_id, data):
        """Установить данные без установки dirty-флага (для загрузки из БД)"""
        self.set(telegram_id, data, skip_dirty=True)

    def mark_dirty(self, telegram_id):
        """Пометить пользователя как изменённого"""
        with self._lock:
            self._dirty[telegram_id] = True

    def is_dirty(self, telegram_id):
        """Проверить, изменён ли пользователь"""
        with self._lock:
            return self._dirty.get(telegram_id, False)

    def get_all_dirty(self):
        """Получить список всех изменённых пользователей"""
        with self._lock:
            return [tid for tid, is_dirty in self._dirty.items() if is_dirty]

    def clear_dirty(self, telegram_id):
        """Очистить флаг dirty для пользователя"""
        with self._lock:
            self._dirty[telegram_id] = False

    def get_all_users(self):
        """Получить всех пользователей из кеша"""
        with self._lock:
            return list(self._cache.keys())

    def remove(self, telegram_id):
        """Удалить пользователя из кеша"""
        with self._lock:
            self._cache.pop(telegram_id, None)
            self._dirty.pop(telegram_id, None)

    def delete(self, telegram_id):
        """Псевдоним для remove для обратной совместимости"""
        self.remove(telegram_id)

    def delete_key(self, key):
        """Удалить конкретный ключ из кеша"""
        with self._lock:
            self._cache.pop(key, None)
            self._dirty.pop(key, None)

    def update_username_lookup(self, old_username, new_username, telegram_id):
        """Update username_lookup cache when a user's username changes.
        
        Removes stale old_username mapping and adds new_username -> telegram_id.
        This prevents stale cache entries when users change their Telegram username.
        """
        with self._lock:
            lookup = self._cache.get('username_lookup')
            if not lookup:
                return
            old_norm = old_username.lstrip("@").lower() if old_username else None
            new_norm = new_username.lstrip("@").lower() if new_username else None
            if old_norm and old_norm in lookup:
                del lookup[old_norm]
            if new_norm:
                lookup[new_norm] = telegram_id
            self._cache['username_lookup'] = dict(lookup)

    def clear(self):
        """Очистить весь кеш"""
        with self._lock:
            self._cache.clear()
            self._dirty.clear()

    def _evict_lru(self):
        """Evict half the cache when limit reached (simple LRU approximation)."""
        keys_to_remove = list(self._cache.keys())[:len(self._cache) // 2]
        for key in keys_to_remove:
            self._cache.pop(key, None)
            self._dirty.pop(key, None)

    def enforce_limit(self):
        with self._lock:
            if len(self._cache) > self.MAX_CACHE_SIZE:
                self._evict_lru()


# Глобальный экземпляр кеша
user_cache = UserCache()


class TTLCache:
    """Кеш с автоматическим истечением по времени (TTL)"""

    def __init__(self, default_ttl=60):
        self._cache = {}  # key -> (value, expiry_time)
        self._lock = threading.Lock()
        self._default_ttl = default_ttl  # TTL в секундах

    def get(self, key):
        """Получить значение из кеша"""
        with self._lock:
            if key in self._cache:
                value, expiry = self._cache[key]
                if time.time() < expiry:
                    return value
                else:
                    # Кеш истёк, удаляем
                    del self._cache[key]
        return None

    def set(self, key, value, ttl=None):
        """Установить значение в кеш с TTL"""
        if ttl is None:
            ttl = self._default_ttl
        with self._lock:
            self._cache[key] = (value, time.time() + ttl)

    def delete(self, key):
        """Удалить значение из кеша"""
        with self._lock:
            self._cache.pop(key, None)

    def clear(self):
        """Очистить весь кеш"""
        with self._lock:
            self._cache.clear()

    def invalidate_top_cache(self):
        keys_to_remove = [k for k in list(self._cache.keys()) if isinstance(k, str) and k.startswith(('fissure_top_', 'mmr_top_', 'dota_week_top_', 'user_rank_', 'fissure_rank_'))]
        with self._lock:
            for k in keys_to_remove:
                self._cache.pop(k, None)

    def get_timestamp(self, key):
        """Получить timestamp создания/обновления записи"""
        with self._lock:
            if key in self._cache:
                _, expiry = self._cache[key]
                return expiry - self._default_ttl
        return 0


class UserStateManager:
    """Unified state manager for user data with atomic cache invalidation."""

    _DEPENDENT_KEYS = (
        'dota_week_top', 'dota_week_top_ts',
        'digest_stats', 'weekly_digest_stats', 'dota_digest_stats',
    )

    def __init__(self, user_cache: UserCache, top_cache: TTLCache) -> None:
        self._user_cache = user_cache
        self._top_cache = top_cache

    def apply_user_update(self, telegram_id: int, fields: dict, save_to_db: bool = True) -> dict:
        user = self._user_cache.get(telegram_id)
        if not user:
            return {}

        for key, value in fields.items():
            user[key] = value

        self._user_cache.set(telegram_id, user)
        self._user_cache.mark_dirty(telegram_id)

        if save_to_db:
            _save_user_to_db_immediately(telegram_id, user)

        self._invalidate_dependent_caches(telegram_id)
        return dict(user)

    def _invalidate_dependent_caches(self, telegram_id: int) -> None:
        for key in self._DEPENDENT_KEYS:
            self._user_cache.delete(key)
        self._top_cache.invalidate_top_cache()

    def flush_dirty(self) -> int:
        return flush_users_cache()

    def get_all_users(self):
        return self._user_cache.get_all_users()


# Глобальные экземпляры кешей (оптимизировано для экономии CU в serverless)
config_cache = TTLCache(default_ttl=300)  # 5 минут для конфигурации
top_cache = TTLCache(default_ttl=1800)  # 30 минут для топов и рангов

user_state_manager = UserStateManager(user_cache, top_cache)

_aiohttp_session = None

async def get_aiohttp_session():
    """Получить переиспользуемую aiohttp сессию для оптимизации соединений.
    Создаёт новую сессию, если предыдущая закрыта или event loop изменился.
    """
    global _aiohttp_session
    try:
        if _aiohttp_session is None or _aiohttp_session.closed:
            import aiohttp
            _aiohttp_session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=15, connect=5),
                connector=aiohttp.TCPConnector(limit=5, limit_per_host=3)
            )
        return _aiohttp_session
    except RuntimeError as e:
        if "Event loop is closed" in str(e):
            logger.warning("Event loop closed, creating new aiohttp session")
            import aiohttp
            _aiohttp_session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=15, connect=5),
                connector=aiohttp.TCPConnector(limit=5, limit_per_host=3)
            )
            return _aiohttp_session
        raise

async def close_aiohttp_session():
    """Закрыть aiohttp сессию при выключении бота"""
    global _aiohttp_session
    if _aiohttp_session and not _aiohttp_session.closed:
        await _aiohttp_session.close()
        _aiohttp_session = None


async def flush_users_cache(max_retries: int = 3):
    """Сброс всех изменённых пользователей в БД с использованием batch операций"""
    dirty_users = user_cache.get_all_dirty()
    if not dirty_users:
        logger.info("flush_users_cache: no dirty users")
        return 0

    logger.info(f"flush_users_cache: found {len(dirty_users)} dirty users, saving to DB")

    db_type = get_db_type()
    flushed = 0

    for attempt in range(max_retries):
        conn = None
        cursor = None
        try:
            conn = get_connection()
            cursor = conn.cursor()

            batch_data = []
            for telegram_id in dirty_users:
                if not isinstance(telegram_id, int) or telegram_id > 76561190000000000:
                    logger.warning(f"flush_users_cache: skipping user with invalid telegram_id={telegram_id}")
                    continue

                user_data = user_cache.get(telegram_id)
                if user_data:
                    batch_data.append((
                        user_data.get('username'), user_data.get('fissure', 0),
                        user_data.get('last_fissure', 0), user_data.get('total_growth', 0),
                        user_data.get('total_rolls', 0), user_data.get('current_streak', 0),
                        user_data.get('best_streak', 0), user_data.get('weekly_rolls', 0),
                        user_data.get('weekly_growth', 0), user_data.get('steam_id'),
                        user_data.get('steam_nickname'), user_data.get('mmr', 0),
                        user_data.get('rank_tier', 0), user_data.get('dota_total_games', 0),
                        user_data.get('dota_wins', 0), user_data.get('last_dota_games', 0),
                        user_data.get('last_dota_wins', 0), user_data.get('week_games', 0),
                        user_data.get('week_wins', 0), user_data.get('week_best_streak', 0),
                        user_data.get('week_start_date'), telegram_id
                    ))

            if batch_data:
                if db_type == "postgresql":
                    query = """
                        UPDATE users SET 
                            username = %s, fissure = %s, last_fissure = %s,
                            total_growth = %s, total_rolls = %s, current_streak = %s,
                            best_streak = %s, weekly_rolls = %s, weekly_growth = %s,
                            steam_id = %s, steam_nickname = %s, mmr = %s, rank_tier = %s,
                            dota_total_games = %s, dota_wins = %s, last_dota_games = %s,
                            last_dota_wins = %s, week_games = %s, week_wins = %s,
                            week_best_streak = %s, week_start_date = %s, last_activity = CURRENT_TIMESTAMP
                        WHERE telegram_id = %s
                    """
                    psycopg2.extras.execute_batch(cursor, query, batch_data, page_size=100)
                else:
                    query = """
                        UPDATE users SET 
                            username = ?, fissure = ?, last_fissure = ?,
                            total_growth = ?, total_rolls = ?, current_streak = ?,
                            best_streak = ?, weekly_rolls = ?, weekly_growth = ?,
                            steam_id = ?, steam_nickname = ?, mmr = ?, rank_tier = ?,
                            dota_total_games = ?, dota_wins = ?, last_dota_games = ?,
                            last_dota_wins = ?, week_games = ?, week_wins = ?,
                            week_best_streak = ?, week_start_date = ?, last_activity = CURRENT_TIMESTAMP
                        WHERE telegram_id = ?
                    """
                    cursor.executemany(query, batch_data)

                flushed = len(batch_data)
                for i in range(flushed):
                    telegram_id = batch_data[i][-1]
                    user_cache.clear_dirty(telegram_id)

                top_cache.invalidate_top_cache()

            conn.commit()
            break

        except Exception as e:
            logger.error(f"flush_users_cache: batch error (attempt {attempt + 1}/{max_retries}): {e}")
            if conn:
                conn.rollback()
            if attempt == max_retries - 1:
                logger.error(f"flush_users_cache: failed after {max_retries} attempts")
                raise
            import asyncio
            await asyncio.sleep(2 ** attempt)
        finally:
            if cursor:
                cursor.close()
            if conn:
                release_connection(conn)

    logger.info(f"flush_users_cache: flushed {flushed} users")
    return flushed


def update_dota_week_top_cache():
    """Обновление кэша топа MMR из данных пользователей"""
    all_users = user_cache.get_all_users()

    # Если в кеше нет пользователей - загружаем из БД
    if not all_users:
        logger.info("update_dota_week_top_cache: no users in cache, loading from DB")
        try:
            db_users = get_all_users_with_steam()
            for u in db_users:
                user_cache.set(u['telegram_id'], u, skip_dirty=True)
            all_users = user_cache.get_all_users()
            logger.info(f"update_dota_week_top_cache: loaded {len(all_users)} users from DB to cache")
        except Exception as e:
            logger.error(f"update_dota_week_top_cache: error loading users: {e}")

    if not all_users:
        logger.info("update_dota_week_top_cache: no users found")
        return

    top_users = []
    for telegram_id in all_users:
        # Пропускаем метаданные (не числовые ключи)
        if not isinstance(telegram_id, int):
            continue

        user = user_cache.get(telegram_id)
        if not user or not user.get('steam_id'):
            continue

        week_games = user.get('week_games') or 0
        week_wins = user.get('week_wins') or 0
        winrate = round(week_wins / week_games * 100) if week_games > 0 else 0

        top_users.append({
            'telegram_id': telegram_id,
            'username': user.get('username'),
            'steam_nickname': user.get('steam_nickname'),
            'mmr': user.get('mmr', 0),
            'week_games': week_games,
            'week_wins': week_wins,
            'rank_tier': user.get('rank_tier', 0),
            'winrate': winrate,
            'week_current_streak': user.get('week_current_streak', 0)
        })

    # Сортировка: score = 2 * week_wins - week_games (победы - поражения)
    # Игроки без игр за неделю идут в самый конец
    def get_sort_key(x):
        g = x.get('week_games', 0)
        w = x.get('week_wins', 0)
        if g == 0:
            return (1, 0, 0)  # Помещаем в самый конец
        score = w - (g - w)  # wins - losses
        return (0, -score, -g)  # Сортировка по убыванию score, затем по убыванию игр

    top_users.sort(key=get_sort_key)

    logger.info("===== TOP USERS AFTER SORT =====")
    for i, u in enumerate(top_users):
        week_losses = (u.get('week_games') or 0) - (u.get('week_wins') or 0)
        logger.info(f"  POS{i+1}. {u.get('steam_nickname')}: {u.get('week_wins')}W/{week_losses}L, WR={u.get('winrate')}%")
    logger.info("===== END SORT =====")

    # Сохраняем в кеш (память + база)
    user_cache.set('dota_week_top', top_users)
    logger.info(f"update_dota_week_top_cache: cached {len(top_users)} users")


def restore_dota_week_top_cache():
    """Восстановление кеша топа MMR из базы после рестарта"""
    cached = get_config('dota_week_top_cache')
    if cached:
        try:
            top_users = json.loads(cached)
            # Restore individual users to user_cache
            for u in top_users:
                if 'telegram_id' in u:
                    user_cache.set(u['telegram_id'], u)
            user_cache.set('dota_week_top', top_users)
            logger.info(f"restore_dota_week_top_cache: restored {len(top_users)} users from database cache")
            return True
        except Exception as e:
            logger.error(f"restore_dota_week_top_cache: error parsing cache: {e}")
    return False


# Connection pool management
_pool_lock = threading.Lock()
_pool = {}
_max_connections = 50

SCHEMA_VERSION = "20260613v1"
SCHEMA_VERSION_KEY = "schema_version"

# PostgreSQL connection pool
_pg_pool = None
_pg_pool_lock = threading.Lock()

def _pg_dsn():
    """DSN для PostgreSQL-пула: sslmode, connect_timeout и TCP keepalive.

    keepalives не даёт прокси/серверу разорвать idle-соединение
    (причина предупреждений 'SSL connection has been closed unexpectedly')."""
    import urllib.parse as urlparse
    parsed = urlparse.urlparse(DATABASE_URL)
    dsn = DATABASE_URL
    params = []
    if "postgres" in parsed.scheme and "sslmode" not in dsn:
        params.append("sslmode=require")
    if "connect_timeout" not in dsn:
        params.append("connect_timeout=10")
    # TCP keepalive, чтобы idle-соединения не рвались
    params.append("keepalives=1")
    params.append("keepalives_idle=240")
    params.append("keepalives_interval=30")
    params.append("keepalives_count=5")
    if params:
        sep = "&" if "?" in dsn else "?"
        dsn = f"{dsn}{sep}{'&'.join(params)}"
    return dsn


def get_pg_connection():
    """Get a PostgreSQL connection from the pool"""
    global _pg_pool
    if _pg_pool is None:
        with _pg_pool_lock:
            if _pg_pool is None:
                try:
                    import urllib.parse as urlparse

                    from psycopg2 import pool
                    parsed = urlparse.urlparse(DATABASE_URL)
                    dsn = _pg_dsn()
                    _pg_pool = pool.ThreadedConnectionPool(
                        minconn=1,
                        maxconn=15,
                        dsn=dsn
                    )
                except Exception as e:
                    logger.warning(f"Failed to create psycopg2 pool: {e}")
                    _pg_pool = None
    if _pg_pool is None:
        return get_connection()
    try:
        conn = _pg_pool.getconn()
        if conn and not conn.closed:
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT 1")
                cursor.close()
                return conn
            except Exception as e:
                logger.debug(f"Connection is broken, resetting pool: {e}")
                try:
                    conn.close()
                except Exception:
                    pass
                _reset_persistent_pg_conn(str(e))
        else:
            _reset_persistent_pg_conn("closed connection returned from pool")
    except Exception as e:
        logger.warning(f"Pool connection error, recreating: {e}")
        _reset_persistent_pg_conn(str(e))
    # Retry once after pool reset — recreate pool and get a fresh connection
    try:
        with _pg_pool_lock:
            if _pg_pool is None:
                try:
                    import urllib.parse as urlparse

                    from psycopg2 import pool
                    parsed = urlparse.urlparse(DATABASE_URL)
                    dsn = _pg_dsn()
                    _pg_pool = pool.ThreadedConnectionPool(minconn=1, maxconn=15, dsn=dsn)
                except Exception as e:
                    logger.warning(f"Failed to recreate psycopg2 pool: {e}")
                    _pg_pool = None
        if _pg_pool is not None:
            conn = _pg_pool.getconn()
            if conn and not conn.closed:
                try:
                    cursor = conn.cursor()
                    cursor.execute("SELECT 1")
                    cursor.close()
                    return conn
                except Exception as e:
                    logger.debug(f"Fresh connection broken, resetting pool: {e}")
                    try:
                        conn.close()
                    except Exception:
                        pass
                    _reset_persistent_pg_conn(str(e))
    except Exception as e:
        logger.warning(f"Failed to get pg connection after pool reset: {e}")
    return get_connection()

def release_pg_connection(conn):
    """Release a PostgreSQL connection back to the pool"""
    global _pg_pool
    if conn is None:
        return
    # Только PG-соединения (psycopg2) принадлежат пулу. SQLite-фолбэк-конн,
    # который возвращает get_pg_connection при сбое пула, сюда попадать не должен
    # (иначе psycopg2 бросает "trying to put unkeyed connection").
    try:
        from psycopg2 import extensions as _pg_ext
    except Exception:
        _pg_ext = None
    if _pg_ext is not None and not isinstance(conn, _pg_ext.connection):
        return
    if _pg_pool is not None:
        try:
            _pg_pool.putconn(conn)
        except Exception:
            try:
                conn.close()
            except Exception as close_err:
                logger.debug(f"Failed to close PG connection after pool error: {close_err}")


def close_pg_pool():
    """Close PostgreSQL connection pool"""
    global _pg_pool
    if _pg_pool is not None:
        try:
            _pg_pool.closeall()
            logger.info("PostgreSQL pool closed")
        except Exception as e:
            logger.warning(f"Failed to close pg pool: {e}")
        _pg_pool = None
    # No fallback needed - if pool is None, there's nothing to close

_PG_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_users_fissure ON users(fissure DESC)",
    "CREATE INDEX IF NOT EXISTS idx_users_mmr ON users(mmr DESC)",
    "CREATE INDEX IF NOT EXISTS idx_users_steam_id ON users(steam_id)",
    "CREATE INDEX IF NOT EXISTS idx_users_week_games ON users(week_games DESC)",
    "CREATE INDEX IF NOT EXISTS idx_users_current_position ON users(current_position)",
    "CREATE INDEX IF NOT EXISTS idx_users_rank_tier ON users(rank_tier DESC)",
    "CREATE INDEX IF NOT EXISTS idx_users_in_chat ON users(in_chat)",
    "CREATE INDEX IF NOT EXISTS idx_users_username ON users(LOWER(username))",
    "CREATE INDEX IF NOT EXISTS idx_users_week_active ON users(steam_id, week_games DESC) WHERE steam_id IS NOT NULL AND week_games > 0",
    "CREATE INDEX IF NOT EXISTS idx_users_daily_best_growth ON users(daily_best_growth DESC)",
    # Critical composite indexes for top queries
    "CREATE INDEX IF NOT EXISTS idx_users_mmr_steam ON users(mmr DESC) WHERE steam_id IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS idx_users_fissure_inchat ON users(fissure DESC) WHERE in_chat",
    "CREATE INDEX IF NOT EXISTS idx_users_last_activity ON users(last_activity) WHERE in_chat",
)

# Лёгкие миграции — выполняются даже при fast init (ADD IF NOT EXISTS)
_PG_ENSURE_COLUMNS = (
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS week_updated_at TIMESTAMP",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS mmr_last_updated REAL",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS weekly_mvp INTEGER DEFAULT 0",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS weekly_top2 INTEGER DEFAULT 0",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS weekly_top3 INTEGER DEFAULT 0",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS user_tags TEXT DEFAULT '[]'",
    "UPDATE users SET in_chat = TRUE WHERE in_chat IS NULL OR in_chat = FALSE",
)


def _ensure_pg_columns(cursor):
    for sql in _PG_ENSURE_COLUMNS:
        cursor.execute(sql)


def _reset_persistent_pg_conn(reason: str = ""):
    """Reset the PostgreSQL connection pool on connection errors."""
    global _pg_pool
    if reason:
        logger.warning(f"Resetting PostgreSQL pool: {reason}")
    if _pg_pool is not None:
        try:
            _pg_pool.closeall()
        except Exception as e:
            logger.debug(f"Error closing pool: {e}")
        _pg_pool = None


def get_db_type():
    if DATABASE_URL is None:
        logger.warning("DATABASE_URL is None, using SQLite")
        return "sqlite"
    url = urlparse.urlparse(DATABASE_URL)
    scheme = url.scheme.lower()
    if scheme in ("postgresql", "postgres", "pg"):
        return "postgresql"
    elif scheme == "sqlite":
        return "sqlite"
    else:
        logger.warning(f"Unknown DB scheme: {scheme}, defaulting to SQLite")
        return "sqlite"


def _postgres_connect_kwargs():
    """Разобрать DATABASE_URL для psycopg2 (libpq не понимает pgbouncer=true)."""
    url = urlparse.urlparse(DATABASE_URL)
    query = urlparse.parse_qs(url.query, keep_blank_values=True)
    query.pop("pgbouncer", None)
    query.pop("channel_binding", None)  # Remove channel_binding - not supported by psycopg2

    sslmode = (query.pop("sslmode", None) or ["require"])[0]
    kwargs = {
        "dbname": (url.path or "").lstrip("/"),
        "user": url.username,
        "password": url.password,
        "host": url.hostname,
        "port": url.port or 5432,
        "sslmode": sslmode,
        "connect_timeout": 10,
        # TCP keepalive: не даём прокси/серверу разорвать idle-соединение (причина "SSL connection has been closed unexpectedly")
        "keepalives": 1,
        "keepalives_idle": 240,
        "keepalives_interval": 30,
        "keepalives_count": 5,
    }
    # Add statement timeout to prevent runaway queries
    query.pop("options", None)
    kwargs["options"] = "-c statement_timeout=30000"  # 30s max query time
    for key in ("sslrootcert", "sslcert", "sslkey", "application_name"):
        if key in query and query[key]:
            kwargs[key] = query[key][0]
    return kwargs


def get_connection():
    """Получение соединения с базой данных"""
    db_type = get_db_type()
    if db_type == "postgresql":
        return get_pg_connection()
    with _pool_lock:
        if db_type in _pool and _pool[db_type]:
            conn = _pool[db_type].pop()
            try:
                return conn
            except Exception as e:
                logger.debug(f"Pool connection failed: {e}")
                try:
                    conn.close()
                except Exception:
                    pass
        return _create_new_connection(db_type)


def _create_new_connection(db_type):
    """Создать новое соединение с БД"""
    if db_type == "postgresql":
        try:
            conn = psycopg2.connect(**_postgres_connect_kwargs())
            conn.autocommit = True
            logger.debug("PostgreSQL connected (short-lived)")
            return conn
        except Exception as e:
            logger.error(f"PostgreSQL connection failed: {e}")
            raise
    else:
        db_path = "fissure_bot.db"
        if DATABASE_URL and DATABASE_URL.startswith("sqlite:///"):
            db_path = DATABASE_URL[10:]
        elif DATABASE_URL and DATABASE_URL.startswith("sqlite://"):
            db_path = DATABASE_URL[9:]
        conn = sqlite3.connect(db_path, timeout=10)
        logger.debug("SQLite connected")
        return conn


def release_connection(conn):
    """Закрыть соединение или вернуть в пул (только SQLite)"""
    if conn is None:
        return
    db_type = get_db_type()
    if db_type == "postgresql":
        release_pg_connection(conn)
        return
    with _pool_lock:
        if db_type not in _pool:
            _pool[db_type] = []
        if len(_pool[db_type]) < _max_connections:
            _pool[db_type].append(conn)
        else:
            try:
                conn.close()
            except Exception:
                pass

@contextmanager
def get_db_connection():
    """Контекстный менеджер для безопасного управления соединениями"""
    conn = None
    try:
        conn = get_connection()
        yield conn
        conn.commit()
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"Database transaction failed: {e}")
        raise
    finally:
        release_connection(conn)


@contextmanager
def db_transaction():
    """Async-safe transaction context manager"""
    conn = None
    try:
        conn = get_connection()
        cursor = conn.cursor()
        yield cursor
        conn.commit()
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"Transaction failed: {e}")
        raise
    finally:
        if conn:
            release_connection(conn)

def _save_schema_version(cursor, is_pg):
    if is_pg:
        cursor.execute(
            """
            INSERT INTO bot_config (key, value) VALUES (%s, %s)
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
            """,
            (SCHEMA_VERSION_KEY, SCHEMA_VERSION),
        )
    else:
        cursor.execute(
            """
            INSERT INTO bot_config (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (SCHEMA_VERSION_KEY, SCHEMA_VERSION),
        )


def init_db():
    """Initialize database tables and add missing columns."""
    conn = None
    try:
        conn = get_connection()
        cursor = conn.cursor()
        url = urlparse.urlparse(DATABASE_URL)
        scheme = url.scheme or ""
        is_pg = "postgres" in scheme

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS bot_config (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)

        if is_pg:
            cursor.execute(
                "SELECT value FROM bot_config WHERE key = %s",
                (SCHEMA_VERSION_KEY,),
            )
        else:
            cursor.execute(
                "SELECT value FROM bot_config WHERE key = ?",
                (SCHEMA_VERSION_KEY,),
            )
        row = cursor.fetchone()
        if row and row[0] == SCHEMA_VERSION:
            if is_pg:
                _ensure_pg_columns(cursor)
            conn.commit()
            logger.info("init_db: schema up to date, skipped DDL")
            return

        if is_pg:
            # Создаём таблицу если не существует
            cursor.execute("""
                 CREATE TABLE IF NOT EXISTS users (
                     id SERIAL PRIMARY KEY,
                     telegram_id BIGINT UNIQUE NOT NULL,
                     username VARCHAR(255),
                     fissure REAL DEFAULT 0.1,
                     last_fissure DOUBLE PRECISION DEFAULT 0,
                     last_message_id INTEGER DEFAULT 0,
                     total_growth REAL DEFAULT 0,
                     total_rolls INTEGER DEFAULT 0,
                     message_count INTEGER DEFAULT 0,
                     last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                     current_streak INTEGER DEFAULT 0,
                     best_streak INTEGER DEFAULT 0,
                     current_position INTEGER DEFAULT 0,
                     digest_position INTEGER DEFAULT 0,
                     digest_fissure REAL DEFAULT 0.0
                 )
            """)
            # Добавляем колонки если не существуют
            cursor.execute("""
                ALTER TABLE users ADD COLUMN IF NOT EXISTS last_message_id INTEGER DEFAULT 0
            """)
            cursor.execute("""
                ALTER TABLE users ADD COLUMN IF NOT EXISTS total_growth REAL DEFAULT 0
            """)
            cursor.execute("""
                ALTER TABLE users ADD COLUMN IF NOT EXISTS total_rolls INTEGER DEFAULT 0
            """)
            cursor.execute("""
                ALTER TABLE users ADD COLUMN IF NOT EXISTS last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            """)
            cursor.execute("""
                ALTER TABLE users ADD COLUMN IF NOT EXISTS current_streak INTEGER DEFAULT 0
            """)
            cursor.execute("""
                ALTER TABLE users ADD COLUMN IF NOT EXISTS best_streak INTEGER DEFAULT 0
            """)
            cursor.execute("""
                ALTER TABLE users ADD COLUMN IF NOT EXISTS current_position INTEGER DEFAULT 0
            """)
            cursor.execute("""
                ALTER TABLE users ADD COLUMN IF NOT EXISTS digest_position INTEGER DEFAULT 0
            """)
            cursor.execute("""
                ALTER TABLE users ADD COLUMN IF NOT EXISTS digest_fissure REAL DEFAULT 0.0
            """)
            cursor.execute("""
                ALTER TABLE users ADD COLUMN IF NOT EXISTS weekly_rolls INTEGER DEFAULT 0
            """)
            cursor.execute("""
                ALTER TABLE users ADD COLUMN IF NOT EXISTS weekly_growth REAL DEFAULT 0.0
            """)
            cursor.execute("""
                ALTER TABLE users ADD COLUMN IF NOT EXISTS daily_best_growth REAL DEFAULT 0.0
            """)
            cursor.execute("""
                ALTER TABLE users ADD COLUMN IF NOT EXISTS weekly_digest_position INTEGER DEFAULT 0
            """)
            cursor.execute("""
                ALTER TABLE users ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT NULL
            """)
            cursor.execute("""
                ALTER TABLE users ADD COLUMN IF NOT EXISTS message_count INTEGER DEFAULT 0
            """)
            # Dota 2 поля
            cursor.execute("""
                ALTER TABLE users ADD COLUMN IF NOT EXISTS steam_id BIGINT
            """)
            cursor.execute("""
                ALTER TABLE users ADD COLUMN IF NOT EXISTS steam_nickname VARCHAR(255)
            """)
            cursor.execute("""
                ALTER TABLE users ADD COLUMN IF NOT EXISTS mmr INTEGER DEFAULT 0
            """)
            cursor.execute("""
                ALTER TABLE users ADD COLUMN IF NOT EXISTS dota_total_games INTEGER DEFAULT 0
            """)
            cursor.execute("""
                ALTER TABLE users ADD COLUMN IF NOT EXISTS dota_wins INTEGER DEFAULT 0
            """)
            cursor.execute("""
                ALTER TABLE users ADD COLUMN IF NOT EXISTS week_games INTEGER DEFAULT 0
            """)
            cursor.execute("""
                ALTER TABLE users ADD COLUMN IF NOT EXISTS week_wins INTEGER DEFAULT 0
            """)
            cursor.execute("""
                ALTER TABLE users ADD COLUMN IF NOT EXISTS last_dota_games INTEGER DEFAULT 0
            """)
            cursor.execute("""
                ALTER TABLE users ADD COLUMN IF NOT EXISTS last_dota_wins INTEGER DEFAULT 0
            """)
            cursor.execute("""
                ALTER TABLE users ADD COLUMN IF NOT EXISTS mmr_updated_at TIMESTAMP
            """)
            cursor.execute("""
                ALTER TABLE users ADD COLUMN IF NOT EXISTS analytics_cache TEXT
            """)
            cursor.execute("""
                ALTER TABLE users ADD COLUMN IF NOT EXISTS analytics_updated_at TIMESTAMP
            """)
            cursor.execute("""
                ALTER TABLE users ADD COLUMN IF NOT EXISTS rank_tier INTEGER DEFAULT 0
            """)
            cursor.execute("""
                ALTER TABLE users ADD COLUMN IF NOT EXISTS wins INTEGER DEFAULT 0
            """)
            cursor.execute("""
                ALTER TABLE users ADD COLUMN IF NOT EXISTS losses INTEGER DEFAULT 0
            """)
            cursor.execute("""
                ALTER TABLE users ADD COLUMN IF NOT EXISTS last_match_id BIGINT DEFAULT 0
            """)
            cursor.execute("""
                ALTER TABLE users ADD COLUMN IF NOT EXISTS week_start_date DATE
            """)
            cursor.execute("""
                ALTER TABLE users ADD COLUMN IF NOT EXISTS week_best_streak INTEGER DEFAULT 0
            """)
            cursor.execute("""
                ALTER TABLE users ADD COLUMN IF NOT EXISTS week_current_streak INTEGER DEFAULT 0
            """)
            cursor.execute("""
                ALTER TABLE users ADD COLUMN IF NOT EXISTS in_chat BOOLEAN DEFAULT TRUE
            """)
            cursor.execute("""
                ALTER TABLE users ADD COLUMN IF NOT EXISTS last_greeting_date DATE
            """)
            cursor.execute("""
                ALTER TABLE users ADD COLUMN IF NOT EXISTS first_name TEXT
            """)
            # Новые столбцы для раздельных серий побед/поражений
            cursor.execute("""
                ALTER TABLE users ADD COLUMN IF NOT EXISTS current_win_streak INTEGER DEFAULT 0
            """)
            cursor.execute("""
                ALTER TABLE users ADD COLUMN IF NOT EXISTS current_lose_streak INTEGER DEFAULT 0
            """)
            cursor.execute("""
                ALTER TABLE users ADD COLUMN IF NOT EXISTS best_lose_streak INTEGER DEFAULT 0
            """)
            cursor.execute("""
                ALTER TABLE users ADD COLUMN IF NOT EXISTS avatar TEXT
            """)
            cursor.execute("""
                ALTER TABLE users ADD COLUMN IF NOT EXISTS week_updated_at TIMESTAMP
            """)
            _ensure_pg_columns(cursor)
            for index_sql in _PG_INDEXES:
                cursor.execute(index_sql)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS chat_messages (
                    id SERIAL PRIMARY KEY,
                    chat_id BIGINT NOT NULL,
                    user_id BIGINT,
                    message_text TEXT,
                    is_bot BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_chat_messages_chat_id ON chat_messages(chat_id, created_at DESC)")
        else:
            # Для SQLite создаём таблицу
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_id INTEGER UNIQUE NOT NULL,
                    username TEXT,
                    fissure REAL DEFAULT 0.1,
                    last_fissure REAL DEFAULT 0,
                    last_message_id INTEGER DEFAULT 0,
                    total_growth REAL DEFAULT 0,
                    total_rolls INTEGER DEFAULT 0,
                    last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    current_streak INTEGER DEFAULT 0,
                    best_streak INTEGER DEFAULT 0,
                    current_position INTEGER DEFAULT 0,
                    digest_position INTEGER DEFAULT 0,
                    digest_fissure REAL DEFAULT 0.0,
                    weekly_rolls INTEGER DEFAULT 0,
weekly_growth REAL DEFAULT 0.0,
                     daily_best_growth REAL DEFAULT 0.0,
                     weekly_digest_position INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT NULL,
                    steam_id INTEGER,
                    steam_nickname TEXT,
                    mmr INTEGER DEFAULT 0,
                    dota_total_games INTEGER DEFAULT 0,
                    dota_wins INTEGER DEFAULT 0,
                    week_games INTEGER DEFAULT 0,
                    week_wins INTEGER DEFAULT 0,
                    last_dota_games INTEGER DEFAULT 0,
                    last_dota_wins INTEGER DEFAULT 0,
                    mmr_updated_at TIMESTAMP,
                    mmr_last_updated TIMESTAMP,
                    rank_tier INTEGER DEFAULT 0,
wins INTEGER DEFAULT 0,
                     losses INTEGER DEFAULT 0,
                     last_match_id INTEGER DEFAULT 0,
                     week_start_date DATE,
                     week_best_streak INTEGER DEFAULT 0,
                     week_current_streak INTEGER DEFAULT 0,
                     in_chat BOOLEAN DEFAULT 1,
                     last_greeting_date DATE,
                     message_count INTEGER DEFAULT 0,
                     first_name TEXT,
                     current_win_streak INTEGER DEFAULT 0,
                     current_lose_streak INTEGER DEFAULT 0,
                     best_lose_streak INTEGER DEFAULT 0,
                     avatar TEXT
                 )
            """)
# Для SQLite проверяем есть ли колонки и добавляем если нет
            cursor.execute("PRAGMA table_info(users)")
            columns = [col[1] for col in cursor.fetchall()]
            if 'last_message_id' not in columns:
                cursor.execute("ALTER TABLE users ADD COLUMN last_message_id INTEGER DEFAULT 0")
            if 'total_growth' not in columns:
                cursor.execute("ALTER TABLE users ADD COLUMN total_growth REAL DEFAULT 0")
            if 'total_rolls' not in columns:
                cursor.execute("ALTER TABLE users ADD COLUMN total_rolls INTEGER DEFAULT 0")
            if 'message_count' not in columns:
                cursor.execute("ALTER TABLE users ADD COLUMN message_count INTEGER DEFAULT 0")
            if 'last_activity' not in columns:
                cursor.execute("ALTER TABLE users ADD COLUMN last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
            if 'current_streak' not in columns:
                cursor.execute("ALTER TABLE users ADD COLUMN current_streak INTEGER DEFAULT 0")
            if 'best_streak' not in columns:
                cursor.execute("ALTER TABLE users ADD COLUMN best_streak INTEGER DEFAULT 0")
            if 'current_position' not in columns:
                cursor.execute("ALTER TABLE users ADD COLUMN current_position INTEGER DEFAULT 0")
            if 'digest_position' not in columns:
                cursor.execute("ALTER TABLE users ADD COLUMN digest_position INTEGER DEFAULT 0")
            if 'digest_fissure' not in columns:
                cursor.execute("ALTER TABLE users ADD COLUMN digest_fissure REAL DEFAULT 0.0")
            if 'weekly_rolls' not in columns:
                cursor.execute("ALTER TABLE users ADD COLUMN weekly_rolls INTEGER DEFAULT 0")
            if 'weekly_growth' not in columns:
                cursor.execute("ALTER TABLE users ADD COLUMN weekly_growth REAL DEFAULT 0.0")
            if 'daily_best_growth' not in columns:
                cursor.execute("ALTER TABLE users ADD COLUMN daily_best_growth REAL DEFAULT 0.0")
            if 'weekly_digest_position' not in columns:
                cursor.execute("ALTER TABLE users ADD COLUMN weekly_digest_position INTEGER DEFAULT 0")
            if 'created_at' not in columns:
                cursor.execute("ALTER TABLE users ADD COLUMN created_at TIMESTAMP DEFAULT NULL")
            # Dota 2 поля
            if 'steam_id' not in columns:
                cursor.execute("ALTER TABLE users ADD COLUMN steam_id INTEGER")
            if 'steam_nickname' not in columns:
                cursor.execute("ALTER TABLE users ADD COLUMN steam_nickname TEXT")
            if 'mmr' not in columns:
                cursor.execute("ALTER TABLE users ADD COLUMN mmr INTEGER DEFAULT 0")
            if 'dota_total_games' not in columns:
                cursor.execute("ALTER TABLE users ADD COLUMN dota_total_games INTEGER DEFAULT 0")
            if 'dota_wins' not in columns:
                cursor.execute("ALTER TABLE users ADD COLUMN dota_wins INTEGER DEFAULT 0")
            if 'week_games' not in columns:
                cursor.execute("ALTER TABLE users ADD COLUMN week_games INTEGER DEFAULT 0")
            if 'week_wins' not in columns:
                cursor.execute("ALTER TABLE users ADD COLUMN week_wins INTEGER DEFAULT 0")
            if 'last_dota_games' not in columns:
                cursor.execute("ALTER TABLE users ADD COLUMN last_dota_games INTEGER DEFAULT 0")
            if 'last_dota_wins' not in columns:
                cursor.execute("ALTER TABLE users ADD COLUMN last_dota_wins INTEGER DEFAULT 0")
            if 'mmr_updated_at' not in columns:
                cursor.execute("ALTER TABLE users ADD COLUMN mmr_updated_at TIMESTAMP")
            if 'mmr_last_updated' not in columns:
                cursor.execute("ALTER TABLE users ADD COLUMN mmr_last_updated TIMESTAMP")
            if 'rank_tier' not in columns:
                cursor.execute("ALTER TABLE users ADD COLUMN rank_tier INTEGER DEFAULT 0")
            if 'wins' not in columns:
                cursor.execute("ALTER TABLE users ADD COLUMN wins INTEGER DEFAULT 0")
            if 'losses' not in columns:
                cursor.execute("ALTER TABLE users ADD COLUMN losses INTEGER DEFAULT 0")
            if 'last_match_id' not in columns:
                cursor.execute("ALTER TABLE users ADD COLUMN last_match_id INTEGER DEFAULT 0")
            if 'week_start_date' not in columns:
                cursor.execute("ALTER TABLE users ADD COLUMN week_start_date DATE")
            if 'week_best_streak' not in columns:
                cursor.execute("ALTER TABLE users ADD COLUMN week_best_streak INTEGER DEFAULT 0")
            if 'week_current_streak' not in columns:
                cursor.execute("ALTER TABLE users ADD COLUMN week_current_streak INTEGER DEFAULT 0")
            if 'in_chat' not in columns:
                cursor.execute("ALTER TABLE users ADD COLUMN in_chat INTEGER DEFAULT 1")
            if 'last_greeting_date' not in columns:
                cursor.execute("ALTER TABLE users ADD COLUMN last_greeting_date DATE")
            if 'message_count' not in columns:
                cursor.execute("ALTER TABLE users ADD COLUMN message_count INTEGER DEFAULT 0")
            if 'first_name' not in columns:
                cursor.execute("ALTER TABLE users ADD COLUMN first_name TEXT")
            if 'weekly_mvp' not in columns:
                cursor.execute("ALTER TABLE users ADD COLUMN weekly_mvp INTEGER DEFAULT 0")
            if 'weekly_top2' not in columns:
                cursor.execute("ALTER TABLE users ADD COLUMN weekly_top2 INTEGER DEFAULT 0")
            if 'weekly_top3' not in columns:
                cursor.execute("ALTER TABLE users ADD COLUMN weekly_top3 INTEGER DEFAULT 0")
            if 'user_tags' not in columns:
                cursor.execute("ALTER TABLE users ADD COLUMN user_tags TEXT DEFAULT '[]'")

            # Создаём индексы для часто используемых полей (улучшение производительности)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_fissure ON users(fissure DESC)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_mmr ON users(mmr DESC)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_steam_id ON users(steam_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_week_games ON users(week_games DESC)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_current_position ON users(current_position)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_rank_tier ON users(rank_tier DESC)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_in_chat ON users(in_chat)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_daily_best_growth ON users(daily_best_growth DESC)")
            # Critical composite indexes for top queries
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_mmr_steam ON users(mmr DESC) WHERE steam_id IS NOT NULL")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_fissure_inchat ON users(fissure DESC) WHERE in_chat")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_week_active ON users(steam_id, week_games DESC) WHERE steam_id IS NOT NULL AND week_games > 0")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_last_activity ON users(last_activity) WHERE in_chat")
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS chat_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER NOT NULL,
                    user_id INTEGER,
                    message_text TEXT,
                    is_bot BOOLEAN DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_chat_messages_chat_id ON chat_messages(chat_id, created_at DESC)")

        _save_schema_version(cursor, is_pg)
        conn.commit()
        logger.info("Database initialized (full schema apply)")
    except Exception as e:
        logger.error(f"DB init error: {e}")
    finally:
        release_connection(conn)

def migrate_db():
    """Run database migrations using Alembic"""
    try:
        import subprocess
        import sys

        # Check if alembic.ini exists
        alembic_ini_path = os.path.join(os.path.dirname(__file__), 'alembic.ini')
        if not os.path.exists(alembic_ini_path):
            logger.info("Alembic not configured, skipping migrations")
            return True

        # Run alembic upgrade head
        result = subprocess.run([
            sys.executable, '-m', 'alembic', 'upgrade', 'head'
        ], capture_output=True, text=True, cwd=os.path.dirname(__file__))

        if result.returncode == 0:
            logger.info("Database migrations completed successfully")
            return True
        else:
            logger.error(f"Migration error: {result.stderr}")
            return False
    except Exception as e:
        logger.error(f"Migration start error: {e}")
        return False

_config_cache = {}
_config_cache_time = {}
_CONFIG_CACHE_TTL = 600  # 10 минут - конфиги меняются редко

class Database:
    USER_PRIMARY_KEY = "telegram_id"
    USERNAME_IS_DISPLAY_ONLY = True
    def execute_query(self, query, params=None, fetch="none"):
        """Выполнить SQL запрос с параметрами"""
        url = urlparse.urlparse(DATABASE_URL)
        scheme = url.scheme

        if "postgres" in scheme:
            conn = get_connection()
            try:
                cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                if params:
                    cursor.execute(query, params)
                else:
                    cursor.execute(query)

                if fetch == "one":
                    result = cursor.fetchone()
                elif fetch == "all":
                    result = cursor.fetchall()
                else:
                    result = cursor.rowcount
                conn.commit()
                return result
            except Exception as e:
                if _telegram_error_contains(e, "closed", "ssl", "connection", "server closed", "terminating", "eof", "broken"):
                    _reset_persistent_pg_conn(f"execute_query postgres error: {e}")
                    # Try to reconnect and retry once
                    try:
                        conn = get_connection()
                        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                        if params:
                            cursor.execute(query, params)
                        else:
                            cursor.execute(query)

                        if fetch == "one":
                            result = cursor.fetchone()
                        elif fetch == "all":
                            result = cursor.fetchall()
                        else:
                            result = cursor.rowcount
                        conn.commit()
                        return result
                    except Exception as e2:
                        logger.error(f"execute_query retry error: {e2}")
                        try:
                            conn.rollback()
                        except Exception as rb_err:
                            logger.debug(f"rollback failed: {rb_err}")
                        raise
                else:
                    logger.error(f"execute_query error: {e} (type={type(e).__name__}, args={getattr(e, 'args', 'N/A')})")
                    try:
                        conn.rollback()
                    except Exception as rb_err:
                        logger.debug(f"rollback failed: {rb_err}")
                    raise
            finally:
                release_connection(conn)
        else:
            conn = get_connection()
            try:
                cursor = conn.cursor()
                if params:
                    cursor.execute(query, params)
                else:
                    cursor.execute(query)

                if fetch == "one":
                    result = cursor.fetchone()
                elif fetch == "all":
                    result = cursor.fetchall()
                else:
                    result = cursor.rowcount
                conn.commit()
                return result
            except Exception as e:
                if _telegram_error_contains(e, "closed", "ssl", "connection", "server closed", "terminating", "eof", "broken"):
                    _reset_persistent_pg_conn(f"execute_query sqlite error: {e}")
                    # Try to reconnect and retry once
                    try:
                        conn = get_connection()
                        cursor = conn.cursor()
                        if params:
                            cursor.execute(query, params)
                        else:
                            cursor.execute(query)

                        if fetch == "one":
                            result = cursor.fetchone()
                        elif fetch == "all":
                            result = cursor.fetchall()
                        else:
                            result = cursor.rowcount
                        conn.commit()
                        return result
                    except Exception as e2:
                        logger.error(f"execute_query retry error: {e2}")
                        try:
                            conn.rollback()
                        except Exception as rb_err:
                            logger.debug(f"rollback failed: {rb_err}")
                        raise
                else:
                    logger.error(f"execute_query error: {e} (type={type(e).__name__}, args={getattr(e, 'args', 'N/A')})")
                    try:
                        conn.rollback()
                    except Exception as rb_err:
                        logger.debug(f"rollback failed: {rb_err}")
                    raise
            finally:
                release_connection(conn)

    def add_user(self, telegram_id, username=None, first_name=None):
        """Legacy: добавление пользователя. Используйте register_user() для новых мест."""
        url = urlparse.urlparse(DATABASE_URL)
        scheme = url.scheme
        db_type = get_db_type()

        try:
            if "postgres" in scheme:
                existing = self.execute_query("SELECT telegram_id FROM users WHERE telegram_id = %s", (telegram_id,), fetch="one")
                if existing:
                    self.execute_query(
                        "UPDATE users SET username = %s, first_name = %s, in_chat = TRUE, last_activity = CURRENT_TIMESTAMP WHERE telegram_id = %s",
                        (username, first_name, telegram_id)
                    )
                else:
                    self.execute_query(
                        "INSERT INTO users (telegram_id, username, first_name, fissure, created_at, in_chat) VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP, TRUE)",
                        (telegram_id, username, first_name, 0.1)
                    )
                return telegram_id
            else:
                self.execute_query(
                    "INSERT INTO users (telegram_id, username, first_name, fissure, created_at, in_chat) VALUES (?, ?, ?, ?, datetime('now'), 1) ON CONFLICT(telegram_id) DO UPDATE SET username = COALESCE(username, excluded.username), first_name = COALESCE(first_name, excluded.first_name), in_chat = 1",
                    (telegram_id, username, first_name, 0.1)
                )
                return telegram_id
        except Exception as e:
            error_msg = str(e) if str(e) else "unknown error"
            error_type = type(e).__name__
            error_args = getattr(e, 'args', None)

            if _telegram_error_contains(e, "duplicate key") and "users_pkey" in error_msg.lower():
                try:
                    existing = self.execute_query("SELECT id FROM users WHERE telegram_id = %s", (telegram_id,), fetch="one")
                    if existing:
                        logger.warning(f"add_user: recovered from pkey sequence desync for telegram_id={telegram_id}")
                        return existing["id"]
                except Exception:
                    pass

            logger.error(f"Error adding user: {error_msg} (type={error_type}, db_type={db_type}, telegram_id={telegram_id}, username={username})")
            return None

    @staticmethod
    def _normalize_telegram_id(tid):
        if tid is None:
            return None
        if isinstance(tid, str):
            try:
                tid = int(tid)
            except Exception:
                return None
        if isinstance(tid, int) and tid > 0:
            return tid
        return None

    def register_user(self, telegram_id, username=None, first_name=None, source="unknown"):
        tid = self._normalize_telegram_id(telegram_id)
        if not tid:
            logger.warning(f"register_user: invalid telegram_id={telegram_id} from {source}")
            return None

        safe_username = (username or first_name or "").strip() if (username or first_name) else None
        safe_first_name = (first_name or "").strip() if first_name else None

        url = urlparse.urlparse(DATABASE_URL)
        scheme = url.scheme

        try:
            if "postgres" in scheme:
                existing = self.execute_query("SELECT telegram_id, username, first_name FROM users WHERE telegram_id = %s", (tid,), fetch="one")
                old_username = existing.get("username") if existing else None
                if existing:
                    updates = []
                    params = []
                    if safe_username and existing.get("username") != safe_username:
                        updates.append("username = %s")
                        params.append(safe_username)
                    if safe_first_name and existing.get("first_name") != safe_first_name:
                        updates.append("first_name = %s")
                        params.append(safe_first_name)
                    if updates:
                        params.append(tid)
                        self.execute_query(f"UPDATE users SET {', '.join(updates)}, last_activity = CURRENT_TIMESTAMP WHERE telegram_id = %s", tuple(params))
                        if safe_username != old_username:
                            user_cache.update_username_lookup(old_username, safe_username, tid)
                else:
                    self.execute_query(
                        "INSERT INTO users (telegram_id, username, first_name, fissure, created_at, in_chat, last_activity) VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP, TRUE, CURRENT_TIMESTAMP)",
                        (tid, safe_username, safe_first_name, 0.1)
                    )
                return tid
            else:
                old_username = None
                try:
                    conn = get_connection()
                    cursor = conn.cursor()
                    cursor.execute("SELECT username FROM users WHERE telegram_id = ?", (tid,))
                    row = cursor.fetchone()
                    if row:
                        old_username = row[0] if not isinstance(row, dict) else row.get('username')
                    cursor.close()
                except Exception:
                    pass
                finally:
                    if conn:
                        release_connection(conn)
                self.execute_query(
                    "INSERT INTO users (telegram_id, username, first_name, fissure, created_at, in_chat, last_activity) VALUES (?, ?, ?, ?, datetime('now'), 1, datetime('now')) ON CONFLICT(telegram_id) DO UPDATE SET username = COALESCE(?, excluded.username), first_name = COALESCE(?, excluded.first_name), last_activity = datetime('now')",
                    (tid, safe_username, safe_first_name, 0.1, safe_username, safe_first_name)
                )
                if safe_username != old_username:
                    user_cache.update_username_lookup(old_username, safe_username, tid)
                return tid
        except Exception as e:
            logger.error(f"register_user error: {e} (telegram_id={tid}, source={source})", exc_info=True)
            return None

    def audit_invalid_telegram_ids(self):
        """Аудит пользователей с невалидным telegram_id.
        
        Только читает и логирует проблемные записи. Ничего не удаляет и не изменяет.
        
        Правила:
        - telegram_id NULL/0/невалидный
        - steam_id отсутствует
        - fissure == 0.1 (дефолт)
        - message_count == 0
        
        Returns: (count_invalid, count_active_skipped)
        """
        url = urlparse.urlparse(DATABASE_URL)
        scheme = url.scheme
        db_type = get_db_type()
        invalid_count = 0
        active_skipped = 0

        try:
            if "postgres" in scheme:
                candidates = self.execute_query("""
                    SELECT id, telegram_id, username, first_name, steam_id, fissure, message_count, last_activity
                    FROM users
                    WHERE telegram_id IS NULL
                       OR telegram_id = 0
                       OR CAST(telegram_id AS TEXT) NOT SIMILAR TO '[1-9][0-9]*'
                """, fetch="all")
                for row in candidates:
                    uid, bad_tid, username, first_name, steam_id, fissure, message_count, last_activity = row["id"], row["telegram_id"], row.get("username"), row.get("first_name"), row.get("steam_id"), float(row["fissure"] or 0), int(row["message_count"] or 0), row.get("last_activity")
                    if steam_id or fissure > 0.1 or message_count > 0:
                        logger.warning(f"audit_invalid_telegram_ids: skip active row id={uid}, bad telegram_id={bad_tid}, username={username}, steam={bool(steam_id)}, fissure={fissure}, messages={message_count}, last_activity={last_activity}")
                        active_skipped += 1
                        continue
                    logger.warning(f"audit_invalid_telegram_ids: invalid row id={uid}, bad telegram_id={bad_tid}, username={username}, steam={bool(steam_id)}, fissure={fissure}, messages={message_count}, last_activity={last_activity}")
                    invalid_count += 1
                logger.warning(f"audit_invalid_telegram_ids: done. invalid={invalid_count}, active_skipped={active_skipped}")
                return invalid_count, active_skipped

            conn = get_connection()
            cursor = conn.cursor()
            try:
                cursor.execute("SELECT id, telegram_id, username, steam_id, fissure, message_count, last_activity FROM users WHERE telegram_id IS NULL OR telegram_id = 0 OR CAST(telegram_id AS TEXT) NOT LIKE '1%' AND CAST(telegram_id AS TEXT) NOT LIKE '2%' AND CAST(telegram_id AS TEXT) NOT LIKE '3%' AND CAST(telegram_id AS TEXT) NOT LIKE '4%' AND CAST(telegram_id AS TEXT) NOT LIKE '5%' AND CAST(telegram_id AS TEXT) NOT LIKE '6%' AND CAST(telegram_id AS TEXT) NOT LIKE '7%' AND CAST(telegram_id AS TEXT) NOT LIKE '8%' AND CAST(telegram_id AS TEXT) NOT LIKE '9%'")
                rows = cursor.fetchall()
                for row in rows:
                    rid, bad_tid, username, steam_id, fissure, message_count, last_activity = row
                    steam_id = steam_id if len(row) > 3 else None
                    fissure = float(fissure or 0) if len(row) > 4 else 0.0
                    message_count = int(message_count or 0) if len(row) > 5 else 0
                    last_activity = row[6] if len(row) > 6 else None
                    if steam_id or fissure > 0.1 or message_count > 0:
                        logger.warning(f"audit_invalid_telegram_ids: skip active sqlite row id={rid}, bad telegram_id={bad_tid}, username={username}, steam={bool(steam_id)}, fissure={fissure}, messages={message_count}, last_activity={last_activity}")
                        active_skipped += 1
                        continue
                    logger.warning(f"audit_invalid_telegram_ids: invalid sqlite row id={rid}, bad telegram_id={bad_tid}, username={username}, steam={bool(steam_id)}, fissure={fissure}, messages={message_count}, last_activity={last_activity}")
                    invalid_count += 1
                logger.warning(f"audit_invalid_telegram_ids: done. invalid={invalid_count}, active_skipped={active_skipped}")
                return invalid_count, active_skipped
            finally:
                cursor.close()
                release_connection(conn)
        except Exception as e:
            logger.error(f"audit_invalid_telegram_ids error: {e}")
            return 0, 0

    def repair_missing_telegram_ids(self, dry_run: bool = False):
        """Legacy: перенаправляет в audit_invalid_telegram_ids().
        
        Удаление пользователей отключено насовсем. Используйте audit_invalid_telegram_ids()
        для безопасного аудита без изменений данных.
        """
        logger.warning("repair_missing_telegram_ids() is deprecated; use audit_invalid_telegram_ids() instead. No users will be deleted.")
        return self.audit_invalid_telegram_ids()[0]

    def get_user(self, telegram_id, username=None):
        """Получение пользователя"""
        try:
            url = urlparse.urlparse(DATABASE_URL)
            scheme = url.scheme

            if "postgres" in scheme:
                query = "SELECT * FROM users WHERE telegram_id = %s"
                user = self.execute_query(query, (telegram_id,), fetch="one")
                if user:
                    result = {
                        "telegram_id": user["telegram_id"],
                        "username": user["username"],
                        "fissure": float(user["fissure"]) if user["fissure"] is not None else 0.1,
                        "last_fissure": user["last_fissure"],
                        "last_message_id": user["last_message_id"],
                        "total_growth": float(user["total_growth"]) if user["total_growth"] is not None else 0.0,
                        "total_rolls": int(user["total_rolls"]) if user["total_rolls"] is not None else 0,
                        "best_streak": int(user["best_streak"]) if user["best_streak"] is not None else 0,
                        "current_streak": int(user["current_streak"]) if user["current_streak"] is not None else 0,
                        "current_win_streak": int(user["current_win_streak"]) if user["current_win_streak"] is not None else 0,
                        "current_lose_streak": int(user["current_lose_streak"]) if user["current_lose_streak"] is not None else 0,
                        "best_lose_streak": int(user["best_lose_streak"]) if user["best_lose_streak"] is not None else 0,
                        "steam_id": user["steam_id"],
                        "steam_nickname": user["steam_nickname"],
                        "mmr": int(user["mmr"]) if user["mmr"] is not None else 0,
                        "rank_tier": int(user["rank_tier"]) if user["rank_tier"] is not None else 0,
                        "dota_total_games": int(user["dota_total_games"]) if user["dota_total_games"] is not None else 0,
                        "dota_wins": int(user["dota_wins"]) if user["dota_wins"] is not None else 0,
                        "week_games": int(user["week_games"]) if user["week_games"] is not None else 0,
                        "week_wins": int(user["week_wins"]) if user["week_wins"] is not None else 0,
                        "week_best_streak": int(user["week_best_streak"]) if user["week_best_streak"] is not None else 0,
                        "week_current_streak": int(user["week_current_streak"]) if user["week_current_streak"] is not None else 0,
                        "week_updated_at": user["week_updated_at"],
                        "mmr_updated_at": user["mmr_updated_at"],
                        "analytics_cache": user["analytics_cache"],
                        "analytics_updated_at": user["analytics_updated_at"],
                        "last_dota_games": int(user["last_dota_games"]) if user["last_dota_games"] is not None else 0,
                        "last_dota_wins": int(user["last_dota_wins"]) if user["last_dota_wins"] is not None else 0,
                        "week_start_date": user["week_start_date"],
                        "message_count": int(user["message_count"]) if user["message_count"] is not None else 0,
                        "weekly_mvp": int(user["weekly_mvp"]) if user.get("weekly_mvp") is not None else 0,
                        "weekly_top2": int(user["weekly_top2"]) if user.get("weekly_top2") is not None else 0,
                        "weekly_top3": int(user["weekly_top3"]) if user.get("weekly_top3") is not None else 0,
                        "user_tags": user.get("user_tags") or "[]",
                    }
                    if username is not None and username != result.get('username'):
                        old_username = result.get('username')
                        self.execute_query("UPDATE users SET username = %s WHERE telegram_id = %s", (username, telegram_id))
                        result['username'] = username
                        user_cache.set(telegram_id, result)
                        user_cache.update_username_lookup(old_username, username, telegram_id)
                        logger.info(f"get_user: updated username for {telegram_id} to '{username}'")
                    return result
                else:
                    logger.warning(f"DB.get_user: user {telegram_id} not found")
                    return None
            else:
                # SQLite - use column names to avoid index mismatches
                conn = get_connection()
                try:
                    cursor = conn.cursor()
                    cursor.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))
                    user_row = cursor.fetchone()
                    if user_row:
                        columns = [desc[0] for desc in cursor.description]
                        u = dict(zip(columns, user_row))
                        result = {
                            "telegram_id": u.get("telegram_id"),
                            "username": u.get("username"),
                            "fissure": float(u["fissure"]) if u["fissure"] is not None else 0.1,
                            "last_fissure": u.get("last_fissure"),
                            "last_message_id": u.get("last_message_id"),
                            "total_growth": float(u["total_growth"]) if u["total_growth"] is not None else 0.0,
                            "total_rolls": int(u["total_rolls"]) if u["total_rolls"] is not None else 0,
                            "best_streak": int(u["best_streak"]) if u["best_streak"] is not None else 0,
                            "current_streak": int(u["current_streak"]) if u["current_streak"] is not None else 0,
                            "steam_id": u.get("steam_id"),
                            "steam_nickname": u.get("steam_nickname"),
                            "mmr": int(u["mmr"]) if u["mmr"] is not None else 0,
                            "rank_tier": int(u["rank_tier"]) if u["rank_tier"] is not None else 0,
                            "dota_total_games": int(u["dota_total_games"]) if u["dota_total_games"] is not None else 0,
                            "dota_wins": int(u["dota_wins"]) if u["dota_wins"] is not None else 0,
                            "week_games": int(u["week_games"]) if u["week_games"] is not None else 0,
                            "week_wins": int(u["week_wins"]) if u["week_wins"] is not None else 0,
                            "week_best_streak": int(u["week_best_streak"]) if u["week_best_streak"] is not None else 0,
                            "week_current_streak": int(u["week_current_streak"]) if u["week_current_streak"] is not None else 0,
                            "week_updated_at": u.get("week_updated_at"),
                            "mmr_updated_at": u.get("mmr_updated_at"),
                            "analytics_cache": u.get("analytics_cache"),
                            "analytics_updated_at": u.get("analytics_updated_at"),
                            "last_dota_games": int(u["last_dota_games"]) if u["last_dota_games"] is not None else 0,
                            "last_dota_wins": int(u["last_dota_wins"]) if u["last_dota_wins"] is not None else 0,
                            "week_start_date": u.get("week_start_date"),
                            "message_count": int(u["message_count"]) if u["message_count"] is not None else 0,
                            "current_win_streak": int(u["current_win_streak"]) if u["current_win_streak"] is not None else 0,
                            "current_lose_streak": int(u["current_lose_streak"]) if u["current_lose_streak"] is not None else 0,
                            "best_lose_streak": int(u["best_lose_streak"]) if u["best_lose_streak"] is not None else 0,
                            "weekly_mvp": int(u["weekly_mvp"]) if u.get("weekly_mvp") is not None else 0,
                            "weekly_top2": int(u["weekly_top2"]) if u.get("weekly_top2") is not None else 0,
                            "weekly_top3": int(u["weekly_top3"]) if u.get("weekly_top3") is not None else 0,
                            "user_tags": u.get("user_tags") or "[]",
                        }
                        if username is not None and username != result.get('username'):
                            old_username = result.get('username')
                            cursor.execute("UPDATE users SET username = ? WHERE telegram_id = ?", (username, telegram_id))
                            conn.commit()
                            result['username'] = username
                            user_cache.set(telegram_id, result)
                            user_cache.update_username_lookup(old_username, username, telegram_id)
                            logger.info(f"get_user: updated username for {telegram_id} to '{username}'")
                        cursor.close()
                        return result
                    else:
                        cursor.close()
                        logger.warning(f"DB.get_user: user {telegram_id} not found")
                        return None
                finally:
                    release_connection(conn)
        except Exception as e:
            logger.error(f"Error getting user: {e}")
            return None

    def update_last_message_id(self, telegram_id, message_id):
        """Обновление ID последнего сообщения пользователя"""
        try:
            # Используем execute_query для безопасного выполнения
            url = urlparse.urlparse(DATABASE_URL)
            scheme = url.scheme

            if "postgres" in scheme:
                query = "UPDATE users SET last_message_id=%s WHERE telegram_id=%s"
                self.execute_query(query, (message_id, telegram_id))
            else:
                query = "UPDATE users SET last_message_id=? WHERE telegram_id=?"
                self.execute_query(query, (message_id, telegram_id))
        except Exception as e:
            logger.error(f"Error updating last message ID: {e}")

    def get_fissure_top(self, limit=10):
        """Получение топ пользователей"""
        try:
            url = urlparse.urlparse(DATABASE_URL)
            scheme = url.scheme

            if "postgres" in scheme:
                query = "SELECT telegram_id, username, steam_nickname, first_name, steam_id, fissure, avatar, rank_tier FROM users WHERE (in_chat = TRUE OR in_chat IS NULL) ORDER BY fissure DESC NULLS LAST LIMIT %s"
                users = self.execute_query(query, (limit,), fetch="all")
                return [{"telegram_id": u["telegram_id"], "username": u["username"], "steam_nickname": u["steam_nickname"], "first_name": u["first_name"], "steam_id": u.get("steam_id"), "fissure": u["fissure"], "avatar": u.get("avatar"), "rank_tier": u.get("rank_tier", 0)} for u in users]
            else:
                query = "SELECT telegram_id, username, steam_nickname, first_name, steam_id, fissure, avatar, rank_tier FROM users ORDER BY fissure DESC LIMIT ?"
                users = self.execute_query(query, (limit,), fetch="all")
                return [{"telegram_id": u[0], "username": u[1], "steam_nickname": u[2], "first_name": u[3], "steam_id": u[4], "fissure": u[5], "avatar": u[6], "rank_tier": u[7] if len(u) > 7 else 0} for u in users]
        except Exception as e:
            logger.error(f"Error getting fissure top: {e}")
            return []

    def get_user_rank(self, telegram_id):
        """Получить позицию игрока в топе по MMR"""
        logger.info(f"DEBUG: get_user_rank called for {telegram_id}")
        try:
            # Используем execute_query для безопасного выполнения
            if get_db_type() == "postgresql":
                query = """
                    SELECT COUNT(*) + 1 as rank FROM users WHERE mmr > (
                        SELECT mmr FROM users WHERE telegram_id = %s LIMIT 1
                    ) AND steam_id IS NOT NULL
                """
                result = self.execute_query(query, (telegram_id,), fetch="one")
                # Если пользователь первый (нет тех, у кого больше MMR), возвращаем 1
                if result and result.get('rank') is not None:
                    rank = int(result['rank'])
                    # Если rank = 0, значит пользователь первый (у него максимальный MMR)
                    return rank if rank > 0 else 1
                return None
            else:
                query = """
                    SELECT COUNT(*) + 1 as rank FROM users WHERE mmr > (
                        SELECT mmr FROM users WHERE telegram_id = ? LIMIT 1
                    ) AND steam_id IS NOT NULL
                """
                result = self.execute_query(query, (telegram_id,), fetch="one")
                # Если пользователь первый (нет тех, у кого больше MMR), возвращаем 1
                if result and (result.get('rank') if isinstance(result, dict) else result[0]) is not None:
                    rank = int(result.get('rank') if isinstance(result, dict) else result[0])
                    # Если rank = 0, значит пользователь первый (у него максимальный MMR)
                    return rank if rank > 0 else 1
                return None
        except Exception as e:
            logger.error(f"Error getting user rank: {e}", exc_info=True)
            return None

    def get_fissure_rank(self, telegram_id):
        """Получение позиции игрока в топе по fissure"""
        logger.info(f"DEBUG: get_fissure_rank called for {telegram_id}")
        try:
            if get_db_type() == "postgresql":
                query = """
                    SELECT COUNT(*) + 1 as rank FROM users 
                    WHERE (in_chat = TRUE OR in_chat IS NULL)
                    AND COALESCE(fissure, 0) > COALESCE(
                        (SELECT fissure FROM users WHERE telegram_id = %s LIMIT 1), -1)
                """
                result = self.execute_query(query, (telegram_id,), fetch="one")
                logger.info(f"get_fissure_rank result: {result}, type={type(result)}")
                if result and isinstance(result, dict) and result.get('rank') is not None:
                    rank = int(result['rank'])
                    return rank if rank > 0 else 1
                return None
            else:
                query = """
                    SELECT COUNT(*) + 1 as rank FROM users 
                    WHERE (in_chat = 1 OR in_chat IS NULL)
                    AND COALESCE(fissure, 0) > COALESCE(
                        (SELECT fissure FROM users WHERE telegram_id = ? LIMIT 1), -1)
                """
                result = self.execute_query(query, (telegram_id,), fetch="one")
                logger.info(f"get_fissure_rank result: {result}, type={type(result)}")
                if result and (result.get("rank") if isinstance(result, dict) else result[0]) is not None:
                    rank = int(result.get("rank") if isinstance(result, dict) else result[0])
                    return rank if rank > 0 else 1
                return None
        except Exception as e:
            logger.error(f"Error getting fissure rank: {e}", exc_info=True)
            return None

    def decrease_inactive_fissure(self, days_inactive=1, decrease_amount=1.0):
        """Уменьшить fissure для неактивных игроков"""
        try:
            if get_db_type() == "postgresql":
                query = """
                    UPDATE users 
                    SET fissure = GREATEST(0.1, fissure - %s)
                    WHERE last_activity < CURRENT_TIMESTAMP - INTERVAL '%s days'
                    AND fissure > 0.1
                """
                result = self.execute_query(query, (decrease_amount, days_inactive))
                return result if result is not None and result >= 0 else 0
            else:
                # Для SQLite используем datetime function
                query = """
                    UPDATE users 
                    SET fissure = MAX(0.1, fissure - ?)
                    WHERE last_activity < datetime('now', ?)
                    AND fissure > 0.1
                """
                # Форматируем строку для days_inactive
                days_str = f"-{days_inactive} days"
                result = self.execute_query(query, (decrease_amount, days_str))
                return result if result is not None and result >= 0 else 0
        except Exception as e:
            logger.error(f"Error decreasing inactive fissure: {e}")
            return 0

    def get_config(self, key, default=None, use_cache=True):
        """Получить значение конфигурации с кешированием"""
        if use_cache and key in _config_cache and (time.time() - _config_cache_time.get(key, 0)) < _CONFIG_CACHE_TTL:
            return _config_cache[key]

        result = default
        try:
            url = urlparse.urlparse(DATABASE_URL)
            scheme = url.scheme

            if "postgres" in scheme:
                query = "SELECT value FROM bot_config WHERE key = %s"
                row = self.execute_query(query, (key,), fetch="one")
                if row is None:
                    result = default
                elif isinstance(row, dict):
                    val = row.get('value')
                    if key == 'alternate_digest_type' and val in ('0', '1'):
                        result = val
                    elif val is not None and val != '' and val != '0':
                        result = val
                    else:
                        result = default
                elif isinstance(row, tuple):
                    val = row[0]
                    result = val if val and str(val) != '0' else default
                elif row and row != '0':
                    result = row
            else:
                query = "SELECT value FROM bot_config WHERE key = ?"
                row = self.execute_query(query, (key,), fetch="one")
                if row is None:
                    result = default
                elif isinstance(row, tuple):
                    result = row[0] if row[0] else default
                else:
                    result = row if row else default
        except Exception as e:
            logger.error(f"Error getting config: {e}")
            return default

        if use_cache and result != default:
            _config_cache[key] = result
            _config_cache_time[key] = time.time()
        return result

    def set_config(self, key, value):
        """Установить значение конфигурации"""
        try:
            if value is None:
                url = urlparse.urlparse(DATABASE_URL)
                scheme = url.scheme
                if "postgres" in scheme:
                    self.execute_query("DELETE FROM bot_config WHERE key = %s", (key,))
                else:
                    self.execute_query("DELETE FROM bot_config WHERE key = ?", (key,))
                logger.debug(f"set_config deleted key={key}")
                return True

            if get_db_type() == "postgresql":
                query = """
                    INSERT INTO bot_config (key, value) VALUES (%s, %s)
                    ON CONFLICT(key) DO UPDATE SET value = EXCLUDED.value
                """
                self.execute_query(query, (key, str(value)))
            else:
                query = """
                    INSERT INTO bot_config (key, value) VALUES (?, ?)
                    ON CONFLICT(key) DO UPDATE SET value = EXCLUDED.value
                """
                self.execute_query(query, (key, str(value)))

            # Invalidate cache
            if key in _config_cache:
                del _config_cache[key]
                del _config_cache_time[key]

            return True
        except Exception as e:
            logger.error(f"Error setting config: {e}")
            return False

    def get_digest_stats(self):
        """Получить статистику для дайджеста"""
        try:
            # Используем execute_query для безопасного выполнения
            if get_db_type() == "postgresql":
                query = """
                    SELECT telegram_id, username, first_name, steam_nickname, steam_id, fissure, digest_position, digest_fissure, current_streak, current_win_streak, daily_best_growth
                    FROM users
                    WHERE in_chat = TRUE
                """
                rows = self.execute_query(query, fetch="all")
                users = []
                for r in rows:
                    users.append({
                        "telegram_id": r["telegram_id"],
                        "username": r["username"],
                        "first_name": r.get("first_name"),
                        "steam_nickname": r["steam_nickname"],
                        "steam_id": r.get("steam_id"),
                        "fissure": float(r["fissure"] or 0.0),
                        "digest_position": int(r["digest_position"] or 0),
                        "digest_fissure": float(r["digest_fissure"] or 0.0),
                        "current_streak": int(r["current_streak"] or 0),
                        "current_win_streak": int(r["current_win_streak"] or 0),
                        "daily_best_growth": float(r["daily_best_growth"] or 0.0),
                    })
            else:
                query = """
                    SELECT telegram_id, username, first_name, steam_nickname, steam_id, fissure, digest_position, digest_fissure, current_streak, current_win_streak, daily_best_growth
                    FROM users
                    WHERE in_chat = 1 OR in_chat IS NULL
                """
                rows = self.execute_query(query, fetch="all")
                users = []
                for r in rows:
                    users.append({
                        "telegram_id": r[0],
                        "username": r[1],
                        "first_name": r[2] if len(r) > 2 else None,
                        "steam_nickname": r[3] if len(r) > 3 else None,
                        "steam_id": r[4] if len(r) > 4 else None,
                        "fissure": float(r[5] or 0.0),
                        "digest_position": int(r[6] or 0),
                        "digest_fissure": float(r[7] or 0.0),
                        "current_streak": int(r[8] or 0),
                        "current_win_streak": int(r[9] or 0),
                        "daily_best_growth": float(r[10] if len(r) > 10 else 0.0),
                    })

            top_growth_user = None
            top_growth_cm = 0.0
            top_growth_id = None
            top_growth_username = None
            top_growth_first_name = None
            top_drop_user = None
            top_drop_cm = float('inf')
            top_drop_id = None
            top_drop_username = None
            top_drop_first_name = None
            top_streak_user = None
            top_streak = 0
            top_streak_id = None
            top_streak_username = None
            top_streak_first_name = None
            top_growth_steam_id = None
            top_drop_steam_id = None
            top_streak_steam_id = None

            for u in users:
                telegram_id = u.get("telegram_id")
                if not telegram_id:
                    continue

                # Use delta = fissure - digest_fissure for daily growth (fallback to daily_best_growth if 0)
                prev_f = u.get("digest_fissure", 0.0)
                cur_f = u.get("fissure", 0.0)
                delta = cur_f - prev_f
                daily_best = u.get("daily_best_growth", 0.0) or 0.0

                # Show growth if either delta or daily_best is positive
                growth_cm = max(delta, daily_best) if delta > 0 or daily_best > 0 else 0.0

                if growth_cm > 0 and growth_cm > top_growth_cm:
                    top_growth_cm = growth_cm
                    nick = u.get("username") or u.get("steam_nickname") or u.get("first_name")
                    if not nick or nick in ("None", "Unknown", "Неизвестный игрок") or len(nick.strip()) <= 1:
                        nick = u.get("username") or u.get("first_name")
                    top_growth_user = nick if nick else None
                    top_growth_first_name = u.get("first_name")
                    top_growth_id = telegram_id
                    top_growth_username = u.get("username")
                    top_growth_steam_id = u.get("steam_id")

                # also track drop (fissure decrease) - only if delta is negative (fissure decreased)
                if delta < top_drop_cm:
                    top_drop_cm = delta
                    nick = u.get("username") or u.get("steam_nickname") or u.get("first_name")
                    if not nick or nick in ("None", "Unknown", "Неизвестный игрок") or len(nick.strip()) <= 1:
                        nick = u.get("username") or u.get("first_name")
                    top_drop_user = nick if nick else None
                    top_drop_first_name = u.get("first_name")
                    top_drop_id = telegram_id
                    top_drop_username = u.get("username")
                    top_drop_steam_id = u.get("steam_id")

                if u["current_win_streak"] > top_streak:
                    top_streak = u["current_win_streak"]
                    top_streak_id = telegram_id
                    top_streak_steam_id = u.get("steam_id")
                    nick = u.get("username") or u.get("steam_nickname") or u.get("first_name")
                    if not nick or nick in ("None", "Unknown", "Неизвестный игрок") or len(nick.strip()) <= 1:
                        nick = u.get("username") or u.get("first_name")
                    top_streak_user = nick if nick else None
                    top_streak_first_name = u.get("first_name")
                    top_streak_username = u.get("username")

            if top_drop_cm == float('inf'):
                top_drop_cm = 0.0

            streak_username = None
            if top_streak_id:
                cached = user_cache.get(top_streak_id)
                if cached:
                    streak_username = cached.get('username')
                else:
                    conn = get_connection()
                    cursor = conn.cursor()
                    try:
                        url = urlparse.urlparse(DATABASE_URL)
                        if "postgres" in url.scheme:
                            cursor.execute("SELECT username FROM users WHERE telegram_id = %s", (top_streak_id,))
                        else:
                            cursor.execute("SELECT username FROM users WHERE telegram_id = ?", (top_streak_id,))
                        result = cursor.fetchone()
                        streak_username = result[0] if result else None
                    finally:
                        cursor.close()
                        release_connection(conn)

            return {
                "top_growth": (top_growth_user or "None", round(top_growth_cm)),
                "top_drop": (top_drop_user or "None", float(top_drop_cm)),
                "top_streak": (top_streak_user or "None", int(top_streak)),
                "top_growth_id": top_growth_id,
                "top_drop_id": top_drop_id,
                "top_streak_id": top_streak_id,
                "top_growth_username": top_growth_username,
                "top_drop_username": top_drop_username,
                "top_streak_username": top_streak_username,
                "top_growth_steam_id": top_growth_steam_id,
                "top_drop_steam_id": top_drop_steam_id,
                "top_streak_steam_id": top_streak_steam_id,
                "top_growth_first_name": top_growth_first_name,
                "top_drop_first_name": top_drop_first_name,
                "top_streak_first_name": top_streak_first_name,
                "streak_username": streak_username,
            }
        except Exception as e:
            logger.error(f"Error getting digest stats: {e}")
            return {
                "top_growth": ("None", 0),
                "top_drop": ("None", 0.0),
                "top_streak": ("None", 0),
                "top_growth_id": None,
                "top_drop_id": None,
                "top_streak_id": None,
                "top_growth_username": None,
                "top_drop_username": None,
                "top_streak_username": None,
                "top_growth_steam_id": None,
                "top_drop_steam_id": None,
                "top_streak_steam_id": None,
                "top_growth_first_name": None,
                "top_drop_first_name": None,
                "top_streak_first_name": None,
                "streak_username": None
            }

    def get_user_position(self, telegram_id):
        """Получить текущую позицию пользователя (динамически, без обновления всех)"""
        try:
            query = "SELECT COUNT(*) + 1 FROM users WHERE fissure > (SELECT fissure FROM users WHERE telegram_id = %s)"
            result = self.execute_query(query, (telegram_id,), fetch="one")
            if result is None:
                return 0
            if isinstance(result, dict):
                return int(result.get('count', 0)) + 1
            # Result is tuple/list from SQLite fetchone
            return int(result[0]) + 1 if result else 0
        except Exception as e:
            logger.error(f"Error getting user position: {e}")
            return 0

    def update_player_positions(self):
        """Обновить текущие позиции игроков (устаревший метод - используй get_user_position)"""
        logger.warning("update_player_positions is deprecated - use get_user_position instead")
        return 0

    def update_digest_snapshot(self):
        """Сохранить текущие fissure в digest_fissure для расчета роста (без ROW_NUMBER)"""
        try:
            if get_db_type() == "postgresql":
                query = "UPDATE users SET digest_fissure = fissure WHERE in_chat = TRUE"
            else:
                query = "UPDATE users SET digest_fissure = fissure WHERE in_chat = 1 OR in_chat IS NULL"
            result = self.execute_query(query)
            logger.info("Updated digest_fissure for growth tracking")
            return result
        except Exception as e:
            logger.error(f"Error updating digest snapshot: {e}")
            return 0

    def get_weekly_digest_stats(self):
        """Статистика для еженедельного дайджеста: рост в см, прорыв по позициям, броски, новички, общий рост."""
        try:
            # Используем execute_query для безопасного выполнения
            if get_db_type() == "postgresql":
                query = """
                    SELECT telegram_id, username, fissure, current_position, weekly_digest_position,
                           weekly_growth, weekly_rolls, created_at
                    FROM users
                    WHERE in_chat = TRUE
                """
                rows = self.execute_query(query, fetch="all")

                # Разный синтаксис для дат в PostgreSQL
                query_count = "SELECT COUNT(*) as count FROM users WHERE created_at >= CURRENT_TIMESTAMP - INTERVAL '7 days'"
                new_players_week = self.execute_query(query_count, fetch="one")
                new_players_week = new_players_week.get('count') if new_players_week else 0
            else:
                query = """
                    SELECT telegram_id, username, fissure, current_position, weekly_digest_position,
                           weekly_growth, weekly_rolls, created_at
                    FROM users
                    WHERE in_chat = 1 OR in_chat IS NULL
                """
                rows = self.execute_query(query, fetch="all")

                # Разный синтаксис для дат в SQLite
                query_count = "SELECT COUNT(*) as count FROM users WHERE created_at >= datetime('now', '-7 days')"
                new_players_week = self.execute_query(query_count, fetch="one")
                new_players_week = new_players_week.get('count') if new_players_week else 0

            users = []
            for r in rows:
                is_dict = isinstance(r, dict)
                users.append({
                    "telegram_id": r.get("telegram_id") if is_dict else r[0],
                    "username": r.get("username") if is_dict else r[1],
                    "fissure": float((r.get("fissure") or 0.0) if is_dict else (r[2] or 0.0)),
                    "current_position": int((r.get("current_position") or 0) if is_dict else (r[3] or 0)),
                    "weekly_digest_position": int((r.get("weekly_digest_position") or 0) if is_dict else (r[4] or 0)),
                    "weekly_growth": float((r.get("weekly_growth") or 0.0) if is_dict else (r[5] or 0.0)),
                    "weekly_rolls": int((r.get("weekly_rolls") or 0) if is_dict else (r[6] or 0)),
                })

            # Текущие позиции по fissure (могут отличаться от current_position если не обновлялись)
            users_sorted = sorted(users, key=lambda u: u["fissure"], reverse=True)
            cur_pos = {u["telegram_id"]: i + 1 for i, u in enumerate(users_sorted)}

            # Больше всех вырос в см за неделю
            top_cm_user = None
            top_cm = 0.0
            top_cm_id = None
            for u in users:
                if u["weekly_growth"] > top_cm:
                    top_cm = u["weekly_growth"]
                    cached = user_cache.get(u["telegram_id"])
                    top_cm_user = u["username"] or (cached.get("username") if cached else None) or str(u["telegram_id"])
                    top_cm_id = u["telegram_id"]

            # Прорыв недели: кто поднялся на больше всего позиций в топе
            breakthrough_user = None
            breakthrough_pos = 0
            breakthrough_id = None
            for u in users:
                prev = u["weekly_digest_position"]
                now_pos = cur_pos.get(u["telegram_id"], 0)
                if prev and now_pos:
                    gain = prev - now_pos
                    if gain > breakthrough_pos:
                        breakthrough_pos = gain
                        cached = user_cache.get(u["telegram_id"])
                        breakthrough_user = u["username"] or (cached.get("username") if cached else None) or str(u["telegram_id"])
                        breakthrough_id = u["telegram_id"]

            total_rolls_week = sum(u["weekly_rolls"] for u in users)
            total_growth_week = sum(u["weekly_growth"] for u in users)

            return {
                "top_growth_cm": (top_cm_user or "None", round(top_cm, 1)),
                "top_growth_cm_id": top_cm_id,
                "breakthrough": (breakthrough_user or "None", int(breakthrough_pos)),
                "breakthrough_id": breakthrough_id,
                "total_rolls_week": int(total_rolls_week),
                "new_players_week": int(new_players_week),
                "total_growth_week": round(total_growth_week, 1),
            }
        except Exception as e:
            logger.error(f"Error getting weekly digest stats: {e}")
            return {
                "top_growth_cm": ("None", 0),
                "breakthrough": ("None", 0),
                "total_rolls_week": 0,
                "new_players_week": 0,
                "total_growth_week": 0,
            }

    def update_weekly_digest_snapshot(self):
        """Обновить снимок для недельного дайджеста и обнулить недельные счётчики."""
        try:
            # Используем execute_query для безопасного выполнения
            url = urlparse.urlparse(DATABASE_URL)
            scheme = url.scheme

            if "postgres" in scheme:
                query = """
                    UPDATE users SET 
                        current_position = subquery.pos,
                        weekly_digest_position = subquery.pos,
                        weekly_rolls = 0,
                        weekly_growth = 0
                    FROM (
                        SELECT telegram_id, 
                               ROW_NUMBER() OVER (ORDER BY fissure DESC) as pos 
                        FROM users
                    ) subquery
                    WHERE users.telegram_id = subquery.telegram_id
                """
                result = self.execute_query(query)
                return result if result is not None else 0
            else:
                # SQLite: используем скалярные подзапросы
                query = """
                    UPDATE users SET 
                        current_position = (
                            SELECT COUNT(*) + 1 FROM users u2 WHERE u2.fissure > users.fissure
                        ),
                        weekly_digest_position = (
                            SELECT COUNT(*) + 1 FROM users u2 WHERE u2.fissure > users.fissure
                        ),
                        weekly_rolls = 0,
                        weekly_growth = 0
                """
                result = self.execute_query(query)
                return result if result is not None else 0
        except Exception as e:
            logger.error(f"Error updating weekly digest snapshot: {e}")
            return 0

# Функции для совместимости со старым кодом
def get_user(telegram_id, username=None):
    """Получить пользователя - сначала из кеша (с валидацией), потом из БД"""
    tid = Database._normalize_telegram_id(telegram_id)
    if not tid:
        logger.warning(f"get_user: invalid telegram_id={telegram_id}")
        return None

    cached_user = user_cache.get(tid)
    if cached_user and cached_user.get('fissure') is not None and isinstance(cached_user.get('fissure'), (int, float)):
        cached_user.setdefault('total_rolls', 0)
        cached_user.setdefault('best_streak', 0)
        cached_user.setdefault('current_streak', 0)
        cached_user.setdefault('current_win_streak', 0)
        cached_user.setdefault('current_lose_streak', 0)
        cached_user.setdefault('analytics_cache', None)
        cached_user.setdefault('analytics_updated_at', None)
        cached_user.setdefault('weekly_mvp', 0)
        cached_user.setdefault('weekly_top2', 0)
        cached_user.setdefault('weekly_top3', 0)
        cached_user.setdefault('user_tags', [])
        return cached_user

    # Нет в кэше или данные невалидны - читаем из БД
    db = Database()
    user = db.get_user(tid, username)

    if user:
        logger.info(f"get_user: DB hit for {tid}, fissure={user.get('fissure')}, total_rolls={user.get('total_rolls')}")
        user.setdefault('analytics_cache', None)
        user.setdefault('analytics_updated_at', None)
        user.setdefault('total_rolls', 0)
        user.setdefault('best_streak', 0)
        user.setdefault('current_streak', 0)
        user.setdefault('current_win_streak', 0)
        user.setdefault('current_lose_streak', 0)
        user.setdefault('weekly_mvp', 0)
        user.setdefault('weekly_top2', 0)
        user.setdefault('weekly_top3', 0)
        user.setdefault('user_tags', [])
        user_cache.set(tid, user, skip_dirty=True)
        return user

    # Пользователь не найден - создаём нового
    logger.info(f"get_user: user {tid} NOT found, creating new")
    db.register_user(tid, username or f"Player{tid}", None, source="get_user_fallback")
    user = db.get_user(tid)
    if user:
        user.setdefault('fissure', 0.1)
        user_cache.set(tid, user, skip_dirty=True)
        return user

    logger.warning(f"get_user: failed to create user {tid}")
    return None


def get_user_by_username(username):
    """Найти пользователя по username ИЛИ steam_nickname (без @, регистр не важен).
    Сначала ищем в кеше, потом в БД."""
    username = username.lstrip("@").lower()

    cached = user_cache.get('username_lookup')
    if cached and username in cached:
        tid = cached[username]
        logger.info(f"get_user_by_username: found '{username}' in username cache (tid={tid})")
        return get_user(tid)

    conn = None
    try:
        conn = get_connection()
        cursor = conn.cursor()
        url = urlparse.urlparse(DATABASE_URL)
        scheme = url.scheme
        if "postgres" in scheme:
            cursor.execute(
                "SELECT telegram_id, username, steam_nickname FROM users "
                "WHERE LOWER(username) = %s OR LOWER(steam_nickname) = %s LIMIT 1",
                (username, username),
            )
        else:
            cursor.execute(
                "SELECT telegram_id, username, steam_nickname FROM users "
                "WHERE LOWER(username) = ? OR LOWER(steam_nickname) = ? LIMIT 1",
                (username, username),
            )
        result = cursor.fetchone()
        cursor.close()
        conn.commit() if "postgres" in scheme else None
        if result:
            tid = result[0] if not isinstance(result, dict) else result.get('telegram_id')
            logger.info(f"get_user_by_username: found '{username}' in DB (tid={tid})")
            if user_cache.get('username_lookup') is None:
                user_cache.set('username_lookup', {})
            lookup = user_cache.get('username_lookup')
            lookup[username] = tid
            user_cache.set('username_lookup', lookup)
            return get_user(tid)
    except Exception as e:
        logger.error(f"get_user_by_username error: {e}")
    finally:
        if conn is not None:
            release_connection(conn)

    logger.info(f"get_user_by_username: '{username}' not found")
    return None


def get_user_by_steam_id(steam_id: int):
    """Найти пользователя по steam_id. Ищет сначала в кеше (reverse index), потом в БД."""
    if not steam_id:
        return None

    # Use reverse index first - O(1) lookup
    with user_cache._lock:
        telegram_id = user_cache._steam_index.get(steam_id)
    if telegram_id:
        logger.info(f"get_user_by_steam_id: found {steam_id} in cache index (tid={telegram_id})")
        return get_user(telegram_id)

    conn = None
    try:
        conn = get_connection()
        cursor = conn.cursor()
        url = urlparse.urlparse(DATABASE_URL)
        scheme = url.scheme
        if "postgres" in scheme:
            cursor.execute("SELECT telegram_id, username, steam_nickname FROM users WHERE steam_id = %s LIMIT 1", (steam_id,))
        else:
            cursor.execute("SELECT telegram_id, username, steam_nickname FROM users WHERE steam_id = ? LIMIT 1", (steam_id,))
        result = cursor.fetchone()
        cursor.close()
        if result:
            tid = result[0] if not isinstance(result, dict) else result.get('telegram_id')
            logger.info(f"get_user_by_steam_id: found {steam_id} in DB (tid={tid})")
            return get_user(tid)
    except Exception as e:
        logger.error(f"get_user_by_steam_id error: {e}")
    finally:
        if conn is not None:
            release_connection(conn)

    return None


def update_fissure(telegram_id, fissure, last_fissure, growth=0, last_message_id=None):
    """Обновление fissure + optionally last_message_id in one query"""
    logger.info(f"update_fissure called: telegram_id={telegram_id}, fissure={fissure}, growth={growth}")

    try:
        db = Database()
        scheme = get_db_type()
        win = 1 if growth > 0 else 0
        lose = 1 if growth < 0 else 0

        if "postgres" in scheme:
            query = """
                UPDATE users SET fissure=%s, last_fissure=%s,
                total_growth = total_growth + %s,
                total_rolls = total_rolls + 1,
                weekly_rolls = weekly_rolls + 1,
                weekly_growth = weekly_growth + %s,
                daily_best_growth = GREATEST(daily_best_growth, %s),
                last_activity = CURRENT_TIMESTAMP,
                current_win_streak = CASE WHEN %s = 1 THEN current_win_streak + 1 ELSE 0 END,
                current_lose_streak = CASE WHEN %s = 1 THEN current_lose_streak + 1 ELSE 0 END,
                current_streak = CASE WHEN %s = 1 THEN current_win_streak + 1 WHEN %s = 1 THEN current_lose_streak + 1 ELSE 0 END,
                best_streak = GREATEST(best_streak, CASE WHEN %s = 1 THEN current_win_streak + 1 WHEN %s = 1 THEN current_lose_streak + 1 ELSE 0 END),
                best_lose_streak = GREATEST(best_lose_streak, CASE WHEN %s = 1 THEN current_lose_streak + 1 ELSE best_lose_streak END),
                last_message_id = COALESCE(%s, last_message_id)
                WHERE telegram_id=%s
            """
            db.execute_query(query, (fissure, last_fissure, growth, max(0, growth), max(0, growth), win, lose, lose, win, win, lose, lose, last_message_id, telegram_id))
        else:
            query = """
                UPDATE users SET fissure=?, last_fissure=?,
                total_growth = total_growth + ?,
                total_rolls = total_rolls + 1,
                weekly_rolls = weekly_rolls + 1,
                weekly_growth = weekly_growth + ?,
                daily_best_growth = MAX(daily_best_growth, ?),
                last_activity = CURRENT_TIMESTAMP,
                current_win_streak = CASE WHEN ? = 1 THEN current_win_streak + 1 ELSE 0 END,
                current_lose_streak = CASE WHEN ? = 1 THEN current_lose_streak + 1 ELSE 0 END,
                current_streak = CASE WHEN ? = 1 THEN current_win_streak + 1 WHEN ? = 1 THEN current_lose_streak + 1 ELSE 0 END,
                best_streak = MAX(best_streak, CASE WHEN ? = 1 THEN current_win_streak + 1 WHEN ? = 1 THEN current_lose_streak + 1 ELSE 0 END),
                best_lose_streak = MAX(best_lose_streak, CASE WHEN ? = 1 THEN current_lose_streak + 1 ELSE best_lose_streak END),
                last_message_id = COALESCE(?, last_message_id)
                WHERE telegram_id=?
            """
            db.execute_query(query, (fissure, last_fissure, growth, max(0, growth), max(0, growth), win, lose, lose, win, win, lose, lose, last_message_id, telegram_id))

        user = user_cache.get(telegram_id)
        if user:
            update_fields = {
                'fissure': fissure,
                'last_fissure': last_fissure,
                'total_growth': user.get('total_growth', 0) + growth,
                'total_rolls': user.get('total_rolls', 0) + 1,
                'weekly_rolls': user.get('weekly_rolls', 0) + 1,
                'weekly_growth': user.get('weekly_growth', 0) + max(0, growth),
                'current_win_streak': (user.get('current_win_streak', 0) + 1) if win else 0,
                'current_lose_streak': (user.get('current_lose_streak', 0) + 1) if lose else 0,
                'current_streak': (user.get('current_win_streak', 0) + 1) if win else ((user.get('current_lose_streak', 0) + 1) if lose else 0),
                'best_streak': max(user.get('best_streak', 0), (user.get('current_win_streak', 0) + 1) if win else ((user.get('current_lose_streak', 0) + 1) if lose else 0)),
                'best_lose_streak': max(user.get('best_lose_streak', 0), (user.get('current_lose_streak', 0) + 1) if lose else 0),
            }
            if last_message_id:
                update_fields['last_message_id'] = last_message_id
            try:
                user_state_manager.apply_user_update(telegram_id, update_fields, save_to_db=False)
            except Exception as cache_error:
                logger.warning(f"update_fissure: cache update failed for telegram_id={telegram_id}: {cache_error}")
                user_cache.delete(telegram_id)
        else:
            db_user = db.get_user(telegram_id)
            if db_user:
                db_user.setdefault('fissure', 0.1)
                user_cache.set_without_dirty(telegram_id, db_user)

        logger.info(f"update_fissure: запись в БД выполнена для telegram_id={telegram_id}")
        # Invalidate top cache so get_fissure_top / get_fissure_rank return fresh data.
        # Without this, get_fissure_rank (no cache) sees the new value while
        # get_fissure_top (cached) returns the old top-1 -> tag flickers.
        try:
            top_cache.invalidate_top_cache()
        except Exception as cache_err:
            logger.debug(f"update_fissure: top_cache invalidation failed: {cache_err}")
    except Exception as e:
        logger.error(f"Error updating fissure: {e}")


def set_user_in_chat(telegram_id: int, in_chat: bool):
    """Установить статус нахождения пользователя в чате"""
    conn = None
    try:
        conn = get_connection()
        scheme = get_db_type()
        cursor = conn.cursor()
        if "postgres" in scheme:
            cursor.execute("UPDATE users SET in_chat = %s WHERE telegram_id = %s", (in_chat, telegram_id))
        else:
            cursor.execute("UPDATE users SET in_chat = ? WHERE telegram_id = ?", (1 if in_chat else 0, telegram_id))
        conn.commit()
        cursor.close()
        # Invalidate user cache to force fresh read from DB
        user_cache.delete(telegram_id)
        # Сбрасываем кеш топов
        top_cache.invalidate_top_cache()
        user_cache.delete('dota_digest_stats')  # Invalidate dota digest cache
        # Invalidate week top DB cache
        try:
            from main import get_dota_week_top_from_db
            if hasattr(get_dota_week_top_from_db, '_cache'):
                get_dota_week_top_from_db._cache = {}
        except Exception:
            pass
        logger.info(f"set_user_in_chat: telegram_id={telegram_id}, in_chat={in_chat}")
    except Exception as e:
        logger.error(f"set_user_in_chat error: {e}")
    finally:
        release_connection(conn)


def delete_user(telegram_id: int):
    """Отключить пользователя из чата (ставим in_chat=FALSE, данные сохраняются)"""
    conn = None
    try:
        conn = get_connection()
        scheme = get_db_type()
        cursor = conn.cursor()
        if "postgres" in scheme:
            cursor.execute("UPDATE users SET in_chat = FALSE WHERE telegram_id = %s", (telegram_id,))
        else:
            cursor.execute("UPDATE users SET in_chat = 0 WHERE telegram_id = ?", (telegram_id,))
        conn.commit()
        cursor.close()
        # Сбрасываем кеши
        top_cache.invalidate_top_cache()
        user_cache.delete('dota_digest_stats')
        user_cache.delete('digest_stats')
        user_cache.delete('dota_week_top')
        user_cache.delete('weekly_digest_stats')
        user_cache.delete(telegram_id)  # Remove specific user from cache
        # Clean steam index entry for this user
        with user_cache._lock:
            user_cache._steam_index = {sid: tid for sid, tid in list(user_cache._steam_index.items()) if tid != telegram_id}
        # Invalidate week top DB cache
        try:
            from main import get_dota_week_top_from_db
            if hasattr(get_dota_week_top_from_db, '_cache'):
                get_dota_week_top_from_db._cache = {}
        except Exception:
            pass
        logger.info(f"delete_user: telegram_id={telegram_id}")
        return True
    except Exception as e:
        logger.error(f"delete_user error: {e}")
        return False
    finally:
        release_connection(conn)


def cleanup_left_users():
    """Отключить пользователей, не появлявшихся более 7 дней (НЕ удаляем, просто отключаем)"""
    conn = None
    try:
        conn = get_connection()
        cursor = conn.cursor()
        scheme = get_db_type()

        # Disable users who left more than 7 days ago, regardless of Steam status
        if "postgres" in scheme:
            cursor.execute("""
                UPDATE users 
                SET in_chat = FALSE, 
                    fissure = 0.1, 
                    last_fissure = 0
                WHERE in_chat = TRUE 
                AND last_activity < CURRENT_TIMESTAMP - INTERVAL '7 days'
            """)
        else:
            cursor.execute("""
                UPDATE users 
                SET in_chat = 0, 
                    fissure = 0.1, 
                    last_fissure = 0
                WHERE (in_chat = 1 OR in_chat IS NULL)
                AND last_activity < datetime('now', '-7 days')
            """)
        disabled = cursor.rowcount
        conn.commit()
        cursor.close()
        if disabled:
            top_cache.invalidate_top_cache()
            user_cache.delete('dota_digest_stats')
            user_cache.delete('digest_stats')
            user_cache.delete('dota_week_top')
            user_cache.delete('weekly_digest_stats')
            # Invalidate week top DB cache
            try:
                from main import get_dota_week_top_from_db
                if hasattr(get_dota_week_top_from_db, '_cache'):
                    get_dota_week_top_from_db._cache = {}
            except Exception:
                pass
        logger.info(f"cleanup_left_users: disabled {disabled} inactive users (no activity 7 days)")
        return disabled
    except Exception as e:
        logger.error(f"cleanup_left_users error: {e}")
        return 0
    finally:
        release_connection(conn)


def cleanup_old_matches():
    """Удалить матчи старше 7 дней из public_player_matches"""
    conn = None
    try:
        conn = get_connection()
        scheme = get_db_type()
        cursor = conn.cursor()
        week_ago = int(time.time()) - (7 * 24 * 3600)
        if "postgres" in scheme:
            cursor.execute("DELETE FROM public_player_matches WHERE start_time < %s", (week_ago,))
        else:
            cursor.execute("DELETE FROM public_player_matches WHERE start_time < ?", (week_ago,))
        deleted = cursor.rowcount
        conn.commit()
        cursor.close()
        if deleted:
            logger.info(f"cleanup_old_matches: удалено {deleted} записей старше 7 дней")
        return deleted
    except Exception as e:
        logger.error(f"cleanup_old_matches error: {e}")
        return 0
    finally:
        if conn:
            release_connection(conn)


def get_fissure_top(limit=10):
    """Получение топа пользователей - из кеша"""
    cache_key = f'fissure_top_{limit}'
    cached = top_cache.get(cache_key)
    if cached is not None:
        logger.info(f"get_fissure_top: returning from cache for limit={limit}")
        return cached

    # Нет в кеше - читаем из БД
    db = Database()
    result = db.get_fissure_top(limit)

    # Сохраняем в кеш только непустой результат (иначе пустой [] будет жить вечно)
    if result:
        top_cache.set(cache_key, result)

    return result

def get_user_rank(telegram_id):
    """Получить позицию игрока в топе по MMR - из кеша"""
    cache_key = f'user_rank_{telegram_id}'
    cached = top_cache.get(cache_key)
    if cached is not None:
        logger.info(f"get_user_rank: returning from cache for {telegram_id}")
        return cached

    # Нет в кеше - читаем из БД
    db = Database()
    result = db.get_user_rank(telegram_id)

    # Сохраняем в кеш (если результат не None)
    if result is not None:
        top_cache.set(cache_key, result)

    return result

def get_fissure_rank(telegram_id):
    """Получить позицию игрока в топе по fissure - из кеша"""
    cache_key = f'fissure_rank_{telegram_id}'
    cached = top_cache.get(cache_key)
    if cached is not None:
        logger.info(f"get_fissure_rank: returning from cache for {telegram_id}")
        return cached

    # Нет в кеше - читаем из БД
    db = Database()
    result = db.get_fissure_rank(telegram_id)

    # Сохраняем в кеш (если результат не None)
    if result is not None:
        top_cache.set(cache_key, result)

    return result


def get_chat_messages_for_story(
    chat_id: int,
    period_days: int = 365,
    limit: int = 10000,
    exclude_user_id: int | None = None,
) -> tuple[list[str], dict]:
    conn = None
    try:
        conn = get_connection()
        cursor = conn.cursor()
        db_type = get_db_type()

        if db_type == "postgresql":
            interval_sql = "NOW() - INTERVAL '%s days'"
            total_query = "SELECT COUNT(*) FROM chat_messages WHERE chat_id = %s AND created_at >= " + interval_sql
            bot_query = "SELECT COUNT(*) FROM chat_messages WHERE chat_id = %s AND created_at >= " + interval_sql + " AND is_bot = TRUE"
            user_query = "SELECT message_text FROM chat_messages WHERE chat_id = %s AND created_at >= " + interval_sql + " AND is_bot = FALSE"
            params = [chat_id, period_days]
            if exclude_user_id is not None:
                user_query += " AND user_id != %s"
                params.append(exclude_user_id)
            user_query += " ORDER BY created_at DESC LIMIT %s"
            params.append(limit)
        else:
            interval_sql = "datetime('now', '-' || ? || ' days')"
            total_query = "SELECT COUNT(*) FROM chat_messages WHERE chat_id = ? AND created_at >= " + interval_sql
            bot_query = "SELECT COUNT(*) FROM chat_messages WHERE chat_id = ? AND created_at >= " + interval_sql + " AND is_bot = TRUE"
            user_query = "SELECT message_text FROM chat_messages WHERE chat_id = ? AND created_at >= " + interval_sql + " AND is_bot = FALSE"
            params = [chat_id, period_days]
            if exclude_user_id is not None:
                user_query += " AND user_id != ?"
                params.append(exclude_user_id)
            user_query += " ORDER BY created_at DESC LIMIT ?"
            params.append(limit)

        cursor.execute(total_query, (chat_id, period_days))
        total_messages = cursor.fetchone()[0]

        cursor.execute(bot_query, (chat_id, period_days))
        bot_messages = cursor.fetchone()[0]

        cursor.execute(user_query, params)
        rows = cursor.fetchall()
        messages = [row[0] for row in rows if row[0]]

        stats = {
            "total_messages": total_messages,
            "user_messages": len(messages),
            "bot_messages": bot_messages,
        }
        logger.info(f"get_chat_messages_for_story chat_id={chat_id} loaded={len(messages)} total={total_messages} bot={bot_messages} limit={limit}")
        return messages, stats
    except Exception as e:
        logger.error(f"get_chat_messages_for_story error: {e}")
        return [], {"total_messages": 0, "user_messages": 0, "bot_messages": 0}
    finally:
        if conn:
            release_connection(conn)


def update_last_message_id(telegram_id, message_id):
    """Функция для совместимости - использует новый класс Database"""
    db = Database()
    db.update_last_message_id(telegram_id, message_id)

def update_user_field(telegram_id, field, value):
    """Обновление любого поля пользователя - пишем в кеш и сразу в БД"""
    if not isinstance(telegram_id, int) or telegram_id > 76561190000000000:
        logger.warning(f"update_user_field: invalid telegram_id={telegram_id}, skipping")
        return False

    user = get_user(telegram_id)

    if user:
        user[field] = value
        user_cache.set(telegram_id, user)
        user_cache.mark_dirty(telegram_id)

        immediate_fields = {
            'fissure', 'last_fissure', 'steam_id', 'steam_nickname', 'mmr', 'rank_tier', 'wins', 'losses',
            'week_games', 'week_wins', 'week_best_streak', 'week_current_streak', 'week_start_date',
            'weekly_mvp', 'weekly_top2', 'weekly_top3', 'user_tags',
        }
        if field in immediate_fields:
            _save_user_to_db_immediately(telegram_id, user)

        user_state_manager.apply_user_update(telegram_id, {field: value}, save_to_db=False)
        return True
    return False


def increment_weekly_mmr_award(telegram_id: int, place: int = 1) -> int:
    """Увеличить счётчик награды за место в недельном топе MMR (1=MVP, 2=топ-2, 3=топ-3)."""
    if not isinstance(telegram_id, int) or telegram_id > 76561190000000000:
        logger.warning(f"increment_weekly_mmr_award: invalid telegram_id={telegram_id}")
        return 0

    field_map = {1: 'weekly_mvp', 2: 'weekly_top2', 3: 'weekly_top3'}
    field = field_map.get(place)
    if not field:
        return 0

    new_count = 0
    try:
        db = Database()
        scheme = get_db_type()
        if "postgres" in scheme:
            row = db.execute_query(
                f"UPDATE users SET {field} = COALESCE({field}, 0) + 1 WHERE telegram_id = %s RETURNING {field}",
                (telegram_id,),
                fetch="one",
            )
            if row:
                new_count = int(row[field] if isinstance(row, dict) else row[0])
        else:
            db.execute_query(
                f"UPDATE users SET {field} = COALESCE({field}, 0) + 1 WHERE telegram_id = ?",
                (telegram_id,),
            )
            row = db.execute_query(
                f"SELECT {field} FROM users WHERE telegram_id = ?",
                (telegram_id,),
                fetch="one",
            )
            if row:
                new_count = int(row[field] if isinstance(row, dict) else row[0])
    except Exception as e:
        logger.error(f"increment_weekly_mmr_award error for {telegram_id}: {e}")
        return 0

    user = get_user(telegram_id)
    if user:
        user[field] = new_count
        user_cache.set(telegram_id, user)
        user_cache.mark_dirty(telegram_id)

    logger.info(f"increment_weekly_mmr_award: user {telegram_id} {field} -> {new_count}")
    return new_count


def update_user_fields_batch(telegram_id: int, fields: dict, save_to_db: bool = True, update_top_cache: bool = True):
    """Массовое обновление полей - обновление кеша + опционально БД.
    update_top_cache=False allows the caller (MMR job) to do exactly one rebuild after the full loop.
    """
    if not isinstance(telegram_id, int):
        logger.warning(f"update_user_fields_batch: invalid telegram_id={telegram_id}, skipping")
        return False

    user = get_user(telegram_id)
    if not user:
        return False

    if any(f in fields for f in ('week_games', 'week_wins', 'week_best_streak', 'week_current_streak')):
        try:
            db = Database()
            existing = db.execute_query(
                "SELECT week_games, week_wins, week_best_streak, week_current_streak, week_start_date FROM users WHERE telegram_id = %s",
                (telegram_id,), fetch="one"
            )
        except Exception:
            existing = None
        if existing:
            if isinstance(existing, dict):
                old_week_start = existing.get('week_start_date')
            else:
                old_week_start = existing[4] if len(existing) > 4 else None
            new_week_start = fields.get('week_start_date')
            week_changed = bool(new_week_start and old_week_start and str(new_week_start) != str(old_week_start))
            if week_changed or old_week_start is None:
                for k, v in fields.items():
                    user[k] = v

    for field, value in fields.items():
        user[field] = value

    if save_to_db:
        _save_user_to_db_immediately(telegram_id, user)

    user_state_manager.apply_user_update(telegram_id, fields, save_to_db=False)
    return fields


# Whitelist of allowed field names for security in _save_user_to_db_immediately
_ALLOWED_USER_FIELDS = frozenset([
    'fissure', 'last_fissure', 'total_rolls', 'total_growth', 'current_streak', 'best_streak',
    'steam_id', 'steam_nickname', 'avatar', 'mmr', 'rank_tier',
    'week_games', 'week_wins', 'week_best_streak', 'week_current_streak', 'dota_total_games',
    'dota_wins', 'last_dota_games', 'last_dota_wins', 'wins', 'losses', 'week_start_date',
    'mmr_last_updated', 'message_count', 'weekly_mvp', 'weekly_top2', 'weekly_top3', 'user_tags',
])
_NUMERIC_USER_FIELDS = frozenset([
    'fissure', 'last_fissure', 'total_rolls', 'total_growth', 'current_streak', 'best_streak',
    'mmr', 'rank_tier', 'week_games', 'week_wins', 'week_best_streak', 'week_current_streak',
    'dota_total_games', 'dota_wins', 'last_dota_games', 'last_dota_wins', 'wins', 'losses',
    'message_count', 'weekly_mvp', 'weekly_top2', 'weekly_top3',
])


def _save_user_to_db_immediately(telegram_id, user_data):
    """Сохранение пользователя в БД сразу (для важных полей)"""
    max_retries = 3
    for attempt in range(max_retries):
        try:
            db = Database()
            scheme = get_db_type()

            if "postgres" in scheme:
                placeholders = "%s"
            else:
                placeholders = "?"

            # Build query using whitelisted field names (safe from SQL injection)
            field_names = list(_ALLOWED_USER_FIELDS)
            set_clauses = [f"{name} = {placeholders}" for name in field_names]
            query = f"""
                UPDATE users SET 
                    {', '.join(set_clauses)}
                WHERE telegram_id = {placeholders}
            """

            params = tuple(
                user_data.get(name, 0 if name in _NUMERIC_USER_FIELDS else None)
                for name in field_names
            ) + (telegram_id,)

            db.execute_query(query, params)
            return
        except Exception as e:
            if attempt < max_retries - 1:
                logger.warning(f"_save_user_to_db_immediately attempt {attempt + 1} failed, retrying...: {e}")
                time.sleep(0.1 * (attempt + 1))
            else:
                logger.error(f"Error saving user {telegram_id} to DB immediately after {max_retries} attempts: {e}", exc_info=True)
                raise


def decrease_inactive_fissure(days_inactive=1, decrease_amount=1.0):
    """Уменьшить fissure для неактивных игроков (вызывается ежедневно)"""
    db = Database()
    result = db.decrease_inactive_fissure(days_inactive, decrease_amount)
    # Сбрасываем кеш топа при изменении fissure
    if result > 0:
        top_cache.invalidate_top_cache()
    return result

def zeus_strike(percent=0.025, exclude_telegram_id=None):
    """Удар Зевса: уменьшить fissure ВСЕХ игроков на percent (батчевая версия).
    Исключает пользователя exclude_telegram_id из удара.
    Возвращает (affected_count, total_cm_reduced).
    """
    db = Database()
    scheme = get_db_type()

    logger.info(f"zeus_strike (batched): percent={percent}, exclude={exclude_telegram_id}")

    try:
        if "postgres" in scheme:
            if exclude_telegram_id:
                select_query = "SELECT fissure FROM users WHERE fissure > 0.1 AND telegram_id != %s"
                params_select = (exclude_telegram_id,)
                query = """
                    UPDATE users 
                    SET fissure = GREATEST(0.1, fissure * (1 - %s))
                    WHERE fissure > 0.1 AND telegram_id != %s
                """
                params_update = (percent, exclude_telegram_id)
            else:
                select_query = "SELECT fissure FROM users WHERE fissure > 0.1"
                params_select = None
                query = """
                    UPDATE users 
                    SET fissure = GREATEST(0.1, fissure * (1 - %s))
                    WHERE fissure > 0.1
                """
                params_update = (percent,)
            rows = db.execute_query(select_query, params_select, fetch="all")
            old_fissures = [float(r["fissure"]) for r in rows]
            db.execute_query(query, params_update)
        else:
            if exclude_telegram_id:
                select_query = "SELECT fissure FROM users WHERE fissure > 0.1 AND telegram_id != ?"
                params_select = (exclude_telegram_id,)
                query = """
                    UPDATE users 
                    SET fissure = MAX(0.1, fissure * (1 - ?))
                    WHERE fissure > 0.1 AND telegram_id != ?
                """
                params_update = (percent, exclude_telegram_id)
            else:
                select_query = "SELECT fissure FROM users WHERE fissure > 0.1"
                params_select = None
                query = """
                    UPDATE users 
                    SET fissure = MAX(0.1, fissure * (1 - ?))
                    WHERE fissure > 0.1
                """
                params_update = (percent,)
            rows = db.execute_query(select_query, params_select, fetch="all")
            old_fissures = [float(r[0]) for r in rows]
            db.execute_query(query, params_update)

        total_reduced = sum(
            max(0.0, f - max(0.1, f * (1 - percent)))
            for f in old_fissures
        )
        affected = len(old_fissures)

        user_cache.clear()
        top_cache.invalidate_top_cache()

        return affected, round(total_reduced, 1)

    except Exception as e:
        logger.error(f"zeus_strike error: {e}")
        return 0, 0.0

def reset_all_fissure_data():
    """Сбрасывает cm,rolls и cooldown для всех пользователей"""
    try:
        db = Database()
        db_type = get_db_type()
        if db_type == "postgresql":
            query = "UPDATE users SET fissure = 0.1, last_fissure = 0, total_rolls = 0, weekly_rolls = 0, weekly_growth = 0.0, current_streak = 0, best_streak = 0"
        else:
            query = "UPDATE users SET fissure = 0.1, last_fissure = 0, total_rolls = 0, weekly_rolls = 0, weekly_growth = 0.0, current_streak = 0, best_streak = 0"
        db.execute_query(query)
        top_cache.invalidate_top_cache()
        for uid in user_cache.get_all_users():
            user = user_cache.get(uid)
            if user and isinstance(user, dict):
                user['fissure'] = 0.1
                user['last_fissure'] = 0
                user['total_rolls'] = 0
                user['weekly_rolls'] = 0
                user['weekly_growth'] = 0.0
                user['current_streak'] = 0
                user['best_streak'] = 0
                user_cache.set(uid, user)
        user_cache.delete_key('digest_stats')
        logger.info("reset_all_fissure_data: все данные сброшены")
        return True
    except Exception as e:
        logger.error(f"reset_all_fissure_data error: {e}")
        return False


def batch_save_mmr(users_data: list):
    """
    Batch сохранение MMR данных всех пользователей одним запросом.
    users_data: [{"telegram_id": int, "mmr": int, "steam_nickname": str, ...}, ...]
    """
    if not users_data:
        return
    conn = None
    try:
        conn = get_connection()
        cursor = conn.cursor()

        url = urlparse.urlparse(DATABASE_URL)
        scheme = url.scheme

        if "postgres" in scheme:
            query = """
            UPDATE users SET 
                mmr = CASE WHEN %s IS NOT NULL AND %s != 0 THEN %s ELSE mmr END,
                steam_nickname = COALESCE(%s, steam_nickname),
                rank_tier = CASE WHEN %s IS NOT NULL AND %s != 0 THEN %s ELSE rank_tier END,
                week_games = CASE WHEN %s IS NOT NULL THEN %s ELSE week_games END,
                week_wins = CASE WHEN %s IS NOT NULL THEN %s ELSE week_wins END,
                week_best_streak = CASE WHEN %s IS NOT NULL THEN %s ELSE week_best_streak END,
                week_current_streak = CASE WHEN %s IS NOT NULL THEN %s ELSE week_current_streak END,
                week_start_date = COALESCE(%s, week_start_date),
                mmr_last_updated = COALESCE(%s, mmr_last_updated)
            WHERE telegram_id = %s
        """
        else:
            query = """
                UPDATE users SET 
                    mmr = CASE WHEN ? IS NOT NULL AND ? != 0 THEN ? ELSE mmr END,
                    steam_nickname = COALESCE(?, steam_nickname),
                    rank_tier = CASE WHEN ? IS NOT NULL AND ? != 0 THEN ? ELSE rank_tier END,
                    week_games = CASE WHEN ? IS NOT NULL THEN ? ELSE week_games END,
                    week_wins = CASE WHEN ? IS NOT NULL THEN ? ELSE week_wins END,
                    week_best_streak = CASE WHEN ? IS NOT NULL THEN ? ELSE week_best_streak END,
                    week_current_streak = CASE WHEN ? IS NOT NULL THEN ? ELSE week_current_streak END,
                    week_start_date = COALESCE(?, week_start_date),
                    mmr_last_updated = COALESCE(?, mmr_last_updated)
                WHERE telegram_id = ?
            """

        rows = []
        for u in users_data:
            rows.append((
                u.get("mmr"), u.get("mmr"), u.get("mmr"),
                u.get("steam_nickname"),
                u.get("rank_tier"), u.get("rank_tier"), u.get("rank_tier"),
                u.get("week_games"), u.get("week_games"),
                u.get("week_wins"), u.get("week_wins"),
                u.get("week_best_streak"), u.get("week_best_streak"),
                u.get("week_current_streak"), u.get("week_current_streak"),
                u.get("week_start_date"),
                u.get("mmr_last_updated"),
                u["telegram_id"]
            ))

        cursor.executemany(query, rows)
        conn.commit()
        cursor.close()

        # Обновляем кеш
        for u in users_data:
            cached = user_cache.get(u["telegram_id"])
            if cached:
                for k, v in u.items():
                    if v is not None and k != "telegram_id":
                        cached[k] = v
                cached.setdefault('fissure', 0.1)
                cached.setdefault('total_rolls', 0)
                cached.setdefault('current_streak', 0)
                cached.setdefault('best_streak', 0)
                user_cache.set(u["telegram_id"], cached)

        top_cache.invalidate_top_cache()
        logger.info(f"batch_save_mmr: saved {len(users_data)} users in one transaction")
    except Exception as e:
        if conn is not None:
            conn.rollback()
        logger.error(f"batch_save_mmr error: {e}")
    finally:
        if conn is not None:
            release_connection(conn)


def batch_increment_config(key: str, delta: int):
    """Атомарный инкремент значения в bot_config (1 запрос вместо 2)"""
    conn = None
    try:
        conn = get_connection()
        cursor = conn.cursor()

        url = urlparse.urlparse(DATABASE_URL)
        scheme = url.scheme

        if "postgres" in scheme:
            cursor.execute("""
                INSERT INTO bot_config (key, value) 
                VALUES (%s, %s)
                ON CONFLICT (key) DO UPDATE SET value = CAST(CAST(bot_config.value AS INTEGER) + %s AS TEXT)
            """, (key, str(delta), delta))
        else:
            cursor.execute("""
                INSERT INTO bot_config (key, value) 
                VALUES (?, ?)
                ON CONFLICT (key) DO UPDATE SET value = CAST(CAST(bot_config.value AS INTEGER) + ? AS TEXT)
            """, (key, str(delta), delta))

        conn.commit()
        cursor.close()

        # Чистим кеш
        config_cache.delete(key)
    except Exception as e:
        logger.error(f"batch_increment_config error: {e}")
    finally:
        if conn is not None:
            release_connection(conn)

def get_config(key, default=None):
    """Получить значение конфигурации - из кеша"""
    # Пробуем получить из кеша
    cached = config_cache.get(key)
    if cached is not None:
        logger.info(f"get_config: returning from cache for key={key}")
        return cached

    # Нет в кеше - читаем из БД
    db = Database()
    result = db.get_config(key, default)

    # Сохраняем в кеш (если значение не None)
    if result is not None:
        config_cache.set(key, result)

    return result

def set_config(key, value):
    """Установить значение конфигурации"""
    db = Database()
    result = db.set_config(key, value)
    config_cache.delete(key)
    return result

def get_digest_stats():
    """Получить статистику для дайджеста - из кеша"""
    cached = user_cache.get('digest_stats')
    if cached:
        logger.info("get_digest_stats: returning from cache")
        return cached

    db = Database()
    result = db.get_digest_stats()

    # Persist last known values
    if result["top_growth"][0] == "None":
        last = get_config('last_top_growth')
        if last:
            try:
                parts = json.loads(last)
                result["top_growth"] = tuple(parts[:2])
                result["top_growth_id"] = parts[2] if len(parts) > 2 else None
                result["top_growth_steam_id"] = parts[3] if len(parts) > 3 else None
                result["top_growth_username"] = parts[4] if len(parts) > 4 else None
                result["top_growth_first_name"] = parts[5] if len(parts) > 5 else None
            except Exception as e:
                logger.warning(f"get_digest_stats: failed to parse last_top_growth: {e}")
                pass
    set_config('last_top_growth', json.dumps(result["top_growth"] + (result["top_growth_id"], result.get("top_growth_steam_id"), result.get("top_growth_username"), result.get("top_growth_first_name"))))

    if result["top_drop"][0] == "None":
        last = get_config('last_top_drop')
        if last:
            try:
                parts = json.loads(last)
                result["top_drop"] = tuple(parts[:2])
                result["top_drop_id"] = parts[2] if len(parts) > 2 else None
                result["top_drop_steam_id"] = parts[3] if len(parts) > 3 else None
                result["top_drop_username"] = parts[4] if len(parts) > 4 else None
                result["top_drop_first_name"] = parts[5] if len(parts) > 5 else None
            except Exception as e:
                logger.warning(f"get_digest_stats: failed to parse last_top_drop: {e}")
                pass
    set_config('last_top_drop', json.dumps(result["top_drop"] + (result["top_drop_id"], result.get("top_drop_steam_id"), result.get("top_drop_username"), result.get("top_drop_first_name"))))

    if result["top_streak"][0] == "None":
        last = get_config('last_top_streak')
        if last:
            try:
                parts = json.loads(last)
                result["top_streak"] = tuple(parts[:2])
                result["top_streak_id"] = parts[2] if len(parts) > 2 else None
                result["top_streak_steam_id"] = parts[3] if len(parts) > 3 else None
                result["top_streak_username"] = parts[4] if len(parts) > 4 else None
                result["top_streak_first_name"] = parts[5] if len(parts) > 5 else None
            except Exception as e:
                logger.warning(f"get_digest_stats: failed to parse last_top_streak: {e}")
                pass
    set_config('last_top_streak', json.dumps(result["top_streak"] + (result["top_streak_id"], result.get("top_streak_steam_id"), result.get("top_streak_username"), result.get("top_streak_first_name"))))

    user_cache.set('digest_stats', result)
    return result


def update_player_positions():
    """Обновить позиции игроков"""
    db = Database()
    result = db.update_player_positions()
    # Сбрасываем кеш топа при обновлении позиций
    top_cache.invalidate_top_cache()
    return result



def update_digest_snapshot():
    """Обновить снимок для дайджеста"""
    db = Database()
    result = db.update_digest_snapshot()
    # Сбрасываем кеш дайджеста
    user_cache.delete('digest_stats')
    # Сбрасываем кеш топа при обновлении снимка
    top_cache.invalidate_top_cache()
    return result


def get_weekly_digest_stats():
    """Статистика для еженедельного дайджеста - из кеша"""
    cached = user_cache.get('weekly_digest_stats')
    if cached:
        logger.info("get_weekly_digest_stats: returning from cache")
        return cached

    db = Database()
    result = db.get_weekly_digest_stats()
    user_cache.set('weekly_digest_stats', result)
    return result


def update_weekly_digest_snapshot():
    """Обновить снимок и обнулить недельные счётчики после еженедельного дайджеста"""
    db = Database()
    result = db.update_weekly_digest_snapshot()
    # Сбрасываем кеш
    user_cache.delete_key('weekly_digest_stats')
    # Сбрасываем кеш топа при обновлении снимка
    top_cache.invalidate_top_cache()
    return result

def get_dota_mmr_top(limit=50):
    """Получение топа игроков Dota 2 по MMR с кешем (limit-aware)"""
    from main import get_config, set_config

    cache_key = f'mmr_top_cache_{limit}'
    cached = get_config(cache_key)
    if cached:
        try:
            cached_top = json.loads(cached)
            logger.info(f"get_dota_mmr_top: loaded from cache, {len(cached_top)} users")
            return cached_top[:limit]
        except Exception as e:
            logger.warning(f"Failed to load MMR top cache: {e}")

    try:
        conn = get_connection()
        url = urlparse.urlparse(DATABASE_URL)
        scheme = url.scheme

        cursor = conn.cursor()

        try:
            if "postgres" in scheme:
                cursor.execute("""
                    SELECT telegram_id, username, steam_nickname, mmr,
                            dota_total_games, dota_wins, week_games, week_wins,
                            rank_tier, wins, losses, COALESCE(week_current_streak, 0) as week_current_streak,
                    avatar, fissure,
                    CASE WHEN week_games > 0
                            THEN ROUND((week_wins::numeric / week_games::numeric) * 100)
                            ELSE 0 END as winrate
                    FROM users
                    WHERE steam_id IS NOT NULL
                       AND (in_chat = TRUE OR in_chat IS NULL)
                    ORDER BY
                        COALESCE(rank_tier, 0) DESC,
                        mmr DESC,
                        wins DESC
                 LIMIT %s
                """, (limit,))
                users = cursor.fetchall()
                cursor.close()
                result = [{"telegram_id": u[0], "username": u[1], "steam_nickname": u[2],
                        "mmr": u[3], "dota_total_games": u[4], "dota_wins": u[5],
                        "week_games": u[6], "week_wins": u[7],
                        "rank_tier": u[8] if u[8] else (u[3] // 73 if u[3] else 0), "wins": u[9], "losses": u[10], "week_current_streak": u[11],
                "avatar": u[12], "fissure": float(u[13]) if u[13] else 0.0} for u in users]

                if result:
                    try:
                        set_config(cache_key, json.dumps(result))
                        logger.info(f"get_dota_mmr_top: saved to cache, {len(result)} users")
                    except Exception as e:
                        logger.warning(f"Failed to save MMR top cache: {e}")

                return result
            else:
                cursor.execute("""
                    SELECT telegram_id, username, steam_nickname, mmr,
                           dota_total_games, dota_wins, week_games, week_wins,
                           rank_tier, wins, losses, COALESCE(week_current_streak, 0) as week_current_streak,
                    avatar, fissure,
                    CASE WHEN week_games > 0
                               THEN ROUND(week_wins * 100.0 / week_games)
                               ELSE 0 END as winrate
                 FROM users
                 WHERE steam_id IS NOT NULL
                    AND (in_chat = 1 OR in_chat IS NULL)
                    ORDER BY
                        COALESCE(rank_tier, 0) DESC,
                        mmr DESC,
                        wins DESC
                 LIMIT ?
            """, (limit,))
                users = cursor.fetchall()
                cursor.close()
                result = [{"telegram_id": u[0], "username": u[1], "steam_nickname": u[2],
                        "mmr": u[3], "dota_total_games": u[4], "dota_wins": u[5],
                        "week_games": u[6], "week_wins": u[7],
                        "rank_tier": u[8] if u[8] else (u[3] // 73 if u[3] else 0), "wins": u[9], "losses": u[10], "week_current_streak": u[11],
                "avatar": u[12], "fissure": float(u[13]) if u[13] else 0.0} for u in users]

                if result:
                    try:
                        set_config(cache_key, json.dumps(result))
                        logger.info(f"get_dota_mmr_top: saved to cache, {len(result)} users")
                    except Exception as e:
                        logger.warning(f"Failed to save MMR top cache: {e}")

                return result
        finally:
            cursor.close()
            release_connection(conn)
    except Exception as e:
        logger.error(f"Error get_dota_mmr_top: {e}")
        return []


def get_dota_week_top(limit=10, force_refresh=False):
    """Получение топа игроков Dota 2 за неделю - с TTL и блокировкой"""
    import time

    _TOP_CACHE_TTL = 3600  # 1 час

    # Блокировка от дубликатов - использовать threading.Lock
    global _dota_week_top_lock
    if not hasattr(get_dota_week_top, '_lock'):
        get_dota_week_top._lock = threading.Lock()
        get_dota_week_top._calculating = [False]

    if get_dota_week_top._calculating[0] and not force_refresh:
        cached_top = user_cache.get('dota_week_top')
        if cached_top:
            return cached_top[:limit]

    with get_dota_week_top._lock:
        if get_dota_week_top._calculating[0] and not force_refresh:
            cached_top = user_cache.get('dota_week_top')
            if cached_top:
                return cached_top[:limit]
        get_dota_week_top._calculating[0] = True
        try:
            cached_top = user_cache.get('dota_week_top')
            cached_time = user_cache.get('dota_week_top_ts')
            current_time = time.time()

            if cached_top and cached_time and not force_refresh:
                if current_time - cached_time < _TOP_CACHE_TTL:
                    logger.info(f"get_dota_week_top: returning cached top ({len(cached_top)} users)")
                    return cached_top[:limit]

            all_users = user_cache.get_all_users()

            # Если кеш пустой или force_refresh - загружаем из БД
            if not all_users or force_refresh:
                logger.info("get_dota_week_top: loading users from DB")
                try:
                    db_users = get_all_users_with_steam()
                    for u in db_users:
                        user_cache.set(u['telegram_id'], u)
                    all_users = user_cache.get_all_users()
                    logger.info(f"get_dota_week_top: loaded {len(all_users)} users from DB")
                except Exception as e:
                    logger.error(f"get_dota_week_top: error loading users: {e}")
                    get_dota_week_top._calculating[0] = False
                    return []

            if not all_users:
                # Fallback to config cache (persists across restarts)
                try:
                    cached = get_config('dota_week_top_cache')
                    if cached:
                        import json
                        top_users = json.loads(cached)
                        logger.info(f"get_dota_week_top: using config cache ({len(top_users)} users)")
                        for u in top_users:
                            if 'telegram_id' in u:
                                user_cache.set(u['telegram_id'], u)
                        user_cache.set('dota_week_top', top_users)
                        user_cache.set('dota_week_top_ts', time.time())
                        return top_users[:limit]
                except Exception as e:
                    logger.debug(f"get_dota_week_top: config cache fallback failed: {e}")
                get_dota_week_top._calculating[0] = False
                return []

            top_users = []
            seen_ids = set()  # Убираем дубликаты по telegram_id
            for telegram_id in all_users:
                if not isinstance(telegram_id, int):
                    continue
                # SteamID64 protection - Skip if this looks like a SteamID64 as telegram_id
                if telegram_id > 76561190000000000:
                    logger.warning(f"get_dota_week_top: skipping user with SteamID64 as telegram_id={telegram_id}")
                    continue
                if telegram_id in seen_ids:  # Пропускаем дубликаты
                    continue
                seen_ids.add(telegram_id)

                user = user_cache.get(telegram_id)
                if not user or not user.get('steam_id'):
                    continue

                week_games = user.get('week_games', 0) or 0
                # Пропускаем пользователей без игр за неделю
                if week_games == 0:
                    continue

                week_wins = user.get('week_wins', 0)
                winrate = round(week_wins / week_games * 100) if week_games > 0 else 0

                rank_tier = user.get('rank_tier')
                if rank_tier is None or rank_tier == 0:
                    mmr = user.get('mmr', 0) or 0
                    try:
                        from dota_mmr import mmr_to_rank_tier
                        rank_tier = mmr_to_rank_tier(mmr)
                    except Exception:
                        rank_tier = mmr // 73

                top_users.append({
                    'telegram_id': telegram_id,
                    'username': user.get('username'),
                    'steam_nickname': user.get('steam_nickname'),
                    'steam_id': user.get('steam_id'),
                    'mmr': user.get('mmr', 0),
                    'week_games': week_games,
                    'week_wins': week_wins,
                    'rank_tier': rank_tier,
                    'winrate': winrate,
                    'week_current_streak': user.get('week_current_streak', 0)
                })

            def get_sort_key(x):
                g = x.get('week_games', 0)
                w = x.get('week_wins', 0)
                losses = g - w  # losses
                if g == 0:
                    return (3, 0, 0)
                score = w - losses  # победы - поражения
                return (0, -score, -g)

            top_users.sort(key=get_sort_key)
            result = top_users[:limit]

            user_cache.set('dota_week_top', result)
            user_cache.set('dota_week_top_ts', time.time())

            get_dota_week_top._calculating[0] = False
            return result
        except Exception as e:
            get_dota_week_top._calculating[0] = False
            logger.error(f"get_dota_week_top error: {e}")
            return []


def get_dota_week_top_from_db(limit=10, force_refresh=False):
    """Получение топа игроков Dota 2 за неделю напрямую из БД с кешем 30 минут"""
    import time

    _TTL = 1800  # 30 минут

    cache_key = f'_dota_week_top_db_{limit}'
    if not hasattr(get_dota_week_top_from_db, '_cache') or not isinstance(get_dota_week_top_from_db._cache, dict):
        get_dota_week_top_from_db._cache = {}
    if not hasattr(get_dota_week_top_from_db, '_lock'):
        get_dota_week_top_from_db._lock = threading.Lock()

    with get_dota_week_top_from_db._lock:
        cached_data, cached_time = get_dota_week_top_from_db._cache.get(cache_key, (None, 0))
        if cached_data and (time.time() - cached_time) < _TTL and not force_refresh:
            logger.info(f"get_dota_week_top_from_db: returning cached top ({len(cached_data)} users)")
            return cached_data[:limit]

        result = _get_dota_week_top_query(limit)

        get_dota_week_top_from_db._cache[cache_key] = (result, time.time())
        return result


def _get_dota_week_top_query(limit):
    """Вспомогательная функция для получения топа игроков Dota 2 за неделю"""
    try:
        conn = get_connection()
        url = urlparse.urlparse(DATABASE_URL)
        scheme = url.scheme
        logger.info(f"get_dota_week_top: scheme={scheme}, limit={limit}")

        cursor = conn.cursor()

        # Сначала проверим, есть ли вообще данные
        try:
            cursor.execute("""
                SELECT COUNT(*) FROM users
                WHERE steam_id IS NOT NULL
                  AND (in_chat = TRUE OR in_chat IS NULL)
            """)
            total_with_steam = cursor.fetchone()[0]
            logger.info(f"get_dota_week_top: {total_with_steam} users with steam_id")
        except Exception as e:
            logger.error(f"get_dota_week_top: failed to count users: {e}")
            total_with_steam = 0

        # Если есть пользователи с steam_id, выполняем запрос
        if total_with_steam > 0:
            # Формула сортировки: сначала с играми за неделю, потом без (по рангу)
            if "postgres" in scheme:
                cursor.execute("""
                    WITH wr_calc AS (
                        SELECT telegram_id, username, first_name, steam_nickname, mmr, 
                               week_games, week_wins, rank_tier, steam_id, avatar,
                                CASE WHEN week_games > 0 
                                     THEN ROUND((week_wins::numeric / week_games::numeric) * 100) 
                                     ELSE 0 END as winrate,
                                COALESCE(week_current_streak, 0) as week_current_streak
                         FROM users
                         WHERE steam_id IS NOT NULL
                            AND (in_chat = TRUE OR in_chat IS NULL)
                      )
                     SELECT telegram_id, username, first_name, steam_nickname, mmr,
                                 COALESCE(week_games, 0) as week_games, COALESCE(week_wins, 0) as week_wins, COALESCE(rank_tier, 0) as rank_tier, steam_id, avatar,
                                 winrate, week_current_streak
                      FROM wr_calc
                      ORDER BY
                         CASE WHEN COALESCE(week_games, 0) = 0 THEN 1 ELSE 0 END,
                         CASE WHEN COALESCE(week_games, 0) = 0 THEN COALESCE(rank_tier, 0) END DESC,
                         (COALESCE(week_wins, 0) - (COALESCE(week_games, 0) - COALESCE(week_wins, 0))) DESC,
                         week_games DESC,
                         mmr DESC,
                         rank_tier DESC NULLS LAST
                     LIMIT %s
                """, (limit,))
            else:
                cursor.execute("""
                    WITH wr_calc AS (
                        SELECT telegram_id, username, first_name, steam_nickname, mmr,
                               week_games, week_wins, rank_tier, steam_id, avatar,
                                CASE WHEN week_games > 0 
                                     THEN ROUND(week_wins * 100.0 / week_games) 
                                     ELSE 0 END as winrate,
                              COALESCE(week_current_streak, 0) as week_current_streak
                         FROM users
                         WHERE steam_id IS NOT NULL
                            AND (in_chat = 1 OR in_chat IS NULL)
                     )
SELECT telegram_id, username, first_name, steam_nickname, mmr,
                                COALESCE(week_games, 0) as week_games, COALESCE(week_wins, 0) as week_wins, COALESCE(rank_tier, 0) as rank_tier, steam_id, avatar,
                                winrate, week_current_streak
                      FROM wr_calc
                     ORDER BY
                        CASE WHEN COALESCE(week_games, 0) = 0 THEN 1 ELSE 0 END,
                        CASE WHEN COALESCE(week_games, 0) = 0 THEN COALESCE(rank_tier, 0) END DESC,
                        (COALESCE(week_wins, 0) - (COALESCE(week_games, 0) - COALESCE(week_wins, 0))) DESC,
                        week_games DESC,
                        mmr DESC,
                        rank_tier DESC NULLS LAST
                    LIMIT ?
                """, (limit,))
            users = cursor.fetchall()
            cursor.close()
            logger.info(f"get_dota_week_top: returning {len(users)} users from {scheme}")

            release_connection(conn)
            result = []
            for u in users:
                result.append({
                    'telegram_id': u[0],
                    'username': u[1],
                    'first_name': u[2],
                    'steam_nickname': u[3],
                    'mmr': u[4],
                    'week_games': u[5],
                    'week_wins': u[6],
                    'rank_tier': u[7] if u[7] else (u[4] // 73 if u[4] else 0),
                    'steam_id': u[8],
                    'avatar': u[9],
                    'winrate': u[10],
                    'week_current_streak': u[11] if len(u) > 11 else 0
                })

            return result
        else:
            return []
    except Exception as e:
        logger.error(f"Error get_dota_week_top: {e}")
        release_connection(conn)
        return []


def get_dota_week_rank(telegram_id):
    """Получить позицию игрока в недельном топе Dota 2"""
    try:
        all_users = _get_dota_week_top_query(1000)
        if not all_users:
            return None

        for i, player in enumerate(all_users, 1):
            if player.get('telegram_id') == telegram_id:
                return i

        return None
    except Exception as e:
        logger.error(f"Error get_dota_week_rank: {e}")
        return None


def get_dota_digest_stats():
    """Получение статистики для Dota дайджеста - из кеша"""
    cached = user_cache.get('dota_digest_stats')
    if cached:
        logger.info(f"get_dota_digest_stats: returning from cache: {cached}")
        return cached
    else:
        logger.info("get_dota_digest_stats: cache miss or None, reading from DB")

    conn = None
    try:
        conn = get_connection()
        url = urlparse.urlparse(DATABASE_URL)
        scheme = url.scheme

        cursor = conn.cursor()

        cursor.execute("""
            SELECT COUNT(*) FROM users 
            WHERE steam_id IS NOT NULL AND week_games > 0
        """)
        count = cursor.fetchone()[0]

        if count == 0:
            cursor.close()
            result = {
                "top_winrate": ("None", 0, 0, 0, None),
                "bottom_winrate": ("None", 0, 0, 0, None),
                "top_streak": ("None", 0, None)
            }
            user_cache.set('dota_digest_stats', result)
            return result

        # ОПТИМИЗАЦИЯ: один запрос вместо трёх
        if "postgres" in scheme:
            # Один запрос: лучший винрейт, худший винрейт, лучший стрик (по новой формуле)
            cursor.execute("""
                WITH ranked AS (
                    SELECT 
                        steam_nickname, week_wins, week_games, rank_tier, telegram_id,
                        week_current_streak,
                        (week_wins::numeric / NULLIF(week_games, 0)) * SQRT(week_games::numeric) as score,
                        ROW_NUMBER() OVER (ORDER BY 
                            (CAST(ROUND(week_wins::numeric * 100 / NULLIF(week_games, 0), -1) / 10 * 10 AS INTEGER) DESC,
                            (week_wins::numeric / NULLIF(week_games, 0)) * SQRT(week_games::numeric) DESC
                        ) as rn_top,
                        ROW_NUMBER() OVER (ORDER BY 
                            (CAST(week_wins::numeric * 100 / NULLIF(week_games, 0) AS INTEGER) / 10 * 10) ASC,
                            (week_wins::numeric / NULLIF(week_games, 0)) * SQRT(week_games::numeric) ASC
                        ) as rn_bottom,
                        ROW_NUMBER() OVER (ORDER BY week_current_streak DESC) as rn_streak
                    FROM users 
                    WHERE steam_id IS NOT NULL AND week_games > 0 AND in_chat = TRUE
                )
                SELECT 
                    MAX(CASE WHEN rn_top = 1 THEN steam_nickname END) as top_nickname,
                    MAX(CASE WHEN rn_top = 1 THEN rank_tier END) as top_rank,
                    MAX(CASE WHEN rn_top = 1 THEN week_games END) as top_games,
                    MAX(CASE WHEN rn_top = 1 THEN week_wins END) as top_wins,
                    MAX(CASE WHEN rn_top = 1 THEN telegram_id END) as top_id,
                    MAX(CASE WHEN rn_bottom = 1 THEN steam_nickname END) as bottom_nickname,
                    MAX(CASE WHEN rn_bottom = 1 THEN rank_tier END) as bottom_rank,
                    MAX(CASE WHEN rn_bottom = 1 THEN week_games END) as bottom_games,
                    MAX(CASE WHEN rn_bottom = 1 THEN week_wins END) as bottom_wins,
                    MAX(CASE WHEN rn_bottom = 1 THEN telegram_id END) as bottom_id,
                    MAX(CASE WHEN rn_streak = 1 AND week_current_streak > 0 THEN steam_nickname END) as streak_nickname,
                    MAX(CASE WHEN rn_streak = 1 AND week_current_streak > 0 THEN week_current_streak END) as streak_val,
                    MAX(CASE WHEN rn_streak = 1 AND week_current_streak > 0 THEN telegram_id END) as streak_id
                FROM ranked
            """)
            row = cursor.fetchone()

            top = (row[0], row[1], row[2], row[3], row[4]) if row and row[0] else None
            bottom = (row[5], row[6], row[7], row[8], row[9]) if row and row[5] else None
            streak = (row[10], row[11], row[12]) if row and row[10] else None
        else:
            # SQLite: CTE with window functions вместо 9 подзапросов
            cursor.execute("""
                WITH ranked AS (
                    SELECT 
                        steam_nickname, week_wins, week_games, rank_tier, telegram_id,
                        week_current_streak,
                        (CAST(ROUND(week_wins * 100.0 / week_games, -1) / 10 * 10 AS INTEGER)) as wr_tier,
                        (week_wins * 1.0 / week_games) * SQRT(week_games) as score
                    FROM users 
                    WHERE steam_id IS NOT NULL AND week_games > 0 AND in_chat = 1
                ),
                top_player AS (
                    SELECT steam_nickname, rank_tier, week_games, week_wins, telegram_id, wr_tier, score
                    FROM ranked
                    ORDER BY wr_tier DESC, score DESC
                    LIMIT 1
                ),
                bottom_player AS (
                    SELECT steam_nickname, rank_tier, week_games, week_wins, telegram_id, wr_tier, score
                    FROM ranked
                    ORDER BY wr_tier ASC, score ASC
                    LIMIT 1
                ),
                streak_player AS (
                    SELECT steam_nickname, week_current_streak, telegram_id
                    FROM users 
                    WHERE steam_id IS NOT NULL AND week_current_streak > 0 AND in_chat = 1
                    ORDER BY week_current_streak DESC
                    LIMIT 1
                )
                SELECT 
                    (SELECT steam_nickname FROM top_player) as top_nickname,
                    (SELECT rank_tier FROM top_player) as top_rank,
                    (SELECT week_games FROM top_player) as top_games,
                    (SELECT week_wins FROM top_player) as top_wins,
                    (SELECT telegram_id FROM top_player) as top_id,
                    (SELECT steam_nickname FROM bottom_player) as bottom_nickname,
                    (SELECT rank_tier FROM bottom_player) as bottom_rank,
                    (SELECT week_games FROM bottom_player) as bottom_games,
                    (SELECT week_wins FROM bottom_player) as bottom_wins,
                    (SELECT telegram_id FROM bottom_player) as bottom_id,
                    (SELECT steam_nickname FROM streak_player) as streak_nickname,
                    (SELECT week_current_streak FROM streak_player) as streak_val,
                    (SELECT telegram_id FROM streak_player) as streak_id
            """)
            row = cursor.fetchone()

            top = (row[0], row[1], row[2], row[3], row[4]) if row and row[0] else None
            bottom = (row[5], row[6], row[7], row[8], row[9]) if row and row[5] else None
            streak = (row[10], row[11], row[12]) if row and row[10] else None

        cursor.close()

        result = {
            # (steam_nickname, rank_tier, week_games, week_wins, telegram_id)
            "top_winrate": (top[0], top[3], top[2], top[1], top[4]) if top else ("None", 0, 0, 0, None),
            "bottom_winrate": (bottom[0], bottom[3], bottom[2], bottom[1], bottom[4]) if bottom else ("None", 0, 0, 0, None),
            # SQL: SELECT steam_nickname, week_current_streak, telegram_id
            # (steam_nickname, week_current_streak, telegram_id)
            "top_streak": (streak[0], streak[1], streak[2]) if streak else ("None", 0, None)
        }

        logger.info(f"Dota digest stats: {result}")
        user_cache.set('dota_digest_stats', result)
        return result
    except Exception as e:
        logger.error(f"Error get_dota_digest_stats: {e}")
        return {
            "top_winrate": ("None", 0, 0, 0, None),
            "bottom_winrate": ("None", 0, 0, 0, None),
            "top_streak": ("None", 0, None)
        }
    finally:
        release_connection(conn)


def _get_all_users_query(load_all=False, allow_non_steam=False):
    """Shared helper: fetch users from DB with ALL columns to avoid setdefault in hot path."""
    conn = None
    try:
        conn = get_connection()
        url = urlparse.urlparse(DATABASE_URL)
        scheme = url.scheme
        cursor = conn.cursor()

        where = "" if allow_non_steam or load_all else " WHERE steam_id IS NOT NULL"

        sql = f"""
            SELECT telegram_id, username, fissure, last_fissure, last_message_id,
                   total_growth, total_rolls, best_streak, current_streak,
                   steam_id, steam_nickname, mmr, rank_tier, dota_total_games, dota_wins,
                   week_games, week_wins, week_best_streak, week_current_streak, last_dota_games, last_dota_wins,
                   message_count, week_start_date, week_updated_at, analytics_cache, analytics_updated_at,
                   current_win_streak, current_lose_streak, best_lose_streak, weekly_rolls, weekly_growth,
                   last_activity, in_chat, digest_fissure, weekly_digest_position,
                   mmr_last_updated, created_at, daily_best_growth,
                   weekly_mvp, weekly_top2, weekly_top3, user_tags
             FROM users{where}
        """
        if "postgres" in scheme:
            cursor.execute(sql)
            users = cursor.fetchall()
            columns = [desc[0] for desc in cursor.description]
        else:
            cursor.execute(sql)
            users = cursor.fetchall()
            columns = [desc[0] for desc in cursor.description]
        cursor.close()
        logger.info(f"_get_all_users_query: fetched {len(users)} users")

        return [{
            "telegram_id": u["telegram_id"],
            "username": u["username"],
            "fissure": float(u["fissure"]) if u["fissure"] is not None else 0.1,
            "last_fissure": u["last_fissure"],
            "last_message_id": u["last_message_id"],
            "total_growth": float(u["total_growth"]) if u["total_growth"] is not None else 0.0,
            "total_rolls": int(u["total_rolls"]) if u["total_rolls"] is not None else 0,
            "best_streak": int(u["best_streak"]) if u["best_streak"] is not None else 0,
            "current_streak": int(u["current_streak"]) if u["current_streak"] is not None else 0,
            "steam_id": u["steam_id"],
            "steam_nickname": u["steam_nickname"],
            "mmr": int(u["mmr"]) if u["mmr"] is not None else 0,
            "rank_tier": int(u["rank_tier"]) if u["rank_tier"] is not None else 0,
            "dota_total_games": int(u["dota_total_games"]) if u["dota_total_games"] is not None else 0,
            "dota_wins": int(u["dota_wins"]) if u["dota_wins"] is not None else 0,
            "week_games": int(u["week_games"]) if u["week_games"] is not None else 0,
            "week_wins": int(u["week_wins"]) if u["week_wins"] is not None else 0,
            "week_best_streak": int(u["week_best_streak"]) if u["week_best_streak"] is not None else 0,
            "week_current_streak": int(u["week_current_streak"]) if u["week_current_streak"] is not None else 0,
            "last_dota_games": int(u["last_dota_games"]) if u["last_dota_games"] is not None else 0,
            "last_dota_wins": int(u["last_dota_wins"]) if u["last_dota_wins"] is not None else 0,
            "message_count": int(u["message_count"]) if u.get("message_count") is not None else 0,
            "week_start_date": u.get("week_start_date"),
            "week_updated_at": u.get("week_updated_at"),
            "analytics_cache": u.get("analytics_cache"),
            "analytics_updated_at": u.get("analytics_updated_at"),
            "current_win_streak": int(u["current_win_streak"]) if u.get("current_win_streak") is not None else 0,
            "current_lose_streak": int(u["current_lose_streak"]) if u.get("current_lose_streak") is not None else 0,
            "best_lose_streak": int(u["best_lose_streak"]) if u.get("best_lose_streak") is not None else 0,
            "weekly_rolls": int(u["weekly_rolls"]) if u.get("weekly_rolls") is not None else 0,
            "weekly_growth": float(u["weekly_growth"]) if u.get("weekly_growth") is not None else 0.0,
            "last_activity": u.get("last_activity"),
            "in_chat": bool(u["in_chat"]) if u.get("in_chat") is not None else False,
            "digest_fissure": float(u["digest_fissure"]) if u.get("digest_fissure") is not None else 0.0,
            "weekly_digest_position": int(u["weekly_digest_position"]) if u.get("weekly_digest_position") is not None else 0,
            "week_best_streak": int(u["week_best_streak"]) if u.get("week_best_streak") is not None else 0,
            "mmr_last_updated": float(u["mmr_last_updated"]) if u.get("mmr_last_updated") is not None else 0.0,
            "created_at": u.get("created_at"),
            "daily_best_growth": float(u["daily_best_growth"]) if u.get("daily_best_growth") is not None else 0.0,
            "weekly_mvp": int(u["weekly_mvp"]) if u.get("weekly_mvp") is not None else 0,
            "weekly_top2": int(u["weekly_top2"]) if u.get("weekly_top2") is not None else 0,
            "weekly_top3": int(u["weekly_top3"]) if u.get("weekly_top3") is not None else 0,
            "user_tags": u.get("user_tags") or "[]",
        } for u in (dict(zip(columns, row)) for row in users)]
    except Exception as e:
        logger.error(f"Error _get_all_users_query: {e}")
        return []
    finally:
        if conn is not None:
            release_connection(conn)


def get_all_users_from_db():
    """Получение всех пользователей из БД (полные данные, все колонки)"""
    return _get_all_users_query(load_all=True, allow_non_steam=True)


def get_all_users():
    """Получение всех пользователей (для загрузки в кеш при старте) - ВСЕ пользователи"""
    return _get_all_users_query(load_all=True, allow_non_steam=True)


def reset_weekly_stats():
    """Сброс недельной статистики для всех пользователей (вызывается по понедельникам)"""
    from datetime import datetime as dt
    from datetime import timedelta
    MSK = timezone(timedelta(hours=3))
    monday_msk = dt.now(MSK) - timedelta(days=dt.now(MSK).weekday())
    current_week_start = monday_msk.strftime("%Y-%m-%d")
    try:
        conn = get_connection()
        url = urlparse.urlparse(DATABASE_URL)
        scheme = url.scheme
        cursor = conn.cursor()

        if "postgres" in scheme:
            cursor.execute("""
                UPDATE users SET week_games = 0, week_wins = 0, week_current_streak = 0, week_best_streak = GREATEST(week_best_streak, week_current_streak), week_start_date = %s WHERE steam_id IS NOT NULL
            """, (current_week_start,))
        else:
            cursor.execute("""
                UPDATE users SET week_games = 0, week_wins = 0, week_current_streak = 0, week_best_streak = MAX(week_best_streak, week_current_streak), week_start_date = ? WHERE steam_id IS NOT NULL
            """, (current_week_start,))

        affected = cursor.rowcount
        conn.commit()
        cursor.close()
        logger.info(f"Сброшена недельная статистика для {affected} пользователей, week_start_date={current_week_start}")
        return affected
    except Exception as e:
        logger.error(f"Error reset_weekly_stats: {e}")
        return 0


def get_all_users_with_steam():
    """Получение всех пользователей с привязанным Steam"""
    conn = None
    try:
        conn = get_connection()
        url = urlparse.urlparse(DATABASE_URL)
        scheme = url.scheme
        cursor = conn.cursor()

        if "postgres" in scheme:
            cursor.execute("""
                SELECT telegram_id, username, fissure, last_fissure, last_message_id, 
                       total_growth, total_rolls, best_streak, current_streak,
                       steam_id, steam_nickname, mmr, rank_tier, dota_total_games, dota_wins,
                        week_games, week_wins, week_best_streak, week_current_streak, last_dota_games, last_dota_wins,
                        message_count, avatar, mmr_last_updated
                 FROM users 
                 WHERE steam_id IS NOT NULL
            """)
            users = cursor.fetchall()
            cursor.close()
            return [{
                "telegram_id": u[0], "username": u[1], "fissure": u[2] if u[2] is not None else 0.1, "last_fissure": u[3],
                "last_message_id": u[4], "total_growth": u[5], "total_rolls": u[6],
                "best_streak": u[7], "current_streak": u[8], "steam_id": u[9],
                "steam_nickname": u[10], "mmr": u[11], "rank_tier": u[12],
                "dota_total_games": u[13], "dota_wins": u[14], "week_games": u[15],
                "week_wins": u[16], "week_best_streak": u[17], "week_current_streak": u[18], "last_dota_games": u[19],
                "last_dota_wins": u[20], "message_count": u[21], "avatar": u[22],
                "mmr_last_updated": u[23]
            } for u in users]
        else:
            cursor.execute("""
                SELECT telegram_id, username, fissure, last_fissure, last_message_id, 
                       total_growth, total_rolls, best_streak, current_streak,
                       steam_id, steam_nickname, mmr, rank_tier, dota_total_games, dota_wins,
                        week_games, week_wins, week_best_streak, week_current_streak, last_dota_games, last_dota_wins,
                        message_count, avatar, mmr_last_updated
                 FROM users 
                 WHERE steam_id IS NOT NULL
            """)
            users = cursor.fetchall()
            cursor.close()
            return [{
                "telegram_id": u[0], "username": u[1], "fissure": u[2] if u[2] is not None else 0.1, "last_fissure": u[3],
                "last_message_id": u[4], "total_growth": u[5], "total_rolls": u[6],
                "best_streak": u[7], "current_streak": u[8], "steam_id": u[9],
                "steam_nickname": u[10], "mmr": u[11], "rank_tier": u[12],
                "dota_total_games": u[13], "dota_wins": u[14], "week_games": u[15],
                "week_wins": u[16], "week_best_streak": u[17], "week_current_streak": u[18], "last_dota_games": u[19],
                "last_dota_wins": u[20], "message_count": u[21] if len(u) > 21 else 0,
                "avatar": u[22] if len(u) > 22 else None,
                "mmr_last_updated": u[23] if len(u) > 23 else None
            } for u in users]
    except Exception as e:
        logger.error(f"Error get_all_users_with_steam: {e}")
        return []
    finally:
        if conn is not None:
            release_connection(conn)


RECENT_ROLLS_CACHE_KEY = 'recent_fissure_rolls'


def save_recent_rolls(rolls):
    try:
        set_config(RECENT_ROLLS_CACHE_KEY, json.dumps(rolls))
    except Exception as e:
        logger.error(f"Error saving recent rolls: {e}")


def load_recent_rolls():
    try:
        data = get_config(RECENT_ROLLS_CACHE_KEY)
        if data:
            return json.loads(data)
    except Exception as e:
        logger.error(f"Error loading recent rolls: {e}")
    return []


def invalidate_stale_top_caches():
    try:
        keys_to_delete = []
        for key in ['dota_week_top_cache', 'dota_week_top']:
            if get_config(key):
                keys_to_delete.append(key)
        for key in keys_to_delete:
            try:
                set_config(key, None)
                logger.info(f"invalidated stale cache: {key}")
            except Exception as e:
                logger.warning(f"failed to invalidate cache {key}: {e}")
        try:
            user_cache.delete_key('dota_week_top')
            user_cache.delete_key('dota_week_top_ts')
            user_cache.delete_key('digest_stats')
            user_cache.delete_key('dota_digest_stats')
            top_cache.invalidate_top_cache()
            logger.info("invalidated in-memory top/digest caches")
        except Exception as e:
            logger.warning(f"failed to invalidate memory cache: {e}")
    except Exception as e:
        logger.error(f"invalidate_stale_top_caches error: {e}")


def validate_user_registry():
    try:
        db = Database()
        invalid_count, active_skipped = db.audit_invalid_telegram_ids()
        if invalid_count:
            logger.warning(f"validate_user_registry: found {invalid_count} users with invalid telegram_id (skipped {active_skipped} active users)")
        invalidate_stale_top_caches()
        return invalid_count
    except Exception as e:
        logger.error(f"validate_user_registry error: {e}")
        return -1
