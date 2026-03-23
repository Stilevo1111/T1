import os
import sqlite3
import psycopg2
from psycopg2.extras import RealDictCursor
import logging
import urllib.parse as urlparse

# Configure logging for database operations
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    print("⚠️ DATABASE_URL не задан! Используем SQLite для локального тестирования.")
    DATABASE_URL = "sqlite:///fissure_bot.db"
    print(f"💡 Используется: {DATABASE_URL}")
else:
    print(f"Using DATABASE_URL: {DATABASE_URL[:20]}...")

def get_connection():
    """Получение соединения с базой данных"""
    # Определяем тип базы данных по схеме URL
    url = urlparse.urlparse(DATABASE_URL)
    scheme = url.scheme
    
    print(f"DB TYPE: {scheme}")
    
    if "postgres" in scheme:
        try:
            # Парсим URL для PostgreSQL
            dbname = url.path[1:]  # Убираем первый символ '/' из пути
            user = url.username
            password = url.password
            host = url.hostname
            port = url.port
            
            # Создаем соединение с SSL
            conn = psycopg2.connect(
                dbname=dbname,
                user=user,
                password=password,
                host=host,
                port=port,
                sslmode='require'  # Используем 'require' для Render
            )
            print("✅ Подключено к PostgreSQL")
            return conn
        except Exception as e:
            print(f"❌ PostgreSQL connection failed: {e}")
            raise
    else:
        # Для SQLite обрабатываем URL
        if DATABASE_URL.startswith("sqlite:///"):
            db_path = DATABASE_URL[10:]  # Убираем "sqlite:///"`
        elif DATABASE_URL.startswith("sqlite://"):
            db_path = DATABASE_URL[9:]   # Убираем "sqlite://"
        else:
            db_path = DATABASE_URL
            
        print("⚠️  Подключено к SQLite (только для тестирования)")
        return sqlite3.connect(db_path)

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
                ALTER TABLE users ADD COLUMN IF NOT EXISTS week_updated_at TIMESTAMP
            """)
            cursor.execute("""
                ALTER TABLE users ADD COLUMN IF NOT EXISTS mmr_updated_at TIMESTAMP
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
            if 'mmr_updated_at' not in columns:
                cursor.execute("ALTER TABLE users ADD COLUMN mmr_updated_at TIMESTAMP")
        
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
    """Класс для работы с базой данных"""
    
    def __init__(self):
        self.conn = None
    
    def connect(self):
        """Устанавливаем соединение"""
        if not self.conn:
            self.conn = get_connection()
        return self.conn
    
    def add_user(self, user_id, username, first_name, last_name):
        """Добавление/обновление пользователя"""
        conn = self.connect()
        cur = conn.cursor()
        
        # Определяем тип базы данных по схеме URL
        url = urlparse.urlparse(DATABASE_URL)
        scheme = url.scheme
        
        if "postgres" in scheme:
            cur.execute('''
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
            ''', (user_id, username, 0.1, 0, 0, 0, 0))
        else:
            cur.execute('''
                INSERT INTO users (telegram_id, username, fissure, last_fissure, last_message_id, total_growth, total_rolls, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
                ON CONFLICT(telegram_id) DO UPDATE SET
                    username = excluded.username,
                    fissure = excluded.fissure,
                    last_fissure = excluded.last_fissure,
                    last_message_id = excluded.last_message_id,
                    total_growth = excluded.total_growth,
                    total_rolls = excluded.total_rolls
            ''', (user_id, username, 0.1, 0, 0, 0, 0))
        
        conn.commit()
        if DATABASE_URL.startswith("postgresql://"):
            user = cur.fetchone()
            cur.close()
            return user[0] if user else None
        else:
            cur.close()
            return None
    
    def get_user(self, telegram_id, username=None):
        """Получение пользователя"""
        try:
            conn = self.connect()
            # Определяем тип базы данных по схеме URL
            url = urlparse.urlparse(DATABASE_URL)
            scheme = url.scheme
            
            if "postgres" in scheme:
                cursor = conn.cursor(cursor_factory=RealDictCursor)
                cursor.execute("SELECT * FROM users WHERE telegram_id = %s", (telegram_id,))
                user = cursor.fetchone()
                if user:
                    cursor.close()
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
                        "dota_total_games": user.get("dota_total_games", 0),
                        "dota_wins": user.get("dota_wins", 0),
                        "week_games": user.get("week_games", 0),
                        "week_wins": user.get("week_wins", 0),
                        "week_updated_at": user.get("week_updated_at"),
                        "mmr_updated_at": user.get("mmr_updated_at")
                    }
                else:
                    self.add_user(telegram_id, username, None, None)
                    cursor.close()
                    return {"telegram_id": telegram_id, "username": username, "fissure": 0.1, "last_fissure": 0, "last_message_id": 0, "total_growth": 0, "total_rolls": 0, "best_streak": 0, "current_streak": 0, "steam_id": None, "steam_nickname": None, "mmr": 0, "dota_total_games": 0, "dota_wins": 0, "week_games": 0, "week_wins": 0, "week_updated_at": None, "mmr_updated_at": None}
            else:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))
                user = cursor.fetchone()
                if user:
                    cursor.close()
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
                        "dota_total_games": user[23] if len(user) > 23 else 0,
                        "dota_wins": user[24] if len(user) > 24 else 0,
                        "week_games": user[25] if len(user) > 25 else 0,
                        "week_wins": user[26] if len(user) > 26 else 0,
                        "week_updated_at": user[27] if len(user) > 27 else None,
                        "mmr_updated_at": user[28] if len(user) > 28 else None
                    }
                else:
                    self.add_user(telegram_id, username, None, None)
                    cursor.close()
                    return {"telegram_id": telegram_id, "username": username, "fissure": 0.1, "last_fissure": 0, "last_message_id": 0, "total_growth": 0, "total_rolls": 0, "best_streak": 0, "current_streak": 0, "steam_id": None, "steam_nickname": None, "mmr": 0, "dota_total_games": 0, "dota_wins": 0, "week_games": 0, "week_wins": 0, "week_updated_at": None, "mmr_updated_at": None}
        except Exception as e:
            print(f"❌ Ошибка get_user: {e}")
            return {"telegram_id": telegram_id, "username": username, "fissure": 0.1, "last_fissure": 0, "last_message_id": 0, "total_growth": 0, "total_rolls": 0, "best_streak": 0, "current_streak": 0}
    
    def update_fissure(self, telegram_id, fissure, last_fissure, growth=0):
        """Обновление данных пользователя"""
        try:
            conn = self.connect()
            # Определяем тип базы данных по схеме URL
            url = urlparse.urlparse(DATABASE_URL)
            scheme = url.scheme
            win = 1 if growth > 0 else 0
            
            weekly_inc = max(0.0, float(growth))
            if "postgres" in scheme:
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE users SET fissure=%s, last_fissure=%s, 
                    total_growth = total_growth + %s,
                    total_rolls = total_rolls + 1,
                    weekly_rolls = weekly_rolls + 1,
                    weekly_growth = weekly_growth + %s,
                    last_activity = CURRENT_TIMESTAMP,
                    current_streak = CASE WHEN %s = 1 THEN current_streak + 1 ELSE 0 END,
                    best_streak = GREATEST(best_streak, CASE WHEN %s = 1 THEN current_streak + 1 ELSE 0 END)
                    WHERE telegram_id=%s
                """, (fissure, last_fissure, growth, weekly_inc, win, win, telegram_id))
            else:
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE users SET fissure=?, last_fissure=?, 
                    total_growth = total_growth + ?,
                    total_rolls = total_rolls + 1,
                    weekly_rolls = weekly_rolls + 1,
                    weekly_growth = weekly_growth + ?,
                    last_activity = CURRENT_TIMESTAMP,
                    current_streak = CASE WHEN ? = 1 THEN current_streak + 1 ELSE 0 END,
                    best_streak = MAX(best_streak, CASE WHEN ? = 1 THEN current_streak + 1 ELSE 0 END)
                    WHERE telegram_id=?
                """, (fissure, last_fissure, growth, weekly_inc, win, win, telegram_id))
            conn.commit()
            cursor.close()
        except Exception as e:
            print(f"❌ Ошибка update_fissure: {e}")
    
    def update_last_message_id(self, telegram_id, message_id):
        """Обновление ID последнего сообщения пользователя"""
        try:
            conn = self.connect()
            url = urlparse.urlparse(DATABASE_URL)
            scheme = url.scheme
            
            if "postgres" in scheme:
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE users SET last_message_id=%s WHERE telegram_id=%s
                """, (message_id, telegram_id))
            else:
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE users SET last_message_id=? WHERE telegram_id=?
                """, (message_id, telegram_id))
            conn.commit()
            cursor.close()
        except Exception as e:
            print(f"❌ Ошибка update_last_message_id: {e}")
    
    def get_fissure_top(self, limit=10):
        """Получение топ пользователей"""
        try:
            conn = self.connect()
            # Определяем тип базы данных по схеме URL
            url = urlparse.urlparse(DATABASE_URL)
            scheme = url.scheme
            
            if "postgres" in scheme:
                cursor = conn.cursor(cursor_factory=RealDictCursor)
                cursor.execute("""
                    SELECT telegram_id, username, fissure FROM users ORDER BY fissure DESC LIMIT %s
                """, (limit,))
                users = cursor.fetchall()
                cursor.close()
                return [{"telegram_id": u["telegram_id"], "username": u["username"], "fissure": u["fissure"]} for u in users]
            else:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT telegram_id, username, fissure FROM users ORDER BY fissure DESC LIMIT ?
                """, (limit,))
                users = cursor.fetchall()
                cursor.close()
                return [{"telegram_id": u[0], "username": u[1], "fissure": u[2]} for u in users]
        except Exception as e:
            print(f"❌ Ошибка get_fissure_top: {e}")
            return []
    
    def get_user_rank(self, telegram_id):
        """Получение позиции игрока в топе"""
        try:
            conn = self.connect()
            url = urlparse.urlparse(DATABASE_URL)
            scheme = url.scheme
            
            if "postgres" in scheme:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT COUNT(*) + 1 FROM users WHERE fissure > (
                        SELECT fissure FROM users WHERE telegram_id = %s
                    )
                """, (telegram_id,))
                rank = cursor.fetchone()[0]
                cursor.close()
                return rank
            else:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT COUNT(*) + 1 FROM users WHERE fissure > (
                        SELECT fissure FROM users WHERE telegram_id = ?
                    )
                """, (telegram_id,))
                rank = cursor.fetchone()[0]
                cursor.close()
                return rank
        except Exception as e:
            print(f"❌ Ошибка get_user_rank: {e}")
            return None
    
    def decrease_inactive_fissure(self, days_inactive=1, decrease_amount=1.0):
        """Уменьшить fissure для неактивных игроков"""
        try:
            conn = self.connect()
            url = urlparse.urlparse(DATABASE_URL)
            scheme = url.scheme
            
            if "postgres" in scheme:
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE users 
                    SET fissure = GREATEST(0.1, fissure - %s)
                    WHERE last_activity < CURRENT_TIMESTAMP - INTERVAL '%s days'
                    AND fissure > 0.1
                """, (decrease_amount, days_inactive))
                affected = cursor.rowcount
                conn.commit()
                cursor.close()
                return affected
            else:
                # Для SQLite используем datetime function
                cursor = conn.cursor()
                # Форматируем строку для days_inactive
                days_str = f"-{days_inactive} days"
                cursor.execute("""
                    UPDATE users 
                    SET fissure = MAX(0.1, fissure - ?)
                    WHERE last_activity < datetime('now', ?)
                    AND fissure > 0.1
                """, (decrease_amount, days_str))
                affected = cursor.rowcount
                conn.commit()
                cursor.close()
                return affected
        except Exception as e:
            print(f"❌ Ошибка decrease_inactive_fissure: {e}")
            return 0
    
    def get_config(self, key, default=None):
        """Получить значение конфигурации"""
        try:
            conn = self.connect()
            url = urlparse.urlparse(DATABASE_URL)
            scheme = url.scheme
            cursor = conn.cursor()
            if "postgres" in scheme:
                cursor.execute("SELECT value FROM bot_config WHERE key = %s", (key,))
            else:
                cursor.execute("SELECT value FROM bot_config WHERE key = ?", (key,))
            result = cursor.fetchone()
            cursor.close()
            return result[0] if result else default
        except Exception as e:
            print(f"❌ Ошибка get_config: {e}")
            return default
    
    def set_config(self, key, value):
        """Установить значение конфигурации"""
        try:
            conn = self.connect()
            url = urlparse.urlparse(DATABASE_URL)
            scheme = url.scheme
            cursor = conn.cursor()
            if "postgres" in scheme:
                cursor.execute("""
                    INSERT INTO bot_config (key, value) VALUES (%s, %s)
                    ON CONFLICT(key) DO UPDATE SET value = EXCLUDED.value
                """, (key, str(value)))
            else:
                cursor.execute("""
                    INSERT INTO bot_config (key, value) VALUES (?, ?)
                    ON CONFLICT(key) DO UPDATE SET value = EXCLUDED.value
                """, (key, str(value)))
            conn.commit()
            cursor.close()
            return True
        except Exception as e:
            print(f"❌ Ошибка set_config: {e}")
            return False
    
    def get_digest_stats(self):
        """Получить статистику для дайджеста"""
        try:
            conn = self.connect()
            cursor = conn.cursor()
            
            # Один запрос для обоих типов БД (параметры одинаковые)
            cursor.execute("""
                SELECT telegram_id, username, fissure, digest_position, digest_fissure, current_streak, total_growth
                FROM users
            """)
            rows = cursor.fetchall()
            
            cursor.close()
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
                # Показываем рост если есть текущая позиция
                if cur_pos > 0:
                    moved_up = prev_pos - cur_pos if prev_pos > 0 else 0
                    if moved_up > top_growth_positions:
                        top_growth_positions = moved_up
                        top_growth_user = u["username"] or str(u["telegram_id"])
                        top_growth_id = u["telegram_id"]

            # Падение: насколько см уменьшилась фиссура за сутки (current - digest)
            top_drop_user = None
            top_drop_cm = 0.0  # negative
            top_drop_id = None
            for u in users:
                prev_f = u["digest_fissure"]
                cur_f = u["fissure"]
                # Показываем падение если есть digest_fissure
                if prev_f is not None and prev_f > 0:
                    delta = cur_f - prev_f
                    if delta < top_drop_cm:
                        top_drop_cm = delta
                        top_drop_user = u["username"] or str(u["telegram_id"])
                        top_drop_id = u["telegram_id"]

            # Стрик: текущая серия побед (current_streak)
            top_streak_user = None
            top_streak = 0
            top_streak_id = None
            for u in users:
                if u["current_streak"] > top_streak:
                    top_streak = u["current_streak"]
                    top_streak_user = u["username"] or str(u["telegram_id"])
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
            print(f"❌ Ошибка get_digest_stats: {e}")
            return {"top_growth": ("None", 0), "top_drop": ("None", 0.0), "top_streak": ("None", 0)}
    
    def update_player_positions(self):
        """Обновить текущие позиции игроков (по fissure DESC)"""
        try:
            conn = self.connect()
            url = urlparse.urlparse(DATABASE_URL)
            scheme = url.scheme
            cursor = conn.cursor()
            
            # Используем один запрос с подзапросом для обновления позиций
            if "postgres" in scheme:
                cursor.execute("""
                    UPDATE users SET current_position = subquery.pos
                    FROM (SELECT telegram_id, ROW_NUMBER() OVER (ORDER BY fissure DESC) as pos FROM users) subquery
                    WHERE users.telegram_id = subquery.telegram_id
                """)
            else:
                # SQLite: используем скалярный подзапрос
                cursor.execute("""
                    UPDATE users SET current_position = (
                        SELECT COUNT(*) + 1 FROM users u2 WHERE u2.fissure > users.fissure
                    )
                """)
            
            conn.commit()
            
            # Получаем количество затронутых строк
            affected = cursor.rowcount
            cursor.close()
            return affected
        except Exception as e:
            print(f"❌ Ошибка update_player_positions: {e}")
            return 0

    def update_digest_snapshot(self):
        """Обновить 'снимок' (позиция/фиссура) после отправки дайджеста"""
        try:
            conn = self.connect()
            url = urlparse.urlparse(DATABASE_URL)
            scheme = url.scheme
            cursor = conn.cursor()

            # Используем один запрос с подзапросом для обновления позиций и снимка
            if "postgres" in scheme:
                cursor.execute("""
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
                """)
            else:
                # SQLite: используем скалярные подзапросы
                cursor.execute("""
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
                """)

            conn.commit()
            
            # Получаем количество затронутых строк
            affected = cursor.rowcount
            cursor.close()
            return affected
        except Exception as e:
            print(f"❌ Ошибка update_digest_snapshot: {e}")
            return 0

    def get_weekly_digest_stats(self):
        """Статистика для еженедельного дайджеста: рост в см, прорыв по позициям, броски, новички, общий рост."""
        try:
            conn = self.connect()
            url = urlparse.urlparse(DATABASE_URL)
            scheme = url.scheme
            cursor = conn.cursor()

            # Один запрос для обоих типов БД
            cursor.execute("""
                SELECT telegram_id, username, fissure, current_position, weekly_digest_position,
                       weekly_growth, weekly_rolls, created_at
                FROM users
            """)
            rows = cursor.fetchall()

            # Разный синтаксис для дат в PostgreSQL и SQLite
            if "postgres" in scheme:
                cursor.execute("SELECT COUNT(*) FROM users WHERE created_at >= CURRENT_TIMESTAMP - INTERVAL '7 days'")
            else:
                cursor.execute("SELECT COUNT(*) FROM users WHERE created_at >= datetime('now', '-7 days')")
            new_players_week = cursor.fetchone()[0] or 0

            cursor.close()

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
                    top_cm_user = u["username"] or str(u["telegram_id"])
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
                        breakthrough_user = u["username"] or str(u["telegram_id"])
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
            print(f"❌ Ошибка get_weekly_digest_stats: {e}")
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
            conn = self.connect()
            url = urlparse.urlparse(DATABASE_URL)
            scheme = url.scheme
            cursor = conn.cursor()

            # Используем один запрос с подзапросом
            if "postgres" in scheme:
                cursor.execute("""
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
                """)
            else:
                # SQLite: используем скалярные подзапросы
                cursor.execute("""
                    UPDATE users SET 
                        current_position = (
                            SELECT COUNT(*) + 1 FROM users u2 WHERE u2.fissure > users.fissure
                        ),
                        weekly_digest_position = (
                            SELECT COUNT(*) + 1 FROM users u2 WHERE u2.fissure > users.fissure
                        ),
                        weekly_rolls = 0,
                        weekly_growth = 0
                """)

            conn.commit()
            
            # Получаем количество затронутых строк
            affected = cursor.rowcount
            cursor.close()
            return affected
        except Exception as e:
            print(f"❌ Ошибка update_weekly_digest_snapshot: {e}")
            return 0

