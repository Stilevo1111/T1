#!/usr/bin/env python3
"""Тест для проверки меню Fissure"""

import sys
import os

# Добавляем путь к проекту
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_fissure_menu():
    """Тест меню Fissure"""
    print("🧪 Тестируем меню Fissure...")
    
    try:
        # Импортируем меню Fissure
        from handlers.fissure_menu import get_fissure_menu_keyboard, register_fissure_menu_handlers
        print("✅ Импорт меню Fissure прошел успешно")
        
        # Проверяем, что клавиатура создается
        keyboard = get_fissure_menu_keyboard()
        assert keyboard is not None, "Клавиатура Fissure не создана"
        print("✅ Клавиатура Fissure создана успешно")
        
        # Проверяем, что кнопки есть в меню
        keyboard_text = str(keyboard)
        assert "РОЛЛ" in keyboard_text, "Кнопка РОЛЛ не найдена в меню"
        assert "ТОП" in keyboard_text, "Кнопка ТОП не найдена в меню"
        assert "СТАТИСТИКА" in keyboard_text, "Кнопка СТАТИСТИКА не найдена в меню"
        print("✅ Все кнопки найдены в меню Fissure")
        
        # Проверяем callback-данные
        assert "fissure_roll" in keyboard_text, "Callback fissure_roll не найден"
        assert "fissure_top_menu" in keyboard_text, "Callback fissure_top_menu не найден"
        assert "fissure_stats_menu" in keyboard_text, "Callback fissure_stats_menu не найден"
        print("✅ Все callback-данные найдены")
        
        print("🎉 Тест меню Fissure пройден успешно!")
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

def test_fissure_menu_integration():
    """Тест интеграции меню Fissure с основным меню"""
    print("🧪 Тестируем интеграцию меню Fissure с основным меню...")
    
    try:
        # Импортируем основное меню
        from handlers.menu import get_main_menu_keyboard
        print("✅ Импорт основного меню прошел успешно")
        
        # Проверяем, что кнопка Фиссура есть в основном меню
        keyboard = get_main_menu_keyboard()
        keyboard_text = str(keyboard)
        assert "Фиссура" in keyboard_text, "Кнопка Фиссура не найдена в основном меню"
        print("✅ Кнопка Фиссура найдена в основном меню")
        
        # Проверяем callback
        assert "fissure" in keyboard_text, "Callback fissure не найден в основном меню"
        print("✅ Callback fissure найден в основном меню")
        
        print("🎉 Тест интеграции меню Fissure пройден успешно!")
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
    print("🚀 Запуск тестов меню Fissure...")
    print()
    
    success1 = test_fissure_menu()
    print()
    success2 = test_fissure_menu_integration()
    print()
    
    if success1 and success2:
        print("🎉 Все тесты пройдены успешно!")
        print("✅ Меню Fissure работает корректно")
        print("✅ Кнопки РОЛЛ, ТОП, СТАТИСТИКА доступны")
        print("✅ Интеграция с основным меню работает")
        sys.exit(0)
    else:
        print("❌ Некоторые тесты не прошли")
        sys.exit(1)