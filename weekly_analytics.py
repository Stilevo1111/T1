# weekly_analytics.py - Еженедельная аналитика игрока

import asyncio
import io
import json
import logging
from datetime import datetime, timezone, timedelta

import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt
import matplotlib.patheffects as pe

from PIL import Image

from dota_mmr import (
    steam64_to_account_id,
    OPENDOTA_API_URL,
    _api_get_async
)

from database import get_user, Database

logger = logging.getLogger(__name__)

# =========================================================
# HERO CACHE
# =========================================================

_HERO_NAME_CACHE = {}

# =========================================================
# PRO DATABASE
# =========================================================

PRO_DB = {
    "CARRY": {
        "benchmarks": {
            "gpm": 730,
            "xpm": 820,
            "deaths": 3.0,
            "kda": 5.5,
            "apm": 300,
            "utility": 8
        }
    },
    "MID": {
        "benchmarks": {
            "gpm": 700,
            "xpm": 850,
            "deaths": 3.2,
            "kda": 5.2,
            "apm": 340,
            "utility": 5
        }
    },
    "OFFLANE": {
        "benchmarks": {
            "gpm": 590,
            "xpm": 680,
            "deaths": 4.0,
            "kda": 4.3,
            "apm": 280,
            "utility": 10
        }
    },
    "SUPPORT": {
        "benchmarks": {
            "gpm": 380,
            "xpm": 480,
            "deaths": 5.0,
            "kda": 3.5,
            "apm": 240,
            "utility": 16
        }
    }
}

# =========================================================
# ROLE DETECTION
# =========================================================

async def detect_role(matches):

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
        assists = m.get("assists", 0)
        kills = m.get("kills", 0)
        lane = m.get("lane_role", 0)

        if lane == 2:
            scores["MID"] += 4

        if lane == 3:
            scores["OFFLANE"] += 4

        if gpm >= 650:
            scores["CARRY"] += 3

        if lh >= 220:
            scores["CARRY"] += 2

        if assists > kills:
            scores["SUPPORT"] += 3

        if gpm <= 430:
            scores["SUPPORT"] += 2

    return max(scores, key=scores.get)

# =========================================================
# HEROES
# =========================================================

async def load_heroes():

    global _HERO_NAME_CACHE

    if _HERO_NAME_CACHE:
        return _HERO_NAME_CACHE

    url = f"{OPENDOTA_API_URL}/heroes"

    data = await _api_get_async(url)

    for h in data:
        _HERO_NAME_CACHE[h["id"]] = h["name"].replace(
            "npc_dota_hero_",
            ""
        )

    return _HERO_NAME_CACHE

# =========================================================
# HERO ICON
# =========================================================

async def get_hero_icon(hero_id):

    heroes = await load_heroes()

    hero_name = heroes.get(hero_id)

    if not hero_name:
        return None

    path = f"assets/heroes/{hero_name}.png"

    try:

        with Image.open(path) as img:
            return img.convert("RGBA")

    except Exception as e:

        logger.warning(f"Hero icon error: {e}")

        return None

# =========================================================
# GET MATCHES
# =========================================================

async def get_weekly_matches(telegram_id):

    user = get_user(telegram_id)

    if not user:
        return []

    steam_id = user.get("steam_id")

    if not steam_id:
        return []

    account_id = steam64_to_account_id(steam_id)

    url = f"{OPENDOTA_API_URL}/players/{account_id}/matches"

    matches = await _api_get_async(
        url,
        params={"limit": 20},
        timeout=15
    )

    if not matches:
        return []

    week_ago = datetime.now(timezone.utc) - timedelta(days=7)

    result = []

    for m in matches:

        ts = m.get("start_time", 0)

        dt = datetime.fromtimestamp(
            ts,
            tz=timezone.utc
        )

        if dt < week_ago:
            continue

        player_slot = m.get("player_slot", 0)

        radiant_win = m.get("radiant_win", False)

        is_radiant = player_slot < 128

        win = (
            (radiant_win and is_radiant)
            or
            (not radiant_win and not is_radiant)
        )

        result.append({
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
            "win": win
        })

        if len(result) >= 10:
            break

    return result

# =========================================================
# IMPACT
# =========================================================

def calculate_imp(stats, role):

    bench = PRO_DB[role]["benchmarks"]

    gpm_score = stats["gpm"] / bench["gpm"]
    xpm_score = stats["xpm"] / bench["xpm"]
    kda_score = stats["kda"] / bench["kda"]

    deaths_score = bench["deaths"] / max(stats["deaths"], 1)

    result = (
        gpm_score * 0.35 +
        xpm_score * 0.25 +
        kda_score * 0.25 +
        deaths_score * 0.15
    )

    return round(result, 2)

# =========================================================
# REPORTS
# =========================================================

def generate_report_text(role, stats):

    bench = PRO_DB[role]["benchmarks"]

    text = (
        f"📊 ANALYTICS ({role})\n\n"
        f"GPM: {stats['gpm']}\n"
        f"XPM: {stats['xpm']}\n"
        f"KDA: {stats['kda_string']}\n"
        f"Deaths: {stats['deaths']}\n"
        f"Winrate: {stats['wr']}%\n\n"
        f"======= PRO =======\n"
        f"GPM: {bench['gpm']}\n"
        f"XPM: {bench['xpm']}\n"
        f"KDA: {bench['kda']}\n"
    )

    return {
        "pro": text
    }

