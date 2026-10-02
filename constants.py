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
    "ROSHAN_DEFAULT_CHANCE",
    # Roshan event
    "ROSHAN_STEAL_WINDOW_SEC",
    "ROSHAN_REWARD_MIN",
    "ROSHAN_REWARD_MAX",
    "ROSHAN_REWARD_RATIO",
    "ROSHAN_SESSION_TTL",
    "ROSHAN_TEXTS",
    "ROSHAN_AEGIS_TEXTS",
    "ROSHAN_CHEESE_TEXTS",
    "ROSHAN_KILL_TEXTS",
    "ROSHAN_RESULT_FOOTERS",
    "ROSHAN_EMPTY_PIT_TEXTS",
    "ROSHAN_LOSER_TEXTS",
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
    # Profile card (/profile)
    "PROFILE_CARD_W",
    "PROFILE_CARD_H",
    "PROFILE_CARD_SS",
    "PROFILE_CARD_RANKS_PER_TIER",
    "PROFILE_CARD_LADDER_TOTAL",
    "PROFILE_CARD_FONT_DIR",
    "PROFILE_CARD_BG_FALLBACK",
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

# Default event chances
# Roshan is rolled on its own independent draw (see stats.get_roshan_chance),
# so it does NOT compete with the other three for probability. At 20% it is
# deliberately the most frequent event: it is the only one that pulls the whole
# chat into an interactive round, so it needs the volume to stay active.
# Resulting unconditional split (each of the other three is scaled by 0.8,
# because the Roshan draw happens first and returns early):
#   Roshan 20% | Zeus 8% | Techies 8% | Multicast 6.4% | Plain roll 57.6%
# The multicast cut (10% -> 8%) exists to keep that plain-roll share above ~50%.
MULTICAST_DEFAULT_CHANCE = 0.08
ZEUS_DEFAULT_CHANCE = 0.10
TECHIES_DEFAULT_CHANCE = 0.10
ROSHAN_DEFAULT_CHANCE = 0.20

# Roshan event
ROSHAN_STEAL_WINDOW_SEC = 45          # окно, в котором можно нажать кнопку
ROSHAN_REWARD_MIN = 5.0               # floor награды убийце
ROSHAN_REWARD_MAX = 20.0              # cap награды убийце ( leaders must not snowball)
ROSHAN_REWARD_RATIO = 0.08            # доля текущей фиссуры
ROSHAN_SESSION_TTL = 3600             # через сколько секунд чистим протухшие сессии
ROSHAN_TEXTS = [
    "👹 Из ямы поднялся Рошан. Он не спал с тех пор, как его разбудили.",
    "👹 Рошан вылез из темноты. Что-то очень голодное открыло один глаз.",
    "👹 Тьма в яме сгустилась. Рошан уже смотрит.",
    "👹 Рошан пробуждён. Он помнит, кто вчера копал здесь слишком глубоко.",
    "👹 Снизу что-то вздохнуло. Рошан выходит на свет.",
]
ROSHAN_AEGIS_TEXTS = [
    "Один минус ролл у этого игрока теперь просто не случится.",
    "Рошан не любит делиться. Один раз Фиссура его не достанет.",
    "АЕГИС гасит ровно один минус ролл, а потом рассыпается.",
    "Хоть раз Фиссура остановилась перед этим игроком и передумала.",
]
ROSHAN_CHEESE_TEXTS = [
    "Следующий плюс этого игрока выйдет в полтора раза жирнее.",
    "СЫР сыр, а главное — ×1.5 к следующему плюсу.",
    "Рошан иногда угощает даже тех, кто его не убивал. Вот и угостил.",
    "Плюс ×1.5. Пусть сам догадывается, откуда такой аппетит.",
]
ROSHAN_KILL_TEXTS = [
    "⛏ Последний удар твой. Рошан даже не успел удивиться.",
    "⛏ Рошан повержен тобой. Теперь Фиссура растёт прямо из его ямы.",
    "⛏ Ты забрал Рошана. Добыча твоя, яма — нет.",
]
ROSHAN_RESULT_FOOTERS = [
    "Рошан не злится. Он вообще ничего не чувствует.",
    "Яма не остаётся пустой надолго.",
    "В следующий раз повезёт кому-то другому. Или тому же.",
]
ROSHAN_EMPTY_PIT_TEXTS = [
    "🥀 Окно закрылось, а в яме никого не нашлось. Никто даже не рискнул.",
    "🥀 Яма осталась нетронутой. Ни одного нажатия за 45 секунд.",
    "🥀 Никто не полез в яму. Рошан уважает осторожность.",
]
ROSHAN_LOSER_TEXTS = [
    "🥀 Нажали, но остались ни с чем",
    "🥀 Лезли в яму и не вытащили ничего",
    "🥀 Нажали — и ушли с пустыми руками",
]

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


# ---------------------------------------------------------------------------
# Profile card (/profile) — карточка прогресса ЗВАНИЙ (не фиссуры)
# ---------------------------------------------------------------------------
PROFILE_CARD_W = 1024                     # ширина карточки (как /start: 1024x500)
PROFILE_CARD_H = 500                      # высота карточки
PROFILE_CARD_SS = 3                      # суперсэмплинг: рисуем в 3× и уменьшаем LANCZOS
PROFILE_CARD_RANKS_PER_TIER = 5          # звёзд в одном звании (I..V)
PROFILE_CARD_LADDER_TOTAL = 35           # 7 тиров × 5 звёзд = 35 шагов до Титана
PROFILE_CARD_FONT_DIR = Path(__file__).parent / "assets" / "fonts"
PROFILE_CARD_BG_FALLBACK = BANNER_DIR / "background.webp"
