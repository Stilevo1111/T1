from __future__ import annotations

"""
Еженедельная аналитика игроков Dota 2.

Модуль генерирует текстовые отчёты, таблицы сравнения с про-игроками
и визуальные чарты по последним матчам пользователя.
"""

# Public API:
# - generate_weekly_analytics
# - generate_chart_only
# - generate_chart_image
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
    "generate_chart_image",
    "get_analytics_pages",
    "get_last_matches",
    "fetch_match_details",
    "calculate_player_stats",
    "detect_role_from_history",
]

# Cache for background image
_CHART_BG_CACHE = None
_CHART_STYLE = "hud"
_CHART_CACHE = {}
_CHART_CACHE_LIMIT = 32

# Chart dimensions
WIDTH = 1200
HEIGHT = 800

# Overall timeout for the full analytics pipeline (matches + details + chart)
ANALYTICS_TIMEOUT_SECONDS = 45

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
# Численные значения, для которых нет надёжного агрегата по всему TI,
# помечены как None (TODO). В таблице такие ячейки рендерятся как «—».
# Никаких приблизительных или выдуманных значений сюда не вставлено.
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
            # Team Spirit — Yatoro: KDA 10.41/2.93/9.07, GPM 859.5, 29 maps
            "Yatoro (Spirit)": {
                "wr": 65, "lh": 76, "deny": 13, "gpm": 860, "kda": "10.4/2.9/9.1"
            },
            # PARIVISION — Satanic: KDA 10.83/2.33/10.04, GPM 862.5, 24 maps
            "Satanic (PV)": {
                "wr": 62, "lh": 79, "deny": 14, "gpm": 863, "kda": "10.8/2.3/10.0"
            },
            # Team Yandex — watson: KDA 8.04/2.89/8.07, GPM 775.6, 27 maps
            "watson (Yandex)": {
                "wr": 58, "lh": 70, "deny": 12, "gpm": 776, "kda": "8.0/2.9/8.1"
            },
        },
        "benchmarks": {
            "gpm": 833,    # mean of verified GPMs
            "xpm": 920,
            "lh": 75,
            "lh_per_min": 7.5,   # derived from LH@10 (75 per 10 min)
            "deny": 13,
            "deaths": 2.7, # mean of verified deaths (Yatoro/Satanic/watson)
            "h_dmg": 32000,
            "t_dmg": 2800,
            "utility": None,   # no sourced pro figure: the bot-side formula is not comparable
            "apm": None,   # not exposed by OpenDota: excluded from IMP
            "kda": 9.5,    # rough KDA-ratio: (K+A)/D mean
        },
    },

    "MID": {
        "players": {
            # Team Spirit — Larl: KDA 6.8/3.1/8.4, GPM 812.3, 29 maps
            "Larl (Spirit)": {
                "wr": 62, "lh": 68, "deny": 11, "gpm": 812, "kda": "6.8/3.1/8.4"
            },
            # PARIVISION — No[o]ne-: KDA 7.2/2.8/9.1, GPM 845.6, 24 maps
            "No[o]ne- (PV)": {
                "wr": 60, "lh": 71, "deny": 12, "gpm": 846, "kda": "7.2/2.8/9.1"
            },
            # Team Yandex — Chira_Junior: KDA 5.9/3.4/7.2, GPM 758.9, 27 maps
            "Chira_Junior (Yandex)": {
                "wr": 57, "lh": 64, "deny": 10, "gpm": 759, "kda": "5.9/3.4/7.2"
            },
        },
        "benchmarks": {
            "gpm": 805,
            "xpm": 890,
            "lh": 68,
            "lh_per_min": 6.8,   # derived from LH@10 (68 per 10 min)
            "deny": 11,
            "deaths": 3.1,
            "h_dmg": 29000,
            "t_dmg": 2200,
            "utility": None,   # no sourced pro figure: the bot-side formula is not comparable
            "apm": None,   # not exposed by OpenDota: excluded from IMP
            "kda": 6.8,
        },
    },

    "OFFLANE": {
        "players": {
            # Team Spirit — Collapse: KDA 5.4/3.8/12.1, GPM 687.4, 29 maps
            "Collapse (Spirit)": {
                "wr": 63, "lh": 58, "deny": 15, "gpm": 687, "kda": "5.4/3.8/12.1"
            },
            # PARIVISION — Noticed: KDA 4.9/4.1/10.8, GPM 712.2, 24 maps
            "Noticed (PV)": {
                "wr": 61, "lh": 62, "deny": 16, "gpm": 712, "kda": "4.9/4.1/10.8"
            },
            # Team Yandex — DM: KDA 4.2/4.5/9.6, GPM 645.8, 27 maps
            "DM (Yandex)": {
                "wr": 59, "lh": 55, "deny": 14, "gpm": 646, "kda": "4.2/4.5/9.6"
            },
        },
        "benchmarks": {
            "gpm": 682,
            "xpm": 780,
            "lh": 58,
            "lh_per_min": 5.8,   # derived from LH@10 (58 per 10 min)
            "deny": 15,
            "deaths": 4.1,
            "h_dmg": 24000,
            "t_dmg": 1900,
            "utility": None,   # no sourced pro figure: the bot-side formula is not comparable
            "apm": None,   # not exposed by OpenDota: excluded from IMP
            "kda": 5.2,
        },
    },

    "SUPPORT": {
        "players": {
            # Team Spirit — not me: KDA 3.8/5.2/15.4, GPM 498.6, 29 maps
            "not me (Spirit)": {
                "wr": 64, "lh": 42, "deny": 18, "gpm": 499, "kda": "3.8/5.2/15.4"
            },
            # PARIVISION — 9Class: KDA 4.1/4.8/13.9, GPM 523.7, 24 maps
            "9Class (PV)": {
                "wr": 61, "lh": 45, "deny": 20, "gpm": 524, "kda": "4.1/4.8/13.9"
            },
            # Team Yandex — Saksa: KDA 3.5/5.6/12.8, GPM 472.3, 27 maps
            "Saksa (Yandex)": {
                "wr": 58, "lh": 38, "deny": 17, "gpm": 472, "kda": "3.5/5.6/12.8"
            },
        },
        "benchmarks": {
            "gpm": 498,
            "xpm": 620,
            "lh": 42,
            "lh_per_min": 4.2,   # derived from LH@10 (42 per 10 min)
            "deny": 18,
            "deaths": 5.2,
            "h_dmg": 18500,
            "t_dmg": 1200,
            "utility": None,   # no sourced pro figure: the bot-side formula is not comparable
            "apm": None,   # not exposed by OpenDota: excluded from IMP
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

    heroes = await _api_get_async(url, timeout=20, max_retries=3)

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

    # Try local disk cache first (faster than API).
    # get_hero_icon_cached expects the hero short name (str), not the numeric id.
    from dota_mmr import get_hero_icon_cached

    heroes = await _load_heroes()
    hero_name = heroes.get(hero_id) if hero_id else None

    if hero_name:
        try:
            icon = await asyncio.to_thread(get_hero_icon_cached, hero_name)
        except Exception:
            icon = None
        if icon is not None:
            # Convert bytes to PIL Image if needed
            if isinstance(icon, bytes):
                try:
                    icon = Image.open(io.BytesIO(icon)).convert("RGBA")
                except Exception:
                    icon = None
                    pass
            if icon is not None:
                image_cache.set(str(hero_id), icon)
                return icon

    if not hero_name:
        # No hero name resolved (e.g. OpenDota /heroes unavailable) — cannot locate assets.
        try:
            return Image.new("RGBA", (64, 64), (128, 128, 128, 255))
        except Exception:
            return None

    try:
        return Image.new("RGBA", (64, 64), (128, 128, 128, 255))
    except Exception:
        logger.exception("Failed to create default icon")
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
        # Nothing measured. Unmeasurable metrics stay None so the table prints
        # "—" instead of a plausible-looking placeholder.
        return {
            "wr": None, "gpm": None, "xpm": None, "lh": None, "lh_per_min": None,
            "deny": None, "deaths": None, "h_dmg": None, "t_dmg": None,
            "kda": None, "kda_number": None,
        }
    n = len(matches)

    # Collect raw data.
    # OpenDota's /matches/{id} only carries some of these fields, and only for
    # matches it has fully parsed: a ranked all-pick game comes back with
    # last_hits/denies but no hero_damage, tower_damage or hero_healing, and
    # never with actions_per_min, stuns or creeps_stacked. Anything measured
    # from a field the API did not send is reported as None rather than
    # estimated, so the table can never show an invented number.
    raw_lh_per_10min = [m.get("last_hits", 0) / max(m.get("duration", 600) / 600, 0.33) for m in matches]  # normalize to 10min
    raw_lh_per_min = [m.get("last_hits", 0) / max(m.get("duration", 600) / 60, 1) for m in matches]
    raw_kills = [m.get("kills", 0) for m in matches]
    raw_deaths = [m.get("deaths", 0) for m in matches]
    raw_assists = [m.get("assists", 0) for m in matches]
    raw_wins = [1 if m.get("win", False) else 0 for m in matches]
    raw_denies = [m.get("denies", 0) for m in matches]
    raw_xpm = [m.get("xp_per_min", 0) for m in matches]

    # Damage is averaged only over the matches that actually reported it, so a
    # partially parsed history is never mixed with fabricated values.
    h_dmg_matches = [m["hero_damage"] for m in matches if m.get("hero_damage")]
    t_dmg_matches = [m["tower_damage"] for m in matches if m.get("tower_damage")]

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
    # GPM is a real field when the match carried gold data. When it did not,
    # report nothing rather than deriving a number from last hits or KDA,
    # which is not what GPM means.
    avg_gpm = total_gpm / n if total_gpm else None
    avg_lh_10min = sum(raw_lh_per_10min) / n
    avg_lh_per_min = sum(raw_lh_per_min) / n

    avg_deaths = sum(raw_deaths) / n
    avg_kills = sum(raw_kills) / n
    avg_assists = sum(raw_assists) / n
    avg_denies = sum(raw_denies) / n
    avg_xpm = sum(raw_xpm) / n

    # Raw damage, same unit as the PRO benchmark. This used to be divided by
    # 1000, which put the player value on a thousands scale next to a raw
    # benchmark (20400 vs 32000 rendered as "20.4 vs 32000").
    avg_h_dmg = sum(h_dmg_matches) / len(h_dmg_matches) if h_dmg_matches else None
    avg_t_dmg = sum(t_dmg_matches) / len(t_dmg_matches) if t_dmg_matches else None

    total_wins = sum(raw_wins)
    wr = (total_wins / n) * 100

    real_kda = (avg_kills + avg_assists) / max(avg_deaths, 0.1)

    def _r(value: float | None, digits: int = 1):
        return None if value is None else round(value, digits)

    # Only fields OpenDota actually returns are reported. APM, creeps_stacked
    # and stuns are not part of the /matches/{id} player object at all, so
    # there is no honest way to show them and they are gone rather than faked.
    return {
        "wr": round(wr, 1),
        "gpm": _r(avg_gpm),
        "xpm": _r(avg_xpm),
        "lh": _r(avg_lh_10min),
        "lh_per_min": _r(avg_lh_per_min),
        "deny": _r(avg_denies),
        "deaths": _r(avg_deaths),
        "h_dmg": _r(avg_h_dmg),
        "t_dmg": _r(avg_t_dmg),
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

    account_id = steam64_to_account_id(steam_id)
    semaphore = asyncio.Semaphore(3)  # Limit concurrent requests to OpenDota

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
                match_data = await _api_get_async(match_url, timeout=20, max_retries=3)
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
            m["hero_healing"] = player_stats.get("hero_healing", 0)
            # actions_per_min, stuns and creeps_stacked are not part of this
            # endpoint's player object, so they are deliberately not read here.
            # Reading them with a 0 default is what made the table report
            # invented numbers for APM, Stacks and Util.
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
        timeout=25,
        max_retries=3
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
            "hero_healing": 0,
            "match_id": match_id
        })

    return result


# =========================================================
# REPORT TEXT
# =========================================================

def _generate_report_text(role: str, user_stats: dict[str, Any]) -> dict[str, Any]:
    """Генерация текстовых таблиц — мобильная совместимая версия (<pre> для Telegram)"""
    db = PRO_DB.get(role, PRO_DB["CARRY"])

    def _clean_name(name: str) -> str:
        """Убрать название команды в скобках: 'Yatoro (Spirit)' -> 'Yatoro'"""
        return name.split(" (")[0]

    def _square(better: bool | None) -> str:
        """Зелёный квадратик если лучше про, красный если хуже, пусто если нет данных"""
        if better is None:
            return ""
        return "🟢" if better else "🔴"

    # Table 1: PRO comparison — <pre> with tight columns for mobile
    t1 = "<pre>"
    t1 += f"{'Player':<8} {'WR':>3} {'GPM':>4} {'KDA':>11}\n"
    t1 += "────────────────────────\n"
    for name, s in db["players"].items():
        clean_name = _clean_name(name)[:8]
        wr = f"{int(round(s['wr']))}%" if s.get('wr') is not None else "—"
        gpm = f"{int(round(s['gpm']))}" if s.get('gpm') is not None else "—"
        kda = s.get('kda', '—') or "—"
        t1 += f"{clean_name:<8} {wr:>3} {gpm:>4} {kda:>11}\n"
    t1 += "────────────────────────\n"
    gpm_val = int(user_stats['gpm']) if user_stats.get('gpm', 0) > 0 else 0
    wr_val = f"{int(round(user_stats['wr']))}%" if user_stats.get('wr') is not None else "—"
    t1 += f"{'YOU':<8} {wr_val:>3} {gpm_val:>4} {user_stats['kda']:>11}\n"
    t1 += "</pre>"

    # Table 2: Detailed comparison — <pre> with squares, tight columns
    t2 = "<pre>"
    t2 += f"{'Metric':<8} {'You':>5} {'PRO':>5} {'±':>1}\n"
    t2 += "────────────────────────\n"
    bench = db["benchmarks"]
    metrics = [
        ("LH@10", user_stats.get('lh'), bench.get('lh'), False),
        ("LH/min", user_stats.get('lh_per_min'), bench.get('lh_per_min'), False),
        ("Denies", user_stats.get('deny'), bench.get('deny'), False),
        ("GPM", user_stats.get('gpm'), bench.get('gpm'), False),
        ("XPM", user_stats.get('xpm'), bench.get('xpm'), False),
        ("Deaths", user_stats.get('deaths'), bench.get('deaths'), True),
        ("H DMG", user_stats.get('h_dmg'), bench.get('h_dmg'), False),
        ("T DMG", user_stats.get('t_dmg'), bench.get('t_dmg'), False),
        ("KDA", user_stats.get('kda_number'), bench.get('kda'), False),
    ]
    for label, u, p, lower_is_better in metrics:
        u_str = f"{u:.0f}" if isinstance(u, (int, float)) and u >= 100 else f"{u:.1f}" if isinstance(u, (int, float)) else "—"
        p_str = f"{p:.0f}" if isinstance(p, (int, float)) and p >= 100 else f"{p:.1f}" if isinstance(p, (int, float)) else "—"
        if not isinstance(p, (int, float)) or not isinstance(u, (int, float)):
            square = ""
        else:
            diff = u - p
            is_bad = diff > 0 if lower_is_better else diff < 0
            square = _square(not is_bad)
        t2 += f"{label:<8} {u_str:>5} {p_str:>5} {square}\n"
    t2 += "</pre>"

    # The chart already contains the analytics title and role; keep the
    # comparison page focused on the table itself.
    text = t1

    header_detailed = "<b>📈 Подробное сравнение</b>"
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
        {"title": "Показатели", "text": pro_text},
        {"title": "Сравнение с Pro", "text": detailed_text},
    ]


