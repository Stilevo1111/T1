import os
import random
import time
import asyncio
import logging
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters, JobQueue
from telegram.error import Conflict
from database import init_db, get_user, update_fissure, get_fissure_top, update_last_message_id, Database
from aiohttp import web

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    print("⚠️ BOT_TOKEN не задан! Бот будет работать в режиме ограниченного тестирования.")
    print("💡 Для полноценной работы получите токен у @BotFather в Telegram")
else:
    print("✅ BOT_TOKEN найден")

COOLDOWN = 86400  # 24 часа

# =====================
# НОВАЯ СИСТЕМА РОЛЛОВ
# =====================

# Базовые значения бросков
BASE_ROLLS = [-3, -1, 0, 1, 3, 5, 10, 20]
FATAL_ROLL = -10  # Фатальное уменьшение

# =====================
# ТЕКСТЫ ДЛЯ РЕЗУЛЬТАТОВ
# =====================

ROLL_TEXTS = {
    # 🔥 ПОЛОЖИТЕЛЬНЫЕ
    50: ["🏆 НЕВЕРОЯТНО! +50 см!", "🎰 ДЖЕКПОТ! +50 см СРАЗУ!"],
    30: ["🚀 КОСМОС! +30 см!", "🌟 СВЕРХУДАЧА! +30 см!"],
    20: ["💥 МЕГА-УСПЕХ! +20 см!", "🎯 В ЯБЛОЧКО! +20 см!"],
    10: ["💀 ЛЕГЕНДА! +10 см!", "🔥 ОГОНЬ! +10 см!"],
    5: ["🎉 УРА! +5 см!", "👍 ОТЛИЧНО! +5 см!"],
    3: ["✨ НЕПЛОХО! +3 см", "💪 КРЕПЧАЕМ! +3 см"],
    1: ["🙂 НОРМАС! +1 см", "👌 ЕСТЬ РОСТ! +1 см"],
    0: ["🤷 БЕЗ ИЗМЕНЕНИЙ", "🔄 СТОИМ НА МЕСТЕ"],
    
    # 😅 НЕГАТИВНЫЕ
    -1: ["😅 ЧУТЬ-ЧУТЬ -1 см", "📉 МИНУС ЕСТЬ -1 см"],
    -3: ["😬 ОЙ... -3 см", "📊 ПРОСАДКА -3 см"],
    -5: ["💔 БОЛЬНО -5 см...", "😢 ПРОВАЛ -5 см"],
    -10: ["💀💀💀 КАТАСТРОФА! -10 см!!!", "☠️ АПОКАЛИПСИС! -10 см!!!"]
}

ROLL_MEMES = {
    50: [
        "Твоя fissure теперь больше, чем чья-то самооценка! 😎",
        "Случайный прохожий: 'Что это у тебя такое большое?' 🤔",
        "Теперь можно открыть свой канал на OnlyFissures! 📹"
    ],
    30: [
        "Это как найти 1000 рублей в старых джинсах! 👖💰",
        "Теперь можно достать пульт, не вставая с дивана! 🛋️",
        "Поздравления принимаются в рублях, долларах и см! 💵"
    ],
    20: [
        "Твоя fissure выросла больше, чем акции Tesla! 📈",
        "Теперь это не fissure, а fissURAAAA! 🎸",
        "Размер имеет значение! (оказалось) 📏"
    ],
    10: [
        "Это как получить премию в понедельник! 💼",
        "Fissure: 'Я взрослею!' 🧒→🧑",
        "Теперь ты на 10 см ближе к потолку! 🏠"
    ],
    5: [
        "Это как найти 500 рублей в кармане! 👖",
        "Среднестатистический россиян радуется! 📊",
        "Можно измерить линейкой из Икеа! 📐"
    ],
    3: [
        "Три сантиметра счастья! 📏",
        "Как три рубля в кошельке - мелочь, а приятно! 👛",
        "Медленно, но верно! 🐢"
    ],
    1: [
        "Мал, да удал! 🤏",
        "Один сантиметр лучше, чем ноль сантиметров! 1️⃣",
        "Fissure сказала: 'Я стараюсь!' 🥺"
    ],
    0: [
        "Стабильность - признак мастерства! ⚖️",
        "Fissure решила отдохнуть! 🛌",
        "Ни убавилось, ни прибавилось! 📊"
    ],
    -1: [
        "Fissure на диете! 🥗",
        "Маленький шаг назад для большого прыжка вперед! 🦘",
        "Сгорел один сантиметр... как спичка! 🕯️"
    ],
    -3: [
        "Три сантиметра в никуда! 🕳️",
        "Как потерять 300 рублей в такси! 🚕",
        "Fissure пошла на сокращение! 📉"
    ],
    -5: [
        "Пять сантиметров в неизвестность! 🌌",
        "Как потратить 500 рублей на ненужное! 💸",
        "Fissure в депрессии! 😔"
    ],
    -10: [
        "Десять сантиметров... как не бывало! 🫠",
        "Это как потерять телефон с кошельком! 📱👛",
        "Fissure пережила землетрясение! 🌋"
    ]
}

