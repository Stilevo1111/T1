import asyncio
import logging
import os
import time

from telegram import Bot

logger = logging.getLogger(__name__)


def _telegram_error_contains(error: Exception, *phrases: str) -> bool:
    """РџСЂРѕРІРµСЂСЏРµС‚, СЃРѕРґРµСЂР¶РёС‚ Р»Рё С‚РµРєСЃС‚ РѕС€РёР±РєРё Р»СЋР±СѓСЋ РёР· РїРµСЂРµРґР°РЅРЅС‹С… С„СЂР°Р· (СЂРµРіРёСЃС‚СЂРѕРЅРµР·Р°РІРёСЃРёРјРѕ)."""
    if error is None:
        return False
    msg = str(error).lower()
    return any(p.lower() in msg for p in phrases)


# =====================================================
# DIGEST STATE - encapsulated for multi-instance safety
# =====================================================

class _DigestState:
    """Internal container for digest runtime state.
    Do not access directly from outside this module.
    """
    def __init__(self):
        self.state = {
            "type": None,
            "chat_id": None,
            "last_data_update": 0,
            "last_run": 0,
            "last_text": None,
            "last_hero_meta_update": 0,
            "hero_meta_image": None,
            "last_edited": 0,
        }
        self.cache = {
            "text": None,
            "type": None,
            "created_at": 0,
            "cache_ttl": 300,
            "rotation_interval": 172800,
            "data_hash": None,
            "last_data_check": 0,
        }
        self.last_data_refresh = 0
        self.data_refresh_interval = 600
        self.lock = asyncio.Lock()

    # --- Convenience methods (internal use only) ---
    def get_state(self, key, default=None):
        return self.state.get(key, default)

    def set_state(self, key, value):
        self.state[key] = value

    def is_cache_expired(self) -> bool:
        return (time.time() - self.cache.get("created_at", 0)) > self.cache.get("cache_ttl", 300)

    def mark_data_refreshed(self):
        self.last_data_refresh = time.time()

    # --- Hot path specific accessors (to finish encapsulation) ---
    def get_current_type(self):
        return self.state.get("type")

    def set_current_type(self, value):
        self.state["type"] = value

    def get_last_text(self):
        return self.state.get("last_text")

    def set_last_text(self, value):
        self.state["last_text"] = value

    def get_last_run(self):
        return self.state.get("last_run", 0)

    def set_last_run(self, value):
        self.state["last_run"] = value

    def get_edit_retry_done(self):
        return self.state.get("edit_retry_done", False)

    def set_edit_retry_done(self, value):
        self.state["edit_retry_done"] = value

    def get_digest_data(self):
        return self.state.get("digest_data")

    def set_digest_data(self, value):
        self.state["digest_data"] = value

    def get_dota_data(self):
        return self.state.get("dota_data")

    def set_dota_data(self, value):
        self.state["dota_data"] = value

    def get_last_data_update(self):
        return self.state.get("last_data_update", 0)

    def set_last_data_update(self, value):
        self.state["last_data_update"] = value

    def get_chat_id(self):
        return self.state.get("chat_id")

    def set_chat_id(self, value):
        self.state["chat_id"] = value

    def get_last_data_refresh(self):
        return self.last_data_refresh

    def set_last_data_refresh(self, value):
        self.last_data_refresh = value

    def get_is_photo_message(self):
        return self.state.get("is_photo_message")

    def set_is_photo_message(self, value):
        self.state["is_photo_message"] = value

    def get_dota_last_text(self):
        return self.state.get("dota_last_text")

    def set_dota_last_text(self, value):
        self.state["dota_last_text"] = value

# Single instance of the state container
_digest_state_container = _DigestState()

# Backwards-compatible module-level references (so existing code doesn't break)
_digest_state = _digest_state_container.state
_digest_cache = _digest_state_container.cache
_digest_state_lock = _digest_state_container.lock

_last_data_refresh = _digest_state_container.last_data_refresh
_data_refresh_interval = _digest_state_container.data_refresh_interval

DIGEST_DATA_REFRESH_INTERVAL = 3600
HERO_META_REFRESH_INTERVAL = 3600

# =====================================================
# Fast in-memory tick (15s visible switching, ZERO DB calls)
# Only the current leader runs this background task.
# =====================================================


def refresh_dota_digest_cache() -> None:
    """Refreshes Dota digest data in _digest_state.
    Called from the hourly MMR job so the 15-second fast rotation
    always has fresh data to flip between Fissure and Dota.
    """
    try:
        from database import get_dota_week_top
        dota_top = get_dota_week_top(limit=10)
        _digest_state_container.set_dota_data(dota_top)
        _digest_state_container.mark_data_refreshed()
        logger.info("Dota digest cache refreshed from MMR job (fast 15s rotation now has fresh data)")
    except Exception as e:
        logger.warning(f"Failed to refresh Dota digest cache: {e}")

_fast_tick_task: asyncio.Task | None = None
_fast_tick_chat_id: int | None = None
_fast_tick_message_id: int | None = None
_fast_tick_is_photo: bool = False


async def _fast_digest_tick(bot: Bot) -> None:
    """РџРµСЂРµРєР»СЋС‡Р°РµС‚ С‚РёРї РґР°Р№РґР¶РµСЃС‚Р° РєР°Р¶РґС‹Рµ 15 СЃРµРєСѓРЅРґ, РёСЃРїРѕР»СЊР·СѓСЏ С‚РѕР»СЊРєРѕ РґР°РЅРЅС‹Рµ РІ РїР°РјСЏС‚Рё.
    РќРёРєР°РєРёС… РѕР±СЂР°С‰РµРЅРёР№ Рє Р‘Р” РёР»Рё config.
    """
    global _fast_tick_message_id, _fast_tick_is_photo

    while True:
        try:
            await asyncio.sleep(15)

            if not _fast_tick_chat_id or not _fast_tick_message_id:
                break

            current_type = get_digest_type("0")
            next_type = "1" if current_type == "0" else "0"
            _digest_state_container.set_current_type(next_type)

            # Р“РµРЅРµСЂРёСЂСѓРµРј С‚РµРєСЃС‚ РґР»СЏ РЅРѕРІРѕРіРѕ С‚РёРїР° РёР· Р·Р°РєРµС€РёСЂРѕРІР°РЅРЅС‹С… РґР°РЅРЅС‹С… (Р±РµР· Р‘Р”)
            text = _build_digest_text_for_type(next_type)

            if not text:
                continue

            # Re-sync from the single source of truth every tick (helps with multi-instance drift)
            _fast_tick_is_photo = _get_digest_is_photo()

            try:
                is_photo = _fast_tick_is_photo
                is_photo = _get_digest_is_photo()  # re-sync one last time right before edit (extra drift protection)
                if is_photo:
                    await bot.edit_message_caption(
                        chat_id=_fast_tick_chat_id,
                        message_id=_fast_tick_message_id,
                        caption=text,
                        parse_mode="HTML"
                    )
                else:
                    await bot.edit_message_text(
                        chat_id=_fast_tick_chat_id,
                        message_id=_fast_tick_message_id,
                        text=text,
                        parse_mode="HTML"
                    )
                # Explicitly record the type we just successfully used
                _set_digest_is_photo(is_photo)
            except Exception as e:
                if _telegram_error_contains(e, "message to edit not found", "message can't be edited"):
                    # РЎРѕРѕР±С‰РµРЅРёРµ РёСЃС‡РµР·Р»Рѕ вЂ” РІС‹С…РѕРґРёРј РёР· fast loop, heavy job РїРµСЂРµСЃРѕР·РґР°СЃС‚
                    logger.info("Fast tick: message gone, stopping fast loop")
                    break
                # One-time recovery: if we guessed the wrong message type (photo vs text), try the opposite once
                if _telegram_error_contains(e, "bad request", "there is no text in the message to edit", "there is no caption in the message to edit"):
                    try:
                        if is_photo:
                            await bot.edit_message_text(
                                chat_id=_fast_tick_chat_id,
                                message_id=_fast_tick_message_id,
                                text=text,
                                parse_mode="HTML"
                            )
                            _fast_tick_is_photo = False
                            _set_digest_is_photo(False)
                        else:
                            await bot.edit_message_caption(
                                chat_id=_fast_tick_chat_id,
                                message_id=_fast_tick_message_id,
                                caption=text,
                                parse_mode="HTML"
                            )
                            _fast_tick_is_photo = True
                            _set_digest_is_photo(True)
                        logger.debug("Fast tick recovered by switching edit method")
                        continue
                    except Exception:
                        pass
                logger.debug(f"Fast tick edit skipped: {e}")

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.debug(f"Fast tick error: {e}")


