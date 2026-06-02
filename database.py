from __future__ import annotations
import os
import sqlite3
import psycopg2
import time
import psycopg2.extras
import logging
import urllib.parse as urlparse
import threading
import json
from contextlib import contextmanager
from typing import Optional, Any, Generator, Protocol
from dataclasses import dataclass

def _telegram_error_contains(error: Exception, *phrases: str) -> bool:
    if error is None:
        return False
    msg = str(error).lower()
    return any(p.lower() in msg for p in phrases)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@dataclass
class User:
    telegram_id: int
    username: Optional[str] = None
    steam_id: Optional[int] = None
    steam_nickname: Optional[str] = None
    fissure: float = 0.0
    mmr: int = 0
    rank_tier: int = 0
    total_rolls: int = 0
    current_streak: int = 0
    best_streak: int = 0
    message_count: int = 0

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
                message_count=row.get("message_count", 0),
            )
        return cls(
            telegram_id=row[0],
            username=row[1],
            steam_id=row[2],
            steam_nickname=row[3],
            fissure=float(row[4]) if len(row) > 4 else 0,
            mmr=row[5] if len(row) > 5 else 0,
            rank_tier=row[6] if len(row) > 6 else 0,
            total_rolls=row[7] if len(row) > 7 else 0,
            current_streak=row[8] if len(row) > 8 else 0,
            best_streak=row[9] if len(row) > 9 else 0,
            message_count=row[10] if len(row) > 10 else 0,
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


class UserCache:
    """Кеш данных пользователей в памяти с записью в БД раз в сутки"""
    
    MAX_CACHE_SIZE = 3000  # Максимум пользователей в кеше
    
    def __init__(self) -> None:
        self._cache: dict[int, dict[str, Any]] = {}  # telegram_id -> user_data
        self._dirty: dict[int, bool] = {}  # telegram_id -> True
        self._lock = threading.Lock()


DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    DATABASE_URL = "sqlite:///fissure_bot.db"
    print(f"💡 Используется: {DATABASE_URL}")
else:
    print(f"Using DATABASE_URL: {DATABASE_URL[:20]}...")


class UserCache:
    """Кеш данных пользователей в памяти с записью в БД раз в сутки"""
    
    MAX_CACHE_SIZE = 3000  # Максимум пользователей в кеше
    
    def __init__(self) -> None:
        self._cache: dict[int, dict[str, Any]] = {}  # telegram_id -> user_data
        self._dirty: dict[int, bool] = {}  # telegram_id -> True
        self._lock = threading.Lock()
    
    def get(self, telegram_id: int) -> Optional[dict[str, Any]]:
        """Получить данные пользователя из кеша"""
        with self._lock:
            return self._cache.get(telegram_id)
    
    def set(self, telegram_id, data):
        """Установить данные пользователя в кеш"""
        # Prevent SteamID64 from being used as telegram_id key
        if isinstance(telegram_id, int) and telegram_id > 76561190000000000:
            logger.warning(f"UserCache.set: rejecting SteamID64 as telegram_id key={telegram_id}")
            return
        with self._lock:
            self._cache[telegram_id] = data
            # Проверяем лимит при каждой записи
            if len(self._cache) > self.MAX_CACHE_SIZE:
                self.enforce_limit()
    
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

    def clear(self):
        """Очистить весь кеш"""
        with self._lock:
            self._cache.clear()
            self._dirty.clear()
    
    def enforce_limit(self):
        with self._lock:
            if len(self._cache) > self.MAX_CACHE_SIZE:
                # Удаляем старые записи (первые N / 2)
                keys_to_remove = list(self._cache.keys())[:len(self._cache) // 2]
                for key in keys_to_remove:
                    self._cache.pop(key, None)
                    self._dirty.pop(key, None)  # Используем pop с дефолтом


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


# Глобальные экземпляры кешей (оптимизировано для экономии CU в serverless)
config_cache = TTLCache(default_ttl=300)  # 5 минут для конфигурации
top_cache = TTLCache(default_ttl=1800)  # 30 минут для топов и рангов

_aiohttp_session = None

async def get_aiohttp_session():
    """Получить переиспользуемую aiohttp сессию для оптимизации соединений"""
    global _aiohttp_session
    if _aiohttp_session is None or _aiohttp_session.closed:
        import aiohttp
        _aiohttp_session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=10),
            connector=aiohttp.TCPConnector(limit=10, limit_per_host=5)
        )
    return _aiohttp_session

async def close_aiohttp_session():
    """Закрыть aiohttp сессию при выключении бота"""
    global _aiohttp_session
    if _aiohttp_session and not _aiohttp_session.closed:
        await _aiohttp_session.close()
        _aiohttp_session = None


def flush_users_cache():
    """Сброс всех изменённых пользователей в БД с использованием batch операций"""
    dirty_users = user_cache.get_all_dirty()
    if not dirty_users:
        logger.info("flush_users_cache: no dirty users")
        return 0
    
    logger.info(f"flush_users_cache: found {len(dirty_users)} dirty users, saving to DB")
    
    db_type = get_db_type()
    flushed = 0
    
    conn = None
    cursor = None
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        # Подготавливаем данные для batch обновления
        batch_data = []
        for telegram_id in dirty_users:
            # Skip if telegram_id looks like SteamID64 (protection against corrupted cache)
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
        
        # Batch обновление через executemany для экономии CU
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
            
            # Очищаем dirty флаги только для успешно обновленных пользователей
            flushed = len(batch_data)
            for i in range(flushed):
                telegram_id = batch_data[i][-1]  # telegram_id is last element
                user_cache.clear_dirty(telegram_id)
        
        conn.commit()
        
    except Exception as e:
        logger.error(f"flush_users_cache: batch error: {e}")
        if conn:
            conn.rollback()
    finally:
        if cursor:
            cursor.close()
        if conn:
            release_connection(conn)
    
    logger.info(f"flush_users_cache: flushed {flushed} users")
    return flushed


def update_dota_week_top_cache():
    """Обновление кеша топа MMR из данных пользователей"""
    all_users = user_cache.get_all_users()
    
    # Если в кеше нет пользователей - загружаем из БД
    if not all_users:
        logger.info("update_dota_week_top_cache: no users in cache, loading from DB")
        try:
            # Note: get_all_users_with_steam is defined at line 2802, called at runtime so it works
            db_users = get_all_users_with_steam()
            for u in db_users:
                user_cache.set(u['telegram_id'], u)
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
        
        week_games = user.get('week_games', 0)
        week_wins = user.get('week_wins', 0)
        winrate = round((week_wins / week_games * 100), 1) if week_games > 0 else 0
        
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
        score = 2 * w - g  # wins - losses
        return (0, -score, -g)  # Сортировка по убыванию score, затем по убыванию игр
    
    top_users.sort(key=get_sort_key)
    
    logger.info("===== TOP USERS AFTER SORT =====")
    for i, u in enumerate(top_users):
        week_losses = u.get('week_games', 0) - u.get('week_wins', 0)
        logger.info(f"  POS{i+1}. {u.get('steam_nickname')}: {u.get('week_wins')}W/{week_losses}L, WR={u.get('winrate')}%")
    logger.info("===== END SORT =====")
    
    # Сохраняем в кеш
    user_cache.set('dota_week_top', top_users)
    logger.info(f"update_dota_week_top_cache: cached {len(top_users)} users")


# Connection pool management
_pool_lock = threading.Lock()
_pool = {}  # db_type -> list of connections
_max_connections = 50  # Max connections per DB type (оптимизировано для serverless)
_persistent_pg_conn = None  # одно соединение на процесс — меньше DISCARD ALL на Neon
_last_pg_conn_check = 0
_PG_CONN_CHECK_INTERVAL = 90  # секунд — не чаще одного лёгкого пинга в 1.5 минуты (минимальный оверхед)

SCHEMA_VERSION = "20260516v1"
SCHEMA_VERSION_KEY = "schema_version"

_PG_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_users_fissure ON users(fissure DESC)",
    "CREATE INDEX IF NOT EXISTS idx_users_mmr ON users(mmr DESC)",
    "CREATE INDEX IF NOT EXISTS idx_users_steam_id ON users(steam_id)",
    "CREATE INDEX IF NOT EXISTS idx_users_week_games ON users(week_games DESC)",
    "CREATE INDEX IF NOT EXISTS idx_users_current_position ON users(current_position)",
    "CREATE INDEX IF NOT EXISTS idx_users_rank_tier ON users(rank_tier DESC)",
)

# Лёгкие миграции — выполняются даже при fast init (ADD IF NOT EXISTS)
_PG_ENSURE_COLUMNS = (
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS weekly_mvp_count INTEGER DEFAULT 0",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS weekly_top2_count INTEGER DEFAULT 0",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS weekly_top3_count INTEGER DEFAULT 0",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS week_updated_at TIMESTAMP",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS mmr_last_updated REAL",
)


def _ensure_pg_columns(cursor):
    for sql in _PG_ENSURE_COLUMNS:
        cursor.execute(sql)


