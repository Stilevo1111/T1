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
from typing import Any
import urllib.parse as urlparse
import hashlib
from datetime import timezone, timedelta
from collections import deque
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, Message, MessageEntity, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.request import HTTPXRequest
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters, JobQueue, ChatMemberHandler, CallbackQueryHandler
from telegram.error import Conflict
from database import (
    init_db, get_user, update_fissure, get_fissure_top, update_last_message_id, Database,
    get_user_rank, get_fissure_rank, decrease_inactive_fissure, get_config, set_config,
    get_digest_stats, update_player_positions, update_digest_snapshot, migrate_db,
    get_connection, get_dota_digest_stats, set_user_in_chat, zeus_strike, get_user_by_username,
    delete_user, top_cache, update_user_fields_batch, get_dota_mmr_top, get_dota_week_top,
    get_dota_week_rank, DATABASE_URL, reset_all_fissure_data, cleanup_left_users,
    get_all_users_with_steam, user_cache, update_dota_week_top_cache, get_db_type, config_cache
)
from mute import register_handlers as register_mute_handlers
from dota_mmr import update_user_mmr, get_opendota_rate_limit_message, _get_start_card_background
import aiohttp
from aiohttp import web
from rate_limiter import telegram_rate_limiter, rate_limit

# Logging setup
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)


def _telegram_error_contains(error: Exception, *phrases: str) -> bool:
    """Проверяет, содержит ли текст ошибки любую из переданных фраз (регистронезависимо)."""
    if error is None:
        return False
    msg = str(error).lower()
    return any(p.lower() in msg for p in phrases)


TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    print("WARNING: BOT_TOKEN is not set!")
else:
    print("BOT_TOKEN found")

# COOLDOWN moved to constants.py

_USER_START_COOLDOWN = {}  # Spam protection for /start: user_id -> timestamp
_START_COOLDOWN = 5  # 5 seconds cooldown for /start command

# Digest state and logic are now fully centralized in digest.py
# (leader election + single active instance on Render).

_rate_limit_until = 0  # Unix timestamp - skip API calls until this time after 429
RATE_LIMIT_COOLDOWN = 60  # 60 seconds cooldown after hitting rate limit


def is_rate_limited() -> bool:
    """Check if bot is currently rate limited."""
    return time.time() < _rate_limit_until


