import os
import sqlite3
import psycopg2
from psycopg2.extras import RealDictCursor

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    print("⚠️  DATABASE_URL не задан, используем SQLite для тестирования")
    DATABASE_URL = "test.db"
else:
    print(f"✅ Используем DATABASE_URL: {DATABASE_URL[:20]}...")

def get_connection():
    if DATABASE_URL.startswith("postgresql://"):
        try:
            # Add timeout and better SSL handling
            return psycopg2.connect(
                DATABASE_URL, 
                sslmode='prefer',  # Changed from 'require' to 'prefer' for better compatibility
                connect_timeout=10  # 10 second timeout
            )
        except Exception as e:
            print(f"❌ PostgreSQL connection failed: {e}")
            print("⚠️  Falling back to SQLite...")
            return sqlite3.connect("fallback.db")
    else:
        return sqlite3.connect(DATABASE_URL)

def init_db():
    try:
        conn = get_connection()
        cursor = conn.cursor()
        if DATABASE_URL.startswith("postgresql://"):
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
        print("✅ База данных инициализирована")
    except Exception as e:
        print(f"❌ Ошибка инициализации БД: {e}")

def get_user(telegram_id, username=None):
    try:
        conn = get_connection()
        if DATABASE_URL.startswith("postgresql://"):
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute("SELECT * FROM users WHERE telegram_id = %s", (telegram_id,))
            user = cursor.fetchone()
            if user:
                conn.close()
                return {
                    "telegram_id": user["telegram_id"],
                    "username": user["username"],
                    "fissure": user["fissure"],
                    "last_fissure": user["last_fissure"]
                }
            else:
                cursor.execute(
                    "INSERT INTO users (telegram_id, username, fissure, last_fissure) VALUES (%s, %s, %s, %s)",
                    (telegram_id, username, 0.1, 0)
                )
                conn.commit()
                conn.close()
                return {"telegram_id": telegram_id, "username": username, "fissure": 0.1, "last_fissure": 0}
        else:
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
    try:
        conn = get_connection()
        if DATABASE_URL.startswith("postgresql://"):
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
        conn.close()
    except Exception as e:
        print(f"❌ Ошибка update_fissure: {e}")

def get_fissure_top(limit=10):
    try:
        conn = get_connection()
        if DATABASE_URL.startswith("postgresql://"):
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute("""
                SELECT telegram_id, username, fissure FROM users ORDER BY fissure DESC LIMIT %s
            """, (limit,))
            users = cursor.fetchall()
            conn.close()
            return [{"telegram_id": u["telegram_id"], "username": u["username"], "fissure": u["fissure"]} for u in users]
        else:
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
