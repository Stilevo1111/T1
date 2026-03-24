# -*- coding: utf-8 -*-
import os
import random
import time
import asyncio
import logging
import datetime
import urllib.parse as urlparse
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters, JobQueue, ChatMemberHandler
from telegram.error import Conflict
from database import init_db, get_user, update_fissure, get_fissure_top, update_last_message_id, Database, get_user_rank, get_fissure_rank, decrease_inactive_fissure, get_config, set_config, get_digest_stats, update_player_positions, update_digest_snapshot, get_weekly_digest_stats, update_weekly_digest_snapshot, migrate_db, get_connection, get_dota_digest_stats
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


async def update_all_mmr_job(context):
    """Ежедневное обновление MMR всех пользователей с привязанным Steam"""
    try:
        logger.info("Запуск ежедневного обновления MMR")
        from dota_mmr import update_user_mmr
        from database import get_all_users_with_steam
        
        users = get_all_users_with_steam()
        if not users:
            logger.info("Нет пользователей с привязанным Steam для обновления MMR")
            return
        
        logger.info(f"Обновление MMR для {len(users)} пользователей")
        success_count = 0
        for user in users:
            try:
                result = update_user_mmr(user['telegram_id'])
                if result:
                    success_count += 1
            except Exception as e:
                logger.error(f"Ошибка обновления MMR для {user['telegram_id']}: {e}")
        
        logger.info(f"MMR обновлён для {success_count}/{len(users)} пользователей")
    except Exception as e:
        logger.error(f"Ошибка в update_all_mmr_job: {e}")


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
        
        if streak_player and streak_player != "None":
            streak_part = f"🍀{streak_display} - Стрик {streak_len}"
        else:
            streak_part = "🍀—"
        
        text = f"{growth_part} ┃{drop_part} ┃{streak_part}\n\n🌅УТРЕНИЙ ДАЙДЖЕСТ 🔄 9:00 МСК\n\n📈 = рост позиций в топе\n💀 = топ падение\n🍀 = текущий стрик побед"
        
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
        set_config("daily_digest_message_id", None)

        # Создаём контекст для ручного вызова дайджеста
        class ManualContext:
            def __init__(self, application, bot):
                self.application = application
                self.bot = bot
                self.manual = True

        manual_context = ManualContext(context.application, context.bot)
        await morning_digest_job(manual_context)

        msg = await context.bot.send_message(chat_id=update.effective_chat.id, text="✅ Утренний дайджест для этого чата создан/обновлён.")
        if chat.type in ['group', 'supergroup', 'channel']:
            schedule_delete(context.bot, chat_id, msg.message_id, 30, context.application.job_queue)
    except Exception as e:
        logger.error(f"Error in digest_now: {e}", exc_info=True)
        try:
            err_msg = await context.bot.send_message(chat_id=update.effective_chat.id, text="❌ Не удалось создать дайджест сейчас")
            chat = update.effective_chat
            if chat and chat.type in ['group', 'supergroup', 'channel']:
                schedule_delete(context.bot, chat.id, err_msg.message_id, 30, context.application.job_queue)
        except Exception:
            pass


