# -*- coding: utf-8 -*-
import os
import io
import random
import time
import asyncio
import logging
import datetime
import urllib.parse as urlparse
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, Message
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters, JobQueue, ChatMemberHandler, CallbackQueryHandler
from telegram.error import Conflict
from database import init_db, get_user, update_fissure, get_fissure_top, update_last_message_id, Database, get_user_rank, get_fissure_rank, decrease_inactive_fissure, get_config, set_config, get_digest_stats, update_player_positions, update_digest_snapshot, migrate_db, get_connection, get_dota_digest_stats, set_user_in_chat, zeus_strike, get_user_by_username, delete_user, top_cache, update_user_fields_batch, get_dota_mmr_top, get_dota_week_top, BACKUP_DATABASE_URL

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

# Глобальная переменная для отслеживания активности бота
last_update_time = time.time()

COOLDOWN = 86400  # 24 hours

_user_processing = {}  # Spam protection: user_id -> timestamp

_digest_state = {"type": None, "chat_id": None, "last_data_update": 0, "last_run": 0}
DIGEST_DATA_REFRESH_INTERVAL = 3600  # 1 час - обновление данных из БД


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



_bot_can_delete_cache = {}
_bot_can_delete_ttl = 3600  # 1 час

async def bot_can_delete(bot, chat_id):
    """Проверить может ли бот удалять сообщения в чате"""
    cached = _bot_can_delete_cache.get(chat_id)
    if cached is not None:
        cached_val, cached_time = cached
        if time.time() - cached_time < _bot_can_delete_ttl:
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
    if job_queue:
        try:
            job_queue.run_once(
                delete_message_job,
                delay,
                data={'chat_id': chat_id, 'msg_id': msg_id},
                name=f"delete_{chat_id}_{msg_id}"
            )
            logger.info(f"Scheduled delete for msg {msg_id} in {delay}s via job_queue")
        except Exception as e:
            logger.warning(f"JobQueue failed, using asyncio fallback: {e}")
            asyncio.create_task(delete_after_delay(bot, chat_id, msg_id, delay, None))
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


async def announce_weekly_mmr_winner(bot):
    """Отправляет поздра��ление победителю недельного топа MMR при смене недели."""
    from datetime import timezone, timedelta
    MSK = timezone(timedelta(hours=3))
    today_msk = datetime.datetime.now(MSK)
    monday_msk = today_msk - datetime.timedelta(days=today_msk.weekday())
    current_week_start = monday_msk.strftime("%Y-%m-%d")

    last_announced = get_config('mmr_week_top_announced')
    if last_announced == current_week_start:
        return

    if today_msk.weekday() != 0:
        return

    if today_msk.hour >= 1:
        logger.info(f"announce_weekly_mmr_winner: пропуск, уже {today_msk.hour}:00 MSK — окно объявления прошло")
        set_config('mmr_week_top_announced', current_week_start)
        return

    from database import get_connection, DATABASE_URL
    conn = get_connection()
    cursor = conn.cursor()
    url = urlparse.urlparse(DATABASE_URL)
    scheme = url.scheme
    if "postgres" in scheme:
        cursor.execute(
            "SELECT COUNT(*) FROM users WHERE steam_id IS NOT NULL AND week_games > 0 AND (week_start_date IS NULL OR week_start_date::text != %s)",
            (current_week_start,)
        )
    else:
        cursor.execute(
            "SELECT COUNT(*) FROM users WHERE steam_id IS NOT NULL AND week_games > 0 AND (week_start_date IS NULL OR week_start_date != ?)",
            (current_week_start,)
        )
    stale_count = cursor.fetchone()[0]
    cursor.close()

    if stale_count == 0:
        logger.info("announce_weekly_mmr_winner: все пользователи уже обновлены на новую неделю, пропуск")
        set_config('mmr_week_top_announced', current_week_start)
        return

    digest_chat_id = get_config('digest_chat_id')
    if not digest_chat_id:
        logger.info("announce_weekly_mmr_winner: чат для дайджеста не настроен")
        return

    from database import get_dota_week_top_from_db
    top_users = get_dota_week_top_from_db(5)
    if not top_users or all(u.get('week_games', 0) == 0 for u in top_users):
        logger.info("announce_weekly_mmr_winner: нет данных для топа MMR (никто не играл)")
        set_config('mmr_week_top_announced', current_week_start)
        return

    active_users = [u for u in top_users if u.get('week_games', 0) > 0]
    if not active_users:
        set_config('mmr_week_top_announced', current_week_start)
        return

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
        from database import update_user_fields_batch, get_user
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
    streak_text = f"\n🔥 Текущий стрик: {streak} побед" if streak > 0 else ""
    
    tag_info = ""
    if tag_set:
        tag_info = f"\n👤 Ему присвоен титул \"{mvp_tag}\" и добавлена медалька в профиль!"

    text = (
        f"\n🥇 {name_display}\n"
        f"📊 {rank_str} • {mmr} MMR\n\n"
        f"📈 Результат за неделю:\n"
        f" └ {week_wins}W / {week_losses}L • WR {winrate}%{streak_text}\n\n"
        f"🏆Этот игрок показал лучший результат в топе MMR за неделю!{tag_info}"
    )

    winner_banner_url = "https://i.ibb.co/Jj3vwbWB/ANQkz.jpg"
    
    await bot.send_photo(
        chat_id=digest_chat_id,
        photo=winner_banner_url,
        caption=text,
        parse_mode="HTML"
    )
    set_config('mmr_week_top_announced', current_week_start)
    logger.info(f"announce_weekly_mmr_winner: отправлено поздравление для {username} (неделя {current_week_start})")


async def backup_database_job(context):
    """Копирование данных в backup БД каждый час"""
    try:
        from database import BACKUP_DATABASE_URL, get_all_users_with_steam
        if not BACKUP_DATABASE_URL:
            return
        
        logger.info("Запуск копирования в backup БД")
        
        users = get_all_users_with_steam()
        if not users:
            logger.info("Нет пользователей для копирования")
            return
        
        import psycopg2
        from urllib.parse import urlparse
        
        backup_url = urlparse(BACKUP_DATABASE_URL)
        conn = psycopg2.connect(
            host=backup_url.hostname,
            port=backup_url.port or 5432,
            dbname=backup_url.path[1:],
            user=backup_url.username,
            password=backup_url.password
        )
        conn.autocommit = True
        cursor = conn.cursor()
        
        for user in users:
            try:
                cursor.execute("""
                    INSERT INTO users (telegram_id, username, steam_id, steam_nickname, mmr, rank_tier, 
                                      dota_total_games, dota_wins, week_games, week_wins, 
                                      week_best_streak, week_current_streak, week_start_date, 
                                      mmr_updated_at, rank_tier_updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (telegram_id) DO UPDATE SET
                        steam_id = EXCLUDED.steam_id,
                        steam_nickname = EXCLUDED.steam_nickname,
                        mmr = EXCLUDED.mmr,
                        rank_tier = EXCLUDED.rank_tier,
                        dota_total_games = EXCLUDED.dota_total_games,
                        dota_wins = EXCLUDED.dota_wins,
                        week_games = EXCLUDED.week_games,
                        week_wins = EXCLUDED.week_wins,
                        week_best_streak = EXCLUDED.week_best_streak,
                        week_current_streak = EXCLUDED.week_current_streak,
                        week_start_date = EXCLUDED.week_start_date,
                        mmr_updated_at = EXCLUDED.mmr_updated_at,
                        rank_tier_updated_at = EXCLUDED.rank_tier_updated_at
                """, (
                    user.get('telegram_id'),
                    user.get('username'),
                    user.get('steam_id'),
                    user.get('steam_nickname'),
                    user.get('mmr', 0),
                    user.get('rank_tier', 0),
                    user.get('dota_total_games', 0),
                    user.get('dota_wins', 0),
                    user.get('week_games', 0),
                    user.get('week_wins', 0),
                    user.get('week_best_streak', 0),
                    user.get('week_current_streak', 0),
                    user.get('week_start_date'),
                    user.get('mmr_updated_at'),
                    user.get('rank_tier_updated_at')
                ))
            except Exception as e:
                logger.debug(f"Error copying user {user.get('telegram_id')}: {e}")
        
        cursor.close()
        conn.close()
        logger.info(f"Скопировано {len(users)} пользователей в backup БД")
        
    except Exception as e:
        logger.error(f"Backup job error: {e}")


