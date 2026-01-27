"""Инициализация всех обработчиков"""

from .main import start, stats, profile
from .fissure import fissure, fissure_top, stats as fissure_stats
from .boss import boss, attack
from .shop import shop, show_category_items, buy, potion
from .pvp import pvp, handle_pvp_fight_callback, fight
from .talents import talents, learn_talent, add_stat, level_up_handler, achievements
from .talents import add_str, add_agi, add_int, learn, level_up, handle_talents_category, handle_talents_stats, handle_talents_main, handle_learn_talent_callback
from .heal import heal
from .messages import handle_message, handle_pvp_buttons

# Импортируем новые системы
from .menu_handlers import register_menu_handlers
from .combat_system import register_combat_handlers
from .pvp_system import register_pvp_handlers
from .quest_system import register_quest_handlers
from .inventory_system import register_inventory_handlers
from .talent_system import register_talent_handlers
from .system_registrars import register_fissure_handlers
from .achievement_system import register_achievement_handlers
from .fissure_menu import register_fissure_menu_handlers

__all__ = [
    # Основные обработчики
    'start', 'stats', 'profile',
    'fissure', 'fissure_top', 'fissure_stats',
    'boss', 'attack',
    'shop', 'show_category_items', 'buy', 'potion',
    'pvp', 'handle_pvp_fight_callback', 'fight',
    'talents', 'learn_talent', 'add_stat', 'level_up_handler', 'achievements',
    'add_str', 'add_agi', 'add_int', 'learn', 'level_up', 'handle_talents_category', 'handle_talents_stats', 'handle_talents_main', 'handle_learn_talent_callback',
    'heal',
    'handle_message', 'handle_pvp_buttons',
    
    # Функции регистрации систем
    'register_menu_handlers',
    'register_combat_handlers', 
    'register_pvp_handlers',
    'register_quest_handlers',
    'register_inventory_handlers',
    'register_talent_handlers',
    'register_fissure_handlers',
    'register_achievement_handlers',
    'register_fissure_menu_handlers'
]
