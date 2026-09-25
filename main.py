import asyncio
import atexit
import datetime
import io
import json
import os
import random
import re
import signal
import time
import traceback
import urllib.parse as urlparse
from collections import OrderedDict
from datetime import timedelta, timezone
from pathlib import Path

import aiohttp

# Logging setup
import structlog
from aiohttp import web
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, MessageEntity, Update
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    ChatMemberHandler,
    CommandHandler,
    ContextTypes,
    JobQueue,
    MessageHandler,
    filters,
)
from telegram.request import HTTPXRequest

from chat_wordcloud.handler import story_command
from database import (
    DATABASE_URL,
    Database,
    cleanup_left_users,
    decrease_inactive_fissure,
    delete_user,
    get_aiohttp_session,
    get_config,
    get_digest_stats,
    get_dota_week_rank,
    get_dota_week_top,
    get_fissure_rank,
    grant_weekly_mmr_awards,
    get_fissure_top,
    get_user,
    get_user_by_username,
    init_db,
    migrate_db,
    release_connection,
    reset_all_fissure_data,
    set_config,
    set_user_in_chat,
    top_cache,
    update_last_message_id,
    update_user_fields_batch,
    user_cache,
)
from dota_mmr import _get_start_card_background, generate_achievement_banner, update_user_mmr
from mute import register_handlers as register_mute_handlers
from rate_limiter import is_rate_limited, rate_limit, set_rate_limited
from tags import (
    TAG_DISPLAY,
    TAG_TYPES,
    add_user_tag,
    format_user_tags,
    remove_user_tag,
)

structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.dev.ConsoleRenderer()
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger(__name__)

# Correlation ID support
import threading
import uuid

_correlation_id = threading.local()

def get_correlation_id() -> str:
    """Get current correlation ID, generate new one if not set."""
    if not hasattr(_correlation_id, 'value') or _correlation_id.value is None:
        _correlation_id.value = str(uuid.uuid4())
    return _correlation_id.value

def set_correlation_id(cid: str = None) -> str:
    """Set correlation ID for current context."""
    if cid is None:
        cid = str(uuid.uuid4())
    _correlation_id.value = cid
    return cid

def clear_correlation_id():
    """Clear correlation ID for current context."""
    if hasattr(_correlation_id, 'value'):
        _correlation_id.value = None

# Bot token
TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    logger.warning("BOT_TOKEN is not set!")

# Anti-spam tracking for party invitations
_party_invite_tracking = {}
PARTY_INVITE_COOLDOWN = 5  # seconds between invites from same user
PARTY_INVITE_MAX_PER_HOUR = 720  # max invites per user per hour (1 every 5 seconds)

MORNING_GREETINGS = [
    "<b>⚔️ Доброе утро, тима!</b>\n\n<i>❤️ – доброе утро всем \n💔 – я сегодня один играю</i>",
    "<b>🛡️ Респавн успешный. Жизнь началась.</b>\n\n<i>❤️ – отличное начало \n💔 – а я ещё сплю</i>",
    "<b>🌄 Кофе + бкб. День не пробьёт.</b>\n\n<i>❤️ – хороший настрой \n💔 – я без кофе сегодня</i>",
    "<b>🍃 Лёгкой линии сегодня, бро!</b>\n\n<i>❤️ – и тебе лёгкой \n💔 – мне и сложная норм</i>",
    "<b>☀️ Мягкое утро, яркие кувшины!</b>\n\n<i>❤️ – спасибо за позитив \n💔 – мне и раковина важна</i>",
    "<b>🌅 Планка дня: не рваться в одиночку.</b>\n\n<i>❤️ – учту на зубок \n💔 – я как всегда в одиночку</i>",
    "<b>🚀 День стартовал, фарм в дело!</b>\n\n<i>❤️ – давай порвёмся \n💔 – а мне и так норм</i>",
    "<b>🎯 Доброе утро, тима! Криты — в плюс.</b>\n\n<i>❤️ – доброе утро \n💔 – сегодня не критует</i>",
    "<b>🔮 Доброе утро, мана пополнена — твори чудеса!</b>\n\n<i>❤️ – удачного дня \n💔 – сегодня без чудес</i>",
    "<b>💪 Доброе утро, ХП восполнен — сила внутри!</b>\n\n<i>❤️ – в рейд \n💔 – дайте фласку</i>",
]

EVENING_GREETINGS = [
    "<b>🌙 Спокойной ночи! Восстанавливай хп.</b>\n\n<i>❤️ – спокойной ночи \n💔 – я ещё немного поиграю</i>",
    "<b>🛌 Карта погашена. Сладких снов.</b>\n\n<i>❤️ – приятных снов \n💔 – а я ещё не ложусь</i>",
    "<b>🌃 Хорошая катка была. Отдыхай.</b>\n\n<i>❤️ – да, пора отдыхать \n💔 – я на ещё одну</i>",
    "<b>✨ Ночная руна. Восстанавливай хп.</b>\n\n<i>❤️ – спокойной ночи \n💔 – я ещё побегаю</i>",
    "<b>🌌 Варды сняты. Спи спокойно.</b>\n\n<i>❤️ – и тебе сладких снов \n💔 – я пока с вардами постою</i>",
    "<b>🕯️ Выход из игры. Сладких снов.</b>\n\n<i>❤️ – ладно, иду спать \n💔 – у меня ещё дела</i>",
    "<b>🎮 Дота спит. И ты ложись.</b>\n\n<i>❤️ – согласен, отдыхаю \n💔 – я без саппорта</i>",
    "<b>🛡️ Отдых — лучший саппорт. Сладких снов.</b>\n\n<i>❤️ – хорошей ночи \n💔 – а мне и в темноте хорошо</i>",
    "<b>🌙 Фарми сны, а не крипов.</b>\n\n<i>❤️ – спокойной ночи \n💔 – я ещё немного поиграю</i>",
    "<b>💤 Тьма на карте. Доброй ночи.</b>\n\n<i>❤️ – приятных снов \n💔 – а я ещё не ложусь</i>",
]

# Prometheus metrics (optional, for monitoring)
try:
    from prometheus_client import Counter, Gauge, Histogram, start_http_server
    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False

from config import settings

if settings.PROMETHEUS_ENABLED and PROMETHEUS_AVAILABLE:
    from prometheus_client import Counter, Gauge, Histogram, start_http_server
    PROMETHEUS_ENABLED = True
    REQUEST_COUNT = Counter('http_requests_total', 'Total HTTP requests', ['method', 'endpoint', 'status'])
    REQUEST_LATENCY = Histogram('http_request_latency_seconds', 'HTTP request latency', ['endpoint'])
    UPDATE_FISSURE_COUNT = Counter('fissure_updates_total', 'Total fissure updates')
    DIGEST_JOB_LATENCY = Histogram('digest_job_latency_seconds', 'Digest job latency')
    ACTIVE_USERS = Gauge('active_users_count', 'Number of users with in_chat=True')
    try:
        start_http_server(8000)
        logger.info("Prometheus metrics server started on port 8000")
    except OSError as e:
        logger.warning(f"Could not start Prometheus server: {e}")
else:
    PROMETHEUS_ENABLED = False
    REQUEST_COUNT = lambda *args, **kwargs: None
    REQUEST_LATENCY = lambda *args, **kwargs: None
    UPDATE_FISSURE_COUNT = lambda *args, **kwargs: None
    DIGEST_JOB_LATENCY = lambda *args, **kwargs: None
    ACTIVE_USERS = lambda *args, **kwargs: None

# Start cooldown tracking (for anti-spam on /start commands)
_START_COOLDOWN = 2  # seconds between /start commands
_USER_START_COOLDOWN = {}
_START_COOLDOWN_MAX_SIZE = 1000
_START_COOLDOWN_TTL = 3600  # 1 hour


from utils import _telegram_error_contains


async def health_check(request):
    """Health check endpoint for Render - verifies DB connectivity"""
    try:
        from database import get_connection, release_connection
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        cursor.close()
        release_connection(conn)
        return web.Response(text="OK: DB connected", status=200)
    except Exception as e:
        logger.error(f"Health check DB error: {e}")
        return web.Response(text=f"ERROR: {e}", status=503)


def _start_cooldown_cleanup_if_needed():
    """Evict oldest entries if cache exceeds max size (simple LRU)"""
    if len(_USER_START_COOLDOWN) > _START_COOLDOWN_MAX_SIZE:
        # Remove oldest 20% of entries
        oldest = sorted(_USER_START_COOLDOWN.items(), key=lambda x: x[1])[:_START_COOLDOWN_MAX_SIZE // 5]
        for uid, _ in oldest:
            _USER_START_COOLDOWN.pop(uid, None)
        logger.debug(f"LRU evicted {len(oldest)} entries from start cooldown")

async def _cleanup_start_cooldown(*args, **kwargs):
    """Periodic cleanup of old _USER_START_COOLDOWN entries to prevent memory leak"""
    current_time = time.time()
    to_remove = [uid for uid, ts in _USER_START_COOLDOWN.items() if current_time - ts > _START_COOLDOWN_TTL]
    for uid in to_remove:
        _USER_START_COOLDOWN.pop(uid, None)
    if to_remove:
        logger.debug(f"Cleaned up {len(to_remove)} stale start cooldown entries")
    # Also apply LRU cleanup
    _start_cooldown_cleanup_if_needed()

async def _cleanup_user_analytics(context):
    """Clean up old analytics_* entries from user_data to prevent memory leak (entries older than 5 minutes)"""
    current_time = time.time()
    ANALYTICS_ENTRY_TTL = 300  # 5 minutes

    # Check for cached timestamp of when analytics data was stored
    analytics_ts = context.user_data.get('analytics_timestamp', 0)
    if current_time - analytics_ts > ANALYTICS_ENTRY_TTL:
        to_remove = []
        for key in list(context.user_data.keys()):
            if isinstance(key, str) and key.startswith('analytics_'):
                to_remove.append(key)
        for key in to_remove:
            context.user_data.pop(key, None)
        # Reset timestamp
        context.user_data['analytics_timestamp'] = 0
        if to_remove:
            logger.debug(f"Cleaned up {len(to_remove)} stale analytics user_data entries")

# Digest state and logic are now fully centralized in digest.py
# (leader election + single active instance on Render).

_bot_can_delete_ttl = 3600  # 1 час
_BOT_CAN_DELETE_CACHE_MAX = 200
_bot_can_delete_cache = {}  # chat_id -> (can_delete, timestamp)

async def bot_can_delete(bot, chat_id):
    """Проверить может ли бот удалять сообщения в чате"""
    current_time = time.time()
    # Cleanup old entries if cache is too large
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


async def cleanup_left_users_job(context):
    """Ежедневная очистка пользователей, вышедших из чата дайджеста"""
    try:
        deleted = cleanup_left_users()
        if deleted:
            logger.info(f"cleanup_left_users_job: удалено {deleted} пользователей")
    except Exception as e:
        logger.error(f"cleanup_left_users_job: {e}")


async def verify_chat_membership_job(context):
    """Лёгкая постепенная проверка — без нагрузки на БД и Telegram.
    Раз в 6 часов проверяем порцию (100) самых "холодных" пользователей.
    """
    try:
        from database import get_connection, get_db_type, release_connection, set_user_in_chat

        digest_chat_id = get_config('digest_chat_id')
        if not digest_chat_id:
            return

        # Берём небольшую порцию — старых по last_activity
        conn = get_connection()
        cursor = conn.cursor()
        db_type = get_db_type()
        if "postgres" in db_type:
            cursor.execute("""
                SELECT telegram_id FROM users
                WHERE in_chat = TRUE
                ORDER BY last_activity ASC NULLS FIRST
                LIMIT 100
            """)
        else:
            cursor.execute("""
                SELECT telegram_id FROM users
                WHERE in_chat = 1
                ORDER BY last_activity ASC
                LIMIT 100
            """)
        candidates = [row[0] for row in cursor.fetchall()]
        cursor.close()
        release_connection(conn)

        if not candidates:
            return

        bot = context.bot
        marked_left = 0

        for tid in candidates:
            try:
                member = await bot.get_chat_member(digest_chat_id, tid)
                if member.status in ('left', 'kicked', 'banned'):
                    set_user_in_chat(tid, False)
                    marked_left += 1
                else:
                    # Подтверждаем, что пользователь всё ещё в чате
                    set_user_in_chat(tid, True)
            except Exception as e:
                # Пользователь реально ушёл или забанен / не найден
                if _telegram_error_contains(e, "user not found", "chat not found", "kicked", "left"):
                    set_user_in_chat(tid, False)
                    marked_left += 1
                else:
                    # Временная ошибка (rate limit, network) — пропускаем этого пользователя в этот раз
                    logger.debug(f"verify membership skip {tid}: {e}")

        if marked_left:
            logger.info(f"verify_chat_membership_job: помечено in_chat=FALSE для {marked_left} пользователей")

    except Exception as e:
        logger.error(f"verify_chat_membership_job: {e}")


async def flush_users_cache_job(context):
    """Периодический сброс dirty-пользователей из кеша в БД"""
    try:
        from database import flush_users_cache
        flushed = await flush_users_cache()
        if flushed:
            logger.info(f"flush_users_cache_job: сохранено {flushed} пользователей")
    except Exception as e:
        logger.error(f"flush_users_cache_job: {e}")


async def decrease_inactive_job(context):
    """Ежедневное задание: уменьшить fissure неактивным игрокам (с кешем)"""
    from datetime import datetime

    # Проверяем когда последний раз выполнялось (кешируем в памяти)
    last_run = get_config('last_decrease_inactive_run')
    today = datetime.now().strftime("%Y-%m-%d")

    if last_run == today:
        logger.info("decrease_inactive_job: уже выполнено сегодня, пропуск")
        return

    try:
        logger.info("Запуск ежедневного уменьшения fissure для неактивных игроков")
        # Неактивные - более 7 дней без активности
        affected = decrease_inactive_fissure(days_inactive=7, decrease_amount=1.0)
        if affected > 0:
            logger.info(f"Уменьшен fissure для {affected} неактивных игроков")
        else:
            logger.info("Нет неактивных игроков для уменьшения fissure")

        # Запоминаем что выполнено сегодня
        set_config('last_decrease_inactive_run', datetime.now().strftime("%Y-%m-%d"))
    except Exception as e:
        logger.error(f"Ошибка в decrease_inactive_job: {e}")






@rate_limit(tokens=1)
async def morning_greeting_job(context):
    """✅ Утреннее приветствие 09:00 MSK - 1 раз в чат"""
    from datetime import datetime as dt

    from database import get_config

    MSK = timezone(timedelta(hours=3))
    today_str = dt.now(MSK).strftime("%Y-%m-%d")

    last_greeting = await asyncio.to_thread(get_config, 'daily_greeting_sent')
    if last_greeting == today_str:
        logger.info("Утреннее приветствие уже отправлено сегодня")
        return

    greeting_text = random.choice(MORNING_GREETINGS)

    try:
        logger.info("Запуск утреннего приветствия 09:00 MSK")

        digest_chat_id = await asyncio.to_thread(get_config, 'digest_chat_id')
        if not digest_chat_id:
            logger.info("Чат для дайджеста не настроен")
            return

        bot = context.application.bot
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("❤️", callback_data="greeting_good"), InlineKeyboardButton("💔", callback_data="greeting_bad")]
        ])
        await bot.send_message(chat_id=digest_chat_id, text=greeting_text, reply_markup=keyboard, parse_mode="HTML")

        await asyncio.to_thread(set_config, 'daily_greeting_sent', today_str)
        logger.info(f"Утреннее приветствие отправлено в чат {digest_chat_id}")

    except Exception as e:
        logger.error(f"Ошибка в morning_greeting_job: {e}")


@rate_limit(tokens=1)
async def night_greeting_job(context):
    """✅ Вечернее приветствие 23:00 MSK - 1 раз в чат"""
    from datetime import datetime as dt

    from database import get_config

    MSK = timezone(timedelta(hours=3))
    today_str = dt.now(MSK).strftime("%Y-%m-%d")

    last_greeting = await asyncio.to_thread(get_config, 'night_greeting_sent')
    if last_greeting == today_str:
        logger.info("Вечернее приветствие уже отправлено сегодня")
        return

    greeting_text = random.choice(EVENING_GREETINGS)

    try:
        logger.info("Запуск вечернего приветствия 23:00 MSK")

        digest_chat_id = await asyncio.to_thread(get_config, 'digest_chat_id')
        if not digest_chat_id:
            logger.info("Чат для дайджеста не настроен")
            return

        bot = context.application.bot
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("❤️", callback_data="greeting_good"), InlineKeyboardButton("💔", callback_data="greeting_bad")]
        ])
        await bot.send_message(chat_id=digest_chat_id, text=greeting_text, reply_markup=keyboard, parse_mode="HTML")

        await asyncio.to_thread(set_config, 'night_greeting_sent', today_str)
        logger.info(f"Вечернее приветствие отправлено в чат {digest_chat_id}")

    except Exception as e:
        logger.error(f"Ошибка в night_greeting_job: {e}")







