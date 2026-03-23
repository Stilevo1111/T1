# -*- coding: utf-8 -*-
import re
import time
import requests
import logging
from database import get_user, update_user_field

logger = logging.getLogger(__name__)

OPENDOTA_API_URL = "https://api.opendota.com/api"
STEAM_OFFSET = 76561197960265728

# Простой кеш для запросов (5 минут)
_cache = {}
CACHE_TTL = 300  # 5 минут


def _get_cached(key):
    """Получить значение из кеша"""
    if key in _cache:
        value, timestamp = _cache[key]
        if time.time() - timestamp < CACHE_TTL:
            return value
        del _cache[key]
    return None


def _set_cached(key, value):
    """Сохранить значение в кеш"""
    _cache[key] = (value, time.time())


# ========================
# 🔧 UTILS
# ========================

def steam64_to_account_id(steam_id: int) -> int:
    return steam_id - STEAM_OFFSET


def account_id_to_steam64(account_id: int) -> int:
    return account_id + STEAM_OFFSET


def parse_steam_identifier(identifier: str) -> int:
    """
    Возвращает SteamID64 из:
    - SteamID64 (17 цифр, 7656119...)
    - Account ID (короткий)
    - Dotabuff-ссылки (https://www.dotabuff.com/players/123456789)
    - Никнейм (возвращает None, обработаем позже)
    """
    identifier = identifier.strip()
    
    # Dotabuff ссылка
    match = re.search(r"players/(\d+)", identifier)
    if match:
        account_id = int(match.group(1))
        return account_id_to_steam64(account_id)
    
    # Чистые цифры
    if identifier.isdigit():
        number = int(identifier)
        if len(identifier) >= 17:  # SteamID64
            return number
        else:  # короткий Account ID
            return account_id_to_steam64(number)
    
    # Никнейм (не цифры) → вернем None, обработаем позже
    return None


def safe_winrate(wins: int, games: int) -> float:
    return round((wins / games * 100), 1) if games > 0 else 0


# ========================
# 🎯 MMR (примерный)
# ========================

def rank_to_mmr(rank_tier: int) -> int:
    if not rank_tier:
        return 0

    tier = rank_tier // 10
    star = rank_tier % 10

    return tier * 700 + star * 150


# ========================
# 🔍 SEARCH PLAYER
# ========================

def search_player(nickname: str) -> dict:
    try:
        url = f"{OPENDOTA_API_URL}/search"
        r = requests.get(url, params={"q": nickname}, timeout=10)

        if r.status_code != 200:
            return None

        data = r.json()
        if not data:
            return None

        player = data[0]
        account_id = player.get("account_id")

        if not account_id:
            return None

        steam_id = account_id_to_steam64(account_id)
        stats = get_player_stats(steam_id)

        if not stats:
            return None

        # Обновляем никнейм из результатов поиска
        stats["nickname"] = player.get("personaname", stats.get("nickname", "Unknown"))
        
        return {
            "steam_id": steam_id,
            **stats
        }

    except Exception as e:
        logger.error(f"search error: {e}")
        return None


# ========================
# 📊 GET STATS
# ========================

def get_player_stats(steam_id: int) -> dict:
    try:
        # Проверяем кеш
        cache_key = f"player_{steam_id}"
        cached = _get_cached(cache_key)
        if cached:
            return cached
            
        account_id = steam64_to_account_id(steam_id)
        url = f"{OPENDOTA_API_URL}/players/{account_id}"

        r = requests.get(url, timeout=10)

        if r.status_code != 200:
            return None

        data = r.json()

        profile = data.get("profile", {})
        rank_tier = data.get("rank_tier") or 0
        
        # Получаем статистику побед/поражений через отдельный запрос
        wl_url = f"{OPENDOTA_API_URL}/players/{account_id}/wl"
        r2 = requests.get(wl_url, timeout=10)
        
        if r2.status_code == 200:
            wl = r2.json() or {}
            wins = wl.get("win", 0)
            loses = wl.get("lose", 0)
            total_games = wins + loses
        else:
            total_games = 0
            wins = 0
        
        # Используем mmr_estimate для более точного MMR
        mmr_estimate = data.get("mmr_estimate", {}).get("estimate", 0)
        mmr = mmr_estimate or rank_to_mmr(rank_tier)
        
        # Вычисляем винрейт
        winrate = safe_winrate(wins, total_games)

        result = {
            "nickname": profile.get("personaname", "Unknown"),
            "mmr": mmr,
            "total_games": total_games,
            "wins": wins,
            "winrate": winrate,
        }
        
        # Сохраняем в кеш
        _set_cached(cache_key, result)
        
        return result

    except Exception as e:
        logger.error(f"stats error: {e}")
        return None


