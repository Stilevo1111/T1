import os
import sqlite3
import psycopg2
import time
import psycopg2.extras
import logging
import urllib.parse as urlparse
import threading
from contextlib import contextmanager
from datetime import datetime

# Configure logging for database operations
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Force redeploy to clear any cached bytecode
REDEPLOY_MARKER = "2026-04-08-21-05-00-final-fix"

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    print("⚠️ DATABASE_URL не задан! Используем SQLite для локального тестирования.")
    DATABASE_URL = "sqlite:///fissure_bot.db"
    print(f"💡 Используется: {DATABASE_URL}")
else:
    print(f"Using DATABASE_URL: {DATABASE_URL[:20]}...")


class UserCache:
    """Кеш данных пользователей в памяти с записью в БД раз в сутки"""
    
    def __init__(self):
        self._cache = {}  # telegram_id -> user_data
        self._dirty = {}  # telegram_id -> True
        self._lock = threading.Lock()
    
    def get(self, telegram_id):
        """Получить данные пользователя из кеша"""
        with self._lock:
            return self._cache.get(telegram_id)
    
    def set(self, telegram_id, data):
        """Установить данные пользователя в кеш"""
        with self._lock:
            self._cache[telegram_id] = data
    
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
            if key in self._cache:
                del self._cache[key]


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


# Глобальные экземпляры кешей
config_cache = TTLCache(default_ttl=300)  # 5 минут для конфигурации
top_cache = TTLCache(default_ttl=60)  # 1 минута для топов и рангов


def flush_users_cache():
    """Сброс всех изменённых пользователей в БД"""
    dirty_users = user_cache.get_all_dirty()
    if not dirty_users:
        logger.info("flush_users_cache: no dirty users")
        return 0
    
    # Обновляем кеш топа перед сбросом
    update_dota_week_top_cache()
    
    db = Database()
    flushed = 0
    
    for telegram_id in dirty_users:
        user_data = user_cache.get(telegram_id)
        if not user_data:
            continue
        
        try:
            # Используем batch update для всех полей
            query = """
                UPDATE users SET 
                    username = %s,
                    fissure = %s,
                    last_fissure = %s,
                    total_growth = %s,
                    total_rolls = %s,
                    current_streak = %s,
                    best_streak = %s,
                    weekly_rolls = %s,
                    weekly_growth = %s,
                    steam_id = %s,
                    steam_nickname = %s,
                    mmr = %s,
                    rank_tier = %s,
                    dota_total_games = %s,
                    dota_wins = %s,
                    last_dota_games = %s,
                    last_dota_wins = %s,
                    week_games = %s,
                    week_wins = %s,
                    week_best_streak = %s,
                    week_start_date = %s,
                    last_activity = CURRENT_TIMESTAMP
                WHERE telegram_id = %s
            """
            db.execute_query(query, (
                user_data.get('username'),
                user_data.get('fissure', 0),
                user_data.get('last_fissure', 0),
                user_data.get('total_growth', 0),
                user_data.get('total_rolls', 0),
                user_data.get('current_streak', 0),
                user_data.get('best_streak', 0),
                user_data.get('weekly_rolls', 0),
                user_data.get('weekly_growth', 0),
                user_data.get('steam_id'),
                user_data.get('steam_nickname'),
                user_data.get('mmr', 0),
                user_data.get('rank_tier', 0),
                user_data.get('dota_total_games', 0),
                user_data.get('dota_wins', 0),
                user_data.get('last_dota_games', 0),
                user_data.get('last_dota_wins', 0),
                user_data.get('week_games', 0),
                user_data.get('week_wins', 0),
                user_data.get('week_best_streak', 0),
                user_data.get('week_start_date'),
                telegram_id
            ))
            user_cache.clear_dirty(telegram_id)
            flushed += 1
        except Exception as e:
            logger.error(f"flush_users_cache: error for {telegram_id}: {e}")
    
    logger.info(f"flush_users_cache: flushed {flushed} users")
    return flushed


