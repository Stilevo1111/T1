"""Telegram handler for /story command."""
import asyncio
import datetime as _dt
import logging
from collections import Counter
from datetime import datetime

from telegram import Update
from telegram.ext import ContextTypes

from bot_utils import schedule_delete
from cache_service import top_cache
from chat_wordcloud.config import (
    WORDCLOUD_ANGLES,
    WORDCLOUD_CACHE_TTL,
    WORDCLOUD_COLOR_RAMP,
    WORDCLOUD_GENERATION_TIMEOUT,
    WORDCLOUD_HUD_BOLD_THRESHOLD,
    WORDCLOUD_HUD_MAX_FONT_SIZE,
    WORDCLOUD_HUD_RELATIVE_SCALING,
    WORDCLOUD_MAX_WORDS,
    WORDCLOUD_MESSAGE_LIMIT,
    WORDCLOUD_PERIOD_DAYS,
    WORDCLOUD_TITLE,
    WORDCLOUD_WORD_PADDING,
)
from chat_wordcloud.curation import (
    diff_periods,
    month_bounds,
    month_bounds_label,
    previous_month_bounds,
)
from chat_wordcloud.generator import generate_wordcloud_image
from chat_wordcloud.hud import generate_hud_wordcloud
from chat_wordcloud.processor import curate_words, log_top_words
from chat_wordcloud.redis_stats import (
    get_top_words_from_redis,
    increment_message_words,
)
from database import get_chat_messages_in_range
from rate_limiter import rate_limit

logger = logging.getLogger(__name__)


async def _generate_wordcloud_in_thread(
    top_words,
    timeout: int,
    *,
    period_label: str = "",
    message_count: int = 0,
    rising_label: str = "",
) -> bytes:
    """Render the card in a worker thread (no multiprocessing spawn overhead).

    Uses the HUD design from :mod:`chat_wordcloud.hud`, which matches the
    weekly analytics card. If it raises for any reason the legacy
    OpenDota-style renderer is used instead, so a failure in the new renderer
    can never leave the command without a picture.
    """
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(
                generate_hud_wordcloud,
                top_words,
                title=WORDCLOUD_TITLE,
                subtitle=period_label,
                footer=rising_label or "БЕЗ ИЗМЕНЕНИЙ В ЭТОМ МЕСЯЦЕ",
                color_ramp=WORDCLOUD_COLOR_RAMP,
                angles=WORDCLOUD_ANGLES,
                max_font_size=WORDCLOUD_HUD_MAX_FONT_SIZE,
                relative_scaling=WORDCLOUD_HUD_RELATIVE_SCALING,
                word_padding=WORDCLOUD_WORD_PADDING,
                bold_threshold=WORDCLOUD_HUD_BOLD_THRESHOLD,
            ),
            timeout=timeout,
        )
    except Exception as exc:
        logger.warning(f"hud wordcloud failed, falling back to legacy: {exc}", exc_info=True)
        return await asyncio.wait_for(
            asyncio.to_thread(
                generate_wordcloud_image,
                top_words,
                period_label=period_label,
                message_count=message_count,
                rising_label=rising_label,
            ),
            timeout=timeout,
        )


async def _collect_monthly_words(chat_id: int, bot_user_id: int | None):
    """Build the card data for the current calendar month.

    Fast path: read pre-aggregated word counters from Redis (populated on every
    incoming message via :func:`increment_message_words`). This avoids scanning
    up to 10 000 ``chat_messages`` rows per /story call.

    Falls back to the original database scan if Redis is unavailable or has no
    data for the chat/month.
    """
    now = _dt.datetime.now()
    start, end = month_bounds(now)
    prev_start, prev_end = previous_month_bounds(now)

    # --- Redis fast path -------------------------------------------------
    try:
        current_counter = await get_top_words_from_redis(
            chat_id, start, end, WORDCLOUD_MAX_WORDS
        )
        previous_counter = await get_top_words_from_redis(
            chat_id, prev_start, prev_end, WORDCLOUD_MAX_WORDS
        )
    except Exception as exc:
        logger.warning(f"redis word stats unavailable, falling back to DB: {exc}")
        current_counter = Counter()
        previous_counter = Counter()

    # Если данных всего одно слово — всё равно показываем его
    if current_counter and len(current_counter) == 1:
        top_words = sorted(
            current_counter.items(), key=lambda x: x[1], reverse=True
        )[: WORDCLOUD_MAX_WORDS]

        rising, fading = [], []
        try:
            rising, fading = diff_periods(
                current_counter,
                previous_counter,
                current_days=(end - start).days,
                previous_days=(prev_end - prev_start).days,
            )
        except Exception as exc:
            logger.warning(f"monthly comparison unavailable: {exc}", exc_info=True)

        stats = {
            "total_messages": 0,
            "user_messages": sum(current_counter.values()),
            "bot_messages": 0,
            "authors": 1,
        }
        return top_words, stats, rising, fading

    if current_counter:
        top_words = sorted(
            current_counter.items(), key=lambda x: x[1], reverse=True
        )[: WORDCLOUD_MAX_WORDS]

        rising, fading = [], []
        try:
            rising, fading = diff_periods(
                current_counter,
                previous_counter,
                current_days=(end - start).days,
                previous_days=(prev_end - prev_start).days,
            )
        except Exception as exc:
            logger.warning(f"monthly comparison unavailable: {exc}", exc_info=True)

        stats = {
            "total_messages": 0,
            "user_messages": sum(current_counter.values()),
            "bot_messages": 0,
            "authors": 0,
        }
        return top_words, stats, rising, fading

    # --- Database fallback -----------------------------------------------
    current, current_stats = await asyncio.to_thread(
        get_chat_messages_in_range,
        chat_id, start, end, WORDCLOUD_MESSAGE_LIMIT, bot_user_id,
    )
    if not current:
        return [], {}, [], current_stats

    top_words = await asyncio.to_thread(curate_words, current, max_words=WORDCLOUD_MAX_WORDS)

    rising, fading = [], []
    try:
        previous, _ = await asyncio.to_thread(
            get_chat_messages_in_range,
            chat_id, prev_start, prev_end, WORDCLOUD_MESSAGE_LIMIT, bot_user_id,
        )
        if previous:
            prev_top = await asyncio.to_thread(
                curate_words, previous, max_words=WORDCLOUD_MAX_WORDS, use_phrases=False
            )
            rising, fading = diff_periods(
                Counter(dict(top_words)),
                Counter(dict(prev_top)),
                current_days=(end - start).days,
                previous_days=(prev_end - prev_start).days,
            )
    except Exception as exc:
        logger.warning(f"monthly comparison unavailable: {exc}", exc_info=True)

    return top_words, current_stats, rising, fading


