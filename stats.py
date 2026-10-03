"""
Event chances and statistics system for the fissure bot.
Handles multicast/zeus chances and persistent counters.
Extracted from main.py without changing behavior.
"""


from constants import (
    BOT_CAN_DELETE_TTL,
    JOB_COOLDOWN,
    MULTICAST_DEFAULT_CHANCE,
    ROSHAN_DEFAULT_CHANCE,
    TECHIES_DEFAULT_CHANCE,
    USER_PROCESSING_TTL,
    WEEKLY_JOB_COOLDOWN,
    ZEUS_DEFAULT_CHANCE,
)

__all__ = [
    "MULTICAST_DEFAULT_CHANCE",
    "ZEUS_DEFAULT_CHANCE",
    "TECHIES_DEFAULT_CHANCE",
    "ROSHAN_DEFAULT_CHANCE",
    "USER_PROCESSING_TTL",
    "BOT_CAN_DELETE_TTL",
    "JOB_COOLDOWN",
    "WEEKLY_JOB_COOLDOWN",
    "get_event_chances",
    "get_roshan_chance",
]


def get_event_chances():
    return MULTICAST_DEFAULT_CHANCE, ZEUS_DEFAULT_CHANCE, TECHIES_DEFAULT_CHANCE


def get_roshan_chance():
    """Roshan is the first slice of the shared event scale.

    It is kept out of get_event_chances() on purpose: the returned triple is
    unpacked in fissure.py and monkeypatched with a literal triple in
    tests/test_fissure_roll_delivery.py, so widening it would break every
    existing test for no runtime benefit. Roshan takes the head of the scale,
    Zeus follows it, then Techies and multicast.
    """
    return ROSHAN_DEFAULT_CHANCE