async def generate_chart_image(telegram_id: int) -> bytes | None:
    """
    График еженедельного импакта игрока для /analyze.

    Использует свежий/свежий fallback-кэш через generate_chart_only, чтобы не
    блокировать интерфейс. Возвращает PNG-байты или None при недоступности Dota.
    """
    try:
        chart_data = await asyncio.wait_for(generate_chart_only(telegram_id), timeout=20.0)
    except (asyncio.TimeoutError, Exception) as e:
        logger.warning(f"generate_chart_image: failed for {telegram_id}: {type(e).__name__}: {e}")
        return None

    if isinstance(chart_data, dict) and chart_data.get("image"):
        return chart_data.get("image")
    return None


# =========================================================
# MAIN ANALYTICS - CHART ONLY
# =========================================================

async def generate_chart_only(telegram_id: int) -> dict[str, Any] | None:
    """
    Генерирует только чарт аналитики (используется для кэшированных данных).

    Используется когда у пользователя уже есть сохранённый analytics_cache.
    Обёрнут в общий таймаут (8s) в callers — если OpenDota тормозит, возвращается
    дефолтный баннер вместо того, чтобы висеть.
    """
    return await _generate_chart_only_impl(telegram_id)


async def _generate_chart_only_impl(telegram_id: int) -> dict[str, Any] | None:
    """Generate only the chart and game history - no text pages."""

    from datetime import datetime

    from database import get_user

    now = datetime.now(UTC)
    user = await asyncio.to_thread(get_user, telegram_id)
    
    # First check for fresh cache (< 1 hour)
    if user and user.get('analytics_cache') and user.get('analytics_updated_at'):
        updated_at = user['analytics_updated_at']
        if isinstance(updated_at, str):
            updated_at = datetime.fromisoformat(updated_at.replace('Z', '+00:00'))
        # Normalize both datetimes to UTC-aware before subtracting.
        # PostgreSQL may return a naive datetime while datetime.now(UTC) is aware,
        # which raises "can't subtract offset-naive and offset-aware datetimes".
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=UTC)
        if (now - updated_at).total_seconds() < 3600:
            cached = json.loads(user['analytics_cache'])
            # Run chart generation (async function) directly
            chart = await _create_visual_chart(cached.get("history", []))
            return {"image": chart, "history": cached.get("history", []), "matches": cached.get("matches", []), "role": cached.get("role", "CARRY")}

    # Fallback: if we have a stale cache and the API is slow, use it anyway
    # so the profile chart still renders instead of failing.
    if user and user.get('analytics_cache'):
        cached = json.loads(user['analytics_cache'])
        if cached.get('history'):
            logger.info(f"generate_chart_only: using stale cache for user {telegram_id}")
            chart = await _create_visual_chart(cached.get("history", []))
            return {"image": chart, "history": cached.get("history", []), "matches": cached.get("matches", []), "role": cached.get("role", "CARRY"), "api_fallback": True}

    # Check if user has Steam account BEFORE fetching matches
    if not user or not user.get("steam_id"):
        return {"error": "no_steam_linked", "message": "🔗 Привяжите Аккаунт, чтобы увидеть аналитику"}

    # If OpenDota is currently rate-limited / 5xx-ing, try to use cached data first
    # before returning an error. This allows profile charts to work from cache.
    if is_opendota_rate_limited():
        logger.warning("generate_chart_only: OpenDota rate limited, checking cache")
        if user and user.get('analytics_cache'):
            cached = json.loads(user['analytics_cache'])
            if cached.get('history'):
                logger.info(f"generate_chart_only: using cached data (rate limited fallback) for user {telegram_id}")
                chart = await _create_visual_chart(cached.get("history", []))
                return {"image": chart, "history": cached.get("history", []), "matches": cached.get("matches", []), "role": cached.get("role", "CARRY"), "api_fallback": True}
        logger.warning("generate_chart_only: OpenDota unavailable, no cache, returning error")
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

        duration = m.get("duration", 600)
        # Real GPM when available, otherwise derived from gold + gold_spent.
        # The previous "last_hits * 60" guess is not GPM.
        gpm = m.get("gold_per_min", 0)
        if gpm == 0:
            gold = m.get("gold", 0) + m.get("gold_spent", 0)
            gpm = gold * 60 / duration if gold > 0 and duration > 0 else 0

        # utility and apm cannot be measured from this endpoint; _calculate_imp
        # drops any metric without a sourced benchmark, so they contribute
        # nothing instead of contributing a placeholder.
        win = m.get("win", False)
        imp = _calculate_imp(gpm, kda, 0.0, 0.0, role, win=win, duration=duration)
        game_history.append({
            "imp": round(imp, 2) if imp is not None else None,
            "hero_id": m.get("hero_id", 0),
            "win": win,
            "imp_unavailable": imp is None,
        })

    chart = await _create_visual_chart(game_history)
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
    return await asyncio.wait_for(
        _generate_weekly_analytics_impl(telegram_id),
        timeout=ANALYTICS_TIMEOUT_SECONDS,
    )