def _format_rising(rising: list[tuple[str, int]], limit: int = 5) -> str:
    if not rising:
        return ""
    names = ", ".join(word for word, _ in rising[:limit])
    return f"НОВЫЕ В ЭТОМ МЕСЯЦЕ: {names}"


@rate_limit(tokens=1)
async def story_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info("story_command invoked")
    if not update.message or not update.effective_chat:
        return

    chat_id = update.effective_chat.id
    logger.info(f"story requested chat_id={chat_id}")

    try:
        await context.bot.delete_message(chat_id, update.message.message_id)
    except Exception:
        pass

    try:
        bot_user_id = context.bot.id
        now = datetime.now()
        month_key = f"{now.year}-{now.month:02d}"
        cache_key = f"story_monthly_{chat_id}_{month_key}"
        cached = top_cache.get(cache_key)
        rising = []
        if cached is not None:
            logger.info(f"story cache hit chat_id={chat_id} month={month_key}")
            top_words, rising = cached
            # If cached data is empty (no words), notify the user
            if not top_words:
                msg = await context.bot.send_message(
                    chat_id=chat_id,
                    text="Недостаточно данных для создания истории чата.",
                )
                schedule_delete(context.bot, chat_id, msg.message_id, 30, context.job_queue)
                return
            messages_loaded = None
            stats = {}
            unique_words = 0
            words_used = 0
        else:
            logger.info(f"story cache miss chat_id={chat_id} month={month_key}")
            top_words, stats, rising, _fading = await _collect_monthly_words(
                chat_id, bot_user_id
            )
            messages_loaded = stats.get("user_messages", 0)
            logger.info(
                f"story month={month_key} messages={messages_loaded} "
                f"limit={WORDCLOUD_MESSAGE_LIMIT} authors={stats.get('authors')} "
                f"rising={len(rising)}"
            )

            if not top_words:
                # Send a short notification to the user, then remove it automatically
                msg = await context.bot.send_message(
                    chat_id=chat_id,
                    text="Недостаточно данных для создания истории чата.",
                )
                schedule_delete(context.bot, chat_id, msg.message_id, 30, context.job_queue)
                return

            unique_words = len(top_words)
            words_used = sum(c for _, c in top_words)
            logger.info(
                f"story chat_id={chat_id} month={month_key} unique_words={unique_words} "
                f"words_used={words_used} phrases={sum(1 for w, _ in top_words if ' ' in w)}"
            )

            log_top_words(top_words, f"TOP 20 WORDS chat_id={chat_id}")

            top_cache.set(cache_key, (top_words, rising), ttl=WORDCLOUD_CACHE_TTL)
            logger.info(f"story cached chat_id={chat_id} ttl={WORDCLOUD_CACHE_TTL}")

        period_label = f"{month_bounds_label(now)}  ·  {WORDCLOUD_PERIOD_DAYS} дней"
        rising_label = _format_rising(rising)

        # Show a status message so the user knows the bot is working, not frozen.
        # Use send_message directly (not reply_text) — the user's /story message
        # may already be deleted by the time we reach this line, and reply_text
        # raises "Message to be replied not found".
        status_msg = await context.bot.send_message(
            chat_id=chat_id,
            text="🎨 Собираю облако слов чата..."
        )

        try:
            png_bytes = await _generate_wordcloud_in_thread(
                top_words,
                WORDCLOUD_GENERATION_TIMEOUT,
                period_label=period_label,
                message_count=messages_loaded or 0,
                rising_label=rising_label,
            )
        except TimeoutError:
            logger.error(
                f"story image generation timed out after {WORDCLOUD_GENERATION_TIMEOUT}s"
            )
            await status_msg.edit_text("Генерация облака слов занимает слишком много времени. Попробуйте позже.")
            return
        logger.info("story image generated successfully")

        try:
            await context.bot.delete_message(chat_id, status_msg.message_id)
        except Exception:
            pass

        # The image is self-explanatory: it already shows the title, period,
        # top words, message count and the frequency legend, so the photo is
        # sent without a caption to avoid duplicating the same data in text.
        sent = await context.bot.send_photo(
            chat_id=chat_id,
            photo=png_bytes,
        )
        schedule_delete(context.bot, chat_id, sent.message_id, 30, context.job_queue)
    except Exception as e:
        logger.error(f"story error: {e}", exc_info=True)
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text="Ошибка генерации облака слов чата.",
            )
        except Exception:
            pass
