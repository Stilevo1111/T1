# -*- coding: utf-8 -*-
"""Модуль для работы с Dota 2 MMR"""

import requests
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from database import get_user, update_user_field

logger = logging.getLogger(__name__)

# Stratz API (бесплатный, без ключа)
STRATZ_API_URL = "https://api.stratz.com/players"


def search_player_by_nickname(nickname: str) -> dict:
    """
    Поиск игрока по никнейму через Stratz API
    Returns: {steam_id, nickname, mmr, total_games, wins}
    """
    try:
        # Stratz allows searching by nickname
        url = f"{STRATZ_API_URL}/{nickname}"
        response = requests.get(url, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            return {
                "steam_id": data.get("steamId"),
                "nickname": data.get("nickName"),
                "mmr": data.get("mmr", 0),
                "total_games": data.get("stats", {}).get("matchCount", 0),
                "wins": data.get("stats", {}).get("winCount", 0)
            }
        elif response.status_code == 404:
            return None
        else:
            logger.warning(f"Stratz API error: {response.status_code}")
            return None
    except Exception as e:
        logger.error(f"Error searching player: {e}")
        return None


def get_player_stats(steam_id: int) -> dict:
    """
    Получение полной статистики игрока
    Returns: {mmr, total_games, wins, week_games, week_wins}
    """
    try:
        url = f"{STRATZ_API_URL}/{steam_id}"
        response = requests.get(url, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            return {
                "mmr": data.get("mmr", 0),
                "total_games": data.get("stats", {}).get("matchCount", 0),
                "wins": data.get("stats", {}).get("winCount", 0),
                "rank_tier": data.get("rankTier", 0)
            }
        return None
    except Exception as e:
        logger.error(f"Error getting player stats: {e}")
        return None


def update_user_mmr(telegram_id: int) -> bool:
    """
    Обновление MMR пользователя из Stratz API
    Returns: True если обновление прошло успешно
    """
    try:
        user = get_user(telegram_id)
        if not user or not user.get("steam_id"):
            return False
        
        steam_id = user["steam_id"]
        player_data = get_player_stats(steam_id)
        
        if player_data:
            # Обновляем MMR и статистику
            update_user_field(telegram_id, "mmr", player_data.get("mmr", 0))
            update_user_field(telegram_id, "dota_total_games", player_data.get("total_games", 0))
            update_user_field(telegram_id, "dota_wins", player_data.get("wins", 0))
            update_user_field(telegram_id, "mmr_updated_at", "CURRENT_TIMESTAMP")
            
            return True
        return False
    except Exception as e:
        logger.error(f"Error updating user MMR: {e}")
        return False


def register_steam(telegram_id: int, identifier: str) -> dict:
    """
    Регистрация Steam аккаунта по нику или Steam ID
    Returns: {success: bool, message: str, data: dict}
    """
    # Проверяем, если это число - это Steam ID
    if identifier.isdigit():
        # Проверяем длину (от 9 до 17 цифр)
        if len(identifier) < 9 or len(identifier) > 17:
            return {"success": False, "message": "❌ Неверный формат Steam ID. Должно быть от 9 до 17 цифр."}
        
        steam_id = int(identifier)
        # Пробуем получить данные по Steam ID
        player_data = get_player_stats(steam_id)
        if player_data:
            # Сохраняем в БД
            update_user_field(telegram_id, "steam_id", steam_id)
            update_user_field(telegram_id, "steam_nickname", player_data.get("nickname", ""))
            update_user_field(telegram_id, "mmr", player_data.get("mmr", 0))
            update_user_field(telegram_id, "dota_total_games", player_data.get("total_games", 0))
            update_user_field(telegram_id, "dota_wins", player_data.get("wins", 0))
            return {
                "success": True,
                "message": f"✅ Привязано! {player_data.get('nickname')} - MMR: {player_data.get('mmr')}",
                "data": player_data
            }
        else:
            return {"success": False, "message": "❌ Не удалось найти игрока по этому Steam ID"}
    
    # Иначе - ищем по никнейму
    player_data = search_player_by_nickname(identifier)
    if player_data and player_data.get("steam_id"):
        steam_id = player_data["steam_id"]
        # Сохраняем в БД
        update_user_field(telegram_id, "steam_id", steam_id)
        update_user_field(telegram_id, "steam_nickname", player_data.get("nickname", identifier))
        update_user_field(telegram_id, "mmr", player_data.get("mmr", 0))
        update_user_field(telegram_id, "dota_total_games", player_data.get("total_games", 0))
        update_user_field(telegram_id, "dota_wins", player_data.get("wins", 0))
        
        return {
            "success": True,
            "message": f"✅ Привязано! {player_data.get('nickname')} - MMR: {player_data.get('mmr')}",
            "data": player_data
        }
    else:
        return {"success": False, "message": "❌ Не удалось найти игрока. Попробуй другой ник или используй Steam ID"}


def get_user_dota_stats(telegram_id: int) -> dict:
    """Получение сохранённой статистики Dota 2 пользователя"""
    user = get_user(telegram_id)
    if not user:
        return None
    
    return {
        "steam_id": user.get("steam_id"),
        "steam_nickname": user.get("steam_nickname"),
        "mmr": user.get("mmr", 0),
        "total_games": user.get("dota_total_games", 0),
        "wins": user.get("dota_wins", 0),
        "week_games": user.get("week_games", 0),
        "week_wins": user.get("week_wins", 0),
        "week_updated_at": user.get("week_updated_at"),
        "mmr_updated_at": user.get("mmr_updated_at")
    }


def get_week_top(limit: int = 10) -> list:
    """Получение топа за неделю по винрейту"""
    # Здесь нужна будет функция в database.py для получения топа
    # Пока возвращаем заглушку
    return []


def is_steam_linked(telegram_id: int) -> bool:
    """Проверка, привязан ли Steam к аккаунту"""
    user = get_user(telegram_id)
    return user and user.get("steam_id") is not None


async def show_mmr_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать меню Dota 2 MMR"""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    
    user_id = update.effective_user.id
    user = get_user(user_id)
    
    keyboard = []
    
    if user and user.get("steam_id"):
        mmr = user.get("mmr", 0)
        nickname = user.get("steam_nickname", "Unknown")
        total_games = user.get("dota_total_games", 0)
        wins = user.get("dota_wins", 0)
        winrate = f"{(wins/total_games*100):.1f}%" if total_games > 0 else "0%"
        
        text = f"🎮 {nickname}\nMMR: {mmr}\nИгр: {total_games} (WR: {winrate})"
        keyboard.append([InlineKeyboardButton("🔄 Обновить MMR", callback_data="refresh_mmr")])
    else:
        text = "🔗 Привяжи свой Steam аккаунт\n\nИспользуй /link \u003cnickname\u003d или Steam ID\nПример: /link NoNam3"
    
    keyboard.append([InlineKeyboardButton("🏆 Топ недели", callback_data="week_top")])
    keyboard.append([InlineKeyboardButton("« Назад в меню", callback_data="back_to_menu")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(text, reply_markup=reply_markup)
