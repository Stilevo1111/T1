"""Обработчики основных команд"""

import logging
from typing import Dict, Any
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ContextTypes

from database import get_user
from game_logic import calculate_character_stats, get_user_progress, get_next_level_exp
from utils.formatters import format_stats_text
from utils.keyboard import MAIN_KEYBOARD, FISSURE_KEYBOARD

logger = logging.getLogger(__name__)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /start"""
    try:
        username = update.effective_user.username or update.effective_user.full_name
        user = await get_user(update.effective_user.id, username)
        stats = calculate_character_stats(user)
        progress = get_user_progress(user)
        next_level_exp = get_next_level_exp(user["level"])
        
        # Импортируем меню
        from handlers.menu import get_main_menu_keyboard
        
        msg = await update.message.reply_text(
            f"🌟 Добро пожаловать в Fissure Bot, {user['username']}!\n\n"
            f"🎮 *Ваш персонаж:*\n"
            f"• Уровень: {user['level']}\n"
            f"• Опыт: {user['exp']}/{next_level_exp}\n"
            f"• Золото: {user['gold']}\n"
            f"• Fissure: {user['fissure']:.1f} см\n\n"
            f"📋 *Выберите действие:*",
            reply_markup=get_main_menu_keyboard(),
            parse_mode='Markdown'
        )
        # Автоудаление ответа
        context.application.create_task(
            auto_delete(context, update.effective_chat.id, [msg.message_id])
        )
    except Exception as e:
        logger.error(f"Ошибка в команде /start: {e}")
        await update.message.reply_text("❌ Произошла ошибка. Попробуйте позже.")

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /stats"""
    try:
        username = update.effective_user.username or update.effective_user.full_name
        user = await get_user(update.effective_user.id, username)
        stats = calculate_character_stats(user)
        
        msg = await update.message.reply_text(
            f"📊 Твоя Фиссура:\n📏 {user['fissure']:.1f} см",
            reply_markup=FISSURE_KEYBOARD
        )
        context.application.create_task(
            auto_delete(context, update.effective_chat.id, [msg.message_id])
        )
    except Exception as e:
        logger.error(f"Ошибка в команде /stats: {e}")
        await update.message.reply_text("❌ Произошла ошибка. Попробуйте позже.")

async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /profile"""
    try:
        username = update.effective_user.username or update.effective_user.full_name
        user = await get_user(update.effective_user.id, username)
        stats = calculate_character_stats(user)
        
        text = format_stats_text(user, stats)
        msg = await update.message.reply_text(text)
        context.application.create_task(
            auto_delete(context, update.effective_chat.id, [msg.message_id])
        )
    except Exception as e:
        logger.error(f"Ошибка в команде /profile: {e}")
        await update.message.reply_text("❌ Произошла ошибка. Попробуйте позже.")


async def auto_delete(context: ContextTypes.DEFAULT_TYPE, chat_id: int, msg_ids: list) -> None:
    """Автоматическое удаление сообщений через заданное время"""
    import asyncio
    await asyncio.sleep(30)  # 30 секунд
    for msg_id in msg_ids:
        try:
            await context.bot.delete_message(chat_id, msg_id)
        except Exception:
            pass