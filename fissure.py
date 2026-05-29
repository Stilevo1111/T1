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
    delete_last_bot_message,
    format_time,
    main_menu,
    schedule_delete,
    set_last_bot_message,
)
from constants import (
    COOLDOWN,
    WEEKEND_BONUS_MULTIPLIERS,
    ZEUS_TEXTS,
)
from database import get_user, update_fissure, update_last_message_id, zeus_strike
from rolls import (
    CATEGORY_PHRASES,
    MULTICAST_TEXTS,
    ROLL_MEMES,
    ROLL_TEXTS,
    apply_fissure_protection,
    calculate_fissure_roll,
    calculate_new_fissure,
)
from stats import get_event_chances

# Fissure-specific in-memory state (moved from main.py for clean extraction)
_user_fissure_processing: dict[int, float] = {}

# In-memory ring buffer for last fissure rolls (for website /api/recent-rolls)
# Zero DB writes вЂ” pure RAM, maxlen 50
recent_fissure_rolls = deque(maxlen=50)


def record_recent_fissure_roll(user_id: int, username: str, growth: float, new_fissure: float, cascade: int = 1):
    """Append one fissure roll event to the in-memory ring buffer (no DB write)."""
    recent_fissure_rolls.append({
        "ts": time.time(),
        "user_id": user_id,
        "username": (username or "unknown")[:25],
        "growth": round(growth, 1),
        "fissure": round(new_fissure, 1),
        "cascade": cascade
    })


logger = logging.getLogger(__name__)


# =====================
# HELPER FUNCTIONS (pure, safe to extract)
# =====================

def is_weekend_msk() -> bool:
    """РћРїСЂРµРґРµР»СЏРµС‚, СЏРІР»СЏРµС‚СЃСЏ Р»Рё С‚РµРєСѓС‰РёР№ РґРµРЅСЊ РІС‹С…РѕРґРЅС‹Рј РїРѕ РњРЎРљ (Р±РµР· РёР·РјРµРЅРµРЅРёСЏ Р»РѕРіРёРєРё)."""
    import datetime
    msk_time = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=3)
    return msk_time.weekday() in (5, 6)


async def delete_fissure_user_and_last_messages(bot, chat_id, user_id, user_msg_id, chat_type):
    """
    Р‘РµР·РѕРїР°СЃРЅРѕРµ СѓРґР°Р»РµРЅРёРµ СЃРѕРѕР±С‰РµРЅРёР№ РїРѕР»СЊР·РѕРІР°С‚РµР»СЏ Рё РїРѕСЃР»РµРґРЅРµРіРѕ Р±РѕС‚Р° РїСЂРё /fissure.
    Р›РѕРіРёРєР° РїРѕР»РЅРѕСЃС‚СЊСЋ СЃРѕС…СЂР°РЅРµРЅР° РёР· main.py.
    """
    import asyncio

    from main import bot_can_delete

    # Delete user message only in groups/channels (not in private)
    if chat_type in ['group', 'supergroup', 'channel']:
        if await bot_can_delete(bot, chat_id):
            try:
                await bot.delete_message(chat_id, user_msg_id)
            except Exception:
                # logger is not imported here to keep it minimal; caller can log if needed
                pass

    # Small delay before deleting last bot message to ensure new message can be sent
    await asyncio.sleep(0.2)

    # Delete last bot message immediately
    try:
        await delete_last_bot_message(bot, chat_id, user_id)
    except Exception:
        pass


def build_fissure_cooldown_bar_and_text(now, last_fissure, COOLDOWN, format_time):
    """Pure function to build the cooldown progress bar and text. Logic unchanged."""
    wait = COOLDOWN - (now - (last_fissure or 0))
    elapsed = COOLDOWN - wait
    filled = int(elapsed / COOLDOWN * 10)
    bar = "рџџ©" * filled + "в¬њпёЏ" * (10 - filled)
    text = f"рџ§¬ Р’РѕСЃСЃС‚Р°РЅР°РІР»РёРІР°РµС‚СЃСЏ. {format_time(wait)}\n{bar}"
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


