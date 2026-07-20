"""
Fissure-specific logic extracted from main.py.
This module contains the core fissure roll handling and related helpers.
All extractions are done without changing any bot behavior or visuals.
"""

import asyncio
import logging
import random
import time
import traceback
from collections import deque

from telegram import Update
from telegram.ext import ContextTypes

# Imports from other modules (will be adjusted as we extract more)
# The following are prepared for the full fissure() implementation (do not remove during incremental extraction)
from bot_utils import (
    add_bot_message,
    bot_can_delete,
    delete_last_bot_message,
    format_time,
    main_menu,
    make_clickable,
    record_recent_fissure_roll,
    recent_fissure_rolls,
    schedule_delete,
    set_last_bot_message,
)
from constants import get_banner_path, get_random_cooldown_banner_path
from constants import (
    COOLDOWN,
    WEEKEND_BONUS_MULTIPLIERS,
    ZEUS_TEXTS,
)
from database import get_user, update_fissure, update_last_message_id, zeus_strike, user_cache
from digest import invalidate_digest_cache
from rate_limiter import is_rate_limited
from rolls import (
    apply_fissure_protection,
    calculate_fissure_roll,
    calculate_new_fissure,
    calculate_streak_bonus,
    get_roll_text,
    get_hero_quote,
    ROLL_TEXTS,
    MULTICAST_TEXTS,
)
from stats import get_event_chances
from techies import handle_techies_event

# Fissure-specific in-memory state (moved from main.py for clean extraction)
_user_fissure_processing: dict[int, float] = {}


logger = logging.getLogger(__name__)


# =====================
# HELPER FUNCTIONS (pure, safe to extract)
# =====================

def is_weekend_msk() -> bool:
    """Определяет, является ли текущий день выходным по МСК (без изменения логики)."""
    import datetime
    msk_time = datetime.datetime.now(datetime.UTC) + datetime.timedelta(hours=3)
    return msk_time.weekday() in (5, 6)


async def delete_fissure_user_and_last_messages(bot, chat_id, user_id, user_msg_id, chat_type):
    """
    Безопасное удаление сообщений пользователя и последнего бота при /fissure.
    Логика полностью сохранена из main.py.
    """
    # Delete user message only in groups/channels (not in private)
    if chat_type in ['group', 'supergroup', 'channel']:
        if await bot_can_delete(bot, chat_id):
            try:
                await bot.delete_message(chat_id, user_msg_id)
            except Exception as e:
                logger.debug(f"Could not delete user message in delete_fissure_user_and_last_messages: {e}")

    # Small delay before deleting last bot message to ensure new message can be sent
    await asyncio.sleep(0.2)

    # Delete last bot message immediately
    try:
        await delete_last_bot_message(bot, chat_id, user_id)
    except Exception as e:
        logger.debug(f"Could not delete last bot message in delete_fissure_user_and_last_messages: {e}")


def build_fissure_cooldown_bar_and_text(now, last_fissure, COOLDOWN, format_time):
    """Pure function to build the cooldown progress bar and text. Logic unchanged."""
    wait = COOLDOWN - (now - (last_fissure or 0))
    elapsed = COOLDOWN - wait
    filled = int(elapsed / COOLDOWN * 10)
    bar = "🟩" * filled + "⬜️" * (10 - filled)
    text = f"🧬 Восстанавливается. {format_time(wait)}\n{bar}"
    return text


def should_skip_due_to_spam(user_id, now, processing_dict):
    """Returns True if the user is already being processed (spam protection)."""
    if processing_dict.get(user_id):
        return True
    processing_dict[user_id] = now
    return False


