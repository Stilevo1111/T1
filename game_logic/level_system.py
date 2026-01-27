"""Система уровней и опыта"""

import math
import logging
from typing import Dict, Any, Tuple
from database import get_user, update_user

logger = logging.getLogger(__name__)

class LevelSystem:
    """Система уровней и опыта"""
    
    @staticmethod
    def get_exp_for_level(level: int) -> int:
        """Рассчет опыта, необходимого для следующего уровня"""
        # Экспоненциальная формула: base_exp * level^exp_factor
        base_exp = 100
        exp_factor = 1.5
        
        if level <= 1:
            return 0
        
        # Формула: base_exp * (level^(exp_factor)) - base_exp * ((level-1)^(exp_factor))
        current_level_exp = base_exp * (level ** exp_factor)
        prev_level_exp = base_exp * ((level - 1) ** exp_factor)
        
        return int(current_level_exp - prev_level_exp)
    
    @staticmethod
    def get_total_exp_for_level(level: int) -> int:
        """Общий опыт, необходимый для достижения уровня"""
        base_exp = 100
        exp_factor = 1.5
        
        if level <= 1:
            return 0
        
        return int(base_exp * (level ** exp_factor))
    
    @staticmethod
    def calculate_level_from_exp(total_exp: int) -> Tuple[int, int]:
        """Рассчет уровня и прогресса от общего опыта"""
        if total_exp <= 0:
            return 1, 0
        
        # Используем логарифм для обратного расчета уровня
        base_exp = 100
        exp_factor = 1.5
        
        # level = (total_exp / base_exp)^(1/exp_factor)
        level_float = (total_exp / base_exp) ** (1 / exp_factor)
        level = int(level_float)
        
        # Убедимся, что уровень не меньше 1
        if level < 1:
            level = 1
        
        # Рассчитываем прогресс до следующего уровня
        current_level_exp = LevelSystem.get_total_exp_for_level(level)
        next_level_exp = LevelSystem.get_total_exp_for_level(level + 1)
        
        if next_level_exp <= current_level_exp:
            progress = 0
        else:
            progress = int(((total_exp - current_level_exp) / (next_level_exp - current_level_exp)) * 100)
        
        # Ограничиваем прогресс 99%
        progress = min(progress, 99)
        
        return level, progress
    
    @staticmethod
    def get_stat_bonus_for_level(level: int) -> Dict[str, int]:
        """Получение бонусов к характеристикам за уровень"""
        # Базовые бонусы за уровень
        base_bonuses = {
            'hp': 50,
            'max_hp': 50,
            'damage': 5,
            'armor': 1,
            'str': 2,
            'agi': 2,
            'int': 2,
            'mana': 20,
            'max_mana': 20
        }
        
        # Множитель в зависимости от уровня
        multiplier = 1 + (level // 10) * 0.1  # Каждые 10 уровней +10% к бонусам
        
        return {stat: int(value * multiplier) for stat, value in base_bonuses.items()}
    
    @staticmethod
    async def check_level_up(user_id: int, current_exp: int, new_exp_gained: int) -> Dict[str, Any]:
        """Проверка повышения уровня"""
        total_exp = current_exp + new_exp_gained
        new_level, progress = LevelSystem.calculate_level_from_exp(total_exp)
        
        # Получаем текущий уровень
        user = await get_user(user_id, "temp")
        if not user:
            return {'level_up': False}
        
        current_level = user.get('level', 1)
        
        if new_level > current_level:
            # Произошло повышение уровня!
            level_up_count = new_level - current_level
            
            # Рассчитываем бонусы
            total_bonuses = {'hp': 0, 'max_hp': 0, 'damage': 0, 'armor': 0, 
                           'str': 0, 'agi': 0, 'int': 0, 'mana': 0, 'max_mana': 0}
            
            for level in range(current_level + 1, new_level + 1):
                level_bonuses = LevelSystem.get_stat_bonus_for_level(level)
                for stat, bonus in level_bonuses.items():
                    total_bonuses[stat] += bonus
            
            # Обновляем пользователя
            await update_user(user_id, {
                'level': new_level,
                'hp': user.get('hp', 1000) + total_bonuses['hp'],
                'max_hp': user.get('max_hp', 1000) + total_bonuses['max_hp'],
                'damage': user.get('damage', 50) + total_bonuses['damage'],
                'armor': user.get('armor', 5) + total_bonuses['armor'],
                'str': user.get('str', 10) + total_bonuses['str'],
                'agi': user.get('agi', 10) + total_bonuses['agi'],
                'int': user.get('int', 10) + total_bonuses['int'],
                'mana': user.get('mana', 200) + total_bonuses['mana'],
                'max_mana': user.get('max_mana', 200) + total_bonuses['max_mana'],
                'exp': total_exp
            })
            
            return {
                'level_up': True,
                'old_level': current_level,
                'new_level': new_level,
                'level_up_count': level_up_count,
                'bonuses': total_bonuses,
                'progress': progress
            }
        
        else:
            # Обновляем только опыт
            await update_user(user_id, {'exp': total_exp})
            
            return {
                'level_up': False,
                'new_level': current_level,
                'progress': progress
            }

class CharacterStats:
    """Система расчета характеристик персонажа"""
    
    @staticmethod
    def calculate_base_stats(user_data: Dict[str, Any]) -> Dict[str, Any]:
        """Рассчет базовых характеристик"""
        level = user_data.get('level', 1)
        str_val = user_data.get('str', 10)
        agi_val = user_data.get('agi', 10)
        int_val = user_data.get('int', 10)
        
        # Базовые формулы
        base_hp = 1000 + (level * 50)
        base_damage = 50 + (level * 5)
        base_armor = 5 + (level * 1)
        base_mana = 200 + (level * 20)
        
        # Модификаторы от характеристик
        str_bonus_hp = str_val * 10
        str_bonus_damage = str_val * 2
        str_bonus_armor = str_val * 0.5
        
        agi_bonus_damage = agi_val * 1.5
        agi_bonus_evasion = agi_val * 0.5
        agi_bonus_speed = agi_val * 2
        
        int_bonus_mana = int_val * 20
        int_bonus_spell_damage = int_val * 1.2
        int_bonus_mana_regen = int_val * 1
        
        # Итоговые характеристики
        stats = {
            'hp': int(base_hp + str_bonus_hp),
            'max_hp': int(base_hp + str_bonus_hp),
            'damage': int(base_damage + str_bonus_damage + agi_bonus_damage),
            'armor': int(base_armor + str_bonus_armor),
            'evasion': int(agi_bonus_evasion),
            'speed': int(100 + agi_bonus_speed),
            'mana': int(base_mana + int_bonus_mana),
            'max_mana': int(base_mana + int_bonus_mana),
            'spell_damage': int(int_bonus_spell_damage),
            'mana_regen': int(int_bonus_mana_regen),
            'crit': user_data.get('crit', 5),
            'block': user_data.get('block', 0),
            'reflect': user_data.get('reflect', 0)
        }
        
        return stats
    
    @staticmethod
    async def apply_item_bonuses(user_id: int, base_stats: Dict[str, Any]) -> Dict[str, Any]:
        """Применение бонусов от предметов"""
        # Заглушка для временного решения - возвращаем базовые статы без бонусов
        return base_stats
        
        # Бонусы от предметов
        item_bonuses = {
            'hp': 0, 'max_hp': 0, 'damage': 0, 'armor': 0,
            'evasion': 0, 'speed': 0, 'mana': 0, 'max_mana': 0,
            'spell_damage': 0, 'mana_regen': 0, 'crit': 0,
            'block': 0, 'reflect': 0
        }
        
        # База данных предметов с их бонусами
        items_db = {
            'boots_of_speed': {'speed': 20},
            'phase_boots': {'agi': 15, 'speed': 10},
            'power_treads': {'str': 10, 'agi': 10},
            'arcane_boots': {'int': 15, 'mana': 100},
            'ring_of_protection': {'armor': 5},
            'vanguard': {'hp': 300, 'block': 20},
            'stout_shield': {'armor': 10, 'block': 15},
            'blademail': {'armor': 15, 'reflect': 25},
            'quelling_blade': {'damage': 15},
            'daedalus': {'damage': 80, 'crit': 25},
            'dagon': {'int': 50, 'spell_damage': 30},
            'monkey_king_bar': {'damage': 60, 'agi': 30},
            'ring_of_basilius': {'int': 10, 'mana_regen': 5},
            'aghanims_scepter': {'int': 50, 'spell_power': 20},
            'force_staff': {'int': 20, 'mana': 200},
            'glimmer_cape': {'agi': 25, 'invis': 1},
            'healing_salve': {'heal': 150},
            'clarity_potion': {'mana': 200},
            'invisibility_potion': {'invis_time': 30},
            'speed_potion': {'speed': 50, 'duration': 60}
        }
        
        # Применяем бонусы от экипированных предметов
        for item in inventory:
            if item.get('equipped', 0) and item['item_id'] in items_db:
                item_stats = items_db[item['item_id']]
                for stat, bonus in item_stats.items():
                    if stat in item_bonuses:
                        item_bonuses[stat] += bonus
        
        # Применяем бонусы
        final_stats = base_stats.copy()
        for stat, bonus in item_bonuses.items():
            if stat in final_stats:
                final_stats[stat] += bonus
        
        return final_stats
    
    @staticmethod
    async def apply_talent_bonuses(user_id: int, base_stats: Dict[str, Any]) -> Dict[str, Any]:
        """Применение бонусов от талантов"""
        # Заглушка для временного решения - возвращаем базовые статы без бонусов
        return base_stats
        
        # База данных талантов с их бонусами
        talents_db = {
            'str_1': {'str': 10},
            'str_2': {'damage_mult': 1.15},
            'str_3': {'armor_mult': 1.10},
            'str_4': {'hp_mult': 1.15},
            'agi_1': {'agi': 10},
            'agi_2': {'crit_mult': 1.15},
            'agi_3': {'evasion_mult': 1.10},
            'agi_4': {'speed_mult': 1.15},
            'int_1': {'int': 10},
            'int_2': {'spell_damage_mult': 1.15},
            'int_3': {'mana_mult': 1.10},
            'int_4': {'magic_resist_mult': 1.15},
            'hybrid_1': {'str': 5, 'agi': 5, 'int': 5},
            'hybrid_2': {'all_stats_mult': 1.10},
            'hybrid_3': {'all_damage_mult': 1.05},
            'hybrid_4': {'all_defense_mult': 1.05}
        }
        
        # Множители
        multipliers = {
            'damage_mult': 1.0,
            'armor_mult': 1.0,
            'hp_mult': 1.0,
            'evasion_mult': 1.0,
            'speed_mult': 1.0,
            'spell_damage_mult': 1.0,
            'mana_mult': 1.0,
            'magic_resist_mult': 1.0,
            'all_stats_mult': 1.0,
            'all_damage_mult': 1.0,
            'all_defense_mult': 1.0
        }
        
        # Статистические бонусы
        stat_bonuses = {
            'str': 0, 'agi': 0, 'int': 0
        }
        
        # Применяем бонусы талантов
        for talent_id in learned_talents:
            if talent_id in talents_db:
                talent_stats = talents_db[talent_id]
                for stat, value in talent_stats.items():
                    if stat in multipliers:
                        multipliers[stat] *= value
                    elif stat in stat_bonuses:
                        stat_bonuses[stat] += value
        
        # Применяем статистические бонусы
        final_stats = base_stats.copy()
        for stat, bonus in stat_bonuses.items():
            if stat in final_stats:
                final_stats[stat] += bonus
        
        # Применяем множители
        for stat, multiplier in multipliers.items():
            if multiplier != 1.0:
                # Преобразуем имя статистики
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
    
    @staticmethod
    async def get_full_character_stats(user_id: int) -> Dict[str, Any]:
        """Получение полной статистики персонажа"""
        user = await get_user(user_id, "temp")
        if not user:
            return {}
        
        # Базовые характеристики
        base_stats = CharacterStats.calculate_base_stats(user)
        
        # Бонусы от предметов
        item_stats = await CharacterStats.apply_item_bonuses(user_id, base_stats)
        
        # Бонусы от талантов
        final_stats = await CharacterStats.apply_talent_bonuses(user_id, item_stats)
        
        # Добавляем информацию о уровне
        level, progress = LevelSystem.calculate_level_from_exp(user.get('exp', 0))
        final_stats['level'] = level
        final_stats['exp_progress'] = progress
        final_stats['exp_total'] = user.get('exp', 0)
        final_stats['gold'] = user.get('gold', 0)
        final_stats['mmr'] = user.get('mmr', 1000)
        
        return final_stats

__all__ = ['LevelSystem', 'CharacterStats']