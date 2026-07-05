"""
Event chances and statistics system for the fissure bot.
Handles multicast/zeus chances and persistent counters.
Extracted from main.py without changing behavior.
"""

import logging

__all__ = [
    "MULTICAST_DEFAULT_CHANCE",
    "ZEUS_DEFAULT_CHANCE",
    "TECHIES_DEFAULT_CHANCE",
    "USER_PROCESSING_TTL",
    "BOT_CAN_DELETE_TTL",
    "JOB_COOLDOWN",
    "WEEKLY_JOB_COOLDOWN",
    "get_event_chances",
]

MULTICAST_DEFAULT_CHANCE = 0.10
ZEUS_DEFAULT_CHANCE = 0.10
TECHIES_DEFAULT_CHANCE = 0.10

def get_event_chances():
    return MULTICAST_DEFAULT_CHANCE, ZEUS_DEFAULT_CHANCE, TECHIES_DEFAULT_CHANCE
