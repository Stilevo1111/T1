# weekly_analytics.py - Еженедельная аналитика игрока

import asyncio
import io
import json
import logging
import numpy as np
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

    # Create figure with specified dimensions
    fig, ax = plt.subplots(
        figsize=(12, 8),  # 1200x800 at 100 DPI
        dpi=100
    )

    # Create gradient background
    gradient = np.linspace(0, 1, 256).reshape(1, -1)
    gradient = np.vstack((gradient, gradient))

    # Dark green to brown gradient
    from matplotlib.colors import LinearSegmentedColormap
    cmap = LinearSegmentedColormap.from_list("custom", ["#0a1f0f", "#2c1f14"])
    ax.imshow(gradient, extent=[0, 1, 0, 1], aspect='auto',
              cmap=cmap, alpha=1.0, zorder=-10,
              transform=ax.transAxes)

    fig.patch.set_facecolor("#0a1f0f")
    ax.set_facecolor("none")  # Transparent to show gradient

    # Plot the main line with glow effect
    line = ax.plot(
        x,
        impacts,
        linewidth=6,
        color="#f4c430",
        solid_capstyle='round'
    )[0]

    # Add glow effect
    line.set_path_effects([
        matplotlib.patheffects.Stroke(linewidth=10, foreground="#f4c430", alpha=0.3),
        matplotlib.patheffects.Normal()
    ])

    # Fill area under the curve
    ax.fill_between(x, impacts, 0, color="#8B4513", alpha=0.3)

    # Calculate average
    avg_value = sum(impacts) / len(impacts)

    # Add dashed average line
    ax.axhline(
        y=avg_value,
        color="#CCCCCC",
        linestyle="--",
        linewidth=2,
        alpha=0.7
    )

    # Add average text
    ax.text(
        len(x) - 0.5, avg_value + 0.05,
        f"AVG {avg_value:.2f}",
        color="#CCCCCC",
        fontsize=12,
        fontweight="bold",
        ha="right",
        va="bottom",
        bbox=dict(boxstyle="round,pad=0.3", facecolor="#1a1a1a", alpha=0.8)
    )

    # Get hero icons
    tasks = [
        get_hero_icon(g["hero_id"])
        for g in history
    ]

    icons = await asyncio.gather(*tasks)

    # Color mapping based on performance
    max_imp = max(impacts)
    min_imp = min(impacts)
    mid_imp = (max_imp + min_imp) / 2

    for idx, icon in enumerate(icons):

        if not icon:
            continue

        imp = history[idx]["imp"]

        # Determine border color based on performance
        if imp >= mid_imp + (max_imp - mid_imp) * 0.3:  # Top performers
            border_color = "#00FF00"  # Green
        elif imp <= mid_imp - (mid_imp - min_imp) * 0.3:  # Poor performers
            border_color = "#FF0000"  # Red
        else:  # Average performers
            border_color = "#FFFF00"  # Yellow

        # Special case for point 10 (last point)
        if idx == len(icons) - 1:
            border_color = "#FF0000"  # Red for the last point

        img = icon.resize((64, 64))

        # Create circular mask
        from PIL import ImageDraw
        mask = Image.new("L", (64, 64), 0)
        draw = ImageDraw.Draw(mask)
        draw.ellipse((0, 0, 64, 64), fill=255)

        # Create circular icon with border
        bordered_icon = Image.new("RGBA", (72, 72), (0, 0, 0, 0))
        icon_draw = ImageDraw.Draw(bordered_icon)

        # Draw border circle
        icon_draw.ellipse((0, 0, 72, 72), outline=border_color, width=3)
        # Draw inner circle for icon
        icon_draw.ellipse((4, 4, 68, 68), fill=(0, 0, 0, 255))

        # Paste icon with circular mask
        bordered_icon.paste(img, (4, 4), mask)

        # Add glow effect to border
        glow_icon = Image.new("RGBA", (80, 80), (0, 0, 0, 0))
        glow_draw = ImageDraw.Draw(glow_icon)
        glow_draw.ellipse((0, 0, 80, 80), outline=border_color, width=1)
        glow_draw.ellipse((1, 1, 79, 79), outline=border_color, width=1)

        # Composite glow under main icon
        final_icon = Image.new("RGBA", (80, 80), (0, 0, 0, 0))
        final_icon.paste(glow_icon, (0, 0))
        final_icon.paste(bordered_icon, (4, 4), bordered_icon)

        ax.imshow(
            final_icon,
            extent=(
                idx + 1 - 0.2,
                idx + 1 + 0.2,
                imp - 0.08,
                imp + 0.08
            ),
            zorder=15
        )

    # Configure axes
    ax.set_xlim(0.5, len(x) + 0.5)
    ax.set_ylim(0, max(2.0, max(impacts) + 0.2))

    # Set ticks and labels
    ax.set_xticks(x)
    ax.set_xticklabels([str(i) for i in x], color="#CCCCCC", fontsize=12, fontweight="bold")
    ax.set_yticks([0, 0.5, 1.0, 1.5, 2.0])
    ax.set_yticklabels(["0", "0.5", "1.0", "1.5", "2.0"], color="#CCCCCC", fontsize=12, fontweight="bold")

    # Add grid
    ax.grid(axis='y', color="#333333", linestyle="-", linewidth=0.5, alpha=0.3)

    # Remove spines
    for spine in ax.spines.values():
        spine.set_visible(False)

    # Set layout
    plt.tight_layout()

    buf = io.BytesIO()

    plt.savefig(
        buf,
        format="png",
        bbox_inches="tight",
        facecolor=fig.get_facecolor(),
        dpi=100
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