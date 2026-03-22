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


async def delete_after_delay(bot, chat_id, msg_id, delay, job_queue=None):
    """������� ��������� ����� delay ������"""
    if job_queue:
        # ���������� JobQueue ��� ��������� ������������
        job_queue.run_once(
            delete_message_job,
            delay,
            data={'chat_id': chat_id, 'msg_id': msg_id},  # data ��� PTB
            name=f"delete_{chat_id}_{msg_id}"
        )
    else:
        # Fallback - �������� ������� ����� (����� �������)
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
    """Job ��� �������� ���������"""
    bot = context.application.bot  # ������ ����� context.application.bot � PTB v20+
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
    """������������� �������� ��������� ����� delay ������"""
    if job_queue:
        job_queue.run_once(
            delete_message_job,
            delay,
            data={'chat_id': chat_id, 'msg_id': msg_id},  # data ��� PTB
            name=f"delete_{chat_id}_{msg_id}"
        )
    else:
        # Fallback ���� job_queue �� �������
        asyncio.create_task(delete_after_delay(bot, chat_id, msg_id, delay, job_queue))


async def decrease_inactive_job(context):
    """���������� �������: ��������� fissure ���������� �������"""
    try:
        logger.info("������ ����������� ���������� fissure ��� ���������� �������")
        affected = decrease_inactive_fissure(days_inactive=1, decrease_amount=1.0)
        if affected > 0:
            logger.info(f"�������� fissure ��� {affected} ���������� �������")
        else:
            logger.info("��� ���������� ������� ��� ���������� fissure")
        
        # ��������� ������� �������
        update_player_positions()
    except Exception as e:
        logger.error(f"������ � decrease_inactive_job: {e}")


async def morning_digest_job(context):
    """�������� �������� (9:00)"""
    try:
        logger.info("������ ��������� ���������")
        
        # �������� ID ���� ��� ���������
        digest_chat_id = get_config('digest_chat_id')
        if not digest_chat_id:
            logger.info("��� ��� ��������� �� ��������")
            return
        
        stats = get_digest_stats()
        
        # ��������� ��������� � ������������� ����������
        growth_player, growth_pos = stats.get("top_growth", ("None", 0))
        drop_player, drop_cm = stats.get("top_drop", ("None", 0.0))
        streak_player, streak_len = stats.get("top_streak", ("None", 0))
        
        # �������� telegram_id ��� �������� ������������ ������
        growth_id = stats.get("top_growth_id")
        drop_id = stats.get("top_drop_id")
        streak_id = stats.get("top_streak_id")
        
        # ������� ��� �������� ������������� ��������
        def make_clickable(name, user_id):
            if name and name != "None" and user_id:
                return f"<a href=\"tg://user?id={user_id}\">{name}</a>"
            return name if name and name != "None" else "�"
        
        growth_display = make_clickable(growth_player, growth_id)
        drop_display = make_clickable(drop_player, drop_id)
        streak_display = make_clickable(streak_player, streak_id)
        
        # ������: ??stilevo +2?? ???None -X ��???Wad1m1 - ����� 1
        # ������ ���������� ������ ���� ���� �����
        if growth_player and growth_player != "None":
            growth_part = f"??{growth_display} +{growth_pos}??"
        else:
            growth_part = "??�"
        
        if drop_player and drop_player != "None":
            if drop_cm < 0:
                drop_part = f"??{drop_display} {drop_cm:.0f} ��"
            else:
                drop_part = f"??{drop_display} +{drop_cm:.0f} ��"
        else:
            drop_part = "??�"
        
        if streak_player and streak_player != "None":
            streak_part = f"??{streak_display} - ����� {streak_len}"
        else:
            streak_part = "??�"
        
        text = f"{growth_part} ?{drop_part} ?{streak_part}\n\n??������� �������� ?? 9:00 ���\n\n?? = ���� ������� � ����\n?? = ��� �������\n?? = ������� ����� �����"
        
        bot = context.application.bot
        
        # ������� ��������������� ������������ ���������
        last_message_id = get_config('daily_digest_message_id')
        if last_message_id:
            try:
                await bot.edit_message_text(
                    chat_id=digest_chat_id,
                    message_id=int(last_message_id),
                    text=text,
                    parse_mode="HTML"
                )
                logger.info(f"������� ������������ �������� {last_message_id}")
                # ��� ��������� ��������� (9:00) ��������� "������" �� ��������� �����.
                # ��� ������� /digestnow snapshot �� �������, ����� �������� ��������� �� ���������� 9:00.
                if not getattr(context, "manual", False):
                    update_digest_snapshot()
                return
            except Exception as e:
                error_str = str(e)
                # ���� ��������� �� ������� (�������) - ������� ID
                if "Message to edit not found" in error_str or "message can't be edited" in error_str:
                    logger.info(f"������ ��������� {last_message_id} ������� ��� ������ �������������, ������ �����")
                    set_config('daily_digest_message_id', None)
                else:
                    logger.info(f"�� ������� ������������� ���������: {e}")
        
        # ���������� ����� ���������
        msg = await bot.send_message(chat_id=digest_chat_id, text=text, parse_mode="HTML")
        set_config('daily_digest_message_id', msg.message_id)
        logger.info(f"������ ����� �������� �������� {msg.message_id}")
        if not getattr(context, "manual", False):
            update_digest_snapshot()
        
    except Exception as e:
        logger.error(f"������ � morning_digest_job: {e}", exc_info=True)


