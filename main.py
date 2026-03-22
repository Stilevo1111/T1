# -*- coding: utf-8 -*-
import os
import random
import time
import asyncio
import logging
import datetime
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters, JobQueue, ChatMemberHandler, ConversationHandler
from telegram.error import Conflict
from database import init_db, get_user, update_fissure, get_fissure_top, update_last_message_id, Database, get_user_rank, decrease_inactive_fissure, get_config, set_config, get_digest_stats, update_player_positions, update_digest_snapshot, get_weekly_digest_stats, update_weekly_digest_snapshot
import dota_mmr
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

# Conversation states
WAITING_FOR_STEAM_ID = 1


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
        asyncio.create_task(delete_after_delay(bot, chat_id, msg_id, delay, job_queue))


async def decrease_inactive_job(context):
    """Ежедневное задание: уменьшить fissure неактивным игрокам"""
    try:
        logger.info("Запуск ежедневного уменьшения fissure для неактивных игроков")
        affected = decrease_inactive_fissure(days_inactive=1, decrease_amount=1.0)
        if affected > 0:
            logger.info(f"Уменьшен fissure для {affected} неактивных игроков")
        else:
            logger.info("Нет неактивных игроков для уменьшения fissure")
        
        # Обновляем позиции игроков
        update_player_positions()
    except Exception as e:
        logger.error(f"Ошибка в decrease_inactive_job: {e}")


async def morning_digest_job(context):
    """Утренний дайджест (9:00)"""
    try:
        logger.info("Запуск утреннего дайджеста")
        
        # Получаем ID чата для дайджеста
        digest_chat_id = get_config('digest_chat_id')
        if not digest_chat_id:
            logger.info("Чат для дайджеста не настроен")
            return
        
        stats = get_digest_stats()
        
        # Формируем сообщение с кликабельными никнеймами
        growth_player, growth_pos = stats.get("top_growth", ("None", 0))
        drop_player, drop_cm = stats.get("top_drop", ("None", 0.0))
        streak_player, streak_len = stats.get("top_streak", ("None", 0))
        
        # Получаем telegram_id для создания кликабельных ссылок
        growth_id = stats.get("top_growth_id")
        drop_id = stats.get("top_drop_id")
        streak_id = stats.get("top_streak_id")
        
        # Функция для создания кликабельного никнейма
        def make_clickable(name, user_id):
            if name and name != "None" and user_id:
                return f"<a href=\"tg://user?id={user_id}\">{name}</a>"
            return name if name and name != "None" else "—"
        
        growth_display = make_clickable(growth_player, growth_id)
        drop_display = make_clickable(drop_player, drop_id)
        streak_display = make_clickable(streak_player, streak_id)
        
        # Формат: 📈stilevo +2⬆️ ┃💀None -X СМ┃🍀Wad1m1 - Стрик 1
        # Всегда показываем данные если есть игрок
        if growth_player and growth_player != "None":
            growth_part = f"📈{growth_display} +{growth_pos}⬆️"
        else:
            growth_part = "📈—"
        
        if drop_player and drop_player != "None":
            if drop_cm < 0:
                drop_part = f"💀{drop_display} {drop_cm:.0f} СМ"
            else:
                drop_part = f"💀{drop_display} +{drop_cm:.0f} СМ"
        else:
            drop_part = "💀—"
        
        if streak_player and streak_player != "None":
            streak_part = f"🍀{streak_display} - Стрик {streak_len}"
        else:
            streak_part = "🍀—"
        
        text = f"{growth_part} ┃{drop_part} ┃{streak_part}\n\n🌅УТРЕНИЙ ДАЙДЖЕСТ 🔄 9:00 МСК\n\n📈 = рост позиций в топе\n💀 = топ падение\n🍀 = текущий стрик побед"
        
        bot = context.application.bot
        
        # Пробуем отредактировать существующее сообщение
        last_message_id = get_config('daily_digest_message_id')
        if last_message_id:
            try:
                await bot.edit_message_text(
                    chat_id=digest_chat_id,
                    message_id=int(last_message_id),
                    text=text,
                    parse_mode="HTML"
                )
                logger.info(f"Обновлён существующий дайджест {last_message_id}")
                # Для планового дайджеста (9:00) обновляем "снимок" на следующие сутки.
                # Для ручного /digestnow snapshot НЕ трогаем, чтобы значение держалось до следующего 9:00.
                if not getattr(context, "manual", False):
                    update_digest_snapshot()
                return
            except Exception as e:
                error_str = str(e)
                # Если сообщение не найдено (удалено) - очищаем ID
                if "Message to edit not found" in error_str or "message can't be edited" in error_str:
                    logger.info(f"Старое сообщение {last_message_id} удалено или нельзя редактировать, создаём новое")
                    set_config('daily_digest_message_id', None)
                else:
                    logger.info(f"Не удалось редактировать сообщение: {e}")
        
        # Отправляем новое сообщение
        msg = await bot.send_message(chat_id=digest_chat_id, text=text, parse_mode="HTML")
        set_config('daily_digest_message_id', msg.message_id)
        logger.info(f"Создан новый утренний дайджест {msg.message_id}")
        if not getattr(context, "manual", False):
            update_digest_snapshot()
        
    except Exception as e:
        logger.error(f"Ошибка в morning_digest_job: {e}", exc_info=True)


