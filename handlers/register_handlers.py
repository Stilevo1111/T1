"""Функции регистрации обработчиков для всех систем"""

from telegram.ext import Application

def register_all_handlers(app: Application):
    """Регистрация всех обработчиков"""
    # Регистрация систем
    from .menu_handlers import register_menu_handlers
    from .system_registrars import (
        register_combat_handlers, register_pvp_handlers, register_quest_handlers,
        register_inventory_handlers, register_talent_handlers, register_fissure_handlers,
        register_achievement_handlers
    )
    from .pvp import register_pvp_callbacks
    from .talents import register_talent_callbacks
    from .shop import register_shop_callbacks
    
    # Регистрация всех систем
    register_menu_handlers(app)
    register_combat_handlers(app)
    register_pvp_handlers(app)
    register_quest_handlers(app)
    register_inventory_handlers(app)
    register_talent_handlers(app)
    register_fissure_handlers(app)
    register_achievement_handlers(app)
    
    # Регистрация обработчиков колбэков
    register_pvp_callbacks(app)
    register_talent_callbacks(app)
    register_shop_callbacks(app)

__all__ = ['register_all_handlers']


