import asyncpg
import sqlite3
import os
from config import DATABASE_URL, logging

# Глобальный пул соединений
db_pool: asyncpg.Pool | None = None
sqlite_conn = None

async def init_db(app):
    """Инициализация базы данных и создание пула соединений"""
    global db_pool, sqlite_conn

    if DATABASE_URL.startswith('sqlite'):
        # SQLite connection
        db_path = DATABASE_URL.replace('sqlite:///', '')
        sqlite_conn = sqlite3.connect(db_path, check_same_thread=False)
        logging.info("Using SQLite database")
        _create_tables_if_not_exists_sqlite()
        _add_talent_fields_if_not_exists_sqlite()
    else:
        # PostgreSQL connection
        db_pool = await asyncpg.create_pool(DATABASE_URL)
        logging.info("Using PostgreSQL database")
        await _create_tables_if_not_exists()
        await _add_talent_fields_if_not_exists()

async def _create_tables_if_not_exists():
    """Создание таблиц, если они не существуют"""
    async with db_pool.acquire() as conn:
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
            logging.info("DB initialized - new table created")
        else:
            # Проверяем, есть ли все необходимые поля
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
                    logging.info(f"DB migration completed - added missing fields: {', '.join(missing_fields)}")
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
                    logging.info("DB migration completed - added boss_ability field")
                else:
                    logging.info("DB initialized - existing table with all required fields")

async def get_user(uid: int, username: str) -> dict:
    """Получение пользователя по ID, создание если не существует"""
    async with db_pool.acquire() as conn:
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

async def update_user(uid: int, **kwargs):
    """Обновление данных пользователя"""
    async with db_pool.acquire() as conn:
        set_clause = ", ".join([f"{k}=${i+1}" for i, k in enumerate(kwargs.keys())])
        values = list(kwargs.values()) + [str(uid)]
        await conn.execute(
            f"UPDATE users SET {set_clause} WHERE user_id=${len(values)}",
            *values
        )

async def get_top_by_stat(stat: str, limit: int = 10):
    """Получение топа по статистике"""
    async with db_pool.acquire() as conn:
        return await conn.fetch(f"""
            SELECT username, {stat}
            FROM users
            ORDER BY {stat} DESC
            LIMIT $1
        """, limit)

async def get_fissure_top(limit: int = 10):
    """Получение топа по длине фиссуры"""
    async with db_pool.acquire() as conn:
        return await conn.fetch("""
            SELECT username, fissure
            FROM users
            ORDER BY fissure DESC
            LIMIT $1
        """, limit)

async def update_fissure(uid: int, fissure: float, ts: float):
    """Обновление длины фиссуры пользователя"""
    async with db_pool.acquire() as conn:
        await conn.execute(
            "UPDATE users SET fissure=$1, last_fissure=$2 WHERE user_id=$3",
            fissure, ts, str(uid),
        )


async def _add_talent_fields_if_not_exists():
    """Добавление полей для системы талантов и уровней"""
    async with db_pool.acquire() as conn:
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
                logging.info(f"Added talent field: {field_name}")

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
                logging.info(f"Added talent effect field: {field_name}")

