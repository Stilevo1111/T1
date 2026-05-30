# -*- coding: utf-8 -*-
"""
Bot utilities: helper functions for Telegram IDs, clickable names, and message tracking.
Extracted from main.py without any behavior changes.
"""

import logging
import asyncio
from database import user_cache, get_user
from telegram import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardButton, InlineKeyboardMarkup
from rate_limiter import rate_limit

logger = logging.getLogger(__name__)

__all__ = [
    # Public API
    "is_valid_telegram_id",
    "make_clickable",
    "delete_last_bot_message",
    "set_last_bot_message",
    "add_bot_message",
    "main_menu",
    "delete_after_delay",
    "delete_message_job",
    "schedule_delete",
    "ManualContext",
    "last_bot_message",
]


def _telegram_error_contains(error: Exception, *phrases: str) -> bool:
    """Проверяет, содержит ли текст ошибки любую из переданных фраз (регистронезависимо)."""
    if error is None:
        return False
    msg = str(error).lower()
    return any(p.lower() in msg for p in phrases)


# Track last bot message per user per chat for cleanup
last_bot_message = {}  # {chat_id: {user_id: message_id or list}}


def format_time(seconds):
    """Format seconds as HHч MMм"""
    h = seconds // 3600
    m = (seconds % 3600) // 60
    return f"{int(h)}ч {int(m)}м"


def is_valid_telegram_id(user_id):
    """Проверяет, что user_id это валидный Telegram ID (не SteamID64)"""
    if not user_id:
        return False
    try:
        uid = int(user_id)
    except (ValueError, TypeError):
        return False
    # Telegram IDs: могут быть любого размера, но обычно 6-10 цифр
    # SteamID64: начинается с 7656119... (более 15 цифр)
    if uid > 10**15:  # Защита от SteamID64 (7656119...)
        return False
    if uid < 1:  # Telegram ID должен быть положительным
        return False
    return True


def make_clickable(name, user_id, max_length=12):
    """Создать кликабельный никейм для Telegram"""
    try:
        uid = int(user_id) if user_id else 0
    except (ValueError, TypeError):
        uid = 0
    
    if name and name != "None" and uid > 0:
        display_name = name
        try:
            # Сначала пробуем из кеша
            cached = user_cache.get(uid)
            if cached:
                display_name = cached.get('steam_nickname') or cached.get('username') or name
            else:
                # Пробуем из БД напрямую
                db_user = get_user(uid)
                if db_user:
                    display_name = db_user.get('steam_nickname') or db_user.get('username') or name
        except:
            display_name = name

        # Нормализуем никнейм - убираем @ если есть
        if display_name and display_name.startswith('@'):
            display_name = display_name[1:]

        # Если получилось все равно число - показываем как есть
        if display_name.isdigit():
            display_name = f"Игрок {display_name}"

        # Обрезаем длинные ники
        if len(display_name) > max_length:
            display_name = display_name[:max_length-1] + "."

        return f'<a href="tg://user?id={uid}">{display_name}</a>'
    return name if name and name != "None" else "—"


async def delete_last_bot_message(bot, chat_id, user_id):
    """Delete all tracked bot messages for this user in this chat immediately"""
    if chat_id in last_bot_message and user_id in last_bot_message[chat_id]:
        msg_ids = last_bot_message[chat_id][user_id]
        if not isinstance(msg_ids, list):
            msg_ids = [msg_ids]

        unique_msg_ids = []
        seen = set()
        for msg_id in msg_ids:
            if msg_id not in seen and isinstance(msg_id, int) and msg_id > 0:
                unique_msg_ids.append(msg_id)
                seen.add(msg_id)

        for msg_id in unique_msg_ids:
            try:
                logger.info(f"delete_last_bot_message: attempting to delete msg_id={msg_id} in chat={chat_id}")
                await bot.delete_message(chat_id, msg_id)
                logger.info(f"Deleted last bot message for user {user_id}: {msg_id}")
            except Exception as e:
                if _telegram_error_contains(e, "message to delete not found", "bad request", "not found"):
                    logger.debug(f"Message {msg_id} already deleted or invalid in chat {chat_id}: {e}")
                else:
                    logger.warning(f"Could not delete last bot message {msg_id}: {e}")

        try:
            del last_bot_message[chat_id][user_id]
            if not last_bot_message[chat_id]:
                del last_bot_message[chat_id]
        except KeyError:
            pass


def set_last_bot_message(chat_id, user_id, message_id):
    """Set the last bot message for this user in this chat"""
    if not isinstance(message_id, int) or message_id <= 0:
        logger.debug(f"set_last_bot_message: skipping invalid message_id={message_id}")
        return

    if chat_id not in last_bot_message:
        last_bot_message[chat_id] = {}
    last_bot_message[chat_id][user_id] = message_id