def update_dota_week_top_cache():
    """Обновление кеша топа MMR из данных пользователей"""
    all_users = user_cache.get_all_users()
    
    # Если в кеше нет пользователей - загружаем из БД
    if not all_users:
        logger.info("update_dota_week_top_cache: no users in cache, loading from DB")
        try:
            from database import get_all_users_with_steam
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
    
    # Сортировка: сначала те у кого есть игры, потом по целому WR%, потом WR×√игр
    import math
    def calc_score(user):
        g = user.get('week_games', 0)
        w = user.get('week_wins', 0)
        if g == 0:
            return (0, 0)
        wr = w / g
        wr_int = int(wr * 100)  # целый винрейт
        wr_score = wr * math.sqrt(g)  # WR × √игр
        return (wr_int, wr_score)
    
    def get_sort_key(x):
        g = x.get('week_games', 0)
        w = x.get('week_wins', 0)
        if g == 0:
            return (1, 0, 0)
        wr = w / g
        # Группировка по 10% диапазонам (80-89%, 70-79%, 60-69% и т.д.)
        wr_group = (int(wr * 100) // 10) * 10  # простой: 83%→80, 75%→70, 55%→50
        wr_score = wr * math.sqrt(g)
        return (0, wr_group, wr_score)
    
    top_users.sort(key=lambda x: get_sort_key(x))
    
    # Сохраняем в кеш
    user_cache.set('dota_week_top', top_users)
    logger.info(f"update_dota_week_top_cache: cached {len(top_users)} users")


# Connection pool management
_connection_pool = {}
_pool_lock = threading.Lock()
def get_db_type():
    """Получить тип базы данных"""
    if DATABASE_URL is None:
        return "sqlite"
    url = urlparse.urlparse(DATABASE_URL)
    scheme = url.scheme
    # Явно преобразуем scheme в строку для избежания проблем с типами
    if scheme is None:
        return "sqlite"
    scheme_str = str(scheme)
    return "postgresql" if "postgres" in scheme_str else "sqlite"

def get_connection():
    """Получение соединения с базой данных с пулом"""
    db_type = get_db_type()
    print(f"[DB] Getting connection, type: {db_type}")
    
    with _pool_lock:
        # Проверяем активное соединение в пуле
        if db_type in _connection_pool:
            conn = _connection_pool[db_type]
            try:
                # Проверяем соединение
                cursor = conn.cursor()
                cursor.execute("SELECT 1")
                cursor.close()
                print(f"[DB] Reusing existing connection")
                return conn
            except Exception as e:
                print(f"[DB] Existing connection failed: {e}")
                # Соединение неактивно, удаляем из пула
                try:
                    conn.close()
                except:
                    pass
                del _connection_pool[db_type]
        
        # Создаем новое соединение
        print(f"[DB] Creating new connection for {db_type}")
        if db_type == "postgresql":
            try:
                url = urlparse.urlparse(DATABASE_URL)
                dbname = url.path[1:] if url.path else ""
                user = url.username
                password = url.password
                host = url.hostname
                port = url.port
                
                conn = psycopg2.connect(
                    dbname=dbname,
                    user=user,
                    password=password,
                    host=host,
                    port=port,
                    sslmode='require',
                    connect_timeout=10
                )
                print("✅ Подключено к PostgreSQL")
            except Exception as e:
                print(f"❌ PostgreSQL connection failed: {e}")
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
            print("✅ Подключено к SQLite")
        
        # Сохраняем в пул
        _connection_pool[db_type] = conn
        return conn

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
        # Соединение остается в пуле, не закрываем его
        pass

def init_db():
    """Initialize database tables and add missing columns."""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        url = urlparse.urlparse(DATABASE_URL)
        scheme = url.scheme
        
        if "postgres" in scheme:
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
                ALTER TABLE users ADD COLUMN IF NOT EXISTS week_updated_at TIMESTAMP
            """)
            cursor.execute("""
                ALTER TABLE users ADD COLUMN IF NOT EXISTS mmr_updated_at TIMESTAMP
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
                    digest_fissure REAL DEFAULT 0.0
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
            
            # Создаём индексы для часто используемых полей (улучшение производительности)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_fissure ON users(fissure DESC)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_mmr ON users(mmr DESC)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_steam_id ON users(steam_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_week_games ON users(week_games DESC)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_current_position ON users(current_position)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_rank_tier ON users(rank_tier DESC)")
        
        # Создаём таблицу для настроек бота (чат для дайджестов)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS bot_config (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        
        conn.commit()
        conn.close()
        logger.info("✅ База данных инициализирована")
    except Exception as e:
        logger.error(f"❌ Ошибка инициализации БД: {e}")

def migrate_db():
    """Run database migrations using Alembic"""
    try:
        import subprocess
        import sys
        
        # Check if alembic.ini exists
        alembic_ini_path = os.path.join(os.path.dirname(__file__), 'alembic.ini')
        if not os.path.exists(alembic_ini_path):
            logger.info("ℹ️ Alembic не настроен, пропускаем миграции")
            return True
        
        # Run alembic upgrade head
        result = subprocess.run([
            sys.executable, '-m', 'alembic', 'upgrade', 'head'
        ], capture_output=True, text=True, cwd=os.path.dirname(__file__))
        
        if result.returncode == 0:
            logger.info("✅ Миграции базы данных выполнены успешно")
            return True
        else:
            logger.error(f"❌ Ошибка выполнения миграций: {result.stderr}")
            return False
    except Exception as e:
        logger.error(f"❌ Ошибка запуска миграций: {e}")
        return False

class Database:
    """Класс для работы с базой данных с улучшенным управлением соединениями"""
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(Database, cls).__new__(cls)
            cls._instance.conn = None
        return cls._instance
    
    def __init__(self):
        # Singleton - инициализация только один раз
        pass
    
    def connect(self):
        """Устанавливаем соединение с проверкой активности"""
        if not self.conn:
            self.conn = get_connection()
        else:
            # Проверяем, что соединение всё ещё активно
            try:
                cursor = self.conn.cursor()
                cursor.execute("SELECT 1")
                cursor.close()
            except:
                # Соединение мертво, создаём новое
                self.conn = get_connection()
        return self.conn
    
    def execute_query(self, query, params=None, fetch=None):
        """Унифицированный метод выполнения запросов"""
        try:
            conn = self.connect()
            url = urlparse.urlparse(DATABASE_URL)
            scheme = url.scheme
            
            if get_db_type() == "postgresql":
                # Для PostgreSQL используем RealDictCursor для доступа по ключу
                cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            else:
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
                result = None
            
            conn.commit()
            cursor.close()
            return result
        except Exception as e:
            logger.error(f"Database query failed: {e}")
            return None
    
    def add_user(self, user_id, username, first_name, last_name):
        """Добавление/обновление пользователя"""
        try:
            # Используем execute_query для безопасного выполнения
            url = urlparse.urlparse(DATABASE_URL)
            scheme = url.scheme
            
            if "postgres" in scheme:
                query = '''
                    INSERT INTO users (telegram_id, username, fissure, last_fissure, last_message_id, total_growth, total_rolls, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                    ON CONFLICT (telegram_id) 
                    DO UPDATE SET 
                        username = EXCLUDED.username,
                        fissure = EXCLUDED.fissure,
                        last_fissure = EXCLUDED.last_fissure,
                        last_message_id = EXCLUDED.last_message_id,
                        total_growth = EXCLUDED.total_growth,
                        total_rolls = EXCLUDED.total_rolls
                    RETURNING id
                '''
                result = self.execute_query(query, (user_id, username, 0.1, 0, 0, 0, 0), fetch="one")
                return result[0] if result else user_id
            else:
                query = '''
                    INSERT INTO users (telegram_id, username, fissure, last_fissure, last_message_id, total_growth, total_rolls, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
                    ON CONFLICT(telegram_id) DO UPDATE SET
                        username = excluded.username,
                        fissure = excluded.fissure,
                        last_fissure = excluded.last_fissure,
                        last_message_id = excluded.last_message_id,
                        total_growth = excluded.total_growth,
                        total_rolls = excluded.total_rolls
                '''
                self.execute_query(query, (user_id, username, 0.1, 0, 0, 0, 0))
                return None
        except Exception as e:
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
                    return {
                        "telegram_id": user["telegram_id"],
                        "username": user["username"],
                        "fissure": user["fissure"],
                        "last_fissure": user["last_fissure"],
                        "last_message_id": user["last_message_id"],
                        "total_growth": user.get("total_growth", 0),
                        "total_rolls": user.get("total_rolls", 0),
                        "best_streak": user.get("best_streak", 0),
                        "current_streak": user.get("current_streak", 0),
                        # Dota 2 поля
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
                        "last_dota_games": user.get("last_dota_games", 0),
                        "last_dota_wins": user.get("last_dota_wins", 0),
                        "week_start_date": user.get("week_start_date")
                    }
                else:
                    self.add_user(telegram_id, username, None, None)
                    return {"telegram_id": telegram_id, "username": username, "fissure": 0.1, "last_fissure": 0, "last_message_id": 0, "total_growth": 0, "total_rolls": 0, "best_streak": 0, "current_streak": 0, "steam_id": None, "steam_nickname": None, "mmr": 0, "dota_total_games": 0, "dota_wins": 0, "week_games": 0, "week_wins": 0, "week_best_streak": 0, "week_current_streak": 0, "week_updated_at": None, "mmr_updated_at": None}
            else:
                query = "SELECT * FROM users WHERE telegram_id = ?"
                user = self.execute_query(query, (telegram_id,), fetch="one")
                if user:
                    return {
                        "telegram_id": user[1],
                        "username": user[2],
                        "fissure": user[3],
                        "last_fissure": user[4],
                        "last_message_id": user[5] if len(user) > 5 else 0,
                        "total_growth": user[6] if len(user) > 6 else 0,
                        "total_rolls": user[7] if len(user) > 7 else 0,
                        "best_streak": user[10] if len(user) > 10 else 0,
                        "current_streak": user[9] if len(user) > 9 else 0,
                        # Dota 2 поля
                        "steam_id": user[20] if len(user) > 20 else None,
                        "steam_nickname": user[21] if len(user) > 21 else None,
                        "mmr": user[22] if len(user) > 22 else 0,
                        "rank_tier": user[32] if len(user) > 32 else 0,
                        "dota_total_games": user[23] if len(user) > 23 else 0,
                        "dota_wins": user[24] if len(user) > 24 else 0,
                        "week_games": user[25] if len(user) > 25 else 0,
                        "week_wins": user[26] if len(user) > 26 else 0,
                        "week_best_streak": user[29] if len(user) > 29 else 0,
                        "week_current_streak": user[30] if len(user) > 30 else 0,
                        "week_updated_at": user[27] if len(user) > 27 else None,
                        "mmr_updated_at": user[28] if len(user) > 28 else None
                    }
                else:
                    self.add_user(telegram_id, username, None, None)
                    return {"telegram_id": telegram_id, "username": username, "fissure": 0.1, "last_fissure": 0, "last_message_id": 0, "total_growth": 0, "total_rolls": 0, "best_streak": 0, "current_streak": 0, "steam_id": None, "steam_nickname": None, "mmr": 0, "rank_tier": 0, "dota_total_games": 0, "dota_wins": 0, "week_games": 0, "week_wins": 0, "week_best_streak": 0, "week_current_streak": 0, "week_updated_at": None, "mmr_updated_at": None}
        except Exception as e:
            logger.error(f"Error getting user: {e}")
            return {"telegram_id": telegram_id, "username": username, "fissure": 0.1, "last_fissure": 0, "last_message_id": 0, "total_growth": 0, "total_rolls": 0, "best_streak": 0, "current_streak": 0, "week_current_streak": 0}
    
    def update_fissure(self, telegram_id, fissure, last_fissure, growth=0):
        """Обновление данных пользователя"""
        try:
            # Используем execute_query для безопасного выполнения
            url = urlparse.urlparse(DATABASE_URL)
            scheme = url.scheme
            win = 1 if growth > 0 else 0
            
            weekly_inc = max(0.0, float(growth))
            if "postgres" in scheme:
                query = """
                    UPDATE users SET fissure=%s, last_fissure=%s, 
                    total_growth = total_growth + %s,
                    total_rolls = total_rolls + 1,
                    weekly_rolls = weekly_rolls + 1,
                    weekly_growth = weekly_growth + %s,
                    last_activity = CURRENT_TIMESTAMP,
                    current_streak = CASE WHEN %s = 1 THEN current_streak + 1 ELSE 0 END,
                    best_streak = GREATEST(best_streak, CASE WHEN %s = 1 THEN current_streak + 1 ELSE 0 END)
                    WHERE telegram_id=%s
                """
                self.execute_query(query, (fissure, last_fissure, growth, weekly_inc, win, win, telegram_id))
            else:
                query = """
                    UPDATE users SET fissure=?, last_fissure=?, 
                    total_growth = total_growth + ?,
                    total_rolls = total_rolls + 1,
                    weekly_rolls = weekly_rolls + 1,
                    weekly_growth = weekly_growth + ?,
                    last_activity = CURRENT_TIMESTAMP,
                    current_streak = CASE WHEN ? = 1 THEN current_streak + 1 ELSE 0 END,
                    best_streak = MAX(best_streak, CASE WHEN ? = 1 THEN current_streak + 1 ELSE 0 END)
                    WHERE telegram_id=?
                """
                self.execute_query(query, (fissure, last_fissure, growth, weekly_inc, win, win, telegram_id))
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
            # Используем execute_query для безопасного выполнения
            url = urlparse.urlparse(DATABASE_URL)
            scheme = url.scheme
            
            if get_db_type() == "postgresql":
                query = "SELECT telegram_id, username, fissure FROM users WHERE in_chat = TRUE ORDER BY fissure DESC LIMIT %s"
                users = self.execute_query(query, (limit,), fetch="all")
                return [{"telegram_id": u["telegram_id"], "username": u["username"], "fissure": u["fissure"]} for u in users]
            else:
                query = "SELECT telegram_id, username, fissure FROM users WHERE in_chat = 1 ORDER BY fissure DESC LIMIT ?"
                users = self.execute_query(query, (limit,), fetch="all")
                return [{"telegram_id": u[0], "username": u[1], "fissure": u[2]} for u in users]
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
                    ) AND steam_id IS NOT NULL AND in_chat = TRUE
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
                    ) AND steam_id IS NOT NULL AND in_chat = 1
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
                    WHERE in_chat = 1 
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
                return result if result is not None else 0
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
                return result if result is not None else 0
        except Exception as e:
            logger.error(f"Error decreasing inactive fissure: {e}")
            return 0
    
    def get_config(self, key, default=None):
        """Получить значение конфигурации"""
        try:
            # Используем execute_query для безопасного выполнения
            url = urlparse.urlparse(DATABASE_URL)
            scheme = url.scheme
            logger.debug(f"get_config: key={key}, scheme={scheme}")
            
            if "postgres" in scheme:
                query = "SELECT value FROM bot_config WHERE key = %s"
                result = self.execute_query(query, (key,), fetch="one")
                logger.debug(f"get_config result: {result}, type={type(result)}")
                if result is None:
                    logger.debug(f"get_config: result is None, returning default={default}")
                    return default
                # PostgreSQL с RealDictCursor возвращает словарь {'value': '...'}
                if isinstance(result, dict):
                    val = result.get('value')
                    logger.debug(f"get_config: dict value = {repr(val)}")
                    # Для alternate_digest_type разрешаем "0" как валидное значение
                    if key == 'alternate_digest_type' and val in ('0', '1'):
                        return val
                    # Проверяем что значение не пустое и не "0"
                    if val is not None and val != '' and val != '0':
                        return val
                    logger.info(f"get_config: empty or zero value, returning default={default}")
                    return default
                # result может быть (value,) или просто value
                if isinstance(result, tuple):
                    val = result[0]
                    if val and str(val) != '0':
                        return val
                    return default
                if result and result != '0':
                    return result
                return default
            else:
                query = "SELECT value FROM bot_config WHERE key = ?"
                result = self.execute_query(query, (key,), fetch="one")
                if result is None:
                    return default
                if isinstance(result, tuple):
                    return result[0] if result[0] else default
                return result if result else default
        except Exception as e:
            logger.error(f"Error getting config: {e}")
            return default
    
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

            # Используем execute_query для безопасного выполнения
            url = urlparse.urlparse(DATABASE_URL)
            scheme = url.scheme
            logger.debug(f"set_config: key={key}, value={value}, scheme={scheme}")
            
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
            
            logger.info(f"set_config completed for key={key}")
            return True
        except Exception as e:
            logger.error(f"Error setting config: {e}")
            return False
    
    def get_digest_stats(self):
        """Получить статистику для дайджеста"""
        try:
            # Используем execute_query для безопасного выполнения
            url = urlparse.urlparse(DATABASE_URL)
            scheme = url.scheme
            
            if get_db_type() == "postgresql":
                query = """
                    SELECT telegram_id, username, fissure, digest_position, digest_fissure, current_streak, total_growth
                    FROM users
                """
                rows = self.execute_query(query, fetch="all")
                users = []
                for r in rows:
                    users.append({
                        "telegram_id": r["telegram_id"],
                        "username": r["username"],
                        "fissure": float(r["fissure"] or 0.0),
                        "digest_position": int(r["digest_position"] or 0),
                        "digest_fissure": float(r["digest_fissure"] or 0.0),
                        "current_streak": int(r["current_streak"] or 0),
                        "total_growth": float(r["total_growth"] or 0.0),
                    })
            else:
                query = """
                    SELECT telegram_id, username, fissure, digest_position, digest_fissure, current_streak, total_growth
                    FROM users
                """
                rows = self.execute_query(query, fetch="all")
                users = []
                for r in rows:
                    users.append({
                        "telegram_id": r[0],
                        "username": r[1],
                        "fissure": float(r[2] or 0.0),
                        "digest_position": int(r[3] or 0),
                        "digest_fissure": float(r[4] or 0.0),
                        "current_streak": int(r[5] or 0),
                        "total_growth": float(r[6] or 0.0),
                    })

            # Текущие позиции по текущей фиссуре
            users_sorted = sorted(users, key=lambda u: u["fissure"], reverse=True)
            current_pos_by_id = {u["telegram_id"]: i + 1 for i, u in enumerate(users_sorted)}

            # Рост: насколько позиций вверх за сутки (digest_position - current_position)
            top_growth_user = None
            top_growth_positions = 0
            top_growth_id = None
            for u in users:
                prev_pos = u["digest_position"]
                cur_pos = current_pos_by_id.get(u["telegram_id"], 0)
                if cur_pos > 0:
                    moved_up = prev_pos - cur_pos if prev_pos > 0 else 0
                    if moved_up > top_growth_positions:
                        top_growth_positions = moved_up
                        cached = user_cache.get(u["telegram_id"])
                        top_growth_user = u["username"] or (cached.get("username") if cached else None) or str(u["telegram_id"])
                        top_growth_id = u["telegram_id"]

            # Падение: насколько см уменьшилась фиссура за сутки (current - digest)
            top_drop_user = None
            top_drop_cm = 0.0
            top_drop_id = None
            for u in users:
                prev_f = u["digest_fissure"]
                cur_f = u["fissure"]
                if prev_f is not None and prev_f > 0:
                    delta = cur_f - prev_f
                    if delta < top_drop_cm:
                        top_drop_cm = delta
                        cached = user_cache.get(u["telegram_id"])
                        top_drop_user = u["username"] or (cached.get("username") if cached else None) or str(u["telegram_id"])
                        top_drop_id = u["telegram_id"]

            # Стрик: текущая серия побед (current_streak)
            top_streak_user = None
            top_streak = 0
            top_streak_id = None
            for u in users:
                if u["current_streak"] > top_streak:
                    top_streak = u["current_streak"]
                    cached = user_cache.get(u["telegram_id"])
                    top_streak_user = u["username"] or (cached.get("username") if cached else None) or str(u["telegram_id"])
                    top_streak_id = u["telegram_id"]

            return {
                "top_growth": (top_growth_user or "None", int(top_growth_positions)),
                "top_drop": (top_drop_user or "None", float(top_drop_cm)),
                "top_streak": (top_streak_user or "None", int(top_streak)),
                "top_growth_id": top_growth_id,
                "top_drop_id": top_drop_id,
                "top_streak_id": top_streak_id,
            }
        except Exception as e:
            logger.error(f"Error getting digest stats: {e}")
            return {"top_growth": ("None", 0), "top_drop": ("None", 0.0), "top_streak": ("None", 0)}
    
    def update_player_positions(self):
        """Обновить текущие позиции игроков (по fissure DESC)"""
        try:
            # Используем execute_query для безопасного выполнения
            if get_db_type() == "postgresql":
                query = """
                    UPDATE users SET current_position = subquery.pos
                    FROM (SELECT telegram_id, ROW_NUMBER() OVER (ORDER BY fissure DESC) as pos FROM users) subquery
                    WHERE users.telegram_id = subquery.telegram_id
                """
                result = self.execute_query(query)
                return result if result is not None else 0
            else:
                # SQLite: используем скалярный подзапрос
                query = """
                    UPDATE users SET current_position = (
                        SELECT COUNT(*) + 1 FROM users u2 WHERE u2.fissure > users.fissure
                    )
                """
                result = self.execute_query(query)
                return result if result is not None else 0
        except Exception as e:
            logger.error(f"Error updating player positions: {e}")
            return 0

    def update_digest_snapshot(self):
        """Обновить 'снимок' (позиция/фиссура) после отправки дайджеста"""
        try:
            # Используем execute_query для безопасного выполнения
            if get_db_type() == "postgresql":
                query = """
                    UPDATE users SET 
                        current_position = subquery.pos,
                        digest_position = subquery.pos,
                        digest_fissure = subquery.fissure
                    FROM (
                        SELECT telegram_id, fissure, 
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
                        digest_position = (
                            SELECT COUNT(*) + 1 FROM users u2 WHERE u2.fissure > users.fissure
                        ),
                        digest_fissure = (
                            SELECT fissure FROM users u2 WHERE u2.telegram_id = users.telegram_id
                        )
                """
                result = self.execute_query(query)
                return result if result is not None else 0
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
        return cached_user
    
    # Нет в кеше - читаем из БД
    db = Database()
    user = db.get_user(telegram_id, username)
    
    # Сохраняем в кеш если пользователь найден
    if user:
        user.setdefault('fissure', 0)
        user.setdefault('last_fissure', 0)
        user.setdefault('total_growth', 0)
        user.setdefault('total_rolls', 0)
        user.setdefault('best_streak', 0)
        user.setdefault('current_streak', 0)
        user.setdefault('steam_id', None)
        user.setdefault('steam_nickname', None)
        user.setdefault('mmr', 0)
        user.setdefault('rank_tier', 0)
        user.setdefault('week_games', 0)
        user.setdefault('week_wins', 0)
        user.setdefault('week_best_streak', 0)
        user.setdefault('week_current_streak', 0)
        user.setdefault('dota_total_games', 0)
        user.setdefault('dota_wins', 0)
        user_cache.set(telegram_id, user)
    
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
        if result:
            tid = result[0] if not isinstance(result, dict) else result.get('telegram_id')
            logger.info(f"get_user_by_username: found '{username}' in DB (tid={tid})")
            return get_user(tid)
    except Exception as e:
        logger.error(f"get_user_by_username error: {e}")
    
    logger.info(f"get_user_by_username: '{username}' not found in cache or DB")
    return None


