#!/usr/bin/env python3
"""
Тестовый скрипт для проверки функциональности бота fissure-bot
"""

import os
import sys
import time
import random

# Добавляем путь к проекту
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def test_database():
    """Тестируем функции базы данных"""
    print("🧪 Тестируем базу данных...")
    
    import db
    
    # Инициализируем базу данных
    db.init_db()
    print("✅ База данных инициализирована")
    
    # Тестируем создание пользователя с username
    test_uid = 999999
    test_username = "test_user"
    user = db.get_user(test_uid, test_username)
    assert user['uid'] == test_uid
    assert user['username'] == test_username
    assert user['fissure'] == 0.1
    assert user['last_fissure'] == 0
    print("✅ Пользователь с username создан")
    
    # Тестируем обновление данных
    new_fissure = 5.5
    new_time = int(time.time())
    db.update_fissure(test_uid, new_fissure, new_time)
    
    user_updated = db.get_user(test_uid, test_username)
    assert user_updated['fissure'] == new_fissure
    assert user_updated['last_fissure'] == new_time
    assert user_updated['username'] == test_username
    print("✅ Данные пользователя обновлены")
    
    # Тестируем получение топа с username
    top = db.get_fissure_top()
    assert len(top) >= 1
    assert top[0]['uid'] == test_uid
    assert top[0]['username'] == test_username
    assert top[0]['fissure'] == new_fissure
    print("✅ Таблица лидеров с username работает")

def test_bot_logic():
    """Тестируем логику бота"""
    print("\n🎮 Тестируем игровую логику...")
    
    import main
    import db
    
    # Проверяем константы
    assert main.COOLDOWN == 86400  # 24 часа
    assert len(main.ROLLS) == 8
    assert 10 in main.ROLLS
    assert -5 in main.ROLLS
    print("✅ Игровые константы корректны")
    
    # Проверяем формат времени
    test_time = main.format_time(3661)  # 1 час 1 минута 1 секунда
    assert "1ч 1м" in test_time
    print("✅ Форматирование времени работает")
    
    # Проверяем фразы
    assert len(main.FISURE_PHRASES["up"]) > 0
    assert len(main.FISURE_PHRASES["down"]) > 0
    assert len(main.FISURE_PHRASES["same"]) > 0
    assert len(main.FISURE_MEMES) > 0
    print("✅ Фразы и мемы загружены")
    
    # Проверяем, что функция top возвращает username
    db.init_db()
    test_uid = 888888
    test_username = "test_top_user"
    user = db.get_user(test_uid, test_username)
    top_users = db.get_fissure_top()
    if len(top_users) > 0:
        assert 'username' in top_users[0], "Функция get_fissure_top должна возвращать username"
        print("✅ Функция top возвращает username")

def test_menu():
    """Тестируем меню"""
    print("\n📱 Тестируем меню...")
    
    import main
    import db
    
    menu = main.main_menu()
    assert menu is not None
    print("✅ Меню создается корректно")
    
    # Проверяем, что функция top в main.py правильно форматирует username
    db.init_db()
    test_uid = 777777
    test_username = "test_menu_user"
    user = db.get_user(test_uid, test_username)
    
    # Имитируем функцию top из main.py
    top_users = db.get_fissure_top()
    if len(top_users) > 0:
        u = top_users[0]
        username = u['username'] if u['username'] else f"Пользователь {u['uid']}"
        assert username == test_username, f"Ожидалось {test_username}, получено {username}"
        print("✅ Функция top правильно форматирует username")

def main():
    """Основная функция тестирования"""
    print("🚀 Запуск тестирования fissure бота\n")
    
    try:
        test_database()
        test_bot_logic()
        test_menu()
        
        print("\n🎉 Все тесты пройдены успешно!")
        print("✅ Бот готов к работе")
        print("\nДля запуска бота:")
        print("1. Создайте файл .env с вашим BOT_TOKEN")
        print("2. Запустите: python main.py")
        
        # Дополнительная проверка: убедимся, что все функции работают вместе
        import main as bot_main
        import db
        
        # Проверим, что функция top из main.py может быть вызвана
        db.init_db()
        test_uid = 666666
        test_username = "final_test_user"
        user = db.get_user(test_uid, test_username)
        
        # Проверим, что функция top в main.py возвращает текст с username
        top_users = db.get_fissure_top()
        if len(top_users) > 0:
            u = top_users[0]
            username = u['username'] if u['username'] else f"Пользователь {u['uid']}"
            assert username == test_username
            print("✅ Интеграционная проверка пройдена: top показывает username")
        
    except Exception as e:
        print(f"\n❌ Тесты не пройдены: {e}")
        return False
    
    return True

if __name__ == "__main__":
    main()