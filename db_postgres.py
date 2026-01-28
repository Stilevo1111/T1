import os
import psycopg2
from psycopg2.extras import RealDictCursor

# Получаем URL базы данных из переменной окружения
DATABASE_URL = os.getenv("DATABASE_URL")

def init_db():
    """Инициализация PostgreSQL базы данных"""
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cursor = conn.cursor()
        
        # Создаем таблицу пользователей
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                uid INTEGER PRIMARY KEY,
                username TEXT,
                fissure REAL DEFAULT 0.1,
                last_fissure INTEGER DEFAULT 0
            )
        """)
        
        conn.commit()
        conn.close()
        print("✅ PostgreSQL база данных инициализирована")
    except Exception as e:
        print(f"❌ Ошибка инициализации базы данных: {e}")

def get_user(uid, username=None):
    """Получение пользователя из PostgreSQL базы данных"""
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
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
            # Создаем нового пользователя с username
            cursor.execute("INSERT INTO users (uid, username, fissure, last_fissure) VALUES (%s, %s, %s, %s)", 
                          (uid, username, 0.1, 0))
            conn.commit()
            conn.close()
            return {
                "uid": uid,
                "username": username,
                "fissure": 0.1,
                "last_fissure": 0
            }
    except Exception as e:
        print(f"❌ Ошибка получения пользователя: {e}")
        return {
            "uid": uid,
            "username": username,
            "fissure": 0.1,
            "last_fissure": 0
        }

def update_fissure(uid, fissure, last_fissure):
    """Обновление данных пользователя в PostgreSQL"""
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cursor = conn.cursor()
        
        cursor.execute("""
            UPDATE users 
            SET fissure = %s, last_fissure = %s 
            WHERE uid = %s
        """, (fissure, last_fissure, uid))
        
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"❌ Ошибка обновления данных: {e}")

def get_fissure_top(limit=10):
    """Получение топ пользователей по длине фиссуры из PostgreSQL"""
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        cursor.execute("""
            SELECT uid, username, fissure 
            FROM users 
            ORDER BY fissure DESC 
            LIMIT %s
        """, (limit,))
        
        users = cursor.fetchall()
        conn.close()
        
        return [{"uid": u["uid"], "username": u["username"], "fissure": u["fissure"]} for u in users]
    except Exception as e:
        print(f"❌ Ошибка получения топа: {e}")
        return []

def get_user_count():
    """Получение количества пользователей"""
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cursor = conn.cursor()
        
        cursor.execute("SELECT COUNT(*) FROM users")
        count = cursor.fetchone()[0]
        conn.close()
        
        return count
    except Exception as e:
        print(f"❌ Ошибка получения количества пользователей: {e}")
        return 0