# =====================
# СЛУЧАЙНЫЕ ФРАЗЫ
# =====================

CATEGORY_PHRASES = {
    "up": [
        "Растёт… и ничего не спрашивает! 📈",
        "Бот инвестирует в твой успех! 💸",
        "Кто тут у нас подрос? 🤔",
        "Рост на лицо! 👀"
    ],
    "same": [
        "Всё стабильно, как кофе утром! ☕",
        "Fissure задумалась о смысле жизни... 🤔",
        "Зато не уменьшилась! 😊",
        "Отдых - это тоже работа! 😴"
    ],
    "down": [
        "Сжалась… тихо так, но гордо! 🥀",
        "Немного съежилась от скромности! 🙈",
        "Минус - это не приговор! ⚖️",
        "Бывает... (вздыхает) 😮‍💨"
    ],
    "fatal": [
        "💀 FISSURE В ШОКЕ!",
        "☠️ КРИТИЧЕСКИЙ УРОН!",
        "🔥 ВСЁ ГОРИТ!",
        "⚡ УДАР СУДЬБЫ!"
    ],
    "bonus_help": [
        "💖 СИСТЕМА ВЗЯЛА ТЕБЯ НА КАРМУ!",
        "🛡️ БОТ РЕШИЛ ПОМОЧЬ НОВИЧКУ!",
        "✨ МАГИЯ АЛГОРИТМОВ В ДЕЙСТВИИ!",
        "🎁 ПОДАРОК ОТ РАЗРАБОТЧИКА!"
    ]
}

