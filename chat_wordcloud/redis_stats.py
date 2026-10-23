"""Redis-backed word statistics for /story.

Instead of scanning up to 10 000 chat_messages rows on every /story call, we
maintain per-word counters in Redis sorted sets:

    ZINCRBY wc:words:{chat_id}:{YYYY-MM} {word} 1

on every incoming message, and read the top words with ZREVRANGE. A background
job flushes Redis into PostgreSQL (table ``chat_word_stats``) so counts survive
restarts.
"""
from __future__ import annotations

import asyncio
import datetime as _dt
import logging
import re
from collections import Counter
from typing import Optional

from cache import cache as redis_cache

logger = logging.getLogger(__name__)

# Redis key template: wc:words:{chat_id}:{YYYY-MM}
REDIS_WORD_KEY = "wc:words:{chat_id}:{month}"

# Token pattern mirrors chat_wordcloud.processor.normalize_text/filter_words
_WORD_RE = re.compile(r"[а-яёa-z0-9_+/*]+", re.IGNORECASE)
_STAR_TOKENS = {"**", "*"}


def _month_key(chat_id: int, when: Optional[_dt.datetime] = None) -> str:
    when = when or _dt.datetime.now()
    return REDIS_WORD_KEY.format(chat_id=chat_id, month=when.strftime("%Y-%m"))


def _redis_client():
    """Return the raw redis client, or None if Redis is unavailable."""
    try:
        client = redis_cache.client
        if client is None:
            return None
        return client
    except Exception:
        return None


async def increment_message_words(chat_id: int, text: str) -> None:
    """Increment per-word counters for a single incoming message.

    Safe to call from the message handler: failures are logged and swallowed so
    a Redis outage never breaks chat.
    """
    client = _redis_client()
    if client is None or not text:
        return

    month = _dt.datetime.now().strftime("%Y-%m")
    key = REDIS_WORD_KEY.format(chat_id=chat_id, month=month)

    words = _WORD_RE.findall(text.lower())
    if not words:
        return

    pipe = client.pipeline()
    for w in words:
        if len(w) < 2 or len(w) > 20:
            continue
        if w in _STAR_TOKENS or w.startswith("/") or w.isdigit():
            continue
        pipe.zincrby(key, 1, w)
    try:
        await asyncio.wait_for(pipe.execute(), timeout=3.0)
    except Exception as exc:
        logger.debug(f"redis word stats increment failed for chat {chat_id}: {exc}")


async def get_top_words_from_redis(
    chat_id: int,
    month_start: _dt.datetime,
    month_end: _dt.datetime,
    limit: int = 120,
) -> Counter:
    """Read aggregated top words for a month range from Redis.

    Returns a Counter {word: count}. Falls back to an empty Counter on any
    Redis error so callers can degrade to the DB path.
    """
    client = _redis_client()
    if client is None:
        return Counter()

    result: Counter = Counter()
    months = set()
    cursor = month_start.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    end = month_end
    while cursor <= end:
        months.add(cursor.strftime("%Y-%m"))
        if cursor.month == 12:
            cursor = cursor.replace(year=cursor.year + 1, month=1)
        else:
            cursor = cursor.replace(month=cursor.month + 1)

    for month in months:
        key = REDIS_WORD_KEY.format(chat_id=chat_id, month=month)
        try:
            top = await asyncio.wait_for(
                client.zrevrange(key, 0, limit - 1, withscores=True), timeout=3.0
            )
        except Exception as exc:
            logger.debug(f"redis zrevrange failed for {key}: {exc}")
            continue
        for member, score in top:
            try:
                word = member.decode() if isinstance(member, bytes) else str(member)
            except Exception:
                continue
            result[word] += int(score)

    return result


async def sync_redis_to_postgres() -> int:
    """Flush Redis word counters into PostgreSQL ``chat_word_stats``.

    Returns the number of (chat_id, word, month) rows upserted. Safe to run as
    a recurring JobQueue task (async callback).
    """
    from database import get_connection, release_connection, get_db_type  # noqa: PLC0415

    client = _redis_client()
    if client is None:
        return 0

    is_pg = False
    try:
        is_pg = get_db_type() == "postgresql"
    except Exception:
        pass

    conn = None
    upserted = 0
    try:
        conn = await asyncio.to_thread(get_connection)
        cursor = conn.cursor()

        cursor_ = 0
        while True:
            cursor_, keys = await asyncio.wait_for(
                client.scan(cursor=cursor_, match="wc:words:*", count=500), timeout=5.0
            )
            for key in keys:
                k = key.decode() if isinstance(key, bytes) else str(key)
                parts = k.split(":")
                if len(parts) != 4:
                    continue
                _, _, chat_id_s, month = parts
                try:
                    chat_id = int(chat_id_s)
                except ValueError:
                    continue

                try:
                    members = await asyncio.wait_for(
                        client.zrevrange(k, 0, -1, withscores=True), timeout=5.0
                    )
                except Exception as exc:
                    logger.debug(f"redis zrevrange failed for {k}: {exc}")
                    continue

                for member, score in members:
                    word = member.decode() if isinstance(member, bytes) else str(member)
                    count = int(score)
                    if is_pg:
                        await asyncio.to_thread(
                            cursor.execute,
                            """
                            INSERT INTO chat_word_stats (chat_id, word, month_start, count, updated_at)
                            VALUES (%s, %s, %s, %s, NOW())
                            ON CONFLICT (chat_id, word, month_start)
                            DO UPDATE SET count = EXCLUDED.count, updated_at = NOW()
                            """,
                            (chat_id, word, f"{month}-01", count),
                        )
                    else:
                        await asyncio.to_thread(
                            cursor.execute,
                            """
                            INSERT INTO chat_word_stats (chat_id, word, month_start, count, updated_at)
                            VALUES (?, ?, ?, ?, datetime('now'))
                            ON CONFLICT(chat_id, word, month_start)
                            DO UPDATE SET count = excluded.count, updated_at = datetime('now')
                            """,
                            (chat_id, word, f"{month}-01", count),
                        )
                    upserted += 1
            if cursor_ == 0:
                break
        await asyncio.to_thread(conn.commit)
    except Exception as exc:
        logger.warning(f"sync_redis_to_postgres failed: {exc}")
        try:
            if conn:
                await asyncio.to_thread(conn.rollback)
        except Exception:
            pass
    finally:
        if conn:
            await asyncio.to_thread(release_connection, conn)
    return upserted
