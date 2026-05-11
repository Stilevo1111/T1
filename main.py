# -*- coding: utf-8 -*-
import os
import io
import json
import random
import time
import asyncio
import logging
import datetime
import traceback
import urllib.parse as urlparse
import psycopg2
import html
import hashlib
from datetime import timezone, timedelta
from concurrent.futures import ThreadPoolExecutor
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, Message, MessageEntity, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters, JobQueue, ChatMemberHandler, CallbackQueryHandler
from telegram.error import Conflict
from database import init_db, get_user, update_fissure, get_fissure_top, update_last_message_id, Database, get_user_rank, get_fissure_rank, decrease_inactive_fissure, get_config, set_config, get_digest_stats, update_player_positions, update_digest_snapshot, migrate_db, get_connection, get_dota_digest_stats, set_user_in_chat, zeus_strike, get_user_by_username, delete_user, top_cache, update_user_fields_batch, get_dota_mmr_top, get_dota_week_top, get_dota_week_rank, BACKUP_DATABASE_URL, DATABASE_URL, reset_all_fissure_data, cleanup_left_users
from dota_mmr import update_user_mmr
from database import get_all_users_with_steam, user_cache, update_dota_week_top_cache
import aiohttp
from aiohttp import web
from rate_limiter import telegram_rate_limiter, rate_limit

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

_user_fissure_processing = {}  # Request lock: user_id -> timestamp (for fissure processing)
_USER_START_COOLDOWN = {}  # Spam protection for /start: user_id -> timestamp
_START_COOLDOWN = 5  # 5 seconds cooldown for /start command

_digest_state = {"type": None, "chat_id": None, "last_data_update": 0, "last_run": 0, "last_text": None, "last_hero_meta_update": 0, "hero_meta_image": None}
_digest_state_lock = asyncio.Lock()  # Lock for thread-safe access to _digest_state
_digest_cache = {
    "text": None,           # Кешированный текст дайджеста
    "type": None,          # Тип дайджеста для кеша
    "created_at": 0,       # Время создания кеша
    "cache_ttl": 300,      # Время жизни кеша в секундах (5 минут)
    "rotation_interval": 15,  # Интервал смены типа в секундах (15 секунд)
    "data_hash": None,     # Хеш данных для быстрого сравнения изменений
    "last_data_check": 0   # Время последней проверки данных
}

def get_digest_data_hash():
    """Быстрое хеширование ключевых метрик дайджеста без тяжелых SQL запросов"""
    try:
        # Получаем ключевые метрики из кеша или быстрой проверки
        from database import user_cache

        # Используем кешированные данные если они свежие
        digest_stats = user_cache.get('digest_stats')
        dota_stats = user_cache.get('dota_digest_stats')

        if not digest_stats or not dota_stats:
            # Если нет кеша, делаем быструю проверку без полного запроса
            return None

        # Создаем хеш из ключевых метрик
        key_data = f"{digest_stats.get('top_growth', '')}{digest_stats.get('top_drop', '')}{digest_stats.get('top_streak', '')}"
        key_data += f"{dota_stats.get('top_mmr_player', '')}{dota_stats.get('top_mmr', 0)}{dota_stats.get('total_active', 0)}"

        return hashlib.md5(key_data.encode()).hexdigest()

    except Exception as e:
        logger.debug(f"Error creating digest data hash: {e}")
        return None

_last_data_refresh = 0
_data_refresh_interval = 300  # Обновлять данные каждые 5 минут
DIGEST_DATA_REFRESH_INTERVAL = 3600  # Обновлять данные дайджеста раз в час
HERO_META_REFRESH_INTERVAL = 3600  # Обновлять мета-баннер героя раз в час

_rate_limit_until = 0  # Unix timestamp - skip API calls until this time after 429
RATE_LIMIT_COOLDOWN = 60  # 60 seconds cooldown after hitting rate limit


def is_rate_limited():
    """Check if bot is currently rate limited"""
    return time.time() < _rate_limit_until


def set_rate_limited(retry_after=None):
    """Set rate limit state. retry_after is seconds to wait (default COOLDOWN)"""
    global _rate_limit_until
    wait_time = retry_after if retry_after else RATE_LIMIT_COOLDOWN
    _rate_limit_until = time.time() + wait_time
    logger.warning(f"Rate limited until {time.strftime('%H:%M:%S', time.localtime(_rate_limit_until))}")


@rate_limit(tokens=1)
async def delete_after_delay(bot, chat_id, msg_id, delay, job_queue=None):
    """Удалить сообщение через delay секунд"""
    # Skip invalid message IDs
    if not isinstance(msg_id, int) or msg_id <= 0:
        logger.debug(f"delete_after_delay: skipping invalid msg_id={msg_id}")
        return

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
            logger.info(f"delete_after_delay: attempting to delete msg_id={msg_id} in chat={chat_id}")
            await bot.delete_message(chat_id, msg_id)
            logger.info(f"Deleted delayed message {msg_id} in chat {chat_id}")
        except Exception as e:
            error_str = str(e).lower()
            if "message to delete not found" in error_str:
                logger.debug(f"Message {msg_id} already deleted in chat {chat_id}")
            else:
                logger.warning(f"Failed to delete delayed message {msg_id} in chat {chat_id}: {e}")


@rate_limit(tokens=1)
async def delete_message_job(context):
    """Job для удаления сообщения"""
    bot = context.application.bot  # Доступ через context.application.bot в PTB v20+
    chat_id = context.job.data['chat_id']
    msg_id = context.job.data['msg_id']

    # Skip invalid message IDs
    if not isinstance(msg_id, int) or msg_id <= 0:
        logger.debug(f"delete_message_job: skipping invalid msg_id={msg_id}")
        return

    try:
        logger.info(f"delete_message_job: attempting to delete msg_id={msg_id} in chat={chat_id}")
        await bot.delete_message(chat_id, msg_id)
        logger.info(f"Deleted scheduled message {msg_id} in chat {chat_id}")
    except Exception as e:
        error_str = str(e).lower()
        if "message to delete not found" in error_str or "bad request" in error_str:
            # Message already deleted or can't be deleted - this is normal
            logger.debug(f"Message {msg_id} already deleted in chat {chat_id}")
        else:
            logger.warning(f"Failed to delete message {msg_id} in chat {chat_id}: {e}")


class ManualContext:
    """Контекст для ручного вызова jobs"""
    def __init__(self, application, bot):
        self.application = application
        self.bot = bot
        self.manual = True


_bot_can_delete_cache = {}
_bot_can_delete_ttl = 3600  # 1 час
_BOT_CAN_DELETE_CACHE_MAX = 200

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

def schedule_delete(bot, chat_id, msg_id, delay=30, job_queue=None):
    """Запланировать удаление сообщения через delay секунд"""
    asyncio.create_task(delete_after_delay(bot, chat_id, msg_id, delay))


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

        # Обновляем позиции игроков
        update_player_positions()

        # Запоминаем что выполнено сегодня
        set_config('last_decrease_inactive_run', datetime.now().strftime("%Y-%m-%d"))
    except Exception as e:
        logger.error(f"Ошибка в decrease_inactive_job: {e}")





@rate_limit(tokens=1)
async def morning_greeting_job(context):
    """✅ Утреннее приветствие 09:00 MSK - 1 раз в чат"""
    from datetime import datetime as dt, timezone, timedelta
    from database import get_config

    MSK = timezone(timedelta(hours=3))
    today_str = dt.now(MSK).strftime("%Y-%m-%d")

    last_greeting = get_config('daily_greeting_sent')
    if last_greeting == today_str:
        logger.info("Утреннее приветствие уже отправлено сегодня")
        return

    MORNING_GREETINGS = [
        "🦇 Утречко! Готовы к каточке? 🎮",
        "☀️ Доброе утро! Время мочить.",
        "🌅 Всем хорошего дня! Ролли.",
        "☕ Утро началось! Кто в игре?"
    ]

    greeting_text = random.choice(MORNING_GREETINGS)

    try:
        logger.info(f"Запуск утреннего приветствия 09:00 MSK")

        digest_chat_id = get_config('digest_chat_id')
        if not digest_chat_id:
            logger.info("Чат для дайджеста не настроен")
            return

        bot = context.application.bot
        await bot.send_message(chat_id=digest_chat_id, text=greeting_text, reply_markup=main_menu())

        set_config('daily_greeting_sent', today_str)
        logger.info(f"Утреннее приветствие отправлено в чат {digest_chat_id}")

    except Exception as e:
        logger.error(f"Ошибка в morning_greeting_job: {e}")


@rate_limit(tokens=1)
async def night_greeting_job(context):
    """✅ Вечернее приветствие 23:00 MSK - 1 раз в чат"""
    from datetime import datetime as dt, timezone, timedelta
    from database import get_config

    MSK = timezone(timedelta(hours=3))
    today_str = dt.now(MSK).strftime("%Y-%m-%d")

    last_greeting = get_config('night_greeting_sent')
    if last_greeting == today_str:
        logger.info("Вечернее приветствие уже отправлено сегодня")
        return

    NIGHT_GREETINGS = [
        "🦇 Спокойной ночи, дотеры. Если кто не спит — играйте тихо, я молчу.",
        "🦇 Спокойной ночи! Вижу, все уснули. 💤",
        "🦇 Zzz... Спокойной ночи!",
        "🌙 Доброй ночи! Завтра новые катки."
    ]

    greeting_text = random.choice(NIGHT_GREETINGS)

    try:
        logger.info(f"Запуск вечернего приветствия 23:00 MSK")

        digest_chat_id = get_config('digest_chat_id')
        if not digest_chat_id:
            logger.info("Чат для дайджеста не настроен")
            return

        bot = context.application.bot
        await bot.send_message(chat_id=digest_chat_id, text=greeting_text, reply_markup=main_menu())

        set_config('night_greeting_sent', today_str)
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
        from datetime import datetime as dt, timezone, timedelta
        MSK = timezone(timedelta(hours=3))
        today_msk = dt.now(MSK)
        sunday_msk = today_msk - timedelta(days=(today_msk.weekday() + 1) % 7)
        current_week_start = sunday_msk.strftime("%Y-%m-%d")

        last_announced = get_config('mmr_week_top_announced')
        digest_chat_id = get_config('digest_chat_id')

        debug_info = f"Отладка MVP:\n"
        debug_info += f"Сегодня: {today_msk.strftime('%Y-%m-%d %H:%M:%S')} MSK (weekday={today_msk.weekday()})\n"
        debug_info += f"Начало недели: {current_week_start}\n"
        debug_info += f"Последнее поздравление: {last_announced}\n"
        debug_info += f"digest_chat_id: {digest_chat_id}\n"

        # Проверяем данные MMR
        from database import get_dota_week_top_from_db
        top_users = get_dota_week_top_from_db(5, force_refresh=True)
        active_users = [u for u in top_users if u.get('week_games', 0) > 0] if top_users else []

        debug_info += f"Топ MMR пользователей: {len(top_users) if top_users else 0}\n"
        debug_info += f"Активных пользователей: {len(active_users)}\n"

        if active_users:
            winner = active_users[0]
            debug_info += f"MVP: {winner.get('steam_nickname', 'Unknown')} ({winner.get('week_games', 0)} игр, {winner.get('week_wins', 0)} побед)\n"

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
async def analyze_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Еженедельная аналитика игрока"""
    user_obj = update.effective_user
    username = user_obj.username or user_obj.first_name
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

        # Send loading message
        loading_msg = await context.bot.send_message(
            chat_id=chat_id,
            text="⏳ Генерирую аналитику..."
        )

        from weekly_analytics import generate_chart_only, get_analytics_pages
        chart_data = await generate_chart_only(update.effective_user.id)

        # Delete loading message
        try:
            await context.bot.delete_message(chat_id, loading_msg.message_id)
        except Exception as e:
            logger.debug(f"Could not delete loading message: {e}")

        if chart_data:
            history = chart_data.get("history", [])
            matches = chart_data.get("matches", [])
            chart_image = chart_data.get("image")
            
            # Ensure charts directory exists for potential caching
            import os
            os.makedirs("charts", exist_ok=True)
            
            from weekly_analytics import detect_role_from_history, calculate_player_stats
            role = await detect_role_from_history(matches)
            
            stats = calculate_player_stats(matches)
            
            # Сохраняем данные для ленивой генерации страниц
            context.user_data['analytics_stats'] = stats
            context.user_data['analytics_role'] = role
            context.user_data['analytics_page'] = 0
            context.user_data['analytics_history'] = history
            context.user_data['analytics_matches'] = matches
            context.user_data['analytics_pages'] = [None, None]  # Placeholder - не генерируем сразу
            context.user_data['analytics_generated'] = set()

            if chart_image:
                # Send analytics with chart as photo - ТОЛЬКО ГРАФИК, без текста
                photo_buf = io.BytesIO(chart_image)
                photo_buf.name = "weekly_analytics.png"

                reply_markup = _build_analytics_keyboard(0, 2, set())

                result_msg = await context.bot.send_photo(
                    chat_id=chat_id,
                    photo=photo_buf,
                    caption="📊 Аналитика готова\\. Нажмите кнопку для просмотра таблиц\\.",
                    reply_markup=reply_markup,
                    parse_mode="MarkdownV2"
                )
        else:
            # No analytics data available
            result_msg = await context.bot.send_message(
                chat_id=chat_id,
                text="❌ Недостаточно данных для аналитики. Сыграйте больше матчей за неделю."
            )

        # Track this message for future deletion
        set_last_bot_message(chat_id, update.effective_user.id, result_msg.message_id)
        schedule_delete(context.bot, chat_id, result_msg.message_id, 30, context.application.job_queue)
        update_last_message_id(update.effective_user.id, result_msg.message_id)

        # Small delay to ensure message is visible
        await asyncio.sleep(0.1)
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
        schedule_delete(context.bot, chat_id, msg.message_id, 30, context.application.job_queue)
        update_last_message_id(update.effective_user.id, msg.message_id)


def _get_player_stats_wrapper(steam_id, use_cache):
    """Обёртка для вызова синхронной get_player_stats из потока"""
    from dota_mmr import get_player_stats
    return get_player_stats(steam_id, use_cache=use_cache)


@rate_limit(tokens=1)
async def weekly_champion_announcement_job(context):
    """Объявление чемпиона недели в воскресенье 23:00 MSK"""
    try:
        await announce_weekly_mmr_winner(context.bot)
    except Exception as e:
        logger.error(f"Ошибка в weekly_champion_announcement_job: {e}")


async def weekly_mmr_reset_job(context):
    """Сброс еженедельной статистики MMR в 00:00 MSK."""
    from datetime import datetime as dt, timezone, timedelta
    MSK = timezone(timedelta(hours=3))
    today_msk = dt.now(MSK)
    sunday_msk = today_msk - timedelta(days=(today_msk.weekday() + 1) % 7)
    current_week_start = sunday_msk.strftime("%Y-%m-%d")

    try:
        from database import get_connection, DATABASE_URL
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
                    week_start_date = ?
                WHERE steam_id IS NOT NULL
            """, (current_week_start,))
        conn_reset.commit()
        cursor_reset.close()
        user_cache.clear()
        top_cache.clear()
        logger.info("weekly_mmr_reset_job: еженедельная статистика MMR сброшена в 00:00 MSK")
    except Exception as e:
        logger.error(f"weekly_mmr_reset_job: ошибка при сбросе статистики: {e}")