async def test_greeting(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Testovaja komanda dlya otpravki utrennego i vechernego privetstvija"""
    try:
        await morning_greeting_job(context)
        await night_greeting_job(context)
        await update.message.reply_text("Privetstviya otpravleny (esli chat_id nastroen)")
    except Exception as e:
        logger.error(f"Error in test_greeting: {e}")
        await update.message.reply_text(f"Oshibka: {e}")

async def test_mvp_winner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Тестовая команда для отправки поздравления MVP но недели"""
    try:
        # Добавляем отладку перед вызовом функции
        from datetime import datetime as dt
        from datetime import timedelta, timezone
        MSK = timezone(timedelta(hours=3))
        today_msk = dt.now(MSK)
        # Понедельник - начало недели (weekday 0 = Monday)
        monday_msk = today_msk - timedelta(days=today_msk.weekday())
        current_week_start = monday_msk.strftime("%Y-%m-%d")

        last_announced = get_config('mmr_week_top_announced')
        digest_chat_id = get_config('digest_chat_id')

        debug_info = "Отладка MVP:\n"
        debug_info += f"Сегодня: {today_msk.strftime('%Y-%m-%d %H:%M:%S')} MSK (weekday={today_msk.weekday()})\n"
        debug_info += f"Начало недели: {current_week_start}\n"
        debug_info += f"Последнее поздравление: {last_announced}\n"
        debug_info += f"digest_chat_id: {digest_chat_id}\n"

# Проверяем данные MMR
        from database import get_dota_week_top_from_db
        top_users = get_dota_week_top_from_db(5)
        active_users = [u for u in top_users if u.get('week_games', 0) > 0] if top_users else []

        debug_info += f"Топ MMR пользователей: {len(top_users) if top_users else 0}\n"
        debug_info += f"Активных пользователей: {len(active_users)}\n"

        if active_users:
            winner = active_users[0]
            winner_name = winner.get('steam_nickname') or winner.get('username') or 'Игрок'
            winner_id = winner.get('telegram_id')
            winner_clickable = make_clickable(winner_name, winner_id)
            debug_info += f"MVP: {winner_clickable} ({winner.get('week_games', 0)} игр, {winner.get('week_wins', 0)} побед)\n"

        await update.message.reply_text(debug_info)

        # Теперь вызываем основную функцию
        result = await announce_weekly_mmr_winner(context.bot)

        if result is None:  # Функция завершилась без отправки
            await update.message.reply_text("MVP поздравление НЕ отправлено - проверьте условия выше")
        else:
            await update.message.reply_text("MVP поздравление отправлено!")

    except Exception as e:
        logger.error(f"Error in test_mvp_winner: {e}")
        await update.message.reply_text(f"Ошибка: {e}")


@rate_limit(tokens=1)
async def analyze_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Еженедельная аналитика игрока"""
    user_id = update.effective_user.id
    if not hasattr(analyze_command, "_start_locks"):
        analyze_command._start_locks = {}
    start_lock = analyze_command._start_locks.setdefault(user_id, asyncio.Lock())
    if start_lock.locked():
        await update.effective_message.reply_text("⏳ Аналитика уже обновляется, дождись текущего запуска.")
        return
    await start_lock.acquire()
    try:
        await asyncio.to_thread(get_user, user_id, update.effective_user.username)
    except Exception:
        start_lock.release()
        raise
    loading_msg = None
    chat_id = update.message.chat_id

    # Try to get chat_type safely
    chat_type = 'private'
    if update.message and update.message.chat:
        chat_type = update.message.chat.type

    # Delete user message only in groups/channels
    if chat_type in ['group', 'supergroup', 'channel']:
        if update.message and await bot_can_delete(context.bot, chat_id):
            try:
                await context.bot.delete_message(chat_id, update.message.message_id)
            except Exception:
                pass

    try:
        # Delete previous bot message before sending new one
        try:
            await delete_last_bot_message(context.bot, chat_id, update.effective_user.id)
        except Exception as e:
            logger.debug(f"Could not delete last bot message: {e}")

        # Delete old analytics chart if exists
        old_chart_msg_id = context.user_data.get('analytics_chart_msg_id')
        if old_chart_msg_id:
            try:
                await context.bot.delete_message(chat_id, old_chart_msg_id)
            except Exception as e:
                logger.debug(f"Could not delete old analytics chart: {e}")
            context.user_data['analytics_chart_msg_id'] = None

        # Send loading message and start animation
        try:
            loading_msg = await context.bot.send_message(
                chat_id=chat_id,
                text="<b>🪝Хукаю график...</b>",
                parse_mode="HTML"
            )
            logger.info(f"Created loading message in analyze: chat_id={chat_id}, msg_id={loading_msg.message_id if loading_msg else None}")
        except Exception as e:
            logger.debug(f"Could not send loading message: {e}")
            loading_msg = None

        # Start analytics generation in background task
        async def generate_and_update_analytics():
            nonlocal loading_msg
            try:
                from weekly_analytics import (
                    generate_weekly_analytics,
                    get_last_matches,
                )
                chart_data = await generate_weekly_analytics(update.effective_user.id)

                if chart_data:
                    if isinstance(chart_data, dict) and chart_data.get("error") in ("opendota_rate_limit", "no_steam_linked"):
                        if loading_msg:
                            try:
                                await context.bot.edit_message_text(
                                    chat_id=chat_id,
                                    message_id=loading_msg.message_id,
                                    text=chart_data.get("message", "⚠️ OpenDota API недоступен")
                                )
                            except Exception as e:
                                logger.debug(f"Could not edit loading message: {e}")
                            schedule_delete(context.bot, chat_id, loading_msg.message_id, 10, context.job_queue)
                        return

                    history = chart_data.get("history", [])
                    matches = chart_data.get("matches", [])
                    chart_image = chart_data.get("image")
                    role_from_chart = chart_data.get("role", "CARRY")
                    pro_text = chart_data.get("pro_text", "")
                    detailed_text = chart_data.get("detailed_text", "")
                    stats = chart_data.get("stats")

                    if not matches:
                        try:
                            fresh_matches = await get_last_matches(update.effective_user.id)
                            if len(fresh_matches) >= 5:
                                matches = fresh_matches
                                logger.info(f"Analytics: refetched {len(matches)} fresh matches from API")
                        except Exception as e:
                            logger.warning(f"Analytics: failed to refetch matches: {e}")

                    logger.info(f"Analytics: got chart_data with {len(matches)} matches, image={chart_image is not None}")

                    import os
                    os.makedirs("charts", exist_ok=True)

                    context.user_data['analytics_stats'] = stats
                    context.user_data['analytics_role'] = role_from_chart
                    context.user_data['analytics_page'] = 0
                    context.user_data['analytics_history'] = history
                    context.user_data['analytics_matches'] = matches
                    context.user_data['analytics_chart_image'] = chart_image
                    context.user_data['analytics_pages'] = [
                        {"title": "📊 Разбор матчей", "text": pro_text} if pro_text else None,
                        {"title": "🔎 Что в данных", "text": detailed_text} if detailed_text else None,
                    ]
                    context.user_data['analytics_generated'] = {
                        i for i, p in enumerate([pro_text, detailed_text]) if p is not None
                    }

                    old_chart_msg_id = context.user_data.get('analytics_chart_msg_id')
                    old_table_msg_id = context.user_data.get('analytics_table_msg_id')
                    if old_chart_msg_id or old_table_msg_id:
                        for mid in (old_chart_msg_id, old_table_msg_id):
                            if not mid:
                                continue
                            try:
                                await context.bot.delete_message(chat_id, mid)
                            except Exception as e:
                                logger.debug(f"Could not delete old analytics message: {e}")
                        context.user_data.pop('analytics_chart_msg_id', None)
                        context.user_data.pop('analytics_table_msg_id', None)

                    pages = context.user_data['analytics_pages']
                    generated = context.user_data['analytics_generated']
                    first_page_idx = sorted(generated)[0] if generated else 0
                    if pages and first_page_idx < len(pages) and pages[first_page_idx]:
                        first_text = pages[first_page_idx]["text"]
                    else:
                        first_text = "⚠️ Не удалось сгенерировать таблицы аналитики. Попробуйте позже."

                    keyboard = _build_analytics_table_keyboard(pages, generated, first_page_idx)
                    chart_image = context.user_data.get('analytics_chart_image')
                    table_shown = False
                    if loading_msg:
                        _loading_msg_id = loading_msg.message_id
                        loading_msg = None  # Stop animation
                        try:
                            await context.bot.delete_message(chat_id, _loading_msg_id)
                        except Exception:
                            pass
                    if chart_image:
                        try:
                            chart_msg = await context.bot.send_photo(
                                chat_id=chat_id,
                                photo=io.BytesIO(chart_image),
                                caption=first_text,
                                reply_markup=keyboard,
                                parse_mode="HTML",
                            )
                            context.user_data['analytics_chart_msg_id'] = chart_msg.message_id
                            schedule_delete(context.bot, chat_id, chart_msg.message_id, 60, context.job_queue)
                            table_shown = True
                        except Exception as e:
                            logger.debug(f"Could not send analytics chart photo: {e}")
                    if not table_shown:
                        try:
                            await delete_last_bot_message(context.bot, chat_id, update.effective_user.id)
                        except Exception:
                            pass
                        new_msg = await context.bot.send_message(
                            chat_id=chat_id,
                            text=first_text,
                            reply_markup=keyboard,
                            parse_mode="HTML"
                        )
                        context.user_data['analytics_table_msg_id'] = new_msg.message_id
                        job_queue = context.job_queue
                        if job_queue:
                            schedule_delete(context.bot, chat_id, new_msg.message_id, 60, job_queue)

            except Exception as e:
                logger.error(f"Error in background analytics generation: {e}")
                err_msg_id = loading_msg.message_id if loading_msg else None
                loading_msg = None
                try:
                    await context.bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=err_msg_id,
                        text=f"Ошибка генерации аналитики: {str(e)[:100]}..."
                    )
                except Exception:
                    pass

                schedule_delete(context.bot, chat_id, err_msg_id, 10, context.job_queue)

        # Track background task for this user to cancel on subsequent requests
        user_id_for_tracking = update.effective_user.id
        # Initialize _active_tasks BEFORE pop to avoid race condition
        if not hasattr(analyze_command, '_active_tasks'):
            analyze_command._active_tasks = {}
        existing_task = analyze_command._active_tasks.get(user_id_for_tracking)
        if existing_task and not existing_task.done():
            logger.info("Analytics already running for user %s; ignoring duplicate", user_id_for_tracking)
            start_lock.release()
            return

        # Start background task and track it
        task = asyncio.create_task(generate_and_update_analytics())
        task.add_done_callback(lambda t: analyze_command._active_tasks.pop(user_id_for_tracking, None))
        analyze_command._active_tasks[user_id_for_tracking] = task
        start_lock.release()

        # Start cleanup task
        asyncio.create_task(_cleanup_user_analytics(context))

    except Exception as e:
        logger.error(f"Error in analyze_command: {e}")
        # Delete previous bot message before sending error
        try:
            await delete_last_bot_message(context.bot, chat_id, update.effective_user.id)
        except Exception:
            pass

        msg = await context.bot.send_message(
            chat_id=chat_id,
            text=f"Ошибка анализа: {e}"
        )
        set_last_bot_message(chat_id, update.effective_user.id, msg.message_id)
        schedule_delete(context.bot, chat_id, msg.message_id, 30, context.job_queue)
        update_last_message_id(update.effective_user.id, msg.message_id)


def _get_player_stats_wrapper(steam_id, use_cache):
    """Обёртка для вызова синхронной get_player_stats из потока"""
    from dota_mmr import get_player_stats
    return get_player_stats(steam_id, use_cache=use_cache)


@rate_limit(tokens=1)
async def weekly_champion_announcement_job(context):
    """Объявление чемпиона недели в воскресенье 21:00 MSK (только лидер)."""
    if not await claim_or_check_weekly_leader():
        return
    try:
        await announce_weekly_mmr_winner(context.bot)
    except Exception as e:
        logger.error(f"Ошибка в weekly_champion_announcement_job: {e}")


async def weekly_mmr_reset_job(context):
    """Сброс еженедельной статистики MMR в понедельник 00:00 MSK (только лидер)."""
    if not await claim_or_check_weekly_leader():
        return

    from datetime import datetime as dt
    MSK = timezone(timedelta(hours=3))
    today_msk = dt.now(MSK)
    # Понедельник - начало недели (weekday 0 = Monday)
    monday_msk = today_msk - timedelta(days=today_msk.weekday())
    current_week_start = monday_msk.strftime("%Y-%m-%d")

    try:
        from database import DATABASE_URL, get_connection
        conn_reset = get_connection()
        cursor_reset = conn_reset.cursor()
        url_parsed = urlparse.urlparse(DATABASE_URL)
        scheme = url_parsed.scheme
        if "postgres" in scheme:
            cursor_reset.execute("""
                UPDATE users
                SET week_games = 0,
                    week_wins = 0,
                    week_current_streak = 0,
                    week_best_streak = GREATEST(week_best_streak, week_current_streak),
                    weekly_mvp = 0,
                    weekly_top2 = 0,
                    weekly_top3 = 0,
                    week_start_date = %s
                WHERE steam_id IS NOT NULL
            """, (current_week_start,))
        else:
            cursor_reset.execute("""
                UPDATE users
                SET week_games = 0,
                    week_wins = 0,
                    week_current_streak = 0,
                    week_best_streak = MAX(week_best_streak, week_current_streak),
                    weekly_mvp = 0,
                    weekly_top2 = 0,
                    weekly_top3 = 0,
                    week_start_date = ?
                WHERE steam_id IS NOT NULL
            """, (current_week_start,))
        conn_reset.commit()
        cursor_reset.close()
        from database import release_connection
        release_connection(conn_reset)
        user_cache.clear()
        top_cache.clear()
        user_cache.delete_key('dota_week_top')
        # This helper has its own 30-minute cache, outside top_cache.
        from database import get_dota_week_top_from_db
        digest_chat_id = get_config('digest_chat_id')
        mmr_tag_chat_id = get_config('mmr_chat_id') or digest_chat_id
        get_dota_week_top_from_db._cache = {}
        from database import set_config
        set_config('weekly_mmr_reset_date', current_week_start)
        # Снятие тегов чемпионов/топов предыдущей недели (MVP, ТОП 2, ТОП 3) для всех, кто держит
        try:
            from database import get_connection as _gc
            _conn = _gc()
            _cur = _conn.cursor()
            if "postgres" in scheme:
                for _tag in ("weekly_mvp", "weekly_top1", "weekly_top2", "weekly_top3"):
                    _cur.execute("SELECT telegram_id FROM users WHERE user_tags::text LIKE %s", (f"%{_tag}%",))
                    for _row in _cur.fetchall():
                        try:
                            tag_chat_id = digest_chat_id if _tag == "weekly_mvp" else mmr_tag_chat_id
                            await remove_user_tag(
                                int(_row[0]), _tag, bot=context.bot, chat_id=tag_chat_id
                            )
                        except Exception as _te:
                            logger.warning(f"weekly_reset tag remove failed for {_tag} {_row[0]}: {_te}")
            else:
                for _tag in ("weekly_mvp", "weekly_top1", "weekly_top2", "weekly_top3"):
                    _cur.execute("SELECT telegram_id FROM users WHERE user_tags LIKE ?", (f"%{_tag}%",))
                    for _row in _cur.fetchall():
                        try:
                            tag_chat_id = digest_chat_id if _tag == "weekly_mvp" else mmr_tag_chat_id
                            await remove_user_tag(
                                int(_row[0]), _tag, bot=context.bot, chat_id=tag_chat_id
                            )
                        except Exception as _te:
                            logger.warning(f"weekly_reset tag remove failed for {_tag} {_row[0]}: {_te}")
            _conn.commit()
            _cur.close()
            release_connection(_conn)
            # Do not let the next refresh re-add last week's holders to the
            # freshly reset (empty) weekly top.
            for _key in (
                'current_mvp_telegram_id',
                'current_mvp_tag',
                'current_mmr_top1_telegram_id',
                'current_mmr_top2_telegram_id',
                'current_mmr_top3_telegram_id',
                'mmr_week_awards_granted',
            ):
                set_config(_key, "")
        except Exception as _ge:
            logger.warning(f"weekly_reset tag cleanup skipped: {_ge}")
        logger.info("weekly_mmr_reset_job: еженедельная статистика MMR сброшена в 00:00 MSK")
    except Exception as e:
        logger.error(f"weekly_mmr_reset_job: ошибка при сбросе статистики: {e}")

async def announce_weekly_mmr_winner(bot) -> None:
    """Отправляет поздравление победителю недельного топа MMR в воскресенье."""
    from datetime import datetime as dt
    MSK = timezone(timedelta(hours=3))
    today_msk = dt.now(MSK)
    # Понедельник - начало недели (weekday 0 = Monday)
    monday_msk = today_msk - timedelta(days=today_msk.weekday())
    current_week_start = monday_msk.strftime("%Y-%m-%d")

    # Leader election inside the function too (defense-in-depth)
    if not await claim_or_check_weekly_leader():
        return False

    last_announced = get_config('mmr_week_top_announced')
    if last_announced == current_week_start:
        return False

    # Проверяем, есть ли игроки с данными за текущую неделю
    import urllib.parse as urlparse

    from database import get_connection as gc2
    conn = gc2()
    cursor = conn.cursor()
    scheme = urlparse.urlparse(DATABASE_URL).scheme
    if "postgres" in scheme:
        cursor.execute(
            "SELECT COUNT(*) FROM users WHERE steam_id IS NOT NULL AND week_games > 0 AND week_start_date::text = %s",
            (current_week_start,))
    else:
        cursor.execute(
            "SELECT COUNT(*) FROM users WHERE steam_id IS NOT NULL AND week_games > 0 AND week_start_date = ?",
            (current_week_start,))
    active_players_count = cursor.fetchone()[0]
    cursor.close()
    release_connection(conn)

    is_sunday = today_msk.weekday() == 6

    # Объявление только в воскресенье
    if not is_sunday:
        logger.info("announce_weekly_mmr_winner: не воскресенье - пропускаем")
        return False

    # В воскресенье проверяем, что есть игроки с данными за текущую неделю
    if active_players_count == 0:
        logger.info("announce_weekly_mmr_winner: в воскресенье active_players_count == 0 - данных за неделю ещё нет")
        return False

    digest_chat_id = get_config('digest_chat_id')
    if not digest_chat_id:
        logger.info("announce_weekly_mmr_winner: чат для дайджеста не настроен")
        return False

    from database import get_dota_week_top_from_db
    top_users = await asyncio.to_thread(get_dota_week_top_from_db, 5)
    if not top_users or all(u.get('week_games', 0) == 0 for u in top_users):
        logger.info("announce_weekly_mmr_winner: нет данных для топа MMR (никто не играл)")
        set_config('mmr_week_top_announced', current_week_start)
        return False

    active_users = [u for u in top_users if u.get('week_games', 0) > 0]
    if not active_users:
        set_config('mmr_week_top_announced', current_week_start)
        return False

    winner = active_users[0]
    username = (winner.get('username') or winner.get('steam_nickname') or 'Игрок')
    week_wins = winner.get('week_wins') or 0
    week_games = winner.get('week_games') or 0
    week_losses = week_games - week_wins
    winrate = round(week_wins / week_games * 100) if week_games > 0 else 0
    rank_tier = winner.get('rank_tier', 0)
    telegram_id = winner.get('telegram_id')

    prev_winner_tg_id = get_config('current_mvp_telegram_id')
    prev_winner_tag = get_config('current_mvp_tag')
    if prev_winner_tg_id and prev_winner_tag and digest_chat_id:
        try:
            await remove_user_tag(int(prev_winner_tg_id), "weekly_mvp", bot=bot, chat_id=digest_chat_id)
            logger.info(f"Забран тег у прошлого победителя {prev_winner_tg_id}")
        except Exception as e:
            logger.warning(f"Не удалось забрать тег у прошлого победителя: {e}")

    mvp_tag = "MVP"
    tag_set = False
    if telegram_id and digest_chat_id:
        try:
            tag_set = await add_user_tag(
                telegram_id, "weekly_mvp", bot=bot, chat_id=digest_chat_id
            )
            if tag_set:
                set_config('current_mvp_telegram_id', str(telegram_id))
                set_config('current_mvp_tag', mvp_tag)
                logger.info(f"Установлен тег {mvp_tag} для победителя {telegram_id}")
            else:
                logger.warning(f"Telegram API не подтвердил MVP-тег для {telegram_id}")
        except Exception as e:
            logger.warning(f"Не удалось установить тег победителю: {e}")

    # TOP 1/2/3 are live weekly standings and are updated by the MMR job.
    # The ceremony owns MVP only; it must not also become a second MMR writer.

    ranks = ["🌱 Рекрут", "🔰 Страж", "⚔️ Рыцарь", "🗡️ Герой", "💫 Легенда", "👑 Властелин", "💎 Божество", "🔱 Титан"]
    if rank_tier:
        tier = min(rank_tier // 10, 8)
        star = rank_tier % 10
        if tier < 1 or tier > 8:
            rank_str = "Без ранга"
        elif tier == 8:
            rank_str = ranks[tier - 1]
        else:
            rank_str = f"{ranks[tier - 1]} {star}"
    else:
        rank_str = "Без ранга"

    name_display = make_clickable(username, telegram_id)

    weekly_mvp_count = 0
    weekly_top2_count = 0
    weekly_top3_count = 0
    placements = [(telegram_id, 1)] if telegram_id else []
    if len(active_users) > 1:
        top2_user = active_users[1]
        top2_tg_id = top2_user.get('telegram_id')
        if top2_tg_id:
            placements.append((top2_tg_id, 2))
    if len(active_users) > 2:
        top3_user = active_users[2]
        top3_tg_id = top3_user.get('telegram_id')
        if top3_tg_id:
            placements.append((top3_tg_id, 3))

    award_counts = await asyncio.to_thread(
        grant_weekly_mmr_awards, current_week_start, placements
    )
    if award_counts is None:
        logger.error("Не удалось атомарно начислить недельные награды; церемония будет повторена")
        return False
    weekly_mvp_count = award_counts.get(1, 0)
    weekly_top2_count = award_counts.get(2, 0)
    weekly_top3_count = award_counts.get(3, 0)

    week_heroes = []
    winner_steam_id = winner.get('steam_id')
    if winner_steam_id:
        try:
            from dota_mmr import get_week_top_heroes_async
            week_heroes = await get_week_top_heroes_async(winner_steam_id, top_k=5)
        except Exception as e:
            logger.warning(f"Could not fetch week heroes for champion: {e}")

    net_wins = week_wins - week_losses
    net_sign = "+" if net_wins >= 0 else ""

    _top2_disp = (make_clickable(top2_user.get("username") or top2_user.get("steam_nickname"), top2_user.get("telegram_id")) if len(active_users) > 1 else "")
    _top3_disp = (make_clickable(top3_user.get("username") or top3_user.get("steam_nickname"), top3_user.get("telegram_id")) if len(active_users) > 2 else "")
    text = (
        f"🏆 <b>ЧЕМПИОНЫ НЕДЕЛИ MMR</b> 🏆\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🥇 <b>{name_display}</b>\n"
        f"🥈 <b>{_top2_disp}</b>\n"
        f"🥉 <b>{_top3_disp}</b>\n\n"
        f"✨ <b>Награды и теги выданы:</b>\n"
        f"👑 Чемпион (1-е место) — тег «MVP» в чат + медаль + ачивка «Писатель 100» → в профиль\n"
        f"🥈 Второе место — тег «🥈 ТОП 2» в чат + медаль → в профиль\n"
        f"🥉 Третье место — тег «🥉 ТОП 3» в чат + медаль → в профиль"
    )

    if tag_set or weekly_mvp_count > 0 or weekly_top2_count > 0 or weekly_top3_count > 0:
        text += "\n\n✨ <b>Награды</b>\n"
        if tag_set:
            text += f"👑 Титул «{mvp_tag}» в чате\n"
        if weekly_mvp_count > 0:
            mvp_line = f" ×{weekly_mvp_count}" if weekly_mvp_count > 1 else ""
            text += f"🏅 Медаль MVP{mvp_line} — в профиле\n"
        if weekly_top2_count > 0:
            text += f"🥈 Медаль ТОП 2 ×{weekly_top2_count} — в профиле\n"
        if weekly_top3_count > 0:
            text += f"🥉 Медаль ТОП 3 ×{weekly_top3_count} — в профиле"

    from dota_mmr import generate_start_card

    avatar_url = await resolve_avatar_url_for_card(
        bot,
        telegram_id=telegram_id,
        steam_id=winner.get('steam_id'),
        db_avatar=winner.get('avatar'),
    )
    logger.info(f"Champion card avatar for {username}: {str(avatar_url)[:80] if avatar_url else 'none'}...")

    # Асинхронно генерируем карточку (безопасно для event loop)
    try:
        card_data = await asyncio.to_thread(
            generate_start_card,
            avatar_url=avatar_url,
            message_count=week_games,
            username=username,
            steam_nickname=username,
            rank_tier=rank_tier,
            weekly_mvp=weekly_mvp_count,
            weekly_top2=weekly_top2_count,
            weekly_top3=weekly_top3_count,
            week_wins=week_wins,
            week_losses=week_losses,
            top_heroes=week_heroes or None,
            is_champion=True,
        )

        if card_data:
            await bot.send_photo(
                chat_id=digest_chat_id,
                photo=card_data,
                caption=text,
                parse_mode="HTML"
            )
        else:
            winner_banner_url = get_banner_path("topmmr")
            await bot.send_photo(
                chat_id=digest_chat_id,
                photo=winner_banner_url,
                caption=text,
                parse_mode="HTML"
            )
    except Exception as e:
        logger.error(f"Failed to generate/announce champion card: {e}")
        # Fallback: отправляем текст без карточки
        await bot.send_message(
            chat_id=digest_chat_id,
            text=text,
            parse_mode="HTML"
        )

    set_config('mmr_week_top_announced', current_week_start)
    logger.info(f"announce_weekly_mmr_winner: отправлено поздравление для {username} (неделя {current_week_start})")
    return True



@rate_limit(tokens=1)
async def claim_or_check_mmr_leader():
    """Leader election for MMR job (prevents duplicate heavy work when 2+ Render instances run the same bot)."""
    instance_id = os.getenv("RENDER_INSTANCE_ID") or f"local_{os.getpid()}"
    now = time.time()
    LEADER_TIMEOUT = 900  # 15 minutes (100-200 users with rate limiting)

    current_leader = None
    last_seen = 0.0

    try:
        current_leader = get_config('mmr_leader_id')
        last_seen_str = get_config('mmr_leader_last_seen')
        last_seen = float(last_seen_str) if last_seen_str else 0
    except Exception:
        pass

    is_leader = False

    if current_leader == instance_id:
        is_leader = True
    elif not current_leader or (now - last_seen > LEADER_TIMEOUT):
        try:
            set_config('mmr_leader_id', instance_id)
            set_config('mmr_leader_last_seen', str(now))
            logger.warning(f"MMR: ЗАХВАТИЛ ЛИДЕРСТВО (instance={instance_id})")
            is_leader = True
        except Exception as e:
            logger.error(f"MMR: failed to claim leadership: {e}")
    else:
        logger.info(f"MMR job: пропуск (лидер = {current_leader}, я = {instance_id})")

    if is_leader:
        try:
            set_config('mmr_leader_last_seen', str(now))
        except Exception:
            pass

    return is_leader


async def claim_or_check_weekly_leader():
    """Leader election for weekly jobs (champion announcement + MMR reset).
    Prevents duplicate execution and missed runs when 2+ Render instances are active.
    Uses longer timeout because these tasks run infrequently and can take time.
    """
    instance_id = os.getenv("RENDER_INSTANCE_ID") or f"local_{os.getpid()}"
    now = time.time()
    LEADER_TIMEOUT = 3600  # 1 hour — weekly jobs may take long and run infrequently

    current_leader = None
    last_seen = 0.0

    try:
        current_leader = get_config('weekly_leader_id')
        last_seen_str = get_config('weekly_leader_last_seen')
        last_seen = float(last_seen_str) if last_seen_str else 0
    except Exception:
        pass

    is_leader = False

    if current_leader == instance_id:
        is_leader = True
    elif not current_leader or (now - last_seen > LEADER_TIMEOUT):
        try:
            set_config('weekly_leader_id', instance_id)
            set_config('weekly_leader_last_seen', str(now))
            logger.warning(f"weekly: ЗАХВАТИЛ ЛИДЕРСТВО (instance={instance_id})")
            is_leader = True
        except Exception as e:
            logger.error(f"weekly: failed to claim leadership: {e}")
    else:
        logger.info(f"weekly job: пропуск (лидер = {current_leader}, я = {instance_id})")

    if is_leader:
        try:
            set_config('weekly_leader_last_seen', str(now))
        except Exception:
            pass

    return is_leader


async def update_all_mmr_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Ежечасовое обновление MMR всех пользователей с привязанным Steam (только в кеш)"""
    try:
        if not await claim_or_check_mmr_leader():
            return

        logger.info("Запуск ежечасного обновления MMR")
        from database import batch_save_mmr, cleanup_old_matches, get_all_users_with_steam

        # Fetch users in thread to avoid blocking event loop on DB query
        users = await asyncio.to_thread(get_all_users_with_steam)
        if not users:
            logger.info("Нет пользователей с привязанным Steam для обновления MMR")
            return

        logger.info(f"Обновление MMR для {len(users)} пользователей (leader)")
        success_count = 0
        rank_up_users = []
        all_updated_users = []  # Collect all updated data for batch save

        # Semaphore to limit concurrent OpenDota API calls
        MMR_CONCURRENCY_LIMIT = int(os.getenv("MMR_CONCURRENCY_LIMIT", "2"))
        mmr_semaphore = asyncio.Semaphore(MMR_CONCURRENCY_LIMIT)

        async def update_single_user_mmr_async(user: dict) -> tuple[int, dict | None]:
            """Update MMR for a single user with semaphore limiting"""
            async with mmr_semaphore:
                try:
                    result = await asyncio.to_thread(
                        update_user_mmr, user['telegram_id'], update_top_cache=False
                    )
                    if result and result.get('success'):
                        return user['telegram_id'], result
                    return user['telegram_id'], None
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.error(f"Ошибка обновления MMR для {user['telegram_id']}: {e}")
                    return user['telegram_id'], None

        try:
            results = await asyncio.gather(*[update_single_user_mmr_async(user) for user in users])
        except asyncio.CancelledError:
            logger.warning("update_all_mmr_job cancelled, saving partial progress...")
            results = []

        for telegram_id, result in results:
            if result:
                success_count += 1
                logger.info(f"MMR updated for {telegram_id}: {result.get('mmr')} MMR")
                if result.get('rank_up'):
                    fresh_user = await asyncio.to_thread(get_user, telegram_id) or {'telegram_id': telegram_id}
                    if fresh_user.get('in_chat', True):
                        rank_up_users.append((fresh_user, result['rank_up']))
                if result.get('mmr') is not None:
                    all_updated_users.append({
                        'telegram_id': telegram_id,
                        'mmr': result.get('mmr'),
                        'steam_nickname': result.get('steam_nickname'),
                        'rank_tier': result.get('rank_tier'),
                        'week_games': result.get('week_games') if result.get('week_games') else None,
                        'week_wins': result.get('week_wins') if result.get('week_wins') else None,
                        'week_best_streak': result.get('week_best_streak'),
                        'week_current_streak': result.get('week_current_streak'),
                        'week_start_date': result.get('week_start_date'),
                        'mmr_last_updated': result.get('mmr_last_updated')
                    })

        if all_updated_users:
            await asyncio.to_thread(batch_save_mmr, all_updated_users)

        # Update top cache once after all updates
        from database import get_dota_week_top_from_db, update_dota_week_top_cache
        await asyncio.to_thread(update_dota_week_top_cache)
        # Clear top cache to force refresh on next read. The helper expects a
        # dict; the old (None, 0) tuple made the next call rebuild the dict.
        get_dota_week_top_from_db._cache = {}

        # TOP 1/2/3 are live standings. Reconcile them immediately after the
        # weekly MMR data has been saved, without waiting for the 30-min job.
        try:
            from tags import refresh_mmr_top_tags
            await refresh_mmr_top_tags(context.bot)
            logger.info("MMR job: live TOP 1/2/3 tags refreshed")
        except Exception as e:
            logger.warning(f"MMR job: failed to refresh TOP 1/2/3 tags: {e}")

        # Invalidate dota_digest_stats cache to force fresh data on next read
        from database import user_cache
        user_cache.delete('dota_digest_stats')

        # Refresh Dota digest cache
        try:
            from digest import refresh_dota_digest_cache
            refresh_dota_digest_cache()
        except Exception as e:
            logger.warning(f"Could not refresh Dota digest cache from MMR job: {e}")

        logger.info(f"MMR обновлён для {success_count}/{len(users)} пользователей")

        # Очищаем матчи старше 7 дней из public_player_matches
        try:
            await asyncio.to_thread(cleanup_old_matches)
            logger.info("Очистка старых матчей из public_player_matches завершена")
        except Exception as e:
            logger.warning(f"Ошибка очистки старых матчей: {e}")

        # Получаем digest_chat_id из конфига
        digest_chat_id = get_config('digest_chat_id')

        # Отправляем уведомления о ранк-апах параллельно
        if digest_chat_id and rank_up_users:
            from dota_mmr import (
                generate_start_card,
                get_week_top_heroes,
            )

            async def notify_rank_up(user, rank_info):
                try:
                    username = user.get('username') or user.get('steam_nickname') or 'Игрок'
                    telegram_id = user.get('telegram_id')
                    message_count = user.get('message_count', 0)
                    rank_tier = user.get('rank_tier', 0)
                    avatar_url = await resolve_avatar_url_for_card(
                        context.bot,
                        telegram_id=telegram_id,
                        steam_id=user.get('steam_id'),
                        db_avatar=user.get('avatar'),
                    )

                    card_data = await asyncio.to_thread(
                        generate_start_card,
                        avatar_url=avatar_url,
                        message_count=message_count,
                        username=username,
                        steam_nickname=username,
                        rank_tier=rank_tier,
                        weekly_mvp=user.get('weekly_mvp') or 0,
                        weekly_top2=user.get('weekly_top2') or 0,
                        weekly_top3=user.get('weekly_top3') or 0,
                        week_wins=user.get('week_wins', 0),
                        week_losses=(user.get('week_games', 0) or 0) - (user.get('week_wins', 0) or 0),
                        top_heroes=await asyncio.to_thread(get_week_top_heroes, user.get('steam_id'), top_k=5, match_limit=20) if user.get('steam_id') else None
                    )

                    if card_data:
                        name_display = make_clickable(username, telegram_id)
                        text = f"🎉 {name_display} повысил ранг!\n{rank_info['old_rank']} → {rank_info['new_rank']}"
                        await context.bot.send_photo(chat_id=digest_chat_id, photo=card_data, caption=text, parse_mode="HTML")
                    else:
                        name_display = make_clickable(username, telegram_id)
                        text = f"{name_display} повысил ранг!\n{rank_info['old_rank']} → {rank_info['new_rank']}"
                        rank_up_banner_url = get_banner_path("rankup")
                        await context.bot.send_photo(chat_id=digest_chat_id, photo=rank_up_banner_url, caption=text, parse_mode="HTML")
                except Exception as notify_err:
                    logger.error(f"Ошибка отправки уведомления о ранк-апе: {notify_err}")

            await asyncio.gather(*[notify_rank_up(u, r) for u, r in rank_up_users], return_exceptions=True)



    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.error(f"Ошибка в update_all_mmr_job: {e}")


async def refresh_digest_message(bot):
    """Обновляет данные fissure-дайджеста в памяти (для типа=0).
    Фактическое редактирование сообщения выполняет alternate_digest_job в digest.py."""
    from digest import get_digest_type, set_digest_type, set_fissure_digest_data

    try:
        digest_chat_id = get_config('digest_chat_id')
        if not digest_chat_id:
            return

        current_type = get_digest_type()
        if current_type is None or current_type == "None":
            raw_type = get_config('alternate_digest_type')
            if raw_type is not None:
                current_type = str(raw_type)
            else:
                current_type = "0"
            set_digest_type(current_type)

        if current_type != "0":
            logger.debug(f"refresh_digest_message: пропуск, текущий тип = {current_type} (не fissure-дайджест)")
            return

        # Только обновляем кэш данных, редактирование будет через alternate_digest_job
        stats = await asyncio.to_thread(get_digest_stats)
        set_fissure_digest_data(stats)
        logger.debug("refresh_digest_message: кэш digest_data обновлён, дайджест будет обновлён в следующем тике alternate_digest_job")

    except Exception as e:
        logger.error(f"Ошибка в refresh_digest_message: {e}", exc_info=True)


@rate_limit(tokens=1)
async def dota_digest_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Dota дайджест - лучший/худший винрейт и стрик побед за неделю"""
    try:
        last_run = get_config('dota_digest_last_run')
        now = time.time()
        if last_run and (now - float(last_run)) < JOB_COOLDOWN:
            logger.info(f"dota_digest_job: пропуск (запущен {(now - float(last_run)):.1f}с назад)")
            return
        set_config('dota_digest_last_run', str(now))

        logger.info("Запуск Dota дайджеста")

        # Получаем ID чата для дайджеста
        digest_chat_id = get_config('digest_chat_id')
        if not digest_chat_id:
            logger.info("Чат для дайджеста не настроен")
            return

        mmr_top = get_dota_week_top(limit=10)

        if not mmr_top:
            logger.info("Нет данных для Dota дайджеста")
            return

        # top_winrate - лучший по винрейту среди топ MMR (не менее 3 игр за неделю)
        # bottom_winrate - худший по винрейту среди топ MMR
        # top_streak - лучший стрик среди топ MMR

        valid_players = [p for p in mmr_top if p.get('week_games', 0) >= 3]

        if not valid_players:
            logger.info("Нет игроков с 3+ играми для Dota дайджеста")
            return

        # top_net - лучший по разнице побед-поражений (wins - losses), при равенстве net — больше игр
        # Убедимся что top и bottom это РАЗНЫЕ игроки
        valid_players_sorted = sorted(valid_players, key=lambda p: ((p.get('week_wins') or 0) - ((p.get('week_games') or 0) - (p.get('week_wins') or 0)), p.get('week_games', 0) or 0), reverse=True)

        if len(valid_players_sorted) >= 2:
            top_by_net = valid_players_sorted[0]
            # Для bottom ищем с конца, но исключаем top игрока
            for p in reversed(valid_players_sorted):
                if p.get('telegram_id') != top_by_net.get('telegram_id'):
                    bottom_by_net = p
                    break
            else:
                # Если не нашли другого - берем последнего
                bottom_by_net = valid_players_sorted[-1]
        elif len(valid_players_sorted) == 1:
            top_by_net = valid_players_sorted[0]
            bottom_by_net = valid_players_sorted[0]  # Только один игрок
        else:
            top_by_net = None
            bottom_by_net = None

        # Лучший стрик - только игроки со стриком > 0
        players_with_streak = [p for p in valid_players if p.get('week_current_streak', 0) > 0]
        top_streak_player = max(players_with_streak, key=lambda p: p.get('week_current_streak', 0)) if players_with_streak else None

        top_player = top_by_net.get('steam_nickname', 'None')
        top_id = top_by_net.get('telegram_id')
        top_steam_id = top_by_net.get('steam_id')
        top_games = top_by_net.get('week_games', 0)
        top_wins = top_by_net.get('week_wins', 0)
        top_losses = top_games - top_wins
        top_winrate = round(top_wins / top_games * 100) if top_games > 0 else 0

        bottom_player = bottom_by_net.get('steam_nickname', 'None')
        bottom_id = bottom_by_net.get('telegram_id')
        bottom_steam_id = bottom_by_net.get('steam_id')
        bottom_games = bottom_by_net.get('week_games', 0)
        bottom_wins = bottom_by_net.get('week_wins', 0)
        bottom_losses = bottom_games - bottom_wins
        bottom_winrate = round(bottom_wins / bottom_games * 100) if bottom_games > 0 else 0

        if top_streak_player:
            streak_player = top_streak_player.get('steam_nickname', 'None')
            streak_wins = top_streak_player.get('week_current_streak', 0)
            streak_id = top_streak_player.get('telegram_id')
            streak_steam_id = top_streak_player.get('steam_id')
        else:
            streak_player = 'None'
            streak_wins = 0
            streak_id = None
            streak_steam_id = None

        # Форматируем - показываем net wins (разницу)
        top_display = clickable_name(top_player, top_id, top_steam_id) if top_player and top_player != "None" else "—"
        bottom_display = clickable_name(bottom_player, bottom_id, bottom_steam_id) if bottom_player and bottom_player != "None" else "—"
        streak_display = clickable_name(streak_player, streak_id, streak_steam_id) if streak_player and streak_player != "None" and streak_wins > 0 else "—"

        if top_player and top_player != "None":
            top_part = f"🎯 {top_display}▲ {top_wins}W/{top_losses}L ≈{top_winrate}%"
        else:
            top_part = "🔺—"

        if bottom_player and bottom_player != "None":
            bottom_part = f"🔻{bottom_display}: {bottom_wins}W/{bottom_losses}L ≈{bottom_winrate}%"
        else:
            bottom_part = "🔻—"

        if streak_player and streak_player != "None" and streak_wins > 0:
            streak_part = f"🔸{streak_display}: {streak_wins} игр подряд"
        else:
            streak_part = "🔸—"

        text = f"<b>{top_part}\n{bottom_part}\n{streak_part}</b>\n\n🦞 Дота Дайджест."

        bot = context.application.bot

        from digest import get_dota_last_text, set_dota_last_text

        # Пропускаем если текст не изменился
        if get_dota_last_text() == text:
            logger.debug("Dota дайджест текст не изменился, пропускаем")
            return

        # Пробуем отредактировать существующее сообщение
        last_message_id = get_config('dota_digest_message_id')
        if last_message_id:
            try:
                await bot.edit_message_text(
                    chat_id=int(digest_chat_id),
                    message_id=int(last_message_id),
                    text=text,
                    parse_mode="HTML"
                )
                logger.info(f"Обновлён существующий Dota дайджест {last_message_id}")
                set_dota_last_text(text)  # кэшируем
                return
            except Exception as e:
                if _telegram_error_contains(e, "429", "too many requests"):
                    logger.warning("Rate limited by Telegram in dota_digest, skipping")
                    set_dota_last_text(text)
                    return
                if _telegram_error_contains(e, "message is not modified"):
                    logger.info("Dota дайджест не изменился, пропускаем")
                    set_dota_last_text(text)  # кэшируем текущий
                    return
                if _telegram_error_contains(e, "message to edit not found", "message can't be edited"):
                    logger.info(f"Старое сообщение {last_message_id} удалено или нельзя редактировать, создаём новое")
                    set_config('dota_digest_message_id', None)
                else:
                    logger.info(f"Не удалось редактировать сообщение: {e}")

        # Отправляем новое сообщение
        msg = await bot.send_message(chat_id=digest_chat_id, text=text, parse_mode="HTML")
        set_config('dota_digest_message_id', msg.message_id)
        set_dota_last_text(text)  # кэшируем
        logger.info(f"Создан новый Dota дайджест {msg.message_id}")

    except Exception as e:
        logger.error(f"Ошибка в dota_digest_job: {e}", exc_info=True)


# alternate_digest_job живёт в digest.py (с лидерской выборкой).
from bot_utils import (
    ManualContext,
    _build_analytics_keyboard,
    _build_analytics_table_keyboard,
    add_bot_message,
    clickable_name,
    delete_last_bot_message,
    get_user_avatar_url,
    main_menu,
    make_clickable,
    record_recent_fissure_roll,
    schedule_delete,
    set_last_bot_message,
    update_last_message_id,
)
from constants import (
    JOB_COOLDOWN,
    KEEPALIVE_PING_NEON_HOURS,
    TOPMMR_BANNER_PATH,
    WELCOME_PHRASES,
    get_banner_path,
)
from digest import alternate_digest_job, morning_digest_job
from fissure import (
    fissure,
)
from party import party_command

# All roll data (ROLL_MEMES, CATEGORY_PHRASES), welcome phrases,
# multicast/zeus defaults, weekend multipliers and digest headers
# have been moved to rolls.py and constants.py.
# Local duplicates removed — using imported versions.




async def fetch_hero_icon(url, session=None, size=96):
    if not url:
        return None
    close_session = False
    if session is None:
        session = aiohttp.ClientSession()
        close_session = True
    try:
        async with session.get(url) as resp:
            if resp.status == 200:
                data = await resp.read()
                # Уменьшаем через Pillow в отдельном потоке чтобы не блокировать event loop
                try:
                    import io

                    from PIL import Image
                    loop = asyncio.get_running_loop()
                    # Выполняем блокирующие операции в thread pool
                    img = await loop.run_in_executor(
                        None,
                        lambda: Image.open(io.BytesIO(data)).resize((size, size), Image.LANCZOS)
                    )
                    bio = io.BytesIO()
                    await loop.run_in_executor(None, img.save, bio, format='PNG', optimize=True)
                    bio.seek(0)
                    bio.name = url.split("/")[-1]
                    return bio
                except ImportError:
                    # Pillow не установлен — возвращаем оригинал
                    bio = io.BytesIO(data)
                    bio.name = url.split("/")[-1]
                    return bio
    finally:
        if close_session:
            await session.close()
    return None




DEFAULT_AVATAR_URL = str(get_banner_path("default_avatar"))

_TOP_CARD_CACHE: OrderedDict[tuple, bytes] = OrderedDict()
_TOP_CARD_CACHE_MAX_SIZE = 20


def get_cached_top_card(generator, cache_key: tuple, **kwargs):
    """Generate a top card once per unchanged leader data and keep it in RAM.

    The old implementation downloaded the winner's avatar and rebuilt the same
    PNG on every command invocation.  Cache keys contain every visible input,
    so a leader/MMR/fissure/name/avatar change immediately produces a new card.
    """
    cached = _TOP_CARD_CACHE.get(cache_key)
    if cached is not None:
        _TOP_CARD_CACHE.move_to_end(cache_key)
        return cached

    card = generator(**kwargs)
    if card:
        _TOP_CARD_CACHE[cache_key] = card
        _TOP_CARD_CACHE.move_to_end(cache_key)
        while len(_TOP_CARD_CACHE) > _TOP_CARD_CACHE_MAX_SIZE:
            _TOP_CARD_CACHE.popitem(last=False)
    return card


async def resolve_avatar_url_for_card(
    bot,
    telegram_id: int | None = None,
    steam_id: int | None = None,
    db_avatar: str | None = None,
    fetch_steam: bool = True,
) -> str:
    """Telegram → БД → Steam → дефолтная картинка."""
    if telegram_id and bot:
        tg_url = await get_user_avatar_url(bot, telegram_id)
        if tg_url:
            return tg_url
    if db_avatar:
        return db_avatar
    if fetch_steam and steam_id:
        try:
            fresh = await asyncio.to_thread(_get_player_stats_wrapper, steam_id, False)
            if fresh and fresh.get("avatar"):
                return fresh["avatar"]
        except Exception as e:
            logger.warning(f"resolve_avatar_url_for_card steam {steam_id}: {e}")
    return DEFAULT_AVATAR_URL


async def about(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show bot stats and resource usage."""
    await asyncio.to_thread(get_user, update.effective_user.id, update.effective_user.username)
    try:
        from analytics_dashboard import generate_dashboard_text
        text = generate_dashboard_text()
        await update.message.reply_text(text, parse_mode="HTML")
    except Exception as e:
        logger.error(f"about error: {e}")
        await update.message.reply_text("Stats unavailable")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command - show profile card"""
    chat_id = update.effective_chat.id if update.effective_chat else None
    try:
        if is_rate_limited():
            logger.warning("Skipping /start due to rate limit")
            try:
                await update.message.reply_text("Пожалуйста, подождите несколько секунд и попробуйте снова.")
            except Exception:
                pass
            return

        user_id = update.effective_user.id
        current_time = time.time()

        if len(_USER_START_COOLDOWN) > 100:
            await _cleanup_start_cooldown()

        if user_id in _USER_START_COOLDOWN:
            last_time = _USER_START_COOLDOWN[user_id]
            if current_time - last_time < _START_COOLDOWN:
                logger.warning(f"Spam protection: user {user_id} tried to use /start too soon")
                await update.message.reply_text("Пожалуйста, подождите перед повторным использованием команды /start")
                return
        _USER_START_COOLDOWN[user_id] = current_time

        user = await _ensure_user_for_start(update, user_id)
        if not user:
            return

        if user.get("is_new"):
            await _send_welcome_start(update, user_id, context)
            return

        await _send_profile_card(update, user_id, context)

    except Exception as e:
        error_str = str(e).lower()
        if _telegram_error_contains(e, "flood control", "429", "too many requests"):
            retry_after = 60
            match = re.search(r'retry in (\d+) seconds', error_str)
            if match:
                retry_after = int(match.group(1)) + 5
            set_rate_limited(retry_after)
        logger.error(f"start command error: {e}", exc_info=True)
        await menu_handler(update, context, allow_when_rate_limited=True)


async def _ensure_user_for_start(update: Update, user_id: int) -> dict | None:
    telegram_username = update.effective_user.username
    first_name = update.effective_user.first_name or "Friend"
    plain_username = telegram_username or first_name

    db_user = await asyncio.to_thread(get_user, user_id)
    if db_user is None:
        fallback_name = telegram_username or first_name or f"Player{user_id}"
        db = Database()
        db.register_user(user_id, fallback_name, first_name, source="start")
        logger.info(f"Created new user {user_id} with name '{fallback_name}'")
        user = await asyncio.to_thread(get_user, user_id)
        if user:
            user["is_new"] = True
        return user

    updates = {}
    current_username = db_user.get("username")
    if telegram_username and telegram_username != current_username:
        updates["username"] = telegram_username
    elif current_username is None and first_name and first_name != "Friend":
        updates["username"] = first_name
    if updates:
        await asyncio.to_thread(update_user_fields_batch, user_id, updates)
        logger.info(f"Updated user {user_id} fields: {updates}")

    user = dict(db_user)
    user["is_new"] = False
    return user


async def _send_welcome_start(update: Update, user_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    banner_url = get_banner_path("cooldown")
    text = "👉 Ты в игре — крути фиссуру, чекай топы, подключай Dota и докажи, что ты тут не случайно."
    msg = await context.bot.send_photo(
        chat_id=chat_id,
        photo=banner_url,
        caption=text,
        reply_markup=main_menu()
    )
    set_last_bot_message(chat_id, user_id, msg.message_id)
    update_last_message_id(user_id, msg.message_id)


async def _send_profile_card(update: Update, user_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = await asyncio.to_thread(get_user, user_id)
    if not user:
        logger.error(f"Failed to get user {user_id}")
        return

    from dota_mmr import generate_start_card

    chat_id = update.effective_chat.id
    user_msg_id = update.message.message_id if update.message else None

    if user_msg_id and isinstance(user_msg_id, int) and user_msg_id > 0:
        try:
            await context.bot.delete_message(chat_id, user_msg_id)
        except Exception as e:
            if _telegram_error_contains(e, "not found", "bad request"):
                logger.debug(f"User message {user_msg_id} already deleted: {e}")
            else:
                logger.debug(f"Could not delete user message {user_msg_id}: {e}")

    try:
        await delete_last_bot_message(context.bot, chat_id, user_id)
    except Exception as e:
        logger.debug(f"Could not delete last bot message in start: {e}")

    loading_msg = None
    try:
        loading_msg = await context.bot.send_message(
            chat_id=chat_id,
            text="<b>🪝Хукаю...</b>",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.debug(f"Could not send loading message in start: {e}")

    steam_id = user.get("steam_id")
    steam_nickname = user.get("steam_nickname")
    plain_username = update.effective_user.username or update.effective_user.first_name or "Friend"
    rank_tier = user.get("rank_tier", 0)
    message_count = user.get("message_count", 0)

    card_data = None
    if steam_id and steam_nickname:
        avatar_url = await _resolve_start_avatar(user, context.bot, user_id)
        weekly_mvp = user.get("weekly_mvp") or 0
        weekly_top2 = user.get("weekly_top2") or 0
        weekly_top3 = user.get("weekly_top3") or 0

        card_data = await asyncio.to_thread(
            generate_start_card,
            avatar_url=avatar_url,
            message_count=message_count,
            username=plain_username,
            steam_nickname=steam_nickname,
            rank_tier=rank_tier,
            weekly_mvp=weekly_mvp,
            weekly_top2=weekly_top2,
            weekly_top3=weekly_top3,
            week_wins=None,
            week_losses=None,
        )
    else:
        avatar_url = await get_user_avatar_url(context.bot, user_id)
        if not avatar_url:
            avatar_url = DEFAULT_AVATAR_URL

        card_data = await asyncio.to_thread(
            generate_start_card,
            avatar_url=avatar_url,
            message_count=message_count,
            username=plain_username,
            steam_nickname=None,
            rank_tier=0,
            weekly_mvp=user.get("weekly_mvp") or 0,
            weekly_top2=user.get("weekly_top2") or 0,
            weekly_top3=user.get("weekly_top3") or 0,
            week_wins=None,
            week_losses=None,
        )

    if card_data:
        name_display = make_clickable(plain_username, user_id)
        text = f"👤 {name_display}"
        msg = await context.bot.send_photo(
            chat_id=chat_id,
            photo=card_data,
            caption=text,
            parse_mode="HTML",
            reply_markup=main_menu()
        )
        set_last_bot_message(chat_id, user_id, msg.message_id)
        update_last_message_id(user_id, msg.message_id)
        schedule_delete(context.bot, chat_id, msg.message_id, 30, context.job_queue)
    else:
        await menu_handler(update, context)

    if loading_msg:
        try:
            await context.bot.delete_message(chat_id, loading_msg.message_id)
        except Exception:
            pass


async def _resolve_start_avatar(user: dict, bot, user_id: int) -> str:
    from dota_mmr import get_player_stats

    steam_id = user.get("steam_id")
    avatar_url = await get_user_avatar_url(bot, user_id)
    if not avatar_url:
        avatar_url = user.get("avatar")
    if not avatar_url:
        try:
            stats = await asyncio.to_thread(get_player_stats, steam_id, True, 8)
            if stats and stats.get("avatar"):
                avatar_url = stats["avatar"]
        except Exception:
            pass
    return avatar_url or DEFAULT_AVATAR_URL


def _increment_greeting_counter(key: str, date_str: str, reaction_type: str) -> tuple[int, int, int]:
    """Atomically persist greeting counters in a worker thread.

    The database API is synchronous, so keeping it out of the Telegram event
    loop prevents a slow Neon round-trip from delaying other commands.
    """
    from database import get_config, set_config

    current = int(get_config(key) or 0) + 1
    set_config(key, current)
    good_count = int(get_config(f"greeting_{date_str}_good") or 0)
    bad_count = int(get_config(f"greeting_{date_str}_bad") or 0)
    return current, good_count, bad_count


@rate_limit(tokens=1)
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle button callbacks with pagination support for analytics."""
    callback_query = update.callback_query
    if not callback_query:
        return

    data = callback_query.data
    chat_id = callback_query.message.chat_id if callback_query.message else None
    logger.info(f"button_callback: user={callback_query.from_user.id} chat={chat_id} data={data}")

    # === ROLL FISSURE HANDLER (callback from menu/welcome) - FIRST PRIORITY ===
    if data == "roll_fissure":
        import time as _time
        await callback_query.answer()
        user_obj = callback_query.from_user
        chat_id = callback_query.message.chat_id
        chat_type = callback_query.message.chat.type if callback_query.message else 'private'

        logger.info(f"roll_fissure: user={user_obj.id} chat={chat_id} chat_type={chat_type}")

        # Get current time for fake message
        _current_time = int(_time.time())

        # Ensure user account exists before rolling
        from database import get_user
        await asyncio.to_thread(get_user, user_obj.id, user_obj.username)

        class _FakeChat:
            def __init__(self):
                self.id = chat_id
                self.type = chat_type

        class _FakeUser:
            def __init__(self):
                self.id = user_obj.id
                self.is_bot = user_obj.is_bot
                self.first_name = user_obj.first_name or ''
                self.username = user_obj.username
                self.last_name = getattr(user_obj, 'last_name', None)
                self.language_code = getattr(user_obj, 'language_code', None)

        class _FakeMsg:
            def __init__(self):
                self.message_id = 0
                self.chat_id = chat_id
                self.chat = _FakeChat()
                self.from_user = _FakeUser()
                self.date = _current_time
                self.text = '/fissure'

        fake_msg = _FakeMsg()

        class _FakeUpdate:
            def __init__(self):
                self.update_id = update.update_id
                self.message = fake_msg
                # fissure() reads update.effective_message, so the synthetic update
                # must expose it too (otherwise AttributeError for real user objects)
                self.effective_message = fake_msg
                self.effective_user = _FakeUser()
                self.effective_chat = _FakeChat()

        await fissure(_FakeUpdate(), context)
        return

    # Handle analytics_show separately with loading indicator (as chat message)
    if data == "analytics_show":
        await callback_query.answer()
        loading_msg = await context.bot.send_message(chat_id=chat_id, text="<b>🪝Хукаю аналитику...</b>", parse_mode="HTML")

        try:
            await _show_analytics_page(callback_query, 0, context, loading_msg=loading_msg)
        except Exception as e:
            logger.error(f"Error in button_callback: {e}", exc_info=True)
            if loading_msg:
                msg_id = loading_msg.message_id if loading_msg else None
                loading_msg = None
                if msg_id:
                    try:
                        await context.bot.edit_message_text(chat_id=chat_id, message_id=msg_id, text="❌ Ошибка загрузки данных")
                        schedule_delete(context.bot, chat_id, msg_id, 30, context.job_queue)
                    except Exception:
                        pass
        return

    # Handle analytics table buttons (Pro / Подробное сравнение)
    if data and data.startswith("analytics_table_"):
        await callback_query.answer()
        try:
            table_idx = int(data.split("_")[-1])
            await _show_analytics_page(callback_query, table_idx, context)
        except Exception as e:
            logger.error(f"Error in button_callback: {e}", exc_info=True)
        return

    # Handle analytics_page_N - no loading indicator (pages already generated or will show error)
    if data and data.startswith("analytics_page_"):
        await callback_query.answer()
        # Ignore page indicator button clicks
        if data == "analytics_page_current":
            return
        try:
            page_idx = int(data.split("_")[-1])
            await _show_analytics_page(callback_query, page_idx, context)
        except Exception as e:
            logger.error(f"Error in button_callback: {e}", exc_info=True)
        return

    # Handle pro compare button from chart
    if data == "analytics_pro_compare":
        await callback_query.answer()
        loading_msg = await context.bot.send_message(chat_id=chat_id, text="<b>🪝Хукаю сравнение с Pro...</b>", parse_mode="HTML")
        try:
            await _show_analytics_page(callback_query, 0, context, loading_msg=loading_msg)
        except Exception as e:
            logger.error(f"Error in analytics_pro_compare: {e}", exc_info=True)
        return

    # Link button handler (callback from menu)
    if data == "link":
        await callback_query.answer()
        chat_id = callback_query.message.chat_id if callback_query.message else None
        if not chat_id:
            chat_id = update.effective_chat.id

        from bot_utils import delete_last_bot_message
        try:
            await delete_last_bot_message(context.bot, chat_id, callback_query.from_user.id)
        except Exception as e:
            logger.debug(f"Could not delete last bot message: {e}")

        link_banner_url = get_banner_path("link")
        link_text = ("🦞 <b>Привязать Аккаунт Dota 2</b>\n\n"
            "Добавить в друзья → Ваш ID → копировать →\n"
            "<code>/link 347614947</code>\n\n"
            "Или ссылку на dotabuff →\n"
            "<code>/link https://ru.dotabuff.com/players/347614699</code>\n\n"
            "⚠️ в игре:\n"
            "Настройки → расширенные → сообщество → общедоступная история матчей (вкл)")

        result_msg = await context.bot.send_photo(
            chat_id=chat_id,
            photo=link_banner_url,
            caption=link_text,
        parse_mode='HTML',
            reply_markup=main_menu()
        )
        set_last_bot_message(chat_id, callback_query.from_user.id, result_msg.message_id)
        add_bot_message(chat_id, callback_query.from_user.id, result_msg.message_id)
        schedule_delete(context.bot, chat_id, result_msg.message_id, 30, context.job_queue)
        update_last_message_id(callback_query.from_user.id, result_msg.message_id)
        return

    # Techies "roll again" button — user guessed the mine, offer another fissure roll.
    # NOTE: this branch MUST stay above the generic "techies_" branch below: the latter
    # catches every "techies_*" callback, so "techies_again_<user_id>" would be swallowed
    # by handle_techies_button (which needs >= 5 underscore-separated parts).
    if data and data.startswith("techies_again_"):
        import time as _time

        # The button is emitted per-user as "techies_again_<user_id>", so only the player
        # who defused the mine may use it (same rule as in techies.handle_techies_button).
        try:
            _again_owner_id = int(data.rsplit("_", 1)[1])
        except (IndexError, ValueError):
            _again_owner_id = None
        if _again_owner_id is not None and callback_query.from_user.id != _again_owner_id:
            await callback_query.answer("🧨 Это не твоя мина, бродяга!", show_alert=True)
            return

        await callback_query.answer("🎲 Запускаю ещё один ролл!")
        user_obj = callback_query.from_user
        chat_id = callback_query.message.chat_id if callback_query.message else None
        chat_type = callback_query.message.chat.type if callback_query.message else 'private'

        class _FakeChat_again:
            def __init__(self):
                self.id = chat_id
                self.type = chat_type

        class _FakeUser_again:
            def __init__(self):
                self.id = user_obj.id
                self.is_bot = user_obj.is_bot
                self.first_name = user_obj.first_name or ''
                self.username = user_obj.username
                self.last_name = getattr(user_obj, 'last_name', None)
                self.language_code = getattr(user_obj, 'language_code', None)

        class _FakeMsg_again:
            def __init__(self):
                self.message_id = 0
                self.chat_id = chat_id
                self.chat = _FakeChat_again()
                self.from_user = _FakeUser_again()
                self.date = int(_time.time())
                self.text = '/fissure'

        _fake_msg = _FakeMsg_again()

        class _FakeUpdate_again:
            def __init__(self):
                self.update_id = update.update_id
                self.message = _fake_msg
                # fissure() reads update.effective_message, so the synthetic update
                # must expose it too (otherwise AttributeError for real user objects)
                self.effective_message = _fake_msg
                self.effective_user = _FakeUser_again()
                self.effective_chat = _FakeChat_again()

        await fissure(_FakeUpdate_again(), context)
        return

    # Techies buttons answer inside handler (wrong-user alert / already exploded)
    if data and data.startswith("techies_"):
        from techies import handle_techies_button
        await handle_techies_button(update, context, record_recent_fissure_roll)
        return

    # Party buttons - send @username with party invitation (with anti-spam protection)
    if data and data.startswith("party_user:"):
        import time

        inviter_id = callback_query.from_user.id
        now = time.time()

        # Check cooldown - simple time-based check
        last_invite_time = _party_invite_tracking.get(inviter_id, 0)
        # Ensure last_invite_time is a number (handle old data)
        if not isinstance(last_invite_time, (int, float)):
            last_invite_time = 0
        if now - last_invite_time < PARTY_INVITE_COOLDOWN:
            await callback_query.answer()
            return

        # Check hourly limit
        hour_ago = now - 3600
        invite_count = _party_invite_tracking.get(f"{inviter_id}_count", 0)
        if now - last_invite_time < 3600 and invite_count >= PARTY_INVITE_MAX_PER_HOUR:
            await callback_query.answer()
            return

        # Update tracking
        _party_invite_tracking[inviter_id] = now
        _party_invite_tracking[f"{inviter_id}_count"] = invite_count + 1

        await callback_query.answer()
        user_identifier = data.split(":", 1)[1]
        chat_id = callback_query.message.chat_id

        # Import get_user for this handler
        from database import get_user

        # Get the invited player
        invited_player = None
        if user_identifier.isdigit():
            invited_player = await asyncio.to_thread(get_user, int(user_identifier))
        else:
            invited_player = await asyncio.to_thread(get_user_by_username, user_identifier)

        if not invited_player:
            await context.bot.send_message(
                chat_id=chat_id,
                text="❌ Пользователь не найден.",
            )
            return

        # Get inviter data
        inviter = await asyncio.to_thread(get_user, inviter_id)

        # Build invitation message
        username = invited_player.get("username") or ""
        if username and username.startswith("@"):
            username = username[1:]
        if not username:
            username = f"tg{invited_player.get('telegram_id')}" if invited_player.get("telegram_id") else "пользователь"

        # Get invited player stats
        invited_rank_tier = invited_player.get("rank_tier", 0) or 0

        # Get inviter stats for the invitation
        inviter_username = inviter.get("username") or "" if inviter else ""
        if inviter_username and inviter_username.startswith("@"):
            inviter_username = inviter_username[1:]
        if not inviter_username:
            inviter_username = f"tg{inviter_id}" if inviter_id else "пользователь"

        inviter_week_games = 0
        inviter_week_wins = 0
        if inviter:
            inviter_week_games = inviter.get("week_games", 0) or 0
            inviter_week_wins = inviter.get("week_wins", 0) or 0
        inviter_winrate = round(inviter_week_wins / inviter_week_games * 100) if inviter_week_games > 0 else 0

        # Use rank_to_string from dota_mmr for real ranks
        from dota_mmr import rank_to_string
        inviter_rank_name = rank_to_string(inviter.get("rank_tier", 0) or 0 if inviter else 0)

        invitation_text = (
            f"👤 @{username},  Готов к игре?\n\n"
            f"👤 @{inviter_username},  приглашает тебя в пати!\n"
            f"└  {inviter_rank_name} • WR: {inviter_winrate}% за неделю."
        )

        await context.bot.send_message(chat_id=chat_id, text=invitation_text, parse_mode="HTML")
        return

    # Answer only for branches that don't handle it themselves (techies, greeting)
    if data and (data.startswith("techies_") or data.startswith("greeting_")):
        await callback_query.answer()

    try:
        # === GREETING REACTIONS ===
        if data and data.startswith("greeting_"):
            emoji = "👍" if "good" in data else "❤️"
            reaction_type = "good" if "good" in data else "bad"

            from datetime import datetime as dt

            # Синхронный config read/write выполняем в worker thread: нажатие
            # кнопки не должно блокировать обработку остальных апдейтов.
            from database import get_config, set_config
            date_str = dt.now(timezone(timedelta(hours=3))).strftime("%Y-%m-%d")
            key = f"greeting_{date_str}_{reaction_type}"

            # Сначала подтверждаем нажатие — это быстрый Telegram-ответ.
            await callback_query.answer(cache_time=0)

            current, good_count, bad_count = await asyncio.to_thread(
                _increment_greeting_counter, key, date_str, reaction_type
            )

            # Не делаем лишний Telegram API-вызов, если callback уже был
            # обработан и счётчик не изменился (защита от retry Telegram).
            try:
                await context.bot.set_message_reaction(
                    chat_id=chat_id,
                    message_id=callback_query.message.message_id,
                    reaction={"emoji": emoji}
                )
            except Exception:
                logger.debug("Could not set greeting reaction", exc_info=True)

            try:
                keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton(f"❤️ {good_count}", callback_data="greeting_good"),
                     InlineKeyboardButton(f"💔 {bad_count}", callback_data="greeting_bad")]
                ])
                await context.bot.edit_message_reply_markup(
                    chat_id=chat_id,
                    message_id=callback_query.message.message_id,
                    reply_markup=keyboard
                )
            except Exception as e:
                # "Message is not modified" — это нормально, не ошибка.
                if "not modified" not in str(e).lower():
                    logger.debug(f"Could not update greeting buttons: {e}")
            return

    except Exception as e:
        logger.error(f"Error in button_callback: {e}", exc_info=True)
        await callback_query.answer(text="Ошибка при обработке кнопки", show_alert=True)