async def update_all_mmr_job(context):
    """Ежечасовое обновление MMR всех пользователей с привязанным Steam (только в кеш)"""
    try:
        logger.info("Запуск ежечасного обновления MMR")
        await announce_weekly_mmr_winner(context.bot)
        from dota_mmr import update_user_mmr
        from database import get_all_users_with_steam, user_cache, BACKUP_DATABASE_URL
        
        users = get_all_users_with_steam()
        if not users:
            logger.info("Нет пользователей с привязанным Steam для обновления MMR")
            return
        
        logger.info(f"Обновление MMR для {len(users)} пользователей")
        success_count = 0
        rank_up_users = []  # собираем для уведомлений
        
        for user in users:
            try:
                result = update_user_mmr(user['telegram_id'])
                if result and result.get('success'):
                    success_count += 1
                    logger.info(f"MMR updated for {user['telegram_id']}: {result.get('mmr')} MMR")

                    # Sync week stats from DB after MMR update
                    from database import get_user as get_db_user
                    db_user = get_db_user(user['telegram_id'])
                    if db_user:
                        user_cache.set(user['telegram_id'], {
                            **user_cache.get(user['telegram_id'], {}),
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
        
        # Отправляем уведомления о ранк-апах
        digest_chat_id = get_config('digest_chat_id')
        if digest_chat_id and rank_up_users:
            for user, rank_info in rank_up_users:
                try:
                    username = user.get('steam_nickname') or user.get('username') or 'Игрок'
                    telegram_id = user.get('telegram_id')
                    name_display = f"<a href=\"tg://user?id={telegram_id}\">{username}</a>" if telegram_id else username
                    text = f"{name_display} повысил ранг!\n{rank_info['old_rank']} → {rank_info['new_rank']}"
                    rank_up_banner_url = "https://i.ibb.co/8LbRb8Zh/dsadasdas23323.png"
                    await context.bot.send_photo(chat_id=digest_chat_id, photo=rank_up_banner_url, caption=text, parse_mode="HTML")
                except Exception as notify_err:
                    logger.error(f"Ошибка отправки уведомления о ранк-апе: {notify_err}")
    except Exception as e:
        logger.error(f"Ошибка в update_all_mmr_job: {e}")


async def morning_digest_job(context):
    """Утренний дайджест (9:00)"""
    try:
        # Блокировка от параллельного запуска
        import time
        last_run = get_config('morning_digest_last_run')
        now = time.time()
        if last_run and (now - float(last_run)) < JOB_COOLDOWN:
            logger.info(f"morning_digest_job: пропуск (запущен {(now - float(last_run)):.1f}с назад)")
            return
        set_config('morning_digest_last_run', str(now))
        
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
        
        # Используем глобальную функцию make_clickable
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
        
        if streak_player and streak_player != "None" and streak_len > 0:
            streak_part = f"🍀{streak_display} - Стрик {streak_len}"
        else:
            streak_part = "🍀—"
        
        text = f"{growth_part} ┃{drop_part} ┃{streak_part}\n\n{MORNING_DIGEST_HEADER}\n\n\n🎁 Сбор фиссур: {daily_fissure_rolls} из {BONUS_FISSURE_GOAL}\n\n{MORNING_DIGEST_FOOTER}"
        
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
        
        # Удаляем старое сообщение дайджеста перед созданием нового
        if last_message_id:
            try:
                await bot.delete_message(chat_id=digest_chat_id, message_id=int(last_message_id))
                logger.info(f"Удалено старое сообщение дайджеста {last_message_id}")
            except Exception as e:
                logger.debug(f"Не удалось удалить старое сообщение дайджеста: {e}")
        
        # Отправляем новое сообщение
        msg = await bot.send_message(chat_id=digest_chat_id, text=text, parse_mode="HTML")
        set_config('daily_digest_message_id', msg.message_id)
        logger.info(f"Создан новый утренний дайджест {msg.message_id}")
        if not getattr(context, "manual", False):
            update_digest_snapshot()
        
        # Закрепляем новый дайджест
        try:
            await bot.unpin_chat_message(chat_id=digest_chat_id)
        except Exception as e:
            logger.debug(f"Не удалось открепить старый дайджест: {e}")
        try:
            await bot.pin_chat_message(chat_id=digest_chat_id, message_id=msg.message_id, disable_notification=True)
            logger.info(f"Дайджест {msg.message_id} закреплён")
            
            # Удаляем системное сообщение о закрепе
            try:
                chat_info = await bot.get_chat(chat_id=digest_chat_id)
                pinned_msg = getattr(chat_info, 'pinned_message', None)
                if pinned_msg:
                    await bot.delete_message(chat_id=digest_chat_id, message_id=pinned_msg.message_id)
                    logger.debug(f"Удалено системное сообщение о закрепе {pinned_msg.message_id}")
            except Exception as e:
                logger.debug(f"Не удалось удалить системное сообщение о закрепе: {e}")
        except Exception as e:
            logger.debug(f"Не удалось закрепить дайджест: {e}")
        
    except Exception as e:
        logger.error(f"Ошибка в morning_digest_job: {e}", exc_info=True)




async def refresh_digest_message(bot):
    """Обновляет сообщение дайджеста после каждого броска"""
    try:
        digest_chat_id = get_config('digest_chat_id')
        if not digest_chat_id:
            return
        
        # Получаем статистику (сравнивает со старым снимком)
        # НЕ обновляем снимок! Он обновляется только в morning_digest_job
        stats = get_digest_stats()
        
        # Формируем сообщение с кликабельными никнеймами
        growth_player, growth_pos = stats.get("top_growth", ("None", 0))
        drop_player, drop_cm = stats.get("top_drop", ("None", 0.0))
        streak_player, streak_len = stats.get("top_streak", ("None", 0))
        
        # Получаем telegram_id для создания кликабельных ссылок
        growth_id = stats.get("top_growth_id")
        drop_id = stats.get("top_drop_id")
        streak_id = stats.get("top_streak_id")
        
        # Используем глобальную функцию make_clickable
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
        
        if streak_player and streak_player != "None" and streak_len > 0:
            streak_part = f"🍀{streak_display} - Стрик {streak_len}"
        else:
            streak_part = "🍀—"
        
        text = f"{growth_part} ┃{drop_part} ┃{streak_part}\n\n{MORNING_DIGEST_HEADER}\n\n\n🎁 Сбор фиссур: {daily_fissure_rolls} из {BONUS_FISSURE_GOAL}\n\n{MORNING_DIGEST_FOOTER}"
        
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
                    logger.info(f"Старый дайджест {last_message_id} удалён/недоступен, сбрасываем ID")
                    set_config('daily_digest_message_id', None)
                else:
                    logger.debug(f"Не удалось обновить дайджест: {e}")
        
        # Если message_id пустой/None - не создаём новое сообщение, morning_digest_job создаст его
        logger.debug("Нет message_id для дайджеста, не создаём (ждём morning_digest_job)")
        
    except Exception as e:
        logger.error(f"Ошибка в refresh_digest_message: {e}", exc_info=True)


async def digest_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ручной запуск утреннего дайджеста в этот чат"""
    try:
        chat = update.effective_chat
        chat_id = chat.id
        # В группах удаляем сообщение пользователя с командой
        if chat.type in ['group', 'supergroup', 'channel']:
            if await bot_can_delete(context.bot, chat_id):
                try:
                    await context.bot.delete_message(chat_id, update.message.message_id)
                except Exception as e:
                    logger.debug(f"Could not delete user message: {e}")
        # Сохраняем этот чат как чат для дайджеста и сбрасываем message_id
        set_config("digest_chat_id", chat_id)
        set_config("daily_digest_message_id", None)

        # Создаём контекст для ручного вызова дайджеста
        class ManualContext:
            def __init__(self, application, bot):
                self.application = application
                self.bot = bot
                self.manual = True

        manual_context = ManualContext(context.application, context.bot)
        await alternate_digest_job(manual_context)

        msg = await context.bot.send_message(chat_id=update.effective_chat.id, text="✅ Фиссура дайджест обновлён!")
        if chat.type in ['group', 'supergroup', 'channel']:
            schedule_delete(context.bot, chat_id, msg.message_id, 30, context.application.job_queue)
    except Exception as e:
        logger.error(f"Error in digest_now: {e}", exc_info=True)
        try:
            err_msg = await context.bot.send_message(chat_id=update.effective_chat.id, text="❌ Не удалось создать дайджест сейчас", reply_markup=main_menu())
            chat = update.effective_chat
            if chat and chat.type in ['group', 'supergroup', 'channel']:
                schedule_delete(context.bot, chat.id, err_msg.message_id, 30, context.application.job_queue)
        except Exception:
            pass


async def dota_digest_job(context):
    """Dota дайджест - лучший/худший винрейт и стрик побед за неделю"""
    try:
        # Блокировка от параллельного запуска
        import time
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
        
        # Лучший винрейт
        top_by_wr = max(valid_players, key=lambda p: (p.get('week_wins', 0) / p.get('week_games', 1) if p.get('week_games', 0) > 0 else 0))
        # Худший винрейт
        bottom_by_wr = min(valid_players, key=lambda p: (p.get('week_wins', 0) / p.get('week_games', 1) if p.get('week_games', 0) > 0 else 0))
        # Лучший стрик - только игроки со стриком > 0
        players_with_streak = [p for p in valid_players if p.get('week_current_streak', 0) > 0]
        top_streak_player = max(players_with_streak, key=lambda p: p.get('week_current_streak', 0)) if players_with_streak else None
        
        top_player = top_by_wr.get('steam_nickname', 'None')
        top_rank = top_by_wr.get('rank_tier', 0)
        top_games = top_by_wr.get('week_games', 0)
        top_wins = top_by_wr.get('week_wins', 0)
        top_id = top_by_wr.get('telegram_id')
        
        bottom_player = bottom_by_wr.get('steam_nickname', 'None')
        bottom_rank = bottom_by_wr.get('rank_tier', 0)
        bottom_games = bottom_by_wr.get('week_games', 0)
        bottom_wins = bottom_by_wr.get('week_wins', 0)
        bottom_id = bottom_by_wr.get('telegram_id')
        
        if top_streak_player:
            streak_player = top_streak_player.get('steam_nickname', 'None')
            streak_wins = top_streak_player.get('week_current_streak', 0)
            streak_id = top_streak_player.get('telegram_id')
        else:
            streak_player = 'None'
            streak_wins = 0
            streak_id = None
        
        # Форматируем винрейт (по реальным победам/поражениям, макс 100%)
        if top_games > 0 and top_wins >= 0:
            top_losses = max(0, top_games - top_wins)
            top_total = top_wins + top_losses
            top_winrate = min(round((top_wins / top_total * 100), 1), 100.0) if top_total > 0 else 0
        else:
            top_winrate = 0
            top_losses = 0
        
        if bottom_games > 0 and bottom_wins >= 0:
            bottom_losses = max(0, bottom_games - bottom_wins)
            bottom_total = bottom_wins + bottom_losses
            bottom_winrate = min(round((bottom_wins / bottom_total * 100), 1), 100.0) if bottom_total > 0 else 0
        else:
            bottom_winrate = 0
            bottom_losses = 0
        
        # Используем make_clickable для никнеймов
        top_display = make_clickable(top_player, top_id) if top_player and top_player != "None" else "—"
        bottom_display = make_clickable(bottom_player, bottom_id) if bottom_player and bottom_player != "None" else "—"
        streak_display = make_clickable(streak_player, streak_id) if streak_player and streak_player != "None" and streak_wins > 0 else "—"
        
        # Формат: 🎯 Джумбет▲ 5/3 (62.5%)
        if top_player and top_player != "None":
            top_losses = max(0, top_games - top_wins)
            top_part = f"🎯 {top_display}▲ {top_wins}/{top_losses} ({top_winrate}%)"
        else:
            top_part = "🔺—"
        
        if bottom_player and bottom_player != "None":
            bottom_losses = max(0, bottom_games - bottom_wins)
            bottom_part = f"🔻{bottom_display}: {bottom_wins}W/{bottom_losses}L≈{bottom_winrate}%"
        else:
            bottom_part = "🔻—"
        
        if streak_player and streak_player != "None" and streak_wins > 0:
            streak_part = f" 🔸{streak_display}: {streak_wins}"
        else:
            streak_part = " 🔸—"
        
        text = f"<b>{top_part} {bottom_part} {streak_part}</b>\n\n{DOTA_DIGEST_HEADER}\n\n{DOTA_DIGEST_FOOTER}"
        
        bot = context.application.bot
        
        # Пробуем отредактировать существующее сообщение
        last_message_id = get_config('dota_digest_message_id')
        if last_message_id:
            try:
                await bot.edit_message_text(
                    chat_id=digest_chat_id,
                    message_id=int(last_message_id),
                    text=text,
                    parse_mode="HTML"
                )
                logger.info(f"Обновлён существующий Dota дайджест {last_message_id}")
                return
            except Exception as e:
                error_str = str(e)
                if "Message to edit not found" in error_str or "message can't be edited" in error_str:
                    logger.info(f"Старое сообщение {last_message_id} удалено или нельзя редактировать, создаём новое")
                    set_config('dota_digest_message_id', None)
                else:
                    logger.info(f"Не удалось редактировать сообщение: {e}")
        
        # Отправляем новое сообщение
        msg = await bot.send_message(chat_id=digest_chat_id, text=text, parse_mode="HTML")
        set_config('dota_digest_message_id', msg.message_id)
        logger.info(f"Создан новый Dota дайджест {msg.message_id}")
        
    except Exception as e:
        logger.error(f"Ошибка в dota_digest_job: {e}", exc_info=True)


async def dota_digest_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ручной запуск Dota дайджеста в этот чат"""
    try:
        chat = update.effective_chat
        chat_id = chat.id
        # В группах удаляем сообщение пользователя с командой
        if chat.type in ['group', 'supergroup', 'channel']:
            if await bot_can_delete(context.bot, chat_id):
                try:
                    await context.bot.delete_message(chat_id, update.message.message_id)
                except Exception as e:
                    logger.debug(f"Could not delete user message: {e}")
        # Сохраняем этот чат как чат для дайджеста и сбрасываем message_id
        set_config("digest_chat_id", chat_id)
        set_config("dota_digest_message_id", None)

        # Создаём контекст для ручного вызова дайджеста
        class ManualContext:
            def __init__(self, application, bot):
                self.application = application
                self.bot = bot
                self.manual = True

        manual_context = ManualContext(context.application, context.bot)
        await dota_digest_job(manual_context)

        msg = await context.bot.send_message(chat_id=update.effective_chat.id, text="✅ Dota дайджест для этого чата создан/обновлён.")
        if chat.type in ['group', 'supergroup', 'channel']:
            schedule_delete(context.bot, chat_id, msg.message_id, 30, context.application.job_queue)
    except Exception as e:
        logger.error(f"Error in dota_digest_now: {e}", exc_info=True)
        try:
            err_msg = await context.bot.send_message(chat_id=update.effective_chat.id, text="❌ Не удалось создать Dota дайджест сейчас")
            chat = update.effective_chat
            if chat and chat.type in ['group', 'supergroup', 'channel']:
                schedule_delete(context.bot, chat.id, err_msg.message_id, 30, context.application.job_queue)
        except Exception:
            pass


async def alternate_digest_job(context):
    """Чередование утреннего и Dota дайджестов каждые 15 секунд"""
    try:
        import time
        now = time.time()
        
        # Блокировка от параллельного запуска (в памяти)
        last_run = _digest_state.get('last_run', 0)
        if now - last_run < 10:
            logger.info(f"alternate_digest_job: пропуск (запущен {(now - last_run):.1f}с назад)")
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
        
        # Получаем текущий тип дайджеста из памяти
        current_type = _digest_state.get("type")
        if current_type is None:
            # Ensure string type - convert from int if needed
            raw_type = get_config('alternate_digest_type')
            if raw_type is not None:
                current_type = str(raw_type)
            else:
                current_type = "0"
            _digest_state["type"] = current_type
        logger.info(f"alternate_digest_job: current_type = {current_type} (type={type(current_type).__name__}), _digest_state = {_digest_state}")
        if current_type is None:
            current_type = "0"
        
        # Формируем текст в зависимости от типа
        if current_type == "0":
            # Утренний дайджест
            # Используем закэшированные данные если есть
            if _digest_state.get("digest_data") is None:
                stats = get_digest_stats()
                _digest_state["digest_data"] = stats
            else:
                stats = _digest_state["digest_data"]
            
            growth_player, growth_pos = stats.get("top_growth", ("None", 0))
            drop_player, drop_cm = stats.get("top_drop", ("None", 0.0))
            streak_player, streak_len = stats.get("top_streak", ("None", 0))
            
            growth_id = stats.get("top_growth_id")
            drop_id = stats.get("top_drop_id")
            streak_id = stats.get("top_streak_id")
            
            growth_display = make_clickable(growth_player, growth_id)
            drop_display = make_clickable(drop_player, drop_id)
            streak_display = make_clickable(streak_player, streak_id)
            
            if growth_player and growth_player != "None":
                growth_part = f"🔺{growth_display} +{growth_pos}"
            else:
                growth_part = "🔺—"
            
            if drop_player and drop_player != "None":
                if drop_cm < 0:
                    drop_part = f"🔻{drop_display} {drop_cm:.0f} СМ"
                else:
                    drop_part = f"🔻{drop_display} +{drop_cm:.0f} СМ"
            else:
                drop_part = "🔻—"
            
            if streak_player and streak_player != "None" and streak_len > 0:
                streak_part = f" 🍀{streak_display}: {streak_len}"
            else:
                streak_part = " 🍀—"
            
            text = f"{growth_part} ┃{drop_part} ┃{streak_part}\n\n🌅ФИССУРА ДАЙДЖЕСТ\n🎁 Сбор фиссур: {daily_fissure_rolls} из {BONUS_FISSURE_GOAL}\n\n🔺 = рост позиций в топе\n🔻 = топ падение\n🍀 = текущий стрик побед"
            next_type = "1"
        else:
            # Dota дайджест
            # Используем закэшированные данные если есть
            if _digest_state.get("dota_data") is None:
                mmr_top = get_dota_week_top(limit=10)
                _digest_state["dota_data"] = mmr_top
            else:
                mmr_top = _digest_state["dota_data"]
            if not mmr_top:
                logger.info("Нет данных для Dota дайджеста")
                return
            
            valid_players = [p for p in mmr_top if p.get('week_games', 0) >= 3]
            
            if not valid_players:
                logger.info("Нет игроков с 3+ играми для Dota дайджеста")
                # Сохраняем пустой dota_data чтобы не делать запрос повторно до обновления
                _digest_state["dota_data"] = []
                return
            
            top_by_wr = max(valid_players, key=lambda p: (p.get('week_wins', 0) / p.get('week_games', 1) if p.get('week_games', 0) > 0 else 0))
            bottom_by_wr = min(valid_players, key=lambda p: (p.get('week_wins', 0) / p.get('week_games', 1) if p.get('week_games', 0) > 0 else 0))
            players_with_streak = [p for p in valid_players if p.get('week_current_streak', 0) > 0]
            top_streak_player = max(players_with_streak, key=lambda p: p.get('week_current_streak', 0)) if players_with_streak else None
            
            top_player = top_by_wr.get('steam_nickname', 'None')
            top_rank = top_by_wr.get('rank_tier', 0)
            top_games = top_by_wr.get('week_games', 0)
            top_wins = top_by_wr.get('week_wins', 0)
            top_id = top_by_wr.get('telegram_id')
            
            bottom_player = bottom_by_wr.get('steam_nickname', 'None')
            bottom_rank = bottom_by_wr.get('rank_tier', 0)
            bottom_games = bottom_by_wr.get('week_games', 0)
            bottom_wins = bottom_by_wr.get('week_wins', 0)
            bottom_id = bottom_by_wr.get('telegram_id')
            
            if top_streak_player:
                streak_player = top_streak_player.get('steam_nickname', 'None')
                streak_wins = top_streak_player.get('week_current_streak', 0)
                streak_id = top_streak_player.get('telegram_id')
            else:
                streak_player = 'None'
                streak_wins = 0
                streak_id = None
            
            # Форматируем винрейт правильно
            if top_games > 0 and top_wins >= 0:
                top_losses = max(0, top_games - top_wins)
                top_total = top_wins + top_losses
                top_winrate = min(round((top_wins / top_total * 100), 1), 100.0) if top_total > 0 else 0
            else:
                top_winrate = 0
                top_losses = 0
            
            if bottom_games > 0 and bottom_wins >= 0:
                bottom_losses = max(0, bottom_games - bottom_wins)
                bottom_total = bottom_wins + bottom_losses
                bottom_winrate = min(round((bottom_wins / bottom_total * 100), 1), 100.0) if bottom_total > 0 else 0
            else:
                bottom_winrate = 0
                bottom_losses = 0
            
            top_display = make_clickable(top_player, top_id) if top_player and top_player != "None" else "—"
            bottom_display = make_clickable(bottom_player, bottom_id) if bottom_player and bottom_player != "None" else "—"
            streak_display = make_clickable(streak_player, streak_id) if streak_player and streak_player != "None" and streak_wins > 0 else "—"
            
            if top_player and top_player != "None":
                top_losses = max(0, top_games - top_wins)
                top_part = f"🔺{top_display}: {top_wins}W/{top_losses}L≈{top_winrate}%"
            else:
                top_part = "🔺—"

            if bottom_player and bottom_player != "None":
                bottom_losses = max(0, bottom_games - bottom_wins)
                bottom_part = f"🔻{bottom_display}: {bottom_wins}W/{bottom_losses}L≈{bottom_winrate}%"
            else:
                bottom_part = "🔻—"

            if streak_player and streak_player != "None" and streak_wins > 0:
                streak_part = f" 🔸{streak_display}: {streak_wins}"
            else:
                streak_part = " 🔸—"
            
            text = f"<b>{top_part} {bottom_part} {streak_part}</b>\n\n{DOTA_DIGEST_HEADER}\n\n{DOTA_DIGEST_FOOTER}"
            next_type = "0"
        
        # Пробуем отредактировать существующее сообщение
        last_message_id = get_config('alternate_digest_message_id')
        logger.info(f"alternate_digest_job: text = {text[:100]}...")
        edited = False
        if last_message_id:
            try:
                await bot.edit_message_text(
                    chat_id=digest_chat_id,
                    message_id=int(last_message_id),
                    text=text,
                    parse_mode="HTML"
                )
                logger.info(f"Обновлён alternate дайджест {last_message_id}")
                edited = True
                
                # Переключаем тип даже при успешном редактировании
                next_type = "0" if current_type == "1" else "1"
                _digest_state["type"] = next_type
                set_config('alternate_digest_type', next_type)
            except Exception as e:
                error_str = str(e)
                logger.info(f"Ошибка редактирования: {e}")
                if "Message to edit not found" in error_str or "message can't be edited" in error_str:
                    logger.info(f"Старое сообщение {last_message_id} удалено, создаём новое")
                    set_config('alternate_digest_message_id', None)
                    last_message_id = None
                elif "Message is not modified" in error_str:
                    logger.info(f"Сообщение не изменилось, пропускаем удаление и создание")
                    edited = True  # Считаем что отредактировано успешно
                    
                    # Переключаем тип даже если сообщение не изменилось
                    next_type = "0" if current_type == "1" else "1"
                    logger.info(f"Switching type: {current_type} -> {next_type}")
                    _digest_state["type"] = next_type
                    set_config('alternate_digest_type', next_type)
                else:
                    logger.info(f"Не удалось редактировать: {e}")

        # Если не удалось редактировать - проверяем можем ли мы создать новое
        if not edited:
            # Удаляем старое сообщение ПЕРЕД проверкой времени
            if last_message_id:
                try:
                    await bot.delete_message(chat_id=digest_chat_id, message_id=int(last_message_id))
                    logger.info(f"Удалено старое alternate сообщение {last_message_id}")
                except Exception as e:
                    logger.debug(f"Не удалось удалить старое alternate сообщение: {e}")
            set_config('alternate_digest_message_id', None)  # сбрасываем сразу после удаления

            # Проверяем, не создавали ли мы новое сообщение слишком недавно (антиспам)
            last_created_str = get_config('alternate_digest_last_created')
            last_created = float(last_created_str) if last_created_str and last_created_str.strip() else 0
            time_since_last = time.time() - last_created
            logger.info(f"alternate_digest_job: last_created={last_created}, time_since_last={time_since_last:.0f}sec")
            if time_since_last < 60:  # 1 минута
                logger.info(f"Пропускаем создание нового дайджеста, прошло только {time_since_last:.0f} сек с последнего создания")
                return  # Выходим без создания
            
            # Проверяем, не запущен ли уже процесс создания
            creating = get_config('alternate_digest_creating')
            if creating and creating.strip() and time.time() - float(creating) < 60:
                logger.info(f"Уже идёт создание дайджеста, пропускаем")
                return
            
            # помечаем что начинаем создавать
            set_config('alternate_digest_creating', str(time.time()))

            try:
                # Отправляем новое сообщение
                msg = await bot.send_message(chat_id=digest_chat_id, text=text, parse_mode="HTML")
                # СОХРАНЯЕМ СРАЗУ ПОСЛЕ ОТПРАВКИ
                set_config('alternate_digest_message_id', msg.message_id)
                set_config('alternate_digest_last_created', str(time.time()))
                logger.info(f"Создан новый alternate дайджест {msg.message_id}, type={next_type}")
                
                # ТОЛЬКО ПОСЛЕ УСПЕШНОГО СОЗДАНИЯ ПЕРЕКЛЮЧАЕМ ТИП
                _digest_state["type"] = next_type
                set_config('alternate_digest_type', next_type)  # пишем в БД один раз за переключение

                # Закрепляем дайджест (открепляем старый, закрепляем новый)
                # Сначала получаем текущий закреплённый message_id ДО открепления
                old_pinned_id = None
                try:
                    chat_info = await bot.get_chat(chat_id=digest_chat_id)
                    pinned_msg = getattr(chat_info, 'pinned_message', None)
                    if pinned_msg:
                        old_pinned_id = pinned_msg.message_id
                    await bot.unpin_chat_message(chat_id=digest_chat_id)
                except Exception as e:
                    logger.debug(f"Не удалось открепить старый: {e}")
                
                try:
                    await bot.pin_chat_message(chat_id=digest_chat_id, message_id=msg.message_id, disable_notification=True)
                    logger.info(f"Дайджест {msg.message_id} закреплён")
                    
                    # Удаляем системное сообщение о закрепе - это сообщение ДО дайджеста
                    try:
                        # Получаем последние сообщения чтобы найти системное
                        messages = await bot.get_chat_history(chat_id=digest_chat_id, limit=2)
                        for m in messages:
                            # Системное сообщение о закрепе обычно содержит "закрепил"
                            if m.message_id != msg.message_id and hasattr(m, 'text') and m.text and 'закрепил' in m.text.lower():
                                await bot.delete_message(chat_id=digest_chat_id, message_id=m.message_id)
                                logger.debug(f"Удалено системное сообщение о закрепе {m.message_id}")
                                break
                    except Exception as e:
                        logger.debug(f"Не удалось удалить системное сообщение: {e}")
                except Exception as e:
                    logger.debug(f"Не удалось закрепить: {e}")
            finally:
                # ВСЕГДА очищаем флаг создания, даже если упало исключение
                set_config('alternate_digest_creating', '')  # очищаем флаг создания
        
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
        
        for msg_id in msg_ids:
            try:
                await bot.delete_message(chat_id, msg_id)
                logger.info(f"Deleted last bot message for user {user_id}: {msg_id}")
            except Exception as e:
                error_str = str(e).lower()
                if "message to delete not found" in error_str or "bad request" in error_str:
                    logger.debug(f"Message {msg_id} already deleted in chat {chat_id}: {e}")
                else:
                    logger.warning(f"Could not delete last bot message {msg_id}: {e}")
        
        # Всегда очищаем после попытки
        del last_bot_message[chat_id][user_id]
        # Очищаем пустые записи чата
        if not last_bot_message[chat_id]:
            del last_bot_message[chat_id]


def set_last_bot_message(chat_id, user_id, message_id):
    """Set the last bot message for this user in this chat"""
    if chat_id not in last_bot_message:
        last_bot_message[chat_id] = {}
    last_bot_message[chat_id][user_id] = message_id


def add_bot_message(chat_id, user_id, message_id):
    """Add bot message to track list for this user in this chat"""
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
    else:  # 1-15
        return 2, f"\n{random.choice(MULTICAST_TEXTS[2])}"


# ── Мультикаст (каскадный) ───────────────────────────────────────────
# Шансы загружаются из bot_config, дефолты здесь
MULTICAST_DEFAULT_CHANCE = 0.15
MULTICAST_CASCADE = [0.75, 0.50, 0.40]  # [не используется, ×3 шанс, ×4 шанс]

ZEUS_DEFAULT_CHANCE = 0.05
ZEUS_ICON_URL = "https://cdn.cloudflare.steamstatic.com/apps/dota2/images/dota_react/heroes/icons/zuus.png"

# Выходной бонус
WEEKEND_BONUS_MULTIPLIERS = [1.5, 2, 2.5]

# Счётчик бонусной фистуры за сутки
BONUS_FISSURE_GOAL = 10  # сколько бросков нужно для бонуса


def _load_daily_fissure_rolls():
    """Загрузить счётчик бросков из БД"""
    try:
        return int(get_config("daily_fissure_rolls", 0))
    except (ValueError, TypeError):
        return 0


def _save_daily_fissure_rolls(value):
    """Сохранить счётчик бросков в БД"""
    set_config("daily_fissure_rolls", str(value))


def _load_bonus_ready_users():
    """Загрузить бонусы из БД"""
    try:
        import json
        data = get_config("bonus_ready_users", "{}")
        return json.loads(data) if data else {}
    except (ValueError, TypeError, json.JSONDecodeError):
        return {}


def _save_bonus_ready_users(users):
    """Сохранить бонусы в БД"""
    import json
    set_config("bonus_ready_users", json.dumps(users))


daily_fissure_rolls = _load_daily_fissure_rolls()
bonus_ready_users = _load_bonus_ready_users()

# Тексты дайджестов
MORNING_DIGEST_HEADER = "🌅ФИССУРА ДАЙДЖЕСТ"
MORNING_DIGEST_FOOTER = "🔺 = рост позиций в топе\n🔻 = топ падение\n🍀 = текущий стрик побед"
DOTA_DIGEST_HEADER = "🎮 DOTA ДАЙДЖЕСТ 📊"
DOTA_DIGEST_FOOTER = "🔺 = лучший винрейт за неделю\n🔻 = худший винрейт за неделю\n🔸 = текущий стрик побед"
# # WEEKLY_DIGEST_HEADER удалён

# Ожидание анимации dice
DICE_ANIMATION_DELAY = 1.0

# URL баннеров
COOLDOWN_BANNER_URL = "https://i.ibb.co/kVFSSXKB/2v-Eh7-1.jpg"
PROFILE_BANNER_URL = "https://i.ibb.co/zTfF02C3/W0o-Gg.jpg"
TOP_BANNER_URL = "https://i.ibb.co/gLcnbBJ0/wx-Kwo.jpg"
TOPMMR_BANNER_URL = "https://i.ibb.co/7Jy3hjsF/o-TVJg.jpg"
LINK_BANNER_URL = "https://i.ibb.co/s9L6mTtx/dsfcv23123.png"
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
_digest_state = {"last_run": 0, "type": None, "chat_id": None, "message_id": None}
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
    import io
    close_session = False
    if session is None:
        import aiohttp
        session = aiohttp.ClientSession()
        close_session = True
    try:
        async with session.get(url) as resp:
            if resp.status == 200:
                data = await resp.read()
                # Уменьшаем через Pillow
                try:
                    from PIL import Image
                    img = Image.open(io.BytesIO(data))
                    img = img.resize((size, size), Image.LANCZOS)
                    bio = io.BytesIO()
                    img.save(bio, format='PNG', optimize=True)
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
        [KeyboardButton("🔑 Привязать Аккаунт")],
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
    
    # Delete last bot message immediately
    try:
        await delete_last_bot_message(context.bot, chat_id, user_obj.id)
    except Exception as e:
        logger.debug(f"Could not delete last bot message: {e}")
    
    # Spam protection - ignore if already processing this user
    if _user_processing.get(user_obj.id):
        return
    _user_processing[user_obj.id] = now
    
    try:
        user = get_user(user_obj.id, username)
        logger.info(f"user data: {user}")
        
        # Проверяем кулдаун или бонус (для всех игроков)
        bonus_time = bonus_ready_users.get("all", 0)
        # Бонус сгорает через 5 часов если не использован
        BONUS_EXPIRE = 5 * 3600  # 5 часов
        if bonus_time > 0 and (now - bonus_time) > BONUS_EXPIRE:
            # Бонус протух - удаляем
            bonus_ready_users.pop("all", None)
            _save_bonus_ready_users(bonus_ready_users)
            bonus_time = 0
        
        has_bonus = (bonus_time > 0)
        
        if has_bonus:
            # Бонус - пропускаем кулдаун
            bonus_ready_users.pop("all", None)
            _save_bonus_ready_users(bonus_ready_users)
        elif now - (user.get("last_fissure") or 0) < COOLDOWN:
            wait = COOLDOWN - (now - (user.get("last_fissure") or 0))
            elapsed = COOLDOWN - wait
            filled = int(elapsed / COOLDOWN * 10)
            bar = "🟩" * filled + "⬜️" * (10 - filled)
            text = f"🧬 Восстанавливается. {format_time(wait)}\n{bar}"
            cooldown_banner_url = "https://i.ibb.co/tMyxHtz1/dsadsadasdas.png"
            result_msg = await context.bot.send_photo(
                chat_id=update.message.chat_id,
                photo=cooldown_banner_url,
                caption=text,
                reply_markup=main_menu()
            )
            set_last_bot_message(chat_id, user_obj.id, result_msg.message_id)
            schedule_delete(context.bot, chat_id, result_msg.message_id, 30, context.application.job_queue)
            update_last_message_id(user_obj.id, result_msg.message_id)
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
            
            return  # выходим — без ролла
        
        # Остальные события (обычный ролл или мулькаст)
        roll, special_message, is_fatal, got_help = calculate_fissure_roll(user["fissure"])
        
        # Инкремент счётчика для бонусной фиссуры
        global daily_fissure_rolls
        bonus_available = False
        daily_fissure_rolls += 1
        _save_daily_fissure_rolls(daily_fissure_rolls)
        
        # Проверяем достигли цели - бонус будет на следующий бросок
        if daily_fissure_rolls >= BONUS_FISSURE_GOAL:
            # Бонус для ВСЕХ игроков - сохраняем с timestamp
            bonus_ready_users["all"] = now
            daily_fissure_rolls = 0
            _save_daily_fissure_rolls(0)
            _save_bonus_ready_users(bonus_ready_users)
            # Отправляем оповещение в чат - бонус для ВСЕХ
            bonus_msg = await context.bot.send_message(
                chat_id=chat_id,
                text=f"✅ ЗАДАНОЕ ВЫПОЛНЕНО: 🎁 10/10! +1 ФИССУРА!"
            )
            schedule_delete(context.bot, chat_id, bonus_msg.message_id, 30, context.application.job_queue)
        
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
                return  # выходим из мультикаста, делаем обычный ролл
            
            roll = roll * cascade_count
            logger.info(f"fissure multicast: roll after multiply={roll}, cascade_count={cascade_count}")
            original_roll = roll // cascade_count  # сохраняем для текста
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
            await asyncio.sleep(0.3)
        
        # Даем время slot сообщениям отправиться перед итоговым
        await asyncio.sleep(0.3)
        
        roll, protection_msg = apply_fissure_protection(user["fissure"], roll, is_fatal)
        
        # Сохраняем original_roll для отображения в мультикасте (до бонусов)
        display_roll = roll
        
        # Бонус за 10 бросков - добавляем сообщение
        if has_bonus:
            extra_text = "\n🎁 БОНУС! +ЕЩЁ РАЗ!"
        else:
            extra_text = ""
        
        # Бонус для выходных: увеличиваем положительный ролл
        if is_weekend and roll > 0 and not is_fatal:
            bonus_multiplier = random.choice(WEEKEND_BONUS_MULTIPLIERS)
            # Показываем точное значение в сообщении, но сохраняем как целое для расчета
            bonus_amount = roll * bonus_multiplier
            roll = int(roll * bonus_multiplier)
            weekend_bonus = f"\n🎉 ВЫХОДНОЙ! x{bonus_multiplier:.1f} = {bonus_amount:.1f} СМ"
        
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

        roll_key = min(roll, 75)
        roll_key = max(roll_key, -15)
        
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
        
        # Добавляем бонус за 10 бросков (если бонус доступен)
        bonus_triggered = bonus_time > 0 and (now - bonus_time) < BONUS_EXPIRE
        if bonus_triggered:
            extra_text = extra_text  # уже добавлено выше
        
        if cascade_count > 1 and original_roll is not None:
            roll_display = f"+{original_roll}" if original_roll > 0 else str(original_roll)
            mc_level = f"×{cascade_count}"
            roll_final = original_roll * cascade_count
            text = (
                f"🎲 {display_username}\n\n"
                f"{result_text}\n"
                f"{multicast_text}\n\n"
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
            roll_banner_url = "https://i.ibb.co/vCq9LvgM/dsad23.png"
        else:
            roll_banner_url = "https://i.ibb.co/4RRBrQkv/9k-Rlz.jpg"
        
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
        
        # Удаляем анимационные сообщения слотов
        if slot_msg_ids:
            for msg_id in slot_msg_ids:
                schedule_delete(context.bot, chat_id, msg_id, 30, context.application.job_queue)
        
        update_last_message_id(user_obj.id, result_msg.message_id)
        
        await flush_stat_buffer()
                   
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        logger.error(f"Error in fissure: {e}\n{tb}")
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"❌ Ошибка обработки запроса\n<code>{e}</code>",
                parse_mode="HTML"
            )
        except Exception:
            pass
    finally:
        _user_processing.pop(user_obj.id, None)


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
            username = user_obj.username or user_obj.first_name
            target_user = get_user(user_obj.id, username)
        
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
                from dota_mmr import get_recent_matches
                steam_id = target_user.get('steam_id')
                if steam_id and week_games > 0:
                    matches = get_recent_matches(steam_id, limit=50)
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
        profile_banner_url = "https://i.ibb.co/d0pcyNcM/image.png"
        
        if target_user.get('steam_id'):
            try:
                from dota_mmr import get_top_heroes, generate_heroes_image
                top_heroes = get_top_heroes(target_user['steam_id'], last_n=20, top_k=5)
                if top_heroes:
                    img_bytes = generate_heroes_image(top_heroes)
                    if img_bytes:
                        profile_banner_url = io.BytesIO(img_bytes)
            except Exception as e:
                logger.debug(f"Could not generate heroes image: {e}")
        
        result_msg = await context.bot.send_photo(
            chat_id=update.message.chat_id,
            photo=profile_banner_url,
            caption=text,
            parse_mode="HTML",
            reply_markup=main_menu()
        )
        set_last_bot_message(chat_id, update.effective_user.id, result_msg.message_id)
        schedule_delete(context.bot, chat_id, result_msg.message_id, 30, context.application.job_queue)
        update_last_message_id(update.effective_user.id, result_msg.message_id)
        
    except Exception as e:
        import traceback
        logger.error(f"Error in stats: {e}\n{traceback.format_exc()}")
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"❌ Ошибка: <code>{e}</code>",
                parse_mode="HTML"
            )
        except Exception:
            pass


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
        
        if not top_users:
            text = "😶 Пока нет игроков. Будь первым!"
        else:
            text = ""
            medals = {1: "🥇", 2: "🥈", 3: "🥉"}
            emoji_nums = {4: "4️⃣", 5: "5️⃣", 6: "6️⃣", 7: "7️⃣", 8: "8️⃣", 9: "9️⃣", 10: "🔟"}
            for i, user_top in enumerate(top_users, 1):
                name = (user_top.get('username') or 'Unknown')
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
            
            # Всегда показываем позицию пользователя, даже если он не в топе
            if user_rank:
                user_fissure = user.get('fissure', 0) if user else 0
                text += f"\n<b>👤 Твоя позиция: #{user_rank} ({user_fissure:.1f} см)</b>"
            else:
                user_fissure = user.get('fissure', 0) if user else 0
                text += f"\n<b>👤 Твоя позиция: — ({user_fissure:.1f} см)</b>"
        
        # Add banner and send
        top_banner_url = "https://i.ibb.co/gLcnbBJ0/wx-Kwo.jpg"
        
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
            await update.message.reply_text("❌ Ошибка получения топа", reply_markup=main_menu())
        except Exception:
            pass


async def topmmr(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать топ игроков по MMR"""
    logger.info(f"User {update.effective_user.id} called topmmr")
    
    chat_id = update.message.chat_id
    chat_type = update.message.chat.type
    
    # Delete user message only in groups/channels
    if chat_type in ['group', 'supergroup', 'channel']:
        if await bot_can_delete(context.bot, chat_id):
            try:
                await context.bot.delete_message(chat_id, update.message.message_id)
            except Exception:
                pass

    try:
        from database import get_dota_week_top_from_db
        from database import get_user
        user = get_user(update.effective_user.id)
        
        # Получаем топ напрямую из БД для актуальных данных
        top_users = get_dota_week_top_from_db(8)
        
        # Initialize user position variables
        user_is_in_top = False
        user_pos = None
        user_rank_str = "Без ранга"
        user_week_games = 0
        user_week_wins = 0
        user_winrate = 0
        
        if user:
            user_rank_tier = user.get('rank_tier', 0)
            user_week_games = user.get('week_games', 0)
            user_week_wins = user.get('week_wins', 0)
            user_week_losses = user_week_games - user_week_wins
            user_winrate = round((user_week_wins / user_week_games * 100), 1) if user_week_games > 0 else 0
            
            # Convert user rank tier to string
            if user_rank_tier:
                ranks = ["Рекрут", "Страж", "Рыцарь", "Герой", "Легенда", "Властелин", "Божество", "Титан"]
                tier = min(user_rank_tier // 10, 8)
                star = user_rank_tier % 10
                
                if tier < 1 or tier > 8:
                    user_rank_str = "Неизвестно"
                else:
                    rank_name = ranks[tier - 1]
                    if tier == 8:  # Immortal
                        user_rank_str = rank_name
                    else:
                        user_rank_str = f"{rank_name} {star}"
            else:
                # User without rank (rank_tier=0), but possibly with games
                user_rank_str = "Без ранга"
            
            # Check if user is already in the top list
            if user:
                for player in top_users:
                    if player.get('telegram_id') == user.get('telegram_id'):
                        user_is_in_top = True
                        break
            
            # Find user's REAL position in the sorted top list
            user_pos = None
            if user and user.get('telegram_id'):
                for i, player in enumerate(top_users, 1):
                    if player.get('telegram_id') == user.get('telegram_id'):
                        user_pos = i
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
            
            for i, player in enumerate(top_users, 1):
                username = player.get('steam_nickname') or player.get('username') or 'Unknown'
                rank_tier = player.get('rank_tier', 0)
                week_games = player.get('week_games', 0)
                week_wins = player.get('week_wins', 0)
                week_losses = week_games - week_wins
                
                # Format rank
                if rank_tier:
                    ranks = ["Рекрут", "Страж", "Рыцарь", "Герой", "Легенда", "Властелин", "Божество", "Титан"]
                    tier = min(rank_tier // 10, 8)
                    star = rank_tier % 10
                    
                    if tier < 1 or tier > 8:
                        rank_str = "Неизвестно"
                    else:
                        rank_name = ranks[tier - 1]
                        if tier == 8:  # Immortal
                            rank_str = rank_name
                        else:
                            rank_str = f"{rank_name} {star}"
                else:
                    rank_str = "Не откалиброван"
                
                # Format winrate
                winrate = round((week_wins / week_games * 100), 1) if week_games > 0 else 0
                
                # Format prefix (medal or number)
                if i == 1:
                    prefix = "🥇"
                elif i == 2:
                    prefix = "🥈"
                elif i == 3:
                    prefix = "🥉"
                else:
                    emoji_nums = {4: "4️⃣", 5: "5️⃣", 6: "6️⃣", 7: "7️⃣", 8: "8️⃣", 9: "9️⃣", 10: "🔟"}
                    prefix = emoji_nums.get(i, f"{i}.")
                
                # Format streak
                streak = player.get('week_current_streak', 0)
                streak_text = f" • 🔥{streak}" if streak > 0 else ""
                
                if username and len(username) > 25:
                    username = username[:25] + "."
                
                # Build player entry - two lines per player
                # Если пользователь в топе - показываем только 7 игроков, его позицию добавим в конце
                telegram_id = player.get('telegram_id')
                clickable_name = f'<b><a href="tg://user?id={telegram_id}">{username}</a></b>'
                lines.append(f"{prefix} {clickable_name} - {rank_str}\n")
                if week_games > 0:
                    lines.append(f" └ {week_wins}W/{week_losses}L • WR {winrate}%{streak_text}\n\n")
                else:
                    lines.append(f" └ Нет игр за неделю\n\n")
            
            # Если пользователь НЕ в топе - показываем его внизу с позицией
            if not user_is_in_top:
                if user and user.get('steam_id') and user_pos:
                    lines.append("\n")  # Extra line before user position
                    username = user.get('steam_nickname') or user.get('username') or 'Unknown'
                    if username and len(username) > 25:
                        username = username[:25] + "."
                    user_tg_id = user.get('telegram_id')
                    clickable_name = f'<b><a href="tg://user?id={user_tg_id}">{username}</a></b>'
                    emoji_nums = {1: "1️⃣", 2: "2️⃣", 3: "3️⃣", 4: "4️⃣", 5: "5️⃣", 6: "6️⃣", 7: "7️⃣", 8: "8️⃣", 9: "9️⃣", 10: "🔟"}
                    prefix = f"{emoji_nums.get(user_pos, '#' + str(user_pos))} "
                    lines.append(f"\n{prefix}{clickable_name} - {user_rank_str}\n")
                    if user_week_games > 0:
                        lines.append(f" └ {user_week_games}W/{user_week_losses}L • WR {user_winrate}%\n\n")
                    else:
                        lines.append(f" └ Нет игр за неделю\n\n")
            
            text = "".join(lines)
        
        # Add header to final text
        topmmr_banner_url = "https://i.ibb.co/7Jy3hjsF/o-TVJg.jpg"
        text = f"{text}"
        
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
        # Track this message for future deletion
        set_last_bot_message(chat_id, update.effective_user.id, result_msg.message_id)
        schedule_delete(context.bot, chat_id, result_msg.message_id, 30, context.application.job_queue)
    except Exception as e:
        logger.error(f"Error in topmmr: {e}", exc_info=True)
        # Send new message instead of replying to avoid "Message not found" error
        try:
            await delete_last_bot_message(context.bot, chat_id, update.effective_user.id)
        except Exception:
            pass
        await context.bot.send_message(chat_id=update.effective_chat.id, text="❌ Ошибка получения топа MMR", reply_markup=main_menu())


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
        except Exception as e:
            logger.error(f"Error in link: {e}")
            await context.bot.send_message(chat_id=update.effective_chat.id, text="❌ Ошибка привязки Dota аккаунта", reply_markup=main_menu())
        return
    
    # Если нет аргумента - отправляем инструкцию
    # Delete previous bot message before sending new one
    try:
        await delete_last_bot_message(context.bot, chat_id, update.effective_user.id)
    except Exception as e:
        logger.debug(f"Could not delete last bot message: {e}")
    
    link_banner_url = "https://i.ibb.co/s9L6mTtx/dsfcv23123.png"
    link_text = ("🦞 *Привязка Dota*\n\n"
    "Отправьте `/link` и ваш Dota ID или ссылку на профиль.\n\n"
    "*Примеры:*\n"
    "`/link 76561198012345678`\n"
    "`/link https://ru.dotabuff.com/players/347614699`\n\n"
    "⚠️ Профиль должен быть открытым\n"
    "📡 Статистика с OpenDota")
    
    result_msg = await context.bot.send_photo(
        chat_id=update.effective_chat.id,
        photo=link_banner_url,
        caption=link_text,
        parse_mode='Markdown',
        reply_markup=main_menu()
    )
    # Track this message for future deletion
    set_last_bot_message(chat_id, update.effective_user.id, result_msg.message_id)
    schedule_delete(context.bot, chat_id, result_msg.message_id, 30, context.application.job_queue)


async def refresh(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обновить MMR одного пользователя"""
    logger.info(f"User {update.effective_user.id} called refresh")
    
    chat_id = update.message.chat_id
    chat_type = update.message.chat.type
    
    # Delete user message only in groups/channels if bot has permissions
    if chat_type in ['group', 'supergroup', 'channel']:
        if await bot_can_delete(context.bot, chat_id):
            try:
                await context.bot.delete_message(chat_id, update.message.message_id)
            except Exception:
                pass
    
    try:
        from dota_mmr import update_user_mmr
        from database import get_user
        
        # Обновляем MMR только этого пользователя
        result = update_user_mmr(update.effective_user.id)
        
        # Delete previous bot message before sending new one
        try:
            await delete_last_bot_message(context.bot, chat_id, update.effective_user.id)
        except Exception as e:
            logger.debug(f"Could not delete last bot message: {e}")
        
        if result:
            user = get_user(update.effective_user.id)
            if user and user.get('steam_nickname'):
                result_msg = await context.bot.send_message(chat_id=update.effective_chat.id, text=(
                    f"✅ MMR обновлён!\n"
                    f"{user['steam_nickname']} - {user['mmr']}\n"
                    f"📊 Всего игр: {user['dota_total_games']}"
                ))
            else:
                result_msg = await context.bot.send_message(chat_id=update.effective_chat.id, text="❌ Не удалось получить статистику", reply_markup=main_menu())
        else:
            result_msg = await context.bot.send_message(chat_id=update.effective_chat.id, text="❌ У тебя не привязан Steam аккаунт. Используй /link", reply_markup=main_menu())
        # Track this message for future deletion
        set_last_bot_message(chat_id, update.effective_user.id, result_msg.message_id)
        schedule_delete(context.bot, chat_id, result_msg.message_id, 30, context.application.job_queue)
    except Exception as e:
        logger.error(f"Error in refresh: {e}")
        try:
            await delete_last_bot_message(context.bot, chat_id, update.effective_user.id)
        except Exception:
            pass
        await context.bot.send_message(chat_id=update.effective_chat.id, text="❌ Ошибка обновления MMR", reply_markup=main_menu())


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle inline button callbacks"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    
    if data == "link":
        await query.answer("Открываю привязку...", show_alert=False)
        
        try:
            await link(update, context)
        except Exception as e:
            logger.error(f"Error in button_callback link: {e}")
    elif data == "start":
        await start(update, context)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    # Handle callback from inline button
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        # Create fake message for the function
        from telegram import Message
        fake_message = Message(
            message_id=query.message.message_id,
            date=query.message.date,
            chat=query.message.chat,
            from_user=query.from_user,
            text="/start"
        )
        update.message = fake_message
    
    logger.info(f"New user {update.effective_user.id}")
    
    chat_id = update.message.chat_id
    chat_type = update.message.chat.type
    
    # Delete user command only in groups/channels if bot has permissions
    if chat_type in ['group', 'supergroup', 'channel']:
        if await bot_can_delete(context.bot, chat_id):
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
        text = (
            "👉 Ты в игре — крути фиссуру, чекай топы, подключай Dota и докажи, что ты тут не случайно."
        )
        
        banner_url = "https://i.ibb.co/LXsGsfxZ/213.png"
        
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        inline_keyboard = [[InlineKeyboardButton("🔑 Привязать Аккаунт", callback_data="link")]]
        reply_markup = InlineKeyboardMarkup(inline_keyboard)
        
        result_msg = await context.bot.send_photo(
            chat_id=chat_id,
            photo=banner_url,
            caption=text,
            reply_markup=reply_markup
        )
        
        await context.bot.send_message(
            chat_id=chat_id,
            text="📋 Главное меню:",
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
            if await bot_can_delete(context.bot, chat_id):
                try:
                    await context.bot.delete_message(chat_id, update.message.message_id)
                except Exception as e:
                    logger.debug(f"Could not delete user message: {e}")
        # Сохраняем ID чата в конфиг и сбрасываем message_id
        set_config("digest_chat_id", chat_id)
        set_config("daily_digest_message_id", None)

        msg = await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"✅ Чат для утреннего дайджеста установлен.\n"
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
            err_msg = await context.bot.send_message(chat_id=update.effective_chat.id, text="❌ Не удалось сохранить чат для дайджеста", reply_markup=main_menu())
            chat = update.effective_chat
            if chat and chat.type in ['group', 'supergroup', 'channel']:
                schedule_delete(context.bot, chat.id, err_msg.message_id, 30, context.application.job_queue)
        except Exception:
            pass


async def setchance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Изменить шансы событий: /setchance multicast 0.10 или /setchance zeus 0.05"""
    try:
        # Проверяем аргументы
        if not context.args or len(context.args) < 2:
            stats = _load_stats()
            mc, ze = get_event_chances()
            await update.message.reply_text(
                f"📊 Текущие шансы:\n"
                f"  👹 Мулькаст: {mc*100:.0f}%\n"
                f"  ⚡ Зевс: {ze*100:.0f}%\n\n"
                f"Использование: /setchance multicast 10\n"
                f"Статистика: бросков={stats['rolls']}, мулькаст={stats['multicast']}, зевс={stats['zeus']}"
            )
            return
        
        event = context.args[0].lower()
        try:
            value = float(context.args[1])
        except ValueError:
            await update.message.reply_text("❌ Шанс должен быть числом (например: 10 для 10%)")
            return
        
        if event in ("multicast", "mc", "м"):
            set_config("multicast_chance", str(value / 100.0))
            _event_chances_cache["ts"] = 0  # сброс кеша
            await update.message.reply_text(f"✅ Шанс мулькаста: {value:.0f}%")
        elif event in ("zeus", "z", "з"):
            set_config("zeus_chance", str(value / 100.0))
            _event_chances_cache["ts"] = 0
            await update.message.reply_text(f"✅ Шанс Зевса: {value:.0f}%")
        else:
            await update.message.reply_text("❌ Неизвестное событие. Используй: multicast или zeus")
    except Exception as e:
        logger.error(f"Error in setchance: {e}")
        await update.message.reply_text("❌ Ошибка")


async def settitle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Установить тег (титул) администратору группы"""
    try:
        chat = update.effective_chat
        user = update.effective_user
        
        if not context.args:
            await context.bot.send_message(chat_id=chat.id, text="Использование: /settitle @username [тег]\nПример: /settitle @username Герой")
            return
        
        # Разбираем аргументы: или @username тег, или username тег
        first_arg = context.args[0]
        if first_arg.startswith('@'):
            username = first_arg[1:]
            title = " ".join(context.args[1:]) if len(context.args) > 1 else ""
        else:
            username = first_arg
            title = " ".join(context.args[1:]) if len(context.args) > 1 else ""
        
        if not username:
            await context.bot.send_message(chat_id=chat.id, text="Укажите username пользователя")
            return
        
        # Получаем chat member по username
        try:
            member = await context.bot.get_chat_member(chat.id, f"@{username}")
        except Exception as e:
            await context.bot.send_message(chat_id=chat.id, text=f"Не удалось найти пользователя @{username}: {e}")
            return
        
        if member.status not in ('administrator', 'creator'):
            await context.bot.send_message(chat_id=chat.id, text="Пользователь не является администратором группы")
            return
        
        # Устанавливаем титул
        try:
            await context.bot.set_chat_administrator_custom_title(
                chat_id=chat.id,
                user_id=member.user.id,
                custom_title=title if title else "Участник"
            )
            await context.bot.send_message(
                chat_id=chat.id, 
                text=f"✅ Тег установлен для @{username}: {title if title else 'Участник'}"
            )
        except Exception as e:
            await context.bot.send_message(chat_id=chat.id, text=f"Ошибка: {e}")
            
    except Exception as e:
        logger.error(f"Error in settitle: {e}")
        try:
            await context.bot.send_message(chat_id=update.effective_chat.id, text=f"Ошибка: {e}")
        except:
            pass


async def removeuser(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Удалить пользователя: /removeuser @username или /removeuser telegram_id"""
    try:
        user_obj = update.effective_user
        # Only allow the bot owner (replace with your ID)
        # You can set your telegram ID here for security
        # BOT_OWNER_ID = 123456789
        # if user_obj.id != BOT_OWNER_ID:
        #     await update.message.reply_text("❌ Нет доступа")
        #     return
        
        if not context.args:
            await update.message.reply_text("Использование: /removeuser @username\nили: /removeuser <telegram_id>")
            return
        
        target = context.args[0].strip()
        
        if target.startswith('@'):
            # Search by username
            target_user = get_user_by_username(target[1:])
            if not target_user:
                await update.message.reply_text(f"❌ Пользователь {target} не найден")
                return
            tid = target_user.get('telegram_id')
            uname = target_user.get('username', 'Unknown')
        else:
            try:
                tid = int(target)
                user_data = get_user(tid, None)
                uname = user_data.get('username', 'Unknown') if user_data else 'Unknown'
            except ValueError:
                await update.message.reply_text("❌ Неверный формат. Используй @username или числовой ID")
                return
        
        if tid:
            success = delete_user(tid)
            if success:
                await update.message.reply_text(f"✅ Пользователь {uname} (ID: {tid}) удалён из базы")
            else:
                await update.message.reply_text(f"❌ Ошибка при удалении {uname}")
        else:
            await update.message.reply_text("❌ Не удалось определить ID пользователя")
    except Exception as e:
        logger.error(f"Error in removeuser: {e}")
        await update.message.reply_text("❌ Ошибка")


async def menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Menu button handler - sends new content, deletes user message and old bot message immediately"""
    try:
        user_id = update.effective_user.id if update.effective_user else "unknown"
        chat_id = update.message.chat_id if update.message else "unknown"
        logger.info(f"menu_handler: user={user_id}, chat={chat_id}")
        
        if not update.message:
            logger.warning(f"menu_handler: no message in update")
            return
        
        if not update.message.text:
            logger.warning(f"menu_handler: no text in message, msg={update.message}")
            return
        
        text = update.message.text.strip()
        logger.info(f"menu_handler: text='{text}' (len={len(text)})")
        
        menu_buttons = {
            "🎲 Ролл Фиссуры": "🎲 Ролл Фиссуры",
            "👤 Профиль": "👤 Профиль",
            "🏆 Топ Фиссур": "🏆 Топ Фиссур",
            "🏆 Топ MMR": "🏆 Топ MMR",
            "🔑 Привязать Аккаунт": "🔑 Привязать Аккаунт"
        }
        
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
        if old_member and new_member and new_member.user.id != context.bot.id:
            old_status = old_member.status
            new_status = new_member.status
            
            # User joined the chat (was not a member, now is member)
            if old_status in ['left', 'kicked'] and new_status in ['member', 'administrator']:
                name = new_member.user.first_name or "Friend"
                user_id = new_member.user.id
                
                # Отмечаем пользователя как участника чата
                try:
                    set_user_in_chat(user_id, True)
                except Exception as e:
                    logger.debug(f"Could not set in_chat=True for {user_id}: {e}")
                
                # Формируем приветственное сообщение с кликабельным ником
                from telegram import InlineKeyboardButton, InlineKeyboardMarkup
                
                welcome_text = f"<a href=\"tg://user?id={user_id}\">{name}</a>, {random.choice(WELCOME_PHRASES)}"
                
                keyboard = [[InlineKeyboardButton("🔑 Привязать Аккаунт", callback_data="link")]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                result_msg = await context.bot.send_message(
                    chat_id=chat_id,
                    text=welcome_text,
                    parse_mode="HTML",
                    reply_markup=reply_markup
                )
                logger.info(f"Welcome sent for {name}")
                # Удаляем приветственное сообщение через час
                schedule_delete(context.bot, chat_id, result_msg.message_id, 3600, context.application.job_queue)
            
            # User left the chat (was member, now is left/kicked)
            elif old_status in ['member', 'administrator'] and new_status in ['left', 'kicked']:
                user_id = new_member.user.id
                name = new_member.user.first_name or "Unknown"
                try:
                    set_user_in_chat(user_id, False)
                    update_user_fields_batch(user_id, {
                        "steam_id": None,
                        "steam_nickname": None,
                        "mmr": 0,
                        "rank_tier": 0,
                        "week_games": 0,
                        "week_wins": 0,
                        "week_best_streak": 0,
                        "week_current_streak": 0,
                        "dota_total_games": 0,
                        "dota_wins": 0,
                        "wins": 0,
                        "losses": 0
                    })
                    logger.info(f"User {name} ({user_id}) left chat, set in_chat=False and reset Steam data")
                except Exception as e:
                    logger.debug(f"Could not process user leave for {user_id}: {e}")
        
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
        update_digest_snapshot()
        logger.info("Digest snapshot initialized on startup")
        
        from database import get_all_users_with_steam, user_cache
        all_users = get_all_users_with_steam()
        for u in all_users:
            user_cache.set(u['telegram_id'], u)
        logger.info(f"Loaded {len(all_users)} users with Steam into cache on startup")
        
        from database import update_dota_week_top_cache
        update_dota_week_top_cache()
        logger.info("Dota week top cache initialized on startup")
        
        job_queue = JobQueue()
        app = ApplicationBuilder().token(TOKEN).job_queue(job_queue).build()
        job_queue.set_application(app)
        
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
        
        job_queue.run_repeating(
            alternate_digest_job,
            interval=datetime.timedelta(seconds=15),
            first=datetime.datetime.now() + datetime.timedelta(seconds=20)
        )
        
        job_queue.run_repeating(
            decrease_inactive_job,
            interval=datetime.timedelta(minutes=1),
            first=datetime.datetime.now() + datetime.timedelta(seconds=30)
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
        app.add_handler(CommandHandler("fissure", fissure))
        app.add_handler(CommandHandler("stats", stats))
        app.add_handler(CommandHandler("profile", stats))
        app.add_handler(CommandHandler("top", top))
        app.add_handler(CommandHandler("topmmr", topmmr))
        app.add_handler(CommandHandler("link", link))
        app.add_handler(CommandHandler("refresh", refresh))
        app.add_handler(CommandHandler("digestnow", digest_now))
        app.add_handler(CommandHandler("dotadigestnow", dota_digest_now))
        
        app.add_handler(CommandHandler("setdigestchat", set_digest_chat))
        app.add_handler(CommandHandler("setchance", setchance))
        app.add_handler(CommandHandler("settitle", settitle))
        app.add_handler(CommandHandler("removeuser", removeuser))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, menu_handler))
        app.add_handler(ChatMemberHandler(welcome_new_member, ChatMemberHandler.CHAT_MEMBER))
        
        webhook_url = os.getenv("WEBHOOK_URL")
        use_polling = os.getenv("USE_POLLING", "false").lower() == "true"
        
        await app.initialize()
        await app.start()
        await job_queue.start()
        
        if use_polling or not webhook_url:
            logger.info("Starting bot in POLLING mode")
            await app.bot.delete_webhook(drop_pending_updates=True)
            
            from aiohttp import web
            async def health_handler(request):
                return web.Response(text="Bot is polling", status=200)
            web_app = web.Application()
            web_app.router.add_get('/', health_handler)
            web_app.router.add_get('/health', health_handler)
            runner = web.AppRunner(web_app)
            await runner.setup()
            port = int(os.getenv('PORT', 10000))
            site = web.TCPSite(runner, '0.0.0.0', port)
            await site.start()
            logger.info(f"Health server on port {port}")
            
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
            await app.bot.set_webhook(url=webhook_url, drop_pending_updates=True)
            logger.info(f"Webhook URL: {webhook_url}")
            
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
            logger.info(f"Web server started on port {port}")
            
            async def keep_alive_ping():
                import aiohttp
                ping_url = webhook_url.rsplit('/webhook', 1)[0] + '/health'
                while True:
                    try:
                        await asyncio.sleep(300)  # Ping every 5 minutes to prevent Render sleep
                        async with aiohttp.ClientSession() as session:
                            # Ping health endpoint
                            await session.get(ping_url, timeout=aiohttp.ClientTimeout(total=30))
                            logger.info("Keep-alive ping sent")
                            # Also ping root to keep web server awake
                            root_url = webhook_url.rsplit('/webhook', 1)[0] + '/'
                            await session.get(root_url, timeout=aiohttp.ClientTimeout(total=10))
                    except Exception as e:
                        logger.error(f"Keep-alive ping error: {e}")
            asyncio.create_task(keep_alive_ping())
        
        async def daily_flush_cache():
            from database import flush_users_cache
            while True:
                try:
                    await asyncio.sleep(3600)
                    flushed = flush_users_cache()
                    logger.info(f"Hourly flush cache completed: {flushed} users")
                except Exception as e:
                    logger.error(f"Daily flush cache error: {e}")
        asyncio.create_task(daily_flush_cache())
        
        while True:
            await asyncio.sleep(3600)
            
    except Exception as e:
        logger.error(f"Critical error: {e}", exc_info=True)
        raise
    finally:
        try:
            from database import flush_users_cache
            flushed = flush_users_cache()
            logger.info(f"Shutdown: flushed {flushed} users to DB")
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



