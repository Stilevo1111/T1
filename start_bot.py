#!/usr/bin/env python3
"""
Альтернативный скрипт для запуска бота на Render
Использует более стабильный способ управления event loop
"""

import os
import sys
import asyncio
import logging
from main import main

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

def main_render():
    """Главная функция для запуска бота на Render"""
    try:
        # Проверяем наличие токена
        token = os.getenv("BOT_TOKEN")
        if not token:
            logger.error("❌ BOT_TOKEN не задан в переменных окружения!")
            sys.exit(1)
        
        logger.info("🚀 Запуск бота для Render...")
        
        # Создаем новый event loop для Render
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            # Запускаем основную функцию
            loop.run_until_complete(main())
        except KeyboardInterrupt:
            logger.info("✋ Бот остановлен пользователем")
        except Exception as e:
            logger.error(f"❌ Ошибка в работе бота: {e}", exc_info=True)
            raise
        finally:
            # Закрываем event loop
            loop.close()
            
    except Exception as e:
        logger.error(f"❌ Критическая ошибка при запуске: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main_render()