def _build_digest_text_for_type(digest_type: str) -> str | None:
    """Р“РµРЅРµСЂРёСЂСѓРµС‚ С‚РµРєСЃС‚ РґР°Р№РґР¶РµСЃС‚Р° РґР»СЏ СѓРєР°Р·Р°РЅРЅРѕРіРѕ С‚РёРїР°, РёСЃРїРѕР»СЊР·СѓСЏ С‚РѕР»СЊРєРѕ РґР°РЅРЅС‹Рµ РІ РїР°РјСЏС‚Рё."""
    try:
        from main import make_clickable
    except Exception:
        from bot_utils import make_clickable

    if digest_type == "0":
        stats = _digest_state_container.get_digest_data()
        if not stats:
            return None
        growth_data = stats.get("top_growth", ("None", 0))
        growth_player = growth_data[0] if len(growth_data) > 0 else "None"
        growth_pos = growth_data[1] if len(growth_data) > 1 else 0
        drop_data = stats.get("top_drop", ("None", 0.0))
        drop_player = drop_data[0] if len(drop_data) > 0 else "None"
        drop_cm = drop_data[1] if len(drop_data) > 1 else 0.0
        streak_data = stats.get("top_streak", ("None", 0))
        streak_player = streak_data[0] if len(streak_data) > 0 else "None"
        streak_len = streak_data[1] if len(streak_data) > 1 else 0

        growth_display = make_clickable(growth_player, stats.get("top_growth_id"))
        drop_display = make_clickable(drop_player, stats.get("top_drop_id"))
        streak_display = make_clickable(streak_player, stats.get("top_streak_id"))

        growth_part = f"рџ”є{growth_display} +{growth_pos}" if growth_player and growth_player != "None" else "рџ”євЂ”"
        drop_part = f"рџ”»{drop_display} {drop_cm:.0f} РЎРњ" if drop_player and drop_player != "None" else "рџ”»вЂ”"
        streak_part = f" рџЌЂ{streak_display}: {streak_len} РїРѕР±РµРґ РїРѕРґСЂСЏРґ" if streak_player and streak_player != "None" and streak_len > 0 else " рџЌЂвЂ”"

        return f"<b>{growth_part}\n{drop_part}\n{streak_part}</b>\n\nрџ—їР¤РёСЃСЃСѓСЂР° РґР°Р№РґР¶РµСЃС‚.\n\n<b><a href=\"https://seredin999.onrender.com/patch-fissure\">РџРѕРґСЂРѕР±РЅРµРµ РЅР° РЅР°С€РµРј СЃР°Р№С‚Рµ.</a></b>"

    else:
        mmr_top = _digest_state_container.get_dota_data()
        if not mmr_top:
            return None

        valid_players = [p for p in mmr_top if p.get('week_games', 0) >= 3]
        if len(valid_players) < 2:
            return None

        # Top = best by net (2*wins - games)
        top_by_net = max(
            valid_players,
            key=lambda p: (p.get('week_wins', 0) - (p.get('week_games', 0) - p.get('week_wins', 0)), p.get('week_games', 0))
        )

        # Bottom = worst = opposite (lowest net)
        bottom_by_net = min(
            valid_players,
            key=lambda p: (p.get('week_wins', 0) - (p.get('week_games', 0) - p.get('week_wins', 0)), -p.get('week_games', 0))
        )

        top_name = make_clickable(top_by_net.get('steam_nickname') or top_by_net.get('username'), top_by_net.get('telegram_id'))
        bottom_name = make_clickable(bottom_by_net.get('steam_nickname') or bottom_by_net.get('username'), bottom_by_net.get('telegram_id'))

        top_games = top_by_net.get('week_games', 0)
        top_wins = top_by_net.get('week_wins', 0)
        top_losses = top_games - top_wins
        top_wr = round((top_wins / top_games * 100), 1) if top_games > 0 else 0

        bottom_games = bottom_by_net.get('week_games', 0)
        bottom_wins = bottom_by_net.get('week_wins', 0)
        bottom_losses = bottom_games - bottom_wins
        bottom_wr = round((bottom_wins / bottom_games * 100), 1) if bottom_games > 0 else 0

        return f"<b>рџ”є{top_name}: {top_wins}W/{top_losses}L в‰€{top_wr}%\nрџ”»{bottom_name}: {bottom_wins}W/{bottom_losses}L в‰€{bottom_wr}%</b>\n\nрџЋ® Dota РґР°Р№РґР¶РµСЃС‚.\n\n<b><a href='https://seredin999.onrender.com/patch-fissure'>РџРѕРґСЂРѕР±РЅРµРµ РЅР° РЅР°С€РµРј СЃР°Р№С‚Рµ.</a></b>"

    return None


def start_fast_digest_loop(bot: Bot, chat_id: int, message_id: int, is_photo: bool) -> None:
    """Р—Р°РїСѓСЃРєР°РµС‚ Р±С‹СЃС‚СЂС‹Р№ 15-СЃРµРєСѓРЅРґРЅС‹Р№ С†РёРєР» (С‚РѕР»СЊРєРѕ РµСЃР»Рё РµРіРѕ РµС‰С‘ РЅРµС‚)."""
    global _fast_tick_task, _fast_tick_chat_id, _fast_tick_message_id, _fast_tick_is_photo

    _fast_tick_chat_id = chat_id
    _fast_tick_message_id = message_id
    _fast_tick_is_photo = _get_digest_is_photo()

    if _fast_tick_task and not _fast_tick_task.done():
        return  # РЈР¶Рµ Р·Р°РїСѓС‰РµРЅ

    _fast_tick_task = asyncio.create_task(_fast_digest_tick(bot))
    logger.info(f"Fast 15s digest tick started (message {message_id})")


def stop_fast_digest_loop() -> None:
    """РћСЃС‚Р°РЅР°РІР»РёРІР°РµС‚ Р±С‹СЃС‚СЂС‹Р№ С†РёРєР»."""
    global _fast_tick_task, _fast_tick_chat_id, _fast_tick_message_id

    if _fast_tick_task and not _fast_tick_task.done():
        _fast_tick_task.cancel()
        logger.info("Fast 15s digest tick stopped")

    _fast_tick_task = None
    _fast_tick_chat_id = None
    _fast_tick_message_id = None
    _fast_tick_is_photo = False

# =====================================================
# Leader Election (for single active instance on Render free)
# =====================================================

def get_instance_id():
    return os.getenv("RENDER_INSTANCE_ID") or f"local_{os.getpid()}"


async def claim_or_check_digest_leader():
    """
    Р’РѕР·РІСЂР°С‰Р°РµС‚ True, РµСЃР»Рё С‚РµРєСѓС‰РёР№ РёРЅСЃС‚Р°РЅСЃ вЂ” Р»РёРґРµСЂ Рё РјРѕР¶РµС‚ РІС‹РїРѕР»РЅСЏС‚СЊ СЂР°Р±РѕС‚Сѓ СЃ РґР°Р№РґР¶РµСЃС‚РѕРј.
    РРЅР°С‡Рµ False (РґСЂСѓРіРѕР№ РєРѕРЅС‚РµР№РЅРµСЂ СѓР¶Рµ Р»РёРґРµСЂ).
    """
    instance_id = get_instance_id()
    now = time.time()
    LEADER_TIMEOUT = 60

    current_leader = None
    last_seen = 0.0

    from database import get_config, set_config

    try:
        current_leader = get_config('digest_leader_id')
        last_seen_str = get_config('digest_leader_last_seen')
        last_seen = float(last_seen_str) if last_seen_str else 0
    except Exception:
        pass

    is_leader = False

    if current_leader == instance_id:
        is_leader = True
    elif not current_leader or (now - last_seen > LEADER_TIMEOUT):
        try:
            set_config('digest_leader_id', instance_id)
            set_config('digest_leader_last_seen', str(now))
            logger.warning(f"digest: Р—РђРҐР’РђРўРР› Р›РР”Р•Р РЎРўР’Рћ (instance={instance_id})")
            is_leader = True
        except Exception as e:
            logger.error(f"digest: failed to claim leadership: {e}")
    else:
        logger.info(f"digest: РїСЂРѕРїСѓСЃРє (Р»РёРґРµСЂ = {current_leader}, СЏ = {instance_id})")

    if is_leader:
        try:
            set_config('digest_leader_last_seen', str(now))
        except Exception:
            pass
        if int(now) % 300 == 0:
            logger.info(f"digest: active leader = {instance_id}")

    return is_leader


def get_digest_data_hash():
    """Р‘С‹СЃС‚СЂРѕРµ С…РµС€РёСЂРѕРІР°РЅРёРµ РєР»СЋС‡РµРІС‹С… РјРµС‚СЂРёРє РґР°Р№РґР¶РµСЃС‚Р° Р±РµР· С‚СЏР¶РµР»С‹С… SQL Р·Р°РїСЂРѕСЃРѕРІ"""
    try:
        from database import user_cache

        digest_stats = user_cache.get('digest_stats')
        dota_stats = user_cache.get('dota_digest_stats')

        if not digest_stats or not dota_stats:
            return None

        key_data = f"{digest_stats.get('top_growth', '')}{digest_stats.get('top_drop', '')}{digest_stats.get('top_streak', '')}"
        key_data += f"{dota_stats.get('top_mmr_player', '')}{dota_stats.get('top_mmr', 0)}{dota_stats.get('total_active', 0)}"

        import hashlib
        return hashlib.md5(key_data.encode()).hexdigest()

    except Exception as e:
        logger.debug(f"Error creating digest data hash: {e}")
        return None


# ============================================================
# alternate_digest_job - РџРћР›РќРћРЎРўР¬Р® РџР•Р Р•РќР•РЎР•РќРђ РЎР®Р”Рђ
# ============================================================

