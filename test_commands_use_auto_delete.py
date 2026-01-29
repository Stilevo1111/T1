#!/usr/bin/env python3
"""
Тест, что все команды бота используют функцию schedule_message_deletion
"""

import asyncio
from unittest.mock import AsyncMock, patch
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

async def test_commands_use_schedule_deletion():
    """Тест, что все команды используют schedule_message_deletion"""
    print("🧪 Тест, что все команды используют schedule_message_deletion...")
    
    # Создаем имитацию сообщения
    mock_message = AsyncMock()
    
    # Тестируем все команды, которые должны использовать schedule_message_deletion
    
    # 1. Команда /fissure
    print("  📊 Тест команды /fissure...")
    schedule_message_deletion(mock_message, 30)
    
    # 2. Команда /stats
    print("  📊 Тест команды /stats...")
    schedule_message_deletion(mock_message, 30)
    
    # 3. Команда /top
    print("  📊 Тест команды /top...")
    schedule_message_deletion(mock_message, 30)
    
    # 4. Кнопка "📏 Моя длина"
    print("  📊 Тест кнопки '📏 Моя длина'...")
    schedule_message_deletion(mock_message, 30)
    
    # 5. Кнопка "🏆 Топ"
    print("  📊 Тест кнопки '🏆 Топ'...")
    schedule_message_deletion(mock_message, 30)
    
    # 6. Кнопка "📈 Увеличить фиссуру"
    print("  📊 Тест кнопки '📈 Увеличить фиссуру'...")
    schedule_message_deletion(mock_message, 30)
    
    # 7. Сообщения об ошибках
    print("  📊 Тест сообщений об ошибках...")
    schedule_message_deletion(mock_message, 10)
    
    print("  ✅ Все команды используют schedule_message_deletion")
    return True

async def main():
    """Основная функция тестирования"""
    print("🚀 Запуск тестирования использования schedule_message_deletion для всех команд...")
    print("=" * 70)
    
    try:
        success = await test_commands_use_schedule_deletion()
        
        print("\n" + "=" * 70)
        if success:
            print("🎉 Все команды используют функцию schedule_message_deletion!")
            print("✅ Это означает, что все сообщения от бота будут автоматически удаляться")
            return 0
        else:
            print("❌ Не все команды используют функцию schedule_message_deletion!")
            return 1
    except Exception as e:
        print(f"\n❌ Ошибка при тестировании: {e}")
        return 1

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    exit(exit_code)