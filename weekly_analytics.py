# weekly_analytics.py - Еженедельная аналитика игрока (fixed version)

import asyncio
import aiohttp
import json
from PIL import Image, ImageDraw, ImageFont
import io
from datetime import datetime, timezone, timedelta

from dota_mmr import steam64_to_account_id, OPENDOTA_API_URL, _api_get_async
from database import get_user
from hero_positions import hero_positions

import logging

logger = logging.getLogger(__name__)

logger = logging.getLogger(__name__)

# Cache for background image and hero icons
_CHART_BG_CACHE = None
_HERO_ICON_CACHE = {}

# =========================================================
# MARKDOWN ESCAPE
# =========================================================

def escape_markdown_v2(text: str) -> str:
    """Escape special characters for Telegram MarkdownV2"""
    escape_chars = r"_*[]()~`>#+-=|{}.!"
    return "".join(f"\\{c}" if c in escape_chars else c for c in text)

# =========================================================
# HERO CACHE
# =========================================================

_HERO_NAME_CACHE = {}
_HERO_ROLE_CACHE = {}

# =========================================================
# PRO DATABASE
# =========================================================

PRO_DB = {
    "CARRY": {
        "players": {
            "Watson": {"wr": 68, "lh": 72, "deny": 12, "gpm": 725, "kda": "8/2.9/8"},
            "skiter": {"wr": 65, "lh": 72, "deny": 13, "gpm": 693, "kda": "7/3.0/9"},
            "Pure": {"wr": 63, "lh": 67, "deny": 11, "gpm": 742, "kda": "8/3.7/9"},
            "Satanic": {"wr": 61, "lh": 81, "deny": 14, "gpm": 825, "kda": "8/2.8/7"},
            "Ame": {"wr": 60, "lh": 78, "deny": 9, "gpm": 743, "kda": "7/3.2/7"}
        },
        "benchmarks": {
            "gpm": 732,
            "xpm": 855,
            "lh": 74,
            "deny": 12,
            "deaths": 3.1,
            "h_dmg": 28.0,
            "t_dmg": 9.3,
            "stacks": 5,
            "utility": 8.0,
            "apm": 310,
            "kda": 5.5
        }
    },

    "MID": {
        "players": {
            "Malr1ne": {"wr": 64, "lh": 75, "deny": 24, "gpm": 715, "kda": "9/3.1/8"},
            "Quinn": {"wr": 62, "lh": 70, "deny": 20, "gpm": 690, "kda": "8/3.4/9"},
            "Nisha": {"wr": 63, "lh": 73, "deny": 22, "gpm": 705, "kda": "9/2.8/7"},
            "gpk~": {"wr": 60, "lh": 68, "deny": 25, "gpm": 685, "kda": "8/3.5/10"},
            "No[o]ne": {"wr": 61, "lh": 74, "deny": 21, "gpm": 710, "kda": "10/3.2/8"}
        },
        "benchmarks": {
            "gpm": 702,
            "xpm": 810,
            "lh": 72,
            "deny": 22,
            "deaths": 3.2,
            "h_dmg": 32.0,
            "t_dmg": 4.5,
            "stacks": 8,
            "utility": 5.0,
            "apm": 340,
            "kda": 5.0
        }
    },

    "OFFLANE": {
        "players": {
            "Collapse": {"wr": 62, "lh": 62, "deny": 18, "gpm": 590, "kda": "5/3.8/12"},
            "33": {"wr": 65, "lh": 58, "deny": 15, "gpm": 610, "kda": "4/3.2/14"},
            "Ace": {"wr": 63, "lh": 65, "deny": 20, "gpm": 580, "kda": "5/3.5/15"},
            "ATF": {"wr": 60, "lh": 70, "deny": 14, "gpm": 640, "kda": "7/4.1/10"},
            "Wisper": {"wr": 58, "lh": 63, "deny": 16, "gpm": 595, "kda": "6/4.0/11"}
        },
        "benchmarks": {
            "gpm": 595,
            "xpm": 680,
            "lh": 64,
            "deny": 17,
            "deaths": 3.8,
            "h_dmg": 24.5,
            "t_dmg": 6.2,
            "stacks": 12,
            "utility": 10.0,
            "apm": 290,
            "kda": 4.5
        }
    },

    "SUPPORT": {
        "players": {
            "Miposhka": {"wr": 62, "lh": 12, "deny": 4, "gpm": 380, "kda": "3/4.2/18"},
            "Save-": {"wr": 60, "lh": 18, "deny": 6, "gpm": 410, "kda": "4/3.8/15"},
            "Sneyking": {"wr": 64, "lh": 14, "deny": 3, "gpm": 395, "kda": "2/4.5/20"},
            "Puppey": {"wr": 58, "lh": 10, "deny": 2, "gpm": 350, "kda": "1/5.1/14"},
            "Fishman": {"wr": 59, "lh": 15, "deny": 5, "gpm": 370, "kda": "2/4.9/16"}
        },
        "benchmarks": {
            "gpm": 385,
            "xpm": 420,
            "lh": 14,
            "deny": 4,
            "deaths": 4.8,
            "h_dmg": 12.0,
            "t_dmg": 0.8,
            "stacks": 20,
            "utility": 15.0,
            "apm": 270,
            "kda": 3.5
        }
    }
}