def update_fissure(telegram_id, fissure, last_fissure, growth=0):
    """Обновление fissure - пишем в кеш и сразу в БД"""
    # Получаем текущие данные пользователя
    user = get_user(telegram_id)
    
    if user:
        # Обновляем данные в кеше
        user['fissure'] = fissure
        user['last_fissure'] = last_fissure
        user['total_growth'] = user.get('total_growth', 0) + growth
        user['total_rolls'] = user.get('total_rolls', 0) + 1
        user['weekly_rolls'] = user.get('weekly_rolls', 0) + 1
        user['weekly_growth'] = user.get('weekly_growth', 0) + max(0, growth)
        
        win = 1 if growth > 0 else 0
        user['current_streak'] = user.get('current_streak', 0) + 1 if win else 0
        user['best_streak'] = max(user.get('best_streak', 0), user['current_streak'])
        
        user_cache.set(telegram_id, user)
        user_cache.mark_dirty(telegram_id)
        
        # Пишем в БД сразу чтобы не потерять при перезапуске
        try:
            conn = get_connection()
            scheme = get_db_type()
            cursor = conn.cursor()
            if scheme == "postgresql":
                cursor.execute("""
                    UPDATE users SET 
                        fissure = %s, last_fissure = %s,
                        total_growth = total_growth + %s,
                        total_rolls = total_rolls + 1,
                        weekly_rolls = weekly_rolls + 1,
                        weekly_growth = weekly_growth + %s,
                        current_streak = CASE WHEN %s = 1 THEN current_streak + 1 ELSE 0 END,
                        best_streak = GREATEST(best_streak, CASE WHEN %s = 1 THEN current_streak + 1 ELSE 0 END),
                        last_activity = CURRENT_TIMESTAMP
                    WHERE telegram_id = %s
                """, (fissure, last_fissure, growth, max(0, growth), win, win, telegram_id))
            else:
                cursor.execute("""
                    UPDATE users SET 
                        fissure = ?, last_fissure = ?,
                        total_growth = total_growth + ?,
                        total_rolls = total_rolls + 1,
                        weekly_rolls = weekly_rolls + 1,
                        weekly_growth = weekly_growth + ?,
                        current_streak = CASE WHEN ? = 1 THEN current_streak + 1 ELSE 0 END,
                        best_streak = MAX(best_streak, CASE WHEN ? = 1 THEN current_streak + 1 ELSE 0 END),
                        last_activity = CURRENT_TIMESTAMP
                    WHERE telegram_id = ?
                """, (fissure, last_fissure, growth, max(0, growth), win, win, telegram_id))
            conn.commit()
            cursor.close()
        except Exception as e:
            logger.error(f"update_fissure: DB write error: {e}")
        
        # Сбрасываем кеши дайджестов при изменении fissure
        user_cache.set('digest_stats', None)
        # Сбрасываем кеш топа при изменении fissure
        top_cache.clear()
    else:
        # Пользователя нет - создаем нового
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
            user_cache.mark_dirty(telegram_id)
            # Сбрасываем кеш топа при создании нового пользователя
            top_cache.clear()


