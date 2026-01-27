"""Функции регистрации обработчиков для всех систем"""

from telegram.ext import Application

def register_all_handlers(app: Application):
    """Регистрация всех обработчиков"""
    # Регистрация основных обработчиков
    from .pvp import register_pvp_callbacks
    from .shop import register_shop_callbacks
    
    # Регистрация обработчиков колбэков
    register_pvp_callbacks(app)
    register_shop_callbacks(app)

__all__ = ['register_all_handlers']


