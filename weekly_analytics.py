# weekly_analytics.py - Еженедельная аналитика игрока (финальная версия)
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

# На Render локальный кэш не сохраняется, поэтому загружаем напрямую из CDN

# ПОЛНАЯ БАЗА ДАННЫХ РОЛЕЙ И ПРО-ИГРОКОВ
PRO_DB = {
    "CARRY": {
        "players": {
            "Watson":  {"wr": 68, "lh": 72, "deny": 12, "gpm": 725, "kda": "8/2.9/8"},
            "skiter":  {"wr": 65, "lh": 72, "deny": 13, "gpm": 693, "kda": "7/3.0/9"},
            "Pure":    {"wr": 63, "lh": 67, "deny": 11, "gpm": 742, "kda": "8/3.7/9"},
            "Satanic": {"wr": 61, "lh": 81, "deny": 14, "gpm": 825, "kda": "8/2.8/7"},
            "Ame":     {"wr": 60, "lh": 78, "deny": 9,  "gpm": 743, "kda": "7/3.2/7"}
        },
        "benchmarks": {"lh10": 73.8, "deny10": 10.2, "gpm": 732, "xpm": 855, "deaths": 3.1, "h_dmg": 28.0, "t_dmg": 9.3, "stacks": 2.3, "utility": 1.0, "apm": 310}
    },
    "MID": {
        "players": {
            "Malr1ne": {"wr": 64, "lh": 75, "deny": 24, "gpm": 715, "kda": "9/3.1/8"},
            "Quinn":   {"wr": 62, "lh": 70, "deny": 20, "gpm": 690, "kda": "8/3.4/9"},
            "Nisha":   {"wr": 63, "lh": 73, "deny": 22, "gpm": 705, "kda": "9/2.8/7"},
            "gpk~":    {"wr": 60, "lh": 68, "deny": 25, "gpm": 685, "kda": "8/3.5/10"},
            "No[o]ne": {"wr": 61, "lh": 74, "deny": 21, "gpm": 710, "kda": "10/3.2/8"}
        },
        "benchmarks": {"lh10": 71.5, "deny10": 21.8, "gpm": 702, "xpm": 810, "deaths": 3.2, "h_dmg": 32.0, "t_dmg": 4.5, "stacks": 1.2, "utility": 1.5, "apm": 340}
    },
    "OFFLANE": {
        "players": {
            "Collapse": {"wr": 62, "lh": 62, "deny": 18, "gpm": 590, "kda": "5/3.8/12"},
            "33":       {"wr": 65, "lh": 58, "deny": 15, "gpm": 610, "kda": "4/3.2/14"},
            "Ace":      {"wr": 63, "lh": 65, "deny": 20, "gpm": 580, "kda": "5/3.5/15"},
            "ATF":      {"wr": 60, "lh": 70, "deny": 14, "gpm": 640, "kda": "7/4.1/10"},
            "Wisper":   {"wr": 58, "lh": 63, "deny": 16, "gpm": 595, "kda": "6/4.0/11"}
        },
        "benchmarks": {"lh10": 61.2, "deny10": 17.5, "gpm": 595, "xpm": 680, "deaths": 3.8, "h_dmg": 24.5, "t_dmg": 6.2, "stacks": 3.5, "utility": 4.2, "apm": 290}
    },
    "SUPPORT": {
        "players": {
            "Miposhka": {"wr": 62, "lh": 12, "deny": 4, "gpm": 380, "kda": "3/4.2/18"},
            "Save-":    {"wr": 60, "lh": 18, "deny": 6, "gpm": 410, "kda": "4/3.8/15"},
            "Sneyking": {"wr": 64, "lh": 14, "deny": 3, "gpm": 395, "kda": "2/4.5/20"},
            "Puppey":   {"wr": 58, "lh": 10, "deny": 2, "gpm": 350, "kda": "1/5.1/14"},
            "Fishman":  {"wr": 59, "lh": 15, "deny": 5, "gpm": 370, "kda": "2/4.9/16"}
        },
        "benchmarks": {"lh10": 14.5, "deny10": 4.8, "gpm": 385, "xpm": 420, "deaths": 4.8, "h_dmg": 12.0, "t_dmg": 0.8, "stacks": 5.2, "utility": 8.5, "apm": 270}
    }
}