async def format_digest_message():
    """����������� ����� ��������� ���������"""
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
        return name if name and name != "None" else "�"
    
    growth_display = make_clickable(growth_player, growth_id)
    drop_display = make_clickable(drop_player, drop_id)
    streak_display = make_clickable(streak_player, streak_id)
    
    # ���� ���������� ���� ���� �����
    if growth_player and growth_player != "None":
        growth_part = f"??{growth_display} +{growth_pos}??"
    else:
        growth_part = "??�"
    
    # ������� ���������� ���� ���� ����� (����� ���� + ��� -)
    if drop_player and drop_player != "None":
        if drop_cm < 0:
            drop_part = f"??{drop_display} {drop_cm:.0f} ��"
        else:
            drop_part = f"??{drop_display} +{drop_cm:.0f} ��"
    else:
        drop_part = "??�"
    
    # ����� ���������� ���� ���� �����
    if streak_player and streak_player != "None":
        streak_part = f"??{streak_display} - ����� {streak_len}"
    else:
        streak_part = "??�"
    
    return f"{growth_part} ?{drop_part} ?{streak_part}\n\n??������� �������� ?? 9:00 ���\n\n?? = ���� ������� � ����\n?? = ��� �������\n?? = ������� ����� �����"


async def refresh_digest_message(bot):
    """��������� ��������� ��������� ����� ������� ������"""
    try:
        digest_chat_id = get_config('digest_chat_id')
        if not digest_chat_id:
            return
        
        # �������� ���������� (���������� �� ������ �������)
        # �� ��������� ������! �� ����������� ������ � morning_digest_job
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
                logger.debug(f"������� �������� ����� ������")
                return
            except Exception as e:
                error_str = str(e)
                if "Message to edit not found" in error_str or "message can't be edited" in error_str:
                    logger.info(f"��������� ��������� {last_message_id} ������ �������������, ���������� ID")
                    set_config('daily_digest_message_id', None)
                    return
                else:
                    logger.debug(f"�� ������� �������� ��������: {e}")
                    return
        
        # ���� message_id ������ - �� ������ �������������
        # �������� �������� ������ ����� ��� ����� /digestnow
        logger.debug("��������� ��������� ���, �� ������ �������������")
        
    except Exception as e:
        logger.error(f"������ � refresh_digest_message: {e}", exc_info=True)


