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

__all__ = ["hero_positions"]

hero_positions: dict[str, int] = {
    # POS 1 — Carry
    "Anti-Mage": 1,
    "Drow Ranger": 1,
    "Faceless Void": 1,
    "Juggernaut": 1,
    "Luna": 1,
    "Medusa": 1,
    "Phantom Assassin": 1,
    "Phantom Lancer": 1,
    "Spectre": 1,
    "Sven": 1,
    "Terrorblade": 1,
    "Troll Warlord": 1,
    "Ursa": 1,
    "Wraith King": 1,
    "Bloodseeker": 1,
    "Clinkz": 1,
    "Gyrocopter": 1,
    "Kez": 1,
    "Monkey King": 1,
    "Morphling": 1,
    "Muerta": 1,
    "Razor": 1,
    "Riki": 1,
    "Shadow Fiend": 1,
    "Slark": 1,
    "Sniper": 1,
    "Templar Assassin": 1,
    "Viper": 1,
    "Weaver": 1,
    "Chaos Knight": 1,
    "Lifestealer": 1,
    "Alchemist": 1,
    "Naga Siren": 1,
    # POS 2 — Mid
    "Ember Spirit": 2,
    "Storm Spirit": 2,
    "Void Spirit": 2,
    "Queen of Pain": 2,
    "Puck": 2,
    "Invoker": 2,
    "Tinker": 2,
    "Zeus": 2,
    "Huskar": 2,
    "Lina": 2,
    "Leshrac": 2,
    "Dragon Knight": 2,
    "Necrophos": 2,
    "Outworld Destroyer": 2,
    "Pugna": 2,
    "Silencer": 2,
    "Skywrath Mage": 2,
    "Kunkka": 2,
    "Magnus": 2,
    "Tiny": 2,
    "Lone Druid": 2,
    # POS 3 — Offlane
    "Axe": 3,
    "Mars": 3,
    "Tidehunter": 3,
    "Centaur Warrunner": 3,
    "Sand King": 3,
    "Slardar": 3,
    "Underlord": 3,
    "Primal Beast": 3,
    "Doom": 3,
    "Timbersaw": 3,
    "Night Stalker": 3,
    "Bristleback": 3,
    "Dawnbreaker": 3,
    "Beastmaster": 3,
    "Brewmaster": 3,
    "Dark Seer": 3,
    "Legion Commander": 3,
    "Lycan": 3,
    "Pangolier": 3,
    "Spirit Breaker": 3,
    "Visage": 3,
    "Venomancer": 3,
    "Broodmother": 3,
    # POS 4 — Soft Support
    "Earth Spirit": 4,
    "Tusk": 4,
    "Nyx Assassin": 4,
    "Bounty Hunter": 4,
    "Hoodwink": 4,
    "Mirana": 4,
"Rubick": 4,
    "Phoenix": 4,
    "Pudge": 4,
    "Snapfire": 4,
    "Vengeful Spirit": 4,
    "Windranger": 4,
    "Marci": 4,
    "Dark Willow": 4,
    "Enchantress": 4,
    "Death Prophet": 2,  # Best Pos 2 (Mid)
    # POS 5 — Hard Support
    "Crystal Maiden": 5,
    "Lion": 5,
    "Shadow Shaman": 5,
    "Witch Doctor": 5,
    "Warlock": 5,
    "Dazzle": 5,
    "Oracle": 5,
    "Disruptor": 5,
    "Treant Protector": 5,
    "Lich": 5,
    "Bane": 5,
    "Chen": 5,
    "Keeper of the Light": 5,
    "Ogre Magi": 5,
    "Ringmaster": 5,
    "Winter Wyvern": 5,
    "Grimstroke": 5,
    "Jakiro": 5,
    # === FLEXIBLE / META OVERRIDES ===
    # These entries override the earlier positional assignments above.
    # They reflect current patch/meta preferences where a hero's best role differs
    # from the traditional grouping. Last definition wins (dict order).
    "Nature's Prophet": 3,  # Best Pos 3 now
    "Tiny": 2,  # Best Pos 2
    "Mirana": 4,  # Best Pos 4
    "Windranger": 2,  # Best Pos 2
    "Magnus": 2,  # Best Pos 2
    "Pudge": 4,  # Best Pos 4
}