async def format_digest_message():
    """Форматирует текст сообщения дайджеста"""
    stats = get_digest_stats()
    
    growth_player, growth_pos = stats.get("top_growth", ("None", 0))
    drop_player, drop_cm = stats.get("top_drop", ("None", 0.0))
    streak_player, streak_len = stats.get("top_streak", ("None", 0))
    
    growth_id = stats.get("top_growth_id")
    drop_id = stats.get("top_drop_id")
    streak_id = stats.get("top_streak_id")
    
    def make_clickable(name, user_id):
        if name and name != "None" and user_id:
            return f"<a href=\"tg://user?id={user_id}\">{name}</a>"
        return name if name and name != "None" else "—"
    
    growth_display = make_clickable(growth_player, growth_id)
    drop_display = make_clickable(drop_player, drop_id)
    streak_display = make_clickable(streak_player, streak_id)
    
    # Рост показываем если есть игрок
    if growth_player and growth_player != "None":
        growth_part = f"📈{growth_display} +{growth_pos}⬆️"
    else:
        growth_part = "📈—"
    
    # Падение показываем если есть игрок (может быть + или -)
    if drop_player and drop_player != "None":
        if drop_cm < 0:
            drop_part = f"💀{drop_display} {drop_cm:.0f} СМ"
        else:
            drop_part = f"💀{drop_display} +{drop_cm:.0f} СМ"
    else:
        drop_part = "💀—"
    
    # Стрик показываем если есть игрок
    if streak_player and streak_player != "None":
        streak_part = f"🍀{streak_display} - Стрик {streak_len}"
    else:
        streak_part = "🍀—"
    
    return f"{growth_part} ┃{drop_part} ┃{streak_part}\n\n🌅УТРЕНИЙ ДАЙДЖЕСТ 🔄 9:00 МСК\n\n📈 = рост позиций в топе\n💀 = топ падение\n🍀 = текущий стрик побед"


async def refresh_digest_message(bot):
    """Обновляет сообщение дайджеста после каждого броска"""
    try:
        digest_chat_id = get_config('digest_chat_id')
        if not digest_chat_id:
            return
        
        # Получаем статистику (сравнивает со старым снимком)
        # НЕ обновляем снимок! Он обновляется только в morning_digest_job
        text = await format_digest_message()
        
        last_message_id = get_config('daily_digest_message_id')
        if last_message_id:
            try:
                await bot.edit_message_text(
                    chat_id=digest_chat_id,
                    message_id=int(last_message_id),
                    text=text,
                    parse_mode="HTML"
                )
                logger.debug(f"Обновлён дайджест после броска")
                return
            except Exception as e:
                error_str = str(e)
                if "Message to edit not found" in error_str or "message can't be edited" in error_str:
                    set_config('daily_digest_message_id', None)
                else:
                    logger.debug(f"Не удалось обновить дайджест: {e}")
        
        msg = await bot.send_message(chat_id=digest_chat_id, text=text, parse_mode="HTML")
        set_config('daily_digest_message_id', msg.message_id)
        logger.info(f"Создан новый дайджест после броска {msg.message_id}")
        
    except Exception as e:
        logger.error(f"Ошибка в refresh_digest_message: {e}", exc_info=True)


