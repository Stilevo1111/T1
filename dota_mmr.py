# -*- coding: utf-8 -*-
import re
import time
import requests
import logging
from datetime import datetime, timedelta
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


def _api_get(url: str, params: dict = None) -> dict:
    """Универсальная функция для API-запросов с обработкой ошибок и кешем"""
    try:
        r = requests.get(url, params=params or {}, timeout=10)
        if r.status_code == 200:
            return r.json()
        return None
    except Exception as e:
        logger.error(f"API request error: {e}", exc_info=True)
        return None


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
    - SteamID64 (17-20 цифр, 7656119...)
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
        if 17 <= len(identifier) <= 20:  # SteamID64 с защитой от случайных чисел
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

    tier = min(rank_tier // 10, 8)
    star = rank_tier % 10

    return tier * 700 + star * 150


def rank_to_string(rank_tier: int) -> str:
    """Конвертировать rank_tier в читаемый вид (например: "Guardian 3", "Ancient 5", "Immortal")"""
    if not rank_tier:
        return "Unranked"
    
    ranks = ["Herald", "Guardian", "Crusader", "Archon", "Legend", "Ancient", "Divine", "Immortal"]
    tier = rank_tier // 10
    star = rank_tier % 10
    
    if tier < 1 or tier > 8:
        return "Unknown"
    
    rank_name = ranks[tier - 1]
    
    # Immortal не имеет звёзд
    if tier == 8:
        return rank_name
    
    return f"{rank_name} {star}"


# ========================
# 🔍 SEARCH PLAYER
# ========================

def search_player(nickname: str) -> dict:
    try:
        url = f"{OPENDOTA_API_URL}/search"
        
        data = _api_get(url, {"q": nickname})
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
        logger.error("search error", exc_info=True)
        return None


# ========================
# 🎮 MATCHES
# ========================

def get_recent_matches(steam_id: int, limit: int = 5) -> list:
    """Получить последние матчи игрока"""
    try:
        account_id = steam64_to_account_id(steam_id)
        url = f"{OPENDOTA_API_URL}/players/{account_id}/matches"
        
        matches = _api_get(url, {"limit": limit})
        return matches or []
    except Exception as e:
        logger.error(f"get_recent_matches error: {e}", exc_info=True)
        return []


def is_win(match: dict, steam_id: int) -> bool:
    """Определить, выиграл ли игрок матч по данным матча"""
    try:
        account_id = steam64_to_account_id(steam_id)
        # radiant_win = True означает что Radiant выиграл
        # player_is_radiant = нужно проверить radiant
        radiant_win = match.get("radiant_win", False)
        player_is_radiant = match.get("radiant", True)
        
        # Если игрок на Radiant и Radiant выиграл -> победа
        # Если игрок на Dire и Dire выиграл (Radiant проиграл) -> победа
        return (player_is_radiant and radiant_win) or (not player_is_radiant and not radiant_win)
    except Exception as e:
        logger.error(f"is_win error: {e}", exc_info=True)
        return False


def is_win_api(match_id: int, steam_id: int) -> bool:
    """Определить, выиграл ли игрок в матче по ID матча (через API)"""
    try:
        account_id = steam64_to_account_id(steam_id)
        url = f"{OPENDOTA_API_URL}/matches/{match_id}"
        
        match_data = _api_get(url)
        if not match_data:
            return False
        
        players = match_data.get("players", [])
        
        for player in players:
            if player.get("account_id") == account_id:
                return player.get("win", 0) == 1
        
        return False
    except Exception as e:
        logger.error(f"is_win_api error: {e}", exc_info=True)
        return False


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
        
        # Получаем основную информацию об игроке
        player_data = _api_get(f"{OPENDOTA_API_URL}/players/{account_id}")
        if not player_data:
            logger.warning(f"Player data not found for account_id: {account_id}")
            return None

        profile = player_data.get("profile", {})
        rank_tier = player_data.get("rank_tier") or 0
        
        # Получаем статистику побед/поражений
        wl_data = _api_get(f"{OPENDOTA_API_URL}/players/{account_id}/wl")
        if wl_data:
            wins = wl_data.get("win", 0)
            losses = wl_data.get("lose", 0)
            total_games = wins + losses
        else:
            logger.warning(f"Win/Loss data not found for account_id: {account_id}")
            total_games = 0
            wins = 0
            losses = 0
        
        # Используем mmr_estimate для более точного MMR
        mmr_estimate = player_data.get("mmr_estimate", {}).get("estimate", 0)
        mmr = mmr_estimate or rank_to_mmr(rank_tier)
        
        # Вычисляем винрейт
        winrate = safe_winrate(wins, total_games)

        result = {
            "nickname": profile.get("personaname", "Unknown"),
            "mmr": mmr,
            "rank_tier": rank_tier,
            "total_games": total_games,
            "wins": wins,
            "losses": losses,
            "winrate": winrate,
        }
        
        # Сохраняем в кеш
        _set_cached(cache_key, result)
        
        return result

    except Exception as e:
        logger.error(f"stats error: {e}", exc_info=True)
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
        update_user_field(telegram_id, "rank_tier", stats.get("rank_tier", 0))
        update_user_field(telegram_id, "wins", stats.get("wins", 0))
        update_user_field(telegram_id, "losses", stats.get("losses", 0))
        update_user_field(telegram_id, "dota_games", stats["total_games"])
        update_user_field(telegram_id, "dota_wins", stats["wins"])
        # Инициализируем дату начала недели
        update_user_field(telegram_id, "week_start_date", datetime.utcnow().date().isoformat())
        
        # Обновляем недельную статистику сразу после привязки
        update_user_mmr(telegram_id)

        # Формируем строку ранга
        rank_tier = stats.get("rank_tier", 0)
        rank_str = rank_to_string(rank_tier)
        wins = stats.get("wins", 0)
        losses = stats.get("losses", 0)
        total = wins + losses
        winrate = stats.get("winrate", 0)
        
        return {
            "success": True,
            "message": f"✅ {stats['nickname']} | {rank_str}\n📊 {total} игр | ✅ {wins} | ❌ {losses} | {winrate}%"
        }

    except Exception as e:
        logger.error(f"register error: {e}", exc_info=True)
        return {"success": False, "message": "❌ Ошибка"}


# ========================
# 🔄 UPDATE MMR
# ========================

def update_user_mmr(telegram_id: int) -> dict:
    try:
        user = get_user(telegram_id)
        if not user or not user.get("steam_id"):
            return {"success": False, "rank_up": None}

        stats = get_player_stats(user["steam_id"])
        if not stats:
            return {"success": False, "rank_up": None}

        current_games = stats["total_games"]
        current_wins = stats["wins"]

        # === Проверка и сброс недельной статистики ===
        today = datetime.utcnow().date()
        week_start = user.get("week_start_date")
        
        if week_start:
            # Преобразуем строку в дату если нужно
            if isinstance(week_start, str):
                try:
                    week_start = datetime.strptime(week_start, "%Y-%m-%d").date()
                except:
                    logger.warning(f"Invalid week_start_date format for {telegram_id}, using today")
                    week_start = today
        
        week_reset = False
        # Если нет даты начала недели - ставим текущую
        if not week_start:
            update_user_field(telegram_id, "week_start_date", today.isoformat())
            week_start = today
        # Если прошло >= 7 дней - сбрасываем статистику
        elif (today - week_start).days >= 7:
            logger.info(f"Week reset for {telegram_id}: {(today - week_start).days} days passed")
            update_user_field(telegram_id, "week_games", 0)
            update_user_field(telegram_id, "week_wins", 0)
            update_user_field(telegram_id, "week_start_date", today.isoformat())
            week_reset = True
        
        last_games = user.get("last_dota_games", 0)
        last_wins = user.get("dota_wins", 0)
        week_games = user.get("week_games", 0)
        
        logger.info(f"MMR update for {telegram_id}: current_games={current_games}, last_games={last_games}, week_games={week_games}")
        
        # Если это первое обновление - инициализируем недельную статистику
        if last_games == 0:
            logger.info(f"First MMR update for {telegram_id}: initializing week stats")
            update_user_field(telegram_id, "week_games", 0)
            update_user_field(telegram_id, "week_wins", 0)
        elif week_reset:
            # После сброса недели всегда инициализируем новую статистику
            new_games = max(0, current_games - last_games)
            new_wins = max(0, current_wins - last_wins)
            logger.info(f"Week stats initializing after reset for {telegram_id}: new_games={new_games}")
            update_user_field(telegram_id, "week_games", new_games)
            update_user_field(telegram_id, "week_wins", new_wins)
        elif week_games == 0:
            # Если неделя начата, но статистики нет - инициализируем
            new_games = max(0, current_games - last_games)
            new_wins = max(0, current_wins - last_wins)
            logger.info(f"Week stats initializing for {telegram_id}: new_games={new_games}")
            update_user_field(telegram_id, "week_games", new_games)
            update_user_field(telegram_id, "week_wins", new_wins)
        else:
            # Обновляем существующую статистику
            new_games = max(0, current_games - last_games)
            new_wins = max(0, current_wins - last_wins)
            logger.info(f"Updating week stats for {telegram_id}: new_games={new_games}, new_wins={new_wins}")

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

        # Обновляем rank_tier если изменился
        new_rank_tier = stats.get("rank_tier", 0)
        old_rank_tier = user.get("rank_tier", 0)
        
        rank_up = None
        if new_rank_tier > old_rank_tier:
            logger.info(f"Rank UP for {telegram_id}: {old_rank_tier} -> {new_rank_tier}")
            old_rank_str = rank_to_string(old_rank_tier)
            new_rank_str = rank_to_string(new_rank_tier)
            rank_up = {
                "old_rank": old_rank_str,
                "new_rank": new_rank_str
            }
        
        update_user_field(telegram_id, "rank_tier", new_rank_tier)
        update_user_field(telegram_id, "wins", stats.get("wins", 0))
        update_user_field(telegram_id, "losses", stats.get("losses", 0))
        update_user_field(telegram_id, "mmr", stats["mmr"])
        update_user_field(telegram_id, "dota_games", current_games)
        update_user_field(telegram_id, "dota_wins", current_wins)

        return {"success": True, "rank_up": rank_up}

    except Exception as e:
        logger.error(f"update error: {e}", exc_info=True)
        return {"success": False, "rank_up": None}


# ========================
# 🏆 TOP MMR (без API!)
# ========================

def get_mmr_top(limit=10):
    from database import get_dota_mmr_top
    return get_dota_mmr_top(limit)


def get_week_top(limit=10):
    from database import get_dota_week_top
    return get_dota_week_top(limit)


# ========================
# 🎮 MATCHES
# ========================

