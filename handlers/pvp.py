"""Обработчики команд, связанных с PvP"""

import logging
import time
import random
from typing import Dict, Any
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CallbackQueryHandler

from database import get_user, update_user, get_pvp_opponents
from database.real_database import db_manager
from game_logic import calculate_character_stats, calculate_damage, calculate_dodge, get_meme_message
from utils.formatters import format_pvp_opponents

logger = logging.getLogger(__name__)

async def pvp(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /pvp - показывает список противников с кнопками для вызова на дуэль"""
    try:
        username = update.effective_user.username or update.effective_user.full_name
        user = await get_user(update.effective_user.id, username)
        stats = calculate_character_stats(user)
        
        # Получаем список игроков для PvP (исключая самого пользователя)
        opponents = await get_pvp_opponents(update.effective_user.id)
        
        if not opponents:
            await update.message.reply_text("❌ Нет доступных противников")
            return
        
        # Создаем клавиатуру с кнопками для каждого противника
        keyboard = []
        row = []
        max_buttons_per_row = 2
        
        for opponent in opponents:
            opponent_id = opponent['user_id']
            opponent_name = opponent['username']
            opponent_mmr = opponent['mmr']
            opponent_level = opponent['level']
            
            # Создаем кнопку для вызова на дуэль
            button_text = f"⚔️ {opponent_name} (Lvl {opponent_level})"
            button = InlineKeyboardButton(button_text, callback_data=f"pvp_fight_{opponent_id}")
            row.append(button)
            
            # Добавляем строку, если набралось достаточно кнопок
            if len(row) == max_buttons_per_row:
                keyboard.append(row)
                row = []
        
        # Добавляем оставшиеся кнопки
        if row:
            keyboard.append(row)
        
        # Добавляем кнопку для обновления списка
        keyboard.append([InlineKeyboardButton("🔄 Обновить список", callback_data="pvp_refresh")])
        keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data="main_menu")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        text = f"👥 Доступные противники для PvP:\n\n{format_pvp_opponents(opponents)}"
        msg = await update.message.reply_text(text, reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"Ошибка в команде /pvp: {e}")
        await update.message.reply_text("❌ Произошла ошибка. Попробуйте позже.")

async def handle_pvp_fight_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик нажатия на кнопку вызова на дуэль"""
    try:
        query = update.callback_query
        await query.answer()
        
        # Извлекаем ID противника из callback_data
        callback_data = query.data
        if not callback_data.startswith("pvp_fight_"):
            return
        
        enemy_id = int(callback_data.replace("pvp_fight_", ""))
        username = update.effective_user.username or update.effective_user.full_name
        user1 = await get_user(update.effective_user.id, username)
        stats1 = calculate_character_stats(user1)
        
        # Получаем информацию о противнике из базы данных
        user2 = await get_user(enemy_id, f"Player{enemy_id}")
        stats2 = calculate_character_stats(user2)
        
        if time.time() - user1["last_pvp"] < 600:
            await query.edit_message_text("⏳ КД PvP")
            return

        # Проверка MMR
        if user2["mmr"] < user1["mmr"] * 0.5:
            await query.edit_message_text("❌ Противник слишком слабый")
            return

        # Информация о противнике
        text = f"👤 Противник: {user2['username']}\n"
        text += f"📊 MMR: {user2['mmr']} | Уровень: {user2['level']}\n"
        text += f"💪 STR: {user2['str']} | 🏃‍♂️ AGI: {user2['agi']} | 🧠 INT: {user2['int']}\n"
        text += f"❤️ HP: {user2['hp']}/{user2['hp_max']}\n"
        text += f"🎒 Экипировка: {', '.join([item or 'Пусто' for item in user2['items']]) if user2['items'] else 'Пусто'}\n\n"
        
        # Боевые действия с короткими логами
        text += "⚔️ БОЙ НАЧАЛСЯ!\n\n"
        
        # Раунд 1
        dmg1, is_crit1 = calculate_damage(user1)
        dmg2, is_crit2 = calculate_damage(user2)
        
        text += f"1. {user1['username']} наносит {dmg1} урона\n"
        if is_crit1:
            text += "   💥 КРИТ! Я инвестировал в урон\n"
        
        user2_hp = max(0, user2["hp"] - dmg1)
        text += f"2. {user2['username']} наносит {dmg2} урона\n"
        if is_crit2:
            text += "   💥 КРИТ! Я инвестировал в урон\n"
        
        user1_hp = max(0, user1["hp"] - dmg2)
        
        # Раунд 2
        if user1_hp > 0 and user2_hp > 0:
            dmg1, is_crit1 = calculate_damage(user1)
            dmg2, is_crit2 = calculate_damage(user2)
            
            text += f"3. {user1['username']} наносит {dmg1} урона\n"
            if is_crit1:
                text += "   💥 КРИТ! Я инвестировал в урон\n"
            
            user2_hp = max(0, user2_hp - dmg1)
            text += f"4. {user2['username']} наносит {dmg2} урона\n"
            if is_crit2:
                text += "   💥 КРИТ! Я инвестировал в урон\n"
            
            user1_hp = max(0, user1_hp - dmg2)
        
        # Определение победителя
        if user1_hp > user2_hp:
            winner = user1
            loser = user2
            text += f"\n🏆 ПОБЕДИТЕЛЬ: {user1['username']}!\n"
        else:
            winner = user2
            loser = user1
            text += f"\n🏆 ПОБЕДИТЕЛЬ: {user2['username']}!\n"
        
        # Передача MMR и опыта
        mmr_change = 20
        exp_change = 50
        
        winner_mmr = winner["mmr"] + mmr_change
        loser_mmr = loser["mmr"] - mmr_change
        winner_exp = winner["exp"] + exp_change
        loser_exp = loser["exp"] + exp_change // 2  # Проигравший получает немного опыта
        
        text += f"\n📊 ИЗМЕНЕНИЯ:\n"
        text += f"🥇 {winner['username']}: +{mmr_change} MMR, +{exp_change} EXP\n"
        text += f"🥈 {loser['username']}: -{mmr_change} MMR, +{exp_change // 2} EXP\n"
        
        # Восстановление HP до 100% и установка кулдауна
        text += f"\n💚 Оба игрока восстановили HP до 100%\n"
        text += f"⏳ PvP кулдаун: 5 минут\n"
        
        # Шутка в конце
        jokes = [
            "Шутка: Проигравший теперь знает, что ботинки нужно завязывать tighter!",
            "Шутка: Победитель теперь может хвастаться, что он сильнее, чем его противник!",
            "Шутка: Проигравший обещал купить себе лучшие предметы и вернуться за реваншем!",
            "Шутка: Победитель теперь может позволить себе купить новое зелье!",
            "Шутка: Проигравший сказал, что это была тактическая сдача!"
        ]
        text += f"\n{random.choice(jokes)}"
        
        # Обновление данных
        await update_user(update.effective_user.id, hp=stats1["max_hp"], mmr=winner_mmr if winner == user1 else loser_mmr, exp=winner_exp if winner == user1 else loser_exp, last_pvp=time.time())
        await update_user(enemy_id, hp=stats2["max_hp"], mmr=winner_mmr if winner == user2 else loser_mmr, exp=winner_exp if winner == user2 else loser_exp, last_pvp=time.time())
        
        await query.edit_message_text(text)
    except Exception as e:
        logger.error(f"Ошибка в handle_pvp_fight_callback: {e}")
        await query.edit_message_text("❌ Произошла ошибка. Попробуйте позже.")

async def handle_pvp_refresh(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик обновления списка противников"""
    try:
        query = update.callback_query
        await query.answer()
        
        username = update.effective_user.username or update.effective_user.full_name
        user = await get_user(update.effective_user.id, username)
        stats = calculate_character_stats(user)
        
        # Получаем обновленный список игроков для PvP
        opponents = await get_pvp_opponents(update.effective_user.id)
        
        if not opponents:
            await query.edit_message_text("❌ Нет доступных противников")
            return
        
        # Создаем обновленную клавиатуру
        keyboard = []
        row = []
        max_buttons_per_row = 2
        
        for opponent in opponents:
            opponent_id = opponent['user_id']
            opponent_name = opponent['username']
            opponent_mmr = opponent['mmr']
            opponent_level = opponent['level']
            
            button_text = f"⚔️ {opponent_name} (Lvl {opponent_level})"
            button = InlineKeyboardButton(button_text, callback_data=f"pvp_fight_{opponent_id}")
            row.append(button)
            
            if len(row) == max_buttons_per_row:
                keyboard.append(row)
                row = []
        
        if row:
            keyboard.append(row)
        
        keyboard.append([InlineKeyboardButton("🔄 Обновить список", callback_data="pvp_refresh")])
        keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data="main_menu")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        text = f"👥 Доступные противники для PvP:\n\n{format_pvp_opponents(opponents)}"
        await query.edit_message_text(text, reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"Ошибка в handle_pvp_refresh: {e}")
        await query.edit_message_text("❌ Произошла ошибка. Попробуйте позже.")

async def fight(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /fight - для ручного ввода ID противника"""
    try:
        username = update.effective_user.username or update.effective_user.full_name
        user1 = await get_user(update.effective_user.id, username)
        stats1 = calculate_character_stats(user1)
        
        try:
            enemy_id = int(context.args[0]) if context.args else None
        except:
            await update.message.reply_text("❌ Укажите ID противника")
            return

        user2 = await get_user(enemy_id, f"Player{enemy_id}")
        stats2 = calculate_character_stats(user2)
        
        if time.time() - user1["last_pvp"] < 600:
            await update.message.reply_text("⏳ КД PvP")
            return

        # Проверка MMR
        if user2["mmr"] < user1["mmr"] * 0.5:
            await update.message.reply_text("❌ Противник слишком слабый")
            return

        # Информация о противнике
        text = f"👤 Противник: {user2['username']}\n"
        text += f"📊 MMR: {user2['mmr']} | Уровень: {user2['level']}\n"
        text += f"💪 STR: {user2['str']} | 🏃‍♂️ AGI: {user2['agi']} | 🧠 INT: {user2['int']}\n"
        text += f"❤️ HP: {user2['hp']}/{user2['hp_max']}\n"
        text += f"🎒 Экипировка: {', '.join([item or 'Пусто' for item in user2['items']]) if user2['items'] else 'Пусто'}\n\n"
        
        # Боевые действия с короткими логами
        text += "⚔️ БОЙ НАЧАЛСЯ!\n\n"
        
        # Раунд 1
        dmg1, is_crit1 = calculate_damage(user1)
        dmg2, is_crit2 = calculate_damage(user2)
        
        text += f"1. {user1['username']} наносит {dmg1} урона\n"
        if is_crit1:
            text += "   💥 КРИТ! Я инвестировал в урон\n"
        
        user2_hp = max(0, user2["hp"] - dmg1)
        text += f"2. {user2['username']} наносит {dmg2} урона\n"
        if is_crit2:
            text += "   💥 КРИТ! Я инвестировал в урон\n"
        
        user1_hp = max(0, user1["hp"] - dmg2)
        
        # Раунд 2
        if user1_hp > 0 and user2_hp > 0:
            dmg1, is_crit1 = calculate_damage(user1)
            dmg2, is_crit2 = calculate_damage(user2)
            
            text += f"3. {user1['username']} наносит {dmg1} урона\n"
            if is_crit1:
                text += "   💥 КРИТ! Я инвестировал в урон\n"
            
            user2_hp = max(0, user2_hp - dmg1)
            text += f"4. {user2['username']} наносит {dmg2} урона\n"
            if is_crit2:
                text += "   💥 КРИТ! Я инвестировал в урон\n"
            
            user1_hp = max(0, user1_hp - dmg2)
        
        # Определение победителя
        if user1_hp > user2_hp:
            winner = user1
            loser = user2
            text += f"\n🏆 ПОБЕДИТЕЛЬ: {user1['username']}!\n"
        else:
            winner = user2
            loser = user1
            text += f"\n🏆 ПОБЕДИТЕЛЬ: {user2['username']}!\n"
        
        # Передача MMR и опыта
        mmr_change = 20
        exp_change = 50
        
        winner_mmr = winner["mmr"] + mmr_change
        loser_mmr = loser["mmr"] - mmr_change
        winner_exp = winner["exp"] + exp_change
        loser_exp = loser["exp"] + exp_change // 2  # Проигравший получает немного опыта
        
        text += f"\n📊 ИЗМЕНЕНИЯ:\n"
        text += f"🥇 {winner['username']}: +{mmr_change} MMR, +{exp_change} EXP\n"
        text += f"🥈 {loser['username']}: -{mmr_change} MMR, +{exp_change // 2} EXP\n"
        
        # Восстановление HP до 100% и установка кулдауна
        text += f"\n💚 Оба игрока восстановили HP до 100%\n"
        text += f"⏳ PvP кулдаун: 5 минут\n"
        
        # Шутка в конце
        jokes = [
            "Шутка: Проигравший теперь знает, что ботинки нужно завязывать tighter!",
            "Шутка: Победитель теперь может хвастаться, что он сильнее, чем его противник!",
            "Шутка: Проигравший обещал купить себе лучшие предметы и вернуться за реваншем!",
            "Шутка: Победитель теперь может позволить себе купить новое зелье!",
            "Шутка: Проигравший сказал, что это была тактическая сдача!"
        ]
        text += f"\n{random.choice(jokes)}"
        
        # Обновление данных
        await update_user(update.effective_user.id, hp=stats1["max_hp"], mmr=winner_mmr if winner == user1 else loser_mmr, exp=winner_exp if winner == user1 else loser_exp, last_pvp=time.time())
        await update_user(enemy_id, hp=stats2["max_hp"], mmr=winner_mmr if winner == user2 else loser_mmr, exp=winner_exp if winner == user2 else loser_exp, last_pvp=time.time())
        
        msg = await update.message.reply_text(text)
    except Exception as e:
        logger.error(f"Ошибка в команде /fight: {e}")
        await update.message.reply_text("❌ Произошла ошибка. Попробуйте позже.")


# Регистрация обработчиков колбэков
def register_pvp_callbacks(app):
    """Регистрация обработчиков колбэков для PvP"""
    app.add_handler(CallbackQueryHandler(handle_pvp_fight_callback, pattern=r"^pvp_fight_\d+$"))
    app.add_handler(CallbackQueryHandler(handle_pvp_refresh, pattern=r"^pvp_refresh$"))

# Экспортируем функции для использования в handlers/__init__.py
__all__ = ['pvp', 'fight', 'handle_pvp_fight_callback', 'handle_pvp_refresh', 'register_pvp_callbacks']



