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
    print("❌ DATABASE_URL не задан! Бот не может работать без базы данных.")
    raise ValueError("DATABASE_URL environment variable is required")
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
    """Initialize database tables. Use migrations instead for production."""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        # Определяем тип базы данных по схеме URL
        url = urlparse.urlparse(DATABASE_URL)
        scheme = url.scheme
        
        if "postgres" in scheme:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    telegram_id BIGINT UNIQUE NOT NULL,
                    username VARCHAR(255),
                    fissure REAL DEFAULT 0.1,
                    last_fissure DOUBLE PRECISION DEFAULT 0
                )
            """)
        else:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_id INTEGER UNIQUE NOT NULL,
                    username TEXT,
                    fissure REAL DEFAULT 0.1,
                    last_fissure REAL DEFAULT 0
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
                INSERT INTO users (telegram_id, username, fissure, last_fissure)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (telegram_id) 
                DO UPDATE SET 
                    username = EXCLUDED.username,
                    fissure = EXCLUDED.fissure,
                    last_fissure = EXCLUDED.last_fissure
                RETURNING id
            ''', (user_id, username, 0.1, 0))
        else:
            cur.execute('''
                INSERT OR REPLACE INTO users (telegram_id, username, fissure, last_fissure)
                VALUES (?, ?, ?, ?)
            ''', (user_id, username, 0.1, 0))
        
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
                        "last_fissure": user["last_fissure"]
                    }
                else:
                    self.add_user(telegram_id, username, None, None)
                    cursor.close()
                    return {"telegram_id": telegram_id, "username": username, "fissure": 0.1, "last_fissure": 0}
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
                        "last_fissure": user[4]
                    }
                else:
                    self.add_user(telegram_id, username, None, None)
                    cursor.close()
                    return {"telegram_id": telegram_id, "username": username, "fissure": 0.1, "last_fissure": 0}
        except Exception as e:
            print(f"❌ Ошибка get_user: {e}")
            return {"telegram_id": telegram_id, "username": username, "fissure": 0.1, "last_fissure": 0}
    
    def update_fissure(self, telegram_id, fissure, last_fissure):
        """Обновление данных пользователя"""
        try:
            conn = self.connect()
            # Определяем тип базы данных по схеме URL
            url = urlparse.urlparse(DATABASE_URL)
            scheme = url.scheme
            
            if "postgres" in scheme:
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE users SET fissure=%s, last_fissure=%s WHERE telegram_id=%s
                """, (fissure, last_fissure, telegram_id))
            else:
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE users SET fissure=?, last_fissure=? WHERE telegram_id=?
                """, (fissure, last_fissure, telegram_id))
            conn.commit()
            cursor.close()
        except Exception as e:
            print(f"❌ Ошибка update_fissure: {e}")
    
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

# Функции для совместимости со старым кодом
def get_user(telegram_id, username=None):
    """Функция для совместимости - использует новый класс Database"""
    db = Database()
    return db.get_user(telegram_id, username)

def update_fissure(telegram_id, fissure, last_fissure):
    """Функция для совместимости - использует новый класс Database"""
    db = Database()
    db.update_fissure(telegram_id, fissure, last_fissure)

def get_fissure_top(limit=10):
    """Функция для совместимости - использует новый класс Database"""
    db = Database()
    return db.get_fissure_top(limit)

# ТОЧКА ВХОДА - добавьте этот код
if __name__ == "__main__":
    print("🚀 Запуск теста базы данных...")
    
    # 1. Инициализация БД
    init_db()
    print("✅ База данных готова")
    
    # 2. Тест добавления пользователя
    test_user = get_user(123456789, "test_user")
    print(f"✅ Получен/создан пользователь: {test_user}")
    
    # 3. Тест обновления
    update_fissure(123456789, 0.5, 1234567890)
    
    # 4. Тест получения топа
    top_users = get_fissure_top(5)
    print(f"✅ Топ пользователей: {top_users}")
    
    print("🎉 Все операции выполнены успешно!")
