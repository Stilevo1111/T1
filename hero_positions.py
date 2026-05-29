"""
Manual hero positions database for Dota 2.

This module provides a static mapping of hero names to their preferred positions
(1=Safe Lane Carry, 2=Mid, 3=Offlane, 4=Soft Support, 5=Hard Support).

Used by:
- hero_meta.py (for meta images and position detection)
- weekly_analytics.py (for role distribution stats)

Entries at the bottom (Flexible heroes) intentionally override earlier definitions
to reflect current meta preferences. Do not change any position values without
updating the consumers.

All changes must preserve exact hero names and assigned positions.
"""

from __future__ import annotations

# Position constants for readability and consistency across modules
POS_CARRY: int = 1
POS_MID: int = 2
POS_OFFLANE: int = 3
POS_SOFT_SUPPORT: int = 4
POS_HARD_SUPPORT: int = 5

__all__ = ["hero_positions", "POS_CARRY", "POS_MID", "POS_OFFLANE", "POS_SOFT_SUPPORT", "POS_HARD_SUPPORT"]

hero_positions: dict[str, int] = {
    # POS 1 — Carry
    "Anti-Mage": POS_CARRY,
    "Drow Ranger": POS_CARRY,
    "Faceless Void": POS_CARRY,
    "Juggernaut": POS_CARRY,
    "Luna": POS_CARRY,
    "Medusa": POS_CARRY,
    "Phantom Assassin": POS_CARRY,
    "Phantom Lancer": POS_CARRY,
    "Spectre": POS_CARRY,
    "Sven": POS_CARRY,
    "Terrorblade": POS_CARRY,
    "Troll Warlord": POS_CARRY,
    "Ursa": POS_CARRY,
    "Wraith King": POS_CARRY,
    "Bloodseeker": POS_CARRY,
    "Clinkz": POS_CARRY,
    "Gyrocopter": POS_CARRY,
    "Kez": POS_CARRY,
    "Monkey King": POS_CARRY,
    "Morphling": POS_CARRY,
    "Muerta": POS_CARRY,
    "Razor": POS_CARRY,
    "Riki": POS_CARRY,
    "Shadow Fiend": POS_CARRY,
    "Slark": POS_CARRY,
    "Sniper": POS_CARRY,
    "Templar Assassin": POS_CARRY,
    "Viper": POS_CARRY,
    "Weaver": POS_CARRY,
    "Chaos Knight": POS_CARRY,
    "Lifestealer": POS_CARRY,
    "Alchemist": POS_CARRY,
    # POS 2 — Mid
    "Ember Spirit": POS_MID,
    "Storm Spirit": POS_MID,
    "Void Spirit": POS_MID,
    "Queen of Pain": POS_MID,
    "Puck": POS_MID,
    "Invoker": POS_MID,
    "Tinker": POS_MID,
    "Zeus": POS_MID,
    "Huskar": POS_MID,
    "Lina": POS_MID,
    "Leshrac": POS_MID,
    "Dragon Knight": POS_MID,
    "Necrophos": POS_MID,
    "Outworld Destroyer": POS_MID,
    "Pugna": POS_MID,
    "Silencer": POS_MID,
    "Skywrath Mage": POS_MID,
    "Kunkka": POS_MID,
    "Magnus": POS_MID,
    "Tiny": POS_MID,
    "Lone Druid": POS_MID,
    # POS 3 — Offlane
    "Axe": POS_OFFLANE,
    "Mars": POS_OFFLANE,
    "Tidehunter": POS_OFFLANE,
    "Centaur Warrunner": POS_OFFLANE,
    "Sand King": POS_OFFLANE,
    "Slardar": POS_OFFLANE,
    "Underlord": POS_OFFLANE,
    "Primal Beast": POS_OFFLANE,
    "Doom": POS_OFFLANE,
    "Timbersaw": POS_OFFLANE,
    "Night Stalker": POS_OFFLANE,
    "Bristleback": POS_OFFLANE,
    "Dawnbreaker": POS_OFFLANE,
    "Beastmaster": POS_OFFLANE,
    "Brewmaster": POS_OFFLANE,
    "Dark Seer": POS_OFFLANE,
    "Legion Commander": POS_OFFLANE,
    "Lycan": POS_OFFLANE,
    "Pangolier": POS_OFFLANE,
    "Spirit Breaker": POS_OFFLANE,
    "Visage": POS_OFFLANE,
    "Venomancer": POS_OFFLANE,
    "Broodmother": POS_OFFLANE,
    # POS 4 — Soft Support
    "Earth Spirit": POS_SOFT_SUPPORT,
    "Tusk": POS_SOFT_SUPPORT,
    "Nyx Assassin": POS_SOFT_SUPPORT,
    "Bounty Hunter": POS_SOFT_SUPPORT,
    "Hoodwink": POS_SOFT_SUPPORT,
    "Mirana": POS_SOFT_SUPPORT,
    "Rubick": POS_SOFT_SUPPORT,
    "Phoenix": POS_SOFT_SUPPORT,
    "Pudge": POS_SOFT_SUPPORT,
    "Snapfire": POS_SOFT_SUPPORT,
    "Techies": POS_SOFT_SUPPORT,
    "Vengeful Spirit": POS_SOFT_SUPPORT,
    "Marci": POS_SOFT_SUPPORT,
    "Dark Willow": POS_SOFT_SUPPORT,
    "Enchantress": POS_SOFT_SUPPORT,
    # POS 5 — Hard Support
    "Crystal Maiden": POS_HARD_SUPPORT,
    "Lion": POS_HARD_SUPPORT,
    "Shadow Shaman": POS_HARD_SUPPORT,
    "Witch Doctor": POS_HARD_SUPPORT,
    "Warlock": POS_HARD_SUPPORT,
    "Dazzle": POS_HARD_SUPPORT,
    "Oracle": POS_HARD_SUPPORT,
    "Disruptor": POS_HARD_SUPPORT,
    "Treant Protector": POS_HARD_SUPPORT,
    "Lich": POS_HARD_SUPPORT,
    "Bane": POS_HARD_SUPPORT,
    "Chen": POS_HARD_SUPPORT,
    "Keeper of the Light": POS_HARD_SUPPORT,
    "Ogre Magi": POS_HARD_SUPPORT,
    "Ringmaster": POS_HARD_SUPPORT,
    "Winter Wyvern": POS_HARD_SUPPORT,
    "Grimstroke": POS_HARD_SUPPORT,
    "Jakiro": POS_HARD_SUPPORT,
    # === FLEXIBLE / META OVERRIDES ===
    # These entries override the earlier positional assignments above.
    # They reflect current patch/meta preferences where a hero's best role differs
    # from the traditional grouping. Last definition wins (dict order).
    "Nature's Prophet": POS_OFFLANE,
    "Tiny": POS_MID,
    "Mirana": POS_SOFT_SUPPORT,
    "Windranger": POS_MID,
    "Magnus": POS_MID,
    "Pudge": POS_SOFT_SUPPORT,
}