def set_user_in_chat(telegram_id: int, in_chat: bool):
    """Установить статус нахождения пользователя в чате"""
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
        conn.close()
        # Сбрасываем кеш топов
        top_cache.clear()
        user_cache.delete('dota_digest_stats')  # Invalidate dota digest cache
        logger.info(f"set_user_in_chat: telegram_id={telegram_id}, in_chat={in_chat}")
    except Exception as e:
        logger.error(f"set_user_in_chat error: {e}")


def delete_user(telegram_id: int):
    """Удалить пользователя из базы данных"""
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
        conn.close()
        # Сбрасываем кеши
        top_cache.clear()
        user_cache.delete('dota_digest_stats')
        logger.info(f"delete_user: telegram_id={telegram_id}")
        return True
    except Exception as e:
        logger.error(f"delete_user error: {e}")
        return False


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
    
    # Сохраняем в кеш
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
    user = get_user(telegram_id)
    
    if user:
        user[field] = value
        user_cache.set(telegram_id, user)
        user_cache.mark_dirty(telegram_id)
        
        # Поля Steam: записываем сразу в БД
        steam_fields = ['steam_id', 'steam_nickname', 'mmr', 'rank_tier', 
                        'wins', 'losses',
                        'week_games', 'week_wins', 'week_best_streak', 'week_current_streak', 'week_start_date']
        if field in steam_fields:
            _save_user_to_db_immediately(telegram_id, user)
        
        # Сбрасываем кеши дайджестов при изменении данных пользователя
        user_cache.set('digest_stats', None)
        user_cache.set('weekly_digest_stats', None)
        user_cache.set('dota_digest_stats', None)
        # Сбрасываем кеш топа при изменении данных пользователей
        top_cache.clear()
        
        return True
    return False