async def send_fissure_cooldown_response(bot, chat_id, user_id, text, banner_url, main_menu_func, set_last_bot_message_func, schedule_delete_func, update_last_message_id_func, job_queue):
    """
    Sends the cooldown photo message and performs all related tracking.
    Logic is 100% preserved from the original.
    """
    result_msg = await bot.send_photo(
        chat_id=chat_id,
        photo=banner_url,
        caption=text,
        reply_markup=main_menu_func()
    )
    set_last_bot_message_func(chat_id, user_id, result_msg.message_id)
    schedule_delete_func(bot, chat_id, result_msg.message_id, 30, job_queue)
    update_last_message_id_func(user_id, result_msg.message_id)
    await asyncio.sleep(0.1)


async def handle_zeus_event(bot, chat_id, user, user_obj, display_username, now, ZEUS_TEXTS, main_menu, set_last_bot_message, schedule_delete, update_fissure, update_last_message_id, zeus_strike, record_recent_fissure_roll=None):
    """
    Handles the Zeus strike event (no roll, -2.5% to all fissures).
    Logic and all messages are 100% preserved from the original.
    """
    affected, total_cm = zeus_strike(percent=0.025, exclude_telegram_id=user_obj.id)

    user = get_user(user_obj.id, user_obj.username)
    new_fissure = user.get("fissure", 0)

    zeus_text = random.choice(ZEUS_TEXTS)

    text = (
        f"🎲 {display_username}\n\n"
        f"{zeus_text}\n\n"
        f"💀 Все Фиссуры −2.5%, {affected} жертв.\n"
        f"📉 Суммарно отнято: {total_cm} см\n\n"
        f"📏 {new_fissure:.1f} см"
    )

    zeus_banner_url = get_banner_path("zeus")
    result_msg = await bot.send_photo(
        chat_id=chat_id,
        photo=zeus_banner_url,
        caption=text,
        parse_mode="HTML",
        reply_markup=main_menu()
    )
    if record_recent_fissure_roll:
        record_recent_fissure_roll(user_obj.id, user_obj.username, 0, user.get("fissure", 0), cascade=0, event_type="zeus")

    set_last_bot_message(chat_id, user_obj.id, result_msg.message_id)
    schedule_delete(bot, chat_id, result_msg.message_id, 600, None)  # job_queue passed from caller if needed
    update_fissure(user_obj.id, user.get("fissure", 0), now, 0, last_message_id=result_msg.message_id)

    await asyncio.sleep(0.1)
    return  # exit without roll


def process_multicast_result(roll, cascade_count, MULTICAST_TEXTS):
    """
    Applies the cascade multiplier to the roll and selects the multicast text.
    Pure function, logic unchanged.
    """
    original_roll = roll
    roll = roll * cascade_count

    multicast_text = ""
    if cascade_count > 1:
        multicast_text = random.choice(MULTICAST_TEXTS[cascade_count])

    return roll, original_roll, multicast_text


# =====================
# MAIN FISSURE HANDLER (extracted from main.py - behavior 100% preserved)
# =====================
# MAIN FISSURE HANDLER (extracted from main.py - behavior 100% preserved)
# =====================

