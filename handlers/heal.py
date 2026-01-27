"""Обработчики команд, связанных с лечением"""

import logging
import time
from typing import Dict, Any
from telegram import Update
from telegram.ext import ContextTypes

from database import get_user, update_user
from game_logic import regenerate_hp, calculate_character_stats

logger = logging.getLogger(__name__)

async def heal(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /heal"""
    try:
        username = update.effective_user.username or update.effective_user.full_name
        user = await get_user(update.effective_user.id, username)
        stats = calculate_character_stats(user)
        
        # Регенерация HP
        new_hp, last_heal = regenerate_hp(user)
        if new_hp != user["hp"]:
            await update_user(update.effective_user.id, hp=new_hp, last_heal=last_heal)
            msg = await update.message.reply_text(f"💚 HP восстановлено до {new_hp}/{stats['max_hp']}")
        else:
            msg = await update.message.reply_text("💚 HP уже восстановлено")
    except Exception as e:
        logger.error(f"Ошибка в команде /heal: {e}")
        await update.message.reply_text("❌ Произошла ошибка. Попробуйте позже.")

