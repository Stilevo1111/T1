import sqlite3
import os

DB_PATH = "fissure.db"

def init_db():
    """Инициализация базы данных"""
    conn = sqlite3.connect(DB_PATH)
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

def get_user(uid, username=None):
    """Получение пользователя из базы данных"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM users WHERE uid = ?", (uid,))
    user = cursor.fetchone()
    
    if user:
        conn.close()
        return {
            "uid": user[0],
            "username": user[1],
            "fissure": user[2],
            "last_fissure": user[3]
        }
    else:
        # Создаем нового пользователя с username
        cursor.execute("INSERT INTO users (uid, username, fissure, last_fissure) VALUES (?, ?, ?, ?)", 
                      (uid, username, 0.1, 0))
        conn.commit()
        conn.close()
        return {
            "uid": uid,
            "username": username,
            "fissure": 0.1,
            "last_fissure": 0
        }

def update_fissure(uid, fissure, last_fissure):
    """Обновление данных пользователя"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("""
        UPDATE users 
        SET fissure = ?, last_fissure = ? 
        WHERE uid = ?
    """, (fissure, last_fissure, uid))
    
    conn.commit()
    conn.close()

def get_fissure_top(limit=10):
    """Получение топ пользователей по длине фиссуры"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT uid, username, fissure 
        FROM users 
        ORDER BY fissure DESC 
        LIMIT ?
    """, (limit,))
    
    users = cursor.fetchall()
    conn.close()
    
    return [{"uid": u[0], "username": u[1], "fissure": u[2]} for u in users]
