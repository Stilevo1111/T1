import asyncio
import os
import time
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


def _telegram_error_contains(error: Exception, *phrases: str) -> bool:
    """Проверяет, содержит ли текст ошибки любую из переданных фраз (регистронезависимо)."""
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


def refresh_dota_digest_cache():
    """Refreshes Dota digest data in _digest_state.
    Called from the hourly MMR job so the 15-second fast rotation
    always has fresh data to flip between Fissure and Dota.
    """
    try:
        from database import get_dota_week_top
        dota_top = get_dota_week_top(limit=10)
        _digest_state["dota_data"] = dota_top
        _digest_state["last_data_refresh"] = time.time()
        logger.info("Dota digest cache refreshed from MMR job (fast 15s rotation now has fresh data)")
    except Exception as e:
        logger.warning(f"Failed to refresh Dota digest cache: {e}")

_fast_tick_task: asyncio.Task | None = None
_fast_tick_chat_id: int | None = None
_fast_tick_message_id: int | None = None
_fast_tick_is_photo: bool = False


async def _fast_digest_tick(bot):
    """Переключает тип дайджеста каждые 15 секунд, используя только данные в памяти.
    Никаких обращений к БД или config.
    """
    global _fast_tick_message_id, _fast_tick_is_photo

    while True:
        try:
            await asyncio.sleep(15)

            if not _fast_tick_chat_id or not _fast_tick_message_id:
                break

            current_type = _digest_state.get("type") or "0"
            next_type = "1" if current_type == "0" else "0"
            _digest_state["type"] = next_type

            # Генерируем текст для нового типа из закешированных данных (без БД)
            text = _build_digest_text_for_type(next_type)

            if not text:
                continue

            # Re-sync from the single source of truth every tick (helps with multi-instance drift)
            _fast_tick_is_photo = _get_digest_is_photo()

            try:
                is_photo = _fast_tick_is_photo
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
                    # Сообщение исчезло — выходим из fast loop, heavy job пересоздаст
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
    """Генерирует текст дайджеста для указанного типа, используя только данные в памяти."""
    try:
        from main import make_clickable
    except Exception:
        from bot_utils import make_clickable

    if digest_type == "0":
        stats = _digest_state.get("digest_data")
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

        growth_part = f"🔺{growth_display} +{growth_pos}" if growth_player and growth_player != "None" else "🔺—"
        drop_part = f"🔻{drop_display} {drop_cm:.0f} СМ" if drop_player and drop_player != "None" else "🔻—"
        streak_part = f" 🍀{streak_display}: {streak_len} побед подряд" if streak_player and streak_player != "None" and streak_len > 0 else " 🍀—"

        return f"<b>{growth_part}\n{drop_part}\n{streak_part}</b>\n\n🗿Фиссура дайджест.\n\n<b><a href=\"https://seredin999.onrender.com/patch-fissure\">Подробнее на нашем сайте.</a></b>"

    else:
        mmr_top = _digest_state.get("dota_data")
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

        return f"<b>🔺{top_name}: {top_wins}W/{top_losses}L ≈{top_wr}%\n🔻{bottom_name}: {bottom_wins}W/{bottom_losses}L ≈{bottom_wr}%</b>\n\n🎮 Dota дайджест.\n\n<b><a href='https://seredin999.onrender.com/patch-fissure'>Подробнее на нашем сайте.</a></b>"

    return None


def start_fast_digest_loop(bot, chat_id: int, message_id: int, is_photo: bool):
    """Запускает быстрый 15-секундный цикл (только если его ещё нет)."""
    global _fast_tick_task, _fast_tick_chat_id, _fast_tick_message_id, _fast_tick_is_photo

    _fast_tick_chat_id = chat_id
    _fast_tick_message_id = message_id
    _fast_tick_is_photo = _get_digest_is_photo()

    if _fast_tick_task and not _fast_tick_task.done():
        return  # Уже запущен

    _fast_tick_task = asyncio.create_task(_fast_digest_tick(bot))
    logger.info(f"Fast 15s digest tick started (message {message_id})")


