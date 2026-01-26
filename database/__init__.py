"""Модуль для работы с базой данных"""

from .connection import init_db, get_db_pool
from .queries import (
    get_user, update_user, get_top_by_stat, get_fissure_top, 
    update_fissure, get_user_by_id, create_user_if_not_exists,
    get_pvp_opponents, get_user_stats_summary
)

__all__ = [
    'init_db', 'get_db_pool',
    'get_user', 'update_user', 'get_top_by_stat', 'get_fissure_top',
    'update_fissure', 'get_user_by_id', 'create_user_if_not_exists',
    'get_pvp_opponents', 'get_user_stats_summary'
]
