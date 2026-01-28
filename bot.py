#!/usr/bin/env python3
"""
Fissure Bot - Telegram бот для игры в трещины и PvP
"""

import logging
import os
import sys
import asyncio
from datetime import datetime, timedelta

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from config import BOT_TOKEN, PORT, RENDER_URL, validate_config, logger
from database import init_db, get_user, update_user, get_top_by_stat, get_fissure_top, update_fissure
from handlers import fissure, stats, pvp, handle_pvp_fight_callback, fight
from handlers.fissure import register_fissure_handlers
from handlers.pvp_system import register_pvp_handlers
from handlers.stats import register_stats_handlers
from game_logic import calculate_character_stats, get_fissure_result, get_user_progress, get_next_level_exp

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

logger = logging.getLogger(__name__)

# Глобальные переменные
bot_start_time = datetime.now()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка команды /start"""
    user = update.effective_user
    user_data = await get_user(user.id, user.username or user.first_name)
    
    if user_data:
        await update.message.reply_text(
            f"Добро пожаловать обратно, {user.first_name}!\n"
            f"Ваш уровень: {user_data['level']}\n"
            f"Ваш MMR: {user_data['mmr']}\n"
            f"Ваша фиссура: {user_data['fissure']} см\n"
            f"Используйте /help для просмотра доступных команд."
        )
    else:
        await update.message.reply_text(
            f"Добро пожаловать, {user.first_name}!\n"
            "Вы успешно зарегистрированы в системе.\n"
            "Используйте /help для просмотра доступных команд."
        )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка команды /help"""
    help_text = """
🎮 <b>Доступные команды:</b>

<b>Основные команды:</b>
/start - Зарегистрироваться в боте
/help - Показать это сообщение
/stats - Проверка длины фиссуры
/fissure - Пройти трещину (раз в 24 часа)

<b>PvP команды:</b>
/pvp - Поиск PvP противника
/fight - Быстрый бой с рандомным противником

<b>Рейтинги:</b>
/top_mmr - Топ игроков по MMR
/top - Топ игроков по длине фиссуры
"""
    await update.message.reply_text(help_text, parse_mode='HTML')

async def info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Информация о боте"""
    global bot_start_time
    uptime = datetime.now() - bot_start_time
    hours, remainder = divmod(int(uptime.total_seconds()), 3600)
    minutes, seconds = divmod(remainder, 60)
    days, hours = divmod(hours, 24)
    
    info_text = f"""
🤖 <b>Fissure Bot</b>

<b>Статистика:</b>
• Время работы: {days}д {hours}ч {minutes}м
• Версия: 1.0.0
• Разработчик: @hidlor

<b>Описание:</b>
Это Telegram бот для игры в трещины и PvP бои.
• Проходите трещины для увеличения длины
• Сражайтесь с другими игроками в PvP
• Прокачивайте своего персонажа
• Соревнуйтесь в рейтингах

<b>Команды:</b> Используйте /help для просмотра всех команд.
"""
    await update.message.reply_text(info_text, parse_mode='HTML')

async def top_mmr(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Топ игроков по MMR"""
    top_users = await get_top_by_stat('mmr', 10)
    if not top_users:
        await update.message.reply_text("Таблица рейтинга пока пуста.")
        return
    
    message = "🏆 <b>Топ игроков по MMR:</b>\n\n"
    for i, user in enumerate(top_users, 1):
        message += f"{i}. {user['username']} - {user['mmr']} MMR\n"
    
    await update.message.reply_text(message, parse_mode='HTML')

async def top_level(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Топ игроков по уровню"""
    top_users = await get_top_by_stat('level', 10)
    if not top_users:
        await update.message.reply_text("Таблица уровней пока пуста.")
        return
    
    message = "🔝 <b>Топ игроков по уровню:</b>\n\n"
    for i, user in enumerate(top_users, 1):
        message += f"{i}. {user['username']} - {user['level']} уровень\n"
    
    await update.message.reply_text(message, parse_mode='HTML')

async def top_fissure(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Топ игроков по длине фиссуры"""
    top_users = await get_fissure_top(10)
    if not top_users:
        await update.message.reply_text("Таблица фиссур пока пуста.")
        return
    
    message = "📏 <b>Топ игроков по длине фиссуры:</b>\n\n"
    for i, user in enumerate(top_users, 1):
        message += f"{i}. {user['username']} - {user['fissure']} см\n"
    
    await update.message.reply_text(message, parse_mode='HTML')

async def register_handlers(application: Application):
    """Регистрация всех обработчиков"""
    # Основные команды
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("info", info))
    
    # Рейтинги
    application.add_handler(CommandHandler("top_mmr", top_mmr))
    application.add_handler(CommandHandler("top_level", top_level))
    application.add_handler(CommandHandler("top", top_fissure))
    
    # Регистрация обработчиков из модулей
    register_fissure_handlers(application)
    register_pvp_handlers(application)
    register_stats_handlers(application)

async def main():
    """Основная функция запуска бота"""
    # Проверка конфигурации
    if not validate_config():
        logger.error("Конфигурация не прошла валидацию. Завершение работы.")
        sys.exit(1)
    
    # Создание приложения
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Инициализация базы данных
    await init_db(application)
    
    # Регистрация обработчиков
    await register_handlers(application)
    
    # Запуск бота
    if RENDER_URL:
        # Запуск вебхука для Render
        await application.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            webhook_url=f"{RENDER_URL}/webhook",
            drop_pending_updates=True
        )
    else:
        # Запуск polling для локальной разработки
        await application.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)

if __name__ == '__main__':
    try:
        # Запуск бота через asyncio.run() - это правильный способ для асинхронных функций
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен вручную")
    except Exception as e:
        logger.error(f"Ошибка при запуске бота: {e}")
        sys.exit(1)