def stop_fast_digest_loop():
    """Останавливает быстрый цикл."""
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
    Возвращает True, если текущий инстанс — лидер и может выполнять работу с дайджестом.
    Иначе False (другой контейнер уже лидер).
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
            logger.warning(f"digest: ЗАХВАТИЛ ЛИДЕРСТВО (instance={instance_id})")
            is_leader = True
        except Exception as e:
            logger.error(f"digest: failed to claim leadership: {e}")
    else:
        logger.info(f"digest: пропуск (лидер = {current_leader}, я = {instance_id})")

    if is_leader:
        try:
            set_config('digest_leader_last_seen', str(now))
        except Exception:
            pass
        if int(now) % 300 == 0:
            logger.info(f"digest: active leader = {instance_id}")

    return is_leader


def get_digest_data_hash():
    """Быстрое хеширование ключевых метрик дайджеста без тяжелых SQL запросов"""
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
# alternate_digest_job - ПОЛНОСТЬЮ ПЕРЕНЕСЕНА СЮДА
# ============================================================

async def alternate_digest_job(context):
    """Чередование утреннего и Dota дайджестов (редактирование существующего, создание нового только при необходимости)"""
    from main import is_rate_limited, make_clickable, bot_can_delete
    from database import get_config, set_config, get_digest_stats, get_dota_week_top, update_digest_snapshot, user_cache
    try:
        now = time.time()
        
        # Проверяем глобальный rate limit
        if is_rate_limited():
            logger.warning(f"alternate_digest_job: skipped - bot is rate limited")
            return

        # === SINGLE ACTIVE INSTANCE (leader election via DB) ===
        # На бесплатном Render может быть 2 контейнера. Только один должен реально работать с дайджестом.
        if not await claim_or_check_digest_leader():
            stop_fast_digest_loop()
            return

        # Блокировка от параллельного запуска - УДЕРЖИВАЕМ ДО КОНЦА!
        async with _digest_state_lock:
            last_run = _digest_state.get('last_run', 0)
            if now - last_run < 5:
                logger.info(f"alternate_digest_job: пропуск (запущен {(now - last_run):.1f}с назад)")
                return
            _digest_state['last_run'] = now
            
            # Проверяем, нужно ли обновить данные из БД (раз в час)
            if now - _digest_state.get("last_data_update", 0) >= DIGEST_DATA_REFRESH_INTERVAL:
                logger.info("alternate_digest_job: обновляем данные из БД")
                # Сбрасываем кеш в database.py чтобы получить свежие данные
                from database import user_cache
                user_cache.set('digest_stats', None)
                user_cache.set('dota_digest_stats', None)
                # Очищаем локальный кеш дайджестов
                _digest_state["digest_data"] = None
                _digest_state["dota_data"] = None
                _digest_state["last_data_update"] = now
            
            # Получаем ID чата для дайджеста (из кеша, не БД)
            digest_chat_id = _digest_state.get("chat_id") or get_config('digest_chat_id')
            if digest_chat_id:
                _digest_state["chat_id"] = digest_chat_id
            logger.info(f"alternate_digest_job: digest_chat_id = {digest_chat_id}")
            if not digest_chat_id:
                logger.info("Чат для дайджеста не настроен")
                return
            
            bot = context.application.bot

        # Re-sync photo/text state from the single source of truth early
        # (reduces drift between instances after restarts)
        _get_digest_is_photo()  # warms up the in-memory value from config if needed
        
        now = time.time()
        
        # === ЗАЩИТА ОТ ЛОЖНОЙ РОТАЦИИ ПОСЛЕ РЕСТАРТА ===
        # Если в БД уже есть alternate_digest_message_id — пост существует,
        # значит мы должны РЕДАКТИРОВАТЬ его, а не создавать новый.
        # created_at=0 после импорта модуля больше не должен триггерить should_create_new.
        cache = _digest_cache
        if get_config('alternate_digest_message_id'):
            if not cache.get("created_at") or cache.get("created_at", 0) <= 0:
                cache["created_at"] = time.time() - 30
                logger.info("alternate_digest_job: existing message_id in config, created_at adjusted to prevent false rotation after restart")
        
