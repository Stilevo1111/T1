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


def award(telegram_id: int, key: str) -> bool:
    """Поставить достижение пользователю. True — только что выдано."""
    if key not in ACHIEVEMENTS:
        return False
    from database import Database, get_db_type, get_user, user_cache

    with _award_lock:
        user = get_user(telegram_id)
        if not user:
            return False

        raw = user.get("achievements") or "{}"
        try:
            achieved = json.loads(raw) if isinstance(raw, str) else (raw or {})
        except Exception:
            achieved = {}

        if achieved.get(key):
            return False

        achieved[key] = 1
        serialized = json.dumps(achieved, ensure_ascii=False)

        # 1. Update in-memory user objects and cache
        user["achievements"] = serialized
        user_cache.set(telegram_id, user)
        user_cache.mark_dirty(telegram_id)

        # 2. Persist directly to DB to avoid overwrite races
        try:
            db = Database()
            scheme = get_db_type()
            placeholder = "%s" if "postgres" in scheme else "?"
            db.execute_query(
                f"UPDATE users SET achievements = {placeholder} WHERE telegram_id = {placeholder}",
                (serialized, telegram_id)
            )
        except Exception as e:
            logger.error(f"award: failed to persist achievements for {telegram_id}: {e}")

        return True


def check_and_award(telegram_id: int, metric: str, new_value: int) -> list[str]:
    """Проверить пороги достижений для метрики и выдать новые."""
    new: list[str] = []
    with _award_lock:
        from database import Database, get_db_type, get_user, user_cache

        user = get_user(telegram_id)
        if not user:
            return []

        raw = user.get("achievements") or "{}"
        try:
            achieved = json.loads(raw) if isinstance(raw, str) else (raw or {})
        except Exception:
            achieved = {}

        for key, spec in ACHIEVEMENTS.items():
            if spec["metric"] != metric:
                continue
            if new_value >= spec["target"]:
                if not achieved.get(key):
                    achieved[key] = 1
                    new.append(key)

        if not new:
            return []

        serialized = json.dumps(achieved, ensure_ascii=False)
        user["achievements"] = serialized
        user_cache.set(telegram_id, user)
        user_cache.mark_dirty(telegram_id)

        try:
            db = Database()
            scheme = get_db_type()
            placeholder = "%s" if "postgres" in scheme else "?"
            db.execute_query(
                f"UPDATE users SET achievements = {placeholder} WHERE telegram_id = {placeholder}",
                (serialized, telegram_id)
            )
        except Exception as e:
            logger.error(f"check_and_award: failed to persist achievements for {telegram_id}: {e}")

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