# =========================================================
# IMP WEIGHTS
# =========================================================

IMP_WEIGHTS = {
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

def calculate_utility(
    stuns: float = 0,
    heals: float = 0,
    stacks: int = 0,
    wards: int = 0
) -> float:

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

def calculate_imp(
    gpm: float,
    kda: float,
    utility: float,
    apm: float,
    role: str
) -> float:

    if role not in PRO_DB:
        role = "CARRY"

    pro = PRO_DB[role]["benchmarks"]
    weights = IMP_WEIGHTS[role]

    p_gpm = gpm / pro["gpm"]
    p_kda = kda / pro["kda"]
    p_utility = utility / pro["utility"]
    p_apm = apm / pro["apm"]

    imp = (
        p_gpm * weights["gpm"] +
        p_kda * weights["kda"] +
        p_utility * weights["utility"] +
        p_apm * weights["apm"]
    )

    return round(imp, 2)

# =========================================================
# HERO DATA
# =========================================================

async def load_heroes():

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
# load_heroes() returns names like "anti_mage", "npc_dota_hero_necrophos" etc
HERO_NAME_MAP = {
    "anti_mage": "antimage",
    "npc_dota_hero_necrophos": "necrophos",
    "queenofpain": "queenofpain",
    "skywrath_mage": "skywrath_mage",
    "outworld_destroyer": "outworld_destroyer",
    "lone_druid": "lone_druid",
    "centaur": "centaur",
    "magnataur": "magnataur",  # File is magnataur.png
    "doom_bringer": "doom_bringer",
    "witchdoctor": "witch_doctor",
    "keeper_of_the_light": "keeper_of_the_light",
    "nightstalker": "night_stalker",
    "shadow_shaman": "shadow_shaman",
    "life_stealer": "life_stealer",
    "abyssal_underlord": "abyssal_underlord",
}

def normalize_hero_file_name(internal_name: str) -> str:
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


async def get_hero_icon(hero_id: int):
    global _HERO_ICON_CACHE

    if hero_id in _HERO_ICON_CACHE:
        return _HERO_ICON_CACHE[hero_id]

    heroes = await load_heroes()

    hero_name = heroes.get(hero_id)

    if hero_name:
        file_name = normalize_hero_file_name(hero_name)
        path = f"assets/heroes/{file_name}.png"

        try:
            icon = Image.open(path).convert("RGBA")
            _HERO_ICON_CACHE[hero_id] = icon
            return icon

        except Exception:

            logger.warning(
                f"Failed load icon: {hero_name}"
            )

    # Fallback to default icon
    try:
        # Create a gray placeholder icon
        img = Image.new("RGBA", (64, 64), (128, 128, 128, 255))
        return img
    except Exception:
        logger.exception("Failed to create default icon")
        return None

# =========================================================
# HERO ROLE CACHE & LOADING
# =========================================================

async def load_hero_roles():

    global _HERO_ROLE_CACHE

    if _HERO_ROLE_CACHE:
        return _HERO_ROLE_CACHE

    url = f"{OPENDOTA_API_URL}/heroStats"

    data = await _api_get_async(url, timeout=15)

    if not data:
        return {}

    for hero in data:

        hero_id = hero["id"]
        roles = hero.get("roles", [])
        _HERO_ROLE_CACHE[hero_id] = roles

    logger.info("Loaded hero role database")

    return _HERO_ROLE_CACHE


def convert_opendota_roles(opendota_roles: list) -> str:

    roles = set(opendota_roles)

    # CARRY - highest priority if Carry exists
    if "Carry" in roles:
        return "CARRY"

    # MID
    if "Nuker" in roles and "Escape" in roles:
        return "MID"

    # OFFLANE
    if "Durable" in roles and "Initiator" in roles:
        return "OFFLANE"

    # SUPPORT
    if "Support" in roles or "Disabler" in roles:
        return "SUPPORT"

    return "SUPPORT"


def normalize_hero_name(internal_name: str) -> str:
    """Convert internal hero name (anti_mage) to display name (Anti-Mage)"""
    import re
    # Handle special cases first
    name_map = {
        "npc_dota_hero_necrophos": "Necrophos",
        "npc_dota_hero_queenofpain": "Queen of Pain",
        "npc_dota_hero_skywrath_mage": "Skywrath Mage",
        "npc_dota_hero_outworld_destroyer": "Outworld Destroyer",
        "npc_dota_hero_lone_druid": "Lone Druid",
        "npc_dota_hero_centaur": "Centaur Warrunner",
        "npc_dota_hero_magnataur": "Magnus",
        "npc_dota_hero_axe": "Axe",
        "npc_dota_hero_doom_bringer": "Doom",
        "npc_dota_hero_witchdoctor": "Witch Doctor",
        "npc_dota_hero_keeper_of_the_light": "Keeper of the Light",
        "npc_dota_hero_nightstalker": "Night Stalker",
        "npc_dota_hero_shadow_shaman": "Shadow Shaman",
        "npc_dota_hero_life_stealer": "Lifestealer",
        "npc_dota_hero_abyssal_underlord": "Underlord",
    }
    
    if internal_name in name_map:
        return name_map[internal_name]
    
    # Replace npc_dota_hero_ prefix
    name = internal_name.replace("npc_dota_hero_", "")
    
    # Convert snake_case to Title Case with spaces
    # e.g., "anti_mage" -> "Anti Mage" -> handle special cases
    parts = name.split("_")
    result = " ".join(p.capitalize() for p in parts)
    
    # Fix known multi-word hero names
    multi_word_fixes = {
        "Anti Mage": "Anti-Mage",
        "Drow Ranger": "Drow Ranger",  # already correct
        "Faceless Void": "Faceless Void",  # already correct
        "Phantom Assassin": "Phantom Assassin",  # already correct
        "Phantom Lancer": "Phantom Lancer",  # already correct
        "Shadow Fiend": "Shadow Fiend",  # already correct
        "Treant Protector": "Treant Protector",  # already correct
        "Winter Wyvern": "Winter Wyvern",  # already correct
        "Queen Of Pain": "Queen of Pain",
        "Skywrath Mage": "Skywrath Mage",
        "Outworld Destroyer": "Outworld Destroyer",
        "Dust II": "Dust II",  # handle edge cases
    }
    
    return multi_word_fixes.get(result, result)


async def detect_role_from_hero_counts(matches: list) -> str:
    heroes = await load_heroes()
    
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
        hero_name = normalize_hero_name(internal_name)
        
        # Look up position from local hero_positions database
        position = hero_positions.get(hero_name, 0)
        
        # Map position to role
        if position in POS_TO_ROLE:
            role = POS_TO_ROLE[position]
            role_counts[role] += 1
    
    if total_matches == 0:
        return "CARRY"
    
    # Find dominant role (60% threshold)
    dominant_role = max(role_counts, key=role_counts.get)
    dominant_count = role_counts[dominant_role]
    
    if dominant_count >= total_matches * 0.6:
        logger.info(f"ROLE BY HERO COUNT: {dominant_role} ({dominant_count}/{total_matches})")
        return dominant_role
    
    logger.info(f"ROLE BY HERO COUNT: no dominance ({role_counts})")
    return None


async def detect_role_from_history(matches: list):
    role = await detect_role_from_hero_counts(matches)
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
    else:
        return "SUPPORT"


def calculate_player_stats(matches: list) -> dict:
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
    avg_lh = total_lh / n
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

async def fetch_match_details(matches: list, steam_id: str) -> list:
    """Fetch full match details for matches that have minimal data."""
    account_id = steam64_to_account_id(steam_id)
    enriched = []
    
    for m in matches:
        # If match already has all needed data, keep it
        if m.get("gold_per_min", 0) > 0 and m.get("last_hits", 0) > 0:
            enriched.append(m)
            continue
        
        match_id = m.get("match_id")
        if not match_id:
            enriched.append(m)
            continue
        
        try:
            match_url = f"{OPENDOTA_API_URL}/matches/{match_id}"
            match_data = await _api_get_async(match_url, timeout=10)
            
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
            
            # Yield to event loop to prevent blocking
            await asyncio.sleep(0)
            
        except Exception as e:
            logger.debug(f"Failed to fetch match {match_id}: {e}")
        
        enriched.append(m)
    
    return enriched


async def get_weekly_matches(telegram_id: int):

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
        params={"limit": 10},
        timeout=15
    )

    if not matches:
        return []
    
    logger.info(f"get_weekly_matches: got {len(matches)} matches from API for account {account_id}")

    week_start = (
        datetime.now(timezone.utc)
        - timedelta(days=7)
    )

    filtered = []

    # Use only basic match data from /players/{account_id}/matches (no individual match API calls)
    for m in matches:
        ts = m.get("start_time", 0)

        match_time = datetime.fromtimestamp(
            ts,
            tz=timezone.utc
        )

        if match_time < week_start:
            continue

        match_id = m.get("match_id")
        hero_id = m.get("hero_id", 0)
        duration = m.get("duration", 0)
        player_slot = m.get("player_slot", 0)

        # Use basic data from match list (no full match API calls)
        kills = m.get("kills", 0)
        deaths = m.get("deaths", 0)
        assists = m.get("assists", 0)
        radiant_win = m.get("radiant_win", False)

        # Determine if player was on radiant (slot < 128)
        is_radiant = player_slot < 128 if player_slot else True
        is_win = radiant_win if is_radiant else not radiant_win

        filtered.append({
            "hero_id": hero_id,
            "kills": kills,
            "deaths": deaths,
            "assists": assists,
            "gold_per_min": 0,  # Will be fetched lazily when needed
            "duration": duration,
            "gold": 0,
            "gold_spent": 0,
            "xp_per_min": 0,
            "last_hits": 0,
            "hero_damage": 0,
            "tower_damage": 0,
            "lane_role": 0,
            "start_time": ts,
            "win": is_win,
            "denies": 0,
            "actions_per_min": 0,
            "stuns": 0.0,
            "hero_healing": 0,
            "creeps_stacked": 0,
            "observer_uses": 0,
            "sentry_uses": 0,
            "match_id": match_id  # Keep for lazy loading later
        })

        if len(filtered) >= 10:
            break

    return filtered