# SQLite versions of database functions
def _create_tables_if_not_exists_sqlite():
    """Создание таблиц для SQLite, если они не существуют"""
    cursor = sqlite_conn.cursor()

    # Проверяем, есть ли таблица users
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'")
    table_exists = cursor.fetchone()

    if not table_exists:
        # Создаем новую таблицу
        cursor.execute("""
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
                items TEXT DEFAULT '[]',
                boss_dmg INTEGER DEFAULT 0,
                last_pvp REAL DEFAULT 0,
                last_heal REAL DEFAULT 0,
                boss_hp INTEGER DEFAULT 3000,
                boss_name TEXT DEFAULT 'Shadow Fiend',
                boss_max INTEGER DEFAULT 3000,
                boss_level INTEGER DEFAULT 1,
                boss_ability TEXT DEFAULT 'мощные атаки, высокая живучесть',
                fissure REAL DEFAULT 10.0,
                last_fissure REAL DEFAULT 0,
                bosses_killed INTEGER DEFAULT 0,
                talent_points INTEGER DEFAULT 0,
                unspent_stats INTEGER DEFAULT 0,
                talents TEXT DEFAULT '{}',
                title TEXT DEFAULT 'Новичок',
                total_talent_points INTEGER DEFAULT 0,
                boss_damage_bonus REAL DEFAULT 0.0,
                double_strike_chance REAL DEFAULT 0.0,
                berserk_damage REAL DEFAULT 0.0,
                dodge_bonus REAL DEFAULT 0.0,
                crit_chance_bonus REAL DEFAULT 0.0,
                poison_damage REAL DEFAULT 0.0,
                vanish_chance REAL DEFAULT 0.0,
                firestorm_chance REAL DEFAULT 0.0,
                mana_shield REAL DEFAULT 0.0,
                resurrection_chance REAL DEFAULT 0.0,
                all_damage_bonus REAL DEFAULT 0.0,
                phoenix_damage REAL DEFAULT 0.0
            )
        """)
        sqlite_conn.commit()
        logging.info("SQLite DB initialized - new table created")
    else:
        logging.info("SQLite DB initialized - existing table")

def _add_talent_fields_if_not_exists_sqlite():
    """Добавление полей для системы талантов и уровней (SQLite)"""
    cursor = sqlite_conn.cursor()

    # Проверяем и добавляем недостающие поля
    cursor.execute("PRAGMA table_info(users)")
    columns = [column[1] for column in cursor.fetchall()]

    required_fields = [
        'talent_points', 'unspent_stats', 'talents', 'title', 'total_talent_points',
        'boss_damage_bonus', 'double_strike_chance', 'berserk_damage', 'dodge_bonus',
        'crit_chance_bonus', 'poison_damage', 'vanish_chance', 'firestorm_chance',
        'mana_shield', 'resurrection_chance', 'all_damage_bonus', 'phoenix_damage'
    ]

    for field in required_fields:
        if field not in columns:
            if field == 'talents':
                cursor.execute(f"ALTER TABLE users ADD COLUMN {field} TEXT DEFAULT '{{}}'")
            elif field in ['talent_points', 'unspent_stats', 'total_talent_points']:
                cursor.execute(f"ALTER TABLE users ADD COLUMN {field} INTEGER DEFAULT 0")
            elif field == 'title':
                cursor.execute(f"ALTER TABLE users ADD COLUMN {field} TEXT DEFAULT 'Новичок'")
            else:
                cursor.execute(f"ALTER TABLE users ADD COLUMN {field} REAL DEFAULT 0.0")

            sqlite_conn.commit()
            logging.info(f"Added SQLite talent field: {field}")

def get_user_sqlite(uid: int, username: str) -> dict:
    """Получение пользователя по ID для SQLite, создание если не существует"""
    cursor = sqlite_conn.cursor()

    user = cursor.execute("SELECT * FROM users WHERE user_id=?", (str(uid),)).fetchone()

    if not user:
        cursor.execute("INSERT INTO users (user_id, username) VALUES (?, ?)", (str(uid), username))
        sqlite_conn.commit()
        user = cursor.execute("SELECT * FROM users WHERE user_id=?", (str(uid),)).fetchone()

    # Конвертируем в словарь
    column_names = [description[0] for description in cursor.description]
    user_dict = dict(zip(column_names, user))

    # Обновляем имя пользователя, если оно изменилось
    if user_dict["username"] != username:
        cursor.execute("UPDATE users SET username=? WHERE user_id=?", (username, str(uid)))
        sqlite_conn.commit()

    return user_dict

