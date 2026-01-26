"""Реальная система базы данных с SQLite"""

import sqlite3
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from contextlib import contextmanager

logger = logging.getLogger(__name__)

class DatabaseManager:
    """Менеджер реальной базы данных"""
    
    def __init__(self, db_path: str = "fissure_bot.db"):
        self.db_path = db_path
        self.init_database()
    
    def init_database(self):
        """Инициализация базы данных"""
        with self.get_connection() as conn:
            # Основная таблица пользователей
            conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY,
                    username TEXT UNIQUE NOT NULL,
                    level INTEGER DEFAULT 1,
                    exp INTEGER DEFAULT 0,
                    gold INTEGER DEFAULT 100,
                    hp INTEGER DEFAULT 1000,
                    max_hp INTEGER DEFAULT 1000,
                    damage INTEGER DEFAULT 50,
                    armor INTEGER DEFAULT 5,
                    str INTEGER DEFAULT 10,
                    agi INTEGER DEFAULT 10,
                    int INTEGER DEFAULT 10,
                    crit INTEGER DEFAULT 5,
                    evasion INTEGER DEFAULT 0,
                    mana INTEGER DEFAULT 200,
                    max_mana INTEGER DEFAULT 200,
                    mmr INTEGER DEFAULT 1000,
                    pvp_wins INTEGER DEFAULT 0,
                    pvp_losses INTEGER DEFAULT 0,
                    pvp_draws INTEGER DEFAULT 0,
                    bosses_killed INTEGER DEFAULT 0,
                    bosses_lost INTEGER DEFAULT 0,
                    total_damage_dealt INTEGER DEFAULT 0,
                    total_damage_taken INTEGER DEFAULT 0,
                    items_bought INTEGER DEFAULT 0,
                    talents_learned INTEGER DEFAULT 0,
                    daily_streak INTEGER DEFAULT 0,
                    daily_rewards_claimed INTEGER DEFAULT 0,
                    last_daily_reward TEXT,
                    pvp_last_fight TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Таблица инвентаря
            conn.execute("""
                CREATE TABLE IF NOT EXISTS inventory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    item_id TEXT,
                    equipped BOOLEAN DEFAULT 0,
                    quantity INTEGER DEFAULT 1,
                    FOREIGN KEY (user_id) REFERENCES users (id)
                )
            """)
            
            # Таблица изученных талантов
            conn.execute("""
                CREATE TABLE IF NOT EXISTS learned_talents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    talent_id TEXT,
                    learned_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (id)
                )
            """)
            
            # Таблица квестов
            conn.execute("""
                CREATE TABLE IF NOT EXISTS quests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    quest_type TEXT,
                    target_count INTEGER,
                    current_count INTEGER DEFAULT 0,
                    reward_exp INTEGER,
                    reward_gold INTEGER,
                    reward_item TEXT,
                    is_completed BOOLEAN DEFAULT 0,
                    is_daily BOOLEAN DEFAULT 0,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    completed_at TEXT,
                    FOREIGN KEY (user_id) REFERENCES users (id)
                )
            """)
            
            # Таблица PvP боев
            conn.execute("""
                CREATE TABLE IF NOT EXISTS pvp_fights (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    attacker_id INTEGER,
                    defender_id INTEGER,
                    winner_id INTEGER,
                    rounds INTEGER,
                    fight_log TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (attacker_id) REFERENCES users (id),
                    FOREIGN KEY (defender_id) REFERENCES users (id),
                    FOREIGN KEY (winner_id) REFERENCES users (id)
                )
            """)
            
            # Таблица боев с боссами
            conn.execute("""
                CREATE TABLE IF NOT EXISTS boss_fights (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    boss_type TEXT,
                    result TEXT,
                    rounds INTEGER,
                    exp_gained INTEGER,
                    gold_gained INTEGER,
                    item_reward TEXT,
                    fight_log TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (id)
                )
            """)
            
            # Таблица Fissure Growth игры
            conn.execute("""
                CREATE TABLE IF NOT EXISTS fissure_growth (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    current_growth INTEGER DEFAULT 0,
                    max_growth INTEGER DEFAULT 100,
                    growth_speed INTEGER DEFAULT 5,
                    game_active BOOLEAN DEFAULT 1,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    last_update TEXT,
                    finished_at TEXT,
                    FOREIGN KEY (user_id) REFERENCES users (id)
                )
            """)
            
            conn.commit()
            logger.info("База данных инициализирована")
    
    @contextmanager
    def get_connection(self):
        """Контекстный менеджер для подключения к БД"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row  # Для доступа к колонкам по имени
        try:
            yield conn
        finally:
            conn.close()
    
    async def get_user(self, user_id: int, username: str = None) -> Optional[Dict[str, Any]]:
        """Получение пользователя из базы данных"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            if username:
                cursor.execute("SELECT * FROM users WHERE id = ? OR username = ?", (user_id, username))
            else:
                cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
            
            row = cursor.fetchone()
            if row:
                return dict(row)
            
            # Если пользователь не найден, создаем нового
            if username:
                await self.create_user(user_id, username)
                return await self.get_user(user_id, username)
            
            return None
    
    async def create_user(self, user_id: int, username: str) -> bool:
        """Создание нового пользователя"""
        with self.get_connection() as conn:
            try:
                conn.execute("""
                    INSERT INTO users (id, username) VALUES (?, ?)
                """, (user_id, username))
                conn.commit()
                logger.info(f"Создан новый пользователь: {username} (ID: {user_id})")
                return True
            except sqlite3.IntegrityError:
                logger.warning(f"Пользователь с ID {user_id} или username {username} уже существует")
                return False
    
    async def update_user(self, user_id: int, updates: Dict[str, Any]) -> bool:
        """Обновление данных пользователя"""
        with self.get_connection() as conn:
            try:
                # Формируем запрос обновления
                set_clauses = []
                values = []
                
                for key, value in updates.items():
                    set_clauses.append(f"{key} = ?")
                    values.append(value)
                
                set_clauses.append("updated_at = CURRENT_TIMESTAMP")
                
                query = f"UPDATE users SET {', '.join(set_clauses)} WHERE id = ?"
                values.append(user_id)
                
                conn.execute(query, values)
                conn.commit()
                return True
            except Exception as e:
                logger.error(f"Ошибка при обновлении пользователя {user_id}: {e}")
                return False
    
    async def get_leaderboard(self, category: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Получение таблицы лидеров"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Определяем колонку для сортировки
            sort_column = {
                'level': 'level',
                'exp': 'exp', 
                'gold': 'gold',
                'mmr': 'mmr',
                'damage': 'damage',
                'wins': 'pvp_wins',
                'bosses': 'bosses_killed'
            }.get(category, 'level')
            
            cursor.execute(f"""
                SELECT username, {sort_column} as value, level, mmr
                FROM users 
                ORDER BY {sort_column} DESC 
                LIMIT ?
            """, (limit,))
            
            return [dict(row) for row in cursor.fetchall()]
    
    async def get_user_stats(self, user_id: int) -> Dict[str, Any]:
        """Получение статистики пользователя"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Основная статистика
            cursor.execute("""
                SELECT 
                    pvp_wins, pvp_losses, pvp_draws,
                    bosses_killed, bosses_lost,
                    total_damage_dealt, total_damage_taken,
                    items_bought, talents_learned,
                    daily_streak, daily_rewards_claimed
                FROM users WHERE id = ?
            """, (user_id,))
            
            stats = dict(cursor.fetchone() or {})
            
            # Статистика PvP боев
            cursor.execute("""
                SELECT COUNT(*) as total_fights,
                       AVG(rounds) as avg_rounds
                FROM pvp_fights 
                WHERE attacker_id = ? OR defender_id = ?
            """, (user_id, user_id))
            
            pvp_stats = dict(cursor.fetchone() or {})
            stats.update(pvp_stats)
            
            # Статистика боев с боссами
            cursor.execute("""
                SELECT 
                    COUNT(*) as total_boss_fights,
                    SUM(CASE WHEN result = 'win' THEN 1 ELSE 0 END) as boss_wins,
                    SUM(CASE WHEN result = 'lose' THEN 1 ELSE 0 END) as boss_losses,
                    AVG(rounds) as avg_boss_rounds
                FROM boss_fights WHERE user_id = ?
            """, (user_id,))
            
            boss_stats = dict(cursor.fetchone() or {})
            stats.update(boss_stats)
            
            return stats
    
    async def add_item_to_inventory(self, user_id: int, item_id: str, quantity: int = 1) -> bool:
        """Добавление предмета в инвентарь"""
        with self.get_connection() as conn:
            try:
                conn.execute("""
                    INSERT INTO inventory (user_id, item_id, quantity)
                    VALUES (?, ?, ?)
                    ON CONFLICT(user_id, item_id) DO UPDATE SET
                    quantity = quantity + excluded.quantity
                """, (user_id, item_id, quantity))
                conn.commit()
                return True
            except Exception as e:
                logger.error(f"Ошибка при добавлении предмета в инвентарь: {e}")
                return False
    
    async def get_user_inventory(self, user_id: int) -> List[Dict[str, Any]]:
        """Получение инвентаря пользователя"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT item_id, quantity, equipped
                FROM inventory WHERE user_id = ?
            """, (user_id,))
            return [dict(row) for row in cursor.fetchall()]
    
    async def learn_talent(self, user_id: int, talent_id: str) -> bool:
        """Изучение таланта"""
        with self.get_connection() as conn:
            try:
                # Проверяем, не изучен ли уже талант
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT COUNT(*) FROM learned_talents 
                    WHERE user_id = ? AND talent_id = ?
                """, (user_id, talent_id))
                
                if cursor.fetchone()[0] > 0:
                    return False  # Талант уже изучен
                
                # Добавляем талант
                conn.execute("""
                    INSERT INTO learned_talents (user_id, talent_id)
                    VALUES (?, ?)
                """, (user_id, talent_id))
                conn.commit()
                return True
            except Exception as e:
                logger.error(f"Ошибка при изучении таланта: {e}")
                return False
    
    async def get_learned_talents(self, user_id: int) -> List[str]:
        """Получение изученных талантов"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT talent_id FROM learned_talents WHERE user_id = ?
            """, (user_id,))
            return [row[0] for row in cursor.fetchall()]
    
    async def create_quest(self, user_id: int, quest_type: str, target_count: int, 
                          reward_exp: int, reward_gold: int, reward_item: str = None, 
                          is_daily: bool = False) -> bool:
        """Создание квеста"""
        with self.get_connection() as conn:
            try:
                conn.execute("""
                    INSERT INTO quests (user_id, quest_type, target_count, 
                                      reward_exp, reward_gold, reward_item, is_daily)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (user_id, quest_type, target_count, reward_exp, reward_gold, 
                      reward_item, is_daily))
                conn.commit()
                return True
            except Exception as e:
                logger.error(f"Ошибка при создании квеста: {e}")
                return False
    
    async def update_quest_progress(self, user_id: int, quest_type: str, increment: int = 1) -> bool:
        """Обновление прогресса квеста"""
        with self.get_connection() as conn:
            try:
                conn.execute("""
                    UPDATE quests SET current_count = current_count + ?
                    WHERE user_id = ? AND quest_type = ? AND is_completed = 0
                """, (increment, user_id, quest_type))
                conn.commit()
                return True
            except Exception as e:
                logger.error(f"Ошибка при обновлении прогресса квеста: {e}")
                return False
    
    async def complete_quest(self, user_id: int, quest_type: str) -> Optional[Dict[str, Any]]:
        """Завершение квеста и получение награды"""
        with self.get_connection() as conn:
            try:
                # Получаем информацию о квесте
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT id, reward_exp, reward_gold, reward_item, current_count, target_count
                    FROM quests 
                    WHERE user_id = ? AND quest_type = ? AND is_completed = 0
                """, (user_id, quest_type))
                
                quest = cursor.fetchone()
                if not quest:
                    return None
                
                quest_id, reward_exp, reward_gold, reward_item, current_count, target_count = quest
                
                # Проверяем, выполнен ли квест
                if current_count < target_count:
                    return None
                
                # Отмечаем квест как выполненный
                conn.execute("""
                    UPDATE quests SET is_completed = 1, completed_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                """, (quest_id,))
                
                # Обновляем статистику пользователя
                await self.update_user(user_id, {
                    'exp': self.get_user_exp(user_id) + reward_exp,
                    'gold': self.get_user_gold(user_id) + reward_gold
                })
                
                # Добавляем предмет, если есть
                if reward_item:
                    await self.add_item_to_inventory(user_id, reward_item)
                
                conn.commit()
                
                return {
                    'exp': reward_exp,
                    'gold': reward_gold,
                    'item': reward_item
                }
            except Exception as e:
                logger.error(f"Ошибка при завершении квеста: {e}")
                return None
    
    def get_user_exp(self, user_id: int) -> int:
        """Получение опыта пользователя (вспомогательная функция)"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT exp FROM users WHERE id = ?", (user_id,))
            result = cursor.fetchone()
            return result[0] if result else 0
    
    def get_user_gold(self, user_id: int) -> int:
        """Получение золота пользователя (вспомогательная функция)"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT gold FROM users WHERE id = ?", (user_id,))
            result = cursor.fetchone()
            return result[0] if result else 0

# Глобальный экземпляр менеджера базы данных
db_manager = DatabaseManager()

__all__ = ['DatabaseManager', 'db_manager']