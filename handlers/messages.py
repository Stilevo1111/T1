"""Обработчики текстовых сообщений"""

import logging
from typing import Dict, Any
from telegram import Update
from telegram.ext import ContextTypes, filters

from handlers.main import start, stats, profile
from handlers.fissure import fissure, fissure_top, stats as fissure_stats
from handlers.boss import boss, attack
from handlers.shop import shop, show_category_items, buy, potion
from handlers.pvp import pvp, handle_pvp_fight_callback, fight
from handlers.top import top
from handlers.talents import talents, learn_talent, stats_distribute, add_stat, level_up_handler, achievements
from handlers.talents import add_str, add_agi, add_int, learn, level_up, handle_talents_category, handle_talents_stats, handle_talents_main, handle_learn_talent_callback
from handlers.heal import heal

from utils.validators import validate_talent_id, validate_user_id

logger = logging.getLogger(__name__)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик текстовых сообщений"""
    try:
        text = update.message.text
        user_id = update.effective_user.id
        
        if text == "👹 BOSS":
            await boss(update, context)
        elif text == "🛒 SHOP":
            await shop(update, context)
        elif text == "⚔️ PVP":
            await pvp(update, context)
        elif text == "🏆 TOP":
            await top(update, context)
        elif text == "👤 ПРОФИЛЬ":
            await profile(update, context)
        elif text == "📊 STATS":
            await stats(update, context)
        elif text == "🍆 FISSURE":
            await update.message.reply_text("🍆 Меню фиссуры", reply_markup=None)  # Нужно импортировать FISSURE_KEYBOARD
        elif text == "🎲 ROLL":
            await fissure(update, context)
        elif text == "⬅️ НАЗАД":
            await update.message.reply_text("⬅️ Вернулись в главное меню", reply_markup=None)  # Нужно импортировать MAIN_KEYBOARD
        # Обработка категорий магазина
        elif text == "👟 Сапоги":
            await show_category_items(update, context, "Сапоги")
        elif text == "🛡️ Броня":
            await show_category_items(update, context, "Броня")
        elif text == "🗡️ Оружие":
            await show_category_items(update, context, "Оружие")
        elif text == "🛡️ Защита":
            await show_category_items(update, context, "Защита")
        elif text == "🔮 Поддержка":
            await show_category_items(update, context, "Поддержка")
        elif text == "🧪 Зелья":
            await show_category_items(update, context, "Зелья")
        else:
            await update.message.reply_text(
                f"Неизвестная команда. Используйте кнопки меню ниже.",
                reply_markup=None  # Нужно импортировать MAIN_KEYBOARD
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
                if validate_user_id(enemy_id):
                    await fight(update, context)
                else:
                    await update.message.reply_text("❌ Неверный ID противника")
            except ValueError:
                await update.message.reply_text("❌ Неверный ID противника")
    except Exception as e:
        logger.error(f"Ошибка в handle_pvp_buttons: {e}")
        await update.message.reply_text("❌ Произошла ошибка. Попробуйте позже.")