def update_user_sqlite(uid: int, **kwargs):
    """Обновление данных пользователя для SQLite"""
    cursor = sqlite_conn.cursor()

    set_clause = ", ".join([f"{k}=?" for k in kwargs.keys()])
    values = list(kwargs.values()) + [str(uid)]

    cursor.execute(f"UPDATE users SET {set_clause} WHERE user_id=?", values)
    sqlite_conn.commit()

def get_top_by_stat_sqlite(stat: str, limit: int = 10):
    """Получение топа по статистике для SQLite"""
    cursor = sqlite_conn.cursor()
    cursor.execute(f"SELECT username, {stat} FROM users ORDER BY {stat} DESC LIMIT ?", (limit,))
    return cursor.fetchall()

def get_fissure_top_sqlite(limit: int = 10):
    """Получение топа по длине фиссуры для SQLite"""
    cursor = sqlite_conn.cursor()
    cursor.execute("SELECT username, fissure FROM users ORDER BY fissure DESC LIMIT ?", (limit,))
    return cursor.fetchall()

def update_fissure_sqlite(uid: int, fissure: float, ts: float):
    """Обновление длины фиссуры пользователя для SQLite"""
    cursor = sqlite_conn.cursor()
    cursor.execute("UPDATE users SET fissure=?, last_fissure=? WHERE user_id=?", (fissure, ts, str(uid)))
    sqlite_conn.commit()

# Wrapper functions to handle both PostgreSQL and SQLite
def get_user(uid: int, username: str) -> dict:
    """Получение пользователя по ID, создание если не существует"""
    if sqlite_conn:
        return get_user_sqlite(uid, username)
    else:
        # For PostgreSQL, we need to make it async
        async def _get_user_async():
            async with db_pool.acquire() as conn:
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
        return _get_user_async()

def update_user(uid: int, **kwargs):
    """Обновление данных пользователя"""
    if sqlite_conn:
        update_user_sqlite(uid, **kwargs)
    else:
        # For PostgreSQL, we need to make it async
        async def _update_user_async():
            async with db_pool.acquire() as conn:
                set_clause = ", ".join([f"{k}=${i+1}" for i, k in enumerate(kwargs.keys())])
                values = list(kwargs.values()) + [str(uid)]
                await conn.execute(
                    f"UPDATE users SET {set_clause} WHERE user_id=${len(values)}",
                    *values
                )
        return _update_user_async()

def get_top_by_stat(stat: str, limit: int = 10):
    """Получение топа по статистике"""
    if sqlite_conn:
        return get_top_by_stat_sqlite(stat, limit)
    else:
        # For PostgreSQL, we need to make it async
        async def _get_top_by_stat_async():
            async with db_pool.acquire() as conn:
                return await conn.fetch(f"""
                    SELECT username, {stat}
                    FROM users
                    ORDER BY {stat} DESC
                    LIMIT $1
                """, limit)
        return _get_top_by_stat_async()

def get_fissure_top(limit: int = 10):
    """Получение топа по длине фиссуры"""
    if sqlite_conn:
        return get_fissure_top_sqlite(limit)
    else:
        # For PostgreSQL, we need to make it async
        async def _get_fissure_top_async():
            async with db_pool.acquire() as conn:
                return await conn.fetch("""
                    SELECT username, fissure
                    FROM users
                    ORDER BY fissure DESC
                    LIMIT $1
                """, limit)
        return _get_fissure_top_async()

def update_fissure(uid: int, fissure: float, ts: float):
    """Обновление длины фиссуры пользователя"""
    if sqlite_conn:
        update_fissure_sqlite(uid, fissure, ts)
    else:
        # For PostgreSQL, we need to make it async
        async def _update_fissure_async():
            async with db_pool.acquire() as conn:
                await conn.execute(
                    "UPDATE users SET fissure=$1, last_fissure=$2 WHERE user_id=$3",
                    fissure, ts, str(uid),
                )
        return _update_fissure_async()
