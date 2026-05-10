# weekly_analytics.py - Еженедельная аналитика игрока (fixed version)

import asyncio
import aiohttp
import plotly.graph_objects as go
from PIL import Image, ImageDraw, ImageFont
import io
import base64
from datetime import datetime, timezone, timedelta

from dota_mmr import steam64_to_account_id, OPENDOTA_API_URL, _api_get_async
from database import get_user

import logging

logger = logging.getLogger(__name__)

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
            "lh10": 73.8,
            "deny10": 10.2,
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
            "lh10": 71.5,
            "deny10": 21.8,
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
            "lh10": 61.2,
            "deny10": 17.5,
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
            "lh10": 14.5,
            "deny10": 4.8,
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

# (Replaced by detect_role_from_history using OpenDota hero roles)

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

    from main import get_config, set_config

    cache_key = f"icon_{hero_id}"

    cached = get_config(cache_key)

    if cached:
        try:
            data = base64.b64decode(cached)
            return Image.open(io.BytesIO(data))
        except Exception:
            logger.exception("Failed decode cached icon")

    heroes = await load_heroes()

    hero_name = heroes.get(hero_id)

    if not hero_name:
        return None

    url = (
        "https://cdn.cloudflare.steamstatic.com/apps/dota2/images/"
        f"dota_react/heroes/icons/{hero_name}.png"
    )

    try:

        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=5) as resp:

                if resp.status == 200:

                    data = await resp.read()

                    encoded = base64.b64encode(data).decode()

                    set_config(cache_key, encoded)

                    return Image.open(io.BytesIO(data))

    except Exception:
        logger.exception("Failed load hero icon")

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


async def detect_role_from_history(matches: list) -> str:

    hero_roles = await load_hero_roles()

    role_scores = {
        "CARRY": 0,
        "MID": 0,
        "OFFLANE": 0,
        "SUPPORT": 0
    }

    for match in matches:

        hero_id = match.get("hero_id")
        gpm = match.get("gold_per_min", 0)
        xpm = match.get("xp_per_min", 0)
        lh = match.get("last_hits", 0)
        kills = match.get("kills", 0)
        assists = match.get("assists", 0)
        hero_dmg = match.get("hero_damage", 0)
        obs = match.get("observer_uses", 0)
        sen = match.get("sentry_uses", 0)
        lane = match.get("lane_role", 0)

        # Hero base role from OpenDota (2 points)
        od_roles = hero_roles.get(hero_id, [])
        predicted_role = convert_opendota_roles(od_roles)
        role_scores[predicted_role] += 2

        # Lane role (3 points, higher weight)
        if lane == 1:
            role_scores["CARRY"] += 3
        elif lane == 2:
            role_scores["MID"] += 3
        elif lane == 3:
            role_scores["OFFLANE"] += 3

        # Stat-based corrections (1 point)
        # MID
        if xpm >= 600 and hero_dmg >= 18000:
            role_scores["MID"] += 1

        # OFFLANE
        if hero_dmg >= 18000 and assists >= kills:
            role_scores["OFFLANE"] += 1

        # CARRY
        if gpm >= 650 and lh >= 220:
            role_scores["CARRY"] += 1

        # SUPPORT
        if obs + sen >= 10:
            role_scores["SUPPORT"] += 1
        if assists > kills and gpm < 450:
            role_scores["SUPPORT"] += 1

    logger.info(f"Role scores: {role_scores}")

    final_role = max(role_scores, key=role_scores.get)
    logger.info(f"Detected role: {final_role}")

    return final_role

# =========================================================
# MATCH DETAILS
# =========================================================