# =========================================================
# REPORT TEXT
# =========================================================

def generate_report_text(role: str, user_stats: dict) -> dict:
    """Генерация текстовых таблиц в стиле референса"""

    db = PRO_DB.get(role, PRO_DB["CARRY"])

    # Table 1: PRO comparison
    t1 = "```\n"
    t1 += f"{'PLAYER':<12} {'WR':>4} {'GPM':>5} {'KDA':>11}\n"
    t1 += "--------------------------------\n"
    for name, s in db["players"].items():
        t1 += (
            f"{name:<12} "
            f"{s['wr']:>3}% "
            f"{s['gpm']:>5} "
            f"{s['kda']:>11}\n"
        )
    t1 += "--------------------------------\n"
    gpm_val = int(user_stats['gpm']) if user_stats.get('gpm', 0) > 0 else 0
    you_line = (
        f"{'YOU':<12} "
        f"{user_stats['wr']:>3}% "
        f"{gpm_val:>5} "
        f"{user_stats['kda']:>11}\n"
    )
    t1 += you_line
    t1 += "```"

    # Таблица 2: Детальное сравнение
    t2 = "```\n"
    t2 += f"{'Metric':<10} {'You':>6} {'PRO':>6}\n"
    t2 += "----------------------------\n"
    bench = db["benchmarks"]
    metrics = [
        ("LH@10", user_stats.get('lh', 0), bench.get('lh', 0)),
        ("Denies@10", user_stats.get('deny', 0), bench.get('deny', 0)),
        ("GPM", user_stats.get('gpm', 0), bench['gpm']),
        ("XPM", user_stats.get('xpm', 0), bench['xpm']),
        ("Deaths", user_stats.get('deaths', 0), bench['deaths']),
        ("H DMG", user_stats.get('h_dmg', 0), bench['h_dmg']),
        ("T DMG", user_stats.get('t_dmg', 0), bench['t_dmg']),
        ("Stacks", user_stats.get('stacks', 0), bench.get('stacks', 0)),
        ("Util", user_stats.get('util', 0), bench['utility']),
        ("APM", user_stats.get('apm', 0), bench['apm'])
    ]
    for label, u, p in metrics:
        u_str = f"{u:.0f}" if u >= 100 else f"{u:.1f}"
        p_str = f"{p:.0f}" if p >= 100 else f"{p:.1f}"
        diff = u - p
        is_bad = diff > 0 if "Deaths" in label else diff < 0
        arrow = "↓" if is_bad else "↑"
        t2 += f"{label:<10} {u_str:>6} {p_str:>6} {arrow}\n"
    t2 += "```"

    header = escape_markdown_v2(f"📊 ANALYTICS ({role})")

    text = f"{header}\n\n{t1}"

    header_detailed = escape_markdown_v2(f"🔍 Detailed comparison")

    text_detailed = f"{header_detailed}\n\n{t2}"

    return {"pro": text, "detailed": text_detailed}


