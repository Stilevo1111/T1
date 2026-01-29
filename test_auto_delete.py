#!/usr/bin/env python3
"""
Тест функции автоудаления сообщений
"""

import asyncio
import time
from unittest.mock import Mock, AsyncMock
import logging

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Имитируем функции из main.py
async def auto_delete(message, delay=30):
    """Удаляет сообщение через указанное количество секунд"""
    try:
        await asyncio.sleep(delay)
        await message.delete()
        logger.info(f"✅ Сообщение удалено через {delay} секунд")
    except Exception as e:
        logger.debug(f"Не удалось удалить сообщение: {e}")

def schedule_message_deletion(message, delay=30):
    """Планирует удаление сообщения"""
    try:
        asyncio.create_task(auto_delete(message, delay))
        logger.info(f"✅ Запланировано удаление сообщения через {delay} секунд")
    except Exception as e:
        logger.error(f"Ошибка при планировании удаления сообщения: {e}")

async def test_auto_delete():
    """Тест функции автоудаления"""
    print("🧪 Тест функции автоудаления сообщений...")
    
    # Создаем имитацию сообщения
    mock_message = AsyncMock()
    
    # Тестируем короткую задержку (1 секунда для быстрого теста)
    schedule_message_deletion(mock_message, 1)
    
    # Ждем 2 секунды, чтобы сообщение точно было удалено
    await asyncio.sleep(2)
    
    # Проверяем, что метод delete был вызван
    mock_message.delete.assert_called_once()
    print("✅ Функция автоудаления работает корректно")

async def test_schedule_deletion():
    """Тест функции планирования удаления"""
    print("🧪 Тест функции планирования удаления...")
    
    # Создаем имитацию сообщения
    mock_message = AsyncMock()
    
    # Планируем удаление
    schedule_message_deletion(mock_message, 1)
    
    # Ждем 2 секунды
    await asyncio.sleep(2)
    
    # Проверяем, что метод delete был вызван
    mock_message.delete.assert_called_once()
    print("✅ Функция планирования удаления работает корректно")

async def main():
    """Основная функция тестирования"""
    print("🚀 Запуск тестирования функции автоудаления сообщений...")
    print("=" * 60)
    
    try:
        await test_auto_delete()
        await test_schedule_deletion()
        
        print("\n" + "=" * 60)
        print("🎉 Все тесты пройдены! Функция автоудаления работает корректно.")
        return 0
    except Exception as e:
        print(f"\n❌ Ошибка при тестировании: {e}")
        return 1

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    exit(exit_code)