async def weekly_digest_job(context):
    """������������ �������� (�� ����������)"""
    try:
        logger.info("������ ������������� ���������")
        
        digest_chat_id = get_config('digest_chat_id')
        if not digest_chat_id:
            logger.info("��� ��� ��������� �� ��������")
            return
        
        stats = get_weekly_digest_stats()
        
        text = "?? ������������ ��������\n\n"
        
        # ������ ���� ����� � �� �� ������
        growth_player, growth_cm = stats.get("top_growth_cm", ("None", 0))
        growth_id = stats.get("top_growth_cm_id")
        
        def make_clickable_weekly(name, user_id):
            if name and name != "None" and user_id:
                return f"<a href=\"tg://user?id={user_id}\">{name}</a>"
            return name if name and name != "None" else "�"
        
        growth_display = make_clickable_weekly(growth_player, growth_id)
        if growth_player and growth_player != "None":
            text += f"?? ������ ���� �����: {growth_display} (+{growth_cm:.0f} ��)\n"
        
        # ������ ������: ��� �������� �� ������ ����� ������� � ����
        breakthrough_player, breakthrough_pos = stats.get("breakthrough", ("None", 0))
        breakthrough_id = stats.get("breakthrough_id")
        breakthrough_display = make_clickable_weekly(breakthrough_player, breakthrough_id)
        if breakthrough_player and breakthrough_player != "None":
            text += f"?? ������ ������: {breakthrough_display} (+{breakthrough_pos} �������)\n"
        
        total_rolls = stats.get("total_rolls_week", 0)
        new_players = stats.get("new_players_week", 0)
        total_growth = stats.get("total_growth_week", 0)
        
        text += f"\n?? ���������� ������:\n"
        text += f"� ����� �������: {total_rolls}\n"
        text += f"� ����� �������: {new_players}\n"
        text += f"� ����� ����: +{total_growth:.0f} ��\n"
        
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
        logger.error(f"������ � weekly_digest_job: {e}", exc_info=True)


async def digest_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """������ ������ ��������� ��������� � ���� ���"""
    try:
        chat = update.effective_chat
        chat_id = chat.id
        # � ������� ������� ��������� ������������ � ��������
        if chat.type in ['group', 'supergroup', 'channel']:
            try:
                await context.bot.delete_message(chat_id, update.message.message_id)
            except Exception as e:
                logger.debug(f"Could not delete user message: {e}")
        # ��������� ���� ��� ��� ��� ��� ��������� � ���������� message_id
        set_config("digest_chat_id", chat_id)
        set_config("daily_digest_message_id", "")

        class SimpleContext:
            def __init__(self, application):
                self.application = application
                # ����, ��� ��� ������ ������, � �� �������� ����
                self.manual = True

        # ������ ������� ��������, ����� ���������������� morning_digest_job
        simple_context = SimpleContext(context.application)
        await morning_digest_job(simple_context)

        msg = await update.message.reply_text("? �������� �������� ��� ����� ���� ������/�������.")
        if chat.type in ['group', 'supergroup', 'channel']:
            schedule_delete(context.bot, chat_id, msg.message_id, 30, context.application.job_queue)
    except Exception as e:
        logger.error(f"Error in digest_now: {e}", exc_info=True)
        try:
            err = await update.message.reply_text("? �� ������� ������� �������� ������")
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
    50: ["?????? ����������! +50 ��!", "?? �������! +50 �� �� ���!", "?? ����������! +50 ��!", "?? �����������! +50 ��!", "?? �����������! +50 ��!"],
    30: ["?? ������! +30 ��!", "?? ����� �����! +30 ��!", "? ���� �����! +30 ��!", "?? ���� ����! +30 ��!"],
    20: ["?? MEGA �����! +20 ��!", "?? ����� � �������! +20 ��!", "?? ������� ����! +20 ��!", "?? ���������! +20 ��!"],
    10: ["?? �������! +10 ��!", "?? �����! +10 ��!", "?? ������ �����! +10 ��!", "?? ������������ �����! +10 ��!"],
    5: ["?? ���! +5 ��!", "?? �������! +5 ��!", "? ����! +5 ��!", "?? �������! +5 ��!"],
    3: ["?? �������! +3 ��", "?? ���Ҩ�! +3 ��", "?? ��! +3 ��", "?? � ����! +3 ��"],
    1: ["? OK! +1 ��", "?? ���� ����! +1 ��", "?? �������! +1 ��", "?? ����� ���� ����! +1 ��"],
    0: ["? ��� ���������", "?? ����� �� �����", "? �����", "?? ���?"],
    -1: ["?? ������� -1 ��", "?? ����� -1 ��", "?? ��! -1 ��", "?? ����! -1 ��"],
    -3: ["?? ��... -3 ��", "?? ���� -3 ��", "?? �����! -3 ��", "?? ������! -3 ��"],
    -5: ["?? ������ -5 ��...", "?? ������� -5 ��", "?? �����! -5 ��...", "?? �� ��... -5 ��"],
    -10: ["?? ����������! -10 ��!!!", "?? �����������! -10 ��!!!", "?? ������ ����! -10 ��!!!", "?? ����������! -10 ��!!!"]
}

