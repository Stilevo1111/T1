# weekly_analytics.py - Еженедельная аналитика игрока (без ИИ, математические формулы)
import asyncio
import aiohttp
import requests
import plotly.graph_objects as go
from PIL import Image, ImageDraw, ImageFont
import io
import os
from datetime import datetime, timezone, timedelta
from dota_mmr import steam64_to_account_id, OPENDOTA_API_URL, _api_get_async
from database import get_user
import logging

logger = logging.getLogger(__name__)

# Конфигурация
ASSETS_DIR = "assets/heroes"
os.makedirs(ASSETS_DIR, exist_ok=True)

# PRO-бенчмарки (средние значения по ролям)
PRO_DATA = {
    "CARRY": {
        "players": ["Yatoro", "Ame", "Skiter", "Nightfall", "Pure"],
        "gpm": 750,
        "kda": 5.5,
        "lh": 78,
        "apm": 320,
        "utility": 400
    },
    "MID": {
        "players": ["Malr1ne", "Quinn", "Nisha", "gpk", "SumaiL"],
        "gpm": 700,
        "kda": 4.8,
        "lh": 72,
        "apm": 350,
        "utility": 800
    },
    "OFFLANE": {
        "players": ["Collapse", "33", "Ace", "ATF", "Wisper"],
        "gpm": 580,
        "kda": 4.2,
        "lh": 60,
        "apm": 300,
        "utility": 1500
    },
    "SUPPORT": {
        "players": ["Miposhka", "Save-", "Sneyking", "Puppey", "Fishman"],
        "gpm": 380,
        "kda": 3.5,
        "lh": 15,
        "apm": 280,
        "utility": 4500
    }
}

# Весовые коэффициенты для IMP
IMP_WEIGHTS = {
    "CARRY": {"gpm": 0.4, "kda": 0.3, "utility": 0.1, "apm": 0.2},
    "SUPPORT": {"gpm": 0.1, "kda": 0.3, "utility": 0.4, "apm": 0.2},
    "MID": {"gpm": 0.35, "kda": 0.35, "utility": 0.15, "apm": 0.15},
    "OFFLANE": {"gpm": 0.3, "kda": 0.3, "utility": 0.2, "apm": 0.2}
}


def detect_role(match_data: dict) -> str:
    """Определяет роль игрока по данным матча"""
    lane_role = match_data.get("lane_role", 0)
    gpm = match_data.get("gold_per_min", 0)
    hero_damage = match_data.get("hero_damage", 0)

    if lane_role == 1 and gpm > 600 and hero_damage > 15000:
        return "CARRY"
    elif lane_role == 2 and gpm > 650:
        return "MID"
    elif lane_role == 3 and hero_damage > 10000:
        return "OFFLANE"
    elif (lane_role == 4 or lane_role == 5) and hero_damage < 8000:
        return "SUPPORT"
    else:
        return "UNIVERSAL"


def calculate_utility(stuns: float = 0, heals: float = 0, stacks: int = 0, wards: int = 0) -> float:
    """Расчёт Utility по формуле"""
    return (stuns * 0.5) + (heals * 0.01) + (stacks * 150) + (wards * 50)


def calculate_imp(gpm: float, kda: float, utility: float, apm: float, role: str) -> float:
    """Расчёт Индекса Импакта (IMP)"""
    if role not in PRO_DATA:
        role = "CARRY"  # Default

    pro = PRO_DATA[role]
    weights = IMP_WEIGHTS[role]

    p_gpm = gpm / pro["gpm"] if pro["gpm"] > 0 else 0
    p_kda = kda / pro["kda"] if pro["kda"] > 0 else 0
    p_utility = utility / pro["utility"] if pro["utility"] > 0 else 0
    p_apm = apm / pro["apm"] if pro["apm"] > 0 else 0

    imp = (p_gpm * weights["gpm"]) + (p_kda * weights["kda"]) + (p_utility * weights["utility"]) + (p_apm * weights["apm"])
    return round(imp, 2)


def compare_with_pro(player_stats: dict, role: str) -> dict:
    """Сравнение с PRO-бенчмарками"""
    if role not in PRO_DATA:
        return {"error": "Unknown role"}

    pro = PRO_DATA[role]
    result = {}

    for metric in ["gpm", "kda", "lh", "apm", "utility"]:
        player_val = player_stats.get(metric, 0)
        pro_val = pro.get(metric, 0)
        if pro_val > 0:
            delta = ((player_val - pro_val) / pro_val) * 100
            if delta > 10:
                emoji = "🟢"
            elif delta < -10:
                emoji = "🔴"
            else:
                emoji = "🟡"
            result[metric] = {
                "value": round(player_val, 1) if metric != "utility" else int(player_val),
                "delta": round(delta, 1),
                "emoji": emoji
            }
        else:
            result[metric] = {"value": "-", "delta": 0, "emoji": "🟡"}

    return result


