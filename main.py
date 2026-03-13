# -*- coding: utf-8 -*-
import os
import random
import time
import asyncio
import logging
import datetime
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters, JobQueue, ChatMemberHandler
from telegram.error import Conflict
from database import init_db, get_user, update_fissure, get_fissure_top, update_last_message_id, Database, get_user_rank, decrease_inactive_fissure
from aiohttp import web

# Logging setup
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    print("WARNING: BOT_TOKEN is not set!")
else:
    print("BOT_TOKEN found")

COOLDOWN = 86400  # 24 hours


async def delete_after_delay(bot, chat_id, msg_id, delay, job_queue=None):
    """Удалить сообщение через delay секунд"""
    if job_queue:
        # Используем JobQueue для надежного планирования
        job_queue.run_once(
            delete_message_job,
            delay,
            data={'chat_id': chat_id, 'msg_id': msg_id},  # data для PTB
            name=f"delete_{chat_id}_{msg_id}"
        )
    else:
        # Fallback - пытаемся удалить сразу (менее надежно)
        await asyncio.sleep(delay)
        try:
            await bot.delete_message(chat_id, msg_id)
            logger.info(f"Deleted delayed message {msg_id} in chat {chat_id}")
        except Exception as e:
            error_str = str(e).lower()
            if "message to delete not found" in error_str or "bad request" in error_str:
                logger.debug(f"Message {msg_id} already deleted in chat {chat_id}")
            else:
                logger.warning(f"Failed to delete delayed message {msg_id}: {e}")


async def delete_message_job(context):
    """Job для удаления сообщения"""
    bot = context.application.bot  # Доступ через context.application.bot в PTB v20+
    chat_id = context.job.data['chat_id']
    msg_id = context.job.data['msg_id']
    try:
        await bot.delete_message(chat_id, msg_id)
        logger.info(f"Deleted scheduled message {msg_id} in chat {chat_id}")
    except Exception as e:
        error_str = str(e).lower()
        if "message to delete not found" in error_str or "bad request" in error_str:
            # Message already deleted or can't be deleted - this is normal
            logger.debug(f"Message {msg_id} already deleted in chat {chat_id}")
        else:
            logger.warning(f"Failed to delete message {msg_id} in chat {chat_id}: {e}")


def schedule_delete(bot, chat_id, msg_id, delay=30, job_queue=None):
    """Запланировать удаление сообщения через delay секунд"""
    if job_queue:
        job_queue.run_once(
            delete_message_job,
            delay,
            data={'chat_id': chat_id, 'msg_id': msg_id},  # data для PTB
            name=f"delete_{chat_id}_{msg_id}"
        )
    else:
        # Fallback если job_queue не передан
        asyncio.create_task(delete_after_delay(bot, chat_id, msg_id, delay))


async def decrease_inactive_job(context):
    """Ежедневное задание: уменьшить fissure неактивным игрокам"""
    try:
        logger.info("Запуск ежедневного уменьшения fissure для неактивных игроков")
        affected = decrease_inactive_fissure(days_inactive=1, decrease_amount=1.0)
        if affected > 0:
            logger.info(f"Уменьшен fissure для {affected} неактивных игроков")
        else:
            logger.info("Нет неактивных игроков для уменьшения fissure")
    except Exception as e:
        logger.error(f"Ошибка в decrease_inactive_job: {e}")


# =====================
# ROLL SYSTEM
# =====================

BASE_ROLLS = [-3, -1, 0, 1, 3, 5, 10, 20]
FATAL_ROLL = -10

# =====================
# ROLL TEXTS
# =====================