def get_analytics_pages(role: str, stats: dict) -> list:
    """Generate a list of analytics pages for pagination.

    Each page is a dict with 'title' and 'text' keys.
    Page 0: PRO comparison
    Page 1: Detailed comparison
    """
    tables = generate_report_text(role, stats)
    pro_text = tables["pro"]
    detailed_text = tables["detailed"]

    return [
        {"title": "🆚Сравнение с Pro", "text": pro_text},
        {"title": "🔍 Детальное сравнение", "text": detailed_text},
    ]


# =========================================================
# MAIN ANALYTICS - CHART ONLY
# =========================================================

async def generate_chart_only(telegram_id: int):
    """Generate only the chart and game history - no text pages."""
    
    from database import get_user
    from datetime import datetime, timezone, timedelta
    
    user = get_user(telegram_id)
    if user and user.get('analytics_cache') and user.get('analytics_updated_at'):
        updated_at = user['analytics_updated_at']
        if isinstance(updated_at, str):
            updated_at = datetime.fromisoformat(updated_at.replace('Z', '+00:00'))
        now = datetime.now(timezone.utc)
        if (now - updated_at).total_seconds() < 3600:
            import json
            cached = json.loads(user['analytics_cache'])
            # Run chart generation (async function) directly
            chart = await create_visual_chart(cached.get("history", []))
            return {"image": chart, "history": cached.get("history", []), "matches": cached.get("matches", [])}

    matches = await get_weekly_matches(telegram_id)

    if len(matches) < 5:
        from dota_mmr import get_opendota_rate_limit_message
        return {"error": "opendota_rate_limit", "message": get_opendota_rate_limit_message()}

    matches = sorted(matches, key=lambda x: x.get("start_time", 0))

    # Detect role from hero picks
    role = await detect_role_from_hero_counts(matches) or "CARRY"

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
        utility = stacks * 1.5 + denies * 0.5
        
        # Estimate APM (typical values by role)
        apm = 250
        
        imp = calculate_imp(gpm, kda, utility, apm, role)
        game_history.append({"imp": round(imp, 2), "hero_id": m.get("hero_id", 0)})

    chart = await create_visual_chart(game_history)
    return {"image": chart, "history": game_history, "matches": matches}