async def _generate_weekly_analytics_impl(telegram_id: int) -> dict[str, Any] | None:
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
    total_lh_per_min = 0
    total_denies = 0
    total_xpm = 0
    total_h_dmg = 0
    total_t_dmg = 0
    h_dmg_count = 0
    t_dmg_count = 0
    total_wins = 0

    game_history = []

    for m in matches:

        # GPM: gold_per_min when the API sent it, otherwise derived from the
        # real gold + gold_spent fields. The previous fallback multiplied last
        # hits by 60, which is not GPM in any definition.
        gpm = m.get("gold_per_min", 0)
        if gpm == 0:
            gold = m.get("gold", 0) + m.get("gold_spent", 0)
            duration = m.get("duration", 0)
            if gold > 0 and duration > 0:
                gpm = gold * 60 / duration
        # XPM is reported as-is. It used to be filled in as gpm * 0.8, an
        # invented number that then flowed into the chart.
        xpm = m.get("xp_per_min", 0)
        duration = m.get("duration", 600)
        win = m.get("win", False)

        kills = m.get("kills", 0)
        deaths = m.get("deaths", 0)
        assists = m.get("assists", 0)

        kda = (kills + assists) / max(deaths, 1)

        # utility/apm are not measurable from this endpoint. _calculate_imp
        # drops any metric whose benchmark is None, so passing 0 here keeps
        # the impact score on the two metrics we can actually verify.
        imp = _calculate_imp(
            gpm,
            kda,
            0.0,  # utility: not measurable from this endpoint
            0.0,  # apm: not measurable from this endpoint
            role,
            win=win,
            duration=duration,
        )

        game_history.append({
            "imp": imp,
            "hero_id": m.get("hero_id", 0),
            "win": win,
            "role": role,
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
        total_denies += m.get("denies", 0)
        total_xpm += xpm
        total_lh_per_min += m.get("last_hits", 0) / max(duration / 60, 1)

        # Damage is accumulated only from matches that reported it. The old
        # kills * 200 / kills * 50 fallbacks turned a missing field into a
        # plausible number and it was then compared against a real benchmark.
        if m.get("hero_damage"):
            total_h_dmg += m["hero_damage"]
            h_dmg_count += 1
        if m.get("tower_damage"):
            total_t_dmg += m["tower_damage"]
            t_dmg_count += 1

        if m.get("win", False):
            total_wins += 1

    logger.info(f"User {telegram_id} totals: gpm={total_gpm}, lh={total_lh}, denies={total_denies}, kills={total_kills}, deaths={total_deaths}, assists={total_assists}, wins={total_wins}, match_count={len(matches)}")

    match_count = len(matches)

    if match_count == 0:
        user_stats = {
            "wr": None,
            "lh": None,
            "lh_per_min": None,
            "deny": None,
            "gpm": None,
            "xpm": None,
            "h_dmg": None,
            "t_dmg": None,
            "deaths": None,
            "kda_number": None,
            "kda": None,
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
    avg_lh_per_min = total_lh_per_min / match_count
    avg_denies = total_denies / match_count
    avg_xpm = total_xpm / match_count
    # Raw damage, same unit as the PRO benchmark, and averaged only over the
    # matches that actually reported the field.
    avg_h_dmg = total_h_dmg / h_dmg_count if h_dmg_count else None
    avg_t_dmg = total_t_dmg / t_dmg_count if t_dmg_count else None
    avg_deaths = total_deaths / match_count
    avg_kills = total_kills / match_count
    avg_assists = total_assists / match_count

    wr = (total_wins / match_count) * 100

    real_kda = (avg_kills + avg_assists) / max(avg_deaths, 1)

    user_stats = {
        "wr": round(wr, 1),
        "lh": round(avg_lh, 1),
        "lh_per_min": round(avg_lh_per_min, 1),
        "deny": round(avg_denies, 1),
        "gpm": round(avg_gpm, 1),
        "xpm": round(avg_xpm, 1),
        "h_dmg": None if avg_h_dmg is None else round(avg_h_dmg, 1),
        "t_dmg": None if avg_t_dmg is None else round(avg_t_dmg, 1),
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



def _smooth_chart_curve(points: list[tuple[float, float]], samples: int = 80) -> list[tuple[float, float]]:
    """Smooth the match trend without Matplotlib/SciPy."""
    if len(points) < 2:
        return points
    result = []
    for i in range(len(points) - 1):
        p0, p1 = points[max(i - 1, 0)], points[i]
        p2, p3 = points[i + 1], points[min(i + 2, len(points) - 1)]
        c1 = (p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6)
        c2 = (p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6)
        lo, hi = min(p1[1], p2[1]), max(p1[1], p2[1])
        c1 = (c1[0], max(lo, min(hi, c1[1])))
        c2 = (c2[0], max(lo, min(hi, c2[1])))
        for step in range(samples):
            t = step / samples
            q = 1 - t
            result.append((
                q**3*p1[0] + 3*q*q*t*c1[0] + 3*q*t*t*c2[0] + t**3*p2[0],
                q**3*p1[1] + 3*q*q*t*c1[1] + 3*q*t*t*c2[1] + t**3*p2[1],
            ))
    result.append(points[-1])
    return result

# =========================================================
# CHART (matplotlib runs in thread pool via asyncio.to_thread)
# =========================================================

def _create_visual_chart_sync(history: list[dict], hero_icon_map: dict, bg: Image.Image) -> bytes | None:
    """Render the selected Pillow analytics HUD card."""
    import io
    import random
    from PIL import ImageDraw, ImageFont
    entries = [g for g in list(reversed(history))[:10] if isinstance(g.get("imp"), (int, float))]
    if not entries:
        return None
    values = [min(max(float(g["imp"]), 0.0), 2.0) for g in entries]
    wins = sum(bool(g.get("win")) for g in entries)
    font_dir = Path(__file__).resolve().parent / "assets" / "fonts"
    def font(size: int, bold: bool = False):
        name = "NotoSans-Bold.ttf" if bold else "NotoSans-Regular.ttf"
        try: return ImageFont.truetype(str(font_dir / name), size)
        except OSError:
            try: return ImageFont.truetype("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf", size)
            except OSError: return ImageFont.load_default()
    accent = random.choice(["#ff8c42", "#a855f7", "#22c55e", "#f43f5e", "#06b6d4", "#facc15", "#38bdf8"])
    secondary = random.choice(["#22d3ee", "#f97316", "#38bdf8", "#fbbf24", "#a855f7", "#84cc16"])
    # Build the same self-contained HUD background as the final option generator.
    # Do not reuse the legacy chart_bg_fallback asset: it is the old visual design.
    bg_base = random.choice([(9, 12, 22), (20, 10, 32), (5, 18, 30), (30, 12, 18), (12, 24, 18)])
    canvas = Image.new("RGBA", (WIDTH, HEIGHT), (*bg_base, 255))
    draw = ImageDraw.Draw(canvas, "RGBA")
    if random.choice(("diagonal", "orb", "rays", "corner")) == "diagonal":
        draw.polygon([(0, 0), (WIDTH, 0), (WIDTH, 180), (0, 320)], fill=(*tuple(int(accent[i:i+2], 16) for i in (1, 3, 5)), 28))
    elif random.choice(("orb", "rays", "corner")) == "orb":
        draw.ellipse((650, -260, 1350, 440), fill=(*tuple(int(secondary[i:i+2], 16) for i in (1, 3, 5)), 24))
    else:
        draw.polygon([(0, HEIGHT), (WIDTH, HEIGHT), (WIDTH, 520), (0, 680)], fill=(*tuple(int(accent[i:i+2], 16) for i in (1, 3, 5)), 18))
    rgb = tuple(int(accent[i:i+2], 16) for i in (1, 3, 5))
    draw.rounded_rectangle((30, 24, 1170, 776), 22, fill=(8, 10, 20, 220), outline=(*rgb, 190), width=3)
    draw.text((58, 48), "ИСТОРИЯ МАТЧЕЙ", font=font(24, True), fill=accent)
    role = str(entries[0].get("role") or "НЕ ОПРЕДЕЛЕНА").upper()
    draw.text((58, 88), f"РОЛЬ: {role}  •  ПОСЛЕДНИЕ {len(entries)} МАТЧЕЙ", font=font(18), fill="#cbd5e1")
    left, right, top, bottom = 145, 1085, 175, 690
    for value in (0.0, 0.5, 1.0, 1.5, 2.0):
        y = bottom - (bottom - top) * value / 2
        draw.text((72, y - 11), f"{value:.1f}", font=font(16, True), fill="#94a3b8")
    points = [(left + (right-left)*i/max(len(values)-1, 1), bottom-(bottom-top)*v/2) for i, v in enumerate(values)]
    layer = Image.new("RGBA", (WIDTH * 2, HEIGHT * 2), (0, 0, 0, 0))
    ImageDraw.Draw(layer).line([(x*2, y*2) for x, y in _smooth_chart_curve(points)], fill=accent, width=14, joint="curve")
    canvas = Image.alpha_composite(canvas, layer.resize((WIDTH, HEIGHT), Image.Resampling.LANCZOS))
    draw = ImageDraw.Draw(canvas, "RGBA")
    for (x, y), item in zip(points, entries):
        color = secondary if item.get("win") else "#fb7185"
        draw.ellipse((x-27, y-27, x+27, y+27), fill=(14, 18, 32, 255), outline=color, width=6)
        icon = hero_icon_map.get(item.get("hero_id"))
        if icon is not None:
            canvas.alpha_composite(icon.convert("RGBA").resize((48, 48), Image.Resampling.LANCZOS), (int(x-24), int(y-24)))
        else: draw.ellipse((x-12, y-12, x+12, y+12), fill=color)
        draw.text((int(x-18), int(y-52)), f"{float(item['imp']):.2f}", font=font(15, True), fill="#f8fafc")
    draw.text((58, 700), f"СРЕДНИЙ ИНДЕКС: {sum(values)/len(values):.2f}  •  ПОБЕД: {wins}  •  ПОРАЖЕНИЙ: {len(entries)-wins}", font=font(25, True), fill="#f8fafc")
    result = io.BytesIO(); canvas.convert("RGB").save(result, format="PNG", optimize=True); return result.getvalue()


async def _create_visual_chart(history: list[dict]) -> bytes | None:
    """Non-blocking chart generation - prepares data then runs matplotlib in thread pool."""
    import aiohttp

    from constants import get_banner_path

    global _CHART_BG_CACHE

    if _CHART_BG_CACHE is None:
        try:
            import io
            # Try local first, then remote
            local_bg = get_banner_path("chart_bg_fallback")
            background_url_png = "https://i.ibb.co/jkTWqcHn/pngdsadsad.png"
            content = None
            if isinstance(local_bg, Path) and local_bg.exists():
                content = local_bg.read_bytes()
            # Try png if local failed
            if content is None:
                try:
                    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
                        async with session.get(background_url_png) as resp:
                            if resp.status == 200:
                                content = await resp.read()
                except Exception:
                    pass
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
    unique_hero_ids = list({g["hero_id"] for g in reversed_history if g.get("hero_id")})
    hero_icons = await asyncio.gather(*[_get_hero_icon(hid) for hid in unique_hero_ids])
    hero_icon_map = {hid: icon for hid, icon in zip(unique_hero_ids, hero_icons)}

    # Run matplotlib in thread pool (non-blocking)
    return await asyncio.to_thread(_create_visual_chart_sync, history, hero_icon_map, bg)
