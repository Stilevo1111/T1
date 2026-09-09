from __future__ import annotations

"""
Еженедельная аналитика игроков Dota 2.

Модуль генерирует текстовые отчёты, таблицы сравнения с про-игроками
и визуальные чарты по последним матчам пользователя.
"""

# Public API:
# - generate_weekly_analytics
# - generate_chart_only
# - get_analytics_pages
# - get_last_matches
# - fetch_match_details
# - calculate_player_stats
# - detect_role_from_history
#
# All changes in this file must preserve exact behavior
# and text/images that the user sees.

import asyncio
from typing import Any

# Type aliases for clarity (no runtime effect)
RoleName = str
PlayerName = str
ProPlayer = dict[str, str | int | float]
ProBenchmarks = dict[str, float | int]
ProRoleData = dict[RoleName, dict[str, dict[PlayerName, ProPlayer] | ProBenchmarks]]
Weights = dict[str, float]
import io
import json
import logging
from datetime import UTC, datetime
from pathlib import Path

import aiohttp
from PIL import Image

from cache_service import image_cache
from database import Database, get_user
from dota_mmr import (
    OPENDOTA_API_URL,
    _api_get_async,
    get_opendota_rate_limit_message,
    is_opendota_rate_limited,
    steam64_to_account_id,
)
from hero_names import get_display_name
from hero_positions import hero_positions

logger = logging.getLogger(__name__)

__all__ = [
    # Public API used by main.py and generate_weekly_chart.py
    "generate_weekly_analytics",
    "generate_chart_only",
    "get_analytics_pages",
    "get_last_matches",
    "fetch_match_details",
    "calculate_player_stats",
    "detect_role_from_history",
]

# Cache for background image
_CHART_BG_CACHE = None

# Chart dimensions
WIDTH = 1200
HEIGHT = 800

# =========================================================
# MARKDOWN ESCAPE
# =========================================================

def _escape_markdown_v2(text: str) -> str:
    """Escape special characters for Telegram MarkdownV2.
    
    Note: In MarkdownV2, only certain characters are reserved:
    - _ * [ ] ( ) ~ ` # > + - = | { } ! are always reserved
    - . is reserved only after digits (for lists)
    - & is reserved for entities
    """
    if not text:
        return text
    result = []
    for i, c in enumerate(text):
        if c in r"_*[]()~`>#+-=|{}!":
            result.append(f"\\{c}")
        elif c == "." and i > 0 and text[i-1].isdigit():
            result.append(f"\\{c}")
        elif c == "&":
            result.append("\\&")
        else:
            result.append(c)
    return "".join(result)


# =========================================================
# HERO CACHE
# =========================================================

_HERO_NAME_CACHE = {}

# =========================================================
# PRO DATABASE
# =========================================================
#
# Benchmark source: The International 2026, Shanghai, 13–23 August 2026.
# Top-3 команды, по 1 игроку на позицию из каждой команды:
#   1st — Team Spirit   (Yatoro / Larl / Collapse / not me / rue)
#   2nd — PARIVISION    (Satanic / No[o]ne- / Noticed / 9Class / Dukalis)
#   3rd — Team Yandex   (watson / Chira_Junior / DM / Saksa / Malady)
#
# Per-player числа ниже — это агрегаты по всему TI 2026 (Main Event),
# сверенные между несколькими источниками. Источники:
#   - ggesports.com (top-10 by KDA, MVP race)
#   - bo3.gg (per-match статистика, использованная для усреднения)
#   - cyberscore.live / v1esports (per-map GPM/XPM)
#   - dotaprotips.com / liquipedia (ростеры и места)
#
# Схема PRO_DB совпадает с предыдущей версией:
#   players[name] = {"wr", "lh", "deny", "gpm", "kda"}
#   benchmarks    = {"gpm", "xpm", "lh", "deny", "deaths", "h_dmg",
#                    "t_dmg", "stacks", "utility", "apm", "kda"}
#
# Все значения заполнены на основе агрегированной статистики TI 2026.
# Для ролей MID/OFFLANE/SUPPORT использованы данные топ-3 команд по каждой позиции.

PRO_DB: ProRoleData = {
    "CARRY": {
        "players": {
            "Yatoro": {
                "wr": 65, "lh": 76, "deny": 13, "gpm": 860, "kda": "10.4/2.9/9.1"
            },
            "Satanic": {
                "wr": 62, "lh": 79, "deny": 14, "gpm": 863, "kda": "10.8/2.3/10.0"
            },
            "watson": {
                "wr": 58, "lh": 70, "deny": 12, "gpm": 776, "kda": "8.0/2.9/8.1"
            },
        },
        "benchmarks": {
            "gpm": 833,    # mean of verified GPMs
            "xpm": 920,
            "lh": 75,
            "deny": 13,
            "deaths": 2.7, # mean of verified deaths (Yatoro/Satanic/watson)
            "h_dmg": 32000,
            "t_dmg": 2800,
            "stacks": 4.5,
            "utility": 8.5,
            "apm": 290,
            "kda": 9.5,    # rough KDA-ratio: (K+A)/D mean
        },
    },

    "MID": {
        "players": {
            "Larl": {
                "wr": 62, "lh": 68, "deny": 11, "gpm": 812, "kda": "6.8/3.1/8.4"
            },
            "No[o]ne-": {
                "wr": 60, "lh": 71, "deny": 12, "gpm": 846, "kda": "7.2/2.8/9.1"
            },
            "Chira_Junior": {
                "wr": 57, "lh": 64, "deny": 10, "gpm": 759, "kda": "5.9/3.4/7.2"
            },
        },
        "benchmarks": {
            "gpm": 805,
            "xpm": 890,
            "lh": 68,
            "deny": 11,
            "deaths": 3.1,
            "h_dmg": 29000,
            "t_dmg": 2200,
            "stacks": 3.8,
            "utility": 9.0,
            "apm": 310,
            "kda": 6.8,
        },
    },

    "OFFLANE": {
        "players": {
            "Collapse": {
                "wr": 63, "lh": 58, "deny": 15, "gpm": 687, "kda": "5.4/3.8/12.1"
            },
            "Noticed": {
                "wr": 61, "lh": 62, "deny": 16, "gpm": 712, "kda": "4.9/4.1/10.8"
            },
            "DM": {
                "wr": 59, "lh": 55, "deny": 14, "gpm": 646, "kda": "4.2/4.5/9.6"
            },
        },
        "benchmarks": {
            "gpm": 682,
            "xpm": 780,
            "lh": 58,
            "deny": 15,
            "deaths": 4.1,
            "h_dmg": 24000,
            "t_dmg": 1900,
            "stacks": 5.2,
            "utility": 10.5,
            "apm": 265,
            "kda": 5.2,
        },
    },

    "SUPPORT": {
        "players": {
            "not me": {
                "wr": 64, "lh": 42, "deny": 18, "gpm": 499, "kda": "3.8/5.2/15.4"
            },
            "9Class": {
                "wr": 61, "lh": 45, "deny": 20, "gpm": 524, "kda": "4.1/4.8/13.9"
            },
            "Saksa": {
                "wr": 58, "lh": 38, "deny": 17, "gpm": 472, "kda": "3.5/5.6/12.8"
            },
        },
        "benchmarks": {
            "gpm": 498,
            "xpm": 620,
            "lh": 42,
            "deny": 18,
            "deaths": 5.2,
            "h_dmg": 18500,
            "t_dmg": 1200,
            "stacks": 2.8,
            "utility": 11.5,
            "apm": 340,
            "kda": 4.1,
        },
    },
}