ROLL_TEXTS = {
    50: ["🔥🔥🔥 НЕВЕРОЯТНО! +50 см!", "💰 ДЖЕКПОТ! +50 см за раз!", "🦸 ЛЕГЕНДАРНО! +50 СМ!", "👑 ДОМИНИРУЕШЬ! +50 СМ!", "💀 БОЖЕСТВЕННО! +50 СМ!"],
    30: ["🚀 КОСМОС! +30 см!", "🍀 СУПЕР УДАЧА! +30 см!", "⚡ СИЛА УЛЬТЫ! +30 СМ!", "🔥 МЕГА КИЛЛ! +30 СМ!"],
    20: ["💪 MEGA УСПЕХ! +20 см!", "🎯 ТОЧНО В ДЕСЯТКУ! +20 см!", "🎯 ДВОЙНОЙ КИЛЛ! +20 СМ!", "💪 НЕУДЕРЖИМ! +20 СМ!"],
    10: ["🌟 ЛЕГЕНДА! +10 см!", "🔥 ОГОНЬ! +10 см!", "🌟 ПЕРВАЯ КРОВЬ! +10 СМ!", "🎮 УБИЙСТВЕННАЯ СЕРИЯ! +10 СМ!"],
    5: ["🎉 УРА! +5 см!", "👍 ОТЛИЧНО! +5 см!", "✅ НОРМ! +5 СМ!", "👍 КРАСАВА! +5 СМ!"],
    3: ["😊 НЕПЛОХО! +3 см", "📈 РАСТЁМ! +3 см", "💪 НА! +3 СМ", "🔥 В ОГНЕ! +3 СМ"],
    1: ["✅ OK! +1 см", "💪 ЕСТЬ РОСТ! +1 см", "🙄 ПОВЕЗЛО! +1 СМ", "🤔 МОГЛО БЫТЬ ХУЖЕ! +1 СМ"],
    0: ["❌ БЕЗ ИЗМЕНЕНИЙ", "💤 СТОИМ НА МЕСТЕ", "❌ НИЧЬЯ", "💤 АФК?"],
    -1: ["🤔 НЕМНОГО -1 см", "📉 МИНУС -1 см", "😬 ОЙ! -1 СМ", "💀 КОРМ! -1 СМ"],
    -3: ["😬 ОЙ... -3 см", "⬇️ УПАЛ -3 см", "🤕 ДЕНАЙ! -3 СМ", "☠️ НАРЖАЛ! -3 СМ"],
    -5: ["😢 БОЛЬНО -5 см...", "💔 НЕУДАЧА -5 см", "💀 ПОПАЛ! -5 СМ...", "🎮 ГГ ВП... -5 СМ"],
    -10: ["💥 КАТАСТРОФА! -10 см!!!", "🌋 АПОКАЛИПСИС! -10 см!!!", "😵 СЕРВЕР УПАЛ! -10 СМ!!!", "💥 ДИСКОННЕКТ! -10 СМ!!!"]
}

ROLL_MEMES = {
    50: [
        "💪 Ваша фиссура больше, чем чья-то самооценка!",
        "🔍 Прохожий: 'А что это за большая штука?'",
        "📺 Теперь можно создавать OnlyFissures канал!"
    ],
    30: [
        "🎁 Это как найти 1000 рублей в старых джинсах!",
        "🛋️ Теперь можно достать пульт не вставая!",
        "💵 Поздравления в рублях, долларах и см!"
    ],
    20: [
        "📈 Ваша фиссура выросла больше, чем акции Теслы!",
        "🎤 Это уже не фиссура, а ФИССУУУРА!",
        "📏 Размер имеет значение! (оказалось, что да)"
    ],
    10: [
        "🎰 Это как получить бонус в понедельник!",
        "🌱 Фиссура: 'Я расту!'",
        "🏠 Теперь вы на 10 см ближе к потолку!"
    ],
    5: [
        "💰 Это как найти 500 рублей в кармане!",
        "😄 Среднестатистический русский доволен!",
        "📐 Можно мерить икеевской линейкой!"
    ],
    3: [
        "🎊 Три сантиметра счастья!",
        "💵 Как три рубля в кошельке - мелочь, но приятно!",
        "🐢 Медленно, но верно!"
    ],
    1: [
        "💪 Маленький, но гордый!",
        "✅ Один см лучше, чем ноль см!",
        "🙏 Фиссура сказала: 'Я стараюсь!'",
        "🌱 Будет и на вашей улице праздник!"
    ],
    0: [
        "🛡️ Стабильность - признак мастерства!",
        "😴 Фиссура решила отдохнуть!",
        "➡️ Ни уменьшилось, ни увеличилось!"
    ],
    -1: [
        "🥗 Фиссура на диете!",
        "👣 Один маленький шаг назад для большого прыжка вперёд!",
        "🔥 Один сантиметр сгорел... как спичка!"
    ],
    -3: [
        "📉 Три сантиметра в никуда!",
        "😤 Фиссура чихнула!",
        "⚖️ Гравитация побеждает в этом раунде!",
        "😤 Ганкнули на ровном месте!"
    ],
    -5: [
        "📺 Когда фиссура объявляет забастовку!",
        "⭐ Минус пять - как плохой отзыв!",
        "🏖️ Фиссуре нужен отпуск!",
        "💀 Бездыханное тело!"
    ],
    -10: [
        "💥 ПОЛНОЕ УНИЧТОЖЕНИЕ!",
        "🦸 Из героя в ноль!",
        "👋 Фиссура покинула чат!",
        "👻 0/10/0!",
        "🔥 ТИЛЬТ МОД АКТИВИРОВАН!",
        "☠️ ГГ, СЛЕДУЮЩИЙ!"
    ]
}