# Весовые коэффициенты для IMP
IMP_WEIGHTS = {
    "CARRY": {"gpm": 0.4, "kda": 0.3, "utility": 0.1, "apm": 0.2},
    "SUPPORT": {"gpm": 0.1, "kda": 0.3, "utility": 0.4, "apm": 0.2},
    "MID": {"gpm": 0.35, "kda": 0.35, "utility": 0.15, "apm": 0.15},
    "OFFLANE": {"gpm": 0.3, "kda": 0.3, "utility": 0.2, "apm": 0.2}
}

def detect_role(m: dict) -> str:
    """Определение роли по статистике матча"""
    lane = m.get("lane_role", 0)
    gpm = m.get("gold_per_min", 0)
    if lane == 1 or (lane == 0 and gpm > 650): return "CARRY"
    if lane == 2: return "MID"
    if lane == 3: return "OFFLANE"
    return "SUPPORT"

def calculate_utility(stuns: float = 0, heals: float = 0, stacks: int = 0, wards: int = 0) -> float:
    """Расчёт Utility по формуле"""
    return (stuns * 0.5) + (heals * 0.01) + (stacks * 150) + (wards * 50)

def calculate_imp(gpm: float, kda: float, utility: float, apm: float, role: str) -> float:
    """Расчёт Индекса Импакта (IMP)"""
    if role not in PRO_DB:
        role = "CARRY"

    pro = PRO_DB[role]["benchmarks"]
    weights = IMP_WEIGHTS[role]

    p_gpm = gpm / pro["gpm"] if pro["gpm"] > 0 else 0
    p_kda = kda / 5.5 if role == "CARRY" else kda / 3.5  # Simplified
    p_utility = utility / pro["utility"] if pro["utility"] > 0 else 0
    p_apm = apm / pro["apm"] if pro["apm"] > 0 else 0

    imp = (p_gpm * weights["gpm"]) + (p_kda * weights["kda"]) + (p_utility * weights["utility"]) + (p_apm * weights["apm"])
    return round(imp, 2)

def get_hero_icon(hero_id: int):
    """Получение URL иконки героя (без кэша на Render)"""
    return f"https://cdn.cloudflare.steamstatic.com/apps/dota2/images/dota_react/heroes/icons/{hero_id}.png"

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

    matches = await _api_get_async(url, params, timeout=10)
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