def generate_detailed_metrics_table(role, stats):

    bench = PRO_DB[role]["benchmarks"]

    metrics = [
        ("GPM", stats["gpm"], bench["gpm"]),
        ("XPM", stats["xpm"], bench["xpm"]),
        ("Deaths", stats["deaths"], bench["deaths"]),
        ("KDA", stats["kda"], bench["kda"]),
    ]

    text = "📈 DETAILED METRICS\n\n"

    for name, user_val, pro_val in metrics:

        diff = round(user_val - pro_val, 1)

        if name == "Deaths":
            better = diff <= 0
        else:
            better = diff >= 0

        status = "✅" if better else "❌"

        text += (
            f"{status} {name}\n"
            f"You: {user_val}\n"
            f"PRO: {pro_val}\n"
            f"Delta: {diff}\n\n"
        )

    return text

# =========================================================
# CHART
# =========================================================

async def create_visual_chart(history):

    impacts = [x["imp"] for x in history]

    if not impacts:
        return None

    x = list(range(1, len(impacts) + 1))

    fig, ax = plt.subplots(
        figsize=(10, 5),
        dpi=150
    )

    fig.patch.set_facecolor("#0f0f0f")
    ax.set_facecolor("#0f0f0f")

    ax.plot(
        x,
        impacts,
        linewidth=4,
        color="#ffb000"
    )

    tasks = [
        get_hero_icon(g["hero_id"])
        for g in history
    ]

    icons = await asyncio.gather(*tasks)

    for idx, icon in enumerate(icons):

        if not icon:
            continue

        imp = history[idx]["imp"]

        img = icon.resize((48, 48))

        ax.imshow(
            img,
            extent=(
                idx + 1 - 0.15,
                idx + 1 + 0.15,
                imp - 0.06,
                imp + 0.06
            ),
            zorder=10
        )

    ax.set_xticks([])
    ax.set_yticks([])

    for spine in ax.spines.values():
        spine.set_visible(False)

    plt.tight_layout()

    buf = io.BytesIO()

    plt.savefig(
        buf,
        format="png",
        bbox_inches="tight",
        facecolor=fig.get_facecolor()
    )

    plt.close(fig)

    buf.seek(0)

    return buf.getvalue()

# =========================================================
# MAIN
# =========================================================

async def generate_weekly_analytics(telegram_id):

    user = get_user(telegram_id)

    if not user:
        return None

    try:

        if user.get("analytics_cache"):

            updated = user.get("analytics_updated_at")

            if updated:

                if isinstance(updated, str):

                    updated = datetime.fromisoformat(updated)

                delta = (
                    datetime.now(timezone.utc) - updated
                ).total_seconds()

                if delta < 3600:

                    cache = json.loads(
                        user["analytics_cache"]
                    )

                    chart = await create_visual_chart(
                        cache["history"]
                    )

                    cache["image"] = chart

                    return cache

    except Exception as e:

        logger.warning(f"Cache error: {e}")

    matches = await get_weekly_matches(
        telegram_id
    )

    if len(matches) < 5:
        return None

    role = await detect_role(matches)

    total_gpm = 0
    total_xpm = 0
    total_kills = 0
    total_deaths = 0
    total_assists = 0
    total_wins = 0

    history = []

    for m in matches:

        kills = m["kills"]
        deaths = m["deaths"]
        assists = m["assists"]

        kda = (
            (kills + assists)
            / max(deaths, 1)
        )

        imp = calculate_imp({
            "gpm": m["gold_per_min"],
            "xpm": m["xp_per_min"],
            "kda": kda,
            "deaths": deaths
        }, role)

        history.append({
            "hero_id": m["hero_id"],
            "imp": imp
        })

        total_gpm += m["gold_per_min"]
        total_xpm += m["xp_per_min"]
        total_kills += kills
        total_deaths += deaths
        total_assists += assists

        if m["win"]:
            total_wins += 1

    count = len(matches)

    avg_kda = (
        (total_kills + total_assists)
        / max(total_deaths, 1)
    )

    stats = {
        "gpm": round(total_gpm / count, 1),
        "xpm": round(total_xpm / count, 1),
        "deaths": round(total_deaths / count, 1),
        "kda": round(avg_kda, 2),
        "wr": round((total_wins / count) * 100, 1),
        "kda_string":
            f"{round(total_kills / count,1)}/"
            f"{round(total_deaths / count,1)}/"
            f"{round(total_assists / count,1)}"
    }

    image = await create_visual_chart(
        history
    )

    result = {
        "image": image,
        "role": role,
        "stats": stats,
        "history": history
    }

    try:

        db = Database()

        cache_data = json.dumps({
            "role": role,
            "stats": stats,
            "history": history
        })

        db.execute_query(
            """
            UPDATE users
            SET analytics_cache = ?,
                analytics_updated_at = ?
            WHERE telegram_id = ?
            """,
            (
                cache_data,
                datetime.now(
                    timezone.utc
                ).isoformat(),
                telegram_id
            )
        )

    except Exception as e:

        logger.warning(f"DB cache save error: {e}")

    return result