# === УМНАЯ СИСТЕМА КЕШИРОВАНИЯ ДАЙДЖЕСТОВ ===
        # Rotation (48h) triggers new post with fresh hero meta banner.
        # Otherwise we edit the existing post.
        should_create_new = False
        should_refresh_data = False
        
        existing_msg_id = get_config('alternate_digest_message_id')
        
        # 1. Rotation interval — create new message and regenerate hero meta
        #    (We delete the old one and create a fresh post with new hero meta)
        if now - cache["created_at"] > cache["rotation_interval"]:
            should_create_new = True
            logger.info(f"Rotation interval reached, will create new digest")
        
        # 2. No message_id in config at all (and cache empty) — first time, create new
        elif cache["text"] is None and not existing_msg_id:
            should_create_new = True
            logger.info("Кеш пуст и нет сохранённого сообщения — создаём новое")
        
        # 3. Cache expired (TTL) - REFRESH DATA in existing message
        elif now - cache["created_at"] > cache["cache_ttl"]:
            should_refresh_data = True
            logger.info(f"Кеш устарел ({now - cache['created_at']:.0f}с > {cache['cache_ttl']}с), обновляем данные")
        
        # 4. Data refreshed - REFRESH DATA in existing message
        elif now - _digest_state.get("last_data_refresh", 0) > _data_refresh_interval:
            should_refresh_data = True
            logger.info(f"Данные в БД обновились ({_data_refresh_interval}с), обновляем")
        
        # Если кеш валиден - используем его и переключаем тип
        if not should_create_new and not should_refresh_data:
            # После рестарта контейнера in-memory данные могут быть пустыми,
            # даже если cache TTL ещё не истёк (из-за safeguard created_at).
            # В этом случае принудительно идём в ветку загрузки данных.
            current_type = cache.get("type") or "0"
            data_key = "digest_data" if current_type == "0" else "dota_data"
            if _digest_state.get(data_key) is None:
                should_refresh_data = True
                logger.info("Данные в памяти пусты (новый контейнер) — принудительно обновляем из БД")

        if not should_create_new and not should_refresh_data:
            logger.info(f"Используем кешированный дайджест (создан {now - cache['created_at']:.0f}с назад)")

            # Просто меняем тип для следующего раза
            current_type = cache["type"]
            if current_type == "0":
                next_type = "1"
            else:
                next_type = "0"

            # ПРИ СМЕНЕ ТИПА - ГЕНЕРИРУЕМ ТЕКСТ ДЛЯ НОВОГО ТИПА (next_type)
            # Определяем следующий тип (чередуем)
            _digest_state["type"] = next_type
            logger.info(f"Переключаем тип: {current_type} -> {next_type} (генерируем текст для нового типа)")
            current_type = next_type  # Используем next_type как текущий для генерации текста

            # Формируем текст в зависимости от типа (без обращения к БД - используем кешированные данные)
            text = None

            if current_type == "0":
                # Фиссур-дайджест из кеша
                stats = _digest_state.get("digest_data")
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
                        growth_part = f"🔺{growth_display} +{growth_pos}"
                    else:
                        growth_part = "🔺—"

                    if drop_player and drop_player != "None":
                        if drop_cm < 0:
                            drop_part = f"🔻{drop_display} {drop_cm:.0f} СМ"
                        else:
                            drop_part = f"🔻{drop_display} +{drop_cm:.0f} СМ"
                    else:
                        drop_part = "🔻—"

                    if streak_player and streak_player != "None" and streak_len > 0:
                        streak_part = f" 🍀{streak_display}: {streak_len} побед подряд"
                    else:
                        streak_part = " 🍀—"

                    text = f"<b>{growth_part}\n{drop_part}\n{streak_part}</b>\n\n🗿Фиссура дайджест."

            else:
                # Dota-дайджест из кеша
                mmr_top = _digest_state.get("dota_data")
                if not mmr_top:
                    logger.info("Нет данных для Dota дайджеста, используем fallback")
                    next_type = "0"
                else:
                    valid_players = [p for p in mmr_top if p.get('week_games', 0) >= 3]
                    if len(valid_players) < 2:
                        logger.info("Недостаточно игроков для Dota дайджеста, используем fallback")
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
                            top_part = f"🔺{make_clickable(top_player, top_id)}: {top_wins}W/{top_losses}L ≈{top_winrate}%"
                        else:
                            top_part = "🔺—"

                        if bottom_player and bottom_player != "None":
                            bottom_part = f"🔻{make_clickable(bottom_player, bottom_id)}: {bottom_wins}W/{bottom_losses}L ≈{bottom_winrate}%"
                        else:
                            bottom_part = "🔻—"

                        text = f"<b>{top_part}\n{bottom_part}</b>\n\n🦞Дота Дайджест."

            # Если не удалось сгенерировать текст - используем fallback
            if text is None:
                logger.info("Не удалось сгенерировать дайджест, используем fallback")
                text = "<b>📊 Данные для дайджеста пока не доступны</b>\n\nПопробуйте позже!"
                next_type = "0"

            logger.info(f"Дайджест сгенерирован для переключения типа (тип: {current_type}, редактируем существующее)")

            # next_type должен быть типом для СЛЕДУЮЩЕГО запуска (обратный текущему)
            next_type = "0" if current_type == "1" else "1"

            # Обновляем кеш для нового типа (но не трогаем created_at - чтобы ротация работала корректно)
            cache["text"] = text
            cache["type"] = current_type
        
        # Иначе - генерируем новый дайджест или обновляем данные
        else:
            # Получаем текущий тип дайджеста из памяти
            current_type = _digest_state.get("type")
            if current_type is None:
                raw_type = get_config('alternate_digest_type')
                if raw_type is not None:
                    current_type = str(raw_type)
                else:
                    current_type = "0"
                _digest_state["type"] = current_type
            
            # Определяем следующий тип (чередуем)
            if current_type == "0":
                next_type = "1"
            else:
                next_type = "0"
            
            # Формируем текст в зависимости от типа
            text = None
            if current_type is None:
                raw_type = get_config('alternate_digest_type')
                if raw_type is not None:
                    current_type = str(raw_type)
                else:
                    current_type = "0"
                _digest_state["type"] = current_type
            
            logger.info(f"alternate_digest_job: current_type = {current_type}, генерируем новый дайджест")
            
            # Определяем следующий тип (чередуем)
            if current_type == "0":
                next_type = "1"
            else:
                next_type = "0"
            
            # Формируем текст в зависимости от типа
            text = None
            
            if current_type == "0":
                # Фиссур-дайджест

                # === ЕЖЕДНЕВНЫЙ СБРОС SNAPSHOT ===
                # Чтобы в дайджесте каждый день могли появляться новые лидеры роста/падения,
                # раз в календарный день мы копируем текущую fissure в digest_fissure.
                from datetime import date
                today = date.today().isoformat()
                last_snapshot = get_config('last_fissure_digest_snapshot')

                if last_snapshot != today:
                    logger.info(f"Новый день ({today}) — обновляем digest_fissure snapshot для расчёта суточного роста")
                    update_digest_snapshot()
                    user_cache.set('digest_stats', None)      # сбрасываем кеш в database.py
                    _digest_state["digest_data"] = None       # сбрасываем локальный кеш дайджеста
                    set_config('last_fissure_digest_snapshot', today)

                    # Чистим fallback-значения прошлых победителей, чтобы они не "залипали"
                    set_config('last_top_growth', None)
                    set_config('last_top_drop', None)
                    set_config('last_top_streak', None)

                # Проверяем, нужно ли обновить данные из БД
                if _digest_state.get("digest_data") is None or now - _digest_state.get("last_data_refresh", 0) > _data_refresh_interval:
                    logger.info("Обновляем данные для фиссур-дайджеста из БД")
                    stats = get_digest_stats()
                    _digest_state["digest_data"] = stats
                    _digest_state["last_data_refresh"] = now
                else:
                    stats = _digest_state["digest_data"]
                
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
                    growth_part = f"🔺{growth_display} +{growth_pos}"
                else:
                    growth_part = "🔺—"
                
                if drop_player and drop_player != "None":
                    if drop_cm < 0:
                        drop_part = f"🔻{drop_display} {drop_cm:.0f} СМ"
                    else:
                        drop_part = f"🔻{drop_display} +{drop_cm:.0f} СМ"
                else:
                    drop_part = "🔻—"
                
                if streak_player and streak_player != "None" and streak_len > 0:
                    streak_part = f" 🍀{streak_display}: {streak_len} побед подряд"
                else:
                    streak_part = " 🍀—"
                
                text = f"<b>{growth_part}\n{drop_part}\n{streak_part}</b>\n\n🗿Фиссура дайджест."
            
            else:
                # Dota-дайджест
                # Данные обновляются отдельным job'ом раз в час + при старте контейнера.
                # Здесь просто читаем из кеша (get_dota_week_top почти никогда не будет делать тяжёлый SQL,
                # потому что кеш поддерживается часовым job'ом).
                mmr_top = get_dota_week_top(limit=30)
                _digest_state["dota_data"] = mmr_top
                
                dota_text = None
                if not mmr_top:
                    logger.info("Нет данных для Dota дайджеста")
                    # Fallback на фиссур-дайджест
                    next_type = "0"
                else:
                    valid_players = [p for p in mmr_top if p.get('week_games', 0) >= 3]
                    if not valid_players:
                        logger.info("Нет игроков с 3+ играми для Dota дайджеста")
                        next_type = "0"
                    else:
                        # Top = best by net (2*wins - games)
                        top_by_net = max(
                            valid_players,
                            key=lambda p: (p.get('week_wins', 0) - (p.get('week_games', 0) - p.get('week_wins', 0)), p.get('week_games', 0))
                        )

                        # Bottom = worst = opposite of best formula (lowest net)
                        # When nets equal — more games = "worse" (more impressive bad performance)
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
                                top_part = f"🔺{make_clickable(top_player, top_id)}: {top_wins}W/{top_losses}L ≈{top_winrate}%"
                            else:
                                top_part = "🔺—"
                            
                            if bottom_player and bottom_player != "None":
                                bottom_part = f"🔻{make_clickable(bottom_player, bottom_id)}: {bottom_wins}W/{bottom_losses}L ≈{bottom_winrate}%"
                            else:
                                bottom_part = "🔻—"
                            
                            dota_text = f"<b>{top_part}\n{bottom_part}</b>\n\n🦞Дота Дайджест."
                        
                        if dota_text is None:
                            next_type = "0"
                
                text = dota_text
            
            # Если не удалось сгенерировать текст - используем fallback
            if text is None:
                logger.info("Не удалось сгенерировать дайджест, используем fallback")
                text = "<b>📊 Данные для дайджеста пока не доступны</b>\n\nПопробуйте позже!"
                next_type = "0"
            
            # === СОХРАНЯЕМ В КЕШ ТОЛЬКО ПРИ СОЗДАНИИ НОВОГО СООБЩЕНИЯ ===
            # При простом обновлении данных НЕ трогаем кеш - чтобы ротация работала корректно
            if should_create_new:
                cache["text"] = text
                cache["type"] = current_type
                cache["created_at"] = now
                logger.info(f"Дайджест сгенерирован и сохранен в кеш (тип: {current_type}, новое сообщение)")
            else:
                logger.info(f"Дайджест сгенерирован для обновления (тип: {current_type}, редактируем существующее)")
        
