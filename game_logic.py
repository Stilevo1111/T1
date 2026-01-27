import random
import time
from typing import Dict, List, Tuple, Optional
from config import BASE_HP_PER_STR, BASE_DMG_PER_STR, BASE_DODGE_PER_AGI, BASE_CRIT_PER_AGI, BASE_HP_REGEN_PER_INT, EXP_PER_LEVEL, EXP_MULTIPLIER, MEMES, ROLLS, FISURE_TEXTS, FISURE_PHRASES

# Предметы (вдохновлены Dota 2)
ITEMS = {
    # Сапоги (5 штук)
    "Boots of Speed": {"gold": 400, "agi": 10, "description": "Ботинки скорости (+10 ловкости)", "category": "Сапоги"},
    "Phase Boots": {"gold": 1500, "agi": 22, "dmg": 16, "description": "Часовые сапоги (+22 ловкости, +16 урона)", "category": "Сапоги"},
    "Power Treads": {"gold": 1400, "str": 22, "agi": 22, "description": "Сапоги силы (+22 силы, +22 ловкости)", "category": "Сапоги"},
    "Arcane Boots": {"gold": 475, "int": 10, "description": "Чародейские ботинки (+10 интеллекта)", "category": "Сапоги"},
    "Boots of Travel": {"gold": 2400, "agi": 15, "dmg": 10, "description": "Ботинки путешествий (+15 ловкости, +10 урона)", "category": "Сапоги"},

    # Броня (5 штук)
    "Ring of Protection": {"gold": 175, "str": 3, "description": "Кольцо защиты (+3 силы)", "category": "Броня"},
    "Vanguard": {"gold": 2250, "str": 10, "hp": 200, "description": "Вангард (+10 силы, +200 HP)", "category": "Броня"},
    "Crimson Guard": {"gold": 3500, "str": 15, "hp": 250, "description": "Багряная стража (+15 силы, +250 HP)", "category": "Броня"},
    "Hood of Defiance": {"gold": 2175, "int": 10, "hp": 150, "description": "Капюшон неповиновения (+10 интеллекта, +150 HP)", "category": "Броня"},
    "Blade Mail": {"gold": 2200, "str": 10, "agi": 10, "description": "Лезвие mail (+10 силы, +10 ловкости)", "category": "Броня"},

    # Оружие (5 штук)
    "Quelling Blade": {"gold": 210, "dmg": 7, "description": "Клинок рубки (+7 урона)", "category": "Оружие"},
    "Sange": {"gold": 1150, "str": 10, "dmg": 10, "description": "Сандже (+10 силы, +10 урона)", "category": "Оружие"},
    "Yasha": {"gold": 1500, "agi": 16, "crit": 10, "description": "Яша (+16 ловкости, +10% крита)", "category": "Оружие"},
    "Daedalus": {"gold": 5150, "crit": 25, "dmg": 81, "description": "Дедал (+25% крита, +81 урона)", "category": "Оружие"},
    "Butterfly": {"gold": 5500, "agi": 30, "dodge": 30, "description": "Бабочка (+30 ловкости, +30% уклонения)", "category": "Оружие"},

    # Защита (5 штук)
    "Stout Shield": {"gold": 200, "dodge": 10, "description": "Крепкий щит (+10% уклонения)", "category": "Защита"},
    "Mekansm": {"gold": 2350, "str": 5, "hp": 150, "description": "Меканзм (+5 силы, +150 HP)", "category": "Защита"},
    "Black King Bar": {"gold": 4100, "str": 22, "hp": 300, "description": "Черная королевская барра (+22 силы, +300 HP)", "category": "Защита"},
    "Heart of Tarrasque": {"gold": 5500, "str": 45, "hp": 500, "description": "Сердце Тараска (+45 силы, +500 HP)", "category": "Защита"},
    "Shiva's Guard": {"gold": 4750, "str": 20, "agi": 20, "description": "Защита Шивы (+20 силы, +20 ловкости)", "category": "Защита"},

    # Поддержка (5 штук)
    "Ring of Basilius": {"gold": 450, "str": 5, "int": 5, "description": "Кольцо Базилиуса (+5 силы, +5 интеллекта)", "category": "Поддержка"},
    "Magic Wand": {"gold": 460, "hp": 75, "int": 5, "description": "Волшебная палочка (+75 HP, +5 интеллекта)", "category": "Поддержка"},
    "Aghanim's Scepter": {"gold": 4200, "int": 20, "str": 10, "description": "Скипетр Аганима (+20 интеллекта, +10 силы)", "category": "Поддержка"},
    "Eul's Scepter": {"gold": 2750, "int": 25, "agi": 10, "description": "Скипетр Еуля (+25 интеллекта, +10 ловкости)", "category": "Поддержка"},
    "Gleipnir": {"gold": 5400, "str": 20, "agi": 20, "description": "Глепнир (+20 силы, +20 ловкости)", "category": "Поддержка"},

    # Зелья (5 штук)
    "Healing Salve": {"gold": 100, "heal": 100, "description": "Целебный бальзам (+100 HP)", "category": "Зелья"},
    "Tome of Knowledge": {"gold": 300, "exp": 100, "description": "Фолиант знаний (+100 опыта)", "category": "Зелья"},
    "Ring of Regen": {"gold": 325, "hp": 100, "description": "Кольцо регенерации (+100 HP)", "category": "Зелья"},
    "Ring of Health": {"gold": 850, "hp": 150, "description": "Кольцо здоровья (+150 HP)", "category": "Зелья"},
    "Perseverance": {"gold": 1650, "int": 10, "hp": 150, "description": "Стойкость (+10 интеллекта, +150 HP)", "category": "Зелья"}
}


