"""
Bot utilities: helper functions for Telegram IDs, clickable names, and message tracking.
Extracted from main.py without any behavior changes.
"""

import asyncio
import logging
import time
from collections import deque

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

from database import get_user, user_cache
from rate_limiter import rate_limit

logger = logging.getLogger(__name__)

recent_fissure_rolls = deque(maxlen=50)

from utils import _telegram_error_containsdef format_time(seconds: float) -> str:
    """Format seconds into human-readable time string (e.g., '5м 30с', '1ч 23м')."""
    if seconds is None or seconds < 0:
        return "0с"
    seconds = int(seconds)
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    
    parts = []
    if hours > 0:
        parts.append(f"{hours}ч")
    if minutes > 0:
        parts.append(f"{minutes}м")
    if secs > 0 or not parts:
        parts.append(f"{secs}с")
    return " ".join(parts)

def record_recent_fissure_roll(user_id: int, username: str, growth: float, new_fissure: float, cascade: int = 1, event_type: str = "roll"):
    """Append one fissure roll event to the in-memory ring buffer (no DB write).
    
    event_type: 'roll', 'multicast', 'zeus', 'techies'
    """
    recent_fissure_rolls.append({
        "ts": time.time(),
        "user_id": user_id,
        "username": (username or "unknown")[:25],
        "growth": round(growth, 1),
        "fissure": round(new_fissure, 1),
        "cascade": cascade,
        "event_type": event_type
    })

_bot_can_delete_ttl = 3600
_BOT_CAN_DELETE_CACHE_MAX = 200
_bot_can_delete_cache = {}

async def bot_can_delete(bot, chat_id):
    """Проверить может ли бот удалять сообщения в чате"""
    current_time = time.time()
    if len(_bot_can_delete_cache) > _BOT_CAN_DELETE_CACHE_MAX:
        _bot_can_delete_cache.clear()
        logger.debug("Cleared bot_can_delete cache (exceeded limit)")

    cached = _bot_can_delete_cache.get(chat_id)
    if cached is not None:
        cached_val, cached_time = cached
        if current_time - cached_time < _bot_can_delete_ttl:
            return cached_val
    try:
        me = await bot.get_me()
        member = await bot.get_chat_member(chat_id, me.id)
        can_delete = getattr(member, 'can_delete_messages', False) or member.status in ('administrator', 'creator')
        _bot_can_delete_cache[chat_id] = (can_delete, time.time())
        return can_delete
    except Exception:
        _bot_can_delete_cache[chat_id] = (False, time.time())
        return False


_BAD_NAMES = ("", "none", "unknown", "неизвестный игрок")


def _clean_display_name(username):
    """Return a clean display name, or None if it is empty/unknown/placeholder."""
    if username is None:
        return None
    name = str(username).strip()
    if not name:
        return None
    # strip leading @ (telegram handles)
    if name.startswith("@"):
        name = name[1:].strip()
    if not name:
        return None
    # strip surrounding quotes that sometimes come from DB
    if (name.startswith('"') and name.endswith('"')) or (name.startswith("'") and name.endswith("'")):
        name = name[1:-1].strip()
    if name.lower() in _BAD_NAMES:
        return None
    return name


def make_clickable(username, telegram_id):
    """Create an HTML clickable link for a user.

    Guarantees:
    - never shows 'Unknown' / 'None' / empty placeholders
    - always clickable when telegram_id is present and non-zero (falls back to 'Игрок')
    - returns a plain (non-clickable) cleaned name only when no telegram_id exists
    """
    display = _clean_display_name(username)
    if not display:
        display = "Игрок"
    if telegram_id is None or telegram_id == 0:
        return display
    return f'<a href="tg://user?id={telegram_id}">{display}</a>'


def clickable_name(username, telegram_id=None, steam_id=None):
    """Create an HTML clickable link for a user with fallbacks.

    Priority:
    1) Telegram link when telegram_id is present (non-zero integer)
    2) Steam profile link when steam_id is present
    3) Plain cleaned name otherwise
    """
    display = _clean_display_name(username)
    if not display:
        display = "Игрок"
    if telegram_id is not None and telegram_id != 0:
        return f'<a href="tg://user?id={telegram_id}">{display}</a>'
    if steam_id:
        return f'<a href="https://steamcommunity.com/profiles/{steam_id}">{display}</a>'
    return display


def main_menu():
    """Return main menu reply markup"""
    keyboard = [
        ["🎲 Ролл Фиссуры", "👤 Профиль"],
        ["🏆 Топ Фиссур", "🏆 Топ MMR"],
        ["🔎 Аналитика", "🔑 Привязать Аккаунт"]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


async def delete_last_bot_message(bot, chat_id, user_id):
    """Delete last bot message for user in chat"""
    try:
        import json
        from database import get_config, set_config
        key = f"last_bot_msg_{chat_id}_{user_id}"
        msg_id = get_config(key)
        if msg_id:
            await bot.delete_message(chat_id, int(msg_id))
            set_config(key, None)
    except Exception as e:
        logger.debug(f"Could not delete last bot message: {e}")


def set_last_bot_message(chat_id, user_id, msg_id):
    """Set last bot message for user in chat"""
    from database import set_config
    key = f"last_bot_msg_{chat_id}_{user_id}"
    set_config(key, str(msg_id))


def schedule_delete(bot, chat_id, msg_id, delay, job_queue=None):
    """Schedule message deletion after delay seconds"""
    if job_queue:
        def _safe_delete(ctx):
            try:
                return bot.delete_message(chat_id=chat_id, message_id=msg_id)
            except Exception as e:
                logger.debug(f"Could not delete scheduled message: {e}")
        job_queue.run_once(_safe_delete, delay)
    else:
        async def _delete():
            await asyncio.sleep(delay)
            try:
                await bot.delete_message(chat_id=chat_id, message_id=msg_id)
            except Exception as e:
                logger.debug(f"Could not delete scheduled message: {e}")
        asyncio.create_task(_delete())


def add_bot_message(chat_id, user_id, msg_id):
    """Track bot message for cleanup"""
    logger.debug(f"add_bot_message is deprecated; chat_id={chat_id}, user_id={user_id}, msg_id={msg_id}")


def update_last_message_id(user_id, msg_id):
    """Update last message id in cache"""
    logger.debug(f"update_last_message_id is deprecated; user_id={user_id}, msg_id={msg_id}")


def _build_analytics_keyboard(page_idx, total_pages, generated):
    """Build inline keyboard for analytics pagination"""
    buttons = []
    if page_idx > 0:
        buttons.append(InlineKeyboardButton("◀ Назад", callback_data=f"analytics_page_{page_idx-1}"))
    if total_pages > 0:
        buttons.append(InlineKeyboardButton(f"{page_idx+1}/{total_pages}", callback_data="analytics_page_current"))
    if page_idx < total_pages - 1:
        buttons.append(InlineKeyboardButton("Вперёд ▶", callback_data=f"analytics_page_{page_idx+1}"))
    return InlineKeyboardMarkup([buttons])


def _build_stats_button_keyboard():
    """Build inline keyboard for stats page"""
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("📊 Статистика", callback_data="analytics_show")
    ]])


class ManualContext:
    """Minimal context-like object for manual job execution"""
    def __init__(self, application, bot):
        self.application = application
        self.bot = bot
        self.job_queue = application.job_queue if application else None
        self.job = None

    async def bot_data(self):
        return {}

    def __getattr__(self, name):
        return None