def update_user_fields_batch(telegram_id: int, fields: dict, save_to_db: bool = True):
    """Массовое обновление полей - обновление кеша + опционально БД"""
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
    
    # Обновляем кеш топа MMR только 1 раз
    dota_fields = ['mmr', 'rank_tier', 'week_games', 'week_wins', 'week_best_streak', 'steam_nickname']
    if any(f in dota_fields for f in fields):
        update_dota_week_top_cache()
    
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
                steam_id = {placeholders}, steam_nickname = {placeholders}, mmr = {placeholders}, rank_tier = {placeholders},
                week_games = {placeholders}, week_wins = {placeholders}, 
                week_best_streak = {placeholders}, week_current_streak = {placeholders}, dota_total_games = {placeholders},
                dota_wins = {placeholders}, last_dota_games = {placeholders}, last_dota_wins = {placeholders},
                wins = {placeholders}, losses = {placeholders}, week_start_date = {placeholders}
            WHERE telegram_id = {placeholders}
        """
        db.execute_query(query, (
            user_data.get('steam_id'),
            user_data.get('steam_nickname'),
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
            telegram_id
        ))
        logger.info(f"Saved user {telegram_id} Dota fields to DB immediately")
    except Exception as e:
        logger.error(f"Error saving user to DB immediately: {e}")

def decrease_inactive_fissure(days_inactive=1, decrease_amount=1.0):
    """Уменьшить fissure для неактивных игроков (вызывается ежедневно)"""
    db = Database()
    result = db.decrease_inactive_fissure(days_inactive, decrease_amount)
    # Сбрасываем кеш топа при изменении fissure
    if result > 0:
        top_cache.clear()
    return result

def zeus_strike(percent=0.05):
    """Удар Зевса: уменьшить fissure ВСЕХ игроков на percent (5% = 0.05). Фиссуры < 5 см защищены."""
    db = Database()
    url = urlparse.urlparse(DATABASE_URL)
    scheme = url.scheme
    multiplier = 1.0 - percent
    
    try:
        if "postgres" in scheme:
            query = "UPDATE users SET fissure = GREATEST(0.1, fissure * %s) WHERE fissure >= 5"
            db.execute_query(query, (multiplier,))
            count_query = "SELECT COUNT(*) FROM users WHERE fissure >= 5"
            result = db.execute_query(count_query, fetch="one")
            affected = result[0] if result else 0
        else:
            query = "UPDATE users SET fissure = MAX(0.1, fissure * ?) WHERE fissure >= 5"
            db.execute_query(query, (multiplier,))
            count_query = "SELECT COUNT(*) FROM users WHERE fissure >= 5"
            result = db.execute_query(count_query, fetch="one")
            affected = result[0] if result else 0
        
        # Обновляем кеш только затронутых пользователей
        all_users = user_cache.get_all_users()
        for uid, udata in all_users.items():
            if isinstance(udata, dict) and udata.get('fissure', 0) >= 5:
                udata['fissure'] = max(0.1, udata['fissure'] * multiplier)
                user_cache.set(uid, udata)
        
        top_cache.clear()
        user_cache.set('digest_stats', None)
        logger.info(f"Zeus strike: {affected} users affected, -{int(percent*100)}% each")
        return affected
    except Exception as e:
        logger.error(f"Zeus strike error: {e}")
        return 0


def batch_save_mmr(users_data: list):
    """
    Batch сохранение MMR данных всех пользователей одним запросом.
    users_data: [{"telegram_id": int, "mmr": int, "steam_nickname": str, ...}, ...]
    """
    if not users_data:
        return
    try:
        db = Database()
        conn = db.connect()
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


def batch_increment_config(key: str, delta: int):
    """Атомарный инкремент значения в bot_config (1 запрос вместо 2)"""
    try:
        db = Database()
        conn = db.connect()
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
    # Сбрасываем кеш конфигурации при изменении
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
    """Получение топа игроков Dota 2 по MMR"""
    try:
        conn = get_connection()
        url = urlparse.urlparse(DATABASE_URL)
        scheme = url.scheme
        
        cursor = conn.cursor()
        
        if "postgres" in scheme:
            cursor.execute("""
                SELECT telegram_id, username, steam_nickname, mmr, 
                       dota_total_games, dota_wins, week_games, week_wins,
                       rank_tier, wins, losses,
