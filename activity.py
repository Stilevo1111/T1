# -*- coding: utf-8 -*-
"""
Модуль "Актив" для fissure бота
Бот-эхолокация: отслеживание активности в чате
"""
import time
import random
import datetime
import logging
import asyncio

logger = logging.getLogger(__name__)


# =====================
# ФРАЗЫ ДЛЯ УТРЕННЕГО И НОЧНОГО СООБЩЕНИЙ
# =====================

ACTIVITY_NIGHT = [
    "🦇 Спокойной ночи, дотеры. Если кто не спит — играйте тихо, я молчу.",
    "🦇 Спокойной ночи! 💤",
    "🦇 Спокойной ночи! Завтра будет новый день.",
    "🦇 Спокойной ночи! Zzz...",
    "🦇 Спокойной ночи! Я тоже спать.",
    "🦇 Спокойной ночи! Вижу, все уснули. 💤",
    "🦇 Ночная тишина... Спокойной ночи!",
    "🦇 Zzz... Спокойной ночи!",
    "🦇 Ладно, спокойной ночи! До утра!",
    "🦇 Все спят? Спокойной ночи! 💤",
    "🦇 Спокойной ночи! Сладких снов!",
    "🦇 Ночь! Все спят - я тоже.",
    "🦇 Спокойной ночи, народ!",
    "🦇 Zzz... иду спать. Спокойной ночи!",
    "🦇 Ночная смена - я спит. Спокойной ночи!",
    "🦇 Спокойной ночи! До завтра!",
    "🦇 Все в сон? Я тоже на боковую!",
    "🦇 Ночной дозор... завершён. Спокойной ночи!",
    "🦇 Ладно, спокойной ночи! Завтра будет день!",
    "🦇 Спокойной ночи! Кто не спит - тот молчит! 😴",
]

ACTIVITY_MORNING = [
    "🦇 Доброе утро! Чай, кофе, калибровка?",
    "🦇 Утро! Кто на катку? ☕🎮",
    "🦇 Доброе утро! Всем кофе и каток!",
    "🦇 Утречко! Готовы к каточке? 🎮",
    "🦇 Доброе утро! Время катать!",
    "🦇 Утро наступило! Кто на катку?",
    "🦇 Доброе утро! Начинаем день с катки!",
    "🦇 Солнце встало! Каток ждёт! 🎮",
    "🦇 Утро! Кофе, завтрак, катка!",
    "🦇 Доброе утро! Все на катку!",
    "🦇 Утро! Кто не спал - тот молодец!",
    "🦇 Доброе утро! Как спалось?",
    "🦇 Утречко! Всем привет!",
    "🦇 Доброе утро! Новый день - новые катки!",
    "🦇 Утро! Солнце встало, народ просыпайся!",
    "🦇 Доброе утро! Кто готов к катке?",
    "🦇 Утро! Всем привет из утренней смены!",
    "🦇 Доброе утро! Начинаем день!",
    "🦇 Утречко! кто не выспался - пьём кофе! ☕",
    "🦇 Доброе утро! Все на катку!",
]


# =====================
# ГЛОБАЛЬНОЕ СОСТОЯНИЕ (per chat_id)
# =====================

chat_last_activity = {}
last_bot_message_time = {}

sent_night_message = {}
sent_morning_greeting = {}


# =====================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# =====================

def get_chat_id(config_func):
    return config_func('digest_chat_id')


def update_chat_activity(chat_id):
    chat_last_activity[chat_id] = time.time()


async def activity_send_permanent(bot, chat_id, text):
    """Отправляет сообщение которое не удаляется"""
    try:
        await bot.send_message(chat_id=chat_id, text=text)
    except Exception as e:
        logger.debug(f"Error in activity_send_permanent: {e}")


async def check_activity_job(context, config_func=None):
    global chat_last_activity, last_bot_message_time
    global sent_night_message, sent_morning_greeting
    
    if config_func is None:
        from database import get_config
        config_func = get_config
    
    now = time.time()
    chat_id = config_func('digest_chat_id')
    
    if not chat_id:
        return
    
    if chat_id not in chat_last_activity:
        chat_last_activity[chat_id] = now
    if chat_id not in last_bot_message_time:
        last_bot_message_time[chat_id] = 0
    
    last_activity = chat_last_activity.get(chat_id, now)
    last_bot_msg_time = last_bot_message_time.get(chat_id, 0)
    
    msk_hour = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=3)).hour
    
    # === УТРЕННЕЕ СООБЩЕНИЕ В 09:00 ===
    if msk_hour == 9:
        morning_sent = sent_morning_greeting.get(chat_id, False)
        if not morning_sent and now - last_bot_msg_time >= 60:
            text = random.choice(ACTIVITY_MORNING)
            await activity_send_permanent(context.bot, chat_id, text)
            last_bot_message_time[chat_id] = now
            sent_morning_greeting[chat_id] = True
        return
    
    # === ВЕЧЕРНЕЕ СООБЩЕНИЕ В 23:00 ===
    if msk_hour == 23:
        night_sent = sent_night_message.get(chat_id, False)
        if not night_sent and now - last_bot_msg_time >= 60:
            text = random.choice(ACTIVITY_NIGHT)
            await activity_send_permanent(context.bot, chat_id, text)
            last_bot_message_time[chat_id] = now
            sent_night_message[chat_id] = True
        return
    
    # Сброс флагов в полночь (00:00)
    if msk_hour == 0:
        sent_morning_greeting[chat_id] = False
        sent_night_message[chat_id] = False
        # Сброс счётчика бонусной фиссуры и бонусов игроков
        from main import daily_fissure_rolls, bonus_ready_users, _save_daily_fissure_rolls, _save_bonus_ready_users
        daily_fissure_rolls = 0
        bonus_ready_users = {}
        _save_daily_fissure_rolls(0)
        _save_bonus_ready_users({})