async def _show_analytics_page(callback_query, page_idx: int, context: ContextTypes.DEFAULT_TYPE, loading_msg=None) -> None:
    """Send a new message with analytics table when button is pressed.
    
    Pages are generated lazily — only when the user actually navigates to them.
    Creates a NEW message with the table, does NOT edit the chart message.
    If loading_msg is provided, it will be edited with the content instead of sending a new message.
    """
    from weekly_analytics import calculate_player_stats, fetch_match_details, get_analytics_pages

    generated = context.user_data.get('analytics_generated', set())
    pages = context.user_data.get('analytics_pages', [])
    chat_id = callback_query.message.chat_id

    # Determine if we need to generate pages (lazy loading)
    is_first_generation = page_idx not in generated or pages == [None, None]

    # Check if user has steam_id linked
    if is_first_generation:
        user = await asyncio.to_thread(get_user, callback_query.from_user.id)
        if not user or not user.get('steam_id'):
            await callback_query.answer(text="🎮 У вас не привязан аккаунт Steam. Используйте /link для привязки.", show_alert=True)
            if loading_msg:
                try:
                    await context.bot.delete_message(chat_id, loading_msg.message_id)
                except Exception:
                    pass
            return

    if page_idx < 0:
        logger.warning(f"Invalid page index: {page_idx}, pages: {len(pages)}")
        return

    # Handle empty pages array - need to generate
    if len(pages) == 0:
        is_first_generation = True

    # If not first generation and pages exist, validate page index
    if not is_first_generation and page_idx >= len(pages):
        logger.warning(f"Invalid page index: {page_idx}, pages: {len(pages)}")
        return

    # Ленивая генерация: если страница ещё не создана — генерируем все страницы
    if is_first_generation:
        # Вычисляем статистику и роль только при первом нажатии
        matches = context.user_data.get('analytics_matches', [])
        logger.info(f"Analytics: is_first_generation=True, matches={len(matches) if matches else 0}")

        # Check if matches exist
        if not matches:
            await callback_query.answer(text="❌ Нет данных матчей для аналитики", show_alert=True)
            if loading_msg:
                msg_id = loading_msg.message_id
                loading_msg = None  # Stop animation
                try:
                    await context.bot.delete_message(chat_id, msg_id)
                except Exception:
                    pass
            return

        # Fetch full details for matches that have match_id
        telegram_id = callback_query.from_user.id
        user = await asyncio.to_thread(get_user, telegram_id)
        if user and user.get('steam_id'):
            steam_id = user.get('steam_id')
            matches = await fetch_match_details(matches, steam_id)
            context.user_data['analytics_matches'] = matches
            logger.info(f"Analytics: after fetch_match_details, matches={len(matches)}")
        else:
            logger.info("Analytics: no steam_id, using original matches")

        stats = context.user_data.get('analytics_stats')
        role = context.user_data.get('analytics_role')

        # Always recalculate stats if None, or if role is set but stats is missing
        need_recalc = stats is None or role is None

        if not need_recalc and role and matches and len(matches) > 0:
            logger.info(f"Analytics: using cached role={role}")
        else:
            from weekly_analytics import detect_role_from_history
            logger.info("Analytics: detecting role and calculating stats")
            role = await detect_role_from_history(matches)
            # Wrap blocking calculate_player_stats in thread
            stats = await asyncio.to_thread(calculate_player_stats, matches)
            context.user_data['analytics_stats'] = stats
            context.user_data['analytics_role'] = role
            logger.info(f"Analytics: detected role={role}, stats keys={list(stats.keys()) if stats else 'None'}")

        # Ensure stats is valid before generating pages
        if not stats:
            await callback_query.answer(text="❌ Ошибка анализа статистики", show_alert=True)
            if loading_msg:
                msg_id = loading_msg.message_id
                loading_msg = None  # Stop animation
                try:
                    await context.bot.delete_message(chat_id, msg_id)
                except Exception:
                    pass
            return

        try:
            all_pages = await asyncio.to_thread(get_analytics_pages, role, stats)
            logger.info(f"Analytics: generated {len(all_pages)} pages")
        except Exception as e:
            logger.error(f"Error generating analytics pages: {e}", exc_info=True)
            await callback_query.answer(text=f"Ошибка: {e}", show_alert=True)
            if loading_msg:
                msg_id = loading_msg.message_id
                loading_msg = None  # Stop animation
                try:
                    await context.bot.delete_message(chat_id, msg_id)
                except Exception:
                    pass
            return
        pages = all_pages  # Replace placeholder with real pages
        generated = set(range(len(pages)))
        context.user_data['analytics_pages'] = pages
        context.user_data['analytics_generated'] = generated

    # Обновляем текущую страницу в user_data для корректной работы навигации
    context.user_data['analytics_page'] = page_idx

    page = pages[page_idx]
    text = page["text"]
    total_pages = len(pages)
    page_titles = [p.get("title", f"Стр. {i+1}") for i, p in enumerate(pages) if p]
    keyboard = _build_analytics_keyboard(page_idx, total_pages, generated, page_titles)

    try:
        chart_msg_id = context.user_data.get('analytics_chart_msg_id')

        # If a chart photo is already shown above the table, just update its caption.
        if chart_msg_id:
            keyboard = _build_analytics_table_keyboard(pages, generated, page_idx)
            try:
                await context.bot.edit_message_caption(
                    chat_id=chat_id,
                    message_id=chart_msg_id,
                    caption=text,
                    reply_markup=keyboard,
                    parse_mode="HTML",
                )
                if loading_msg:
                    _loading_msg_id = loading_msg.message_id
                    loading_msg = None  # Stop animation
                    try:
                        await context.bot.delete_message(chat_id, _loading_msg_id)
                    except Exception:
                        pass
                return
            except Exception as edit_err:
                err_str = str(edit_err).lower()
                if "not modified" in err_str:
                    return  # Same content, nothing to do
                logger.debug(f"Could not edit chart caption: {edit_err}")
                context.user_data.pop('analytics_chart_msg_id', None)

        # No chart photo yet: fall back to editing/sending a plain table message.
        keyboard = _build_analytics_keyboard(page_idx, total_pages, generated, page_titles)

        # Check if there's an existing table message to edit (for pagination between pages)
        existing_msg_id = context.user_data.get('analytics_table_msg_id')

        if existing_msg_id:
            # Try to edit the existing table message (for page navigation)
            try:
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=existing_msg_id,
                    text=text,
                    reply_markup=keyboard,
                    parse_mode="HTML"
                )
                return  # Successfully edited, done
            except Exception as edit_err:
                err_str = str(edit_err).lower()
                if "not modified" in err_str:
                    return  # Same content, nothing to do
                # Message was deleted or doesn't exist, clear the stored ID
                logger.debug(f"Could not edit existing table message: {edit_err}")
                context.user_data['analytics_table_msg_id'] = None

        if loading_msg:
            # Edit the loading message with the analytics table content
            msg_id = loading_msg.message_id
            loading_msg = None  # Stop animation
            try:
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=msg_id,
                    text=text,
                    reply_markup=keyboard,
                    parse_mode="HTML"
                )
                context.user_data['analytics_table_msg_id'] = msg_id
                job_queue = context.job_queue
                if job_queue:
                    schedule_delete(context.bot, chat_id, msg_id, 60, job_queue)
                return
            except Exception as edit_err:
                err_str = str(edit_err).lower()
                # Message was edited to photo, use edit_message_caption instead
                if "no text" in err_str or "caption" in err_str:
                    try:
                        await context.bot.edit_message_caption(
                            chat_id=chat_id,
                            message_id=msg_id,
                            caption=text,
                            reply_markup=keyboard,
                            parse_mode="HTML"
                        )
                        context.user_data['analytics_table_msg_id'] = msg_id
                        schedule_delete(context.bot, chat_id, msg_id, 60, context.job_queue)
                        return
                    except Exception:
                        pass
                logger.debug(f"Could not edit loading message: {edit_err}")
                # Fall through to send new message

        # Send a NEW message with the analytics table (first click or previous was deleted)
        if loading_msg:
            try:
                await context.bot.delete_message(chat_id, loading_msg.message_id)
            except Exception:
                pass
            loading_msg = None
        new_msg = await context.bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        # Store the new message_id for potential cleanup and pagination
        context.user_data['analytics_table_msg_id'] = new_msg.message_id
        # Schedule auto-delete after 60 seconds using job_queue
        job_queue = context.job_queue
        if job_queue:
            schedule_delete(context.bot, chat_id, new_msg.message_id, 60, job_queue)
        else:
            schedule_delete(context.bot, chat_id, new_msg.message_id, 60, None)
    except Exception as e:
        logger.error(f"Error sending analytics table message: {e}", exc_info=True)


