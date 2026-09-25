"""Достижения за активность в чате (сообщения, стрики).

Хранятся в колонке users.achievements как JSON dict:
    {"ah_msg100": 1, ...}
ключ — id достижения, значение — 1 выдано / 0 не выдано.

Графика к каждому достижению (assets/achievements/<key>.webp) добавляется позже.
"""
from __future__ import annotations

import json
import logging
import threading

logger = logging.getLogger(__name__)

# Пороги для достижений за сообщения: 100 — первая сотня, 20000 — максимум.
MESSAGE_THRESHOLDS = (100, 500, 1000, 5000, 10000, 20000)

ACHIEVEMENTS: dict[str, dict] = {
    **{
        f"ah_msg{t}": {
            "label": f"{t} Сообщений",
            "metric": "message_count",
            "target": t,
            "once": True,
        }
        for t in MESSAGE_THRESHOLDS
    },
}

_AH_COLORS = {
    "ah_msg100":    (255, 215, 0),
    "ah_msg500":    (66, 133, 244),
    "ah_msg1000":   (156, 113, 232),
    "ah_msg5000":   (234, 67, 53),
    "ah_msg10000":  (234, 67, 53),
    "ah_msg20000":  (234, 67, 53),
}

_award_lock = threading.Lock()


def _load_achievements(db, scheme: str, telegram_id: int) -> tuple[dict, str | None]:
    """Read the authoritative achievements straight from the database.

    Returns the parsed dict and the exact stored text, because the write below
    is a compare-and-swap against that text.

    The in-memory user cache cannot be trusted here: a background job may hold
    a snapshot taken before another writer changed the column, so deciding from
    the cache alone let the same badge be handed out again on a later message.
    """
    placeholder = "%s" if "postgres" in scheme else "?"
    row = db.execute_query(
        f"SELECT achievements FROM users WHERE telegram_id = {placeholder}",
        (telegram_id,),
        fetch="one",
    )
    raw = None
    if isinstance(row, dict):
        raw = row.get("achievements")
    elif row:
        raw = row[0]
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else (raw or {})
    except Exception:
        parsed = {}
    if not isinstance(parsed, dict):
        parsed = {}
    return parsed, raw


def _store_if_unchanged(db, scheme: str, telegram_id: int, previous, achieved: dict) -> bool:
    """Compare-and-swap the column. False means someone else wrote first.

    Guarding on the previous value makes the award atomic across processes, so
    a second Render container cannot award the same badge again.
    """
    placeholder = "%s" if "postgres" in scheme else "?"
    serialized = json.dumps(achieved, ensure_ascii=False)
    updated = db.execute_query(
        f"UPDATE users SET achievements = {placeholder} "
        f"WHERE telegram_id = {placeholder} "
        f"AND ((achievements = {placeholder}) "
        f"OR (achievements IS NULL AND {placeholder} IS NULL))",
        (serialized, telegram_id, previous, previous),
    )
    return int(updated or 0) > 0


def _store(telegram_id: int, user: dict, achieved: dict) -> None:
    """Mirror the new column value into the in-memory cache."""
    user["achievements"] = json.dumps(achieved, ensure_ascii=False)
    from database import user_cache

    user_cache.set(telegram_id, user)
    user_cache.mark_dirty(telegram_id)


def award(telegram_id: int, key: str) -> bool:
    """Поставить достижение пользователю. True — только что выдано."""
    if key not in ACHIEVEMENTS:
        return False
    from database import Database, get_db_type, get_user

    with _award_lock:
        user = get_user(telegram_id)
        if not user:
            return False

        db = Database()
        scheme = get_db_type()
        achieved, previous = _load_achievements(db, scheme, telegram_id)

        if achieved.get(key):
            return False

        achieved[key] = 1
        try:
            if not _store_if_unchanged(db, scheme, telegram_id, previous, achieved):
                return False
        except Exception as e:
            logger.error(f"award: failed to persist achievements for {telegram_id}: {e}")
            return False

        _store(telegram_id, user, achieved)
        return True


def check_and_award(telegram_id: int, metric: str, new_value: int) -> list[str]:
    """Проверить пороги достижений для метрики и выдать новые."""
    new: list[str] = []
    with _award_lock:
        from database import Database, get_db_type, get_user

        user = get_user(telegram_id)
        if not user:
            return []

        db = Database()
        scheme = get_db_type()
        achieved, previous = _load_achievements(db, scheme, telegram_id)

        for key, spec in ACHIEVEMENTS.items():
            if spec["metric"] != metric:
                continue
            if new_value >= spec["target"] and not achieved.get(key):
                achieved[key] = 1
                new.append(key)

        if not new:
            return []

        try:
            if not _store_if_unchanged(db, scheme, telegram_id, previous, achieved):
                # Another instance awarded the same badge first.
                logger.info(
                    f"check_and_award: {telegram_id} achievements changed concurrently, "
                    f"not re-awarding {new}"
                )
                return []
        except Exception as e:
            logger.error(f"check_and_award: failed to persist achievements for {telegram_id}: {e}")
            return []

        _store(telegram_id, user, achieved)

    return new


def get_user_achievements(telegram_id: int) -> dict[str, int]:
    """Вернуть dict {key: 1} выданных достижений пользователю."""
    from database import get_user

    user = get_user(telegram_id)
    if not user:
        return {}
    raw = user.get("achievements") or "{}"
    try:
        data = json.loads(raw) if isinstance(raw, str) else (raw or {})
    except Exception:
        data = {}
    return {k: v for k, v in data.items() if k in ACHIEVEMENTS and v}
