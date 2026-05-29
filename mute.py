"""
РњРѕРґСѓР»СЊ РјРѕРґРµСЂР°С†РёРё: /mute вЂ” "РјРѕР»С‡Р°РЅРєР°" (РєР»СЏРї) Р·Р° 10 СЃРј С„РёСЃСЃСѓСЂС‹.

вњЁ Р”РІР° СЃРїРѕСЃРѕР±Р° РІС‹РґР°С‡Рё:
  РЎРџРћРЎРћР‘ 1: /mute РІ РѕС‚РІРµС‚ РЅР° СЃРѕРѕР±С‰РµРЅРёРµ
  РЎРџРћРЎРћР‘ 2: /mute @username

РџСЂРё РІС‹РґР°С‡Рµ:
  в‘  РџСЂРѕРІРµСЂРєР°: РЅРµР»СЊР·СЏ РґР°С‚СЊ РєР»СЏРї СЃРµР±Рµ
  в‘Ў РџСЂРѕРІРµСЂРєР° Р±Р°Р»Р°РЅСЃР° Р°РґРјРёРЅР° (РЅСѓР¶РЅРѕ в‰Ґ 10 СЃРј С„РёСЃСЃСѓСЂС‹)
  в‘ў РЎРїРёСЃС‹РІР°РµС‚СЃСЏ 10 СЃРј Р±РµР· СѓРїРѕРјРёРЅР°РЅРёСЏ РІ С‡Р°С‚Рµ
  в‘Ј Р‘РѕС‚ РїРёС€РµС‚: "рџ“ў {Р°РґРјРёРЅ} РґР°Р»(Р°) РєР»СЏРї {Р¶РµСЂС‚РІРµ}рџ¤ђ РЅР° 30 СЃРµРєСѓРЅРґ!"
  в‘¤ РЎРѕРѕР±С‰РµРЅРёСЏ Р·Р°РєР»СЏРїР»РµРЅРЅРѕРіРѕ СѓРґР°Р»СЏСЋС‚СЃСЏ 30 СЃРµРєСѓРЅРґ
  в‘Ґ РђРІС‚РѕРјР°С‚РёС‡РµСЃРєРѕРµ СЃРЅСЏС‚РёРµ РєР»СЏРїР° С‡РµСЂРµР· 30 СЃРµРєСѓРЅРґ
"""

import asyncio
import logging
from datetime import datetime, timedelta

from telegram import Update
from telegram.ext import CommandHandler, ContextTypes, MessageHandler

logger = logging.getLogger(__name__)

__all__ = [
    "register_handlers",
]

# в”Ђв”Ђв”Ђ РќР°СЃС‚СЂРѕР№РєРё в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
_MUTE_COST_CM = 10          # СЃС‚РѕРёРјРѕСЃС‚СЊ РІ СЃРј С„РёСЃСЃСѓСЂС‹
_MUTE_DURATION_SEC = 30     # РґР»РёС‚РµР»СЊРЅРѕСЃС‚СЊ РєР»СЏРїР°

# Р Р°Р·РЅРѕРѕР±СЂР°Р·РЅС‹Рµ СЃРјР°Р№Р»С‹ РєР»СЏРїР° (Р±РµР· РґСѓР±Р»РёРєР°С‚РѕРІ)
_GAG_EMOJIS = [
    "рџ¤ђ", "рџ”‡", "рџ™Љ", "рџ§¦", "рџЌЊ",
    "рџ¤«", "рџ”•", "рџ¦·", "рџЋ­", "рџ¶",
    "рџ¤Єрџ”‡", "рџ¤­", "рџ—ЈпёЏ", "рџ—ЇпёЏ", "рџ’¤",
    "рџ”њ", "рџ™…", "рџ™†", "рџ¤Ё",
]

# в”Ђв”Ђв”Ђ РҐСЂР°РЅРёР»РёС‰Р° в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
# Р—Р°Р°РєР»СЏРїР»РµРЅРЅС‹Рµ: {user_id: datetime_РѕРєРѕРЅС‡Р°РЅРёСЏ}
_gagged_users: dict[int, datetime] = {}

