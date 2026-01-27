"""Инициализация всех обработчиков"""

from .main import start, stats, profile
from .fissure import fissure, fissure_top, stats as fissure_stats
from .boss import boss, attack
from .shop import shop, show_category_items, buy, potion
from .pvp import pvp, handle_pvp_fight_callback, fight
from .messages import handle_message, handle_pvp_buttons

__all__ = [
    # Основные обработчики
    'start', 'stats', 'profile',
    'fissure', 'fissure_top', 'fissure_stats',
    'boss', 'attack',
    'shop', 'show_category_items', 'buy', 'potion',
    'pvp', 'handle_pvp_fight_callback', 'fight',
    'handle_message', 'handle_pvp_buttons',
]
