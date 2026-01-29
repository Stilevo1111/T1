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
                uid BIGINT PRIMARY KEY,
                username TEXT,
                fissure REAL DEFAULT 0.1,
                last_fissure DOUBLE PRECISION DEFAULT 0
            )
        """)
        conn.commit()
        conn.close()
        print("✅ База данных инициализирована")
    except Exception as e:
        print(f"❌ Ошибка инициализации БД: {e}")

def get_user(uid, username=None):
    try:
        conn = get_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT * FROM users WHERE uid = %s", (uid,))
        user = cursor.fetchone()
        if user:
            conn.close()
            return {
                "uid": user["uid"],
                "username": user["username"],
                "fissure": user["fissure"],
                "last_fissure": user["last_fissure"]
            }
        else:
            cursor.execute(
                "INSERT INTO users (uid, username, fissure, last_fissure) VALUES (%s, %s, %s, %s)",
                (uid, username, 0.1, 0)
            )
            conn.commit()
            conn.close()
            return {"uid": uid, "username": username, "fissure": 0.1, "last_fissure": 0}
    except Exception as e:
        print(f"❌ Ошибка get_user: {e}")
        return {"uid": uid, "username": username, "fissure": 0.1, "last_fissure": 0}

def update_fissure(uid, fissure, last_fissure):
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE users SET fissure=%s, last_fissure=%s WHERE uid=%s
        """, (fissure, last_fissure, uid))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"❌ Ошибка update_fissure: {e}")

def get_fissure_top(limit=10):
    try:
        conn = get_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("""
            SELECT uid, username, fissure FROM users ORDER BY fissure DESC LIMIT %s
        """, (limit,))
        users = cursor.fetchall()
        conn.close()
        return [{"uid": u["uid"], "username": u["username"], "fissure": u["fissure"]} for u in users]
    except Exception as e:
        print(f"❌ Ошибка get_fissure_top: {e}")
        return []