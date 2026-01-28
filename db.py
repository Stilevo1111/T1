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
            fissure REAL DEFAULT 0.1,
            last_fissure INTEGER DEFAULT 0
        )
    """)
    
    conn.commit()
    conn.close()

def get_user(uid):
    """Получение пользователя из базы данных"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM users WHERE uid = ?", (uid,))
    user = cursor.fetchone()
    
    if user:
        conn.close()
        return {
            "uid": user[0],
            "fissure": user[1],
            "last_fissure": user[2]
        }
    else:
        # Создаем нового пользователя
        cursor.execute("INSERT INTO users (uid, fissure, last_fissure) VALUES (?, ?, ?)", 
                      (uid, 0.1, 0))
        conn.commit()
        conn.close()
        return {
            "uid": uid,
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
        SELECT uid, fissure 
        FROM users 
        ORDER BY fissure DESC 
        LIMIT ?
    """, (limit,))
    
    users = cursor.fetchall()
    conn.close()
    
    return [{"uid": u[0], "fissure": u[1]} for u in users]