CASE WHEN week_games > 0 
                             THEN ROUND((week_wins::numeric / week_games::numeric) * 100, 1) 
                             ELSE 0 END as winrate
                FROM users 
                WHERE steam_id IS NOT NULL AND rank_tier > 0
ORDER BY 
                    CASE WHEN week_games > 0 THEN 0 ELSE 1 END,
                    CAST(week_wins * 100.0 / NULLIF(week_games, 0) AS INTEGER) DESC,
                    (week_wins * 1.0 / NULLIF(week_games, 0)) * SQRT(week_games) DESC,
                    week_games DESC,
                    week_wins DESC, mmr DESC
                LIMIT %s
            """, (limit,))
            users = cursor.fetchall()
            cursor.close()
            return [{"telegram_id": u[0], "username": u[1], "steam_nickname": u[2], 
                    "mmr": u[3], "dota_total_games": u[4], "dota_wins": u[5],
                    "week_games": u[6], "week_wins": u[7],
                    "rank_tier": u[8], "wins": u[9], "losses": u[10]} for u in users]
        else:
            cursor.execute("""
                SELECT telegram_id, username, steam_nickname, mmr, 
                       dota_total_games, dota_wins, week_games, week_wins,
                       rank_tier, wins, losses,
CASE WHEN week_games > 0 
                             THEN ROUND(week_wins * 100.0 / week_games, 1) 
                             ELSE 0 END as winrate
                FROM users 
                WHERE steam_id IS NOT NULL AND rank_tier > 0
                ORDER BY 
                    CASE WHEN week_games > 0 THEN 0 ELSE 1 END,
                    CAST(ROUND(week_wins * 100.0 / NULLIF(week_games, 0), -1) / 10 * 10 AS INTEGER) DESC,
                    (week_wins * 1.0 / NULLIF(week_games, 0)) * SQRT(week_games) DESC,
                    week_games DESC,
                    week_wins DESC, mmr DESC
                LIMIT ?
            """, (limit,))
            users = cursor.fetchall()
            cursor.close()
            return [{"telegram_id": u[0], "username": u[1], "steam_nickname": u[2], 
                    "mmr": u[3], "dota_total_games": u[4], "dota_wins": u[5],
                    "week_games": u[6], "week_wins": u[7],
                    "rank_tier": u[8], "wins": u[9], "losses": u[10]} for u in users]
    except Exception as e:
        logger.error(f"Ошибка get_dota_mmr_top: {e}")
        return []


def get_dota_week_top(limit=10, force_refresh=False):
    """Получение топа игроков Dota 2 за неделю - сначала из кеша, потом из БД"""
    from database import user_cache
    
    # Всегда обновляем кеш при force_refresh или если данных мало
    if force_refresh:
        logger.info("get_dota_week_top: forcing refresh from OpenDota cache")
        # Очищаем кеш пользователей чтобы загрузить свежие данные
        user_cache.delete_key('dota_week_top')
        # Обновляем кеш - он перечитает из OpenDota и применит новую сортировку
        from database import update_dota_week_top_cache
        update_dota_week_top_cache()
        cached_top = user_cache.get('dota_week_top')
        if cached_top:
            return cached_top[:limit]
    
    # Иначе пробуем получить из кеша
    cached_top = user_cache.get('dota_week_top')
    all_users = user_cache.get_all_users()
    
    if cached_top and len(cached_top) > 0 and len(all_users) > 0:
        logger.info(f"get_dota_week_top: returning from cache ({len(cached_top)} users)")
        return cached_top[:limit]
    
    # Кеш пустой - обновляем его из БД
    logger.info("get_dota_week_top: cache empty, refreshing from DB")
    from database import update_dota_week_top_cache
    update_dota_week_top_cache()
    
    # Теперь получаем из кеша
    cached_top = user_cache.get('dota_week_top')
    if cached_top:
        return cached_top[:limit]
    
    # Если всё ещё нет - читаем напрямую
    return get_dota_week_top_from_db(limit)


def get_dota_week_top_from_db(limit=10):
    """Получение топа игроков Dota 2 за неделю напрямую из БД"""
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
        cursor.execute("""
            SELECT COUNT(*) FROM users 
            WHERE steam_id IS NOT NULL AND week_games > 0
        """)
        count = cursor.fetchone()[0]
        logger.info(f"get_dota_week_top: {total_with_steam} users with steam_id, {count} with week_games > 0")
        
        # Если есть пользователи с steam_id, выполняем запрос
        if total_with_steam > 0:
            if "postgres" in scheme:
                cursor.execute("""
                    SELECT telegram_id, username, steam_nickname, mmr, 
                           week_games, week_wins, rank_tier,
                           CASE WHEN week_games > 0 
                                THEN ROUND((week_wins::numeric / week_games::numeric) * 100, 1) 
                                ELSE 0 END as winrate,
                           COALESCE(week_current_streak, 0)
                    FROM users 
                    WHERE steam_id IS NOT NULL AND COALESCE(in_chat, TRUE) = TRUE