async def handle_zeus_event(bot, chat_id, user, user_obj, display_username, now, ZEUS_TEXTS, main_menu, set_last_bot_message, schedule_delete, update_fissure, update_last_message_id, zeus_strike):
    """
    Handles the Zeus strike event (no roll, -5% to all fissures).
    Logic and all messages are 100% preserved from the original.
    """
    affected = zeus_strike()

    new_fissure = user["fissure"]
    update_fissure(user_obj.id, new_fissure, now, 0)

    zeus_text = random.choice(ZEUS_TEXTS)

    text = (
        f"рџЋІ {display_username}\n\n"
        f"{zeus_text}\n"
        f"<i>Р’СЃРµ С„РёСЃСЃСѓСЂС‹ РїРѕС‚РµСЂСЏР»Рё -5%! ({affected} РёРіСЂРѕРєРѕРІ)</i>\n\n"
        f"рџ“Џ {new_fissure:.1f} СЃРј"
    )

    zeus_banner_url = "https://i.ibb.co/0jg01gWW/Gemini-Generated-Image-wyz68gwyz68gwyz6-1.png"
    result_msg = await bot.send_photo(
        chat_id=chat_id,
        photo=zeus_banner_url,
        caption=text,
        parse_mode="HTML",
        reply_markup=main_menu()
    )
    set_last_bot_message(chat_id, user_obj.id, result_msg.message_id)
    schedule_delete(bot, chat_id, result_msg.message_id, 600, None)  # job_queue passed from caller if needed
    update_fissure(user_obj.id, user["fissure"], now, 0, last_message_id=result_msg.message_id)

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
        multicast_text = f"\n{random.choice(MULTICAST_TEXTS[cascade_count])}"

    return roll, original_roll, multicast_text


# =====================
# MAIN FISSURE HANDLER (extracted from main.py - behavior 100% preserved)
# =====================