# РљРµС€ username в†’ (user_id, РІСЂРµРјСЏ_РєРµС€РёСЂРѕРІР°РЅРёСЏ)
_username_cache: dict[str, tuple[int, datetime]] = {}
_USERNAME_CACHE_TTL = timedelta(hours=1)

# РўРµРєСѓС‰Р°СЏ Р·Р°РґР°С‡Р° Р°РІС‚РѕСЃРЅСЏС‚РёСЏ РєР»СЏРїР°: victim_id в†’ asyncio.Task
_gag_auto_release_tasks: dict[int, asyncio.Task] = {}


# в”Ђв”Ђв”Ђ Р’СЃРїРѕРјРѕРіР°С‚РµР»СЊРЅС‹Рµ РјРµС‚РѕРґС‹ в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ

def _pick_gag_emoji(victim_id: int) -> str:
    """РЎР»СѓС‡Р°Р№РЅС‹Р№ РІС‹Р±РѕСЂ СЃРјР°Р№Р»Р° РєР»СЏРїР°."""
    import random
    return random.choice(_GAG_EMOJIS)


def _get_gag_expiry(user_id: int) -> datetime | None:
    """Р’РѕР·РІСЂР°С‰Р°РµС‚ РІСЂРµРјСЏ РѕРєРѕРЅС‡Р°РЅРёСЏ РєР»СЏРїР° РёР»Рё None."""
    expiry = _gagged_users.get(user_id)
    if expiry is None:
        return None
    if datetime.now() >= expiry:
        # РЈСЃС‚Р°СЂРµР» вЂ” С‡РёСЃС‚РёРј
        _gagged_users.pop(user_id, None)
        return None
    return expiry


def _is_gagged(user_id: int) -> bool:
    return _get_gag_expiry(user_id) is not None


# в”Ђв”Ђв”Ђ Р Р°Р±РѕС‚Р° СЃ С„РёСЃСЃСѓСЂРѕР№ в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ

def add_fissure(user_id: int, amount_cm: float) -> None:
    """
    Р”РѕР±Р°РІРёС‚СЊ / РѕС‚РЅСЏС‚СЊ С„РёСЃСЃСѓСЂСѓ Сѓ РїРѕР»СЊР·РѕРІР°С‚РµР»СЏ.

    РСЃРїРѕР»СЊР·СѓРµС‚ Р‘Р” РЅР°РїСЂСЏРјСѓСЋ (РєР°Рє РѕСЃС‚Р°Р»СЊРЅРѕР№ Р±РѕС‚), РїРѕСЌС‚РѕРјСѓ **РЅРµ** РґРµР»Р°РµС‚ flush
    РєРµС€Р° вЂ” РёР·РјРµРЅРµРЅРёСЏ СЃСЂР°Р·Сѓ РїРѕРїР°РґР°СЋС‚ РІ Р±Р°Р·Сѓ.
    """
    from database import (  # Р»РѕРєР°Р»СЊРЅС‹Р№ РёРјРїРѕСЂС‚, С‡С‚РѕР±С‹ РЅРµ Р±С‹Р»Рѕ С†РёРєР»Р°
        get_user,
        update_fissure,
    )

    user = get_user(user_id)
    if user is None:       # РїРѕР»СЊР·РѕРІР°С‚РµР»СЊ РµС‰С‘ РЅРµ Р·Р°СЂРµРіРёСЃС‚СЂРёСЂРѕРІР°РЅ
        return

    current = float(user.get("fissure", 0.0))
    new_fissure = max(0.0, current + amount_cm)
    import time
    update_fissure(user_id, new_fissure, time.time(), 0)


# в”Ђв”Ђв”Ђ РџРѕРёСЃРє РїРѕР»СЊР·РѕРІР°С‚РµР»СЏ РїРѕ @username РІ С‡Р°С‚Рµ в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ

