"""Система квестов"""

import logging
import random
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta

from database.real_database import db_manager

logger = logging.getLogger(__name__)

class QuestManager:
    """Менеджер квестов"""
    
    def __init__(self):
        # Определение типов квестов
        self.quest_templates = {
            'boss_kills': {
                'name': 'Охотник на боссов',
                'description': 'Победите {target_count} боссов',
                'target_type': 'bosses_killed',
                'reward_exp': 100,
                'reward_gold': 50,
                'reward_item': None,
                'is_daily': False
            },
            'pvp_wins': {
                'name': 'PvP чемпион',
                'description': 'Победите {target_count} противников в PvP',
                'target_type': 'pvp_wins',
                'reward_exp': 150,
                'reward_gold': 75,
                'reward_item': None,
                'is_daily': False
            },
            'gold_earned': {
                'name': 'Золотой мастер',
                'description': 'Заработайте {target_count} золота',
                'target_type': 'gold',
                'reward_exp': 80,
                'reward_gold': 40,
                'reward_item': None,
                'is_daily': False
            },
            'daily_boss': {
                'name': 'Ежедневный вызов',
                'description': 'Победите 3 боссов',
                'target_type': 'bosses_killed',
                'target_count': 3,
                'reward_exp': 50,
                'reward_gold': 25,
                'reward_item': 'healing_salve',
                'is_daily': True
            },
            'daily_pvp': {
                'name': 'Ежедневный поединок',
                'description': 'Победите 2 противников в PvP',
                'target_type': 'pvp_wins',
                'target_count': 2,
                'reward_exp': 75,
                'reward_gold': 35,
                'reward_item': 'clarity_potion',
                'is_daily': True
            },
            'daily_gold': {
                'name': 'Ежедневный заработок',
                'description': 'Заработайте 200 золота',
                'target_type': 'gold',
                'target_count': 200,
                'reward_exp': 60,
                'reward_gold': 30,
                'reward_item': 'speed_potion',
                'is_daily': True
            }
        }
    
    async def generate_quests_for_user(self, user_id: int) -> List[Dict[str, Any]]:
        """Генерация квестов для пользователя"""
        quests = []
        
        # Генерируем основные квесты (не ежедневные)
        main_quests = ['boss_kills', 'pvp_wins', 'gold_earned']
        selected_main = random.sample(main_quests, 2)  # Выбираем 2 случайных
        
        for quest_type in selected_main:
            template = self.quest_templates[quest_type]
            target_count = self._calculate_target_count(quest_type, user_id)
            
            success = await db_manager.create_quest(
                user_id=user_id,
                quest_type=quest_type,
                target_count=target_count,
                reward_exp=template['reward_exp'],
                reward_gold=template['reward_gold'],
                reward_item=template['reward_item'],
                is_daily=False
            )
            
            if success:
                quests.append({
                    'type': quest_type,
                    'name': template['name'],
                    'description': template['description'].format(target_count=target_count),
                    'target_count': target_count,
                    'current_count': 0,
                    'reward_exp': template['reward_exp'],
                    'reward_gold': template['reward_gold'],
                    'reward_item': template['reward_item']
                })
        
        # Генерируем ежедневные квесты
        daily_quests = ['daily_boss', 'daily_pvp', 'daily_gold']
        
        for quest_type in daily_quests:
            template = self.quest_templates[quest_type]
            
            # Проверяем, не выполнял ли пользователь этот ежедневный квест сегодня
            if not await self._has_completed_daily_quest_today(user_id, quest_type):
                success = await db_manager.create_quest(
                    user_id=user_id,
                    quest_type=quest_type,
                    target_count=template['target_count'],
                    reward_exp=template['reward_exp'],
                    reward_gold=template['reward_gold'],
                    reward_item=template['reward_item'],
                    is_daily=True
                )
                
                if success:
                    quests.append({
                        'type': quest_type,
                        'name': template['name'],
                        'description': template['description'],
                        'target_count': template['target_count'],
                        'current_count': 0,
                        'reward_exp': template['reward_exp'],
                        'reward_gold': template['reward_gold'],
                        'reward_item': template['reward_item'],
                        'is_daily': True
                    })
        
        return quests
    
    def _calculate_target_count(self, quest_type: str, user_id: int) -> int:
        """Рассчет целевого количества для квеста"""
        # Получаем статистику пользователя
        user = db_manager.get_user(user_id)
        if not user:
            return 5  # Стандартное значение
        
        level = user.get('level', 1)
        
        if quest_type == 'boss_kills':
            return max(5, level * 2)
        elif quest_type == 'pvp_wins':
            return max(3, level)
        elif quest_type == 'gold_earned':
            return max(500, level * 100)
        
        return 5
    
    async def _has_completed_daily_quest_today(self, user_id: int, quest_type: str) -> bool:
        """Проверка, выполнял ли пользователь ежедневный квест сегодня"""
        with db_manager.get_connection() as conn:
            cursor = conn.cursor()
            today = datetime.now().date().isoformat()
            
            cursor.execute("""
                SELECT COUNT(*) FROM quests 
                WHERE user_id = ? AND quest_type = ? AND is_daily = 1 
                AND completed_at LIKE ?
            """, (user_id, quest_type, f"{today}%"))
            
            return cursor.fetchone()[0] > 0
    
    async def update_quest_progress(self, user_id: int, quest_type: str, increment: int = 1) -> List[Dict[str, Any]]:
        """Обновление прогресса квестов"""
        completed_quests = []
        
        # Обновляем прогресс для всех активных квестов этого типа
        success = await db_manager.update_quest_progress(user_id, quest_type, increment)
        
        if success:
            # Проверяем, завершились ли какие-то квесты
            completed_quests = await self._check_completed_quests(user_id, quest_type)
        
        return completed_quests
    
    async def _check_completed_quests(self, user_id: int, quest_type: str) -> List[Dict[str, Any]]:
        """Проверка завершенных квестов"""
        completed = []
        
        # Получаем информацию о завершенном квесте
        reward_info = await db_manager.complete_quest(user_id, quest_type)
        
        if reward_info:
            completed.append({
                'type': quest_type,
                'reward_exp': reward_info['exp'],
                'reward_gold': reward_info['gold'],
                'reward_item': reward_info['item']
            })
        
        return completed
    
    async def get_user_quests(self, user_id: int) -> List[Dict[str, Any]]:
        """Получение активных квестов пользователя"""
        with db_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT quest_type, target_count, current_count, reward_exp, 
                       reward_gold, reward_item, is_daily, is_completed
                FROM quests 
                WHERE user_id = ? AND is_completed = 0
                ORDER BY is_daily ASC, created_at DESC
            """, (user_id,))
            
            quests = []
            for row in cursor.fetchall():
                quest_type, target_count, current_count, reward_exp, reward_gold, reward_item, is_daily, is_completed = row
                
                template = self.quest_templates.get(quest_type, {})
                quest_info = {
                    'type': quest_type,
                    'name': template.get('name', quest_type),
                    'description': template.get('description', '').format(target_count=target_count),
                    'target_count': target_count,
                    'current_count': current_count,
                    'reward_exp': reward_exp,
                    'reward_gold': reward_gold,
                    'reward_item': reward_item,
                    'is_daily': bool(is_daily),
                    'progress': min(100, int((current_count / target_count) * 100)) if target_count > 0 else 100
                }
                quests.append(quest_info)
            
            return quests
    
    async def get_completed_quests(self, user_id: int) -> List[Dict[str, Any]]:
        """Получение завершенных квестов"""
        with db_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT quest_type, target_count, reward_exp, reward_gold, 
                       reward_item, completed_at
                FROM quests 
                WHERE user_id = ? AND is_completed = 1
                ORDER BY completed_at DESC
                LIMIT 20
            """, (user_id,))
            
            quests = []
            for row in cursor.fetchall():
                quest_type, target_count, reward_exp, reward_gold, reward_item, completed_at = row
                
                template = self.quest_templates.get(quest_type, {})
                quest_info = {
                    'type': quest_type,
                    'name': template.get('name', quest_type),
                    'target_count': target_count,
                    'reward_exp': reward_exp,
                    'reward_gold': reward_gold,
                    'reward_item': reward_item,
                    'completed_at': completed_at
                }
                quests.append(quest_info)
            
            return quests
    
    async def reset_daily_quests(self, user_id: int) -> List[Dict[str, Any]]:
        """Сброс ежедневных квестов"""
        # Удаляем старые ежедневные квесты
        with db_manager.get_connection() as conn:
            conn.execute("""
                DELETE FROM quests 
                WHERE user_id = ? AND is_daily = 1 AND is_completed = 0
            """, (user_id,))
            conn.commit()
        
        # Генерируем новые
        return await self.generate_quests_for_user(user_id)

# Глобальный экземпляр менеджера квестов
quest_manager = QuestManager()

__all__ = ['QuestManager', 'quest_manager']