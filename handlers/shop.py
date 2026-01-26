"""Обработчики команд, связанных с магазином"""

import logging
from typing import Dict, Any
from telegram import Update
from telegram.ext import ContextTypes

from database import get_user, update_user
from game_logic import get_items_by_category, get_item_description, get_potion_data
from utils.keyboard import SHOP_CATEGORIES_KEYBOARD

logger = logging.getLogger(__name__)

async def shop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /shop"""
    try:
        msg = await update.message.reply_text("🛒 Выберите категорию:", reply_markup=SHOP_CATEGORIES_KEYBOARD)
        context.application.create_task(
            auto_delete(context, update.effective_chat.id, [msg.message_id])
        )
    except Exception as e:
        logger.error(f"Ошибка в команде /shop: {e}")
        await update.message.reply_text("❌ Произошла ошибка. Попробуйте позже.")

async def show_category_items(update: Update, context: ContextTypes.DEFAULT_TYPE, category: str) -> None:
    """Показывает предметы в выбранной категории"""
    try:
        items_in_category = get_items_by_category(category)
        if not items_in_category:
            await update.message.reply_text("❌ В этой категории нет предметов")
            return
        
        text = f"🛒 {category}:\n\n"
        for item_name, item_data in items_in_category.items():
            text += f"🗡️ {item_name}\n"
            text += f"   💰 {item_data['gold']}g\n"
            if 'description' in item_data:
                text += f"   📖 {item_data['description']}\n"
            if 'dmg' in item_data:
                text += f"   ⚔️ +{item_data['dmg']} урона\n"
            if 'str' in item_data:
                text += f"   💪 +{item_data['str']} силы\n"
            if 'agi' in item_data:
                text += f"   🏃‍♂️ +{item_data['agi']} ловкости\n"
            if 'int' in item_data:
                text += f"   🧠 +{item_data['int']} интеллекта\n"
            if 'hp' in item_data:
                text += f"   ❤️ +{item_data['hp']} HP\n"
            if 'crit' in item_data:
                text += f"   🎯 +{item_data['crit']}% крита\n"
            if 'dodge' in item_data:
                text += f"   🛡️ +{item_data['dodge']}% уклонения\n"
            if 'heal' in item_data:
                text += f"   💚 +{item_data['heal']} HP\n"
            if 'exp' in item_data:
                text += f"   📚 +{item_data['exp']} опыта\n"
            text += "\n"
        text += "/buy ITEM — купить предмет"
        await update.message.reply_text(text)
    except Exception as e:
        logger.error(f"Ошибка в show_category_items: {e}")
        await update.message.reply_text("❌ Произошла ошибка. Попробуйте позже.")

async def buy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /buy"""
    try:
        username = update.effective_user.username or update.effective_user.full_name
        user = await get_user(update.effective_user.id, username)
        stats = calculate_character_stats(user)
        
        try:
            item_name = context.args[0] if context.args else None
        except:
            await update.message.reply_text("❌ Укажите предмет для покупки")
            return

        if item_name not in get_items_by_category("Все"):
            await update.message.reply_text("❌ Нет такого предмета")
            return

        item_data = get_items_by_category("Все")[item_name]
        cost = item_data["gold"]
        
        if user["gold"] < cost:
            await update.message.reply_text("💰 Мало золота")
            return

        # Проверка слотов
        items = user["items"] if user["items"] else [None] * 6
        if None not in items:
            await update.message.reply_text("🎒 Слоты заняты")
            return

        # Покупка предмета
        items[items.index(None)] = item_name
        await update_user(update.effective_user.id, items=items, gold=user["gold"] - cost)
        msg = await update.message.reply_text(f"✅ Куплен {item_name}")
        context.application.create_task(
            auto_delete(context, update.effective_chat.id, [msg.message_id])
        )
    except Exception as e:
        logger.error(f"Ошибка в команде /buy: {e}")
        await update.message.reply_text("❌ Произошла ошибка. Попробуйте позже.")

async def potion(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /potion"""
    try:
        username = update.effective_user.username or update.effective_user.full_name
        user = await get_user(update.effective_user.id, username)
        stats = calculate_character_stats(user)
        
        try:
            potion_type = context.args[0] if context.args else None
        except:
            await update.message.reply_text("❌ Укажите тип зелья (Minor/Major/Ultimate)")
            return

        potion_data = get_potion_data(potion_type)
        if not potion_data:
            await update.message.reply_text("❌ Нет такого зелья")
            return

        cost = potion_data["gold"]
        
        if user["gold"] < cost:
            await update.message.reply_text("💰 Мало золота")
            return

        # Покупка зелья
        new_hp = min(user["hp"] + potion_data["heal"], stats["max_hp"])
        await update_user(update.effective_user.id, hp=new_hp, gold=user["gold"] - cost)
        msg = await update.message.reply_text(f"🧪 {potion_type} зелье использовано. HP восстановлено")
        context.application.create_task(
            auto_delete(context, update.effective_chat.id, [msg.message_id])
        )
    except Exception as e:
        logger.error(f"Ошибка в команде /potion: {e}")
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

# Импортируем calculate_character_stats для использования в buy и potion
from game_logic import calculate_character_stats