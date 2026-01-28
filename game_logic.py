"""Система уровней и характеристик персонажа"""

import math
import random
from typing import Dict, Any, Tuple, Optional

class CharacterStats:
    """Класс для расчета характеристик персонажа"""
    
    @staticmethod
    def calculate_max_hp(base_str: int, level: int, items_bonus: int = 0) -> int:
        """Рассчитывает максимальное HP персонажа"""
        base_hp = 100  # Базовое HP
        str_hp = base_str * 10  # BASE_HP_PER_STR = 10
        level_hp = level * 20  # Каждый уровень дает +20 HP
        return base_hp + str_hp + level_hp + items_bonus
    
    @staticmethod
    def calculate_base_damage(base_str: int, items_bonus: int = 0) -> int:
        """Рассчитывает базовый урон персонажа"""
        base_dmg = 5  # Базовый урон
        str_dmg = base_str * 2  # BASE_DMG_PER_STR = 2
        return base_dmg + str_dmg + items_bonus
    
    @staticmethod
    def calculate_dodge_chance(base_agi: int, items_bonus: int = 0) -> float:
        """Рассчитывает шанс уклонения в процентах"""
        agi_dodge = base_agi * 0.5  # BASE_DODGE_PER_AGI = 0.5
        return agi_dodge + items_bonus
    
    @staticmethod
    def calculate_crit_chance(base_agi: int, items_bonus: int = 0) -> float:
        """Рассчитывает шанс критического удара в процентах"""
        agi_crit = base_agi * 0.5  # BASE_CRIT_PER_AGI = 0.5
        return agi_crit + items_bonus
    
    @staticmethod
    def calculate_hp_regen(base_int: int, items_bonus: int = 0) -> float:
        """Рассчитывает регенерацию HP в процентах от максимума в минуту"""
        int_regen = base_int * 0.5  # BASE_HP_REGEN_PER_INT = 0.5
        return int_regen + items_bonus

def get_item_bonus(user: Dict, stat: str) -> int:
    """Получение бонуса от предметов"""
    return 0  # Система предметов удалена

def calculate_character_stats(user: Dict) -> Dict[str, Any]:
    """Рассчитывает все характеристики персонажа"""
    # Базовые характеристики
    base_str = user["str"]
    base_agi = user["agi"] 
    base_int = user["int"]
    level = user["level"]
    
    # Расчет характеристик (без бонусов от предметов)
    max_hp = CharacterStats.calculate_max_hp(base_str, level, 0)
    base_damage = CharacterStats.calculate_base_damage(base_str, 0)
    dodge_chance = CharacterStats.calculate_dodge_chance(base_agi, 0)
    crit_chance = CharacterStats.calculate_crit_chance(base_agi, 0)
    hp_regen = CharacterStats.calculate_hp_regen(base_int, 0)
    
    return {
        "max_hp": max_hp,
        "base_damage": base_damage,
        "dodge_chance": dodge_chance,
        "crit_chance": crit_chance,
        "hp_regen": hp_regen,
        "str_total": base_str,
        "agi_total": base_agi,
        "int_total": base_int,
        "level": level
    }

def get_fissure_result(user: Dict) -> Dict[str, Any]:
    """Получает результат броска фиссуры"""
    roll = random.choice([0.1, 0.2, 0.3, 0.4, 0.5, -0.1, -0.2, -0.3, 0.0])
    new_value = max(0.1, roll)  # Минимальная длина фиссуры 0.1 см
    
    # Определяем текст результата
    if roll > 0:
        text = f"+{roll} см!"
        phrase = "Фиссура немного выросла"
    elif roll < 0:
        text = f"{roll} см..."
        phrase = "Фиссура немного уменьшилась"
    else:
        text = "0.0 см"
        phrase = "Фиссура не изменилась"
    
    return {
        "success": True,
        "message": f"{text} {phrase}",
        "updates": {"fissure_size": new_value}
    }

def get_user_progress(user: Dict) -> Dict[str, float]:
    """Получает прогресс пользователя по уровням"""
    current_exp = user.get("exp", 0)
    next_level_exp = get_next_level_exp(user["level"])
    progress = (current_exp / next_level_exp) * 100 if next_level_exp > 0 else 100
    return {
        "current_exp": current_exp,
        "next_level_exp": next_level_exp,
        "progress_percent": min(progress, 100),
        "level": user["level"]
    }

def get_next_level_exp(current_level: int) -> int:
    """Рассчитывает опыт для следующего уровня"""
    return int(100 * (1.2 ** (current_level - 1)))  # EXP_PER_LEVEL = 100, EXP_MULTIPLIER = 1.2


__all__ = ['CharacterStats', 'calculate_character_stats', 'get_fissure_result', 'get_user_progress', 'get_next_level_exp']