# === ОТПРАВКА ДАЙДЖЕСТА ===
        # Пропускаем редактирование если текст не изменился
        if _digest_state.get("last_text") == text:
            logger.debug("Текст дайджеста не изменился, пропускаем редактирование")
            return

        # Check if another worker already created a message recently (prevent dual worker spam)
        # Increased to 30s for safety on platforms with multiple containers / slow starts
        last_created_str = get_config('alternate_digest_last_created')
        if last_created_str:
            try:
                last_created = float(last_created_str)
                if now - last_created < 30:  # 30 second cooldown to prevent dual worker spam
                    logger.info(f"Пропуск - другой воркер создал дайджест {now - last_created:.0f}с назад")
                    return
            except ValueError:
                pass

        # Пробуем отредактировать существующее сообщение
        last_message_id = get_config('alternate_digest_message_id')
        logger.info(f"alternate_digest_job: last_message_id = {last_message_id}, should_create_new = {should_create_new}")

        # Для РОТАЦИИ (новое сообщение) - принудительно удаляем старое перед созданием нового
        if should_create_new and last_message_id:
            logger.info("Ротация - принудительно удаляем старое сообщение и создаём новое")
            try:
                msg_id_int = int(last_message_id)
                if msg_id_int > 0:
                    await bot.delete_message(chat_id=int(digest_chat_id), message_id=msg_id_int)
                    logger.info(f"Удалено старое сообщение {last_message_id}")
            except Exception as e:
                logger.debug(f"Старое сообщение уже удалено: {e}")
            set_config('alternate_digest_message_id', None)
            last_message_id = None

        logger.info(f"alternate_digest_job: text = {text[:100]}...")
        edited = False

        # Проверяем, является ли сообщение фото или текстом
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
                    # Используем editMessageCaption для фото, editMessageText для текста
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
                    logger.info(f"Обновлён alternate дайджест {last_message_id}")
                    edited = True
                    _digest_state["type"] = next_type
                    _digest_state["last_text"] = text

                    # Ensure photo state is explicitly recorded via the single source of truth
                    _set_digest_is_photo(is_photo_message)

                    # Обновляем fast tick с актуальным message_id (always from the authoritative source)
                    start_fast_digest_loop(bot, int(digest_chat_id), msg_id_int, _get_digest_is_photo())
                    try:
                        await bot.pin_chat_message(chat_id=int(digest_chat_id), message_id=msg_id_int, disable_notification=True)
                        logger.info(f"Закреплён дайджест {last_message_id}")
                    except Exception as e:
                        logger.debug(f"Не удалось закрепить: {e}")
            except (ValueError, TypeError) as e:
                logger.warning(f"Invalid alternate_digest_message_id format: {last_message_id}, error: {e}")
                set_config('alternate_digest_message_id', None)
                last_message_id = None
            except Exception as e:
                is_rate_limit = _telegram_error_contains(e, "429", "too many requests", "retry after")
                logger.info(f"Ошибка редактирования: {e}")
                if is_rate_limit:
                    logger.warning(f"Rate limited by Telegram, skipping edit")
                    _digest_state["last_text"] = text
                    _digest_state["last_run"] = 0
                    return
                # Try to detect if message is text or photo and retry once
                if _telegram_error_contains(e, "bad request", "there is no text in the message to edit", "there is no caption in the message to edit"):
                    # Toggle the edit method and retry once
                    if not _digest_state.get("edit_retry_done"):
                        _digest_state["edit_retry_done"] = True
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
                            _digest_state["type"] = next_type
                            _digest_state["last_text"] = text
                            _digest_state["edit_retry_done"] = False
                            return
                        except Exception as e2:
                            logger.warning(f"Retry with alternate edit method also failed: {e2}")
                            _digest_state["edit_retry_done"] = False
                    logger.warning(f"Bad request for message {last_message_id}, resetting message_id")
                    set_config('alternate_digest_message_id', None)
                    last_message_id = None
                    edited = False
                elif _telegram_error_contains(e, "message to edit not found", "message can't be edited"):
                    logger.info(f"Старое сообщение {last_message_id} удалено, создаём новое")
                    set_config('alternate_digest_message_id', None)
                    last_message_id = None
                    edited = False
                    should_create_new = True
                elif _telegram_error_contains(e, "message is not modified"):
                    logger.info(f"Сообщение не изменилось, пропускаем")
                    edited = True
                    _digest_state["type"] = next_type
                    _digest_state["last_text"] = text
                    try:
                        await bot.pin_chat_message(chat_id=int(digest_chat_id), message_id=msg_id_int, disable_notification=True)
                        logger.info(f"Закреплён дайджест {last_message_id}")
                    except Exception as e:
                        logger.debug(f"Не удалось закрепить: {e}")
                elif _telegram_error_contains(e, "there is no text in the message to edit"):
                    # Сообщение - фото, нужно использовать editMessageCaption
                    logger.info(f"Сообщение {last_message_id} - фото, используем editMessageCaption")
                    try:
                        await bot.edit_message_caption(
                            chat_id=int(digest_chat_id),
                            message_id=msg_id_int,
                            caption=text,
                            parse_mode="HTML"
                        )
                        logger.info(f"Обновлён alternate дайджест (caption) {last_message_id}")
                        edited = True
                        _digest_state["type"] = next_type
                        _digest_state["last_text"] = text
                        _set_digest_is_photo(True)
                        try:
                            await bot.pin_chat_message(chat_id=int(digest_chat_id), message_id=msg_id_int, disable_notification=True)
                            logger.info(f"Закреплён дайджест {last_message_id}")
                        except Exception as e:
                            logger.debug(f"Не удалось закрепить: {e}")
                    except Exception as e2:
                        logger.warning(f"Не удалось отредактировать caption: {e2}")
                        set_config('alternate_digest_message_id', None)
                        last_message_id = None
                        edited = False
                        should_create_new = True

        # Если не удалось редактировать - создаём новое
        logger.info(f"alternate_digest_job: edited = {edited}, will create new message")
        if not edited:
            # Проверяем анти-спам - защита от дублирования
            # Increased to 5 minutes: if two instances race on startup/restart,
            # the second one will almost always see the recent creation and skip.
            last_created_str = get_config('alternate_digest_last_created')
            last_created = float(last_created_str) if last_created_str and last_created_str.strip() else 0
            time_since_last = now - last_created
            if time_since_last < 300:
                logger.info(f"Пропускаем создание - прошло всего {time_since_last:.0f} сек с последнего создания (last_message_id={last_message_id})")
                return

            # last_message_id = None (БД отвалилась или сообщение удалено) — можем создавать новый
            # Но проверяем, что кеш валиден (чтобы не генерить баннер каждый тик)

            # Генерируем геро-мета баннер ТОЛЬКО при создании нового поста (ротация 48ч или первый запуск)
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

            # Удаляем старое сообщение если есть
            if last_message_id:
                try:
                    msg_id_int = int(last_message_id)
                    if msg_id_int > 0:
                        await bot.delete_message(chat_id=int(digest_chat_id), message_id=msg_id_int)
                        logger.info(f"Удалено старое сообщение {last_message_id}")
                except Exception as e:
                    logger.debug(f"Старое сообщение уже удалено: {e}")
                set_config('alternate_digest_message_id', None)

            # Создаём новое сообщение
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
                    logger.info(f"Создан новый дайджест с фото {msg.message_id}")
                    _set_digest_is_photo(True)
                else:
                    msg = await bot.send_message(
                        chat_id=int(digest_chat_id),
                        text=text,
                        parse_mode="HTML"
                    )
                    logger.info(f"Создан новый дайджест (текст) {msg.message_id}")
                    _set_digest_is_photo(False)

                set_config('alternate_digest_message_id', str(msg.message_id))
                set_config('alternate_digest_last_created', str(time.time()))
                _digest_state["type"] = next_type
                _digest_state["last_text"] = text
                logger.info(f"alternate_digest_job: saved new message_id = {msg.message_id}")

                # Запускаем быстрый 15-секундный цикл (только в памяти)
                start_fast_digest_loop(bot, int(digest_chat_id), msg.message_id, _get_digest_is_photo())

                # Закрепляем новое сообщение
                try:
                    # Открепляем ВСЕ закреплённые сообщения перед закреплением нового
                    # Это решает проблему гонки между воркерами — только последний останется
                    try:
                        await bot.unpin_all_chat_messages(chat_id=int(digest_chat_id))
                        logger.info("Откреплены все предыдущие закреплённые сообщения")
                    except Exception as e:
                        logger.debug(f"Не удалось открепить все сообщения: {e}")

                    await bot.pin_chat_message(chat_id=digest_chat_id, message_id=msg.message_id, disable_notification=True)
                    logger.info(f"Дайджест {msg.message_id} закреплён")

                    # Удаляем системное сообщение о закрепе, если есть права
                    logger.info(f"Проверка прав на удаление системного сообщения для chat_id={digest_chat_id}")
                    can_del = await bot_can_delete(bot, digest_chat_id)
                    logger.info(f"bot_can_delete result: {can_del}")
                    if can_del:
                        try:
                            logger.info("Попытка удаления системного сообщения о закрепе...")
                            await asyncio.sleep(0.5)
                            logger.info("Задержка 0.5с завершена, ищем системное сообщение")

                            # Системное сообщение о закрепе имеет message_id = msg.message_id + N (обычно +1 или +2)
                            pin_keywords = ('закрепил', 'закрепила', 'закрепили', 'pinned')
                            found = False
                            for offset in range(1, 6):
                                candidate_id = msg.message_id + offset
                                try:
                                    candidate_msg = await bot.get_message(chat_id=int(digest_chat_id), message_id=candidate_id)
                                    if hasattr(candidate_msg, 'text') and candidate_msg.text:
                                        text_lower = candidate_msg.text.lower().replace('\u200b', '').replace('\u2060', '')
                                        logger.info(f"Проверяем msg {candidate_id}: text='{candidate_msg.text[:50]}'")
                                        if any(kw in text_lower for kw in pin_keywords):
                                            await bot.delete_message(chat_id=int(digest_chat_id), message_id=candidate_id)
                                            logger.info(f"✅ Удалено системное сообщение о закрепе {candidate_id}")
                                            found = True
                                            break
                                except Exception as e:
                                    if _telegram_error_contains(e, "message not found", "message to delete not found"):
                                        logger.debug(f"Сообщение {candidate_id} не найдено, прекращаем поиск")
                                        break
                                    else:
                                        logger.debug(f"Ошибка при проверке сообщения {candidate_id}: {e}")
                            if not found:
                                logger.info("Системное сообщение о закрепе не найдено среди следующих сообщений")

                        except Exception as e:
                            logger.info(f"Ошибка при удалении системного сообщения: {e}", exc_info=True)
                    else:
                        logger.info("❌ Нет прав на удаление системного сообщения о закрепе")
                except Exception as e:
                    logger.debug(f"Не удалось закрепить: {e}")
            finally:
                pass  # Флаг создания больше не используется
        
    except Exception as e:
        logger.error(f"Ошибка в alternate_digest_job: {e}", exc_info=True)


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
    """Возвращает, является ли текущее pinned сообщение фото (True) или текстом (False)."""
    val = _digest_state.get("is_photo_message")
    if val is not None:
        return bool(val)
    try:
        from database import get_config
        return get_config('alternate_digest_is_photo') == 'true'
    except Exception:
        return False