ROLL_MEMES = {
    50: [
        "?? ���� ������� ������, ��� ���-�� ����������!",
        "?? ��������: '� ��� ��� �� ������� �����?'",
        "?? ������ ����� ��������� OnlyFissures �����!"
    ],
    30: [
        "?? ��� ��� ����� 1000 ������ � ������ �������!",
        "??? ������ ����� ������� ����� �� �������!",
        "?? ������������ � ������, �������� � ��!"
    ],
    20: [
        "?? ���� ������� ������� ������, ��� ����� �����!",
        "?? ��� ��� �� �������, � ���������!",
        "?? ������ ����� ��������! (���������, ��� ��)"
    ],
    10: [
        "?? ��� ��� �������� ����� � �����������!",
        "?? �������: '� �����!'",
        "?? ������ �� �� 10 �� ����� � �������!"
    ],
    5: [
        "?? ��� ��� ����� 500 ������ � �������!",
        "?? �������������������� ������� �������!",
        "?? ����� ������ ��������� ��������!"
    ],
    3: [
        "?? ��� ���������� �������!",
        "?? ��� ��� ����� � �������� - ������, �� �������!",
        "?? ��������, �� �����!"
    ],
    1: [
        "?? ���������, �� ������!",
        "? ���� �� �����, ��� ���� ��!",
        "?? ������� �������: '� ��������!'",
        "?? ����� � �� ����� ����� ��������!"
    ],
    0: [
        "??? ������������ - ������� ����������!",
        "?? ������� ������ ���������!",
        "?? �� �����������, �� �����������!"
    ],
    -1: [
        "?? ������� �� �����!",
        "?? ���� ��������� ��� ����� ��� �������� ������ �����!",
        "?? ���� ��������� ������... ��� ������!"
    ],
    -3: [
        "?? ��� ���������� � ������!",
        "?? ������� �������!",
        "?? ���������� ��������� � ���� ������!",
        "?? �������� �� ������ �����!"
    ],
    -5: [
        "?? ����� ������� ��������� ����������!",
        "? ����� ���� - ��� ������ �����!",
        "??? ������� ����� ������!",
        "?? ����������� ����!"
    ],
    -10: [
        "?? ������ �����������!",
        "?? �� ����� � ����!",
        "?? ������� �������� ���!",
        "?? 0/10/0!",
        "?? ����� ��� �����������!",
        "?? ��, ���������!"
    ]
}

CATEGORY_PHRASES = {
    "up": [
        "?? �����!",
        "?? ������ �� �����!",
        "? ������� ��������!",
        "?? ������������� ��������!",
        "?? ��� �������!",
        "?? ����� � ������ �����!"
    ],
    "down": [
        "?? ��������� �����!",
        "?? ������� �������������!",
        "?? ������ ����� ����!",
        "? ��������� ����!",
        "?? �� ��������!",
        "?? ��� ��� �� �����!"
    ],
    "same": [
        "?? ������������ - ��� ������!",
        "?? ������ �������!",
        "?? ��� ��������� - ���� ���������!",
        "? ����� ��� �����!",
        "?? ����������� �����!",
        "??? ������� ���������!"
    ],
    "bonus_help": [
        "? ������� �������!",
        "?? ������� �������!",
        "?? �����!",
        "?? ����������� ���������!",
        "?? �������!",
        "?? ���������!"
    ],
    "fatal": [
        "?? ����������� ����!",
        "?? �� �� ������!",
        "?? �����!",
        "?? ��� � ����!",
        "?? ���������!",
        "?? ������� �� ��������!"
    ]
}