async def weekly_digest_job(context):
    """Еженедельный дайджест (по расписанию)"""
    try:
        logger.info("Запуск еженедельного дайджеста")
        
        digest_chat_id = get_config('digest_chat_id')
        if not digest_chat_id:
            logger.info("Чат для дайджеста не настроен")
            return
        
        stats = get_weekly_digest_stats()
        
        text = "🌅 ЕЖЕНЕДЕЛЬНЫЙ ДАЙДЖЕСТ\n\n"
        
        # Больше всех вырос в см за неделю
        growth_player, growth_cm = stats.get("top_growth_cm", ("None", 0))
        growth_id = stats.get("top_growth_cm_id")
        
        def make_clickable_weekly(name, user_id):
            if name and name != "None" and user_id:
                return f"<a href=\"tg://user?id={user_id}\">{name}</a>"
            return name if name and name != "None" else "—"
        
        growth_display = make_clickable_weekly(growth_player, growth_id)
        if growth_player and growth_player != "None":
            text += f"🍆 Больше всех вырос: {growth_display} (+{growth_cm:.0f} см)\n"
        
        # Прорыв недели: кто поднялся на больше всего позиций в топе
        breakthrough_player, breakthrough_pos = stats.get("breakthrough", ("None", 0))
        breakthrough_id = stats.get("breakthrough_id")
        breakthrough_display = make_clickable_weekly(breakthrough_player, breakthrough_id)
        if breakthrough_player and breakthrough_player != "None":
            text += f"🔥 Прорыв недели: {breakthrough_display} (+{breakthrough_pos} позиций)\n"
        
        total_rolls = stats.get("total_rolls_week", 0)
        new_players = stats.get("new_players_week", 0)
        total_growth = stats.get("total_growth_week", 0)
        
        text += f"\n📊 Статистика недели:\n"
        text += f"• Всего бросков: {total_rolls}\n"
        text += f"• Новых игроков: {new_players}\n"
        text += f"• Общий рост: +{total_growth:.0f} см\n"
        
        bot = context.application.bot
        
        last_message_id = get_config('weekly_digest_message_id')
        if last_message_id:
            try:
                await bot.edit_message_text(
                    chat_id=digest_chat_id,
                    message_id=int(last_message_id),
                    text=text
                )
                update_weekly_digest_snapshot()
                return
            except Exception:
                pass
        
        msg = await bot.send_message(chat_id=digest_chat_id, text=text)
        set_config('weekly_digest_message_id', msg.message_id)
        update_weekly_digest_snapshot()
        
    except Exception as e:
        logger.error(f"Ошибка в weekly_digest_job: {e}", exc_info=True)