def calculate_fissure_roll(current_fissure):
    """
    Рассчитывает новый бросок с учетом текущего размера fissure
    Возвращает: (значение броска, сообщение, является_ли_фатальным, получена_ли_помощь)
    """
    # 1. Проверяем шанс на фатальное уменьшение (только для больших fissure)
    if current_fissure >= 5:
        fatal_chance = min(0.05, current_fissure / 500)  # Максимум 5%
        if random.random() < fatal_chance:
            return FATAL_ROLL, "💀 ФАТАЛЬНОЕ УМЕНЬШЕНИЕ!", True, False
    
    # 2. УРОВЕНЬ 1: Критически маленький (< 0.5 см) - МАКСИМАЛЬНАЯ ПОМОЩЬ
    if current_fissure < 0.5:
        # 80% шанс на бонус
        if random.random() < 0.8:
            bonus_options = [
                (5, 30),   # +5 см (30%)
                (10, 25),  # +10 см (25%)
                (20, 20),  # +20 см (20%)
                (30, 15),  # +30 см (15%)
                (50, 10)   # +50 см (10%)
            ]
            values, weights = zip(*bonus_options)
            roll = random.choices(values, weights=weights)[0]
            return roll, "💖 МАКСИМАЛЬНАЯ ПОМОЩЬ СИСТЕМЫ!", False, True
        
        # 20% - обычный бросок, но без минусов
        protected_rolls = [0, 1, 3, 5, 10, 20]
        roll = random.choice(protected_rolls)
        return roll, "🛡️ ЗАЩИЩЕННЫЙ БРОСОК", False, True
    
    # 3. УРОВЕНЬ 2: Маленький (0.5 - 2 см) - УМЕРЕННАЯ ЗАЩИТА
    elif current_fissure < 2:
        # 40% шанс на улучшенный бросок
        if random.random() < 0.4:
            improved_options = [3, 5, 10, 20]
            roll = random.choice(improved_options)
            return roll, "✨ УЛУЧШЕННЫЙ БРОСОК!", False, True
        
        # 60% - обычный бросок со сниженными минусами
        weighted_rolls = [
            (-3, 5),   # 5%
            (-1, 10),  # 10%
            (0, 15),   # 15%
            (1, 20),   # 20%
            (3, 20),   # 20%
            (5, 15),   # 15%
            (10, 10),  # 10%
            (20, 5)    # 5%
        ]
        values, weights = zip(*weighted_rolls)
        roll = random.choices(values, weights=weights)[0]
        return roll, "", False, False
    
    # 4. УРОВЕНЬ 3: Средний (2 - 20 см) - БАЛАНС
    elif current_fissure < 20:
        # 20% шанс на бонус
        if random.random() < 0.2:
            bonus = random.choice([5, 10, 20])
            return bonus, "🎯 УДАЧНЫЙ БРОСОК!", False, False
        
        # 80% - стандартные шансы
        weighted_rolls = [
            (-3, 10),  # 10%
            (-1, 15),  # 15%
            (0, 20),   # 20%
            (1, 20),   # 20%
            (3, 15),   # 15%
            (5, 10),   # 10%
            (10, 7),   # 7%
            (20, 3)    # 3%
        ]
        values, weights = zip(*weighted_rolls)
        roll = random.choices(values, weights=weights)[0]
        return roll, "", False, False
    
    # 5. УРОВЕНЬ 4: Большой (20+ см) - ПОЛНЫЙ РИСК
    else:
        risky_rolls = [
            (-3, 15),  # 15%
            (-1, 20),  # 20%
            (0, 15),   # 15%
            (1, 15),   # 15%
            (3, 10),   # 10%
            (5, 10),   # 10%
            (10, 5),   # 5%
            (20, 3),   # 3%
            (50, 2)    # 2%
        ]
        values, weights = zip(*risky_rolls)
        roll = random.choices(values, weights=weights)[0]
        return roll, "", False, False

def apply_fissure_protection(current_fissure, roll, is_fatal):
    """
    Применяет защиту для маленьких fissure при фатальных бросках
    Возвращает: (фактическое изменение, сообщение_о_защите)
    """
    if is_fatal and current_fissure < 5:
        # Для маленьких fissure снижаем фатальный урон
        reduced_roll = max(-5, roll)  # Вместо -10 делаем максимум -5
        protection_msg = f"⚡ УРОН СНИЖЕН! Было бы {roll}, стало {reduced_roll}"
        return reduced_roll, protection_msg
    
    return roll, ""

def calculate_new_fissure(current_fissure, roll):
    """
    Рассчитывает новый размер fissure с минимальным пределом 0.1
    """
    new_value = current_fissure + roll
    return max(0.1, new_value)

