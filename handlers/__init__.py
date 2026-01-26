"""Модуль обработчиков команд бота"""

from .main import start, stats, profile, debug_boss
from .fissure import fissure, fissure_top, stats as fissure_stats
from .boss import boss, attack
from .shop import shop, show_category_items, buy, potion
from .pvp import pvp, handle_pvp_fight, fight
from .top import top
from .talents import talents, learn_talent, stats_distribute, add_stat, level_up_handler, achievements
from .talents import add_str, add_agi, add_int, learn, level_up, handle_talent_buttons
from .heal import heal
from .messages import handle_message, handle_pvp_buttons

__all__ = [
    'start', 'stats', 'profile', 'debug_boss',
    'fissure', 'fissure_top', 'fissure_stats',
    'boss', 'attack',
    'shop', 'show_category_items', 'buy', 'potion',
    'pvp', 'handle_pvp_fight', 'fight',
    'top',
    'talents', 'learn_talent', 'stats_distribute', 'add_stat', 'level_up_handler', 'achievements',
    'add_str', 'add_agi', 'add_int', 'learn', 'level_up', 'handle_talent_buttons',
    'heal',
    'handle_message', 'handle_pvp_buttons'
]