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

# PRO-бенчмарки с игроками и средними
PRO_DB = {
    "CARRY": {
        "players": {
            "Watson":  {"wr": 68, "lh": 72, "deny": 12, "gpm": 725, "kda": "8/2.9/8"},
            "skiter":  {"wr": 65, "lh": 72, "deny": 13, "gpm": 693, "kda": "7/3.0/9"},
            "Pure":    {"wr": 63, "lh": 67, "deny": 11, "gpm": 742, "kda": "8/3.7/9"},
            "Satanic": {"wr": 61, "lh": 81, "deny": 14, "gpm": 825, "kda": "8/2.8/7"},
            "Ame":     {"wr": 60, "lh": 78, "deny": 9,  "gpm": 743, "kda": "7/3.2/7"}
        },
        "benchmarks": {"lh10": 73.8, "deny10": 10.2, "gpm": 732, "xpm": 855, "deaths": 3.1, "h_dmg": 28.0, "t_dmg": 9.3, "stacks": 2.3, "utility": 1.0, "apm": 300}
    },
    "SUPPORT": {
        "players": {
            "Miposhka": {"wr": 62, "lh": 12, "deny": 4, "gpm": 380, "kda": "3/4.2/18"},
            "Save-":    {"wr": 60, "lh": 18, "deny": 6, "gpm": 410, "kda": "4/3.8/15"},
            "Sneyking": {"wr": 64, "lh": 14, "deny": 3, "gpm": 395, "kda": "2/4.5/20"},
            "Puppey":   {"wr": 58, "lh": 10, "deny": 2, "gpm": 350, "kda": "1/5.1/14"},
            "Fishman":  {"wr": 59, "lh": 15, "deny": 5, "gpm": 370, "kda": "2/4.9/16"}
        },
        "benchmarks": {"lh10": 14.5, "deny10": 4.8, "gpm": 385, "xpm": 420, "deaths": 5.2, "h_dmg": 12.0, "t_dmg": 0.8, "stacks": 4.5, "utility": 5.2, "apm": 280}
    }
    # TODO: Добавить MID и OFFLANE
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


def generate_pro_table(role: str, user_stats: dict) -> str:
    """Генерирует таблицу ТОП-5 PRO игроков"""
    if role not in PRO_DB:
        role = "CARRY"

    config = PRO_DB[role]
    pros = config["players"]

    lines = []
    lines.append("          WR   LH  Deny  GPM   KDA")
    lines.append("--------------------------------------")
    for name, stats in pros.items():
        line = f"{name:<9}{stats['wr']:>3}% {stats['lh']:>4} {stats['deny']:>4} {stats['gpm']:>5} {stats['kda']}"
        lines.append(line)
    lines.append("--------------------------------------")
    # PRO AVG
    avg_wr = sum(stats['wr'] for stats in pros.values()) // len(pros)
    avg_lh = sum(stats['lh'] for stats in pros.values()) / len(pros)
    avg_deny = sum(stats['deny'] for stats in pros.values()) / len(pros)
    avg_gpm = sum(stats['gpm'] for stats in pros.values()) // len(pros)
    avg_kda = "8/3.1/8" if role == "CARRY" else "2/4.5/17"
    line = f"PRO AVG   {avg_wr:>3}% {avg_lh:>4.1f} {avg_deny:>4.1f} {avg_gpm:>5} {avg_kda}"
    lines.append(line)
    lines.append("")
    # YOU
    u_wr = user_stats.get('wr', 0)
    u_lh = user_stats.get('lh', 0)
    u_deny = user_stats.get('deny', 0)
    u_gpm = user_stats.get('gpm', 0)
    u_kda = user_stats.get('kda', "0/0/0")
    line = f"YOU ✨    {u_wr:>3}% {u_lh:>4.1f} {u_deny:>4.1f} {int(u_gpm):>5} {u_kda}"
    lines.append(line)

    # Выровнять все строки по максимальной длине
    max_len = max(len(line) for line in lines)
    aligned_lines = [line.ljust(max_len) for line in lines]
    table = "```\n" + "\n".join(aligned_lines) + "\n```"

    return table


def compare_with_pro(player_stats: dict, role: str) -> str:
    """Генерирует таблицу детального сравнения"""
    if role not in PRO_DB:
        return "```\nРоль не найдена\n```"

    bench = PRO_DB[role]["benchmarks"]

    lines = []
    lines.append("🔍 Детальное сравнение")
    lines.append("")
    lines.append("Метрика          Ты      PRO      Δ ")
    lines.append("------------------------------------")

    metrics = [
        ("LH@10", "lh10", 1),
        ("Denies@10", "deny10", 1),
        ("GPM", "gpm", 0),
        ("XPM", "xpm", 0),
        ("Deaths", "deaths", 1),
        ("Hero DMG", "h_dmg", 0),
        ("Tower DMG", "t_dmg", 0),
        ("Stacks", "stacks", 1),
        ("Utility", "utility", 1),
        ("APM", "apm", 0)
    ]

    for label, key, decimal in metrics:
        player_val = player_stats.get(key, 0)
        pro_val = bench.get(key, 0)
        if pro_val > 0:
            delta = player_val - pro_val
            arrow = "↑" if delta > 0 else "↓" if delta < 0 else "→"
            if key in ["h_dmg", "t_dmg"]:
                p_val = f"{player_val:.1f}k"
                p_pro = f"{pro_val:.1f}k"
                d_str = f"{delta:+.1f}"
            else:
                p_val = f"{player_val:.1f}" if decimal else f"{int(player_val)}"
                p_pro = f"{pro_val:.1f}" if decimal else f"{int(pro_val)}"
                d_str = f"{delta:+.1f}" if decimal else f"{int(delta):+d}"
            line = f"{label:<15} {p_val:>7} {p_pro:>7} {d_str:>6} {arrow}"
            lines.append(line)
        else:
            line = f"{label:<15} {player_val:>7} -      -      -"
            lines.append(line)

    # Выровнять все строки по максимальной длине
    max_len = max(len(line) for line in lines)
    aligned_lines = [line.ljust(max_len) for line in lines]
    table = "```\n" + "\n".join(aligned_lines) + "\n```"

    return table


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


def create_impact_chart(game_history: list[dict]) -> io.BytesIO:
    """
    Создаёт график IMP с иконками героев
    game_history: [{'impact': float, 'hero_id': int}, ...]
    """
    impacts = [g['impact'] for g in game_history]
    hero_ids = [g['hero_id'] for g in game_history]

    # 1. Создаем базовый график в Plotly
    fig = go.Figure()

    # Линия и заливка
    fig.add_trace(go.Scatter(
        x=list(range(len(impacts))),
        y=impacts,
        mode='lines',
        line=dict(color='#ff9900', width=4),
        fill='tozeroy',
        fillcolor='rgba(255, 153, 0, 0.15)',
        hoverinfo='none'
    ))

    # Линия PRO TARGET
    fig.add_hline(
        y=1.0,
        line_dash="dash",
        line_color="rgba(255, 255, 255, 0.4)",
        annotation_text="PRO TARGET",
        annotation_position="top left",
        annotation_font=dict(color="rgba(255, 255, 255, 0.4)")
    )

    # Добавляем иконки героев
    for i, (val, h_id) in enumerate(zip(impacts, hero_ids)):
        icon_url = f"https://cdn.cloudflare.steamstatic.com/apps/dota2/images/dota_react/heroes/icons/{h_id}.png"

        fig.add_layout_image(
            dict(
                source=icon_url,
                xref="x", yref="y",
                x=i, y=val,
                sizex=0.6, sizey=0.6, # Размер иконок
                xanchor="center", yanchor="middle",
                layer="above"
            )
        )

    # Настройка темной темы
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor='rgb(24, 24, 27)',
        plot_bgcolor='rgb(24, 24, 27)',
        width=900,
        height=500,
        margin=dict(l=50, r=50, t=80, b=50),
        xaxis=dict(showgrid=False, visible=False),
        yaxis=dict(
            gridcolor='rgba(255, 255, 255, 0.1)',
            zeroline=False,
            tickfont=dict(color="gray")
        ),
        title=dict(
            text="Impact (IMP)",
            font=dict(size=24, color="white"),
            x=0.05, y=0.92
        )
    )

    # Рендерим в байты (нужна библиотека kaleido)
    img_bytes = fig.to_image(format="png", engine="kaleido")

    # 2. Добавляем бейдж "Улучшение" с помощью Pillow
    img = Image.open(io.BytesIO(img_bytes))
    draw = ImageDraw.Draw(img)

    # Координаты для бейджа (правый верхний угол)
    badge_rect = [680, 25, 850, 65]
    draw.rounded_rectangle(badge_rect, radius=20, fill="#22c55e")

    # Текст на бейдже (используй шрифт, если он есть в системе, или дефолтный)
    try:
        font = ImageFont.truetype("Arial.ttf", 20)
    except:
        font = ImageFont.load_default()

    draw.text((700, 32), "↑ Улучшение", fill="white", font=font)

    # Сохраняем финальный результат
    output = io.BytesIO()
    img.save(output, format="PNG")
    output.seek(0)

    return output


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

    matches = await _api_get_async(url, params, timeout=10)  # Увеличить timeout
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

    player_stats = {
        "gpm": avg_gpm,
        "kda": avg_kda,
        "lh": avg_lh,
        "apm": avg_apm,
        "utility": avg_utility
    }

    # Подготовка данных для таблиц
    avg_xpm = sum(m.get("xp_per_min", 0) for m in matches) / len(matches)
    avg_deaths = total_deaths / len(matches)
    avg_h_dmg = sum(m.get("hero_damage", 0) for m in matches) / len(matches)
    avg_t_dmg = sum(m.get("tower_damage", 0) for m in matches) / len(matches)
    avg_stacks = total_stacks / len(matches)
    avg_wards = total_wards / len(matches)

    user_table_stats = {
        'wr': int(wr),
        'lh': avg_lh,
        'deny': 0,  # Denies не всегда доступны
        'gpm': avg_gpm,
        'kda': f"{int(total_kills / len(matches))}/{int(avg_deaths)}/{int(total_assists / len(matches))}",
        'lh10': avg_lh,
        'deny10': 0,
        'xpm': avg_xpm,
        'deaths': avg_deaths,
        'h_dmg': avg_h_dmg / 1000,  # В к
        't_dmg': avg_t_dmg / 1000,
        'stacks': avg_stacks,
        'utility': avg_utility,
        'apm': avg_apm
    }

    # Таблица 1: ТОП-5 PRO
    table1 = generate_pro_table(role, user_table_stats)

    # Таблица 2: Детальное сравнение
    table2 = compare_with_pro(user_table_stats, role)

    # IMP по матчам
    game_history = []
    for m in matches:
        imp = calculate_imp(avg_gpm, avg_kda, avg_utility, avg_apm, role)
        game_history.append({'impact': imp, 'hero_id': m.get("hero_id", 0)})

    # График
    chart_image = create_impact_chart(game_history)

    # Текст в MarkdownV2
    text = f"🏆 Сравнение с ПРО ({role.upper()})\n\n{table1}\n\n{table2}\n\n"
    text += "📊 График IMP по 10 матчам\\. PRO Target \\= 1\\.0"

    return {"text": text, "image": chart_image}