def _set_digest_is_photo(value: bool):
    """Устанавливает тип текущего pinned сообщения и сохраняет в config."""
    _digest_state["is_photo_message"] = bool(value)
    try:
        from database import set_config
        set_config('alternate_digest_is_photo', 'true' if value else 'false')
    except Exception:
        pass


# ============================================================
# Public helpers for main.py (to avoid direct _digest_state access)
# These are thin wrappers — behavior is 100% identical.
# ============================================================

def get_digest_type(default: str = "0") -> str:
    """Возвращает текущий тип дайджеста (0 = fissure, 1 = dota)."""
    return _digest_state.get("type") or default


def set_digest_type(value: str):
    """Устанавливает текущий тип дайджеста."""
    _digest_state["type"] = str(value)


def set_fissure_digest_data(stats: dict):
    """Сохраняет данные fissure-дайджеста (вызывается из refresh_digest_message)."""
    _digest_state["digest_data"] = stats
    _digest_state["last_data_update"] = time.time()


def set_dota_last_text(text: str):
    """Кэширует последний текст Dota-дайджеста (чтобы не редактировать одинаковый)."""
    _digest_state["dota_last_text"] = text


def get_dota_last_text():
    """Возвращает последний закешированный текст Dota-дайджеста."""
    return _digest_state.get("dota_last_text")
