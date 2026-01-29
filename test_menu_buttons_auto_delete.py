#!/usr/bin/env python3
"""
Тест удаления сообщений от кнопок меню
"""

import asyncio
import logging
from unittest.mock import Mock, AsyncMock, patch
from telegram import Update, Message, User, Chat
from telegram.ext import ContextTypes

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Импортируем функции из main.py
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from main import menu_handler, schedule_message_deletion

class MockMessage:
    """Мок сообщения"""
    def __init__(self, text, message_id=123):
        self.text = text
        self.message_id = message_id
        self.delete = AsyncMock()

class MockUser:
    """Мок пользователя"""
    def __init__(self, user_id=123456789, username="test_user"):
        self.id = user_id
        self.username = username

class MockChat:
    """Мок чата"""
    def __init__(self, chat_id=987654321):
        self.id = chat_id

class MockUpdate:
    """Мок обновления"""
    def __init__(self, message_text, user_id=123456789, username="test_user", chat_id=987654321):
        self.message = MockMessage(message_text)
        self.effective_user = MockUser(user_id, username)
        self.effective_chat = MockChat(chat_id)

class MockContext:
    """Мок контекста"""
    def __init__(self):
        pass

async def test_menu_buttons_auto_delete():
    """Тест удаления сообщений от кнопок меню"""
    print("🧪 Тест удаления сообщений от кнопок меню...")
    
    # Тестируем все кнопки меню
    test_cases = [
        "📈 Увеличить фиссуру",
        "📏 Моя длина", 
        "🏆 Топ"
    ]
    
    for button_text in test_cases:
        print(f"  📊 Тест кнопки: '{button_text}'")
        
        # Создаем моки
        update = MockUpdate(button_text)
        context = MockContext()
        
        # Мокаем функции базы данных
        with patch('main.get_user') as mock_get_user:
            mock_get_user.return_value = {
                'telegram_id': 123456789,
                'username': 'test_user',
                'fissure': 5.0,
                'last_fissure': 0
            }
            
            # Мокаем schedule_message_deletion
            with patch('main.schedule_message_deletion') as mock_schedule_delete:
                try:
                    await menu_handler(update, context)
                    
                    # Проверяем, что schedule_message_deletion был вызван для сообщения от кнопки
                    mock_schedule_delete.assert_called_with(update.message, 10)
                    print(f"    ✅ Сообщение от кнопки '{button_text}' будет удалено через 10 секунд")
                    
                except Exception as e:
                    print(f"    ❌ Ошибка при тестировании кнопки '{button_text}': {e}")
                    return False
    
    print("  ✅ Все кнопки меню используют автоудаление сообщений")
    return True

async def test_menu_buttons_auto_delete_with_errors():
    """Тест удаления сообщений от кнопок меню при ошибках"""
    print("\n🧪 Тест удаления сообщений от кнопок меню при ошибках...")
    
    # Тестируем случай с ошибкой
    update = MockUpdate("📈 Увеличить фиссуру")
    context = MockContext()
    
    # Мокаем функции базы данных с ошибкой
    with patch('main.get_user') as mock_get_user:
        mock_get_user.side_effect = Exception("Database error")
        
        # Мокаем schedule_message_deletion
        with patch('main.schedule_message_deletion') as mock_schedule_delete:
            try:
                await menu_handler(update, context)
                
                # Проверяем, что schedule_message_deletion был вызван для сообщения от кнопки
                mock_schedule_delete.assert_called_with(update.message, 10)
                print("    ✅ Сообщение от кнопки удалено даже при ошибке")
                
            except Exception as e:
                print(f"    ❌ Ошибка при тестировании: {e}")
                return False
    
    print("  ✅ Сообщения от кнопок удаляются даже при ошибках")
    return True

async def main():
    """Основная функция тестирования"""
    print("🚀 Запуск тестирования удаления сообщений от кнопок меню...")
    print("=" * 60)
    
    # Тест 1: Удаление сообщений от кнопок меню
    test1_passed = await test_menu_buttons_auto_delete()
    
    # Тест 2: Удаление сообщений при ошибках
    test2_passed = await test_menu_buttons_auto_delete_with_errors()
    
    print("\n" + "=" * 60)
    print("📊 Результаты тестирования:")
    
    if test1_passed:
        print("✅ Тест удаления сообщений от кнопок: ПРОЙДЕН")
    else:
        print("❌ Тест удаления сообщений от кнопок: ПРОВАЛЕН")
    
    if test2_passed:
        print("✅ Тест удаления сообщений при ошибках: ПРОЙДЕН")
    else:
        print("❌ Тест удаления сообщений при ошибках: ПРОВАЛЕН")
    
    if test1_passed and test2_passed:
        print("\n🎉 Все тесты пройдены! Сообщения от кнопок меню корректно удаляются.")
        return 0
    else:
        print("\n⚠️  Некоторые тесты не пройдены. Проверьте логи.")
        return 1

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    exit(exit_code)