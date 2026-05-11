# weekly_analytics.py - Еженедельная аналитика игрока (fixed version)

import asyncio
import aiohttp
from PIL import Image, ImageDraw, ImageFont
import io
from datetime import datetime, timezone, timedelta

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


async def detect_role_from_history(matches: list):

    scores = {
        "CARRY": 0,
        "MID": 0,
        "OFFLANE": 0,
        "SUPPORT": 0
    }

    for m in matches:

        gpm = m.get("gold_per_min", 0)
        xpm = m.get("xp_per_min", 0)
        lh = m.get("last_hits", 0)

        kills = m.get("kills", 0)
        assists = m.get("assists", 0)

        lane = m.get("lane_role", 0)

        hero_damage = m.get(
            "hero_damage",
            0
        )

        # =========================
        # MID
        # =========================

        if lane == 2:
            scores["MID"] += 5

        if xpm >= 650:
            scores["MID"] += 2

        if hero_damage >= 25000:
            scores["MID"] += 1

        # =========================
        # CARRY
        # =========================

        if gpm >= 650:
            scores["CARRY"] += 3

        if lh >= 220:
            scores["CARRY"] += 2

        if kills > assists:
            scores["CARRY"] += 1

        # =========================
        # SUPPORT
        # =========================

        if assists > kills:
            scores["SUPPORT"] += 2

        if gpm <= 450:
            scores["SUPPORT"] += 2

        if lh <= 80:
            scores["SUPPORT"] += 2

        # =========================
        # OFFLANE
        # =========================

        if lane == 3:
            scores["OFFLANE"] += 4

        if assists >= kills:
            scores["OFFLANE"] += 1

        if 450 <= gpm <= 650:
            scores["OFFLANE"] += 1

    logger.info(f"ROLE SCORES: {scores}")

    return max(scores, key=scores.get)

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

    text = f"{header}\n\n{t1}"

    header_detailed = escape_markdown_v2(f"🔍 Детальное сравнение")

    text_detailed = f"{header_detailed}\n\n{t2}"

    return {"pro": text, "detailed": text_detailed}


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

    header = escape_markdown_v2(f"📈 DETAILED METRICS ({role})")
    feedback = escape_markdown_v2(f"🧠 AI FEEDBACK\n{feedback_text}")
    return f"{header}\n\n{table}\n\n{feedback}"


def get_analytics_pages(role: str, stats: dict) -> list:
    """Generate a list of analytics pages for pagination.

    Each page is a dict with 'title' and 'text' keys.
    Page 0: PRO comparison
    Page 1: Detailed comparison
    Page 2: Detailed metrics with AI feedback
    """
    tables = generate_report_text(role, stats)
    pro_text = tables["pro"]
    detailed_text = tables["detailed"]
    metrics_text = generate_detailed_metrics_table(role, stats)

    return [
        {"title": "🆚 Сравнение с ПРО", "text": pro_text},
        {"title": "🔍 Детальное сравнение", "text": detailed_text},
    ]


# =========================================================
# MAIN ANALYTICS
# =========================================================