async def get_user_by_username_in_chat(
    chat_id: int,
    username: str,
    context: ContextTypes.DEFAULT_TYPE,
) -> dict | None:
    """
    РќР°Р№С‚Рё РїРѕР»СЊР·РѕРІР°С‚РµР»СЏ Telegram РїРѕ СЃРѕРєСЂР°С‰С‘РЅРЅРѕРјСѓ username (Р±РµР· @) СЃСЂРµРґРё СѓС‡Р°СЃС‚РЅРёРєРѕРІ С‡Р°С‚Р°.

    РЎС‚СЂР°С‚РµРіРёСЏ РїРѕРёСЃРєР°:
      1. РџСЂРѕРІРµСЂРёС‚СЊ РєРµС€ (username в†’ user_id).
      2. РЈС‚РѕС‡РЅРёС‚СЊ С‡РµСЂРµР· get_chat_member() вЂ” РїРѕР»СЊР·РѕРІР°С‚РµР»СЊ РјРѕРі РїРµСЂРµРёРјРµРЅРѕРІР°С‚СЊСЃСЏ.
      3. Р•СЃР»Рё РІ РєРµС€Рµ РЅРµС‚ вЂ” РїРµСЂРµР±СЂР°С‚СЊ Р°РґРјРёРЅРёСЃС‚СЂР°С‚РѕСЂРѕРІ С‡Р°С‚Р° (bech <= 50, РґРµС€РµРІРѕ РїРѕ API).
      4. Р•СЃР»Рё Р°РґРјРёРЅРѕРІ РјР°Р»Рѕ вЂ” РѕРїСЂРѕСЃРёС‚СЊ СѓС‡Р°СЃС‚РЅРёРєРѕРІ С‡РµСЂРµР· get_chat_member РґРѕ РѕР±РЅР°СЂСѓР¶РµРЅРёСЏ.
    """
    username = username.lstrip("@").lower().strip()
    if not username:
        return None

    bot = context.bot

    # в‘  РљРµС€
    cached = _username_cache.get(username)
    if cached:
        cached_uid, cached_at = cached
        if datetime.now() - cached_at < _USERNAME_CACHE_TTL:
            try:
                member = await bot.get_chat_member(chat_id, cached_uid)
                tg_user = member.user
                if tg_user.username and tg_user.username.lower() == username:
                    return {"telegram_id": tg_user.id, "username": tg_user.username}
            except Exception:
                _username_cache.pop(username, None)

    # в‘Ў РђРґРјРёРЅРёСЃС‚СЂР°С‚РѕСЂС‹ вЂ” Р±С‹СЃС‚СЂС‹Р№ РїСѓС‚СЊ
    try:
        admins = await bot.get_chat_administrators(chat_id)
        for admin in admins:
            u = admin.user
            if u.username and u.username.lower() == username:
                _username_cache[username] = (u.id, datetime.now())
                return {"telegram_id": u.id, "username": u.username}
    except Exception:
        logger.debug(f"get_chat_administrators failed for chat {chat_id}")

    # в‘ў С‡С‚РµРЅРёРµ РёР· Р‘Р” РїРѕ username (РµСЃР»Рё Р±РѕС‚ СѓР¶Рµ РІРёРґРµР» С‚Р°РєРѕРіРѕ)
    try:
        from database import get_user_by_username as db_get_by_username
        user_data = db_get_by_username(username)
        if user_data:
            uid = user_data.get("telegram_id")
            if uid:
                _username_cache[username] = (uid, datetime.now())
                return user_data
    except Exception:
        logger.debug(f"get_user_by_username DB lookup failed for '{username}'")

    return None


# в”Ђв”Ђв”Ђ РћСЃРЅРѕРІРЅР°СЏ Р»РѕРіРёРєР° РІС‹РґР°С‡Рё РєР»СЏРїР° в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ

async def _do_give_gag(
    admin: dict,
    victim: dict,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> bool:
    """Р’С‹РґР°С‚СЊ РєР»СЏРї Р¶РµСЂС‚РІРµ, СЃРїРёСЃР°С‚СЊ 10 СЃРј С„РёСЃСЃСѓСЂС‹ СЃ Р°РґРјРёРЅР°."""
    admin_id   = admin["telegram_id"]
    victim_id  = victim["telegram_id"]
    chat_id    = update.effective_chat.id
    chat_type  = str(update.effective_chat.type)

    is_self_mute = (admin_id == victim_id)

    # в”Ђв”Ђ 1. РџСЂРѕРІРµСЂРєР° Р±Р°Р»Р°РЅСЃР° (РЅРµ СЃРїРёСЃС‹РІР°РµРј, РµСЃР»Рё РјСѓС‚РёРј СЃРµР±СЏ) в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
    if not is_self_mute:
        current = get_current_fissure(admin_id)
        if current < _MUTE_COST_CM:
            await context.bot.send_message(
                chat_id,
                f"рџ’ё РќРµРґРѕСЃС‚Р°С‚РѕС‡РЅРѕ С„РёСЃСЃСѓСЂ! "
                f"РќСѓР¶РЅРѕ {_MUTE_COST_CM} СЃРј, Р° Сѓ С‚РµР±СЏ С‚РѕР»СЊРєРѕ {current:.1f} СЃРј."
            )
            try:
                await update.message.delete()
            except Exception:
                pass
            return False

        # в”Ђв”Ђ 2. РЎРїРёСЃС‹РІР°РµРј С„РёСЃСЃСѓСЂСѓ (С‚РѕР»СЊРєРѕ РµСЃР»Рё РЅРµ РјСѓС‚РёРј СЃРµР±СЏ) в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
        add_fissure(admin_id, -_MUTE_COST_CM)

    # в”Ђв”Ђ 4. РЈРґР°Р»СЏРµРј РєРѕРјР°РЅРґСѓ /mute РёР· С‡Р°С‚Р° в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
    try:
        await update.message.delete()
    except Exception:
        logger.debug(f"Could not delete /mute command message in {chat_id}", exc_info=True)

    # в”Ђв”Ђ 5. В«РљР»Р°РґС‘РјВ» РєР»СЏРї РЅР° Р¶РµСЂС‚РІСѓ в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
    expiry = datetime.now() + timedelta(seconds=_MUTE_DURATION_SEC)
    _gagged_users[victim_id] = expiry

    # в”Ђв”Ђ 6. РђРЅРѕРЅСЃ РІ С‡Р°С‚ (РѕС‚РґРµР»СЊРЅС‹Рј СЃРѕРѕР±С‰РµРЅРёРµРј, РЅРµ СЂРµРїР»Р°Р№) в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
    gag_emoji    = _pick_gag_emoji(victim_id)
    victim_name  = victim.get("username") or victim.get("first_name") or str(victim_id)
    admin_name   = admin.get("username") or admin.get("first_name") or str(admin_id)
    victim_link  = (
        f"<a href='tg://user?id={victim_id}'>"
        f"{victim_name}</a>"
    )
    admin_link   = (
        f"<a href='tg://user?id={admin_id}'>"
        f"{admin_name}</a>"
    )
    announcement = (
        f"рџ‘¤ {admin_link} РґР°Р»(Р°) РєР»СЏРї {gag_emoji} {victim_link} РЅР° 30 СЃРµРєСѓРЅРґ."
    )
    announce_msg = await context.bot.send_message(
        chat_id=chat_id,
        text=announcement,
        parse_mode="HTML",
    )
    # РЈРґР°Р»РёС‚СЊ Р°РЅРѕРЅСЃ С‚РѕР¶Рµ С‡РµСЂРµР· 30 СЃРµРєСѓРЅРґ
    try:
        from main import schedule_delete
        schedule_delete(
            context.bot, chat_id, announce_msg.message_id,
            _MUTE_DURATION_SEC, context.application.job_queue
        )
    except Exception:
        logger.debug("schedule_delete import failed, using asyncio fallback", exc_info=True)
        asyncio.create_task(_delayed_delete(context.bot, chat_id, announce_msg.message_id, _MUTE_DURATION_SEC))

    # в”Ђв”Ђ 6. Р—Р°РїСѓСЃРєР°РµРј Р°РІС‚РѕСЃРЅСЏС‚РёРµ в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
    _schedule_gag_release(victim_id, chat_id, chat_type, context)

    return True


async def _delayed_delete(bot, chat_id: int, msg_id: int, delay: int) -> None:
    """Fallback: СѓРґР°Р»РёС‚СЊ СЃРѕРѕР±С‰РµРЅРёРµ С‡РµСЂРµР· delay СЃРµРєСѓРЅРґ."""
    await asyncio.sleep(delay)
    try:
        await bot.delete_message(chat_id, msg_id)
    except Exception:
        logger.debug(f"Fallback delete failed: {msg_id} in {chat_id}", exc_info=True)


def _schedule_gag_release(
    victim_id: int,
    chat_id: int,
    chat_type: str,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Р—Р°РїСѓСЃРєР°РµС‚ С„РѕРЅРѕРІСѓСЋ Р·Р°РґР°С‡Сѓ, РєРѕС‚РѕСЂР°СЏ СЃРЅРёРјРµС‚ РєР»СЏРї Рё СѓРІРµРґРѕРјРёС‚ С‡Р°С‚."""
    # РћС‚РјРµРЅСЏРµРј РїСЂРµРґС‹РґСѓС‰СѓСЋ Р·Р°РґР°С‡Сѓ, РµСЃР»Рё РµСЃС‚СЊ
    old_task = _gag_auto_release_tasks.pop(victim_id, None)
    if old_task and not old_task.done():
        old_task.cancel()

    task = asyncio.create_task(
        _gag_timeout_job(victim_id, chat_id, chat_type, context)
    )
    _gag_auto_release_tasks[victim_id] = task


async def _gag_timeout_job(
    victim_id: int,
    chat_id: int,
    chat_type: str,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Р¤РѕРЅРѕРІР°СЏ Р·Р°РґР°С‡Р°: Р¶РґС‘С‚ РёСЃС‚РµС‡РµРЅРёСЏ РєР»СЏРїР°, РїРѕС‚РѕРј СЃРЅРёРјР°РµС‚ РµРіРѕ."""
    expiry = _gagged_users.get(victim_id)
    if not expiry:
        return

    wait = (expiry - datetime.now()).total_seconds()
    if wait > 0:
        await asyncio.sleep(wait)

    # РЎРЅРёРјР°РµРј РєР»СЏРї
    _gagged_users.pop(victim_id, None)
    _gag_auto_release_tasks.pop(victim_id, None)

    # РЈРІРµРґРѕРјР»СЏРµРј С‡Р°С‚ (С‚РѕР»СЊРєРѕ РІ РіСЂСѓРїРїРµ/СЃСѓРїРµСЂРіСЂСѓРїРїРµ)
    if chat_type in ("group", "supergroup"):
        try:
            from database import get_user
            victim = get_user(victim_id)
            name = (
                (victim.get("username") if victim else None)
                or (victim.get("first_name") if victim else None)
                or str(victim_id)
            )
            notify_msg = await context.bot.send_message(
                chat_id=chat_id,
                text=f"рџ—Ј РљР»СЏРї СЃРЅСЏС‚ Сѓ @{name}",
            )
            # РЈРґР°Р»СЏРµРј СѓРІРµРґРѕРјР»РµРЅРёРµ С‡РµСЂРµР· 10 СЃРµРєСѓРЅРґ
            asyncio.create_task(_delayed_delete(
                context.bot, chat_id, notify_msg.message_id, 10
            ))
        except Exception:
            logger.debug(f"Gag release notify failed for {victim_id} in {chat_id}", exc_info=True)


# в”Ђв”Ђв”Ђ Р¤РёР»СЊС‚СЂ СѓРґР°Р»РµРЅРёСЏ СЃРѕРѕР±С‰РµРЅРёР№ Р·Р°РєР»СЏРїР»РµРЅРЅС‹С… в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ

GAG_FILTER_FLAG = "mute"

async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Middleware-С„РёР»СЊС‚СЂ: СѓРґР°Р»СЏРµС‚ СЃРѕРѕР±С‰РµРЅРёСЏ РѕС‚ РїРѕР»СЊР·РѕРІР°С‚РµР»РµР№ СЃ Р°РєС‚РёРІРЅС‹Рј РєР»СЏРїРѕРј.
    РџРѕРґРєР»СЋС‡Р°РµС‚СЃСЏ РєР°Рє РѕС‚РґРµР»СЊРЅС‹Р№ MessageHandler СЃ РЅРёР·РєРёРј РїСЂРёРѕСЂРёС‚РµС‚РѕРј.
    """
    # РџСЂРѕРїСѓСЃРєР°РµРј СЃРѕРѕР±С‰РµРЅРёСЏ Р±РµР· С‚РµРєСЃС‚Р° (СЃС‚РёРєРµСЂС‹, РјРµРґРёР° РїСЂРѕС…РѕРґСЏС‚ вЂ” РµСЃР»Рё РЅСѓР¶РЅРѕ
    # РёС… С‚РѕР¶Рµ Р±Р»РѕРєРёСЂРѕРІР°С‚СЊ, СЂР°СЃС€РёСЂСЊС‚Рµ СѓСЃР»РѕРІРёСЏ РЅРёР¶Рµ)
    if not update.effective_message:
        return

    user = update.effective_user
    if user is None:
        return

    # РђРґРјРёРЅРёСЃС‚СЂР°С‚РѕСЂС‹ СЃ РїСЂР°РІРѕРј СѓРґР°Р»РµРЅРёСЏ СЃРѕРѕР±С‰РµРЅРёР№ РќР• СЃС‚СЂР°РґР°СЋС‚ РѕС‚ РєР»СЏРїР°
    if _can_admin_bypass(context, update):
        return

    if _gagged_users.get(user.id) and datetime.now() < _gagged_users[user.id]:
        try:
            await update.effective_message.delete()
        except Exception:
            logger.debug(f"Failed to delete gagged message from {user.id}", exc_info=True)
    else:
        # РљР»СЏРї РёСЃС‚С‘Рє вЂ” С‡РёСЃС‚РёРј
        _gagged_users.pop(user.id, None)


def _can_admin_bypass(
    context: ContextTypes.DEFAULT_TYPE,
    update: Update,
) -> bool:
    """РђРґРјРёРЅРёСЃС‚СЂР°С‚РѕСЂС‹ РјРѕРіСѓС‚ РѕР±С…РѕРґРёС‚СЊ РєР»СЏРї."""
    try:
        chat_id  = update.effective_chat.id
        user_id  = update.effective_user.id
        member = context.bot.get_chat_member(chat_id, user_id)
        status  = member.status
        return status in ("creator", "administrator")
    except Exception:
        return False


# в”Ђв”Ђв”Ђ РљРѕРјР°РЅРґР° /mute в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ

_MUTE_USAGE = (
    "рџ¤Є <b>Р—Р°РјСѓС‚РёС‚СЊ РїРѕР»СЊР·РѕРІР°С‚РµР»СЏ</b> вЂ” С†РµРЅР° 10 С„РёСЃСЃСѓСЂ.\n"
    "<code>/mute @username</code> РёР»Рё <code>/mute</code> РІ РѕС‚РІРµС‚ РЅР° РµРіРѕ СЃРѕРѕР±С‰РµРЅРёРµ"
)


async def mute_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """РћР±СЂР°Р±РѕС‚С‡РёРє /mute вЂ” РґРІР° СЃРїРѕСЃРѕР±Р° РІС‹РґР°С‡Рё РєР»СЏРїР°."""
    if not update.message or not update.effective_user:
        return

    chat = update.effective_chat
    if chat.type == "private":
        chat_id = update.effective_chat.id
        await context.bot.send_message(chat_id, "в›” РљРѕРјР°РЅРґР° СЂР°Р±РѕС‚Р°РµС‚ С‚РѕР»СЊРєРѕ РІ РіСЂСѓРїРїР°С… Рё СЃСѓРїРµСЂРіСЂСѓРїРїР°С…!")
        try:
            await update.message.delete()
        except Exception:
            pass
        return

    admin_id = update.effective_user.id
    chat_id = update.effective_chat.id

    # в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
    # РЎРџРћРЎРћР‘ 1: /mute РІ РѕС‚РІРµС‚ РЅР° СЃРѕРѕР±С‰РµРЅРёРµ
    # в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
    if update.message.reply_to_message:
        victim_tg = update.message.reply_to_message.from_user
        if victim_tg is None:
            await context.bot.send_message(chat_id, "вќЊ РќРµ СѓРґР°Р»РѕСЃСЊ РѕРїСЂРµРґРµР»РёС‚СЊ Р°РІС‚РѕСЂР° СЃРѕРѕР±С‰РµРЅРёСЏ.")
            try:
                await update.message.delete()
            except Exception:
                pass
            return
        victim = {
            "telegram_id": victim_tg.id,
            "username":     getattr(victim_tg, "username", None) or "",
            "first_name":   getattr(victim_tg, "first_name", ""),
        }
        await _do_give_gag(
            admin={
                "telegram_id": admin_id,
                "username":    getattr(update.effective_user, "username", None) or "",
                "first_name":  getattr(update.effective_user, "first_name", ""),
            },
            victim=victim,
            update=update,
            context=context,
        )
        return

    # в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
    # РЎРџРћРЎРћР‘ 2: /mute @username
    # в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
    if context.args:
        for arg in context.args:
            if arg.startswith("@"):
                victim = await get_user_by_username_in_chat(
                    chat_id=chat.id,
                    username=arg[1:],
                    context=context,
                )
                if victim:
                    await _do_give_gag(
                        admin={
                            "telegram_id": admin_id,
                            "username":    getattr(update.effective_user, "username", None) or "",
                            "first_name":  getattr(update.effective_user, "first_name", ""),
                        },
                        victim=victim,
                        update=update,
                        context=context,
                    )
                    return

        # No @-Р°СЂРіСѓРјРµРЅС‚РѕРІ РЅР°Р№РґРµРЅРѕ вЂ” РІРѕР·РјРѕР¶РЅРѕ, Р·Р°Р±С‹Р»Рё @
        await context.bot.send_message(
            chat_id,
            "вќЊ РЈРєР°Р¶Рё username СЃ @, РЅР°РїСЂРёРјРµСЂ:\n/mute @username"
        )
        try:
            await update.message.delete()
        except Exception:
            pass
        return

    # РќРёС‡РµРіРѕ РЅРµ РїРѕРґРѕС€Р»Рѕ вЂ” СЃРїСЂР°РІРєР°
    await context.bot.send_message(chat_id, f"вќ“ {_MUTE_USAGE}", parse_mode="HTML")
    try:
        await update.message.delete()
    except Exception:
        pass


# в”Ђв”Ђв”Ђ Р’СЃРїРѕРјРѕРіР°С‚РµР»СЊРЅС‹Рµ РїСЂРѕРІРµСЂРєРё в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ

def get_current_fissure(user_id: int) -> float:
    """Р’РѕР·РІСЂР°С‰Р°РµС‚ С‚РµРєСѓС‰СѓСЋ С„РёСЃСЃСѓСЂСѓ РїРѕР»СЊР·РѕРІР°С‚РµР»СЏ (РёР· Р‘Р”)."""
    try:
        from database import get_user
        user = get_user(user_id)
        if user:
            return float(user.get("fissure", 0.0))
    except Exception:
        logger.debug(f"get_current_fissure error for {user_id}", exc_info=True)
    return 0.0


# в”Ђв”Ђв”Ђ РџСѓР±Р»РёС‡РЅС‹Р№ API РјРѕРґСѓР»СЏ в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ

def register_handlers(application) -> None:
    """
    Р—Р°СЂРµРіРёСЃС‚СЂРёСЂРѕРІР°С‚СЊ РІСЃРµ РѕР±СЂР°Р±РѕС‚С‡РёРєРё РјРѕРґСѓР»СЏ РІ Application.

    РџСЂРёРЅРёРјР°РµС‚ Application РёР· python-telegram-bot v20.
    """
    # РљРѕРјР°РЅРґР° /mute
    application.add_handler(CommandHandler("mute", mute_command))

    # Р¤РёР»СЊС‚СЂ СЃРѕРѕР±С‰РµРЅРёР№: СѓРґР°Р»СЏРµС‚ СЃРѕРѕР±С‰РµРЅРёСЏ Р·Р°РєР»СЏРїР»РµРЅРЅС‹С…
    # block=False в†’ РЅРµ РїРµСЂРµС…РІР°С‚С‹РІР°РµС‚ РѕР±РЅРѕРІР»РµРЅРёРµ, РґСЂСѓРіРёРµ С…РµРЅРґР»РµСЂС‹ continue СЂР°Р±РѕС‚Р°С‚СЊ
    application.add_handler(
        MessageHandler(filters=None, callback=on_message, block=False)
    )