async def announce_weekly_mmr_winner(bot):
    """Отправляет поздравление победителю недельного топа MMR при смене недели."""
    from datetime import datetime as dt, timezone, timedelta
    MSK = timezone(timedelta(hours=3))
    today_msk = dt.now(MSK)
    sunday_msk = today_msk - timedelta(days=(today_msk.weekday() + 1) % 7)
    current_week_start = sunday_msk.strftime("%Y-%m-%d")

    last_announced = get_config('mmr_week_top_announced')
    if last_announced == current_week_start:
        return False

    # Проверяем, есть ли игроки с данными за ПРОШЛУЮ неделю
    from database import get_connection as gc2
    conn = gc2()
    cursor = conn.cursor()
    if "postgres" in scheme:
        cursor.execute(
            "SELECT COUNT(*) FROM users WHERE steam_id IS NOT NULL AND week_games > 0 AND (week_start_date IS NULL OR week_start_date::text != %s)",
            (current_week_start,))
    else:
        cursor.execute(
            "SELECT COUNT(*) FROM users WHERE steam_id IS NOT NULL AND week_games > 0 AND (week_start_date IS NULL OR week_start_date != ?)",
            (current_week_start,))
    stale_count = cursor.fetchone()[0]
    cursor.close()

    is_sunday = today_msk.weekday() == 6

    # В воскресенье проверяем, что есть игроки с новыми данными
    if is_sunday and stale_count == 0:
        logger.info("announce_weekly_mmr_winner: в воскресенье stale_count == 0 - данных за новую неделю ещё нет")
        return False

    # Если не воскресенье и нет данных за прошлую неделю — пропускаем
    if not is_sunday and stale_count == 0:
        logger.info("announce_weekly_mmr_winner: нет данных за прошлую неделю и не воскресенье")
        return False

    digest_chat_id = get_config('digest_chat_id')
    if not digest_chat_id:
        logger.info("announce_weekly_mmr_winner: чат для дайджеста не настроен")
        return False

    from database import get_dota_week_top_from_db
    top_users = get_dota_week_top_from_db(5, force_refresh=True)
    if not top_users or all(u.get('week_games', 0) == 0 for u in top_users):
        logger.info("announce_weekly_mmr_winner: нет данных для топа MMR (никто не играл)")
        set_config('mmr_week_top_announced', current_week_start)
        return False

    active_users = [u for u in top_users if u.get('week_games', 0) > 0]
    if not active_users:
        set_config('mmr_week_top_announced', current_week_start)
        return False

    winner = active_users[0]
    username = winner.get('steam_nickname') or winner.get('username') or 'Игрок'
    week_wins = winner.get('week_wins', 0)
    week_games = winner.get('week_games', 0)
    week_losses = week_games - week_wins
    winrate = round((week_wins / week_games * 100), 1) if week_games > 0 else 0
    rank_tier = winner.get('rank_tier', 0)
    mmr = winner.get('mmr', 0)
    telegram_id = winner.get('telegram_id')
    streak = winner.get('week_current_streak', 0)

    prev_winner_tg_id = get_config('current_mvp_telegram_id')
    prev_winner_tag = get_config('current_mvp_tag')
    if prev_winner_tg_id and prev_winner_tag and digest_chat_id:
        try:
            await bot.set_chat_administrator_custom_title(
                chat_id=digest_chat_id,
                user_id=prev_winner_tg_id,
                custom_title=""
            )
            logger.info(f"Забран тег у прошлого победителя {prev_winner_tg_id}")
        except Exception as e:
            logger.warning(f"Не удалось забрать тег у прошлого победителя: {e}")

    mvp_tag = "MVP недели"
    tag_set = False
    if telegram_id and digest_chat_id:
        try:
            await bot.set_chat_administrator_custom_title(
                chat_id=digest_chat_id,
                user_id=telegram_id,
                custom_title=mvp_tag
            )
            tag_set = True
            logger.info(f"Установлен тег {mvp_tag} для победителя {telegram_id}")
        except Exception as e:
            logger.warning(f"Не удалось установить тег победителю: {e}")

    if telegram_id:
        user = get_user(telegram_id)
        if user:
            current_mvp_count = user.get('weekly_mvp_count', 0)
            update_user_fields_batch(telegram_id, {'weekly_mvp_count': current_mvp_count + 1})

    set_config('current_mvp_telegram_id', str(telegram_id) if telegram_id else "")
    set_config('current_mvp_tag', mvp_tag)

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

    name_display = f"<a href=\"tg://user?id={telegram_id}\">{username}</a>" if telegram_id else username

    tag_info = ""
    if tag_set:
        tag_info = f"\n👤 Ему присвоен титул \"{mvp_tag}\" и добавлена медалька в профиль!"

    text = (
        f"Поздравляем чемпиона недели🏆\n"
        f"🥇 {name_display} • 🗡️ {rank_str}\n\n"
        f"📈 Результат за неделю:\n"
        f" └ {week_wins}W • {week_losses}L • WR {winrate}%\n"
        f"🔥 Текущий стрик: {streak} побед\n\n"
        f"🏆Этот игрок показал лучший результат в топе MMR за неделю!{tag_info}"
    )

    from dota_mmr import generate_start_card

    # Асинхронно получаем свежий аватар (безопасно для event loop)
    avatar_url = winner.get('avatar')
    if winner.get('steam_id'):
        logger.info(f"Fetching fresh avatar for champion {winner.get('steam_nickname')}")
        try:
            fresh_stats = await asyncio.to_thread(
                _get_player_stats_wrapper, winner.get('steam_id'), False
            )
            if fresh_stats and fresh_stats.get('avatar'):
                avatar_url = fresh_stats.get('avatar')
                logger.info(f"Using fresh avatar for champion: {avatar_url}")
            else:
                logger.info(f"No fresh avatar available for champion, using DB: {avatar_url}")
        except Exception as e:
            logger.warning(f"Failed to fetch fresh avatar: {e}")

    # Асинхронно генерируем карточку (безопасно для event loop)
    try:
        card_data = await asyncio.to_thread(
            generate_start_card,
            avatar_url=avatar_url,
            message_count=week_games,
            username=username,
            steam_nickname=username,
            rank_tier=rank_tier,
            weekly_mvp=0,
            weekly_top2=0,
            weekly_top3=0,
            week_wins=week_wins,
            week_losses=week_losses
        )

        if card_data:
            await bot.send_photo(
                chat_id=digest_chat_id,
                photo=card_data,
                caption=text,
                parse_mode="HTML"
            )
        else:
            winner_banner_url = "https://i.ibb.co/Jj3vwbWB/ANQkz.jpg"
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



async def backup_database_job(context):
    """Копирование данных в backup БД каждый час"""
    try:
        if not BACKUP_DATABASE_URL:
            return

        logger.info("Запуск копирования в backup БД")

        # Import psycopg2 locally to avoid any shadowing issues
        import psycopg2

        main_url = urlparse(DATABASE_URL)
        backup_url = urlparse(BACKUP_DATABASE_URL)

        main_conn = psycopg2.connect(
            host=main_url.hostname,
            port=main_url.port or 5432,
            dbname=main_url.path[1:],
            user=main_url.username,
            password=main_url.password
        )

        backup_conn = psycopg2.connect(
            host=backup_url.hostname,
            port=backup_url.port or 5432,
            dbname=backup_url.path[1:],
            user=backup_url.username,
            password=backup_url.password
        )

        main_cursor = main_conn.cursor()
        backup_cursor = backup_conn.cursor()

        # Get all tables
        main_cursor.execute("""
            SELECT table_name FROM information_schema.tables 
            WHERE table_schema = 'public'
        """)
        tables = [row[0] for row in main_cursor.fetchall()]

        total_copied = 0
        for table in tables:
            try:
                # Get all data from table
                main_cursor.execute(f"SELECT * FROM {table}")
                rows = main_cursor.fetchall()

                if rows:
                    # Get column names
                    columns = [desc[0] for desc in main_cursor.description]
                    placeholders = ','.join(['%s'] * len(columns))
                    column_names = ','.join(columns)

                    # Clear and insert (or use DELETE + INSERT)
                    backup_cursor.execute(f"DELETE FROM {table}")

                    for row in rows:
                        backup_cursor.execute(f"INSERT INTO {table} ({column_names}) VALUES ({placeholders})", row)

                    total_copied += len(rows)
                    logger.info(f"Table {table}: copied {len(rows)} rows")
            except Exception as e:
                logger.warning(f"Error copying table {table}: {e}")

        main_cursor.close()
        backup_cursor.close()
        main_conn.close()
        backup_conn.close()
        logger.info(f"Скопировано {total_copied} записей в backup БД")

    except Exception as e:
        logger.error(f"Backup job error: {e}")


@rate_limit(tokens=1)
async def update_all_mmr_job(context):
    """Ежечасовое обновление MMR всех пользователей с привязанным Steam (только в кеш)"""
    try:
        logger.info("Запуск ежечасного обновления MMR")
        from dota_mmr import update_user_mmr
        from database import get_all_users_with_steam, user_cache, BACKUP_DATABASE_URL

        # Fetch users in thread to avoid blocking event loop on DB query
        users = await asyncio.to_thread(get_all_users_with_steam)
        if not users:
            logger.info("Нет пользователей с привязанным Steam для обновления MMR")
            return

        logger.info(f"Обновление MMR для {len(users)} пользователей")
        success_count = 0
        rank_up_users = []  # собираем для уведомлений

        # Pre-fetch all user data in one query to avoid N queries
        users_by_id = {u['telegram_id']: u for u in users}

        for user in users:
            try:
                # Run blocking update_user_mmr in thread pool to avoid blocking event loop
                result = await asyncio.to_thread(update_user_mmr, user['telegram_id'])
                if result and result.get('success'):
                    success_count += 1
                    logger.info(f"MMR updated for {user['telegram_id']}: {result.get('mmr')} MMR")

                    # Sync week stats from pre-fetched data instead of individual DB query
                    db_user = users_by_id.get(user['telegram_id'])
                    if db_user:
                        existing = user_cache.get(user['telegram_id']) or {}
                        user_cache.set(user['telegram_id'], {
                            **existing,
                            'week_games': db_user.get('week_games', 0),
                            'week_wins': db_user.get('week_wins', 0),
                            'week_best_streak': db_user.get('week_best_streak', 0),
                            'week_current_streak': db_user.get('week_current_streak', 0)
                        })

                    if result.get('rank_up'):
                        rank_up_users.append((user, result['rank_up']))
            except Exception as e:
                logger.error(f"Ошибка обновления MMR для {user['telegram_id']}: {e}")

        # Обновляем кеш топа MMR (только в памяти, без записи в БД)
        from database import update_dota_week_top_cache
        update_dota_week_top_cache()

        logger.info(f"MMR обновлён для {success_count}/{len(users)} пользователей")

        # Получаем digest_chat_id из конфига
        digest_chat_id = get_config('digest_chat_id')

        # Отправляем уведомления о ранк-апах
        if digest_chat_id and rank_up_users:
            from dota_mmr import generate_start_card

            for user, rank_info in rank_up_users:
                try:
                    username = user.get('steam_nickname') or user.get('username') or 'Игрок'
                    telegram_id = user.get('telegram_id')
                    message_count = user.get('message_count', 0)
                    rank_tier = user.get('rank_tier', 0)
                    avatar_url = user.get('avatar')

                    # Generate card in thread (blocking image + network ops)
                    card_data = await asyncio.to_thread(
                        generate_start_card,
                        avatar_url=avatar_url,
                        message_count=message_count,
                        username=username,
                        steam_nickname=username,
                        rank_tier=rank_tier,
                        weekly_mvp=0,
                        weekly_top2=0,
                        weekly_top3=0
                    )

                    if card_data:
                        name_display = f"<a href=\"tg://user?id={telegram_id}\">{username}</a>" if telegram_id else username
                        text = f"🎉 {name_display} повысил ранг!\n{rank_info['old_rank']} → {rank_info['new_rank']}"
                        await context.bot.send_photo(chat_id=digest_chat_id, photo=card_data, caption=text, parse_mode="HTML")
                    else:
                        # Fallback
                        name_display = f"<a href=\"tg://user?id={telegram_id}\">{username}</a>" if telegram_id else username
                        text = f"{name_display} повысил ранг!\n{rank_info['old_rank']} → {rank_info['new_rank']}"
                        rank_up_banner_url = "https://i.ibb.co/HLF6JJTw/ji8hy.jpg"
                        await context.bot.send_photo(chat_id=digest_chat_id, photo=rank_up_banner_url, caption=text, parse_mode="HTML")
                except Exception as notify_err:
                    logger.error(f"Ошибка отправки уведомления о ранк-апе: {notify_err}")



    except Exception as e:
        logger.error(f"Ошибка в update_all_mmr_job: {e}")


async def refresh_digest_message(bot):
    """Обновляет кэш дайджеста после каждого броска (только для fissure-дайджеста, тип=0).
    Редактирование сообщения теперь выполняет alternate_digest_job."""
    try:
        digest_chat_id = get_config('digest_chat_id')
        if not digest_chat_id:
            return

        current_type = _digest_state.get("type")
        if current_type is None:
            raw_type = get_config('alternate_digest_type')
            if raw_type is not None:
                current_type = str(raw_type)
            else:
                current_type = "0"
            _digest_state["type"] = current_type

        if current_type != "0":
            logger.debug(f"refresh_digest_message: пропуск, текущий тип = {current_type} (не fissure-дайджест)")
            return

        # Только обновляем кэш消化 данных, редактирование будет через alternate_digest_job
        stats = get_digest_stats()
        _digest_state["digest_data"] = stats
        _digest_state["last_data_update"] = time.time()
        logger.debug("refresh_digest_message: кэш digest_data обновлён, дайджест будет обновлён в следующем тике alternate_digest_job")
    except Exception as e:
        logger.error(f"Ошибка в refresh_digest_message: {e}", exc_info=True)

        logger.debug("Нет alternate_digest_message_id для дайджеста, не создаём")

    except Exception as e:
        logger.error(f"Ошибка в refresh_digest_message: {e}", exc_info=True)


# DEPRECATED: Используйте digest_handler
# async def digest_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     """Ручной запуск утреннего дайджеста в этот чат"""
#     pass


@rate_limit(tokens=1)
async def dota_digest_job(context):
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
        valid_players_sorted = sorted(valid_players, key=lambda p: (p.get('week_wins', 0) - (p.get('week_games', 0) - p.get('week_wins', 0)), p.get('week_games', 0)), reverse=True)

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
        top_games = top_by_net.get('week_games', 0)
        top_wins = top_by_net.get('week_wins', 0)
        top_losses = top_games - top_wins
        top_net = top_wins - top_losses
        top_winrate = round((top_wins / top_games * 100), 1) if top_games > 0 else 0

        bottom_player = bottom_by_net.get('steam_nickname', 'None')
        bottom_id = bottom_by_net.get('telegram_id')
        bottom_games = bottom_by_net.get('week_games', 0)
        bottom_wins = bottom_by_net.get('week_wins', 0)
        bottom_losses = bottom_games - bottom_wins
        bottom_net = bottom_wins - bottom_losses
        bottom_winrate = round((bottom_wins / bottom_games * 100), 1) if bottom_games > 0 else 0

        if top_streak_player:
            streak_player = top_streak_player.get('steam_nickname', 'None')
            streak_wins = top_streak_player.get('week_current_streak', 0)
            streak_id = top_streak_player.get('telegram_id')
        else:
            streak_player = 'None'
            streak_wins = 0
            streak_id = None

        # Форматируем - показываем net wins (разницу)
        top_display = make_clickable(top_player, top_id) if top_player and top_player != "None" else "—"
        bottom_display = make_clickable(bottom_player, bottom_id) if bottom_player and bottom_player != "None" else "—"
        streak_display = make_clickable(streak_player, streak_id) if streak_player and streak_player != "None" and streak_wins > 0 else "—"

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

        # Пропускаем если текст не изменился
        if _digest_state.get("dota_last_text") == text:
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
                _digest_state["dota_last_text"] = text  # кэшируем
                return
            except Exception as e:
                error_str = str(e)
                is_rate_limit = "429" in error_str or "too many requests" in error_str
                if is_rate_limit:
                    logger.warning(f"Rate limited by Telegram in dota_digest, skipping")
                    _digest_state["dota_last_text"] = text
                    return
                if "message is not modified" in error_str.lower():
                    logger.info("Dota дайджест не изменился, пропускаем")
                    _digest_state["dota_last_text"] = text  # кэшируем текущий
                    return
                if "Message to edit not found" in error_str or "message can't be edited" in error_str:
                    logger.info(f"Старое сообщение {last_message_id} удалено или нельзя редактировать, создаём новое")
                    set_config('dota_digest_message_id', None)
                else:
                    logger.info(f"Не удалось редактировать сообщение: {e}")

        # Отправляем новое сообщение
        msg = await bot.send_message(chat_id=digest_chat_id, text=text, parse_mode="HTML")
        set_config('dota_digest_message_id', msg.message_id)
        _digest_state["dota_last_text"] = text  # кэшируем
        logger.info(f"Создан новый Dota дайджест {msg.message_id}")

    except Exception as e:
        logger.error(f"Ошибка в dota_digest_job: {e}", exc_info=True)


# DEPRECATED: Используйте digest_handler
# async def dota_digest_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     """Ручной запуск Dota дайджеста в этот чат"""
#     pass


