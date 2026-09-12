"""Telegram handler for /story command."""
import asyncio
import logging
from datetime import datetime, timedelta

from telegram import Update
from telegram.ext import ContextTypes

from bot_utils import schedule_delete
from cache_service import top_cache
from chat_wordcloud.config import (
    WORDCLOUD_CACHE_TTL,
    WORDCLOUD_GENERATION_TIMEOUT,
    WORDCLOUD_MAX_WORDS,
    WORDCLOUD_MESSAGE_LIMIT,
    WORDCLOUD_MIN_WORD_FREQUENCY,
    WORDCLOUD_PERIOD_DAYS,
)
from chat_wordcloud.generator import generate_wordcloud_image
from chat_wordcloud.processor import log_top_words, process_messages
from database import get_chat_messages_for_story

logger = logging.getLogger(__name__)


async def _generate_wordcloud_in_thread(top_words, timeout: int) -> bytes:
    """Run wordcloud generation in a worker thread (no multiprocessing spawn overhead)."""
    return await asyncio.wait_for(
        asyncio.to_thread(generate_wordcloud_image, top_words),
        timeout=timeout,
    )


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
        cache_key = f"story_top_words_{chat_id}_{WORDCLOUD_PERIOD_DAYS}"
        cached = top_cache.get(cache_key)
        if cached is not None:
            logger.info(f"story cache hit chat_id={chat_id}")
            top_words = cached
            messages_loaded = None
            stats = {}
            words_before = 0
            words_after = 0
            unique_words = 0
            words_used = 0
        else:
            logger.info(f"story cache miss chat_id={chat_id}")
            messages, stats = await asyncio.to_thread(
                get_chat_messages_for_story,
                chat_id,
                WORDCLOUD_PERIOD_DAYS,
                WORDCLOUD_MESSAGE_LIMIT,
                bot_user_id,
            )
            messages_loaded = len(messages)
            logger.info(
                f"story messages loaded={messages_loaded} limit={WORDCLOUD_MESSAGE_LIMIT} "
                f"total={stats.get('total_messages')} bot={stats.get('bot_messages')}"
            )

            if not messages:
                await update.message.reply_text("Недостаточно данных для создания истории чата.")
                return

            counter = await asyncio.to_thread(process_messages, messages)
            words_before = len(counter)

            total_words = sum(counter.values())
            if total_words <= 50 or words_before <= 20:
                effective_min = 1
            elif total_words <= 200 or words_before <= 60:
                effective_min = 2
            else:
                effective_min = WORDCLOUD_MIN_WORD_FREQUENCY

            filtered = [(w, c) for w, c in counter.items() if c >= effective_min]
            words_after = len(filtered)
            filtered.sort(key=lambda x: x[1], reverse=True)
            top_words = filtered[:WORDCLOUD_MAX_WORDS]
            unique_words = len(top_words)
            words_used = sum(c for _, c in top_words)

            logger.info(
                f"story chat_id={chat_id} words_before_filtering={words_before} "
                f"words_after_filtering={words_after} unique_words={unique_words} "
                f"words_used={words_used}"
            )

            log_top_words(top_words, f"TOP 20 WORDS chat_id={chat_id}")

            if not top_words:
                await update.message.reply_text("Недостаточно данных для создания истории чата.")
                return

            top_cache.set(cache_key, top_words, ttl=WORDCLOUD_CACHE_TTL)
            logger.info(f"story cached chat_id={chat_id} ttl={WORDCLOUD_CACHE_TTL}")

        top_word = top_words[0][0]
        top_count = top_words[0][1]

        try:
            png_bytes = await _generate_wordcloud_in_thread(
                top_words, WORDCLOUD_GENERATION_TIMEOUT
            )
        except TimeoutError:
            logger.error(
                f"story image generation timed out after {WORDCLOUD_GENERATION_TIMEOUT}s"
            )
            await update.message.reply_text("Генерация истории чата занимает слишком много времени. Попробуйте позже.")
            return
        logger.info("story image generated successfully")

        if messages_loaded is not None:
            messages_text = f"Сообщений: {messages_loaded}"
        else:
            messages_text = f"Сообщений: ≤{WORDCLOUD_MESSAGE_LIMIT} (из кеша)"

        period_end = datetime.now()
        period_start = period_end - timedelta(days=WORDCLOUD_PERIOD_DAYS)

        caption = (
            f"📖 История чата\n"
            f"Период: {period_start.strftime('%d.%m.%Y')} — {period_end.strftime('%d.%m.%Y')}\n"
            f"{messages_text}\n"
            f"Уникальных слов: {unique_words}\n"
            f"Самое популярное слово: {top_word} ({top_count})"
        )

        sent = await context.bot.send_photo(chat_id=chat_id, photo=png_bytes, caption=caption)
        schedule_delete(context.bot, chat_id, sent.message_id, 30, context.job_queue)
    except Exception as e:
        logger.error(f"story error: {e}", exc_info=True)
        await update.message.reply_text("Ошибка генерации истории чата.")