# ========================
# 🔗 REGISTER
# ========================

def register_steam(telegram_id: int, identifier: str) -> dict:
    try:
        steam_id = parse_steam_identifier(identifier)

        if steam_id:
            # если получилось получить steam_id → stats по ID
            stats = get_player_stats(steam_id)
            if not stats:
                return {"success": False, "message": "❌ Игрок не найден"}
        else:
            # иначе ищем по никнейму через OpenDota
            data = search_player(identifier)
            if not data:
                return {"success": False, "message": "❌ Игрок не найден"}
            steam_id = data["steam_id"]
            stats = data

        # сохраняем в БД
        update_user_field(telegram_id, "steam_id", steam_id)
        update_user_field(telegram_id, "steam_nickname", stats["nickname"])
        update_user_field(telegram_id, "mmr", stats["mmr"])
        update_user_field(telegram_id, "dota_total_games", stats["total_games"])
        update_user_field(telegram_id, "dota_wins", stats["wins"])
        update_user_field(telegram_id, "last_dota_games", stats["total_games"])
        
        # Обновляем недельную статистику сразу после привязки
        update_user_mmr(telegram_id)

        return {
            "success": True,
            "message": f"✅ {stats['nickname']} | MMR: {stats['mmr']} | Winrate: {stats.get('winrate', 0)}%"
        }

    except Exception as e:
        logger.error(f"register error: {e}")
        return {"success": False, "message": "❌ Ошибка"}


# ========================
# 🔄 UPDATE MMR
# ========================

def update_user_mmr(telegram_id: int) -> bool:
    try:
        user = get_user(telegram_id)
        if not user or not user.get("steam_id"):
            return False

        stats = get_player_stats(user["steam_id"])
        if not stats:
            return False

        current_games = stats["total_games"]
        current_wins = stats["wins"]

        last_games = user.get("last_dota_games", 0)
        last_wins = user.get("dota_wins", 0)
        week_games = user.get("week_games", 0)
        
        # Если это первое обновление - инициализируем недельную статистику
        if last_games == 0 or week_games == 0:
            update_user_field(telegram_id, "week_games", current_games)
            update_user_field(telegram_id, "week_wins", current_wins)
        else:
            new_games = max(0, current_games - last_games)
            new_wins = max(0, current_wins - last_wins)

            if new_games > 0:
                update_user_field(
                    telegram_id,
                    "week_games",
                    week_games + new_games
                )
                update_user_field(
                    telegram_id,
                    "week_wins",
                    user.get("week_wins", 0) + new_wins
                )

        update_user_field(telegram_id, "mmr", stats["mmr"])
        update_user_field(telegram_id, "dota_total_games", current_games)
        update_user_field(telegram_id, "dota_wins", current_wins)
        update_user_field(telegram_id, "last_dota_games", current_games)

        return True

    except Exception as e:
        logger.error(f"update error: {e}")
        return False


# ========================
# 🏆 TOP MMR (без API!)
# ========================

def get_mmr_top(limit=10):
    from database import get_dota_mmr_top
    return get_dota_mmr_top(limit)


def get_week_top(limit=10):
    from database import get_dota_week_top
    return get_dota_week_top(limit)