# Боссы
BOSSES = [
    {"name": "Shadow Fiend", "hp": 6000, "dmg": [20, 35], "min_level": 1, "max_level": 10, "ability": "ворует EXP", "loot": ["Daedalus", "Aegis of the Immortal"]},
    {"name": "Axe", "hp": 6500, "dmg": [28, 44], "min_level": 5, "max_level": 12, "ability": "контратакует", "loot": ["Blade Mail", "Abyssal Blade"]},
    {"name": "Doom", "hp": 7000, "dmg": [24, 36], "min_level": 7, "max_level": 14, "ability": "отключает предметы на 1 удар", "loot": ["Black King Bar", "Assault Cuirass"]},
    {"name": "Zeus", "hp": 9000, "dmg": [16, 40], "min_level": 8, "max_level": 15, "ability": "каждые 3 хода удар по случайному игроку", "loot": ["Boots of Travel", "Mjolnir"]},
    {"name": "Invoker", "hp": 7500, "dmg": [16, 32], "min_level": 10, "max_level": 18, "ability": "случайные эффекты", "loot": ["Scythe of Vyse", "Octarine Core"]},
    {"name": "Roshan", "hp": 8000, "dmg": [20, 32], "min_level": 12, "max_level": 20, "ability": "ярость <30% HP", "loot": ["Divine Rapier", "Heart of Tarrasque"]},
    {"name": "Roshan Prime", "hp": 12000, "dmg": [40, 64], "min_level": 20, "max_level": 30, "ability": "ярость <30% HP", "loot": ["Divine Rapier", "Eul's Scepter"]}
]

class CharacterStats:
    """Класс для расчета характеристик персонажа"""
    
    @staticmethod
    def calculate_max_hp(base_str: int, level: int, items_bonus: int = 0) -> int:
        """Рассчитывает максимальное HP персонажа"""
        base_hp = 100  # Базовое HP
        str_hp = base_str * BASE_HP_PER_STR
        level_hp = level * 20  # Каждый уровень дает +20 HP
        return base_hp + str_hp + level_hp + items_bonus
    
    @staticmethod
    def calculate_base_damage(base_str: int, items_bonus: int = 0) -> int:
        """Рассчитывает базовый урон персонажа"""
        base_dmg = 5  # Базовый урон
        str_dmg = base_str * BASE_DMG_PER_STR
        return base_dmg + str_dmg + items_bonus
    
    @staticmethod
    def calculate_dodge_chance(base_agi: int, items_bonus: int = 0) -> float:
        """Рассчитывает шанс уклонения в процентах"""
        agi_dodge = base_agi * BASE_DODGE_PER_AGI
        return agi_dodge + items_bonus
    
    @staticmethod
    def calculate_crit_chance(base_agi: int, items_bonus: int = 0) -> float:
        """Рассчитывает шанс критического удара в процентах"""
        agi_crit = base_agi * BASE_CRIT_PER_AGI
        return agi_crit + items_bonus
    
    @staticmethod
    def calculate_hp_regen(base_int: int, items_bonus: int = 0) -> float:
        """Рассчитывает регенерацию HP в процентах от максимума в минуту"""
        int_regen = base_int * BASE_HP_REGEN_PER_INT
        return int_regen + items_bonus