async def digest_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ручной запуск утреннего дайджеста в этот чат"""
    try:
        chat = update.effective_chat
        chat_id = chat.id
        # В группах удаляем сообщение пользователя с командой
        if chat.type in ['group', 'supergroup', 'channel']:
            try:
                await context.bot.delete_message(chat_id, update.message.message_id)
            except Exception as e:
                logger.debug(f"Could not delete user message: {e}")
        # Сохраняем этот чат как чат для дайджеста и сбрасываем message_id
        set_config("digest_chat_id", chat_id)
        set_config("daily_digest_message_id", "")

        class SimpleContext:
            def __init__(self, application):
                self.application = application
                # Флаг, что это ручной запуск, а не плановый джоб
                self.manual = True

        # Создаём простой контекст, чтобы переиспользовать morning_digest_job
        simple_context = SimpleContext(context.application)
        await morning_digest_job(simple_context)

        msg = await update.message.reply_text("✅ Утренний дайджест для этого чата создан/обновлён.")
        if chat.type in ['group', 'supergroup', 'channel']:
            schedule_delete(context.bot, chat_id, msg.message_id, 30, context.application.job_queue)
    except Exception as e:
        logger.error(f"Error in digest_now: {e}", exc_info=True)
        try:
            err = await update.message.reply_text("❌ Не удалось создать дайджест сейчас")
            chat = update.effective_chat
            if chat and chat.type in ['group', 'supergroup', 'channel']:
                schedule_delete(context.bot, chat.id, err.message_id, 30, context.application.job_queue)
        except Exception:
            pass

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
    # Dota 2 длинные мемы
    "{name}, добро пожаловать! Сразимся на поле боя?",
    "{name} присоединился! Время фармить и побеждать!",
    "{name}, готов к эпичной битве? Давай нальём!",
    "Внимание! {name} зашел в лобби - игра начинается!",
    "{name} в чате! Теперь команда непобедима!",
    "Добро пожаловать, {name}! Заказываем мида или харда?",
    "{name}, не забудь купить варды и ганкнуть!",
    "{name} в игре! Время показать на что способен!",
    "Наконец-то {name} здесь! Рошан не за горами!",
    "{name}, не стой на линии! Фарми быстрее!",
    "Готовься, {name}! Сегодня будет винрейт 100%!",
    "{name}, не зевай! Враг уже идет!",
    "{name} в команде! Это гарантированная победа!",
    "Добро пожаловать в ад, {name}! Удачи!",
    "{name}, не забывай пить воду между играми!",
    "Фарми, {name}, фарми! Крипы не сами себя скроят!",
    "{name}, выйди из куста! Мы видим тебя!",
    "Приветствуем нового героя - {name}!",
    "{name}, бери херо и играй!",
    "{name}, не говори что ты хардкор игрок!",
    # Ещё
    "{name}, добро пожаловать! Сколько крипов нафармил?",
    "{name} в деле! Время пикать!",
    "Привет, {name}! Давай выиграем эту игру!",
    "{name}, ты готов к бою? Враг на базе!",
    "Добро пожаловать, {name}! Не забудь про ульт!",
    "{name}, не тупи! Время пушить!",
    "{name}, заходи в игру! Команда ждёт!",
    "{name}, фокус! Мы на тебя рассчитываем!",
    "{name}, давай без багов! Играем чисто!",
    "{name}, готов к победе? Враг слаб!",
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
    if current_fissure >= 20:
        fatal_chance = 0.02  # 2% для фиссур 20+ см
        if random.random() < fatal_chance:
            return FATAL_ROLL, "FATAL DECREASE!", True, False
    
    # Единый баланс для всех фиссур
    if current_fissure < 5:
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
    
    elif current_fissure < 20:
        if random.random() < 0.4:
            improved_options = [3, 5, 10, 20]
            roll = random.choice(improved_options)
            return roll, "🚀 УЛУЧШЕННЫЙ РОЛЛ!", False, True
    
    elif current_fissure < 100:
        if random.random() < 0.2:
            bonus = random.choice([5, 10, 20])
            return bonus, "🍀 УДАЧНЫЙ РОЛЛ!", False, False
    
    else:
        # Для очень больших фиссур - меньше бонусов
        if random.random() < 0.1:
            bonus = random.choice([5, 10, 20])
            return bonus, "🍀 УДАЧНЫЙ РОЛЛ!", False, False
    
    # Единый баланс для всех:
    # Выигрыш 65%, Проигрыш 30%, Ничья 5%
    weighted_rolls = [
        (-3, 15), (-1, 15), (0, 5), (1, 15), (3, 15), (5, 15), (10, 15), (20, 5)
    ]
    values, weights = zip(*weighted_rolls)
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
        [KeyboardButton("🔗 Dota 2 MMR"), KeyboardButton("🏆 Топ MMR")],
        [KeyboardButton("💀 Руинер")],
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
    
    # Проверка на выходные (суббота = 5, воскресенье = 6)
    import datetime
    is_weekend = datetime.datetime.now().weekday() in (5, 6)
    weekend_bonus = ""
    
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
        
        # Бонус для выходных: увеличиваем положительный ролл
        if is_weekend and roll > 0 and not is_fatal:
            bonus_multiplier = random.choice([1.5, 2, 2.5])
            roll = int(roll * bonus_multiplier)
            weekend_bonus = f"\n🎉 ВЫХОДНОЙ! x{bonus_multiplier:.1f}"
        
        new_fissure = calculate_new_fissure(user["fissure"], roll)
        update_fissure(user_obj.id, new_fissure, now, roll)
        
        # Обновляем дайджест после каждого броска
        await refresh_digest_message(context.bot)
        
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
        
        user_id = user_obj.id
        display_username = f"<a href=\"tg://user?id={user_id}\">{username}</a>"
        
        text = (
            f"🎲 {display_username}\n\n"
            f"{result_text}\n"
            f"{extra_text}\n\n"
            f"📏 Длина сейчас: {new_fissure:.1f} см"
        )
        
        if is_fatal and protection_msg:
            text = f"{text}\n\n{protection_msg}"
        
        if weekend_bonus:
            text = f"{text}\n{weekend_bonus}"
        
        logger.info(f"Sending result message to chat_id={update.message.chat_id}")
        # Don't use reply_to_message_id because user message was already deleted
        result_msg = await context.bot.send_message(
            chat_id=update.message.chat_id,
            text=text,
            parse_mode="HTML",
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
        
        # Форматируем username как кликабельную ссылку на профиль
        user_id = user_obj.id
        display_username = f"<a href=\"tg://user?id={user_id}\">{username}</a>"
        
        text = f"👑 {display_username}\n\n📏 Длина: {user['fissure']:.1f} см\n🎲 Бросков: {user.get('total_rolls', 0)}\n🔥 Текущий стрик: {user.get('current_streak', 0)}\n🏆 Лучший стрик: {user.get('best_streak', 0)}"
        
        result_msg = await context.bot.send_message(
            chat_id=update.message.chat_id,
            text=text,
            parse_mode="HTML",
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
            medals = {1: "🥇", 2: "🥈", 3: "🥉"}
            for i, user_top in enumerate(top_users, 1):
                name = user_top.get('username', 'Unknown')[:15]
                medal = medals.get(i)
                if medal:
                    text += f"{medal} {name}: {user_top['fissure']:.1f} см\n"
                else:
                    text += f" {i}. {name}: {user_top['fissure']:.1f} см\n"
            
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


async def set_digest_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Установить текущий чат как чат для утреннего дайджеста"""
    try:
        chat = update.effective_chat
        chat_id = chat.id
        # В группах удаляем сообщение пользователя с командой
        if chat.type in ['group', 'supergroup', 'channel']:
            try:
                await context.bot.delete_message(chat_id, update.message.message_id)
            except Exception as e:
                logger.debug(f"Could not delete user message: {e}")
        # Сохраняем ID чата в конфиг и сбрасываем message_id
        set_config("digest_chat_id", chat_id)
        set_config("daily_digest_message_id", "")

        msg = await update.message.reply_text(
            f"✅ Чат для утреннего дайджеста установлен.\n"
            f"ID чата: `{chat_id}`\n"
            f"Теперь в 09:00 дайджест будет приходить сюда.",
            parse_mode="Markdown"
        )
        # В группах/каналах удаляем сервисное сообщение через 30 секунд
        if chat.type in ['group', 'supergroup', 'channel']:
            schedule_delete(context.bot, chat_id, msg.message_id, 30, context.application.job_queue)
    except Exception as e:
        logger.error(f"Error in set_digest_chat: {e}", exc_info=True)
        try:
            err = await update.message.reply_text("❌ Не удалось сохранить чат для дайджеста")
            chat = update.effective_chat
            if chat and chat.type in ['group', 'supergroup', 'channel']:
                schedule_delete(context.bot, chat.id, err.message_id, 30, context.application.job_queue)
        except Exception:
            pass