async def set_digest_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set digest chat - установить текущий чат для дайджестов"""
    try:
        chat_id = update.effective_chat.id
        set_config("digest_chat_id", str(chat_id))
        set_config("alternate_digest_message_id", None)

        await update.message.reply_text(f"Чат {chat_id} установлен для дайджестов")
    except Exception as e:
        logger.error(f"set_digest_chat error: {e}")
        await menu_handler(update, context, allow_when_rate_limited=True)


async def digest_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Универсальный обработчик для команд digestnow, dotadigestnow, setdigestchat, setfissurechat"""
    try:
        chat = update.effective_chat
        chat_id = chat.id
        command = update.message.text.split()[0].lower().replace('/', '')

        if chat.type in ['group', 'supergroup', 'channel']:
            if await bot_can_delete(context.bot, chat_id):
                try:
                    await context.bot.delete_message(chat_id, update.message.message_id)
                except Exception as e:
                    logger.debug(f"Could not delete user message: {e}")

        if command == "setdigestchat":
            set_config("digest_chat_id", str(chat_id))
            set_config("alternate_digest_message_id", None)
            await context.bot.send_message(chat_id=chat_id, text=f"Чат {chat_id} установлен для дайджестов")
            return

        if command == "setfissurechat":
            set_config("fissure_chat_id", str(chat_id))
            await context.bot.send_message(chat_id=chat_id, text=f"Чат {chat_id} установлен для обновления тегов фиссуры")
            return

        if command == "setmmrchat":
            set_config("mmr_chat_id", str(chat_id))
            await context.bot.send_message(chat_id=chat_id, text=f"Чат {chat_id} установлен для обновления тегов MMR")
            return

        current_digest_chat = get_config('digest_chat_id')
        if not current_digest_chat:
            set_config("digest_chat_id", str(chat_id))

        if command == "digestnow":
            from digest import _digest_state_container, set_digest_type
            set_digest_type("0")
            set_config("alternate_digest_type", "0")
            set_config("alternate_digest_message_id", None)
            set_config("alternate_digest_last_created", "0")
            _digest_state_container.set_digest_data(None)  # Force fresh fetch
            _digest_state_container.set_dota_data(None)  # Force fresh fetch

            manual_context = ManualContext(context.application, context.bot)
            await alternate_digest_job(manual_context)

            msg = await context.bot.send_message(chat_id=chat_id, text="✅ Фиссура дайджест обновлён!")
            if chat.type in ['group', 'supergroup', 'channel']:
                schedule_delete(context.bot, chat_id, msg.message_id, 30, context.job_queue)

        elif command == "dotadigestnow":
            from digest import _digest_state_container, set_digest_type
            set_digest_type("1")
            set_config("alternate_digest_type", "1")
            set_config("alternate_digest_message_id", None)
            set_config("alternate_digest_last_created", "0")
            _digest_state_container.set_dota_data(None)  # Force fresh fetch

            manual_context = ManualContext(context.application, context.bot)
            await alternate_digest_job(manual_context)

            msg = await context.bot.send_message(chat_id=chat_id, text="✅ Dota дайджест для этого чата создан/обновлён.")
            if chat.type in ['group', 'supergroup', 'channel']:
                schedule_delete(context.bot, chat_id, msg.message_id, 30, context.job_queue)

    except Exception as e:
        logger.error(f"Error in digest_handler: {e}", exc_info=True)
        try:
            err_msg = await context.bot.send_message(chat_id=update.effective_chat.id, text="❌ Не удалось создать дайджест сейчас", reply_markup=main_menu())
            chat = update.effective_chat
            if chat and chat.type in ['group', 'supergroup', 'channel']:
                schedule_delete(context.bot, chat.id, err_msg.message_id, 30, context.job_queue)
        except Exception:
            pass