def get_item_bonus(user: Dict, stat: str) -> int:
    """Получение бонуса от предметов"""
    bonus = 0
    if user["items"]:
        for item_name in user["items"]:
            if item_name and item_name in ITEMS and stat in ITEMS[item_name]:
                bonus += ITEMS[item_name][stat]
    return bonus

def calculate_character_stats(user: Dict) -> Dict[str, int]:
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

def calculate_damage(user: Dict) -> Tuple[int, bool]:
    """Рассчитывает урон персонажа с учетом критических ударов"""
    stats = calculate_character_stats(user)
    base_dmg = stats["base_damage"] + random.randint(1, 10)
    
    # Критический удар
    is_crit = random.randint(1, 100) <= stats["crit_chance"]
    if is_crit:
        base_dmg *= 2
    
    return base_dmg, is_crit

def calculate_dodge(user: Dict) -> bool:
    """Проверяет, удалось ли уклониться от атаки"""
    stats = calculate_character_stats(user)
    return random.randint(1, 100) <= stats["dodge_chance"]

def calculate_pvp_advantage(user1: Dict, user2: Dict) -> Dict[str, float]:
    """Рассчитывает преимущество в PvP между двумя игроками"""
    stats1 = calculate_character_stats(user1)
    stats2 = calculate_character_stats(user2)
    
    # Разница в уровнях
    level_diff = user1["level"] - user2["level"]
    
    # Разница в MMR
    mmr_diff = user1["mmr"] - user2["mmr"]
    
    # Разница в уроне
    dmg_diff = stats1["base_damage"] - stats2["base_damage"]
    
    # Разница в уклонении
    dodge_diff = stats1["dodge_chance"] - stats2["dodge_chance"]
    
    # Разница в критах
    crit_diff = stats1["crit_chance"] - stats2["crit_chance"]
    
    # Общее преимущество (в процентах)
    advantage = (
        level_diff * 2 +  # Каждый уровень дает 2% преимущества
        mmr_diff * 0.01 +  # Каждые 100 MMR дают 1% преимущества
        dmg_diff * 0.5 +   # Каждый урон дает 0.5% преимущества
        dodge_diff * 0.2 + # Каждый % уклонения дает 0.2% преимущества
        crit_diff * 0.3    # Каждый % крита дает 0.3% преимущества
    )
    
    return {
        "advantage": advantage,
        "level_diff": level_diff,
        "mmr_diff": mmr_diff,
        "dmg_diff": dmg_diff,
        "dodge_diff": dodge_diff,
        "crit_diff": crit_diff
    }

def calculate_boss_strategy(user: Dict, boss_level: int) -> Dict[str, str]:
    """Рассчитывает рекомендации по стратегии против босса"""
    stats = calculate_character_stats(user)
    
    recommendations = []
    
    # Проверка уровня
    if user["level"] < boss_level:
        recommendations.append(f"⚠️ Босс на {boss_level - user['level']} уровней выше. Будьте осторожны!")
    
    # Проверка урона
    if stats["base_damage"] < boss_level * 10:
        recommendations.append("🗡️ Ваш урон низкий. Рассмотрите покупку оружия.")
    
    # Проверка HP
    if stats["max_hp"] < boss_level * 100:
        recommendations.append("❤️ Ваше HP низкое. Купите броню или зелья.")
    
    # Проверка уклонения
    if stats["dodge_chance"] < 10:
        recommendations.append("🛡️ Низкое уклонение. Рассмотрите предметы на ловкость.")
    
    # Проверка критов
    if stats["crit_chance"] < 15:
        recommendations.append("🎯 Низкий шанс крита. Предметы на ловкость помогут.")
    
    # Проверка регенерации
    if stats["hp_regen"] < 2:
        recommendations.append("💚 Низкая регенерация. Предметы на интеллект помогут.")
    
    if not recommendations:
        recommendations.append("✅ Вы хорошо подготовлены к бою!")
    
    return {
        "recommendations": recommendations,
        "damage_per_second": stats["base_damage"] * 0.5,  # Примерный DPS
        "survivability": stats["max_hp"] / (boss_level * 20),  # Примерная живучесть
        "overall_score": (stats["base_damage"] + stats["max_hp"] + stats["dodge_chance"] + stats["crit_chance"]) / 4
    }

