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
    "ROSHAN_STEAL_TEXTS",
    "ROSHAN_AEGIS_EFFECTS",
    "ROSHAN_CHEESE_EFFECTS",
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
# Every unique roll has the SAME 10% chance: Roshan is no more and no less
# likely than Zeus, Techies or multicast. All four sit on one scale in
# fissure.py (Roshan → Zeus → Techies → multicast), so they are read off one
# number instead of four.
# Resulting split: any unique event 10% | plain roll 60%.
MULTICAST_DEFAULT_CHANCE = 0.10
ZEUS_DEFAULT_CHANCE = 0.10
TECHIES_DEFAULT_CHANCE = 0.10
ROSHAN_DEFAULT_CHANCE = 0.10

# Roshan event
ROSHAN_STEAL_WINDOW_SEC = 45          # окно, в котором можно нажать кнопку
ROSHAN_REWARD_MIN = 5.0               # floor награды убийце
ROSHAN_REWARD_MAX = 20.0              # cap награды убийце ( leaders must not snowball)
ROSHAN_REWARD_RATIO = 0.08            # доля текущей фиссуры
ROSHAN_SESSION_TTL = 3600             # через сколько секунд чистим протухшие сессии
# Roshan has no voice lines in Dota 2 - he is an ancient creep with roars only,
# so there are no quotes to lift. These lines paraphrase the actual lore instead:
#   - "Are We Heroes Yet?" comic: Roshan killed a Shopkeeper and took the Aegis.
#     The gods cursed him to be killed repeatedly and to have his treasure stolen
#     time and time again. Both halves of that curse are this event: the kill
#     grows the fissure, the artifacts drop off his body.
#   - "Tarn of Roshan" is the comic's name for the pit he lies in.
#   - The Aegis cannot be bought, sold or destroyed - only carried off his body,
#     and it returns to him on respawn.
#   - Roshan went into the Underhollow after Roshefort cheese himself and brought
#     the tunnels down, which is why the cheese is under him.
ROSHAN_TEXTS = [
    "🪤 За Торговца боги наказали Рошана: его убивают по кругу, и добычу с него снимают по кругу.",
    "🪤 Рошан убил Хранителя и забрал АЕГИС. С тех пор он умирает каждый раз заново, а вещи уходят чужим рукам.",
    "🪤 Проклятие Торговца не даёт Рошану умереть спокойно — только выронить добычу.",
    "🪤 Он спускался в Андерхоллоу за Рошефортом и обвалил тоннели. Теперь сыр лежит у него под ногами.",
]
# Что выпадает из поверженного Рошана. Одна строка: лор уже отработал выше,
# здесь только факт дропа и окно. Окно подставляется через {window}, иначе
# рано или поздно появится вариант без срока.
ROSHAN_STEAL_TEXTS = [
    "Из Рошана высыпались 🧿 АЕГИС и 🧀 СЫР. У тебя {window} секунд — что достанется, то твоё.",
    "Из Рошана высыпались 🧿 АЕГИС и 🧀 СЫР. {window} секунд, предмет выпадет случайно.",
    "Из Рошана высыпались 🧿 АЕГИС и 🧀 СЫР. Выкупить нельзя, только своровать. {window} секунд, что достанется — то твоё.",
    "Из Рошана высыпались 🧿 АЕГИС и 🧀 СЫР. Он воскреснет и заберёт всё. {window} секунд, что достанется — то твоё.",
]
# Что артефакт делает на самом деле, по rolls.py:
#   apply_aegis   обнуляет отрицательный ролл целиком и НЕ тратится на плюсе;
#   apply_cheese  умножает положительный ролл на 1.5 и минус не трогает.
# Короткие ярлыки для строки результата, а не описания механики.
ROSHAN_AEGIS_EFFECTS = [
    "страховка от минуса",
]
ROSHAN_CHEESE_EFFECTS = [
    "усиление плюса ×1.5",
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
