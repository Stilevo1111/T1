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

# Импортируем обработчики из модулей
from handlers.main import start, stats, profile
from handlers.fissure import fissure, stats as fissure_stats
from handlers.boss import boss
from handlers.shop import shop, show_category_items, buy, potion
from handlers.pvp import pvp, handle_pvp_fight_callback, fight
from handlers.top import top
from handlers.talents import talents, learn_talent, add_stat, level_up_handler, achievements
from handlers.talents import add_str, add_agi, add_int, learn, level_up, handle_talents_category, handle_talents_stats, handle_talents_main, handle_learn_talent_callback
from handlers.heal import heal
from handlers.messages import handle_message, handle_pvp_buttons

# Импортируем систему регистрации
from handlers.register_handlers import register_all_handlers

# Импортируем меню
from handlers.menu import handle_menu_callback

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
        # Регистрация всех систем
        register_all_handlers(app)
        
        # Основные команды
        app.add_handler(CommandHandler("start", start))
        app.add_handler(CommandHandler("stats", stats))
        app.add_handler(CommandHandler("profile", profile))
        app.add_handler(CommandHandler("boss", boss))
        app.add_handler(CommandHandler("shop", shop))
        app.add_handler(CommandHandler("buy", buy))
        app.add_handler(CommandHandler("potion", potion))
        app.add_handler(CommandHandler("heal", heal))
        app.add_handler(CommandHandler("pvp", pvp))
        app.add_handler(CommandHandler("fight", fight))
        app.add_handler(CommandHandler("fissure", fissure))
        app.add_handler(CommandHandler("top", top))
        app.add_handler(CommandHandler("talents", talents))
        app.add_handler(CommandHandler("level", level_up_handler))
        app.add_handler(CommandHandler("achievements", achievements))
        app.add_handler(CommandHandler("add_str", add_str))
        app.add_handler(CommandHandler("add_agi", add_agi))
        app.add_handler(CommandHandler("add_int", add_int))
        app.add_handler(CommandHandler("learn", learn))
        app.add_handler(CommandHandler("level_up", level_up))

        # Callback-обработчики для inline-кнопок
        app.add_handler(CallbackQueryHandler(handle_learn_talent_callback, pattern=r'^learn_'))
        app.add_handler(CallbackQueryHandler(handle_pvp_fight_callback, pattern=r'^fight_'))
        app.add_handler(CallbackQueryHandler(
            lambda update, context: show_category_items(update, context, update.callback_query.data), 
            pattern=r'^(boots|armor|weapon|defense|support|potions)$'
        ))
        
        # Callback-обработчик для интерактивного меню
        app.add_handler(CallbackQueryHandler(handle_menu_callback))

        # Текстовые обработчики
        app.add_handler(MessageHandler(
            filters.TEXT & filters.Regex(r'^/learn_[a-z0-9]+$'), 
            lambda update, context: learn_talent(update, context, update.message.text.replace("/learn_", ""))
        ))
        
        app.add_handler(MessageHandler(
            filters.TEXT & filters.Regex(r'^(👟 Сапоги|🛡️ Броня|🗡️ Оружие|🛡️ Защита|🔮 Поддержка|🧪 Зелья)$'), 
            lambda update, context: show_category_items(update, context, update.message.text)
        ))
        
        app.add_handler(MessageHandler(
            filters.TEXT & filters.Regex(r'^/fight_\d+$'), 
            handle_pvp_buttons
        ))
        
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
