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
    schedule_delete,
    set_last_bot_message,
)
from constants import (
    COOLDOWN,
    WEEKEND_BONUS_MULTIPLIERS,
    ZEUS_TEXTS,
    get_banner_path,
    get_random_cooldown_banner_path,
)
from database import (
    consume_free_roll,
    consume_item,
    get_fissure_rank,
    get_free_rolls,
    get_user,
    update_fissure,
    update_last_message_id,
    update_user_field,
    user_cache,
    zeus_strike,
)
from digest import invalidate_digest_cache
from rate_limiter import is_rate_limited, rate_limit
from roshan import handle_roshan_event
from rolls import (
    MULTICAST_TEXTS,
    apply_aegis,
    apply_cheese,
    apply_fissure_protection,
    calculate_fissure_roll,
    calculate_new_fissure,
    calculate_streak_bonus,
    get_hero_quote,
    get_roll_text,
)
from stats import get_event_chances, get_roshan_chance
from techies import handle_techies_event

# Fissure-specific in-memory state (moved from main.py for clean extraction)
_user_fissure_processing: dict[int, float] = {}

# Minimum seconds between consecutive /fissure calls from the same user.
# Prevents double-click spam: two rolls within this window are treated as
# the same action, and the second one is ignored.
MIN_SPAM_INTERVAL = 3.0


logger = logging.getLogger(__name__)


# Compatibility hooks for older integrations/tests. The production roll
# balancer is currently stateless; keeping these no-op symbols avoids breaking
# external code that used to import them from this module.
def init_global_stats() -> None:
    return None


def record_player_roll(*args, **kwargs) -> None:
    return None


def update_global_stats_on_event(*args, **kwargs) -> None:
    return None


def maybe_persist_global_stats(*args, **kwargs) -> None:
    return None


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
    # Delete user message only in groups/channels (not in private).
    # user_msg_id may be 0 when the roll is triggered from an inline button
    # (no real user message) — skip the API call in that case.
    if chat_type in ['group', 'supergroup', 'channel'] and user_msg_id:
        can_delete = await bot_can_delete(bot, chat_id)
        delete_tasks = []
        if can_delete:
            delete_tasks.append(_safe_delete_user_msg(bot, chat_id, user_msg_id))
        delete_tasks.append(delete_last_bot_message(bot, chat_id, user_id))
        if delete_tasks:
            await asyncio.gather(*delete_tasks, return_exceptions=True)

    return


async def _safe_delete_user_msg(bot, chat_id, user_msg_id):
    try:
        await bot.delete_message(chat_id, user_msg_id)
    except Exception as e:
        logger.debug(f"Could not delete user message: {e}")


def build_fissure_cooldown_bar_and_text(now, last_fissure, COOLDOWN, format_time):
    """Pure function to build the cooldown progress bar and text. Logic unchanged."""
    wait = COOLDOWN - (now - (last_fissure or 0))
    elapsed = COOLDOWN - wait
    filled = int(elapsed / COOLDOWN * 10)
    bar = "🟩" * filled + "⬜️" * (10 - filled)
    text = f"🧬 Восстанавливается. {format_time(wait)}\n{bar}"
    return text


