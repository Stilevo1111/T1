"""Инициализация обработчиков PvP и фиссуры"""

from .fissure import fissure, stats
from .pvp_system import pvp, handle_pvp_fight_callback, fight

__all__ = [
    # Обработчики фиссуры
    'fissure', 'stats',
    # Обработчики PvP
    'pvp', 'handle_pvp_fight_callback', 'fight',
]