@rate_limit(tokens=1)
async def alternate_digest_job(context):
    """Чередование утреннего и Dota дайджестов (редактирование существующего, создание нового только при необходимости)"""
    global _last_data_refresh, _data_refresh_interval
    try:
        now = time.time()

        # Проверяем глобальный rate limit
        if is_rate_limited():
            logger.warning(f"alternate_digest_job: skipped - bot is rate limited")
            return

        # Блокировка от параллельного запуска в рамках одного воркера (уменьшена до 5 сек для частых запусков)
        async with _digest_state_lock:
            last_run = _digest_state.get('last_run', 0)
            if now - last_run < 5:
                logger.debug(f"alternate_digest_job: пропуск (запущен {(now - last_run):.1f}с назад)")
                return
            _digest_state['last_run'] = now

            # Проверяем, нужно ли обновить данные из БД (раз в час)
            if now - _digest_state.get("last_data_update", 0) >= DIGEST_DATA_REFRESH_INTERVAL:
                logger.info("alternate_digest_job: обновляем данные из БД")
                # Сбрасываем кеш в database.py чтобы получить свежие данные
                from database import user_cache
                user_cache.set('digest_stats', None)
                user_cache.set('dota_digest_stats', None)
                # Очищаем локальный кеш дайджестов
                _digest_state["digest_data"] = None
                _digest_state["dota_data"] = None
                _digest_state["last_data_update"] = now

            # При первом запуске после деплоя сбрасываем тип на "0"
            if _digest_state.get("last_data_update") == 0:
                _digest_state["type"] = "0"
                set_config('alternate_digest_type', "0")
                logger.info("alternate_digest_job: сброшен тип на 0 после перезапуска")

            logger.info("Запуск alternate_digest_job")

            # Получаем ID чата для дайджеста (из кеша, не БД)
            digest_chat_id = _digest_state.get("chat_id") or get_config('digest_chat_id')
            if digest_chat_id:
                _digest_state["chat_id"] = digest_chat_id
            logger.info(f"alternate_digest_job: digest_chat_id = {digest_chat_id}")
            if not digest_chat_id:
                logger.info("Чат для дайджеста не настроен")
                return

            bot = context.application.bot

        now = time.time()

        # === УМНАЯ СИСТЕМА КЕШИРОВАНИЯ ДАЙДЖЕСТОВ ===
        # Проверяем, нужно ли обновить кеш
        cache = _digest_cache
        should_regenerate = False

        # Быстрая проверка изменений данных каждые 15 секунд
        current_data_hash = get_digest_data_hash()
        data_changed = current_data_hash != cache.get("data_hash")

        # 1. Если кеш пустой - генерируем
        if cache["text"] is None:
            should_regenerate = True
            logger.info("Кеш дайджеста пуст, генерируем новый")

        # 2. Если данные изменились - генерируем
        elif data_changed:
            should_regenerate = True
            logger.info(f"Данные дайджеста изменились (hash: {current_data_hash[:8] if current_data_hash else 'None'}...), обновляем")

        # 3. Если кеш устарел (TTL) - генерируем новый
        elif now - cache["created_at"] > cache["cache_ttl"]:
            should_regenerate = True
            logger.info(f"Кеш дайджеста устарел ({now - cache['created_at']:.0f}с > {cache['cache_ttl']}с), обновляем")

        # 4. Если пришло время сменить тип (rotation) - генерируем
        elif now - cache["created_at"] > cache["rotation_interval"]:
            should_regenerate = True
            logger.info(f"Время сменить тип дайджеста ({cache['rotation_interval']}с), обновляем")

        # 5. Если данные в БД обновились - генерируем
        elif now - _last_data_refresh > _data_refresh_interval:
            should_regenerate = True
            logger.info(f"Данные в БД устарели ({_data_refresh_interval}с), обновляем")

        # Если кеш валиден - используем его и просто меняем тип для отображения
        if not should_regenerate:
            logger.debug(f"Используем кешированный дайджест (создан {now - cache['created_at']:.0f}с назад)")

            # Просто меняем тип для следующего раза
            current_type = cache["type"]
            if current_type == "0":
                next_type = "1"
            else:
                next_type = "0"

            text = cache["text"]

            # Обновляем метаданные
            _digest_state["type"] = next_type
            set_config('alternate_digest_type', next_type)

            # Обновляем хеш данных в кеше если нужно
            if current_data_hash and cache.get("data_hash") != current_data_hash:
                cache["data_hash"] = current_data_hash
                cache["last_data_check"] = now

            logger.debug(f"Переключаем тип: {current_type} -> {next_type} (используем кеш)")

        # Иначе - генерируем новый дайджест
        else:
            # Получаем текущий тип дайджеста из памяти
            current_type = _digest_state.get("type")
            if current_type is None:
                raw_type = get_config('alternate_digest_type')
                if raw_type is not None:
                    current_type = str(raw_type)
                else:
                    current_type = "0"
                _digest_state["type"] = current_type

            logger.info(f"alternate_digest_job: current_type = {current_type}, генерируем новый дайджест")

            # Определяем следующий тип (чередуем)
            if current_type == "0":
                next_type = "1"
            else:
                next_type = "0"

            # Формируем текст в зависимости от типа
            text = None

            if current_type == "0":
                # Фиссур-дайджест
                # Проверяем, нужно ли обновить данные из БД
                if _digest_state.get("digest_data") is None or now - _last_data_refresh > _data_refresh_interval:
                    logger.info("Обновляем данные для фиссур-дайджеста из БД")
                    stats = get_digest_stats()
                    _digest_state["digest_data"] = stats
                    _last_data_refresh = now
                else:
                    stats = _digest_state["digest_data"]

                # Проверяем, есть ли данные
                if stats.get("top_growth", ("None", 0))[0] == "None" and stats.get("top_drop", ("None", 0.0))[0] == "None" and stats.get("top_streak", ("None", 0))[0] == "None":
                    # Загружаем из кеша
                    cached_stats = get_config('fissure_digest_cache')
                    if cached_stats:
                        try:
                            stats = json.loads(cached_stats)
                            logger.info("Загружены кешированные данные для фиссур-дайджеста")
                        except Exception as e:
                            logger.warning(f"Не удалось загрузить кеш фиссур-дайджеста: {e}")

                growth_player, growth_pos = stats.get("top_growth", ("None", 0))
                drop_player, drop_cm = stats.get("top_drop", ("None", 0.0))
                streak_player, streak_len = stats.get("top_streak", ("None", 0))
                growth_id = stats.get("top_growth_id")
                drop_id = stats.get("top_drop_id")
                streak_id = stats.get("top_streak_id")

                # Сохраняем в кеш если есть данные
                if growth_player != "None" or drop_player != "None" or streak_player != "None":
                    try:
                        set_config('fissure_digest_cache', json.dumps(stats))
                        logger.info("Сохранены данные фиссур-дайджеста в кеш")
                    except Exception as e:
                        logger.warning(f"Не удалось сохранить кеш фиссур-дайджеста: {e}")

                growth_display = make_clickable(growth_player, growth_id) if growth_id else growth_player
                drop_display = make_clickable(drop_player, drop_id) if drop_id else drop_player
                streak_display = make_clickable(streak_player, streak_id) if streak_id else streak_player

                parts = []
                if growth_player and growth_player != "None":
                    parts.append(f"🔺{growth_display} +{growth_pos} см")
                else:
                    parts.append("🔺—")
                if drop_player and drop_player != "None":
                    parts.append(f"🔻{drop_display} {drop_cm:.0f} см")
                else:
                    parts.append("🔻—")
                if streak_player and streak_player != "None" and streak_len > 0:
                    parts.append(f"🍀{streak_display}: {streak_len} побед подряд")
                else:
                    parts.append("🍀—")

                text = f"<b>{chr(10).join(parts)}</b>\n\n🗿 Фиссура Дайджест."

            else:
                # Dota-дайджест
                # Проверяем, нужно ли обновить данные из БД
                if _digest_state.get("dota_data") is None or now - _last_data_refresh > _data_refresh_interval:
                    logger.info("Обновляем данные для Dota-дайджеста из БД")
                    mmr_top = get_dota_week_top(limit=10)
                    _digest_state["dota_data"] = mmr_top
                    _last_data_refresh = now
                else:
                    mmr_top = _digest_state["dota_data"]

                dota_text = None
                if not mmr_top:
                    logger.info("Нет данных для Dota дайджеста")
                    # Fallback на фиссур-дайджест
                    next_type = "0"
                else:
                    valid_players = [p for p in mmr_top if p.get('week_games', 0) >= 1]
                    if not valid_players or len(valid_players) < 2:
                        logger.info("Нет игроков с 5+ играми или менее 2 игроков для Dota дайджеста")
                        next_type = "0"
                    else:
                        valid_players_sorted = sorted(valid_players, key=lambda p: (p.get('week_wins', 0) - (p.get('week_games', 0) - p.get('week_wins', 0)), p.get('week_games', 0)), reverse=True)

                        top_by_net = valid_players_sorted[0]
                        # Для bottom выбираем игрока с наименьшим net wins, отличного от top
                        for p in reversed(valid_players_sorted):
                            if p.get('telegram_id') != top_by_net.get('telegram_id'):
                                bottom_by_net = p
                                break
                        else:
                            # Если все одинаковые, берём последнего
                            bottom_by_net = valid_players_sorted[-1]

                        players_with_streak = [p for p in valid_players if p.get('week_current_streak', 0) > 0]
                        top_streak_player = max(players_with_streak, key=lambda p: p.get('week_current_streak', 0)) if players_with_streak else None

                        if top_by_net:
                            top_player = top_by_net.get('steam_nickname', 'None')
                            top_id = top_by_net.get('telegram_id')
                            top_games = top_by_net.get('week_games', 0)
                            top_wins = top_by_net.get('week_wins', 0)
                            top_losses = top_games - top_wins
                            top_winrate = round((top_wins / top_games * 100), 1) if top_games > 0 else 0

                            bottom_player = bottom_by_net.get('steam_nickname', 'None')
                            bottom_id = bottom_by_net.get('telegram_id')
                            bottom_games = bottom_by_net.get('week_games', 0)
                            bottom_wins = bottom_by_net.get('week_wins', 0)
                            bottom_losses = bottom_games - bottom_wins
                            bottom_winrate = round((bottom_wins / bottom_games * 100), 1) if bottom_games > 0 else 0

                            streak_player = top_streak_player.get('steam_nickname', 'None') if top_streak_player else 'None'
                            streak_wins = top_streak_player.get('week_current_streak', 0) if top_streak_player else 0
                            streak_id = top_streak_player.get('telegram_id') if top_streak_player else None

                            if top_player and top_player != "None":
                                top_part = f"🔺{make_clickable(top_player, top_id)}: {top_wins}W/{top_losses}L ≈{top_winrate}%"
                            else:
                                top_part = "🔺—"

                            if bottom_player and bottom_player != "None":
                                bottom_part = f"🔻{make_clickable(bottom_player, bottom_id)}: {bottom_wins}W/{bottom_losses}L ≈{bottom_winrate}%"
                            else:
                                bottom_part = "🔻—"

                            if streak_player and streak_player != "None" and streak_wins > 0:
                                streak_part = f"🔸{make_clickable(streak_player, streak_id)}: {streak_wins} игр подряд"
                            else:
                                streak_part = "🔸—"

                            dota_text = f"<b>{top_part}\n{bottom_part}\n{streak_part}</b>\n\n🦞 Дота Дайджест."

                        if dota_text is None:
                            next_type = "0"

                text = dota_text

            # Если не удалось сгенерировать текст - используем fallback
            if text is None:
                logger.info("Не удалось сгенерировать дайджест, используем fallback")
                text = "<b>📊 Данные для дайджеста пока не доступны</b>\n\nПопробуйте позже!"
                next_type = "0"

            # === СОХРАНЯЕМ В КЕШ ===
            cache["text"] = text
            cache["type"] = current_type
            cache["created_at"] = now
            cache["data_hash"] = current_data_hash  # Сохраняем хеш данных
            cache["last_data_check"] = now

            logger.info(f"Дайджест сгенерирован и сохранен в кеш (тип: {current_type}, hash: {current_data_hash[:8] if current_data_hash else 'None'}...)")

        # === ОТПРАВКА ДАЙДЖЕСТА ===
        # Анти-спам: проверяем, не было ли недавнего обновления дайджеста
        last_created_str = get_config('alternate_digest_last_created')
        last_created = float(last_created_str) if last_created_str and last_created_str.strip() else 0
        time_since_last = time.time() - last_created
        if time_since_last < 10:  # 10 секунд защиты от гонки
            logger.info(f"Пропускаем - дайджест обновлен {time_since_last:.0f} сек назад")
            return

        # Пропускаем редактирование если текст не изменился
        last_text = _digest_state.get("last_text")
        if last_text == text:
            logger.debug("Текст дайджеста не изменился, пропускаем редактирование")
            return

        # Пробуем отредактировать существующее сообщение
        last_message_id = get_config('alternate_digest_message_id')
        logger.info(f"alternate_digest_job: last_message_id = {last_message_id}")
        logger.info(f"alternate_digest_job: text = {text[:100]}...")
        
        # Сохраняем ID текущего сообщения из БД для защиты от удаления в cleanup
        stored_msg_id_for_cleanup = last_message_id
        edited = False
        # Try to edit existing message
        if last_message_id:
            logger.info(f"alternate_digest_job: attempting to edit message {last_message_id}")
            try:
                msg_id_int = int(last_message_id)
                if msg_id_int <= 0:
                    logger.warning(f"Invalid alternate_digest_message_id: {last_message_id}")
                    set_config('alternate_digest_message_id', None)
                    last_message_id = None
                else:
                    # Try to edit - start with text edit
                    try:
                        await bot.edit_message_text(
                            chat_id=int(digest_chat_id),
                            message_id=msg_id_int,
                            text=text,
                            parse_mode="HTML"
                        )
                        logger.info(f"Updated text alternate digest {last_message_id}")
                        edited = True
                        _digest_state["type"] = next_type
                        set_config('alternate_digest_type', next_type)
                        _digest_state["last_text"] = text
                        set_config('alternate_digest_last_created', str(time.time()))
                    except Exception as e_caption:
                        # If text edit fails (photo message), try caption edit
                        error_str = str(e_caption).lower()
                        if "no text" in error_str or "message is not modified" in error_str:
                            try:
                                await bot.edit_message_caption(
                                    chat_id=int(digest_chat_id),
                                    message_id=msg_id_int,
                                    caption=text,
                                    parse_mode="HTML"
                                )
                                logger.info(f"Updated caption alternate digest {last_message_id}")
                                edited = True
                                _digest_state["type"] = next_type
                                set_config('alternate_digest_type', next_type)
                                _digest_state["last_text"] = text
                                set_config('alternate_digest_last_created', str(time.time()))
                            except Exception as e2:
                                logger.warning(f"Caption edit also failed: {e2}")
                                edited = False
                        else:
                            # Re-raise if it's another error
                            raise
            except (ValueError, TypeError) as e:
                logger.warning(f'Invalid alternate_digest_message_id format: {last_message_id}, error: {e}')
                set_config('alternate_digest_message_id', None)
                last_message_id = None
            except Exception as e:
                error_str = str(e).lower()
                is_rate_limit = '429' in error_str or 'too many requests' in error_str or 'retry after' in error_str
                logger.info(f'Edit error: {e}')
                if is_rate_limit:
                    logger.warning(f'Rate limited by Telegram, skipping edit')
                    _digest_state['last_text'] = text
                    _digest_state['last_run'] = 0
                    return
                if 'bad request' in error_str:
                    logger.warning(f'Bad request for message {last_message_id}, resetting message_id')
                    set_config('alternate_digest_message_id', None)
                    last_message_id = None
                    edited = False
                elif 'message to edit not found' in error_str or 'message can\'t be edited' in error_str:
                    logger.info(f'Old message {last_message_id} deleted, creating new')
                    set_config('alternate_digest_message_id', None)
                    last_message_id = None
                elif 'message is not modified' in error_str:
                    logger.info(f'Message not modified, skipping')
                    edited = True
                    _digest_state['type'] = next_type
                    set_config('alternate_digest_type', next_type)
                    _digest_state['last_text'] = text

        logger.info(f"alternate_digest_job: edited = {edited}, will create new message")
        if not edited:
            # Проверяем анти-спам до генерации баннера (быстрый выход)
            last_created_str = get_config('alternate_digest_last_created')
            last_created = float(last_created_str) if last_created_str and last_created_str.strip() else 0
            time_since_last = time.time() - last_created
            if time_since_last < 60:
                logger.info(f"Пропускаем - прошло всего {time_since_last:.0f} сек с последнего создания")
                return

            # Генерируем или используем кешированный геро-мета баннер (обновление раз в 48 часов)
            hero_meta_banner = None
            current_time = time.time()
            last_meta_update = _digest_state.get("last_hero_meta_update", 0)
            cached_image = _digest_state.get("hero_meta_image")

            if cached_image is not None and (current_time - last_meta_update) < HERO_META_REFRESH_INTERVAL:
                hero_meta_banner = cached_image
                logger.info(f"Using cached hero meta banner (age: {current_time - last_meta_update:.0f}s, refresh in {HERO_META_REFRESH_INTERVAL - (current_time - last_meta_update):.0f}s)")
            else:
                try:
                    from hero_meta import get_hero_meta_image
                    import asyncio
                    try:
                        hero_meta_banner = await asyncio.wait_for(get_hero_meta_image(), timeout=45.0)
                    except asyncio.TimeoutError:
                        logger.warning("Hero meta banner generation timed out after 45 seconds")
                        hero_meta_banner = None
                    if hero_meta_banner:
                        logger.info("Hero meta banner generated for digest")
                        # Обновляем кеш и timestamp
                        _digest_state["hero_meta_image"] = hero_meta_banner
                        _digest_state["last_hero_meta_update"] = current_time
                    else:
                        logger.warning("Hero meta banner generation returned None")
                except Exception as e:
                    logger.warning(f"Could not generate hero meta banner: {e}")
                    hero_meta_banner = None

                # Fallback на старый кеш, если генерация не удалась
                if hero_meta_banner is None and cached_image is not None:
                    logger.warning("Using stale cached hero meta image due to generation failure")
                    hero_meta_banner = cached_image

            # Удаляем старое сообщение если есть
            if last_message_id:
                try:
                    msg_id_int = int(last_message_id)
                    if msg_id_int > 0:
                        await bot.delete_message(chat_id=int(digest_chat_id), message_id=msg_id_int)
                        logger.info(f"Удалено старое сообщение {last_message_id}")
                except Exception as e:
                    logger.debug(f"Старое сообщение уже удалено: {e}")
            set_config('alternate_digest_message_id', None)

            # Создаём новое сообщение
            try:
                from io import BytesIO
                if hero_meta_banner:
                    photo_buf = BytesIO(hero_meta_banner)
                    photo_buf.name = "hero_meta_banner.png"
                    msg = await bot.send_photo(
                        chat_id=int(digest_chat_id),
                        photo=photo_buf,
                        caption=text,
                        parse_mode="HTML"
                    )
                    logger.info(f"Создан новый дайджест с фото {msg.message_id}")
                else:
                    msg = await bot.send_message(
                        chat_id=int(digest_chat_id),
                        text=text,
                        parse_mode="HTML"
                    )
                    logger.info(f"Создан новый дайджест (текст) {msg.message_id}")

                set_config('alternate_digest_message_id', str(msg.message_id))
                set_config('alternate_digest_last_created', str(time.time()))
                set_config('alternate_digest_type', next_type)
                _digest_state["type"] = next_type
                _digest_state["last_text"] = text
                logger.info(f"alternate_digest_job: saved new message_id = {msg.message_id}")

                # Закрепляем новое сообщение
                try:
                    # Открепляем ВСЕ закреплённые сообщения перед закреплением нового
                    # Это решает проблему гонки между воркерами — только последний останется
                    try:
                        await bot.unpin_all_chat_messages(chat_id=int(digest_chat_id))
                        logger.info("Откреплены все предыдущие закреплённые сообщения")
                    except Exception as e:
                        logger.debug(f"Не удалось открепить все сообщения: {e}")

                    await bot.pin_chat_message(chat_id=digest_chat_id, message_id=msg.message_id, disable_notification=True)
                    logger.info(f"Дайджест {msg.message_id} закреплён")

                    # Удаляем системное сообщение о закрепе, если есть права
                    logger.info(f"Проверка прав на удаление системного сообщения для chat_id={digest_chat_id}")
                    can_del = await bot_can_delete(bot, digest_chat_id)
                    logger.info(f"bot_can_delete result: {can_del}")
                    if can_del:
                        try:
                            logger.info("Попытка удаления системного сообщения о закрепе...")
                            time.sleep(0.5)
                            logger.info("Задержка 0.5с завершена, ищем системное сообщение")

                            # Системное сообщение о закрепе имеет message_id = msg.message_id + N (обычно +1 или +2)
                            pin_keywords = ('закрепил', 'закрепила', 'закрепили', 'pinned')
                            found = False
                            for offset in range(1, 6):
                                candidate_id = msg.message_id + offset
                                try:
                                    candidate_msg = await bot.get_message(chat_id=int(digest_chat_id), message_id=candidate_id)
                                    if hasattr(candidate_msg, 'text') and candidate_msg.text:
                                        text_lower = candidate_msg.text.lower().replace('\u200b', '').replace('\u2060', '')
                                        logger.info(f"Проверяем msg {candidate_id}: text='{candidate_msg.text[:50]}'")
                                        if any(kw in text_lower for kw in pin_keywords):
                                            await bot.delete_message(chat_id=int(digest_chat_id), message_id=candidate_id)
                                            logger.info(f"✅ Удалено системное сообщение о закрепе {candidate_id}")
                                            found = True
                                            break
                                except Exception as e:
                                    if "message not found" in str(e).lower() or "message to delete not found" in str(e).lower():
                                        logger.debug(f"Сообщение {candidate_id} не найдено, прекращаем поиск")
                                        break
                                    else:
                                        logger.debug(f"Ошибка при проверке сообщения {candidate_id}: {e}")
                            if not found:
                                logger.info("Системное сообщение о закрепе не найдено среди следующих сообщений")

                            # Дополнительно: удаляем другие дайджесты бота в узком диапазоне ID вокруг только что созданного
                            # Это очищает возможные дубликаты от гонки
                            # Но сохраняем текущее сообщение из БД (ID из момента входа в блок), чтобы не удалить его в гонке
                            try:
                                saved_orig_msg_id = int(stored_msg_id_for_cleanup) if stored_msg_id_for_cleanup else None
                                for offset in range(-20, 0):  # проверяем до 20 сообщений до
                                    old_id = msg.message_id + offset
                                    # Не удаляем текущее сохранённое в БД сообщение
                                    if saved_orig_msg_id and old_id == saved_orig_msg_id:
                                        continue
                                    if old_id <= 0:
                                        continue
                                    try:
                                        old_msg = await bot.get_message(chat_id=int(digest_chat_id), message_id=old_id)
                                        if hasattr(old_msg, 'from_user') and old_msg.from_user and old_msg.from_user.is_bot:
                                            if hasattr(old_msg, 'text') and old_msg.text:
                                                txt = old_msg.text.lower()
                                                if ('фиссур' in txt and ('дайджест' in txt or 'dota' in txt)) or ('dota' in txt and 'дайджест' in txt):
                                                    await bot.delete_message(chat_id=int(digest_chat_id), message_id=old_id)
                                                    logger.info(f"Удалён дублирующий дайджест {old_id} (offset {offset})")
                                    except Exception:
                                        pass  # ignore not found etc.
                            except Exception as e:
                                logger.debug(f"Ошибка при cleanup соседних дайджестов: {e}")

                        except Exception as e:
                            logger.info(f"Ошибка при удалении системного сообщения: {e}", exc_info=True)
                    else:
                        logger.info("❌ Нет прав на удаление системного сообщения о закрепе")
                except Exception as e:
                    logger.debug(f"Не удалось закрепить: {e}")
            finally:
                pass

    except Exception as e:
        logger.error(f"Ошибка в alternate_digest_job: {e}", exc_info=True)

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
    15: ["🔥 МУЛЬТИБОНУС! +15 СМ!", "💥 ОТЛИЧНЫЙ РЕЗУЛЬТАТ! +15 СМ!", "🚀 РАСТИ! +15 СМ!"],
    12: ["💪 СИЛЬНО! +12 СМ!", "🎮 УЛУЧШЕНИЕ! +12 СМ!"],
    10: ["🌟 ЛЕГЕНДА! +10 см!", "🔥 ОГОНЬ! +10 см!", "🌟 ПЕРВАЯ КРОВЬ! +10 СМ!", "🎮 УБИЙСТВЕННАЯ СЕРИЯ! +10 СМ!"],
    9: ["📈 РАСТИ! +9 СМ!", "💪 НЕПЛОХО! +9 СМ!"],
    8: ["📈 ХОРОШО! +8 СМ!", "💪 ЕЩЁ! +8 СМ!"],
    7: ["👍 ЕСТЬ! +7 СМ!", "📈 НАРАЩИВАЕМ! +7 СМ!"],
    6: ["👍 ЕСТЬ! +6 СМ!", "📈 НАРАЩИВАЕМ! +6 СМ!"],
    5: ["🎉 УРА! +5 см!", "👍 ОТЛИЧНО! +5 см!", "✅ НОРМ! +5 СМ!", "👍 КРАСАВА! +5 СМ!"],
    4: ["✅ НЕПЛОХО! +4 СМ!", "💪 ПОТИХОНЬКУ! +4 СМ!"],
    3: ["😊 НЕПЛОХО! +3 см", "📈 РАСТЁМ! +3 см", "💪 НА! +3 СМ", "🔥 В ОГНЕ! +3 СМ"],
    2: ["✅ ЕСТЬ! +2 СМ!", "💪 ШАГ! +2 СМ!"],
    1: ["✅ OK! +1 см", "💪 ЕСТЬ РОСТ! +1 см", "🙄 ПОВЕЗЛО! +1 СМ", "🤔 МОГЛО БЫТЬ ХУЖЕ! +1 СМ"],
    0: ["❌ БЕЗ ИЗМЕНЕНИЙ", "💤 СТОИМ НА МЕСТЕ", "❌ НИЧЬЯ", "💤 АФК?"],
    -1: ["🤔 НЕМНОГО -1 см", "📉 МИНУС -1 см", "😬 ОЙ! -1 СМ", "💀 КОРМ! -1 СМ"],
    -2: ["📉 МИНУС -2 СМ", "😬 НЕМНОГО БОЛЬНО! -2 СМ"],
    -3: ["😬 ОЙ... -3 см", "⬇️ УПАЛ -3 см", "🤕 ДЕНАЙ! -3 СМ", "☠️ НАРЖАЛ! -3 СМ"],
    -4: ["⬇️ СКОЛЬЗИМ! -4 СМ", "😬 НЕУДАЧА! -4 СМ"],
    -5: ["😢 БОЛЬНО -5 см...", "💔 НЕУДАЧА -5 см", "💀 ПОПАЛ! -5 СМ...", "🎮 ГГ ВП... -5 СМ"],
    -6: ["💀 ПОПАЛ! -6 СМ...", "⬇️ УПАЛ! -6 СМ"],
    -7: ["😢 ОЙ! -7 СМ...", "💔 БОЛЬНО! -7 СМ"],
    -8: ["😢 НЕПРИЯТНО! -8 СМ...", "⬇️ КАПУТ! -8 СМ"],
    -9: ["😢 БОЛЬНО! -9 СМ...", "💀 КРИТИЧЕСКИЙ УРОН! -9 СМ"],
    -10: ["💥 КАТАСТРОФА! -10 см!!!", "🌋 АПОКАЛИПСИС! -10 см!!!", "😵 СЕРВЕР УПАЛ! -10 СМ!!!", "💥 ДИСКОННЕКТ! -10 СМ!!!"],
    -11: ["💥 УЖАС! -11 СМ!!!", "☠️ КРАШ! -11 СМ!!!"],
    -12: ["💀 БОЛЬНО! -12 СМ!!!", "🌋 ВУЛКАН! -12 СМ!!!"],
    -13: ["💥 ПОЛНЫЙ КРАХ! -13 СМ!!!", "☠️ ФИНАЛ! -13 СМ!!!"],
    -14: ["💀 НЕВОССТАНОВИМО! -14 СМ!!!", "🌋 АПОКАЛИПСИС! -14 СМ!!!"],
    -15: ["💀 ФАТАЛЬНЫЙ УРОН! -15 СМ!!!", "🌋 КОНЕЦ! -15 СМ!!!", "☠️ ОТПРАВЛЕН В СТАРТ! -15 СМ!!!"],
    75: ["🏆 ЛЕГЕНДАРНЫЙ РОЛЛ!!! +75 СМ!!!", "💥 МЕГАДРОП!!! +75 СМ!!!", "🎯 ШОТ! +75 СМ!!!"]
}

