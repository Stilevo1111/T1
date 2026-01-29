#!/usr/bin/env python3
"""
Тест SQLite-совместимой базы данных для fissure-bot
"""

import time
import sys
import os

# Добавляем путь к проекту
sys.path.append(os.path.dirname(__file__))

# Импортируем SQLite-версию базы данных
from database_sqlite import init_db, get_user, update_fissure, get_fissure_top

def test_recharge_logic():
    """Тест логики перезарядки"""
    print("🧪 Тест логики перезарядки...")
    
    # Тестовый пользователь
    test_uid = 999999999
    test_username = "test_user_recharge"
    
    # Получаем пользователя (создаем если не существует)
    user = get_user(test_uid, test_username)
    print(f"✅ Пользователь: {user}")
    
    # Устанавливаем время последнего использования в прошлое (чтобы можно было использовать)
    past_time = time.time() - 86400 - 1  # 24 часа + 1 секунда назад
    update_fissure(test_uid, user["fissure"], past_time)
    
    # Проверяем, что можно использовать фиссуру
    user_after = get_user(test_uid, test_username)
    current_time = time.time()
    
    if current_time - user_after["last_fissure"] >= 86400:
        print("✅ Можно использовать фиссуру (время перезарядки прошло)")
    else:
        print("❌ Ошибка: время перезарядки не прошло")
        return False
    
    # Используем фиссуру (устанавливаем текущее время)
    update_fissure(test_uid, user_after["fissure"] + 1, current_time)
    
    # Проверяем, что теперь нельзя использовать фиссуру
    user_final = get_user(test_uid, test_username)
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
    top_users = get_fissure_top(5)
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
    print("🚀 Запуск тестирования SQLite-версии fissure-bot...")
    print("=" * 60)
    
    # Инициализируем тестовую базу данных
    init_db()
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
        print("\n🎉 Все тесты пройдены! SQLite-версия работает корректно.")
        return 0
    else:
        print("\n⚠️  Некоторые тесты не пройдены. Проверьте логи.")
        return 1

if __name__ == "__main__":
    exit_code = main()
    exit(exit_code)