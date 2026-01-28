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
    
    # Тестируем создание пользователя
    test_uid = 999999
    user = db.get_user(test_uid)
    assert user['uid'] == test_uid
    assert user['fissure'] == 0.1
    assert user['last_fissure'] == 0
    print("✅ Пользователь создан")
    
    # Тестируем обновление данных
    new_fissure = 5.5
    new_time = int(time.time())
    db.update_fissure(test_uid, new_fissure, new_time)
    
    user_updated = db.get_user(test_uid)
    assert user_updated['fissure'] == new_fissure
    assert user_updated['last_fissure'] == new_time
    print("✅ Данные пользователя обновлены")
    
    # Тестируем получение топа
    top = db.get_fissure_top()
    assert len(top) >= 1
    assert top[0]['uid'] == test_uid
    assert top[0]['fissure'] == new_fissure
    print("✅ Таблица лидеров работает")

def test_bot_logic():
    """Тестируем логику бота"""
    print("\n🎮 Тестируем игровую логику...")
    
    import main
    
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

def test_menu():
    """Тестируем меню"""
    print("\n📱 Тестируем меню...")
    
    import main
    
    menu = main.main_menu()
    assert menu is not None
    print("✅ Меню создается корректно")

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
        
    except Exception as e:
        print(f"\n❌ Тесты не пройдены: {e}")
        return False
    
    return True

if __name__ == "__main__":
    main()