ROLL_MEMES = {
    75: [
        "👁️ «Я ВИДЕЛ БУДУЩЕЕ — ТЕБЯ ТАМ НЕТ» (Войд)",
        "⚔️ «ЗА НАЙТСИЛЬВЕР!» (Мирана)",
        "🌑 «ИЗ МРАКА!» (НС)"
    ],
    50: [
        "💥 «ХАОС ДАНК!» (СиКей)",
        "🩹 «РАЗЛОМ ИСЦЕЛЯЕТСЯ!» (СК)",
        "🩸 «ЦАРСТВО КРОВИ!» (Блад)"
    ],
    30: [
        "🔥 «ДУХАМИ ЗАКЛИНАЮ!» (Эмбер)",
        "🛡️ «ЗА МОЙ НАРОД!» (Свен)",
        "⚜️ «КЛЯТВА ПРИНЕСЕНА!» (Омни)"
    ],
    20: [
        "🌹 «ПРОКЛЯТИЕ РОЗЫ!» (КоП)",
        "🔨 «Я НЕСУ МОЛОТ!» (Омни)",
        "🗡️ «ОДИН КЛИНОК — ОДНА ЦЕЛЬ» (Джагг)"
    ],
    15: [
        "✨ «Я — СВЕТ!» (КотЛ)",
        "🏹 «СТРАННИЦА ВОЗВРАЩАЕТСЯ» (ВР)",
        "😈 «ПЛАЧЬ ЕЩЁ!» (ЛЦ)"
    ],
    10: [
        "🚫 «МАГИЯ — ОТСТОЙ!» (АМ)",
        "👑 «ЗА ПОСЛЕДНЕГО КОРОЛЯ!» (ВК)",
        "🕳️ «БЕЗДНА ЗОВЁТ» (Войд)"
    ],
    9: [
        "👻 «ЗА ТВОЕЙ СПИНОЙ!» (Рики)",
        "🧈 «МЯГКИЙ, КАК МАСЛО» (ПА)",
        "🕷️ «ГНЕЗДО ЖДЁТ» (Бруд)"
    ],
    5: [
        "🍖 «СВЕЖЕЕ МЯСО!» (Падж)",
        "🐟 «ОХОТА НАЧИНАЕТСЯ» (Сларк)",
        "🐻 «КАЛЕЧИТЬ! УБИВАТЬ!» (Урса)"
    ],
    1: [
        "🪨 «БРОСАЙ МЕНЯ!» (Тайни)",
        "🪙 «ВЕЗУЧАЯ МОНЕТКА» (Гамблер)",
        "🧪 «МАЛЫЕ НАЧАЛА» (Мипо)"
    ],
    0: [
        "💤 «Я ОТДОХНУ ТЕПЕРЬ» (Висп)",
        "⏳ «ДРЕВНИЕ ЖДУТ» (Аганим)",
        "🧘 «СОЗЕРЦАНИЕ» (Элдер Т)"
    ],
    -1: [
        "😔 «Я ПОДВЁЛ» (Свен)",
        "😩 «НЕ ТАК» (Зевс)",
        "🌫️ «ВИДЕНИЕ ТУСКНЕЕТ» (Войд)"
    ],
    -5: [
        "🥶 «ПЛАМЯ ПОГАСЛО» (Лина)",
        "😖 «Я... СПОТКНУЛСЯ» (Эмбер)",
        "💔 «МОЯ ЧЕСТЬ... РАЗБИТА» (ЛЦ)"
    ],
    -10: [
        "🚨 «ДРЕВНИЙ АТАКУЮТ» (диктор)",
        "🏃‍♂️💨 «КОМАНДА ТЕБЯ БРОСИЛА» (игра)",
        "🌚 «ПОБЕДА ТЬМЫ» (Тьма)"
    ],
    -15: [
        "😭 «СВЕТ ПОВЕРЖЕН» (диктор)",
        "🎭 «ТВОЙ ММР — ЛОЖЬ» (Crownfall)",
        "🕳️ «ОБРАТНО В РАЗЛОМ» (СК)"
    ],
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
    "Присоединился! Падж облизнулся на тебя, свежее мясо🍖",
    "Добро пожаловать! Свен хлопнул тебя по плечу👏",
    "Не зевай! Сларк шепчет тебе на ухо🤫",
    "Заходи! Бруда раскинула сеть для тебя🕸️",
    "Открой рундук! Джагернаут, дал тебе клинок⚔️",
    "Привет! Zeus сверкнул молнией⚡",
    "Погнали! Spirit Breaker тебя прокатит🚕",
    "Здарова! Tusk дал тебе в плечо кулачищем🐧",
    "Ой, а ты кто? Axe почесал тебе затылок секирой🪓",
    "Ой, а ты кто? Morphling умыл тебе лицо💧",
    "Не зевай! Phantom Assassin хочет пересчитать твой ребра💀",
    "Здарова! Slardar брызнул слюной🐟",
    "Чего уставился? Clinkz натянул тебе тетиву🏹",
    "Привет! Faceless Void остановил время на секунду🕰️",
    "Будь как дома! Wisp засветился у тебя за спиной💫",
    "Не зевай! Techies Три, две, одна — улыбнись🧨",
    "Чего встал? Primal Beast топнул — пол треснул🦍",
    "Сладкий! Queen of Pain услышала твой голос👑",
]


# =====================
# 🔧 УТИЛИТЫ
# =====================

def make_clickable(name, user_id, max_length=12):
    """Создать кликабельный никнейм для Telegram"""
    if name and name != "None" and user_id:
        display_name = name
        try:
            from database import user_cache, get_user
            # Сначала пробуем из кеша
            cached = user_cache.get(int(user_id))
            if cached:
                display_name = cached.get('steam_nickname') or cached.get('username') or name
            else:
                # Пробуем из БД напрямую
                db_user = get_user(int(user_id))
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

        return f"<a href=\"tg://user?id={user_id}\">{display_name}</a>"
    return name if name and name != "None" else "—"

# Track last bot message per user per chat for cleanup
last_bot_message = {}  # {chat_id: {user_id: message_id}}


async def delete_last_bot_message(bot, chat_id, user_id):
    """Delete all tracked bot messages for this user in this chat immediately"""
    if chat_id in last_bot_message and user_id in last_bot_message[chat_id]:
        msg_ids = last_bot_message[chat_id][user_id]
        # Поддерживаем оба формата: список и одиночный ID
        if not isinstance(msg_ids, list):
            msg_ids = [msg_ids]

        # Удаляем дубликаты чтобы избежать повторного удаления
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
                error_str = str(e).lower()
                if "message to delete not found" in error_str or "bad request" in error_str or "not found" in error_str:
                    logger.debug(f"Message {msg_id} already deleted or invalid in chat {chat_id}: {e}")
                else:
                    logger.warning(f"Could not delete last bot message {msg_id}: {e}")

        # Всегда очищаем после попытки (даже если удалить не получилось)
        try:
            del last_bot_message[chat_id][user_id]
            # Очищаем пустые записи чата
            if not last_bot_message[chat_id]:
                del last_bot_message[chat_id]
        except KeyError:
            pass


def set_last_bot_message(chat_id, user_id, message_id):
    """Set the last bot message for this user in this chat"""
    # Skip invalid message IDs
    if not isinstance(message_id, int) or message_id <= 0:
        logger.debug(f"set_last_bot_message: skipping invalid message_id={message_id}")
        return

    if chat_id not in last_bot_message:
        last_bot_message[chat_id] = {}
    last_bot_message[chat_id][user_id] = message_id