async def get_player_match_details(match_id: int, account_id: int) -> dict:
    """Fetch detailed match data and extract player's stats"""
    try:
        url = f"{OPENDOTA_API_URL}/matches/{match_id}"
        match_data = await _api_get_async(url, timeout=10)

        if not match_data or "players" not in match_data:
            return {}

        # Find the player's data in the match
        for player in match_data["players"]:
            if player.get("account_id") == account_id:
                return {
                    "gold_per_min": player.get("gold_per_min", 0),
                    "xp_per_min": player.get("xp_per_min", 0),
                    "last_hits": player.get("last_hits", 0),
                    "denies": player.get("denies", 0),
                    "hero_damage": player.get("hero_damage", 0),
                    "tower_damage": player.get("tower_damage", 0),
                    "actions_per_min": player.get("actions_per_min", 0),
                    "kills": player.get("kills", 0),
                    "deaths": player.get("deaths", 0),
                    "assists": player.get("assists", 0),
                    "win": 1 if player.get("win", 0) == 1 else 0,
                    "lane_role": player.get("lane_role", 0),
                    "observer_uses": player.get("observer_uses", 0),
                    "sentry_uses": player.get("sentry_uses", 0),
                    "stuns": player.get("stuns", 0.0),
                    "hero_healing": player.get("hero_healing", 0),
                    "creeps_stacked": player.get("creeps_stacked", 0),
                    "hero_id": player.get("hero_id", 0),
                    "start_time": match_data.get("start_time", 0)
                }

        return {}

    except Exception as e:
        logger.exception(f"Failed to get match details for {match_id}")
        return {}

# =========================================================
# MATCHES
# =========================================================

async def get_weekly_matches(telegram_id: int):

    user = get_user(telegram_id)

    if not user or not user.get("steam_id"):
        return []

    steam_id = user["steam_id"]

    account_id = steam64_to_account_id(steam_id)

    now = datetime.now(timezone.utc)

    week_start = now - timedelta(days=7)

    url = f"{OPENDOTA_API_URL}/players/{account_id}/matches"

    params = {
        "limit": 50,
        "sort": "-start_time"
    }

    matches = await _api_get_async(
        url,
        params,
        timeout=15
    )

    if not matches:
        return []

    weekly_matches = []

    for m in matches:

        match_time = datetime.fromtimestamp(
            m.get("start_time", 0),
            tz=timezone.utc
        )

        if match_time >= week_start:
            # Fetch detailed match data for the player
            match_details = await get_player_match_details(m["match_id"], account_id)
            if match_details:
                weekly_matches.append(match_details)

        if len(weekly_matches) >= 10:
            break

    return weekly_matches

# =========================================================
# REPORT TEXT
# =========================================================

