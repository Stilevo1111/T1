"""
Global constants for the fissure bot.
Extracted from main.py without changing any behavior.
"""

from pathlib import Path

__all__ = [
    # Cooldown
    "COOLDOWN",
    # Banners
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
    "TECHIES_DEFAULT_CHANCE",
    # Digest headers/footers
    "MORNING_DIGEST_HEADER",
    "MORNING_DIGEST_FOOTER",
    "DOTA_DIGEST_HEADER",
    "DOTA_DIGEST_FOOTER",
    # Digest intervals
    "DIGEST_ANTI_SPAM_INTERVAL",
    "DIGEST_DATA_REFRESH_INTERVAL",
    "DIGEST_CACHE_TTL",
    "DIGEST_ROTATION_INTERVAL",
    "HERO_META_DIGEST_REFRESH_INTERVAL",
    # Assets
    "TOPMMR_BANNER_PATH",
    # Zeus
    "ZEUS_TEXTS",
    # Welcome
    "WELCOME_PHRASES",
    # Keep-alive
    "KEEPALIVE_PING_NEON_HOURS",
]

# Cooldown for fissure rolls (24 hours)
COOLDOWN = 86400

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
ZEUS_DEFAULT_CHANCE = 0.09
TECHIES_DEFAULT_CHANCE = 0.15

# Texts
MORNING_DIGEST_HEADER = "🌅 ФИССУРА ДАЙДЖЕСТ"
MORNING_DIGEST_FOOTER = "🔺 = рост позиций в топе\n🔻 = топ падение\n🔸 = текущий стрик побед"
DOTA_DIGEST_HEADER = "🎮 DOTA ДАЙДЖЕСТ 📊"
DOTA_DIGEST_FOOTER = "🔺 = лучший винрейт за неделю\n🔻 = худший винрейт за неделю\n🔸 = текущий стрик побед"

# Digest intervals
DIGEST_ANTI_SPAM_INTERVAL = 300  # 5 minutes between digest creations
DIGEST_CACHE_TTL = 1200  # 20 minutes
DIGEST_DATA_REFRESH_INTERVAL = 3600  # 1 hour
DIGEST_ROTATION_INTERVAL = 172800  # 48 hours
HERO_META_DIGEST_REFRESH_INTERVAL = 12 * 3600  # 12 hours

# Владыка небес texts (moved here for centralization)
ZEUS_TEXTS = [
    "🧙 Зевс, Владыка небес 🗣️ Ничто не укроется от моего гнева!",
    "🧙 Зевс, Владыка небес 🗣️ Ты не против меня!",
    "🧙 Зевс, Владыка небес 🗣️ Гром обрушится на тебя!",
    "🧙 Зевс, Владыка небес 🗣️ Падение света!",
    "🧙 Зевс, Владыка небес 🗣️ Конец исходит от меня!",
]

# Welcome phrases for new members
WELCOME_PHRASES = [
    "Присоединился! Падж облизнулся на тебя, свежее мясо🍖",
    "Добро пожаловать! Свен хлопнул тебя по плечу👏",
    "Не зевай! Сларк шепчет тебе на ухо🤫",
    "Заходи! Бруда раскинула сеть для тебя🕸️",
    "Открой рундук! Джагернаут дал тебе клинок⚔️",
    "Привет! Зевс, Владыка небес сверкнул молнией⚡",
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

# Keep-alive ping cost (estimated Render free-tier hours per ping)
KEEPALIVE_PING_NEON_HOURS = 0.56

# Local banner helper
COOLDOWN_BANNERS = ["cooldown", "cooldown_2"]

def get_banner_path(banner_name: str) -> Path:
    """Get local banner path."""
    return BANNER_DIR / f"{banner_name}.webp"

TOPMMR_BANNER_PATH = str(get_banner_path("topmmr"))

def get_random_cooldown_banner_path() -> Path:
    """Get a random cooldown banner path."""
    import random
    name = random.choice(COOLDOWN_BANNERS)
    return BANNER_DIR / f"{name}.webp"
