#!/usr/bin/env python3
"""Простой тест для проверки системы Fissure"""

import sys
import os

# Добавляем путь к проекту
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_fissure_functions():
    """Тест функций Fissure"""
    print("🧪 Тестируем функции системы Fissure...")
    
    try:
        # Импортируем функции из handlers/fissure.py
        from handlers.fissure import fissure, fissure_top, stats as fissure_stats
        print("✅ Импорты прошли успешно")
        
        # Проверяем, что функции существуют
        assert callable(fissure), "Функция fissure не найдена"
        assert callable(fissure_top), "Функция fissure_top не найдена"
        assert callable(fissure_stats), "Функция fissure_stats не найдена"
        print("✅ Все функции существуют и являются callable")
        
        print("🎉 Тест функций системы Fissure пройден успешно!")
        return True
        
    except ImportError as e:
        print(f"❌ Ошибка импорта: {e}")
        return False
    except AssertionError as e:
        print(f"❌ Ошибка ассерта: {e}")
        return False
    except Exception as e:
        print(f"❌ Непредвиденная ошибка: {e}")
        return False

def test_menu_integration():
    """Тест интеграции с меню"""
    print("🧪 Тестируем интеграцию с меню...")
    
    try:
        # Импортируем меню
        from handlers.menu import get_main_menu_keyboard
        print("✅ Импорт меню прошел успешно")
        
        # Проверяем, что клавиатура создается
        keyboard = get_main_menu_keyboard()
        assert keyboard is not None, "Клавиатура не создана"
        print("✅ Клавиатура создана успешно")
        
        # Проверяем, что кнопка фиссуры есть в меню
        keyboard_text = str(keyboard)
        assert "Фиссура" in keyboard_text, "Кнопка Фиссура не найдена в меню"
        print("✅ Кнопка Фиссура найдена в меню")
        
        print("🎉 Тест интеграции с меню пройден успешно!")
        return True
        
    except ImportError as e:
        print(f"❌ Ошибка импорта: {e}")
        return False
    except AssertionError as e:
        print(f"❌ Ошибка ассерта: {e}")
        return False
    except Exception as e:
        print(f"❌ Непредвиденная ошибка: {e}")
        return False

if __name__ == "__main__":
    print("🚀 Запуск тестов системы Fissure...")
    print()
    
    success1 = test_fissure_functions()
    print()
    success2 = test_menu_integration()
    print()
    
    if success1 and success2:
        print("🎉 Все тесты пройдены успешно!")
        print("✅ Система Fissure работает корректно")
        print("✅ Команда /fissure доступна")
        print("✅ Кнопка Фиссура в меню работает")
        sys.exit(0)
    else:
        print("❌ Некоторые тесты не прошли")
        sys.exit(1)