WELCOME_PHRASES = [
    # Dota 2 ������� ����
    "{name}, ����� ����������! �������� �� ���� ���?",
    "{name} �������������! ����� ������� � ���������!",
    "{name}, ����� � ������� �����? ����� ������!",
    "��������! {name} ����� � ����� - ���� ����������!",
    "{name} � ����! ������ ������� ����������!",
    "����� ����������, {name}! ���������� ���� ��� �����?",
    "{name}, �� ������ ������ ����� � ��������!",
    "{name} � ����! ����� �������� �� ��� ��������!",
    "�������-�� {name} �����! ����� �� �� ������!",
    "{name}, �� ���� �� �����! ����� �������!",
    "��������, {name}! ������� ����� ������� 100%!",
    "{name}, �� �����! ���� ��� ����!",
    "{name} � �������! ��� ��������������� ������!",
    "����� ���������� � ��, {name}! �����!",
    "{name}, �� ������� ���� ���� ����� ������!",
    "�����, {name}, �����! ����� �� ���� ���� ������!",
    "{name}, ����� �� �����! �� ����� ����!",
    "������������ ������ ����� - {name}!",
    "{name}, ���� ���� � �����!",
    "{name}, �� ������ ��� �� ������� �����!",
    # ���
    "{name}, ����� ����������! ������� ������ ��������?",
    "{name} � ����! ����� ������!",
    "������, {name}! ����� �������� ��� ����!",
    "{name}, �� ����� � ���? ���� �� ����!",
    "����� ����������, {name}! �� ������ ��� ����!",
    "{name}, �� ����! ����� ������!",
    "{name}, ������ � ����! ������� ���!",
    "{name}, �����! �� �� ���� ������������!",
    "{name}, ����� ��� �����! ������ �����!",
    "{name}, ����� � ������? ���� ����!",
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
        fatal_chance = 0.02  # 2% ��� ������ 20+ ��
        if random.random() < fatal_chance:
            return FATAL_ROLL, "FATAL DECREASE!", True, False
    
    # ������ ������ ��� ���� ������
    if current_fissure < 5:
        if random.random() < 0.8:
            bonus_options = [
                (5, 30), (10, 25), (20, 20), (30, 15), (50, 10)
            ]
            values, weights = zip(*bonus_options)
            roll = random.choices(values, weights=weights)[0]
            return roll, "? ������������ ������!", False, True
        
        protected_rolls = [0, 1, 3, 5, 10, 20]
        roll = random.choice(protected_rolls)
        return roll, "?? ����٨���� ����", False, True
    
    elif current_fissure < 20:
        if random.random() < 0.4:
            improved_options = [3, 5, 10, 20]
            roll = random.choice(improved_options)
            return roll, "?? ���������� ����!", False, True
    
    elif current_fissure < 100:
        if random.random() < 0.2:
            bonus = random.choice([5, 10, 20])
            return bonus, "?? ������� ����!", False, False
    
    else:
        # ��� ����� ������� ������ - ������ �������
        if random.random() < 0.1:
            bonus = random.choice([5, 10, 20])
            return bonus, "?? ������� ����!", False, False
    
    # ������ ������ ��� ����:
    # ������� 65%, �������� 30%, ����� 5%
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
        protection_msg = f"?? ���� ������! ���� {roll}, ������ {reduced_roll}"
        return reduced_roll, protection_msg
    
    return roll, ""


def calculate_new_fissure(current_fissure, roll):
    """Calculates new fissure size with minimum 0.1"""
    new_value = current_fissure + roll
    return max(0.1, new_value)


def main_menu():
    keyboard = [
        [KeyboardButton("?? ��������� �������")],
        [KeyboardButton("?? ��� �����"), KeyboardButton("?? ���")],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)


def format_time(seconds):
    h = seconds // 3600
    m = (seconds % 3600) // 60
    return f"{int(h)}� {int(m)}�"


async def fissure(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Increase fissure"""
    logger.info(f"User {update.effective_user.id} called fissure")
    
    user_obj = update.effective_user
    username = user_obj.username or user_obj.first_name
    chat_id = update.message.chat_id
    chat_type = update.message.chat.type
    user_msg_id = update.message.message_id
    now = time.time()
    
    # �������� �� �������� (������� = 5, ����������� = 6)
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
            text = f"? ������� �����������������. �������: {format_time(wait)}"
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
        
        # ����� ��� ��������: ����������� ������������� ����
        if is_weekend and roll > 0 and not is_fatal:
            bonus_multiplier = random.choice([1.5, 2, 2.5])
            roll = int(roll * bonus_multiplier)
            weekend_bonus = f"\n?? ��������! x{bonus_multiplier:.1f}"
        
        new_fissure = calculate_new_fissure(user["fissure"], roll)
        update_fissure(user_obj.id, new_fissure, now, roll)
        
        # ��������� �������� ����� ������� ������
        await refresh_digest_message(context.bot)
        
        logger.info(f"User {user_obj.id} used fissure. New cooldown: {now}")

        roll_key = min(roll, 50)
        roll_key = max(roll_key, -10)
        
        if roll_key in ROLL_TEXTS:
            result_text = random.choice(ROLL_TEXTS[roll_key])
        else:
            result_text = f"{'+' if roll > 0 else ''}{roll} ��"
        
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
            f"?? {display_username}\n\n"
            f"{result_text}\n"
            f"{extra_text}\n\n"
            f"?? ����� ������: {new_fissure:.1f} ��"
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
                await update.message.reply_text("? ������ ��������� �������")
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
            wait_text = f"��������������: {format_time(remaining_cooldown)}"
        else:
            wait_text = "? ����� � ����������!"
        
        # ����������� username ��� ������������ ������ �� �������
        user_id = user_obj.id
        display_username = f"<a href=\"tg://user?id={user_id}\">{username}</a>"
        
        text = f"?? {display_username}\n\n?? �����: {user['fissure']:.1f} ��\n?? �������: {user.get('total_rolls', 0)}\n?? ������� �����: {user.get('current_streak', 0)}\n?? ������ �����: {user.get('best_streak', 0)}"
        
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
            await update.message.reply_text("? ������ ��������� ����������")
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
            text = "?? ���� ��� �������. ���� ������!"
        else:
            text = "?? ��� 10 ������\n\n"
            medals = {1: "??", 2: "??", 3: "??"}
            for i, user_top in enumerate(top_users, 1):
                name = user_top.get('username', 'Unknown')[:15]
                medal = medals.get(i)
                if medal:
                    text += f"{medal} {name}: {user_top['fissure']:.1f} ��\n"
                else:
                    text += f" {i}. {name}: {user_top['fissure']:.1f} ��\n"
            
            if user_rank:
                user_fissure = user.get('fissure', 0) if user else 0
                text += f"\n?? ���� �������: #{user_rank} ({user_fissure:.1f} ��)"
        
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
            await update.message.reply_text("? ������ ��������� ����")
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
        text = "?? ������! ����� ����� ��������� ���� �������"
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
    """���������� ������� ��� ��� ��� ��� ��������� ���������"""
    try:
        chat = update.effective_chat
        chat_id = chat.id
        # � ������� ������� ��������� ������������ � ��������
        if chat.type in ['group', 'supergroup', 'channel']:
            try:
                await context.bot.delete_message(chat_id, update.message.message_id)
            except Exception as e:
                logger.debug(f"Could not delete user message: {e}")
        # ��������� ID ���� � ������ � ���������� message_id
        set_config("digest_chat_id", chat_id)
        set_config("daily_digest_message_id", "")

        msg = await update.message.reply_text(
            f"? ��� ��� ��������� ��������� ����������.\n"
            f"ID ����: `{chat_id}`\n"
            f"������ � 09:00 �������� ����� ��������� ����.",
            parse_mode="Markdown"
        )
        # � �������/������� ������� ��������� ��������� ����� 30 ������
        if chat.type in ['group', 'supergroup', 'channel']:
            schedule_delete(context.bot, chat_id, msg.message_id, 30, context.application.job_queue)
    except Exception as e:
        logger.error(f"Error in set_digest_chat: {e}", exc_info=True)
        try:
            err = await update.message.reply_text("? �� ������� ��������� ��� ��� ���������")
            chat = update.effective_chat
            if chat and chat.type in ['group', 'supergroup', 'channel']:
                schedule_delete(context.bot, chat.id, err.message_id, 30, context.application.job_queue)
        except Exception:
            pass




async def link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /link command - link Steam account"""
    try:
        user = update.effective_user
        if not user:
            return
        
        args = context.args
        if not args:
            await update.message.reply_text(
                "?? <b>�������� Steam ��������</b>\n\n"
                "�����������: /link <SteamID ��� �������>\n\n"
                "������: /link 123456789\n"
                "������: /link Dendi",
                parse_mode='HTML'
            )
            return
        
        identifier = args[0]
        result = dota_mmr.register_steam(user.id, identifier)
        
        if result.get('success'):
            data = result.get('data', {})
            await update.message.reply_text(
                f"? <b>Steam ������� ��������!</b>\n\n"
                f"?? Nickname: {data.get('nickname', 'N/A')}\n"
                f"?? MMR: {data.get('mmr', 0)}\n"
                f"?? ���: {data.get('total_games', 0)}",
                parse_mode='HTML'
            )
        else:
            await update.message.reply_text(
                f"? ������: {result.get('message', '����������� ������')}"
            )
    except Exception as e:
        logger.error(f"Error in link command: {e}")
        await update.message.reply_text("? ��������� ������ ��� ��������� �������")


async def topmmr(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /topmmr command - show top players by MMR"""
    try:
        result = dota_mmr.get_mmr_top(limit=10)
        
        if not result:
            await update.message.reply_text(
                "?? <b>��� ������� �� MMR</b>\n\n"
                "���� ��� ������ � �������. "
                "����������� /link ��� �������� Steam!",
                parse_mode='HTML'
            )
            return
        
        text = "?? <b>��� ������� �� MMR</b>\n\n"
        for i, player in enumerate(result, 1):
            text += f"{i}. {player.get('nickname', 'N/A')} - {player.get('mmr', 0)} MMR\n"
        
        await update.message.reply_text(text, parse_mode='HTML')
    except Exception as e:
        logger.error(f"Error in topmmr command: {e}")
        await update.message.reply_text("? ��������� ������ ��� ��������� �������")


async def mmr_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /mmr command - show user's Dota MMR"""
    try:
        user = update.effective_user
        if not user:
            return
        
        # Check if Steam is linked
        if not dota_mmr.is_steam_linked(user.id):
            await update.message.reply_text(
                "? Steam ������� �� ��������!\n"
                "����������� /link <SteamID ��� �������> ��� ��������."
            )
            return
        
        result = dota_mmr.get_user_dota_stats(user.id)
        
        if result:
            total_games = result.get('total_games', 0)
            wins = result.get('wins', 0)
            winrate = round((wins / total_games * 100) if total_games > 0 else 0, 1)
            
            text = (
                f"?? <b>���� MMR</b>\n\n"
                f"���: {result.get('steam_nickname', 'N/A')}\n"
                f"?? MMR: {result.get('mmr', 0)}\n"
                f"?? ���: {total_games} | �����: {wins} ({winrate}%)"
            )
            await update.message.reply_text(text, parse_mode='HTML')
        else:
            await update.message.reply_text("? �� ������� �������� ����������")
    except Exception as e:
        logger.error(f"Error in mmr command: {e}")
        await update.message.reply_text("? ��������� ������ ��� ��������� �������")


async def ruiner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /Ruiner command - find a random chat member as 'ruiner'"""
    try:
        user = update.effective_user
        if not user:
            return
        
        # Random jokes about being a "ruiner"
        jokes = [
            "@{user}, �� ����� �����, � �� ������� ������?",
            "@{user}, ���� ���� ���������? ������ ��� �� ������ � �������, ��� �������� � �������",
            "@{user}, ���� �������� � ��������� �� ��, ��� ����� ������������?",
            "@{user}, ���� �������� ������, ����� �� �������� � ����",
            "@{user}, ��� �� ��� ����� ���������?",
            "@{user}, ��� �������, ��� �� �����... �������",
            "@{user}, ������ � ������� '������ �����������' ��� ��� ����",
            "@{user}, Valve ������ ���� ������ '����� � ��������� �������'",
            "@{user}, �� ���������, ��� ���� ������� - ��� 4 �������� � ��?",
            "@{user}, �� ������� ���, ����� � ���� 100 ���� � 2 FPS",
        ]
        
        joke = random.choice(jokes).format(user=user.username or user.first_name)
        
        await update.message.reply_text(
            f"?? <b>������ ������!</b>\n\n{joke}",
            parse_mode='HTML'
        )
    except Exception as e:
        logger.error(f"Error in ruiner command: {e}")
        await update.message.reply_text("? ��������� ������ ��� ��������� �������")


async def menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Menu button handler - sends new content, deletes user message and old bot message immediately"""
    try:
        text = update.message.text.strip()
        
        menu_buttons = ["?? ��������� �������", "?? ��� �����", "?? ���"]
        
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
        if text == "?? ��������� �������":
            await fissure(update, context)
        elif text == "?? ��� �����":
            await stats(update, context)
        elif text == "?? ���":
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
        
        # ���� ��� ��� ��� ������ ��� �������� � ��� � ������������� ���������� ��� ��� ���������,
        # ���� �� ��� �� ��������
        try:
            bot_id = context.bot.id
            if new_member.user.id == bot_id and not get_config("digest_chat_id"):
                set_config("digest_chat_id", chat_id)
                logger.info(f"������������� ���������� digest_chat_id = {chat_id}")
        except Exception as e:
            logger.debug(f"�� ������� ������������� ���������� digest_chat_id: {e}")
        
        # User joined the chat (was not a member, now is member)
        if old_status in ['left', 'kicked'] and new_status in ['member', 'administrator']:
            name = new_member.user.first_name or "Friend"
            user_id = new_member.user.id
            
            # ��������� �������������� ��������� � ������������ �����
            welcome_text = f"<a href=\"tg://user?id={user_id}\">{name}</a>, {random.choice(WELCOME_PHRASES)}"

            
            result_msg = await context.bot.send_message(
                chat_id=chat_id,
                text=welcome_text,
                parse_mode="HTML"
            )
            logger.info(f"Welcome sent for {name}")
            # ������� �������������� ��������� ����� ���
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
        
        # ������ JobQueue � ����������� � application
        job_queue = JobQueue()
        app = ApplicationBuilder().token(TOKEN).job_queue(job_queue).build()
        
        # �������������� job_queue � application ��� PTB v20+
        job_queue.set_application(app)
        
        # Daily job
        job_queue.run_daily(
            decrease_inactive_job,
            time=datetime.time(hour=0, minute=0),
            days=(0, 1, 2, 3, 4, 5, 6)
        )
        
        # �������� �������� � 9:00 ���� �� ��� (6:00 UTC)
        job_queue.run_daily(
            morning_digest_job,
            time=datetime.time(hour=6, minute=0),
            days=(0, 1, 2, 3, 4, 5, 6)
        )
        logger.info("Done")
        
        # �������� �������� ������ live (����������� ����� ������� ������)
        
        # ������������ �������� �� �������������
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
        app.add_handler(CommandHandler("link", link))
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
        
        # ��������� application ��� ��������� job_queue
        await app.start()
        # ��������� job_queue ��� PTB v20+
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
        
        # ������ JobQueue � ����������� � application
        job_queue = JobQueue()
        app = ApplicationBuilder().token(TOKEN).job_queue(job_queue).build()
        
        # �������������� job_queue � application ��� PTB v20+
        job_queue.set_application(app)
        
        # Daily job
        job_queue.run_daily(
            decrease_inactive_job,
            time=datetime.time(hour=0, minute=0),
            days=(0, 1, 2, 3, 4, 5, 6)
        )
        
        # �������� �������� � 9:00 ���� �� ��� (6:00 UTC)
        job_queue.run_daily(
            morning_digest_job,
            time=datetime.time(hour=6, minute=0),
            days=(0, 1, 2, 3, 4, 5, 6)
        )
        logger.info("Done")
        
        # �������� �������� ������ live (����������� ����� ������� ������)
        # ������������ �������� �� �������������
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
        app.add_handler(CommandHandler("link", link))
        app.add_handler(CommandHandler("topmmr", topmmr))
        app.add_handler(CommandHandler("Ruiner", ruiner))
        app.add_handler(MessageHandler(filters.Regex(r'^/start@DotaFull_bot$'), start))
        app.add_handler(MessageHandler(filters.Regex(r'^/fissure@DotaFull_bot$'), fissure))
        app.add_handler(MessageHandler(filters.Regex(r'^/stats@DotaFull_bot$'), stats))
        app.add_handler(MessageHandler(filters.Regex(r'^/top@DotaFull_bot$'), top))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, menu_handler))
        app.add_handler(ChatMemberHandler(welcome_new_member, ChatMemberHandler.CHAT_MEMBER))

        logger.info("Telegram bot started in polling mode")
        
        # ��������� job_queue ��� PTB v20+
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