async def generate_weekly_analytics(telegram_id: int):
    matches = await get_weekly_matches(telegram_id)

    if len(matches) < 5:
        return None

    # Sort by start_time ascending (oldest first)
    matches = sorted(
        matches,
        key=lambda x: x.get("start_time", 0)
    )

    # Advanced role detection using OpenDota hero roles + match stats
    role = await detect_role_from_history(matches)

    # averages

    total_gpm = 0
    total_kills = 0
    total_deaths = 0
    total_assists = 0
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

        # Use gold_per_min directly from match data (it's already computed by OpenDota)
        gpm = m.get("gold_per_min", 0)
        # Fallback: if GPM zero, estimate from last_hits
        if gpm == 0:
            last_hits = m.get("last_hits", 0)
            if last_hits > 0:
                gpm = last_hits * 60

        kills = m.get("kills", 0)
        deaths = m.get("deaths", 0)
        assists = m.get("assists", 0)

        kda = (kills + assists) / max(deaths, 1)

        utility = calculate_utility(
            m.get("stuns", 0),
            m.get("hero_healing", 0),
            m.get("creeps_stacked", 0),
            m.get("observer_uses", 0) +
            m.get("sentry_uses", 0)
        )

        apm = m.get("actions_per_min", 0)
        # Fallback for APM - use typical value
        if apm == 0:
            apm = 250  # default

        imp = calculate_imp(
            gpm,
            kda,
            utility,
            apm,
            role
        )

        game_history.append({
            "imp": imp,
            "hero_id": m.get("hero_id", 0)
        })

        total_gpm += gpm
        total_kills += kills
        total_deaths += deaths
        total_assists += assists
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
    tables = generate_report_text(role, user_stats)
    pro_text = tables["pro"]
    detailed_text = tables["detailed"]

    # График
    chart_image = await create_visual_chart(game_history)

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
            "UPDATE users SET analytics_cache = ?, analytics_updated_at = ? WHERE telegram_id = ?",
            (cache_data, datetime.now(timezone.utc).isoformat(), telegram_id)
        )
        logger.info(f"Saved analytics cache for {telegram_id}")
    except Exception as e:
        logger.warning(f"Failed to save analytics cache for {telegram_id}: {e}")

    return data