async def generate_weekly_analytics(telegram_id: int):

    # Check cache
    from database import get_user, Database
    import json
    from datetime import datetime, timezone

    user = get_user(telegram_id)
    if user and user.get('analytics_cache') and user.get('analytics_updated_at'):
        updated_at = user['analytics_updated_at']
        if isinstance(updated_at, str):
            updated_at = datetime.fromisoformat(updated_at.replace('Z', '+00:00'))
        now = datetime.now(timezone.utc)
        if (now - updated_at).total_seconds() < 3600:  # 1 hour cache
            logger.info(f"Using cached analytics for {telegram_id}")
            cached = json.loads(user['analytics_cache'])
            # Regenerate image from cached history
            chart_image = await create_visual_chart(cached["history"])
            cached["image"] = chart_image
            return cached

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
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        import matplotlib.patheffects as pe
        from matplotlib.offsetbox import OffsetImage, AnnotationBbox
        import numpy as np
    except ImportError:
        logger.warning("matplotlib not available, skipping chart generation")
        return None

    impacts = [g["imp"] for g in history]

    if not impacts:
        return None

    x = list(range(1, len(impacts) + 1))

    avg_value = sum(impacts) / len(impacts)

    # Create figure 1200x800 (figsize=12, dpi=100)
    fig = plt.figure(figsize=(12, 8), dpi=100, facecolor="#0a1f0f")
    ax = fig.add_axes([0.08, 0.1, 0.87, 0.8])

    # Load background image - single URL
    bg_loaded = False
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://i.ibb.co/39KgbrCY/photo-2026-05-10-21-24-42.png",
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status == 200:
                    bg_data = await resp.read()
                    bg_image = Image.open(io.BytesIO(bg_data)).convert("RGBA")
                    # Place as cover (maintains aspect ratio, fills entire area)
                    ax.imshow(bg_image, aspect='auto', zorder=-10, extent=[0, 12, 0, 8])
                    bg_loaded = True
                    logger.info("Background loaded")
    except Exception as e:
        logger.warning(f"Background load failed: {e}")

    if not bg_loaded:
        ax.set_facecolor("#0a1f0f")

    ax.set_xlim(0.5, len(x) + 0.5)
    ax.set_ylim(0, max(2.0, max(impacts) + 0.5))

    # Fill under curve
    ax.fill_between(x, impacts, 0, color="#8B4513", alpha=0.3)

    # Smooth line with rounded caps
    line = ax.plot(x, impacts, linewidth=5, color="#f4c430", 
                   solid_capstyle='round', solid_joinstyle='round')[0]
    line.set_path_effects([
        matplotlib.patheffects.Stroke(linewidth=12, foreground="#f4c430", alpha=0.4),
        matplotlib.patheffects.Normal()
    ])

    # Average line
    ax.axhline(y=avg_value, color="#CCCCCC", linestyle="--", linewidth=2, alpha=0.7)

    # Average text
    ax.text(len(x) - 0.3, avg_value + 0.08, f"AVG {avg_value:.2f}",
            color="#CCCCCC", fontsize=12, fontweight="bold",
            ha="right", va="bottom",
            bbox=dict(boxstyle="round,pad=0.3", facecolor="#1a1a1a", alpha=0.8))

    # Load hero icons
    tasks = [get_hero_icon(g["hero_id"]) for g in history]
    icons = await asyncio.gather(*tasks)

    for idx, icon in enumerate(icons):
        if not icon:
            continue

        imp = history[idx]["imp"]

        if imp > avg_value + 0.2:
            border_color = "#00FF00"
        elif imp < avg_value - 0.2:
            border_color = "#FF0000"
        else:
            border_color = "#FFFF00"

        # Create circular icon (56x56) with thicker border and glow
        icon_img = icon.resize((56, 56))

        mask = Image.new("L", (56, 56), 0)
        mask_draw = ImageDraw.Draw(mask)
        mask_draw.ellipse((0, 0, 56, 56), fill=255)

        # Outer circle for border + glow (толще, с радиусом меньше)
        bordered = Image.new("RGBA", (72, 72), (0, 0, 0, 0))
        bd = ImageDraw.Draw(bordered)
        
        # Thicker border (width=4)
        bd.ellipse((0, 0, 72, 72), outline=border_color, width=4)
        bd.ellipse((4, 4, 68, 68), fill=(0, 0, 0, 255))
        bordered.paste(icon_img, (8, 8), mask)

        # Add glow effect
        glow = Image.new("RGBA", (88, 88), (0, 0, 0, 0))
        glow_draw = ImageDraw.Draw(glow)
        glow_draw.ellipse((0, 0, 88, 88), outline=border_color, width=2)
        glow_draw.ellipse((2, 2, 86, 86), outline=border_color, width=1)
        
        final = Image.new("RGBA", (88, 88), (0, 0, 0, 0))
        final.paste(glow, (0, 0))
        final.paste(bordered, (8, 8), bordered)

        offset = OffsetImage(final, zoom=1.0)
        ab = AnnotationBbox(offset, (idx + 1, imp), frameon=False, xycoords='data')
        ax.add_artist(ab)

    # Configure axes
    ax.set_xticks(x)
    ax.set_xticklabels([str(i) for i in x], color="#CCCCCC", fontsize=12, fontweight="bold")
    ax.set_yticks([0, 0.5, 1.0, 1.5, 2.0])
    ax.set_yticklabels(["0", "0.5", "1.0", "1.5", "2.0"], color="#CCCCCC", fontsize=12)

    ax.grid(axis='y', color="#333333", linestyle="-", linewidth=0.5, alpha=0.3)

    for spine in ax.spines.values():
        spine.set_visible(False)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor="#0a1f0f", dpi=100, pad_inches=0)
    plt.close(fig)
    buf.seek(0)

    return buf.getvalue()