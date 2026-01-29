import os
import asyncio
import logging
from telegram.ext import Application
import sys

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    stream=sys.stdout
)

logger = logging.getLogger(__name__)

async def main():
    """Основная функция запуска бота"""
    try:
        # Получаем переменные окружения
        TOKEN = os.getenv("BOT_TOKEN")
        RENDER_URL = os.getenv("RENDER_EXTERNAL_URL")
        
        if not TOKEN:
            logger.error("❌ TELEGRAM_BOT_TOKEN не установлен")
            return
        
        if not RENDER_URL:
            logger.error("❌ RENDER_EXTERNAL_URL не установлен")
            # На Render эта переменная должна быть автоматически
            # Для локальной разработки используем значение по умолчанию
            RENDER_URL = f"http://localhost:{os.getenv('PORT', 10000)}"
        
        WEBHOOK_URL = f"{RENDER_URL}/webhook"
        
        logger.info(f"🚀 Запуск бота...")
        logger.info(f"🌐 Webhook URL: {WEBHOOK_URL}")
        
        # Создаем приложение
        application = Application.builder().token(TOKEN).build()
        
        # Регистрируем обработчики команд
        from handlers import register_handlers
        register_handlers(application)
        
        # Инициализируем базу данных
        from database import init_db
        init_db()
        
        # Удаляем старый webhook и устанавливаем новый
        await application.bot.delete_webhook(drop_pending_updates=True)
        await application.bot.set_webhook(
            url=WEBHOOK_URL,
            secret_token=os.getenv("WEBHOOK_SECRET", "")
        )
        logger.info("✅ Webhook установлен")
        
        # Запускаем webhook сервер
        port = int(os.getenv("PORT", 10000))
        logger.info(f"🔌 Прослушивание порта {port}")
        
        # Используем правильный метод для запуска
        await application.run_webhook(
            listen="0.0.0.0",
            port=port,
            webhook_url=WEBHOOK_URL,
            secret_token=os.getenv("WEBHOOK_SECRET", "")
        )
        
    except Exception as e:
        logger.error(f"❌ Критическая ошибка: {e}", exc_info=True)
        raise

def run_bot():
    """Функция для запуска бота с обработкой событий"""
    try:
        # Создаем новую event loop для каждого запуска
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        # Запускаем основную функцию
        loop.run_until_complete(main())
        
    except KeyboardInterrupt:
        logger.info("🛑 Бот остановлен пользователем")
    except Exception as e:
        logger.error(f"❌ Ошибка при запуске бота: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    run_bot()
