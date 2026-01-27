"""Функции регистрации обработчиков для всех систем"""

import logging
from telegram.ext import Application

logger = logging.getLogger(__name__)

def register_all_handlers(app: Application):
    """Регистрация всех обработчиков"""
    try:
        # Регистрация основных обработчиков
        from .main import register_main_handlers
        from .fissure import register_fissure_handlers
        from .pvp import register_pvp_handlers
        from .boss import register_boss_handlers
        from .messages import register_message_handlers
        
        # Регистрация обработчиков
        register_main_handlers(app)
        register_fissure_handlers(app)
        register_pvp_handlers(app)
        register_boss_handlers(app)
        register_message_handlers(app)
        
        logger.info("Все обработчики зарегистрированы успешно")
    except Exception as e:
        logger.error(f"Ошибка регистрации обработчиков: {e}")
        raise

__all__ = ['register_all_handlers']


