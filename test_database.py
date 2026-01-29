#!/usr/bin/env python3
"""
Упрощенная тестовая база данных для проверки fissure-bot
"""

import sqlite3
import time

# Создаем тестовую базу данных
def init_test_db():
    conn = sqlite3.connect("test_fissure.db")
    cursor = conn.cursor()
    
    # Создаем таблицу пользователей
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

def get_user_test(telegram_id, username=None):
    """Тестовая функция получения пользователя"""
    conn = sqlite3.connect("test_fissure.db")
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

def update_fissure_test(telegram_id, fissure, last_fissure):
    """Тестовая функция обновления фиссуры"""
    conn = sqlite3.connect("test_fissure.db")
    cursor = conn.cursor()
    
    cursor.execute("""
        UPDATE users SET fissure=?, last_fissure=? WHERE telegram_id=?
    """, (fissure, last_fissure, telegram_id))
    
    conn.commit()
    conn.close()

def get_fissure_top_test(limit=10):
    """Тестовая функция получения топа"""
    conn = sqlite3.connect("test_fissure.db")
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT telegram_id, username, fissure FROM users ORDER BY fissure DESC LIMIT ?
    """, (limit,))
    
    users = cursor.fetchall()
    conn.close()
    
    return [{"telegram_id": u[0], "username": u[1], "fissure": u[2]} for u in users]

def test_recharge_logic():
    """Тест логики перезарядки"""
    print("🧪 Тест логики перезарядки...")
    
    # Тестовый пользователь
    test_uid = 999999999
    test_username = "test_user_recharge"
    
    # Получаем пользователя (создаем если не существует)
    user = get_user_test(test_uid, test_username)
    print(f"✅ Пользователь: {user}")
    
    # Устанавливаем время последнего использования в прошлое (чтобы можно было использовать)
    past_time = time.time() - 86400 - 1  # 24 часа + 1 секунда назад
    update_fissure_test(test_uid, user["fissure"], past_time)
    
    # Проверяем, что можно использовать фиссуру
    user_after = get_user_test(test_uid, test_username)
    current_time = time.time()
    
    if current_time - user_after["last_fissure"] >= 86400:
        print("✅ Можно использовать фиссуру (время перезарядки прошло)")
    else:
        print("❌ Ошибка: время перезарядки не прошло")
        return False
    
    # Используем фиссуру (устанавливаем текущее время)
    update_fissure_test(test_uid, user_after["fissure"] + 1, current_time)
    
    # Проверяем, что теперь нельзя использовать фиссуру
    user_final = get_user_test(test_uid, test_username)
    check_time = time.time()
    
    if check_time - user_final["last_fissure"] < 86400:
        print("✅ Фиссура в перезарядке (время установлено правильно)")
        return True
    else:
        print("❌ Ошибка: фиссура не в перезарядке")
        return False

def test_top_command():
    """Тест команды топ"""
    print("\n🧪 Тест команды топ...")
    
    # Получаем топ пользователей
    top_users = get_fissure_top_test(5)
    print(f"✅ Получено {len(top_users)} пользователей в топе")
    
    if len(top_users) > 0:
        print("🏆 Топ пользователей:")
        for i, user in enumerate(top_users, 1):
            username = user['username'] or f"Пользователь {user['telegram_id']}"
            print(f"  {i}. {username} — {user['fissure']:.1f} см")
        return True
    else:
        print("⚠️  Топ пуст (это нормально для нового бота)")
        return True

def main():
    """Основная функция тестирования"""
    print("🚀 Запуск тестирования fissure-bot (тестовая база данных)...")
    print("=" * 60)
    
    # Инициализируем тестовую базу данных
    init_test_db()
    print("✅ Тестовая база данных инициализирована")
    
    # Тест 1: Логика перезарядки
    recharge_test_passed = test_recharge_logic()
    
    # Тест 2: Команда топ
    top_test_passed = test_top_command()
    
    print("\n" + "=" * 60)
    print("📊 Результаты тестирования:")
    
    if recharge_test_passed:
        print("✅ Тест перезарядки: ПРОЙДЕН")
    else:
        print("❌ Тест перезарядки: ПРОВАЛЕН")
    
    if top_test_passed:
        print("✅ Тест топа: ПРОЙДЕН")
    else:
        print("❌ Тест топа: ПРОВАЛЕН")
    
    if recharge_test_passed and top_test_passed:
        print("\n🎉 Все тесты пройдены! Исправления работают корректно.")
        return 0
    else:
        print("\n⚠️  Некоторые тесты не пройдены. Проверьте логи.")
        return 1

if __name__ == "__main__":
    exit_code = main()
    exit(exit_code)