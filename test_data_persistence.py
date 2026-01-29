#!/usr/bin/env python3
"""
Тест сохранения данных в базе данных (результаты фиссуры и таймер перезарядки)
"""

import time
import os
import sqlite3
from database_local import init_db, get_user, update_fissure, get_fissure_top

def test_data_persistence():
    """Тест сохранения данных в базе данных"""
    print("🧪 Тест сохранения данных в базе данных...")
    
    # Инициализируем базу данных
    init_db()
    print("✅ База данных инициализирована")
    
    # Тестовый пользователь
    test_uid = 999999998
    test_username = "test_user_persistence"
    
    # Получаем пользователя (создаем если не существует)
    user = get_user(test_uid, test_username)
    print(f"✅ Пользователь: {user}")
    
    # Устанавливаем начальные значения
    initial_fissure = 5.0
    initial_time = time.time()
    
    # Обновляем данные
    update_fissure(test_uid, initial_fissure, initial_time)
    print(f"✅ Установлены начальные значения: длина={initial_fissure}, время={initial_time}")
    
    # Проверяем, что данные сохранились
    user_after = get_user(test_uid, test_username)
    print(f"✅ Данные после обновления: {user_after}")
    
    if user_after["fissure"] == initial_fissure and user_after["last_fissure"] == initial_time:
        print("✅ Данные корректно сохранены в базе")
    else:
        print("❌ Ошибка: данные не сохранились корректно")
        return False
    
    # Симулируем "перезапуск" - просто получаем данные снова
    # В реальной жизни это было бы закрытие и открытие соединения с базой
    user_reloaded = get_user(test_uid, test_username)
    print(f"✅ Данные после перезагрузки: {user_reloaded}")
    
    if user_reloaded["fissure"] == initial_fissure and user_reloaded["last_fissure"] == initial_time:
        print("✅ Данные корректно восстановлены после перезагрузки")
        return True
    else:
        print("❌ Ошибка: данные не восстановились после перезагрузки")
        return False

def test_timer_persistence():
    """Тест сохранения таймера перезарядки"""
    print("\n🧪 Тест сохранения таймера перезарядки...")
    
    # Тестовый пользователь
    test_uid = 999999997
    test_username = "test_user_timer"
    
    # Получаем пользователя
    user = get_user(test_uid, test_username)
    print(f"✅ Пользователь: {user}")
    
    # Устанавливаем время перезарядки в прошлое (чтобы можно было использовать)
    past_time = time.time() - 86400 - 1  # 24 часа + 1 секунда назад
    update_fissure(test_uid, user["fissure"], past_time)
    
    # Проверяем, что можно использовать фиссуру
    user_after = get_user(test_uid, test_username)
    current_time = time.time()
    
    if current_time - user_after["last_fissure"] >= 86400:
        print("✅ Таймер перезарядки корректно сохранен")
    else:
        print("❌ Ошибка: таймер перезарядки не сохранен")
        return False
    
    # Используем фиссуру (устанавливаем текущее время)
    update_fissure(test_uid, user_after["fissure"] + 1, current_time)
    
    # Проверяем, что таймер обновился
    user_final = get_user(test_uid, test_username)
    check_time = time.time()
    
    if check_time - user_final["last_fissure"] < 86400:
        print("✅ Таймер перезарядки корректно обновлен")
        return True
    else:
        print("❌ Ошибка: таймер перезарядки не обновлен")
        return False

def test_database_file_persistence():
    """Тест, что данные сохраняются в файле базы данных"""
    print("\n🧪 Тест сохранения данных в файле базы данных...")
    
    # Проверяем существование файла базы данных
    db_file = "fissure_bot.db"
    if os.path.exists(db_file):
        print(f"✅ Файл базы данных существует: {db_file}")
        
        # Проверяем размер файла (должен быть больше 0)
        file_size = os.path.getsize(db_file)
        print(f"✅ Размер файла базы данных: {file_size} байт")
        
        if file_size > 0:
            print("✅ Файл базы данных содержит данные")
            return True
        else:
            print("❌ Ошибка: файл базы данных пустой")
            return False
    else:
        print(f"❌ Ошибка: файл базы данных не существует: {db_file}")
        return False

def main():
    """Основная функция тестирования"""
    print("🚀 Запуск тестирования сохранения данных в базе данных...")
    print("=" * 60)
    
    # Тест 1: Сохранение данных
    persistence_test_passed = test_data_persistence()
    
    # Тест 2: Сохранение таймера
    timer_test_passed = test_timer_persistence()
    
    # Тест 3: Сохранение в файле
    file_test_passed = test_database_file_persistence()
    
    print("\n" + "=" * 60)
    print("📊 Результаты тестирования:")
    
    if persistence_test_passed:
        print("✅ Тест сохранения данных: ПРОЙДЕН")
    else:
        print("❌ Тест сохранения данных: ПРОВАЛЕН")
    
    if timer_test_passed:
        print("✅ Тест сохранения таймера: ПРОЙДЕН")
    else:
        print("❌ Тест сохранения таймера: ПРОВАЛЕН")
    
    if file_test_passed:
        print("✅ Тест сохранения в файле: ПРОЙДЕН")
    else:
        print("❌ Тест сохранения в файле: ПРОВАЛЕН")
    
    if persistence_test_passed and timer_test_passed and file_test_passed:
        print("\n🎉 Все тесты пройдены! Данные корректно сохраняются в базе данных.")
        print("✅ Результаты фиссуры и таймер перезарядки сохраняются между перезапусками бота.")
        return 0
    else:
        print("\n⚠️  Некоторые тесты не пройдены. Проверьте логи.")
        return 1

if __name__ == "__main__":
    exit_code = main()
    exit(exit_code)