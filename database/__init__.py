"""Модуль для работы с базой данных"""

# Import from the main database_main.py file which supports both PostgreSQL and SQLite
from database_main import (
    init_db, get_user, update_user, get_top_by_stat, get_fissure_top, update_fissure
)

# Add missing functions that are needed by handlers
async def get_pvp_opponents(user_id: int, min_mmr_ratio: float = 0.5, limit: int = 10):
    """Получение списка PvP противников"""
    # For now, return an empty list since we don't have the full implementation
    # This is a placeholder to make the bot run
    return []

async def get_user_stats_summary(user_id: int):
    """Получение сводной статистики пользователя"""
    # For now, return None since we don't have the full implementation
    # This is a placeholder to make the bot run
    return None

__all__ = [
    'init_db', 'get_user', 'update_user', 'get_top_by_stat', 'get_fissure_top', 'update_fissure',
    'get_pvp_opponents', 'get_user_stats_summary'
]
