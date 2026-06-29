"""
Global constants for the fissure bot.
Extracted from main.py without changing any behavior.
"""

from pathlib import Path

__all__ = [
    # Cooldown
    "COOLDOWN",
    # Banners
    "COOLDOWN_BANNER_URL",
    "PROFILE_BANNER_URL",
    "TOP_BANNER_URL",
    "TOPMMR_BANNER_URL",
    "LINK_BANNER_URL",
    "SETDIGEST_BANNER_URL",
    "ZEUS_BANNER_URL",
    "BANNER_DIR",
    "get_banner_path",
    # Timeouts / delays
    "DICE_ANIMATION_DELAY",
    "USER_PROCESSING_TTL",
    "BOT_CAN_DELETE_TTL",
    "JOB_COOLDOWN",
    "WEEKLY_JOB_COOLDOWN",
    # Weekend bonus
    "WEEKEND_BONUS_MULTIPLIERS",
    # Default chances (legacy - some also in stats.py)
    "MULTICAST_DEFAULT_CHANCE",
    "ZEUS_DEFAULT_CHANCE",
    # Digest headers/footers
    "MORNING_DIGEST_HEADER",
    "MORNING_DIGEST_FOOTER",
    "DOTA_DIGEST_HEADER",
    "DOTA_DIGEST_FOOTER",
    # Zeus
    "ZEUS_TEXTS",
    # Welcome
    "WELCOME_PHRASES",
]

# Cooldown for fissure rolls (24 hours)
COOLDOWN = 86400

# Banner URLs
COOLDOWN_BANNER_URL = "https://i.ibb.co/FkzCZxNG/m-Yqbu.jpg"
PROFILE_BANNER_URL = "https://i.ibb.co/n8g8yQYt/dasdsadasdsadasdsad.png"
TOP_BANNER_URL = "https://i.ibb.co/1fbJD2hb/l-Ij20.jpg"
TOPMMR_BANNER_URL = "https://i.ibb.co/CsbCfzTz/Tv-Sd2.jpg"
LINK_BANNER_URL = "https://i.ibb.co/0jdSyXWx/MZXz-H.jpg"
SETDIGEST_BANNER_URL = "https://i.ibb.co/LXsGsfxZ/213.png"
ZEUS_BANNER_URL = "https://i.ibb.co/0jg01gWW/Gemini-Generated-Image-wyz68gwyz68gwyz6-1.png"

# Local banner directory
BANNER_DIR = Path(__file__).parent / "images" / "banners"

# Timeouts and delays
DICE_ANIMATION_DELAY = 1.0
USER_PROCESSING_TTL = 30          # seconds
BOT_CAN_DELETE_TTL = 3600         # 1 hour
JOB_COOLDOWN = 30                 # seconds between job runs
WEEKLY_JOB_COOLDOWN = 60          # seconds between weekly jobs

# Weekend bonus
WEEKEND_BONUS_MULTIPLIERS = [1.5, 2, 2.5]

# Default event chances (can be overridden in DB)
MULTICAST_DEFAULT_CHANCE = 0.15
ZEUS_DEFAULT_CHANCE = 0.04
TECHIES_DEFAULT_CHANCE = 0.15

# Texts
MORNING_DIGEST_HEADER = "🌅ФИССУРА ДАЙДЖЕСТ"
MORNING_DIGEST_FOOTER = "🔺 = рост позиций в топе\n🔻 = топ падение\n🍀 = текущий стрик побед"
DOTA_DIGEST_HEADER = "🎮 DOTA ДАЙДЖЕСТ 📊"
DOTA_DIGEST_FOOTER = "🔺 = лучший винрейт за неделю\n🔻 = худший винрейт за неделю\n🔸 = текущий стрик побед"

# Zeus texts (moved here for centralization)
ZEUS_TEXTS = [
    "⚡️ Zeus «Ничто не укроется от моего гнева!»",
    "⚡️ Zeus «Ты не против меня!»",
    "⚡️ Zeus «Гром обрушится на тебя!»",
    "⚡️ Zeus «Падение света!»",
    "⚡️ Zeus «Конец исходит от меня!»",
]

# Welcome phrases for new members
WELCOME_PHRASES = [
    "Присоединился! Падж облизнулся на тебя, свежее мясо🍖",
    "Добро пожаловать! Свен хлопнул тебя по плечу👏",
    "Не зевай! Сларк шепчет тебе на ухо🤫",
    "Заходи! Бруда раскинула сеть для тебя🕸️",
    "Открой рундук! Джагернаут дал тебе клинок⚔️",
    "Привет! Zeus сверкнул молнией⚡",
    "Погнали! Spirit Breaker тебя прокатит🚕",
    "Здарова! Tusk дал тебе в плечо кулачищем🐧",
    "Ой, а ты кто? Axe почесал тебе затылок секирой🪓",
    "Ой, а ты кто? Morphling умыл тебе лицо💧",
    "Не зевай! Phantom Assassin хочет пересчитать твои ребра💀",
    "Здарова! Slardar брызнул слюной🐟",
    "Чего уставился? Clinkz натянул тебе тетиву🏹",
    "Привет! Faceless Void остановил время на секунду🕰️",
    "Будь как дома! Wisp засветился у тебя за спиной💫",
    "Не зевай! Techies Три, две, одна — улыбнись🧨",
    "Чего встал? Primal Beast топнул — пол треснул🦍",
    "Сладкий! Queen of Pain услышала твой голос👑",
]

# Local banner helper
def get_banner_path(banner_name: str) -> str | Path:
    """Get local banner path, returns URL if not found locally."""
    local = BANNER_DIR / f"{banner_name}.webp"
    if local.exists():
        return local
    local = BANNER_DIR / f"{banner_name}.jpg"
    if local.exists():
        return local
    local_png = BANNER_DIR / f"{banner_name}.png"
    if local_png.exists():
        return local_png
    return {
        "cooldown": COOLDOWN_BANNER_URL,
        "profile": PROFILE_BANNER_URL,
        "top": TOP_BANNER_URL,
        "topmmr": TOPMMR_BANNER_URL,
        "link": LINK_BANNER_URL,
        "zeus": ZEUS_BANNER_URL,
        "winner": "https://i.ibb.co/CsbCfzTz/Tv-Sd2.jpg",
        "rankup": "https://i.ibb.co/HLF6JJTw/ji8hy.jpg",
        "default_avatar": "https://i.ibb.co/nMSN7mHM/photo-2025-12-29-00-02-39.jpg",
        "roll_fatal": "https://i.ibb.co/WN5CBpqR/dsad23.png",
        "roll_normal": "https://i.ibb.co/Mk35C5PY/Hf-S7B.jpg",
        "background": "https://i.ibb.co/ZzWpzWN0/photo-2026-04-18-22-24-21.png",
        "heroes_strip": "https://i.ibb.co/4Zr4fgNb/image.png",
        "chart_bg_fallback": "https://i.ibb.co/jkTWqcHn/pngdsadsad.png",
    }.get(banner_name, COOLDOWN_BANNER_URL)
