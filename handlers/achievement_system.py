"""Система достижений"""

import logging
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta

from database.real_database import db_manager

logger = logging.getLogger(__name__)

class AchievementManager:
    """Менеджер достижений"""
    
    def __init__(self):
        # Определение достижений
        self.achievements_db = {
            # Боевые достижения
            'first_win': {
                'name': 'Первая Победа',
                'description': 'Победите в первом бою с боссом',
                'category': 'combat',
                'target_value': 1,
                'progress_type': 'bosses_killed',
                'reward_exp': 100,
                'reward_gold': 50,
                'icon': '🏆'
            },
            'boss_hunter': {
                'name': 'Охотник на Боссов',
                'description': 'Победите 10 боссов',
                'category': 'combat',
                'target_value': 10,
                'progress_type': 'bosses_killed',
                'reward_exp': 500,
                'reward_gold': 250,
                'icon': '🗡️'
            },
            'unstoppable': {
                'name': 'Непобедимый',
                'description': 'Победите 50 боссов',
                'category': 'combat',
                'target_value': 50,
                'progress_type': 'bosses_killed',
                'reward_exp': 2000,
                'reward_gold': 1000,
                'icon': '🔥'
            },
            'pvp_champion': {
                'name': 'PvP Чемпион',
                'description': 'Победите 20 игроков в PvP',
                'category': 'pvp',
                'target_value': 20,
                'progress_type': 'pvp_wins',
                'reward_exp': 1000,
                'reward_gold': 500,
                'icon': '⚔️'
            },
            'survivor': {
                'name': 'Выживший',
                'description': 'Переживите бой с боссом, получив менее 10% HP',
                'category': 'combat',
                'target_value': 1,
                'progress_type': 'survivor_bosses',
                'reward_exp': 300,
                'reward_gold': 150,
                'icon': '🛡️'
            },
            
            # Экономические достижения
            'rich': {
                'name': 'Богач',
                'description': 'Накопите 10000 золота',
                'category': 'economy',
                'target_value': 10000,
                'progress_type': 'gold',
                'reward_exp': 500,
                'reward_gold': 250,
                'icon': '💰'
            },
            'shopaholic': {
                'name': 'Шопоголик',
                'description': 'Потратьте 5000 золота в магазине',
                'category': 'economy',
                'target_value': 5000,
                'progress_type': 'gold_spent',
                'reward_exp': 300,
                'reward_gold': 150,
                'icon': '🛒'
            },
            'investor': {
                'name': 'Инвестор',
                'description': 'Купите 50 предметов',
                'category': 'economy',
                'target_value': 50,
                'progress_type': 'items_bought',
                'reward_exp': 400,
                'reward_gold': 200,
                'icon': '🛍️'
            },
            
            # Развитие персонажа
            'level_10': {
                'name': 'Начинающий',
                'description': 'Достигните 10 уровня',
                'category': 'progress',
                'target_value': 10,
                'progress_type': 'level',
                'reward_exp': 200,
                'reward_gold': 100,
                'icon': '📈'
            },
            'level_25': {
                'name': 'Опытный',
                'description': 'Достигните 25 уровня',
                'category': 'progress',
                'target_value': 25,
                'progress_type': 'level',
                'reward_exp': 800,
                'reward_gold': 400,
                'icon': '🚀'
            },
            'level_50': {
                'name': 'Мастер',
                'description': 'Достигните 50 уровня',
                'category': 'progress',
                'target_value': 50,
                'progress_type': 'level',
                'reward_exp': 2000,
                'reward_gold': 1000,
                'icon': '👑'
            },
            'talent_master': {
                'name': 'Мастер Талантов',
                'description': 'Изучите 10 талантов',
                'category': 'progress',
                'target_value': 10,
                'progress_type': 'talents_learned',
                'reward_exp': 500,
                'reward_gold': 250,
                'icon': '🧠'
            },
            
            # PvP достижения
            'first_blood': {
                'name': 'Первая Кровь',
                'description': 'Победите в первом PvP бою',
                'category': 'pvp',
                'target_value': 1,
                'progress_type': 'pvp_wins',
                'reward_exp': 100,
                'reward_gold': 50,
                'icon': '🩸'
            },
            'gladiator': {
                'name': 'Гладиатор',
                'description': 'Победите 100 игроков в PvP',
                'category': 'pvp',
                'target_value': 100,
                'progress_type': 'pvp_wins',
                'reward_exp': 3000,
                'reward_gold': 1500,
                'icon': '🪓'
            },
            'undefeated': {
                'name': 'Непобедимый',
                'description': 'Выиграйте 10 PvP боев подряд',
                'category': 'pvp',
                'target_value': 10,
                'progress_type': 'pvp_wins_streak',
                'reward_exp': 1000,
                'reward_gold': 500,
                'icon': '🔥'
            },
            
            # Квесты и задания
            'quest_master': {
                'name': 'Мастер Квестов',
                'description': 'Выполните 20 квестов',
                'category': 'quests',
                'target_value': 20,
                'progress_type': 'quests_completed',
                'reward_exp': 600,
                'reward_gold': 300,
                'icon': '📜'
            },
            'daily_hero': {
                'name': 'Герой Дня',
                'description': 'Выполните ежедневные квесты 7 дней подряд',
                'category': 'quests',
                'target_value': 7,
                'progress_type': 'daily_streak',
                'reward_exp': 400,
                'reward_gold': 200,
                'icon': '☀️'
            },
            
            # Fissure достижения
            'dimensional_traveler': {
                'name': 'Путешественник Измерений',
                'description': 'Посетите Fissure 10 раз',
                'category': 'fissure',
                'target_value': 10,
                'progress_type': 'fissure_visits',
                'reward_exp': 500,
                'reward_gold': 250,
                'icon': '🌀'
            },
            'blessed': {
                'name': 'Благословенный',
                'description': 'Получите 5 положительных эффектов от Fissure',
                'category': 'fissure',
                'target_value': 5,
                'progress_type': 'positive_fissure_effects',
                'reward_exp': 300,
                'reward_gold': 150,
                'icon': '✨'
            },
            'cursed': {
                'name': 'Проклятый',
                'description': 'Получите 5 отрицательных эффектов от Fissure',
                'category': 'fissure',
                'target_value': 5,
                'progress_type': 'negative_fissure_effects',
                'reward_exp': 200,
                'reward_gold': 100,
                'icon': '💀'
            }
        }
    
    async def check_achievements(self, user_id: int, progress_type: str, value: int = 1) -> List[Dict[str, Any]]:
        """Проверка выполнения достижений"""
        completed_achievements = []
        
        # Получаем прогресс пользователя
        user_progress = await self.get_user_progress(user_id)
        
        for achievement_id, achievement_data in self.achievements_db.items():
            # Проверяем, не выполнено ли уже достижение
            if await self.is_achievement_completed(user_id, achievement_id):
                continue
            
            # Проверяем, подходит ли тип прогресса
            if achievement_data['progress_type'] != progress_type:
                continue
            
            # Обновляем прогресс
            current_progress = user_progress.get(progress_type, 0)
            new_progress = current_progress + value
            
            # Проверяем выполнение
            if new_progress >= achievement_data['target_value']:
                # Достижение выполнено!
                reward = await self.complete_achievement(user_id, achievement_id, achievement_data)
                
                completed_achievements.append({
                    'id': achievement_id,
                    'name': achievement_data['name'],
                    'description': achievement_data['description'],
                    'category': achievement_data['category'],
                    'reward': reward,
                    'icon': achievement_data['icon']
                })
        
        return completed_achievements
    
    async def complete_achievement(self, user_id: int, achievement_id: str, achievement_data: Dict[str, Any]) -> Dict[str, Any]:
        """Завершение достижения"""
        # Сохраняем в базу данных
        with db_manager.get_connection() as conn:
            try:
                conn.execute("""
                    INSERT INTO achievements (
                        user_id, achievement_id, achievement_name, 
                        achievement_category, completed_at
                    ) VALUES (?, ?, ?, ?, ?)
                """, (
                    user_id, achievement_id, achievement_data['name'],
                    achievement_data['category'], datetime.now().isoformat()
                ))
                
                # Начисляем награду
                user = await db_manager.get_user(user_id)
                if user:
                    new_exp = user.get('exp', 0) + achievement_data['reward_exp']
                    new_gold = user.get('gold', 0) + achievement_data['reward_gold']
                    
                    await db_manager.update_user(user_id, {
                        'exp': new_exp,
                        'gold': new_gold
                    })
                
                conn.commit()
                
                return {
                    'exp': achievement_data['reward_exp'],
                    'gold': achievement_data['reward_gold']
                }
            except Exception as e:
                logger.error(f"Ошибка при завершении достижения: {e}")
                return {'exp': 0, 'gold': 0}
    
    async def is_achievement_completed(self, user_id: int, achievement_id: str) -> bool:
        """Проверка, выполнено ли достижение"""
        with db_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT COUNT(*) FROM achievements 
                WHERE user_id = ? AND achievement_id = ?
            """, (user_id, achievement_id))
            
            return cursor.fetchone()[0] > 0
    
    async def get_user_progress(self, user_id: int) -> Dict[str, int]:
        """Получение прогресса пользователя по всем достижениям"""
        user = await db_manager.get_user(user_id)
        if not user:
            return {}
        
        # Получаем статистику пользователя
        stats = await db_manager.get_user_stats(user_id)
        
        # Формируем прогресс
        progress = {
            'bosses_killed': user.get('bosses_killed', 0),
            'pvp_wins': user.get('pvp_wins', 0),
            'gold': user.get('gold', 0),
            'items_bought': user.get('items_bought', 0),
            'level': user.get('level', 1),
            'talents_learned': user.get('talents_learned', 0),
            'quests_completed': stats.get('boss_wins', 0),  # Используем победы как пример
            'daily_streak': user.get('daily_streak', 0),
            'fissure_visits': 0,  # Нужно будет отслеживать отдельно
            'positive_fissure_effects': 0,
            'negative_fissure_effects': 0,
            'survivor_bosses': 0,
            'gold_spent': 0
        }
        
        return progress
    
    async def get_user_achievements(self, user_id: int) -> Dict[str, Any]:
        """Получение всех достижений пользователя"""
        with db_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT achievement_id, achievement_name, achievement_category, completed_at
                FROM achievements 
                WHERE user_id = ?
                ORDER BY completed_at DESC
            """, (user_id,))
            
            completed = []
            for row in cursor.fetchall():
                achievement_id, achievement_name, achievement_category, completed_at = row
                completed.append({
                    'id': achievement_id,
                    'name': achievement_name,
                    'category': achievement_category,
                    'completed_at': completed_at
                })
            
            # Получаем прогресс по незавершенным достижениям
            user_progress = await self.get_user_progress(user_id)
            in_progress = []
            
            for achievement_id, achievement_data in self.achievements_db.items():
                if not await self.is_achievement_completed(user_id, achievement_id):
                    current_progress = user_progress.get(achievement_data['progress_type'], 0)
                    progress_percent = int((current_progress / achievement_data['target_value']) * 100)
                    
                    in_progress.append({
                        'id': achievement_id,
                        'name': achievement_data['name'],
                        'description': achievement_data['description'],
                        'category': achievement_data['category'],
                        'current_progress': current_progress,
                        'target_progress': achievement_data['target_value'],
                        'progress_percent': min(100, progress_percent),
                        'icon': achievement_data['icon']
                    })
            
            return {
                'completed': completed,
                'in_progress': in_progress,
                'total_completed': len(completed),
                'total_achievements': len(self.achievements_db),
                'completion_percent': int((len(completed) / len(self.achievements_db)) * 100) if self.achievements_db else 0
            }
    
    async def get_achievement_statistics(self, user_id: int) -> Dict[str, Any]:
        """Получение статистики по достижениям"""
        achievements = await self.get_user_achievements(user_id)
        
        # Группируем по категориям
        categories = {}
        for achievement in achievements['completed']:
            category = achievement['category']
            if category not in categories:
                categories[category] = 0
            categories[category] += 1
        
        # Рассчитываем прогресс по категориям
        category_progress = {}
        for category in ['combat', 'pvp', 'economy', 'progress', 'quests', 'fissure']:
            category_achievements = [a for a in self.achievements_db.values() if a['category'] == category]
            completed_count = sum(1 for a in achievements['completed'] if a['category'] == category)
            
            category_progress[category] = {
                'total': len(category_achievements),
                'completed': completed_count,
                'progress': int((completed_count / len(category_achievements)) * 100) if category_achievements else 0
            }
        
        return {
            'total_completed': achievements['total_completed'],
            'total_achievements': achievements['total_achievements'],
            'completion_percent': achievements['completion_percent'],
            'categories': category_progress,
            'best_category': max(categories.items(), key=lambda x: x[1])[0] if categories else None,
            'recent_achievements': achievements['completed'][:5]  # Последние 5 достижений
        }
    
    async def get_leaderboard(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Получение таблицы лидеров по достижениям"""
        with db_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT username, COUNT(*) as achievements_count
                FROM achievements a
                JOIN users u ON a.user_id = u.id
                GROUP BY a.user_id, u.username
                ORDER BY achievements_count DESC
                LIMIT ?
            """, (limit,))
            
            return [{'username': row[0], 'count': row[1]} for row in cursor.fetchall()]

# Глобальный экземпляр менеджера достижений
achievement_manager = AchievementManager()

# Функция для регистрации обработчиков достижений
def register_achievement_handlers(application):
    """Регистрация обработчиков системы достижений"""
    # Здесь можно добавить обработчики команд достижений
    pass

__all__ = ['AchievementManager', 'achievement_manager', 'register_achievement_handlers']