def spawn_boss() -> Dict:
    """Создает нового босса"""
    boss = random.choice(BOSSES)
    return {
        "name": boss["name"],
        "hp": boss["hp"],
        "max": boss["hp"],
        "dmg": boss["dmg"],
        "min_level": boss["min_level"],
        "max_level": boss["max_level"],
        "ability": boss["ability"]
    }

def check_level_restriction(user_level: int, boss_min: int, boss_max: int) -> bool:
    """Проверяет, соответствует ли уровень пользователя требованиям босса"""
    return boss_min <= user_level <= boss_max


def check_level_up(user: Dict) -> bool:
    """Проверяет, нужно ли повысить уровень персонажа"""
    exp_needed = EXP_PER_LEVEL * (EXP_MULTIPLIER ** (user["level"] - 1))
    return user["exp"] >= exp_needed

def get_fissure_result() -> Tuple[float, str, str]:
    """Получает результат броска фиссуры"""
    roll = random.choice(ROLLS)
    new_value = max(0.1, roll)  # Минимальная длина фиссуры 0.1 см
    
    # Определяем текст результата
    if roll > 0:
        text = FISURE_TEXTS.get(roll, f"+{roll} см!")
        phrase = random.choice(FISURE_PHRASES["up"])
    elif roll < 0:
        text = FISURE_TEXTS.get(roll, f"{roll} см...")
        phrase = random.choice(FISURE_PHRASES["down"])
    else:
        text = FISURE_TEXTS[0]
        phrase = random.choice(FISURE_PHRASES["same"])
    
    return new_value, text, phrase

def get_meme_message(category: str, **kwargs) -> str:
    """Получает мемное сообщение для категории"""
    messages = MEMES.get(category, [""])
    message = random.choice(messages)
    return message.format(**kwargs) if kwargs else message

def get_item_description(item_name: str) -> str:
    """Получает описание предмета"""
    if item_name in ITEMS:
        return ITEMS[item_name]["description"]
    return "Неизвестный предмет"

def get_items_by_category(category: str) -> Dict[str, Dict]:
    """Получает предметы по категории"""
    if category == "Все":
        return ITEMS
    return {name: data for name, data in ITEMS.items() if data.get("category") == category}


def calculate_boss_reward(boss_name: str) -> Tuple[int, int]:
    """Рассчитывает награду за убийство босса"""
    rewards = {
        "Shadow Fiend": (random.randint(800, 3200), random.randint(35, 140)),
        "Axe": (random.randint(1000, 4000), random.randint(40, 160)),
        "Doom": (random.randint(1200, 4800), random.randint(45, 180)),
        "Zeus": (random.randint(1500, 6000), random.randint(50, 200)),
        "Invoker": (random.randint(1300, 5200), random.randint(48, 192)),
        "Roshan": (random.randint(1800, 7200), random.randint(55, 220)),
        "Roshan Prime": (random.randint(2000, 8000), random.randint(60, 240))
    }
    return rewards.get(boss_name, (1000, 100))  # Награда по умолчанию

def get_next_level_exp(current_level: int) -> int:
    """Рассчитывает опыт для следующего уровня"""
    return int(EXP_PER_LEVEL * (EXP_MULTIPLIER ** (current_level - 1)))

def get_user_progress(user: Dict) -> Dict[str, float]:
    """Получает прогресс пользователя по уровням"""
    next_level_exp = get_next_level_exp(user["level"])
    progress = (user["exp"] / next_level_exp) * 100 if next_level_exp > 0 else 100
    return {
        "current_exp": user["exp"],
        "next_level_exp": next_level_exp,
        "progress_percent": min(progress, 100),
        "level": user["level"]
    }

def get_talent_info(user: Dict) -> Dict[str, any]:
    """Получает информацию о талантах пользователя"""
    # Временная заглушка - в будущем можно добавить систему талантов
    return {
        "available_points": 0,
        "unlocked_talents": [],
        "talent_tree": {},
        "message": "Система талантов пока не реализована"
    }


