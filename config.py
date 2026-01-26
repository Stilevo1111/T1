import os
import logging
from typing import Dict, List, Tuple
from dotenv import load_dotenv

# Загружаем переменные окружения из .env файла
load_dotenv()

# ================= CONFIG =================

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Переменные окружения
BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
RENDER_URL = os.getenv("RENDER_EXTERNAL_URL")
PORT = int(os.getenv("PORT", 10000))

# Проверка обязательных переменных окружения
required_env_vars = ["BOT_TOKEN", "DATABASE_URL", "RENDER_EXTERNAL_URL"]
missing_vars = [var for var in required_env_vars if not os.getenv(var)]

if missing_vars:
    logger.error(f"Не заданы обязательные переменные окружения: {', '.join(missing_vars)}")
    raise RuntimeError(f"Не заданы обязательные переменные окружения: {', '.join(missing_vars)}")

# ================= CONSTANTS =================

# Основные константы
COOLDOWN = 86400  # 24 часа в секундах
AUTO_DELETE_DELAY = 30  # секунд для автоудаления сообщений
MAX_MESSAGE_LENGTH = 4096  # Максимальная длина сообщения Telegram

# Fissure система
ROLLS = [-5, -3, -1, 0, 1, 3, 5, 10]
FISURE_TEXTS = {
    10: "💀 ЛЕГЕНДА! +10 см!",
    5: "🎉 +5 см!",
    3: "🔥 +3 см",
    1: "🙂 +1 см",
    0: "🤷 Без изменений",
    -1: "😅 -1 см",
    -3: "📉 -3 см",
    -5: "💔 -5 см...",
}
FISURE_PHRASES = {
    "up": ["Растёт… и ничего не спрашивает.", "Увеличилась… без лишних слов."],
    "same": ["Стоит на месте… зато уверенно.", "На месте… как старый добрый друг."],
    "down": ["Сжалась… тихо так, но гордо.", "Сократился… но с достоинством."],
}

# Мем-комментарии
MEMES: Dict[str, List[str]] = {
    "crit": [
        "💥 КРИТ! Я инвестировал в урон",
        "🔥 Минус лицо",
        "😈 Это было больно",
        "🎯 Точно в цель!",
        "⚡️ Супер удар!"
    ],
    "dodge": [
        "🌀 Я вообще-то тут не стоял",
        "😎 Уклон — стиль жизни",
        "💨 Слишком медленно!",
        "🎭 Фехтование, мать его!",
        "🏃‍♂️ Быстрее ветра!"
    ],
    "death": [
        "💀 Это был тактический фид",
        "🪦 Я ещё вернусь",
        "⚰️ Пора на кладбище",
        "👻 Смерть — не повод для грусти",
        "⚰️ Вечная память"
    ],
    "boss_kill": [
        "🏆 {boss} повержен!",
        "🔥 Мы его взяли!",
        "💀 Босс упал!",
        "🎯 Цель уничтожена!",
        "🔥 Это был эпик бой!"
    ]
}

# Характеристики персонажа
BASE_HP_PER_STR = 10  # Каждый пункт силы дает +10 HP
BASE_DMG_PER_STR = 1  # Каждый пункт силы дает +1 урон
BASE_DODGE_PER_AGI = 0.5  # Каждый пункт ловкости дает +0.5% уклонения
BASE_CRIT_PER_AGI = 0.2  # Каждый пункт ловкости дает +0.2% крита
BASE_MANA_PER_INT = 10  # Каждый пункт интеллекта дает +10 маны (если будет добавлена система маны)
BASE_HP_REGEN_PER_INT = 0.5  # Каждый пункт интеллекта дает +0.5% регенерации HP в минуту

# Опыт для уровней
EXP_PER_LEVEL = 100  # Базовый опыт для следующего уровня
EXP_MULTIPLIER = 1.2  # Множитель опыта для каждого уровня

# Ограничения и лимиты
MAX_LEVEL = 30
MAX_STAT_VALUE = 1000
MAX_ITEM_SLOTS = 6
MAX_TALENT_POINTS = 30
MAX_MMR = 3000
MIN_FISSURE_LENGTH = 0.1  # Минимальная длина фиссуры в см

# PvP настройки
PVP_COOLDOWN = 600  # 10 минут в секундах
MMR_CHANGE = 20  # Изменение MMR за победу/поражение
EXP_CHANGE = 50  # Опыт за победу
MIN_MMR_RATIO = 0.5  # Минимальный MMR противника (50% от игрока)

# Босс настройки
BOSS_REGEN_DELAY = 300  # 5 минут в секундах
MAX_BOSS_HP = 15000
MIN_BOSS_HP = 3000

# Валидация конфигурации
def validate_config() -> bool:
    """Проверяет корректность конфигурации"""
    try:
        # Проверка токена бота
        if not BOT_TOKEN or len(BOT_TOKEN) < 10:
            logger.error("Некорректный BOT_TOKEN")
            return False

        # Проверка URL базы данных (разрешаем sqlite для тестирования)
        if not DATABASE_URL or ("postgresql" not in DATABASE_URL.lower() and "sqlite" not in DATABASE_URL.lower()):
            logger.error("Некорректный DATABASE_URL")
            return False

        # Проверка RENDER_URL
        if not RENDER_URL or not RENDER_URL.startswith("https://"):
            logger.error("Некорректный RENDER_URL")
            return False

        # Проверка порта
        if not (1000 <= PORT <= 65535):
            logger.error(f"Некорректный PORT: {PORT}")
            return False

        logger.info("Конфигурация валидна")
        return True
    except Exception as e:
        logger.error(f"Ошибка валидации конфигурации: {e}")
        return False

# Инициализация конфигурации
if not validate_config():
    raise RuntimeError("Конфигурация не прошла валидацию")