ORDER BY 
                    CASE WHEN week_games > 0 THEN 0 ELSE 1 END,
                    CAST(week_wins::numeric * 100 / NULLIF(week_games, 0) AS INTEGER) DESC,
                    (week_wins::numeric / NULLIF(week_games, 0)) * SQRT(week_games::numeric) DESC,
                    week_games DESC,
                    week_wins DESC, mmr DESC
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
                    'winrate': u[7],
                    'week_current_streak': u[8] if len(u) > 8 else 0
                })
            
            logger.info(f"get_dota_week_top: returning {len(result)} users")
            for r in result:
                logger.info(f"  - {r['steam_nickname']}: {r['week_wins']}W / {r['week_games']}G")
            
            return result
        else:
            cursor.execute("""
                SELECT telegram_id, username, steam_nickname, mmr, 
                       week_games, week_wins, rank_tier,
                       CASE WHEN week_games > 0 
                            THEN ROUND(week_wins * 100.0 / week_games, 1) 
                            ELSE 0 END as winrate,
                       COALESCE(week_current_streak, 0)
FROM users 
                WHERE steam_id IS NOT NULL AND COALESCE(in_chat, 1) = 1
ORDER BY 
                    CASE WHEN week_games > 0 THEN 0 ELSE 1 END,
                    CAST(ROUND(week_wins * 100.0 / NULLIF(week_games, 0), -1) / 10 * 10 AS INTEGER) DESC,
                    (week_wins * 1.0 / NULLIF(week_games, 0)) * SQRT(week_games) DESC,
                    week_games DESC,
                    week_wins DESC, mmr DESC
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
                    'winrate': u[7],
                    'week_current_streak': u[8] if len(u) > 8 else 0
                })
            
            logger.info(f"get_dota_week_top: returning {len(result)} users")
            for r in result:
                logger.info(f"  - {r['steam_nickname']}: {r['week_wins']}W / {r['week_games']}G")
            
            return result
    except Exception as e:
        logger.error(f"Ошибка get_dota_week_top: {e}")
        return []


def get_dota_digest_stats():
    """Получение статистики для Dota дайджеста - из кеша"""
    cached = user_cache.get('dota_digest_stats')
    if cached:
        logger.info(f"get_dota_digest_stats: returning from cache: {cached}")
        return cached
    else:
        logger.info("get_dota_digest_stats: cache miss or None, reading from DB")
    
    # Читаем из БД
    try:
        conn = get_connection()
        url = urlparse.urlparse(DATABASE_URL)
        scheme = url.scheme
        
        cursor = conn.cursor()
        
        # Проверяем есть ли пользователи с играми за неделю
        cursor.execute("""
            SELECT COUNT(*) FROM users 
            WHERE steam_id IS NOT NULL AND week_games > 0
        """)
        count = cursor.fetchone()[0]
        
        if count == 0:
            cursor.close()
            conn.close()
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
                    WHERE steam_id IS NOT NULL AND week_games > 0
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
                    (SELECT steam_nickname FROM users WHERE steam_id IS NOT NULL AND week_games > 0 
                     ORDER BY CAST(ROUND(week_wins * 100.0 / week_games, -1) / 10 * 10 AS INTEGER) DESC,
                          (week_wins * 1.0 / week_games) * SQRT(week_games) DESC LIMIT 1) as top_nickname,
                    (SELECT rank_tier FROM users WHERE steam_id IS NOT NULL AND week_games > 0 
                     ORDER BY CASE 
                        WHEN week_wins * 1.0 / week_games > 0.6 THEN week_wins * 1.0 / week_games * SQRT(week_games) * 1.2
                        WHEN week_wins * 1.0 / week_games >= 0.5 THEN week_wins * 1.0 / week_games * SQRT(week_games) * 0.7
                        ELSE week_wins * 1.0 / week_games * SQRT(week_games) * 0.5
                     END DESC LIMIT 1) as top_rank,
                    (SELECT week_games FROM users WHERE steam_id IS NOT NULL AND week_games > 0 
                     ORDER BY CASE 
                        WHEN week_wins * 1.0 / week_games > 0.6 THEN week_wins * 1.0 / week_games * SQRT(week_games) * 1.2
                        WHEN week_wins * 1.0 / week_games >= 0.5 THEN week_wins * 1.0 / week_games * SQRT(week_games) * 0.7
                        ELSE week_wins * 1.0 / week_games * SQRT(week_games) * 0.5
                     END DESC LIMIT 1) as top_games,
                    (SELECT week_wins FROM users WHERE steam_id IS NOT NULL AND week_games > 0 
                     ORDER BY CASE 
                        WHEN week_wins * 1.0 / week_games > 0.6 THEN week_wins * 1.0 / week_games * SQRT(week_games) * 1.2
                        WHEN week_wins * 1.0 / week_games >= 0.5 THEN week_wins * 1.0 / week_games * SQRT(week_games) * 0.7
                        ELSE week_wins * 1.0 / week_games * SQRT(week_games) * 0.5
                     END DESC LIMIT 1) as top_wins,
                    (SELECT telegram_id FROM users WHERE steam_id IS NOT NULL AND week_games > 0 
                     ORDER BY CASE 
                        WHEN week_wins * 1.0 / week_games > 0.6 THEN week_wins * 1.0 / week_games * SQRT(week_games) * 1.2
                        WHEN week_wins * 1.0 / week_games >= 0.5 THEN week_wins * 1.0 / week_games * SQRT(week_games) * 0.7
                        ELSE week_wins * 1.0 / week_games * SQRT(week_games) * 0.5
                     END DESC LIMIT 1) as top_id,
                    (SELECT steam_nickname FROM users WHERE steam_id IS NOT NULL AND week_games > 0 
                     ORDER BY CASE 
                        WHEN week_wins * 1.0 / week_games > 0.6 THEN week_wins * 1.0 / week_games * SQRT(week_games) * 1.2
                        WHEN week_wins * 1.0 / week_games >= 0.5 THEN week_wins * 1.0 / week_games * SQRT(week_games) * 0.7
                        ELSE week_wins * 1.0 / week_games * SQRT(week_games) * 0.5
                     END ASC LIMIT 1) as bottom_nickname,
                    (SELECT rank_tier FROM users WHERE steam_id IS NOT NULL AND week_games > 0 
                     ORDER BY CASE 
                        WHEN week_wins * 1.0 / week_games > 0.6 THEN week_wins * 1.0 / week_games * SQRT(week_games) * 1.2
                        WHEN week_wins * 1.0 / week_games >= 0.5 THEN week_wins * 1.0 / week_games * SQRT(week_games) * 0.7
                        ELSE week_wins * 1.0 / week_games * SQRT(week_games) * 0.5
                     END ASC LIMIT 1) as bottom_rank,
                    (SELECT week_games FROM users WHERE steam_id IS NOT NULL AND week_games > 0 
                     ORDER BY CASE 
                        WHEN week_wins * 1.0 / week_games > 0.6 THEN week_wins * 1.0 / week_games * SQRT(week_games) * 1.2
                        WHEN week_wins * 1.0 / week_games >= 0.5 THEN week_wins * 1.0 / week_games * SQRT(week_games) * 0.7
                        ELSE week_wins * 1.0 / week_games * SQRT(week_games) * 0.5
                     END ASC LIMIT 1) as bottom_games,
                    (SELECT week_wins FROM users WHERE steam_id IS NOT NULL AND week_games > 0 
                     ORDER BY CASE 
                        WHEN week_wins * 1.0 / week_games > 0.6 THEN week_wins * 1.0 / week_games * SQRT(week_games) * 1.2
                        WHEN week_wins * 1.0 / week_games >= 0.5 THEN week_wins * 1.0 / week_games * SQRT(week_games) * 0.7
                        ELSE week_wins * 1.0 / week_games * SQRT(week_games) * 0.5
                     END ASC LIMIT 1) as bottom_wins,
                    (SELECT telegram_id FROM users WHERE steam_id IS NOT NULL AND week_games > 0 
                     ORDER BY CASE 
                        WHEN week_wins * 1.0 / week_games > 0.6 THEN week_wins * 1.0 / week_games * SQRT(week_games) * 1.2
                        WHEN week_wins * 1.0 / week_games >= 0.5 THEN week_wins * 1.0 / week_games * SQRT(week_games) * 0.7
                        ELSE week_wins * 1.0 / week_games * SQRT(week_games) * 0.5
                     END ASC LIMIT 1) as bottom_id,
                    (SELECT steam_nickname FROM users WHERE steam_id IS NOT NULL AND week_current_streak > 0 ORDER BY week_current_streak DESC LIMIT 1) as streak_nickname,
                    (SELECT week_current_streak FROM users WHERE steam_id IS NOT NULL AND week_current_streak > 0 ORDER BY week_current_streak DESC LIMIT 1) as streak_val,
                    (SELECT telegram_id FROM users WHERE steam_id IS NOT NULL AND week_current_streak > 0 ORDER BY week_current_streak DESC LIMIT 1) as streak_id
            """)
            row = cursor.fetchone()
            
            top = (row[0], row[1], row[2], row[3], row[4]) if row and row[0] else None
            bottom = (row[5], row[6], row[7], row[8], row[9]) if row and row[5] else None
            streak = (row[10], row[11], row[12]) if row and row[10] else None
        
        cursor.close()
        conn.close()
        
        # SQL: SELECT steam_nickname, week_wins, week_games, rank_tier, telegram_id
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
        logger.error(f"Ошибка get_dota_digest_stats: {e}")
        return {
            "top_winrate": ("None", 0, 0, 0, None),
            "bottom_winrate": ("None", 0, 0, 0, None),
            "top_streak": ("None", 0, None)
        }


