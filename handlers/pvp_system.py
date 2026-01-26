"""Полноценная система PvP с матчмейкингом"""

import logging
import random
import asyncio
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timedelta

from database.real_database import db_manager
from game_logic.level_system import CharacterStats
from utils.formatters import format_pvp_result

logger = logging.getLogger(__name__)

class PvPQueue:
    """Система очереди на поиск PvP противника"""
    
    def __init__(self):
        self.queues = {}  # {mmr_range: [user_ids]}
        self.user_queue_status = {}  # {user_id: {'mmr': int, 'timestamp': datetime}}
        self.matchmaking_task = None
    
    async def add_to_queue(self, user_id: int, mmr: int) -> Dict[str, Any]:
        """Добавление пользователя в очередь на поиск"""
        # Определяем диапазон MMR
        mmr_range = (mmr // 100) * 100
        
        if mmr_range not in self.queues:
            self.queues[mmr_range] = []
        
        # Проверяем, есть ли уже подходящий противник
        suitable_opponents = []
        current_time = datetime.now()
        
        for opponent_id in self.queues[mmr_range]:
            if opponent_id != user_id:
                opponent_data = self.user_queue_status.get(opponent_id, {})
                opponent_mmr = opponent_data.get('mmr', 1000)
                
                # Проверяем разницу MMR (максимум 200)
                if abs(mmr - opponent_mmr) <= 200:
                    time_in_queue = current_time - opponent_data.get('timestamp', current_time)
                    # Не дольше 5 минут в очереди
                    if time_in_queue < timedelta(minutes=5):
                        suitable_opponents.append(opponent_id)
        
        # Если есть подходящие противники, создаем матч
        if suitable_opponents:
            opponent_id = random.choice(suitable_opponents)
            
            # Удаляем обоих из очереди
            self.queues[mmr_range].remove(user_id)
            self.queues[mmr_range].remove(opponent_id)
            del self.user_queue_status[user_id]
            del self.user_queue_status[opponent_id]
            
            return {
                'found_match': True,
                'opponent_id': opponent_id,
                'match_type': 'queue'
            }
        
        # Добавляем в очередь
        self.queues[mmr_range].append(user_id)
        self.user_queue_status[user_id] = {
            'mmr': mmr,
            'timestamp': current_time
        }
        
        # Запускаем поиск (если еще не запущен)
        if not self.matchmaking_task:
            self.matchmaking_task = asyncio.create_task(self._matchmaking_loop())
        
        return {
            'found_match': False,
            'queue_position': len(self.queues[mmr_range]),
            'estimated_wait': min(len(self.queues[mmr_range]) * 30, 300)  # Максимум 5 минут
        }
    
    async def remove_from_queue(self, user_id: int) -> bool:
        """Удаление пользователя из очереди"""
        for mmr_range, queue in self.queues.items():
            if user_id in queue:
                queue.remove(user_id)
                if user_id in self.user_queue_status:
                    del self.user_queue_status[user_id]
                return True
        return False
    
    async def _matchmaking_loop(self):
        """Цикл автоматического поиска матчей"""
        try:
            while self.queues:
                await asyncio.sleep(10)  # Проверяем каждые 10 секунд
                
                current_time = datetime.now()
                
                for mmr_range, queue in list(self.queues.items()):
                    if len(queue) < 2:
                        continue
                    
                    # Пытаемся найти пары
                    for i in range(0, len(queue) - 1, 2):
                        user1_id = queue[i]
                        user2_id = queue[i + 1]
                        
                        user1_data = self.user_queue_status.get(user1_id, {})
                        user2_data = self.user_queue_status.get(user2_id, {})
                        
                        user1_mmr = user1_data.get('mmr', 1000)
                        user2_mmr = user2_data.get('mmr', 1000)
                        
                        # Проверяем разницу MMR
                        if abs(user1_mmr - user2_mmr) <= 300:
                            # Создаем матч
                            await self._create_match(user1_id, user2_id)
                            
                            # Удаляем из очереди
                            queue.pop(i + 1)  # Сначала удаляем второго (чтобы индекс первого не изменился)
                            queue.pop(i)
                            
                            del self.user_queue_status[user1_id]
                            del self.user_queue_status[user2_id]
                            
                            break
                
                # Очищаем пустые очереди
                empty_ranges = [r for r, q in self.queues.items() if not q]
                for r in empty_ranges:
                    del self.queues[r]
        
        except Exception as e:
            logger.error(f"Ошибка в цикле матчмейкинга: {e}")
        finally:
            self.matchmaking_task = None
    
    async def _create_match(self, user1_id: int, user2_id: int):
        """Создание PvP матча"""
        try:
            # Здесь можно отправить уведомления пользователям о начале матча
            # Пока просто логируем
            logger.info(f"Создан PvP матч: {user1_id} vs {user2_id}")
        except Exception as e:
            logger.error(f"Ошибка при создании матча: {e}")

class PvPManager:
    """Менеджер PvP боев"""
    
    def __init__(self):
        self.queue = PvPQueue()
        self.active_fights = {}  # {fight_id: fight_data}
    
    async def start_pvp_fight(self, attacker_id: int, defender_id: int) -> Dict[str, Any]:
        """Начало PvP боя"""
        # Получаем данные пользователей
        attacker = await db_manager.get_user(attacker_id)
        defender = await db_manager.get_user(defender_id)
        
        if not attacker or not defender:
            return {'success': False, 'message': 'Один из игроков не найден'}
        
        if attacker_id == defender_id:
            return {'success': False, 'message': 'Нельзя драться с самим собой'}
        
        # Получаем полные характеристики
        attacker_stats = await CharacterStats.get_full_character_stats(attacker_id)
        defender_stats = await CharacterStats.get_full_character_stats(defender_id)
        
        # Симуляция боя
        fight_result = await self._simulate_pvp_fight(attacker_id, defender_id, attacker_stats, defender_stats)
        
        if not fight_result['success']:
            return fight_result
        
        # Обновляем статистику
        await self._update_pvp_stats(attacker_id, defender_id, fight_result)
        
        # Обновляем MMR
        await self._update_mmr(attacker_id, defender_id, fight_result)
        
        return fight_result
    
    async def _simulate_pvp_fight(self, attacker_id: int, defender_id: int, 
                                 attacker_stats: Dict[str, Any], 
                                 defender_stats: Dict[str, Any]) -> Dict[str, Any]:
        """Симуляция PvP боя"""
        attacker_hp = attacker_stats['hp']
        defender_hp = defender_stats['hp']
        
        round_num = 0
        max_rounds = 50
        log = []
        
        while attacker_hp > 0 and defender_hp > 0 and round_num < max_rounds:
            round_num += 1
            
            # Атака атакующего
            damage = self._calculate_pvp_damage(attacker_stats, defender_stats)
            defender_hp -= damage
            log.append(f"Раунд {round_num}: Игрок {attacker_id} нанес {damage} урона")
            
            if defender_hp <= 0:
                break
            
            # Атака защитника
            damage = self._calculate_pvp_damage(defender_stats, attacker_stats)
            attacker_hp -= damage
            log.append(f"Раунд {round_num}: Игрок {defender_id} нанес {damage} урона")
        
        # Определение победителя
        if attacker_hp > defender_hp:
            winner_id = attacker_id
            loser_id = defender_id
            winner_hp = attacker_hp
            loser_hp = defender_hp
        elif defender_hp > attacker_hp:
            winner_id = defender_id
            loser_id = attacker_id
            winner_hp = defender_hp
            loser_hp = attacker_hp
        else:
            # Ничья
            return {
                'success': True,
                'result': 'draw',
                'rounds': round_num,
                'log': log,
                'attacker_hp': attacker_hp,
                'defender_hp': defender_hp
            }
        
        # Получаем имена пользователей
        winner_data = await db_manager.get_user(winner_id)
        loser_data = await db_manager.get_user(loser_id)
        
        winner_name = winner_data.get('username', f'Игрок {winner_id}')
        loser_name = loser_data.get('username', f'Игрок {loser_id}')
        
        return {
            'success': True,
            'result': 'win',
            'winner_id': winner_id,
            'winner_name': winner_name,
            'loser_id': loser_id,
            'loser_name': loser_name,
            'winner_hp': max(winner_hp, 1),
            'loser_hp': max(loser_hp, 0),
            'rounds': round_num,
            'log': log
        }
    
    def _calculate_pvp_damage(self, attacker_stats: Dict[str, Any], defender_stats: Dict[str, Any]) -> int:
        """Рассчет урона в PvP"""
        base_damage = attacker_stats.get('damage', 50)
        
        # Модификаторы от характеристик
        str_bonus = attacker_stats.get('str', 10) * 2
        agi_bonus = attacker_stats.get('agi', 10) * 1.5
        int_bonus = attacker_stats.get('int', 10) * 1.2
        
        # Критический удар
        crit_chance = attacker_stats.get('crit', 5)
        crit_multiplier = 1.0
        if random.random() < crit_chance / 100:
            crit_multiplier = 2.0
        
        # Уклонение
        evasion = defender_stats.get('evasion', 0)
        if random.random() < evasion / 100:
            return 0  # Промах
        
        # Броня
        armor = defender_stats.get('armor', 0)
        armor_reduction = min(armor * 0.05, 0.7)  # Максимальное снижение на 70%
        
        total_damage = (base_damage + str_bonus + agi_bonus + int_bonus) * crit_multiplier
        final_damage = int(total_damage * (1 - armor_reduction))
        
        return max(final_damage, 1)  # Минимум 1 урон
    
    async def _update_pvp_stats(self, attacker_id: int, defender_id: int, fight_result: Dict[str, Any]):
        """Обновление PvP статистики"""
        current_time = datetime.now().isoformat()
        
        if fight_result['result'] == 'win':
            winner_id = fight_result['winner_id']
            loser_id = fight_result['loser_id']
            
            # Обновляем победителя
            await db_manager.update_user(winner_id, {
                'pvp_wins': self.get_pvp_wins(winner_id) + 1,
                'pvp_last_fight': current_time
            })
            
            # Обновляем проигравшего
            await db_manager.update_user(loser_id, {
                'pvp_losses': self.get_pvp_losses(loser_id) + 1,
                'pvp_last_fight': current_time
            })
            
            # Сохраняем информацию о бое
            await self._save_pvp_fight(winner_id, loser_id, fight_result)
        
        elif fight_result['result'] == 'draw':
            # Обновляем ничьи для обоих
            await db_manager.update_user(attacker_id, {
                'pvp_draws': self.get_pvp_draws(attacker_id) + 1,
                'pvp_last_fight': current_time
            })
            await db_manager.update_user(defender_id, {
                'pvp_draws': self.get_pvp_draws(defender_id) + 1,
                'pvp_last_fight': current_time
            })
    
    async def _update_mmr(self, attacker_id: int, defender_id: int, fight_result: Dict[str, Any]):
        """Обновление MMR после боя"""
        attacker_mmr = self.get_mmr(attacker_id)
        defender_mmr = self.get_mmr(defender_id)
        
        # Рассчет изменения MMR (Elo система)
        expected_win_attacker = 1 / (1 + 10 ** ((defender_mmr - attacker_mmr) / 400))
        expected_win_defender = 1 / (1 + 10 ** ((attacker_mmr - defender_mmr) / 400))
        
        k_factor = 32  # Коэффициент изменения рейтинга
        
        if fight_result['result'] == 'win':
            winner_id = fight_result['winner_id']
            loser_id = fight_result['loser_id']
            
            if winner_id == attacker_id:
                new_attacker_mmr = attacker_mmr + k_factor * (1 - expected_win_attacker)
                new_defender_mmr = defender_mmr + k_factor * (0 - expected_win_defender)
            else:
                new_attacker_mmr = attacker_mmr + k_factor * (0 - expected_win_attacker)
                new_defender_mmr = defender_mmr + k_factor * (1 - expected_win_defender)
            
            await db_manager.update_user(attacker_id, {'mmr': int(new_attacker_mmr)})
            await db_manager.update_user(defender_id, {'mmr': int(new_defender_mmr)})
        
        elif fight_result['result'] == 'draw':
            new_attacker_mmr = attacker_mmr + k_factor * (0.5 - expected_win_attacker)
            new_defender_mmr = defender_mmr + k_factor * (0.5 - expected_win_defender)
            
            await db_manager.update_user(attacker_id, {'mmr': int(new_attacker_mmr)})
            await db_manager.update_user(defender_id, {'mmr': int(new_defender_mmr)})
    
    async def _save_pvp_fight(self, winner_id: int, loser_id: int, fight_result: Dict[str, Any]):
        """Сохранение информации о PvP бое"""
        with db_manager.get_connection() as conn:
            try:
                conn.execute("""
                    INSERT INTO pvp_fights (attacker_id, defender_id, winner_id, rounds, fight_log)
                    VALUES (?, ?, ?, ?, ?)
                """, (winner_id, loser_id, winner_id, fight_result['rounds'], 
                      '\n'.join(fight_result['log'])))
                conn.commit()
            except Exception as e:
                logger.error(f"Ошибка при сохранении PvP боя: {e}")
    
    def get_pvp_wins(self, user_id: int) -> int:
        """Получение количества побед (вспомогательная функция)"""
        with db_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT pvp_wins FROM users WHERE id = ?", (user_id,))
            result = cursor.fetchone()
            return result[0] if result else 0
    
    def get_pvp_losses(self, user_id: int) -> int:
        """Получение количества поражений (вспомогательная функция)"""
        with db_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT pvp_losses FROM users WHERE id = ?", (user_id,))
            result = cursor.fetchone()
            return result[0] if result else 0
    
    def get_pvp_draws(self, user_id: int) -> int:
        """Получение количества ничьих (вспомогательная функция)"""
        with db_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT pvp_draws FROM users WHERE id = ?", (user_id,))
            result = cursor.fetchone()
            return result[0] if result else 0
    
    def get_mmr(self, user_id: int) -> int:
        """Получение MMR (вспомогательная функция)"""
        with db_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT mmr FROM users WHERE id = ?", (user_id,))
            result = cursor.fetchone()
            return result[0] if result else 1000

# Глобальный экземпляр PvP менеджера
pvp_manager = PvPManager()

__all__ = ['PvPQueue', 'PvPManager', 'pvp_manager']