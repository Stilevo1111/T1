import time
import random
import logging
import asyncio
from typing import Dict, List, Tuple, Optional
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes, CommandHandler, MessageHandler, filters, CallbackQueryHandler

from config import AUTO_DELETE_DELAY, COOLDOWN, MEMES
from database import get_user, update_user, get_fissure_top, update_fissure
from game_logic import (
    calculate_character_stats, calculate_damage, calculate_dodge, spawn_boss, 
    check_level_restriction, regenerate_hp, check_level_up, get_fissure_result,
    get_meme_message, get_items_by_category, get_item_description, get_potion_data,
    calculate_boss_reward, get_user_progress, get_next_level_exp,
    calculate_pvp_advantage, calculate_boss_strategy,
    check_level_up as check_level_up_new
)

# ================= UTILS =================

async def auto_delete(context: ContextTypes.DEFAULT_TYPE, chat_id: int, msg_ids: List[int]):
    """Автоматическое удаление сообщений через заданное время"""
    await asyncio.sleep(AUTO_DELETE_DELAY)
    for msg_id in msg_ids:
        try:
            await context.bot.delete_message(chat_id, msg_id)
        except Exception:
            pass

def format_stats_text(user: Dict, stats: Dict) -> str:
    """Форматирует текст статистики персонажа"""
    progress = get_user_progress(user)
    next_level_exp = get_next_level_exp(user["level"])
    
    text = (f"👤 ПРОФИЛЬ {user['username']}\n\n"
            f"🎮 Уровень: {user['level']} (Опыт: {user['exp']}/{next_level_exp})\n"
            f"📊 Винрейт: {user['mmr']} MMR\n"
            f"👹 Убито боссов: {user.get('bosses_killed', 0)}\n"
            f"🗡️ Общий урон по боссам: {user['boss_dmg']}\n\n"
            f"❤️ HP: {user['hp']}/{stats['max_hp']}\n"
            f"💪 STR: {stats['str_total']} (база: {user['str']})\n"
            f"🏃‍♂️ AGI: {stats['agi_total']} (база: {user['agi']})\n"
            f"🧠 INT: {stats['int_total']} (база: {user['int']})\n"
            f"⚔️ Урон: {stats['base_damage']}\n"
            f"🎯 Крит: {stats['crit_chance']:.1f}%\n"
            f"🛡️ Уклонение: {stats['dodge_chance']:.1f}%\n"
            f"💚 Реген: {stats['hp_regen']:.1f}% в минуту\n\n"
            f"📚 EXP: {user['exp']}\n"
            f"💰 Gold: {user['gold']}\n"
            f"🍆 Fissure: {user['fissure']:.1f} см\n\n")
    
    # Форматируем слоты для артефактов
    slots = user["items"] if user["items"] else [None] * 6
    artifacts_text = "🎒 СЛОТЫ АРТЕФАКТОВ:\n"
    for i, item in enumerate(slots, 1):
        if item:
            description = get_item_description(item)
            artifacts_text += f"  {i}. {item} — {description}\n"
        else:
            artifacts_text += f"  {i}. ПУСТО\n"
    
    text += artifacts_text + "\n"
    text += "💡 Подсказка: /buy ITEM — купить предмет"
    return text

def format_boss_info(user: Dict) -> str:
    """Форматирует информацию о боссе"""
    boss_ability = user.get('boss_ability', 'Нет информации')
    return (f"👹 **{user['boss_name']}**\n"
            f"❤️ HP: {user['boss_hp']}/{user['boss_max']}\n"
            f"📊 Уровень: {user['boss_level']}\n"
            f"⚡ Способности: {boss_ability}\n\n"
            f"💢 Используйте /attack чтобы атаковать")

# ================= COMMAND HANDLERS =================