CATEGORY_PHRASES = {
    "up": [
        "💪 Растём!",
        "📏 Каждый см важен!",
        "✅ Фиссура одобряет!",
        "📈 Положительная динамика!",
        "🔥 Так держать!",
        "⬆️ Вверх и только вверх!"
    ],
    "down": [
        "😔 Небольшой откат!",
        "💪 Фиссура восстановится!",
        "🌅 Завтра новый день!",
        "⏳ Временный спад!",
        "💪 Не сдавайся!",
        "🎯 Это ещё не конец!"
    ],
    "same": [
        "🛡 Стабильность - это хорошо!",
        "💪 Держим позиции!",
        "➡️ Без изменений - тоже результат!",
        "⚓ Твёрдо как скала!",
        "📊 Постоянство важно!",
        "🏗️ Прочный фундамент!"
    ],
    "bonus_help": [
        "✨ СИСТЕМА ПОМОГЛА!",
        "🍀 Удачный расклад!",
        "🎁 БОНУС!",
        "🛡 КРИТИЧЕСКАЯ ПОДДЕРЖКА!",
        "💰 ДЖЕКПОТ!",
        "🚀 МНОЖИТЕЛЬ!"
    ],
    "fatal": [
        "💥 КРИТИЧЕСКИЙ УРОН!",
        "🔥 Но ты устоял!",
        "🦾 ВЫЖИЛ!",
        "🎮 Ещё в игре!",
        "💪 Стойкость!",
        "🏆 Никогда не сдавайся!"
    ]
}

WELCOME_PHRASES = [
    "Привет, {name}! Твоя фиссурная история начинается!",
    "Рады видеть тебя, {name}! Время расти!",
    "{name} присоединился! Фиссурное сообщество растёт!",
    "Привет, {name}! Давай увеличивать вместе!",
    "{name} здесь! Новые возможности ждут!",
    "Привет, {name}! Твоя фиссура ждёт!",
    "Приятно видеть, {name}! Давай станем больше!",
    "{name} присоединился к фиссурному клубу!",
    "Эй, {name}! Время измерить!",
    "{name} готов расти!"
]

# Track last bot message per user per chat for cleanup
last_bot_message = {}  # {chat_id: {user_id: message_id}}


async def delete_last_bot_message(bot, chat_id, user_id):
    """Delete the last bot message for this user in this chat immediately"""
    if chat_id in last_bot_message and user_id in last_bot_message[chat_id]:
        msg_id = last_bot_message[chat_id][user_id]
        try:
            await bot.delete_message(chat_id, msg_id)
            logger.info(f"Deleted last bot message for user {user_id}: {msg_id}")
        except Exception as e:
            error_str = str(e).lower()
            if "message to delete not found" in error_str or "bad request" in error_str:
                # Message already deleted or can't be deleted - this is normal
                logger.debug(f"Message {msg_id} already deleted in chat {chat_id}: {e}")
            else:
                logger.warning(f"Could not delete last bot message {msg_id}: {e}")
        finally:
            # Always remove from dictionary after trying
            del last_bot_message[chat_id][user_id]
            # Clean up empty chat entries
            if not last_bot_message[chat_id]:
                del last_bot_message[chat_id]