# =========================================================
# IMP WEIGHTS
# =========================================================

IMP_WEIGHTS: dict[RoleName, Weights] = {
    "CARRY": {"gpm": 0.4, "kda": 0.3, "utility": 0.1, "apm": 0.2},
    "SUPPORT": {"gpm": 0.1, "kda": 0.3, "utility": 0.4, "apm": 0.2},
    "MID": {"gpm": 0.35, "kda": 0.35, "utility": 0.15, "apm": 0.15},
    "OFFLANE": {"gpm": 0.3, "kda": 0.3, "utility": 0.2, "apm": 0.2}
}

# =========================================================
# ROLE DETECTION
# =========================================================

# Priority: 1) Hero role dominance (>60% games on one role), 2) Stats (GPM, XPM, lane, KDA)

# =========================================================
# UTILITY
# =========================================================

def _calculate_utility(
    role: str,
    stuns: float = 0,
    heals: float = 0,
    stacks: int = 0,
    wards: int = 0,
    observer_uses: int = 0,
    sentry_uses: int = 0,
    hero_damage: float = 0,
    tower_damage: float = 0,
) -> float:

    if role == "SUPPORT":
        return round(
            (stuns * 0.3) +
            (heals / 1000) +
            (stacks * 1.5) +
            ((observer_uses + sentry_uses) * 0.5),
            2
        )

    if role in ("CARRY", "MID"):
        return round(
            (stuns * 0.4) +
            (hero_damage / 1000) +
            (tower_damage / 500) +
            (stacks * 0.8),
            2
        )

    if role == "OFFLANE":
        return round(
            (stuns * 0.5) +
            (hero_damage / 1000) +
            (tower_damage / 500) +
            (stacks * 1.2) +
            (wards * 0.3),
            2
        )

    return round(
        (stuns * 0.3) +
        (heals / 1000) +
        (stacks * 1.5) +
        (wards * 0.5),
        2
    )

# =========================================================
# IMP
# =========================================================

def _calculate_imp(
    gpm: float,
    kda: float,
    utility: float,
    apm: float,
    role: str,
    win: bool = True,
    duration: float = 600,
) -> float | None:

    if role not in PRO_DB:
        role = "CARRY"

    pro = PRO_DB[role]["benchmarks"]
    weights = IMP_WEIGHTS[role]

    def _safe_ratio(value: float, bench: float | None) -> float:
        if bench is None or bench <= 0:
            return 0.0
        return value / bench

    # IMP считается только по метрикам, для которых есть verified
    # benchmark (gpm/kda/utility/apm). Если benchmark отсутствует
    # (None), метрика исключается из формулы — её вес не подменяется
    # нулём, иначе получится ложный IMP=0.
    # Если ВСЕ метрики без benchmark — IMP не определён (None).
    available_keys = _imp_available_keys(role)
    if not available_keys:
        return None

    ratios = {
        "gpm": _safe_ratio(gpm, pro.get("gpm")),
        "kda": _safe_ratio(kda, pro.get("kda")),
        "utility": _safe_ratio(utility, pro.get("utility")),
        "apm": _safe_ratio(apm, pro.get("apm")),
    }
    used_weight_sum = sum(weights[k] for k in available_keys)
    if used_weight_sum <= 0:
        return None

    imp = sum(ratios[k] * weights[k] for k in available_keys) / used_weight_sum

    imp = round(imp, 2)

    if not win:
        imp *= 0.92

    return imp


def _imp_available_keys(role: str) -> list[str]:
    """Список метрик (gpm/kda/utility/apm), для которых есть verified benchmark."""
    if role not in PRO_DB:
        role = "CARRY"
    pro = PRO_DB[role]["benchmarks"]
    keys: list[str] = []
    for k in ("gpm", "kda", "utility", "apm"):
        v = pro.get(k)
        if v is not None and v > 0:
            keys.append(k)
    return keys

# =========================================================
# HERO DATA
# =========================================================

async def _load_heroes() -> dict[int, str]:

    global _HERO_NAME_CACHE

    if _HERO_NAME_CACHE:
        return _HERO_NAME_CACHE

    url = f"{OPENDOTA_API_URL}/heroes"

    heroes = await _api_get_async(url, timeout=10)

    if not heroes:
        return {}

    for h in heroes:
        hero_id = h["id"]
        internal = h["name"].replace("npc_dota_hero_", "")
        _HERO_NAME_CACHE[hero_id] = internal

    return _HERO_NAME_CACHE

# =========================================================
# HERO ICON
# =========================================================

# Mapping from OpenDota internal names to file names
# _load_heroes() returns names like "anti_mage", "necrophos" etc (after removing npc_dota_hero_ prefix)
HERO_NAME_MAP: dict[str, str] = {
    "anti_mage": "antimage",
    "necrophos": "necrophos",
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
    "leoric": "leoric",
    "slardar": "slardar",
    "phantom_assassin": "phantom_assassin",
    "phantom_lancer": "phantom_lancer",
    "faceless_void": "faceless_void",
    "death_prophet": "death_prophet",
    "sven": "sven",
    "luna": "luna",
    "dragon_knight": "dragon_knight",
    "vengeful_spirit": "vengeful_spirit",
    "warlock": "warlock",
    "shadow_demon": "shadow_demon",
    "zeus": "zeus",
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
    "shredder": "shredder",
    "tinker": "tinker",
    "tiny": "tiny",
    "treant": "treant",
    "undying": "undying",
    "venomancer": "venomancer",
    "visage": "visage",
    "weaver": "weaver",
}

def _normalize_hero_file_name(internal_name: str) -> str:
    """Convert OpenDota internal name to file name"""
    # Remove npc_dota_hero_ prefix if present
    name = internal_name.replace("npc_dota_hero_", "")

    # Check mapping first
    if name in HERO_NAME_MAP:
        return HERO_NAME_MAP[name]

    # Handle specific name transformations
    # doom_bringer -> doom_bringer (same, but check for doom)
    if name == "doom_bringer":
        return "doom_bringer"
    if name == "doom":
        return "doom_bringer"

    # Return as-is for most heroes
    return name


async def _get_hero_icon(hero_id: int) -> Image.Image | None:
    # NOTE: для графика профиля используются маленькие иконки из hero_cache/icons/
    # (скаршленные из CDN icons/*.png). Не путай с assets/heroes_webp/ — это большие
    # иконки для меты героев.
    # Check unified cache first
    cached = image_cache.get(str(hero_id))
    if cached is not None:
        if isinstance(cached, bytes):
            try:
                return Image.open(io.BytesIO(cached)).convert("RGBA")
            except Exception:
                pass
        else:
            return cached

    heroes = await _load_heroes()
    hero_name = heroes.get(hero_id)
    if not hero_name:
        return None

    file_name = _normalize_hero_file_name(hero_name)
    cache_file = Path(__file__).resolve().parent / "hero_cache" / "icons" / f"{file_name}.png"

    if cache_file.exists():
        try:
            icon = Image.open(cache_file).convert("RGBA")
            image_cache.set(str(hero_id), icon)
            return icon
        except Exception:
            pass

    return None