async def alternate_digest_job(context):
    """Р§РµСЂРµРґРѕРІР°РЅРёРµ СѓС‚СЂРµРЅРЅРµРіРѕ Рё Dota РґР°Р№РґР¶РµСЃС‚РѕРІ (СЂРµРґР°РєС‚РёСЂРѕРІР°РЅРёРµ СЃСѓС‰РµСЃС‚РІСѓСЋС‰РµРіРѕ, СЃРѕР·РґР°РЅРёРµ РЅРѕРІРѕРіРѕ С‚РѕР»СЊРєРѕ РїСЂРё РЅРµРѕР±С…РѕРґРёРјРѕСЃС‚Рё)"""
    from database import (
        get_config,
        get_digest_stats,
        get_dota_week_top,
        set_config,
        update_digest_snapshot,
        user_cache,
    )
    from main import bot_can_delete, is_rate_limited, make_clickable
    try:
        now = time.time()

        # РџСЂРѕРІРµСЂСЏРµРј РіР»РѕР±Р°Р»СЊРЅС‹Р№ rate limit
        if is_rate_limited():
            logger.warning("alternate_digest_job: skipped - bot is rate limited")
            return

        # === SINGLE ACTIVE INSTANCE (leader election via DB) ===
        # РќР° Р±РµСЃРїР»Р°С‚РЅРѕРј Render РјРѕР¶РµС‚ Р±С‹С‚СЊ 2 РєРѕРЅС‚РµР№РЅРµСЂР°. РўРѕР»СЊРєРѕ РѕРґРёРЅ РґРѕР»Р¶РµРЅ СЂРµР°Р»СЊРЅРѕ СЂР°Р±РѕС‚Р°С‚СЊ СЃ РґР°Р№РґР¶РµСЃС‚РѕРј.
        if not await claim_or_check_digest_leader():
            stop_fast_digest_loop()
            return

        # Р‘Р»РѕРєРёСЂРѕРІРєР° РѕС‚ РїР°СЂР°Р»Р»РµР»СЊРЅРѕРіРѕ Р·Р°РїСѓСЃРєР° - РЈР”Р•Р Р–РР’РђР•Рњ Р”Рћ РљРћРќР¦Рђ!
        async with _digest_state_lock:
            last_run = _digest_state_container.get_last_run() or 0
            if now - last_run < 5:
                logger.info(f"alternate_digest_job: РїСЂРѕРїСѓСЃРє (Р·Р°РїСѓС‰РµРЅ {(now - last_run):.1f}СЃ РЅР°Р·Р°Рґ)")
                return
            _digest_state_container.set_last_run(now)

            # РџСЂРѕРІРµСЂСЏРµРј, РЅСѓР¶РЅРѕ Р»Рё РѕР±РЅРѕРІРёС‚СЊ РґР°РЅРЅС‹Рµ РёР· Р‘Р” (СЂР°Р· РІ С‡Р°СЃ)
            if now - _digest_state_container.get_last_data_update() >= DIGEST_DATA_REFRESH_INTERVAL:
                logger.info("alternate_digest_job: РѕР±РЅРѕРІР»СЏРµРј РґР°РЅРЅС‹Рµ РёР· Р‘Р”")
                # РЎР±СЂР°СЃС‹РІР°РµРј РєРµС€ РІ database.py С‡С‚РѕР±С‹ РїРѕР»СѓС‡РёС‚СЊ СЃРІРµР¶РёРµ РґР°РЅРЅС‹Рµ
                from database import user_cache
                user_cache.set('digest_stats', None)
                user_cache.set('dota_digest_stats', None)
                # РћС‡РёС‰Р°РµРј Р»РѕРєР°Р»СЊРЅС‹Р№ РєРµС€ РґР°Р№РґР¶РµСЃС‚РѕРІ
                _digest_state_container.set_digest_data(None)
                _digest_state_container.set_dota_data(None)
                _digest_state_container.set_last_data_update(now)

            # РџРѕР»СѓС‡Р°РµРј ID С‡Р°С‚Р° РґР»СЏ РґР°Р№РґР¶РµСЃС‚Р° (РёР· РєРµС€Р°, РЅРµ Р‘Р”)
            digest_chat_id = _digest_state_container.get_chat_id() or get_config('digest_chat_id')
            if digest_chat_id:
                _digest_state_container.set_chat_id(digest_chat_id)
            logger.info(f"alternate_digest_job: digest_chat_id = {digest_chat_id}")
            if not digest_chat_id:
                logger.info("Р§Р°С‚ РґР»СЏ РґР°Р№РґР¶РµСЃС‚Р° РЅРµ РЅР°СЃС‚СЂРѕРµРЅ")
                return

            bot = context.application.bot

        # Re-sync photo/text state from the single source of truth early
        # (reduces drift between instances after restarts)
        _get_digest_is_photo()  # warms up the in-memory value from config if needed

        now = time.time()

        # === Р—РђР©РРўРђ РћРў Р›РћР–РќРћР™ Р РћРўРђР¦РР РџРћРЎР›Р• Р Р•РЎРўРђР РўРђ ===
        # Р•СЃР»Рё РІ Р‘Р” СѓР¶Рµ РµСЃС‚СЊ alternate_digest_message_id вЂ” РїРѕСЃС‚ СЃСѓС‰РµСЃС‚РІСѓРµС‚,
        # Р·РЅР°С‡РёС‚ РјС‹ РґРѕР»Р¶РЅС‹ Р Р•Р”РђРљРўРР РћР’РђРўР¬ РµРіРѕ, Р° РЅРµ СЃРѕР·РґР°РІР°С‚СЊ РЅРѕРІС‹Р№.
        # created_at=0 РїРѕСЃР»Рµ РёРјРїРѕСЂС‚Р° РјРѕРґСѓР»СЏ Р±РѕР»СЊС€Рµ РЅРµ РґРѕР»Р¶РµРЅ С‚СЂРёРіРіРµСЂРёС‚СЊ should_create_new.
        cache = _digest_cache
        if get_config('alternate_digest_message_id'):
            if not cache.get("created_at") or cache.get("created_at", 0) <= 0:
                cache["created_at"] = time.time() - 30
                logger.info("alternate_digest_job: existing message_id in config, created_at adjusted to prevent false rotation after restart")