async def dota_digest_job(context):
    """Dota дайджест - лучший/худший винрейт и стрик побед за неделю"""
    try:
        logger.info("Запуск Dota дайджеста")
        
        # Получаем ID чата для дайджеста
        digest_chat_id = get_config('digest_chat_id')
        if not digest_chat_id:
            logger.info("Чат для дайджеста не настроен")
            return
        
        stats = get_dota_digest_stats()
        
        # Формируем сообщение
        # top_winrate: (nickname, rank_tier, week_games, week_wins, telegram_id)
        # bottom_winrate: (nickname, rank_tier, week_games, week_wins, telegram_id)
        # top_streak: (nickname, week_wins, telegram_id)
        
        top_player, top_rank, top_games, top_wins, top_id = stats.get("top_winrate", ("None", 0, 0, 0, None))
        bottom_player, bottom_rank, bottom_games, bottom_wins, bottom_id = stats.get("bottom_winrate", ("None", 0, 0, 0, None))
        streak_player, streak_wins, streak_id = stats.get("top_streak", ("None", 0, None))
        
        # Форматируем винрейт
        top_winrate = round((top_wins / top_games * 100), 1) if top_games > 0 else 0
        bottom_winrate = round((bottom_wins / bottom_games * 100), 1) if bottom_games > 0 else 0
        
        # Используем make_clickable для никнеймов
        top_display = make_clickable(top_player, top_id) if top_player and top_player != "None" else "—"
        bottom_display = make_clickable(bottom_player, bottom_id) if bottom_player and bottom_player != "None" else "—"
        streak_display = make_clickable(streak_player, streak_id) if streak_player and streak_player != "None" else "—"
        
        # Формат аналогичен утреннему дайджесту
        if top_player and top_player != "None":
            top_losses = top_games - top_wins
            top_part = f"🎯{top_display} {top_winrate}% ({top_wins}W/{top_losses}L)"
        else:
            top_part = "🎯—"
        
        if bottom_player and bottom_player != "None":
            bottom_losses = bottom_games - bottom_wins
            bottom_part = f"💀{bottom_display} {bottom_winrate}% ({bottom_wins}W/{bottom_losses}L)"
        else:
            bottom_part = "💀—"
        
        if streak_player and streak_player != "None":
            streak_part = f"🔥{streak_display} - {streak_wins} Стрик"
        else:
            streak_part = "🔥—"
        
        text = f"{top_part} ┃{bottom_part} ┃{streak_part}\n\n🎮 DOTA ДАЙДЖЕСТ 📊\n\n🎯 = лучший винрейт за неделю\n💀 = худший винрейт за неделю\n🔥 = больше всего побед за неделю"
        
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
    """Чередование утреннего и Dota дайджестов каждые 10 минут"""
    try:
        logger.info("Запуск alternate_digest_job")
        
        # Получаем ID чата для дайджеста
        digest_chat_id = get_config('digest_chat_id')
        if not digest_chat_id:
            logger.info("Чат для дайджеста не настроен")
            return
        
        bot = context.application.bot
        
        # Получаем текущий тип дайджеста (0 = morning, 1 = dota)
        current_type = get_config('alternate_digest_type')
        if current_type is None:
            current_type = "0"
        
        # Формируем текст в зависимости от типа
        if current_type == "0":
            # Утренний дайджест
            stats = get_digest_stats()
            
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
            next_type = "1"
        else:
            # Dota дайджест
            stats = get_dota_digest_stats()
            
            top_player, top_rank, top_games, top_wins, top_id = stats.get("top_winrate", ("None", 0, 0, 0, None))
            bottom_player, bottom_rank, bottom_games, bottom_wins, bottom_id = stats.get("bottom_winrate", ("None", 0, 0, 0, None))
            streak_player, streak_wins, streak_id = stats.get("top_streak", ("None", 0, None))
            
            top_winrate = round((top_wins / top_games * 100), 1) if top_games > 0 else 0
            bottom_winrate = round((bottom_wins / bottom_games * 100), 1) if bottom_games > 0 else 0
            
            top_display = make_clickable(top_player, top_id) if top_player and top_player != "None" else "—"
            bottom_display = make_clickable(bottom_player, bottom_id) if bottom_player and bottom_player != "None" else "—"
            streak_display = make_clickable(streak_player, streak_id) if streak_player and streak_player != "None" else "—"
            
            if top_player and top_player != "None":
                top_losses = top_games - top_wins
                top_part = f"🎯{top_display} {top_winrate}% ({top_wins}W/{top_losses}L)"
            else:
                top_part = "🎯—"
            
            if bottom_player and bottom_player != "None":
                bottom_losses = bottom_games - bottom_wins
                bottom_part = f"💀{bottom_display} {bottom_winrate}% ({bottom_wins}W/{bottom_losses}L)"
            else:
                bottom_part = "💀—"
            
            if streak_player and streak_player != "None":
                streak_part = f"🔥{streak_display} - {streak_wins} Стрик"
            else:
                streak_part = "🔥—"
            
            text = f"{top_part} ┃{bottom_part} ┃{streak_part}\n\n🎮 DOTA ДАЙДЖЕСТ 📊\n\n🎯 = лучший винрейт за неделю\n💀 = худший винрейт за неделю\n🔥 = больше всего побед за неделю"
            next_type = "0"
        
        # Пробуем отредактировать существующее сообщение
        last_message_id = get_config('alternate_digest_message_id')
        if last_message_id:
            try:
                await bot.edit_message_text(
                    chat_id=digest_chat_id,
                    message_id=int(last_message_id),
                    text=text,
                    parse_mode="HTML"
                )
                logger.info(f"Обновлён alternate дайджест {last_message_id}")
                # Меняем тип для следующего раза
                set_config('alternate_digest_type', next_type)
                return
            except Exception as e:
                error_str = str(e)
                if "Message to edit not found" in error_str or "message can't be edited" in error_str:
                    logger.info(f"Старое сообщение {last_message_id} удалено, создаём новое")
                    set_config('alternate_digest_message_id', None)
                else:
                    logger.info(f"Не удалось редактировать: {e}")
        
        # Отправляем новое сообщение
        msg = await bot.send_message(chat_id=digest_chat_id, text=text, parse_mode="HTML")
        set_config('alternate_digest_message_id', msg.message_id)
        set_config('alternate_digest_type', next_type)
        logger.info(f"Создан новый alternate дайджест {msg.message_id}")
        
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