async def cache_hero_icon(hero_id: int) -> str:
    """Кэширует иконку героя локально"""
    cache_path = os.path.join(ASSETS_DIR, f"{hero_id}.png")
    if os.path.exists(cache_path):
        return cache_path

    try:
        url = f"https://cdn.cloudflare.steamstatic.com/apps/dota2/images/dota_react/heroes/icons/{hero_id}.png"
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.read()
                    with open(cache_path, "wb") as f:
                        f.write(data)
                    return cache_path
    except Exception as e:
        logger.error(f"Failed to cache hero icon {hero_id}: {e}")

    return ""  # Fallback


def create_impact_chart(data_points: list[float], hero_ids: list[int]) -> bytes:
    """Создаёт график IMP с иконками героев"""
    fig = go.Figure()

    # Линия графика
    fig.add_trace(go.Scatter(
        x=list(range(1, len(data_points) + 1)),
        y=data_points,
        mode='lines+markers',
        line=dict(color='#ff9900', width=3),
        fill='tozeroy',
        fillcolor='rgba(255, 153, 0, 0.1)'
    ))

    # PRO Target линия
    fig.add_hline(y=1.0, line_dash="dot", line_color="red", annotation_text="PRO Target")

    # Настройки
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor='#18181b',
        plot_bgcolor='#18181b',
        font=dict(family="Arial", size=12),
        xaxis_title="Матч",
        yaxis_title="IMP",
        showlegend=False
    )

    # Сохранить в PNG
    buf = io.BytesIO()
    fig.write_image(buf, format='png', engine='kaleido')
    buf.seek(0)
    return buf.getvalue()


async def get_weekly_matches(telegram_id: int) -> list[dict]:
    """Получает 10 последних матчей за неделю"""
    user = get_user(telegram_id)
    if not user or not user.get("steam_id"):
        return []

    steam_id = user["steam_id"]
    account_id = steam64_to_account_id(steam_id)

    # Рассчитать начало недели (понедельник 00:00 MSK)
    msk = timezone(timedelta(hours=3))
    now_msk = datetime.now(msk)
    monday_msk = now_msk - timedelta(days=now_msk.weekday())
    week_start = monday_msk.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start_utc = week_start.astimezone(timezone.utc)

    # Запрос матчей
    url = f"{OPENDOTA_API_URL}/players/{account_id}/matches"
    params = {"limit": 50, "sort": "-start_time"}  # Новые первыми

    matches = await _api_get_async(url, params)
    if not matches:
        return []

    # Фильтр по неделе
    weekly_matches = []
    for match in matches:
        match_time = datetime.fromtimestamp(match.get("start_time", 0), tz=timezone.utc)
        if match_time >= week_start_utc:
            weekly_matches.append(match)
        if len(weekly_matches) >= 10:
            break

    return weekly_matches[:10]


async def generate_weekly_analytics(telegram_id: int) -> dict | None:
    """Генерирует еженедельную аналитику"""
    matches = await get_weekly_matches(telegram_id)
    if len(matches) < 5:  # Минимум 5 матчей
        return None

    # Определить доминирующую роль
    roles = [detect_role(m) for m in matches]
    role = max(set(roles), key=roles.count) if roles else "UNIVERSAL"

    # Рассчитать средние метрики
    total_gpm = sum(m.get("gold_per_min", 0) for m in matches)
    total_kills = sum(m.get("kills", 0) for m in matches)
    total_deaths = sum(m.get("deaths", 0) for m in matches)
    total_assists = sum(m.get("assists", 0) for m in matches)
    total_lh = sum(m.get("last_hits", 0) for m in matches)
    total_apm = sum(m.get("actions_per_min", 0) for m in matches)

    avg_gpm = total_gpm / len(matches)
    avg_kda = (total_kills + total_assists) / (total_deaths + 1)  # +1 чтобы избежать деления на 0
    avg_lh = total_lh / len(matches)
    avg_apm = total_apm / len(matches)

    # Utility (упрощённо, без детальных данных)
    avg_utility = calculate_utility()  # Заглушка, так как данные не всегда доступны

    player_stats = {
        "gpm": avg_gpm,
        "kda": avg_kda,
        "lh": avg_lh,
        "apm": avg_apm,
        "utility": avg_utility
    }

    # Сравнение с PRO
    comparison = compare_with_pro(player_stats, role)

    # IMP по матчам (упрощённо, повторяем среднее)
    hero_ids = [m.get("hero_id", 0) for m in matches]
    imp_points = [calculate_imp(avg_gpm, avg_kda, avg_utility, avg_apm, role)] * len(matches)

    # График
    chart_image = create_impact_chart(imp_points, hero_ids)

    # Текст в MarkdownV2
    text = f"🎯 Еженедельная аналитика\n\nРоль: {role}\n\n"
    text += "```\n"
    text += "Метрика | Значение | Дельта | Статус\n"
    text += "--------|----------|--------|--------\n"
    for metric, data in comparison.items():
        if "error" not in data:
            text += f"{metric.upper()} | {data['value']} | {data['delta']}% | {data['emoji']}\n"
    text += "```\n\n"
    text += "📊 График IMP по 10 матчам\\. PRO Target \\= 1\\.0"

    return {"text": text, "image": chart_image}