# === РЈРњРќРђРЇ РЎРРЎРўР•РњРђ РљР•РЁРР РћР’РђРќРРЇ Р”РђР™Р”Р–Р•РЎРўРћР’ ===
        # Rotation (48h) triggers new post with fresh hero meta banner.
        # Otherwise we edit the existing post.
        should_create_new = False
        should_refresh_data = False

        existing_msg_id = get_config('alternate_digest_message_id')

        # 1. Rotation interval вЂ” create new message and regenerate hero meta
        #    (We delete the old one and create a fresh post with new hero meta)
        if now - cache["created_at"] > cache["rotation_interval"]:
            should_create_new = True
            logger.info("Rotation interval reached, will create new digest")

        # 2. No message_id in config at all (and cache empty) вЂ” first time, create new
        elif cache["text"] is None and not existing_msg_id:
            should_create_new = True
            logger.info("РљРµС€ РїСѓСЃС‚ Рё РЅРµС‚ СЃРѕС…СЂР°РЅС‘РЅРЅРѕРіРѕ СЃРѕРѕР±С‰РµРЅРёСЏ вЂ” СЃРѕР·РґР°С‘Рј РЅРѕРІРѕРµ")

        # 3. Cache expired (TTL) - REFRESH DATA in existing message
        elif now - cache["created_at"] > cache["cache_ttl"]:
            should_refresh_data = True
            logger.info(f"РљРµС€ СѓСЃС‚Р°СЂРµР» ({now - cache['created_at']:.0f}СЃ > {cache['cache_ttl']}СЃ), РѕР±РЅРѕРІР»СЏРµРј РґР°РЅРЅС‹Рµ")

        # 4. Data refreshed - REFRESH DATA in existing message
        elif now - _digest_state_container.get_last_data_refresh() > _data_refresh_interval:
            should_refresh_data = True
            logger.info(f"Р”Р°РЅРЅС‹Рµ РІ Р‘Р” РѕР±РЅРѕРІРёР»РёСЃСЊ ({_data_refresh_interval}СЃ), РѕР±РЅРѕРІР»СЏРµРј")

        # Р•СЃР»Рё РєРµС€ РІР°Р»РёРґРµРЅ - РёСЃРїРѕР»СЊР·СѓРµРј РµРіРѕ Рё РїРµСЂРµРєР»СЋС‡Р°РµРј С‚РёРї
        if not should_create_new and not should_refresh_data:
            # РџРѕСЃР»Рµ СЂРµСЃС‚Р°СЂС‚Р° РєРѕРЅС‚РµР№РЅРµСЂР° in-memory РґР°РЅРЅС‹Рµ РјРѕРіСѓС‚ Р±С‹С‚СЊ РїСѓСЃС‚С‹РјРё,
            # РґР°Р¶Рµ РµСЃР»Рё cache TTL РµС‰С‘ РЅРµ РёСЃС‚С‘Рє (РёР·-Р·Р° safeguard created_at).
            # Р’ СЌС‚РѕРј СЃР»СѓС‡Р°Рµ РїСЂРёРЅСѓРґРёС‚РµР»СЊРЅРѕ РёРґС‘Рј РІ РІРµС‚РєСѓ Р·Р°РіСЂСѓР·РєРё РґР°РЅРЅС‹С….
            current_type = cache.get("type") or "0"
            if current_type == "0":
                if _digest_state_container.get_digest_data() is None:
                    should_refresh_data = True
                    logger.info("Р”Р°РЅРЅС‹Рµ РІ РїР°РјСЏС‚Рё РїСѓСЃС‚С‹ (РЅРѕРІС‹Р№ РєРѕРЅС‚РµР№РЅРµСЂ) вЂ” РїСЂРёРЅСѓРґРёС‚РµР»СЊРЅРѕ РѕР±РЅРѕРІР»СЏРµРј РёР· Р‘Р”")
            else:
                if _digest_state_container.get_dota_data() is None:
                    should_refresh_data = True
                    logger.info("Р”Р°РЅРЅС‹Рµ РІ РїР°РјСЏС‚Рё РїСѓСЃС‚С‹ (РЅРѕРІС‹Р№ РєРѕРЅС‚РµР№РЅРµСЂ) вЂ” РїСЂРёРЅСѓРґРёС‚РµР»СЊРЅРѕ РѕР±РЅРѕРІР»СЏРµРј РёР· Р‘Р”")

        if not should_create_new and not should_refresh_data:
            logger.info(f"РСЃРїРѕР»СЊР·СѓРµРј РєРµС€РёСЂРѕРІР°РЅРЅС‹Р№ РґР°Р№РґР¶РµСЃС‚ (СЃРѕР·РґР°РЅ {now - cache['created_at']:.0f}СЃ РЅР°Р·Р°Рґ)")

            # РџСЂРѕСЃС‚Рѕ РјРµРЅСЏРµРј С‚РёРї РґР»СЏ СЃР»РµРґСѓСЋС‰РµРіРѕ СЂР°Р·Р°
            current_type = cache["type"]
            if current_type == "0":
                next_type = "1"
            else:
                next_type = "0"

            # РџР Р РЎРњР•РќР• РўРРџРђ - Р“Р•РќР•Р РР РЈР•Рњ РўР•РљРЎРў Р”Р›РЇ РќРћР’РћР“Рћ РўРРџРђ (next_type)
            # РћРїСЂРµРґРµР»СЏРµРј СЃР»РµРґСѓСЋС‰РёР№ С‚РёРї (С‡РµСЂРµРґСѓРµРј)
            _digest_state_container.set_current_type(next_type)
            logger.info(f"РџРµСЂРµРєР»СЋС‡Р°РµРј С‚РёРї: {current_type} -> {next_type} (РіРµРЅРµСЂРёСЂСѓРµРј С‚РµРєСЃС‚ РґР»СЏ РЅРѕРІРѕРіРѕ С‚РёРїР°)")
            current_type = next_type  # РСЃРїРѕР»СЊР·СѓРµРј next_type РєР°Рє С‚РµРєСѓС‰РёР№ РґР»СЏ РіРµРЅРµСЂР°С†РёРё С‚РµРєСЃС‚Р°

            # Р¤РѕСЂРјРёСЂСѓРµРј С‚РµРєСЃС‚ РІ Р·Р°РІРёСЃРёРјРѕСЃС‚Рё РѕС‚ С‚РёРїР° (Р±РµР· РѕР±СЂР°С‰РµРЅРёСЏ Рє Р‘Р” - РёСЃРїРѕР»СЊР·СѓРµРј РєРµС€РёСЂРѕРІР°РЅРЅС‹Рµ РґР°РЅРЅС‹Рµ)
            text = None

            if current_type == "0":
                # Р¤РёСЃСЃСѓСЂ-РґР°Р№РґР¶РµСЃС‚ РёР· РєРµС€Р°
                stats = _digest_state_container.get_digest_data()
                if stats:
                    growth_data = stats.get("top_growth", ("None", 0))
                    growth_player = growth_data[0] if len(growth_data) > 0 else "None"
                    growth_pos = growth_data[1] if len(growth_data) > 1 else 0
                    drop_data = stats.get("top_drop", ("None", 0.0))
                    drop_player = drop_data[0] if len(drop_data) > 0 else "None"
                    drop_cm = drop_data[1] if len(drop_data) > 1 else 0.0
                    streak_data = stats.get("top_streak", ("None", 0))
                    streak_player = streak_data[0] if len(streak_data) > 0 else "None"
                    streak_len = streak_data[1] if len(streak_data) > 1 else 0
                    growth_id = stats.get("top_growth_id")
                    drop_id = stats.get("top_drop_id")
                    streak_id = stats.get("top_streak_id")

                    growth_display = make_clickable(growth_player, growth_id)
                    drop_display = make_clickable(drop_player, drop_id)
                    streak_display = make_clickable(streak_player, streak_id)

                    if growth_player and growth_player != "None":
                        growth_part = f"рџ”є{growth_display} +{growth_pos}"
                    else:
                        growth_part = "рџ”євЂ”"

                    if drop_player and drop_player != "None":
                        if drop_cm < 0:
                            drop_part = f"рџ”»{drop_display} {drop_cm:.0f} РЎРњ"
                        else:
                            drop_part = f"рџ”»{drop_display} +{drop_cm:.0f} РЎРњ"
                    else:
                        drop_part = "рџ”»вЂ”"

                    if streak_player and streak_player != "None" and streak_len > 0:
                        streak_part = f" рџЌЂ{streak_display}: {streak_len} РїРѕР±РµРґ РїРѕРґСЂСЏРґ"
                    else:
                        streak_part = " рџЌЂвЂ”"

                    text = f"<b>{growth_part}\n{drop_part}\n{streak_part}</b>\n\nрџ—їР¤РёСЃСЃСѓСЂР° РґР°Р№РґР¶РµСЃС‚."

            else:
                # Dota-РґР°Р№РґР¶РµСЃС‚ РёР· РєРµС€Р°
                mmr_top = _digest_state_container.get_dota_data()
                if not mmr_top:
                    logger.info("РќРµС‚ РґР°РЅРЅС‹С… РґР»СЏ Dota РґР°Р№РґР¶РµСЃС‚Р°, РёСЃРїРѕР»СЊР·СѓРµРј fallback")
                    next_type = "0"
                else:
                    valid_players = [p for p in mmr_top if p.get('week_games', 0) >= 3]
                    if len(valid_players) < 2:
                        logger.info("РќРµРґРѕСЃС‚Р°С‚РѕС‡РЅРѕ РёРіСЂРѕРєРѕРІ РґР»СЏ Dota РґР°Р№РґР¶РµСЃС‚Р°, РёСЃРїРѕР»СЊР·СѓРµРј fallback")
                        next_type = "0"
                    else:
                        valid_players_sorted = sorted(valid_players, key=lambda p: (p.get('week_wins', 0) - (p.get('week_games', 0) - p.get('week_wins', 0)), p.get('week_games', 0)), reverse=True)

                        top_by_net = valid_players_sorted[0]
                        for p in reversed(valid_players_sorted):
                            if p.get('telegram_id') != top_by_net.get('telegram_id'):
                                bottom_by_net = p
                                break
                        else:
                            bottom_by_net = valid_players_sorted[-1]

                        top_player = top_by_net.get('steam_nickname', 'None')
                        top_id = top_by_net.get('telegram_id')
                        top_games = top_by_net.get('week_games', 0)
                        top_wins = top_by_net.get('week_wins', 0)
                        top_losses = top_games - top_wins
                        top_winrate = round((top_wins / top_games * 100), 1) if top_games > 0 else 0

                        bottom_player = bottom_by_net.get('steam_nickname', 'None')
                        bottom_id = bottom_by_net.get('telegram_id')
                        bottom_games = bottom_by_net.get('week_games', 0)
                        bottom_wins = bottom_by_net.get('week_wins', 0)
                        bottom_losses = bottom_games - bottom_wins
                        bottom_winrate = round((bottom_wins / bottom_games * 100), 1) if bottom_games > 0 else 0

                        if top_player and top_player != "None":
                            top_part = f"рџ”є{make_clickable(top_player, top_id)}: {top_wins}W/{top_losses}L в‰€{top_winrate}%"
                        else:
                            top_part = "рџ”євЂ”"

                        if bottom_player and bottom_player != "None":
                            bottom_part = f"рџ”»{make_clickable(bottom_player, bottom_id)}: {bottom_wins}W/{bottom_losses}L в‰€{bottom_winrate}%"
                        else:
                            bottom_part = "рџ”»вЂ”"

                        text = f"<b>{top_part}\n{bottom_part}</b>\n\nрџ¦ћР”РѕС‚Р° Р”Р°Р№РґР¶РµСЃС‚."

            # Р•СЃР»Рё РЅРµ СѓРґР°Р»РѕСЃСЊ СЃРіРµРЅРµСЂРёСЂРѕРІР°С‚СЊ С‚РµРєСЃС‚ - РёСЃРїРѕР»СЊР·СѓРµРј fallback
            if text is None:
                logger.info("РќРµ СѓРґР°Р»РѕСЃСЊ СЃРіРµРЅРµСЂРёСЂРѕРІР°С‚СЊ РґР°Р№РґР¶РµСЃС‚, РёСЃРїРѕР»СЊР·СѓРµРј fallback")
                text = "<b>рџ“Љ Р”Р°РЅРЅС‹Рµ РґР»СЏ РґР°Р№РґР¶РµСЃС‚Р° РїРѕРєР° РЅРµ РґРѕСЃС‚СѓРїРЅС‹</b>\n\nРџРѕРїСЂРѕР±СѓР№С‚Рµ РїРѕР·Р¶Рµ!"
                next_type = "0"

            logger.info(f"Р”Р°Р№РґР¶РµСЃС‚ СЃРіРµРЅРµСЂРёСЂРѕРІР°РЅ РґР»СЏ РїРµСЂРµРєР»СЋС‡РµРЅРёСЏ С‚РёРїР° (С‚РёРї: {current_type}, СЂРµРґР°РєС‚РёСЂСѓРµРј СЃСѓС‰РµСЃС‚РІСѓСЋС‰РµРµ)")

            # next_type РґРѕР»Р¶РµРЅ Р±С‹С‚СЊ С‚РёРїРѕРј РґР»СЏ РЎР›Р•Р”РЈР®Р©Р•Р“Рћ Р·Р°РїСѓСЃРєР° (РѕР±СЂР°С‚РЅС‹Р№ С‚РµРєСѓС‰РµРјСѓ)
            next_type = "0" if current_type == "1" else "1"

            # РћР±РЅРѕРІР»СЏРµРј РєРµС€ РґР»СЏ РЅРѕРІРѕРіРѕ С‚РёРїР° (РЅРѕ РЅРµ С‚СЂРѕРіР°РµРј created_at - С‡С‚РѕР±С‹ СЂРѕС‚Р°С†РёСЏ СЂР°Р±РѕС‚Р°Р»Р° РєРѕСЂСЂРµРєС‚РЅРѕ)
            cache["text"] = text
            cache["type"] = current_type

        # РРЅР°С‡Рµ - РіРµРЅРµСЂРёСЂСѓРµРј РЅРѕРІС‹Р№ РґР°Р№РґР¶РµСЃС‚ РёР»Рё РѕР±РЅРѕРІР»СЏРµРј РґР°РЅРЅС‹Рµ
        else:
            # РџРѕР»СѓС‡Р°РµРј С‚РµРєСѓС‰РёР№ С‚РёРї РґР°Р№РґР¶РµСЃС‚Р° РёР· РїР°РјСЏС‚Рё
            current_type = get_digest_type(None)
            if current_type is None:
                raw_type = get_config('alternate_digest_type')
                if raw_type is not None:
                    current_type = str(raw_type)
                else:
                    current_type = "0"
                _digest_state_container.set_current_type(current_type)
            else:
                current_type = "0"
                _digest_state_container.set_current_type(current_type)

            logger.info(f"alternate_digest_job: current_type = {current_type}, РіРµРЅРµСЂРёСЂСѓРµРј РЅРѕРІС‹Р№ РґР°Р№РґР¶РµСЃС‚")

            # РћРїСЂРµРґРµР»СЏРµРј СЃР»РµРґСѓСЋС‰РёР№ С‚РёРї (С‡РµСЂРµРґСѓРµРј)
            if current_type == "0":
                next_type = "1"
            else:
                next_type = "0"

            # Р¤РѕСЂРјРёСЂСѓРµРј С‚РµРєСЃС‚ РІ Р·Р°РІРёСЃРёРјРѕСЃС‚Рё РѕС‚ С‚РёРїР°
            text = None

            if current_type == "0":
                # Р¤РёСЃСЃСѓСЂ-РґР°Р№РґР¶РµСЃС‚

                # === Р•Р–Р•Р”РќР•Р’РќР«Р™ РЎР‘Р РћРЎ SNAPSHOT ===
                # Р§С‚РѕР±С‹ РІ РґР°Р№РґР¶РµСЃС‚Рµ РєР°Р¶РґС‹Р№ РґРµРЅСЊ РјРѕРіР»Рё РїРѕСЏРІР»СЏС‚СЊСЃСЏ РЅРѕРІС‹Рµ Р»РёРґРµСЂС‹ СЂРѕСЃС‚Р°/РїР°РґРµРЅРёСЏ,
                # СЂР°Р· РІ РєР°Р»РµРЅРґР°СЂРЅС‹Р№ РґРµРЅСЊ РјС‹ РєРѕРїРёСЂСѓРµРј С‚РµРєСѓС‰СѓСЋ fissure РІ digest_fissure.
                from datetime import date
                today = date.today().isoformat()
                last_snapshot = get_config('last_fissure_digest_snapshot')

                if last_snapshot != today:
                    logger.info(f"РќРѕРІС‹Р№ РґРµРЅСЊ ({today}) вЂ” РѕР±РЅРѕРІР»СЏРµРј digest_fissure snapshot РґР»СЏ СЂР°СЃС‡С‘С‚Р° СЃСѓС‚РѕС‡РЅРѕРіРѕ СЂРѕСЃС‚Р°")
                    update_digest_snapshot()
                    user_cache.set('digest_stats', None)      # СЃР±СЂР°СЃС‹РІР°РµРј РєРµС€ РІ database.py
                    _digest_state_container.set_digest_data(None)       # СЃР±СЂР°СЃС‹РІР°РµРј Р»РѕРєР°Р»СЊРЅС‹Р№ РєРµС€ РґР°Р№РґР¶РµСЃС‚Р°
                    set_config('last_fissure_digest_snapshot', today)

                    # Р§РёСЃС‚РёРј fallback-Р·РЅР°С‡РµРЅРёСЏ РїСЂРѕС€Р»С‹С… РїРѕР±РµРґРёС‚РµР»РµР№, С‡С‚РѕР±С‹ РѕРЅРё РЅРµ "Р·Р°Р»РёРїР°Р»Рё"
                    set_config('last_top_growth', None)
                    set_config('last_top_drop', None)
                    set_config('last_top_streak', None)

                # РџСЂРѕРІРµСЂСЏРµРј, РЅСѓР¶РЅРѕ Р»Рё РѕР±РЅРѕРІРёС‚СЊ РґР°РЅРЅС‹Рµ РёР· Р‘Р”
                if _digest_state_container.get_digest_data() is None or now - _digest_state_container.get_last_data_refresh() > _data_refresh_interval:
                    logger.info("РћР±РЅРѕРІР»СЏРµРј РґР°РЅРЅС‹Рµ РґР»СЏ С„РёСЃСЃСѓСЂ-РґР°Р№РґР¶РµСЃС‚Р° РёР· Р‘Р”")
                    stats = get_digest_stats()
                    _digest_state_container.set_digest_data(stats)
                    _digest_state_container.set_last_data_refresh(now)
                else:
                    stats = _digest_state_container.get_digest_data()


                growth_data = stats.get("top_growth", ("None", 0))
                growth_player = growth_data[0] if len(growth_data) > 0 else "None"
                growth_pos = growth_data[1] if len(growth_data) > 1 else 0
                drop_data = stats.get("top_drop", ("None", 0.0))
                drop_player = drop_data[0] if len(drop_data) > 0 else "None"
                drop_cm = drop_data[1] if len(drop_data) > 1 else 0.0
                streak_data = stats.get("top_streak", ("None", 0))
                streak_player = streak_data[0] if len(streak_data) > 0 else "None"
                streak_len = streak_data[1] if len(streak_data) > 1 else 0
                growth_id = stats.get("top_growth_id")
                drop_id = stats.get("top_drop_id")
                streak_id = stats.get("top_streak_id")

                growth_display = make_clickable(growth_player, growth_id)
                drop_display = make_clickable(drop_player, drop_id)
                streak_display = make_clickable(streak_player, streak_id)

                if growth_player and growth_player != "None":
                    growth_part = f"рџ”є{growth_display} +{growth_pos}"
                else:
                    growth_part = "рџ”євЂ”"

                if drop_player and drop_player != "None":
                    if drop_cm < 0:
                        drop_part = f"рџ”»{drop_display} {drop_cm:.0f} РЎРњ"
                    else:
                        drop_part = f"рџ”»{drop_display} +{drop_cm:.0f} РЎРњ"
                else:
                    drop_part = "рџ”»вЂ”"

                if streak_player and streak_player != "None" and streak_len > 0:
                    streak_part = f" рџЌЂ{streak_display}: {streak_len} РїРѕР±РµРґ РїРѕРґСЂСЏРґ"
                else:
                    streak_part = " рџЌЂвЂ”"

                text = f"<b>{growth_part}\n{drop_part}\n{streak_part}</b>\n\nрџ—їР¤РёСЃСЃСѓСЂР° РґР°Р№РґР¶РµСЃС‚."

            else:
                # Dota-РґР°Р№РґР¶РµСЃС‚
                # Р”Р°РЅРЅС‹Рµ РѕР±РЅРѕРІР»СЏСЋС‚СЃСЏ РѕС‚РґРµР»СЊРЅС‹Рј job'РѕРј СЂР°Р· РІ С‡Р°СЃ + РїСЂРё СЃС‚Р°СЂС‚Рµ РєРѕРЅС‚РµР№РЅРµСЂР°.
                # Р—РґРµСЃСЊ РїСЂРѕСЃС‚Рѕ С‡РёС‚Р°РµРј РёР· РєРµС€Р° (get_dota_week_top РїРѕС‡С‚Рё РЅРёРєРѕРіРґР° РЅРµ Р±СѓРґРµС‚ РґРµР»Р°С‚СЊ С‚СЏР¶С‘Р»С‹Р№ SQL,
                # РїРѕС‚РѕРјСѓ С‡С‚Рѕ РєРµС€ РїРѕРґРґРµСЂР¶РёРІР°РµС‚СЃСЏ С‡Р°СЃРѕРІС‹Рј job'РѕРј).
                mmr_top = get_dota_week_top(limit=30)
                _digest_state_container.set_dota_data(mmr_top)

                dota_text = None
                if not mmr_top:
                    logger.info("РќРµС‚ РґР°РЅРЅС‹С… РґР»СЏ Dota РґР°Р№РґР¶РµСЃС‚Р°")
                    # Fallback РЅР° С„РёСЃСЃСѓСЂ-РґР°Р№РґР¶РµСЃС‚
                    next_type = "0"
                else:
                    valid_players = [p for p in mmr_top if p.get('week_games', 0) >= 3]
                    if not valid_players:
                        logger.info("РќРµС‚ РёРіСЂРѕРєРѕРІ СЃ 3+ РёРіСЂР°РјРё РґР»СЏ Dota РґР°Р№РґР¶РµСЃС‚Р°")
                        next_type = "0"
                    else:
                        # Top = best by net (2*wins - games)
                        top_by_net = max(
                            valid_players,
                            key=lambda p: (p.get('week_wins', 0) - (p.get('week_games', 0) - p.get('week_wins', 0)), p.get('week_games', 0))
                        )

                        # Bottom = worst = opposite of best formula (lowest net)
                        # When nets equal вЂ” more games = "worse" (more impressive bad performance)
                        bottom_by_net = min(
                            valid_players,
                            key=lambda p: (p.get('week_wins', 0) - (p.get('week_games', 0) - p.get('week_wins', 0)), -p.get('week_games', 0))
                        )

                        if top_by_net:
                            top_player = top_by_net.get('steam_nickname', 'None')
                            top_id = top_by_net.get('telegram_id')
                            top_games = top_by_net.get('week_games', 0)
                            top_wins = top_by_net.get('week_wins', 0)
                            top_losses = top_games - top_wins
                            top_winrate = round((top_wins / top_games * 100), 1) if top_games > 0 else 0

                            bottom_player = bottom_by_net.get('steam_nickname', 'None')
                            bottom_id = bottom_by_net.get('telegram_id')
                            bottom_games = bottom_by_net.get('week_games', 0)
                            bottom_wins = bottom_by_net.get('week_wins', 0)
                            bottom_losses = bottom_games - bottom_wins
                            bottom_winrate = round((bottom_wins / bottom_games * 100), 1) if bottom_games > 0 else 0

                            if top_player and top_player != "None":
                                top_part = f"рџ”є{make_clickable(top_player, top_id)}: {top_wins}W/{top_losses}L в‰€{top_winrate}%"
                            else:
                                top_part = "рџ”євЂ”"

                            if bottom_player and bottom_player != "None":
                                bottom_part = f"рџ”»{make_clickable(bottom_player, bottom_id)}: {bottom_wins}W/{bottom_losses}L в‰€{bottom_winrate}%"
                            else:
                                bottom_part = "рџ”»вЂ”"

                            dota_text = f"<b>{top_part}\n{bottom_part}</b>\n\nрџ¦ћР”РѕС‚Р° Р”Р°Р№РґР¶РµСЃС‚."

                        if dota_text is None:
                            next_type = "0"

                text = dota_text

            # Р•СЃР»Рё РЅРµ СѓРґР°Р»РѕСЃСЊ СЃРіРµРЅРµСЂРёСЂРѕРІР°С‚СЊ С‚РµРєСЃС‚ - РёСЃРїРѕР»СЊР·СѓРµРј fallback
            if text is None:
                logger.info("РќРµ СѓРґР°Р»РѕСЃСЊ СЃРіРµРЅРµСЂРёСЂРѕРІР°С‚СЊ РґР°Р№РґР¶РµСЃС‚, РёСЃРїРѕР»СЊР·СѓРµРј fallback")
                text = "<b>рџ“Љ Р”Р°РЅРЅС‹Рµ РґР»СЏ РґР°Р№РґР¶РµСЃС‚Р° РїРѕРєР° РЅРµ РґРѕСЃС‚СѓРїРЅС‹</b>\n\nРџРѕРїСЂРѕР±СѓР№С‚Рµ РїРѕР·Р¶Рµ!"
                next_type = "0"

            # === РЎРћРҐР РђРќРЇР•Рњ Р’ РљР•РЁ РўРћР›Р¬РљРћ РџР Р РЎРћР—Р”РђРќРР РќРћР’РћР“Рћ РЎРћРћР‘Р©Р•РќРРЇ ===
            # РџСЂРё РїСЂРѕСЃС‚РѕРј РѕР±РЅРѕРІР»РµРЅРёРё РґР°РЅРЅС‹С… РќР• С‚СЂРѕРіР°РµРј РєРµС€ - С‡С‚РѕР±С‹ СЂРѕС‚Р°С†РёСЏ СЂР°Р±РѕС‚Р°Р»Р° РєРѕСЂСЂРµРєС‚РЅРѕ
            if should_create_new:
                cache["text"] = text
                cache["type"] = current_type
                cache["created_at"] = now
                logger.info(f"Р”Р°Р№РґР¶РµСЃС‚ СЃРіРµРЅРµСЂРёСЂРѕРІР°РЅ Рё СЃРѕС…СЂР°РЅРµРЅ РІ РєРµС€ (С‚РёРї: {current_type}, РЅРѕРІРѕРµ СЃРѕРѕР±С‰РµРЅРёРµ)")
            else:
                logger.info(f"Р”Р°Р№РґР¶РµСЃС‚ СЃРіРµРЅРµСЂРёСЂРѕРІР°РЅ РґР»СЏ РѕР±РЅРѕРІР»РµРЅРёСЏ (С‚РёРї: {current_type}, СЂРµРґР°РєС‚РёСЂСѓРµРј СЃСѓС‰РµСЃС‚РІСѓСЋС‰РµРµ)")