def get_all_users_with_steam():
    """Получение всех пользователей с привязанным Steam (полные данные)"""
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
                       week_games, week_wins, week_best_streak, last_dota_games, last_dota_wins
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
                "week_wins": u[16], "week_best_streak": u[17], "last_dota_games": u[18],
                "last_dota_wins": u[19]
            } for u in users]
        else:
            cursor.execute("""
                SELECT telegram_id, username, fissure, last_fissure, last_message_id, 
                       total_growth, total_rolls, best_streak, current_streak,
                       steam_id, steam_nickname, mmr, rank_tier, dota_total_games, dota_wins,
                       week_games, week_wins, week_best_streak, last_dota_games, last_dota_wins
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
                "week_wins": u[16], "week_best_streak": u[17], "last_dota_games": u[18],
                "last_dota_wins": u[19]
            } for u in users]
    except Exception as e:
        logger.error(f"Ошибка get_all_users_with_steam: {e}")
        return []


def reset_weekly_stats():
    """Сброс недельной статистики для всех пользователей (вызывается по понедельникам)"""
    try:
        conn = get_connection()
        url = urlparse.urlparse(DATABASE_URL)
        scheme = url.scheme
        
        cursor = conn.cursor()
        
        if "postgres" in scheme:
            cursor.execute("""
                UPDATE users SET week_games = 0, week_wins = 0 WHERE steam_id IS NOT NULL
            """)
        else:
            cursor.execute("""
                UPDATE users SET week_games = 0, week_wins = 0 WHERE steam_id IS NOT NULL
            """)
        
        affected = cursor.rowcount
        conn.commit()
        cursor.close()
        logger.info(f"Сброшена недельная статистика для {affected} пользователей")
        return affected
    except Exception as e:
        logger.error(f"Ошибка reset_weekly_stats: {e}")
        return 0


def backup_database(backup_dir=None):
    """Создать резервную копию базы данных"""
    try:
        if backup_dir is None:
            backup_dir = os.path.dirname(os.path.abspath(__file__))
        
        url = urlparse.urlparse(DATABASE_URL)
        scheme = url.scheme
        
        if "postgres" in scheme:
            # Для PostgreSQL используем pg_dump
            import subprocess
            import tempfile
            
            # Создаем имя файла резервной копии
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_file = os.path.join(backup_dir, f"fissure_bot_backup_{timestamp}.sql")
            
            # Формируем команду pg_dump
            cmd = [
                "pg_dump",
                "-h", url.hostname,
                "-p", str(url.port),
                "-U", url.username,
                "-d", url.path[1:],  # Убираем первый символ '/' из пути
                "-f", backup_file,
                "--no-password"
            ]
            
            # Устанавливаем переменную окружения для пароля
            env = os.environ.copy()
            env["PGPASSWORD"] = url.password
            
            # Выполняем команду
            result = subprocess.run(cmd, env=env, capture_output=True, text=True)
            
            if result.returncode == 0:
                logger.info(f"Резервная копия PostgreSQL создана: {backup_file}")
                return backup_file
            else:
                logger.error(f"Ошибка создания резервной копии PostgreSQL: {result.stderr}")
                return None
        else:
            # Для SQLite просто копируем файл
            if DATABASE_URL.startswith("sqlite:///"):
                db_path = DATABASE_URL[10:]  # Убираем "sqlite:///"`
            elif DATABASE_URL.startswith("sqlite://"):
                db_path = DATABASE_URL[9:]   # Убираем "sqlite://"
            else:
                db_path = DATABASE_URL
            
            # Создаем имя файла резервной копии
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_file = os.path.join(backup_dir, f"fissure_bot_backup_{timestamp}.db")
            
            # Копируем файл базы данных
            import shutil
            shutil.copy2(db_path, backup_file)
            
            logger.info(f"Резервная копия SQLite создана: {backup_file}")
            return backup_file
            
    except Exception as e:
        logger.error(f"Ошибка создания резервной копии: {e}")
        return None


def restore_database(backup_file):
    """Восстановить базу данных из резервной копии"""
    try:
        if not os.path.exists(backup_file):
            logger.error(f"Файл резервной копии не существует: {backup_file}")
            return False
        
        url = urlparse.urlparse(DATABASE_URL)
        scheme = url.scheme
        
        if "postgres" in scheme:
            # Для PostgreSQL используем psql
            import subprocess
            
            # Формируем команду psql
            cmd = [
                "psql",
                "-h", url.hostname,
                "-p", str(url.port),
                "-U", url.username,
                "-d", url.path[1:],  # Убираем первый символ '/' из пути
                "-f", backup_file,
                "--no-password"
            ]
            
            # Устанавливаем переменную окружения для пароля
            env = os.environ.copy()
            env["PGPASSWORD"] = url.password
            
            # Выполняем команду
            result = subprocess.run(cmd, env=env, capture_output=True, text=True)
            
            if result.returncode == 0:
                logger.info(f"База данных PostgreSQL восстановлена из: {backup_file}")
                return True
            else:
                logger.error(f"Ошибка восстановления PostgreSQL: {result.stderr}")
                return False
        else:
            # Для SQLite копируем файл обратно
            if DATABASE_URL.startswith("sqlite:///"):
                db_path = DATABASE_URL[10:]  # Убираем "sqlite:///"`
            elif DATABASE_URL.startswith("sqlite://"):
                db_path = DATABASE_URL[9:]   # Убираем "sqlite://"
            else:
                db_path = DATABASE_URL
            
            import shutil
            shutil.copy2(backup_file, db_path)
            
            logger.info(f"База данных SQLite восстановлена из: {backup_file}")
            return True
            
    except Exception as e:
        logger.error(f"Ошибка восстановления базы данных: {e}")
        return False
