"""Centralized hero name mappings for Dota 2.

Provides:
- CDN name mapping (internal OpenDota name -> Steam CDN filename)
- Display name mapping (internal OpenDota name -> human-readable name)
"""
from __future__ import annotations

__all__ = [
    "HERO_NAME_TO_CDN",
    "CDN_TO_LOCAL_NAME",
    "DISPLAY_NAME_MAP",
    "get_cdn_hero_name",
    "get_local_hero_name",
    "get_display_name",
]

HERO_NAME_TO_CDN: dict[str, str] = {
    "anti_mage": "antimage",
    "necrophos": "necrolyte",
    "queenofpain": "queenofpain",
    "skywrath_mage": "skywrath_mage",
    "outworld_destroyer": "obsidian_destroyer",
    "lone_druid": "lone_druid",
    "centaur": "centaur",
    "magnataur": "magnataur",
    "doom_bringer": "doom_bringer",
    "witchdoctor": "witch_doctor",
    "keeper_of_the_light": "keeper_of_the_light",
    "nightstalker": "night_stalker",
    "shadow_shaman": "shadow_shaman",
    "life_stealer": "life_stealer",
    "abyssal_underlord": "abyssal_underlord",
    "crystal_maiden": "crystal_maiden",
    "tusk": "tusk",
    "brewmaster": "brewmaster",
    "oracle": "oracle",
    "techies": "techies",
    "ember_spirit": "ember_spirit",
    "earth_spirit": "earth_spirit",
    "terrorblade": "terrorblade",
    "phoenix": "phoenix",
    "winter_wyvern": "winter_wyvern",
    "dark_seer": "dark_seer",
    "riki": "riki",
    "chen": "chen",
    "enigma": "enigma",
    "huskar": "huskar",
    "leoric": "skeleton_king",
    "slardar": "slardar",
    "phantom_assassin": "phantom_assassin",
    "phantom_lancer": "phantom_lancer",
    "faceless_void": "faceless_void",
    "death_prophet": "death_prophet",
    "sven": "sven",
    "luna": "luna",
    "dragon_knight": "dragon_knight",
    "vengeful_spirit": "vengefulspirit",
    "warlock": "warlock",
    "shadow_demon": "shadow_demon",
    "zeus": "zuus",
    "razor": "razor",
    "axe": "axe",
    "pudge": "pudge",
    "sand_king": "sand_king",
    "clinkz": "clinkz",
    "templar_assassin": "templar_assassin",
    "viper": "viper",
    "mirana": "mirana",
    "morphling": "morphling",
    "storm_spirit": "storm_spirit",
    "wraith_king": "skeleton_king",
    "invoker": "invoker",
    "abaddon": "abaddon",
    "ancient_apparition": "ancient_apparition",
    "arc_warden": "arc_warden",
    "bloodseeker": "bloodseeker",
    "bounty_hunter": "bounty_hunter",
    "broodmother": "broodmother",
    "disruptor": "disruptor",
    "doom": "doom",
    "elder_titan": "elder_titan",
    "enchantress": "enchantress",
    "earthshaker": "earthshaker",
    "legion_commander": "legion_commander",
    "lich": "lich",
    "lifestealer": "life_stealer",
    "lion": "lion",
    "meepo": "meepo",
    "natures_prophet": "furion",
    "ogre_magi": "ogre_magi",
    "omniknight": "omniknight",
    "pugna": "pugna",
    "rubick": "rubick",
    "slark": "slark",
    "sniper": "sniper",
    "spectre": "spectre",
    "spirit_breaker": "spirit_breaker",
    "tidehunter": "tidehunter",
    "clockwerk": "rattletrap",
    "io": "wisp",
    "timber_saw": "shredder",
    "tinker": "tinker",
    "tiny": "tiny",
    "treant": "treant",
    "undying": "undying",
    "venomancer": "venomancer",
    "visage": "visage",
    "weaver": "weaver",
}

CDN_TO_LOCAL_NAME: dict[str, str] = {
    cdn_name: local_name
    for local_name, cdn_name in HERO_NAME_TO_CDN.items()
    if cdn_name != local_name
}

DISPLAY_NAME_MAP: dict[str, str] = {
    "necrophos": "Necrophos",
    "queenofpain": "Queen of Pain",
    "skywrath_mage": "Skywrath Mage",
    "outworld_destroyer": "Outworld Destroyer",
    "lone_druid": "Lone Druid",
    "centaur": "Centaur Warrunner",
    "magnataur": "Magnus",
    "axe": "Axe",
    "doom_bringer": "Doom",
    "witchdoctor": "Witch Doctor",
    "keeper_of_the_light": "Keeper of the Light",
    "nightstalker": "Night Stalker",
    "shadow_shaman": "Shadow Shaman",
    "life_stealer": "Lifestealer",
    "abyssal_underlord": "Underlord",
}


def get_cdn_hero_name(short_name: str) -> str:
    """Convert OpenDota hero name to Steam CDN file name"""
    return HERO_NAME_TO_CDN.get(short_name, short_name)


def get_local_hero_name(cdn_name: str) -> str:
    """Convert Steam CDN hero name to local asset file name.
    
    Steam renames some hero icons (e.g., 'doom_bringer' instead of 'doom'),
    but CDN URLs may use the short name. This maps CDN names back to
    the actual local asset names.
    """
    return CDN_TO_LOCAL_NAME.get(cdn_name, cdn_name)


def get_display_name(internal_name: str) -> str:
    """Convert internal OpenDota hero name (with or without npc_dota_hero_ prefix) to display name."""
    if internal_name.startswith("npc_dota_hero_"):
        internal_name = internal_name[len("npc_dota_hero_"):]

    if internal_name in DISPLAY_NAME_MAP:
        return DISPLAY_NAME_MAP[internal_name]

    return " ".join(word.capitalize() for word in internal_name.split("_"))