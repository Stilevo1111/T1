"""Game Logic Package"""

# Импортируем основные классы для удобства использования
from .level_system import LevelSystem, CharacterStats

# Функции для совместимости со старым кодом
def calculate_character_stats(user_data):
    """Рассчет характеристик персонажа"""
    return CharacterStats.calculate_base_stats(user_data)

def get_user_progress(user):
    """Получение прогресса пользователя"""
    level, progress = LevelSystem.calculate_level_from_exp(user.get('exp', 0))
    return {
        'level': level,
        'progress': progress,
        'exp': user.get('exp', 0)
    }

def get_next_level_exp(level):
    """Получение опыта для следующего уровня"""
    return LevelSystem.get_exp_for_level(level + 1)

# Импортируем функции из основного модуля game_logic.py для совместимости
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

try:
    # Импортируем функции из game_logic.py
    import importlib.util
    spec = importlib.util.spec_from_file_location("game_logic_module", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "game_logic.py"))
    game_logic_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(game_logic_module)

    # Импортируем нужные функции
    calculate_boss_strategy = game_logic_module.calculate_boss_strategy
    get_fissure_result = game_logic_module.get_fissure_result
    get_meme_message = game_logic_module.get_meme_message
    spawn_boss = game_logic_module.spawn_boss
    check_level_restriction = game_logic_module.check_level_restriction
    calculate_damage_with_talents = game_logic_module.calculate_damage_with_talents
    calculate_dodge = game_logic_module.calculate_dodge
    calculate_boss_reward = game_logic_module.calculate_boss_reward
    check_level_up_new = game_logic_module.check_level_up_new
    get_user_progress = game_logic_module.get_user_progress
    get_next_level_exp = game_logic_module.get_next_level_exp
    calculate_character_stats = game_logic_module.calculate_character_stats
    get_items_by_category = game_logic_module.get_items_by_category
    get_item_description = game_logic_module.get_item_description
    get_potion_data = game_logic_module.get_potion_data
    calculate_damage = game_logic_module.calculate_damage
    get_talent_info = game_logic_module.get_talent_info
    can_learn_talent = game_logic_module.can_learn_talent
    apply_talent_effects = game_logic_module.apply_talent_effects
    get_user_achievements = game_logic_module.get_user_achievements
    regenerate_hp = game_logic_module.regenerate_hp
    check_level_up = game_logic_module.check_level_up

except ImportError as e:
    print(f"Ошибка при импорте из game_logic.py: {e}")
    # Если game_logic.py не доступен, создаем заглушки
    def calculate_boss_strategy(user, boss_level):
        """Заглушка для calculate_boss_strategy"""
        return {
            "recommendations": ["Стратегия недоступна"],
            "damage_per_second": 0,
            "survivability": 0,
            "overall_score": 0
        }

    def get_fissure_result():
        """Заглушка для get_fissure_result"""
        return 0.1, "+0.1 см", "Фиссура немного выросла"

    def get_meme_message(category, **kwargs):
        """Заглушка для get_meme_message"""
        return "Мем недоступен"