def add_bot_message(chat_id, user_id, message_id):
    """Add bot message to track list for this user in this chat"""
    # Skip invalid message IDs
    if not isinstance(message_id, int) or message_id <= 0:
        logger.debug(f"add_bot_message: skipping invalid message_id={message_id}")
        return

    if chat_id not in last_bot_message:
        last_bot_message[chat_id] = {}
    # Сохраняем последние 2 сообщения для удаления
    if isinstance(last_bot_message[chat_id].get(user_id), list):
        msg_list = last_bot_message[chat_id][user_id]
        msg_list.append(message_id)
        # Оставляем только последние 2 сообщения
        last_bot_message[chat_id][user_id] = msg_list[-2:]
    else:
        # Конвертируем старый формат в список
        last_bot_message[chat_id][user_id] = [message_id]

    # Cleanup memory: ограничить размер словаря чтобы не было утечки памяти
    if len(last_bot_message) > 500:
        last_bot_message.clear()
        logger.warning("Cleared last_bot_message cache (exceeded 500 entries)")


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
    # Расширенный диапазон: от -15 до +75
    weighted_rolls = [
        (-15, 3), (-10, 5), (-7, 7), (-5, 8), (-3, 7), (-1, 5), (0, 5),
        (1, 5), (3, 7), (5, 8), (7, 7), (10, 8), (15, 6), (20, 5),
        (30, 4), (50, 2), (75, 1)
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


def calculate_multicast(dice_value: int) -> tuple[int, str]:
    """Вычисляет множитель и текст для multicast по значению dice (1-64)"""
    if dice_value == 64:
        return 4, "\n🎰🎰🎰 <b>ДЖЕКПОТ!!!</b>\n🗣️ Ogre Magi <i>«КАКОВЫ ШАНСЫ?!»</i>"
    elif dice_value >= 48:  # 49-64
        return 3, f"\n{random.choice(MULTICAST_TEXTS[3])}"
    elif dice_value >= 16:  # 16-48
        return 2, f"\n{random.choice(MULTICAST_TEXTS[2])}"
    else:  # 1-15 - обычный ролл без мультикаста
        return 1, ""


# ── Мультикаст (каскадный) ───────────────────────────────────────────
# Шансы загружаются из bot_config, дефолты здесь
MULTICAST_DEFAULT_CHANCE = 0.15
MULTICAST_CASCADE = [0.75, 0.50, 0.40]  # [не используется, ×3 шанс, ×4 шанс]

ZEUS_DEFAULT_CHANCE = 0.05
ZEUS_ICON_URL = "https://cdn.cloudflare.steamstatic.com/apps/dota2/images/dota_react/heroes/icons/zuus.png"

# Выходной бонус
WEEKEND_BONUS_MULTIPLIERS = [1.5, 2, 2.5]

# Тексты дайджестов
MORNING_DIGEST_HEADER = "🌅ФИССУРА ДАЙДЖЕСТ"
MORNING_DIGEST_FOOTER = "🔺 = рост позиций в топе\n🔻 = топ падение\n🍀 = текущий стрик побед"
DOTA_DIGEST_HEADER = "🎮 DOTA ДАЙДЖЕСТ 📊"
DOTA_DIGEST_FOOTER = "🔺 = лучший винрейт за неделю\n🔻 = худший винрейт за неделю\n🔸 = текущий стрик побед"
# # WEEKLY_DIGEST_HEADER удалён

# Ожидание анимации dice
DICE_ANIMATION_DELAY = 1.0

# URL баннеров
COOLDOWN_BANNER_URL = "https://i.ibb.co/FkzCZxNG/m-Yqbu.jpg"
PROFILE_BANNER_URL = "https://i.ibb.co/n8g8yQYt/dasdsadasdsadasdsad.png"
TOP_BANNER_URL = "https://i.ibb.co/1fbJD2hb/l-Ij20.jpg"
TOPMMR_BANNER_URL = "https://i.ibb.co/CsbCfzTz/Tv-Sd2.jpg"
LINK_BANNER_URL = "https://i.ibb.co/0jdSyXWx/MZXz-H.jpg"
SETDIGEST_BANNER_URL = "https://i.ibb.co/LXsGsfxZ/213.png"

# Кеш шансов (обновляется раз в минуту)
_event_chances_cache = {"ts": 0, "multicast": MULTICAST_DEFAULT_CHANCE, "zeus": ZEUS_DEFAULT_CHANCE}

# Spam protection
USER_PROCESSING_TTL = 30  # секунд
BOT_CAN_DELETE_TTL = 3600  # 1 час
JOB_COOLDOWN = 30  # секунд между запусками job
WEEKLY_JOB_COOLDOWN = 60  # секунд между запусками weekly job

def get_event_chances():
    """Получить шансы событий из bot_config с кешированием"""
    now = time.time()
    if now - _event_chances_cache["ts"] < 60:
        return _event_chances_cache["multicast"], _event_chances_cache["zeus"]

    try:
        mc = float(get_config("multicast_chance", MULTICAST_DEFAULT_CHANCE))
        ze = float(get_config("zeus_chance", ZEUS_DEFAULT_CHANCE))
        _event_chances_cache.update({"ts": now, "multicast": mc, "zeus": ze})
        return mc, ze
    except Exception:
        return MULTICAST_DEFAULT_CHANCE, ZEUS_DEFAULT_CHANCE

# Счётчики событий (persistent через bot_config)
STATS_KEYS = ["rolls", "multicast", "zeus", "multicast_x2", "multicast_x3", "multicast_x4"]

# Буфер инкрементов — пишем в БД пачкой
_stat_buffer = {}
_stat_flush_timer = None


def increment_stat(key):
    """Инкрементировать счётчик в буфере (пишется в БД после броска)"""
    if key in STATS_KEYS:
        _stat_buffer[key] = _stat_buffer.get(key, 0) + 1


async def flush_stat_buffer():
    """Записать накопленные счётчики в БД атомарно"""
    if not _stat_buffer:
        return
    try:
        for key, delta in _stat_buffer.items():
            # Атомарный инкремент: UPDATE value = value + delta (без read-modify-write)
            try:
                from database import batch_increment_config
                batch_increment_config(f"stat_{key}", delta)
            except ImportError:
                # Fallback: обычный read-modify-write
                try:
                    val = int(get_config(f"stat_{key}", 0)) + delta
                except (ValueError, TypeError):
                    val = delta
                set_config(f"stat_{key}", str(val))
        _stat_buffer.clear()
    except Exception as e:
        logger.error(f"flush_stat_buffer error: {e}")


def _load_stats():
    """Загрузить счётчики из буфера + БД"""
    stats = {}
    for key in STATS_KEYS:
        try:
            buf = _stat_buffer.get(key, 0)
            db_val = int(get_config(f"stat_{key}", 0))
            stats[key] = db_val + buf
        except (ValueError, TypeError):
            stats[key] = _stat_buffer.get(key, 0)
    return stats


def get_event_stats_text():
    """Текст со статистикой событий"""
    stats = _load_stats()
    total = stats["rolls"]
    if total == 0:
        return ""
    mc = stats["multicast"]
    ze = stats["zeus"]
    mc_pct = mc / total * 100 if total else 0
    ze_pct = ze / total * 100 if total else 0
    return (
        f"📊 События (всего бросков: {total}):\n"
        f"  👹 Мулькаст: {mc} ({mc_pct:.1f}%) — x2: {stats['multicast_x2']}, x3: {stats['multicast_x3']}, x4: {stats['multicast_x4']}\n"
        f"  ⚡ Зевс: {ze} ({ze_pct:.1f}%)"
    )


MULTICAST_TEXTS = {
    2: [
        "🧙‍♂️ «Эй, ты это видел? Ну конечно не видел, ты же тупой!»",
        "🧙‍♂️ «Одного раза мало? А два раза — в самый раз!»",
        "🧙‍♂️ «Я сказал — ещё раз! А ты что хотел?»",
        "🧙‍♂️ «Смотри сюда, сейчас опять будет! Или не будет? Будет!»",
        "🧙‍♂️ «Это не магия, это чистая удача. А удача — это тоже скилл!»"
    ],
    3: [
        "🧙‍♂️ «Три раза! Три! Считай, если умеешь. Один, два, три! Во!»",
        "🧙‍♂️ «Огр — сила! А два огра — три силы! Не понял? Сам не понял, но звучит круто!»",
        "🧙‍♂️ «Где твоя мана? А у нас есть! Потому что мы умные. Ну, умнее тебя точно.»",
        "🧙‍♂️ «Это не повезло, это мастерство. Мастерство быть везучим! Ха-ха!»",
        "🧙‍♂️ «Мы говорили, что мы великие? Нет? Ну, теперь говорим. МЫ ВЕЛИКИЕ!»"
    ],
    4: [
        "🧙‍♂️ «Четыре! Четыре раза, дурак! Наша дубина магии круче твоего посоха!»",
        "🧙‍♂️ «Кто тут главный волшебник? Я! А я? И я! Мы оба! А ты кто? Никто!»",
        "🧙‍♂️ «Дружба победила! Потому что две головы думают, а одна даже не знает, где уши.»",
        "🧙‍♂️ «Мы сейчас так ударим, что у тебя мана кончится ещё до того, как мы начали!»",
        "🧙‍♂️ «Это называется мультикаст. Запомни слово. Повтори. Не смог? То-то же!»"
    ]
}

ZEUS_TEXTS = [
    "⚡ Zeus <i>«Небеса рассвирепели!»</i>",
    "⚡ Zeus <i>«Вы чувствовали это?»</i>",
    "⚡ Zeus <i>«Ничто не укроется от моего гнева!»</i>",
    "⚡ Zeus <i>«Я — молния, что разрывает небеса!»</i>",
    "⚡ Zeus <i>«Гром и молния! Всё кончено!»</i>",
    "⚡ Zeus <i>«Каждый из вас будет поражён!»</i>",
    "⚡ Zeus <i>«Небесный гнев падёт на всех!»</i>",
]


SLOT_SYMBOLS = ["🍒", "🍋", "🍇", "💎", "🔥", "⚡", "7️⃣", "🎰"]


def slot_animation(level):
    """Генерирует слот-анимацию: 3 одинаковых = переход на уровень"""
    symbol = random.choice(SLOT_SYMBOLS)
    return f"🎰 {symbol}{symbol}{symbol}"


async def send_multicast_anim(chat_id, display_username, level, bot, is_test=False):
    """Анимация мультикаста с слот-машиной"""
    prefix = "🧪 ТЕСТ\n" if is_test else ""
    slot_text = slot_animation(level)
    return await bot.send_message(
        chat_id=chat_id,
        text=f"🎲 {display_username}\n\n{prefix}{slot_text}\n👹⚡ Мультикаст ×{level}!",
        parse_mode="HTML"
    )


async def edit_multicast_anim(anim_msg, display_username, level, is_test=False):
    """Редактирование анимации мультикаста"""
    prefix = "🧪 ТЕСТ\n" if is_test else ""
    slot_text = slot_animation(level)
    try:
        await anim_msg.edit_text(
            f"🎲 {display_username}\n\n{prefix}{slot_text}\n👹⚡ Мультикаст ×{level}!",
            parse_mode="HTML"
        )
    except Exception:
        pass


def check_multicast(fissure_size):
    """
    Каскадный мультикаст (генератор).
    Вызывается ТОЛЬКО когда мультикаст уже выбран.
    Yields: (step_number, extra_roll) на каждом шаге каскада.
    """
    for i, chance in enumerate(MULTICAST_CASCADE):
        if random.random() < chance:
            extra_roll, _, is_fatal, _ = calculate_fissure_roll(fissure_size)
            if not is_fatal:
                yield i + 2, extra_roll
        else:
            break


async def fetch_hero_icon(url, session=None, size=96):
    """Скачать и уменьшить иконку героя через aiohttp"""
    close_session = False
    if session is None:
        from database import get_aiohttp_session
        session = await get_aiohttp_session()
        close_session = True
    try:
        async with session.get(url) as resp:
            if resp.status == 200:
                data = await resp.read()
                # Уменьшаем через Pillow в отдельном потоке чтобы не блокировать event loop
                try:
                    from PIL import Image
                    import io
                    loop = asyncio.get_event_loop()
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


def format_time(seconds):
    h = seconds // 3600
    m = (seconds % 3600) // 60
    return f"{int(h)}ч {int(m)}м"


async def get_user_avatar_url(bot, user_id: int) -> str | None:
    """Get Telegram user profile photo URL"""
    try:
        photos = await bot.get_user_profile_photos(user_id, limit=1)
        if photos and photos.photos:
            photo = photos.photos[0][-1]  # Get biggest photo
            file = await bot.get_file(photo.file_id)
            return file.file_path
    except Exception as e:
        logger.debug(f"Could not get user avatar: {e}")
    return None


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command - show profile card"""
    try:
        # Skip if rate limited
        if is_rate_limited():
            logger.warning(f"Skipping /start due to rate limit")
            return

        # Spam protection for /start command
        user_id = update.effective_user.id
        current_time = time.time()
        if user_id in _USER_START_COOLDOWN:
            last_time = _USER_START_COOLDOWN[user_id]
            if current_time - last_time < _START_COOLDOWN:
                logger.warning(f"Spam protection: user {user_id} tried to use /start too soon")
                await update.message.reply_text("Пожалуйста, подождите перед повторным использованием команды /start")
                return
        _USER_START_COOLDOWN[user_id] = current_time

        user_id = update.effective_user.id
        telegram_username = update.effective_user.username  # только Telegram username (может быть None)
        first_name = update.effective_user.first_name or "Friend"
        display_username = telegram_username or first_name  # для отображения в карточке

        # Получаем пользователя без авто-создания
        db_user = get_user(user_id)
        is_new_user = False

        if db_user is None:
            # Создаём нового пользователя с лучшим доступным именем
            fallback_name = telegram_username or first_name or "Unknown"
            db = Database()
            db.add_user(user_id, fallback_name, None, None)
            logger.info(f"Created new user {user_id} with name '{fallback_name}'")
            is_new_user = True
            user = get_user(user_id)
        else:
            # Существующий пользователь — обновляем username если нужно
            updates = {}
            current_username = db_user.get('username')
            if telegram_username and telegram_username != current_username:
                updates['username'] = telegram_username
            elif current_username is None and first_name and first_name != "Friend":
                updates['username'] = first_name
            if updates:
                update_user_fields_batch(user_id, updates)
                logger.info(f"Updated user {user_id} fields: {updates}")
            user = db_user

        if is_new_user:
            # Для нового пользователя отправляем приветственный баннер и возвращаемся
            chat_id = update.effective_chat.id
            banner_url = "https://i.ibb.co/LXsGsfxZ/213.png"
            text = "👉 Ты в игре — крути фиссуру, чекай топы, подключай Dota и докажи, что ты тут не случайно."
            msg = await context.bot.send_photo(
                chat_id=chat_id,
                photo=banner_url,
                caption=text,
                reply_markup=main_menu()
            )
            set_last_bot_message(chat_id, user_id, msg.message_id)
            update_last_message_id(user_id, msg.message_id)
            return

        if not user:
            logger.error(f"Failed to get/user {user_id}")
            return

        steam_id = user.get("steam_id")
        steam_nickname = user.get("steam_nickname")
        rank_tier = user.get("rank_tier", 0)
        message_count = user.get("message_count", 0)
        logger.info(f"start: user {user_id} message_count from DB/cache = {message_count}")

        chat_id = update.effective_chat.id
        user_msg_id = update.message.message_id if update.message else None

        # Delete user message
        if user_msg_id and isinstance(user_msg_id, int) and user_msg_id > 0:
            try:
                await context.bot.delete_message(chat_id, user_msg_id)
            except Exception as e:
                error_str = str(e).lower()
                if "not found" in error_str or "bad request" in error_str:
                    logger.debug(f"User message {user_msg_id} already deleted: {e}")
                else:
                    logger.debug(f"Could not delete user message {user_msg_id}: {e}")

        # Delete last bot message
        try:
            await delete_last_bot_message(context.bot, chat_id, user_id)
        except:
            pass

        loading_msg = None

        # Send animated loading message with ⏳⌛️
        try:
            loading_msg = await context.bot.send_message(
                chat_id=chat_id,
                text="⏳ Загружаю меню..."
            )
            logger.info(f"Created loading message in start: chat_id={chat_id}, msg_id={loading_msg.message_id}")

            # Animate with alternating clocks ⏳⌛️
            for i in range(3):
                await asyncio.sleep(0.35)
                frame = "⌛️" if i % 2 == 1 else "⏳"
                messages = [
                    "Загружаю меню...",
                    "Подготавливаю интерфейс...",
                    "Строю карточку...",
                    "Готово!"
                ]
                try:
                    # На последнем кадре не редактируем, а удаляем заглушку
                    if i == 2:
                        await loading_msg.delete()
                        loading_msg = None
                        break
                    await loading_msg.edit_text(f"{frame} {messages[min(i, len(messages)-1)]}")
                except Exception:
                    break

        except Exception as e:
            logger.debug(f"Could not send loading message: {e}")
            loading_msg = None

        if steam_id and steam_nickname:
            from dota_mmr import generate_start_card, get_player_stats

            # Get avatar and heroes
            avatar_url = user.get("avatar")
            if not avatar_url:
                stats = get_player_stats(steam_id)
                if stats and stats.get("avatar"):
                    avatar_url = stats["avatar"]
                    update_user_fields_batch(user_id, {"avatar": avatar_url}, save_to_db=False)

            if not avatar_url:
                avatar_url = await get_user_avatar_url(context.bot, user_id)

            weekly_mvp, weekly_top2, weekly_top3 = 0, 0, 0

            card_data = generate_start_card(
                avatar_url=avatar_url,
                message_count=message_count,
                username=display_username,
                steam_nickname=steam_nickname,
                rank_tier=rank_tier,
                weekly_mvp=weekly_mvp,
                weekly_top2=weekly_top2,
                weekly_top3=weekly_top3
            )

            if card_data:
                msg = await context.bot.send_photo(
                    chat_id=chat_id,
                    photo=card_data,
                    reply_markup=main_menu()
                )
                set_last_bot_message(chat_id, user_id, msg.message_id)
                update_last_message_id(user_id, msg.message_id)
                # Auto-delete after 30 seconds
                schedule_delete(context.bot, chat_id, msg.message_id, 30, context.application.job_queue)
            else:
                await menu_handler(update, context)
            if loading_msg:
                    try:
                        msg_id = loading_msg.message_id
                        logger.info(f"Deleting loading message: chat_id={chat_id}, msg_id={msg_id}")
                        await context.bot.delete_message(chat_id, msg_id)
                        logger.info(f"Successfully deleted loading message {msg_id}")
                    except Exception as e:
                        logger.error(f"Failed to delete loading message: {e}")
            return

        # No Steam - show card with Telegram avatar, no message count
        from dota_mmr import generate_start_card

        avatar_url = await get_user_avatar_url(context.bot, user_id)

        card_data = generate_start_card(
            avatar_url=avatar_url,
            message_count=message_count,
            username=display_username,
            steam_nickname=None,
            rank_tier=0,
            weekly_mvp=0,
            weekly_top2=0,
            weekly_top3=0
        )

        if card_data:
            msg = await context.bot.send_photo(
                chat_id=chat_id,
                photo=card_data,
                reply_markup=main_menu()
            )
            set_last_bot_message(chat_id, user_id, msg.message_id)
            update_last_message_id(user_id, msg.message_id)
            # Auto-delete after 30 seconds
            schedule_delete(context.bot, chat_id, msg.message_id, 30, context.application.job_queue)
        else:
            await menu_handler(update, context)
        if loading_msg:
            try:
                await context.bot.delete_message(chat_id, loading_msg.message_id)
                logger.info(f"Deleted loading message {loading_msg.message_id} in start (no Steam)")
            except Exception as e:
                logger.warning(f"Failed to delete loading message in start: {e}")

    except Exception as e:
        error_str = str(e).lower()
        if "flood control" in error_str or "429" in error_str or "too many requests" in error_str:
            retry_after = 60
            import re
            match = re.search(r'retry in (\d+) seconds', error_str)
            if match:
                retry_after = int(match.group(1)) + 5
            set_rate_limited(retry_after)
        logger.error(f"start command error: {e}")
        if loading_msg:
            try:
                await context.bot.delete_message(chat_id, loading_msg.message_id)
            except Exception:
                pass
        await menu_handler(update, context, allow_when_rate_limited=True)
    finally:
        pass  # No shared processing dictionary to clean up for /start


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle button callbacks with pagination support for analytics."""
    callback_query = update.callback_query
    if not callback_query:
        return

    data = callback_query.data

    # Answer immediately for instant feedback
    await callback_query.answer()

    try:
        # === LINK HANDLER ===
        if data == "link":
            await link(update, context)
            return

        # === ANALYTICS PAGE (analytics_page_N) ===
        if data and data.startswith("analytics_page_"):
            page_idx = int(data.split("_")[-1])
            await _show_analytics_page(callback_query, page_idx, context)
            return

    except Exception as e:
        logger.error(f"Error in button_callback: {e}", exc_info=True)
        await callback_query.answer(text="Ошибка при обработке кнопки", show_alert=True)


async def _show_analytics_page(callback_query, page_idx: int, context: ContextTypes.DEFAULT_TYPE):
    """Edit the existing message to show the requested analytics page.
    Pages are generated lazily — only when the user actually navigates to them."""
    from weekly_analytics import get_analytics_pages

    generated = context.user_data.get('analytics_generated', set())
    pages = context.user_data.get('analytics_pages', [])

    if page_idx < 0 or page_idx >= len(pages):
        await callback_query.answer(text="Неверная страница.", show_alert=True)
        return

    # Ленивая генерация: если страница ещё не создана — генерируем все страницы
    if page_idx not in generated:
        stats = context.user_data.get('analytics_stats', {})
        role = context.user_data.get('analytics_role', 'CARRY')
        all_pages = get_analytics_pages(role, stats)
        pages = all_pages  # Replace placeholder with real pages
        generated = set(range(len(pages)))
        context.user_data['analytics_pages'] = pages
        context.user_data['analytics_generated'] = generated

    # Обновляем текущую страницу в user_data для корректной работы навигации
    context.user_data['analytics_page'] = page_idx

    page = pages[page_idx]
    text = page["text"]
    total_pages = len(pages)
    keyboard = _build_analytics_keyboard(page_idx, total_pages, generated)

    try:
        msg = callback_query.message
        # Try editing caption first (for photo messages), then fall back to text
        try:
            if msg.caption is not None:
                await msg.edit_caption(
                    caption=text,
                    reply_markup=keyboard,
                    parse_mode="MarkdownV2"
                )
            else:
                await msg.edit_text(
                    text=text,
                    reply_markup=keyboard,
                    parse_mode="MarkdownV2"
                )
        except Exception as edit_err:
            err_str = str(edit_err).lower()
            if "not modified" in err_str:
                # Content is the same, no need to edit
                return
            raise
    except Exception as e:
        logger.error(f"Error editing analytics message: {e}", exc_info=True)
        await callback_query.answer(text="Не удалось обновить сообщение. Попробуйте запросить аналитику заново.", show_alert=True)


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
    """Универсальный обработчик для команд digestnow, dotadigestnow, setdigestchat"""
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

        current_digest_chat = get_config('digest_chat_id')
        if not current_digest_chat:
            set_config("digest_chat_id", str(chat_id))

        if command == "digestnow":
            _digest_state["type"] = "0"
            set_config("alternate_digest_type", "0")
            set_config("alternate_digest_message_id", None)

            manual_context = ManualContext(context.application, context.bot)
            await alternate_digest_job(manual_context)

            msg = await context.bot.send_message(chat_id=chat_id, text="✅ Фиссура дайджест обновлён!")
            if chat.type in ['group', 'supergroup', 'channel']:
                schedule_delete(context.bot, chat_id, msg.message_id, 30, context.application.job_queue)

        elif command == "dotadigestnow":
            _digest_state["type"] = "1"
            set_config("alternate_digest_type", "1")
            set_config("alternate_digest_message_id", None)

            manual_context = ManualContext(context.application, context.bot)
            await alternate_digest_job(manual_context)

            msg = await context.bot.send_message(chat_id=chat_id, text="✅ Dota дайджест для этого чата создан/обновлён.")
            if chat.type in ['group', 'supergroup', 'channel']:
                schedule_delete(context.bot, chat_id, msg.message_id, 30, context.application.job_queue)

    except Exception as e:
        logger.error(f"Error in digest_handler: {e}", exc_info=True)
        try:
            err_msg = await context.bot.send_message(chat_id=update.effective_chat.id, text="❌ Не удалось создать дайджест сейчас", reply_markup=main_menu())
            chat = update.effective_chat
            if chat and chat.type in ['group', 'supergroup', 'channel']:
                schedule_delete(context.bot, chat.id, err_msg.message_id, 30, context.application.job_queue)
        except Exception:
            pass


async def reset_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Сброс игры"""
    logger.info("reset_game called")
    chat = update.effective_chat

    success = reset_all_fissure_data()
    if success:
        msg = await context.bot.send_message(chat_id=chat.id, text="✅ Игра сброшена! Все начинают заново.")
    else:
        msg = await context.bot.send_message(chat_id=chat.id, text="❌ Не удалось сбросить игру")

    # Small delay to ensure message is visible
    await asyncio.sleep(0.1)

    if chat.type in ['group', 'supergroup', 'channel']:
        schedule_delete(context.bot, chat.id, msg.message_id, 30, context.application.job_queue)


@rate_limit(tokens=1)
async def fissure(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Increase fissure"""
    logger.info(f"User {update.effective_user.id} called fissure")

    user_obj = update.effective_user
    username = user_obj.username or user_obj.first_name
    chat_id = update.message.chat_id
    chat_type = update.message.chat.type
    user_msg_id = update.message.message_id
    now = time.time()

    # Проверка на выходные по МСК (суббота = 5, воскресенье = 6)
    import datetime
    msk_time = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=3)
    is_weekend = msk_time.weekday() in (5, 6)
    weekend_bonus = ""

    # Delete user message only in groups/channels (not in private)
    if chat_type in ['group', 'supergroup', 'channel']:
        if await bot_can_delete(context.bot, chat_id):
            try:
                await context.bot.delete_message(chat_id, user_msg_id)
            except Exception as e:
                logger.debug(f"Could not delete user message: {e}")

    # Small delay before deleting last bot message to ensure new message can be sent
    await asyncio.sleep(0.2)

    # Delete last bot message immediately
    try:
        await delete_last_bot_message(context.bot, chat_id, user_obj.id)
    except Exception as e:
        logger.debug(f"Could not delete last bot message: {e}")

    # Spam protection - ignore if already processing this user
    if _user_fissure_processing.get(user_obj.id):
        return
    _user_fissure_processing[user_obj.id] = now

    try:
        user = get_user(user_obj.id, username)
        logger.info(f"user data: {user}")

        # Check cooldown
        if now - (user.get("last_fissure") or 0) < COOLDOWN:
            wait = COOLDOWN - (now - (user.get("last_fissure") or 0))
            elapsed = COOLDOWN - wait
            filled = int(elapsed / COOLDOWN * 10)
            bar = "🟩" * filled + "⬜️" * (10 - filled)
            text = f"🧬 Восстанавливается. {format_time(wait)}\n{bar}"
            cooldown_banner_url = "https://i.ibb.co/FkzCZxNG/m-Yqbu.jpg"
            result_msg = await context.bot.send_photo(
                chat_id=update.message.chat_id,
                photo=cooldown_banner_url,
                caption=text,
                reply_markup=main_menu()
            )
            set_last_bot_message(chat_id, user_obj.id, result_msg.message_id)
            schedule_delete(context.bot, chat_id, result_msg.message_id, 30, context.application.job_queue)
            update_last_message_id(user_obj.id, result_msg.message_id)

            # Small delay to ensure cooldown message is visible
            await asyncio.sleep(0.1)
            return

        multicast_count = 1
        multicast_text = ""
        original_roll = None
        zeus_triggered = False
        zeus_text = ""
        cascade_count = 1
        display_username = f"<a href=\"tg://user?id={user_obj.id}\">{username}</a>"

        # Один рандом: что выпало?
        event_roll = random.random()
        multicast_chance, zeus_chance = get_event_chances()
        increment_stat("rolls")
        anim_msg = None

        if event_roll < zeus_chance:
            # ⚡ ЗЕВС — отдельное событие, без ролла
            zeus_triggered = True
            increment_stat("zeus")
            affected = zeus_strike()

            # Фиссура пользователя не меняется (Зевс бьёт всех, но не даёт ролл)
            new_fissure = user["fissure"]
            update_fissure(user_obj.id, new_fissure, now, 0)

            zeus_text = random.choice(ZEUS_TEXTS)

            text = (
                f"🎲 {display_username}\n\n"
                f"{zeus_text}\n"
                f"<i>Все фиссуры потеряли -5%! ({affected} игроков)</i>\n\n"
                f"📏 {new_fissure:.1f} см"
            )

            logger.info(f"User {user_obj.id} triggered Zeus. No roll.")

            # Отправляем результат с шапкой
            zeus_banner_url = "https://i.ibb.co/0jg01gWW/Gemini-Generated-Image-wyz68gwyz68gwyz6-1.png"
            result_msg = await context.bot.send_photo(
                chat_id=update.message.chat_id,
                photo=zeus_banner_url,
                caption=text,
                parse_mode="HTML",
                reply_markup=main_menu()
            )
            set_last_bot_message(chat_id, user_obj.id, result_msg.message_id)
            schedule_delete(context.bot, chat_id, result_msg.message_id, 600, context.application.job_queue)
            update_last_message_id(user_obj.id, result_msg.message_id)

            # Small delay to ensure Zeus message is visible
            await asyncio.sleep(0.1)

            return  # выходим — без ролла

        # Остальные события (обычный ролл или мулькаст)
        roll, special_message, is_fatal, got_help = calculate_fissure_roll(user["fissure"])


        slot_msg_ids = []

        if event_roll < zeus_chance + multicast_chance:
            # 🎰 МУЛЬТИКАСТ — слоты как в казино
            slot_emojis = ["🍒", "🍋", "🍇", "🔔", "💎"]
            multicast_text = ""
            cascade_count = 1

            # Проверяем переход на x2 (скрытый рандом 75%)
            slot_msg_ids = []
            if random.random() < 0.75:
                cascade_count = 2
                # Показываем джекпот (3 одинаковых) - это и есть анимация x2
                jackpot_symbol = random.choice(slot_emojis)
                slots = [jackpot_symbol, jackpot_symbol, jackpot_symbol]

                msg = await context.bot.send_message(
                    chat_id=update.message.chat_id,
                    text=f"🎰 {' | '.join(slots)} | x2"
                )
                slot_msg_ids.append(msg.message_id)
                await asyncio.sleep(1)

                # Проверяем переход на x3 (скрытый рандом 25%)
                if random.random() < 0.25:
                    cascade_count = 3
                    # Показываем джекпот - анимация x3
                    jackpot_symbol = random.choice(slot_emojis)
                    slots = [jackpot_symbol, jackpot_symbol, jackpot_symbol]

                    msg = await context.bot.send_message(
                        chat_id=update.message.chat_id,
                        text=f"🎰 {' | '.join(slots)} | x3"
                    )
                    slot_msg_ids.append(msg.message_id)
                    await asyncio.sleep(1)

                    # Проверяем переход на x4 (скрытый рандом 15%)
                    if random.random() < 0.15:
                        cascade_count = 4
                        # Показываем джекпот - анимация x4
                        jackpot_symbol = random.choice(slot_emojis)
                        slots = [jackpot_symbol, jackpot_symbol, jackpot_symbol]

                        msg = await context.bot.send_message(
                            chat_id=update.message.chat_id,
                            text=f"🎰 {' | '.join(slots)} | x4"
                        )
                        slot_msg_ids.append(msg.message_id)
                        await asyncio.sleep(0.5)
                    else:
                        # Не попали в x4 - показываем проигрышный спин и финиш на x3
                        slots = random.sample(slot_emojis, 3)
                        msg = await context.bot.send_message(
                            chat_id=update.message.chat_id,
                            text=f"🎰 {' | '.join(slots)} | x4"
                        )
                        slot_msg_ids.append(msg.message_id)
                        await asyncio.sleep(0.5)
                        cascade_count = 3
                else:
                    # Не попали в x3 - показываем проигрышный спин и финиш на x2
                    slots = random.sample(slot_emojis, 3)
                    msg = await context.bot.send_message(
                        chat_id=update.message.chat_id,
                        text=f"🎰 {' | '.join(slots)} | x3"
                    )
                    slot_msg_ids.append(msg.message_id)
                    await asyncio.sleep(0.5)
                    cascade_count = 2
            else:
                # Не попали в x2 - обычный ролл (не мультикаст)
                multicast_count = 1
                # Продолжаем выполнение для обычного ролла

            # Сохраняем original_roll ДО умножения!
            original_roll = roll
            roll = roll * cascade_count
            logger.info(f"fissure multicast: roll after multiply={roll}, cascade_count={cascade_count}")
            increment_stat("multicast")
            if cascade_count >= 4:
                increment_stat("multicast_x4")
            elif cascade_count >= 3:
                increment_stat("multicast_x3")
            elif cascade_count >= 2:
                increment_stat("multicast_x2")
            if cascade_count > 1:
                multicast_text = f"\n{random.choice(MULTICAST_TEXTS[cascade_count])}"

        else:
            # 🎲 ОБЫЧНЫЙ РОЛЛ (90%)
            pass

        # Даем время slot сообщениям отправиться перед итоговым
        if cascade_count > 1:
            await asyncio.sleep(0.3)

        roll, protection_msg = apply_fissure_protection(user["fissure"], roll, is_fatal)

        # Сохраняем original_roll для отображения в мультикасте (до бонусов)
        display_roll = roll

        # Определяем базовый ролл для текста результата (без учета бонусов выходного дня)
        if original_roll is not None:
            base_roll_for_text = original_roll
        else:
            base_roll_for_text = roll

        # Вычисляем result_text на основе базового ролла
        roll_key_text = min(base_roll_for_text, 75)
        roll_key_text = max(roll_key_text, -15)
        if roll_key_text in ROLL_TEXTS:
            result_text = random.choice(ROLL_TEXTS[roll_key_text])
        else:
            result_text = f"{'+' if base_roll_for_text > 0 else ''}{base_roll_for_text} см"

        # Бонус для выходных: увеличиваем положительный ролл
        # НЕ применяем выходной бонус при мультикасте
        if is_weekend and roll > 0 and not is_fatal and cascade_count == 1:
            bonus_multiplier = random.choice(WEEKEND_BONUS_MULTIPLIERS)
            # Показываем точное значение в сообщении, но сохраняем как целое для расчета
            bonus_amount = roll * bonus_multiplier
            roll = int(roll * bonus_multiplier)
            weekend_bonus = f"🎉 ВЫХОДНОЙ! x{bonus_multiplier:.1f} = {bonus_amount:.1f} СМ"
        else:
            weekend_bonus = ""

        old_fissure = user["fissure"]

        # Считаем новую фиссуру: база - 5% Зевса + ролл (фиссуры < 5 защищены от Зевса)
        if zeus_triggered and user["fissure"] >= 5:
            base_fissure = user["fissure"] * 0.95
        else:
            base_fissure = user["fissure"]
        base_fissure = max(0.1, base_fissure)
        new_fissure = calculate_new_fissure(base_fissure, roll)
        growth = new_fissure - old_fissure
        update_fissure(user_obj.id, new_fissure, now, growth)

        logger.info(f"User {user_obj.id} used fissure. New cooldown: {now}")

        # Вычисляем roll_key для финального значения (используется в extra_text)
        roll_key = min(roll, 75)
        roll_key = max(roll_key, -15)

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

        extra_text = ""
        if roll_key in ROLL_MEMES and random.random() < 0.5:
            extra_text = random.choice(ROLL_MEMES[roll_key])
        elif not is_weekend and cascade_count == 1 and roll > 0 and not is_fatal:
            # Выбираем фразу только если нет выходного бонуса, нет мультикаста и это положительный ролл
            extra_text = random.choice(CATEGORY_PHRASES[category])

        if cascade_count > 1 and original_roll is not None:
            logger.info(f"DEBUG: original_roll={original_roll}, cascade_count={cascade_count}, roll_final={original_roll * cascade_count}")
            roll_display = f"+{original_roll}" if original_roll > 0 else str(original_roll)
            mc_level = f"×{cascade_count}"
            # Ролл уже умножён, используем его напрямую
            roll_final = roll
            text = (
                f"🎲 {display_username}\n\n"
                f"{result_text}\n"
                f"{multicast_text}\n"
                f"⚡ МУЛЬТИКАСТ{mc_level}  {roll_final} CM"
            )
        else:
            # Старый дизайн без мультикаста
            text = (
                f"🎲 {display_username}\n\n"
                f"{result_text}\n"
                f"{extra_text}"
            )

        if is_fatal and protection_msg:
            text = f"{text}\n{protection_msg}"

        if weekend_bonus:
            text = f"{text}\n{weekend_bonus}"

        # Строчка с изменением фиссуры - ВСЕГДА В САМОМ КОНЦЕ
        text = f"{text}\n\n📏 {old_fissure:.1f} см → {new_fissure:.1f} см"

        if zeus_text:
            text = f"{text}\n{zeus_text}"

        logger.info(f"Sending result message to chat_id={update.message.chat_id}")

        # Шапка: старая для обычных, новая для мультикаста
        if cascade_count > 1:
            # Баннер для мультикаста
            roll_banner_url = "https://i.ibb.co/WN5CBpqR/dsad23.png"
        else:
            roll_banner_url = "https://i.ibb.co/Mk35C5PY/Hf-S7B.jpg"

        try:
            if roll_banner_url:
                result_msg = await context.bot.send_photo(
                    chat_id=update.message.chat_id,
                    photo=roll_banner_url,
                    caption=text,
                    parse_mode="HTML",
                    reply_markup=main_menu()
                )
            else:
                result_msg = await context.bot.send_message(
                    chat_id=update.message.chat_id,
                    text=text,
                    parse_mode="HTML",
                    reply_markup=main_menu()
                )
            add_bot_message(chat_id, user_obj.id, result_msg.message_id)
        except Exception as e:
            logger.debug(f"Could not send roll banner: {e}")
            try:
                await anim_msg.edit_text(text=text, parse_mode="HTML", reply_markup=main_menu())
                result_msg = anim_msg
            except Exception:
                result_msg = await context.bot.send_message(
                    chat_id=update.message.chat_id, text=text,
                    parse_mode="HTML", reply_markup=main_menu()
                )

        logger.info(f"Result message sent successfully: message_id={result_msg.message_id}")
        set_last_bot_message(chat_id, user_obj.id, result_msg.message_id)
        # ВСЕГДА удаляем сообщение через 30 секунд во всех чатах
        schedule_delete(context.bot, chat_id, result_msg.message_id, 30, context.application.job_queue)

        # Small delay to ensure message is visible before any further processing
        await asyncio.sleep(0.1)

        # Удаляем анимационные сообщения слотов
        if slot_msg_ids:
            await asyncio.sleep(0.2)
            for msg_id in slot_msg_ids:
                schedule_delete(context.bot, chat_id, msg_id, 30, context.application.job_queue)

        update_last_message_id(user_obj.id, result_msg.message_id)

        await flush_stat_buffer()

    except Exception as e:
        tb = traceback.format_exc()
        logger.error(f"Error in fissure: {e}\n{tb}")
        try:
            msg = await context.bot.send_message(
                chat_id=chat_id,
                text=f"❌ Ошибка обработки запроса\n<code>{e}</code>",
                parse_mode="HTML"
            )
            schedule_delete(context.bot, chat_id, msg.message_id, 30, context.application.job_queue)
        except Exception:
            pass
    finally:
        _user_fissure_processing.pop(user_obj.id, None)


