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
                    total_rolls INTEGER DEFAULT 0
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
            # Для хранения позиций для отслеживания роста/падения
            cursor.execute("""
                ALTER TABLE users ADD COLUMN IF NOT EXISTS last_week_position INTEGER DEFAULT 0
            """)
            cursor.execute("""
                ALTER TABLE users ADD COLUMN IF NOT EXISTS last_day_position INTEGER DEFAULT 0
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
                    total_rolls INTEGER DEFAULT 0
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
            if 'last_week_position' not in columns:
                cursor.execute("ALTER TABLE users ADD COLUMN last_week_position INTEGER DEFAULT 0")
            if 'last_day_position' not in columns:
                cursor.execute("ALTER TABLE users ADD COLUMN last_day_position INTEGER DEFAULT 0")
        
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
                INSERT INTO users (telegram_id, username, fissure, last_fissure, last_message_id, total_growth, total_rolls)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
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
                INSERT OR REPLACE INTO users (telegram_id, username, fissure, last_fissure, last_message_id, total_growth, total_rolls)
                VALUES (?, ?, ?, ?, ?, ?, ?)
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
                        "total_rolls": user.get("total_rolls", 0)
                    }
                else:
                    self.add_user(telegram_id, username, None, None)
                    cursor.close()
                    return {"telegram_id": telegram_id, "username": username, "fissure": 0.1, "last_fissure": 0, "last_message_id": 0, "total_growth": 0, "total_rolls": 0}
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
                        "total_rolls": user[7] if len(user) > 7 else 0
                    }
                else:
                    self.add_user(telegram_id, username, None, None)
                    cursor.close()
                    return {"telegram_id": telegram_id, "username": username, "fissure": 0.1, "last_fissure": 0, "last_message_id": 0, "total_growth": 0, "total_rolls": 0}
        except Exception as e:
            print(f"❌ Ошибка get_user: {e}")
            return {"telegram_id": telegram_id, "username": username, "fissure": 0.1, "last_fissure": 0, "last_message_id": 0, "total_growth": 0, "total_rolls": 0}
    
    def update_fissure(self, telegram_id, fissure, last_fissure, growth=0):
        """Обновление данных пользователя"""
        try:
            conn = self.connect()
            # Определяем тип базы данных по схеме URL
            url = urlparse.urlparse(DATABASE_URL)
            scheme = url.scheme
            
            if "postgres" in scheme:
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE users SET fissure=%s, last_fissure=%s, 
                    total_growth = total_growth + %s,
                    total_rolls = total_rolls + 1,
                    last_activity = CURRENT_TIMESTAMP
                    WHERE telegram_id=%s
                """, (fissure, last_fissure, growth, telegram_id))
            else:
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE users SET fissure=?, last_fissure=?, 
                    total_growth = total_growth + ?,
                    total_rolls = total_rolls + 1,
                    last_activity = CURRENT_TIMESTAMP
                    WHERE telegram_id=?
                """, (fissure, last_fissure, growth, telegram_id))
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
                cursor.execute("""
                    UPDATE users 
                    SET fissure = MAX(0.1, fissure - ?)
                    WHERE last_activity < datetime('now', '-' || ? || ' days')
                    AND fissure > 0.1
                """, (decrease_amount, days_inactive))
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
            cursor = conn.cursor()
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
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO bot_config (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
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
            url = urlparse(DATABASE_URL)
            scheme = url.scheme
            cursor = conn.cursor()
            
            # Всего игроков
            cursor.execute("SELECT COUNT(*) FROM users")
            total_players = cursor.fetchone()[0]
            
            # Новые игроки сегодня
            if "postgres" in scheme:
                cursor.execute("SELECT COUNT(*) FROM users WHERE DATE(created_at) = CURRENT_DATE")
                new_today = cursor.fetchone()[0]
                # Игроки с наибольшим ростом позиции за день
                cursor.execute("""
                    SELECT username, last_day_position - last_week_position as growth
                    FROM users WHERE last_day_position > 0 ORDER BY growth DESC LIMIT 1
                """)
                top_growth = cursor.fetchone()
            else:
                cursor.execute("SELECT COUNT(*) FROM users WHERE DATE(created_at) = DATE('now')")
                new_today = cursor.fetchone()[0]
                cursor.execute("""
                    SELECT username, last_day_position - last_week_position as growth
                    FROM users WHERE last_day_position > 0 ORDER BY growth DESC LIMIT 1
                """)
                top_growth = cursor.fetchone()
            
            cursor.close()
            return {
                'total_players': total_players,
                'new_today': new_today,
                'top_growth': top_growth if top_growth else ('None', 0)
            }
        except Exception as e:
            print(f"❌ Ошибка get_digest_stats: {e}")
            return {'total_players': 0, 'new_today': 0, 'top_growth': ('None', 0)}
    
    def update_player_positions(self):
        """Обновить позиции игроков (вызывается раз в день)"""
        try:
            conn = self.connect()
            url = urlparse(DATABASE_URL)
            scheme = url.scheme
            cursor = conn.cursor()
            
            # Получаем текущий топ
            cursor.execute("SELECT telegram_id, ROW_NUMBER() OVER (ORDER BY fissure DESC) as pos FROM users")
            players = cursor.fetchall()
            
            for player in players:
                telegram_id = player[0]
                new_position = player[1]
                
                if "postgres" in scheme:
                    cursor.execute("""
                        UPDATE users SET last_week_position = last_day_position, last_day_position = %s
                        WHERE telegram_id = %s
                    """, (new_position, telegram_id))
                else:
                    cursor.execute("""
                        UPDATE users SET last_week_position = last_day_position, last_day_position = ?
                        WHERE telegram_id = ?
                    """, (new_position, telegram_id))
            
            conn.commit()
            cursor.close()
            return len(players)
        except Exception as e:
            print(f"❌ Ошибка update_player_positions: {e}")
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