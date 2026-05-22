# -*- coding: utf-8 -*-
"""
Event chances and statistics system for the fissure bot.
Handles multicast/zeus chances and persistent counters.
Extracted from main.py without changing behavior.
"""

import time
import logging
from database import get_config, set_config

logger = logging.getLogger(__name__)

# Default chances
MULTICAST_DEFAULT_CHANCE = 0.15
ZEUS_DEFAULT_CHANCE = 0.05

# Cache for event chances (refreshed every minute)
_event_chances_cache = {"ts": 0, "multicast": MULTICAST_DEFAULT_CHANCE, "zeus": ZEUS_DEFAULT_CHANCE}

# Spam protection constants (moved here for now, can be moved later if needed)
USER_PROCESSING_TTL = 30
BOT_CAN_DELETE_TTL = 3600
JOB_COOLDOWN = 30
WEEKLY_JOB_COOLDOWN = 60

# Stats keys
STATS_KEYS = ["rolls", "multicast", "zeus", "multicast_x2", "multicast_x3", "multicast_x4"]

# Buffer for batch writing stats to DB
_stat_buffer = {}
_stat_flush_timer = None


def get_event_chances():
    """Получить шансы событий из bot_config с кешированием"""
    now = time.time()
    if now - _event_chances_cache["ts"] < 60:
        return _event_chances_cache["multicast"], _event_chances_cache["zeus"]

    try:
        mc = float(get_config("multicast_chance", MULTICAST_DEFAULT_CHANCE))
        ze = float(get_config("zeus_chance", ZEUS_DEFAULT_CHANCE))
        _event_chances_cache.update({"ts": now, "multicast": mc, "zeus": ze})
        return mc, ze
    except Exception:
        return MULTICAST_DEFAULT_CHANCE, ZEUS_DEFAULT_CHANCE


def increment_stat(key):
    """Инкрементировать счётчик в буфере (пишется в БД после броска)"""
    if key in STATS_KEYS:
        _stat_buffer[key] = _stat_buffer.get(key, 0) + 1


async def flush_stat_buffer():
    """Записать накопленные счётчики в БД атомарно"""
    if not _stat_buffer:
        return
    try:
        for key, delta in _stat_buffer.items():
            try:
                from database import batch_increment_config
                batch_increment_config(f"stat_{key}", delta)
            except ImportError:
                try:
                    val = int(get_config(f"stat_{key}", 0)) + delta
                except (ValueError, TypeError):
                    val = delta
                set_config(f"stat_{key}", str(val))
        _stat_buffer.clear()
    except Exception as e:
        logger.error(f"flush_stat_buffer error: {e}")


def _load_stats():
    """Загрузить счётчики из буфера + БД"""
    stats = {}
    for key in STATS_KEYS:
        try:
            buf = _stat_buffer.get(key, 0)
            db_val = int(get_config(f"stat_{key}", 0))
            stats[key] = db_val + buf
        except (ValueError, TypeError):
            stats[key] = _stat_buffer.get(key, 0)
    return stats


def get_event_stats_text():
    """Текст со статистикой событий"""
    stats = _load_stats()
    total = stats["rolls"]
    if total == 0:
        return ""
    mc = stats["multicast"]
    ze = stats["zeus"]
    mc_pct = mc / total * 100 if total else 0
    ze_pct = ze / total * 100 if total else 0
    return (
        f"📊 События (всего бросков: {total}):\n"
        f"  👹 Мулькаст: {mc} ({mc_pct:.1f}%) — x2: {stats['multicast_x2']}, x3: {stats['multicast_x3']}, x4: {stats['multicast_x4']}\n"
        f"  ⚡ Зевс: {ze} ({ze_pct:.1f}%)"
    )