def _reset_persistent_pg_conn(reason: str = ""):
    """Аккуратно закрывает и обнуляет persistent-соединение при обрывах."""
    global _persistent_pg_conn, _last_pg_conn_check
    if _persistent_pg_conn is not None:
        try:
            _persistent_pg_conn.close()
        except Exception:
            pass
        _persistent_pg_conn = None
        _last_pg_conn_check = 0
        if reason:
            logger.warning(f"Persistent PostgreSQL connection reset: {reason}")


def get_db_type():
    """Получить тип базы данных"""
    if DATABASE_URL is None:
        return "sqlite"
    url = urlparse.urlparse(DATABASE_URL)
    scheme = url.scheme
    if scheme is None:
        return "sqlite"
    scheme_str = str(scheme)
    return "postgresql" if "postgres" in scheme_str else "sqlite"


def _postgres_connect_kwargs():
    """Разобрать DATABASE_URL для psycopg2 (libpq не понимает pgbouncer=true)."""
    url = urlparse.urlparse(DATABASE_URL)
    query = urlparse.parse_qs(url.query, keep_blank_values=True)
    query.pop("pgbouncer", None)

    sslmode = (query.pop("sslmode", None) or ["require"])[0]
    kwargs = {
        "dbname": (url.path or "").lstrip("/"),
        "user": url.username,
        "password": url.password,
        "host": url.hostname,
        "port": url.port or 5432,
        "sslmode": sslmode,
        "connect_timeout": 10,
    }
    for key in ("sslrootcert", "sslcert", "sslkey", "options", "application_name"):
        if key in query and query[key]:
            kwargs[key] = query[key][0]
    return kwargs


def get_connection():
    """Получение соединения с базой данных с пулом"""
    db_type = get_db_type()

    if db_type == "postgresql":
        global _persistent_pg_conn, _last_pg_conn_check
        with _pool_lock:
            if _persistent_pg_conn is None or _persistent_pg_conn.closed:
                _persistent_pg_conn = psycopg2.connect(**_postgres_connect_kwargs())
                _persistent_pg_conn.autocommit = True
                _last_pg_conn_check = time.time()
                logger.info("PostgreSQL connected (persistent, autocommit=True)")
            else:
                now = time.time()
                # Лёгкая проверка живости раз в _PG_CONN_CHECK_INTERVAL (не на каждый запрос!)
                if now - _last_pg_conn_check > _PG_CONN_CHECK_INTERVAL:
                    try:
                        with _persistent_pg_conn.cursor() as cur:
                            cur.execute("SELECT 1")
                        _last_pg_conn_check = now
                    except Exception as e:
                        _reset_persistent_pg_conn(f"liveness check failed: {e}")
                        # Пересоздаём сразу
                        _persistent_pg_conn = psycopg2.connect(**_postgres_connect_kwargs())
                        _persistent_pg_conn.autocommit = True
                        _last_pg_conn_check = time.time()
                        logger.info("PostgreSQL reconnected after failed liveness check")

                try:
                    status = _persistent_pg_conn.get_transaction_status()
                    if status != psycopg2.extensions.TRANSACTION_STATUS_IDLE:
                        logger.warning("Persistent connection was in non-idle state, rolling back before reuse")
                        _persistent_pg_conn.rollback()
                except Exception:
                    try:
                        _persistent_pg_conn.rollback()
                    except Exception:
                        pass
            return _persistent_pg_conn

    print(f"[DB] Getting connection, type: {db_type}")
    
    with _pool_lock:
        # Проверяем доступные соединения в пуле
        if db_type in _pool and _pool[db_type]:
            conn = _pool[db_type].pop()
            try:
                conn.isolation_level = None  # Reset isolation level for PostgreSQL
                print("[DB] Reusing connection from pool")
                return conn
            except Exception as e:
                print(f"[DB] Connection failed: {e}")
                try:
                    conn.close()
                except:
                    pass
        
        # Создаем новое соединение
        print(f"[DB] Creating new connection for {db_type}")
        if db_type == "postgresql":
            try:
                # Neon: используйте pooled endpoint (-pooler в hostname), не ?pgbouncer=true
                conn = psycopg2.connect(**_postgres_connect_kwargs())
                logger.info("PostgreSQL connected")
            except Exception as e:
                logger.error(f"PostgreSQL connection failed: {e}")
                raise
        else:
            if DATABASE_URL is None:
                db_path = "fissure_bot.db"
            elif DATABASE_URL.startswith("sqlite:///"):
                db_path = DATABASE_URL[10:]
            elif DATABASE_URL.startswith("sqlite://"):
                db_path = DATABASE_URL[9:]
            else:
                db_path = DATABASE_URL
            
            conn = sqlite3.connect(db_path, timeout=10)
            logger.info("SQLite connected")
        
        return conn