# =========================================================
# CHART
# =========================================================

async def create_visual_chart(history):
    global _CHART_BG_CACHE
    try:
        import numpy as np
        import matplotlib
        matplotlib.use("Agg")

        import matplotlib.pyplot as plt
        import matplotlib.patheffects as pe

        from matplotlib.offsetbox import (
            OffsetImage,
            AnnotationBbox
        )

        from PIL import Image

    except ImportError:
        logger.warning("matplotlib not available, skipping chart generation")
        return None

    try:
        from scipy.interpolate import make_interp_spline
        from scipy.ndimage import gaussian_filter1d
    except ImportError:
        make_interp_spline = None
        gaussian_filter1d = None

    # =====================================================
    # CANVAS SIZE EXACTLY 1200x800
    # =====================================================

    WIDTH = 1200
    HEIGHT = 800

    DPI = 72

    FIG_W = WIDTH / DPI
    FIG_H = HEIGHT / DPI

    # =====================================================
    # LOAD BACKGROUND (cached to avoid blocking)
    # =====================================================

    global _CHART_BG_CACHE
    background_url = (
        "https://i.ibb.co/jkTWqcHn/"
        "pngdsadsad.png"
    )

    if _CHART_BG_CACHE is None:
        try:
            from database import get_aiohttp_session
            session = await get_aiohttp_session()
            async with session.get(background_url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    content = await resp.read()
                    _CHART_BG_CACHE = Image.open(io.BytesIO(content)).convert("RGB")
                    _CHART_BG_CACHE = _CHART_BG_CACHE.resize((WIDTH, HEIGHT), Image.LANCZOS)
                else:
                    raise Exception(f"Failed to load background: {resp.status}")
        except Exception as e:
            logger.warning(f"Could not load background image, using fallback: {e}")
            _CHART_BG_CACHE = Image.new("RGB", (WIDTH, HEIGHT), (20, 20, 30))

    bg = _CHART_BG_CACHE

    # =====================================================
    # PREPARE DATA
    # =====================================================

    raw_impacts = [
        round(g["imp"], 2)
        for g in history[:10]
    ]

    while len(raw_impacts) < 10:
        raw_impacts.append(0.4)

    raw_impacts = raw_impacts[:10]

# =====================================================
    # FORCE BIGGER MOVEMENT
    # =====================================================

    # old values compressed graph too much
    # now remap into full 0.2 → 1.8 range
    min_imp = min(raw_impacts)
    max_imp = max(raw_impacts)

    impacts = []

    for value in raw_impacts:
        normalized = (
            (value - min_imp)
            / max(max_imp - min_imp, 0.01)
        )

        scaled = 0.25 + (normalized * 1.45)

        impacts.append(round(scaled, 2))

    x = np.arange(1, 11)

    avg = np.mean(impacts)

    # =====================================================
    # SMOOTH INTERPOLATION - optimized for speed
    # =====================================================

    if make_interp_spline and len(impacts) >= 4:
        x_smooth = np.linspace(1, 10, 100)
        spl = make_interp_spline(x, impacts, k=3)
        y_smooth = spl(x_smooth)
    else:
        x_smooth = x
        y_smooth = impacts

    # =====================================================
    # FIGURE
    # =====================================================

    fig = plt.figure(
        figsize=(FIG_W, FIG_H),
        dpi=DPI
    )

    # FULL SIZE AXIS
    ax = plt.axes([0, 0, 1, 1])

    fig.patch.set_facecolor("#000000")

    # =====================================================
    # FULL BACKGROUND
    # =====================================================

    ax.imshow(
        bg,
        extent=[0, 11, 0, 2],
        aspect='auto',
        interpolation='bilinear',
        alpha=1.0,
        zorder=0
    )

    # =====================================================
    # UNDER GRAPH AREA
    # =====================================================

    ax.fill_between(
        x_smooth,
        y_smooth,
        np.min(y_smooth),
        color="#f4c430",
        alpha=0.50,
        zorder=3
    )

    # =====================================================
    # MAIN GRAPH LINE
    # =====================================================

    line = ax.plot(
        x_smooth,
        y_smooth,
        color="#f4c430",
        linewidth=6,
        solid_capstyle='round',
        zorder=5
    )[0]

    line.set_path_effects([
        pe.Stroke(
            linewidth=12,
            foreground="#ff8800",
            alpha=0.40
        ),
        pe.Normal()
    ])

    # =====================================================
    # GRAPH POINTS
    # =====================================================

    ax.scatter(
        x,
        impacts,
        s=200,
        color="#ffd54f",
        edgecolors="#fff2a8",
        linewidths=2.5,
        zorder=6
    )

    # =====================================================
    # AVG LINE
    # =====================================================

    ax.axhline(
        avg,
        linestyle=(0, (5, 5)),
        color="#e0e0e0",
        linewidth=3.0,
        alpha=0.80,
        zorder=4
    )

    ax.text(
        9.7,
        avg,
        f"AVG {avg:.2f}",
        fontsize=20,
        color="white",
        weight="bold",
        va="center",
        zorder=10
    )

    # =====================================================
    # HEROES - parallel preload
    # =====================================================

    # Collect unique hero IDs first
    unique_hero_ids = list({g["hero_id"] for g in history[:10] if g.get("hero_id")})
    
    # Load all hero icons in parallel
    hero_icons = await asyncio.gather(*[get_hero_icon(hid) for hid in unique_hero_ids])
    hero_icon_map = {hid: icon for hid, icon in zip(unique_hero_ids, hero_icons)}
    
    for idx, g in enumerate(history[:10]):
        hero_id = g["hero_id"]
        hero_img = hero_icon_map.get(hero_id)

        if not hero_img:
            continue

        imp = impacts[idx]

        # =================================================
        # BORDER COLORS
        # =================================================

        if imp >= 1.0:
            border = "#00ff66"

        elif imp >= 0.6:
            border = "#ffd000"

        else:
            border = "#ff3b3b"

        # =================================================
        # HERO IMAGE EXACT SIZE
        # =================================================

        hero_img = hero_img.resize(
            (72, 72),
            Image.LANCZOS
        )

        imagebox = OffsetImage(
            hero_img,
            zoom=0.72
        )

        ab = AnnotationBbox(
            imagebox,
            (idx + 1, imp),
            frameon=True,
            bboxprops=dict(
                edgecolor=border,
                linewidth=4,
                boxstyle="circle,pad=0.12",
                facecolor="none",
                alpha=1.0
            ),
            zorder=10
        )

        ax.add_artist(ab)

        # =================================================
        # GLOW
        # =================================================

        ax.scatter(
            idx + 1,
            imp,
            s=1800,
            color=border,
            alpha=0.15,
            zorder=8
        )

    # =====================================================
    # AXES
    # =====================================================

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

    # =====================================================
    # GRID
    # =====================================================

    ax.grid(
        axis="y",
        color="white",
        alpha=0.08,
        linewidth=1
    )

    # =====================================================
    # REMOVE BORDERS
    # =====================================================

    for spine in ax.spines.values():
        spine.set_visible(False)

    # =====================================================
    # SAVE EXACTLY 1200x800
    # =====================================================

    buf = io.BytesIO()

    plt.savefig(
        buf,
        format="png",
        dpi=DPI,
        facecolor=fig.get_facecolor(),
        bbox_inches=None,
        pad_inches=0
    )

    plt.close(fig)

    buf.seek(0)

    return buf.getvalue()