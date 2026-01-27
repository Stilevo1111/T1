"""Game Logic Package"""

# Импортируем основные классы и функции для удобства использования
import sys
import os

# Добавляем корневую директорию в путь
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Импортируем напрямую из game_logic.py
import importlib.util
spec = importlib.util.spec_from_file_location("game_logic_module", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "game_logic.py"))
game_logic_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(game_logic_module)

CharacterStats = game_logic_module.CharacterStats
calculate_character_stats = game_logic_module.calculate_character_stats
get_fissure_result = game_logic_module.get_fissure_result
get_user_progress = game_logic_module.get_user_progress
get_next_level_exp = game_logic_module.get_next_level_exp

__all__ = ['CharacterStats', 'calculate_character_stats', 'get_fissure_result', 'get_user_progress', 'get_next_level_exp']
