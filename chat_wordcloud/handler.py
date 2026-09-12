"""Telegram handler for /story command."""
import asyncio
import logging
import multiprocessing
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

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
    WORDCLOUD_RESULT_TIMEOUT,
)
from chat_wordcloud.generator import generate_wordcloud_image_process
from chat_wordcloud.processor import log_top_words, process_messages
from database import get_chat_messages_for_story

logger = logging.getLogger(__name__)

_WORDCLOUD_CONTEXT = multiprocessing.get_context("spawn")
_WORDCLOUD_LOCK_ATTRIBUTE = "_fissure_wordcloud_lock"


def _get_wordcloud_lock() -> asyncio.Lock:
    loop = asyncio.get_running_loop()
    lock = getattr(loop, _WORDCLOUD_LOCK_ATTRIBUTE, None)
    if lock is None:
        lock = asyncio.Lock()
        setattr(loop, _WORDCLOUD_LOCK_ATTRIBUTE, lock)
    return lock


def _close_connection(connection) -> None:
    try:
        connection.close()
    except (AttributeError, OSError, ValueError):
        pass


async def _stop_process(process) -> None:
    if process is None:
        return

    try:
        if process.is_alive():
            process.terminate()
            await asyncio.to_thread(process.join, 2)
        if process.is_alive():
            process.kill()
            await asyncio.to_thread(process.join, 2)
    except (AssertionError, OSError, ValueError):
        pass


async def _cleanup_process(process) -> None:
    await _stop_process(process)
    try:
        process.close()
    except (AssertionError, OSError, ValueError):
        pass


async def _generate_wordcloud_in_process(top_words, timeout: int) -> bytes:
    parent_conn, child_conn = _WORDCLOUD_CONTEXT.Pipe(duplex=False)
    process = None

    try:
        with tempfile.TemporaryDirectory(prefix="fissure-wordcloud-") as temp_dir:
            output_path = Path(temp_dir) / "wordcloud.png"
            async with _get_wordcloud_lock():
                try:
                    try:
                        process = _WORDCLOUD_CONTEXT.Process(
                            target=generate_wordcloud_image_process,
                            args=(top_words, str(output_path), child_conn),
                            daemon=True,
                        )
                        process.start()
                    finally:
                        _close_connection(child_conn)

                    if process.pid is None:
                        raise RuntimeError("wordcloud worker failed to start")

                    await asyncio.to_thread(process.join, timeout)

                    if process.is_alive():
                        process.terminate()
                        await asyncio.to_thread(process.join, 2)
                        if process.is_alive():
                            process.kill()
                            await asyncio.to_thread(process.join, 2)
                        raise TimeoutError(f"wordcloud generation timed out after {timeout}s")

                    if process.exitcode != 0:
                        raise RuntimeError(
                            f"wordcloud worker exited unexpectedly (code={process.exitcode})"
                        )
                    if not await asyncio.to_thread(
                        parent_conn.poll, WORDCLOUD_RESULT_TIMEOUT
                    ):
                        raise RuntimeError("wordcloud worker exited without a result")

                    status, payload_path = await asyncio.to_thread(parent_conn.recv)
                    if status != "ok":
                        raise RuntimeError(payload_path)
                    return await asyncio.to_thread(Path(payload_path).read_bytes)
                finally:
                    await _cleanup_process(process)
    finally:
        _close_connection(child_conn)
        _close_connection(parent_conn)


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
            png_bytes = await _generate_wordcloud_in_process(
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
    except FileNotFoundError as e:
        logger.error(f"story missing asset: {e}")
        await update.message.reply_text("Генерация истории чата временно недоступна.")
    except Exception as e:
        logger.error(f"story error: {e}", exc_info=True)
        await update.message.reply_text("Ошибка генерации истории чата.")
