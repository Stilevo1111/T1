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

__all__ = ['LevelSystem', 'CharacterStats', 'calculate_character_stats', 'get_user_progress', 'get_next_level_exp', 'calculate_boss_strategy', 'get_fissure_result', 'get_meme_message', 'spawn_boss', 'check_level_restriction', 'calculate_damage_with_talents', 'calculate_dodge', 'calculate_boss_reward', 'check_level_up_new', 'get_items_by_category', 'get_item_description', 'get_potion_data', 'calculate_damage', 'get_talent_info', 'can_learn_talent', 'apply_talent_effects', 'get_user_achievements', 'regenerate_hp', 'check_level_up']
