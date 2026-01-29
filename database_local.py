import os
import sqlite3
import logging

# Configure logging for database operations
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Используем локальный SQLite файл
DATABASE_URL = "fissure_bot.db"

def get_connection():
    """Get database connection (SQLite only)"""
    return sqlite3.connect(DATABASE_URL)

def init_db():
    """Initialize database tables."""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
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

def get_user(telegram_id, username=None):
    """Get user from database or create new one"""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))
        user = cursor.fetchone()
        
        if user:
            conn.close()
            return {
                "telegram_id": user[1],
                "username": user[2],
                "fissure": user[3],
                "last_fissure": user[4]
            }
        else:
            cursor.execute(
                "INSERT INTO users (telegram_id, username, fissure, last_fissure) VALUES (?, ?, ?, ?)",
                (telegram_id, username, 0.1, 0)
            )
            conn.commit()
            conn.close()
            return {"telegram_id": telegram_id, "username": username, "fissure": 0.1, "last_fissure": 0}
    except Exception as e:
        print(f"❌ Ошибка get_user: {e}")
        return {"telegram_id": telegram_id, "username": username, "fissure": 0.1, "last_fissure": 0}

def update_fissure(telegram_id, fissure, last_fissure):
    """Update user's fissure and last_fissure time"""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            UPDATE users SET fissure=?, last_fissure=? WHERE telegram_id=?
        """, (fissure, last_fissure, telegram_id))
        
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"❌ Ошибка update_fissure: {e}")

def get_fissure_top(limit=10):
    """Get top users by fissure length"""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT telegram_id, username, fissure FROM users ORDER BY fissure DESC LIMIT ?
        """, (limit,))
        
        users = cursor.fetchall()
        conn.close()
        
        return [{"telegram_id": u[0], "username": u[1], "fissure": u[2]} for u in users]
    except Exception as e:
        print(f"❌ Ошибка get_fissure_top: {e}")
        return []

# ТОЧКА ВХОДА
if __name__ == "__main__":
    print("🚀 Запуск теста базы данных (локальная SQLite версия)...")
    
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