def set_last_bot_message(chat_id, user_id, message_id):
    """Set the last bot message for this user in this chat"""
    if chat_id not in last_bot_message:
        last_bot_message[chat_id] = {}
    last_bot_message[chat_id][user_id] = message_id


def calculate_fissure_roll(current_fissure):
    """
    Calculates new roll based on current fissure size
    Returns: (roll_value, message, is_fatal, got_help)
    """
    if current_fissure >= 5:
        fatal_chance = min(0.05, current_fissure / 500)
        if random.random() < fatal_chance:
            return FATAL_ROLL, "FATAL DECREASE!", True, False
    
    if current_fissure < 0.5:
        if random.random() < 0.8:
            bonus_options = [
                (5, 30), (10, 25), (20, 20), (30, 15), (50, 10)
            ]
            values, weights = zip(*bonus_options)
            roll = random.choices(values, weights=weights)[0]
            return roll, "✨ МАКСИМАЛЬНАЯ ПОМОЩЬ!", False, True
        
        protected_rolls = [0, 1, 3, 5, 10, 20]
        roll = random.choice(protected_rolls)
        return roll, "🛡 ЗАЩИЩЁННЫЙ РОЛЛ", False, True
    
    elif current_fissure < 2:
        if random.random() < 0.4:
            improved_options = [3, 5, 10, 20]
            roll = random.choice(improved_options)
            return roll, "🚀 УЛУЧШЕННЫЙ РОЛЛ!", False, True
        
        weighted_rolls = [
            (-3, 5), (-1, 10), (0, 15), (1, 20), (3, 20), (5, 15), (10, 10), (20, 5)
        ]
        values, weights = zip(*weighted_rolls)
        roll = random.choices(values, weights=weights)[0]
        return roll, "", False, False
    
    elif current_fissure < 20:
        if random.random() < 0.2:
            bonus = random.choice([5, 10, 20])
            return bonus, "🍀 УДАЧНЫЙ РОЛЛ!", False, False
        
        weighted_rolls = [
            (-3, 10), (-1, 15), (0, 20), (1, 20), (3, 15), (5, 10), (10, 7), (20, 3)
        ]
        values, weights = zip(*weighted_rolls)
        roll = random.choices(values, weights=weights)[0]
        return roll, "", False, False
    
    else:
        risky_rolls = [
            (-3, 15), (-1, 20), (0, 15), (1, 15), (3, 10), (5, 10), (10, 5), (20, 3), (50, 2)
        ]
        values, weights = zip(*risky_rolls)
        roll = random.choices(values, weights=weights)[0]
        return roll, "", False, False


def apply_fissure_protection(current_fissure, roll, is_fatal):
    """Applies protection for small fissures on fatal rolls"""
    if is_fatal and current_fissure < 5:
        reduced_roll = max(-5, roll)
        protection_msg = f"🛡 УРОН СНИЖЕН! Было {roll}, теперь {reduced_roll}"
        return reduced_roll, protection_msg
    
    return roll, ""


def calculate_new_fissure(current_fissure, roll):
    """Calculates new fissure size with minimum 0.1"""
    new_value = current_fissure + roll
    return max(0.1, new_value)


def main_menu():
    keyboard = [
        [KeyboardButton("📈 Увеличить фиссуру")],
        [KeyboardButton("📏 Моя длина"), KeyboardButton("🏆 Топ")],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)


def format_time(seconds):
    h = seconds // 3600
    m = (seconds % 3600) // 60
    return f"{int(h)}ч {int(m)}м"


