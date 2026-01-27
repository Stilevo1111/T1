#!/usr/bin/env python3
"""Тест для проверки интеграции системы Fissure"""

import asyncio
import sys
import os

# Добавляем путь к проекту
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

async def test_fissure_integration():
    """Тест интеграции системы Fissure"""
    print("🧪 Тестируем интеграцию системы Fissure...")
    
    try:
        # Импортируем необходимые модули
        from handlers.fissure import fissure, fissure_top, stats as fissure_stats
        from handlers.system_registrars import register_fissure_handlers
        from telegram.ext import Application
        
        print("✅ Импорты прошли успешно")
        
        # Проверяем, что функции существуют
        assert callable(fissure), "Функция fissure не найдена или не является callable"
        assert callable(fissure_top), "Функция fissure_top не найдена или не является callable"
        assert callable(fissure_stats), "Функция fissure_stats не найдена или не является callable"
        print("✅ Все функции существуют и являются callable")
        
        # Проверяем регистрацию обработчиков
        app = Application.builder().token("test_token").build()
        register_fissure_handlers(app)
        print("✅ Обработчики Fissure зарегистрированы успешно")
        
        # Проверяем, что обработчики добавлены
        handlers = app.handlers
        command_handlers = []
        for handler_list in handlers.values():
            for handler in handler_list:
                if hasattr(handler, 'command'):
                    command_handlers.extend(handler.command)
        
        assert 'fissure' in command_handlers, "Команда /fissure не зарегистрирована"
        assert 'fissure_top' in command_handlers, "Команда /fissure_top не зарегистрирована"
        assert 'stats' in command_handlers, "Команда /stats не зарегистрирована"
        print("✅ Все команды Fissure зарегистрированы")
        
        print("🎉 Тест интеграции системы Fissure пройден успешно!")
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
    success = asyncio.run(test_fissure_integration())
    sys.exit(0 if success else 1)