# -*- coding: utf-8 -*-
"""
Event chances and statistics system for the fissure bot.
Handles multicast/zeus chances and persistent counters.
Extracted from main.py without changing behavior.
"""

import time
import logging

__all__ = [
    "MULTICAST_DEFAULT_CHANCE",
    "ZEUS_DEFAULT_CHANCE",
    "USER_PROCESSING_TTL",
    "BOT_CAN_DELETE_TTL",
    "JOB_COOLDOWN",
    "WEEKLY_JOB_COOLDOWN",
    "get_event_chances",
]
# No longer using DB for roll statistics (removed to save Neon hours)

logger = logging.getLogger(__name__)

# Default chances (захардкожены, чтобы не дёргать БД при каждом ролле)
MULTICAST_DEFAULT_CHANCE = 0.15
ZEUS_DEFAULT_CHANCE = 0.05

# Spam protection constants (moved here for now, can be moved later if needed)
USER_PROCESSING_TTL = 30
BOT_CAN_DELETE_TTL = 3600
JOB_COOLDOWN = 30
WEEKLY_JOB_COOLDOWN = 60


def get_event_chances():
    """Возвращает текущие шансы мультикаста и зевса (захардкожены для снижения нагрузки на БД)"""
    return MULTICAST_DEFAULT_CHANCE, ZEUS_DEFAULT_CHANCE
