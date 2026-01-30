#!/usr/bin/env python3
"""
Тест удаления сообщений от команд /fissure, /top, /stats
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

from main import fissure, stats, top, schedule_message_deletion

class MockMessage:
    """Мок сообщения"""
    def __init__(self, text, message_id=123):
        self.text = text
        self.message_id = message_id
        self.reply_text = AsyncMock()

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
    def __init__(self, user_id=123456789, username="test_user", chat_id=987654321):
        self.effective_user = MockUser(user_id, username)
        self.effective_chat = MockChat(chat_id)
        self.message = MockMessage("test message")

class MockContext:
    """Мок контекста"""
    def __init__(self):
        pass

async def test_fissure_command_auto_delete():
    """Тест удаления сообщений от команды /fissure"""
    print("🧪 Тест удаления сообщений от команды /fissure...")
    
    # Создаем моки
    update = MockUpdate()
    context = MockContext()
    
    # Мокаем функции базы данных
    with patch('main.get_user') as mock_get_user:
        mock_get_user.return_value = {
            'telegram_id': 123456789,
            'username': 'test_user',
            'fissure': 5.0,
            'last_fissure': 0
        }
        
        with patch('main.update_fissure') as mock_update_fissure:
            # Мокаем schedule_message_deletion
            with patch('main.schedule_message_deletion') as mock_schedule_delete:
                try:
                    await fissure(update, context)
                    
                    # Проверяем, что schedule_message_deletion был вызван для ответного сообщения
                    mock_schedule_delete.assert_called_with(update.message.reply_text.return_value, 30)
                    print("    ✅ Сообщение от команды /fissure будет удалено через 30 секунд")
                    
                except Exception as e:
                    print(f"    ❌ Ошибка при тестировании команды /fissure: {e}")
                    return False
    
    return True

async def test_stats_command_auto_delete():
    """Тест удаления сообщений от команды /stats"""
    print("\n🧪 Тест удаления сообщений от команды /stats...")
    
    # Создаем моки
    update = MockUpdate()
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
                await stats(update, context)
                
                # Проверяем, что schedule_message_deletion был вызван для ответного сообщения
                mock_schedule_delete.assert_called_with(update.message.reply_text.return_value, 30)
                print("    ✅ Сообщение от команды /stats будет удалено через 30 секунд")
                
            except Exception as e:
                print(f"    ❌ Ошибка при тестировании команды /stats: {e}")
                return False
    
    return True

async def test_top_command_auto_delete():
    """Тест удаления сообщений от команды /top"""
    print("\n🧪 Тест удаления сообщений от команды /top...")
    
    # Создаем моки
    update = MockUpdate()
    context = MockContext()
    
    # Мокаем функции базы данных
    with patch('main.get_fissure_top') as mock_get_top:
        mock_get_top.return_value = [
            {'telegram_id': 123456789, 'username': 'test_user', 'fissure': 10.0},
            {'telegram_id': 987654321, 'username': 'another_user', 'fissure': 8.0}
        ]
        
        # Мокаем schedule_message_deletion
        with patch('main.schedule_message_deletion') as mock_schedule_delete:
            try:
                await top(update, context)
                
                # Проверяем, что schedule_message_deletion был вызван для ответного сообщения
                mock_schedule_delete.assert_called_with(update.message.reply_text.return_value, 30)
                print("    ✅ Сообщение от команды /top будет удалено через 30 секунд")
                
            except Exception as e:
                print(f"    ❌ Ошибка при тестировании команды /top: {e}")
                return False
    
    return True

async def test_commands_auto_delete_with_errors():
    """Тест удаления сообщений от команд при ошибках"""
    print("\n🧪 Тест удаления сообщений от команд при ошибках...")
    
    # Тестируем все команды с ошибками
    commands = [
        ("fissure", fissure),
        ("stats", stats),
        ("top", top)
    ]
    
    for cmd_name, cmd_func in commands:
        print(f"  📊 Тест команды /{cmd_name} при ошибке...")
        
        # Создаем моки
        update = MockUpdate()
        context = MockContext()
        
        # Мокаем функции базы данных с ошибкой
        if cmd_name == "fissure":
            with patch('main.get_user') as mock_get_user:
                mock_get_user.side_effect = Exception("Database error")
                
                with patch('main.schedule_message_deletion') as mock_schedule_delete:
                    try:
                        await cmd_func(update, context)
                        
                        # Проверяем, что schedule_message_deletion был вызван для сообщения об ошибке
                        mock_schedule_delete.assert_called_with(update.message.reply_text.return_value, 10)
                        print(f"    ✅ Сообщение об ошибке от команды /{cmd_name} будет удалено через 10 секунд")
                        
                    except Exception as e:
                        print(f"    ❌ Ошибка при тестировании команды /{cmd_name}: {e}")
                        return False
        elif cmd_name == "stats":
            with patch('main.get_user') as mock_get_user:
                mock_get_user.side_effect = Exception("Database error")
                
                with patch('main.schedule_message_deletion') as mock_schedule_delete:
                    try:
                        await cmd_func(update, context)
                        
                        # Проверяем, что schedule_message_deletion был вызван для сообщения об ошибке
                        mock_schedule_delete.assert_called_with(update.message.reply_text.return_value, 10)
                        print(f"    ✅ Сообщение об ошибке от команды /{cmd_name} будет удалено через 10 секунд")
                        
                    except Exception as e:
                        print(f"    ❌ Ошибка при тестировании команды /{cmd_name}: {e}")
                        return False
        elif cmd_name == "top":
            with patch('main.get_fissure_top') as mock_get_top:
                mock_get_top.side_effect = Exception("Database error")
                
                with patch('main.schedule_message_deletion') as mock_schedule_delete:
                    try:
                        await cmd_func(update, context)
                        
                        # Проверяем, что schedule_message_deletion был вызван для сообщения об ошибке
                        mock_schedule_delete.assert_called_with(update.message.reply_text.return_value, 10)
                        print(f"    ✅ Сообщение об ошибке от команды /{cmd_name} будет удалено через 10 секунд")
                        
                    except Exception as e:
                        print(f"    ❌ Ошибка при тестировании команды /{cmd_name}: {e}")
                        return False
    
    return True

async def main():
    """Основная функция тестирования"""
    print("🚀 Запуск тестирования удаления сообщений от команд...")
    print("=" * 60)
    
    # Тест 1: Удаление сообщений от команды /fissure
    test1_passed = await test_fissure_command_auto_delete()
    
    # Тест 2: Удаление сообщений от команды /stats
    test2_passed = await test_stats_command_auto_delete()
    
    # Тест 3: Удаление сообщений от команды /top
    test3_passed = await test_top_command_auto_delete()
    
    # Тест 4: Удаление сообщений при ошибках
    test4_passed = await test_commands_auto_delete_with_errors()
    
    print("\n" + "=" * 60)
    print("📊 Результаты тестирования:")
    
    if test1_passed:
        print("✅ Тест команды /fissure: ПРОЙДЕН")
    else:
        print("❌ Тест команды /fissure: ПРОВАЛЕН")
    
    if test2_passed:
        print("✅ Тест команды /stats: ПРОЙДЕН")
    else:
        print("❌ Тест команды /stats: ПРОВАЛЕН")
    
    if test3_passed:
        print("✅ Тест команды /top: ПРОЙДЕН")
    else:
        print("❌ Тест команды /top: ПРОВАЛЕН")
    
    if test4_passed:
        print("✅ Тест команд при ошибках: ПРОЙДЕН")
    else:
        print("❌ Тест команд при ошибках: ПРОВАЛЕН")
    
    if test1_passed and test2_passed and test3_passed and test4_passed:
        print("\n🎉 Все тесты пройдены! Сообщения от команд корректно удаляются.")
        return 0
    else:
        print("\n⚠️  Некоторые тесты не пройдены. Проверьте логи.")
        return 1

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    exit(exit_code)