async def fissure(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Increase fissure"""
    logger.info(f"User {update.effective_user.id} called fissure")
    
    user_obj = update.effective_user
    username = user_obj.username or user_obj.first_name
    chat_id = update.message.chat_id
    chat_type = update.message.chat.type
    user_msg_id = update.message.message_id
    now = time.time()
    
    # Delete user message only in groups/channels (not in private)
    if chat_type in ['group', 'supergroup', 'channel']:
        try:
            await context.bot.delete_message(chat_id, user_msg_id)
        except Exception as e:
            logger.debug(f"Could not delete user message: {e}")
    
    # Delete last bot message immediately
    try:
        await delete_last_bot_message(context.bot, chat_id, user_obj.id)
    except Exception as e:
        logger.debug(f"Could not delete last bot message: {e}")
    
    try:
        user = get_user(user_obj.id, username)
        logger.info(f"user data: {user}")
        
        if now - user["last_fissure"] < COOLDOWN:
            wait = COOLDOWN - (now - user["last_fissure"])
            text = f"⏳ Фиссура восстанавливается. Подожди: {format_time(wait)}"
            result_msg = await context.bot.send_message(
                chat_id=update.message.chat_id,
                text=text,
                reply_markup=main_menu()
            )
            set_last_bot_message(chat_id, user_obj.id, result_msg.message_id)
            schedule_delete(context.bot, chat_id, result_msg.message_id, 30, context.application.job_queue)
            update_last_message_id(user_obj.id, result_msg.message_id)
            return

        roll, special_message, is_fatal, got_help = calculate_fissure_roll(user["fissure"])
        roll, protection_msg = apply_fissure_protection(user["fissure"], roll, is_fatal)
        new_fissure = calculate_new_fissure(user["fissure"], roll)
        update_fissure(user_obj.id, new_fissure, now, roll)
        
        logger.info(f"User {user_obj.id} used fissure. New cooldown: {now}")

        roll_key = min(roll, 50)
        roll_key = max(roll_key, -10)
        
        if roll_key in ROLL_TEXTS:
            result_text = random.choice(ROLL_TEXTS[roll_key])
        else:
            result_text = f"{'+' if roll > 0 else ''}{roll} см"
        
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
        
        if roll_key in ROLL_MEMES and random.random() < 0.5:
            extra_text = random.choice(ROLL_MEMES[roll_key])
        else:
            extra_text = random.choice(CATEGORY_PHRASES[category])
        
        text = (
            f"🎲 {username}\n\n"
            f"{result_text}\n"
            f"{extra_text}\n\n"
            f"📏 Длина сейчас: {new_fissure:.1f} см"
        )
        
        if is_fatal and protection_msg:
            text = f"{text}\n\n{protection_msg}"
        
        logger.info(f"Sending result message to chat_id={update.message.chat_id}")
        # Don't use reply_to_message_id because user message was already deleted
        result_msg = await context.bot.send_message(
            chat_id=update.message.chat_id,
            text=text,
            reply_markup=main_menu()
        )
        logger.info(f"Result message sent successfully: message_id={result_msg.message_id}")
        set_last_bot_message(chat_id, user_obj.id, result_msg.message_id)
        schedule_delete(context.bot, chat_id, result_msg.message_id, 600, context.application.job_queue)
        update_last_message_id(user_obj.id, result_msg.message_id)
                  
    except Exception as e:
        logger.error(f"Error in fissure: {e}", exc_info=True)
        try:
            if update.message:
                await update.message.reply_text("❌ Ошибка обработки запроса")
        except Exception:
            pass


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show stats"""
    logger.info(f"User {update.effective_user.id} called stats")
    
    chat_id = update.message.chat_id
    chat_type = update.message.chat.type
    
    # Delete user message only in groups/channels
    if chat_type in ['group', 'supergroup', 'channel']:
        user_msg_id = update.message.message_id
        try:
            await context.bot.delete_message(chat_id, user_msg_id)
        except Exception as e:
            logger.debug(f"Could not delete user message: {e}")
    
    # Delete last bot message immediately
    try:
        await delete_last_bot_message(context.bot, chat_id, update.effective_user.id)
    except Exception as e:
        logger.debug(f"Could not delete last bot message: {e}")
    
    try:
        user_obj = update.effective_user
        username = user_obj.username or user_obj.first_name
        user = get_user(user_obj.id, username)
        
        last_fissure_time = user["last_fissure"]
        now = time.time()
        time_since_last = now - last_fissure_time
        remaining_cooldown = max(0, COOLDOWN - time_since_last)
        
        if remaining_cooldown > 0:
            wait_text = f"Восстановление: {format_time(remaining_cooldown)}"
        else:
            wait_text = "✅ Готов к увеличению!"
        
        text = f"🎲 {username}\n\n📏 Длина: {user['fissure']:.1f} см"
        
        result_msg = await context.bot.send_message(
            chat_id=update.message.chat_id,
            text=text,
            reply_markup=main_menu()
        )
        set_last_bot_message(chat_id, user_obj.id, result_msg.message_id)
        schedule_delete(context.bot, chat_id, result_msg.message_id, 30, context.application.job_queue)
        update_last_message_id(user_obj.id, result_msg.message_id)
        
    except Exception as e:
        logger.error(f"Error in stats: {e}", exc_info=True)
        try:
            await update.message.reply_text("❌ Ошибка получения статистики")
        except Exception:
            pass


async def top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show top users"""
    logger.info(f"User {update.effective_user.id} called top")
    
    chat_id = update.message.chat_id
    chat_type = update.message.chat.type
    
    # Delete user message only in groups/channels
    if chat_type in ['group', 'supergroup', 'channel']:
        user_msg_id = update.message.message_id
        try:
            await context.bot.delete_message(chat_id, user_msg_id)
        except Exception as e:
            logger.debug(f"Could not delete user message: {e}")
    
    # Delete last bot message immediately
    try:
        await delete_last_bot_message(context.bot, chat_id, update.effective_user.id)
    except Exception as e:
        logger.debug(f"Could not delete last bot message: {e}")
    
    try:
        top_users = get_fissure_top(10)
        user_rank = get_user_rank(update.effective_user.id)
        user = get_user(update.effective_user.id, update.effective_user.username)
        
        if not top_users:
            text = "😶 Пока нет игроков. Будь первым!"
        else:
            text = "🏆 Топ 10 Фиссур\n\n"
            for i, user_top in enumerate(top_users, 1):
                name = user_top.get('username', 'Unknown')[:15]
                text += f"{i}. {name}: {user_top['fissure']:.1f} см\n"
            
            if user_rank:
                user_fissure = user.get('fissure', 0) if user else 0
                text += f"\n👤 Твоя позиция: #{user_rank} ({user_fissure:.1f} см)"
        
        result_msg = await context.bot.send_message(
            chat_id=update.message.chat_id,
            text=text,
            reply_markup=main_menu()
        )
        set_last_bot_message(chat_id, update.effective_user.id, result_msg.message_id)
        schedule_delete(context.bot, chat_id, result_msg.message_id, 30, context.application.job_queue)
        update_last_message_id(update.effective_user.id, result_msg.message_id)
        
    except Exception as e:
        logger.error(f"Error in top: {e}", exc_info=True)
        try:
            await update.message.reply_text("❌ Ошибка получения топа")
        except Exception:
            pass


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    logger.info(f"New user {update.effective_user.id}")
    
    chat_id = update.message.chat_id
    chat_type = update.message.chat.type
    
    # Delete user command only in groups/channels
    if chat_type in ['group', 'supergroup', 'channel']:
        user_msg_id = update.message.message_id
        try:
            await context.bot.delete_message(chat_id, user_msg_id)
        except Exception:
            pass
    
    # Delete last bot message
    try:
        await delete_last_bot_message(context.bot, chat_id, update.effective_user.id)
    except Exception as e:
        logger.debug(f"Could not delete last bot message: {e}")
    
    try:
        uid = update.effective_user.id
        user_obj = update.effective_user
        username = user_obj.username or user_obj.first_name
        
        # Send welcome message - don't fail on DB errors
        try:
            user = get_user(uid, username)
            logger.info(f"start user data: {user}")
        except Exception as db_error:
            logger.warning(f"Database error in start (non-fatal): {db_error}")
        
        # Always send welcome message
        text = "👋 Привет! Здесь можно увеличить свою фиссуру"
        result_msg = await context.bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=main_menu()
        )
        
        # Track this message for future deletion
        set_last_bot_message(chat_id, uid, result_msg.message_id)
        schedule_delete(context.bot, chat_id, result_msg.message_id, 30, context.application.job_queue)
        
        # Try to update message ID in database (non-critical)
        try:
            update_last_message_id(uid, result_msg.message_id)
        except Exception as e:
            logger.debug(f"Could not update last message id: {e}")

    except Exception as e:
        logger.error(f"Error in start: {e}")


async def menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Menu button handler - sends new content, deletes user message and old bot message immediately"""
    try:
        text = update.message.text.strip()
        
        menu_buttons = ["📈 Увеличить фиссуру", "📏 Моя длина", "🏆 Топ"]
        
        if text not in menu_buttons:
            return
        
        chat_id = update.message.chat_id
        chat_type = update.message.chat.type
        user_id = update.effective_user.id
        logger.info(f"User {user_id} pressed button: {text}")
        
        # Delete user's command only in groups/channels
        if chat_type in ['group', 'supergroup', 'channel']:
            user_msg_id = update.message.message_id
            try:
                await context.bot.delete_message(chat_id, user_msg_id)
                logger.info(f"Deleted user message: {user_msg_id}")
            except Exception as e:
                logger.debug(f"Could not delete user message: {e}")
        
        # Delete last bot message immediately
        try:
            await delete_last_bot_message(context.bot, chat_id, user_id)
        except Exception as e:
            logger.debug(f"Could not delete last bot message: {e}")
        
        # Call the appropriate function
        if text == "📈 Увеличить фиссуру":
            await fissure(update, context)
        elif text == "📏 Моя длина":
            await stats(update, context)
        elif text == "🏆 Топ":
            await top(update, context)
            
    except Exception as e:
        logger.error(f"Error in menu_handler: {e}", exc_info=True)


async def health_check(request):
    """Health check endpoint"""
    return web.Response(text="Bot is working", status=200)


health_check_handler = None


def setup_health_check(bot):
    """Initialize health check handler with bot instance"""
    global health_check_handler
    async def check(request):
        return web.Response(text="Bot is working", status=200)
    health_check_handler = check


async def welcome_new_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Welcome new chat member"""
    try:
        chat_id = update.my_chat_member.chat.id
        old_member = update.my_chat_member.old_chat_member
        new_member = update.my_chat_member.new_chat_member
        
        # Only welcome when user joins (not when they leave or get promoted)
        old_status = old_member.status
        new_status = new_member.status
        
        # User joined the chat (was not a member, now is member)
        if old_status in ['left', 'kicked'] and new_status in ['member', 'administrator']:
            name = new_member.user.first_name or "Friend"
            
            welcome_text = random.choice(WELCOME_PHRASES).format(name=name)
            
            result_msg = await context.bot.send_message(
                chat_id=chat_id,
                text=welcome_text
            )
            logger.info(f"Welcome sent for {name}")
            schedule_delete(context.bot, chat_id, result_msg.message_id, 30, context.application.job_queue)
        
    except Exception as e:
        logger.error(f"Error in welcome_new_member: {e}")


async def main():
    """Start Telegram bot in webhook mode for Render"""
    if not TOKEN:
        logger.error("BOT_TOKEN not set! Bot cannot start.")
        return
    
    try:
        init_db()
        
        # Создаём JobQueue и привязываем к application
        job_queue = JobQueue()
        app = ApplicationBuilder().token(TOKEN).job_queue(job_queue).build()
        
        # Инициализируем job_queue с application для PTB v20+
        job_queue.set_application(app)
        
        # Daily job
        job_queue.run_daily(
            decrease_inactive_job,
            time=datetime.time(hour=0, minute=0),
            days=(0, 1, 2, 3, 4, 5, 6)
        )
        logger.info("Done")

        app.add_handler(CommandHandler("start", start))
        app.add_handler(CommandHandler("fissure", fissure))
        app.add_handler(CommandHandler("stats", stats))
        app.add_handler(CommandHandler("top", top))
        app.add_handler(MessageHandler(filters.Regex(r'^/start@DotaFull_bot$'), start))
        app.add_handler(MessageHandler(filters.Regex(r'^/fissure@DotaFull_bot$'), fissure))
        app.add_handler(MessageHandler(filters.Regex(r'^/stats@DotaFull_bot$'), stats))
        app.add_handler(MessageHandler(filters.Regex(r'^/top@DotaFull_bot$'), top))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, menu_handler))
        app.add_handler(ChatMemberHandler(welcome_new_member, ChatMemberHandler.CHAT_MEMBER))

        webhook_url = os.getenv("WEBHOOK_URL")
        if not webhook_url:
            logger.error("WEBHOOK_URL not set!")
            return
            
        await app.bot.set_webhook(url=webhook_url)
        await app.initialize()
        
        # Запускаем application для активации job_queue
        await app.start()
        
        logger.info("Telegram bot started in webhook mode")
        logger.info(f"Webhook URL: {webhook_url}")
        
        from aiohttp import web
        
        async def handle_webhook(request):
            """Handle incoming webhook requests"""
            try:
                update_data = await request.json()
                logger.info(f"Webhook received: {update_data.get('update_id', 'unknown')}")
                update = Update.de_json(update_data, app.bot)
                logger.info(f"Update parsed: {update}")
                await app.process_update(update)
                logger.info(f"Update processed")
                return web.Response(status=200)
            except Exception as e:
                logger.error(f"Webhook error: {e}", exc_info=True)
                return web.Response(status=500)
        
        web_app = web.Application()
        web_app.router.add_post('/webhook', handle_webhook)
        
        # Setup health check with bot access
        setup_health_check(app.bot)
        web_app.router.add_get('/health', health_check_handler)
        
        runner = web.AppRunner(web_app)
        await runner.setup()
        site = web.TCPSite(runner, '0.0.0.0', int(os.getenv('PORT', 8080)))
        await site.start()
        
        logger.info("Web server started")
        
        while True:
            await asyncio.sleep(3600)
            
    except Exception as e:
        logger.error(f"Critical error: {e}", exc_info=True)
        raise


async def main_polling():
    """Start Telegram bot in polling mode for local testing"""
    if not TOKEN:
        logger.error("BOT_TOKEN not set!")
        return
    
    try:
        init_db()
        
        # Создаём JobQueue и привязываем к application
        job_queue = JobQueue()
        app = ApplicationBuilder().token(TOKEN).job_queue(job_queue).build()
        
        # Инициализируем job_queue с application для PTB v20+
        job_queue.set_application(app)
        
        # Daily job
        job_queue.run_daily(
            decrease_inactive_job,
            time=datetime.time(hour=0, minute=0),
            days=(0, 1, 2, 3, 4, 5, 6)
        )
        logger.info("Done")

        app.add_handler(CommandHandler("start", start))
        app.add_handler(CommandHandler("fissure", fissure))
        app.add_handler(CommandHandler("stats", stats))
        app.add_handler(CommandHandler("top", top))
        app.add_handler(MessageHandler(filters.Regex(r'^/start@DotaFull_bot$'), start))
        app.add_handler(MessageHandler(filters.Regex(r'^/fissure@DotaFull_bot$'), fissure))
        app.add_handler(MessageHandler(filters.Regex(r'^/stats@DotaFull_bot$'), stats))
        app.add_handler(MessageHandler(filters.Regex(r'^/top@DotaFull_bot$'), top))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, menu_handler))
        app.add_handler(ChatMemberHandler(welcome_new_member, ChatMemberHandler.CHAT_MEMBER))

        logger.info("Telegram bot started in polling mode")
        
        await app.run_polling(drop_pending_updates=True)
        
    except Exception as e:
        logger.error(f"Critical error: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    if os.getenv("WEBHOOK_URL"):
        asyncio.run(main())
    else:
        asyncio.run(main_polling())