def generate_report_text(role: str, user_stats: dict) -> dict:
    """Генерация текстовых таблиц в стиле референса"""

    db = PRO_DB.get(role, PRO_DB["CARRY"])

    # Таблица 1: Сравнение с PRO игроками
    t1 = "```\n"
    t1 += "PLAYER       WR   LH  DN   GPM   KDA\n"
    t1 += "--------------------------------------\n"
    for name, s in db["players"].items():
        t1 += (
            f"{name:<11}"
            f"{s['wr']:>3}% "
            f"{s['lh']:>4} "
            f"{s['deny']:>3} "
            f"{s['gpm']:>5} "
            f"{s['kda']}\n"
        )
    t1 += "--------------------------------------\n"
    t1 += (
        f"{'YOU':<11}"
        f"{user_stats['wr']:>3}% "
        f"{int(user_stats['lh10']):>4} "
        f"{int(user_stats['deny10']):>3} "
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
        ("LH@10", user_stats['lh10'], bench['lh10']),
        ("Denies@10", user_stats['deny10'], bench['deny10']),
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

    header_pro = f"📊 ANALYTICS \\({role}\\)"
    pro_full = f"{header_pro}\n\n{t1}"
    detailed_full = f"🔍 Детальное сравнение\n{t2}"

    return {"pro": pro_full, "detailed": detailed_full}


def generate_detailed_metrics_table(role: str, user_stats: dict) -> str:
    """Отдельная detailed metrics table для кнопки 'Детальное сравнение🔥'"""

    db = PRO_DB.get(role, PRO_DB["CARRY"])
    bench = db["benchmarks"]

    metrics = [
        ("GPM", user_stats["gpm"], bench["gpm"]),
        ("XPM", user_stats["xpm"], bench["xpm"]),
        ("Deaths", user_stats["deaths"], bench["deaths"]),
        ("Hero DMG", user_stats["h_dmg"], bench["h_dmg"]),
        ("Tower DMG", user_stats["t_dmg"], bench["t_dmg"]),
        ("Utility", user_stats["util"], bench["utility"]),
        ("APM", user_stats["apm"], bench["apm"]),
        ("Win Rate", user_stats["wr"], 60.0),
    ]

    table = "```\n"
    table += "METRIC         YOU      PRO      Δ      STATUS\n"
    table += "------------------------------------------------\n"

    for label, user_value, pro_value in metrics:
        diff = user_value - pro_value
        better = diff < 0 if label == "Deaths" else diff > 0
        arrow = "↑" if better else "↓"

        ratio = user_value / pro_value if pro_value > 0 else 1

        if ratio >= 1.10:
            status = "🔥 ELITE"
        elif ratio >= 0.95:
            status = "✅ GOOD"
        elif ratio >= 0.80:
            status = "⚠️ AVG"
        else:
            status = "❌ LOW"

        table += (
            f"{label:<14}"
            f"{user_value:>7.1f} "
            f"{pro_value:>8.1f} "
            f"{arrow:>4} "
            f"{status:<10}\n"
        )

    table += "```"

    feedback = []
    if user_stats["gpm"] < bench["gpm"] * 0.85:
        feedback.append("• Низкий GPM → улучшите фарминг и работу на линии")
    if user_stats["deaths"] > bench["deaths"] * 1.2:
        feedback.append("• Слишком много смертей → работайте над карточкой и позиционированием")
    if user_stats["apm"] < bench["apm"] * 0.85:
        feedback.append("• Низкий APM → участвуйте активнее в игровых моментах")
    if user_stats["util"] < bench["utility"] * 0.75:
        feedback.append("• Мало утилити → больше помощи команде \\(стаки, варды, контроли\\)")
    if not feedback:
        feedback.append("• Отличные показатели по сравнению с PRO-игроками")

    feedback_text = "\n".join(feedback)

    return f"📈 DETAILED METRICS \\({role}\\)\n\n{table}\n\n🧠 AI FEEDBACK\n{feedback_text}"


# =========================================================
# MAIN ANALYTICS
# =========================================================

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

        if m.get("win", 0) == 1:
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
        "lh10": round(avg_lh * 0.32, 1),
        "deny10": round(avg_denies * 0.55, 1),
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

    return {
        "image": chart_image,
        "pro_text": pro_text,
        "detailed_text": detailed_text,
        "role": role,
        "stats": user_stats
    }

# =========================================================
# CHART
# =========================================================

async def create_visual_chart(history: list, dates: list = None):

    impacts = [g["imp"] for g in history]

    if not impacts:
        return None

    n = len(history)

    avg_imp = sum(impacts) / len(impacts)

    fig = go.Figure()

    # =====================================================
    # BACKGROUND ZONES (symmetrical around 1.0)
    # =====================================================

    CENTER = 1.0

    # Red zone: 0 → 1.0
    fig.add_hrect(
        y0=0,
        y1=CENTER,
        fillcolor="rgba(239,68,68,0.10)",
        line_width=0
    )

    # Green zone: 1.0 → top
    fig.add_hrect(
        y0=CENTER,
        y1=max(1.8, max(impacts) + 0.2),
        fillcolor="rgba(34,197,94,0.10)",
        line_width=0
    )

    # Center line at IMP = 1.0
    fig.add_hline(
        y=CENTER,
        line_dash="solid",
        line_color="rgba(255,255,255,0.15)",
        line_width=2
    )

    # =====================================================
    # AVERAGE LINE
    # =====================================================

    fig.add_hline(
        y=avg_imp,
        line_dash="dash",
        line_color="rgba(255,255,255,0.35)",
        line_width=2
    )

    fig.add_annotation(
        x=n - 0.5,
        y=avg_imp + 0.015,
        text=f"AVG {avg_imp:.2f}",
        showarrow=False,
        font=dict(
            size=18,
            color="rgba(255,255,255,0.75)"
        )
    )

    # =====================================================
    # MAIN LINE GLOW
    # =====================================================

    fig.add_trace(
        go.Scatter(
            x=list(range(n)),
            y=impacts,
            mode="lines",
            line=dict(
                color="rgba(255,170,0,0.25)",
                width=16,
                shape="spline",
                smoothing=1.0
            ),
            hoverinfo="skip"
        )
    )

    # =====================================================
    # MAIN LINE
    # =====================================================

    fig.add_trace(
        go.Scatter(
            x=list(range(n)),
            y=impacts,
            mode="lines+markers",
            line=dict(
                color="#ffb000",
                width=6,
                shape="spline",
                smoothing=1.0
            ),
            marker=dict(
                size=10,
                color="#ffb000"
            ),
            fill="tozeroy",
            fillcolor="rgba(255,176,0,0.12)",
            hoverinfo="skip"
        )
    )

    # =====================================================
    # HERO ICONS WITH COLORED BORDERS & GLOW
    # =====================================================

    for i, g in enumerate(history):

        try:

            img = await get_hero_icon(g["hero_id"])

            if not img:
                continue

            imp = g["imp"]

            # Border color based on performance
            if imp >= 1.0:
                border = "#22c55e"  # green
            elif imp >= 0.8:
                border = "#f59e0b"  # orange
            else:
                border = "#ef4444"  # red

            # Glow effect (large transparent marker)
            fig.add_trace(
                go.Scatter(
                    x=[i],
                    y=[imp],
                    mode="markers",
                    marker=dict(
                        size=76,
                        color=border,
                        opacity=0.22
                    ),
                    hoverinfo="skip",
                    showlegend=False
                )
            )

            # Border ring (transparent fill, colored stroke)
            fig.add_trace(
                go.Scatter(
                    x=[i],
                    y=[imp],
                    mode="markers",
                    marker=dict(
                        size=60,
                        color="rgba(0,0,0,0)",
                        line=dict(
                            color=border,
                            width=8
                        )
                    ),
                    hoverinfo="skip",
                    showlegend=False
                )
            )

            # Hero icon
            fig.add_layout_image(
                dict(
                    source=img,
                    xref="x",
                    yref="y",
                    x=i,
                    y=imp,
                    sizex=0.56,
                    sizey=0.56,
                    xanchor="center",
                    yanchor="middle",
                    layer="above"
                )
            )

        except Exception:
            logger.exception("Hero image failed")

    # =====================================================
    # AXIS
    # =====================================================

    y_min = min(impacts)
    y_max = max(impacts)

    fig.update_layout(

        width=1200,
        height=800,

        template="plotly_dark",

        paper_bgcolor="#050505",
        plot_bgcolor="#050505",

        showlegend=False,

        margin=dict(
            t=40,
            b=40,
            l=40,
            r=40
        ),

        xaxis=dict(
            range=[-0.5, n - 0.5],
            tickmode="array",
            tickvals=list(range(n)),
            ticktext=[str(i + 1) for i in range(n)],
            showgrid=False,
            zeroline=False,
            title=None,
            tickfont=dict(
                size=20,
                color="rgba(255,255,255,0.8)"
            )
        ),

        yaxis=dict(
            range=[
                0,
                max(2.0, y_max + 0.2)
            ],
            showgrid=True,
            gridcolor="rgba(255,255,255,0.05)",
            zeroline=False,
            title=None,
            tickfont=dict(
                size=18,
                color="rgba(255,255,255,0.65)"
            )
        )
    )

    # =====================================================
    # EXPORT
    # =====================================================

    img_bytes = await asyncio.to_thread(
        fig.to_image,
        format="png",
        engine="kaleido",
        scale=2
    )

    out = io.BytesIO(img_bytes)

    return out.getvalue()