async def reset_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Сброс игры — только для администратора (ADMIN_CHAT_ID)."""
    logger.info("reset_game called")
    from config import settings

    ADMIN_CHAT_ID = getattr(settings, 'ADMIN_CHAT_ID', None)
    user_id = update.effective_user.id
    chat = update.effective_chat

    if not ADMIN_CHAT_ID or user_id != ADMIN_CHAT_ID:
        await context.bot.send_message(
            chat_id=chat.id,
            text="❌ Только администратор может сбрасывать игру",
            reply_markup=main_menu()
        )
        return

    success = reset_all_fissure_data()
    if success:
        msg = await context.bot.send_message(chat_id=chat.id, text="✅ Игра сброшена! Все начинают заново.")
    else:
        msg = await context.bot.send_message(chat_id=chat.id, text="❌ Не удалось сбросить игру")

    # Small delay to ensure message is visible
    await asyncio.sleep(0.1)

    if chat.type in ['group', 'supergroup', 'channel']:
        schedule_delete(context.bot, chat.id, msg.message_id, 30, context.job_queue)


async def recent_rolls_handler(request):
    """Public API: returns last 50 fissure rolls as JSON (for the website widget)."""
    try:
        from bot_utils import get_recent_rolls
        data = get_recent_rolls(50)
        resp = web.Response(text=json.dumps(data, ensure_ascii=False), content_type="application/json")
        resp.headers['Access-Control-Allow-Origin'] = '*'
        resp.headers['Access-Control-Allow-Methods'] = 'GET, OPTIONS'
        resp.headers['Access-Control-Allow-Headers'] = 'Content-Type'
        resp.headers['Cache-Control'] = 'public, max-age=30, stale-while-revalidate=30'
        return resp
    except Exception as e:
        logger.error(f"recent_rolls_handler error: {e}")
        return web.Response(text=json.dumps({"error": str(e)}), status=500)


async def api_options_handler(request):
    """Handle CORS preflight OPTIONS requests for API routes."""
    resp = web.Response(status=204)
    resp.headers['Access-Control-Allow-Origin'] = '*'
    resp.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    resp.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    return resp


async def top_mmr_handler(request):
    """Public API: returns top MMR players as JSON (for the website widget).
    
    Сначала пытаемся получить недельный топ (как команда /topmmr в боте),
    если пуст — возвращаем топ по общему MMR.
    """
    from database import get_dota_mmr_top, get_dota_week_top_from_db
    try:
        top_users = await asyncio.to_thread(get_dota_week_top_from_db, 50)
        if not top_users or len(top_users) == 0:
            top_users = await asyncio.to_thread(get_dota_mmr_top, 50)

        def _safe_username(u):
            name = u.get("username") or "Unknown"
            return name[:12] if len(name) > 12 else name

        data = [{"username": _safe_username(u), "mmr": u.get("mmr", 0), "rank_tier": u.get("rank_tier", 0), "week_games": u.get("week_games", 0), "week_wins": u.get("week_wins", 0)} for u in top_users]
        resp = web.Response(text=json.dumps(data, ensure_ascii=False), content_type="application/json")
        resp.headers['Access-Control-Allow-Origin'] = '*'
        resp.headers['Access-Control-Allow-Methods'] = 'GET, OPTIONS'
        resp.headers['Access-Control-Allow-Headers'] = 'Content-Type'
        resp.headers['Cache-Control'] = 'public, max-age=30, stale-while-revalidate=30'
        return resp
    except Exception as e:
        logger.error(f"top_mmr_handler error: {e}")
        return web.Response(text=json.dumps({"error": str(e)}), status=500)


async def obs_last5_handler(request):
    """Public API: returns last 5 matches as transparent PNG for OBS/website.
    
    Query params:
        steam_id: Steam ID64
        telegram_id: Telegram user ID (resolved to steam_id)
        force: "true" to bypass cache and regenerate
    """
    from obs_widget import generate_obs_widget, get_default_steam_id, get_steam_id_from_telegram
    try:
        steam_id = request.query.get("steam_id")
        telegram_id = request.query.get("telegram_id")
        force = request.query.get("force", "false").lower() == "true"

        if not steam_id and telegram_id:
            steam_id = await get_steam_id_from_telegram(int(telegram_id))

        if not steam_id:
            logger.warning("obs_last5_handler: no steam_id/telegram_id provided, trying default...")
            steam_id = await get_default_steam_id()
            if steam_id:
                logger.info("obs_last5_handler: using default steam_id=%s", steam_id)

        if not steam_id:
            logger.error("obs_last5_handler: no steam_id available and no default configured")
            return web.Response(
                text="Missing steam_id or telegram_id. Set ?steam_id=..., ?telegram_id=..., or OBS_WIDGET_STEAM_ID in .env",
                status=400,
            )

        data = await generate_obs_widget(int(steam_id), limit=5, force=force)
        if not data:
            return web.Response(
                text="No matches or widget generation failed",
                status=204,
            )

        resp = web.Response(body=data, content_type="image/png")
        resp.headers['Cache-Control'] = 'public, max-age=30, stale-while-revalidate=30'
        return resp
    except Exception as e:
        logger.error(f"obs_last5_handler error: {e}")
        return web.Response(text=str(e), status=500)


@rate_limit(tokens=1)
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show stats — свой или чужой профиль: /profile или /profile @username"""
    logger.info(f"User {update.effective_user.id} called stats")

    chat_id = update.effective_chat.id
    chat_type = update.effective_chat.type

    loading_msg = None

    if chat_type in ['group', 'supergroup', 'channel']:
        if await bot_can_delete(context.bot, chat_id):
            user_msg_id = update.message.message_id
            try:
                await context.bot.delete_message(chat_id, user_msg_id)
            except Exception as e:
                logger.debug(f"Could not delete user message: {e}")

    try:
        await delete_last_bot_message(context.bot, chat_id, update.effective_user.id)
    except Exception as e:
        logger.debug(f"Could not delete last bot message: {e}")

    try:
        target_user, viewing_other = await _resolve_profile_target(update, context)
        if target_user is None:
            return

        user_id = target_user.get("telegram_id") or update.effective_user.id
        try:
            loading_msg = await context.bot.send_message(
                chat_id=chat_id,
                text="<b>🪝Хукаю...</b>",
                parse_mode="HTML"
            )
        except Exception as e:
            logger.debug(f"Could not send loading message: {e}")

        week_games = 0
        week_wins = 0
        week_losses = 0
        winrate = 0

        if target_user.get('steam_id'):
            week_games = target_user.get('week_games') or 0
            week_wins = target_user.get('week_wins') or 0
            week_losses = week_games - week_wins
            winrate = round(week_wins / week_games * 100) if week_games > 0 else 0

        text = _build_profile_text(
            target_user,
            update.effective_user,
            viewing_other,
            week_games,
            week_wins,
            week_losses,
            winrate,
        )

        profile_banner = await _build_profile_progress_card(context.bot, target_user)
        if profile_banner is None:
            profile_banner = await _resolve_profile_banner(target_user)
        profile_banner_url = profile_banner

        result_msg = await context.bot.send_photo(
            chat_id=update.effective_chat.id,
            photo=profile_banner_url,
            caption=text,
            parse_mode="HTML",
            reply_markup=main_menu()
        )
        logger.info(f"stats: profile card sent uid={target_user.get('telegram_id')} week_games={week_games} week_wins={week_wins} msg_id={result_msg.message_id}")

        if loading_msg:
            try:
                await context.bot.delete_message(chat_id, loading_msg.message_id)
            except Exception:
                pass

        set_last_bot_message(chat_id, user_id, result_msg.message_id)
        schedule_delete(context.bot, chat_id, result_msg.message_id, 30, context.job_queue)
        update_last_message_id(user_id, result_msg.message_id)

    except TimeoutError as e:
        logger.error(f"Timeout in stats: {e}", exc_info=True)
        try:
            result_msg = await context.bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode="HTML",
                reply_markup=main_menu()
            )
            set_last_bot_message(chat_id, update.effective_user.id, result_msg.message_id)
        except Exception:
            pass
    except Exception as e:
        logger.error(f"Error in stats: {e}\n{traceback.format_exc()}")
        if loading_msg:
            try:
                await context.bot.delete_message(chat_id, loading_msg.message_id)
            except Exception:
                pass
        if "Timed out" not in str(e):
            try:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"❌ Ошибка: <code>{e}</code>",
                    parse_mode="HTML"
                )
            except Exception:
                pass


async def _resolve_profile_target(update: Update, context: ContextTypes.DEFAULT_TYPE) -> tuple[dict | None, bool]:
    chat_id = update.effective_chat.id
    target_user = None
    viewing_other = False

    if context.args and context.args[0]:
        target_username = " ".join(context.args).lstrip("@")
        if target_username:
            target_user = await asyncio.to_thread(get_user_by_username, target_username)
            if not target_user:
                msg = await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"❌ Игрок @{target_username} не найден"
                )
                schedule_delete(context.bot, chat_id, msg.message_id, 15, context.job_queue)
                return None, False
            viewing_other = True

    if not target_user:
        user_obj = update.effective_user
        username = user_obj.username or user_obj.first_name or f"Player{user_obj.id}"
        target_user = await asyncio.to_thread(get_user, user_obj.id, username)

    return target_user, viewing_other


async def _fetch_last_10_balls(steam_id: int, week_games: int) -> str:
    """[DEPRECATED] Kept for backwards compatibility, no longer used in profile."""
    return ""


def _build_profile_text(
    target_user: dict,
    effective_user,
    viewing_other: bool,
    week_games: int,
    week_wins: int,
    week_losses: int,
    winrate: int,
) -> str:
    if viewing_other:
        target_id = target_user.get('telegram_id', 0)
        _uname = target_user.get('username')
        if not _uname or _uname == "Unknown":
            _uname = target_user.get('steam_nickname')
        target_name = _uname or 'Unknown'
    else:
        target_id = effective_user.id
        target_name = effective_user.username or effective_user.first_name
    display_username = make_clickable(target_name, target_id)

    steam_id = target_user.get('steam_id')

    if steam_id:
        text = (
            f"👑 {display_username} "
            f"🔗 <a href=\"https://steamcommunity.com/profiles/{steam_id}\">Steam</a> "
            f"🔗 <a href=\"https://www.dotabuff.com/players/{steam_id}\">DotaBuff</a>"
        )
    else:
        text = f"👑 {display_username}"

    text += f"\n\n🍆 Фиссура: {target_user.get('fissure', 0):.1f} см\n🎲 Броски: {target_user.get('total_rolls', 0)} 🍀Стрик: {target_user.get('current_streak', 0)}/{target_user.get('best_streak', 0)}"

    if steam_id:
        text += f"\n\n🎮 Dota за неделю:\n📊 {week_wins}W • {week_losses}L • WR {winrate}%"

    mvp_count = target_user.get('weekly_mvp') or 0
    top2_count = target_user.get('weekly_top2') or 0
    top3_count = target_user.get('weekly_top3') or 0
    if mvp_count or top2_count or top3_count:
        text += "\n\n✨ <b>Награды недели</b>"
        if mvp_count:
            text += f"\n🏆 MVP ×<b>{mvp_count}</b>"
        if top2_count:
            text += f"\n🥈 ТОП 2 ×<b>{top2_count}</b>"
        if top3_count:
            text += f"\n🥉 ТОП 3 ×<b>{top3_count}</b>"

    # Keep tags as the final section of the text profile.
    tags_text = format_user_tags(target_user.get('telegram_id'))
    if tags_text:
        text += f"\n\n🏷️ <b>Теги</b>\n{tags_text}"

    return text


async def _resolve_profile_banner(target_user: dict) -> str | io.BytesIO:
    logger.info(f"_resolve_profile_banner called uid={target_user.get('telegram_id')}")
    return get_banner_path("profile")


async def _build_profile_progress_card(bot, target_user: dict) -> io.BytesIO | None:
    """Карточка прогресса ЗВАНИЙ для /profile.

    Возвращает io.BytesIO с PNG либо None — тогда stats() откатывается на
    прежний график/баннер (_resolve_profile_banner). Никакие исключения наружу.
    """
    telegram_id = target_user.get("telegram_id")
    steam_id = target_user.get("steam_id")
    try:
        from dota_mmr import generate_profile_card, get_week_top_heroes_async
        from tags import get_user_tags

        avatar_url = await resolve_avatar_url_for_card(
            bot,
            telegram_id=telegram_id,
            steam_id=steam_id,
            db_avatar=target_user.get("avatar"),
            fetch_steam=False,
        )

        top_heroes = []
        if steam_id:
            try:
                top_heroes = await asyncio.wait_for(
                    get_week_top_heroes_async(steam_id, top_k=3),
                    timeout=12.0
                )
            except Exception as e:
                logger.debug(f"profile card heroes skipped uid={telegram_id}: {e}")

        tags = []
        achievements = {}
        if telegram_id:
            try:
                tags = await asyncio.to_thread(get_user_tags, telegram_id)
                from achievements import get_user_achievements
                achievements = await asyncio.to_thread(get_user_achievements, telegram_id)
                logger.debug(f"profile card: got tags and awards for uid={telegram_id}")
            except Exception as e:
                logger.debug(f"profile card tags skipped uid={telegram_id}: {e}")

        position = target_user.get("current_position")
        if not position and telegram_id:
            try:
                pos_result = await asyncio.to_thread(get_fissure_rank, telegram_id)
                if pos_result:
                    position = pos_result.get('rank') if isinstance(pos_result, dict) else pos_result
            except Exception as e:
                logger.debug(f"profile card rank skipped uid={telegram_id}: {e}")

        # F1/F2/F3 are reconciled exclusively by refresh_fissure_top_tags.
        # The profile is read-only here: assigning tags from a card caused
        # DB/config drift and visible tag flicker.

        card_bytes = await asyncio.wait_for(
            asyncio.to_thread(
                generate_profile_card,
                avatar_url=avatar_url,
                username=target_user.get("username"),
                steam_nickname=target_user.get("steam_nickname"),
                steam_id=steam_id,
                mmr=target_user.get("mmr") or 0,
                rank_tier=target_user.get("rank_tier") or 0,
                fissure=target_user.get("fissure") or 0.0,
                total_rolls=target_user.get("total_rolls") or 0,
                weekly_rolls=target_user.get("weekly_rolls") or 0,
                current_streak=target_user.get("current_streak") or 0,
                best_streak=target_user.get("best_streak") or 0,
                message_count=target_user.get("message_count") or 0,
                week_games=target_user.get("week_games") or 0,
                week_wins=target_user.get("week_wins") or 0,
                # Losses are not a persisted column for the weekly Dota
                # counter. Derive them from games - wins so profiles never
                # show a false 0L when wins exist.
                week_losses=max(0, (target_user.get("week_games") or 0) - (target_user.get("week_wins") or 0)),
                dota_total_games=target_user.get("dota_total_games") or 0,
                dota_wins=target_user.get("dota_wins") or 0,
                dota_losses=target_user.get("dota_losses") or 0,
                top_heroes=top_heroes,
                tags=tags,
                award_counts={
                    "weekly_mvp": target_user.get("weekly_mvp") or 0,
                    "weekly_top1": 1 if "weekly_top1" in tags else 0,
                    "weekly_top2": target_user.get("weekly_top2") or 0,
                    "weekly_top3": target_user.get("weekly_top3") or 0,
                    "F1": 1 if "F1" in tags else 0,
                    "F2": 1 if "F2" in tags else 0,
                    "F3": 1 if "F3" in tags else 0,
                    "admin_custom": 1 if "admin_custom" in tags else 0,
                },
                achievements=achievements,
                position=position,
            ),
            timeout=30.0
        )

        if not card_bytes:
            logger.info(f"Profile card returned None uid={telegram_id}, fallback to banner")
            return None

        buffer = io.BytesIO(card_bytes)
        buffer.name = "profile_card.png"
        logger.info(f"Profile card built uid={telegram_id} size={len(card_bytes)} bytes")
        return buffer
    except TimeoutError:
        logger.warning(f"Profile card timeout for uid={telegram_id}, fallback to banner")
        return None
    except Exception as e:
        logger.warning(f"Profile card failed for uid={telegram_id}: {type(e).__name__}: {e}")
        return None


