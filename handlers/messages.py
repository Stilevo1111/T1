"""Обработчики текстовых сообщений"""

import logging
from typing import Dict, Any
from telegram import Update
from telegram.ext import ContextTypes, filters

from handlers.main import start, stats, profile
from handlers.fissure import fissure, stats as fissure_stats
from handlers.boss import boss
from handlers.pvp_system import pvp, handle_pvp_fight_callback, fight


logger = logging.getLogger(__name__)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик текстовых сообщений - только для системных команд"""
    try:
        text = update.message.text
        user_id = update.effective_user.id
        
        # Оставляем только системные команды, удаляем текстовый интерфейс
        if text == "/start":
            await start(update, context)
        elif text == "/stats":
            await stats(update, context)
        elif text == "/profile":
            await profile(update, context)
        elif text == "/fissure":
            await fissure(update, context)
        elif text == "/boss":
            await boss(update, context)
        elif text == "/shop":
            await update.message.reply_text("Магазин в разработке")
        elif text == "/pvp":
            await pvp(update, context)
        elif text == "/top":
            await update.message.reply_text("Топ игроков в разработке")
        elif text == "/talents":
            await update.message.reply_text("Таланты в разработке")
        elif text == "/heal":
            await update.message.reply_text("Лечение в разработке")
        else:
            await update.message.reply_text(
                "Для управления ботом используйте кнопки меню.\n"
                "Доступные команды: /start, /profile, /stats, /fissure, /boss, /pvp, /shop, /top, /talents, /heal"
            )
    except Exception as e:
        logger.error(f"Ошибка в handle_message: {e}")
        await update.message.reply_text("❌ Произошла ошибка. Попробуйте позже.")

async def handle_pvp_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик кнопок PvP из списка противников"""
    try:
        text = update.message.text
        if text.startswith("/fight_"):
            try:
                enemy_id = int(text.replace("/fight_", ""))
                await fight(update, context)
            except ValueError:
                await update.message.reply_text("❌ Неверный ID противника")
    except Exception as e:
        logger.error(f"Ошибка в handle_pvp_buttons: {e}")
        await update.message.reply_text("❌ Произошла ошибка. Попробуйте позже.")
