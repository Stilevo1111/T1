#!/usr/bin/env python3
"""
Простой скрипт для запуска Telegram бота "Фиссура"
"""

import os
import sys
import asyncio
import logging
from database import init_db

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

def main():
    """Запуск бота в локальном режиме"""
    print("🚀 Запуск Telegram бота 'Фиссура'...")
    print("💡 Для тестирования бот будет использовать SQLite базу данных")
    print("💡 Вам не нужно настраивать переменные окружения")
    print()
    
    try:
        # Инициализируем базу данных
        print("📦 Инициализация базы данных...")
        init_db()
        print("✅ База данных готова")
        print()
        
        # Запускаем основной бот
        print("🤖 Запуск бота...")
        print("⚠️  Для полноценной работы вам понадобится:")
        print("   1. Создать Telegram бота у @BotFather")
        print("   2. Получить BOT_TOKEN")
        print("   3. Добавить его в переменные окружения BOT_TOKEN")
        print()
        print("Нажмите Ctrl+C для остановки бота")
        print("-" * 50)
        
        # Импортируем и запускаем основной модуль
        from main import main_polling as run_bot
        
        # Создаем новый event loop для избежания конфликтов
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        # Запускаем бота
        loop.run_until_complete(run_bot())
        
    except KeyboardInterrupt:
        print("\n🛑 Бот остановлен пользователем")
        sys.exit(0)
    except Exception as e:
        print(f"❌ Ошибка запуска бота: {e}")
        print()
        print("💡 Советы по решению проблем:")
        print("1. Убедитесь, что установлены все зависимости: pip install -r requirements.txt")
        print("2. Проверьте, что Python версии 3.8 или выше")
        print("3. Убедитесь, что у вас есть действительный BOT_TOKEN")
        print("4. Проверьте настройки переменных окружения")
        sys.exit(1)

if __name__ == "__main__":
    main()