@rate_limit(tokens=1)
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show stats — свой или чужой профиль: /profile или /profile @username"""
    logger.info(f"User {update.effective_user.id} called stats")

    chat_id = update.message.chat_id
    chat_type = update.message.chat.type

    # Delete user message only in groups/channels if bot has permissions
    if chat_type in ['group', 'supergroup', 'channel']:
        if await bot_can_delete(context.bot, chat_id):
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

    loading_msg = None

    try:
        # Определяем: свой профиль или чужой
        target_user = None
        viewing_other = False

        if context.args and context.args[0]:
            # /profile @username или /profile username — ищем другого пользователя
            target_username = context.args[0].lstrip("@")
            if target_username:
                target_user = get_user_by_username(target_username)
                if not target_user:
                    msg = await context.bot.send_message(
                        chat_id=chat_id,
                        text=f"❌ Игрок @{target_username} не найден"
                    )
                    schedule_delete(context.bot, chat_id, msg.message_id, 15, context.application.job_queue)
                    return
                viewing_other = True

        if not target_user:
            user_obj = update.effective_user
            username = user_obj.username or user_obj.first_name or "Unknown"
            target_user = get_user(user_obj.id, username)

        # Send animated loading message with ⏳⌛️
        try:
            loading_msg = await context.bot.send_message(
                chat_id=chat_id,
                text="⏳ Фармирую профиль..."
            )
            logger.info(f"Created loading message: chat_id={chat_id}, msg_id={loading_msg.message_id}")

# Animate with alternating clocks ⏳⌛️
            for i in range(3):
                await asyncio.sleep(0.35)
                frame = "⌛️" if i % 2 == 1 else "⏳"
                messages = [
                    "Фармирую профиль...",
                    "Собираю данные...",
                    "Анализирую статы...",
                    "Готово!"
                ]
                try:
                    # На последнем кадре не редактируем, а удаляем заглушку
                    if i == 2:
                        await loading_msg.delete()
                        loading_msg = None
                        break
                    await loading_msg.edit_text(f"{frame} {messages[min(i, len(messages)-1)]}")
                except Exception:
                    break

        except Exception as e:
            logger.debug(f"Could not send loading message: {e}")
            loading_msg = None

        last_fissure_time = target_user["last_fissure"]
        now = time.time()
        time_since_last = now - last_fissure_time
        remaining_cooldown = max(0, COOLDOWN - time_since_last)

        if remaining_cooldown > 0:
            wait_text = f"Восстановление: {format_time(remaining_cooldown)}"
        else:
            wait_text = "✅ Готов к увеличению!"

        # Форматируем username как кликабельную ссылку
        if viewing_other:
            target_id = target_user.get('telegram_id', 0)
            target_name = target_user.get('username') or target_user.get('steam_nickname') or 'Unknown'
            display_username = f"<a href=\"tg://user?id={target_id}\">{target_name}</a>"
        else:
            user_obj = update.effective_user
            target_id = user_obj.id
            target_name = user_obj.username or user_obj.first_name
            display_username = f"<a href=\"tg://user?id={target_id}\">{target_name}</a>"

        text = f"👑 {display_username}\n\n🍆 Фиссура: {target_user['fissure']:.1f} см\n🎲 Броски: {target_user.get('total_rolls', 0)} 🍀Стрик: {target_user.get('current_streak', 0)}/{target_user.get('best_streak', 0)}"

        # Добавляем стрик Dota если привязан Steam
        if target_user.get('steam_id'):
            week_streak = target_user.get('week_current_streak', 0)
            week_best = target_user.get('week_best_streak', 0)
            week_games = target_user.get('week_games', 0)
            week_wins = target_user.get('week_wins', 0)
            week_losses = week_games - week_wins
            winrate = round((week_wins / week_games * 100), 1) if week_games > 0 else 0

            # Получаем последние 10 игр для отображения
            last_10_balls = ""
            try:
                from dota_mmr import get_recent_matches_async
                steam_id = target_user.get('steam_id')
                if steam_id and week_games > 0:
                    matches = await get_recent_matches_async(steam_id, limit=50)
                    matches = sorted(matches, key=lambda x: x.get('start_time', 0), reverse=True)
                    # Берём только сыгранные за неделю игры (максимум week_games)
                    week_match_count = min(len(matches), week_games)
                    matches = matches[:week_match_count]
                    for match in matches:
                        # OpenDota не возвращает 'win', вычисляем по player_slot и radiant_win
                        player_slot = match.get('player_slot')
                        radiant_win = match.get('radiant_win', False)
                        if player_slot is not None:
                            player_was_radiant = player_slot < 127
                        else:
                            player_was_radiant = True
                        is_win = (radiant_win and player_was_radiant) or (not radiant_win and not player_was_radiant)
                        last_10_balls += "🟢" if is_win else "🔴"
                    # Добавляем zero-width joiner чтобы Telegram не переносил строку
                    if last_10_balls:
                        last_10_balls = last_10_balls.replace("🟢", "🟢‍").replace("🔴", "🔴‍")
            except Exception as e:
                logger.debug(f"Could not get last matches: {e}")

            text += f"\n\n🎮 Dota за неделю:\n📊 {week_wins}W • {week_losses}L • WR {winrate}%\n🔥 Стрик: {week_streak}/{week_best}"

            # Добавляем количество медалей за топ-3 недели
            weekly_mvp = target_user.get('weekly_mvp_count', 0)
            weekly_top2 = target_user.get('weekly_top2_count', 0)
            weekly_top3 = target_user.get('weekly_top3_count', 0)
            medals = []
            if weekly_mvp: medals.append(f"🥇{weekly_mvp}")
            if weekly_top2: medals.append(f"🥈{weekly_top2}")
            if weekly_top3: medals.append(f"🥉{weekly_top3}")
            if medals:
                text += " " + " ".join(medals)

            text += "\n\n🌟 Любимые герои за 20 матчей:"
        else:
            text += "\n\n💡 /profile ＠ник — чужой профиль"

        # Banner URL - для Steam использовать картинку с героями
        profile_banner_url = "https://i.ibb.co/n8g8yQYt/dasdsadasdsadasdsad.png"

        try:
            from dota_mmr import get_top_heroes_async, generate_heroes_image

            # Get top heroes data if Steam is linked
            top_heroes = []
            if target_user.get('steam_id'):
                try:
                    top_heroes = await get_top_heroes_async(target_user['steam_id'], last_n=20, top_k=5)
                    logger.info(f"Fetched top_heroes for steam_id {target_user['steam_id']}: {len(top_heroes)} heroes")
                except Exception as e:
                    logger.warning(f"Could not get top heroes: {e}")
                    top_heroes = []

            try:
                img_bytes = generate_heroes_image(top_heroes)
                if img_bytes:
                    profile_banner_url = io.BytesIO(img_bytes)
                    logger.info(f"Successfully generated heroes image, size: {len(img_bytes)} bytes")
                # else: keep default banner URL for no Steam ID or failed generation
            except Exception as e:
                logger.error(f"Could not generate heroes image: {e}", exc_info=True)
                # keep default banner URL
            
            # Send photo with banner
            result_msg = await context.bot.send_photo(
                chat_id=update.message.chat_id,
                photo=profile_banner_url,
                caption=text,
                parse_mode="HTML",
                reply_markup=main_menu()
)
            logger.info(f"Profile photo sent successfully, result_msg_id={result_msg.message_id}")
            
            # Delete loading message immediately after successful send
            if loading_msg:
                logger.info(f"Loading msg exists: {loading_msg.message_id}, attempting delete...")
                try:
                    await context.bot.delete_message(chat_id, loading_msg.message_id)
                    logger.info(f"SUCCESS: Deleted loading message {loading_msg.message_id} in stats")
                except Exception as del_e:
                    logger.error(f"ERROR: Failed to delete loading message in stats: {del_e}")
            else:
                logger.warning(f"loading_msg is None, cannot delete (already deleted during animation)")

        except Exception as e:
            logger.error(f"Could not generate heroes image: {e}", exc_info=True)

        set_last_bot_message(chat_id, update.effective_user.id, result_msg.message_id)
        schedule_delete(context.bot, chat_id, result_msg.message_id, 30, context.application.job_queue)
        update_last_message_id(update.effective_user.id, result_msg.message_id)

    except Exception as e:
        logger.error(f"Error in stats: {e}\n{traceback.format_exc()}")
        if loading_msg:
            try:
                await context.bot.delete_message(chat_id, loading_msg.message_id)
            except Exception:
                pass
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"❌ Ошибка: <code>{e}</code>",
                parse_mode="HTML"
            )
        except Exception:
            pass


@rate_limit(tokens=1)
async def top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show top users"""
    logger.info(f"User {update.effective_user.id} called top")

    chat_id = update.message.chat_id
    chat_type = update.message.chat.type

    # Delete user message only in groups/channels
    if chat_type in ['group', 'supergroup', 'channel']:
        if await bot_can_delete(context.bot, chat_id):
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
        user_rank = get_fissure_rank(update.effective_user.id)
        user = get_user(update.effective_user.id, update.effective_user.username)
        username = update.effective_user.username or update.effective_user.first_name

        if not top_users:
            text = "😶 Пока нет игроков. Будь первым!"
        else:
            text = ""
            medals = {1: "🥇", 2: "🥈", 3: "🥉"}
            emoji_nums = {4: "4️⃣", 5: "5️⃣", 6: "6️⃣", 7: "7️⃣", 8: "8️⃣", 9: "9️⃣", 10: "🔟"}
            for i, user_top in enumerate(top_users, 1):
                # Приоритет: username -> steam_nickname -> first_name -> telegram_id
                name = user_top.get('username')
                if not name:
                    name = user_top.get('steam_nickname')
                if not name:
                    name = user_top.get('first_name')
                if not name:
                    tg_id = user_top.get('telegram_id')
                    name = str(tg_id) if tg_id else 'Unknown'
                if len(name) > 12:
                    name = name[:12] + "…"
                telegram_id = user_top.get('telegram_id')
                clickable_name = f'<b><a href="tg://user?id={telegram_id}">{name}</a></b>'
                fissure = user_top.get('fissure', 0)
                medal = medals.get(i)
                if medal:
                    text += f"{medal} {clickable_name}: {fissure:.1f} см\n"
                else:
                    text += f"{emoji_nums.get(i, f'{i}.')} {clickable_name}: {fissure:.1f} см\n"

            def get_emoji_num(n):
                if n <= 10:
                    nums = {1: "1️⃣", 2: "2️⃣", 3: "3️⃣", 4: "4️⃣", 5: "5️⃣", 6: "6️⃣", 7: "7️⃣", 8: "8️⃣", 9: "9️⃣", 10: "🔟"}
                    return nums.get(n, str(n))
                else:
                    emoji_digits = {'0': '0️⃣', '1': '1️⃣', '2': '2️⃣', '3': '3️⃣', '4': '4️⃣', '5': '5️⃣', '6': '6️⃣', '7': '7️⃣', '8': '8️⃣', '9': '9️⃣'}
                    return ''.join(emoji_digits[d] for d in str(n))

            # Всегда показываем позицию пользователя, даже если он не в топе
            user_fissure = user.get('fissure', 0) if user else 0
            clickable_username = make_clickable(username, update.effective_user.id)
            if user_rank:
                text += f"\n<b>{get_emoji_num(user_rank)} {clickable_username}: {user_fissure:.1f} см</b>"
            else:
                text += f"\n<b>— {clickable_username}: {user_fissure:.1f} см</b>"

        # Add banner and send
        top_banner_url = "https://i.ibb.co/1fbJD2hb/l-Ij20.jpg"

        text = f"{text}"

        result_msg = await context.bot.send_photo(
            chat_id=update.message.chat_id,
            photo=top_banner_url,
            caption=text,
            parse_mode="HTML",
            reply_markup=main_menu()
        )
        set_last_bot_message(chat_id, update.effective_user.id, result_msg.message_id)
        schedule_delete(context.bot, chat_id, result_msg.message_id, 30, context.application.job_queue)
        update_last_message_id(update.effective_user.id, result_msg.message_id)

    except Exception as e:
        logger.error(f"Error in top: {e}", exc_info=True)
        try:
            msg = await update.message.reply_text("❌ Ошибка получения топа", reply_markup=main_menu())
            schedule_delete(context.bot, update.effective_chat.id, msg.message_id, 30, context.application.job_queue)
        except Exception:
            pass