def main_menu():
    keyboard = [
        [KeyboardButton("📈 Увеличить фиссуру")],
        [KeyboardButton("📏 Моя длина"), KeyboardButton("🏆 Топ")],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def format_time(seconds):
    h = seconds // 3600
    m = (seconds % 3600) // 60
    return f"{int(h)}ч {int(m)}м"

async def delete_previous_message(bot, chat_id, last_message_id):
    """Удаляет предыдущее сообщение бота"""
    try:
        if last_message_id and last_message_id > 0:
            await bot.delete_message(chat_id, last_message_id)
            logger.info(f"Удалено предыдущее сообщение: {last_message_id}")
    except Exception as e:
        logger.debug(f"Не удалось удалить предыдущее сообщение: {e}")

async def delete_user_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Удаляет сообщение пользователя"""
    try:
        logger.info(f"Удаляем сообщение пользователя: {update.message.message_id}")
        await context.bot.delete_message(update.message.chat_id, update.message.message_id)
        logger.info(f"Сообщение пользователя удалено: {update.message.message_id}")
    except Exception as e:
        logger.error(f"Не удалось удалить сообщение пользователя: {e}")

async def auto_delete_message(context: ContextTypes.DEFAULT_TYPE):
    """Автоудаление сообщения через 30 секунд"""
    try:
        chat_id = context.job.data['chat_id']
        message_id = context.job.data['message_id']
        await context.bot.delete_message(chat_id, message_id)
        logger.debug(f"Автоудалено сообщение: {message_id}")
    except Exception as e:
        logger.debug(f"Не удалось автоудалить сообщение: {e}")

def schedule_auto_delete(update: Update, context: ContextTypes.DEFAULT_TYPE, delay: int = 30):
    """Планирует автоудаление сообщения пользователя"""
    context.job_queue.run_once(
        auto_delete_message,
        delay,
        data={
            'chat_id': update.message.chat_id,
            'message_id': update.message.message_id
        },
        name=f"auto_delete_{update.message.chat_id}_{update.message.message_id}"
    )

async def send_or_update_message(bot, chat_id, text, reply_markup=None, last_message_id=0):
    """Отправляет новое сообщение или обновляет существующее"""
    try:
        logger.info(f"send_or_update_message: chat_id={chat_id}, last_message_id={last_message_id}")
        # Сначала отправляем новое сообщение
        msg = await bot.send_message(chat_id, text, reply_markup=reply_markup)
        logger.info(f"Отправлено сообщение: {msg.message_id}")
        
        # Затем удаляем предыдущее сообщение
        await delete_previous_message(bot, chat_id, last_message_id)
        
        return msg.message_id
    except Exception as e:
        logger.error(f"Ошибка отправки сообщения: {e}")
        return 0

async def fissure(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /fissure"""
    logger.info(f"Пользователь {update.effective_user.id} вызвал fissure")
    
    uid = update.effective_user.id
    user_obj = update.effective_user
    username = user_obj.username or user_obj.first_name
    now = time.time()
    
    try:
        user = get_user(uid, username)
        logger.info(f"user data: {user}")
        
        if now - user["last_fissure"] < COOLDOWN:
            wait = COOLDOWN - (now - user["last_fissure"])
            text = f"⏳ Фиссура ещё восстанавливается.\nЖди: {format_time(wait)}"
            message_id = await send_or_update_message(
                context.bot,
                update.message.chat_id,
                text,
                main_menu(),
                user.get("last_message_id", 0)
            )
            update_last_message_id(uid, message_id)
            return

        # Новая логика рандома
        roll, special_message, is_fatal, got_help = calculate_fissure_roll(user["fissure"])
        
        # Применяем защиту при фатальном броске
        roll, protection_msg = apply_fissure_protection(user["fissure"], roll, is_fatal)
        
        # Рассчитываем новое значение
        new_fissure = calculate_new_fissure(user["fissure"], roll)
        update_fissure(uid, new_fissure, now)
        
        # Логируем успешное обновление времени перезарядки
        logger.info(f"Пользователь {uid} использовал фиссуру. Новое время перезарядки: {now}")

        # Формируем текст сообщения - только 1 фраза или мем
        roll_key = min(roll, 50)
        roll_key = max(roll_key, -10)
        
        # Выбираем текст результата
        if roll_key in ROLL_TEXTS:
            result_text = random.choice(ROLL_TEXTS[roll_key])
        else:
            result_text = f"{'+' if roll > 0 else ''}{roll} см"
        
        # Выбираем категорию
        if is_fatal:
            category = "fatal"
        elif got_help:
            category = "bonus_help"
        elif roll > 0:
            category = "up"
        elif roll < 0:
            category = "down"
        else:
            category = "same"
        
        # 50/50 - либо фраза из категории, либо мем из ROLL_MEMES
        if roll_key in ROLL_MEMES and random.random() < 0.5:
            extra_text = random.choice(ROLL_MEMES[roll_key])
        else:
            extra_text = random.choice(CATEGORY_PHRASES[category])
        
        # Формируем сообщение
        text = f"{result_text}\n{extra_text}"
        
        if is_fatal and protection_msg:
            text = f"{text}\n\n{protection_msg}"
        
        # Отправляем сообщение в чат с reply на сообщение пользователя
        try:
            await context.bot.send_message(
                chat_id=update.message.chat_id,
                text=text,
                reply_markup=main_menu(),
                reply_to_message_id=update.message.message_id
            )
            logger.info(f"Результат отправлен как reply пользователю {uid}")
        except Exception as e:
            logger.error(f"Ошибка отправки: {e}")
            # Fallback - просто отправляем в чат
            message_id = await send_or_update_message(
                context.bot,
                update.message.chat_id,
                text,
                main_menu(),
                user.get("last_message_id", 0)
            )
            update_last_message_id(uid, message_id)
        
        # Удаляем сообщение пользователя в чате
        try:
            await delete_user_message(update, context)
            schedule_auto_delete(update, context)
        except Exception as e:
            logger.error(f"Ошибка при удалении: {e}")
        
    except Exception as e:
        logger.error(f"Ошибка в fissure: {e}")
        await update.message.reply_text("❌ Ошибка при обработке запроса")

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать статистику"""
    logger.info(f"Пользователь {update.effective_user.id} вызвал stats")
    
    try:
        uid = update.effective_user.id
        user_obj = update.effective_user
        username = user_obj.username or user_obj.first_name
        user = get_user(uid, username)
        logger.info(f"stats user data: {user}")
        
        text = f"📏 Текущая длина фиссуры: {user['fissure']:.1f} см"
        message_id = await send_or_update_message(
            context.bot,
            update.message.chat_id,
            text,
            main_menu(),
            user.get("last_message_id", 0)
        )
        update_last_message_id(uid, message_id)
        
        # Сразу удаляем + fallback через 30 сек
        try:
            await delete_user_message(update, context)
            schedule_auto_delete(update, context)
        except Exception as e:
            logger.error(f"Ошибка при удалении: {e}")
        
    except Exception as e:
        logger.error(f"Ошибка в stats: {e}")
        text = "❌ Ошибка при получении статистики"
        message_id = await send_or_update_message(
            context.bot,
            update.message.chat_id,
            text,
            main_menu(),
            user.get("last_message_id", 0) if 'user' in locals() else 0
        )
        if 'user' in locals():
            update_last_message_id(uid, message_id)

async def top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать топ"""
    logger.info(f"Пользователь {update.effective_user.id} вызвал top")
    
    try:
        uid = update.effective_user.id
        user_obj = update.effective_user
        username = user_obj.username or user_obj.first_name
        user = get_user(uid, username)
        logger.info(f"top user data: {user}")
        
        top_users = get_fissure_top()
        logger.info(f"Получено {len(top_users)} пользователей для топа")
        
        if not top_users:
            text = "🏆 Топ Фиссур:\n\nПока нет данных для отображения топа"
            message_id = await send_or_update_message(
                context.bot,
                update.message.chat_id,
                text,
                main_menu(),
                user.get("last_message_id", 0)
            )
            update_last_message_id(uid, message_id)
            return
            
        text = "🏆 Топ Фиссур:\n\n"
        for i, u in enumerate(top_users, 1):
            username = u['username'] or f"Пользователь {u['telegram_id']}"
            text += f"{i}. {username} — {u['fissure']:.1f} см\n"
        
        message_id = await send_or_update_message(
            context.bot,
            update.message.chat_id,
            text,
            main_menu(),
            user.get("last_message_id", 0)
        )
        update_last_message_id(uid, message_id)
        
        # Сразу удаляем + fallback через 30 сек
        try:
            await delete_user_message(update, context)
            schedule_auto_delete(update, context)
        except Exception as e:
            logger.error(f"Ошибка при удалении: {e}")
        
    except Exception as e:
        logger.error(f"Ошибка в top: {e}")
        text = "❌ Ошибка при получении топа"
        message_id = await send_or_update_message(
            context.bot,
            update.message.chat_id,
            text,
            main_menu(),
            user.get("last_message_id", 0) if 'user' in locals() else 0
        )
        if 'user' in locals():
            update_last_message_id(uid, message_id)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    logger.info(f"Новый пользователь {update.effective_user.id}")
    
    try:
        uid = update.effective_user.id
        user_obj = update.effective_user
        username = user_obj.username or user_obj.first_name
        user = get_user(uid, username)
        logger.info(f"start user data: {user}")
        
        text = "Добро пожаловать!\nЗдесь можно увеличить фиссуру 😈"
        message_id = await send_or_update_message(
            context.bot,
            update.message.chat_id,
            text,
            main_menu(),
            user.get("last_message_id", 0)
        )
        update_last_message_id(uid, message_id)
        
        # Сразу удаляем + fallback через 30 сек
        try:
            await delete_user_message(update, context)
            schedule_auto_delete(update, context)
        except Exception as e:
            logger.error(f"Ошибка при удалении: {e}")
        
    except Exception as e:
        logger.error(f"Ошибка в start: {e}")
        text = "❌ Ошибка при запуске бота"
        message_id = await send_or_update_message(
            context.bot,
            update.message.chat_id,
            text,
            None,
            user.get("last_message_id", 0) if 'user' in locals() else 0
        )
        if 'user' in locals():
            update_last_message_id(uid, message_id)

async def menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик кнопок меню"""
    text = update.message.text
    
    # Проверяем что это кнопка меню (а не обычный текст)
    menu_buttons = ["📈 Увеличить фиссуру", "📏 Моя длина", "🏆 Топ"]
    
    if text not in menu_buttons:
        # Игнорируем все не-кнопочные сообщения
        return
    
    logger.info(f"Пользователь {update.effective_user.id} нажал кнопку: {text}")
    
    try:
        uid = update.effective_user.id
        user_obj = update.effective_user
        username = user_obj.username or user_obj.first_name
        get_user(uid, username)

        if text == "📈 Увеличить фиссуру":
            await fissure(update, context)
        elif text == "📏 Моя длина":
            await stats(update, context)
        elif text == "🏆 Топ":
            await top(update, context)
    except Exception as e:
        logger.error(f"Ошибка в menu_handler: {e}")
        await update.message.reply_text("❌ Ошибка при обработке команды")

    # Удаляем сообщение пользователя (только кнопки)
    try:
        await context.bot.delete_message(update.message.chat_id, update.message.message_id)
    except Exception as e:
        logger.debug(f"Не удалось удалить сообщение: {e}")

async def health_check(request):
    """Health check endpoint for Render"""
    return web.Response(text="✅ Бот работает", status=200)

async def wake_up_callback(context: ContextTypes.DEFAULT_TYPE):
    """Периодический wake-up для предотвращения сна"""
    logger.info("🛠️ Wake-up: бот активен")
    try:
        # Пингуем себя через health endpoint
        await context.bot.send_message(chat_id=int(os.getenv("ADMIN_ID", 0)), text="🛠️ Бот проснулся и работает!")
    except Exception as e:
        logger.debug(f"Wake-up ping не отправлен: {e}")

def setup_wake_up(job_queue: JobQueue):
    """Настраивает периодический wake-up каждые 14 минут"""
    wake_up_interval = 14 * 60  # 14 минут в секундах
    job_queue.run_repeating(wake_up_callback, wake_up_interval, first=60)
    logger.info(f"🌙 Wake-up настроен: каждые {wake_up_interval} секунд")

async def main():
    """Запуск Telegram бота в webhook режиме для Render"""
    if not TOKEN:
        logger.error("❌ BOT_TOKEN не задан! Бот не может запуститься.")
        return
    
    try:
        init_db()
        
        # Создаем веб-приложение для webhook
        app = ApplicationBuilder().token(TOKEN).job_queue(JobQueue()).build()

        # Добавляем обработчики команд
        app.add_handler(CommandHandler("start", start))
        app.add_handler(CommandHandler("fissure", fissure))
        app.add_handler(CommandHandler("stats", stats))
        app.add_handler(CommandHandler("top", top))
        # Обработка команд с @botname
        app.add_handler(MessageHandler(filters.Regex(r'^/start@DotaFull_bot$'), start))
        app.add_handler(MessageHandler(filters.Regex(r'^/fissure@DotaFull_bot$'), fissure))
        app.add_handler(MessageHandler(filters.Regex(r'^/stats@DotaFull_bot$'), stats))
        app.add_handler(MessageHandler(filters.Regex(r'^/top@DotaFull_bot$'), top))
        app.add_handler(MessageHandler(filters.Regex(r'^(📈 Увеличить фиссуру|📏 Моя длина|🏆 Топ)$'), menu_handler))

        # Получаем webhook URL из переменных окружения
        webhook_url = os.getenv("WEBHOOK_URL")
        if not webhook_url:
            logger.error("❌ WEBHOOK_URL не задан! Укажите URL для webhook.")
            return
            
        # Настраиваем webhook
        await app.bot.set_webhook(url=webhook_url)
        
        # Инициализируем приложение перед обработкой webhook
        await app.initialize()
        
        logger.info("✅ Telegram бот запущен в режиме webhook")
        logger.info(f"📡 Webhook URL: {webhook_url}")
        
        # Настраиваем периодический wake-up
        setup_wake_up(app.job_queue)
        
        # Создаем веб-сервер с aiohttp
        from aiohttp import web
        
        async def handle_webhook(request):
            """Обработка входящих webhook запросов"""
            try:
                update_data = await request.json()
                logger.info(f"Webhook received: {update_data.get('update_id', 'unknown')}")
                update = Update.de_json(update_data, app.bot)
                logger.info(f"Update parsed: {update}")
                await app.process_update(update)
                logger.info(f"Update processed")
                return web.Response(status=200)
            except Exception as e:
                logger.error(f"Ошибка обработки webhook: {e}", exc_info=True)
                return web.Response(status=500)
        
        # Создаем приложение
        web_app = web.Application()
        web_app.router.add_post('/webhook', handle_webhook)
        web_app.router.add_get('/health', health_check)
        
        # Запускаем веб-сервер
        runner = web.AppRunner(web_app)
        await runner.setup()
        site = web.TCPSite(runner, '0.0.0.0', int(os.getenv('PORT', 8080)))
        await site.start()
        
        logger.info("🌐 Веб-сервер запущен")
        
        # Бесконечный цикл для поддержания работы
        while True:
            await asyncio.sleep(3600)
            
    except Exception as e:
        logger.error(f"❌ Критическая ошибка: {e}", exc_info=True)
        raise

async def main_polling():
    """Запуск Telegram бота в режиме polling для локального тестирования"""
    if not TOKEN:
        logger.error("❌ BOT_TOKEN не задан! Бот не может запуститься.")
        return
    
    try:
        init_db()
        
        # Создаем Telegram бота
        app = ApplicationBuilder().token(TOKEN).job_queue(JobQueue()).build()

        # Добавляем обработчики команд
        app.add_handler(CommandHandler("start", start))
        app.add_handler(CommandHandler("fissure", fissure))
        app.add_handler(CommandHandler("stats", stats))
        app.add_handler(CommandHandler("top", top))
        # Обработка команд с @botname
        app.add_handler(MessageHandler(filters.Regex(r'^/start@DotaFull_bot$'), start))
        app.add_handler(MessageHandler(filters.Regex(r'^/fissure@DotaFull_bot$'), fissure))
        app.add_handler(MessageHandler(filters.Regex(r'^/stats@DotaFull_bot$'), stats))
        app.add_handler(MessageHandler(filters.Regex(r'^/top@DotaFull_bot$'), top))
        app.add_handler(MessageHandler(filters.Regex(r'^(📈 Увеличить фиссуру|📏 Моя длина|🏆 Топ)$'), menu_handler))

        logger.info("✅ Telegram бот запущен в режиме polling")
        
        # Запускаем бота в режиме polling
        await app.run_polling(drop_pending_updates=True)
        
    except Exception as e:
        logger.error(f"❌ Критическая ошибка: {e}", exc_info=True)
        raise

if __name__ == "__main__":
    # Запускаем бота с использованием современного подхода asyncio
    try:
        # Используем asyncio.run() для чистого запуска
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 Бот остановлен пользователем")
    except Exception as e:
        print(f"❌ Ошибка запуска бота: {e}")
        raise