async def fissure(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Increase fissure"""
    logger.info(f"User {update.effective_user.id} called fissure")

    user_obj = update.effective_user
    username = user_obj.username
    display_username = make_clickable(username or user_obj.first_name or "Игрок", user_obj.id)
    chat_id = update.message.chat_id
    chat_type = update.message.chat.type
    user_msg_id = update.message.message_id
    now = time.time()

    # Глобальная проверка rate limit - защита от всплеска запросов при атаке/боте
    if is_rate_limited():
        logger.warning("fissure: skipped due to rate limit")
        return

    # Проверка на выходные по МСК (суббота = 5, воскресенье = 6)
    is_weekend = is_weekend_msk()
    weekend_bonus = ""

    # Use extracted helper (logic unchanged)
    await delete_fissure_user_and_last_messages(
        context.bot, chat_id, user_obj.id, user_msg_id, chat_type
    )

    # Spam protection - ignore if already processing this user
    if should_skip_due_to_spam(user_obj.id, now, _user_fissure_processing):
        return

    try:
        user_cache.remove(user_obj.id)
        user = get_user(user_obj.id, username)
        _log_user = {k: v for k, v in user.items() if k != "analytics_cache"}
        logger.info(f"user data: {_log_user}")

        # Check cooldown
        last_f = user.get("last_fissure") or 0
        cooldown_diff = now - last_f
        if cooldown_diff < COOLDOWN:
            text = build_fissure_cooldown_bar_and_text(
                now, last_f, COOLDOWN, format_time
            )
            cooldown_banner_url = get_random_cooldown_banner_path()
            try:
                await send_fissure_cooldown_response(
                    context.bot,
                    chat_id,
                    user_obj.id,
                    text,
                    cooldown_banner_url,
                    main_menu,
                    set_last_bot_message,
                    schedule_delete,
                    update_last_message_id,
                    context.job_queue
                )
            except Exception as e:
                logger.error(f"fissure: cooldown banner failed, sending text fallback: {e}")
                try:
                    msg = await context.bot.send_message(
                        chat_id=chat_id, text=text, parse_mode="HTML", reply_markup=main_menu()
                    )
                    set_last_bot_message(chat_id, user_obj.id, msg.message_id)
                    schedule_delete(context.bot, chat_id, msg.message_id, 30, context.job_queue)
                    update_last_message_id(user_obj.id, msg.message_id)
                except Exception as e2:
                    logger.error(f"fissure: cooldown text fallback also failed: {e2}")
            logger.info(f"fissure: cooldown response sent for user {user_obj.id}")
            return

        multicast_text = ""
        original_roll = None
        zeus_triggered = False
        zeus_text = ""
        cascade_count = 1

        # Один рандом: что выпало?
        event_roll = random.random()
        multicast_chance, zeus_chance, techies_chance = get_event_chances()
        anim_msg = None

        if event_roll < zeus_chance:
            zeus_triggered = True
            await handle_zeus_event(
                context.bot,
                chat_id,
                user,
                user_obj,
                display_username,
                now,
                ZEUS_TEXTS,
                main_menu,
                set_last_bot_message,
                schedule_delete,
                update_fissure,
                update_last_message_id,
                zeus_strike,
                record_recent_fissure_roll
            )
            return

        if event_roll < zeus_chance + techies_chance:
            await handle_techies_event(
                context.bot,
                chat_id,
                user,
                user_obj,
                display_username,
                now,
                main_menu,
                set_last_bot_message,
                schedule_delete,
                update_fissure,
                update_last_message_id,
                context.job_queue,
                record_recent_fissure_roll
            )
            return

        # Остальные события (обычный ролл или мулькаст)
        original_roll = None
        base_roll_before_streak = None  # Сохраняем ролл ДО стрика для вывода

        slot_msg_ids = []

        if event_roll < zeus_chance + techies_chance + multicast_chance:
            # 🎰 МУЛЬТИКАСТ — слоты как в казино
            slot_emojis = ["🍒", "🍋", "🍇", "🔔", "💎"]
            multicast_text = ""
            cascade_count = 1
            slot_msg_ids = []
            is_multicast = True

            # Get base roll first
            roll, special_message, is_fatal, got_help = calculate_fissure_roll(user.get("fissure", 0))
            base_roll_before_streak = roll  # Сохраняем исходный ролл (без стрика)
            current_win_streak = user.get('current_win_streak', 0)
            roll, streak_text = calculate_streak_bonus(current_win_streak, roll)
            # Сохраняем стрик-ролл для мульткаста (стрик входит в расчет)
            streak_roll = roll

            # Проверяем переход на x2 (скрытый рандом 75%)
            if random.random() < 0.75:
                cascade_count = 2
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
                        jackpot_symbol = random.choice(slot_emojis)
                        slots = [jackpot_symbol, jackpot_symbol, jackpot_symbol]

                        msg = await context.bot.send_message(
                            chat_id=update.message.chat_id,
                            text=f"🎰 {' | '.join(slots)} | x4"
                        )
                        slot_msg_ids.append(msg.message_id)
                        await asyncio.sleep(0.5)
                    else:
                        # Не попали в x4 - проигрышный спин и финиш на x3
                        slots = random.sample(slot_emojis, 3)
                        msg = await context.bot.send_message(
                            chat_id=update.message.chat_id,
                            text=f"🎰 {' | '.join(slots)} | x3"
                        )
                        slot_msg_ids.append(msg.message_id)
                        await asyncio.sleep(0.5)
                else:
                    # Не попали в x3 - проигрышный спин и финиш на x2
                    slots = random.sample(slot_emojis, 3)
                    msg = await context.bot.send_message(
                        chat_id=update.message.chat_id,
                        text=f"🎰 {' | '.join(slots)} | x2"
                    )
                    slot_msg_ids.append(msg.message_id)
                    await asyncio.sleep(0.5)
            else:
                # Не попали в x2 - обычный мультикаст x2
                slots = random.sample(slot_emojis, 3)
                msg = await context.bot.send_message(
                    chat_id=update.message.chat_id,
                    text=f"🎰 {' | '.join(slots)} | x2"
                )
                slot_msg_ids.append(msg.message_id)
                await asyncio.sleep(0.5)

            # Сохраняем base_roll как original_roll для отображения
            saved_original_roll = base_roll_before_streak
            roll, original_roll, multicast_text = process_multicast_result(
                streak_roll, cascade_count, MULTICAST_TEXTS
            )
            # Восстанавливаем base_roll для отображения
            original_roll = saved_original_roll
            # Сохраняем значение после применения множителя (до бонуса выходного дня)
            multiplied_roll = roll
            logger.info(f"fissure multicast: roll after multiply={roll}, cascade_count={cascade_count}")
            if cascade_count >= 4:
                pass
            elif cascade_count >= 3:
                pass
            elif cascade_count >= 2:
                pass

        else:
            # 🎲 ОБЫЧНЫЙ РОЛЛ (90%)
            cascade_count = 1
            is_multicast = False
            roll, special_message, is_fatal, got_help = calculate_fissure_roll(user.get("fissure", 0))
            base_roll_before_streak = roll  # Сохраняем исходный ролл
            current_win_streak = user.get('current_win_streak', 0)
            roll, streak_text = calculate_streak_bonus(current_win_streak, roll)
            # Для обычного ролла original_roll = roll со стриком
            original_roll = None  # Сохраняем None чтобы не входить в мультфилияр

        # Даем время slot сообщениям отправиться перед итоговым
        if cascade_count > 1:
            await asyncio.sleep(0.3)

        roll, protection_msg = apply_fissure_protection(user.get("fissure", 0), roll, is_fatal)

        # Displayed roll is the BASE roll (before streak/multicast) so the breakdown
        # below (+streak, xN) always adds up to the actually applied roll.
        display_roll = base_roll_before_streak

        # Weekend bonus applies ONLY to genuine normal rolls. A x1 "miss" slot still
        # goes through the multicast branch, so we exclude it via is_multicast.
        weekend_bonus = ""
        bonus_multiplier = None
        if is_weekend and roll > 0 and not is_fatal and not is_multicast:
            bonus_multiplier = random.choice(WEEKEND_BONUS_MULTIPLIERS)
            roll = roll * bonus_multiplier
            weekend_bonus = f"🎉 ВЫХОДНОЙ! x{bonus_multiplier:.1f} = {roll:.1f} см."

        result_text = get_roll_text(display_roll)

        old_fissure = user.get("fissure", 0)

        # New fissure = current + applied roll. Zeus is handled in a separate branch
        # above and returns early, so it never reaches here.
        base_fissure = max(0.1, user.get("fissure", 0))
        new_fissure = calculate_new_fissure(base_fissure, roll)
        growth = new_fissure - old_fissure

        # Record for website live feed (in-memory only, zero DB cost)
        event = "multicast" if cascade_count > 1 else "roll"
        record_recent_fissure_roll(user_obj.id, username, growth, new_fissure, cascade_count, event_type=event)

        logger.info(f"User {user_obj.id} used fissure. New cooldown: {now}")

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

        # Hero quote is based on the base roll (before streak/multicast)
        extra_text = get_hero_quote(display_roll)

        # Build message parts in order
        parts = []
        parts.append(f"🎲 {display_username}")

        if extra_text:
            parts.append(extra_text)

        parts.append(result_text)

        if streak_text:
            parts.append(streak_text)
        if weekend_bonus:
            parts.append(weekend_bonus)

        # Multicast indicator (only when an actual multiplier happened)
        if cascade_count > 1:
            m_display = f"+{multiplied_roll}" if multiplied_roll > 0 else str(multiplied_roll)
            parts.append(f"⚡ МУЛЬТИКАСТ×{cascade_count} {m_display} см!")

        # Join parts with single blank line between them
        text = "\n\n".join(parts)

        # Add protection message if applicable (separated by single newline)
        if is_fatal and protection_msg:
            text = f"{text}\n{protection_msg}"

        # Add fissure change line (always at the end, preceded by blank line)
        text = f"{text}\n\n📏 {old_fissure:.1f} см → {new_fissure:.1f} см"

        # Add Zeus text if applicable (separated by single newline)
        if zeus_text:
            text = f"{text}\n{zeus_text}"

        logger.info(f"Sending result message to chat_id={update.message.chat_id}")

        # Шапка: старая для обычных, новая для мультикаста
        if cascade_count > 1:
            # Баннер для мультикаста
            roll_banner_url = get_banner_path("roll_fatal")
        else:
            roll_banner_url = get_banner_path("roll_normal")

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
            if anim_msg:
                try:
                    await anim_msg.edit_text(text=text, parse_mode="HTML", reply_markup=main_menu())
                    result_msg = anim_msg
                except Exception as edit_error:
                    logger.debug(f"Could not edit anim_msg: {edit_error}")
                    result_msg = await context.bot.send_message(
                        chat_id=update.message.chat_id, text=text,
                        parse_mode="HTML", reply_markup=main_menu()
                    )
            else:
                result_msg = await context.bot.send_message(
                    chat_id=update.message.chat_id, text=text,
                    parse_mode="HTML", reply_markup=main_menu()
                )

        logger.info(f"Result message sent successfully: message_id={result_msg.message_id}")
        set_last_bot_message(chat_id, user_obj.id, result_msg.message_id)
        # ВСЕГДА удаляем сообщение через 30 секунд во всех чатах
        schedule_delete(context.bot, chat_id, result_msg.message_id, 30, context.job_queue)

        # Small delay to ensure message is visible before any further processing
        await asyncio.sleep(0.1)

        # Удаляем анимационные сообщения слотов
        if slot_msg_ids:
            await asyncio.sleep(0.2)
            for msg_id in slot_msg_ids:
                schedule_delete(context.bot, chat_id, msg_id, 30, context.job_queue)

        # Сохраняем fissure + last_message_id одним запросом
        update_fissure(user_obj.id, new_fissure, now, growth, last_message_id=result_msg.message_id)

        # Инвалидируем кеш дайджеста чтобы следующий job показал свежие данные
        invalidate_digest_cache()

        # Мгновенный (дебаунснутый) апдейт закреплённого дайджеста сразу после ролла
        try:
            from digest import schedule_instant_digest_refresh
            schedule_instant_digest_refresh(context)
        except Exception:
            pass

    except Exception as e:
        tb = traceback.format_exc()
        logger.error(f"Error in fissure: {e}\n{tb}")
        try:
            msg = await context.bot.send_message(
                chat_id=chat_id,
                text=f"❌ Ошибка обработки запроса\n<code>{e}</code>",
                parse_mode="HTML"
            )
            schedule_delete(context.bot, chat_id, msg.message_id, 30, context.job_queue)
        except Exception:
            pass
    finally:
        _user_fissure_processing.pop(user_obj.id, None)