# Функции для совместимости со старым кодом
def get_user(telegram_id, username=None):
    """Функция для совместимости - использует новый класс Database"""
    db = Database()
    return db.get_user(telegram_id, username)

def update_fissure(telegram_id, fissure, last_fissure, growth=0):
    """Функция для совместимости - использует новый класс Database"""
    db = Database()
    db.update_fissure(telegram_id, fissure, last_fissure, growth)

def get_fissure_top(limit=10):
    """Функция для совместимости - использует новый класс Database"""
    db = Database()
    return db.get_fissure_top(limit)

def get_user_rank(telegram_id):
    """Получить позицию игрока в топе"""
    db = Database()
    return db.get_user_rank(telegram_id)

def update_last_message_id(telegram_id, message_id):
    """Функция для совместимости - использует новый класс Database"""
    db = Database()
    db.update_last_message_id(telegram_id, message_id)

def update_user_field(telegram_id, field, value):
    """Обновление любого поля пользователя"""
    try:
        conn = get_connection()
        url = urlparse.urlparse(DATABASE_URL)
        scheme = url.scheme
        
        cursor = conn.cursor()
        
        if "postgres" in scheme:
            cursor.execute(
                f"UPDATE users SET {field} = %s WHERE telegram_id = %s",
                (value, telegram_id)
            )
        else:
            cursor.execute(
                f"UPDATE users SET {field} = ? WHERE telegram_id = ?",
                (value, telegram_id)
            )
        
        conn.commit()
        cursor.close()
        return True
    except Exception as e:
        logger.error(f"Error updating user field: {e}")
        return False