# === РћРўРџР РђР’РљРђ Р”РђР™Р”Р–Р•РЎРўРђ ===
        # РџСЂРѕРїСѓСЃРєР°РµРј СЂРµРґР°РєС‚РёСЂРѕРІР°РЅРёРµ РµСЃР»Рё С‚РµРєСЃС‚ РЅРµ РёР·РјРµРЅРёР»СЃСЏ
        if _digest_state_container.get_last_text() == text:
            logger.debug("РўРµРєСЃС‚ РґР°Р№РґР¶РµСЃС‚Р° РЅРµ РёР·РјРµРЅРёР»СЃСЏ, РїСЂРѕРїСѓСЃРєР°РµРј СЂРµРґР°РєС‚РёСЂРѕРІР°РЅРёРµ")
            return

        # Check if another worker already created a message recently (prevent dual worker spam)
        # Increased to 30s for safety on platforms with multiple containers / slow starts
        last_created_str = get_config('alternate_digest_last_created')
        if last_created_str:
            try:
                last_created = float(last_created_str)
                if now - last_created < 30:  # 30 second cooldown to prevent dual worker spam
                    logger.info(f"РџСЂРѕРїСѓСЃРє - РґСЂСѓРіРѕР№ РІРѕСЂРєРµСЂ СЃРѕР·РґР°Р» РґР°Р№РґР¶РµСЃС‚ {now - last_created:.0f}СЃ РЅР°Р·Р°Рґ")
                    return
            except ValueError:
                pass

        # РџСЂРѕР±СѓРµРј РѕС‚СЂРµРґР°РєС‚РёСЂРѕРІР°С‚СЊ СЃСѓС‰РµСЃС‚РІСѓСЋС‰РµРµ СЃРѕРѕР±С‰РµРЅРёРµ
        last_message_id = get_config('alternate_digest_message_id')
        logger.info(f"alternate_digest_job: last_message_id = {last_message_id}, should_create_new = {should_create_new}")

        # Р”Р»СЏ Р РћРўРђР¦РР (РЅРѕРІРѕРµ СЃРѕРѕР±С‰РµРЅРёРµ) - РїСЂРёРЅСѓРґРёС‚РµР»СЊРЅРѕ СѓРґР°Р»СЏРµРј СЃС‚Р°СЂРѕРµ РїРµСЂРµРґ СЃРѕР·РґР°РЅРёРµРј РЅРѕРІРѕРіРѕ
        if should_create_new and last_message_id:
            logger.info("Р РѕС‚Р°С†РёСЏ - РїСЂРёРЅСѓРґРёС‚РµР»СЊРЅРѕ СѓРґР°Р»СЏРµРј СЃС‚Р°СЂРѕРµ СЃРѕРѕР±С‰РµРЅРёРµ Рё СЃРѕР·РґР°С‘Рј РЅРѕРІРѕРµ")
            try:
                msg_id_int = int(last_message_id)
                if msg_id_int > 0:
                    await bot.delete_message(chat_id=int(digest_chat_id), message_id=msg_id_int)
                    logger.info(f"РЈРґР°Р»РµРЅРѕ СЃС‚Р°СЂРѕРµ СЃРѕРѕР±С‰РµРЅРёРµ {last_message_id}")
            except Exception as e:
                logger.debug(f"РЎС‚Р°СЂРѕРµ СЃРѕРѕР±С‰РµРЅРёРµ СѓР¶Рµ СѓРґР°Р»РµРЅРѕ: {e}")
            set_config('alternate_digest_message_id', None)
            last_message_id = None

        logger.info(f"alternate_digest_job: text = {text[:100]}...")
        edited = False

        # РџСЂРѕРІРµСЂСЏРµРј, СЏРІР»СЏРµС‚СЃСЏ Р»Рё СЃРѕРѕР±С‰РµРЅРёРµ С„РѕС‚Рѕ РёР»Рё С‚РµРєСЃС‚РѕРј
        is_photo_message = _get_digest_is_photo()

        if last_message_id:
            logger.info(f"alternate_digest_job: attempting to edit message {last_message_id}")
            try:
                msg_id_int = int(last_message_id)
                if msg_id_int <= 0:
                    logger.warning(f"Invalid alternate_digest_message_id: {last_message_id}")
                    set_config('alternate_digest_message_id', None)
                    last_message_id = None
                else:
                    # РСЃРїРѕР»СЊР·СѓРµРј editMessageCaption РґР»СЏ С„РѕС‚Рѕ, editMessageText РґР»СЏ С‚РµРєСЃС‚Р°
                    if is_photo_message:
                        await bot.edit_message_caption(
                            chat_id=int(digest_chat_id),
                            message_id=msg_id_int,
                            caption=text,
                            parse_mode="HTML"
                        )
                    else:
                        await bot.edit_message_text(
                            chat_id=int(digest_chat_id),
                            message_id=msg_id_int,
                            text=text,
                            parse_mode="HTML"
                        )
                    logger.info(f"РћР±РЅРѕРІР»С‘РЅ alternate РґР°Р№РґР¶РµСЃС‚ {last_message_id}")
                    edited = True
                    _digest_state_container.set_current_type(next_type)
                    _digest_state_container.set_last_text(text)

                    # Ensure photo state is explicitly recorded via the single source of truth
                    _set_digest_is_photo(is_photo_message)

                    # РћР±РЅРѕРІР»СЏРµРј fast tick СЃ Р°РєС‚СѓР°Р»СЊРЅС‹Рј message_id (always from the authoritative source)
                    start_fast_digest_loop(bot, int(digest_chat_id), msg_id_int, _get_digest_is_photo())
                    try:
                        await bot.pin_chat_message(chat_id=int(digest_chat_id), message_id=msg_id_int, disable_notification=True)
                        logger.info(f"Р—Р°РєСЂРµРїР»С‘РЅ РґР°Р№РґР¶РµСЃС‚ {last_message_id}")
                    except Exception as e:
                        logger.debug(f"РќРµ СѓРґР°Р»РѕСЃСЊ Р·Р°РєСЂРµРїРёС‚СЊ: {e}")
            except (ValueError, TypeError) as e:
                logger.warning(f"Invalid alternate_digest_message_id format: {last_message_id}, error: {e}")
                set_config('alternate_digest_message_id', None)
                last_message_id = None
            except Exception as e:
                is_rate_limit = _telegram_error_contains(e, "429", "too many requests", "retry after")
                logger.info(f"РћС€РёР±РєР° СЂРµРґР°РєС‚РёСЂРѕРІР°РЅРёСЏ: {e}")
                if is_rate_limit:
                    logger.warning("Rate limited by Telegram, skipping edit")
                    _digest_state_container.set_last_text(text)
                    _digest_state_container.set_last_run(0)
                    return
                # Try to detect if message is text or photo and retry once
                if _telegram_error_contains(e, "bad request", "there is no text in the message to edit", "there is no caption in the message to edit"):
                    # Toggle the edit method and retry once
                    if not _digest_state_container.get_edit_retry_done():
                        _digest_state_container.set_edit_retry_done(True)
                        try:
                            if is_photo_message:
                                # Was trying to edit caption, retry with text
                                await bot.edit_message_text(
                                    chat_id=int(digest_chat_id),
                                    message_id=msg_id_int,
                                    text=text,
                                    parse_mode="HTML"
                                )
                                _set_digest_is_photo(False)
                            else:
                                # Was trying to edit text, retry with caption
                                await bot.edit_message_caption(
                                    chat_id=int(digest_chat_id),
                                    message_id=msg_id_int,
                                    caption=text,
                                    parse_mode="HTML"
                                )
                                _set_digest_is_photo(True)
                            logger.info(f"Retry with alternate edit method succeeded for {last_message_id}")
                            edited = True
                            _digest_state_container.set_current_type(next_type)
                            _digest_state_container.set_last_text(text)
                            _digest_state_container.set_edit_retry_done(False)
                            return
                        except Exception as e2:
                            logger.warning(f"Retry with alternate edit method also failed: {e2}")
                            _digest_state_container.set_edit_retry_done(False)
                    logger.warning(f"Bad request for message {last_message_id}, resetting message_id")
                    set_config('alternate_digest_message_id', None)
                    last_message_id = None
                    edited = False
                elif _telegram_error_contains(e, "message to edit not found", "message can't be edited"):
                    logger.info(f"РЎС‚Р°СЂРѕРµ СЃРѕРѕР±С‰РµРЅРёРµ {last_message_id} СѓРґР°Р»РµРЅРѕ, СЃРѕР·РґР°С‘Рј РЅРѕРІРѕРµ")
                    set_config('alternate_digest_message_id', None)
                    last_message_id = None
                    edited = False
                    should_create_new = True
                elif _telegram_error_contains(e, "message is not modified"):
                    logger.info("РЎРѕРѕР±С‰РµРЅРёРµ РЅРµ РёР·РјРµРЅРёР»РѕСЃСЊ, РїСЂРѕРїСѓСЃРєР°РµРј")
                    edited = True
                    _digest_state_container.set_current_type(next_type)
                    _digest_state_container.set_last_text(text)
                    try:
                        await bot.pin_chat_message(chat_id=int(digest_chat_id), message_id=msg_id_int, disable_notification=True)
                        logger.info(f"Р—Р°РєСЂРµРїР»С‘РЅ РґР°Р№РґР¶РµСЃС‚ {last_message_id}")
                    except Exception as e:
                        logger.debug(f"РќРµ СѓРґР°Р»РѕСЃСЊ Р·Р°РєСЂРµРїРёС‚СЊ: {e}")
                elif _telegram_error_contains(e, "there is no text in the message to edit"):
                    # РЎРѕРѕР±С‰РµРЅРёРµ - С„РѕС‚Рѕ, РЅСѓР¶РЅРѕ РёСЃРїРѕР»СЊР·РѕРІР°С‚СЊ editMessageCaption
                    logger.info(f"РЎРѕРѕР±С‰РµРЅРёРµ {last_message_id} - С„РѕС‚Рѕ, РёСЃРїРѕР»СЊР·СѓРµРј editMessageCaption")
                    try:
                        await bot.edit_message_caption(
                            chat_id=int(digest_chat_id),
                            message_id=msg_id_int,
                            caption=text,
                            parse_mode="HTML"
                        )
                        logger.info(f"РћР±РЅРѕРІР»С‘РЅ alternate РґР°Р№РґР¶РµСЃС‚ (caption) {last_message_id}")
                        edited = True
                        _digest_state_container.set_current_type(next_type)
                        _digest_state_container.set_last_text(text)
                        _set_digest_is_photo(True)
                        try:
                            await bot.pin_chat_message(chat_id=int(digest_chat_id), message_id=msg_id_int, disable_notification=True)
                            logger.info(f"Р—Р°РєСЂРµРїР»С‘РЅ РґР°Р№РґР¶РµСЃС‚ {last_message_id}")
                        except Exception as e:
                            logger.debug(f"РќРµ СѓРґР°Р»РѕСЃСЊ Р·Р°РєСЂРµРїРёС‚СЊ: {e}")
                    except Exception as e2:
                        logger.warning(f"РќРµ СѓРґР°Р»РѕСЃСЊ РѕС‚СЂРµРґР°РєС‚РёСЂРѕРІР°С‚СЊ caption: {e2}")
                        set_config('alternate_digest_message_id', None)
                        last_message_id = None
                        edited = False
                        should_create_new = True

        # Р•СЃР»Рё РЅРµ СѓРґР°Р»РѕСЃСЊ СЂРµРґР°РєС‚РёСЂРѕРІР°С‚СЊ - СЃРѕР·РґР°С‘Рј РЅРѕРІРѕРµ
        logger.info(f"alternate_digest_job: edited = {edited}, will create new message")
        if not edited:
            # РџСЂРѕРІРµСЂСЏРµРј Р°РЅС‚Рё-СЃРїР°Рј - Р·Р°С‰РёС‚Р° РѕС‚ РґСѓР±Р»РёСЂРѕРІР°РЅРёСЏ
            # Increased to 5 minutes: if two instances race on startup/restart,
            # the second one will almost always see the recent creation and skip.
            last_created_str = get_config('alternate_digest_last_created')
            last_created = float(last_created_str) if last_created_str and last_created_str.strip() else 0
            time_since_last = now - last_created
            if time_since_last < 300:
                logger.info(f"РџСЂРѕРїСѓСЃРєР°РµРј СЃРѕР·РґР°РЅРёРµ - РїСЂРѕС€Р»Рѕ РІСЃРµРіРѕ {time_since_last:.0f} СЃРµРє СЃ РїРѕСЃР»РµРґРЅРµРіРѕ СЃРѕР·РґР°РЅРёСЏ (last_message_id={last_message_id})")
                return

            # last_message_id = None (Р‘Р” РѕС‚РІР°Р»РёР»Р°СЃСЊ РёР»Рё СЃРѕРѕР±С‰РµРЅРёРµ СѓРґР°Р»РµРЅРѕ) вЂ” РјРѕР¶РµРј СЃРѕР·РґР°РІР°С‚СЊ РЅРѕРІС‹Р№
            # РќРѕ РїСЂРѕРІРµСЂСЏРµРј, С‡С‚Рѕ РєРµС€ РІР°Р»РёРґРµРЅ (С‡С‚РѕР±С‹ РЅРµ РіРµРЅРµСЂРёС‚СЊ Р±Р°РЅРЅРµСЂ РєР°Р¶РґС‹Р№ С‚РёРє)

            # Р“РµРЅРµСЂРёСЂСѓРµРј РіРµСЂРѕ-РјРµС‚Р° Р±Р°РЅРЅРµСЂ РўРћР›Р¬РљРћ РїСЂРё СЃРѕР·РґР°РЅРёРё РЅРѕРІРѕРіРѕ РїРѕСЃС‚Р° (СЂРѕС‚Р°С†РёСЏ 48С‡ РёР»Рё РїРµСЂРІС‹Р№ Р·Р°РїСѓСЃРє)
            hero_meta_banner = None
            if should_create_new:
                try:
                    from hero_meta import get_hero_meta_image
                    try:
                        hero_meta_banner = await asyncio.wait_for(get_hero_meta_image(), timeout=30.0)
                    except asyncio.TimeoutError:
                        logger.warning("Hero meta banner generation timed out after 30 seconds")
                        hero_meta_banner = None
                    if hero_meta_banner:
                        logger.info("Hero meta banner generated for digest")
                    else:
                        logger.warning("Hero meta banner generation returned None")
                except Exception as e:
                    logger.warning(f"Could not generate hero meta banner: {e}")

            # РЈРґР°Р»СЏРµРј СЃС‚Р°СЂРѕРµ СЃРѕРѕР±С‰РµРЅРёРµ РµСЃР»Рё РµСЃС‚СЊ
            if last_message_id:
                try:
                    msg_id_int = int(last_message_id)
                    if msg_id_int > 0:
                        await bot.delete_message(chat_id=int(digest_chat_id), message_id=msg_id_int)
                        logger.info(f"РЈРґР°Р»РµРЅРѕ СЃС‚Р°СЂРѕРµ СЃРѕРѕР±С‰РµРЅРёРµ {last_message_id}")
                except Exception as e:
                    logger.debug(f"РЎС‚Р°СЂРѕРµ СЃРѕРѕР±С‰РµРЅРёРµ СѓР¶Рµ СѓРґР°Р»РµРЅРѕ: {e}")
                set_config('alternate_digest_message_id', None)

            # РЎРѕР·РґР°С‘Рј РЅРѕРІРѕРµ СЃРѕРѕР±С‰РµРЅРёРµ
            try:
                from io import BytesIO
                if hero_meta_banner:
                    photo_buf = BytesIO(hero_meta_banner)
                    photo_buf.name = "hero_meta_banner.png"
                    msg = await bot.send_photo(
                        chat_id=int(digest_chat_id),
                        photo=photo_buf,
                        caption=text,
                        parse_mode="HTML"
                    )
                    logger.info(f"РЎРѕР·РґР°РЅ РЅРѕРІС‹Р№ РґР°Р№РґР¶РµСЃС‚ СЃ С„РѕС‚Рѕ {msg.message_id}")
                    _set_digest_is_photo(True)
                else:
                    msg = await bot.send_message(
                        chat_id=int(digest_chat_id),
                        text=text,
                        parse_mode="HTML"
                    )
                    logger.info(f"РЎРѕР·РґР°РЅ РЅРѕРІС‹Р№ РґР°Р№РґР¶РµСЃС‚ (С‚РµРєСЃС‚) {msg.message_id}")
                    _set_digest_is_photo(False)

                set_config('alternate_digest_message_id', str(msg.message_id))
                set_config('alternate_digest_last_created', str(time.time()))
                _digest_state_container.set_current_type(next_type)
                _digest_state_container.set_last_text(text)
                logger.info(f"alternate_digest_job: saved new message_id = {msg.message_id}")

                # Р—Р°РїСѓСЃРєР°РµРј Р±С‹СЃС‚СЂС‹Р№ 15-СЃРµРєСѓРЅРґРЅС‹Р№ С†РёРєР» (С‚РѕР»СЊРєРѕ РІ РїР°РјСЏС‚Рё)
                start_fast_digest_loop(bot, int(digest_chat_id), msg.message_id, _get_digest_is_photo())

                # Р—Р°РєСЂРµРїР»СЏРµРј РЅРѕРІРѕРµ СЃРѕРѕР±С‰РµРЅРёРµ
                try:
                    # РћС‚РєСЂРµРїР»СЏРµРј Р’РЎР• Р·Р°РєСЂРµРїР»С‘РЅРЅС‹Рµ СЃРѕРѕР±С‰РµРЅРёСЏ РїРµСЂРµРґ Р·Р°РєСЂРµРїР»РµРЅРёРµРј РЅРѕРІРѕРіРѕ
                    # Р­С‚Рѕ СЂРµС€Р°РµС‚ РїСЂРѕР±Р»РµРјСѓ РіРѕРЅРєРё РјРµР¶РґСѓ РІРѕСЂРєРµСЂР°РјРё вЂ” С‚РѕР»СЊРєРѕ РїРѕСЃР»РµРґРЅРёР№ РѕСЃС‚Р°РЅРµС‚СЃСЏ
                    try:
                        await bot.unpin_all_chat_messages(chat_id=int(digest_chat_id))
                        logger.info("РћС‚РєСЂРµРїР»РµРЅС‹ РІСЃРµ РїСЂРµРґС‹РґСѓС‰РёРµ Р·Р°РєСЂРµРїР»С‘РЅРЅС‹Рµ СЃРѕРѕР±С‰РµРЅРёСЏ")
                    except Exception as e:
                        logger.debug(f"РќРµ СѓРґР°Р»РѕСЃСЊ РѕС‚РєСЂРµРїРёС‚СЊ РІСЃРµ СЃРѕРѕР±С‰РµРЅРёСЏ: {e}")

                    await bot.pin_chat_message(chat_id=digest_chat_id, message_id=msg.message_id, disable_notification=True)
                    logger.info(f"Р”Р°Р№РґР¶РµСЃС‚ {msg.message_id} Р·Р°РєСЂРµРїР»С‘РЅ")

                    # РЈРґР°Р»СЏРµРј СЃРёСЃС‚РµРјРЅРѕРµ СЃРѕРѕР±С‰РµРЅРёРµ Рѕ Р·Р°РєСЂРµРїРµ, РµСЃР»Рё РµСЃС‚СЊ РїСЂР°РІР°
                    logger.info(f"РџСЂРѕРІРµСЂРєР° РїСЂР°РІ РЅР° СѓРґР°Р»РµРЅРёРµ СЃРёСЃС‚РµРјРЅРѕРіРѕ СЃРѕРѕР±С‰РµРЅРёСЏ РґР»СЏ chat_id={digest_chat_id}")
                    can_del = await bot_can_delete(bot, digest_chat_id)
                    logger.info(f"bot_can_delete result: {can_del}")
                    if can_del:
                        try:
                            logger.info("РџРѕРїС‹С‚РєР° СѓРґР°Р»РµРЅРёСЏ СЃРёСЃС‚РµРјРЅРѕРіРѕ СЃРѕРѕР±С‰РµРЅРёСЏ Рѕ Р·Р°РєСЂРµРїРµ...")
                            await asyncio.sleep(0.5)
                            logger.info("Р—Р°РґРµСЂР¶РєР° 0.5СЃ Р·Р°РІРµСЂС€РµРЅР°, РёС‰РµРј СЃРёСЃС‚РµРјРЅРѕРµ СЃРѕРѕР±С‰РµРЅРёРµ")

                            # РЎРёСЃС‚РµРјРЅРѕРµ СЃРѕРѕР±С‰РµРЅРёРµ Рѕ Р·Р°РєСЂРµРїРµ РёРјРµРµС‚ message_id = msg.message_id + N (РѕР±С‹С‡РЅРѕ +1 РёР»Рё +2)
                            pin_keywords = ('Р·Р°РєСЂРµРїРёР»', 'Р·Р°РєСЂРµРїРёР»Р°', 'Р·Р°РєСЂРµРїРёР»Рё', 'pinned')
                            found = False
                            for offset in range(1, 6):
                                candidate_id = msg.message_id + offset
                                try:
                                    candidate_msg = await bot.get_message(chat_id=int(digest_chat_id), message_id=candidate_id)
                                    if hasattr(candidate_msg, 'text') and candidate_msg.text:
                                        text_lower = candidate_msg.text.lower().replace('\u200b', '').replace('\u2060', '')
                                        logger.info(f"РџСЂРѕРІРµСЂСЏРµРј msg {candidate_id}: text='{candidate_msg.text[:50]}'")
                                        if any(kw in text_lower for kw in pin_keywords):
                                            await bot.delete_message(chat_id=int(digest_chat_id), message_id=candidate_id)
                                            logger.info(f"вњ… РЈРґР°Р»РµРЅРѕ СЃРёСЃС‚РµРјРЅРѕРµ СЃРѕРѕР±С‰РµРЅРёРµ Рѕ Р·Р°РєСЂРµРїРµ {candidate_id}")
                                            found = True
                                            break
                                except Exception as e:
                                    if _telegram_error_contains(e, "message not found", "message to delete not found"):
                                        logger.debug(f"РЎРѕРѕР±С‰РµРЅРёРµ {candidate_id} РЅРµ РЅР°Р№РґРµРЅРѕ, РїСЂРµРєСЂР°С‰Р°РµРј РїРѕРёСЃРє")
                                        break
                                    else:
                                        logger.debug(f"РћС€РёР±РєР° РїСЂРё РїСЂРѕРІРµСЂРєРµ СЃРѕРѕР±С‰РµРЅРёСЏ {candidate_id}: {e}")
                            if not found:
                                logger.info("РЎРёСЃС‚РµРјРЅРѕРµ СЃРѕРѕР±С‰РµРЅРёРµ Рѕ Р·Р°РєСЂРµРїРµ РЅРµ РЅР°Р№РґРµРЅРѕ СЃСЂРµРґРё СЃР»РµРґСѓСЋС‰РёС… СЃРѕРѕР±С‰РµРЅРёР№")

                        except Exception as e:
                            logger.info(f"РћС€РёР±РєР° РїСЂРё СѓРґР°Р»РµРЅРёРё СЃРёСЃС‚РµРјРЅРѕРіРѕ СЃРѕРѕР±С‰РµРЅРёСЏ: {e}", exc_info=True)
                    else:
                        logger.info("вќЊ РќРµС‚ РїСЂР°РІ РЅР° СѓРґР°Р»РµРЅРёРµ СЃРёСЃС‚РµРјРЅРѕРіРѕ СЃРѕРѕР±С‰РµРЅРёСЏ Рѕ Р·Р°РєСЂРµРїРµ")
                except Exception as e:
                    logger.debug(f"РќРµ СѓРґР°Р»РѕСЃСЊ Р·Р°РєСЂРµРїРёС‚СЊ: {e}")
            finally:
                pass  # Creation flag no longer used (legacy from extraction)

    except Exception as e:
        logger.error(f"РћС€РёР±РєР° РІ alternate_digest_job: {e}", exc_info=True)