@rate_limit(tokens=1)
async def top(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show top users"""
    logger.info(f"User {update.effective_user.id} called top")

    chat_id = update.effective_chat.id
    chat_type = update.effective_chat.type

    if chat_type in ['group', 'supergroup', 'channel']:
        if await bot_can_delete(context.bot, chat_id):
            user_msg_id = update.effective_message.message_id if update.effective_message else None
            if user_msg_id:
                try:
                    await context.bot.delete_message(chat_id, user_msg_id)
                except Exception as e:
                    logger.debug(f"Could not delete user message: {e}")

    try:
        await delete_last_bot_message(context.bot, chat_id, update.effective_user.id)
    except Exception as e:
        logger.debug(f"Could not delete last bot message: {e}")

    try:
        top_users, user_rank, user = await asyncio.gather(
            asyncio.to_thread(get_fissure_top, 15),
            asyncio.to_thread(get_fissure_rank, update.effective_user.id),
            asyncio.to_thread(get_user, update.effective_user.id, update.effective_user.username),
        )
        username = update.effective_user.username or update.effective_user.first_name

        if not top_users:
            text = "😶 Пока нет игроков. Будь первым!"
            result_msg = await context.bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_markup=main_menu()
            )
            set_last_bot_message(chat_id, update.effective_user.id, result_msg.message_id)
            update_last_message_id(update.effective_user.id, result_msg.message_id)
            return

        # Generate top banner with persisted winner data.
        winner = top_users[0]
        # Prefer the persisted avatar: it avoids an extra Telegram API request
        # on every /top invocation. Fall back to Telegram when no URL is stored.
        winner_telegram_id = winner.get('telegram_id')
        winner_avatar = winner.get('avatar')
        if not winner_avatar or not str(winner_avatar).startswith('http'):
            winner_avatar = None

        if winner_telegram_id and not winner_avatar:
            try:
                tg_avatar = await get_user_avatar_url(context.bot, winner_telegram_id)
                if tg_avatar:
                    winner_avatar = tg_avatar
                    logger.info(f"top: using Telegram avatar for user {winner_telegram_id}")
            except Exception as e:
                logger.debug(f"Could not get Telegram avatar for top user: {e}")

        winner_name = (winner.get('username') or winner.get('steam_nickname') or winner.get('first_name') or str(winner.get('telegram_id', 'Игрок'))).strip()
        winner_fissure = winner.get('fissure', 0)
        winner_rank_tier = winner.get('rank_tier', 0)

        # If still no avatar, use DEFAULT_AVATAR_URL
        if not winner_avatar:
            winner_avatar = DEFAULT_AVATAR_URL
            logger.info(f"top: using DEFAULT_AVATAR_URL for user {winner_telegram_id}")

        avatar_source = "steam" if winner.get('avatar') else ("telegram" if winner_avatar and winner_avatar != DEFAULT_AVATAR_URL else "default")
        logger.info(f"top: winner_avatar={str(winner_avatar)[:50] if winner_avatar else None}, avatar_source={avatar_source}, winner_name={winner_name}")

        try:
            from dota_mmr import generate_top_card
            card_cache_key = (
                "fissure", winner_avatar, winner.get('telegram_id'), winner_name,
                winner_fissure, winner_rank_tier,
            )
            banner_bytes = await asyncio.to_thread(
                get_cached_top_card,
                generate_top_card,
                card_cache_key,
                avatar_url=winner_avatar,
                username=winner_name,
                telegram_id=winner.get('telegram_id'),
                fissure=winner_fissure,
                rank_tier=winner_rank_tier,
                show_avatar=True
            )
            banner_url = io.BytesIO(banner_bytes) if banner_bytes else get_banner_path("top")
        except Exception as e:
            logger.warning(f"Could not generate top card: {e}")
            banner_url = get_banner_path("top")

        text = ""
        medals = {1: "🥇", 2: "🥈", 3: "🥉"}

        def get_emoji_num(n):
            if n is None or n == '?':
                return "?"
            emoji_digits = {'0': '0️⃣', '1': '1️⃣', '2': '2️⃣', '3': '3️⃣',
                           '4': '4️⃣', '5': '5️⃣', '6': '6️⃣', '7': '7️⃣',
                           '8': '8️⃣', '9': '9️⃣'}
            return ''.join(emoji_digits[d] for d in str(n))

        for i, user_top in enumerate(top_users, 1):
            raw_name = (user_top.get('username') or user_top.get('steam_nickname') or user_top.get('first_name') or str(user_top.get('telegram_id', 'Игрок'))).strip()
            name = raw_name[:12] if len(raw_name) > 12 else raw_name
            telegram_id = user_top.get('telegram_id')
            steam_id = user_top.get('steam_id')
            display = name[1:] if name.startswith('@') else name
            display_name = f'<b>{clickable_name(display, telegram_id, steam_id)}</b>'
            fissure = user_top.get('fissure', 0)
            medal = medals.get(i)
            if medal:
                text += f"{medal} {display_name} - {fissure:.1f} см\n"
            else:
                text += f"{get_emoji_num(i)} {display_name} - {fissure:.1f} см\n"

        user_fissure = user.get('fissure', 0) if user else 0
        clickable_username = make_clickable(username, update.effective_user.id)
        if user_rank:
            text += f"\n{get_emoji_num(user_rank)} <b>{clickable_username} - {user_fissure:.1f} см</b>"
        else:
            text += f"\n<b>{clickable_username} - {user_fissure:.1f} см</b>"

        text += "\n\n<b><a href=\"https://seredin999.onrender.com/fissure-logs\">📜 История бросков</a></b>"

        result_msg = await context.bot.send_photo(
            chat_id=chat_id,
            photo=banner_url,
            caption=text,
            parse_mode="HTML",
            reply_markup=main_menu()
        )
        set_last_bot_message(chat_id, update.effective_user.id, result_msg.message_id)
        schedule_delete(context.bot, chat_id, result_msg.message_id, 30, context.job_queue)
        update_last_message_id(update.effective_user.id, result_msg.message_id)

    except Exception as e:
        logger.error(f"Error in top: {e}", exc_info=True)
        try:
            msg = await context.bot.send_message("❌ Ошибка получения топа", reply_markup=main_menu(), chat_id=chat_id)
            schedule_delete(context.bot, update.effective_chat.id, msg.message_id, 30, context.job_queue)
        except Exception:
            pass


async def refreshmmr(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Принудительное обновление MMR топа"""
    await asyncio.to_thread(get_user, update.effective_user.id, update.effective_user.username)
    logger.info(f"User {update.effective_user.id} called refreshmmr")

    try:
        from database import update_dota_week_top_cache

        await update_all_mmr_job(context)
        update_dota_week_top_cache()

        await context.bot.send_message("✅ Топ MMR обновлён принудительно", chat_id=update.effective_chat.id)
    except Exception as e:
        logger.error(f"refreshmmr error: {e}")
        await context.bot.send_message(f"❌ Ошибка обновления: {e}", chat_id=update.effective_chat.id)

async def testtechies(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await asyncio.to_thread(get_user, update.effective_user.id, update.effective_user.username)
    from techies import handle_techies_event
    user = update.effective_user
    user_data = {
        "id": user.id,
        "first_name": user.first_name,
        "username": user.username,
        "fissure": 100.0
    }
    user_obj = type('User', (), {'id': user.id, 'first_name': user.first_name, 'username': user.username})()
    display_username = make_clickable(user.username or user.first_name or "Гость", user.id)
    import time
    await handle_techies_event(
        context.bot,
        update.effective_chat.id,
        user_data,
        user_obj,
        display_username,
        time.time(),
        None,
        lambda chat_id, msg_id: None,
        lambda: None,
        lambda uid, fissure, ts, growth: None,
        lambda uid, ts: None,
        context.job_queue,
        lambda uid, uname, growth, new_fissure, cascade: None
    )

@rate_limit(tokens=1)
async def topmmr(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Топ игроков по MMR за неделю"""
    logger.info(f"User {update.effective_user.id} called topmmr")

    from dota_mmr import mmr_to_rank_tier, rank_to_string

    user_obj = update.effective_user
    username = user_obj.username or user_obj.first_name
    chat_id = update.effective_chat.id

    # Delete user message in groups
    chat_type = update.effective_chat.type
    if chat_type in ['group', 'supergroup', 'channel']:
        if await bot_can_delete(context.bot, chat_id):
            try:
                await context.bot.delete_message(chat_id, update.effective_message.message_id if update.effective_message else None)
            except Exception as e:
                logger.debug(f"Could not delete user message: {e}")

    try:
        from database import get_dota_mmr_top, get_dota_week_top_from_db
        # Баннер по умолчанию используется, если генерация карточки не удалась.
        topmmr_banner_url = TOPMMR_BANNER_PATH

        # Пользователь и текущий топ — независимые чтения. Выполняем их
        # параллельно, чтобы не ждать два DB round-trip подряд.
        user, top_users = await asyncio.gather(
            asyncio.to_thread(get_user, update.effective_user.id),
            asyncio.to_thread(get_dota_week_top_from_db, 10),
        )

        # Если недельный топ пустой, используем общий MMR-топ только как
        # fallback. Оба вызова уже выполняются вне event loop.
        if not top_users:
            top_users = await asyncio.to_thread(get_dota_mmr_top, 10)

        # Find user's position
        user_pos = None
        for i, player in enumerate(top_users, 1):
            if player.get('telegram_id') == update.effective_user.id:
                user_pos = i
                break

        # If user not in top 10, get their actual rank
        if user_pos is None:
            user_pos = await asyncio.to_thread(get_dota_week_rank, update.effective_user.id)

        # Initialize user position variables
        user_is_in_top = False
        user_week_games = 0
        user_week_wins = 0
        user_username = ""

        if user:
            user_week_games = user.get('week_games') or 0
            user_week_wins = user.get('week_wins') or 0
            raw_user_name = user.get('username') or user.get('steam_nickname') or user.get('first_name')
            if raw_user_name and raw_user_name not in ("Unknown", "Неизвестный игрок") and len(str(raw_user_name).strip()) > 1:
                user_username = raw_user_name
            else:
                user_username = user.get('steam_nickname') or user.get('username') or user.get('first_name') or str(user.get('telegram_id', 'Игрок'))
            user_week_losses = user_week_games - user_week_wins

            # Check if user is already in the top list
            for player in top_users:
                if player.get('telegram_id') == user.get('telegram_id'):
                    user_is_in_top = True
                    break

        if not top_users:
            text = "🏆 Топ MMR за неделю\n\nПока нет данных об MMR игроков."
            try:
                await delete_last_bot_message(context.bot, chat_id, update.effective_user.id)
            except Exception as e:
                logger.debug(f"Could not delete last bot message: {e}")

            result_msg = await context.bot.send_photo(
                chat_id=update.effective_chat.id,
                photo=topmmr_banner_url,
                caption=text,
                parse_mode="HTML",
                reply_markup=main_menu()
            )
            set_last_bot_message(chat_id, update.effective_user.id, result_msg.message_id)
            schedule_delete(context.bot, chat_id, result_msg.message_id, 30, context.job_queue)
            return
        else:
            # Generate MMR top banner with persisted winner data.
            winner = top_users[0]
            # Prefer the persisted avatar to avoid a Telegram API request on
            # every /topmmr invocation. Fall back to Telegram when it is absent.
            winner_telegram_id = winner.get('telegram_id')
            winner_avatar = winner.get('avatar')
            if not winner_avatar or not str(winner_avatar).startswith('http'):
                winner_avatar = None
            if winner_telegram_id and not winner_avatar:
                try:
                    tg_avatar = await get_user_avatar_url(context.bot, winner_telegram_id)
                    if tg_avatar:
                        winner_avatar = tg_avatar
                        logger.info(f"topmmr: using Telegram avatar for user {winner_telegram_id}")
                except Exception as e:
                    logger.debug(f"Could not get Telegram avatar for topmmr user: {e}")

            # If still no avatar, use DEFAULT_AVATAR_URL
            if not winner_avatar:
                winner_avatar = DEFAULT_AVATAR_URL
                logger.info(f"topmmr: using DEFAULT_AVATAR_URL for user {winner_telegram_id}")

            raw_winner_name = winner.get('username') or winner.get('steam_nickname') or winner.get('first_name')
            winner_name = raw_winner_name or str(winner.get('telegram_id', 'Игрок'))
            winner_rank_tier = winner.get('rank_tier', 0)
            winner_week_games = winner.get('week_games') or 0
            winner_week_wins = winner.get('week_wins') or 0
            winner_week_losses = winner_week_games - winner_week_wins
            winner_wr = round(winner_week_wins / winner_week_games * 100) if winner_week_games > 0 else 0

            try:
                from dota_mmr import generate_start_card
                card_cache_key = (
                    "mmr", winner_avatar, winner.get('telegram_id'), winner_name,
                    winner_rank_tier, winner_week_wins, winner_week_losses,
                )
                banner_bytes = await asyncio.to_thread(
                    get_cached_top_card,
                    generate_start_card,
                    card_cache_key,
                    avatar_url=winner_avatar,
                    message_count=None,
                    username=winner_name,
                    steam_nickname=winner_name,
                    rank_tier=winner_rank_tier,
                    week_wins=winner_week_wins,
                    week_losses=winner_week_losses
                )
                topmmr_banner_url = io.BytesIO(banner_bytes) if banner_bytes else topmmr_banner_url
            except Exception as e:
                logger.warning(f"Could not generate MMR top card: {e}")

            # Build the top list text
            lines = []

            def get_emoji_num(n):
                if n is None or n == '?':
                    return "?"
                emoji_digits = {'0': '0️⃣', '1': '1️⃣', '2': '2️⃣', '3': '3️⃣',
                               '4': '4️⃣', '5': '5️⃣', '6': '6️⃣', '7': '7️⃣',
                               '8': '8️⃣', '9': '9️⃣'}
                return ''.join(emoji_digits[d] for d in str(n))

            for i, player in enumerate(top_users, 1):
                raw_uname = player.get('username') or player.get('steam_nickname') or player.get('first_name')
                if not raw_uname or raw_uname in ("None", "Unknown", "Неизвестный игрок") or len(raw_uname.strip()) <= 1:
                    raw_uname = player.get('username') or player.get('first_name') or str(player.get('telegram_id', 'Игрок'))
                username = raw_uname[:12] if len(raw_uname) > 12 else raw_uname
                rank_tier = player.get('rank_tier', 0)
                week_games = player.get('week_games') or 0
                week_wins = player.get('week_wins') or 0
                week_losses = week_games - week_wins

                # Format rank using helper function
                rank_str = rank_to_string(rank_tier)

                # Medal emoji
                medals = ["🥇", "🥈", "🥉"]
                if i <= 3:
                    medal = medals[i - 1]
                else:
                    medal = get_emoji_num(i)

                player_id = player.get('telegram_id')
                steam_id = player.get('steam_id')
                display_name = clickable_name(username, player_id, steam_id)

                rank_tier = player.get('rank_tier', 0)
                if rank_tier == 0 and week_games > 0:
                    mmr_val = player.get('mmr', 0)
                    if mmr_val and mmr_val > 0:
                        rank_tier = mmr_to_rank_tier(mmr_val)

                rank_str = rank_to_string(rank_tier)
                lines.append(f"{medal} <b>{display_name}</b> - {rank_str}")
                if week_games > 0:
                    wr = round((week_wins / week_games) * 100) if week_games > 0 else 0
                    lines.append(f" └ {week_wins}W • {week_losses}L • {wr}%")
                else:
                    lines.append(" └ Нет игр за неделю")

            top_text = "\n".join(lines)

            # Check if this is a digest chat - show normal top list like in private chat
            try:
                from database import get_config
                digest_chat_id = get_config('digest_chat_id')
                if str(chat_id) == str(digest_chat_id):
                    # In digest chat, we show the normal top list (same as private chat)
                    # The user's personal info will be added at the bottom below
                    pass
            except Exception as e:
                logger.debug(f"Could not process digest chat: {e}")

            # Add the current user's position (always show it at the bottom)
            if user and user_week_games > 0:
                user_wr = round((user_week_wins / user_week_games) * 100) if user_week_games > 0 else 0
                user_rank_tier = user.get('rank_tier', 0)
                if user_rank_tier == 0 and user_week_games > 0:
                    user_mmr = user.get('mmr', 0)
                    if user_mmr and user_mmr > 0:
                        user_rank_tier = mmr_to_rank_tier(user_mmr)
                user_rank_str = rank_to_string(user_rank_tier)
                user_display = clickable_name(user_username, user.get('telegram_id'), user.get('steam_id'))
                top_text += f"\n{get_emoji_num(user_pos)} <b>{user_display}</b> - {user_rank_str}\n"
                top_text += f" └ {user_week_wins}W • {user_week_losses}L • {user_wr}%"
            elif user and user_week_games == 0:
                user_rank_str = rank_to_string(user.get('rank_tier', 0))
                user_display = clickable_name(user_username, user.get('telegram_id'), user.get('steam_id'))
                user_pos_emoji = get_emoji_num(user_pos) if user_pos else "0️⃣"
                top_text += f"\n{user_pos_emoji} <b>{user_display}</b> - {user_rank_str}\n"
                top_text += "└ Нет игр за неделю"

            top_text += "\n\n<b><a href=\"https://seredin999.onrender.com/top-mmr\">🏆 Топ рангов на сайте</a></b>"

            # Delete previous bot message before sending new one
            try:
                await delete_last_bot_message(context.bot, chat_id, update.effective_user.id)
            except Exception as e:
                logger.debug(f"Could not delete last bot message: {e}")

            result_msg = await context.bot.send_photo(
                chat_id=update.effective_chat.id,
                photo=topmmr_banner_url,
                caption=top_text,
                parse_mode="HTML",
                reply_markup=main_menu()
            )
            add_bot_message(chat_id, user_obj.id, result_msg.message_id)
            set_last_bot_message(chat_id, user_obj.id, result_msg.message_id)
            schedule_delete(context.bot, chat_id, result_msg.message_id, 30, context.job_queue)
            update_last_message_id(user_obj.id, result_msg.message_id)

            # Small delay for message visibility
            await asyncio.sleep(0.1)

    except Exception as e:
        logger.error(f"Error in topmmr: {e}", exc_info=True)
        try:
            msg = await context.bot.send_message(
                chat_id=chat_id,
                text="❌ Ошибка получения топа",
                reply_markup=main_menu()
            )
            schedule_delete(context.bot, chat_id, msg.message_id, 30, context.job_queue)
        except Exception:
            try:
                msg = await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text="❌ Ошибка получения топа MMR",
                    reply_markup=main_menu()
                )
                schedule_delete(context.bot, update.effective_chat.id, msg.message_id, 30, context.job_queue)
            except Exception:
                pass


@rate_limit(tokens=1)
async def link(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Привязка Steam аккаунта по нику или Steam ID"""
    logger.info(f"User {update.effective_user.id} called link")

    chat_id = update.effective_chat.id

    # Try to get chat_type safely
    chat_type = 'private'
    if update.message and update.message.chat:
        chat_type = update.message.chat.type

    # Delete user message only in groups/channels
    if chat_type in ['group', 'supergroup', 'channel']:
        if update.message and await bot_can_delete(context.bot, chat_id):
            try:
                await context.bot.delete_message(chat_id, update.message.message_id)
            except Exception:
                pass

    args = context.args
    identifier = args[0] if args else None

    # Если есть аргумент - привязываем в фоне, чтобы не блокировать event loop
    if identifier:
        try:
            loading_msg = await context.bot.send_message(
                chat_id=chat_id,
                text="🪝 Привязываю аккаунт Dota 2…"
            )

            from dota_mmr import register_steam
            result = await asyncio.to_thread(register_steam, update.effective_user.id, identifier)

            # Удалить loading сообщение
            try:
                msg_id = loading_msg.message_id if loading_msg else None
                loading_msg = None  # Stop animation
                if msg_id:
                    await context.bot.delete_message(chat_id, msg_id)
            except Exception:
                pass

            # Delete previous bot message before sending new one
            try:
                await delete_last_bot_message(context.bot, chat_id, update.effective_user.id)
            except Exception as e:
                logger.debug(f"Could not delete last bot message: {e}")

            if result.get('success') and not result.get('private_profile'):
                # При закрытом профиле не запускаем бесполезное обновление MMR.
                try:
                    from dota_mmr import update_user_mmr
                    asyncio.create_task(asyncio.to_thread(update_user_mmr, update.effective_user.id))
                    logger.info(f"Scheduled MMR update for user {update.effective_user.id} after link")
                except Exception as e:
                    logger.debug(f"Could not schedule MMR update after link: {e}")

                try:
                    from weekly_analytics import generate_weekly_analytics
                    asyncio.create_task(generate_weekly_analytics(update.effective_user.id))
                    logger.info(f"Scheduled analytics preload for user {update.effective_user.id} after link")
                except Exception as e:
                    logger.debug(f"Could not schedule analytics preload: {e}")

            result_msg = await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=result.get('message'),
            )
            # Track this message for future deletion
            set_last_bot_message(chat_id, update.effective_user.id, result_msg.message_id)
            schedule_delete(context.bot, chat_id, result_msg.message_id, 30, context.job_queue)
            update_last_message_id(update.effective_user.id, result_msg.message_id)

            # Small delay to ensure message is visible
            await asyncio.sleep(0.1)
        except Exception as e:
            logger.error(f"Error in link: {e}", exc_info=True)
            msg = await context.bot.send_message(chat_id=update.effective_chat.id, text="❌ Ошибка привязки Dota аккаунта", reply_markup=main_menu())
            schedule_delete(context.bot, update.effective_chat.id, msg.message_id, 30, context.job_queue)
        return

    # Если нет аргумента - отправляем инструкцию
    # Delete previous bot message before sending new one
    try:
        await delete_last_bot_message(context.bot, chat_id, update.effective_user.id)
    except Exception as e:
        logger.debug(f"Could not delete last bot message: {e}")

    link_banner_url = get_banner_path("link")
    link_text = ("🦞 <b>Привязать Аккаунт Dota 2</b>\n\n"
    "Добавить в друзья → Ваш ID → копировать →\n"
    "<code>/link 347614947</code>\n\n"
    "Или ссылку на dotabuff →\n"
    "<code>/link https://ru.dotabuff.com/players/347614699</code>\n\n"
    "⚠️ в игре:\n"
    "Настройки → сообщество → настройки → общедоступная история матчей → включить")

    result_msg = await context.bot.send_photo(
        chat_id=update.effective_chat.id,
        photo=link_banner_url,
        caption=link_text,
        parse_mode='HTML',
        reply_markup=main_menu()
    )
    # Track this message for future deletion
    set_last_bot_message(chat_id, update.effective_user.id, result_msg.message_id)
    add_bot_message(chat_id, update.effective_user.id, result_msg.message_id)
    schedule_delete(context.bot, chat_id, result_msg.message_id, 30, context.job_queue)
    update_last_message_id(update.effective_user.id, result_msg.message_id)

    # Small delay to ensure message is visible
    await asyncio.sleep(0.1)

async def admin_unlink(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Административная команда: раз-prивязать Steam-аккаунт по Telegram username."""
    from bot_utils import _telegram_error_contains
    from config import settings
    from database import get_user_by_username

    ADMIN_CHAT_ID = getattr(settings, 'ADMIN_CHAT_ID', None)
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id

    if not ADMIN_CHAT_ID or user_id != ADMIN_CHAT_ID:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="❌ Только администратор может использовать эту команду",
            reply_markup=main_menu()
        )
        return

    args = context.args
    if not args or len(args) < 1:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Использование: /admin_unlink <telegram_username>\nПример: /admin_unlink Seredin999",
            reply_markup=main_menu()
        )
        return

    username = args[0].lstrip('@')  # Убираем @ если он есть

    result = await asyncio.to_thread(get_user_by_username, username)

    if not result:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"❌ Пользователь @{username} не найден в базе",
            reply_markup=main_menu()
        )
        return

    target_telegram_id = result.get('telegram_id')

    try:
        member = await context.bot.get_chat_member(chat_id, target_telegram_id)
        if member.status in ('left', 'kicked', 'banned'):
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"❌ Пользователь @{username} уже не состоит в этом чате",
                reply_markup=main_menu()
            )
            return
    except Exception as e:
        if _telegram_error_contains(e, "user not found", "chat not found", "kicked", "left"):
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"❌ Пользователь @{username} уже не состоит в этом чате",
                reply_markup=main_menu()
            )
            return
        logger.warning(f"admin_unlink: Error checking chat membership: {e}")

    steam_id = result.get('steam_id')
    if not steam_id:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"❌ У пользователя @{username} Steam-аккаунт не привязан",
            reply_markup=main_menu()
        )
        return

    from dota_mmr import admin_unlink_steam
    unlink_result = await asyncio.to_thread(admin_unlink_steam, steam_id)

    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=unlink_result.get('message'),
        reply_markup=main_menu()
    )

async def admin_tag(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from config import settings
    ADMIN_CHAT_ID = getattr(settings, 'ADMIN_CHAT_ID', None)
    user_id = update.effective_user.id

    if not ADMIN_CHAT_ID or user_id != ADMIN_CHAT_ID:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="❌ Только администратор может использовать эту команду",
            reply_markup=main_menu()
        )
        return

    args = context.args
    if not args or len(args) < 2:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Использование: /tag <@username|telegram_id> <тип>\n"
                 "Типы: weekly_mvp, weekly_top1, weekly_top2, weekly_top3, F1, F2, F3, admin_custom, VIP\n"
                 "Пример: /tag @user weekly_top1\n"
                 "VIP: добавляет в список VIP и пытается назначить Telegram-тег",
            reply_markup=main_menu()
        )
        return

    target = args[0].lstrip('@')
    tag_type = args[1]

    if tag_type not in TAG_TYPES:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"❌ Неизвестный тип тега: {tag_type}\n"
                 f"Доступные: {', '.join(TAG_TYPES.keys())}",
            reply_markup=main_menu()
        )
        return

    target_user = None
    if target.isdigit():
        target_user = get_user(int(target))
    else:
        target_user = get_user_by_username(target)

    if not target_user:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"❌ Пользователь {target} не найден",
            reply_markup=main_menu()
        )
        return

    target_id = target_user.get('telegram_id')
    chat_id = update.effective_chat.id

    if tag_type == "VIP":
        from database import add_vip_user
        db_added = await asyncio.to_thread(add_vip_user, target_id)
        tag_added = await add_user_tag(target_id, "VIP", bot=context.bot, chat_id=chat_id)
        if db_added and tag_added:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"✅ VIP тег выдан пользователю {target}\n🎉 Пользователь теперь имеет статус VIP",
                reply_markup=main_menu()
            )
        elif db_added:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"✅ Пользователь {target} добавлен в VIP список\n⚠️ Telegram-тег не удалось применить",
                reply_markup=main_menu()
            )
        else:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"❌ Ошибка при выдаче VIP для {target}",
                reply_markup=main_menu()
            )
        return

    ok = await add_user_tag(target_id, tag_type, bot=context.bot, chat_id=chat_id)
    label = TAG_DISPLAY.get(tag_type, TAG_TYPES.get(tag_type, tag_type))
    if ok:
        text = f"✅ Тег «{label}» выдан пользователю {target}"
    else:
        text = (
            f"❌ Не удалось выдать тег «{label}» пользователю {target}. "
            "Проверьте, что бот администратор с правом «Управлять тегами»."
        )
    await context.bot.send_message(
        chat_id=chat_id,
        text=text,
        reply_markup=main_menu()
    )

async def admin_untag(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from config import settings
    ADMIN_CHAT_ID = getattr(settings, 'ADMIN_CHAT_ID', None)
    user_id = update.effective_user.id

    if not ADMIN_CHAT_ID or user_id != ADMIN_CHAT_ID:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="❌ Только администратор может использовать эту команду",
            reply_markup=main_menu()
        )
        return

    args = context.args
    if not args or len(args) < 2:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Использование: /untag <@username|telegram_id> <тип>\n"
                 "Типы: weekly_mvp, weekly_top2, weekly_top3, F1, F2, F3, admin_custom, VIP\n"
                 "Пример: /untag @user weekly_mvp",
            reply_markup=main_menu()
        )
        return

    target = args[0].lstrip('@')
    tag_type = args[1]

    if tag_type not in TAG_TYPES:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"❌ Неизвестный тип тега: {tag_type}\n"
                 f"Доступные: {', '.join(TAG_TYPES.keys())}",
            reply_markup=main_menu()
        )
        return

    target_user = None
    if target.isdigit():
        target_user = get_user(int(target))
    else:
        target_user = get_user_by_username(target)

    if not target_user:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"❌ Пользователь {target} не найден",
            reply_markup=main_menu()
        )
        return

    target_id = target_user.get('telegram_id')
    chat_id = update.effective_chat.id

    if tag_type == "VIP":
        from database import remove_vip_user
        list_removed = await asyncio.to_thread(remove_vip_user, target_id)
        tag_removed = await remove_user_tag(target_id, "VIP", bot=context.bot, chat_id=chat_id)
        if list_removed and tag_removed:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"✅ VIP снят с пользователя {target}",
                reply_markup=main_menu()
            )
        elif list_removed or tag_removed:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"✅ VIP удалён из профиля/списка для {target}\n⚠️ Telegram-тег не удалось снять",
                reply_markup=main_menu()
            )
        else:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"❌ Ошибка при удалении VIP для {target}",
                reply_markup=main_menu()
            )
        return

    ok = await remove_user_tag(target_id, tag_type, bot=context.bot, chat_id=chat_id)
    label = TAG_DISPLAY.get(tag_type, TAG_TYPES.get(tag_type, tag_type))
    if ok:
        text = f"✅ Тег «{label}» снят с пользователя {target}"
    else:
        text = (
            f"❌ Не удалось снять тег «{label}» с пользователя {target}. "
            "Проверьте, что бот администратор с правом «Управлять тегами»."
        )
    await context.bot.send_message(
        chat_id=chat_id,
        text=text,
        reply_markup=main_menu()
    )


async def vip_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выдача VIP тега пользователю"""
    from config import settings
    ADMIN_CHAT_ID = getattr(settings, 'ADMIN_CHAT_ID', None)
    user_id = update.effective_user.id

    if not ADMIN_CHAT_ID or user_id != ADMIN_CHAT_ID:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="❌ Только администратор может использовать эту команду",
            reply_markup=main_menu()
        )
        return

    args = context.args
    if not args or len(args) < 1:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Использование: /vip <@username|telegram_id>\n"
                 "Пример: /vip @user\n"
                 "Выдаёт VIP тег пользователю",
            reply_markup=main_menu()
        )
        return

    target = args[0].lstrip('@')
    target_user = None
    if target.isdigit():
        target_user = get_user(int(target))
    else:
        target_user = get_user_by_username(target)

    if not target_user:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"❌ Пользователь {target} не найден",
            reply_markup=main_menu()
        )
        return

    target_id = target_user.get('telegram_id')
    chat_id = update.effective_chat.id

    added = await add_user_tag(target_id, "VIP", bot=context.bot, chat_id=chat_id)

    from database import add_vip_user
    db_added = add_vip_user(target_id)

    if added and db_added:
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"✅ VIP тег выдан пользователю {target}\n"
                 f"🎉 Пользователь теперь имеет статус VIP",
            reply_markup=main_menu()
        )
    elif db_added:
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"✅ VIP добавлен в список для {target}\n"
                 f"⚠️ Тег нужно установить вручную в Telegram",
            reply_markup=main_menu()
        )
    else:
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"❌ Ошибка при выдаче VIP для {target}",
            reply_markup=main_menu()
        )