# Функции фиссуры
async def fissure_top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /fissure_top"""
    rows = await get_fissure_top()
    if not rows:
        await update.message.reply_text("Топ пуст 😢")
    else:
        text = ["🏆 ТОП по длине фиссуры:\n"]
        for i, row in enumerate(rows, 1):
            text.append(f"{i}. 👤 {row['username']} — {row['fissure']:.1f} см")
        await update.message.reply_text("\n".join(text))


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /stats"""
    username = update.effective_user.username or update.effective_user.full_name
    user = await get_user(update.effective_user.id, username)
    stats = calculate_character_stats(user)
    
    msg = await update.message.reply_text(
        f"📊 Твоя Фиссура:\n📏 {user['fissure']:.1f} см"
    )

    context.application.create_task(
        auto_delete(context, update.effective_chat.id, [msg.message_id])
    )


# Функции PvP
async def pvp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /pvp"""
    username = update.effective_user.username or update.effective_user.full_name
    user = await get_user(update.effective_user.id, username)
    stats = calculate_character_stats(user)
    
    # Получаем список игроков для PvP (исключая самого пользователя)
    from database import db_pool
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT username, mmr, level, str, agi, int, hp, hp_max, user_id
            FROM users 
            WHERE user_id != $1 AND mmr >= $2
            ORDER BY mmr DESC
            LIMIT 10
        """, str(update.effective_user.id), user["mmr"] * 0.5)
    
    if not rows:
        await update.message.reply_text("❌ Нет доступных противников")
        return
    
    text = "⚔️ Доступные противники для PvP:\n\n"
    for i, row in enumerate(rows, 1):
        # Создаем временного пользователя для расчета характеристик противника
        enemy_user = {
            "username": row['username'],
            "mmr": row['mmr'],
            "level": row['level'],
            "str": row['str'],
            "agi": row['agi'],
            "int": row['int'],
            "hp": row['hp'],
            "hp_max": row['hp_max'],
            "items": [None] * 6  # Предполагаем, что у противника нет предметов для упрощения
        }
        enemy_stats = calculate_character_stats(enemy_user)
        
        # Рассчитываем преимущество
        advantage = calculate_pvp_advantage(user, enemy_user)
        
        text += f"{i}. 👤 {row['username']}\n"
        text += f"   📊 MMR: {row['mmr']} | Уровень: {row['level']}\n"
        text += f"   💪 STR: {row['str']} | 🏃‍♂️ AGI: {row['agi']} | 🧠 INT: {row['int']}\n"
        text += f"   ❤️ HP: {row['hp']}/{row['hp_max']}\n"
        text += f"   ⚔️ Урон: {enemy_stats['base_damage']} | 🛡️ Уклон: {enemy_stats['dodge_chance']:.1f}%\n"
        
        # Показываем преимущество
        if advantage["advantage"] > 5:
            text += f"   🎯 Вы в преимуществе: +{advantage['advantage']:.1f}%\n"
        elif advantage["advantage"] < -5:
            text += f"   ⚠️ Вы в劣势е: {advantage['advantage']:.1f}%\n"
        else:
            text += f"   ⚖️ Равные шансы\n"
        
        text += f"   /fight_{row['user_id']} — сразиться\n\n"
    
    msg = await update.message.reply_text(text)
    # Автоудаление ответа
    context.application.create_task(
        auto_delete(context, update.effective_chat.id, [msg.message_id])
    )


async def handle_pvp_fight(update: Update, context: ContextTypes.DEFAULT_TYPE, enemy_id: int):
    """Обработчик PvP боя по кнопке из списка PvP"""
    username = update.effective_user.username or update.effective_user.full_name
    user1 = await get_user(update.effective_user.id, username)
    stats1 = calculate_character_stats(user1)
    
    # Получаем информацию о противнике из базы данных
    from database import db_pool
    async with db_pool.acquire() as conn:
        enemy_data = await conn.fetchrow("SELECT username FROM users WHERE user_id = $1", str(enemy_id))
        enemy_username = enemy_data["username"] if enemy_data else f"Player{enemy_id}"
    
    user2 = await get_user(enemy_id, enemy_username)
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
    # Автоудаление ответа
    context.application.create_task(
        auto_delete(context, update.effective_chat.id, [msg.message_id])
    )


async def fight(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /fight"""
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
    # Автоудаление ответа
    context.application.create_task(
        auto_delete(context, update.effective_chat.id, [msg.message_id])
    )