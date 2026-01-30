#!/usr/bin/env python3
"""
Тестирование подключения к PostgreSQL базе данных
"""

import os
import sys
import logging
from database import get_connection, init_db, get_user, update_fissure, get_fissure_top

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_postgresql_connection():
    """Тест подключения к PostgreSQL"""
    print("🚀 Тестирование подключения к PostgreSQL...")
    
    # Проверяем наличие DATABASE_URL
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("❌ DATABASE_URL не задан")
        return False
    
    print(f"✅ DATABASE_URL найден: {database_url[:50]}...")
    
    try:
        # Тестируем соединение
        conn = get_connection()
        if conn:
            print("✅ Подключение к базе данных установлено")
            
            # Проверяем тип базы данных
            if database_url.startswith("postgresql://"):
                print("✅ Используется PostgreSQL")
            else:
                print("⚠️  Используется SQLite")
            
            conn.close()
            return True
        else:
            print("❌ Не удалось установить соединение")
            return False
            
    except Exception as e:
        print(f"❌ Ошибка подключения: {e}")
        return False

def test_database_operations():
    """Тест операций с базой данных"""
    print("\n🧪 Тестирование операций с базой данных...")
    
    try:
        # Инициализация базы данных
        init_db()
        print("✅ База данных инициализирована")
        
        # Тест добавления пользователя
        test_user = get_user(123456789, "test_user")
        print(f"✅ Пользователь добавлен: {test_user}")
        
        # Тест обновления данных
        update_fissure(123456789, 0.5, 1234567890)
        print("✅ Данные пользователя обновлены")
        
        # Тест получения топа
        top_users = get_fissure_top(5)
        print(f"✅ Топ пользователей получен: {len(top_users)} пользователей")
        
        return True
        
    except Exception as e:
        print(f"❌ Ошибка операций с БД: {e}")
        return False

def test_data_persistence():
    """Тест сохранения данных между перезапусками"""
    print("\n💾 Тест сохранения данных...")
    
    try:
        # Добавляем тестового пользователя
        test_user = get_user(999999999, "persistence_test")
        print(f"✅ Тестовый пользователь добавлен: {test_user}")
        
        # Обновляем данные
        update_fissure(999999999, 1.5, 9999999999)
        print("✅ Данные обновлены")
        
        # Получаем пользователя снова (имитация перезапуска)
        test_user_2 = get_user(999999999, "persistence_test")
        print(f"✅ Пользователь получен после 'перезапуска': {test_user_2}")
        
        # Проверяем, что данные сохранились
        if test_user_2['fissure'] == 1.5 and test_user_2['last_fissure'] == 9999999999:
            print("✅ Данные успешно сохранены между перезапусками")
            return True
        else:
            print("❌ Данные не сохранились правильно")
            return False
            
    except Exception as e:
        print(f"❌ Ошибка теста сохранения: {e}")
        return False

def main():
    """Основная функция тестирования"""
    print("🧪 Запуск тестов PostgreSQL подключения")
    print("=" * 50)
    
    # Тест подключения
    connection_ok = test_postgresql_connection()
    
    if not connection_ok:
        print("\n❌ Тесты не пройдены - нет подключения к базе данных")
        return False
    
    # Тест операций
    operations_ok = test_database_operations()
    
    # Тест сохранения данных
    persistence_ok = test_data_persistence()
    
    print("\n" + "=" * 50)
    print("📊 Результаты тестов:")
    print(f"✅ Подключение к PostgreSQL: {'Пройдено' if connection_ok else 'Провалено'}")
    print(f"✅ Операции с базой данных: {'Пройдено' if operations_ok else 'Провалено'}")
    print(f"✅ Сохранение данных: {'Пройдено' if persistence_ok else 'Провалено'}")
    
    if connection_ok and operations_ok and persistence_ok:
        print("\n🎉 Все тесты пройдены успешно!")
        return True
    else:
        print("\n❌ Некоторые тесты провалены")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)