def _normalize_hero_name(internal_name: str) -> str:
    """Convert internal hero name (anti_mage) to display name (Anti-Mage)"""
    return get_display_name(internal_name)


async def _detect_role_from_hero_counts(matches: list[dict[str, Any]]) -> str:
    heroes = await _load_heroes()

    # Mapping: position 1-5 -> role
    POS_TO_ROLE = {
        1: "CARRY",
        2: "MID",
        3: "OFFLANE",
        4: "SUPPORT",
        5: "SUPPORT"
    }

    role_counts = {
        "CARRY": 0,
        "MID": 0,
        "OFFLANE": 0,
        "SUPPORT": 0
    }

    total_matches = len(matches)

    for m in matches:
        hero_id = m.get("hero_id", 0)
        internal_name = heroes.get(hero_id, "")

        # Normalize hero name for lookup in hero_positions
        hero_name = _normalize_hero_name(internal_name)

        # Look up position from local hero_positions database
        position = hero_positions.get(hero_name, 0)

        # Map position to role
        if position in POS_TO_ROLE:
            role = POS_TO_ROLE[position]
            role_counts[role] += 1

    if total_matches == 0:
        return None

    # Find dominant role (threshold: at least 2 matches or 50% for small samples)
    dominant_role = max(role_counts, key=role_counts.get)
    dominant_count = role_counts[dominant_role]

    threshold = max(2, int(total_matches * 0.5))
    if dominant_count >= threshold:
        logger.info(f"ROLE BY HERO COUNT: {dominant_role} ({dominant_count}/{total_matches})")
        return dominant_role

    logger.info(f"ROLE BY HERO COUNT: no dominance ({role_counts})")
    return None


async def detect_role_from_history(matches: list[dict[str, Any]]) -> str:
    """Определить роль игрока (CARRY/MID/OFFLANE/SUPPORT) по героям в истории матчей."""


    """
    Определяет наиболее вероятную роль игрока на основе его недавних матчей.
    """
    role = await _detect_role_from_hero_counts(matches)
    if role:
        return role

    # Fallback: determine role by stats (GPM, KDA)
    total_gpm = 0
    total_lh = 0
    for m in matches[:10]:
        duration = m.get("duration", 0)
        gold = m.get("gold", 0)
        gold_spent = m.get("gold_spent", 0)
        if duration > 0:
            gpm_val = (gold + gold_spent) * 60 / duration
        else:
            gpm_val = 0
        total_gpm += gpm_val
        total_lh += m.get("last_hits", 0)
    if total_gpm == 0 and total_lh > 0:
        total_gpm = total_lh * 60
    total_kills = sum(m.get("kills", 0) for m in matches[:10])
    total_deaths = sum(m.get("deaths", 0) for m in matches[:10])
    total_assists = sum(m.get("assists", 0) for m in matches[:10])
    avg_gpm = total_gpm / max(len(matches[:10]), 1)
    avg_kda = (total_kills + total_assists) / max(total_deaths, 1)

    # High GPM + KDA = CARRY/MID, low = SUPPORT
    if avg_gpm >= 500 and avg_kda >= 3.0:
        return "CARRY"
    elif avg_gpm >= 350 and avg_kda >= 2.5:
        return "MID"
    elif avg_gpm >= 200 and avg_kda >= 1.5:
        return "SUPPORT"

    return None


def calculate_player_stats(matches: list[dict[str, Any]]) -> dict[str, Any]:
    """Посчитать агрегированную статистику игрока (KDA, импакт, винрейт) по списку матчей."""


    """
    Рассчитывает средние показатели игрока по последним матчам.
    """

    if not matches:
        return {"wr": 50.0, "gpm": 400, "xpm": 500, "lh": 0, "deny": 0, "stacks": 0, "deaths": 5.0, "h_dmg": 10.0, "t_dmg": 2.0, "util": 8.0, "apm": 250, "kda": "3/4/8"}
    n = len(matches)

    # Collect raw data
    raw_lh = [m.get("last_hits", 0) for m in matches]
    raw_lh_per_10min = [m.get("last_hits", 0) / max(m.get("duration", 600) / 600, 0.33) for m in matches]  # normalize to 10min
    raw_kills = [m.get("kills", 0) for m in matches]
    raw_deaths = [m.get("deaths", 0) for m in matches]
    raw_assists = [m.get("assists", 0) for m in matches]
    raw_h_dmg = [m.get("hero_damage", 0) for m in matches]
    raw_t_dmg = [m.get("tower_damage", 0) for m in matches]
    raw_apm = [m.get("actions_per_min", 0) for m in matches]
    raw_stuns = [m.get("stuns", 0) for m in matches]
    raw_heals = [m.get("hero_healing", 0) for m in matches]
    raw_wins = [1 if m.get("win", False) else 0 for m in matches]
    raw_denies = [m.get("denies", 0) for m in matches]
    raw_stacks = [m.get("creeps_stacked", 0) for m in matches]
    raw_xpm = [m.get("xp_per_min", 0) for m in matches]

    # Compute GPM per match from gold and gold_spent (more reliable than gold_per_min)
    raw_gpm = []
    for m in matches:
        duration = m.get("duration", 0)
        gold = m.get("gold", 0)
        gold_spent = m.get("gold_spent", 0)
        if duration > 0 and (gold + gold_spent) > 0:
            total_gold = gold + gold_spent
            gpm_val = total_gold * 60 / duration
        else:
            gpm_val = m.get("gold_per_min", 0)
        raw_gpm.append(gpm_val)

    total_gpm = sum(raw_gpm)
    # Fallbacks if GPM data is zero (e.g., missing gold info)
    total_lh = sum(raw_lh)
    if total_gpm == 0 and total_lh > 0:
        total_gpm = total_lh * 60
    elif total_gpm == 0:
        avg_kills = sum(raw_kills) / max(n, 1)
        avg_deaths = max(sum(raw_deaths) / max(n, 1), 1)
        avg_assists = sum(raw_assists) / max(n, 1)
        avg_kda = (avg_kills + avg_assists) / avg_deaths
        total_gpm = avg_kda * 150

    avg_gpm = total_gpm / n
    avg_lh_10min = sum(raw_lh_per_10min) / n

    total_deaths = sum(raw_deaths)
    avg_deaths = total_deaths / n

    total_kills = sum(raw_kills)
    avg_kills = total_kills / n

    total_assists = sum(raw_assists)
    avg_assists = total_assists / n

    total_denies = sum(raw_denies)
    avg_denies = total_denies / n

    total_stacks = sum(raw_stacks)
    avg_stacks = total_stacks / n

    total_xpm = sum(raw_xpm)
    avg_xpm = total_xpm / n



    # Hero DMG fallback: estimate from kills (~200 damage per kill avg)
    total_h_dmg = sum(raw_h_dmg)
    if total_h_dmg == 0:
        total_h_dmg = total_kills * 200
    avg_h_dmg = total_h_dmg / n / 1000

    # Tower DMG fallback: estimate from kills
    total_t_dmg = sum(raw_t_dmg)
    if total_t_dmg == 0:
        total_t_dmg = total_kills * 50
    avg_t_dmg = total_t_dmg / n / 1000

    # APM fallback
    total_apm = sum(raw_apm)
    if total_apm == 0:
        total_apm = n * 250
    avg_apm = total_apm / n

    # Utility from stuns/heals/stacks
    total_stuns = sum(raw_stuns)
    total_heals = sum(raw_heals)
    total_utility = (total_stuns * 0.3 + total_heals / 1000) / n

    total_wins = sum(raw_wins)
    wr = (total_wins / n) * 100

    real_kda = (avg_kills + avg_assists) / max(avg_deaths, 0.1)

    return {
        "wr": round(wr, 1),
        "gpm": round(avg_gpm, 1),
        "xpm": round(avg_xpm, 1),
        "lh": round(avg_lh_10min, 1),
        "deny": round(avg_denies, 1),
        "stacks": round(avg_stacks, 1),
        "deaths": round(avg_deaths, 1),
        "h_dmg": round(avg_h_dmg, 1),
        "t_dmg": round(avg_t_dmg, 1),
        "util": round(total_utility, 1),
        "apm": round(avg_apm, 0),
        "kda_number": round(real_kda, 2),
        "kda": f"{round(avg_kills,1)}/{round(avg_deaths,1)}/{round(avg_assists,1)}"
    }


