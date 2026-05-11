# weekly_analytics.py - Еженедельная аналитика игрока (fixed version)

import asyncio
import aiohttp
from PIL import Image, ImageDraw, ImageFont
import io
from datetime import datetime, timezone, timedelta
import requests

from dota_mmr import steam64_to_account_id, OPENDOTA_API_URL, _api_get_async
from database import get_user

import logging

logger = logging.getLogger(__name__)

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
            "deaths": 3.1,
            "h_dmg": 28.0,
            "t_dmg": 9.3,
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
            "deaths": 3.2,
            "h_dmg": 32.0,
            "t_dmg": 4.5,
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
            "deaths": 3.8,
            "h_dmg": 24.5,
            "t_dmg": 6.2,
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
            "deaths": 4.8,
            "h_dmg": 12.0,
            "t_dmg": 0.8,
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

async def get_hero_icon(hero_id: int):

    heroes = await load_heroes()

    hero_name = heroes.get(hero_id)

    if hero_name:
        path = f"assets/heroes/{hero_name}.png"

        try:

            return Image.open(path).convert("RGBA")

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

    # SUPPORT
    if "Support" in roles or "Disabler" in roles:
        return "SUPPORT"

    # MID
    if "Nuker" in roles and "Escape" in roles:
        return "MID"

    # OFFLANE
    if "Durable" in roles and "Initiator" in roles:
        return "OFFLANE"

    # CARRY
    if "Carry" in roles:
        return "CARRY"

    return "SUPPORT"


async def detect_role_from_hero_counts(matches: list) -> str:
    await load_hero_roles()
    
    role_counts = {
        "CARRY": 0,
        "MID": 0,
        "OFFLANE": 0,
        "SUPPORT": 0
    }
    
    total_matches = len(matches)
    
    for m in matches:
        hero_id = m.get("hero_id", 0)
        hero_roles = _HERO_ROLE_CACHE.get(hero_id, [])
        role = convert_opendota_roles(hero_roles)
        role_counts[role] += 1
    
    if total_matches == 0:
        return "CARRY"
    
    dominant_role = max(role_counts, key=role_counts.get)
    dominant_count = role_counts[dominant_role]
    
    if dominant_count >= total_matches * 0.6:
        logger.info(f"ROLE BY HERO COUNT: {dominant_role} ({dominant_count}/{total_matches})")
        return dominant_role
    
    logger.info(f"ROLE BY HERO COUNT: no dominance ({role_counts})")
    return None


async def detect_role_from_history(matches: list):
    return await detect_role_from_hero_counts(matches) or "SUPPORT"


def calculate_player_stats(matches: list) -> dict:
    if not matches:
        return {"wr": 50.0, "gpm": 500, "xpm": 600, "deaths": 4.0, "h_dmg": 15.0, "t_dmg": 5.0, "util": 5.0, "apm": 250, "kda": "5/4/5"}
    n = len(matches)
    total_gpm = sum(m.get("gold_per_min", 0) for m in matches)
    total_xpm = sum(m.get("xp_per_min", 0) for m in matches)
    total_deaths = sum(m.get("deaths", 0) for m in matches)
    total_kills = sum(m.get("kills", 0) for m in matches)
    total_assists = sum(m.get("assists", 0) for m in matches)
    total_h_dmg = sum(m.get("hero_damage", 0) for m in matches)
    total_t_dmg = sum(m.get("tower_damage", 0) for m in matches)
    total_apm = sum(m.get("actions_per_min", 0) for m in matches)
    total_stuns = sum(m.get("stuns", 0) for m in matches)
    total_heals = sum(m.get("hero_healing", 0) for m in matches)
    total_wins = sum(1 for m in matches if m.get("win", False))
    return {
        "wr": round(total_wins / n * 100, 1),
        "gpm": round(total_gpm / n, 1),
        "xpm": round(total_xpm / n, 1),
        "deaths": round(total_deaths / n, 1),
        "h_dmg": round(total_h_dmg / n / 1000, 1),
        "t_dmg": round(total_t_dmg / n / 1000, 1),
        "util": round((total_stuns * 0.3 + total_heals / 1000) / n, 1),
        "apm": round(total_apm / n, 0),
        "kda": f"{round(total_kills/n)}/{round(total_deaths/n)}/{round(total_assists/n)}"
    }


