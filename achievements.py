"""Р”РѕСЃС‚РёР¶РµРЅРёСЏ Р·Р° Р°РєС‚РёРІРЅРѕСЃС‚СЊ РІ С‡Р°С‚Рµ (СЃРѕРѕР±С‰РµРЅРёСЏ, СЃС‚СЂРёРєРё).

РҐСЂР°РЅСЏС‚СЃСЏ РІ РєРѕР»РѕРЅРєРµ ``users.achievements`` РєР°Рє JSON dict:
    {"ah_msg100": 1, ...}
РєР»СЋС‡ вЂ” id РґРѕСЃС‚РёР¶РµРЅРёСЏ, Р·РЅР°С‡РµРЅРёРµ вЂ” 1 РІС‹РґР°РЅРѕ / 0 РЅРµ РІС‹РґР°РЅРѕ.

Р“СЂР°С„РёРєР° Рє РєР°Р¶РґРѕРјСѓ РґРѕСЃС‚РёР¶РµРЅРёСЋ (assets/achievements/<key>.webp) РґРѕР±Р°РІР»СЏРµС‚СЃСЏ РїРѕР·Р¶Рµ.
"""
from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)

# РџРѕСЂРѕРіРё РґР»СЏ РґРѕСЃС‚РёР¶РµРЅРёР№ Р·Р° СЃРѕРѕР±С‰РµРЅРёСЏ: 100 вЂ” РїРµСЂРІР°СЏ СЃРѕС‚РЅСЏ, 20000 вЂ” РјР°РєСЃРёРјСѓРј.
MESSAGE_THRESHOLDS = (100, 500, 1000, 5000, 10000, 20000)

ACHIEVEMENTS: dict[str, dict] = {
    **{
        f"ah_msg{t}": {
            "label": f"Сообщения {t}",
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


def award(telegram_id: int, key: str) -> bool:
    """РџРѕСЃС‚Р°РІРёС‚СЊ РґРѕСЃС‚РёР¶РµРЅРёРµ РїРѕР»СЊР·РѕРІР°С‚РµР»СЋ. True вЂ” С‚РѕР»СЊРєРѕ С‡С‚Рѕ РІС‹РґР°РЅРѕ."""
    if key not in ACHIEVEMENTS:
        return False
    from database import get_user, update_user_field

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
    update_user_field(
        telegram_id,
        "achievements",
        json.dumps(achieved, ensure_ascii=False),
        save_to_db=True,
    )
    return True


def check_and_award(telegram_id: int, metric: str, new_value: int) -> list[str]:
    """РџСЂРѕРІРµСЂРёС‚СЊ РїРѕСЂРѕРіРё РґРѕСЃС‚РёР¶РµРЅРёР№ РґР»СЏ РјРµС‚СЂРёРєРё Рё РІС‹РґР°С‚СЊ РЅРѕРІС‹Рµ."""
    new: list[str] = []
    for key, spec in ACHIEVEMENTS.items():
        if spec["metric"] != metric:
            continue
        if new_value >= spec["target"]:
            if award(telegram_id, key):
                new.append(key)
    return new


def get_user_achievements(telegram_id: int) -> dict[str, int]:
    """Р’РµСЂРЅСѓС‚СЊ dict {key: 1} РІС‹РґР°РЅРЅС‹С… РґРѕСЃС‚РёР¶РµРЅРёР№ РїРѕР»СЊР·РѕРІР°С‚РµР»СЋ."""
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