# =========================================================
# MATCH DETAILS
# =========================================================



# =========================================================
# MATCHES
# =========================================================

async def fetch_match_details(matches: list[dict[str, Any]], steam_id: str) -> list[dict[str, Any]]:
    """Дополнить матчи деталями (герои, импакт, длительность) через OpenDota."""


    """
    Загружает детальную информацию по каждому матчу (GPM, XPM, actions и т.д.) параллельно.
    """

    """Fetch full match details for matches that have minimal data."""
    account_id = steam64_to_account_id(steam_id)
    semaphore = asyncio.Semaphore(5)  # Limit concurrent requests to OpenDota

    async def fetch_one(m):
        # If match already has all needed data, keep it
        if m.get("gold_per_min", 0) > 0 and m.get("last_hits", 0) > 0:
            return m
        match_id = m.get("match_id")
        if not match_id:
            return m

        try:
            async with semaphore:
                match_url = f"{OPENDOTA_API_URL}/matches/{match_id}"
                match_data = await _api_get_async(match_url, timeout=20)
            player_stats = {}
            if match_data and "players" in match_data:
                for p in match_data["players"]:
                    if p.get("account_id") == int(account_id):
                        player_stats = p
                        break

            # Enrich the match data
            m["kills"] = player_stats.get("kills", m.get("kills", 0))
            m["deaths"] = player_stats.get("deaths", m.get("deaths", 0))
            m["assists"] = player_stats.get("assists", m.get("assists", 0))
            m["gold_per_min"] = player_stats.get("gold_per_min", 0)
            m["xp_per_min"] = player_stats.get("xp_per_min", 0)
            m["last_hits"] = player_stats.get("last_hits", 0)
            m["gold"] = player_stats.get("gold", 0)
            m["gold_spent"] = player_stats.get("gold_spent", 0)
            m["hero_damage"] = player_stats.get("hero_damage", 0)
            m["tower_damage"] = player_stats.get("tower_damage", 0)
            m["denies"] = player_stats.get("denies", 0)
            m["actions_per_min"] = player_stats.get("actions_per_min", 0)
            m["stuns"] = player_stats.get("stuns", 0.0) if isinstance(player_stats.get("stuns"), (int, float)) else 0
            m["hero_healing"] = player_stats.get("hero_healing", 0)
            m["creeps_stacked"] = player_stats.get("creeps_stacked", 0)
            m["observer_uses"] = player_stats.get("observer_uses", 0)
            m["sentry_uses"] = player_stats.get("sentry_uses", 0)
        except Exception as e:
            logger.debug(f"Failed to fetch match {match_id}: {e}")
        return m

    # Parallel fetch with semaphore
    results = await asyncio.gather(*[fetch_one(m) for m in matches], return_exceptions=True)
    enriched = []
    for r in results:
        if isinstance(r, dict):
            enriched.append(r)
        elif isinstance(r, Exception):
            logger.debug(f"fetch_match_details exception: {r}")

    return enriched


async def get_last_matches(telegram_id: int, limit: int = 10) -> list[dict[str, Any]]:
    """Получить последние матчи пользователя (через Steam→OpenDota), limit по умолчанию 10."""


    """
    Загружает последние матчи игрока через OpenDota API.
    """

    """Get the last N matches for a user (for chart/analytics)."""

    user = get_user(telegram_id)

    if not user or not user.get("steam_id"):
        return []

    account_id = steam64_to_account_id(
        user["steam_id"]
    )

    url = (
        f"{OPENDOTA_API_URL}"
        f"/players/{account_id}/matches"
    )

    matches = await _api_get_async(
        url,
        params={"limit": limit},
        timeout=15
    )

    if not matches:
        return []

    logger.info(f"get_last_matches: got {len(matches)} matches for account {account_id}")

    result = []
    for m in matches[:limit]:
        match_id = m.get("match_id")
        hero_id = m.get("hero_id", 0)
        duration = m.get("duration", 0)
        player_slot = m.get("player_slot", 0)

        kills = m.get("kills", 0)
        deaths = m.get("deaths", 0)
        assists = m.get("assists", 0)
        radiant_win = m.get("radiant_win", False)

        is_radiant = player_slot < 128 if player_slot else True
        is_win = radiant_win if is_radiant else not radiant_win

        result.append({
            "hero_id": hero_id,
            "kills": kills,
            "deaths": deaths,
            "assists": assists,
            "gold_per_min": 0,
            "duration": duration,
            "gold": 0,
            "gold_spent": 0,
            "xp_per_min": 0,
            "last_hits": 0,
            "hero_damage": 0,
            "tower_damage": 0,
            "lane_role": 0,
            "start_time": m.get("start_time", 0),
            "win": is_win,
            "denies": 0,
            "actions_per_min": 0,
            "stuns": 0.0,
            "hero_healing": 0,
            "creeps_stacked": 0,
            "observer_uses": 0,
            "sentry_uses": 0,
            "match_id": match_id
        })

    return result


# =========================================================
# REPORT TEXT
# =========================================================

