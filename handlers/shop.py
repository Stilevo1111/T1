"""Обработчики команд, связанных с магазином"""

import logging
from typing import Dict, Any
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CallbackQueryHandler

from database import get_user, update_user
from database.real_database import db_manager
from game_logic import get_items_by_category, get_item_description, get_potion_data, calculate_character_stats
from utils.keyboard import SHOP_CATEGORIES_KEYBOARD

logger = logging.getLogger(__name__)

async def shop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /shop"""
    try:
        msg = await update.message.reply_text("🛒 Выберите категорию:", reply_markup=SHOP_CATEGORIES_KEYBOARD)
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
        keyboard = []
        row = []
        
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
            
            # Добавляем кнопку для покупки предмета
            button = InlineKeyboardButton(f"Купить {item_name}", callback_data=f"buy_{item_name}")
            row.append(button)
            
            if len(row) == 2:
                keyboard.append(row)
                row = []
        
        if row:
            keyboard.append(row)
        
        text += "Нажмите на кнопку 'Купить' для покупки предмета"
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(text, reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"Ошибка в show_category_items: {e}")
        await update.message.reply_text("❌ Произошла ошибка. Попробуйте позже.")

async def buy_item_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик нажатия на кнопку покупки предмета"""
    try:
        query = update.callback_query
        await query.answer()
        
        item_name = query.data.replace("buy_", "")
        username = update.effective_user.username or update.effective_user.full_name
        user = await get_user(update.effective_user.id, username)
        stats = calculate_character_stats(user)
        
        if item_name not in get_items_by_category("Все"):
            await query.edit_message_text("❌ Нет такого предмета")
            return

        item_data = get_items_by_category("Все")[item_name]
        cost = item_data["gold"]
        
        if user["gold"] < cost:
            await query.edit_message_text("💰 Мало золота")
            return

        # Проверка слотов в инвентаре
        inventory = await db_manager.get_user_inventory(update.effective_user.id)
        equipped_items = [item['item_id'] for item in inventory if item.get('equipped', 0)]
        
        # Проверяем, есть ли свободные слоты
        if len(equipped_items) >= 6:
            await query.edit_message_text("🎒 Слоты заняты")
            return

        # Покупка предмета через реальную базу данных
        success = await db_manager.add_item_to_inventory(update.effective_user.id, item_name, 1)
        if not success:
            await query.edit_message_text("❌ Ошибка при покупке предмета")
            return

        # Экипируем предмет автоматически
        await db_manager.equip_item(update.effective_user.id, item_name)
        
        # Снимаем золото
        await update_user(update.effective_user.id, gold=user["gold"] - cost)
        
        await query.edit_message_text(f"✅ Куплен и экипирован {item_name} за {cost}g")
    except Exception as e:
        logger.error(f"Ошибка в buy_item_callback: {e}")
        await query.edit_message_text("❌ Произошла ошибка. Попробуйте позже.")

async def buy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /buy для покупки предметов"""
    try:
        username = update.effective_user.username or update.effective_user.full_name
        user = await get_user(update.effective_user.id, username)
        stats = calculate_character_stats(user)
        
        try:
            item_name = context.args[0] if context.args else None
        except:
            await update.message.reply_text("❌ Укажите название предмета")
            return

        if item_name not in get_items_by_category("Все"):
            await update.message.reply_text("❌ Нет такого предмета")
            return

        item_data = get_items_by_category("Все")[item_name]
        cost = item_data["gold"]
        
        if user["gold"] < cost:
            await update.message.reply_text("💰 Мало золота")
            return

        # Проверка слотов в инвентаре
        inventory = await db_manager.get_user_inventory(update.effective_user.id)
        equipped_items = [item['item_id'] for item in inventory if item.get('equipped', 0)]
        
        # Проверяем, есть ли свободные слоты
        if len(equipped_items) >= 6:
            await update.message.reply_text("🎒 Слоты заняты")
            return

        # Покупка предмета через реальную базу данных
        success = await db_manager.add_item_to_inventory(update.effective_user.id, item_name, 1)
        if not success:
            await update.message.reply_text("❌ Ошибка при покупке предмета")
            return

        # Экипируем предмет автоматически
        await db_manager.equip_item(update.effective_user.id, item_name)
        
        # Снимаем золото
        await update_user(update.effective_user.id, gold=user["gold"] - cost)
        msg = await update.message.reply_text(f"✅ Куплен и экипирован {item_name} за {cost}g")
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

        # Покупка зелья через реальную базу данных
        success = await db_manager.add_item_to_inventory(update.effective_user.id, f"{potion_type}_potion", 1)
        if not success:
            await update.message.reply_text("❌ Ошибка при покупке зелья")
            return

        # Снимаем золото
        await update_user(update.effective_user.id, gold=user["gold"] - cost)
        msg = await update.message.reply_text(f"🧪 Куплено {potion_type} зелье за {cost}g")
    except Exception as e:
        logger.error(f"Ошибка в команде /potion: {e}")
        await update.message.reply_text("❌ Произошла ошибка. Попробуйте позже.")

async def use_potion(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /use_potion для использования зелья"""
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

        # Проверяем наличие зелья в инвентаре
        inventory = await db_manager.get_user_inventory(update.effective_user.id)
        potion_found = False
        for item in inventory:
            if item['item_id'] == f"{potion_type}_potion" and item['quantity'] > 0:
                potion_found = True
                break
        
        if not potion_found:
            await update.message.reply_text("❌ У вас нет такого зелья")
            return

        # Используем зелье
        result = await db_manager.use_consumable(update.effective_user.id, f"{potion_type}_potion")
        if not result['success']:
            await update.message.reply_text("❌ Ошибка при использовании зелья")
            return

        effect = result['effect']
        if effect['type'] == 'heal':
            await update.message.reply_text(f"🧪 {potion_type} зелье использовано. Восстановлено {effect['amount']} HP. Текущее HP: {effect['new_hp']}")
        elif effect['type'] == 'mana':
            await update.message.reply_text(f"🧪 {potion_type} зелье использовано. Восстановлено {effect['amount']} маны. Текущая мана: {effect['new_mana']}")
        else:
            await update.message.reply_text(f"🧪 {potion_type} зелье использовано. Эффект: {effect['type']}")
    except Exception as e:
        logger.error(f"Ошибка в команде /use_potion: {e}")
        await update.message.reply_text("❌ Произошла ошибка. Попробуйте позже.")

async def inventory(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /inventory для просмотра инвентаря"""
    try:
        inventory = await db_manager.get_user_inventory(update.effective_user.id)
        if not inventory:
            await update.message.reply_text("🎒 Ваш инвентарь пуст")
            return

        text = "🎒 Ваш инвентарь:\n\n"
        for item in inventory:
            item_name = item['item_id']
            quantity = item['quantity']
            equipped = "✅" if item.get('equipped', 0) else "❌"
            text += f"• {item_name} (x{quantity}) {equipped}\n"

        await update.message.reply_text(text)
    except Exception as e:
        logger.error(f"Ошибка в команде /inventory: {e}")
        await update.message.reply_text("❌ Произошла ошибка. Попробуйте позже.")


# Регистрация обработчиков колбэков
def register_shop_callbacks(app):
    """Регистрация обработчиков колбэков для магазина"""
    app.add_handler(CallbackQueryHandler(buy_item_callback, pattern=r"^buy_.*$"))