# ============================================================
# Internal helpers for photo/text message type (single source of truth)
#
# This is the centralized mechanism for tracking whether the current
# pinned alternate digest message is a photo (with caption) or plain text.
#
# All reads and writes MUST go through these two functions to prevent
# drift between instances, after restarts, or during fast tick <-> job
# interactions.
#
# These helpers do NOT change any user-visible behavior or message content.
# ============================================================

def _get_digest_is_photo() -> bool:
    """Р’РѕР·РІСЂР°С‰Р°РµС‚, СЏРІР»СЏРµС‚СЃСЏ Р»Рё С‚РµРєСѓС‰РµРµ pinned СЃРѕРѕР±С‰РµРЅРёРµ С„РѕС‚Рѕ (True) РёР»Рё С‚РµРєСЃС‚РѕРј (False)."""
    val = _digest_state.get("is_photo_message")
    if val is not None:
        return bool(val)
    try:
        from database import get_config
        return get_config('alternate_digest_is_photo') == 'true'
    except Exception:
        return False


def _set_digest_is_photo(value: bool):
    """РЈСЃС‚Р°РЅР°РІР»РёРІР°РµС‚ С‚РёРї С‚РµРєСѓС‰РµРіРѕ pinned СЃРѕРѕР±С‰РµРЅРёСЏ Рё СЃРѕС…СЂР°РЅСЏРµС‚ РІ config."""
    _digest_state_container.set_is_photo_message(bool(value))
    try:
        from database import set_config
        set_config('alternate_digest_is_photo', 'true' if value else 'false')
    except Exception:
        pass