def set_rate_limited(retry_after=None):
    """Set rate limit state. retry_after is seconds to wait (default COOLDOWN)"""
    global _rate_limit_until
    wait_time = retry_after if retry_after else RATE_LIMIT_COOLDOWN
    _rate_limit_until = time.time() + wait_time
    logger.warning(f"Rate limited until {time.strftime('%H:%M:%S', time.localtime(_rate_limit_until))}")


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
    Раз в ~12 часов проверяем только небольшую порцию (35) самых "холодных" пользователей.
    """
    try:
        from database import get_connection, get_db_type, set_user_in_chat, release_connection

        digest_chat_id = get_config('digest_chat_id')
        if not digest_chat_id:
            return

        # Берём очень маленькую порцию — старых по last_activity
        conn = get_connection()
        cursor = conn.cursor()
        db_type = get_db_type()
        if "postgres" in db_type:
            cursor.execute("""
                SELECT telegram_id FROM users
                WHERE in_chat = TRUE
                ORDER BY last_activity ASC NULLS FIRST
                LIMIT 35
            """)
        else:
            cursor.execute("""
                SELECT telegram_id FROM users
                WHERE in_chat = 1
                ORDER BY last_activity ASC
                LIMIT 35
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
        flushed = flush_users_cache()
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
        # Понедельник - начало недели (weekday 0 = Monday)
        monday_msk = today_msk - timedelta(days=today_msk.weekday())
        current_week_start = monday_msk.strftime("%Y-%m-%d")

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
async def analyze_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Еженедельная аналитика игрока"""
    loading_msg = None
    animation_task = None
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
        
        # Delete old analytics chart if exists
        old_chart_msg_id = context.user_data.get('analytics_chart_msg_id')
        if old_chart_msg_id:
            try:
                await context.bot.delete_message(chat_id, old_chart_msg_id)
            except Exception:
                pass
            context.user_data['analytics_chart_msg_id'] = None

        # Immediately respond with loading message
        try:
            loading_msg = await context.bot.send_message(
                chat_id=chat_id,
                text="⏳ Генерирую аналитику..."
            )
            logger.info(f"Created loading message in analyze: chat_id={chat_id}, msg_id={loading_msg.message_id}")

            # Start animation as background task
            async def animate_loading():
                for i in range(6):
                    try:
                        await asyncio.sleep(0.5)
                    except asyncio.CancelledError:
                        return
                    if loading_msg is None:
                        break
                    frame = "⌛️" if i % 2 == 1 else "⏳"
                    messages = ["Генерирую аналитику...", "Собираю данные...", "Анализирую статы...", "Готово!"]
                    try:
                        await loading_msg.edit_text(f"{frame} {messages[min(i, len(messages)-1)]}")
                    except Exception:
                        pass

            animation_task = asyncio.create_task(animate_loading())
        except Exception as e:
            logger.debug(f"Could not send loading message: {e}")
            loading_msg = None
        
        # Start analytics generation in background task
        async def generate_and_update_analytics():
            try:
                from weekly_analytics import generate_chart_only, get_analytics_pages, get_last_matches
                chart_data = await generate_chart_only(update.effective_user.id)

                if chart_data:
                    # Check if it's an API error response
                    if isinstance(chart_data, dict) and chart_data.get("error") == "opendota_rate_limit":
                        if animation_task:
                            animation_task.cancel()
                        if loading_msg:
                            try:
                                await context.bot.edit_message_text(
                                    chat_id=chat_id,
                                    message_id=loading_msg.message_id,
                                    text=chart_data.get("message", get_opendota_rate_limit_message())
                                )
                            except Exception:
                                pass
                            schedule_delete(context.bot, chat_id, loading_msg.message_id, 10, context.application.job_queue)
                        return
                    
                    history = chart_data.get("history", [])
                    matches = chart_data.get("matches", [])
                    chart_image = chart_data.get("image")
                    role_from_chart = chart_data.get("role", "CARRY")  # Get role from chart data
                    
# If matches empty but cache had old data, fetch fresh matches
                    if not matches:
                        try:
                            fresh_matches = await get_last_matches(update.effective_user.id)
                            if len(fresh_matches) >= 5:
                                matches = fresh_matches
                                logger.info(f"Analytics: refetched {len(matches)} fresh matches from API")
                        except Exception as e:
                            logger.warning(f"Analytics: failed to refetch matches: {e}")
                    
                    logger.info(f"Analytics: got chart_data with {len(matches)} matches, image={chart_image is not None}")
                    
                    # Ensure charts directory exists for potential caching
                    import os
                    os.makedirs("charts", exist_ok=True)
                    
                    # Сохраняем только matches для полной ленивой генерации
                    context.user_data['analytics_stats'] = None
                    context.user_data['analytics_role'] = role_from_chart  # Store role from chart generation
                    context.user_data['analytics_page'] = 0
                    context.user_data['analytics_history'] = history
                    context.user_data['analytics_matches'] = matches
                    context.user_data['analytics_pages'] = [None, None]
                    context.user_data['analytics_generated'] = set()
                    
                    # Delete old analytics table if exists
                    old_table_msg_id = context.user_data.get('analytics_table_msg_id')
                    if old_table_msg_id:
                        try:
                            await context.bot.delete_message(chat_id, old_table_msg_id)
                        except Exception:
                            pass
                        context.user_data['analytics_table_msg_id'] = None
                    
                    if chart_image and len(chart_image) > 0:
                        # Cancel animation and delete loading message
                        if animation_task:
                            animation_task.cancel()
                        
                        # Update loading message with result
                        photo_buf = io.BytesIO(chart_image)
                        photo_buf.name = "weekly_analytics.png"
                        
                        reply_markup = _build_stats_button_keyboard()
                        
                        try:
                            await context.bot.edit_message_media(
                                chat_id=chat_id,
                                message_id=loading_msg.message_id,
                                media=InputMediaPhoto(media=photo_buf, caption="🧠 Импакт в последних 10 играх."),
                                reply_markup=reply_markup
                            )
                            # Store chart message ID for future deletion
                            context.user_data['analytics_chart_msg_id'] = loading_msg.message_id
                            # Schedule deletion after 30 seconds
                            schedule_delete(context.bot, chat_id, loading_msg.message_id, 30, context.application.job_queue)
                        except Exception:
                            # Fallback: delete and send new message
                            photo_buf.seek(0)  # Reset buffer position after failed edit
                            try:
                                await context.bot.delete_message(chat_id, loading_msg.message_id)
                            except Exception:
                                pass
                            # Delete previous bot message before sending new one
                            try:
                                await delete_last_bot_message(context.bot, chat_id, update.effective_user.id)
                            except Exception:
                                pass
                            result_msg = await context.bot.send_photo(
                                chat_id=chat_id,
                                photo=photo_buf,
                                caption="🧠 Импакт в последних 10 играх.",
                                reply_markup=reply_markup,
                                parse_mode="MarkdownV2"
                            )
                            # Store chart message ID for future deletion
                            context.user_data['analytics_chart_msg_id'] = result_msg.message_id
                            set_last_bot_message(chat_id, update.effective_user.id, result_msg.message_id)
                            schedule_delete(context.bot, chat_id, result_msg.message_id, 30, context.application.job_queue)
                            update_last_message_id(update.effective_user.id, result_msg.message_id)
                    else:
                        # Cancel animation and update with error message
                        if animation_task:
                            animation_task.cancel()
                        error_text = "⚠️ Не удалось сгенерировать график аналитики. Попробуйте позже."
                        try:
                            await context.bot.edit_message_text(
                                chat_id=chat_id,
                                message_id=loading_msg.message_id,
                                text=error_text
                            )
                            schedule_delete(context.bot, chat_id, loading_msg.message_id, 10, context.application.job_queue)
                        except Exception:
                            pass

            except Exception as e:
                logger.error(f"Error in background analytics generation: {e}")
                if animation_task:
                    animation_task.cancel()
                err_msg_id = loading_msg.message_id if loading_msg else None
                try:
                    await context.bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=loading_msg.message_id,
                        text=f"Ошибка генерации аналитики: {str(e)[:100]}..."
                    )
                except Exception:
                    pass

                # Schedule deletion of the final loading/error message
                schedule_delete(context.bot, chat_id, err_msg_id, 10, context.application.job_queue)

        # Import required classes
        from telegram import InputMediaPhoto
        
        # Start background task
        context.application.create_task(generate_and_update_analytics())
        
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
    """Объявление чемпиона недели в воскресенье 23:30 MSK (только лидер)."""
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

    from datetime import datetime as dt, timezone, timedelta
    MSK = timezone(timedelta(hours=3))
    today_msk = dt.now(MSK)
    # Понедельник - начало недели (weekday 0 = Monday)
    monday_msk = today_msk - timedelta(days=today_msk.weekday())
    current_week_start = monday_msk.strftime("%Y-%m-%d")

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
        user_cache.delete_key('dota_week_top')
        from database import set_config
        set_config('weekly_mmr_reset_date', current_week_start)
        logger.info("weekly_mmr_reset_job: еженедельная статистика MMR сброшена в 00:00 MSK")
    except Exception as e:
        logger.error(f"weekly_mmr_reset_job: ошибка при сбросе статистики: {e}")

async def announce_weekly_mmr_winner(bot):
    """Отправляет поздравление победителю недельного топа MMR в воскресенье."""
    from datetime import datetime as dt, timezone, timedelta
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

    # Проверяем, есть ли игроки с данными за ПРОШЛУЮ неделю
    from database import get_connection as gc2, DATABASE_URL
    import urllib.parse as urlparse
    conn = gc2()
    cursor = conn.cursor()
    scheme = urlparse.urlparse(DATABASE_URL).scheme
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

    # Объявление только в воскресенье
    if not is_sunday:
        logger.info("announce_weekly_mmr_winner: не воскресенье - пропускаем")
        return False

    # В воскресенье проверяем, что есть игроки с новыми данными
    if stale_count == 0:
        logger.info("announce_weekly_mmr_winner: в воскресенье stale_count == 0 - данных за новую неделю ещё нет")
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

    name_display = make_clickable(username, telegram_id)

    tag_info = ""
    if tag_set:
        tag_info = f"\n👤 Ему присвоен титул \"{mvp_tag}\" и добавлена медалька в профиль!"

    text = (
        f"Поздравляем чемпиона недели🏆\n"
        f"🥇 {name_display} • 🗡️ {rank_str}\n\n"
        f"📈 Результат за неделю:\n"
        f" └ {week_wins}W • {week_losses}L • WR {winrate}%\n\n"
        f"🏆Этот игрок показал лучший результат в топе MMR за неделю!{tag_info}"
    )

    from dota_mmr import generate_start_card

    avatar_url = await resolve_avatar_url_for_card(
        bot,
        telegram_id=telegram_id,
        steam_id=winner.get('steam_id'),
        db_avatar=winner.get('avatar'),
    )
    logger.info(f"Champion card avatar for {username}: {avatar_url[:80] if avatar_url else 'none'}...")

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



@rate_limit(tokens=1)
async def claim_or_check_mmr_leader():
    """Leader election for hourly MMR job (prevents duplicate heavy work when 2+ Render instances run the same bot)."""
    instance_id = os.getenv("RENDER_INSTANCE_ID") or f"local_{os.getpid()}"
    now = time.time()
    LEADER_TIMEOUT = 180  # 3 minutes is enough for hourly job

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
    LEADER_TIMEOUT = 300  # 5 minutes — sufficient for weekly champion card + send

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


async def update_all_mmr_job(context):
    """Ежечасовое обновление MMR всех пользователей с привязанным Steam (только в кеш)"""
    try:
        if not await claim_or_check_mmr_leader():
            return

        logger.info("Запуск ежечасного обновления MMR")
        from database import get_all_users_with_steam, user_cache

        # Fetch users in thread to avoid blocking event loop on DB query
        users = await asyncio.to_thread(get_all_users_with_steam)
        if not users:
            logger.info("Нет пользователей с привязанным Steam для обновления MMR")
            return

        logger.info(f"Обновление MMR для {len(users)} пользователей (leader)")
        success_count = 0
        rank_up_users = []  # собираем для уведомлений

        # === BATCHED + PAUSED to spread Neon/OpenDota load ===
        MMR_BATCH_SIZE = 25
        MMR_BATCH_PAUSE = 10  # seconds between batches

        for i in range(0, len(users), MMR_BATCH_SIZE):
            batch = users[i : i + MMR_BATCH_SIZE]
            for user in batch:
                try:
                    # Pass update_top_cache=False so we rebuild the top cache ONLY ONCE after the full loop
                    result = await asyncio.to_thread(
                        update_user_mmr, user['telegram_id'], update_top_cache=False
                    )
                    if result and result.get('success'):
                        success_count += 1
                        logger.info(f"MMR updated for {user['telegram_id']}: {result.get('mmr')} MMR")

                        if result.get('rank_up'):
                            fresh_user = get_user(user['telegram_id']) or user
                            rank_up_users.append((fresh_user, result['rank_up']))
                except Exception as e:
                    logger.error(f"Ошибка обновления MMR для {user['telegram_id']}: {e}")

            if i + MMR_BATCH_SIZE < len(users):
                logger.info(f"MMR batch done ({i + len(batch)}/{len(users)}), sleeping {MMR_BATCH_PAUSE}s to spread load")
                await asyncio.sleep(MMR_BATCH_PAUSE)

        # Обновляем кеш топа MMR РОВНО ОДИН РАЗ после всех пользователей (не 150 раз из update_user_fields_batch)
        from database import update_dota_week_top_cache
        update_dota_week_top_cache()

        # Refresh Dota digest cache so the 15-second fast rotation
        # can reliably flip between Fissure and fresh Dota content.
        try:
            from digest import refresh_dota_digest_cache
            refresh_dota_digest_cache()
        except Exception as e:
            logger.warning(f"Could not refresh Dota digest cache from MMR job: {e}")

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
                    avatar_url = await resolve_avatar_url_for_card(
                        context.bot,
                        telegram_id=telegram_id,
                        steam_id=user.get('steam_id'),
                        db_avatar=user.get('avatar'),
                    )

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
                        name_display = make_clickable(username, telegram_id)
                        text = f"🎉 {name_display} повысил ранг!\n{rank_info['old_rank']} → {rank_info['new_rank']}"
                        await context.bot.send_photo(chat_id=digest_chat_id, photo=card_data, caption=text, parse_mode="HTML")
                    else:
                        # Fallback
                        name_display = make_clickable(username, telegram_id)
                        text = f"{name_display} повысил ранг!\n{rank_info['old_rank']} → {rank_info['new_rank']}"
                        rank_up_banner_url = "https://i.ibb.co/HLF6JJTw/ji8hy.jpg"
                        await context.bot.send_photo(chat_id=digest_chat_id, photo=rank_up_banner_url, caption=text, parse_mode="HTML")
                except Exception as notify_err:
                    logger.error(f"Ошибка отправки уведомления о ранк-апе: {notify_err}")



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
        stats = get_digest_stats()
        set_fissure_digest_data(stats)
        logger.debug("refresh_digest_message: кэш digest_data обновлён, дайджест будет обновлён в следующем тике alternate_digest_job")

    except Exception as e:
        logger.error(f"Ошибка в refresh_digest_message: {e}", exc_info=True)


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
                    logger.warning(f"Rate limited by Telegram in dota_digest, skipping")
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
# function_fixed.py — только тонкий реэкспорт для совместимости.
from function_fixed import alternate_digest_job
from fissure import (
    fissure,
    recent_fissure_rolls,
)
from bot_utils import (
    is_valid_telegram_id,
    make_clickable,
    delete_last_bot_message,
    set_last_bot_message,
    add_bot_message,
    last_bot_message,
    format_time,
    main_menu,
    _build_analytics_keyboard,
    _build_stats_button_keyboard,
    schedule_delete,
    delete_after_delay,
    delete_message_job,
    ManualContext,
)
from stats import get_event_chances
from constants import (
    COOLDOWN,
    COOLDOWN_BANNER_URL,
    PROFILE_BANNER_URL,
    TOP_BANNER_URL,
    TOPMMR_BANNER_URL,
    LINK_BANNER_URL,
    SETDIGEST_BANNER_URL,
    ZEUS_BANNER_URL,
    DICE_ANIMATION_DELAY,
    USER_PROCESSING_TTL,
    BOT_CAN_DELETE_TTL,
    JOB_COOLDOWN,
    WEEKLY_JOB_COOLDOWN,
    WEEKEND_BONUS_MULTIPLIERS,
    MULTICAST_DEFAULT_CHANCE,
    ZEUS_DEFAULT_CHANCE,
    MORNING_DIGEST_HEADER,
    MORNING_DIGEST_FOOTER,
    DOTA_DIGEST_HEADER,
    DOTA_DIGEST_FOOTER,
    ZEUS_TEXTS,
    WELCOME_PHRASES,
)



# All roll data (ROLL_MEMES, CATEGORY_PHRASES), welcome phrases,
# multicast/zeus defaults, weekend multipliers and digest headers
# have been moved to rolls.py and constants.py.
# Local duplicates removed — using imported versions.




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




DEFAULT_AVATAR_URL = "https://i.ibb.co/nMSN7mHM/photo-2025-12-29-00-02-39.jpg"

async def get_user_avatar_url(bot, user_id: int) -> str | None:
    """Полный URL аватарки Telegram (для загрузки в generate_start_card)."""
    try:
        photos = await bot.get_user_profile_photos(user_id, limit=1)
        if photos and photos.photos:
            photo = photos.photos[0][-1]
            file = await bot.get_file(photo.file_id)
            if file.file_path:
                # file.file_path is already a full URL in python-telegram-bot v20+
                if file.file_path.startswith('http'):
                    return file.file_path
                # Otherwise construct URL from base_file_url and path
                return f"{bot.base_file_url}/{file.file_path}"
        logger.debug(f"No profile photos for user {user_id}")
    except Exception as e:
        logger.warning(f"Could not get user avatar: {e}")
    return DEFAULT_AVATAR_URL


async def resolve_avatar_url_for_card(
    bot,
    telegram_id: int | None = None,
    steam_id: int | None = None,
    db_avatar: str | None = None,
    fetch_steam: bool = True,
) -> str:
    """Steam → БД → Telegram → дефолтная картинка."""
    if db_avatar:
        return db_avatar
    if fetch_steam and steam_id:
        try:
            fresh = await asyncio.to_thread(_get_player_stats_wrapper, steam_id, False)
            if fresh and fresh.get("avatar"):
                return fresh["avatar"]
        except Exception as e:
            logger.warning(f"resolve_avatar_url_for_card steam {steam_id}: {e}")
    cached = None
    if telegram_id:
        cached = user_cache.get(telegram_id)
        if cached and cached.get("avatar"):
            return cached["avatar"]
        db_user = get_user(telegram_id)
        if db_user and db_user.get("avatar"):
            return db_user["avatar"]
    if telegram_id and bot:
        tg_url = await get_user_avatar_url(bot, telegram_id)
        if tg_url:
            return tg_url
    return DEFAULT_AVATAR_URL


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command - show profile card"""
    loading_msg = None
    animation_task = None
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
                if _telegram_error_contains(e, "not found", "bad request"):
                    logger.debug(f"User message {user_msg_id} already deleted: {e}")
                else:
                    logger.debug(f"Could not delete user message {user_msg_id}: {e}")