def decrease_inactive_fissure(days_inactive=1, decrease_amount=1.0):
    """Уменьшить fissure для неактивных игроков (вызывается ежедневно)"""
    db = Database()
    return db.decrease_inactive_fissure(days_inactive, decrease_amount)

def get_config(key, default=None):
    """Получить значение конфигурации"""
    db = Database()
    return db.get_config(key, default)

def set_config(key, value):
    """Установить значение конфигурации"""
    db = Database()
    return db.set_config(key, value)

def get_digest_stats():
    """Получить статистику для дайджеста"""
    db = Database()
    return db.get_digest_stats()

def update_player_positions():
    """Обновить позиции игроков"""
    db = Database()
    return db.update_player_positions()

def update_digest_snapshot():
    """Обновить снимок для дайджеста"""
    db = Database()
    return db.update_digest_snapshot()

def get_weekly_digest_stats():
    """Статистика для еженедельного дайджеста"""
    db = Database()
    return db.get_weekly_digest_stats()

def update_weekly_digest_snapshot():
    """Обновить снимок и обнулить недельные счётчики после еженедельного дайджеста"""
    db = Database()
    return db.update_weekly_digest_snapshot()# Temporary file to add new functions to database.py

# Function to add to database.py at the end:

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
                       dota_total_games, dota_wins
                FROM users 
                WHERE steam_id IS NOT NULL AND mmr > 0
                ORDER BY mmr DESC
                LIMIT %s
            """, (limit,))
            users = cursor.fetchall()
            cursor.close()
            return [{"telegram_id": u[0], "username": u[1], "steam_nickname": u[2], 
                    "mmr": u[3], "dota_total_games": u[4], "dota_wins": u[5]} for u in users]
        else:
            cursor.execute("""
                SELECT telegram_id, username, steam_nickname, mmr, 
                       dota_total_games, dota_wins
                FROM users 
                WHERE steam_id IS NOT NULL AND mmr > 0
                ORDER BY mmr DESC
                LIMIT ?
            """, (limit,))
            users = cursor.fetchall()
            cursor.close()
            return [{"telegram_id": u[0], "username": u[1], "steam_nickname": u[2], 
                    "mmr": u[3], "dota_total_games": u[4], "dota_wins": u[5]} for u in users]
    except Exception as e:
        logger.error(f"Ошибка get_dota_mmr_top: {e}")
        return []


def get_dota_week_top(limit=10):
    """Получение топа игроков Dota 2 за неделю по винрейту (без минимума игр)"""
    try:
        conn = get_connection()
        url = urlparse.urlparse(DATABASE_URL)
        scheme = url.scheme
        
        cursor = conn.cursor()
        
        if "postgres" in scheme:
            cursor.execute("""
                SELECT telegram_id, username, steam_nickname, mmr, 
                       week_games, week_wins, 
                       CASE WHEN week_games > 0 
                            THEN ROUND(week_wins::float / week_games * 100, 1) 
                            ELSE 0 END as winrate
                FROM users 
                WHERE steam_id IS NOT NULL AND week_games > 0
                ORDER BY winrate DESC, week_games DESC
                LIMIT %s
            """, (limit,))
            users = cursor.fetchall()
            cursor.close()
            return [{"telegram_id": u[0], "username": u[1], "steam_nickname": u[2], 
                    "mmr": u[3], "week_games": u[4], "week_wins": u[5], "winrate": u[6]} for u in users]
        else:
            cursor.execute("""
                SELECT telegram_id, username, steam_nickname, mmr, 
                       week_games, week_wins, 
                       CASE WHEN week_games > 0 
                            THEN ROUND(week_wins * 100.0 / week_games, 1) 
                            ELSE 0 END as winrate
                FROM users 
                WHERE steam_id IS NOT NULL AND week_games > 0
                ORDER BY winrate DESC, week_games DESC
                LIMIT ?
            """, (limit,))
            users = cursor.fetchall()
            cursor.close()
            return [{"telegram_id": u[0], "username": u[1], "steam_nickname": u[2], 
                    "mmr": u[3], "week_games": u[4], "week_wins": u[5], "winrate": u[6]} for u in users]
    except Exception as e:
        logger.error(f"Ошибка get_dota_week_top: {e}")
        return []


def get_all_users_with_steam():
    """Получение всех пользователей с привязанным Steam"""
    try:
        conn = get_connection()
        url = urlparse.urlparse(DATABASE_URL)
        scheme = url.scheme
        
        cursor = conn.cursor()
        
        if "postgres" in scheme:
            cursor.execute("""
                SELECT telegram_id, steam_id FROM users WHERE steam_id IS NOT NULL
            """)
            users = cursor.fetchall()
            cursor.close()
            return [{"telegram_id": u[0], "steam_id": u[1]} for u in users]
        else:
            cursor.execute("""
                SELECT telegram_id, steam_id FROM users WHERE steam_id IS NOT NULL
            """)
            users = cursor.fetchall()
            cursor.close()
            return [{"telegram_id": u[0], "steam_id": u[1]} for u in users]
    except Exception as e:
        logger.error(f"Ошибка get_all_users_with_steam: {e}")
        return []


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
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
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
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
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


def get_db_type():
    """Получить тип базы данных"""
    url = urlparse.urlparse(DATABASE_URL)
    scheme = url.scheme
    
    if "postgres" in scheme:
        return "postgresql"
    else:
        return "sqlite"
