"""Обработчики команд, связанных с фиссурой"""

import logging
import time
from typing import Dict, Any
from telegram import Update
from telegram.ext import ContextTypes

from database import get_user, get_fissure_top, update_fissure
from game_logic import get_fissure_result, get_meme_message
from utils.formatters import format_stats_text
from utils.keyboard import FISSURE_KEYBOARD

logger = logging.getLogger(__name__)

# Константы
COOLDOWN = 86400  # 24 часа в секундах
AUTO_DELETE_DELAY = 30  # секунд

async def fissure(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /fissure - рандомная игра"""
    try:
        username = update.effective_user.username or update.effective_user.full_name
        user = await get_user(update.effective_user.id, username)
        now = time.time()
        remaining = COOLDOWN - (now - user["last_fissure"])
        
        if remaining > 0:
            hours = int(remaining // 3600)
            minutes = int((remaining % 3600) // 60)
            msg = await update.message.reply_text(
                f"⏳ Через {hours} ч. {minutes} мин."
            )
        else:
            # Получаем текущую длину фиссуры пользователя
            current_length = user["fissure"]
            new_value, text, phrase = get_fissure_result_with_length(current_length)
            await update_fissure(update.effective_user.id, new_value, now)
            msg = await update.message.reply_text(
                f"{text}\n{phrase}\n📏 Теперь {new_value:.1f} см"
            )
    except Exception as e:
        logger.error(f"Ошибка в команде /fissure: {e}")
        if update and update.message:
            await update.message.reply_text("❌ Произошла ошибка. Попробуйте позже.")

async def fissure_top(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /fissure_top"""
    try:
        rows = await get_fissure_top()
        if not rows:
            await update.message.reply_text("Топ пуст 😢")
        else:
            text = ["🏆 ТОП по длине фиссуры:\n"]
            for i, row in enumerate(rows, 1):
                text.append(f"{i}. 👤 {row['username']} — {row['fissure']:.1f} см")
            await update.message.reply_text("\n".join(text))
    except Exception as e:
        logger.error(f"Ошибка в команде /fissure_top: {e}")
        if update and update.message:
            await update.message.reply_text("❌ Произошла ошибка. Попробуйте позже.")

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /stats для фиссуры"""
    try:
        username = update.effective_user.username or update.effective_user.full_name
        user = await get_user(update.effective_user.id, username)
        stats = calculate_character_stats(user)
        
        msg = await update.message.reply_text(
            f"📊 Твоя Фиссура:\n📏 {user['fissure']:.1f} см",
            reply_markup=FISSURE_KEYBOARD
        )
    except Exception as e:
        logger.error(f"Ошибка в команде /stats (fissure): {e}")
        if update and update.message:
            await update.message.reply_text("❌ Произошла ошибка. Попробуйте позже.")


# Импортируем calculate_character_stats для использования в stats
from game_logic import calculate_character_stats



