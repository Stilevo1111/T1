"""In-memory word statistics for /story.

Instead of relying on Redis (often unavailable), we keep per-word counters in
process memory and batch-flush them to PostgreSQL table ``chat_word_stats``
on a schedule/graceful shutdown. This avoids writing to DB on every message
and works even if Redis is down.
"""
from __future__ import annotations

import asyncio
import datetime as _dt
import logging
import re
from collections import Counter, defaultdict
from typing import Dict, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# Redis key template kept for compatibility
REDIS_WORD_KEY = "wc:words:{chat_id}:{month}"

# Token pattern mirrors chat_wordcloud.processor.normalize_text/filter_words
_WORD_RE = re.compile(r"[а-яёa-z0-9_+/*]+", re.IGNORECASE)
_STAR_TOKENS = {"**", "*"}

# In-memory storage: (chat_id, month) -> {word: count}
_MEM: Dict[Tuple[int, str], Counter] = defaultdict(Counter)
_DIRTY: Set[Tuple[int, str]] = set()
_MEM_LOCK = asyncio.Lock()


def _month_key_str(chat_id: int, when: Optional[_dt.datetime] = None) -> str:
    when = when or _dt.datetime.now()
    return when.strftime("%Y-%m")


async def increment_message_words(chat_id: int, text: str) -> None:
    """Increment per-word counters for a single incoming message.

    Safe to call from the message handler: failures are logged and swallowed so
    counting never breaks chat. No DB writes per message.
    """
    if not text:
        return

    try:
        month = _month_key_str(chat_id)
        words = _WORD_RE.findall(text.lower())
        if not words:
            return

        updates = []
        for w in words:
            if len(w) < 2 or len(w) > 20:
                continue
            if w in _STAR_TOKENS or w.startswith("/") or w.isdigit():
                continue
            updates.append(w)

        if not updates:
            return

        key = (chat_id, month)
        async with _MEM_LOCK:
            counter = _MEM[key]
            for w in updates:
                counter[w] += 1
            _DIRTY.add(key)
    except Exception as exc:
        logger.debug(f"word stats increment failed for chat {chat_id}: {exc}")


async def get_top_words_from_redis(
    chat_id: int,
    month_start: _dt.datetime,
    month_end: _dt.datetime,
    limit: int = 120,
) -> Counter:
    """Read aggregated top words for a month range from in-memory store.

    Kept name for backward compatibility with existing handler imports.
    Falls back to empty Counter if no data.
    """
    try:
        result: Counter = Counter()
        cursor = month_start.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end = month_end
        months = set()
        while cursor <= end:
            months.add(cursor.strftime("%Y-%m"))
            if cursor.month == 12:
                cursor = cursor.replace(year=cursor.year + 1, month=1)
            else:
                cursor = cursor.replace(month=cursor.month + 1)

        async with _MEM_LOCK:
            for month in months:
                key = (chat_id, month)
                counter = _MEM.get(key)
                if not counter:
                    continue
                # Take top up to limit to avoid copying huge counters
                for word, score in counter.most_common(limit):
                    result[word] += int(score)

        return result
    except Exception as exc:
        logger.debug(f"get_top_words_from_memory failed for chat {chat_id}: {exc}")
        return Counter()


async def flush_memory_to_postgres() -> int:
    """Flush in-memory word counters into PostgreSQL ``chat_word_stats``.

    Batch upsert, one connection. Safe to call from JobQueue or atexit.
    Returns number of (chat_id, word, month) rows upserted.
    """
    from database import get_connection, release_connection, get_db_type  # noqa: PLC0415

    # Snapshot dirty keys
    async with _MEM_LOCK:
        if not _DIRTY:
            return 0
        dirty_snapshot = list(_DIRTY)
        _DIRTY.clear()

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

        for chat_id, month in dirty_snapshot:
            async with _MEM_LOCK:
                counter = _MEM.get((chat_id, month))
                if not counter:
                    continue
                items = list(counter.items())

            # Upsert in chunks to keep transactions reasonable
            chunk_size = 500
            for i in range(0, len(items), chunk_size):
                chunk = items[i : i + chunk_size]
                if is_pg:
                    sql = """
                        INSERT INTO chat_word_stats (chat_id, word, month_start, count, updated_at)
                        VALUES (%s, %s, %s, %s, NOW())
                        ON CONFLICT (chat_id, word, month_start)
                        DO UPDATE SET count = EXCLUDED.count, updated_at = NOW()
                    """
                    params = [(chat_id, word, f"{month}-01", int(count)) for word, count in chunk]
                    await asyncio.to_thread(cursor.executemany, sql, params)
                else:
                    sql = """
                        INSERT INTO chat_word_stats (chat_id, word, month_start, count, updated_at)
                        VALUES (?, ?, ?, ?, datetime('now'))
                        ON CONFLICT(chat_id, word, month_start)
                        DO UPDATE SET count = excluded.count, updated_at = datetime('now')
                    """
                    params = [(chat_id, word, f"{month}-01", int(count)) for word, count in chunk]
                    await asyncio.to_thread(cursor.executemany, sql, params)
                upserted += len(chunk)

        await asyncio.to_thread(conn.commit)
    except Exception as exc:
        logger.warning(f"flush_memory_to_postgres failed: {exc}")
        try:
            if conn:
                await asyncio.to_thread(conn.rollback)
        except Exception:
            pass
    finally:
        if conn:
            await asyncio.to_thread(release_connection, conn)
    return upserted


# Backward compatible aliases
async def sync_redis_to_postgres() -> int:
    """Backward compatible name - flushes in-memory counters to DB."""
    return await flush_memory_to_postgres()


def _redis_client():
    """Deprecated: always returns None (no Redis dependency)."""
    return None
