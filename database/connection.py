"""Модуль для управления подключением к базе данных"""

import asyncpg
import logging
from typing import Optional, Dict, Any
from config import DATABASE_URL

# Глобальный пул соединений
_db_pool: Optional[asyncpg.Pool] = None
logger = logging.getLogger(__name__)

async def init_db(app) -> None:
    """Инициализация базы данных и создание пула соединений"""
    global _db_pool
    try:
        _db_pool = await asyncpg.create_pool(DATABASE_URL, min_size=5, max_size=20)
        await _create_tables_if_not_exists()
        await _add_talent_fields_if_not_exists()
        logger.info("База данных инициализирована успешно")
    except Exception as e:
        logger.error(f"Ошибка инициализации базы данных: {e}")
        raise

def get_db_pool() -> Optional[asyncpg.Pool]:
    """Получение пула соединений"""
    return _db_pool

async def _create_tables_if_not_exists() -> None:
    """Создание таблиц, если они не существуют"""
    try:
        async with _db_pool.acquire() as conn:
            # Проверяем, есть ли уже таблица users
            table_exists = await conn.fetchval("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_schema = 'public' 
                    AND table_name = 'users'
                )
            """)

            if not table_exists:
                # Создаем новую таблицу
                await conn.execute("""
                    CREATE TABLE users (
                        user_id TEXT PRIMARY KEY,
                        username TEXT,
                        level INTEGER DEFAULT 1,
                        hp INTEGER DEFAULT 100,
                        hp_max INTEGER DEFAULT 100,
                        str INTEGER DEFAULT 5,
                        agi INTEGER DEFAULT 5,
                        int INTEGER DEFAULT 5,
                        gold INTEGER DEFAULT 200,
                        mmr INTEGER DEFAULT 1000,
                        exp INTEGER DEFAULT 0,
                        items TEXT[] DEFAULT ARRAY[NULL,NULL,NULL,NULL,NULL,NULL],
                        boss_dmg INTEGER DEFAULT 0,
                        last_pvp DOUBLE PRECISION DEFAULT 0,
                        last_heal DOUBLE PRECISION DEFAULT 0,
                        boss_hp INTEGER DEFAULT 3000,
                        boss_name TEXT DEFAULT 'Shadow Fiend',
                        boss_max INTEGER DEFAULT 3000,
                        boss_level INTEGER DEFAULT 1,
                        boss_ability TEXT DEFAULT 'мощные атаки, высокая живучесть',
                        fissure REAL DEFAULT 10.0,
                        last_fissure DOUBLE PRECISION DEFAULT 0,
                        bosses_killed INTEGER DEFAULT 0
                    )
                """)
                logger.info("Таблица users создана")
            else:
                await _migrate_existing_table(conn)
    except Exception as e:
        logger.error(f"Ошибка создания таблиц: {e}")
        raise

async def _migrate_existing_table(conn: asyncpg.Connection) -> None:
    """Миграция существующей таблицы"""
    try:
        required_fields = ['level', 'hp', 'hp_max', 'str', 'agi', 'int', 'gold', 'mmr', 'exp', 'items', 'boss_dmg', 'last_pvp', 'last_heal', 'boss_hp', 'boss_name', 'boss_max', 'boss_level', 'boss_ability', 'fissure', 'last_fissure', 'bosses_killed']
        missing_fields = []
        
        for field in required_fields:
            field_exists = await conn.fetchval("""
                SELECT EXISTS (
                    SELECT FROM information_schema.columns 
                    WHERE table_name = 'users' 
                    AND column_name = $1
                )
            """, field)
            if not field_exists:
                missing_fields.append(field)
        
        if missing_fields:
            # Добавляем недостающие поля
            alter_statements = []
            for field in missing_fields:
                if field in ['level', 'hp', 'hp_max', 'str', 'agi', 'int', 'gold', 'mmr', 'exp', 'boss_dmg', 'boss_hp', 'boss_max', 'boss_level', 'bosses_killed']:
                    alter_statements.append(f"ADD COLUMN {field} INTEGER DEFAULT {1 if field in ['level', 'boss_level', 'bosses_killed'] else 100 if field in ['hp', 'hp_max', 'boss_hp', 'boss_max'] else 5 if field in ['str', 'agi', 'int'] else 200 if field == 'gold' else 1000 if field == 'mmr' else 0}")
                elif field in ['last_pvp', 'last_heal', 'last_fissure']:
                    alter_statements.append(f"ADD COLUMN {field} DOUBLE PRECISION DEFAULT 0")
                elif field == 'boss_name':
                    alter_statements.append(f"ADD COLUMN {field} TEXT DEFAULT 'Shadow Fiend'")
                elif field == 'items':
                    alter_statements.append(f"ADD COLUMN {field} TEXT[] DEFAULT ARRAY[NULL,NULL,NULL,NULL,NULL,NULL]")
                elif field == 'fissure':
                    alter_statements.append(f"ADD COLUMN {field} REAL DEFAULT 10.0")
            
            if alter_statements:
                await conn.execute(f"ALTER TABLE users {', '.join(alter_statements)}")
                logger.info(f"Добавлены недостающие поля: {', '.join(missing_fields)}")
        else:
            # Проверяем, есть ли поле boss_ability
            boss_ability_exists = await conn.fetchval("""
                SELECT EXISTS (
                    SELECT FROM information_schema.columns 
                    WHERE table_name = 'users' 
                    AND column_name = 'boss_ability'
                )
            """)
            if not boss_ability_exists:
                await conn.execute("ALTER TABLE users ADD COLUMN boss_ability TEXT DEFAULT 'мощные атаки, высокая живучесть'")
                logger.info("Добавлено поле boss_ability")
    except Exception as e:
        logger.error(f"Ошибка миграции таблицы: {e}")
        raise

async def _add_talent_fields_if_not_exists() -> None:
    """Добавление полей для системы талантов и уровней"""
    try:
        async with _db_pool.acquire() as conn:
            # Проверяем и добавляем поля для талантов
            talent_fields = [
                ('talent_points', 'INTEGER', '0'),
                ('unspent_stats', 'INTEGER', '0'),
                ('talents', 'JSONB', "'{}'::jsonb"),
                ('title', 'VARCHAR(50)', "'Новичок'"),
                ('total_talent_points', 'INTEGER', '0'),
                ('hp_max', 'INTEGER', '100')  # Добавляем hp_max если нет
            ]
            
            for field_name, field_type, default_value in talent_fields:
                field_exists = await conn.fetchval("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.columns 
                        WHERE table_name = 'users' 
                        AND column_name = $1
                    )
                """, field_name)
                
                if not field_exists:
                    await conn.execute(f"ALTER TABLE users ADD COLUMN {field_name} {field_type} DEFAULT {default_value}")
                    logger.info(f"Добавлено поле талантов: {field_name}")
            
            # Проверяем и добавляем поля для эффектов талантов
            talent_effect_fields = [
                ('boss_damage_bonus', 'REAL', '0.0'),
                ('double_strike_chance', 'REAL', '0.0'),
                ('berserk_damage', 'REAL', '0.0'),
                ('dodge_bonus', 'REAL', '0.0'),
                ('crit_chance_bonus', 'REAL', '0.0'),
                ('poison_damage', 'REAL', '0.0'),
                ('vanish_chance', 'REAL', '0.0'),
                ('firestorm_chance', 'REAL', '0.0'),
                ('mana_shield', 'REAL', '0.0'),
                ('resurrection_chance', 'REAL', '0.0'),
                ('all_damage_bonus', 'REAL', '0.0'),
                ('phoenix_damage', 'REAL', '0.0')
            ]
            
            for field_name, field_type, default_value in talent_effect_fields:
                field_exists = await conn.fetchval("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.columns 
                        WHERE table_name = 'users' 
                        AND column_name = $1
                    )
                """, field_name)
                
                if not field_exists:
                    await conn.execute(f"ALTER TABLE users ADD COLUMN {field_name} {field_type} DEFAULT {default_value}")
                    logger.info(f"Добавлено поле эффекта талантов: {field_name}")
    except Exception as e:
        logger.error(f"Ошибка добавления полей талантов: {e}")
        raise