# =========================================================
# MATCH DETAILS
# =========================================================



# =========================================================
# MATCHES
# =========================================================

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
        params={"limit": 20},
        timeout=10
    )

    if not matches:
        return []

    week_start = (
        datetime.now(timezone.utc)
        - timedelta(days=7)
    )

    filtered = []

    for m in matches:

        ts = m.get("start_time", 0)

        match_time = datetime.fromtimestamp(
            ts,
            tz=timezone.utc
        )

        if match_time < week_start:
            continue

        filtered.append({
            "hero_id": m.get("hero_id", 0),
            "kills": m.get("kills", 0),
            "deaths": m.get("deaths", 0),
            "assists": m.get("assists", 0),
            "gold_per_min": m.get("gold_per_min", 0),
            "xp_per_min": m.get("xp_per_min", 0),
            "last_hits": m.get("last_hits", 0),
            "hero_damage": m.get("hero_damage", 0),
            "tower_damage": m.get("tower_damage", 0),
            "lane_role": m.get("lane_role", 0),
            "start_time": ts,
            "win": m.get("radiant_win", False),
            "denies": m.get("denies", 0),
            "actions_per_min": m.get("actions_per_min", 0),
            "stuns": m.get("stuns", 0),
            "hero_healing": m.get("hero_healing", 0),
            "creeps_stacked": m.get("creeps_stacked", 0),
            "observer_uses": m.get("observer_uses", 0),
            "sentry_uses": m.get("sentry_uses", 0)
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

    # Таблица 1: Сравнение с PRO игроками
    t1 = "```\n"
    t1 += "PLAYER       WR   GPM   KDA\n"
    t1 += "----------------------------\n"
    for name, s in db["players"].items():
        t1 += (
            f"{name:<11}"
            f"{s['wr']:>3}% "
            f"{s['gpm']:>5} "
            f"{s['kda']}\n"
        )
    t1 += "----------------------------\n"
    t1 += (
        f"{'YOU':<11}"
        f"{user_stats['wr']:>3}% "
        f"{int(user_stats['gpm']):>5} "
        f"{user_stats['kda']}\n"
    )
    t1 += "```"

    # Таблица 2: Детальное сравнение
    t2 = "```\n"
    t2 += "Метрика          Ты      PRO      Δ \n"
    t2 += "------------------------------------\n"
    bench = db["benchmarks"]
    metrics = [
        ("GPM", user_stats['gpm'], bench['gpm']),
        ("XPM", user_stats['xpm'], bench['xpm']),
        ("Deaths", user_stats['deaths'], bench['deaths']),
        ("Hero DMG", user_stats['h_dmg'], bench['h_dmg']),
        ("Tower DMG", user_stats['t_dmg'], bench['t_dmg']),
        ("Utility", user_stats['util'], bench['utility']),
        ("APM", user_stats['apm'], bench['apm'])
    ]
    for label, u, p in metrics:
        diff = u - p
        is_bad = diff > 0 if "Deaths" in label else diff < 0
        arrow = "↓" if is_bad else "↑"
        u_str = f"{u:.1f}k" if "DMG" in label else f"{u:.1f}"
        p_str = f"{p:.1f}k" if "DMG" in label else f"{p:.1f}"
        t2 += f"{label:<14} {u_str:>6} {p_str:>8} {arrow:>4}\n"
    t2 += "```"

    header = escape_markdown_v2(f"📊 ANALYTICS ({role})")

    text = f"{header}\n\n{escape_markdown_v2(t1)}"

    header_detailed = escape_markdown_v2(f"🔍 Детальное сравнение")

    text_detailed = f"{header_detailed}\n\n{escape_markdown_v2(t2)}"

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
        {"title": "🆚 Сравнение с ПРО", "text": pro_text},
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
            chart = await create_visual_chart(cached.get("history", []))
            return {"image": chart, "history": cached.get("history", [])}

    matches = await get_weekly_matches(telegram_id)

    if len(matches) < 5:
        return None

    matches = sorted(matches, key=lambda x: x.get("start_time", 0))

    # Calculate only what's needed for chart
    game_history = []
    for m in matches[:10]:
        gpm = m.get("gold_per_min", 0)
        kills = m.get("kills", 0)
        deaths = m.get("deaths", 0)
        assists = m.get("assists", 0)
        kda = (kills + assists) / max(deaths, 1)
        
        utility = calculate_utility(
            m.get("stuns", 0),
            m.get("hero_healing", 0),
            m.get("creeps_stacked", 0),
            m.get("observer_uses", 0) + m.get("sentry_uses", 0)
        )
        apm = m.get("actions_per_min", 0)
        
        imp = calculate_imp(gpm, kda, utility, apm, "CARRY")
        
        game_history.append({"imp": imp, "hero_id": m.get("hero_id", 0)})

    chart = await create_visual_chart(game_history)
    return {"image": chart, "history": game_history, "matches": matches}


async def generate_weekly_analytics(telegram_id: int):

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
    total_lh = 0
    total_apm = 0
    total_denies = 0
    total_xpm = 0
    total_h_dmg = 0
    total_t_dmg = 0
    total_utility = 0
    total_wins = 0

    game_history = []

    for m in matches:

        gpm = m.get("gold_per_min", 0)

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
        total_lh += m.get("last_hits", 0)
        total_apm += apm
        total_denies += m.get("denies", 0)
        total_xpm += m.get("xp_per_min", 0)
        total_h_dmg += m.get("hero_damage", 0)
        total_t_dmg += m.get("tower_damage", 0)
        total_utility += utility

        if m.get("win", False):
            total_wins += 1

    logger.info(f"User {telegram_id} totals: gpm={total_gpm}, lh={total_lh}, denies={total_denies}, kills={total_kills}, deaths={total_deaths}, assists={total_assists}, wins={total_wins}, match_count={len(matches)}")

    match_count = len(matches)

    avg_gpm = total_gpm / match_count
    avg_lh = total_lh / match_count
    avg_apm = total_apm / match_count
    avg_denies = total_denies / match_count
    avg_xpm = total_xpm / match_count
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
    try:
        import io
        import numpy as np
        import matplotlib
        matplotlib.use("Agg")

        import matplotlib.pyplot as plt
        import matplotlib.patheffects as pe

        from matplotlib.offsetbox import (
            OffsetImage,
            AnnotationBbox
        )

        import requests

        from PIL import Image

        from io import BytesIO
    except ImportError:
        logger.warning("matplotlib not available, skipping chart generation")
        return None

    # =====================================================
    # CANVAS SIZE EXACTLY 1200x800
    # =====================================================

    WIDTH = 1200
    HEIGHT = 800

    DPI = 100

    FIG_W = WIDTH / DPI
    FIG_H = HEIGHT / DPI

    # =====================================================
    # LOAD BACKGROUND
    # =====================================================

    background_url = (
        "https://i.ibb.co/jkTWqcHn/"
        "pngdsadsad.png"
    )

    response = requests.get(background_url)

    bg = Image.open(
        BytesIO(response.content)
    ).convert("RGB")

    # EXACT SIZE
    bg = bg.resize(
        (WIDTH, HEIGHT),
        Image.LANCZOS
    )

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

    avg = 0.61

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
        x,
        impacts,
        min(impacts),
        color="#f4c430",
        alpha=0.50,
        zorder=3
    )

    # =====================================================
    # MAIN GRAPH LINE
    # =====================================================

    line = ax.plot(
        x,
        impacts,
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
        linewidth=1.8,
        alpha=0.80,
        zorder=4
    )

    ax.text(
        0.3,
        avg,
        "AVG 0.61",
        fontsize=20,
        color="white",
        weight="bold",
        va="center",
        zorder=10
    )

    # =====================================================
    # HEROES
    # =====================================================

    for idx, g in enumerate(history[:10]):

        hero_img = await get_hero_icon(
            g["hero_id"]
        )

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
                facecolor="#111111",
                alpha=0.95
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
            s=2200,
            color=border,
            alpha=0.10,
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