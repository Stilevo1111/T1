import os
import asyncio
import logging
from typing import Dict, Any
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    MessageHandler,
    filters,
    CallbackQueryHandler,
    Application
)

from config import BOT_TOKEN, RENDER_URL, PORT
from database import init_db

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Импортируем систему регистрации обработчиков
from handlers.register_handlers import register_all_handlers

# Импортируем меню
from handlers.menu import handle_menu_callback
# Импортируем обработчики сообщений
from handlers.messages import handle_message

# ================= ENTRY POINT =================

def create_application() -> Application:
    """Создает и настраивает приложение бота"""
    try:
        app = ApplicationBuilder().token(BOT_TOKEN).post_init(init_db).build()
        logger.info("Приложение бота создано успешно")
        return app
    except Exception as e:
        logger.error(f"Ошибка создания приложения: {e}")
        raise

def setup_handlers(app: Application) -> None:
    """Настраивает обработчики команд и сообщений"""
    try:
        # Регистрация всех систем через модульную систему
        register_all_handlers(app)
        
        # Callback-обработчик для интерактивного меню
        app.add_handler(CallbackQueryHandler(handle_menu_callback))
        
        # Общий обработчик текстовых сообщений
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        
        logger.info("Обработчики настроены успешно")
    except Exception as e:
        logger.error(f"Ошибка настройки обработчиков: {e}")
        raise

def run_webhook(app: Application) -> None:
    """Запускает бота в режиме webhook"""
    try:
        webhook_path = f"webhook/{BOT_TOKEN}"
        webhook_url = f"{RENDER_URL.rstrip('/')}/{webhook_path}"
        
        app.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=webhook_path,
            webhook_url=webhook_url,
            drop_pending_updates=True,
        )
        logger.info(f"Бот запущен в режиме webhook: {webhook_url}")
    except Exception as e:
        logger.error(f"Ошибка запуска webhook: {e}")
        raise

if __name__ == "__main__":
    try:
        logger.info("Запуск бота...")
        application = create_application()
        setup_handlers(application)
        run_webhook(application)
    except KeyboardInterrupt:
        logger.info("Бот остановлен пользователем")
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}")
        raise