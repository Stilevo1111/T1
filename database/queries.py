"""Модуль с SQL-запросами к базе данных"""

import logging
from typing import Dict, List, Optional, Any
from .connection import get_db_pool
from utils.validators import validate_user_id, validate_username

logger = logging.getLogger(__name__)

async def get_user(uid: int, username: str) -> Dict[str, Any]:
    """Получение пользователя по ID, создание если не существует"""
    try:
        if not validate_user_id(uid):
            raise ValueError("Некорректный ID пользователя")
        
        username = validate_username(username)
        pool = get_db_pool()
        if not pool:
            raise RuntimeError("Пул соединений не инициализирован")
        
        async with pool.acquire() as conn:
            user = await conn.fetchrow(
                "SELECT * FROM users WHERE user_id=$1",
                str(uid),
            )
            if not user:
                await conn.execute(
                    "INSERT INTO users (user_id, username) VALUES ($1, $2)",
                    str(uid),
                    username,
                )
                user = await conn.fetchrow(
                    "SELECT * FROM users WHERE user_id=$1",
                    str(uid),
                )
            else:
                # обновляем имя пользователя, если оно изменилось
                if user["username"] != username:
                    await conn.execute(
                        "UPDATE users SET username=$1 WHERE user_id=$2",
                        username,
                        str(uid),
                    )
            return dict(user)
    except Exception as e:
        logger.error(f"Ошибка получения пользователя {uid}: {e}")
        raise

async def get_user_by_id(uid: int) -> Optional[Dict[str, Any]]:
    """Получение пользователя по ID без создания"""
    try:
        if not validate_user_id(uid):
            return None
        
        pool = get_db_pool()
        if not pool:
            raise RuntimeError("Пул соединений не инициализирован")
        
        async with pool.acquire() as conn:
            user = await conn.fetchrow(
                "SELECT * FROM users WHERE user_id=$1",
                str(uid),
            )
            return dict(user) if user else None
    except Exception as e:
        logger.error(f"Ошибка получения пользователя по ID {uid}: {e}")
        return None

async def create_user_if_not_exists(uid: int, username: str) -> Dict[str, Any]:
    """Создание пользователя если не существует"""
    try:
        if not validate_user_id(uid):
            raise ValueError("Некорректный ID пользователя")
        
        username = validate_username(username)
        pool = get_db_pool()
        if not pool:
            raise RuntimeError("Пул соединений не инициализирован")
        
        async with pool.acquire() as conn:
            user = await conn.fetchrow(
                "SELECT * FROM users WHERE user_id=$1",
                str(uid),
            )
            if not user:
                await conn.execute(
                    "INSERT INTO users (user_id, username) VALUES ($1, $2)",
                    str(uid),
                    username,
                )
                user = await conn.fetchrow(
                    "SELECT * FROM users WHERE user_id=$1",
                    str(uid),
                )
            return dict(user)
    except Exception as e:
        logger.error(f"Ошибка создания пользователя {uid}: {e}")
        raise

async def update_user(uid: int, **kwargs) -> None:
    """Обновление данных пользователя с валидацией"""
    try:
        if not validate_user_id(uid):
            raise ValueError("Некорректный ID пользователя")
        
        # Валидация значений
        validated_kwargs = {}
        for key, value in kwargs.items():
            if key == 'username':
                validated_kwargs[key] = validate_username(value)
            elif key in ['level', 'hp', 'hp_max', 'str', 'agi', 'int', 'gold', 'mmr', 'exp', 'boss_dmg', 'boss_hp', 'boss_max', 'boss_level', 'bosses_killed']:
                validated_value = int(value) if value is not None else 0
                if validated_value < 0:
                    continue  # Пропускаем отрицательные значения
                validated_kwargs[key] = validated_value
            elif key in ['last_pvp', 'last_heal', 'last_fissure']:
                validated_kwargs[key] = float(value) if value is not None else 0.0
            elif key in ['boss_name', 'boss_ability']:
                validated_kwargs[key] = str(value)[:100] if value else ''
            elif key == 'fissure':
                validated_kwargs[key] = float(value) if value is not None else 0.0
            elif key == 'items':
                validated_kwargs[key] = value if isinstance(value, list) else [None] * 6
            elif key == 'talents':
                validated_kwargs[key] = value if isinstance(value, dict) else {}
            else:
                validated_kwargs[key] = value
        
        if not validated_kwargs:
            return  # Нечего обновлять
        
        pool = get_db_pool()
        if not pool:
            raise RuntimeError("Пул соединений не инициализирован")
        
        async with pool.acquire() as conn:
            set_clause = ", ".join([f"{k}=${i+1}" for i, k in enumerate(validated_kwargs.keys())])
            values = list(validated_kwargs.values()) + [str(uid)]
            await conn.execute(
                f"UPDATE users SET {set_clause} WHERE user_id=${len(values)}",
                *values
            )
    except Exception as e:
        logger.error(f"Ошибка обновления пользователя {uid}: {e}")
        raise