# Delete last bot message
        try:
            await delete_last_bot_message(context.bot, chat_id, user_id)
        except:
            pass

        # Send loading message and start animation in parallel
        try:
            loading_msg = await context.bot.send_message(
                chat_id=chat_id,
                text="⏳ Загружаю меню..."
            )
            logger.info(f"Created loading message in start: chat_id={chat_id}, msg_id={loading_msg.message_id}")

            # Start animation as background task
            async def animate_loading():
                for i in range(6):
                    try:
                        await asyncio.sleep(0.5)
                    except asyncio.CancelledError:
                        return
                    if loading_msg is None:
                        break
                    frame = "⌛️" if i % 2 == 1 else "⏳"
                    messages = ["Загружаю меню...", "Подготавливаю интерфейс...", "Строю карточку...", "Готово!"]
                    try:
                        await loading_msg.edit_text(f"{frame} {messages[min(i, len(messages)-1)]}")
                    except Exception:
                        pass

            animation_task = asyncio.create_task(animate_loading())
        except Exception as e:
            logger.debug(f"Could not send loading message in start: {e}")
            loading_msg = None

        if steam_id and steam_nickname:
            from dota_mmr import generate_start_card, get_player_stats, is_opendota_rate_limited

            # Get avatar - prefer cached, fallback to Telegram
            avatar_url = user.get("avatar")
            if not avatar_url:
                # If OpenDota API is rate limited, use Telegram avatar directly
                if is_opendota_rate_limited():
                    logger.info(f"OpenDota API rate limited, using Telegram avatar for user {user_id}")
                    avatar_url = await get_user_avatar_url(context.bot, user_id)
                else:
                    try:
                        stats = await asyncio.to_thread(get_player_stats, steam_id)
                        if stats and stats.get("avatar"):
                            avatar_url = stats["avatar"]
                        else:
                            avatar_url = await get_user_avatar_url(context.bot, user_id)
                    except Exception as e:
                        logger.warning(f"Could not get Steam avatar: {e}")
                        avatar_url = await get_user_avatar_url(context.bot, user_id)

            weekly_mvp, weekly_top2, weekly_top3 = 0, 0, 0

            # Run blocking card generation in thread pool to avoid blocking event loop
            card_data = await asyncio.to_thread(
                generate_start_card,
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
                if animation_task:
                    animation_task.cancel()
                if loading_msg:
                    try:
                        msg_id = loading_msg.message_id
                        logger.info(f"Deleting loading message: chat_id={chat_id}, msg_id={msg_id}")
                        await context.bot.delete_message(chat_id, msg_id)
                        logger.info(f"Successfully deleted loading message {msg_id}")
                    except Exception as e:
                        logger.error(f"Failed to delete loading message: {e}")
                return
            else:
                await menu_handler(update, context)
        else:
            # No Steam - show card with Telegram avatar, no message count
            from dota_mmr import generate_start_card

            avatar_url = await get_user_avatar_url(context.bot, user_id)

            # Run blocking card generation in thread pool to avoid blocking event loop
            card_data = await asyncio.to_thread(
                generate_start_card,
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
            if animation_task:
                animation_task.cancel()
            if loading_msg:
                try:
                    await context.bot.delete_message(chat_id, loading_msg.message_id)
                    logger.info(f"Deleted loading message {loading_msg.message_id} in start (no Steam)")
                except Exception as e:
                    logger.warning(f"Failed to delete loading message in start: {e}")

    except Exception as e:
        if animation_task:
            animation_task.cancel()
        error_str = str(e).lower()
        if _telegram_error_contains(e, "flood control", "429", "too many requests"):
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
    chat_id = callback_query.message.chat_id if callback_query.message else None

    # Handle analytics_show separately with loading indicator (as chat message)
    if data == "analytics_show":
        await callback_query.answer()  # Acknowledge callback immediately (no visual loading indicator)
        loading_msg = await context.bot.send_message(chat_id=chat_id, text="⏳ Загружаю детали матчей...")
        
        # Start animation as background task
        animation_task = None
        async def animate_analytics_loading():
            for i in range(6):
                try:
                    await asyncio.sleep(0.5)
                except asyncio.CancelledError:
                    return
                if loading_msg is None:
                    break
                frame = "⌛️" if i % 2 == 1 else "⏳"
                messages = ["Загружаю детали матчей...", "Анализирую статистику...", "Формирую таблицы...", "Готово!"]
                try:
                    await loading_msg.edit_text(f"{frame} {messages[min(i, len(messages)-1)]}")
                except Exception:
                    pass
        animation_task = asyncio.create_task(animate_analytics_loading())
        
        try:
            await _show_analytics_page(callback_query, 0, context, loading_msg=loading_msg)
        except Exception as e:
            logger.error(f"Error in button_callback: {e}", exc_info=True)
            # Try to edit loading message with error and schedule deletion
            try:
                await context.bot.edit_message_text(chat_id=chat_id, message_id=loading_msg.message_id, text="❌ Ошибка загрузки данных")
                schedule_delete(context.bot, chat_id, loading_msg.message_id, 30, context.application.job_queue)
            except Exception:
                pass
        finally:
            if animation_task:
                animation_task.cancel()
        return

    # Handle analytics_page_N - no loading indicator (pages already generated or will show error)
    if data and data.startswith("analytics_page_"):
        await callback_query.answer()  # Just acknowledge the callback
        try:
            page_idx = int(data.split("_")[-1])
            await _show_analytics_page(callback_query, page_idx, context)
        except Exception as e:
            logger.error(f"Error in button_callback: {e}", exc_info=True)
        return

    # Answer immediately for other button types
    await callback_query.answer()

    try:
        # === LINK HANDLER ===
        if data == "link":
            await link(update, context)
            return

    except Exception as e:
        logger.error(f"Error in button_callback: {e}", exc_info=True)
        await callback_query.answer(text="Ошибка при обработке кнопки", show_alert=True)


async def _show_analytics_page(callback_query, page_idx: int, context: ContextTypes.DEFAULT_TYPE, loading_msg=None):
    """Send a new message with analytics table when button is pressed.
    
    Pages are generated lazily — only when the user actually navigates to them.
    Creates a NEW message with the table, does NOT edit the chart message.
    If loading_msg is provided, it will be edited with the content instead of sending a new message.
    """
    from weekly_analytics import get_analytics_pages, fetch_match_details, calculate_player_stats

    generated = context.user_data.get('analytics_generated', set())
    pages = context.user_data.get('analytics_pages', [])
    chat_id = callback_query.message.chat_id

    # Determine if we need to generate pages (lazy loading)
    is_first_generation = page_idx not in generated or pages == [None, None]

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
                try:
                    await context.bot.delete_message(chat_id, loading_msg.message_id)
                except Exception:
                    pass
            return
        
        # Fetch full details for matches that have match_id
        telegram_id = callback_query.from_user.id
        user = get_user(telegram_id)
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
            stats = calculate_player_stats(matches)
            context.user_data['analytics_stats'] = stats
            context.user_data['analytics_role'] = role
            logger.info(f"Analytics: detected role={role}, stats keys={list(stats.keys()) if stats else 'None'}")
        
        # Ensure stats is valid before generating pages
        if not stats:
            await callback_query.answer(text="❌ Ошибка анализа статистики", show_alert=True)
            if loading_msg:
                try:
                    await context.bot.delete_message(chat_id, loading_msg.message_id)
                except Exception:
                    pass
            return
        
        try:
            all_pages = get_analytics_pages(role, stats)
            logger.info(f"Analytics: generated {len(all_pages)} pages")
        except Exception as e:
            logger.error(f"Error generating analytics pages: {e}", exc_info=True)
            await callback_query.answer(text=f"Ошибка: {e}", show_alert=True)
            if loading_msg:
                try:
                    await context.bot.delete_message(chat_id, loading_msg.message_id)
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
    keyboard = _build_analytics_keyboard(page_idx, total_pages, generated)

    try:
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
                    parse_mode="MarkdownV2"
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
            try:
                await loading_msg.edit_text(text=text, reply_markup=keyboard, parse_mode="MarkdownV2")
                context.user_data['analytics_table_msg_id'] = loading_msg.message_id
                job_queue = context.job_queue
                if job_queue:
                    schedule_delete(context.bot, chat_id, loading_msg.message_id, 60, job_queue)
                else:
                    schedule_delete(context.bot, chat_id, loading_msg.message_id, 60, None)
                return
            except Exception as edit_err:
                logger.debug(f"Could not edit loading message: {edit_err}")
                # Fall through to send new message
        
        # Send a NEW message with the analytics table (first click or previous was deleted)
        new_msg = await context.bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=keyboard,
            parse_mode="MarkdownV2"
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
            from digest import set_digest_type
            set_digest_type("0")
            set_config("alternate_digest_type", "0")
            set_config("alternate_digest_message_id", None)
            set_config("alternate_digest_last_created", "0")

            manual_context = ManualContext(context.application, context.bot)
            await alternate_digest_job(manual_context)

            msg = await context.bot.send_message(chat_id=chat_id, text="✅ Фиссура дайджест обновлён!")
            if chat.type in ['group', 'supergroup', 'channel']:
                schedule_delete(context.bot, chat_id, msg.message_id, 30, context.application.job_queue)

        elif command == "dotadigestnow":
            from digest import set_digest_type
            set_digest_type("1")
            set_config("alternate_digest_type", "1")
            set_config("alternate_digest_message_id", None)
            set_config("alternate_digest_last_created", "0")

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


async def recent_rolls_handler(request):
    """Public API: returns last 50 fissure rolls as JSON (for the website widget)."""
    import json
    data = list(recent_fissure_rolls)  # snapshot
    resp = web.Response(text=json.dumps(data, ensure_ascii=False), content_type="application/json")
    resp.headers['Access-Control-Allow-Origin'] = '*'          # Разрешаем запросы с сайта
    resp.headers['Access-Control-Allow-Methods'] = 'GET, OPTIONS'
    resp.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    return resp


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
    animation_task = None

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

            # Send loading message and start animation in parallel
            try:
                loading_msg = await context.bot.send_message(
                    chat_id=chat_id,
                    text="⏳ Формирую профиль..."
                )
                logger.info(f"Created loading message: chat_id={chat_id}, msg_id={loading_msg.message_id}")

                # Start animation as background task
                async def animate_loading():
                    for i in range(6):
                        try:
                            await asyncio.sleep(0.5)
                        except asyncio.CancelledError:
                            return
                        if loading_msg is None:
                            break
                        frame = "⌛️" if i % 2 == 1 else "⏳"
                        messages = ["Формирую профиль...", "Собираю данные...", "Анализирую статы...", "Готово!"]
                        try:
                            await loading_msg.edit_text(f"{frame} {messages[min(i, len(messages)-1)]}")
                        except Exception:
                            pass

                animation_task = asyncio.create_task(animate_loading())
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
        else:
            user_obj = update.effective_user
            target_id = user_obj.id
            target_name = user_obj.username or user_obj.first_name
        display_username = make_clickable(target_name, target_id)

        text = f"👑 {display_username}\n\n🍆 Фиссура: {target_user['fissure']:.1f} см\n🎲 Броски: {target_user.get('total_rolls', 0)} 🍀Стрик: {target_user.get('current_streak', 0)}/{target_user.get('best_streak', 0)}"

        # Dota stats (без стрика)
        if target_user.get('steam_id'):
            week_games = target_user.get('week_games', 0)
            week_wins = target_user.get('week_wins', 0)
            week_losses = week_games - week_wins
            winrate = round((week_wins / week_games * 100), 1) if week_games > 0 else 0

            last_10_balls = ""
            try:
                from dota_mmr import get_recent_matches_async, get_top_heroes_async
                steam_id = target_user.get('steam_id')
                top_heroes = []
                
                if steam_id:
                    # Параллельно получаем матчи и героев
                    try:
                         matches, top_heroes = await asyncio.gather(
                             get_recent_matches_async(steam_id, limit=10),
                             get_top_heroes_async(steam_id, last_n=10, top_k=5)
                         )
                         logger.info(f"Steam {steam_id}: got {len(matches)} matches, {len(top_heroes) if top_heroes else 0} heroes")
                    except asyncio.TimeoutError:
                        logger.warning(f"Timeout getting matches/heroes for steam_id={steam_id}, using cache/default")
                    except Exception as e:
                        logger.debug(f"Could not get matches/heroes: {e}")
                        matches, top_heroes = [], []
                    
                    matches = sorted(matches, key=lambda x: x.get('start_time', 0), reverse=True)
                    week_match_count = min(len(matches), week_games)
                    matches = matches[:week_match_count]
                    for match in matches:
                        player_slot = match.get('player_slot')
                        radiant_win = match.get('radiant_win', False)
                        player_was_radiant = player_slot < 127 if player_slot is not None else True
                        is_win = (radiant_win and player_was_radiant) or (not radiant_win and not player_was_radiant)
                        last_10_balls += "🟢" if is_win else "🔴"
                    if last_10_balls:
                        last_10_balls = last_10_balls.replace("🟢", "🟢‍").replace("🔴", "🔴‍")
            except Exception as e:
                logger.debug(f"Could not get last matches: {e}")

            text += f"\n\n🎮 Dota за неделю:\n📊 {week_wins}W • {week_losses}L • WR {winrate}%"

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

# Добавляем героев только если они есть
            if top_heroes:
                text += "\n\n🌟 Любимые герои за 10 матчей:"
            else:
                text += "\n\n💡 /profile ＠ник — чужой профиль"

        # Banner URL - для Steam использовать картинку с героями
        profile_banner_url = "https://i.ibb.co/n8g8yQYt/dasdsadasdsadasdsad.png"

        try:
            from dota_mmr import generate_heroes_image
            img_bytes = await asyncio.to_thread(generate_heroes_image, top_heroes)
            if img_bytes:
                profile_banner_url = io.BytesIO(img_bytes)
                logger.info(f"Successfully generated heroes image, size: {len(img_bytes)} bytes")
        except asyncio.TimeoutError as e:
            logger.warning(f"Timeout generating heroes image, using default banner")
        except Exception as e:
            logger.error(f"Could not generate heroes image: {e}", exc_info=True)

        result_msg = await context.bot.send_photo(
            chat_id=update.message.chat_id,
            photo=profile_banner_url,
            caption=text,
            parse_mode="HTML",
            reply_markup=main_menu()
        )
        logger.info(f"Profile photo sent successfully, result_msg_id={result_msg.message_id}")

        # Delete loading message immediately after successful send
        if animation_task:
            animation_task.cancel()
        if loading_msg:
            logger.info(f"Loading msg exists: {loading_msg.message_id}, attempting delete...")
            try:
                await context.bot.delete_message(chat_id, loading_msg.message_id)
                logger.info(f"SUCCESS: Deleted loading message {loading_msg.message_id} in stats")
            except Exception as del_e:
                logger.error(f"ERROR: Failed to delete loading message in stats: {del_e}")
        else:
            logger.warning(f"loading_msg is None, cannot delete (already deleted during animation)")

        set_last_bot_message(chat_id, update.effective_user.id, result_msg.message_id)
        schedule_delete(context.bot, chat_id, result_msg.message_id, 30, context.application.job_queue)
        update_last_message_id(update.effective_user.id, result_msg.message_id)

    except asyncio.TimeoutError as e:
        if animation_task:
            animation_task.cancel()
        logger.error(f"Timeout in stats: {e}")
        if loading_msg:
            try:
                await context.bot.delete_message(chat_id, loading_msg.message_id)
            except Exception:
                pass
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
        if animation_task:
            animation_task.cancel()
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
                clickable_name = f'<b>{make_clickable(name, telegram_id)}</b>'
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

            # Ссылка на live логи фиссур внизу топа
            text += "\n\n<b><a href=\"https://seredin999.onrender.com/fissure-logs\">📜 Последние роллы</a></b>"

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
                    # Make all nicknames clickable and bold
                    player_id = player.get('telegram_id')
                    clickable_name = make_clickable(username, player_id)
                    lines.append(f"{medal} <b>{clickable_name}</b> - {rank_str}")
                    lines.append(f" └ {week_wins}W • {week_losses}L • WR {wr}%")
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
                user_display = make_clickable(user_username, user.get('telegram_id'))
                if user_is_in_top:
                    top_text += f"\n\n<b>{get_emoji_num(user_pos)} {user_display}: {user_rank_str}</b>\n"
                    top_text += f" └ В топе • {user_week_wins}W • {user_week_losses}L • WR {user_wr}%"
                else:
                    top_text += f"\n\n<b>{get_emoji_num(user_pos)} {user_display}: {user_rank_str}</b>\n"
                    top_text += f" └ {user_week_wins}W • {user_week_losses}L • WR {user_wr}%"
            elif user and user_week_games == 0:
                user_display = make_clickable(user_username, user.get('telegram_id'))
                top_text += f"\n\n<b>❓{user_display}</b>\n"
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

    # Если есть аргумент - привязываем в фоне, чтобы не блокировать event loop
    if identifier:
        try:
            loading_msg = await context.bot.send_message(
                chat_id=chat_id,
                text="⏳ Привязываю аккаунт Dota 2…"
            )

            from dota_mmr import register_steam
            result = await asyncio.to_thread(register_steam, update.effective_user.id, identifier)

            # Удалить loading сообщение
            try:
                await context.bot.delete_message(chat_id, loading_msg.message_id)
            except Exception:
                pass

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

async def info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Информация с кнопкой перехода на патч заметки"""
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
    info_banner_url = "https://i.ibb.co/zWW6DvLW/photo-2026-05-19-02-50-04.png"

    # Создаем inline клавиатуру с кнопкой
    keyboard = [[
        InlineKeyboardButton("📄 Информация о боте и патчах", url="https://seredin999.onrender.com/patch-fissure")
    ]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    # Отправляем фото с баннером и кнопкой (без подписи)
    result_msg = await context.bot.send_photo(
        chat_id=chat_id,
        photo=info_banner_url,
        caption=None,
        reply_markup=reply_markup
    )

    # Отслеживаем это сообщение для будущего удаления
    set_last_bot_message(chat_id, update.effective_user.id, result_msg.message_id)
    add_bot_message(chat_id, update.effective_user.id, result_msg.message_id)
    schedule_delete(context.bot, chat_id, result_msg.message_id, 30, context.application.job_queue)
    update_last_message_id(update.effective_user.id, result_msg.message_id)

    # Небольшая задержка для обеспечения видимости сообщения
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
                    updates = {'message_count': new_count, 'in_chat': True}
                    # Обновляем username только если есть telegram_username и он отличается;
                    # или если username пуст, а есть first_name — используем first_name как fallback
                    current_username = db_user.get('username')
                    new_telegram_username = update.effective_user.username
                    if new_telegram_username and new_telegram_username != current_username:
                        updates['username'] = new_telegram_username
                    elif current_username is None and update.effective_user.first_name:
                        updates['username'] = update.effective_user.first_name
                    # Не сохраняем в БД при каждом сообщении - только в кеш
                    # БД будет обновлена при завершении работы или ежедневно
                    update_user_fields_batch(user_id, updates, save_to_db=False)
                    logger.info(f"Cached message_count for {user_id}: {new_count}")
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
                    # Telegram entities use UTF-16 code unit offsets/lengths.
                    # Correct length prevents "ends in the middle of a utf-16 symbol" with emojis.
                    utf16_bytes = name.encode('utf-16-le')
                    name_utf16_len = len(utf16_bytes) // 2
                    welcome_text = f"{name}, {phrase}"
                    entities = [MessageEntity(
                        type=MessageEntity.TEXT_MENTION,
                        offset=0,
                        length=name_utf16_len,
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
                    welcome_text = f"{make_clickable(name, user_id)}, {phrase}"
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
        # Pre-warm matplotlib font cache to avoid runtime delays
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        plt.figure()
        plt.close()
        logger.info("Matplotlib font cache pre-warmed")

        init_db()
        migrate_db()

        from database import get_all_users, get_all_users_with_steam, user_cache
        all_users = get_all_users()
        for u in all_users:
            user_cache.set(u['telegram_id'], u)
        logger.info(f"Loaded {len(all_users)} users into cache on startup")

        from database import update_dota_week_top_cache
        update_dota_week_top_cache()
        logger.info("Dota week top cache initialized on startup")

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
            read_timeout=30.0,
            write_timeout=30.0,
            connect_timeout=30.0,
            pool_timeout=30.0
        )
        app = ApplicationBuilder().token(TOKEN).job_queue(job_queue).request(request).build()
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

        job_queue.run_daily(
            cleanup_left_users_job,
            time=datetime.time(hour=4, minute=0),  # 07:00 MSK
            days=(0, 1, 2, 3, 4, 5, 6)
        )

        # Лёгкая проверка членства в чате (без нагрузки)
        # Раз в 12 часов проверяем только 35 самых "старых" пользователей
        job_queue.run_repeating(
            verify_chat_membership_job,
            interval=datetime.timedelta(hours=12),
            first=datetime.timedelta(hours=2),   # первый запуск через 2 часа после старта
        )

        job_queue.run_repeating(
            flush_users_cache_job,
            interval=datetime.timedelta(minutes=30),
            first=datetime.timedelta(minutes=15),
        )

        # morning_digest_job удалён

        # Обновление MMR каждый час (актуальные данные)
        job_queue.run_repeating(
            update_all_mmr_job,
            interval=datetime.timedelta(hours=1),
            first=datetime.datetime.now() + datetime.timedelta(minutes=10)
        )

# Дайджест (Fissure + Dota):
# - Тяжёлая работа (лидерство + обновление данных из БД) — раз в 20 минут (максимальная экономия Neon часов)
# - Быстрый 15-секундный тик (только переключение типов) — чисто в памяти, без БД
        job_queue.run_repeating(
            alternate_digest_job,
            interval=datetime.timedelta(minutes=20),
            first=datetime.datetime.now() + datetime.timedelta(seconds=10)
        )

        # Обновление кеша Dota Weekly Top раз в час
        # (для alternate_digest + /topmmr). Позволяет 20-минутному дайджесту
        # брать данные почти без тяжёлых запросов в БД.
        async def _refresh_dota_week_top_cache(context):
            """Асинхронная обёртка: тяжёлая синхронная работа уходит в thread."""
            await asyncio.to_thread(update_dota_week_top_cache)

        job_queue.run_repeating(
            _refresh_dota_week_top_cache,
            interval=datetime.timedelta(hours=1),
            first=datetime.datetime.now() + datetime.timedelta(minutes=5)
        )

        # ✅ Объявление чемпиона недели в воскресенье 23:30 MSK
        job_queue.run_daily(
            weekly_champion_announcement_job,
            time=datetime.time(hour=20, minute=30),  # 20:30 UTC = 23:30 MSK
            days=(6,)  # Только воскресенье
        )

# ✅ Сброс MMR статистики в понедельник 00:00 MSK (начало новой недели)
        job_queue.run_daily(
            weekly_mmr_reset_job,
            time=datetime.time(hour=21, minute=0),  # 21:00 UTC = 00:00 MSK
            days=(0,),  # Только понедельник
        )

        # Если бот стартует в понедельник после 00:00 - выполняем сброс немедленно
        from datetime import datetime as dt, timezone, timedelta
        MSK = timezone(timedelta(hours=3))
        now_msk = dt.now(MSK)
        if now_msk.weekday() == 0:  # Понедельник
            # Проверяем, не был ли уже сброс сегодня
            from database import get_config, set_config
            today = now_msk.strftime("%Y-%m-%d")
            last_reset = get_config('weekly_mmr_reset_date')
            if last_reset != today:
                try:
                    # Выполняем синхронный сброс
                    from database import get_connection, DATABASE_URL
                    import urllib.parse as urlparse
                    conn = get_connection()
                    cursor = conn.cursor()
                    url_parsed = urlparse.urlparse(DATABASE_URL)
                    scheme = url_parsed.scheme
                    current_week_start = today
                    if "postgres" in scheme:
                        cursor.execute("""
                            UPDATE users SET week_games = 0, week_wins = 0, week_current_streak = 0,
                                week_best_streak = GREATEST(week_best_streak, week_current_streak),
                                week_start_date = %s WHERE steam_id IS NOT NULL
                        """, (current_week_start,))
                    else:
                        cursor.execute("""
                            UPDATE users SET week_games = 0, week_wins = 0, week_current_streak = 0,
                                week_best_streak = MAX(week_best_streak, week_current_streak),
                                week_start_date = ? WHERE steam_id IS NOT NULL
                        """, (current_week_start,))
                    conn.commit()
                    cursor.close()
                    from database import user_cache, top_cache
                    user_cache.clear()
                    top_cache.clear()
                    user_cache.delete_key('dota_week_top')
                    set_config('weekly_mmr_reset_date', today)
                    logger.info(f"Startup: weekly stats reset for {current_week_start}")
                except Exception as e:
                    logger.error(f"Startup weekly reset error: {e}")

        

        app.add_handler(CommandHandler("start", start))
        app.add_handler(CallbackQueryHandler(button_callback))
        app.add_handler(CommandHandler(("fissure", "fissura"), fissure))
        app.add_handler(CommandHandler("profile", stats))
        app.add_handler(CommandHandler("info", info))
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
            web_app.router.add_get('/api/recent-rolls', recent_rolls_handler)
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
            web_app.router.add_get('/api/recent-rolls', recent_rolls_handler)

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



