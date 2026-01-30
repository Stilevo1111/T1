import os
import psycopg2
from psycopg2.extras import RealDictCursor
import logging
import urllib.parse as urlparse

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("❌ DATABASE_URL не задан!")

def get_connection():
    """Получение соединения с PostgreSQL"""
    try:
        # Парсим URL для PostgreSQL
        url = urlparse.urlparse(DATABASE_URL)
        dbname = url.path[1:]
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
            sslmode='require'
        )
        return conn
    except Exception as e:
        logger.error(f"❌ Ошибка подключения к PostgreSQL: {e}")
        raise

def init_db():
    """Инициализация таблиц"""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                telegram_id BIGINT UNIQUE NOT NULL,
                username VARCHAR(255),
                fissure REAL DEFAULT 0.1,
                last_fissure DOUBLE PRECISION DEFAULT 0
            )
        """)
        
        conn.commit()
        conn.close()
        logger.info("✅ База данных инициализирована")
    except Exception as e:
        logger.error(f"❌ Ошибка инициализации БД: {e}")

class Database:
    """Класс для работы с базой данных"""
    
    def __init__(self):
        self.conn = None
    
    def connect(self):
        """Устанавливаем соединение"""
        if not self.conn or self.conn.closed:
            self.conn = get_connection()
        return self.conn
    
    def get_user(self, telegram_id, username=None):
        """Получение пользователя"""
        try:
            conn = self.connect()
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            
            # Ищем пользователя
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
                # Создаем нового пользователя
                cursor.execute("""
                    INSERT INTO users (telegram_id, username, fissure, last_fissure)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (telegram_id) DO NOTHING
                    RETURNING *
                """, (telegram_id, username, 0.1, 0))
                
                conn.commit()
                new_user = cursor.fetchone()
                cursor.close()
                
                if new_user:
                    return {
                        "telegram_id": new_user["telegram_id"],
                        "username": new_user["username"],
                        "fissure": new_user["fissure"],
                        "last_fissure": new_user["last_fissure"]
                    }
                else:
                    # Если конфликт (пользователь уже создан параллельно)
                    cursor = conn.cursor(cursor_factory=RealDictCursor)
                    cursor.execute("SELECT * FROM users WHERE telegram_id = %s", (telegram_id,))
                    user = cursor.fetchone()
                    cursor.close()
                    
                    return {
                        "telegram_id": user["telegram_id"],
                        "username": user["username"],
                        "fissure": user["fissure"],
                        "last_fissure": user["last_fissure"]
                    }
                    
        except Exception as e:
            logger.error(f"❌ Ошибка get_user: {e}")
            return {"telegram_id": telegram_id, "username": username, "fissure": 0.1, "last_fissure": 0}
    
    def update_fissure(self, telegram_id, fissure, last_fissure):
        """Обновление данных пользователя"""
        try:
            conn = self.connect()
            cursor = conn.cursor()
            
            cursor.execute("""
                UPDATE users 
                SET fissure = %s, last_fissure = %s 
                WHERE telegram_id = %s
            """, (fissure, last_fissure, telegram_id))
            
            conn.commit()
            cursor.close()
            
        except Exception as e:
            logger.error(f"❌ Ошибка update_fissure: {e}")
    
    def get_fissure_top(self, limit=10):
        """Получение топ пользователей"""
        try:
            conn = self.connect()
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            
            cursor.execute("""
                SELECT telegram_id, username, fissure 
                FROM users 
                ORDER BY fissure DESC 
                LIMIT %s
            """, (limit,))
            
            users = cursor.fetchall()
            cursor.close()
            
            return [
                {
                    "telegram_id": u["telegram_id"],
                    "username": u["username"],
                    "fissure": u["fissure"]
                } 
                for u in users
            ]
            
        except Exception as e:
            logger.error(f"❌ Ошибка get_fissure_top: {e}")
            return []

# Создаем глобальный экземпляр для использования
db_instance = Database()

# Функции для совместимости
def get_user(telegram_id, username=None):
    return db_instance.get_user(telegram_id, username)

def update_fissure(telegram_id, fissure, last_fissure):
    db_instance.update_fissure(telegram_id, fissure, last_fissure)

def get_fissure_top(limit=10):
    return db_instance.get_fissure_top(limit)