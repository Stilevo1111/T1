"""Функции регистрации обработчиков для всех систем"""

from telegram.ext import Application

def register_all_handlers(app: Application):
    """Регистрация всех обработчиков"""
    # Регистрация основных обработчиков
    from .pvp import register_pvp_handlers
    from .fissure import register_fissure_callbacks
    
    # Регистрация обработчиков колбэков
    register_pvp_handlers(app)
    register_fissure_callbacks(app)

__all__ = ['register_all_handlers']