# Определяем TALENTS для использования в handlers/talents.py
TALENTS = {
    # Сила (Strength)
    'str_1': {
        'name': 'Сила I',
        'description': '+10 к Силе',
        'cost': 1,
        'category': 'strength',
        'level_req': 1,
        'max_level': 1,
        'prerequisites': [],
        'stats': {'str': 10},
        'pvp_effect': 'Увеличивает урон в PvP на 10%',
        'boss_effect': 'Увеличивает урон по боссам на 10%'
    },
    'str_2': {
        'name': 'Сила II',
        'description': 'Увеличивает урон на 15%',
        'cost': 2,
        'category': 'strength',
        'level_req': 5,
        'max_level': 1,
        'prerequisites': ['str_1'],
        'stats': {'damage_mult': 1.15},
        'pvp_effect': 'Увеличивает урон в PvP на 15%',
        'boss_effect': 'Увеличивает урон по боссам на 15%'
    },
    'str_3': {
        'name': 'Сила III',
        'description': 'Увеличивает броню на 10%',
        'cost': 3,
        'category': 'strength',
        'level_req': 10,
        'max_level': 1,
        'prerequisites': ['str_1', 'str_2'],
        'stats': {'armor_mult': 1.10},
        'pvp_effect': 'Увеличивает броню в PvP на 10%',
        'boss_effect': 'Увеличивает броню против боссов на 10%'
    },
    'str_4': {
        'name': 'Сила IV',
        'description': 'Увеличивает максимальное HP на 15%',
        'cost': 4,
        'category': 'strength',
        'level_req': 15,
        'max_level': 1,
        'prerequisites': ['str_1', 'str_2', 'str_3'],
        'stats': {'hp_mult': 1.15},
        'pvp_effect': 'Увеличивает HP в PvP на 15%',
        'boss_effect': 'Увеличивает HP против боссов на 15%'
    },
    
    # Ловкость (Agility)
    'agi_1': {
        'name': 'Ловкость I',
        'description': '+10 к Ловкости',
        'cost': 1,
        'category': 'agility',
        'level_req': 1,
        'max_level': 1,
        'prerequisites': [],
        'stats': {'agi': 10},
        'pvp_effect': 'Увеличивает критический урон в PvP на 10%',
        'boss_effect': 'Увеличивает критический урон по боссам на 10%'
    },
    'agi_2': {
        'name': 'Ловкость II',
        'description': 'Увеличивает критический урон на 15%',
        'cost': 2,
        'category': 'agility',
        'level_req': 5,
        'max_level': 1,
        'prerequisites': ['agi_1'],
        'stats': {'crit_mult': 1.15},
        'pvp_effect': 'Увеличивает критический урон в PvP на 15%',
        'boss_effect': 'Увеличивает критический урон по боссам на 15%'
    },
    'agi_3': {
        'name': 'Ловкость III',
        'description': 'Увеличивает уклонение на 10%',
        'cost': 3,
        'category': 'agility',
        'level_req': 10,
        'max_level': 1,
        'prerequisites': ['agi_1', 'agi_2'],
        'stats': {'evasion_mult': 1.10},
        'pvp_effect': 'Увеличивает уклонение в PvP на 10%',
        'boss_effect': 'Увеличивает уклонение против боссов на 10%'
    },
    'agi_4': {
        'name': 'Ловкость IV',
        'description': 'Увеличивает скорость атаки на 15%',
        'cost': 4,
        'category': 'agility',
        'level_req': 15,
        'max_level': 1,
        'prerequisites': ['agi_1', 'agi_2', 'agi_3'],
        'stats': {'speed_mult': 1.15},
        'pvp_effect': 'Увеличивает скорость атаки в PvP на 15%',
        'boss_effect': 'Увеличивает скорость атаки против боссов на 15%'
    },
    
    # Интеллект (Intelligence)
    'int_1': {
        'name': 'Интеллект I',
        'description': '+10 к Интеллекту',
        'cost': 1,
        'category': 'intelligence',
        'level_req': 1,
        'max_level': 1,
        'prerequisites': [],
        'stats': {'int': 10},
        'pvp_effect': 'Увеличивает магический урон в PvP на 10%',
        'boss_effect': 'Увеличивает магический урон по боссам на 10%'
    },
    'int_2': {
        'name': 'Интеллект II',
        'description': 'Увеличивает силу заклинаний на 15%',
        'cost': 2,
        'category': 'intelligence',
        'level_req': 5,
        'max_level': 1,
        'prerequisites': ['int_1'],
        'stats': {'spell_damage_mult': 1.15},
        'pvp_effect': 'Увеличивает магический урон в PvP на 15%',
        'boss_effect': 'Увеличивает магический урон по боссам на 15%'
    },
    'int_3': {
        'name': 'Интеллект III',
        'description': 'Увеличивает максимальную ману на 10%',
        'cost': 3,
        'category': 'intelligence',
        'level_req': 10,
        'max_level': 1,
        'prerequisites': ['int_1', 'int_2'],
        'stats': {'mana_mult': 1.10},
        'pvp_effect': 'Увеличивает максимальную ману в PvP на 10%',
        'boss_effect': 'Увеличивает максимальную ману против боссов на 10%'
    },
    'int_4': {
        'name': 'Интеллект IV',
        'description': 'Увеличивает магическую защиту на 15%',
        'cost': 4,
        'category': 'intelligence',
        'level_req': 15,
        'max_level': 1,
        'prerequisites': ['int_1', 'int_2', 'int_3'],
        'stats': {'magic_resist_mult': 1.15},
        'pvp_effect': 'Увеличивает магическую защиту в PvP на 15%',
        'boss_effect': 'Увеличивает магическую защиту против боссов на 15%'
    },
    
    # Гибридные таланты
    'hybrid_1': {
        'name': 'Гибрид I',
        'description': '+5 к каждой характеристике',
        'cost': 2,
        'category': 'hybrid',
        'level_req': 3,
        'max_level': 1,
        'prerequisites': [],
        'stats': {'str': 5, 'agi': 5, 'int': 5},
        'pvp_effect': 'Увеличивает все характеристики в PvP',
        'boss_effect': 'Увеличивает все характеристики против боссов'
    },
    'hybrid_2': {
        'name': 'Гибрид II',
        'description': 'Увеличивает все характеристики на 10%',
        'cost': 4,
        'category': 'hybrid',
        'level_req': 8,
        'max_level': 1,
        'prerequisites': ['hybrid_1'],
        'stats': {'all_stats_mult': 1.10},
        'pvp_effect': 'Увеличивает все характеристики в PvP на 10%',
        'boss_effect': 'Увеличивает все характеристики против боссов на 10%'
    },
    'hybrid_3': {
        'name': 'Гибрид III',
        'description': 'Увеличивает весь урон на 5%',
        'cost': 5,
        'category': 'hybrid',
        'level_req': 12,
        'max_level': 1,
        'prerequisites': ['hybrid_1', 'hybrid_2'],
        'stats': {'all_damage_mult': 1.05},
        'pvp_effect': 'Увеличивает весь урон в PvP на 5%',
        'boss_effect': 'Увеличивает весь урон по боссам на 5%'
    },
    'hybrid_4': {
        'name': 'Гибрид IV',
        'description': 'Увеличивает всю защиту на 5%',
        'cost': 5,
        'category': 'hybrid',
        'level_req': 18,
        'max_level': 1,
        'prerequisites': ['hybrid_1', 'hybrid_2', 'hybrid_3'],
        'stats': {'all_defense_mult': 1.05},
        'pvp_effect': 'Увеличивает всю защиту в PvP на 5%',
        'boss_effect': 'Увеличивает всю защиту против боссов на 5%'
    }
}

__all__ = ['LevelSystem', 'CharacterStats', 'calculate_character_stats', 'get_user_progress', 'get_next_level_exp', 'calculate_boss_strategy', 'get_fissure_result', 'get_meme_message', 'spawn_boss', 'check_level_restriction', 'calculate_damage_with_talents', 'calculate_dodge', 'calculate_boss_reward', 'check_level_up_new', 'get_items_by_category', 'get_item_description', 'get_potion_data', 'calculate_damage', 'get_talent_info', 'can_learn_talent', 'apply_talent_effects', 'get_user_achievements', 'regenerate_hp', 'check_level_up', 'TALENTS']


