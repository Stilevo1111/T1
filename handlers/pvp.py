"""PvP обработчики для Telegram бота"""

import logging
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
import asyncio

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery
from telegram.ext import ContextTypes, CommandHandler, CallbackQueryHandler, ConversationHandler, MessageHandler, filters

from database import get_user, update_user
from game_logic import calculate_character_stats
from handlers.pvp_system import pvp_manager

logger = logging.getLogger(__name__)

# Состояния для PvP
SEARCHING_OPPONENT = 1
IN_FIGHT = 2

async def pvp_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /pvp - показывает меню PvP"""
    keyboard = [
        [InlineKeyboardButton("🔎 Поиск противника", callback_data="pvp_search")],
        [InlineKeyboardButton("📊 Моя статистика", callback_data="pvp_stats")],
        [InlineKeyboardButton("🏆 Таблица лидеров", callback_data="pvp_leaderboard")],
        [InlineKeyboardButton("❌ Отмена поиска", callback_data="pvp_cancel")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "⚔️ Добро пожаловать в PvP арену!\n\n"
        "Выберите действие:",
        reply_markup=reply_markup
    )

async def pvp_search_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик поиска противника"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    user = await get_user(user_id)
    
    if not user:
        await query.edit_message_text("❌ Сначала зарегистрируйтесь в игре с помощью /start")
        return
    
    # Проверяем, не в очереди ли уже пользователь
    # queue_status = await pvp_manager.queue.add_to_queue(user_id, user.get('mmr', 1000))
    # 
    # if queue_status['found_match']:
    #     # Найден противник - начинаем бой
    #     opponent_id = queue_status['opponent_id']
    #     await start_pvp_fight(update, context, user_id, opponent_id)
    # else:
    #     # В очереди
    #     position = queue_status['queue_position']
    #     wait_time = queue_status['estimated_wait']
    #     
    #     keyboard = [[InlineKeyboardButton("❌ Отмена поиска", callback_data="pvp_cancel")]]
    #     reply_markup = InlineKeyboardMarkup(keyboard)
    #     
    #     await query.edit_message_text(
    #         f"⏳ Поиск противника...\n"
    #         f"Позиция в очереди: {position}\n"
    #         f"Ожидаемое время: ~{wait_time} сек\n\n"
    #         f"Система автоматически найдет противника с похожим MMR.",
    #         reply_markup=reply_markup
    #     )

async def pvp_cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик отмены поиска"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    removed = await pvp_manager.queue.remove_from_queue(user_id)
    
    if removed:
        await query.edit_message_text("✅ Поиск противника отменен")
    else:
        await query.edit_message_text("❌ Вы не находитесь в очереди")

async def pvp_stats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик просмотра статистики"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    user = await get_user(user_id)
    
    if not user:
        await query.edit_message_text("❌ Сначала зарегистрируйтесь в игре с помощью /start")
        return
    
    # Получаем статистику
    wins = user.get('pvp_wins', 0)
    losses = user.get('pvp_losses', 0)
    draws = user.get('pvp_draws', 0)
    mmr = user.get('mmr', 1000)
    last_fight = user.get('pvp_last_fight', 'Никогда')
    
    total_fights = wins + losses + draws
    win_rate = (wins / total_fights * 100) if total_fights > 0 else 0
    
    stats_text = (
        f"📊 Ваша PvP статистика:\n\n"
        f"🏆 Побед: {wins}\n"
        f"💀 Поражений: {losses}\n"
        f"🤝 Ничьих: {draws}\n"
        f"📊 Общее количество боев: {total_fights}\n"
        f"🎯 Процент побед: {win_rate:.1f}%\n"
        f"⚡️ MMR: {mmr}\n"
        f"🕐 Последний бой: {last_fight}"
    )
    
    keyboard = [[InlineKeyboardButton("⬅️ Назад", callback_data="pvp_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(stats_text, reply_markup=reply_markup)

async def pvp_leaderboard_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик таблицы лидеров"""
    query = update.callback_query
    await query.answer()
    
    leaderboard = await get_pvp_leaderboard()
    
    if not leaderboard:
        await query.edit_message_text("📊 Таблица лидеров пока пуста")
        return
    
    leaderboard_text = "🏆 Таблица лидеров PvP:\n\n"
    for i, player in enumerate(leaderboard[:10], 1):
        username = player['username'] or f"Игрок {player['id']}"
        leaderboard_text += f"{i}. {username} - MMR: {player['mmr']}\n"
    
    keyboard = [[InlineKeyboardButton("⬅️ Назад", callback_data="pvp_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(leaderboard_text, reply_markup=reply_markup)

async def pvp_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Возврат в главное меню PvP"""
    query = update.callback_query
    await query.answer()
    await pvp_command(update, context)

async def start_pvp_fight(update: Update, context: ContextTypes.DEFAULT_TYPE, attacker_id: int, defender_id: int) -> None:
    """Начало PvP боя"""
    # Получаем данные пользователей
    attacker = await get_user(attacker_id)
    defender = await get_user(defender_id)
    
    if not attacker or not defender:
        await update.callback_query.edit_message_text("❌ Один из игроков не найден")
        return
    
    # Получаем полные характеристики
    attacker_stats = calculate_character_stats(attacker)
    defender_stats = calculate_character_stats(defender)
    
    attacker_name = attacker.get('username', f'Игрок {attacker_id}')
    defender_name = defender.get('username', f'Игрок {defender_id}')
    
    fight_text = (
        f"⚔️ Начинается бой!\n\n"
        f"🔴 {attacker_name} (MMR: {attacker.get('mmr', 1000)})\n"
        f"🔵 {defender_name} (MMR: {defender.get('mmr', 1000)})\n\n"
        f"Бой начинается..."
    )
    
    # Отправляем сообщение о начале боя (если это callback)
    if update.callback_query:
        await update.callback_query.edit_message_text(fight_text)
    else:
        await update.message.reply_text(fight_text)
    
    # Симуляция боя (можно сделать асинхронно)
    await asyncio.sleep(2)
    
    fight_result = await pvp_manager.start_pvp_fight(attacker_id, defender_id)
    
    if not fight_result['success']:
        await update.callback_query.edit_message_text(f"❌ Ошибка: {fight_result['message']}")
        return
    
    # Формируем результат боя
    if fight_result['result'] == 'win':
        winner_name = fight_result['winner_name']
        loser_name = fight_result['loser_name']
        winner_hp = fight_result['winner_hp']
        loser_hp = fight_result['loser_hp']
        rounds = fight_result['rounds']
        
        result_text = (
            f"🎉 Бой окончен!\n\n"
            f"🏆 Победитель: {winner_name}\n"
            f"💀 Проигравший: {loser_name}\n"
            f"❤️ Победитель остался с {winner_hp} HP\n"
            f"💔 Проигравший остался с {loser_hp} HP\n"
            f"⏱️ Бой длился {rounds} раундов\n\n"
            f"Спасибо за игру!"
        )
    elif fight_result['result'] == 'draw':
        result_text = (
            f"🤝 Бой окончен вничью!\n\n"
            f"Оба игрока показали достойную игру.\n"
            f"Бой длился {fight_result['rounds']} раундов.\n\n"
            f"Спасибо за игру!"
        )
    else:
        result_text = "❓ Неизвестный результат боя"
    
    # Отправляем результат
    if update.callback_query:
        await update.callback_query.edit_message_text(result_text)
    else:
        await update.message.reply_text(result_text)

async def get_pvp_leaderboard() -> List[Dict[str, Any]]:
    """Получение таблицы лидеров PvP"""
    from database import get_top_by_stat
    
    # Получаем топ по MMR
    leaderboard_data = await get_top_by_stat('mmr', 20)
    
    leaderboard = []
    for row in leaderboard_data:
        leaderboard.append({
            'id': row[0],  # username
            'username': row[0],  # username
            'mmr': row[1],  # mmr
            'wins': 0,  # pvp_wins
            'losses': 0,  # pvp_losses
            'draws': 0  # pvp_draws
        })
    
    return leaderboard

def register_pvp_callbacks(application) -> None:
    """Регистрация callback обработчиков PvP"""
    application.add_handler(CallbackQueryHandler(pvp_search_callback, pattern="^pvp_search$"))
    application.add_handler(CallbackQueryHandler(pvp_cancel_callback, pattern="^pvp_cancel$"))
    application.add_handler(CallbackQueryHandler(pvp_stats_callback, pattern="^pvp_stats$"))
    application.add_handler(CallbackQueryHandler(pvp_leaderboard_callback, pattern="^pvp_leaderboard$"))
    application.add_handler(CallbackQueryHandler(pvp_menu_callback, pattern="^pvp_menu$"))

def register_pvp_handlers(application) -> None:
    """Регистрация обработчиков PvP команд"""
    # Команда /pvp
    application.add_handler(CommandHandler("pvp", pvp_command))
    
    # Callback обработчики
    register_pvp_callbacks(application)

__all__ = ['pvp_command', 'register_pvp_handlers', 'register_pvp_callbacks']