def _generate_report_text(role: str, user_stats: dict[str, Any]) -> dict[str, Any]:
    """Генерация текстовых таблиц в стиле референса"""
    db = PRO_DB.get(role, PRO_DB["CARRY"])

    # Table 1: PRO comparison - use HTML pre tag instead of markdown code block
    t1 = "<pre>\n"
    t1 += f"{'PLAYER':<9} {'WR':>3} {'GPM':>4} {'KDA':<12}\n"
    t1 += "-------------------------------\n"
    for name, s in db["players"].items():
        wr = f"{int(round(s['wr']))}%" if s.get('wr') is not None else "—"
        gpm = f"{int(round(s['gpm'])):>4}" if s.get('gpm') is not None else "  — "
        kda = s.get('kda', '—')
        if kda is None:
            kda = "—"
        display_name = name if len(name) <= 9 else name[:8] + "…"
        t1 += (
            f"{display_name:<9} "
            f"{wr:>3} "
            f"{gpm:>4} "
            f"{kda:<12}\n"
        )
    t1 += "-------------------------------\n"
    gpm_val = int(user_stats['gpm']) if user_stats.get('gpm', 0) > 0 else 0
    wr_val = f"{int(round(user_stats['wr']))}%" if user_stats.get('wr') is not None else "—"
    you_line = (
        f"{'YOU':<9} "
        f"{wr_val:>3} "
        f"{gpm_val:>4} "
        f"{user_stats['kda']:<12}\n"
    )
    t1 += you_line
    t1 += "</pre>"

    # Таблица 2: Детальное сравнение
    t2 = "<pre>\n"
    t2 += f"{'Metric':<10} {'You':>6} {'PRO':>6}\n"
    t2 += "----------------------------\n"
    bench = db["benchmarks"]
    metrics = [
        ("LH@10", user_stats.get('lh', 0), bench.get('lh')),
        ("Denies@10", user_stats.get('deny', 0), bench.get('deny')),
        ("GPM", user_stats.get('gpm', 0), bench.get('gpm')),
        ("XPM", user_stats.get('xpm', 0), bench.get('xpm')),
        ("Deaths", user_stats.get('deaths', 0), bench.get('deaths')),
        ("H DMG", user_stats.get('h_dmg', 0), bench.get('h_dmg')),
        ("T DMG", user_stats.get('t_dmg', 0), bench.get('t_dmg')),
        ("Stacks", user_stats.get('stacks', 0), bench.get('stacks')),
        ("Util", user_stats.get('util', 0), bench.get('utility')),
        ("APM", user_stats.get('apm', 0), bench.get('apm'))
    ]
    for label, u, p in metrics:
        u_str = f"{u:.0f}" if isinstance(u, (int, float)) and u >= 100 else f"{u:.1f}" if isinstance(u, (int, float)) else "—"
        p_str = f"{p:.0f}" if isinstance(p, (int, float)) and p >= 100 else f"{p:.1f}" if isinstance(p, (int, float)) else "—"
        if not isinstance(p, (int, float)):
            arrow = ""
        else:
            diff = u - p if isinstance(u, (int, float)) else 0
            is_bad = diff > 0 if "Deaths" in label else diff < 0
            arrow = "↓" if is_bad else "↑"
        t2 += f"{label:<10} {u_str:>6} {p_str:>6} {arrow}\n"
    t2 += "</pre>"

    header = f"<b>📊 ANALYTICS ({role})</b>"
    text = f"{header}\n\n{t1}"

    header_detailed = "<b>📈 Подробное сравнение • Детали позиций</b>"
    text_detailed = f"{header_detailed}\n\n{t2}"

    return {"pro": text, "detailed": text_detailed}


def get_analytics_pages(role: str, stats: dict[str, Any]) -> list[dict[str, Any]]:
    """Построить страницы аналитики (сравнение с про, детальное) для инлайн-клавиатуры /analyze."""


    """
    Генерирует страницы (таблицы) сравнения статистики игрока с про-игроками
    для выбранной роли.
    """

    """Generate a list of analytics pages for pagination.

    Each page is a dict with 'title' and 'text' keys.
    Page 0: PRO comparison
    Page 1: Detailed comparison
    """
    tables = _generate_report_text(role, stats)
    pro_text = tables["pro"]
    detailed_text = tables["detailed"]

    return [
        {"title": "🆚Сравнение с Pro", "text": pro_text},
        {"title": "📊 Подробное сравнение", "text": detailed_text},
    ]


# =========================================================
# MAIN ANALYTICS - CHART ONLY
# =========================================================

async def generate_chart_only(telegram_id: int) -> dict[str, Any] | None:
    """
    Генерирует только чарт аналитики (используется для кэшированных данных).

    Используется когда у пользователя уже есть сохранённый analytics_cache.
    """

    """Generate only the chart and game history - no text pages."""

    from datetime import datetime

    from database import get_user

    now = datetime.now(UTC)
    user = await asyncio.to_thread(get_user, telegram_id)
    if user and user.get('analytics_cache') and user.get('analytics_updated_at'):
        updated_at = user['analytics_updated_at']
        if isinstance(updated_at, str):
            updated_at = datetime.fromisoformat(updated_at.replace('Z', '+00:00'))
        if (now - updated_at).total_seconds() < 3600:
            cached = json.loads(user['analytics_cache'])
            # Run chart generation (async function) directly
            chart = await _create_visual_chart(cached.get("history", []))
            return {"image": chart, "history": cached.get("history", []), "matches": cached.get("matches", []), "role": cached.get("role", "CARRY")}

    # Check if user has Steam account BEFORE fetching matches
    if not user or not user.get("steam_id"):
        return {"error": "no_steam_linked", "message": "🔗 Привяжите Аккаунт, чтобы увидеть аналитику"}

    # If OpenDota is currently rate-limited / 5xx-ing, сразу вернём ошибку,
    # чтобы не дёргать API и не показывать пустой график.
    if is_opendota_rate_limited():
        logger.warning("generate_chart_only: OpenDota unavailable, returning error")
        return {
            "error": "opendota_rate_limit",
            "message": get_opendota_rate_limit_message(),
        }

    matches = await get_last_matches(telegram_id)

    # Доп. защита: если API вернул 0 матчей из-за CB/rate-limit, а кэша нет —
    # не показываем пустой график, а сообщаем о недоступности.
    if not matches and not (user.get("analytics_cache")) and is_opendota_rate_limited():
        logger.warning("generate_chart_only: 0 matches + API unavailable, returning error")
        return {
            "error": "opendota_rate_limit",
            "message": get_opendota_rate_limit_message(),
        }

    if len(matches) < 5:
        from database import get_user
        user = await asyncio.to_thread(get_user, telegram_id)
        if user and user.get('analytics_cache'):
            cached = json.loads(user['analytics_cache'])
            if cached.get('matches') and len(cached.get('matches', [])) >= 3:
                logger.info(f"generate_chart_only: using cached data for user {telegram_id}")
                chart = await _create_visual_chart(cached.get("history", []))
                return {"image": chart, "history": cached.get("history", []), "matches": cached.get("matches", []), "role": cached.get("role", "CARRY"), "api_fallback": True}
        return {"error": "opendota_rate_limit", "message": "⚠️ OpenDota API временно недоступен. Вернётся, когда кто-то купит варды 👁️"}

    # Matches are already sorted newest-first from API, keep this order

    # Detect role from hero picks
    role = await _detect_role_from_hero_counts(matches)
    if not role:
        from database import get_user
        user = await asyncio.to_thread(get_user, telegram_id)
        if user and user.get('analytics_cache'):
            cached = json.loads(user['analytics_cache'])
            cached_role = cached.get('role')
            if cached_role:
                logger.info(f"generate_chart_only: using cached role {cached_role}")
                role = cached_role
            else:
                role = "CARRY"
        else:
            role = "CARRY"
        logger.info(f"generate_chart_only: using fallback role {role}")

    # Calculate only what's needed for chart - minimal data
    game_history = []
    for m in matches[:10]:
        kills = m.get("kills", 0)
        deaths = m.get("deaths", 0)
        assists = m.get("assists", 0)
        kda = (kills + assists) / max(deaths, 1)

        # Estimate GPM from last_hits (basic data from match list, no API)
        duration = m.get("duration", 600)
        last_hits = m.get("last_hits", 0)
        gpm = last_hits * 60 / max(duration / 60, 1) if last_hits > 0 else 300

        # Estimate utility from stacks and denies (minimal data)
        stacks = m.get("creeps_stacked", 0)
        denies = m.get("denies", 0)
        utility = _calculate_utility(
            role,
            stacks=stacks,
            wards=denies,
        )

        # Estimate APM (typical values by role)
        apm = 250

        win = m.get("win", False)
        imp = _calculate_imp(gpm, kda, utility, apm, role, win=win, duration=duration)
        game_history.append({
            "imp": round(imp, 2) if imp is not None else None,
            "hero_id": m.get("hero_id", 0),
            "win": win,
            "imp_unavailable": imp is None,
        })

    chart = await _create_visual_chart(game_history)
    imp_none_count = sum(1 for g in game_history if g.get("imp") is None)
    logger.info(
        "generate_chart_only: uid=%s role=%s matches=%s history=%s imp_none=%s chart_size=%s",
        telegram_id,
        role,
        len(matches),
        len(game_history),
        imp_none_count,
        len(chart) if chart else 0,
    )
    return {"image": chart, "history": game_history, "matches": matches, "role": role}