async def link_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start linking Steam - ask for ID"""
    await update.message.reply_text(
        "🔗 <b>Привязка Steam аккаунта</b>\n\n"
        "Введите ваш Steam ID (от 9 до 17 цифр)\n"
        "Например: 76561198012345678\n\n"
        "Или никнейм: NoNam3",
        parse_mode='HTML'
    )
    return WAITING_FOR_STEAM_ID


async def link_receive_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receive Steam ID from user"""
    identifier = update.message.text.strip()
    user_id = update.effective_user.id
    
    if not identifier:
        await update.message.reply_text("❌ Пустой ввод. Попробуйте ещё раз:")
        return WAITING_FOR_STEAM_ID
    
    result = dota_mmr.register_steam(user_id, identifier)
    
    if result.get('success'):
        await update.message.reply_text(
            f"✅ <b>Steam аккаунт привязан!</b>\n\n"
            f"🎮 {result.get('nickname', 'N/A')}\n"
            f"MMR: {result.get('mmr', 0)}",
            parse_mode='HTML'
        )
    else:
        await update.message.reply_text(
            f"❌ Ошибка: {result.get('message', 'Unknown error')}\n\n"
            "Попробуйте ещё раз или нажмите /cancel"
        )
        return WAITING_FOR_STEAM_ID
    
    return ConversationHandler.END


