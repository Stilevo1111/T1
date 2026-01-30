#!/usr/bin/env python3
"""
Простой скрипт для локального запуска Telegram бота "Фиссура"
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
        
        # Проверяем наличие токена
        TOKEN = os.getenv("BOT_TOKEN")
        if not TOKEN:
            print("⚠️  ВНИМАНИЕ: BOT_TOKEN не найден!")
            print("   Бот не сможет отправлять сообщения в Telegram.")
            print("   Для полноценной работы:")
            print("   1. Создайте Telegram бота у @BotFather")
            print("   2. Получите BOT_TOKEN")
            print("   3. Добавьте его в переменные окружения: set BOT_TOKEN=ваш_токен")
            print()
            print("   Для тестирования базы данных запустите: python test_bot.py")
            print()
        else:
            print("✅ BOT_TOKEN найден")
            
        print("🤖 Запуск бота...")
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
