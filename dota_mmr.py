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
# 🎮 MATCHES
# ========================

# ========================
# 🦸 HEROES
# ========================

HERO_IMAGE_BASE = "https://cdn.cloudflare.steamstatic.com/apps/dota2/images/dota_react/heroes"
HERO_ICON_BASE = "https://cdn.cloudflare.steamstatic.com/apps/dota2/images/dota_react/heroes/icons"


def get_heroes_data() -> dict:
    """Получить данные всех героев из OpenDota (с кешированием)"""
    cached = _get_cached("heroes_data")
    if cached:
        return cached
    
    try:
        url = f"{OPENDOTA_API_URL}/heroes"
        data = _api_get(url)
        if not data:
            return {}
        
        heroes = {}
        for hero in data:
            hero_id = hero["id"]
            # npc_dota_hero_antimage -> antimage
            short_name = hero["name"].replace("npc_dota_hero_", "")
            heroes[hero_id] = {
                "id": hero_id,
                "name": hero["localized_name"],
                "short_name": short_name,
                "image_url": f"{HERO_IMAGE_BASE}/{short_name}.png",
                "icon_url": f"{HERO_ICON_BASE}/{short_name}.png",
            }
        
        _set_cached("heroes_data", heroes)
        logger.info(f"Loaded {len(heroes)} heroes from OpenDota")
        return heroes
    except Exception as e:
        logger.error(f"get_heroes_data error: {e}", exc_info=True)
        return {}


def get_top_heroes(steam_id: int, last_n: int = 10, top_k: int = 3) -> list:
    """Получить топ-{top_k} популярных героев за последние {last_n} игр"""
    try:
        matches = get_recent_matches(steam_id, limit=last_n)
        if not matches:
            return []
        
        heroes_data = get_heroes_data()
        if not heroes_data:
            return []
        
        # Считаем количество игр на каждом герое
        from collections import Counter
        hero_counts = Counter()
        for match in matches:
            hero_id = match.get("hero_id")
            if hero_id:
                hero_counts[hero_id] += 1
        
        # Берём топ-K
        result = []
        for hero_id, count in hero_counts.most_common(top_k):
            hero_info = heroes_data.get(hero_id)
            if hero_info:
                result.append({
                    "id": hero_id,
                    "name": hero_info["name"],
                    "image_url": hero_info["image_url"],
                    "icon_url": hero_info["icon_url"],
                    "picks": count,
                })
        
        return result
    except Exception as e:
        logger.error(f"get_top_heroes error: {e}", exc_info=True)
        return []


