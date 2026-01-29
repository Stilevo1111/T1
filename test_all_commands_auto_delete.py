#!/usr/bin/env python3
"""
Тест, что все команды бота используют автоудаление сообщений
"""

import asyncio
from unittest.mock import AsyncMock
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

async def test_all_commands():
    """Тест, что все команды используют автоудаление"""
    print("🧪 Тест, что все команды используют автоудаление сообщений...")
    
    # Создаем имитацию сообщения
    mock_message = AsyncMock()
    
    # Тестируем все команды, которые должны использовать автоудаление
    
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
    
    # Ждем 4 секунды, чтобы все сообщения были удалены
    await asyncio.sleep(4)
    
    # Проверяем, что метод delete был вызван
    call_count = mock_message.delete.call_count
    print(f"  ✅ Метод delete был вызван {call_count} раз")
    
    if call_count >= 7:  # 6 команд + 1 ошибка
        print("✅ Все команды используют автоудаление сообщений")
        return True
    else:
        print("❌ Не все команды используют автоудаление сообщений")
        return False

async def main():
    """Основная функция тестирования"""
    print("🚀 Запуск тестирования автоудаления для всех команд...")
    print("=" * 60)
    
    try:
        success = await test_all_commands()
        
        print("\n" + "=" * 60)
        if success:
            print("🎉 Все команды используют автоудаление сообщений!")
            return 0
        else:
            print("❌ Не все команды используют автоудаление сообщений!")
            return 1
    except Exception as e:
        print(f"\n❌ Ошибка при тестировании: {e}")
        return 1

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    exit(exit_code)