async def reset_tags_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Сброс всех конфигов тегов (для переинициализации после ручного удаления)"""
    from config import settings
    ADMIN_CHAT_ID = getattr(settings, 'ADMIN_CHAT_ID', None)
    user_id = update.effective_user.id

    if not ADMIN_CHAT_ID or user_id != ADMIN_CHAT_ID:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="❌ Только администратор может использовать эту команду",
            reply_markup=main_menu()
        )
        return

    from database import set_config
    tag_configs = [
        'current_F1_telegram_id',
        'current_F2_telegram_id',
        'current_F3_telegram_ids',
        'current_mmr_top1_telegram_id',
        'current_mmr_top2_telegram_id',
        'current_mmr_top3_telegram_id',
    ]
    for key in tag_configs:
        set_config(key, "")

    # Также чистим VIP-список если нужно (опционально)
    # set_config('vip_users_list', "[]")

    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="✅ Конфигурации тегов сброшены. При следующем обновлении теги будут выданы заново.",
        reply_markup=main_menu()
    )
    logger.info(f"admin: reset_tags_command executed by {user_id}")


async def tags_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    target = None
    if context.args and len(context.args) >= 1:
        raw = context.args[0].lstrip('@')
        if raw.isdigit():
            target = get_user(int(raw))
        else:
            target = get_user_by_username(raw)

    if not target:
        target = get_user(update.effective_user.id)

    if not target:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="❌ Пользователь не найден",
            reply_markup=main_menu()
        )
        return

    name = target.get('username') or target.get('steam_nickname') or target.get('first_name') or str(target.get('telegram_id'))
    tags_text = format_user_tags(target.get('telegram_id'))
    if tags_text:
        text = f"🏷️ Теги {name}:\n{tags_text}"
    else:
        text = f"🏷️ У {name} нет тегов"

    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=text,
        reply_markup=main_menu()
    )

async def info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Информация с кнопкой перехода на патч заметки"""
    await asyncio.to_thread(get_user, update.effective_user.id, update.effective_user.username)
    logger.info(f"Пользователь {update.effective_user.id} вызвал info")

    chat_id = update.effective_chat.id

    # Попытка безопасно получить тип чата
    chat_type = 'private'
    if update.message and update.message.chat:
        chat_type = update.message.chat.type

    # Удаляем сообщение пользователя только в группах/каналах
    if chat_type in ['group', 'supergroup', 'channel']:
        if update.message and await bot_can_delete(context.bot, chat_id):
            try:
                await context.bot.delete_message(chat_id, update.message.message_id)
            except Exception:
                pass

    # Удаляем последнее сообщение бота сразу
    try:
        await delete_last_bot_message(context.bot, chat_id, update.effective_user.id)
    except Exception as e:
        logger.debug(f"Не удалось удалить последнее сообщение бота: {e}")

    # URL баннера
    info_banner_url = get_banner_path("info_banner")

    # Создаем inline клавиатуру с кнопкой
    keyboard = [[
        InlineKeyboardButton("📄 Информация о боте и патчах", url="https://seredin999.onrender.com/patch-fissure")
    ]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    # Get resource stats text
    from analytics_dashboard import generate_dashboard_text
    resource_text = generate_dashboard_text()

    # Отправляем фото с баннером и кнопкой
    result_msg = await context.bot.send_photo(
        chat_id=chat_id,
        photo=info_banner_url,
        caption=resource_text,
        reply_markup=reply_markup,
        parse_mode="HTML"
    )

    # Отслеживаем это сообщение для будущего удаления
    set_last_bot_message(chat_id, update.effective_user.id, result_msg.message_id)
    add_bot_message(chat_id, update.effective_user.id, result_msg.message_id)
    schedule_delete(context.bot, chat_id, result_msg.message_id, 30, context.job_queue)
    update_last_message_id(update.effective_user.id, result_msg.message_id)

    # Небольшая задержка для обеспечения видимости сообщения
    await asyncio.sleep(0.1)

async def menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, allow_when_rate_limited: bool = False) -> None:
    """Menu button handler - sends new content, deletes user message and old bot message immediately"""
    # Skip if this is a callback query (handled by button_callback)
    if update.callback_query:
        return

    try:
        # Skip if rate limited (but allow override for error fallback)
        if not allow_when_rate_limited and is_rate_limited():
            logger.warning("Skipping menu_handler due to rate limit")
            return

        # Check if we have a message - if not, this is not a text message update
        if not update.message:
            logger.warning("menu_handler: no message in update")
            return

        if not update.message.text:
            logger.warning(f"menu_handler: no text in message, msg={update.message}")
            return

        text = update.message.text.strip()
        logger.info(f"menu_handler: text='{text}' (len={len(text)})")

        # Increment message count only in digest chat
        try:
            from database import get_config
            digest_chat_id = get_config('digest_chat_id')

            # Skip if not in digest chat
            if str(update.effective_chat.id) != str(digest_chat_id):
                logger.info("menu_handler: skipping message_count (not in digest chat)")
            else:
                user_id = update.effective_user.id
                db_user = await asyncio.to_thread(get_user, user_id)
                if not db_user:
                    telegram_username = update.effective_user.username
                    first_name = update.effective_user.first_name
                    fallback_name = telegram_username or first_name or f"Player{user_id}"
                    db = Database()
                    db.register_user(user_id, fallback_name, first_name, source="start")
                    db_user = await asyncio.to_thread(get_user, user_id)
                    logger.info(f"Created new user {user_id} for message counting")

                if db_user:
                    current_count = db_user.get('message_count', 0)
                    new_count = current_count + 1
                    logger.info(f"message_count: {user_id} old={current_count} new={new_count}, user exists: {db_user is not None}")
                    updates = {'message_count': new_count, 'in_chat': True}
                    # Обновляем username только если есть telegram_username и он отличается;
                    # или если username пуст, а есть first_name — используем first_name как fallback
                    current_username = db_user.get('username')
                    new_telegram_username = update.effective_user.username
                    if new_telegram_username and new_telegram_username != current_username:
                        updates['username'] = new_telegram_username
                    elif current_username is None and update.effective_user.first_name:
                        updates['username'] = update.effective_user.first_name
                    # Сохраняем в БД сразу чтобы данные не терялись при деплое
                    await asyncio.to_thread(update_user_fields_batch, user_id, updates, save_to_db=True)
                    logger.info(f"Cached message_count for {user_id}: {new_count}")

                    try:
                        from achievements import ACHIEVEMENTS as _AH
                        from achievements import check_and_award as _aha_check
                        _awarded = await asyncio.to_thread(_aha_check, user_id, 'message_count', new_count)
                        if _awarded:
                            _labels = ", ".join(_AH[k]["label"] for k in _awarded)
                            _nick = update.effective_user.username or update.effective_user.full_name or f"id{user_id}"
                            _mention = make_clickable(_nick, user_id)
                            _text = f"🏆 {_mention} получил(а) достижение: {_labels}!"
                            _banner = await asyncio.to_thread(
                                generate_achievement_banner, _awarded[0], _AH[_awarded[0]]["label"], _nick
                            )
                            try:
                                await context.bot.send_photo(
                                    chat_id=digest_chat_id,
                                    photo=_banner or open(Path("assets/achievements/%s.webp" % _awarded[0]), "rb"),
                                    caption=_text,
                                    parse_mode="HTML",
                                )
                            except Exception:
                                await context.bot.send_message(
                                    chat_id=digest_chat_id,
                                    text=_text,
                                    parse_mode="HTML",
                                )
                    except Exception as _e:
                        logger.warning(f"achievements: message_count check failed: {_e}")
        except Exception as e:
            logger.error(f"Error updating message_count: {e}")

        if not update.message:
            logger.warning("menu_handler: no message in update")
            return

        if not update.message.text:
            logger.warning(f"menu_handler: no text in message, msg={update.message}")
            return

        text = update.message.text.strip()

        menu_buttons = {
            "🎲 Ролл Фиссуры": "🎲 Ролл Фиссуры",
            "👤 Профиль": "👤 Профиль",
            "🏆 Топ Фиссур": "🏆 Топ Фиссур",
            "🏆 Топ MMR": "🏆 Топ MMR",
            "🔎 Аналитика": "🔎 Аналитика",
            "🔑 Привязать Аккаунт": "🔑 Привязать Аккаунт",
            "🎮 Поиск пати": "🎮 Поиск пати"
        }

        logger.info(f"menu_handler: text='{text}' (len={len(text)}), menu_buttons_keys={list(menu_buttons.keys())}")

        # Try exact match first
        button_found = menu_buttons.get(text)

        # If not exact, try case-insensitive match
        if not button_found:
            text_lower = text.lower()
            for btn_key, btn_full in menu_buttons.items():
                if btn_key.lower() == text_lower:
                    button_found = btn_full
                    break

        # If still not exact, try startswith match (case-insensitive)
        if not button_found and len(text) >= 3:
            text_lower = text.lower()
            for btn_key, btn_full in menu_buttons.items():
                # Only match if text starts with button key
                if text_lower.startswith(btn_key.lower()):
                    button_found = btn_full
                    break

        if not button_found:
            logger.info(f"menu_handler: text NOT recognized, skipping: '{text}' (len={len(text)})")
            logger.info(f"menu_handler: available buttons: {list(menu_buttons.keys())}")
            return

        logger.info(f"menu_handler: MATCH FOUND - '{button_found}'")

        chat_id = update.effective_chat.id
        chat_type = update.effective_chat.type
        user_id = update.effective_user.id

        logger.info(f"User {user_id} pressed button: {button_found} in chat type: {chat_type}")



        # Delete user's message only in groups/channels (non-blocking, don't wait)
        if chat_type in ['group', 'supergroup', 'channel']:
            user_msg_id = update.message.message_id if update.message else None
            asyncio.create_task(delete_user_message_safely(context.bot, chat_id, user_msg_id))

        # Delete last bot message immediately (non-blocking)
        asyncio.create_task(delete_last_bot_message_safe(context.bot, chat_id, user_id))

        # Call the appropriate function
        if button_found == "🎲 Ролл Фиссуры":
            await fissure(update, context)
        elif button_found == "👤 Профиль":
            logger.info(f"menu_handler: calling stats for user {user_id}")
            await stats(update, context)
        elif button_found == "🏆 Топ Фиссур":
            await top(update, context)
        elif button_found == "🏆 Топ MMR":
            await topmmr(update, context)
        elif button_found == "🔎 Аналитика":
            await analyze_command(update, context)
        elif button_found == "🔑 Привязать Аккаунт":
            await link(update, context)
        elif button_found == "🎮 Поиск пати":
            await party_command(update, context)

    except Exception as e:
        logger.error(f"Error in menu_handler: {e}", exc_info=True)


async def delete_user_message_safely(bot, chat_id, msg_id):
    """Delete user message safely without blocking"""
    try:
        await bot.delete_message(chat_id, msg_id)
        logger.info(f"Deleted user message: {msg_id}")
    except Exception as e:
        logger.debug(f"Could not delete user message {msg_id}: {e}")


async def delete_last_bot_message_safe(bot, chat_id, user_id):
    """Delete last bot message safely without blocking"""
    try:
        await delete_last_bot_message(bot, chat_id, user_id)
    except Exception as e:
        logger.debug(f"Could not delete last bot message for user {user_id}: {e}")


async def health_check(request):
    """Health check endpoint"""
    return web.Response(text="Bot is working", status=200)


async def steam_debug(request):
    """Debug endpoint to check steam_id issues"""
    try:
        from config import settings
        admin_chat_id = getattr(settings, 'ADMIN_CHAT_ID', None)
        if not admin_chat_id:
            return web.Response(text="Forbidden", status=403)
        auth_header = request.headers.get("X-Admin-Chat-Id")
        if not auth_header or str(auth_header) != str(admin_chat_id):
            return web.Response(text="Forbidden", status=403)

        from database import get_all_users_with_steam, get_db_type
        db_type = get_db_type()

        # Get count of users with steam_id
        conn = None
        try:
            from database import get_connection, release_connection
            conn = get_connection()
            cursor = conn.cursor()

            if "postgres" in db_type:
                cursor.execute("SELECT COUNT(*) FROM users WHERE steam_id IS NOT NULL")
                steam_count = cursor.fetchone()[0] if cursor.description else 0
                cursor.execute("SELECT COUNT(*) FROM users")
                total_count = cursor.fetchone()[0] if cursor.description else 0
            else:
                cursor.execute("SELECT COUNT(*) FROM users WHERE steam_id IS NOT NULL")
                steam_count = cursor.fetchone()[0]
                cursor.execute("SELECT COUNT(*) FROM users")
                total_count = cursor.fetchone()[0]

            cursor.close()

            # Get some sample users
            users = await asyncio.to_thread(get_all_users_with_steam)
            sample = [{"telegram_id": u.get("telegram_id"), "steam_id": u.get("steam_id")} for u in users[:5]]

            result = {
                "db_type": db_type,
                "total_users": total_count,
                "users_with_steam": steam_count,
                "sample": sample
            }
            return web.Response(text=json.dumps(result, indent=2), status=200)
        finally:
            if conn:
                release_connection(conn)
    except Exception as e:
        import traceback
        return web.Response(text=f"Error: {e}\n{traceback.format_exc()}", status=500)


health_check_handler = None


def setup_health_check(bot):
    """Initialize health check handler with bot instance"""
    global health_check_handler
    async def check(request):
        # Всегда возвращаем 200 - бот работает
        # Не проверяем активность - Render может убить бота если нет обновлений
        return web.Response(text="Bot is working", status=200)
    health_check_handler = check


# Deduplication cache for welcome messages (chat_id, user_id) -> timestamp
_welcome_dedup_cache: dict[tuple[int, int], float] = {}
WELCOME_DEDUP_WINDOW = 5.0  # seconds

