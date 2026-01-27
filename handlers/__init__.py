"""Инициализация всех обработчиков"""

from .main import start, stats, profile
from .fissure import fissure, stats as fissure_stats
from .boss import boss
from .shop import shop, show_category_items, buy, potion
from .pvp import pvp, handle_pvp_fight_callback, fight
from .messages import handle_message, handle_pvp_buttons

__all__ = [
    # Основные обработчики
    'start', 'stats', 'profile',
    'fissure', 'fissure_stats',
    'boss',
    'shop', 'show_category_items', 'buy', 'potion',
    'pvp', 'handle_pvp_fight_callback', 'fight',
    'handle_message', 'handle_pvp_buttons',
]
