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
        
        msg = await update.message.reply_text(
            f"🎮 {user['username']}, ты в игре\n"
            f"Уровень: {user['level']} (Опыт: {user['exp']}/{next_level_exp})\n"
            f"HP: {user['hp']}/{stats['max_hp']}\n"
            f"STR: {stats['str_total']} | AGI: {stats['agi_total']} | INT: {stats['int_total']}\n"
            f"Gold: {user['gold']} | MMR: {user['mmr']}\n"
            f"🍆 Fissure: {user['fissure']:.1f} см\n\n"
            "Команды:\n"
            "/boss — посмотреть босса\n"
            "/attack — атаковать босса\n"
            "/shop — магазин\n"
            "/buy ITEM — купить предмет\n"
            "/potion TYPE — купить зелье\n"
            "/heal — восстановить HP\n"
            "/pvp — PvP\n"
            "/fight USER_ID — вызов на дуэль\n"
            "/top — таблица лидеров\n"
            "/fissure — ролл фиссуры\n"
            "/stats — статистика",
            reply_markup=MAIN_KEYBOARD,
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

async def debug_boss(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Отладочная информация о боссе"""
    try:
        user = await get_user(update.effective_user.id, "")
        text = f"""
📊 ДЕБАГ ИНФОРМАЦИЯ:
👤 Пользователь: {user['username']}
❤️ HP игрока: {user['hp']}/{user['hp_max']}
👹 Босс: {user['boss_name']}
❤️ HP босса: {user['boss_hp']}/{user['boss_max']}
📊 Уровень босса: {user['boss_level']}
⚡ Способности: {user.get('boss_ability', 'Нет')}
🗡️ Общий урон по боссу: {user['boss_dmg']}
"""
        await update.message.reply_text(text)
    except Exception as e:
        logger.error(f"Ошибка в debug_boss: {e}")
        await update.message.reply_text("❌ Произошла ошибка.")

async def auto_delete(context: ContextTypes.DEFAULT_TYPE, chat_id: int, msg_ids: list) -> None:
    """Автоматическое удаление сообщений через заданное время"""
    import asyncio
    await asyncio.sleep(30)  # 30 секунд
    for msg_id in msg_ids:
        try:
            await context.bot.delete_message(chat_id, msg_id)
        except Exception:
            pass