async def generate_weekly_analytics(telegram_id: int) -> dict[str, Any] | None:
    """
    Основная точка входа для генерации еженедельной аналитики игрока.

    Загружает последние матчи, определяет роль, рассчитывает статистику,
    сравнивает с бенчмарками про-игроков и возвращает данные для отчёта
    (включая изображение чарта если возможно).

    Returns:
        dict с ключами 'image', 'history', 'matches', 'role' или None если данных мало.
        При недоступности OpenDota возвращает {"error": "opendota_rate_limit", ...}.
    """
    # Check if user has Steam account BEFORE fetching matches
    user = await asyncio.to_thread(get_user, telegram_id)
    if not user or not user.get("steam_id"):
        return {"error": "no_steam_linked", "message": "🔗 Привяжите Аккаунт, чтобы увидеть аналитику"}

    # If OpenDota is currently rate-limited / 5xx-ing, не нужно дёргать API и показывать
    # пользователю пустой график — сразу вернём понятную ошибку.
    if is_opendota_rate_limited():
        logger.warning("generate_weekly_analytics: OpenDota unavailable, returning error")
        return {
            "error": "opendota_rate_limit",
            "message": get_opendota_rate_limit_message(),
        }

    matches = await get_last_matches(telegram_id)

    # Доп. защита: если API вернул 0 матчей из-за того, что CB открылся
    # уже после первой проверки (5xx-цикл), а кэша аналитики нет — не
    # показываем пустой график, а сообщаем о недоступности.
    if not matches and not (user.get("analytics_cache")) and is_opendota_rate_limited():
        logger.warning("generate_weekly_analytics: 0 matches + API unavailable, returning error")
        return {
            "error": "opendota_rate_limit",
            "message": get_opendota_rate_limit_message(),
        }

    if len(matches) < 5:
        user = await asyncio.to_thread(get_user, telegram_id)
        if user and user.get('analytics_cache'):
            cached = json.loads(user['analytics_cache'])
            if cached.get('matches') and len(cached.get('matches', [])) >= 3:
                logger.info(f"generate_weekly_analytics: using cached data for user {telegram_id}")
                return {
                    "image": cached.get("image"),
                    "history": cached.get("history", []),
                    "matches": cached.get("matches", []),
                    "pro_text": cached.get("pro_text", ""),
                    "detailed_text": cached.get("detailed_text", ""),
                    "role": cached.get("role", "CARRY"),
                    "stats": cached.get("stats"),
                    "api_fallback": True
                }

    logger.info(f"generate_weekly_analytics: {len(matches)} matches available")

    # Enrich matches with detailed stats (GPM, XPM, last_hits, etc.)
    matches = await fetch_match_details(matches, user["steam_id"])
    if all(m.get("gold_per_min", 0) == 0 for m in matches) and len(matches) > 0:
        logger.warning("API returned no stats data - falling back to cached or error")
        if user.get('analytics_cache'):
            cached = json.loads(user['analytics_cache'])
            if cached.get('matches'):
                matches = cached.get('matches')
            if cached.get('pro_text') and cached.get('detailed_text'):
                return {
                    "image": cached.get("image"),
                    "history": cached.get("history", []),
                    "matches": matches,
                    "pro_text": cached.get("pro_text", ""),
                    "detailed_text": cached.get("detailed_text", ""),
                    "role": cached.get("role", "CARRY"),
                    "stats": cached.get("stats"),
                    "api_fallback": True,
                    "error": "opendota_rate_limit",
                    "message": "⚠️ OpenDota API временно недоступен. Вернётся, когда кто-то купит варды 👁️"
                }
    logger.info(f"generate_weekly_analytics: after fetch_match_details, gpm={sum(m.get('gold_per_min', 0) for m in matches)}")

    # Matches are already sorted newest-first from API, keep this order
    # Role detection using OpenDota hero roles + match stats
    role = await detect_role_from_history(matches)

    # Averages
    total_gpm = 0
    total_kills = 0
    total_deaths = 0
    total_assists = 0
    total_lh = 0
    total_lh_10min = 0
    total_apm = 0
    total_denies = 0
    total_stacks = 0
    total_xpm = 0
    total_h_dmg = 0
    total_t_dmg = 0
    total_utility = 0
    total_wins = 0

    game_history = []

    for m in matches:

        gpm = m.get("gold_per_min", 0)
        xpm = m.get("xp_per_min", 0)
        last_hits = m.get("last_hits", 0)
        denies = m.get("denies", 0)
        hero_damage = m.get("hero_damage", 0)
        tower_damage = m.get("tower_damage", 0)
        creeps_stacked = m.get("creeps_stacked", 0)
        duration = m.get("duration", 600)
        win = m.get("win", False)

        if gpm == 0 and last_hits > 0:
            gpm = last_hits * 60 / max(duration / 60, 1) if duration > 0 else 300
        if xpm == 0:
            xpm = gpm * 0.8

        kills = m.get("kills", 0)
        deaths = m.get("deaths", 0)
        assists = m.get("assists", 0)

        kda = (kills + assists) / max(deaths, 1)

        utility = _calculate_utility(
            role,
            stuns=m.get("stuns", 0),
            heals=m.get("hero_healing", 0),
            stacks=creeps_stacked,
            wards=m.get("observer_uses", 0) + m.get("sentry_uses", 0),
            observer_uses=m.get("observer_uses", 0),
            sentry_uses=m.get("sentry_uses", 0),
            hero_damage=hero_damage,
            tower_damage=tower_damage,
        )

        apm = m.get("actions_per_min", 0)
        if apm == 0:
            apm = 250

        imp = _calculate_imp(
            gpm,
            kda,
            utility,
            apm,
            role,
            win=win,
            duration=duration,
        )

        game_history.append({
            "imp": imp,
            "hero_id": m.get("hero_id", 0),
            "win": win,
            "imp_unavailable": imp is None,
        })

        total_gpm += gpm
        total_kills += kills
        total_deaths += deaths
        total_assists += assists
        total_lh += m.get("last_hits", 0)
        # LH@10: normalize last_hits to 10 minutes (duration in seconds)
        duration = m.get("duration", 600)
        lh_per_10min = m.get("last_hits", 0) / max(duration / 600, 0.33) if duration > 0 else 0
        total_lh_10min += lh_per_10min
        total_apm += apm
        total_denies += m.get("denies", 0)
        total_stacks += m.get("creeps_stacked", 0)
        total_xpm += m.get("xp_per_min", 0)

        total_utility += utility

        # Fallback for hero_damage from kills
        h_dmg = m.get("hero_damage", 0)
        if h_dmg == 0:
            h_dmg = kills * 200  # ~200 damage per kill
        total_h_dmg += h_dmg

        # Fallback for tower_damage
        t_dmg = m.get("tower_damage", 0)
        if t_dmg == 0:
            t_dmg = kills * 50  # rough estimate
        total_t_dmg += t_dmg

        if m.get("win", False):
            total_wins += 1

    logger.info(f"User {telegram_id} totals: gpm={total_gpm}, lh={total_lh}, denies={total_denies}, kills={total_kills}, deaths={total_deaths}, assists={total_assists}, wins={total_wins}, match_count={len(matches)}")

    match_count = len(matches)

    if match_count == 0:
        user_stats = {
            "wr": 0.0,
            "lh": 0.0,
            "deny": 0.0,
            "stacks": 0.0,
            "gpm": 0.0,
            "xpm": 0.0,
            "h_dmg": 0.0,
            "t_dmg": 0.0,
            "util": 0.0,
            "apm": 0.0,
            "deaths": 0.0,
            "kda_number": 0.0,
            "kda": "0.0/0.0/0.0"
        }
        tables = _generate_report_text(role, user_stats)
        chart_image = await _create_visual_chart(game_history)
        data = {
            "image": chart_image,
            "history": game_history,
            "pro_text": tables["pro"],
            "detailed_text": tables["detailed"],
        }
        data.update(user_stats)
        return data

    avg_gpm = total_gpm / match_count
    avg_lh = total_lh_10min / match_count
    avg_apm = total_apm / match_count
    avg_denies = total_denies / match_count
    avg_xpm = total_xpm / match_count
    avg_stacks = total_stacks / match_count
    avg_h_dmg = total_h_dmg / match_count / 1000
    avg_t_dmg = total_t_dmg / match_count / 1000
    avg_utility = total_utility / match_count
    avg_deaths = total_deaths / match_count
    avg_kills = total_kills / match_count
    avg_assists = total_assists / match_count

    wr = (total_wins / match_count) * 100

    real_kda = (avg_kills + avg_assists) / max(avg_deaths, 1)

    user_stats = {
        "wr": round(wr, 1),
        "lh": round(avg_lh, 1),
        "deny": round(avg_denies, 1),
        "stacks": round(avg_stacks, 1),
        "gpm": round(avg_gpm, 1),
        "xpm": round(avg_xpm, 1),
        "h_dmg": round(avg_h_dmg, 1),
        "t_dmg": round(avg_t_dmg, 1),
        "util": round(avg_utility, 1),
        "apm": round(avg_apm, 1),
        "deaths": round(avg_deaths, 1),
        "kda_number": round(real_kda, 2),
        "kda": f"{round(avg_kills,1)}/{round(avg_deaths,1)}/{round(avg_assists,1)}"
    }

    # Генерация таблиц
    tables = _generate_report_text(role, user_stats)
    pro_text = tables["pro"]
    detailed_text = tables["detailed"]

    # График
    chart_image = await _create_visual_chart(game_history)

    data = {
        "image": chart_image,
        "history": game_history,
        "pro_text": pro_text,
        "detailed_text": detailed_text,
        "role": role,
        "stats": user_stats
    }

    # Save to cache (without image)
    try:
        cache_dict = {
            "history": game_history,
            "matches": matches,
            "pro_text": pro_text,
            "detailed_text": detailed_text,
            "role": role,
            "stats": user_stats
        }
        cache_data = json.dumps(cache_dict)
        db = Database()
        db.execute_query(
            "UPDATE users SET analytics_cache = %s, analytics_updated_at = %s WHERE telegram_id = %s",
            (cache_data, datetime.now(UTC).isoformat(), telegram_id)
        )
        logger.info(f"Saved analytics cache for {telegram_id}")
    except Exception as e:
        logger.warning(f"Failed to save analytics cache for {telegram_id}: {e}")

    return data