def generate_heroes_image(top_heroes: list) -> bytes | None:
    """Сгенерировать картинку с иконками топ-героев (горизонтально)"""
    try:
        from PIL import Image, ImageDraw, ImageFont
        import io
        import requests as req
        
        if not top_heroes:
            return None
        
        # Размеры
        icon_size = 63  # Стандартный размер иконки OpenDota
        padding = 10
        text_height = 20
        cell_width = icon_size + padding * 2
        cell_height = icon_size + text_height + padding * 2
        width = cell_width * len(top_heroes) + padding
        height = cell_height
        
        # Создаём картинку с тёмным фоном
        img = Image.new("RGB", (width, height), color=(30, 30, 46))
        draw = ImageDraw.Draw(img)
        
        # Пытаемся загрузить шрифт
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 12)
        except:
            try:
                font = ImageFont.truetype("arial.ttf", 12)
            except:
                font = ImageFont.load_default()
        
        for i, hero in enumerate(top_heroes):
            x = padding + i * cell_width
            y = padding
            
            # Скачиваем иконку
            try:
                resp = req.get(hero["icon_url"], timeout=5)
                if resp.status_code == 200:
                    icon = Image.open(io.BytesIO(resp.content)).convert("RGBA")
                    icon = icon.resize((icon_size, icon_size), Image.LANCZOS)
                    img.paste(icon, (x, y), icon)
            except Exception as e:
                logger.debug(f"Could not load hero icon: {e}")
                # Рисуем заглушку
                draw.rectangle([x, y, x + icon_size, y + icon_size], fill=(60, 60, 80))
            
            # Рисуем рамку вокруг иконки
            draw.rectangle([x - 1, y - 1, x + icon_size, y + icon_size], outline=(100, 100, 140), width=1)
            
            # Подпись: "Имя xN"
            name = hero["name"]
            picks = hero["picks"]
            text = f"{name} x{picks}"
            
            # Центрируем текст
            bbox = draw.textbbox((0, 0), text, font=font)
            tw = bbox[2] - bbox[0]
            tx = x + (icon_size - tw) // 2
            ty = y + icon_size + 3
            
            draw.text((tx, ty), text, fill=(200, 200, 220), font=font)
        
        # Сохраняем в байты
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        return buf.read()
    except Exception as e:
        logger.error(f"generate_heroes_image error: {e}", exc_info=True)
        return None

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
    """Конвертировать rank_tier в читаемый вид (например: "Страж 3", "Архонт 5", "Бессмертный")"""
    if not rank_tier:
        return "Не откалиброван"
    
    ranks = ["🌱 Рекрут", "🛡️ Страж", "⚔️ Рыцарь", "🗡️ Герой", "💫 Легенда", "👑 Властелин", "💎 Божество", "🔱 Титан"]
    tier = rank_tier // 10
    star = rank_tier % 10
    
    if tier < 1 or tier > 8:
        return "Неизвестно"
    
    rank_name = ranks[tier - 1]
    
    # Титан не имеет звёзд
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
        
        # Сортируем по start_time (дата матча) чтобы получать последние матчи
        matches = _api_get(url, {"limit": limit, "sort": "start_time"})
        return matches or []
    except Exception as e:
        logger.error(f"get_recent_matches error: {e}", exc_info=True)
        return []


def is_win(match: dict, steam_id: int) -> bool:
    """Определить, выиграл ли игрок матч по данным матча"""
    try:
        # OpenDota API provides direct 'win' field - используем его
        return match.get("win", False)
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