def should_skip_due_to_spam(user_id, now, processing_dict):
    """Returns True if the user is already being processed (spam protection).

    Uses a sliding window: if the last call for this user was less than
    MIN_SPAM_INTERVAL seconds ago, skip. Otherwise allow and update the
    timestamp. Unlike the previous implementation, the entry is never
    removed — it just ages, so rapid double-clicks are blocked even when
    the first handler has already finished.
    """
    last_call = processing_dict.get(user_id)
    if last_call is not None and (now - last_call) < MIN_SPAM_INTERVAL:
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
    Handles the Zeus strike event (no roll, dynamic % to all fissures).
    Logic and all messages are 100% preserved from the original.
    """
    # zeus_strike now returns (affected, total_cm_reduced, total_fissure_before)
    affected, total_cm, total_fissure_before = zeus_strike(percent=0.01, exclude_telegram_id=user_obj.id)

    user = await asyncio.to_thread(get_user, user_obj.id, user_obj.username)
    new_fissure = user.get("fissure", 0)

    # Real percentage: how much of the total community fissure was actually taken
    real_percent = (total_cm / total_fissure_before * 100) if total_fissure_before > 0 else 1.0

    # Return ALL the stolen fissure to the initiator (they were excluded from the strike)
    initiator_gain = round(total_cm, 1)
    if initiator_gain > 0:
        initiator_new = max(0.1, new_fissure + initiator_gain)
        await asyncio.to_thread(update_user_field, user_obj.id, "fissure", initiator_new)
        user = await asyncio.to_thread(get_user, user_obj.id, user_obj.username)
        new_fissure = initiator_new

    zeus_text = random.choice(ZEUS_TEXTS)

    text = (
        f"🎲 {display_username}\n\n"
        f"{zeus_text}\n\n"
        f"💀 Все Фиссуры −{real_percent:.2f}%, {affected} жертв.\n"
        f"📉 Суммарно отнято: {total_cm} см\n"
        f"🎁 Ты не пострадал, тебе вернули {initiator_gain:.1f} см!\n\n"
        f"📏 {new_fissure:.1f} см"
    )

    zeus_banner_url = get_banner_path("zeus")
    result_msg = None
    if zeus_banner_url:
        try:
            result_msg = await bot.send_photo(
                chat_id=chat_id,
                photo=zeus_banner_url,
                caption=text,
                parse_mode="HTML",
                reply_markup=main_menu(),
            )
        except Exception as e:
            # Do not let a Telegram hiccup swallow the event: fall back to text
            # below and keep the strike results in the chat.
            logger.warning(f"zeus: banner send failed ({e}), falling back to text")
    if result_msg is None:
        result_msg = await bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode="HTML",
            reply_markup=main_menu(),
        )
    if record_recent_fissure_roll:
        record_recent_fissure_roll(user_obj.id, user_obj.username, initiator_gain, new_fissure, cascade=0, event_type="zeus")

    set_last_bot_message(chat_id, user_obj.id, result_msg.message_id)
    schedule_delete(bot, chat_id, result_msg.message_id, 600, None)  # job_queue passed from caller if needed
    update_fissure(user_obj.id, new_fissure, now, 0, last_message_id=result_msg.message_id)

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

@rate_limit(tokens=1)
async def fissure(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Increase fissure"""
    msg = update.effective_message
    logger.info(f" fissure CALLED user={update.effective_user.id} chat={update.effective_chat.id} text={msg.text if msg else 'no_message'}")

    user_obj = update.effective_user
    username = user_obj.username
    display_username = make_clickable(username or user_obj.first_name or "Игрок", user_obj.id)
    chat_id = msg.chat_id if msg else update.effective_chat.id
    chat_type = msg.chat.type if msg else 'private'
    user_msg_id = msg.message_id if msg else 0
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
        user = await asyncio.to_thread(get_user, user_obj.id, username)
        _safe_user = {k: v for k, v in user.items() if k not in ("analytics_cache", "steam_id", "steam_nickname", "username", "first_name", "last_name")}
        logger.info(f"user data: {_safe_user}")

        # Check cooldown (skip if free_rolls available — bonus from Techies)
        free_rolls = get_free_rolls(user_obj.id)
        last_f = user.get("last_fissure") or 0
        cooldown_diff = now - last_f
        if cooldown_diff < COOLDOWN and free_rolls <= 0:
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

        # Consume one free_roll if available (bonus from Techies/Refresher)
        used_free_roll = False
        if free_rolls > 0:
            consume_free_roll(user_obj.id)
            used_free_roll = True
            logger.info(f"fissure: consumed free_roll for user {user_obj.id}, remaining={free_rolls - 1}")

        multicast_text = ""
        original_roll = None
        zeus_triggered = False
        zeus_text = ""
        cascade_count = 1

        # Один бросок на все уникальные роллы: Рошан, Зевс, Техиес, мультикаст
        # стоят в одной шкале друг за другом и у всех шанс одинаковый — по 10%.
        # Раньше Рошан катался отдельным броском и выходил раньше всех, из-за
        # чего шансы остальных событий нельзя было прочитать по одному числу.
        event_roll = random.random()
        multicast_chance, zeus_chance, techies_chance = get_event_chances()
        roshan_end = get_roshan_chance()
        zeus_end = roshan_end + zeus_chance
        techies_end = zeus_end + techies_chance
        multicast_end = techies_end + multicast_chance

        if event_roll < roshan_end:
            await handle_roshan_event(
                context.bot,
                chat_id,
                user,
                user_obj,
                display_username,
                now,
                update_fissure,
                set_last_bot_message,
                schedule_delete,
                context.job_queue,
                record_recent_fissure_roll,
            )
            return

        if event_roll < zeus_end:
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

        if event_roll < techies_end:
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

        is_multicast = event_roll < multicast_end

        if is_multicast:
            # 🎰 МУЛЬТИКАСТ — счётчик множителя, без сообщений со слотами
            multicast_text = ""
            cascade_count = 1

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

                # Проверяем переход на x3 (скрытый рандом 25%)
                if random.random() < 0.25:
                    cascade_count = 3

                    # Проверяем переход на x4 (скрытый рандом 15%)
                    if random.random() < 0.15:
                        cascade_count = 4
            # иначе остаётся x1: мисс-слот без множителя. Weekend-бонус к нему
            # не применяется — для этого и нужна проверка `not is_multicast` ниже.

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

        else:
            # 🎲 ОБЫЧНЫЙ РОЛЛ (90%)
            cascade_count = 1
            roll, special_message, is_fatal, got_help = calculate_fissure_roll(user.get("fissure", 0))
            base_roll_before_streak = roll  # Сохраняем исходный ролл
            current_win_streak = user.get('current_win_streak', 0)
            roll, streak_text = calculate_streak_bonus(current_win_streak, roll)
            # Для обычного ролла original_roll = roll со стриком
            original_roll = None  # Сохраняем None чтобы не входить в мультфилияр

        # 💎 АЕГИС гасит минус ролл. Применяется до пересчёта фатальности,
        # поэтому предмет спасает и от фатального удара; при срабатывании
        # is_fatal сбрасывается, иначе текст называл бы фатальным нулевой ролл.
        aegis_text = ""
        
        if roll < 0:
            consumed = await asyncio.to_thread(consume_item, user_obj.id, "aegis")
            if consumed:
                roll, _, aegis_text = apply_aegis(roll)
                is_fatal = False
                got_help = False
                logger.info(f"fissure: aegis absorbed roll for {user_obj.id}")

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

        # 🧀 СЫР умножает положительный ролл. Ставится после стрика, выходного
        # множителя и мультикаста, но до calculate_new_fissure — так x1.5
        # попадёт и в новую фиссуру, и в показанный переход «📏», и они
        # будут сходиться (это главный класс багов в этом модуле).
        cheese_text = ""
        if roll > 0 and not is_fatal:
            consumed_cheese = await asyncio.to_thread(consume_item, user_obj.id, "cheese")
            if consumed_cheese:
                roll, _, cheese_text = apply_cheese(roll)
                is_fatal = False
                logger.info(f"fissure: cheese boosted roll for {user_obj.id}")

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

        # Hero quote is only for normal rolls (not multicast)
        if cascade_count > 1:
            extra_text = ""
        else:
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

        # Multicast text (the hero quote from MULTICAST_TEXTS)
        if multicast_text:
            parts.append(multicast_text)

        # Multicast indicator (only when an actual multiplier happened)
        if cascade_count > 1:
            m_display = f"+{multiplied_roll}" if multiplied_roll > 0 else str(multiplied_roll)
            parts.append(f"МУЛЬТИКАСТ×{cascade_count} {m_display} см!")

        if aegis_text:
            parts.append(aegis_text)
        if cheese_text:
            parts.append(cheese_text)

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

        logger.info(f"Sending result message to chat_id={chat_id}")

        # Шапка: старая для обычных, новая для мультикаста
        if cascade_count > 1:
            # Баннер для мультикаста
            roll_banner_url = get_banner_path("multicast")
        else:
            roll_banner_url = get_banner_path("roll_normal")

        result_msg = None
        if roll_banner_url:
            try:
                result_msg = await context.bot.send_photo(
                    chat_id=chat_id,
                    photo=roll_banner_url,
                    caption=text,
                    parse_mode="HTML",
                    reply_markup=main_menu(),
                )
            except Exception as e:
                # Leave result_msg as None so the fallback below still delivers
                # the roll text instead of the handler ending with an error.
                logger.warning(f"fissure: roll banner send failed ({e}), falling back")

        if result_msg is None:
            # Баннер не отправился: шлём результат обычным сообщением, чтобы
            # ролл не пропал молча.
            try:
                if roll_banner_url:
                    result_msg = await context.bot.send_photo(
                        chat_id=chat_id,
                        photo=roll_banner_url,
                        caption=text,
                        parse_mode="HTML",
                        reply_markup=main_menu()
                    )
                else:
                    result_msg = await context.bot.send_message(
                        chat_id=chat_id,
                        text=text,
                        parse_mode="HTML",
                        reply_markup=main_menu()
                    )
            except Exception as e:
                logger.debug(f"Could not send roll banner: {e}")
                result_msg = await context.bot.send_message(
                    chat_id=chat_id, text=text,
                    parse_mode="HTML", reply_markup=main_menu()
                )

        add_bot_message(chat_id, user_obj.id, result_msg.message_id)

        logger.info(f"Result message sent successfully: message_id={result_msg.message_id}")
        set_last_bot_message(chat_id, user_obj.id, result_msg.message_id)
        # ВСЕГДА удаляем сообщение через 30 секунд во всех чатах
        schedule_delete(context.bot, chat_id, result_msg.message_id, 30, context.job_queue)

        # Fissure write is synchronous (psycopg2/sqlite), so keep it off the
        # event loop. This is especially important because the roll handler
        # continues with live tag reconciliation and digest scheduling.
        # Free rolls (from Refresher/Techies) do NOT update last_fissure timer
        update_timestamp = last_f if used_free_roll else now
        await asyncio.to_thread(
            update_fissure,
            user_obj.id,
            new_fissure,
            update_timestamp,
            growth,
            last_message_id=result_msg.message_id,
        )

        # Инвалидируем кеш дайджеста чтобы следующий job показал свежие данные
        invalidate_digest_cache()

        # Live F1/F2/F3 reconciliation. Only top-15 users can change the tag
        # set, so avoid a burst of Telegram API calls for everyone else.
        try:
            rank_result = await asyncio.to_thread(get_fissure_rank, user_obj.id)
            live_rank = (
                rank_result.get('rank')
                if isinstance(rank_result, dict)
                else rank_result
            )
            # Refresh both when entering top-15 and when a current holder falls
            # out of it, otherwise a stale F1/F2/F3 would survive until the
            # 30-minute reconciliation job.
            try:
                from database import get_config
                current_holders = {
                    str(value) for value in (
                        get_config('current_F1_telegram_id'),
                        get_config('current_F2_telegram_id'),
                        *filter(None, (get_config('current_F3_telegram_ids') or '').split(',')),
                    ) if value
                }
                should_refresh = (
                    live_rank is not None and 1 <= int(live_rank) <= 15
                ) or str(user_obj.id) in current_holders
                if should_refresh:
                    from tags import refresh_fissure_top_tags
                    await refresh_fissure_top_tags(context.bot)
                    logger.info(
                        f"Live Fissure tags refreshed after roll by user={user_obj.id} rank={live_rank}"
                    )
            except Exception as e:
                # The 30-minute reconciler will retry if Telegram/DB is temporarily down.
                logger.warning(f"Live Fissure tag refresh skipped after roll: {e}")
        except Exception as e:
            logger.warning(f"Live Fissure rank check failed after roll: {e}")

        # Мгновенный (дебаунснутый) апдейт закреплённого дайджеста сразу после ролла
        try:
            from digest import schedule_instant_digest_refresh
            schedule_instant_digest_refresh(context)
        except Exception as e:
            logger.debug(f"Could not schedule instant digest refresh: {e}")

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
        except Exception as send_err:
            logger.debug(f"fissure: could not send error message: {send_err}")
    # No finally cleanup — should_skip_due_to_spam uses a sliding window
    # (MIN_SPAM_INTERVAL) so the entry just ages naturally.