def add_bot_message(chat_id, user_id, message_id):
    """Add bot message to track list for this user in this chat"""
    if not isinstance(message_id, int) or message_id <= 0:
        logger.debug(f"add_bot_message: skipping invalid message_id={message_id}")
        return

    if chat_id not in last_bot_message:
        last_bot_message[chat_id] = {}
    if isinstance(last_bot_message[chat_id].get(user_id), list):
        msg_list = last_bot_message[chat_id][user_id]
        msg_list.append(message_id)
        last_bot_message[chat_id][user_id] = msg_list[-2:]
    else:
        last_bot_message[chat_id][user_id] = [message_id]

    if len(last_bot_message) > 500:
        last_bot_message.clear()
        logger.warning("Cleared last_bot_message cache (exceeded 500 entries)")


def main_menu():
    keyboard = [
        [KeyboardButton("🎲 Ролл Фиссуры"), KeyboardButton("👤 Профиль")],
        [KeyboardButton("🏆 Топ Фиссур"), KeyboardButton("🏆 Топ MMR")],
        [KeyboardButton("🔑 Привязать Аккаунт"), KeyboardButton("🔎 Аналитика")],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)


def _build_analytics_keyboard(page_idx: int, total_pages: int, generated: set = None) -> InlineKeyboardMarkup:
    """Build inline keyboard for analytics pagination."""
    rows = []
    page_buttons = []
    labels = ["🆚 С ПРО", "🔍 Детально"]
    for i in range(total_pages):
        label = f"⏳ {labels[i]}" if generated and i not in generated else labels[i]
        if i == page_idx:
            page_buttons.append(InlineKeyboardButton(f"✅ {label}", callback_data=f"analytics_page_{i}"))
        else:
            page_buttons.append(InlineKeyboardButton(label, callback_data=f"analytics_page_{i}"))
    rows.append(page_buttons)
    return InlineKeyboardMarkup(rows)


def _build_stats_button_keyboard() -> InlineKeyboardMarkup:
    """Build inline keyboard with single 'Сравнить с Pro 🧠' button under chart."""
    return InlineKeyboardMarkup([[InlineKeyboardButton("Сравнить c Pro🆚", callback_data="analytics_show")]])


class ManualContext:
    """Контекст для ручного вызова jobs"""
    def __init__(self, application, bot):
        self.application = application
        self.bot = bot
        self.manual = True


@rate_limit(tokens=1)
async def delete_after_delay(bot, chat_id, msg_id, delay, job_queue=None):
    """Удалить сообщение через delay секунд"""
    if not isinstance(msg_id, int) or msg_id <= 0:
        logger.debug(f"delete_after_delay: skipping invalid msg_id={msg_id}")
        return

    if job_queue:
        job_queue.run_once(
            delete_message_job,
            delay,
            data={'chat_id': chat_id, 'msg_id': msg_id},
            name=f"delete_{chat_id}_{msg_id}"
        )
    else:
        await asyncio.sleep(delay)
        try:
            logger.info(f"delete_after_delay: attempting to delete msg_id={msg_id} in chat={chat_id}")
            await bot.delete_message(chat_id, msg_id)
            logger.info(f"Deleted delayed message {msg_id} in chat {chat_id}")
        except Exception as e:
            if _telegram_error_contains(e, "message to delete not found", "bad request"):
                logger.debug(f"Message {msg_id} already deleted in chat {chat_id}")
            else:
                logger.warning(f"Failed to delete delayed message {msg_id} in chat {chat_id}: {e}")


@rate_limit(tokens=1)
async def delete_message_job(context):
    """Job для удаления сообщения"""
    bot = context.application.bot
    chat_id = context.job.data['chat_id']
    msg_id = context.job.data['msg_id']

    if not isinstance(msg_id, int) or msg_id <= 0:
        logger.debug(f"delete_message_job: skipping invalid msg_id={msg_id}")
        return

    try:
        logger.info(f"delete_message_job: attempting to delete msg_id={msg_id} in chat={chat_id}")
        await bot.delete_message(chat_id, msg_id)
        logger.info(f"Deleted scheduled message {msg_id} in chat {chat_id}")
    except Exception as e:
        if _telegram_error_contains(e, "message to delete not found", "bad request"):
            logger.debug(f"Message {msg_id} already deleted in chat {chat_id}")
        else:
            logger.warning(f"Failed to delete message {msg_id} in chat {chat_id}: {e}")


def schedule_delete(bot, chat_id, msg_id, delay=30, job_queue=None):
    """Запланировать удаление сообщения через delay секунд"""
    asyncio.create_task(delete_after_delay(bot, chat_id, msg_id, delay))