async def _welcome_joined_member(chat_id: int, user_obj, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Deduplication: skip if same user welcomed recently in same chat
    import time
    key = (chat_id, user_obj.id)
    now = time.time()
    last = _welcome_dedup_cache.get(key, 0)
    if now - last < WELCOME_DEDUP_WINDOW:
        logger.debug(f"Welcome dedup: skipping {user_obj.id} in {chat_id} (recent welcome)")
        return
    _welcome_dedup_cache[key] = now

    name = user_obj.first_name or user_obj.username or "Friend"
    user_id = user_obj.id
    telegram_username = user_obj.username

    logger.info(f"New member joined: {name} (id={user_id}) in chat {chat_id}")

    try:
        registered = await asyncio.to_thread(
            Database().register_user,
            user_id,
            telegram_username or user_obj.first_name,
            user_obj.first_name,
            source="welcome",
        )
        if registered:
            logger.info(f"Ensured user exists for {user_id}")
        else:
            logger.debug(f"Could not ensure user exists for {user_id}")
    except Exception as e:
        logger.debug(f"Could not ensure user exists for {user_id}: {e}")

    try:
        await asyncio.to_thread(set_user_in_chat, user_id, True)
    except Exception as e:
        logger.debug(f"Could not set in_chat=True for {user_id}: {e}")

    phrase = random.choice(WELCOME_PHRASES)
    keyboard = [
        [InlineKeyboardButton("🎲 Ролл Фиссуры", callback_data="roll_fissure")],
        [InlineKeyboardButton("🔑 Привязать Аккаунт", callback_data="link")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if user_obj.username:
        utf16_bytes = name.encode('utf-16-le')
        name_utf16_len = len(utf16_bytes) // 2
        welcome_text = f"{name}, {phrase}"
        entities = [MessageEntity(
            type=MessageEntity.TEXT_MENTION,
            offset=0,
            length=name_utf16_len,
            user=user_obj
        )]
        await context.bot.send_message(
            chat_id=chat_id,
            text=welcome_text,
            entities=entities,
            reply_markup=reply_markup
        )
    else:
        welcome_text = f"{make_clickable(name, user_id)}, {phrase}"
        await context.bot.send_message(
            chat_id=chat_id,
            text=welcome_text,
            parse_mode="HTML",
            reply_markup=reply_markup
        )

    logger.info(f"Welcome sent for {name}")


async def welcome_new_member(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle bot membership changes and members leaving the chat."""
    try:
        chat_update = update.chat_member or update.my_chat_member
        if chat_update is None:
            logger.debug("welcome_new_member called without chat_member/my_chat_member data")
            return

        chat_id = chat_update.chat.id
        old_member = chat_update.old_chat_member
        new_member = chat_update.new_chat_member

        if old_member and new_member and new_member.user.id == context.bot.id:
            if old_member.status in ['left', 'kicked'] and new_member.status in ['member', 'administrator']:
                try:
                    digest_chat_id = await asyncio.to_thread(get_config, "digest_chat_id")
                    if not digest_chat_id:
                        await asyncio.to_thread(set_config, "digest_chat_id", chat_id)
                        logger.info(f"Автоматически установлен digest_chat_id = {chat_id}")
                except Exception as e:
                    logger.debug(f"Не удалось автоматически установить digest_chat_id: {e}")
            return

        # Handle new user joined via chat_member update (not service message)
        if (
            old_member
            and new_member
            and new_member.user.id != context.bot.id
            and new_member.status in ['member', 'administrator', 'creator']
            and old_member.status not in ['member', 'administrator', 'creator']
        ):
            await _welcome_joined_member(chat_id, new_member.user, context)
            return

        if (
            old_member
            and new_member
            and new_member.user.id != context.bot.id
            and new_member.status in ['left', 'kicked']
        ):
            user_id = new_member.user.id
            name = new_member.user.first_name or "Unknown"
            try:
                await asyncio.to_thread(delete_user, user_id)
                logger.info(f"User {name} ({user_id}) left chat, marked as inactive")
            except Exception as e:
                logger.debug(f"Could not mark user {user_id} as left chat: {e}")

    except Exception as e:
        logger.error(f"Error in welcome_new_member: {e}")


@rate_limit(tokens=1)
async def welcome_new_members_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Welcome users from Telegram's new_chat_members service message."""
    message = update.effective_message
    if not message or not message.new_chat_members:
        return

    for new_member in message.new_chat_members:
        if new_member.id != context.bot.id:
            await _welcome_joined_member(message.chat.id, new_member, context)


async def main():
    """Start Telegram bot - unified function for both polling and webhook modes"""
    if not TOKEN:
        logger.error("BOT_TOKEN not set! Bot cannot start.")
        return

    try:
        # Pre-warm matplotlib font cache to avoid runtime delays
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        plt.figure()
        plt.close()
        logger.info("Matplotlib font cache pre-warmed")

        init_db()
        migrate_db()

        # Load resource usage statistics from DB (to survive redeploy)
        try:
            from analytics_dashboard import load_resource_stats
            load_resource_stats()
            logger.info("Resource statistics loaded from database")
        except Exception as e:
            logger.warning(f"Could not load resource stats: {e}")

        from database import (
            get_all_users,
            get_connection,
            get_db_type,
            user_cache,
        )

        # Fix any NULL fissure values in database
        try:
            db_type = get_db_type()
            conn = get_connection()
            cursor = conn.cursor()
            if "postgres" in db_type:
                cursor.execute("UPDATE users SET fissure = 0.1 WHERE fissure IS NULL")
            else:
                cursor.execute("UPDATE users SET fissure = 0.1 WHERE fissure IS NULL")
            conn.commit()
            fixed_count = cursor.rowcount
            cursor.close()
            logger.info(f"Fixed {fixed_count} users with NULL fissure")
            from database import release_connection
            release_connection(conn)
        except Exception as e:
            logger.error(f"Failed to fix NULL fissure values: {e}")

        # Clean up stale placeholder nicknames (e.g. "Неизвестный игрок", "Unknown")
        # that were saved when Steam stats couldn't be fetched during linking.
        # These placeholders override Telegram usernames in display, so clear them
        # to restore correct names. Real Steam nicknames will be re-fetched by
        # update_user_mmr when profiles become public.
        try:
            db_type = get_db_type()
            conn = get_connection()
            cursor = conn.cursor()
            if "postgres" in db_type:
                cursor.execute("UPDATE users SET steam_nickname = NULL WHERE steam_nickname IN ('Неизвестный игрок', 'Unknown')")
            else:
                cursor.execute("UPDATE users SET steam_nickname = NULL WHERE steam_nickname IN ('Неизвестный игрок', 'Unknown')")
            conn.commit()
            fixed_names = cursor.rowcount
            cursor.close()
            logger.info(f"Cleaned {fixed_names} stale placeholder nicknames")
            from database import release_connection
            release_connection(conn)
        except Exception as e:
            logger.error(f"Failed to clean placeholder nicknames: {e}")

        # Test DB connection
        try:
            db_type = get_db_type()
            logger.info(f"DB type: {db_type}")
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM users")
            count = cursor.fetchone()[0]
            logger.info(f"Database connection OK: {count} users in DB")
            from database import release_connection
            release_connection(conn)
        except Exception as e:
            logger.error(f"Database connection failed: {e}")

        try:
            from bot_utils import recent_fissure_rolls
            if len(recent_fissure_rolls) == 0:
                from database import load_recent_rolls
                rolls = load_recent_rolls()
                recent_fissure_rolls.clear()
                recent_fissure_rolls.extend(rolls)
                logger.info(f"Loaded {len(rolls)} recent rolls from DB on startup")
        except Exception as e:
            logger.warning(f"Could not load recent rolls from DB: {e}")

        try:
            all_users = get_all_users()
            logger.info(f"get_all_users returned {len(all_users)} users")
            loaded_count = 0
            for u in all_users:
                try:
                    user_cache.set(u['telegram_id'], u, skip_dirty=True)
                    loaded_count += 1
                except Exception as e:
                    logger.error(f"Failed to cache user {u.get('telegram_id')}: {e}")
            logger.info(f"Loaded {loaded_count} users into cache on startup")
        except Exception as e:
            logger.error(f"Failed to load users into cache: {e}")
            all_users = []

# Инициализируем Dota Week Top кеш из актуальных данных БД
        from database import update_dota_week_top_cache
        await asyncio.to_thread(update_dota_week_top_cache)
        logger.info("Dota week top cache initialized from DB on startup")

        # Start background retry for circuit breaker
        try:
            from dota_mmr import start_background_retry
            start_background_retry()
            logger.info("Background retry started for circuit breaker")
        except Exception as e:
            logger.warning(f"Could not start background retry: {e}")

        # Pre-load start card background image (async)
        async def preload_start_card_bg():
            try:
                await asyncio.to_thread(_get_start_card_background)
                logger.info("Start card background pre-loaded")
            except Exception as e:
                logger.warning(f"Could not pre-load start card background: {e}")
        asyncio.create_task(preload_start_card_bg())

        job_queue = JobQueue()
        # Create HTTPXRequest with increased timeouts to prevent Telegram API timeouts
        request = HTTPXRequest(
            connection_pool_size=8,
            read_timeout=60.0,
            write_timeout=60.0,
            connect_timeout=30.0,
            pool_timeout=30.0
        )
        app = ApplicationBuilder().token(TOKEN).job_queue(job_queue).request(request).build()
        job_queue.set_application(app)

        # ✅ Периодическое обновление всех тегов (каждые 30 минут)
        async def periodic_tag_refresh(context):
            """Independently refresh Fissure and MMR tags in their own chats."""
            from tags import refresh_fissure_top_tags, refresh_mmr_top_tags

            results = await asyncio.gather(
                refresh_fissure_top_tags(context.bot, notify=False),
                refresh_mmr_top_tags(context.bot),
                return_exceptions=True,
            )
            for family, result in zip(("fissure", "mmr"), results, strict=True):
                if isinstance(result, Exception):
                    logger.warning(f"periodic_tag_refresh {family} failed: {result}")
                else:
                    logger.info(f"periodic_tag_refresh {family} completed")

        job_queue.run_repeating(
            periodic_tag_refresh,
            interval=datetime.timedelta(minutes=30),
            first=datetime.timedelta(minutes=5),
        )

        # ✅ Утреннее приветствие 09:00 MSK
        job_queue.run_daily(
            morning_greeting_job,
            time=datetime.time(hour=6, minute=0),  # 06:00 UTC = 09:00 MSK
            days=(0, 1, 2, 3, 4, 5, 6)
        )

        # ✅ Вечернее приветствие 23:00 MSK
        job_queue.run_daily(
            night_greeting_job,
            time=datetime.time(hour=20, minute=0),  # 20:00 UTC = 23:00 MSK
            days=(0, 1, 2, 3, 4, 5, 6)
        )

        job_queue.run_daily(
            decrease_inactive_job,
            time=datetime.time(hour=0, minute=0),
            days=(0, 1, 2, 3, 4, 5, 6)
        )

        job_queue.run_daily(
            cleanup_left_users_job,
            time=datetime.time(hour=4, minute=0),  # 07:00 MSK
            days=(0, 1, 2, 3, 4, 5, 6)
        )

        # Лёгкая проверка членства в чате (без нагрузки)
        # Раз в 6 часов проверяем порцию (100) самых "старых" пользователей
        job_queue.run_repeating(
            verify_chat_membership_job,
            interval=datetime.timedelta(hours=6),
            first=datetime.timedelta(hours=2),   # первый запуск через 2 часа после старта
        )

        job_queue.run_repeating(
            flush_users_cache_job,
            interval=datetime.timedelta(hours=2),
            first=datetime.timedelta(minutes=15),
        )

        async def validate_user_registry_job(context):
            try:
                from database import validate_user_registry
                invalid_count = await asyncio.to_thread(validate_user_registry)
                if invalid_count:
                    logger.warning(f"validate_user_registry_job: found {invalid_count} users with invalid telegram_id (read-only audit, no data modified)")
            except Exception as e:
                logger.error(f"validate_user_registry_job: {e}")

        job_queue.run_repeating(
            validate_user_registry_job,
            interval=datetime.timedelta(hours=12),
            first=datetime.timedelta(hours=1),
        )

        # Periodic cleanup of stale _USER_START_COOLDOWN entries (prevents memory leak)
        job_queue.run_repeating(
            _cleanup_start_cooldown,
            interval=datetime.timedelta(hours=1),
            first=datetime.datetime.now() + datetime.timedelta(minutes=30),
        )

# morning_digest_job удалён

        # Обновление MMR каждые 6 часов (адаптивно при большом количестве игроков)
        job_queue.run_repeating(
            update_all_mmr_job,
            interval=datetime.timedelta(hours=2),
            first=datetime.datetime.now() + datetime.timedelta(minutes=10)
        )

        # Дайджест (Fissure + Dota): раз в 10 минут (актуально + экономия Render)
        job_queue.run_repeating(
            alternate_digest_job,
            interval=datetime.timedelta(minutes=30),
            first=datetime.datetime.now() + datetime.timedelta(seconds=10)
        )

        # Топ MMR обновляется в update_all_mmr_job после обновления всех игроков

        # ✅ Объявление чемпиона недели в воскресенье 21:00 MSK
        job_queue.run_daily(
            weekly_champion_announcement_job,
            time=datetime.time(hour=18, minute=0),  # 18:00 UTC = 21:00 MSK
            days=(6,)  # Только воскресенье
        )

# ✅ Сброс MMR статистики в понедельник 00:00 MSK (начало новой недели)
        job_queue.run_daily(
            weekly_mmr_reset_job,
            time=datetime.time(hour=21, minute=0),  # 21:00 UTC = 00:00 MSK
            days=(0,),  # Только понедельник
        )

        # ✅ Утренний дайджест каждый день в 9:00 MSK (6:00 UTC) — новый пост с обновлённой hero meta
        job_queue.run_daily(
            morning_digest_job,
            time=datetime.time(hour=6, minute=0),  # 6:00 UTC = 9:00 MSK
        )

        # Если бот стартует в понедельник после 00:00 — используем тот же
        # полный reset, что и scheduled job (stats + tags + holder configs + caches).
        from datetime import datetime as dt
        from datetime import timedelta, timezone
        MSK = timezone(timedelta(hours=3))
        now_msk = dt.now(MSK)
        if now_msk.weekday() == 0:
            from database import get_config
            today = now_msk.strftime("%Y-%m-%d")
            if get_config('weekly_mmr_reset_date') != today:
                from types import SimpleNamespace
                try:
                    await weekly_mmr_reset_job(SimpleNamespace(bot=app.bot))
                    logger.info("Startup: full weekly reset executed")
                except Exception as e:
                    logger.error(f"Startup weekly reset error: {e}")

        # Если бот стартует в воскресенье после 21:00 MSK - проверяем, не нужно ли объявить чемпиона
        from datetime import datetime as dt
        from datetime import timedelta, timezone
        MSK = timezone(timedelta(hours=3))
        now_msk = dt.now(MSK)
        if now_msk.weekday() == 6 and now_msk.hour >= 21:  # Воскресенье после 21:00 MSK
            from database import get_config as _get_cfg
            monday_msk = now_msk - timedelta(days=now_msk.weekday())
            current_week_start = monday_msk.strftime("%Y-%m-%d")
            last_announced = _get_cfg('mmr_week_top_announced')
            if last_announced != current_week_start:
                try:
                    await announce_weekly_mmr_winner(app.bot)
                    logger.info("Startup: weekly champion announced on Sunday startup")
                except Exception as e:
                    logger.error(f"Startup weekly champion announcement error: {e}")

        # Если бот стартовал после 9:00 MSK — догоняем утренний дайджест, если он не был отправлен сегодня
        from datetime import datetime as dt
        from datetime import timedelta, timezone
        MSK = timezone(timedelta(hours=3))
        now_msk = dt.now(MSK)
        today_label = now_msk.strftime("%Y-%m-%d")
        try:
            from database import get_config as _get_morning_cfg
            from digest import morning_digest_job as _morning_digest_job

            class _MorningCtx:
                def __init__(self, bot):
                    self.application = _MorningApp(bot)

            class _MorningApp:
                def __init__(self, bot):
                    self.bot = bot

            if _get_morning_cfg('morning_digest_last_date') != today_label and now_msk.hour >= 9:
                logger.info("Startup: catching up missed morning digest")
                await _morning_digest_job(_MorningCtx(app.bot))
        except Exception as e:
            logger.error(f"Startup morning digest catch-up error: {e}")

        app.add_handler(CommandHandler("start", start))
        app.add_handler(CommandHandler("about", about))
        app.add_handler(CallbackQueryHandler(button_callback))
        app.add_handler(CommandHandler(("fissure", "fissura"), fissure))
        app.add_handler(CommandHandler("profile", stats))
        app.add_handler(CommandHandler("info", info))
        app.add_handler(CommandHandler("top", top))
        app.add_handler(CommandHandler("topmmr", topmmr))
        app.add_handler(CommandHandler("refreshmmr", refreshmmr))
        app.add_handler(CommandHandler("link", link))
        app.add_handler(CommandHandler("admin_unlink", admin_unlink))
        app.add_handler(CommandHandler("tag", admin_tag))
        app.add_handler(CommandHandler("untag", admin_untag))
        app.add_handler(CommandHandler("vip", vip_command))
        app.add_handler(CommandHandler("resettags", reset_tags_command))
        app.add_handler(CommandHandler("tags", tags_list))
        app.add_handler(CommandHandler("setdigestchat", digest_handler))
        app.add_handler(CommandHandler("setfissurechat", digest_handler))
        app.add_handler(CommandHandler("setmmrchat", digest_handler))
        app.add_handler(CommandHandler("resetgame", reset_game))
        app.add_handler(CommandHandler("analyze", analyze_command))
        app.add_handler(CommandHandler(("party", "party"), party_command))
        app.add_handler(CommandHandler("story", story_command))
        app.add_handler(ChatMemberHandler(welcome_new_member, ChatMemberHandler.ANY_CHAT_MEMBER))
        app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome_new_members_message))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, menu_handler))

        # ── Модуль модерации /mute ──────────────────────────────────────────
        register_mute_handlers(app)

        # Add error handler
        async def error_handler(update, context):
            logger.error(f"Update {update} caused error {context.error}")

        app.add_error_handler(error_handler)

        webhook_url = os.getenv("WEBHOOK_URL")
        use_polling = os.getenv("USE_POLLING", "false").lower() == "true"

        await app.initialize()
        await app.start()
        await job_queue.start()

        logger.info(f"use_polling={use_polling}, webhook_url={webhook_url}, PORT={os.getenv('PORT')}")

        # Register bot commands so the command menu shows up in chats
        from telegram import BotCommand
        bot_commands = [
            BotCommand("start", "Запустить бота"),
            BotCommand("fissure", "🎲 Ролл Фиссуры"),
            BotCommand("profile", "👤 Профиль"),
            BotCommand("top", "🏆 Топ Фиссур"),
            BotCommand("topmmr", "🏆 Топ MMR"),
            BotCommand("analyze", "🔎 Аналитика"),
            BotCommand("link", "🔑 Привязать Аккаунт"),
            BotCommand("party", "🎮 Поиск пати"),
            BotCommand("about", "ℹ️ О боте"),
            BotCommand("info", "📖 Информация"),
            BotCommand("resetgame", "🔄 Сброс игры"),
            BotCommand("digestnow", "📊 Обновить дайджест"),
            BotCommand("vip", "💎 Выдать VIP"),
        ]
        try:
            await app.bot.set_my_commands(bot_commands)
        except Exception as e:
            logger.warning(f"Could not set bot commands: {e}")

        if use_polling or not webhook_url:
            logger.info("Starting bot in POLLING mode")
            await app.bot.delete_webhook(drop_pending_updates=True)

            from aiohttp import web
            async def health_handler(request):
                return web.Response(text="Bot is polling", status=200)
            web_app = web.Application()
            web_app.router.add_get('/', health_handler)
            web_app.router.add_get('/health', health_handler)
            web_app.router.add_get('/api/recent-rolls', recent_rolls_handler)
            web_app.router.add_get('/api/top-mmr', top_mmr_handler)
            web_app.router.add_get('/api/steam-debug', steam_debug)
            web_app.router.add_get('/api/obs-last5', obs_last5_handler)
            web_app.router.add_route('OPTIONS', '/api/{path:.*}', api_options_handler)
            runner = web.AppRunner(web_app)
            await runner.setup()
            port = int(os.getenv('PORT', 10000))
            logger.info(f"Starting TCP site on port {port}...")
            site = web.TCPSite(runner, '0.0.0.0', port)
            await site.start()
            logger.info("Site started, sleeping 3s for port detection...")
            await asyncio.sleep(3)
            logger.info(f"Health server started on 0.0.0.0:{port}")

            offset = 0
            while True:
                try:
                    updates = await app.bot.get_updates(offset=offset, timeout=30)
                    for update in updates:
                        offset = update.update_id + 1
                        await app.process_update(update)
                except Exception as e:
                    logger.error(f"Polling error: {e}")
                    await asyncio.sleep(5)
        else:
            logger.info("Starting bot in WEBHOOK mode")
            import telegram.error

            for attempt in range(3):
                try:
                    await app.bot.set_webhook(
                        url=webhook_url,
                        drop_pending_updates=True,
                        allowed_updates=[
                            "message",
                            "callback_query",
                            "chat_member",
                            "my_chat_member",
                        ],
                    )
                    logger.info(f"Webhook URL: {webhook_url}")
                    break
                except telegram.error.RetryAfter as e:
                    logger.warning(f"Webhook set failed (attempt {attempt+1}), retrying in {e.retry_after}s...")
                    await asyncio.sleep(e.retry_after + 1)
                except Exception as e:
                    logger.warning(f"Webhook set failed: {e}, retrying in 5s...")
                    await asyncio.sleep(5)
            else:
                logger.warning("All webhook attempts failed, continuing anyway...")

            logger.info("Bot is fully online and ready")

            from aiohttp import web

            async def handle_webhook(request):
                global last_update_time
                try:
                    update_data = await request.json()
                    update_type = 'unknown'
                    update_text = 'unknown'
                    if 'message' in update_data:
                        update_type = 'message'
                        update_text = update_data['message'].get('text', '')
                    elif 'callback_query' in update_data:
                        update_type = 'callback_query'
                        update_text = update_data['callback_query'].get('data', '')
                    logger.info(f"Webhook received update type={update_type} text={update_text}")
                    update = Update.de_json(update_data, request.app['bot_app'].bot)
                    await request.app['bot_app'].process_update(update)
                    last_update_time = time.time()
                    return web.Response(status=200)
                except Exception as e:
                    logger.error(f"Webhook error: {e}", exc_info=True)
                    return web.Response(status=500)

            web_app = web.Application()
            web_app['bot_app'] = app
            web_app.router.add_post('/webhook', handle_webhook)
            web_app.router.add_get('/', lambda r: web.Response(text="OK"))
            setup_health_check(app.bot)
            web_app.router.add_get('/health', health_check_handler)
            web_app.router.add_get('/api/recent-rolls', recent_rolls_handler)
            web_app.router.add_get('/api/top-mmr', top_mmr_handler)
            web_app.router.add_get('/api/steam-debug', steam_debug)
            web_app.router.add_get('/api/obs-last5', obs_last5_handler)
            web_app.router.add_route('OPTIONS', '/api/{path:.*}', api_options_handler)

            async def reset_circuit(request):
                try:
                    from dota_mmr import reset_circuit_breaker
                    reset_circuit_breaker()
                    return web.Response(text="Circuit breaker reset", status=200)
                except Exception as e:
                    logger.error(f"Reset circuit error: {e}")
                    return web.Response(text=f"Error: {e}", status=500)
            web_app.router.add_post('/api/reset-circuit', reset_circuit)

            async def refresh_webhook(request):
                try:
                    await app.bot.delete_webhook(drop_pending_updates=True)
                    await app.bot.set_webhook(
                        url=webhook_url,
                        drop_pending_updates=False,
                        allowed_updates=[
                            "message",
                            "callback_query",
                            "chat_member",
                            "my_chat_member",
                        ],
                    )
                    return web.Response(text=f"Webhook refreshed: {webhook_url}", status=200)
                except Exception as e:
                    logger.error(f"Refresh webhook error: {e}")
                    return web.Response(text=f"Error: {e}", status=500)
            web_app.router.add_post('/api/refresh-webhook', refresh_webhook)

            runner = web.AppRunner(web_app, keepalive_timeout=120, client_max_size=10*1024*1024)
            await runner.setup()
            port = int(os.getenv('PORT', 10000))
            site = web.TCPSite(runner, '0.0.0.0', port)
            await site.start()
            await asyncio.sleep(1)
            logger.info(f"Web server started on 0.0.0.0:{port}")

            # Force sync to ensure port is ready
            await asyncio.sleep(2)

            async def keep_alive_ping():
                ping_url = webhook_url.rsplit('/webhook', 1)[0] + '/health'
                while True:
                    try:
                        await asyncio.sleep(800)
                        session = await get_aiohttp_session()
                        from analytics_dashboard import record_neon_hours
                        record_neon_hours(KEEPALIVE_PING_NEON_HOURS)
                        async with session.get(ping_url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                            await resp.text()
                        root_url = webhook_url.rsplit('/webhook', 1)[0] + '/'
                        async with session.get(root_url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                            await resp.text()
                        logger.info("Keep-alive ping sent")
                    except Exception as e:
                        logger.error(f"Keep-alive ping error: {e}")

            async def webhook_recovery_task():
                """Re-register webhook to recover from Render cold starts and URL mismatches"""
                while True:
                    try:
                        await asyncio.sleep(900)
                        webhook_info = await app.bot.get_webhook_info()
                        needs_renewal = False
                        if not webhook_info.url:
                            logger.warning("Webhook URL is empty, re-registering...")
                            needs_renewal = True
                        elif webhook_info.url != webhook_url:
                            logger.warning(f"Webhook URL mismatch: expected {webhook_url}, got {webhook_info.url}, re-registering...")
                            needs_renewal = True
                        if needs_renewal:
                            await app.bot.set_webhook(
                                url=webhook_url,
                                drop_pending_updates=False,
                                allowed_updates=[
                                    "message",
                                    "callback_query",
                                    "chat_member",
                                    "my_chat_member",
                                ],
                            )
                            logger.info("Webhook re-registered successfully")
                    except Exception as e:
                        logger.error(f"Webhook recovery check error: {e}")

        asyncio.create_task(keep_alive_ping())
        asyncio.create_task(webhook_recovery_task())

        # Graceful shutdown handling
        loop = asyncio.get_running_loop()
        stop_event = asyncio.Event()

        def _signal_handler():
            logger.info("Received SIGTERM/SIGINT, initiating graceful shutdown...")
            stop_event.set()

        try:
            loop.add_signal_handler(signal.SIGTERM, _signal_handler)
            loop.add_signal_handler(signal.SIGINT, _signal_handler)
        except (NotImplementedError, RuntimeError):
            # Windows doesn't support add_signal_handler
            pass

        while not stop_event.is_set():
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=1.0)
            except TimeoutError:
                continue

    except Exception as e:
        logger.error(f"Critical error: {e}", exc_info=True)
        raise
    finally:
        try:
            from database import close_aiohttp_session, close_pg_pool, flush_users_cache
            flushed = flush_users_cache()
            logger.info(f"Shutdown: flushed {flushed} users to DB")
            # Close aiohttp session to prevent "Unclosed connection" error
            await close_aiohttp_session()
            logger.info("Shutdown: aiohttp session closed")
            # Close PostgreSQL pool
            close_pg_pool()
        except Exception as flush_err:
            logger.error(f"Shutdown flush error: {flush_err}")


if __name__ == "__main__":
    def _emergency_flush():
        try:
            from database import flush_users_cache
            dirty = flush_users_cache()
            logger.warning(f"atexit: emergency flush completed ({dirty} users)")
        except Exception as e:
            logger.warning(f"Emergency flush failed: {e}")

    atexit.register(_emergency_flush)

    # Dota week top cache loaded in startup handler above
    try:
        from image_cache import preload_heroes

        from dota_mmr import get_heroes_data
        heroes = get_heroes_data()
        if heroes:
            preload_heroes(heroes)
            logger.info("Hero icons preloaded in background")
    except Exception as e:
        logger.debug(f"Could not preload heroes: {e}")

    asyncio.run(main())