# ============================================================
# Public helpers for main.py (to avoid direct _digest_state access)
# These are thin wrappers вЂ” behavior is 100% identical.
# ============================================================

def get_digest_type(default: str = "0") -> str:
    """Р’РѕР·РІСЂР°С‰Р°РµС‚ С‚РµРєСѓС‰РёР№ С‚РёРї РґР°Р№РґР¶РµСЃС‚Р° (0 = fissure, 1 = dota)."""
    return _digest_state_container.get_current_type() or default


def set_digest_type(value: str):
    """РЈСЃС‚Р°РЅР°РІР»РёРІР°РµС‚ С‚РµРєСѓС‰РёР№ С‚РёРї РґР°Р№РґР¶РµСЃС‚Р°."""
    _digest_state_container.set_current_type(str(value))


def set_fissure_digest_data(stats: dict):
    """РЎРѕС…СЂР°РЅСЏРµС‚ РґР°РЅРЅС‹Рµ fissure-РґР°Р№РґР¶РµСЃС‚Р° (РІС‹Р·С‹РІР°РµС‚СЃСЏ РёР· refresh_digest_message)."""
    _digest_state_container.set_digest_data(stats)
    _digest_state_container.set_last_data_update(time.time())


def set_dota_last_text(text: str):
    """РљСЌС€РёСЂСѓРµС‚ РїРѕСЃР»РµРґРЅРёР№ С‚РµРєСЃС‚ Dota-РґР°Р№РґР¶РµСЃС‚Р° (С‡С‚РѕР±С‹ РЅРµ СЂРµРґР°РєС‚РёСЂРѕРІР°С‚СЊ РѕРґРёРЅР°РєРѕРІС‹Р№)."""
    _digest_state_container.set_dota_last_text(text)


def get_dota_last_text():
    """Р’РѕР·РІСЂР°С‰Р°РµС‚ РїРѕСЃР»РµРґРЅРёР№ Р·Р°РєРµС€РёСЂРѕРІР°РЅРЅС‹Р№ С‚РµРєСЃС‚ Dota-РґР°Р№РґР¶РµСЃС‚Р°."""
    return _digest_state_container.get_dota_last_text()