async def get_top_by_stat(stat: str, limit: int = 10) -> List[Dict[str, Any]]:
    """Получение топа по статистике с кэшированием"""
    try:
        # Валидация параметров
        if stat not in ['level', 'hp', 'gold', 'mmr', 'exp', 'boss_dmg', 'fissure', 'bosses_killed']:
            raise ValueError(f"Некорректная статистика: {stat}")
        
        limit = max(1, min(100, int(limit)))  # Ограничиваем лимит от 1 до 100
        
        pool = get_db_pool()
        if not pool:
            raise RuntimeError("Пул соединений не инициализирован")
        
        async with pool.acquire() as conn:
            return await conn.fetch(f"""
                SELECT username, {stat}
                FROM users
                ORDER BY {stat} DESC
                LIMIT $1
            """, limit)
    except Exception as e:
        logger.error(f"Ошибка получения топа по {stat}: {e}")
        raise

async def get_fissure_top(limit: int = 10) -> List[Dict[str, Any]]:
    """Получение топа по длине фиссуры"""
    return await get_top_by_stat('fissure', limit)

async def update_fissure(uid: int, fissure: float, ts: float) -> None:
    """Обновление длины фиссуры пользователя"""
    try:
        if not validate_user_id(uid):
            raise ValueError("Некорректный ID пользователя")
        
        fissure = max(0.1, float(fissure))  # Минимальная длина 0.1 см
        ts = float(ts)
        
        await update_user(uid, fissure=fissure, last_fissure=ts)
    except Exception as e:
        logger.error(f"Ошибка обновления фиссуры для пользователя {uid}: {e}")
        raise

async def get_pvp_opponents(user_id: int, min_mmr_ratio: float = 0.5, limit: int = 10) -> List[Dict[str, Any]]:
    """Получение списка PvP противников - всех игроков из базы данных"""
    try:
        if not validate_user_id(user_id):
            raise ValueError("Некорректный ID пользователя")
        
        pool = get_db_pool()
        if not pool:
            raise RuntimeError("Пул соединений не инициализирован")
        
        async with pool.acquire() as conn:
            # Получаем всех игроков из базы данных, исключая самого пользователя
            opponents = await conn.fetch("""
                SELECT username, mmr, level, str, agi, int, hp, hp_max, user_id
                FROM users 
                WHERE user_id != $1
                ORDER BY mmr DESC
                LIMIT $2
            """, str(user_id), limit)
            
            logger.info(f"Найдено {len(opponents)} противников для пользователя {user_id}")
            return opponents
    except Exception as e:
        logger.error(f"Ошибка получения списка PvP противников для пользователя {user_id}: {e}")
        raise

async def get_user_stats_summary(user_id: int) -> Optional[Dict[str, Any]]:
    """Получение сводной статистики пользователя"""
    try:
        if not validate_user_id(user_id):
            return None
        
        pool = get_db_pool()
        if not pool:
            raise RuntimeError("Пул соединений не инициализирован")
        
        async with pool.acquire() as conn:
            return await conn.fetchrow("""
                SELECT level, hp, hp_max, str, agi, int, gold, mmr, exp, 
                       boss_dmg, bosses_killed, fissure, talent_points, unspent_stats
                FROM users 
                WHERE user_id = $1
            """, str(user_id))
    except Exception as e:
        logger.error(f"Ошибка получения сводной статистики для пользователя {user_id}: {e}")
        return None