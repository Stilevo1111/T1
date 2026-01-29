import os
import psycopg2
from psycopg2.extras import RealDictCursor

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("❌ DATABASE_URL не задан!")

def get_connection():
    return psycopg2.connect(DATABASE_URL, sslmode='require')

def init_db():
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
        print("✅ База данных инициализирована")
    except Exception as e:
        print(f"❌ Ошибка инициализации БД: {e}")

def get_user(telegram_id, username=None):
    try:
        conn = get_connection()
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
    except Exception as e:
        print(f"❌ Ошибка get_user: {e}")
        return {"telegram_id": telegram_id, "username": username, "fissure": 0.1, "last_fissure": 0}

def update_fissure(telegram_id, fissure, last_fissure):
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE users SET fissure=%s, last_fissure=%s WHERE telegram_id=%s
        """, (fissure, last_fissure, telegram_id))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"❌ Ошибка update_fissure: {e}")

def get_fissure_top(limit=10):
    try:
        conn = get_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("""
            SELECT telegram_id, username, fissure FROM users ORDER BY fissure DESC LIMIT %s
        """, (limit,))
        users = cursor.fetchall()
        conn.close()
        return [{"telegram_id": u["telegram_id"], "username": u["username"], "fissure": u["fissure"]} for u in users]
    except Exception as e:
        print(f"❌ Ошибка get_fissure_top: {e}")
        return []
