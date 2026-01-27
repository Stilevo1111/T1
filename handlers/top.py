"""Обработчик команды /top для рейтинга фиссур"""

import logging
from telegram import Update
from telegram.ext import ContextTypes

from database import get_fissure_top

logger = logging.getLogger(__name__)

async def top(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /top - показывает рейтинг по длине фиссуры"""
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
        logger.error(f"Ошибка в команде /top: {e}")
        if update and update.message:
            await update.message.reply_text("❌ Произошла ошибка. Попробуйте позже.")