def get_player_stats(steam_id: int, use_cache: bool = True) -> dict:
    try:
        # Проверяем кеш
        cache_key = f"player_{steam_id}"
        if use_cache:
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
        # Создаем пользователя если не существует
        from database import get_user
        user = get_user(telegram_id)
        if not user:
            return {"success": False, "message": "❌ Пользователь не найден. Сначала отправьте /start или /fissure"}
        
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

        logger.info(f"topmmr: calling get_player_stats for steam_id={user['steam_id']}")
        stats = get_player_stats(user["steam_id"], use_cache=False)
        logger.info(f"topmmr: get_player_stats returned: {stats}")
        if not stats:
            return {"success": False, "rank_up": None}

        # Получаем последние матчи для расчёта недельной статистики
        # Фиксированная неделя: с понедельника по воскресенье
        from datetime import datetime, timedelta
        # Используем UTC для расчёта начала недели, затем конвертируем в UTC для сравнения с timestamp
        today_utc = datetime.utcnow()
        monday_utc = today_utc - timedelta(days=today_utc.weekday())
        week_start_utc = monday_utc.replace(hour=0, minute=0, second=0, microsecond=0)
        logger.info(f"topmmr: week start (UTC) = {week_start_utc} (Monday)")
        logger.info(f"topmmr: week start (UTC) = {week_start_utc} (Monday)")
        
        # Получаем последние 50 матчей
        matches = get_recent_matches(user["steam_id"], limit=50)
        
        # Логируем все полученные матчи
        if matches:
            logger.info(f"topmmr: total matches received from API: {len(matches)}")
            for i, match in enumerate(matches):
                match_date = datetime.utcfromtimestamp(match.get("start_time", 0))
                in_week = match_date >= week_start_utc
                logger.info(f"topmmr: match[{i}] id={match.get('match_id')} start_time={match.get('start_time')} date={match_date} week_start={week_start_utc} in_week={in_week}")
                if in_week:
                    # Детальное логирование только для первых 3 матчей в неделе
                    if i < 3:
                        radiant_win = match.get("radiant_win", False)
                        player_is_radiant = match.get("radiant", True)
                        is_win = (player_is_radiant and radiant_win) or (not player_is_radiant and not radiant_win)
                        logger.info(f"topmmr:   -> radiant={player_is_radiant}, radiant_win={radiant_win}, is_win={is_win}")
        else:
            logger.warning("topmmr: no matches received from API")
        
        week_games = 0
        week_wins = 0
        current_streak = 0
        max_streak = 0
        week_current_streak = 0
        
        if matches:
            # Идём от старых к новым, чтобы current_streak в конце = текущий стрик
            for match in reversed(matches):
                try:
                    match_date = datetime.utcfromtimestamp(match.get("start_time", 0))
                    if match_date >= week_start_utc:
                        week_games += 1
                        
                        # Определяем победу используя player_slot и radiant_win
                        player_slot = match.get("player_slot")
                        radiant_win = match.get("radiant_win", False)
                        
                        # Логируем ВСЕ значения для отладки (первые 3 матча)
                        if week_games <= 3:
                            logger.info(f"topmmr: DEBUG match {match.get('match_id')} player_slot={player_slot} radiant_win={radiant_win}")
                        
                        # player_slot: 0-4 = Radiant, 128-132 = Dire
                        if player_slot is not None:
                            player_was_radiant = player_slot < 127
                        else:
                            player_was_radiant = True
                        
                        # Победа: игрок был на стороне победившей команды
                        if radiant_win and player_was_radiant:
                            is_win = True
                        elif not radiant_win and not player_was_radiant:
                            is_win = True
                        else:
                            is_win = False
                        
                        # Логируем только для отладки (можно убрать после проверки)
                        if week_games <= 3:
                            logger.info(f"topmmr: match {match.get('match_id')} - player_was_radiant={player_was_radiant}, is_win={is_win}")
                        if is_win:
                            week_wins += 1
                            current_streak += 1
                            week_current_streak = current_streak
                            if current_streak > max_streak:
                                max_streak = current_streak
                        else:
                            current_streak = 0
                            week_current_streak = 0
                except:
                    pass
        
        logger.info(f"Week stats from matches for {telegram_id}: week_games={week_games}, week_wins={week_wins}, week_streak={max_streak}")
        
        # Проверяем смену недели - если неделя изменилась, сбрасываем статистику
        user_week_start = user.get('week_start_date')
        current_week_start = week_start_utc.strftime("%Y-%m-%d")
        
        if user_week_start and user_week_start != current_week_start:
            logger.info(f"Week changed for {telegram_id}: {user_week_start} -> {current_week_start}, resetting week stats")
            update_user_field(telegram_id, "week_games", 0)
            update_user_field(telegram_id, "week_wins", 0)
            update_user_field(telegram_id, "week_best_streak", 0)
        
        # ВАЖНО: Всегда обновляем недельную статистику из матчей
        # Даже если week_games = 0, все равно обновляем, чтобы сбросить старые данные
        update_user_field(telegram_id, "week_games", week_games)
        update_user_field(telegram_id, "week_wins", week_wins)
        update_user_field(telegram_id, "week_best_streak", max_streak)
        update_user_field(telegram_id, "week_current_streak", week_current_streak)
        update_user_field(telegram_id, "week_start_date", current_week_start)
        logger.info(f"Saved week stats to DB: {week_games} games, {week_wins} wins, week_streak={max_streak}, week_start={week_start_utc}")
        
        # Получаем общие данные
        current_games = stats["total_games"]
        current_wins = stats["wins"]
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
        
        # Обновляем остальные поля
        update_user_field(telegram_id, "rank_tier", new_rank_tier)
        update_user_field(telegram_id, "wins", stats.get("wins", 0))
        update_user_field(telegram_id, "losses", stats.get("losses", 0))
        update_user_field(telegram_id, "mmr", stats["mmr"])

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