@rate_limit(tokens=1)
async def topmmr(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Топ игроков по MMR за неделю"""
    logger.info(f"User {update.effective_user.id} called topmmr")

    from dota_mmr import rank_to_string

    user_obj = update.effective_user
    username = user_obj.username or user_obj.first_name
    chat_id = update.message.chat_id

    # Delete user message in groups
    if update.message.chat.type in ['group', 'supergroup', 'channel']:
        if await bot_can_delete(context.bot, chat_id):
            try:
                await context.bot.delete_message(chat_id, update.message.message_id)
            except Exception as e:
                logger.debug(f"Could not delete user message: {e}")

    try:
        from database import get_dota_week_top_from_db, get_dota_mmr_top
        user = get_user(update.effective_user.id)

        # Banner URL
        topmmr_banner_url = "https://i.ibb.co/CsbCfzTz/Tv-Sd2.jpg"

        # Сначала пытаемся получить недельный топ
        logger.info(f"topmmr: before get_dota_week_top_from_db")
        top_users = get_dota_week_top_from_db(10, force_refresh=True)
        logger.info(f"topmmr: got {len(top_users) if top_users else 0} users from weekly DB")

        # Если недельный топ пустой, используем MMR топ
        if not top_users or len(top_users) == 0:
            logger.info(f"topmmr: weekly top empty, using MMR top")
            top_users = get_dota_mmr_top(10)
            logger.info(f"topmmr: got {len(top_users) if top_users else 0} users from MMR DB")

        # Find user's position
        user_pos = None
        for i, player in enumerate(top_users, 1):
            if player.get('telegram_id') == update.effective_user.id:
                user_pos = i
                break

        # If user not in top 10, get their actual rank
        if user_pos is None:
            user_pos = get_dota_week_rank(update.effective_user.id)

        # Initialize user position variables
        user_is_in_top = False
        user_week_games = 0
        user_week_wins = 0
        user_winrate = 0
        user_username = ""

        if user:
            user_week_games = user.get('week_games', 0)
            user_week_wins = user.get('week_wins', 0)
            user_username = user.get('steam_nickname') or user.get('username') or 'Unknown'
            user_week_losses = user_week_games - user_week_wins
            user_winrate = round((user_week_wins / user_week_games * 100), 1) if user_week_games > 0 else 0

            # Check if user is already in the top list
            for player in top_users:
                if player.get('telegram_id') == user.get('telegram_id'):
                    user_is_in_top = True
                    break

        if not top_users:
            text = f"🏆 Топ MMR за неделю\n\nПока нет данных об MMR игроков."
            # Delete previous bot message before sending new one
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
            schedule_delete(context.bot, chat_id, result_msg.message_id, 30, context.application.job_queue)
            return
        else:
            # Build the top MMR text in the requested format (without title)
            lines = []

            # Helper function to convert number to emoji digits
            def number_to_emojis(num: int) -> str:
                emoji_digits = {
                    '0': '0️⃣', '1': '1️⃣', '2': '2️⃣', '3': '3️⃣',
                    '4': '4️⃣', '5': '5️⃣', '6': '6️⃣', '7': '7️⃣',
                    '8': '8️⃣', '9': '9️⃣'
                }
                return ''.join(emoji_digits[d] for d in str(num))

            for i, player in enumerate(top_users, 1):
                username = player.get('steam_nickname') or player.get('username') or 'Unknown'
                rank_tier = player.get('rank_tier', 0)
                week_games = player.get('week_games', 0)
                week_wins = player.get('week_wins', 0)
                week_losses = week_games - week_wins

                # Format rank using helper function
                rank_str = rank_to_string(rank_tier)

                # Medal emoji
                medals = ["🥇", "🥈", "🥉"]
                if i <= 3:
                    medal = medals[i - 1]
                elif i == 10:
                    medal = "🔟"
                else:
                    medal = f"{i}️⃣"

                if week_games > 0:
                    wr = round((week_wins / week_games) * 100, 1)
                    streak = player.get('week_current_streak', 0)
                    # Make all nicknames clickable and bold
                    player_id = player.get('telegram_id')
                    clickable_name = make_clickable(username, player_id)
                    lines.append(f"{medal} <b>{clickable_name}</b> - {rank_str}")
                    streak_text = f" • 🔥{streak}" if streak > 0 else ""
                    lines.append(f" └ {week_wins}W • {week_losses}L • WR {wr}%{streak_text}")
                else:
                    player_id = player.get('telegram_id')
                    clickable_name = make_clickable(username, player_id)
                    lines.append(f"{medal} <b>{clickable_name}</b> - {rank_str}")
                    lines.append(f" └ Нет игр за неделю")



            top_text = "\n".join(lines)

            # Check if this is a digest chat - show normal top list like in private chat
            try:
                from database import get_config
                from datetime import datetime
                digest_chat_id = get_config('digest_chat_id')
                if str(chat_id) == str(digest_chat_id):
                    # In digest chat, we show the normal top list (same as private chat)
                    # The user's personal info will be added at the bottom below
                    pass
            except Exception as e:
                logger.debug(f"Could not process digest chat: {e}")

            def get_emoji_num(n):
                if n is None or n == '?':
                    return "?"
                n = int(n)
                if n <= 10:
                    nums = {1: "1️⃣", 2: "2️⃣", 3: "3️⃣", 4: "4️⃣", 5: "5️⃣", 6: "6️⃣", 7: "7️⃣", 8: "8️⃣", 9: "9️⃣", 10: "🔟"}
                    return nums.get(n, str(n))
                else:
                    emoji_digits = {'0': '0️⃣', '1': '1️⃣', '2': '2️⃣', '3': '3️⃣', '4': '4️⃣', '5': '5️⃣', '6': '6️⃣', '7': '7️⃣', '8': '8️⃣', '9': '9️⃣'}
                    return ''.join(emoji_digits[d] for d in str(n))

            # Add the current user's position (always show it at the bottom)
            if user and user_week_games > 0:
                user_wr = round((user_week_wins / user_week_games) * 100, 1)
                user_rank_str = rank_to_string(user.get('rank_tier', 0))
                if user_is_in_top:
                    top_text += f"\n\n<b>{get_emoji_num(user_pos)} {user_username}: {user_rank_str}</b>\n"
                    top_text += f" └ В топе • {user_week_wins}W • {user_week_losses}L • WR {user_wr}%"
                else:
                    top_text += f"\n\n<b>{get_emoji_num(user_pos)} {user_username}: {user_rank_str}</b>\n"
                    top_text += f" └ {user_week_wins}W • {user_week_losses}L • WR {user_wr}%"
            elif user and user_week_games == 0:
                top_text += f"\n\n<b>— {user_username}</b>\n"
                top_text += f" └ Нет игр за неделю"

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
            schedule_delete(context.bot, chat_id, result_msg.message_id, 30, context.application.job_queue)
            update_last_message_id(user_obj.id, result_msg.message_id)

            # Small delay for message visibility
            await asyncio.sleep(0.1)

        await flush_stat_buffer()

    except Exception as e:
        logger.error(f"Error in topmmr: {e}", exc_info=True)
        try:
            msg = await context.bot.send_message(
                chat_id=chat_id,
                text="❌ Ошибка получения топа",
                reply_markup=main_menu()
            )
            schedule_delete(context.bot, chat_id, msg.message_id, 30, context.application.job_queue)
        except Exception:
            try:
                msg = await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text="❌ Ошибка получения топа MMR",
                    reply_markup=main_menu()
                )
                schedule_delete(context.bot, update.effective_chat.id, msg.message_id, 30, context.application.job_queue)
            except Exception:
                pass


async def link(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

    # Если есть аргумент - сразу привязываем
    if identifier:
        try:
            from dota_mmr import register_steam
            result = register_steam(update.effective_user.id, identifier)

            # Delete previous bot message before sending new one
            try:
                await delete_last_bot_message(context.bot, chat_id, update.effective_user.id)
            except Exception as e:
                logger.debug(f"Could not delete last bot message: {e}")

            if result.get('success'):
                result_msg = await context.bot.send_message(chat_id=update.effective_chat.id, text=result.get('message'))
            else:
                result_msg = await context.bot.send_message(chat_id=update.effective_chat.id, text=result.get('message'))
            # Track this message for future deletion
            set_last_bot_message(chat_id, update.effective_user.id, result_msg.message_id)
            schedule_delete(context.bot, chat_id, result_msg.message_id, 30, context.application.job_queue)
            update_last_message_id(update.effective_user.id, result_msg.message_id)

            # Small delay to ensure message is visible
            await asyncio.sleep(0.1)
        except Exception as e:
            logger.error(f"Error in link: {e}", exc_info=True)
            msg = await context.bot.send_message(chat_id=update.effective_chat.id, text="❌ Ошибка привязки Dota аккаунта", reply_markup=main_menu())
            schedule_delete(context.bot, update.effective_chat.id, msg.message_id, 30, context.application.job_queue)
        return

    # Если нет аргумента - отправляем инструкцию
    # Delete previous bot message before sending new one
    try:
        await delete_last_bot_message(context.bot, chat_id, update.effective_user.id)
    except Exception as e:
        logger.debug(f"Could not delete last bot message: {e}")

    link_banner_url = "https://i.ibb.co/0jdSyXWx/MZXz-H.jpg"
    link_text = ("🦞 *Привязать Аккаунт Dota 2*\n\n"
    "Добавить в друзья → Ваш ID → копировать →\n"
    "`/link 347614947`\n\n"
    "Или ссылку на dotabuff →\n"
    "`/link https://ru.dotabuff.com/players/347614699`\n\n"
    "⚠️ в игре:\n"
    "Настройки → расширенные → сообщество → общедоступная история матчей (вкл)")

    result_msg = await context.bot.send_photo(
        chat_id=update.effective_chat.id,
        photo=link_banner_url,
        caption=link_text,
        parse_mode='Markdown',
        reply_markup=main_menu()
    )
    # Track this message for future deletion
    set_last_bot_message(chat_id, update.effective_user.id, result_msg.message_id)
    add_bot_message(chat_id, update.effective_user.id, result_msg.message_id)
    schedule_delete(context.bot, chat_id, result_msg.message_id, 30, context.application.job_queue)
    update_last_message_id(update.effective_user.id, result_msg.message_id)

    # Small delay to ensure message is visible
    await asyncio.sleep(0.1)





async def menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, allow_when_rate_limited=False):
    """Menu button handler - sends new content, deletes user message and old bot message immediately"""
    try:
        # Skip if rate limited (but allow override for error fallback)
        if not allow_when_rate_limited and is_rate_limited():
            logger.warning(f"Skipping menu_handler due to rate limit")
            return

        # Check if we have a message - if not, this is not a text message update
        if not update.message:
            logger.warning(f"menu_handler: no message in update")
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
                logger.info(f"menu_handler: skipping message_count (not in digest chat)")
            else:
                user_id = update.effective_user.id
                db_user = get_user(user_id)  # get without auto-create
                if not db_user:
                    # User not found in DB, create them first
                    telegram_username = update.effective_user.username
                    first_name = update.effective_user.first_name
                    fallback_name = telegram_username or first_name or "Unknown"
                    db = Database()
                    db.add_user(user_id, fallback_name, None, None)
                    db_user = get_user(user_id)  # Get the newly created user
                    logger.info(f"Created new user {user_id} for message counting")

                if db_user:
                    current_count = db_user.get('message_count', 0)
                    new_count = current_count + 1
                    logger.info(f"message_count: {user_id} old={current_count} new={new_count}, user exists: {db_user is not None}")
                    updates = {'message_count': new_count}
                    # Обновляем username только если есть telegram_username и он отличается;
                    # или если username пуст, а есть first_name — используем first_name как fallback
                    current_username = db_user.get('username')
                    new_telegram_username = update.effective_user.username
                    if new_telegram_username and new_telegram_username != current_username:
                        updates['username'] = new_telegram_username
                    elif current_username is None and update.effective_user.first_name:
                        updates['username'] = update.effective_user.first_name
                    update_user_fields_batch(user_id, updates)
                    logger.info(f"Saved message_count for {user_id}: {new_count}")
        except Exception as e:
            logger.error(f"Error updating message_count: {e}")

        if not update.message:
            logger.warning(f"menu_handler: no message in update")
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
            "🔑 Привязать Аккаунт": "🔑 Привязать Аккаунт"
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

        # If still not exact, try contains match (case-insensitive)
        if not button_found and len(text) >= 3:
            text_lower = text.lower()
            for btn_key, btn_full in menu_buttons.items():
                if btn_key.lower() in text_lower or text_lower in btn_key.lower():
                    button_found = btn_full
                    break

        if not button_found:
            logger.info(f"menu_handler: text NOT recognized, skipping: '{text}' (len={len(text)})")
            logger.info(f"menu_handler: available buttons: {list(menu_buttons.keys())}")
            return

        logger.info(f"menu_handler: MATCH FOUND - '{button_found}'")

        chat_id = update.message.chat_id
        chat_type = update.message.chat.type
        user_id = update.effective_user.id

        logger.info(f"User {user_id} pressed button: {button_found} in chat type: {chat_type}")



        # Delete user's message only in groups/channels (non-blocking, don't wait)
        if chat_type in ['group', 'supergroup', 'channel']:
            user_msg_id = update.message.message_id
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
    import time
    return web.Response(text="Bot is working", status=200)


health_check_handler = None


def setup_health_check(bot):
    """Initialize health check handler with bot instance"""
    global health_check_handler
    async def check(request):
        # Всегда возвращаем 200 - бот работает
        # Не проверяем активность - Render может убить бота если нет обновлений
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

        # Handle bot added to chat (my_chat_member)
        if old_member and new_member:
            bot_id = context.bot.id
            if new_member.user.id == bot_id:
                # Bot was added to chat
                if old_member.status in ['left', 'kicked'] and new_member.status in ['member', 'administrator']:
                    # Автоматически запоминаем чат для дайджеста, если он ещё не настроен
                    try:
                        if not get_config("digest_chat_id"):
                            set_config("digest_chat_id", chat_id)
                            logger.info(f"Автоматически установлен digest_chat_id = {chat_id}")
                    except Exception as e:
                        logger.debug(f"Не удалось автоматически установить digest_chat_id: {e}")
                return

        # Handle user added to chat (chat_member)
        if new_member and new_member.user.id != context.bot.id:
            new_status = new_member.status

            # User joined the chat (was not a member, now is member)
            # Handle both cases: with old_member (left/kicked) and first join (no old_member)
            # Also handle 'creator' (group owner)
            is_new_join = (new_status in ['member', 'administrator', 'creator'])

            # Check if this is NOT a re-join (old_member doesn't exist or is not member)
            is_not_rejoin = (old_member is None) or (old_member.status not in ['member', 'administrator', 'creator'])

            if is_new_join and is_not_rejoin:
                name = new_member.user.first_name or "Friend"
                user_id = new_member.user.id
                user_obj = new_member.user
                telegram_username = user_obj.username  # может быть None

                logger.info(f"New member joined: {name} (id={user_id}) in chat {chat_id}")

                # Убедимся, что пользователь существует в БД
                try:
                    db_user = get_user(user_id)  # без создания
                    if db_user is None:
                        # Новый пользователь — создаём с лучшим доступным именем
                        fallback_name = telegram_username or user_obj.first_name or "Unknown"
                        db = Database()
                        db.add_user(user_id, fallback_name, None, None)
                        logger.info(f"Created new user {user_id} with name '{fallback_name}'")
                    else:
                        # Существующий пользователь — обновляем username если изменился (только если есть telegram_username)
                        current_username = db_user.get('username')
                        if telegram_username and telegram_username != current_username:
                            update_user_fields_batch(user_id, {'username': telegram_username})
                            logger.info(f"Updated username for {user_id} to '{telegram_username}'")
                        # Если username нет в Telegram, но в БД тоже NULL, и есть first_name — устанавливаем first_name
                        elif current_username is None and user_obj.first_name:
                            update_user_fields_batch(user_id, {'username': user_obj.first_name})
                            logger.info(f"Set fallback username for {user_id} to '{user_obj.first_name}'")
                except Exception as e:
                    logger.debug(f"Could not ensure user exists for {user_id}: {e}")

                # Отмечаем пользователя как участника чата
                try:
                    set_user_in_chat(user_id, True)
                except Exception as e:
                    logger.debug(f"Could not set in_chat=True for {user_id}: {e}")

                phrase = random.choice(WELCOME_PHRASES)
                keyboard = [[InlineKeyboardButton("🔑 Привязать Аккаунт", callback_data="link")]]
                reply_markup = InlineKeyboardMarkup(keyboard)

                # Используем text_mention если есть username
                if user_obj.username:
                    welcome_text = f"{name}, {phrase}"
                    entities = [MessageEntity(
                        type=MessageEntity.TEXT_MENTION,
                        offset=0,
                        length=len(name),
                        user=user_obj
                    )]
                    result_msg = await context.bot.send_message(
                        chat_id=chat_id,
                        text=welcome_text,
                        entities=entities,
                        reply_markup=reply_markup
                    )
                else:
                    # Fallback для пользователей без username
                    welcome_text = f"<a href=\"tg://user?id={user_id}\">{name}</a>, {phrase}"
                    result_msg = await context.bot.send_message(
                        chat_id=chat_id,
                        text=welcome_text,
                        parse_mode="HTML",
                        reply_markup=reply_markup
                    )

                logger.info(f"Welcome sent for {name}")

            # User left the chat (was member, now is left/kicked)
            elif old_member and new_status in ['left', 'kicked']:
                user_id = new_member.user.id
                name = new_member.user.first_name or "Unknown"
                try:
                    delete_user(user_id)
                    logger.info(f"User {name} ({user_id}) left chat, deleted from database")
                except Exception as e:
                    logger.debug(f"Could not delete user {user_id} on leave: {e}")

    except Exception as e:
        logger.error(f"Error in welcome_new_member: {e}")


async def main():
    """Start Telegram bot - unified function for both polling and webhook modes"""
    if not TOKEN:
        logger.error("BOT_TOKEN not set! Bot cannot start.")
        return

    try:
        init_db()
        migrate_db()
        cleanup_left_users()
        update_digest_snapshot()
        logger.info("Digest snapshot initialized on startup")

        from database import get_all_users, get_all_users_with_steam, user_cache
        all_users = get_all_users()
        for u in all_users:
            user_cache.set(u['telegram_id'], u)
        logger.info(f"Loaded {len(all_users)} users into cache on startup")

        from database import update_dota_week_top_cache
        update_dota_week_top_cache()
        logger.info("Dota week top cache initialized on startup")

        job_queue = JobQueue()
        app = ApplicationBuilder().token(TOKEN).job_queue(job_queue).build()
        job_queue.set_application(app)

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



        # morning_digest_job удалён

        # Обновление MMR каждый час (актуальные данные)
        job_queue.run_repeating(
            update_all_mmr_job,
            interval=datetime.timedelta(hours=1),
            first=datetime.datetime.now() + datetime.timedelta(minutes=10)
        )

        # Обновление дайджестов каждые 15 секунд (оптимизировано для минимальной нагрузки)
        job_queue.run_repeating(
            alternate_digest_job,
            interval=datetime.timedelta(seconds=15),
            first=datetime.datetime.now() + datetime.timedelta(seconds=10)
        )

        job_queue.run_daily(
            decrease_inactive_job,
            time=datetime.time(hour=3, minute=0),  # 03:00 MSK (00:00 UTC)
            days=(0, 1, 2, 3, 4, 5, 6)
        )

        # ✅ Объявление чемпиона недели в воскресенье 23:30 MSK
        job_queue.run_daily(
            weekly_champion_announcement_job,
            time=datetime.time(hour=20, minute=30),  # 20:30 UTC = 23:30 MSK
            days=(6,)  # Только воскресенье
        )

        # ✅ Сброс MMR статистики в воскресенье 00:00 MSK
        job_queue.run_daily(
            weekly_mmr_reset_job,
            time=datetime.time(hour=21, minute=0),  # 21:00 UTC = 00:00 MSK
            days=(6,)  # Только воскресенье
        )

        # Копия в backup БД каждый час
        if BACKUP_DATABASE_URL:
            job_queue.run_repeating(
                backup_database_job,
                interval=datetime.timedelta(hours=1),
                first=datetime.datetime.now() + datetime.timedelta(minutes=5)
            )

        app.add_handler(CommandHandler("start", start))
        app.add_handler(CallbackQueryHandler(button_callback))
        app.add_handler(CommandHandler(("fissure", "fissura"), fissure))
        app.add_handler(CommandHandler("profile", stats))
        app.add_handler(CommandHandler("top", top))
        app.add_handler(CommandHandler("topmmr", topmmr))
        app.add_handler(CommandHandler("link", link))
        app.add_handler(CommandHandler(("digestnow", "dotadigestnow", "setdigestchat"), digest_handler))
        app.add_handler(CommandHandler("resetgame", reset_game))
        app.add_handler(CommandHandler("testgreeting", test_greeting))
        app.add_handler(CommandHandler("testmvp", test_mvp_winner))

        # Еженедельная аналитика
        app.add_handler(CommandHandler("analyze", analyze_command))
        app.add_handler(ChatMemberHandler(welcome_new_member, ChatMemberHandler.CHAT_MEMBER))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, menu_handler))

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

        if use_polling or not webhook_url:
            logger.info("Starting bot in POLLING mode")
            await app.bot.delete_webhook(drop_pending_updates=True)
            await app.bot.set_my_commands([])

            from aiohttp import web
            async def health_handler(request):
                return web.Response(text="Bot is polling", status=200)
            web_app = web.Application()
            web_app.router.add_get('/', health_handler)
            web_app.router.add_get('/health', health_handler)
            runner = web.AppRunner(web_app)
            await runner.setup()
            port = int(os.getenv('PORT', 10000))
            logger.info(f"Starting TCP site on port {port}...")
            site = web.TCPSite(runner, '0.0.0.0', port)
            await site.start()
            logger.info(f"Site started, sleeping 3s for port detection...")
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
                    await app.bot.set_webhook(url=webhook_url, drop_pending_updates=True)
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

            from aiohttp import web

            async def handle_webhook(request):
                global last_update_time
                try:
                    update_data = await request.json()
                    logger.info(f"Webhook received update: {update_data.get('message', {}).get('text', 'unknown')}")
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

            runner = web.AppRunner(web_app)
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
                        await asyncio.sleep(300)  # Ping every 5 minutes to prevent Render sleep
                        from database import get_aiohttp_session
                        session = await get_aiohttp_session()
                        # Ping health endpoint
                        await session.get(ping_url, timeout=aiohttp.ClientTimeout(total=30))
                        logger.info("Keep-alive ping sent")
                        # Also ping root to keep web server awake
                        root_url = webhook_url.rsplit('/webhook', 1)[0] + '/'
                        await session.get(root_url, timeout=aiohttp.ClientTimeout(total=10))
                    except Exception as e:
                        logger.error(f"Keep-alive ping error: {e}")
        asyncio.create_task(keep_alive_ping())

        while True:
            await asyncio.sleep(3600)

    except Exception as e:
        logger.error(f"Critical error: {e}", exc_info=True)
        raise
    finally:
        try:
            from database import flush_users_cache, close_aiohttp_session
            flushed = flush_users_cache()
            logger.info(f"Shutdown: flushed {flushed} users to DB")
            # Close aiohttp session to prevent "Unclosed connection" error
            await close_aiohttp_session()
            logger.info("Shutdown: aiohttp session closed")
        except Exception as flush_err:
            logger.error(f"Shutdown flush error: {flush_err}")


if __name__ == "__main__":
    try:
        from dota_mmr import get_heroes_data
        from image_cache import preload_heroes
        heroes = get_heroes_data()
        if heroes:
            preload_heroes(heroes)
            logger.info("Hero icons preloaded in background")
    except Exception as e:
        logger.debug(f"Could not preload heroes: {e}")

    asyncio.run(main())