def release_connection(conn):
    """Вернуть соединение в пул"""
    if conn is None:
        return
    if get_db_type() == "postgresql" and conn is _persistent_pg_conn:
        return
    db_type = get_db_type()  # Получаем тип вне блокировки
    with _pool_lock:
        if db_type not in _pool:
            _pool[db_type] = []
        if len(_pool[db_type]) < _max_connections:
            _pool[db_type].append(conn)
        else:
            try:
                conn.close()
            except:
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
            if 'weekly_mvp_count' not in columns:
                cursor.execute("ALTER TABLE users ADD COLUMN weekly_mvp_count INTEGER DEFAULT 0")
            if 'weekly_top2_count' not in columns:
                cursor.execute("ALTER TABLE users ADD COLUMN weekly_top2_count INTEGER DEFAULT 0")
            if 'weekly_top3_count' not in columns:
                cursor.execute("ALTER TABLE users ADD COLUMN weekly_top3_count INTEGER DEFAULT 0")
            if 'last_greeting_date' not in columns:
                cursor.execute("ALTER TABLE users ADD COLUMN last_greeting_date DATE")
            if 'message_count' not in columns:
                cursor.execute("ALTER TABLE users ADD COLUMN message_count INTEGER DEFAULT 0")
            if 'first_name' not in columns:
                cursor.execute("ALTER TABLE users ADD COLUMN first_name TEXT")
            
            # Создаём индексы для часто используемых полей (улучшение производительности)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_fissure ON users(fissure DESC)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_mmr ON users(mmr DESC)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_steam_id ON users(steam_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_week_games ON users(week_games DESC)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_current_position ON users(current_position)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_rank_tier ON users(rank_tier DESC)")
        
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
                logger.error(f"execute_query error: {e}")
                try:
                    conn.rollback()
                except Exception:
                    pass
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
                logger.error(f"execute_query error: {e}")
                try:
                    conn.rollback()
                except Exception:
                    pass
                raise
            finally:
                release_connection(conn)

    def add_user(self, telegram_id, username=None, first_name=None, last_name=None):
        """Добавить нового пользователя или обновить существующего"""
        try:
            url = urlparse.urlparse(DATABASE_URL)
            scheme = url.scheme
            
            if "postgres" in scheme:
                query = '''
                    INSERT INTO users (telegram_id, username, first_name, fissure, last_fissure, last_message_id, total_growth, total_rolls, created_at, message_count)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP, 0)
                    ON CONFLICT (telegram_id) 
                    DO UPDATE SET 
                        username = EXCLUDED.username,
                        first_name = EXCLUDED.first_name,
                        fissure = EXCLUDED.fissure,
                        last_fissure = EXCLUDED.last_fissure,
                        last_message_id = EXCLUDED.last_message_id,
                        total_growth = EXCLUDED.total_growth,
                        total_rolls = EXCLUDED.total_rolls
                    RETURNING id
                '''
                result = self.execute_query(query, (telegram_id, username, first_name, 0.1, 0, 0, 0, 0), fetch="one")
                return result[0] if result else telegram_id
            else:
                query = '''
                    INSERT INTO users (telegram_id, username, first_name, fissure, last_fissure, last_message_id, total_growth, total_rolls, created_at, message_count)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), 0)
                    ON CONFLICT(telegram_id) DO UPDATE SET
                        username = excluded.username,
                        first_name = excluded.first_name,
                        fissure = excluded.fissure,
                        last_fissure = excluded.last_fissure,
                        last_message_id = excluded.last_message_id,
                        total_growth = excluded.total_growth,
                        total_rolls = excluded.total_rolls
                '''
                self.execute_query(query, (telegram_id, username, first_name, 0.1, 0, 0, 0, 0))
                return None
        except Exception as e:
            # If the serial sequence for `id` is out of sync (common after data restores),
            # the INSERT may fail on users_pkey before the ON CONFLICT on telegram_id is even checked.
            if _telegram_error_contains(e, "duplicate key") and "users_pkey" in str(e).lower():
                try:
                    # Fallback: fetch the existing user by telegram_id
                    existing = self.execute_query("SELECT id FROM users WHERE telegram_id = %s", (telegram_id,), fetch="one")
                    if existing:
                        logger.warning(f"add_user: recovered from pkey sequence desync for telegram_id={telegram_id}")
                        return existing[0]
                except Exception:
                    pass
            logger.error(f"Error adding user: {e}")
            return None
    
    def get_user(self, telegram_id, username=None):
        """Получение пользователя"""
        try:
            # Используем execute_query для безопасного выполнения
            url = urlparse.urlparse(DATABASE_URL)
            scheme = url.scheme
            
            if "postgres" in scheme:
                query = "SELECT * FROM users WHERE telegram_id = %s"
                user = self.execute_query(query, (telegram_id,), fetch="one")
                if user:
                    result = {
                        "telegram_id": user["telegram_id"],
                        "username": user["username"],
                        "fissure": user["fissure"],
                        "last_fissure": user["last_fissure"],
                        "last_message_id": user["last_message_id"],
                        "total_growth": user.get("total_growth", 0),
                        "total_rolls": user.get("total_rolls", 0),
                        "best_streak": user.get("best_streak", 0),
                        "current_streak": user.get("current_streak", 0),
                        "steam_id": user.get("steam_id"),
                        "steam_nickname": user.get("steam_nickname"),
                        "mmr": user.get("mmr", 0),
                        "rank_tier": user.get("rank_tier", 0),
                        "dota_total_games": user.get("dota_total_games", 0),
                        "dota_wins": user.get("dota_wins", 0),
                        "week_games": user.get("week_games", 0),
                        "week_wins": user.get("week_wins", 0),
                        "week_best_streak": user.get("week_best_streak", 0),
                        "week_current_streak": user.get("week_current_streak", 0),
                        "week_updated_at": user.get("week_updated_at"),
                        "mmr_updated_at": user.get("mmr_updated_at"),
                        "analytics_cache": user.get("analytics_cache"),
                        "analytics_updated_at": user.get("analytics_updated_at"),
                        "last_dota_games": user.get("last_dota_games", 0),
                        "last_dota_wins": user.get("last_dota_wins", 0),
                        "week_start_date": user.get("week_start_date"),
                        "message_count": user.get("message_count", 0),
                        "weekly_mvp_count": user.get("weekly_mvp_count", 0),
                        "weekly_top2_count": user.get("weekly_top2_count", 0),
                        "weekly_top3_count": user.get("weekly_top3_count", 0),
                    }
                    # Обновляем username если передан не-None и отличается
                    if username is not None and username != result.get('username'):
                        self.execute_query("UPDATE users SET username = %s WHERE telegram_id = %s", (username, telegram_id))
                        result['username'] = username
                        user_cache.set(telegram_id, result)
                        logger.info(f"get_user: updated username for {telegram_id} to '{username}'")
                    return result
                else:
                    if username:
                        self.add_user(telegram_id, username, None, None)
                        return {"telegram_id": telegram_id, "username": username, "fissure": 0.1, "last_fissure": 0, "last_message_id": 0, "total_growth": 0, "total_rolls": 0, "best_streak": 0, "current_streak": 0, "steam_id": None, "steam_nickname": None, "mmr": 0, "rank_tier": 0, "dota_total_games": 0, "dota_wins": 0, "week_games": 0, "week_wins": 0, "week_best_streak": 0, "week_current_streak": 0, "week_updated_at": None, "mmr_updated_at": None, "message_count": 0}
                    else:
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
                        result = dict(zip(columns, user_row))
                        # Update username if provided and different
                        if username is not None and username != result.get('username'):
                            cursor.execute("UPDATE users SET username = ? WHERE telegram_id = ?", (username, telegram_id))
                            conn.commit()
                            result['username'] = username
                            user_cache.set(telegram_id, result)
                            logger.info(f"get_user: updated username for {telegram_id} to '{username}'")
                        cursor.close()
                        return result
                    else:
                        cursor.close()
                        if username:
                            self.add_user(telegram_id, username, None, None)
                            logger.warning(f"DB.get_user: created new user {telegram_id} in DB")
                            return {
                                "telegram_id": telegram_id,
                                "username": username,
                                "fissure": 0.1,
                                "last_fissure": 0,
                                "last_message_id": 0,
                                "total_growth": 0,
                                "total_rolls": 0,
                                "best_streak": 0,
                                "current_streak": 0,
                                "steam_id": None,
                                "steam_nickname": None,
                                "mmr": 0,
                                "rank_tier": 0,
                                "dota_total_games": 0,
                                "dota_wins": 0,
                                "week_games": 0,
                                "week_wins": 0,
                                "week_best_streak": 0,
                                "week_current_streak": 0,
                                "week_updated_at": None,
                                "mmr_updated_at": None,
                                "analytics_cache": None,
                                "analytics_updated_at": None,
                                "message_count": 0
                            }
                        else:
                            logger.warning(f"DB.get_user: user {telegram_id} not found")
                            return None
                finally:
                    release_connection(conn)
        except Exception as e:
            logger.error(f"Error getting user: {e}")
            return None
    
    def update_fissure(self, telegram_id, fissure, last_fissure, growth=0):
        """Обновление данных пользователя"""
        try:
            # Используем execute_query для безопасного выполнения
            url = urlparse.urlparse(DATABASE_URL)
            scheme = url.scheme
            win = 1 if growth > 0 else 0
            lose = 1 if growth < 0 else 0
            
            weekly_inc = max(0.0, float(growth))
            if "postgres" in scheme:
                query = """
                    UPDATE users SET fissure=%s, last_fissure=%s, 
                    total_growth = total_growth + %s,
                    total_rolls = total_rolls + 1,
                    weekly_rolls = weekly_rolls + 1,
                    weekly_growth = weekly_growth + %s,
                    last_activity = CURRENT_TIMESTAMP,
                    current_win_streak = CASE WHEN %s = 1 THEN current_win_streak + 1 ELSE 0 END,
                    current_lose_streak = CASE WHEN %s = 1 THEN current_lose_streak + 1 ELSE 0 END,
                    current_streak = CASE WHEN %s = 1 THEN current_win_streak + 1 ELSE 0 END,
                    best_streak = GREATEST(best_streak, CASE WHEN %s = 1 THEN current_win_streak + 1 ELSE 0 END),
                    best_lose_streak = GREATEST(best_lose_streak, CASE WHEN %s = 1 THEN current_lose_streak + 1 ELSE 0 END)
                    WHERE telegram_id=%s
                """
                self.execute_query(query, (fissure, last_fissure, growth, weekly_inc, win, lose, win, win, lose, telegram_id))
            else:
                query = """
                    UPDATE users SET fissure=?, last_fissure=?, 
                    total_growth = total_growth + ?,
                    total_rolls = total_rolls + 1,
                    weekly_rolls = weekly_rolls + 1,
                    weekly_growth = weekly_growth + ?,
                    last_activity = CURRENT_TIMESTAMP,
                    current_win_streak = CASE WHEN ? = 1 THEN current_win_streak + 1 ELSE 0 END,
                    current_lose_streak = CASE WHEN ? = 1 THEN current_lose_streak + 1 ELSE 0 END,
                    current_streak = CASE WHEN ? = 1 THEN current_win_streak + 1 ELSE 0 END,
                    best_streak = MAX(best_streak, CASE WHEN ? = 1 THEN current_win_streak + 1 ELSE 0 END),
                    best_lose_streak = MAX(best_lose_streak, CASE WHEN ? = 1 THEN current_lose_streak + 1 ELSE 0 END)
                    WHERE telegram_id=?
                """
                self.execute_query(query, (fissure, last_fissure, growth, weekly_inc, win, lose, win, win, lose, telegram_id))
        except Exception as e:
            logger.error(f"Error updating fissure: {e}")

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
                query = "SELECT telegram_id, username, steam_nickname, first_name, fissure, avatar FROM users WHERE (in_chat = TRUE OR in_chat IS NULL) ORDER BY fissure DESC NULLS LAST LIMIT %s"
                users = self.execute_query(query, (limit,), fetch="all")
                return [{"telegram_id": u["telegram_id"], "username": u["username"], "steam_nickname": u["steam_nickname"], "first_name": u["first_name"], "fissure": u["fissure"], "avatar": u.get("avatar")} for u in users]
            else:
                query = "SELECT telegram_id, username, steam_nickname, first_name, fissure, avatar FROM users ORDER BY fissure DESC LIMIT ?"
                users = self.execute_query(query, (limit,), fetch="all")
                return [{"telegram_id": u[0], "username": u[1], "steam_nickname": u[2], "first_name": u[3], "fissure": u[4], "avatar": u[5]} for u in users]
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
                    SELECT COUNT(*) + 1 FROM users WHERE mmr > (
                        SELECT mmr FROM users WHERE telegram_id = ? LIMIT 1
                    ) AND steam_id IS NOT NULL
                """
                result = self.execute_query(query, (telegram_id,), fetch="one")
                # Если пользователь первый (нет тех, у кого больше MMR), возвращаем 1
                if result and result[0] is not None:
                    rank = int(result[0])
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
                    WHERE in_chat = TRUE 
                    AND fissure > COALESCE(
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
                    SELECT COUNT(*) + 1 FROM users 
                    WHERE (in_chat = 1 OR in_chat IS NULL)
                    AND fissure > COALESCE(
                        (SELECT fissure FROM users WHERE telegram_id = ? LIMIT 1), -1)
                """
                result = self.execute_query(query, (telegram_id,), fetch="one")
                logger.info(f"get_fissure_rank result: {result}, type={type(result)}")
                if result and result[0] is not None:
                    rank = int(result[0])
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
            # Если значение None — удаляем ключ вместо сохранения строки "None"
            if value is None:
                url = urlparse.urlparse(DATABASE_URL)
                scheme = url.scheme
                if "postgres" in str(scheme) if scheme is not None else "":
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
                    SELECT telegram_id, username, steam_nickname, fissure, digest_position, digest_fissure, current_streak, total_growth
                    FROM users
                    WHERE in_chat = TRUE
                """
                rows = self.execute_query(query, fetch="all")
                users = []
                for r in rows:
                    users.append({
                        "telegram_id": r["telegram_id"],
                        "username": r["username"],
                        "steam_nickname": r["steam_nickname"],
                        "fissure": float(r["fissure"] or 0.0),
                        "digest_position": int(r["digest_position"] or 0),
                        "digest_fissure": float(r["digest_fissure"] or 0.0),
                        "current_streak": int(r["current_streak"] or 0),
                        "total_growth": float(r["total_growth"] or 0.0),
                    })
            else:
                query = """
                    SELECT telegram_id, username, steam_nickname, fissure, digest_position, digest_fissure, current_streak, total_growth
                    FROM users
                    WHERE in_chat = 1 OR in_chat IS NULL
                """
                rows = self.execute_query(query, fetch="all")
                users = []
                for r in rows:
                    users.append({
                        "telegram_id": r[0],
                        "username": r[1],
                        "steam_nickname": r[2],
                        "fissure": float(r[3] or 0.0),
                        "digest_position": int(r[4] or 0),
                        "digest_fissure": float(r[5] or 0.0),
                        "current_streak": int(r[6] or 0),
                        "total_growth": float(r[7] or 0.0),
                    })

# Рост: самый большой прирост см за сутки (current - digest)
            top_growth_user = None
            top_growth_cm = 0.0
            top_growth_id = None
            for u in users:
                prev_f = u["digest_fissure"]
                cur_f = u["fissure"]
                telegram_id = u.get("telegram_id")
                if prev_f is not None and telegram_id:
                    delta = cur_f - prev_f
                    if delta > top_growth_cm:
                        top_growth_cm = delta
                        cached = user_cache.get(telegram_id)
                        if cached:
                            nick = cached.get('steam_nickname') or cached.get('username') or str(telegram_id)
                            top_growth_user = nick if nick and nick != "None" else None
                        else:
                            nick = u.get("steam_nickname") or u.get("username") or str(telegram_id)
                            top_growth_user = nick if nick and nick != "None" else None
                        if not top_growth_user:
                            top_growth_user = str(telegram_id)
                        top_growth_id = telegram_id

            # Падение: насколько см уменьшилась фиссура за сутки (current - digest)
            top_drop_user = None
            top_drop_cm = 0.0
            top_drop_id = None
            for u in users:
                prev_f = u["digest_fissure"]
                cur_f = u["fissure"]
                telegram_id = u.get("telegram_id")
                if prev_f is not None and telegram_id:
                    delta = cur_f - prev_f
                    if delta < top_drop_cm:
                        top_drop_cm = delta
                        cached = user_cache.get(telegram_id)
                        if cached:
                            nick = cached.get('steam_nickname') or cached.get('username') or str(telegram_id)
                            top_drop_user = nick if nick and nick != "None" else None
                        else:
                            nick = u.get("steam_nickname") or u.get("username") or str(telegram_id)
                            top_drop_user = nick if nick and nick != "None" else None
                        if not top_drop_user:
                            top_drop_user = str(telegram_id)
                        top_drop_id = telegram_id

            # Стрик: текущая серия побед (current_streak)
            top_streak_user = None
            top_streak = 0
            top_streak_id = None
            for u in users:
                telegram_id = u.get("telegram_id")
                if telegram_id and u["current_streak"] > top_streak:
                    top_streak = u["current_streak"]
                    top_streak_id = telegram_id
                    cached = user_cache.get(telegram_id)
                    if cached:
                        nick = cached.get('steam_nickname') or cached.get('username') or str(telegram_id)
                        top_streak_user = nick if nick and nick != "None" else None
                    else:
                        nick = u.get("steam_nickname") or u.get("username") or str(telegram_id)
                        top_streak_user = nick if nick and nick != "None" else None
                        if not top_streak_user:
                            top_streak_user = str(telegram_id)

            def get_user_telegram_username(telegram_id):
                """Получить Telegram username пользователя"""
                cached = user_cache.get(telegram_id)
                if cached:
                    return cached.get('username')
                conn = get_connection()
                cursor = conn.cursor()
                try:
                    url = urlparse.urlparse(DATABASE_URL)
                    if "postgres" in url.scheme:
                        cursor.execute("SELECT username FROM users WHERE telegram_id = %s", (telegram_id,))
                    else:
                        cursor.execute("SELECT username FROM users WHERE telegram_id = ?", (telegram_id,))
                    result = cursor.fetchone()
                    return result[0] if result else None
                finally:
                    cursor.close()
                    release_connection(conn)
            
            streak_username = get_user_telegram_username(top_streak_id) if top_streak_id else None
            
            return {
                "top_growth": (top_growth_user or "None", int(top_growth_cm)),
                "top_drop": (top_drop_user or "None", float(top_drop_cm)),
                "top_streak": (top_streak_user or "None", int(top_streak)),
                "top_growth_id": top_growth_id,
                "top_drop_id": top_drop_id,
                "top_streak_id": top_streak_id,
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
                "streak_username": None
            }
    
    def get_user_position(self, telegram_id):
        """Получить текущую позицию пользователя (динамически, без обновления всех)"""
        try:
            query = "SELECT COUNT(*) + 1 FROM users WHERE fissure > (SELECT fissure FROM users WHERE telegram_id = %s)"
            result = self.execute_query(query, (telegram_id,))
            return result[0][0] if result else 0
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
                query_count = "SELECT COUNT(*) FROM users WHERE created_at >= CURRENT_TIMESTAMP - INTERVAL '7 days'"
                new_players_week = self.execute_query(query_count, fetch="one")
                new_players_week = new_players_week[0] if new_players_week else 0
            else:
                query = """
                    SELECT telegram_id, username, fissure, current_position, weekly_digest_position,
                           weekly_growth, weekly_rolls, created_at
                    FROM users
                    WHERE in_chat = 1 OR in_chat IS NULL
                """
                rows = self.execute_query(query, fetch="all")
                
                # Разный синтаксис для дат в SQLite
                query_count = "SELECT COUNT(*) FROM users WHERE created_at >= datetime('now', '-7 days')"
                new_players_week = self.execute_query(query_count, fetch="one")
                new_players_week = new_players_week[0] if new_players_week else 0

            users = []
            for r in rows:
                users.append({
                    "telegram_id": r[0],
                    "username": r[1],
                    "fissure": float(r[2] or 0.0),
                    "current_position": int(r[3] or 0),
                    "weekly_digest_position": int(r[4] or 0),
                    "weekly_growth": float(r[5] or 0.0),
                    "weekly_rolls": int(r[6] or 0),
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
    """Получить пользователя - сначала из кеша, потом из БД"""
    # Пробуем получить из кеша
    cached_user = user_cache.get(telegram_id)
    if cached_user:
        msg_count = cached_user.get('message_count', 0)
        logger.info(f"get_user: cache hit for {telegram_id}, message_count={msg_count}")
        return cached_user
    
    # Нет в кеше - читаем из БД
    db = Database()
    user = db.get_user(telegram_id, username)
    
    if user:
        msg_count = user.get('message_count', 0)
        logger.info(f"get_user: DB hit for {telegram_id}, message_count={msg_count}, keys={list(user.keys()) if isinstance(user, dict) else 'tuple'}")
        user.setdefault('weekly_mvp_count', 0)
        user.setdefault('weekly_top2_count', 0)
        user.setdefault('weekly_top3_count', 0)
        user.setdefault('analytics_cache', None)
        user.setdefault('analytics_updated_at', None)
        user_cache.set(telegram_id, user)
    else:
        logger.warning(f"get_user: user {telegram_id} NOT found in cache or DB")
    
    return user


def get_user_by_username(username):
    """Найти пользователя по username (без @). Ищет сначала в кеше, потом в БД."""
    username = username.lstrip("@").lower()
    
    # Сначала ищем в кеше
    all_keys = user_cache.get_all_users()
    for uid in all_keys:
        if not isinstance(uid, int):
            continue
        cached_user = user_cache.get(uid)
        if not cached_user or not isinstance(cached_user, dict):
            continue
        cached_name = cached_user.get('username', '')
        if cached_name and cached_name.lower() == username:
            logger.info(f"get_user_by_username: found '{username}' in cache (tid={uid})")
            return get_user(uid)
    
    # Не нашли в кеше — ищем в БД
    conn = None
    try:
        conn = get_connection()
        cursor = conn.cursor()
        url = urlparse.urlparse(DATABASE_URL)
        scheme = url.scheme
        if "postgres" in scheme:
            cursor.execute("SELECT telegram_id, username FROM users WHERE LOWER(username) = %s LIMIT 1", (username,))
        else:
            cursor.execute("SELECT telegram_id, username FROM users WHERE LOWER(username) = ? LIMIT 1", (username,))
        result = cursor.fetchone()
        logger.info(f"get_user_by_username: DB query for '{username}' returned: {result}")
        cursor.close()
        conn.commit() if "postgres" in scheme else None
        if result:
            tid = result[0] if not isinstance(result, dict) else result.get('telegram_id')
            logger.info(f"get_user_by_username: found '{username}' in DB (tid={tid})")
            return get_user(tid)
    except Exception as e:
        logger.error(f"get_user_by_username error: {e}")
    finally:
        if conn is not None:
            release_connection(conn)
    
    logger.info(f"get_user_by_username: '{username}' not found in cache or DB")
    return None


def get_user_by_steam_id(steam_id: int):
    """Найти пользователя по steam_id. Ищет сначала в кеше, потом в БД."""
    if not steam_id:
        return None
    
    # Сначала ищем в кеше
    all_keys = user_cache.get_all_users()
    for uid in all_keys:
        if not isinstance(uid, int):
            continue
        cached_user = user_cache.get(uid)
        if not cached_user or not isinstance(cached_user, dict):
            continue
        cached_steam_id = cached_user.get('steam_id')
        if cached_steam_id == steam_id:
            logger.info(f"get_user_by_steam_id: found {steam_id} in cache (tid={uid})")
            return get_user(uid)
    
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
    logger.info(f"update_fissure called: telegram_id={telegram_id}, fissure={fissure}, last_fissure={last_fissure}, growth={growth}")
    user = get_user(telegram_id)
    
    if user:
        user['fissure'] = fissure
        user['last_fissure'] = last_fissure
        user['total_growth'] = user.get('total_growth', 0) + growth
        user['total_rolls'] = user.get('total_rolls', 0) + 1
        user['weekly_rolls'] = user.get('weekly_rolls', 0) + 1
        user['weekly_growth'] = user.get('weekly_growth', 0) + max(0, growth)
        
        win = 1 if growth > 0 else 0
        lose = 1 if growth < 0 else 0
        
        # Track separate win and lose streaks
        current_win_streak = user.get('current_win_streak', 0) + 1 if win else 0
        current_lose_streak = user.get('current_lose_streak', 0) + 1 if lose else 0
        
        user['current_win_streak'] = current_win_streak
        user['current_lose_streak'] = current_lose_streak
        user['current_streak'] = current_win_streak  # Keep for backward compatibility
        user['best_streak'] = max(user.get('best_streak', 0), current_win_streak)
        user['best_lose_streak'] = max(user.get('best_lose_streak', 0), current_lose_streak)
        
        user_cache.set(telegram_id, user)
        
         # Сразу сохраняем в БД
        db = Database()
        scheme = get_db_type()
        if "postgres" in scheme:
            query = """
                UPDATE users SET fissure=%s, last_fissure=%s, 
                total_growth = total_growth + %s,
                total_rolls = total_rolls + 1,
                weekly_rolls = weekly_rolls + 1,
                weekly_growth = weekly_growth + %s,
                last_activity = CURRENT_TIMESTAMP,
                current_win_streak = CASE WHEN %s = 1 THEN current_win_streak + 1 ELSE 0 END,
                current_lose_streak = CASE WHEN %s = 1 THEN current_lose_streak + 1 ELSE 0 END,
                current_streak = CASE WHEN %s = 1 THEN current_win_streak + 1 ELSE 0 END,
                best_streak = GREATEST(best_streak, CASE WHEN %s = 1 THEN current_win_streak + 1 ELSE 0 END),
                best_lose_streak = GREATEST(best_lose_streak, CASE WHEN %s = 1 THEN current_lose_streak + 1 ELSE 0 END),
                last_message_id = COALESCE(%s, last_message_id)
                WHERE telegram_id=%s
            """
            db.execute_query(query, (fissure, last_fissure, growth, max(0, growth), win, lose, win, win, lose, last_message_id, telegram_id))
        else:
            query = """
                UPDATE users SET fissure=?, last_fissure=?, 
                total_growth = total_growth + ?,
                total_rolls = total_rolls + 1,
                weekly_rolls = weekly_rolls + 1,
                weekly_growth = weekly_growth + ?,
                last_activity = CURRENT_TIMESTAMP,
                current_win_streak = CASE WHEN ? = 1 THEN current_win_streak + 1 ELSE 0 END,
                current_lose_streak = CASE WHEN ? = 1 THEN current_lose_streak + 1 ELSE 0 END,
                current_streak = CASE WHEN ? = 1 THEN current_win_streak + 1 ELSE 0 END,
                best_streak = MAX(best_streak, CASE WHEN ? = 1 THEN current_win_streak + 1 ELSE 0 END),
                best_lose_streak = MAX(best_lose_streak, CASE WHEN ? = 1 THEN current_lose_streak + 1 ELSE 0 END),
                last_message_id = COALESCE(?, last_message_id)
                WHERE telegram_id=?
            """
            db.execute_query(query, (fissure, last_fissure, growth, max(0, growth), win, lose, win, win, lose, last_message_id, telegram_id))
        logger.info(f"update_fissure: запись в БД выполнена для telegram_id={telegram_id}")
        
        # Сбрасываем кеши дайджестов при изменении fissure
        user_cache.set('digest_stats', None)
        # Сбрасываем кеш топа при изменении fissure
        top_cache.clear()
    else:
        # Пользователя нет - создаем нового
        logger.info(f"update_fissure: пользователь не найден, создаём нового для telegram_id={telegram_id}")
        db = Database()
        db.add_user(telegram_id, "", "", "")
        # Теперь пробуем снова
        user = db.get_user(telegram_id)
        if user:
            user['fissure'] = fissure
            user['last_fissure'] = last_fissure
            user['total_growth'] = growth
            user['total_rolls'] = 1
            user['weekly_rolls'] = 1
            user['weekly_growth'] = max(0, growth)
            user['current_streak'] = 1 if growth > 0 else 0
            user['best_streak'] = 1 if growth > 0 else 0
            user_cache.set(telegram_id, user)
            # Сбрасываем кеш топа при создании нового пользователя
            top_cache.clear()


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
        # Сбрасываем кеш топов
        top_cache.clear()
        user_cache.delete('dota_digest_stats')  # Invalidate dota digest cache
        logger.info(f"set_user_in_chat: telegram_id={telegram_id}, in_chat={in_chat}")
    except Exception as e:
        logger.error(f"set_user_in_chat error: {e}")
    finally:
        release_connection(conn)


def delete_user(telegram_id: int):
    """Удалить пользователя из базы данных"""
    conn = None
    try:
        conn = get_connection()
        scheme = get_db_type()
        cursor = conn.cursor()
        if "postgres" in scheme:
            cursor.execute("DELETE FROM users WHERE telegram_id = %s", (telegram_id,))
        else:
            cursor.execute("DELETE FROM users WHERE telegram_id = ?", (telegram_id,))
        conn.commit()
        cursor.close()
        # Сбрасываем кеши
        top_cache.clear()
        user_cache.delete('dota_digest_stats')
        user_cache.delete('digest_stats')
        user_cache.delete('dota_week_top')
        user_cache.delete('weekly_digest_stats')
        user_cache.delete(telegram_id)  # Remove specific user from cache
        logger.info(f"delete_user: telegram_id={telegram_id}")
        return True
    except Exception as e:
        logger.error(f"delete_user error: {e}")
        return False
    finally:
        release_connection(conn)


def cleanup_left_users():
    """Удалить всех пользователей с in_chat = FALSE (кто вышел из чата)"""
    conn = None
    try:
        conn = get_connection()
        cursor = conn.cursor()
        scheme = get_db_type()
        if "postgres" in scheme:
            cursor.execute("DELETE FROM users WHERE in_chat = FALSE")
        else:
            cursor.execute("DELETE FROM users WHERE in_chat = 0")
        deleted = cursor.rowcount
        conn.commit()
        cursor.close()
        # Clear all caches after bulk delete
        top_cache.clear()
        user_cache.delete('dota_digest_stats')
        user_cache.delete('digest_stats')
        user_cache.delete('dota_week_top')
        user_cache.delete('weekly_digest_stats')
        logger.info(f"cleanup_left_users: deleted {deleted} users who left chat")
        return deleted
    except Exception as e:
        logger.error(f"cleanup_left_users error: {e}")
        return 0
    finally:
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

def update_last_message_id(telegram_id, message_id):
    """Функция для совместимости - использует новый класс Database"""
    db = Database()
    db.update_last_message_id(telegram_id, message_id)

def update_user_field(telegram_id, field, value):
    """Обновление любого поля пользователя - пишем в кеш и сразу в БД"""
    # Validate telegram_id is not SteamID64
    if not isinstance(telegram_id, int) or telegram_id > 76561190000000000:
        logger.warning(f"update_user_field: invalid telegram_id={telegram_id}, skipping")
        return False
    
    user = get_user(telegram_id)
    
    if user:
        user[field] = value
        user_cache.set(telegram_id, user)
        user_cache.mark_dirty(telegram_id)
        
        # Важные поля — сразу в БД
        immediate_fields = {
            'steam_id', 'steam_nickname', 'mmr', 'rank_tier', 'wins', 'losses',
            'week_games', 'week_wins', 'week_best_streak', 'week_current_streak', 'week_start_date',
            'weekly_mvp_count', 'weekly_top2_count', 'weekly_top3_count',
        }
        if field in immediate_fields:
            _save_user_to_db_immediately(telegram_id, user)
        
        # Сбрасываем кеши дайджестов при изменении данных пользователя
        user_cache.set('digest_stats', None)
        user_cache.set('weekly_digest_stats', None)
        user_cache.set('dota_digest_stats', None)
        # Сбрасываем кеш топа при изменении данных пользователей
        top_cache.clear()
        
        return True
    return False


def update_user_fields_batch(telegram_id: int, fields: dict, save_to_db: bool = True, update_top_cache: bool = True):
    """Массовое обновление полей - обновление кеша + опционально БД.
    update_top_cache=False allows the caller (MMR job) to do exactly one rebuild after the full loop.
    """
    # Validate telegram_id is not SteamID64
    if not isinstance(telegram_id, int) or telegram_id > 76561190000000000:
        logger.warning(f"update_user_fields_batch: invalid telegram_id={telegram_id}, skipping")
        return False
    
    user = get_user(telegram_id)
    if not user:
        return False
    
    # Обновляем все поля в кеше
    for field, value in fields.items():
        user[field] = value
    
    user_cache.set(telegram_id, user)
    user_cache.mark_dirty(telegram_id)
    
    # Сохраняем в БД только если нужно (по умолчанию да)
    if save_to_db:
        _save_user_to_db_immediately(telegram_id, user)
    
    # Обновляем кеш топа MMR только если caller разрешил (MMR job делает это один раз после всего цикла)
    dota_fields = ['mmr', 'rank_tier', 'week_games', 'week_wins', 'week_best_streak', 'steam_nickname', 'steam_id']
    if update_top_cache and any(f in dota_fields for f in fields):
        update_dota_week_top_cache()
    
    # Сбрасываем кеш топа недели при новом steam_id
    if 'steam_id' in fields and fields['steam_id']:
        user_cache.delete('dota_week_top')
        user_cache.delete('dota_week_top_ts')
    
    # Сбрасываем кеши дайджестов
    user_cache.set('digest_stats', None)
    user_cache.set('weekly_digest_stats', None)
    user_cache.set('dota_digest_stats', None)
    top_cache.clear()
    
    return True


def _save_user_to_db_immediately(telegram_id, user_data):
    """Сохранение пользователя в БД сразу (для важных полей)"""
    try:
        db = Database()
        scheme = get_db_type()
        if "postgres" in scheme:
            placeholders = "%s"
        else:
            placeholders = "?"
        query = f"""
            UPDATE users SET 
                steam_id = {placeholders}, steam_nickname = {placeholders}, avatar = {placeholders}, mmr = {placeholders}, rank_tier = {placeholders},
                week_games = {placeholders}, week_wins = {placeholders}, 
                week_best_streak = {placeholders}, week_current_streak = {placeholders}, dota_total_games = {placeholders},
                dota_wins = {placeholders}, last_dota_games = {placeholders}, last_dota_wins = {placeholders},
                wins = {placeholders}, losses = {placeholders}, week_start_date = {placeholders},
                mmr_last_updated = {placeholders},
                message_count = {placeholders},
                weekly_mvp_count = {placeholders}, weekly_top2_count = {placeholders}, weekly_top3_count = {placeholders}
            WHERE telegram_id = {placeholders}
        """
        params = (
            user_data.get('steam_id'),
            user_data.get('steam_nickname'),
            user_data.get('avatar'),
            user_data.get('mmr', 0),
            user_data.get('rank_tier', 0),
            user_data.get('week_games', 0),
            user_data.get('week_wins', 0),
            user_data.get('week_best_streak', 0),
            user_data.get('week_current_streak', 0),
            user_data.get('dota_total_games', 0),
            user_data.get('dota_wins', 0),
            user_data.get('last_dota_games', 0),
            user_data.get('last_dota_wins', 0),
            user_data.get('wins', 0),
            user_data.get('losses', 0),
            user_data.get('week_start_date'),
            user_data.get('mmr_last_updated'),
            user_data.get('message_count', 0),
            user_data.get('weekly_mvp_count', 0),
            user_data.get('weekly_top2_count', 0),
            user_data.get('weekly_top3_count', 0),
            telegram_id
        )
        db.execute_query(query, params)
    except Exception as e:
        logger.error(f"Error saving user {telegram_id} to DB immediately: {e}", exc_info=True)


def decrease_inactive_fissure(days_inactive=1, decrease_amount=1.0):
    """Уменьшить fissure для неактивных игроков (вызывается ежедневно)"""
    db = Database()
    result = db.decrease_inactive_fissure(days_inactive, decrease_amount)
    # Сбрасываем кеш топа при изменении fissure
    if result > 0:
        top_cache.clear()
    return result

def zeus_strike(percent=0.03):
    """Удар Зевса: уменьшить fissure ВСЕХ игроков на percent (батчевая версия)."""
    db = Database()
    scheme = get_db_type()
    
    logger.info(f"zeus_strike (batched): percent={percent}")
    
    try:
        if "postgres" in scheme:
            query = """
                UPDATE users 
                SET fissure = GREATEST(0.1, fissure * (1 - %s))
                WHERE fissure > 0.1
            """
            affected = db.execute_query(query, (percent,))
        else:
            query = """
                UPDATE users 
                SET fissure = MAX(0.1, fissure * (1 - ?))
                WHERE fissure > 0.1
            """
            affected = db.execute_query(query, (percent,))
        
        # Очищаем кеши
        user_cache.clear()
        top_cache.clear()
        
        return affected or 0
        
    except Exception as e:
        logger.error(f"zeus_strike error: {e}")
        return 0

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
        top_cache.clear()
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
        user_cache.set('digest_stats', None)
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
                    mmr = COALESCE(%s, mmr),
                    steam_nickname = COALESCE(%s, steam_nickname),
                    rank_tier = COALESCE(%s, rank_tier),
                    week_games = COALESCE(%s, week_games),
                    week_wins = COALESCE(%s, week_wins),
                    week_best_streak = COALESCE(%s, week_best_streak),
                    week_current_streak = COALESCE(%s, week_current_streak),
                    week_start_date = COALESCE(%s, week_start_date)
                WHERE telegram_id = %s
            """
        else:
            query = """
                UPDATE users SET 
                    mmr = COALESCE(?, mmr),
                    steam_nickname = COALESCE(?, steam_nickname),
                    rank_tier = COALESCE(?, rank_tier),
                    week_games = COALESCE(?, week_games),
                    week_wins = COALESCE(?, week_wins),
                    week_best_streak = COALESCE(?, week_best_streak),
                    week_current_streak = COALESCE(?, week_current_streak),
                    week_start_date = COALESCE(?, week_start_date)
                WHERE telegram_id = ?
            """
        
        rows = []
        for u in users_data:
            rows.append((
                u.get("mmr"), u.get("steam_nickname"), u.get("rank_tier"),
                u.get("week_games"), u.get("week_wins"), u.get("week_best_streak"),
                u.get("week_current_streak"), u.get("week_start_date"),
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
                user_cache.set(u["telegram_id"], cached)
        
        top_cache.clear()
        logger.info(f"batch_save_mmr: saved {len(users_data)} users in one transaction")
    except Exception as e:
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
                result["top_growth"] = tuple(json.loads(last))
                result["top_growth_id"] = json.loads(last)[2] if len(json.loads(last)) > 2 else None
            except:
                pass
    else:
        set_config('last_top_growth', json.dumps(result["top_growth"] + (result["top_growth_id"],)))

    if result["top_drop"][0] == "None":
        last = get_config('last_top_drop')
        if last:
            try:
                result["top_drop"] = tuple(json.loads(last))
                result["top_drop_id"] = json.loads(last)[2] if len(json.loads(last)) > 2 else None
            except:
                pass
    else:
        set_config('last_top_drop', json.dumps(result["top_drop"] + (result["top_drop_id"],)))

    if result["top_streak"][0] == "None":
        last = get_config('last_top_streak')
        if last:
            try:
                result["top_streak"] = tuple(json.loads(last))
                result["top_streak_id"] = json.loads(last)[2] if len(json.loads(last)) > 2 else None
            except:
                pass
    else:
        set_config('last_top_streak', json.dumps(result["top_streak"] + (result["top_streak_id"],)))

    user_cache.set('digest_stats', result)
    return result


def update_player_positions():
    """Обновить позиции игроков"""
    db = Database()
    result = db.update_player_positions()
    # Сбрасываем кеш топа при обновлении позиций
    top_cache.clear()
    return result



def update_digest_snapshot():
    """Обновить снимок для дайджеста"""
    db = Database()
    result = db.update_digest_snapshot()
    # Сбрасываем кеш дайджеста
    user_cache.set('digest_stats', None)
    # Сбрасываем кеш топа при обновлении снимка
    top_cache.clear()
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
    user_cache.set('weekly_digest_stats', None)
    # Сбрасываем кеш топа при обновлении снимка
    top_cache.clear()
    return result

def get_dota_mmr_top(limit=10):
    """Получение топа игроков Dota 2 по MMR с кешем"""
    from main import get_config, set_config

    # Попытка загрузить из кеша config
    cached = get_config('mmr_top_cache')
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
                            THEN ROUND((week_wins::numeric / week_games::numeric) * 100, 1)
                            ELSE 0 END as winrate
                    FROM users
                    WHERE steam_id IS NOT NULL
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
                "rank_tier": u[8], "wins": u[9], "losses": u[10], "week_current_streak": u[11],
            "avatar": u[12], "fissure": float(u[13]) if u[13] else 0.0} for u in users]

                if result:
                    try:
                        set_config('mmr_top_cache', json.dumps(result))
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
                               THEN ROUND(week_wins * 100.0 / week_games, 1)
                               ELSE 0 END as winrate
                 FROM users
                 WHERE steam_id IS NOT NULL
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
                        "rank_tier": u[8], "wins": u[9], "losses": u[10], "week_current_streak": u[11],
                "avatar": u[12], "fissure": float(u[13]) if u[13] else 0.0} for u in users]

                if result:
                    try:
                        set_config('mmr_top_cache', json.dumps(result))
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
                
                week_games = user.get('week_games', 0)
                # Пропускаем пользователей без игр за неделю
                if week_games == 0:
                    continue
                
                week_wins = user.get('week_wins', 0)
                winrate = round((week_wins / week_games * 100), 1) if week_games > 0 else 0
                
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
            
            user_cache.set('dota_week_top', top_users)
            user_cache.set('dota_week_top_ts', current_time)
            
            def get_sort_key(x):
                g = x.get('week_games', 0)
                w = x.get('week_wins', 0)
                l = g - w  # losses
                if g == 0:
                    return (3, 0, 0)
                score = w - l  # победы - поражения
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
    
    # Простой кеш в памяти
    if not hasattr(get_dota_week_top_from_db, '_cache'):
        get_dota_week_top_from_db._cache = (None, 0)
    
    cached_data, cached_time = get_dota_week_top_from_db._cache
    if cached_data and (time.time() - cached_time) < _TTL and not force_refresh:
        logger.info(f"get_dota_week_top_from_db: returning cached top ({len(cached_data)} users)")
        return cached_data[:limit]
    
    result = _get_dota_week_top_query(limit)
    
    # Сохраняем в кеш
    get_dota_week_top_from_db._cache = (result, time.time())
    
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
        cursor.execute("""
            SELECT COUNT(*) FROM users
            WHERE steam_id IS NOT NULL
        """)
        total_with_steam = cursor.fetchone()[0]
        logger.info(f"get_dota_week_top: {total_with_steam} users with steam_id")
        
        # Если есть пользователи с steam_id, выполняем запрос
        if total_with_steam > 0:
            # Формула сортировки: score = 2 * week_wins - week_games (победы - поражения)
            # Игроки без игр за неделю (week_games = 0) идут в конец
            if "postgres" in scheme:
                cursor.execute("""
                    WITH wr_calc AS (
                        SELECT telegram_id, username, steam_nickname, mmr, 
                               week_games, week_wins, rank_tier, steam_id, avatar,
                               CASE WHEN week_games > 0 
                                    THEN ROUND((week_wins::numeric / week_games::numeric) * 100, 1) 
                                    ELSE 0 END as winrate,
                               COALESCE(week_current_streak, 0) as week_current_streak
                        FROM users
                        WHERE steam_id IS NOT NULL
                    )
                    SELECT telegram_id, username, steam_nickname, mmr, 
                           week_games, week_wins, rank_tier, steam_id, avatar,
                           winrate, week_current_streak
                    FROM wr_calc
                    ORDER BY 
                        CASE WHEN week_games = 0 THEN 1 ELSE 0 END,
                        (2 * week_wins - week_games) DESC,
                        week_games DESC,
                        mmr DESC
                    LIMIT %s
                """, (limit,))
            users = cursor.fetchall()
            logger.info(f"get_dota_week_top: postgres users={users}")
            cursor.close()
            result = []
            for u in users:
                result.append({
                    'telegram_id': u[0],
                    'username': u[1],
                    'steam_nickname': u[2],
                    'mmr': u[3],
                    'week_games': u[4],
                    'week_wins': u[5],
                    'rank_tier': u[6],
                    'steam_id': u[7],
                    'avatar': u[8],
                    'winrate': u[9],
                    'week_current_streak': u[10] if len(u) > 10 else 0
                })
            
            logger.info(f"get_dota_week_top: returning {len(result)} users")
            for r in result:
                logger.info(f"  - {r['steam_nickname']}: {r['week_wins']}W / {r['week_games']}G")
            
            release_connection(conn)
            return result
        else:
            # Формула сортировки: score = 2 * week_wins - week_games
            cursor.execute("""
                WITH wr_calc AS (
                    SELECT telegram_id, username, steam_nickname, mmr, 
                           week_games, week_wins, rank_tier, steam_id, avatar,
                           CASE WHEN week_games > 0 
                                THEN ROUND(week_wins * 100.0 / week_games, 1) 
                                ELSE 0 END as winrate,
                          COALESCE(week_current_streak, 0) as week_current_streak
                    FROM users
                    WHERE steam_id IS NOT NULL
                )
                SELECT telegram_id, username, steam_nickname, mmr, 
                       week_games, week_wins, rank_tier, steam_id, avatar,
                       winrate, week_current_streak
                FROM wr_calc
                ORDER BY 
                    CASE WHEN week_games = 0 THEN 1 ELSE 0 END,
                    (2 * week_wins - week_games) DESC,
                    week_games DESC,
                    mmr DESC
                LIMIT ?
            """, (limit,))
            users = cursor.fetchall()
            logger.info(f"get_dota_week_top: sqlite users={users}")
            cursor.close()
            result = []
            for u in users:
                result.append({
                    'telegram_id': u[0],
                    'username': u[1],
                    'steam_nickname': u[2],
                    'mmr': u[3],
                    'week_games': u[4],
                    'week_wins': u[5],
                    'rank_tier': u[6],
                    'steam_id': u[7],
                    'avatar': u[8],
                    'winrate': u[9],
                    'week_current_streak': u[10] if len(u) > 10 else 0
                })
            
            logger.info(f"get_dota_week_top: returning {len(result)} users")
            for r in result:
                logger.info(f"  - {r['steam_nickname']}: {r['week_wins']}W / {r['week_games']}G")
            
            release_connection(conn)
            # Сохраняем в кеш
            get_dota_week_top_from_db._cache = (result, time.time())
            
            return result
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
            # SQLite: используем подзапросы (новая формула)
            # score = WR * sqrt(games) * multiplier (1.2 if >60%, 0.7 if 50-60%, 0.5 if <50%)
            cursor.execute("""
                SELECT 
                    (SELECT steam_nickname FROM users WHERE steam_id IS NOT NULL AND week_games > 0 AND in_chat = 1
                     ORDER BY CAST(ROUND(week_wins * 100.0 / week_games, -1) / 10 * 10 AS INTEGER) DESC,
                          (week_wins * 1.0 / week_games) * SQRT(week_games) DESC LIMIT 1) as top_nickname,
                    (SELECT rank_tier FROM users WHERE steam_id IS NOT NULL AND week_games > 0 AND in_chat = 1
                     ORDER BY CASE 
                        WHEN week_wins * 1.0 / week_games > 0.6 THEN week_wins * 1.0 / week_games * SQRT(week_games) * 1.2
                        WHEN week_wins * 1.0 / week_games >= 0.5 THEN week_wins * 1.0 / week_games * SQRT(week_games) * 0.7
                        ELSE week_wins * 1.0 / week_games * SQRT(week_games) * 0.5
                     END DESC LIMIT 1) as top_rank,
                    (SELECT week_games FROM users WHERE steam_id IS NOT NULL AND week_games > 0 AND in_chat = 1
                     ORDER BY CASE 
                        WHEN week_wins * 1.0 / week_games > 0.6 THEN week_wins * 1.0 / week_games * SQRT(week_games) * 1.2
                        WHEN week_wins * 1.0 / week_games >= 0.5 THEN week_wins * 1.0 / week_games * SQRT(week_games) * 0.7
                        ELSE week_wins * 1.0 / week_games * SQRT(week_games) * 0.5
                     END DESC LIMIT 1) as top_games,
                    (SELECT week_wins FROM users WHERE steam_id IS NOT NULL AND week_games > 0 AND in_chat = 1
                     ORDER BY CASE 
                        WHEN week_wins * 1.0 / week_games > 0.6 THEN week_wins * 1.0 / week_games * SQRT(week_games) * 1.2
                        WHEN week_wins * 1.0 / week_games >= 0.5 THEN week_wins * 1.0 / week_games * SQRT(week_games) * 0.7
                        ELSE week_wins * 1.0 / week_games * SQRT(week_games) * 0.5
                     END DESC LIMIT 1) as top_wins,
                    (SELECT telegram_id FROM users WHERE steam_id IS NOT NULL AND week_games > 0 AND in_chat = 1
                     ORDER BY CASE 
                        WHEN week_wins * 1.0 / week_games > 0.6 THEN week_wins * 1.0 / week_games * SQRT(week_games) * 1.2
                        WHEN week_wins * 1.0 / week_games >= 0.5 THEN week_wins * 1.0 / week_games * SQRT(week_games) * 0.7
                        ELSE week_wins * 1.0 / week_games * SQRT(week_games) * 0.5
                     END DESC LIMIT 1) as top_id,
                    (SELECT steam_nickname FROM users WHERE steam_id IS NOT NULL AND week_games > 0 AND in_chat = 1
                     ORDER BY CASE 
                        WHEN week_wins * 1.0 / week_games > 0.6 THEN week_wins * 1.0 / week_games * SQRT(week_games) * 1.2
                        WHEN week_wins * 1.0 / week_games >= 0.5 THEN week_wins * 1.0 / week_games * SQRT(week_games) * 0.7
                        ELSE week_wins * 1.0 / week_games * SQRT(week_games) * 0.5
                     END ASC LIMIT 1) as bottom_nickname,
                    (SELECT rank_tier FROM users WHERE steam_id IS NOT NULL AND week_games > 0 AND in_chat = 1
                     ORDER BY CASE 
                        WHEN week_wins * 1.0 / week_games > 0.6 THEN week_wins * 1.0 / week_games * SQRT(week_games) * 1.2
                        WHEN week_wins * 1.0 / week_games >= 0.5 THEN week_wins * 1.0 / week_games * SQRT(week_games) * 0.7
                        ELSE week_wins * 1.0 / week_games * SQRT(week_games) * 0.5
                     END ASC LIMIT 1) as bottom_rank,
                    (SELECT week_games FROM users WHERE steam_id IS NOT NULL AND week_games > 0 AND in_chat = 1
                     ORDER BY CASE 
                        WHEN week_wins * 1.0 / week_games > 0.6 THEN week_wins * 1.0 / week_games * SQRT(week_games) * 1.2
                        WHEN week_wins * 1.0 / week_games >= 0.5 THEN week_wins * 1.0 / week_games * SQRT(week_games) * 0.7
                        ELSE week_wins * 1.0 / week_games * SQRT(week_games) * 0.5
                     END ASC LIMIT 1) as bottom_games,
                    (SELECT week_wins FROM users WHERE steam_id IS NOT NULL AND week_games > 0 AND in_chat = 1
                     ORDER BY CASE 
                        WHEN week_wins * 1.0 / week_games > 0.6 THEN week_wins * 1.0 / week_games * SQRT(week_games) * 1.2
                        WHEN week_wins * 1.0 / week_games >= 0.5 THEN week_wins * 1.0 / week_games * SQRT(week_games) * 0.7
                        ELSE week_wins * 1.0 / week_games * SQRT(week_games) * 0.5
                     END ASC LIMIT 1) as bottom_wins,
                    (SELECT telegram_id FROM users WHERE steam_id IS NOT NULL AND week_games > 0 AND in_chat = 1
                     ORDER BY CASE 
                        WHEN week_wins * 1.0 / week_games > 0.6 THEN week_wins * 1.0 / week_games * SQRT(week_games) * 1.2
                        WHEN week_wins * 1.0 / week_games >= 0.5 THEN week_wins * 1.0 / week_games * SQRT(week_games) * 0.7
                        ELSE week_wins * 1.0 / week_games * SQRT(week_games) * 0.5
                     END ASC LIMIT 1) as bottom_id,
                    (SELECT steam_nickname FROM users WHERE steam_id IS NOT NULL AND week_current_streak > 0 AND in_chat = 1 ORDER BY week_current_streak DESC LIMIT 1) as streak_nickname,
                    (SELECT week_current_streak FROM users WHERE steam_id IS NOT NULL AND week_current_streak > 0 AND in_chat = 1 ORDER BY week_current_streak DESC LIMIT 1) as streak_val,
                    (SELECT telegram_id FROM users WHERE steam_id IS NOT NULL AND week_current_streak > 0 AND in_chat = 1 ORDER BY week_current_streak DESC LIMIT 1) as streak_id
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


def get_all_users_from_db():
    """Получение всех пользователей из БД (полные данные)"""
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
                       message_count
                FROM users WHERE steam_id IS NOT NULL
            """)
            users = cursor.fetchall()
            cursor.close()
            return [{
                "telegram_id": u[0], "username": u[1], "fissure": u[2], "last_fissure": u[3],
                "last_message_id": u[4], "total_growth": u[5], "total_rolls": u[6],
                "best_streak": u[7], "current_streak": u[8], "steam_id": u[9],
                "steam_nickname": u[10], "mmr": u[11], "rank_tier": u[12],
                "dota_total_games": u[13], "dota_wins": u[14], "week_games": u[15],
                "week_wins": u[16], "week_best_streak": u[17], "week_current_streak": u[18], "last_dota_games": u[19],
                "last_dota_wins": u[20], "message_count": u[21] if len(u) > 21 else 0
            } for u in users]
    except Exception as e:
        logger.error(f"Error get_all_users_from_db: {e}")
        return []
    finally:
        release_connection(conn)


