"""Система Fissure - случайные эффекты и бонусы"""

import logging
import random
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timedelta

from database.real_database import db_manager
from game_logic.level_system import CharacterStats

logger = logging.getLogger(__name__)

class FissureSystem:
    """Система Fissure - порталы с случайными эффектами"""
    
    def __init__(self):
        # Определение типов Fissure эффектов
        self.fissure_effects = {
            # Положительные эффекты
            'blessing_of_strength': {
                'name': 'Благословение Силы',
                'description': 'Временно увеличивает Силу на 20',
                'type': 'positive',
                'duration': 300,  # 5 минут
                'stats': {'str': 20},
                'rarity': 'common'
            },
            'blessing_of_agility': {
                'name': 'Благословение Ловкости',
                'description': 'Временно увеличивает Ловкость на 20',
                'type': 'positive',
                'duration': 300,
                'stats': {'agi': 20},
                'rarity': 'common'
            },
            'blessing_of_intelligence': {
                'name': 'Благословение Интеллекта',
                'description': 'Временно увеличивает Интеллект на 20',
                'type': 'positive',
                'duration': 300,
                'stats': {'int': 20},
                'rarity': 'common'
            },
            'rage_of_battle': {
                'name': 'Ярость Битвы',
                'description': 'Увеличивает урон на 25% и скорость атаки на 15%',
                'type': 'positive',
                'duration': 180,  # 3 минуты
                'stats': {'damage_mult': 1.25, 'speed_mult': 1.15},
                'rarity': 'uncommon'
            },
            'shield_of_ancients': {
                'name': 'Щит Древних',
                'description': 'Увеличивает броню на 50% и блокировку на 30%',
                'type': 'positive',
                'duration': 240,  # 4 минуты
                'stats': {'armor_mult': 1.5, 'block_mult': 1.3},
                'rarity': 'uncommon'
            },
            'wisdom_of_mages': {
                'name': 'Мудрость Магов',
                'description': 'Увеличивает силу заклинаний на 40% и максимальную ману на 25%',
                'type': 'positive',
                'duration': 300,
                'stats': {'spell_damage_mult': 1.4, 'mana_mult': 1.25},
                'rarity': 'uncommon'
            },
            'fortune_of_the_brave': {
                'name': 'Удача Храбреца',
                'description': 'Увеличивает шанс критического удара на 20% и уклонение на 15%',
                'type': 'positive',
                'duration': 180,
                'stats': {'crit_mult': 1.2, 'evasion_mult': 1.15},
                'rarity': 'rare'
            },
            'divine_protection': {
                'name': 'Божественная Защита',
                'description': 'Полностью восстанавливает HP и дает 50% сопротивления магии',
                'type': 'positive',
                'duration': 600,  # 10 минут
                'stats': {'magic_resist_mult': 1.5},
                'heal': 100,
                'rarity': 'rare'
            },
            'legendary_power': {
                'name': 'Легендарная Сила',
                'description': 'Все характеристики увеличены на 30%, весь урон на 50%',
                'type': 'positive',
                'duration': 120,  # 2 минуты
                'stats': {'all_stats_mult': 1.3, 'all_damage_mult': 1.5},
                'rarity': 'epic'
            },
            
            # Отрицательные эффекты
            'curse_of_weakness': {
                'name': 'Проклятие Слабости',
                'description': 'Уменьшает Силу на 15',
                'type': 'negative',
                'duration': 180,
                'stats': {'str': -15},
                'rarity': 'common'
            },
            'curse_of_slowness': {
                'name': 'Проклятие Медлительности',
                'description': 'Уменьшает скорость атаки на 20%',
                'type': 'negative',
                'duration': 240,
                'stats': {'speed_mult': 0.8},
                'rarity': 'common'
            },
            'curse_of_fatigue': {
                'name': 'Проклятие Усталости',
                'description': 'Уменьшает максимальную ману на 30%',
                'type': 'negative',
                'duration': 300,
                'stats': {'mana_mult': 0.7},
                'rarity': 'common'
            },
            'mark_of_the_beast': {
                'name': 'Метка Зверя',
                'description': 'Уменьшает броню на 25% и увеличивает получаемый урон на 10%',
                'type': 'negative',
                'duration': 180,
                'stats': {'armor_mult': 0.75, 'damage_taken_mult': 1.1},
                'rarity': 'uncommon'
            },
            'shadow_binding': {
                'name': 'Теневое Оковы',
                'description': 'Уменьшает уклонение на 50% и шанс критического удара на 30%',
                'type': 'negative',
                'duration': 240,
                'stats': {'evasion_mult': 0.5, 'crit_mult': 0.7},
                'rarity': 'uncommon'
            },
            'drain_of_life': {
                'name': 'Истощение Жизни',
                'description': 'Постоянно теряете 5% HP в секунду',
                'type': 'negative',
                'duration': 120,
                'stats': {'hp_drain': 5},
                'rarity': 'rare'
            },
            'chaos_magic': {
                'name': 'Хаосная Магия',
                'description': 'Случайные эффекты каждые 30 секунд',
                'type': 'negative',
                'duration': 180,
                'stats': {'chaos': True},
                'rarity': 'rare'
            },
            'ancient_curse': {
                'name': 'Древнее Проклятие',
                'description': 'Все характеристики уменьшены на 20%, весь урон на 30%',
                'type': 'negative',
                'duration': 300,
                'stats': {'all_stats_mult': 0.8, 'all_damage_mult': 0.7},
                'rarity': 'epic'
            },
            
            # Нейтральные эффекты
            'dimensional_shift': {
                'name': 'Пространственный Сдвиг',
                'description': 'Случайный телепорт в другое измерение',
                'type': 'neutral',
                'duration': 0,
                'stats': {'teleport': True},
                'rarity': 'common'
            },
            'time_warp': {
                'name': 'Искривление Времени',
                'description': 'Время течет иначе',
                'type': 'neutral',
                'duration': 60,
                'stats': {'time_warp': True},
                'rarity': 'uncommon'
            },
            'reality_glitch': {
                'name': 'Глюк Реальности',
                'description': 'Все эффекты удваиваются',
                'type': 'neutral',
                'duration': 60,
                'stats': {'glitch': True},
                'rarity': 'rare'
            }
        }
        
        # Вероятности выпадения эффектов
        self.rarity_weights = {
            'common': 50,
            'uncommon': 30,
            'rare': 15,
            'epic': 5
        }
    
    async def enter_fissure(self, user_id: int) -> Dict[str, Any]:
        """Вход в Fissure"""
        user = await db_manager.get_user(user_id)
        if not user:
            return {'success': False, 'message': 'Пользователь не найден'}
        
        # Проверяем, не в Fissure ли пользователь уже
        if await self.is_in_fissure(user_id):
            return {'success': False, 'message': 'Вы уже находитесь в Fissure'}
        
        # Запускаем интерактивную игру Fissure Growth
        growth_result = await self._start_fissure_growth_game(user_id)
        
        if not growth_result['success']:
            return growth_result
        
        # Выбираем случайный эффект на основе роста Fissure
        effect = self._select_effect_based_on_growth(growth_result['growth_level'])
        
        # Применяем эффект
        result = await self._apply_fissure_effect(user_id, effect)
        
        # Добавляем информацию о росте
        result['growth_level'] = growth_result['growth_level']
        result['growth_message'] = growth_result['message']
        
        return result
    
    async def _start_fissure_growth_game(self, user_id: int) -> Dict[str, Any]:
        """Запуск интерактивной игры Fissure Growth"""
        # Fissure начинает расти, пользователь должен нажимать кнопки вовремя
        growth_level = 0
        max_growth = 100
        growth_speed = 5  # Скорость роста за шаг
        
        # Сохраняем состояние игры
        with db_manager.get_connection() as conn:
            try:
                conn.execute("""
                    INSERT INTO fissure_growth (
                        user_id, current_growth, max_growth, growth_speed, 
                        game_active, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                """, (user_id, growth_level, max_growth, growth_speed, 1, datetime.now().isoformat()))
                conn.commit()
                
                return {
                    'success': True,
                    'growth_level': growth_level,
                    'message': '🌀 Fissure начинает расти! Нажимайте /grow_fissure чтобы контролировать рост!'
                }
            except Exception as e:
                logger.error(f"Ошибка при запуске игры Fissure Growth: {e}")
                return {'success': False, 'message': 'Ошибка при входе в Fissure'}
    
    async def grow_fissure(self, user_id: int) -> Dict[str, Any]:
        """Контроль роста Fissure"""
        # Получаем текущее состояние игры
        with db_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT current_growth, max_growth, growth_speed, game_active
                FROM fissure_growth 
                WHERE user_id = ? AND game_active = 1
                ORDER BY created_at DESC LIMIT 1
            """, (user_id,))
            
            row = cursor.fetchone()
            if not row:
                return {'success': False, 'message': 'Игра Fissure не активна'}
            
            current_growth, max_growth, growth_speed, game_active = row
            
            # Увеличиваем рост
            new_growth = min(current_growth + growth_speed, max_growth)
            
            # Проверяем, достиг ли Fissure максимального роста
            if new_growth >= max_growth:
                # Игра завершена, Fissure взорвалась
                await self._finish_fissure_growth(user_id, new_growth, conn)
                
                return {
                    'success': True,
                    'growth_level': new_growth,
                    'message': '💥 Fissure достигла максимального роста и взорвалась! Получите мощный эффект!',
                    'explosion': True
                }
            else:
                # Обновляем рост
                cursor.execute("""
                    UPDATE fissure_growth 
                    SET current_growth = ?, last_update = ?
                    WHERE user_id = ? AND game_active = 1
                """, (new_growth, datetime.now().isoformat(), user_id))
                conn.commit()
                
                return {
                    'success': True,
                    'growth_level': new_growth,
                    'message': f'🌀 Fissure растет... {new_growth}/{max_growth}. Продолжайте нажимать /grow_fissure!'
                }
    
    async def _finish_fissure_growth(self, user_id: int, final_growth: int, conn):
        """Завершение игры Fissure Growth"""
        try:
            conn.execute("""
                UPDATE fissure_growth 
                SET game_active = 0, finished_at = ?
                WHERE user_id = ? AND game_active = 1
            """, (datetime.now().isoformat(), user_id))
        except Exception as e:
            logger.error(f"Ошибка при завершении игры Fissure Growth: {e}")
    
    def _select_effect_based_on_growth(self, growth_level: int) -> Dict[str, Any]:
        """Выбор эффекта на основе уровня роста Fissure"""
        # Чем больше рост, тем сильнее эффект
        if growth_level >= 90:
            # Epic эффекты
            epic_effects = [e for e in self.fissure_effects.values() if e['rarity'] == 'epic']
            return random.choice(epic_effects) if epic_effects else self.fissure_effects['legendary_power']
        elif growth_level >= 70:
            # Rare эффекты
            rare_effects = [e for e in self.fissure_effects.values() if e['rarity'] == 'rare']
            return random.choice(rare_effects) if rare_effects else self.fissure_effects['fortune_of_the_brave']
        elif growth_level >= 40:
            # Uncommon эффекты
            uncommon_effects = [e for e in self.fissure_effects.values() if e['rarity'] == 'uncommon']
            return random.choice(uncommon_effects) if uncommon_effects else self.fissure_effects['rage_of_battle']
        else:
            # Common эффекты
            common_effects = [e for e in self.fissure_effects.values() if e['rarity'] == 'common']
            return random.choice(common_effects) if common_effects else self.fissure_effects['blessing_of_strength']
    
    def _select_random_effect(self) -> Dict[str, Any]:
        """Выбор случайного эффекта"""
        # Сначала выбираем редкость
        rarity = random.choices(
            list(self.rarity_weights.keys()),
            weights=list(self.rarity_weights.values())
        )[0]
        
        # Затем выбираем эффект этой редкости
        available_effects = [e for e in self.fissure_effects.values() if e['rarity'] == rarity]
        
        if not available_effects:
            # Если нет эффектов этой редкости, выбираем любой
            available_effects = list(self.fissure_effects.values())
        
        return random.choice(available_effects)
    
    async def _apply_fissure_effect(self, user_id: int, effect: Dict[str, Any]) -> Dict[str, Any]:
        """Применение эффекта Fissure"""
        current_time = datetime.now()
        end_time = current_time + timedelta(seconds=effect['duration'])
        
        # Сохраняем эффект в базу данных
        with db_manager.get_connection() as conn:
            try:
                conn.execute("""
                    INSERT INTO fissure_effects (
                        user_id, effect_id, effect_name, effect_type, 
                        duration, end_time, stats, active
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    user_id, effect['name'], effect['description'], 
                    effect['type'], effect['duration'], 
                    end_time.isoformat(), str(effect['stats']), 1
                ))
                conn.commit()
            except Exception as e:
                logger.error(f"Ошибка при применении эффекта Fissure: {e}")
                return {'success': False, 'message': 'Ошибка при входе в Fissure'}
        
        # Применяем немедленные эффекты
        immediate_result = await self._apply_immediate_effects(user_id, effect)
        
        return {
            'success': True,
            'effect_name': effect['name'],
            'effect_description': effect['description'],
            'effect_type': effect['type'],
            'duration': effect['duration'],
            'immediate_result': immediate_result
        }
    
    async def _apply_immediate_effects(self, user_id: int, effect: Dict[str, Any]) -> Dict[str, Any]:
        """Применение немедленных эффектов"""
        result = {}
        
        # Лечение (если есть)
        if 'heal' in effect:
            user = await db_manager.get_user(user_id)
            max_hp = user.get('max_hp', 1000)
            current_hp = user.get('hp', 500)
            
            heal_amount = int(max_hp * (effect['heal'] / 100))
            new_hp = min(max_hp, current_hp + heal_amount)
            
            await db_manager.update_user(user_id, {'hp': new_hp})
            result['heal'] = {'amount': heal_amount, 'new_hp': new_hp}
        
        # Телепортация (если есть)
        if 'teleport' in effect.get('stats', {}):
            result['teleport'] = True
        
        return result
    
    async def is_in_fissure(self, user_id: int) -> bool:
        """Проверка, находится ли пользователь в Fissure"""
        with db_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT COUNT(*) FROM fissure_effects 
                WHERE user_id = ? AND active = 1 AND end_time > ?
            """, (user_id, datetime.now().isoformat()))
            
            return cursor.fetchone()[0] > 0
    
    async def get_fissure_status(self, user_id: int) -> Dict[str, Any]:
        """Получение статуса Fissure"""
        with db_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT effect_name, effect_type, end_time, stats
                FROM fissure_effects 
                WHERE user_id = ? AND active = 1 AND end_time > ?
                ORDER BY end_time DESC
                LIMIT 1
            """, (user_id, datetime.now().isoformat()))
            
            row = cursor.fetchone()
            if not row:
                return {'in_fissure': False}
            
            effect_name, effect_type, end_time, stats_str = row
            
            # Рассчитываем оставшееся время
            end_time_dt = datetime.fromisoformat(end_time)
            remaining_time = max(0, int((end_time_dt - datetime.now()).total_seconds()))
            
            return {
                'in_fissure': True,
                'effect_name': effect_name,
                'effect_type': effect_type,
                'remaining_time': remaining_time,
                'stats': eval(stats_str) if stats_str else {}
            }
    
    async def leave_fissure(self, user_id: int) -> Dict[str, Any]:
        """Выход из Fissure"""
        # Деактивируем все эффекты
        with db_manager.get_connection() as conn:
            try:
                conn.execute("""
                    UPDATE fissure_effects SET active = 0
                    WHERE user_id = ? AND active = 1
                """, (user_id,))
                conn.commit()
                
                return {'success': True, 'message': 'Вы покинули Fissure'}
            except Exception as e:
                logger.error(f"Ошибка при выходе из Fissure: {e}")
                return {'success': False, 'message': 'Ошибка при выходе из Fissure'}
    
    async def get_active_effects(self, user_id: int) -> List[Dict[str, Any]]:
        """Получение активных эффектов"""
        effects = []
        
        with db_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT effect_name, effect_type, end_time, stats
                FROM fissure_effects 
                WHERE user_id = ? AND active = 1 AND end_time > ?
                ORDER BY end_time DESC
            """, (user_id, datetime.now().isoformat()))
            
            for row in cursor.fetchall():
                effect_name, effect_type, end_time, stats_str = row
                
                end_time_dt = datetime.fromisoformat(end_time)
                remaining_time = max(0, int((end_time_dt - datetime.now()).total_seconds()))
                
                effects.append({
                    'name': effect_name,
                    'type': effect_type,
                    'remaining_time': remaining_time,
                    'stats': eval(stats_str) if stats_str else {}
                })
        
        return effects
    
    async def apply_fissure_bonuses(self, user_id: int, base_stats: Dict[str, Any]) -> Dict[str, Any]:
        """Применение бонусов от Fissure к характеристикам"""
        active_effects = await self.get_active_effects(user_id)
        
        if not active_effects:
            return base_stats
        
        # Суммируем все бонусы
        total_bonuses = {
            'str': 0, 'agi': 0, 'int': 0,
            'damage_mult': 1.0, 'armor_mult': 1.0, 'hp_mult': 1.0,
            'evasion_mult': 1.0, 'speed_mult': 1.0, 'spell_damage_mult': 1.0,
            'mana_mult': 1.0, 'magic_resist_mult': 1.0,
            'all_stats_mult': 1.0, 'all_damage_mult': 1.0, 'all_defense_mult': 1.0
        }
        
        for effect in active_effects:
            effect_stats = effect.get('stats', {})
            
            for stat, value in effect_stats.items():
                if stat in total_bonuses:
                    if isinstance(value, float):
                        total_bonuses[stat] *= value
                    else:
                        total_bonuses[stat] += value
        
        # Применяем бонусы
        final_stats = base_stats.copy()
        
        # Статистические бонусы
        for stat in ['str', 'agi', 'int']:
            if total_bonuses[stat] != 0:
                final_stats[stat] += total_bonuses[stat]
        
        # Множители
        for stat, multiplier in total_bonuses.items():
            if multiplier != 1.0 and not isinstance(multiplier, int):
                if stat == 'damage_mult':
                    final_stats['damage'] = int(final_stats['damage'] * multiplier)
                elif stat == 'armor_mult':
                    final_stats['armor'] = int(final_stats['armor'] * multiplier)
                elif stat == 'hp_mult':
                    final_stats['hp'] = int(final_stats['hp'] * multiplier)
                    final_stats['max_hp'] = int(final_stats['max_hp'] * multiplier)
                elif stat == 'evasion_mult':
                    final_stats['evasion'] = int(final_stats['evasion'] * multiplier)
                elif stat == 'speed_mult':
                    final_stats['speed'] = int(final_stats['speed'] * multiplier)
                elif stat == 'spell_damage_mult':
                    final_stats['spell_damage'] = int(final_stats['spell_damage'] * multiplier)
                elif stat == 'mana_mult':
                    final_stats['mana'] = int(final_stats['mana'] * multiplier)
                    final_stats['max_mana'] = int(final_stats['max_mana'] * multiplier)
                elif stat == 'all_stats_mult':
                    for stat_name in ['hp', 'max_hp', 'damage', 'armor', 'evasion', 'speed', 'mana', 'max_mana']:
                        if stat_name in final_stats:
                            final_stats[stat_name] = int(final_stats[stat_name] * multiplier)
                elif stat == 'all_damage_mult':
                    for stat_name in ['damage', 'spell_damage']:
                        if stat_name in final_stats:
                            final_stats[stat_name] = int(final_stats[stat_name] * multiplier)
                elif stat == 'all_defense_mult':
                    for stat_name in ['armor', 'evasion', 'block', 'reflect']:
                        if stat_name in final_stats:
                            final_stats[stat_name] = int(final_stats[stat_name] * multiplier)
        
        return final_stats
    
    async def cleanup_expired_effects(self):
        """Очистка истекших эффектов"""
        with db_manager.get_connection() as conn:
            try:
                conn.execute("""
                    UPDATE fissure_effects SET active = 0
                    WHERE end_time <= ?
                """, (datetime.now().isoformat(),))
                conn.commit()
            except Exception as e:
                logger.error(f"Ошибка при очистке истекших эффектов: {e}")

# Глобальный экземпляр системы Fissure
fissure_system = FissureSystem()

__all__ = ['FissureSystem', 'fissure_system']