async def fissure(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Increase fissure"""
    chat_id = update.message.chat_id
    chat_type = 'private'
    if update.message and update.message.chat:
        chat_type = update.message.chat.type

    # Private chats allowed, groups only if authorized (zero DB queries)
    if chat_type != 'private':
        from main import check_chat_authorized
        if not check_chat_authorized(chat_id):
            if update.message:
                await context.bot.send_message(chat_id=chat_id, text="вљ Нет доступа. Чат не авторизован.")
            return

    logger.info(f"User {update.effective_user.id} called fissure")

    user_obj = update.effective_user
    username = user_obj.username or user_obj.first_name
    chat_id = update.message.chat_id
    chat_type = update.message.chat.type
    user_msg_id = update.message.message_id
    now = time.time()

    # РџСЂРѕРІРµСЂРєР° РЅР° РІС‹С…РѕРґРЅС‹Рµ РїРѕ РњРЎРљ (СЃСѓР±Р±РѕС‚Р° = 5, РІРѕСЃРєСЂРµСЃРµРЅСЊРµ = 6)
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
        user = get_user(user_obj.id, username)
        logger.info(f"user data: {user}")

        # Check cooldown
        if now - (user.get("last_fissure") or 0) < COOLDOWN:
            text = build_fissure_cooldown_bar_and_text(
                now, user.get("last_fissure"), COOLDOWN, format_time
            )
            cooldown_banner_url = "https://i.ibb.co/FkzCZxNG/m-Yqbu.jpg"
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
                context.application.job_queue
            )
            return

        multicast_text = ""
        original_roll = None
        zeus_triggered = False
        zeus_text = ""
        cascade_count = 1
        display_username = f"<a href=\"tg://user?id={user_obj.id}\">{username}</a>"

        # РћРґРёРЅ СЂР°РЅРґРѕРј: С‡С‚Рѕ РІС‹РїР°Р»Рѕ?
        event_roll = random.random()
        multicast_chance, zeus_chance = get_event_chances()
        anim_msg = None

        if event_roll < zeus_chance:
            # вљЎ Р—Р•Р’РЎ вЂ” РѕС‚РґРµР»СЊРЅРѕРµ СЃРѕР±С‹С‚РёРµпјЊР±РµР· СЂРѕР»Р»Р°
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
                zeus_strike
            )
            return  # exit without roll

        # РћСЃС‚Р°Р»СЊРЅС‹Рµ СЃРѕР±С‹С‚РёСЏ (РѕР±С‹С‡РЅС‹Р№ СЂРѕР»Р» РёР»Рё РјСѓР»СЊРєР°СЃС‚)
        roll, special_message, is_fatal, got_help = calculate_fissure_roll(user["fissure"])


        slot_msg_ids = []

        if event_roll < zeus_chance + multicast_chance:
            # рџЋ° РњРЈР›Р¬РўРРљРђРЎРў вЂ” СЃР»РѕС‚С‹ РєР°Рє РІ РєР°Р·РёРЅРѕ
            slot_emojis = ["рџЌ’", "рџЌ‹", "рџЌ‡", "рџ””", "рџ’Ћ"]
            multicast_text = ""
            cascade_count = 1

            # РџСЂРѕРІРµСЂСЏРµРј РїРµСЂРµС…РѕРґ РЅР° x2 (СЃРєСЂС‹С‚С‹Р№ СЂР°РЅРґРѕРј 75%)
            slot_msg_ids = []
            if random.random() < 0.75:
                cascade_count = 2
                # РџРѕРєР°Р·С‹РІР°РµРј РґР¶РµРєРїРѕС‚ (3 РѕРґРёРЅР°РєРѕРІС‹С…) - СЌС‚Рѕ Рё РµСЃС‚СЊ Р°РЅРёРјР°С†РёСЏ x2
                jackpot_symbol = random.choice(slot_emojis)
                slots = [jackpot_symbol, jackpot_symbol, jackpot_symbol]

                msg = await context.bot.send_message(
                    chat_id=update.message.chat_id,
                    text=f"рџЋ° {' | '.join(slots)} | x2"
                )
                slot_msg_ids.append(msg.message_id)
                await asyncio.sleep(1)

                # РџСЂРѕРІРµСЂСЏРµРј РїРµСЂРµС…РѕРґ РЅР° x3 (СЃРєСЂС‹С‚С‹Р№ СЂР°РЅРґРѕРј 25%)
                if random.random() < 0.25:
                    cascade_count = 3
                    # РџРѕРєР°Р·С‹РІР°РµРј РґР¶РµРєРїРѕС‚ - Р°РЅРёРјР°С†РёСЏ x3
                    jackpot_symbol = random.choice(slot_emojis)
                    slots = [jackpot_symbol, jackpot_symbol, jackpot_symbol]

                    msg = await context.bot.send_message(
                        chat_id=update.message.chat_id,
                        text=f"рџЋ° {' | '.join(slots)} | x3"
                    )
                    slot_msg_ids.append(msg.message_id)
                    await asyncio.sleep(1)

                    # РџСЂРѕРІРµСЂСЏРµРј РїРµСЂРµС…РѕРґ РЅР° x4 (СЃРєСЂС‹С‚С‹Р№ СЂР°РЅРґРѕРј 15%)
                    if random.random() < 0.15:
                        cascade_count = 4
                        # РџРѕРєР°Р·С‹РІР°РµРј РґР¶РµРєРїРѕС‚ - Р°РЅРёРјР°С†РёСЏ x4
                        jackpot_symbol = random.choice(slot_emojis)
                        slots = [jackpot_symbol, jackpot_symbol, jackpot_symbol]

                        msg = await context.bot.send_message(
                            chat_id=update.message.chat_id,
                            text=f"рџЋ° {' | '.join(slots)} | x4"
                        )
                        slot_msg_ids.append(msg.message_id)
                        await asyncio.sleep(0.5)
                    else:
                        # РќРµ РїРѕРїР°Р»Рё РІ x4 - РїРѕРєР°Р·С‹РІР°РµРј РїСЂРѕРёРіСЂС‹С€РЅС‹Р№ СЃРїРёРЅ Рё С„РёРЅРёС€ РЅР° x3
                        slots = random.sample(slot_emojis, 3)
                        msg = await context.bot.send_message(
                            chat_id=update.message.chat_id,
                            text=f"рџЋ° {' | '.join(slots)} | x4"
                        )
                        slot_msg_ids.append(msg.message_id)
                        await asyncio.sleep(0.5)
                        cascade_count = 3
                else:
                    # РќРµ РїРѕРїР°Р»Рё РІ x3 - РїРѕРєР°Р·С‹РІР°РµРј РїСЂРѕРёРіСЂС‹С€РЅС‹Р№ СЃРїРёРЅ Рё С„РёРЅРёС€ РЅР° x2
                    slots = random.sample(slot_emojis, 3)
                    msg = await context.bot.send_message(
                        chat_id=update.message.chat_id,
                        text=f"рџЋ° {' | '.join(slots)} | x3"
                    )
                    slot_msg_ids.append(msg.message_id)
                    await asyncio.sleep(0.5)
                    cascade_count = 2
            else:
                # РќРµ РїРѕРїР°Р»Рё РІ x2 - РѕР±С‹С‡РЅС‹Р№ СЂРѕР»Р» (РЅРµ РјСѓР»СЊС‚РёРєР°СЃС‚)
                pass  # multicast_count was dead code, removed safely

            # РЎРѕС…СЂР°РЅСЏРµРј original_roll Р”Рћ СѓРјРЅРѕР¶РµРЅРёСЏ!
            roll, original_roll, multicast_text = process_multicast_result(
                roll, cascade_count, MULTICAST_TEXTS
            )
            logger.info(f"fissure multicast: roll after multiply={roll}, cascade_count={cascade_count}")
            if cascade_count >= 4:
                pass  # Statistics disabled (was: increment_stat("multicast_x4"))
            elif cascade_count >= 3:
                pass  # Statistics disabled (was: increment_stat("multicast_x3"))
            elif cascade_count >= 2:
                pass  # Statistics disabled (was: increment_stat("multicast_x2"))

        else:
            # рџЋІ РћР‘Р«Р§РќР«Р™ Р РћР›Р› (90%)
            pass

        # Р”Р°РµРј РІСЂРµРјСЏ slot СЃРѕРѕР±С‰РµРЅРёСЏРј РѕС‚РїСЂР°РІРёС‚СЊСЃСЏ РїРµСЂРµРґ РёС‚РѕРіРѕРІС‹Рј
        if cascade_count > 1:
            await asyncio.sleep(0.3)

        roll, protection_msg = apply_fissure_protection(user["fissure"], roll, is_fatal)

        # Определяем базовый ролл для текста результата (без учета выходного дня)
        if original_roll is not None:
            base_roll_for_text = original_roll
        else:
            base_roll_for_text = roll

        # Р’С‹С‡РёСЃР»СЏРµРј result_text РЅР° РѕСЃРЅРѕРІРµ Р±Р°Р·РѕРІРѕРіРѕ СЂРѕР»Р»Р°
        roll_key_text = min(base_roll_for_text, 75)
        roll_key_text = max(roll_key_text, -15)
        if roll_key_text in ROLL_TEXTS:
            result_text = random.choice(ROLL_TEXTS[roll_key_text])
        else:
            result_text = f"{'+' if base_roll_for_text > 0 else ''}{base_roll_for_text} СЃРј"

        # Р‘РѕРЅСѓСЃ РґР»СЏ РІС‹С…РѕРґРЅС‹С…: СѓРІРµР»РёС‡РёРІР°РµРј РїРѕР»РѕР¶РёС‚РµР»СЊРЅС‹Р№ СЂРѕР»Р»
        # РќР• РїСЂРёРјРµРЅСЏРµРј РІС‹С…РѕРґРЅРѕР№ Р±РѕРЅСѓСЃ РїСЂРё РјСѓР»СЊС‚РёРєР°СЃС‚Рµ
        if is_weekend and roll > 0 and not is_fatal and cascade_count == 1:
            bonus_multiplier = random.choice(WEEKEND_BONUS_MULTIPLIERS)
            # РџРѕРєР°Р·С‹РІР°РµРј С‚РѕС‡РЅРѕРµ Р·РЅР°С‡РµРЅРёРµ РІ СЃРѕРѕР±С‰РµРЅРёРё, РЅРѕ СЃРѕС…СЂР°РЅСЏРµРј РєР°Рє С†РµР»РѕРµ РґР»СЏ СЂР°СЃС‡РµС‚Р°
            bonus_amount = roll * bonus_multiplier
            roll = int(roll * bonus_multiplier)
            weekend_bonus = f"рџЋ‰ Р’Р«РҐРћР”РќРћР™! x{bonus_multiplier:.1f} = {bonus_amount:.1f} РЎРњ"
        else:
            weekend_bonus = ""

        old_fissure = user["fissure"]

        # РЎС‡РёС‚Р°РµРј РЅРѕРІСѓСЋ С„РёСЃСЃСѓСЂСѓ: Р±Р°Р·Р° - 5% Р—РµРІСЃР° + СЂРѕР»Р» (С„РёСЃСЃСѓСЂС‹ < 5 Р·Р°С‰РёС‰РµРЅС‹ РѕС‚ Р—РµРІСЃР°)
        if zeus_triggered and user["fissure"] >= 5:
            base_fissure = user["fissure"] * 0.95
        else:
            base_fissure = user["fissure"]
        base_fissure = max(0.1, base_fissure)
        new_fissure = calculate_new_fissure(base_fissure, roll)
        growth = new_fissure - old_fissure

        # Record for website live feed (in-memory only, zero DB cost)
        record_recent_fissure_roll(user_obj.id, username, growth, new_fissure, cascade_count)

        logger.info(f"User {user_obj.id} used fissure. New cooldown: {now}")

        # Р’С‹С‡РёСЃР»СЏРµРј roll_key РґР»СЏ С„РёРЅР°Р»СЊРЅРѕРіРѕ Р·РЅР°С‡РµРЅРёСЏ (РёСЃРїРѕР»СЊР·СѓРµС‚СЃСЏ РІ extra_text)
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
            # Р’С‹Р±РёСЂР°РµРј С„СЂР°Р·Сѓ С‚РѕР»СЊРєРѕ РµСЃР»Рё РЅРµС‚ РІС‹С…РѕРґРЅРѕРіРѕ Р±РѕРЅСѓСЃР°, РЅРµС‚ РјСѓР»СЊС‚РёРєР°СЃС‚Р° Рё СЌС‚Рѕ РїРѕР»РѕР¶РёС‚РµР»СЊРЅС‹Р№ СЂРѕР»Р»
            extra_text = random.choice(CATEGORY_PHRASES[category])

        if cascade_count > 1 and original_roll is not None:
            logger.info(f"DEBUG: original_roll={original_roll}, cascade_count={cascade_count}, roll_final={original_roll * cascade_count}")
            mc_level = f"×{cascade_count}"
            # Р РѕР»Р» СѓР¶Рµ СѓРјРЅРѕР¶С‘РЅ, РёСЃРїРѕР»СЊР·СѓРµРј РµРіРѕ РЅР°РїСЂСЏРјСѓСЋ
            roll_final = roll
            text = (
                f"рџЋІ {display_username}\n\n"
                f"{result_text}\n"
                f"{multicast_text}\n"
                f"вљЎ РњРЈР›Р¬РўРРљРђРЎРў{mc_level}  {roll_final} CM"
            )
        else:
            # РЎС‚Р°СЂС‹Р№ РґРёР·Р°Р№РЅ Р±РµР· РјСѓР»СЊС‚РёРєР°СЃС‚Р°
            text = (
                f"рџЋІ {display_username}\n\n"
                f"{result_text}\n"
                f"{extra_text}"
            )

        if is_fatal and protection_msg:
            text = f"{text}\n{protection_msg}"

        if weekend_bonus:
            text = f"{text}\n{weekend_bonus}"

        # РЎС‚СЂРѕС‡РєР° СЃ РёР·РјРµРЅРµРЅРёРµРј С„РёСЃСЃСѓСЂС‹ - Р’РЎР•Р“Р”Рђ Р’ РЎРђРњРћРњ РљРћРќР¦Р•
        text = f"{text}\n\nрџ“Џ {old_fissure:.1f} СЃРј в†’ {new_fissure:.1f} СЃРј"

        if zeus_text:
            text = f"{text}\n{zeus_text}"

        logger.info(f"Sending result message to chat_id={update.message.chat_id}")

        # РЁР°РїРєР°: СЃС‚Р°СЂР°СЏ РґР»СЏ РѕР±С‹С‡РЅС‹С…, РЅРѕРІР°СЏ РґР»СЏ РјСѓР»СЊС‚РёРєР°СЃС‚Р°
        if cascade_count > 1:
            # Р‘Р°РЅРЅРµСЂ РґР»СЏ РјСѓР»СЊС‚РёРєР°СЃС‚Р°
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
        # Р’РЎР•Р“Р”Рђ СѓРґР°Р»СЏРµРј СЃРѕРѕР±С‰РµРЅРёРµ С‡РµСЂРµР· 30 СЃРµРєСѓРЅРґ РІРѕ РІСЃРµС… С‡Р°С‚Р°С…
        schedule_delete(context.bot, chat_id, result_msg.message_id, 30, context.application.job_queue)

        # Small delay to ensure message is visible before any further processing
        await asyncio.sleep(0.1)

        # РЈРґР°Р»СЏРµРј Р°РЅРёРјР°С†РёРѕРЅРЅС‹Рµ СЃРѕРѕР±С‰РµРЅРёСЏ СЃР»РѕС‚РѕРІ
        if slot_msg_ids:
            await asyncio.sleep(0.2)
            for msg_id in slot_msg_ids:
                schedule_delete(context.bot, chat_id, msg_id, 30, context.application.job_queue)

        # РЎРѕС…СЂР°РЅСЏРµРј fissure + last_message_id РѕРґРЅРёРј Р·Р°РїСЂРѕСЃРѕРј
        update_fissure(user_obj.id, new_fissure, now, growth, last_message_id=result_msg.message_id)

    except Exception as e:
        tb = traceback.format_exc()
        logger.error(f"Error in fissure: {e}\n{tb}")
        try:
            msg = await context.bot.send_message(
                chat_id=chat_id,
                text=f"вќЊ РћС€РёР±РєР° РѕР±СЂР°Р±РѕС‚РєРё Р·Р°РїСЂРѕСЃР°\n<code>{e}</code>",
                parse_mode="HTML"
            )
            schedule_delete(context.bot, chat_id, msg.message_id, 30, context.application.job_queue)
        except Exception:
            pass
    finally:
        _user_fissure_processing.pop(user_obj.id, None)