def reset_weekly_stats():
    """Сброс недельной статистики для всех пользователей (вызывается по понедельникам)"""
    from datetime import datetime as dt, timezone, timedelta
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


def get_all_users():
    """Получение всех пользователей (для загрузки в кеш при старте)"""
    conn = None
    try:
        conn = get_connection()
        url = urlparse.urlparse(DATABASE_URL)
        scheme = url.scheme
        cursor = conn.cursor()
        
        logger.info(f"get_all_users: connecting to {scheme} database")
        
        if "postgres" in scheme:
            cursor.execute("""
                SELECT telegram_id, username, fissure, last_fissure, last_message_id, 
                       total_growth, total_rolls, best_streak, current_streak,
                       steam_id, steam_nickname, mmr, rank_tier, dota_total_games, dota_wins,
                       week_games, week_wins, week_best_streak, week_current_streak, last_dota_games, last_dota_wins,
                       message_count
                FROM users
            """)
            users = cursor.fetchall()
            cursor.close()
            return [{
                "telegram_id": u[0], "username": u[1], "fissure": u[2], "last_fissure": u[3],
                "last_message_id": u[4], "total_growth": u[5], "total_rolls": u[6],
                "best_streak": u[7], "current_streak": u[8], "steam_id": u[9],
                "steam_nickname": u[10], "mmr": u[11], "rank_tier": u[12],
                "dota_total_games": u[13], "dota_wins": u[14], "week_games": u[15],
                "week_wins": u[16], "week_best_streak": u[17], "week_current_streak": u[18], "last_dota_games": u[19],
                "last_dota_wins": u[20], "message_count": u[21] if len(u) > 21 else 0
            } for u in users]
        else:
            cursor.execute("""
                SELECT telegram_id, username, fissure, last_fissure, last_message_id, 
                       total_growth, total_rolls, best_streak, current_streak,
                       steam_id, steam_nickname, mmr, rank_tier, dota_total_games, dota_wins,
                       week_games, week_wins, week_best_streak, week_current_streak, last_dota_games, last_dota_wins,
                       message_count
                FROM users
            """)
            users = cursor.fetchall()
            cursor.close()
            return [{
                "telegram_id": u[0], "username": u[1], "fissure": u[2], "last_fissure": u[3],
                "last_message_id": u[4], "total_growth": u[5], "total_rolls": u[6],
                "best_streak": u[7], "current_streak": u[8], "steam_id": u[9],
                "steam_nickname": u[10], "mmr": u[11], "rank_tier": u[12],
                "dota_total_games": u[13], "dota_wins": u[14], "week_games": u[15],
                "week_wins": u[16], "week_best_streak": u[17], "week_current_streak": u[18], "last_dota_games": u[19],
                "last_dota_wins": u[20], "message_count": u[21] if len(u) > 21 else 0
            } for u in users]
    except Exception as e:
        logger.error(f"Error get_all_users: {e}")
        return []
    finally:
        if conn is not None:
            release_connection(conn)


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
                 WHERE steam_id IS NOT NULL AND in_chat = TRUE
            """)
            users = cursor.fetchall()
            cursor.close()
            return [{
                "telegram_id": u[0], "username": u[1], "fissure": u[2], "last_fissure": u[3],
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
                 WHERE steam_id IS NOT NULL AND (in_chat = 1 OR in_chat IS NULL)
            """)
            users = cursor.fetchall()
            cursor.close()
            return [{
                "telegram_id": u[0], "username": u[1], "fissure": u[2], "last_fissure": u[3],
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