async def link_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel linking"""
    await update.message.reply_text("❌ Отменено. Для повтора нажмите /link")
    return ConversationHandler.END


link_conv_handler = ConversationHandler(
    entry_points=[CommandHandler("link", link_start)],
    states={
        WAITING_FOR_STEAM_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, link_receive_id)]
    },
    fallbacks=[CommandHandler("cancel", link_cancel)]
)


async def topmmr(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /topmmr command"""
    try:
        result = dota_mmr.get_week_top(limit=10)
        
        if not result:
            await update.message.reply_text("🏆 No data. Use /link")
            return
        
        text = "🏆 Top by MMR\n\n"
        for i, p in enumerate(result, 1):
            text += f"{i}. {p.get('nickname','?')} - {p.get('mmr',0)}\n"
        
        await update.message.reply_text(text)
    except Exception as e:
        logger.error(f"topmmr error: {e}")


async def ruiner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /Ruiner - find random admin"""
    try:
        chat = update.effective_chat
        if not chat or chat.type not in ['group','supergroup']:
            await update.message.reply_text("❌ Groups only")
            return
        
        admins = await context.bot.get_chat_administrators(chat.id)
        admin_users = [a for a in admins if not a.user.is_bot]
        
        if not admin_users:
            await update.message.reply_text("❌ No admins")
            return
        
        import random
        chosen = random.choice(admin_users)
        user = chosen.user
        
        jokes = [
            f"@{user.username}, ты точно играл?",
            f"@{user.username}, инвайт в команду 'Always Lose' ждёт",
        ]
        
        joke = random.choice(jokes)
        # Делаем никнейм кликабельным
        keyboard = [[InlineKeyboardButton(user.username, url=f"tg://user?id={user.id}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(f"👻 Руинер найден: {user.username}\n\n{joke}", reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"ruiner error: {e}")
        await update.message.reply_text("❌ Error")


async def menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Menu button handler - sends new content, deletes user message and old bot message immediately"""
    try:
        text = update.message.text.strip()
        
        menu_buttons = ["📈 Увеличить фиссуру", "📏 Моя длина", "🏆 Топ", "🔗 Dota 2 MMR", "🏆 Топ MMR", "💀 Руинер"]
        
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
        elif text == "🔗 Dota 2 MMR":
            from dota_mmr import show_mmr_menu
            await show_mmr_menu(update, context)
        elif text == "🏆 Топ MMR":
            await topmmr(update, context)
        elif text == "💀 Руинер":
            await Ruiner(update, context)
            
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
        chat_update = update.chat_member or update.my_chat_member
        if chat_update is None:
            logger.debug("welcome_new_member called without chat_member/my_chat_member data")
            return

        chat_id = chat_update.chat.id
        old_member = chat_update.old_chat_member
        new_member = chat_update.new_chat_member
        
        # Only welcome when user joins (not when they leave or get promoted)
        old_status = old_member.status
        new_status = new_member.status
        
        # Если это сам бот только что добавлен в чат — автоматически запоминаем чат для дайджеста,
        # если он ещё не настроен
        try:
            bot_id = context.bot.id
            if new_member.user.id == bot_id and not get_config("digest_chat_id"):
                set_config("digest_chat_id", chat_id)
                logger.info(f"Автоматически установлен digest_chat_id = {chat_id}")
        except Exception as e:
            logger.debug(f"Не удалось автоматически установить digest_chat_id: {e}")
        
        # User joined the chat (was not a member, now is member)
        if old_status in ['left', 'kicked'] and new_status in ['member', 'administrator']:
            name = new_member.user.first_name or "Friend"
            user_id = new_member.user.id
            
            # Формируем приветственное сообщение с кликабельным ником
            welcome_text = f"<a href=\"tg://user?id={user_id}\">{name}</a>, {random.choice(WELCOME_PHRASES)}"

            
            result_msg = await context.bot.send_message(
                chat_id=chat_id,
                text=welcome_text,
                parse_mode="HTML"
            )
            logger.info(f"Welcome sent for {name}")
            # Удаляем приветственное сообщение через час
            schedule_delete(context.bot, chat_id, result_msg.message_id, 3600, context.application.job_queue)
        
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
        
        # Утренний дайджест в 9:00 утра по МСК (6:00 UTC)
        job_queue.run_daily(
            morning_digest_job,
            time=datetime.time(hour=6, minute=0),
            days=(0, 1, 2, 3, 4, 5, 6)
        )
        logger.info("Done")
        
        # Утренний дайджест теперь live (обновляется после каждого броска)
        
        # Еженедельный дайджест по понедельникам
        job_queue.run_daily(
            weekly_digest_job,
            time=datetime.time(hour=6, minute=0),
            days=(0,)  # Monday only
        )

        app.add_handler(CommandHandler("start", start))
        app.add_handler(CommandHandler("fissure", fissure))
        app.add_handler(CommandHandler("stats", stats))
        app.add_handler(CommandHandler("top", top))
        app.add_handler(CommandHandler("digestnow", digest_now))
        app.add_handler(CommandHandler("setdigestchat", set_digest_chat))
        app.add_handler(link_conv_handler)
        app.add_handler(CommandHandler("topmmr", topmmr))
        app.add_handler(CommandHandler("Ruiner", ruiner))
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
        # Запускаем job_queue для PTB v20+
        await job_queue.start()
        
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
        
        # Утренний дайджест в 9:00 утра по МСК (6:00 UTC)
        job_queue.run_daily(
            morning_digest_job,
            time=datetime.time(hour=6, minute=0),
            days=(0, 1, 2, 3, 4, 5, 6)
        )
        logger.info("Done")
        
        # Утренний дайджест теперь live (обновляется после каждого броска)
        # Еженедельный дайджест по понедельникам
        job_queue.run_daily(
            weekly_digest_job,
            time=datetime.time(hour=6, minute=0),
            days=(0,)  # Monday only
        )

        app.add_handler(CommandHandler("start", start))
        app.add_handler(CommandHandler("fissure", fissure))
        app.add_handler(CommandHandler("stats", stats))
        app.add_handler(CommandHandler("top", top))
        app.add_handler(CommandHandler("digestnow", digest_now))
        app.add_handler(CommandHandler("setdigestchat", set_digest_chat))
        app.add_handler(MessageHandler(filters.Regex(r'^/start@DotaFull_bot$'), start))
        app.add_handler(MessageHandler(filters.Regex(r'^/fissure@DotaFull_bot$'), fissure))
        app.add_handler(MessageHandler(filters.Regex(r'^/stats@DotaFull_bot$'), stats))
        app.add_handler(MessageHandler(filters.Regex(r'^/top@DotaFull_bot$'), top))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, menu_handler))
        app.add_handler(ChatMemberHandler(welcome_new_member, ChatMemberHandler.CHAT_MEMBER))

        logger.info("Telegram bot started in polling mode")
        
        # Запускаем job_queue для PTB v20+
        await job_queue.start()
        
        await app.run_polling(drop_pending_updates=True)
        
    except Exception as e:
        logger.error(f"Critical error: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    if os.getenv("WEBHOOK_URL"):
        asyncio.run(main())
    else:
        asyncio.run(main_polling())





