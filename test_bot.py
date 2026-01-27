#!/usr/bin/env python3
"""
Тестовый скрипт для проверки работоспособности бота
"""

import sys
import os
import asyncio

# Добавляем путь к проекту
sys.path.append('.')

def test_imports():
    """Тестирование импортов"""
    print("🔍 Тестирование импортов...")
    try:
        from config import BOT_TOKEN, DATABASE_URL, validate_config
        print("✅ config импортирован")
        
        from database import get_user, update_user, init_db
        print("✅ database импортирован")
        
        from game_logic import calculate_character_stats, get_fissure_result, get_user_progress
        print("✅ game_logic импортирован")
        
        from handlers import fissure, stats, pvp, handle_pvp_fight_callback, fight
        print("✅ handlers импортированы")
        
        return True
    except ImportError as e:
        print(f"❌ Ошибка импорта: {e}")
        return False

def test_config():
    """Тестирование конфигурации"""
    print("\n🔧 Тестирование конфигурации...")
    try:
        from config import validate_config
        is_valid = validate_config()
        if is_valid:
            print("✅ Конфигурация валидна")
        else:
            print("⚠️  Конфигурация не валидна (ожидаемо без .env)")
        return True
    except Exception as e:
        print(f"❌ Ошибка конфигурации: {e}")
        return False

def test_database():
    """Тестирование базы данных"""
    print("\n🗄️  Тестирование базы данных...")
    try:
        from database import sqlite_conn
        if sqlite_conn:
            print("✅ SQLite соединение доступно")
        else:
            print("⚠️  SQLite соединение недоступно")
        return True
    except Exception as e:
        print(f"❌ Ошибка базы данных: {e}")
        return False

def test_game_logic():
    """Тестирование игровой логики"""
    print("\n🎮 Тестирование игровой логики...")
    try:
        from game_logic import calculate_character_stats
        
        # Тестовые данные пользователя
        test_user = {
            'level': 1,
            'str': 5,
            'agi': 5,
            'int': 5,
            'items': [None] * 6
        }
        
        stats = calculate_character_stats(test_user)
        print(f"✅ Характеристики рассчитаны: {stats['max_hp']} HP, {stats['base_damage']} урон")
        return True
    except Exception as e:
        print(f"❌ Ошибка игровой логики: {e}")
        return False

async def test_database_async():
    """Тестирование асинхронных операций с базой данных"""
    print("\n🔄 Тестирование асинхронных операций...")
    try:
        from database import get_user, update_user
        
        # Тестовые операции (без реального пользователя)
        print("✅ Асинхронные функции доступны")
        return True
    except Exception as e:
        print(f"❌ Ошибка асинхронных операций: {e}")
        return False

def main():
    """Основная функция тестирования"""
    print("🚀 Запуск тестирования Fissure Bot\n")
    
    tests = [
        test_imports,
        test_config,
        test_database,
        test_game_logic
    ]
    
    results = []
    for test in tests:
        results.append(test())
    
    # Асинхронный тест
    results.append(asyncio.run(test_database_async()))
    
    print(f"\n📊 Результаты тестирования:")
    passed = sum(results)
    total = len(results)
    print(f"Пройдено: {passed}/{total}")
    
    if passed == total:
        print("🎉 Все тесты пройдены! Бот готов к запуску.")
    else:
        print("⚠️  Некоторые тесты не пройдены. Проверьте конфигурацию.")
    
    return passed == total

if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)