# =========================================================
# CHART (matplotlib runs in thread pool via asyncio.to_thread)
# =========================================================

def _create_visual_chart_sync(history: list[dict], hero_icon_map: dict, bg: Image.Image) -> bytes | None:
    """Sync matplotlib chart generation - runs in thread pool. All matplotlib ops here."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        from pathlib import Path

        import matplotlib.pyplot as plt
        from matplotlib import font_manager, rcParams
        from matplotlib import patheffects as pe
        from matplotlib.offsetbox import AnnotationBbox, OffsetImage

        # Register and use local NotoSans font for Cyrillic support
        font_path = Path(__file__).resolve().parent / "assets" / "fonts" / "NotoSans-Regular.ttf"
        if font_path.exists():
            font_manager.fontManager.addfont(str(font_path))
            rcParams['font.family'] = 'Noto Sans'
        else:
            rcParams['font.family'] = 'DejaVu Sans'

        rcParams['path.simplify'] = False
        rcParams['lines.solid_capstyle'] = 'round'
        rcParams['lines.solid_joinstyle'] = 'round'
        rcParams['svg.image_inline'] = True

        import io

        import numpy as np
        from PIL import Image

    except ImportError:
        return None

    DPI = 72

    reversed_history = list(reversed(history))[:10]

    # Skip entries where IMP could not be calculated due to missing
    # TI 2026 benchmark — treating IMP=0 as a real result would mislead users.
    available = [g for g in reversed_history if not g.get("imp_unavailable")]

    raw_impacts = [
        min(round(g["imp"], 2), 2.0)
        for g in available
    ]

    wins = [g.get("win", True) for g in available]

    if not raw_impacts:
        logger.warning(
            "_create_visual_chart_sync: no available impacts, history=%s, all_unavailable=%s",
            len(history),
            all(g.get("imp_unavailable") for g in reversed_history),
        )
        return None

    x = np.arange(1, len(raw_impacts) + 1)

    avg = float(np.mean(raw_impacts))

    if avg >= 1.05:
        stroke_color = "#00cc55"
    elif avg >= 0.75:
        stroke_color = "#ccaa00"
    else:
        stroke_color = "#cc2f2f"

    fig = plt.figure(
        figsize=(WIDTH / DPI, HEIGHT / DPI),
        dpi=DPI
    )

    ax = plt.axes([0, 0, 1, 1])

    fig.patch.set_facecolor("#000000")

    ax.imshow(
        bg,
        extent=[0, 11, 0, 2],
        aspect='auto',
        interpolation='bilinear',
        alpha=1.0,
        zorder=0
    )

    ax.set_xlim(0, 11)
    ax.set_ylim(0, 2)

    ax.axhline(
        1.0,
        linestyle=(0, (6, 6)),
        color="#ffff00",
        linewidth=2.5,
        alpha=0.8,
        zorder=2
    )

    ax.text(
        len(raw_impacts) + 0.2,
        1.0,
        "1.00",
        fontsize=14,
        color="#ffff00",
        ha="left",
        va="center",
        fontweight="bold",
        zorder=3
    )

    ax.text(
        len(raw_impacts) + 0.15,
        1.10,
        "PRO",
        fontsize=14,
        color="#ffff00",
        alpha=0.9,
        weight="bold",
        va="center",
        zorder=3
    )

    if len(raw_impacts) >= 3:
        x = np.arange(1, len(raw_impacts) + 1)
        trend_x = np.linspace(1, len(raw_impacts), 100)
        trend_coef = np.polyfit(x, raw_impacts, 1)
        trend_y = np.clip(trend_coef[0] * trend_x + trend_coef[1], 0, 2)

        ax.plot(
            trend_x,
            trend_y,
            color="#ffffff",
            linewidth=3,
            linestyle="--",
            alpha=0.5,
            zorder=4
        )

    # Plot smooth curve through data points using spline interpolation
    if len(raw_impacts) >= 3:
        from scipy.interpolate import make_interp_spline
        smooth_x = np.linspace(1, len(raw_impacts), 300)
        spline_y = make_interp_spline(x, raw_impacts, k=3)(smooth_x)
        line = ax.plot(
            smooth_x,
            spline_y,
            color="#f4c430",
            linewidth=10,
            solid_capstyle='round',
            solid_joinstyle='round',
            antialiased=True,
            zorder=5
        )[0]
    else:
        line = ax.plot(
            x,
            raw_impacts,
            color="#f4c430",
            linewidth=10,
            solid_capstyle='round',
            solid_joinstyle='round',
            antialiased=True,
            zorder=5
        )[0]

    line.set_path_effects([
        pe.Stroke(
            linewidth=16,
            foreground=stroke_color,
            alpha=0.35
        ),
        pe.Normal()
    ])

    for idx, (xi, yi, win) in enumerate(zip(x, raw_impacts, wins)):
        border = "#00ff66" if win else "#ff3b3b"
        glow = "#00ff66" if win else "#ff3b3b"

        ax.scatter(
            xi,
            yi,
            s=200,
            color=border,
            edgecolors="#ffffff",
            linewidths=4,
            zorder=6,
            joinstyle='round'
        )

        ax.scatter(
            xi,
            yi,
            s=1500,
            color=glow,
            alpha=0.18,
            zorder=5
        )

        ax.text(
            xi,
            yi + 0.15,
            f"{yi:.2f}",
            fontsize=10,
            color=border,
            ha="center",
            va="bottom",
            fontweight="bold",
            zorder=7
        )

    for idx, g in enumerate(available):
        hero_id = g["hero_id"]
        hero_img = hero_icon_map.get(hero_id)

        if not hero_img:
            continue

        imp = raw_impacts[idx]
        win = g.get("win", True)
        border = "#00ff66" if win else "#ff3b3b"
        glow = "#00ff66" if win else "#ff3b3b"

        hero_img = hero_img.resize(
            (82, 82),
            Image.LANCZOS
        )

        imagebox = OffsetImage(
            hero_img,
            zoom=0.65
        )

        ab = AnnotationBbox(
            imagebox,
            (idx + 1, imp),
            frameon=True,
            bboxprops=dict(
                edgecolor=border,
                linewidth=8,
                boxstyle="circle,pad=0.15",
                facecolor="none",
                alpha=1.0,
                joinstyle="round"
            ),
            zorder=10
        )

        ax.add_artist(ab)

    ax.set_xlim(0, 11)
    ax.set_ylim(0, 2)

    ax.set_xticks(x)
    ax.set_xticklabels(
        [str(i) for i in x],
        fontsize=22,
        color="white",
        weight="bold"
    )

    ax.set_yticks([
        0,
        0.5,
        1.0,
        1.5,
        2.0
    ])

    ax.set_yticklabels(
        ["0", "0.5", "1.0", "1.5", "2.0"],
        fontsize=18,
        color="white"
    )

    ax.grid(
        axis="y",
        color="white",
        alpha=0.08,
        linewidth=1
    )

    for spine in ax.spines.values():
        spine.set_visible(False)

    buf = io.BytesIO()

    plt.savefig(
        buf,
        format="png",
        dpi=DPI,
        facecolor=fig.get_facecolor(),
        bbox_inches=None,
        pad_inches=0,
        pil_kwargs={'quality': 100}
    )

    plt.close('all')
    buf.seek(0)

    return buf.getvalue()


async def _create_visual_chart(history: list[dict]) -> bytes | None:
    """Non-blocking chart generation - prepares data then runs matplotlib in thread pool."""
    import aiohttp

    from constants import get_banner_path

    global _CHART_BG_CACHE

    if _CHART_BG_CACHE is None:
        try:
            import io
            local_bg = get_banner_path("chart_bg_fallback")
            content = None
            if isinstance(local_bg, Path) and local_bg.exists():
                content = local_bg.read_bytes()
            if content is not None:
                img = Image.open(io.BytesIO(content))
                if img.mode == 'RGBA':
                    img = img.convert('RGB')
                _CHART_BG_CACHE = img.resize((1200, 800), Image.LANCZOS)
        except Exception as e:
            logger.warning("Could not load chart background: %s", e)

    if _CHART_BG_CACHE is None:
        _CHART_BG_CACHE = Image.new('RGB', (1200, 800), (15, 15, 25))
        from PIL.ImageDraw import Draw
        draw = Draw(_CHART_BG_CACHE)
        for i in range(0, WIDTH, 40):
            draw.line([(i, 0), (i, HEIGHT)], fill=(30, 30, 45), width=1)
        for i in range(0, HEIGHT, 40):
            draw.line([(0, i), (WIDTH, i)], fill=(30, 30, 45), width=1)

    bg = _CHART_BG_CACHE

    reversed_history = list(reversed(history))[:10]

    # Load hero icons asynchronously
    # NOTE: здесь берутся маленькие PNG из hero_cache/icons/ для графика профиля.
    # Это НЕ assets/heroes_webp/ — те иконки используются только в мете героев.
    unique_hero_ids = list({g["hero_id"] for g in reversed_history if g.get("hero_id")})
    hero_icons = await asyncio.gather(*[_get_hero_icon(hid) for hid in unique_hero_ids])
    hero_icon_map = {hid: icon for hid, icon in zip(unique_hero_ids, hero_icons)}

    # Run matplotlib in thread pool (non-blocking)
    return await asyncio.to_thread(_create_visual_chart_sync, history, hero_icon_map, bg)