# =====================
# 🔧 УТИЛИТЫ
# =====================

def make_clickable(name, user_id):
    """Создать кликабельный никнейм для Telegram"""
    if name and name != "None" and user_id:
        return f"<a href=\"tg://user?id={user_id}\">{name}</a>"
    return name if name and name != "None" else "—"

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
        [KeyboardButton("📏 Моя длина"), KeyboardButton("🏆 Топ Фиссур")],
        [KeyboardButton("🏆 Топ MMR"), KeyboardButton("🔗 Привязать Steam")],
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
        user_rank = get_fissure_rank(update.effective_user.id)
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
            
            # Всегда показываем позицию пользователя, даже если он не в топе
            if user_rank:
                user_fissure = user.get('fissure', 0) if user else 0
                text += f"\n👤 Твоя позиция: #{user_rank} ({user_fissure:.1f} см)"
            else:
                # Если пользователь не найден в топе, показываем его текущую длину
                user_fissure = user.get('fissure', 0) if user else 0
                text += f"\n👤 Твоя позиция: — ({user_fissure:.1f} см)"
        
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


async def topmmr(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать топ игроков по MMR"""
    logger.info(f"User {update.effective_user.id} called topmmr")
    
    chat_id = update.message.chat_id
    chat_type = update.message.chat.type
    
    # Delete user message only in groups/channels
    if chat_type in ['group', 'supergroup', 'channel']:
        try:
            await context.bot.delete_message(chat_id, update.message.message_id)
        except Exception:
            pass
    
    try:
        from dota_mmr import get_week_top, update_user_mmr
        from database import get_user, get_connection, DATABASE_URL
        # Всегда обновляем MMR при вызове команды (без ограничения по времени)
        logger.info(f"topmmr: starting update for user {update.effective_user.id}")
        user = get_user(update.effective_user.id)
        if user and user.get('steam_id'):
            logger.info(f"topmmr: user has steam_id, calling update_user_mmr")
            result = update_user_mmr(update.effective_user.id)
            logger.info(f"topmmr: update_user_mmr result = {result}")
            # Получаем свежие данные пользователя после обновления
            user = get_user(update.effective_user.id)
        else:
            logger.info(f"topmmr: user has no steam_id")
        top_users = get_week_top(10)
        logger.info(f"topmmr: top_users = {top_users}")
        
        if not top_users:
            text = "🏆 Топ MMR за неделю\n\nПока нет данных об MMR игроков."
        else:
            lines = ["🏆 Топ MMR за неделю\n"]
            for i, player in enumerate(top_users, 1):
                username = player.get('steam_nickname') or player.get('username') or 'Unknown'
                rank_tier = player.get('rank_tier', 0)
                week_games = player.get('week_games', 0)
                week_wins = player.get('week_wins', 0)
                week_losses = week_games - week_wins
                
                # Форматируем ранг
                if rank_tier:
                    # Конвертируем rank_tier в строку ранга
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
                    rank_str = "Не ранжирован"
                
                # Форматируем winrate
                winrate = round((week_wins / week_games * 100), 1) if week_games > 0 else 0
                
                if i == 1:
                    prefix = "🥇"
                elif i == 2:
                    prefix = "🥈"
                elif i == 3:
                    prefix = "🥉"
                else:
                    prefix = f"{i}."
                
                lines.append(f"{prefix} {username} — {rank_str}\n└ 📊 {week_wins}W • {week_losses}L • WR {winrate}%")
            
            # Добавляем позицию пользователя
            user_rank_tier = user.get('rank_tier', 0) if user else 0
            
            if user_rank_tier:
                # Конвертируем rank_tier в строку ранга
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
                # Пользователь без ранга (rank_tier=0), но возможно с играми
                user_rank_str = "Без ранга"
            
            user_week_games = user.get('week_games', 0) if user else 0
            user_week_wins = user.get('week_wins', 0) if user else 0
            user_week_losses = user_week_games - user_week_wins
            user_winrate = round((user_week_wins / user_week_games * 100), 1) if user_week_games > 0 else 0
            
            logger.info(f"topmmr: user position calc - week_games={user_week_games}, week_wins={user_week_wins}, winrate={user_winrate}")
            
            # Проверяем, находится ли пользователь уже в общем топе
            user_is_in_top = False
            for player in top_users:
                if user and player.get('telegram_id') == user.get('telegram_id'):
                    user_is_in_top = True
                    break
            
            # Вычисляем позицию пользователя в недельном топе по винрейту
            user_pos = None
            if user and user.get('steam_id') and user_week_games > 0 and user_week_wins > 0:
                try:
                    conn = get_connection()
                    cursor = conn.cursor()
                    url = urlparse.urlparse(DATABASE_URL)
                    scheme = url.scheme
                    
                    if 'postgres' in scheme:
                        cursor.execute("""
                            SELECT COUNT(*) + 1 as rank FROM users 
                            WHERE (week_wins::numeric / NULLIF(week_games, 0) * 100) > %s 
                            AND steam_id IS NOT NULL AND week_games > 0
                        """, (user_winrate,))
                    else:
                        cursor.execute("""
                            SELECT COUNT(*) + 1 FROM users 
                            WHERE (week_wins * 100.0 / NULLIF(week_games, 0)) > ? 
                            AND steam_id IS NOT NULL AND week_games > 0
                        """, (user_winrate,))
                    
                    result = cursor.fetchone()
                    if result:
                        user_pos = result[0] if not isinstance(result, dict) else result.get('rank')
                    cursor.close()
                    conn.close()
                except Exception as e:
                    logger.error(f"Error getting week rank: {e}")
            
            # Показываем позицию только если пользователь НЕ в общем топе (избегаем дублирования)
            if not user_is_in_top:
                lines.append(f"\n👤 Твоя позиция:")
                if user_pos:
                    lines.append(f"#{user_pos} — {user_rank_str}\n📊 {user_week_wins}W • {user_week_losses}L • WR {user_winrate}%")
                else:
                    if user and user.get('steam_id'):
                        lines.append(f"#? — {user_rank_str}\n📊 {user_week_wins}W • {user_week_losses}L • WR {user_winrate}%")
                    else:
                        lines.append(f"Не привязан")
            
            text = "\n".join(lines)
        
        # Delete previous bot message before sending new one
        try:
            await delete_last_bot_message(context.bot, chat_id, update.effective_user.id)
        except Exception as e:
            logger.debug(f"Could not delete last bot message: {e}")
        
        result_msg = await context.bot.send_message(chat_id=update.effective_chat.id, text=text)
        # Track this message for future deletion
        set_last_bot_message(chat_id, update.effective_user.id, result_msg.message_id)
        schedule_delete(context.bot, chat_id, result_msg.message_id, 30, context.application.job_queue)
    except Exception as e:
        logger.error(f"Error in topmmr: {e}")
        # Send new message instead of replying to avoid "Message not found" error
        try:
            await delete_last_bot_message(context.bot, chat_id, update.effective_user.id)
        except Exception:
            pass
        await context.bot.send_message(chat_id=update.effective_chat.id, text="❌ Ошибка получения топа MMR")


async def link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Привязка Steam аккаунта по нику или Steam ID"""
    logger.info(f"User {update.effective_user.id} called link")
    
    chat_id = update.message.chat_id
    chat_type = update.message.chat.type
    
    # Delete user message only in groups/channels
    if chat_type in ['group', 'supergroup', 'channel']:
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
            await context.bot.send_message(chat_id=update.effective_chat.id, text="❌ Ошибка привязки Steam аккаунта")
        return
    
    # Если нет аргумента - отправляем инструкцию
    # Delete previous bot message before sending new one
    try:
        await delete_last_bot_message(context.bot, chat_id, update.effective_user.id)
    except Exception as e:
        logger.debug(f"Could not delete last bot message: {e}")
    
    result_msg = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="🎮 *Привязка Steam аккаунта*\n\n"
        "Используйте команду с никнеймом или Steam ID:\n"
        "`/link Miracle` - по нику\n"
        "`/link 76561198012345678` - по Steam ID\n"
        "`/link https://ru.dotabuff.com/players/347614699` - по Dotabuff\n\n"
        "Или нажмите кнопку и введите ник в ответ на это сообщение",
        parse_mode='Markdown'
    )
    # Track this message for future deletion
    set_last_bot_message(chat_id, update.effective_user.id, result_msg.message_id)
    schedule_delete(context.bot, chat_id, result_msg.message_id, 30, context.application.job_queue)