def generate_report_text(role: str, user_stats: dict) -> str:
    """Генерация текстовых таблиц в стиле референса"""
    db = PRO_DB.get(role, PRO_DB["CARRY"])

    # Таблица 1
    t1 = "```\n          WR   LH  Deny  GPM   KDA\n"
    t1 += "--------------------------------------\n"
    for name, s in db["players"].items():
        t1 += f"{name:<9} {s['wr']}% {s['lh']:>4} {s['deny']:>4} {s['gpm']:>5} {s['kda']}\n"
    t1 += "--------------------------------------\n"
    t1 += f"YOU ✨    {user_stats['wr']}% {user_stats['lh']:>4} {user_stats['deny']:>4} {user_stats['gpm']:>5} {user_stats['kda']}\n```"

    # Таблица 2
    t2 = "```\nМетрика          Ты      PRO      Δ \n"
    t2 += "------------------------------------\n"
    bench = db["benchmarks"]
    metrics = [
        ("LH@10", user_stats['lh10'], bench['lh10']),
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
        # Инверсия для смертей
        is_bad = diff > 0 if "Deaths" in label else diff < 0
        arrow = "↓" if is_bad else "↑"

        u_str = f"{u:.1f}k" if "DMG" in label else f"{u:.1f}"
        p_str = f"{p:.1f}k" if "DMG" in label else f"{p:.1f}"

        t2 += f"{label:<14} {u_str:>6} {p_str:>8} {arrow:>4}\n"
    t2 += "```"

    return f"📊 **АНАЛИЗ ЗА 10 ИГР (Роль: {role})**\n\n🏆 **Сравнение с ТОП-5 PRO**\n{t1}\n🔍 **Детальное сравнение**\n{t2}"

async def generate_weekly_analytics(telegram_id: int) -> dict | None:
    """Генерирует еженедельную аналитику"""
    matches = await get_weekly_matches(telegram_id)
    if len(matches) < 5:  # Минимум 5 матчей
        return None

    # Определить доминирующую роль
    roles = [detect_role(m) for m in matches]
    role = max(set(roles), key=roles.count) if roles else "CARRY"

    # Рассчитать средние метрики
    total_gpm = sum(m.get("gold_per_min", 0) for m in matches)
    total_kills = sum(m.get("kills", 0) for m in matches)
    total_deaths = sum(m.get("deaths", 0) for m in matches)
    total_assists = sum(m.get("assists", 0) for m in matches)
    total_lh = sum(m.get("last_hits", 0) for m in matches)
    total_apm = sum(m.get("actions_per_min", 0) for m in matches)
    total_wins = sum(1 for m in matches if m.get("win", 0) == 1)
    total_stuns = sum(m.get("stuns", 0) for m in matches)
    total_heals = sum(m.get("hero_healing", 0) for m in matches)
    total_stacks = sum(m.get("creeps_stacked", 0) for m in matches)
    total_wards = sum(m.get("observer_uses", 0) + m.get("sentry_uses", 0) for m in matches)

    avg_gpm = total_gpm / len(matches)
    avg_kda = (total_kills + total_assists) / (total_deaths + 1)  # +1 чтобы избежать деления на 0
    avg_lh = total_lh / len(matches)
    avg_apm = total_apm / len(matches)
    wr = (total_wins / len(matches)) * 100
    avg_utility = calculate_utility(total_stuns, total_heals, total_stacks, total_wards) / len(matches)

    # Подготовка данных для таблиц
    avg_xpm = sum(m.get("xp_per_min", 0) for m in matches) / len(matches)
    avg_deaths = total_deaths / len(matches)
    avg_h_dmg = sum(m.get("hero_damage", 0) for m in matches) / len(matches)
    avg_t_dmg = sum(m.get("tower_damage", 0) for m in matches) / len(matches)

    user_table_stats = {
        'wr': int(wr),
        'lh': avg_lh,
        'deny': 0,  # Заглушка
        'gpm': avg_gpm,
        'kda': f"{int(total_kills / len(matches))}/{int(avg_deaths)}/{int(total_assists / len(matches))}",
        'lh10': avg_lh,
        'xpm': avg_xpm,
        'deaths': avg_deaths,
        'h_dmg': avg_h_dmg / 1000,  # В к
        't_dmg': avg_t_dmg / 1000,
        'util': avg_utility,
        'apm': avg_apm
    }

    # Генерация текста
    text = generate_report_text(role, user_table_stats)

    # IMP по матчам
    game_history = []
    for m in matches:
        imp = calculate_imp(avg_gpm, avg_kda, avg_utility, avg_apm, role)
        game_history.append({'imp': imp, 'hero_id': m.get("hero_id", 0)})

    # График
    chart_image = create_visual_chart(game_history)

    return {"text": text, "image": chart_image}

def create_visual_chart(history: list):
    """Создание графика Plotly + Pillow (синхронно, без кэша)"""
    impacts = [g['imp'] for g in history]
    fig = go.Figure()

    # Стилизация как на скрине
    fig.add_trace(go.Scatter(
        y=impacts, mode='lines', line=dict(color='#ff9900', width=4),
        fill='tozeroy', fillcolor='rgba(255,153,0,0.1)'
    ))

    for i, g in enumerate(history):
        url = get_hero_icon(g['hero_id'])
        fig.add_layout_image(dict(
            source=url, xref="x", yref="y",
            x=i, y=g['imp'], sizex=0.5, sizey=0.5, xanchor="center", yanchor="middle"
        ))

    fig.update_layout(
        template="plotly_dark", paper_bgcolor='#18181b', plot_bgcolor='#18181b',
        margin=dict(t=50, b=20, l=40, r=40), height=400, width=800,
        yaxis=dict(gridcolor='rgba(255,255,255,0.05)', zeroline=False)
    )

    img_bytes = fig.to_image(format="png", engine="kaleido")
    img = Image.open(io.BytesIO(img_bytes))

    # Добавляем бейдж Улучшение
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([620, 20, 780, 55], radius=15, fill="#22c55e")
    draw.text((640, 28), "↑ Улучшение", fill="white")

    out = io.BytesIO()
    img.save(out, format="PNG")
    out.seek(0)
    return out