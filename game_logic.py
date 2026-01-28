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
    bonus = 0
    if user["items"]:
        for item_name in user["items"]:
            if item_name and item_name in ITEMS and stat in ITEMS[item_name]:
                bonus += ITEMS[item_name][stat]
    return bonus

def calculate_character_stats(user: Dict) -> Dict[str, Any]:
    """Рассчитывает все характеристики персонажа"""
    items = user.get("items", []) or [None] * 6
    
    # Базовые характеристики
    base_str = user["str"]
    base_agi = user["agi"] 
    base_int = user["int"]
    level = user["level"]
    
    # Бонусы от предметов
    str_bonus = get_item_bonus(user, "str")
    agi_bonus = get_item_bonus(user, "agi")
    int_bonus = get_item_bonus(user, "int")
    hp_bonus = get_item_bonus(user, "hp")
    dmg_bonus = get_item_bonus(user, "dmg")
    crit_bonus = get_item_bonus(user, "crit")
    dodge_bonus = get_item_bonus(user, "dodge")
    heal_bonus = get_item_bonus(user, "heal")
    exp_bonus = get_item_bonus(user, "exp")
    
    # Расчет характеристик
    max_hp = CharacterStats.calculate_max_hp(base_str + str_bonus, level, hp_bonus)
    base_damage = CharacterStats.calculate_base_damage(base_str + str_bonus, dmg_bonus)
    dodge_chance = CharacterStats.calculate_dodge_chance(base_agi + agi_bonus, dodge_bonus)
    crit_chance = CharacterStats.calculate_crit_chance(base_agi + agi_bonus, crit_bonus)
    hp_regen = CharacterStats.calculate_hp_regen(base_int + int_bonus, heal_bonus)
    
    return {
        "max_hp": max_hp,
        "base_damage": base_damage,
        "dodge_chance": dodge_chance,
        "crit_chance": crit_chance,
        "hp_regen": hp_regen,
        "str_total": base_str + str_bonus,
        "agi_total": base_agi + agi_bonus,
        "int_total": base_int + int_bonus,
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

# Предметы (упрощенная версия)
ITEMS = {
    "Boots of Speed": {"agi": 10},
    "Phase Boots": {"agi": 22, "dmg": 16},
    "Power Treads": {"str": 22, "agi": 22},
    "Arcane Boots": {"int": 10},
    "Boots of Travel": {"agi": 15, "dmg": 10},
    "Ring of Protection": {"str": 3},
    "Vanguard": {"str": 10, "hp": 200},
    "Crimson Guard": {"str": 15, "hp": 250},
    "Hood of Defiance": {"int": 10, "hp": 150},
    "Blade Mail": {"str": 10, "agi": 10},
    "Quelling Blade": {"dmg": 7},
    "Sange": {"str": 10, "dmg": 10},
    "Yasha": {"agi": 16, "crit": 10},
    "Daedalus": {"crit": 25, "dmg": 81},
    "Butterfly": {"agi": 30, "dodge": 30},
    "Stout Shield": {"dodge": 10},
    "Mekansm": {"str": 5, "hp": 150},
    "Black King Bar": {"str": 22, "hp": 300},
    "Heart of Tarrasque": {"str": 45, "hp": 500},
    "Shiva's Guard": {"str": 20, "agi": 20},
    "Ring of Basilius": {"str": 5, "int": 5},
    "Magic Wand": {"hp": 75, "int": 5},
    "Aghanim's Scepter": {"int": 20, "str": 10},
    "Eul's Scepter": {"int": 25, "agi": 10},
    "Gleipnir": {"str": 20, "agi": 20},
    "Healing Salve": {"heal": 100},
    "Tome of Knowledge": {"exp": 100},
    "Ring of Regen": {"hp": 100},
    "Ring of Health": {"hp": 150},
    "Perseverance": {"int": 10, "hp": 150}
}

__all__ = ['CharacterStats', 'calculate_character_stats', 'get_fissure_result', 'get_user_progress', 'get_next_level_exp']

</final_file_content>

IMPORTANT: For any future changes to this file, use the final_file_content shown above as your reference. This content reflects the current state of the file, including any auto-formatting (e.g., if you used single quotes but the formatter converted them to double quotes). Always base your SEARCH/REPLACE operations on this final version to ensure accuracy.

 <environment_details>
# Cursor Visible Files
game_logic.py

# Cursor Open Tabs
requirements.txt
database.py
handlers/pvp_system.py
game_logic.py

# Current Time
1/28/2026, 1:00:25 PM (Europe/Minsk, UTC+3:00)

# Context Window Usage
# Current Mode
ACT MODE