async def refresh(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обновить MMR одного пользователя"""
    logger.info(f"User {update.effective_user.id} called refresh")
    
    chat_id = update.message.chat_id
    chat_type = update.message.chat.type
    
    # Delete user message only in groups/channels
    if chat_type in ['group', 'supergroup', 'channel']:
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
                result_msg = await context.bot.send_message(chat_id=update.effective_chat.id, text="❌ Не удалось получить статистику")
        else:
            result_msg = await context.bot.send_message(chat_id=update.effective_chat.id, text="❌ У тебя не привязан Steam аккаунт. Используй /link")
        # Track this message for future deletion
        set_last_bot_message(chat_id, update.effective_user.id, result_msg.message_id)
        schedule_delete(context.bot, chat_id, result_msg.message_id, 30, context.application.job_queue)
    except Exception as e:
        logger.error(f"Error in refresh: {e}")
        try:
            await delete_last_bot_message(context.bot, chat_id, update.effective_user.id)
        except Exception:
            pass
        await context.bot.send_message(chat_id=update.effective_chat.id, text="❌ Ошибка обновления MMR")


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
            err_msg = await context.bot.send_message(chat_id=update.effective_chat.id, text="❌ Не удалось сохранить чат для дайджеста")
            chat = update.effective_chat
            if chat and chat.type in ['group', 'supergroup', 'channel']:
                schedule_delete(context.bot, chat.id, err_msg.message_id, 30, context.application.job_queue)
        except Exception:
            pass


async def weekly_digest_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ручной запуск еженедельного дайджеста в этот чат"""
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
        set_config("weekly_digest_message_id", None)
        
        # Создаём контекст для ручного вызова дайджеста
        class ManualContext:
            def __init__(self, app, bot):
                self.application = app
                self.bot = bot
        
        manual_context = ManualContext(context.application, context.bot)
        await weekly_digest_job(manual_context)
        
        msg = await context.bot.send_message(chat_id=update.effective_chat.id, text="✅ Еженедельный дайджест для этого чата создан/обновлён.")
        if chat.type in ['group', 'supergroup', 'channel']:
            schedule_delete(context.bot, chat_id, msg.message_id, 30, context.application.job_queue)
    except Exception as e:
        logger.error(f"Error in weekly_digest_now: {e}", exc_info=True)
        try:
            err_msg = await context.bot.send_message(chat_id=update.effective_chat.id, text="❌ Не удалось создать дайджест сейчас")
            chat = update.effective_chat
            if chat and chat.type in ['group', 'supergroup', 'channel']:
                schedule_delete(context.bot, chat.id, err_msg.message_id, 30, context.application.job_queue)
        except Exception:
            pass


async def menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Menu button handler - sends new content, deletes user message and old bot message immediately"""
    try:
        text = update.message.text.strip()
        
        menu_buttons = ["📈 Увеличить фиссуру", "📏 Моя длина", "🏆 Топ Фиссур", "🏆 Топ MMR", "🔗 Привязать Steam"]
        
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
        elif text == "🏆 Топ Фиссур":
            await top(update, context)
        elif text == "🏆 Топ MMR":
            await topmmr(update, context)
        elif text == "🔗 Привязать Steam":
            await link(update, context)
            
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
        try:
            # Пингуем бота чтобы не давать Render уснуть
            await bot.get_me()
            return web.Response(text="Bot is working", status=200)
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return web.Response(text="Bot error", status=500)
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
        if old_member and new_member and old_member.user.id == new_member.user.id:
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
        if old_member and new_member and old_member.user.id != new_member.user.id:
            old_status = old_member.status
            new_status = new_member.status
            
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
        # Запускаем миграции базы данных
        migrate_db()
        
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
        
        # Ежедневное обновление MMR всех пользователей с привязанным Steam
        job_queue.run_daily(
            update_all_mmr_job,
            time=datetime.time(hour=7, minute=0),  # 7:00 утра по МСК (4:00 UTC)
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
        
        # Чередование утреннего и Dota дайджеста каждые 5 минут
        job_queue.run_repeating(
            alternate_digest_job,
            interval=datetime.timedelta(minutes=5),
            first=datetime.datetime.now()
        )

        app.add_handler(CommandHandler("start", start))
        app.add_handler(CommandHandler("fissure", fissure))
        app.add_handler(CommandHandler("stats", stats))
        app.add_handler(CommandHandler("top", top))
        app.add_handler(CommandHandler("topmmr", topmmr))
        app.add_handler(CommandHandler("link", link))
        app.add_handler(CommandHandler("refresh", refresh))
        app.add_handler(CommandHandler("digestnow", digest_now))
        app.add_handler(CommandHandler("dotadigestnow", dota_digest_now))
        app.add_handler(CommandHandler("weeklydigest", weekly_digest_now))
        app.add_handler(CommandHandler("setdigestchat", set_digest_chat))
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
            
        # Сначала инициализируем application
        await app.initialize()
        
        # Запускаем application для активации job_queue
        await app.start()
        # Запускаем job_queue для PTB v20+
        await job_queue.start()
        
        # Устанавливаем webhook после инициализации
        await app.bot.set_webhook(url=webhook_url)
        
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
        site = web.TCPSite(runner, '0.0.0.0', int(os.getenv('PORT', 10000)))
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
        # Запускаем миграции базы данных
        migrate_db()
        
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
        
        # Ежедневное обновление MMR всех пользователей с привязанным Steam
        job_queue.run_daily(
            update_all_mmr_job,
            time=datetime.time(hour=7, minute=0),  # 7:00 утра по МСК (4:00 UTC)
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
        
        # Чередование утреннего и Dota дайджеста каждые 5 минут
        job_queue.run_repeating(
            alternate_digest_job,
            interval=datetime.timedelta(minutes=5),
            first=datetime.datetime.now()
        )

        app.add_handler(CommandHandler("start", start))
        app.add_handler(CommandHandler("fissure", fissure))
        app.add_handler(CommandHandler("stats", stats))
        app.add_handler(CommandHandler("top", top))
        app.add_handler(CommandHandler("topmmr", topmmr))
        app.add_handler(CommandHandler("link", link))
        app.add_handler(CommandHandler("refresh", refresh))
        app.add_handler(CommandHandler("digestnow", digest_now))
        app.add_handler(CommandHandler("dotadigestnow", dota_digest_now))
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



