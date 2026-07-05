import asyncio
import json
import logging
import os
import time

from bot_utils import _telegram_error_contains

logger = logging.getLogger(__name__)


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
            "cache_ttl": 1200,  # 20 минут
            "rotation_interval": 172800,
            "data_hash": None,
            "last_data_check": 0,
        }
        self.last_data_refresh = 0
        self.data_refresh_interval = 1200  # 20 минут между обновлениями данных
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

    def get_last_hero_meta_refresh(self):
        return self.state.get("last_hero_meta_refresh", 0)

    def set_last_hero_meta_refresh(self, value):
        self.state["last_hero_meta_refresh"] = value

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
HERO_META_REFRESH_INTERVAL = 3600  # 1 hour (fallback, only used on new message)

# =====================================================
# Digest cache - invalidate to force refresh on next job run
# Called from fissure.py after each roll to ensure fresh data
# =====================================================

def invalidate_digest_cache():
    """Сбрасывает кеш digest_stats чтобы следующий alternate_digest_job запросил свежие данные."""
    import database
    database.user_cache.delete_key('digest_stats')
    _digest_state_container.set_digest_data(None)
    logger.info("Digest cache invalidated (will refresh on next job run)")


# =====================================================
# Digest cache refresh (hourly, for combined Fissure + Dota display)
# =====================================================


def refresh_dota_digest_cache():
    """Refreshes Dota digest data in _digest_state.
    Called from the hourly MMR job to keep combined digest fresh.
    """
    try:
        from database import get_dota_week_top
        dota_top = get_dota_week_top(limit=10)
        _digest_state_container.set_dota_data(dota_top)
        _digest_state_container.mark_data_refreshed()
        logger.info("Dota digest cache refreshed from MMR job")
    except Exception as e:
        logger.warning(f"Failed to refresh Dota digest cache: {e}")




def _build_digest_text_for_type(digest_type: str) -> str | None:
    """Генерирует объединённый текст дайджеста (Fissure + Dota) в одном сообщении."""
    try:
        from main import make_clickable
    except Exception:
        from bot_utils import make_clickable

    parts = []

    # Dota digest
    mmr_top = _digest_state_container.get_dota_data()
    if mmr_top:
        valid_players = [p for p in mmr_top if p.get('week_games', 0) >= 1]
        if len(valid_players) >= 2:
            top_by_net = max(
                valid_players,
                key=lambda p: (p.get('week_wins', 0) - (p.get('week_games', 0) - p.get('week_wins', 0)), p.get('week_games', 0))
            )

            bottom_by_net = min(
                valid_players,
                key=lambda p: (p.get('week_wins', 0) - (p.get('week_games', 0) - p.get('week_wins', 0)), -p.get('week_games', 0))
)

            top_name = make_clickable(top_by_net.get('steam_nickname') or top_by_net.get('username'), top_by_net.get('telegram_id'))
            bottom_name = make_clickable(bottom_by_net.get('steam_nickname') or bottom_by_net.get('username'), bottom_by_net.get('telegram_id'))

            top_games = top_by_net.get('week_games', 0)
            top_wins = top_by_net.get('week_wins', 0)
            top_wr = round((top_wins / top_games * 100), 1) if top_games > 0 else 0

            bottom_games = bottom_by_net.get('week_games', 0)
            bottom_wins = bottom_by_net.get('week_wins', 0)
            bottom_wr = round((bottom_wins / bottom_games * 100), 1) if bottom_games > 0 else 0

            parts.append(f"📈{top_name} {top_wins}W/{top_games-top_wins}L ≈{top_wr}%\n")
            parts.append(f"📉{bottom_name} {bottom_wins}W/{bottom_games-bottom_wins}L ≈{bottom_wr}%\n")
        else:
            parts.append("📈—\n")
            parts.append("📉—\n")

        parts.append("\n")

    # Fissure digest
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

        growth_display = make_clickable(growth_player, stats.get("top_growth_id")) if growth_player and growth_player != "None" else "—"
        drop_display = make_clickable(drop_player, stats.get("top_drop_id")) if drop_player and drop_player != "None" else "—"
        streak_display = make_clickable(streak_player, stats.get("top_streak_id")) if streak_player and streak_player != "None" and streak_len > 0 else "—"

        parts.append(f"🔺{growth_display} +{growth_pos} см\n" if growth_player and growth_player != "None" and growth_pos > 0 else "🔺—\n")
        parts.append(f"🔻{drop_display} -{abs(drop_cm):.0f} см\n" if drop_player and drop_player != "None" and drop_cm < 0 else "🔻—\n")
        parts.append(f"🍀{streak_display} {streak_len} побед подряд\n" if streak_len > 0 else "🍀—\n")
    else:
        parts.append("🔺—\n")
        parts.append("🔻—\n")
        parts.append("🍀—\n")

    parts.append("\n\n🔷<a href=\"https://seredin999.onrender.com/patch-fissure\">Подробнее на сайте</a>")
    return "".join(parts)


def start_fast_digest_loop(bot, chat_id: int, message_id: int, is_photo: bool):
    """Fast tick disabled - digest now updates via alternative_digest_job (40min interval)."""
    pass


def stop_fast_digest_loop():
    """Fast tick disabled."""
    pass

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

    from database import get_config, set_config

    try:
        current_leader = get_config('digest_leader_id')
        last_seen_str = get_config('digest_leader_last_seen')
        last_seen = float(last_seen_str) if last_seen_str else 0
    except Exception:
        current_leader = None
        last_seen = 0

    is_leader = False

    if current_leader == instance_id:
        is_leader = True
    elif not current_leader or (now - last_seen > LEADER_TIMEOUT):
        # Try to claim leadership
        set_config('digest_leader_id', instance_id)
        set_config('digest_leader_last_seen', str(now))
        is_leader = True
        logger.warning(f"digest: ЗАХВАТИЛ ЛИДЕРСТВО (instance={instance_id})")
    else:
        logger.info(f"digest: пропуск (лидер = {current_leader}, я = {instance_id})")

    if is_leader:
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
        key_data += f"{dota_stats.get('top_winrate', '')}{dota_stats.get('bottom_winrate', '')}{dota_stats.get('top_streak', '')}"

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
    from database import (
        get_config,
        get_digest_stats,
        get_dota_week_top,
        set_config,
        update_digest_snapshot,
        user_cache,
    )
    from main import bot_can_delete, is_rate_limited
    try:
        
        # === ВОССТАНОВЛЕНИЕ СОСТОЯНИЯ ДАЙДЖЕСТА ПОСЛЕ ДЕПЛОЯ ===
        saved_last_text = get_config('alternate_digest_last_text')
        if saved_last_text and _digest_state_container.get_last_text() is None:
            _digest_state_container.set_last_text(saved_last_text)
            logger.info(f"alternate_digest_job: restored last_text from DB after deploy")

        saved_digest_data = get_config('digest_fissure_data')
        if saved_digest_data and _digest_state_container.get_digest_data() is None:
            try:
                data = json.loads(saved_digest_data)
                _digest_state_container.set_digest_data(data)
                _digest_state_container.set_last_data_refresh(time.time())
                logger.info("alternate_digest_job: restored fissure digest data from DB")
            except Exception as e:
                logger.debug(f"Could not parse saved digest data: {e}")

        now = time.time()

        # Проверяем глобальный rate limit
        if is_rate_limited():
            logger.warning("alternate_digest_job: skipped - bot is rate limited")
            return

        # === SINGLE ACTIVE INSTANCE (leader election via DB) ===
        # На бесплатном Render может быть 2 контейнера. Только один должен реально работать с дайджестом.
        if not await claim_or_check_digest_leader():
            stop_fast_digest_loop()
            return

        # Блокировка от параллельного запуска - только для критических секций
        async with _digest_state_lock:
            last_run = _digest_state_container.get_last_run() or 0
            if now - last_run < 5:
                logger.info(f"alternate_digest_job: пропуск (запущен {(now - last_run):.1f}с назад)")
                return
            _digest_state_container.set_last_run(now)

            # Проверяем, нужно ли обновить данные из БД (раз в час)
            if now - _digest_state_container.get_last_data_update() >= DIGEST_DATA_REFRESH_INTERVAL:
                logger.info("alternate_digest_job: обновляем данные из БД")
                # Сбрасываем кеш в database.py чтобы получить свежие данные
                from database import user_cache
                user_cache.delete_key('digest_stats')
                user_cache.delete_key('dota_digest_stats')
                # Очищаем локальный кеш дайджестов
                _digest_state_container.set_digest_data(None)
                _digest_state_container.set_dota_data(None)
                _digest_state_container.set_last_data_update(now)

            # Получаем ID чата для дайджеста (из кеша, не БД)
            digest_chat_id = _digest_state_container.get_chat_id() or get_config('digest_chat_id')
            if digest_chat_id:
                _digest_state_container.set_chat_id(digest_chat_id)
            logger.info(f"alternate_digest_job: digest_chat_id = {digest_chat_id}")
            if not digest_chat_id:
                logger.info("Чат для дайджеста не настроен")
                return

# Release lock before network operations - acquire only for state updates
        bot = context.application.bot

        now = time.time()

        # === ЗАЩИТА ОТ ЛОЖНОЙ РОТАЦИИ ПОСЛЕ РЕСТАРТА ===
        # Если в БД уже есть alternate_digest_message_id — пост существует,
        # значит мы должны РЕДАКТИРОВАТЬ его, а не создавать новый.
        # created_at=0 после импорта модуля больше не должен триггерить should_create_new.
        cache = _digest_cache
        msg_id = get_config('alternate_digest_message_id')
        if msg_id:
            if not cache.get("created_at") or cache.get("created_at", 0) <= 0:
                cache["created_at"] = time.time() - 30
                logger.info("alternate_digest_job: existing message_id in config, created_at adjusted to prevent false rotation after restart")

        # === УМНАЯ СИСТЕМА КЕШИРОВАНИЯ ДАЙДЖЕСТОВ ===
        should_create_new = False
        should_refresh_data = False

        existing_msg_id = msg_id

        # 1. Rotation interval — create new message and regenerate hero meta
        #    (We delete the old one and create a fresh post with new hero meta)
        if now - cache["created_at"] > cache["rotation_interval"]:
            should_create_new = True
            logger.info("Rotation interval reached, will create new digest")

        # 2. No message_id in config — create new message
        elif not existing_msg_id:
            should_create_new = True
            logger.info("Нет сохранённого сообщения — создаём новое")

        # 3. Cache expired (TTL) - REFRESH DATA in existing message
        elif now - cache["created_at"] > cache["cache_ttl"]:
            should_refresh_data = True
            logger.info(f"Кеш устарел ({now - cache['created_at']:.0f}с > {cache['cache_ttl']}с), обновляем данные")

        # 4. Data refreshed - REFRESH DATA in existing message
        elif now - _digest_state_container.get_last_data_refresh() > _data_refresh_interval:
            should_refresh_data = True
            logger.info(f"Данные в БД обновились ({_data_refresh_interval}с), обновляем")

        # Проверяем, является ли сообщение фото или текстом
        is_photo_message = _get_digest_is_photo()

        # Если кеш валиден - используем его и обновляем объединённый дайджест
        if not should_create_new and not should_refresh_data:
            logger.info(f"Используем кешированный дайджест (создан {now - cache['created_at']:.0f}с назад)")

            # Генерируем объединённый текст (Fissure + Dota)
            text = _build_digest_text_for_type("0")
            if not text:
                text = "<b>📊 Данные для дайджеста пока не доступны</b>\n\nПопробуйте позже!"

            next_type = "0"

            # Try to edit existing message with correct method for message type
            if existing_msg_id and int(existing_msg_id) > 0:
                try:
                    if is_photo_message:
                        await bot.edit_message_caption(
                            chat_id=int(digest_chat_id),
                            message_id=int(existing_msg_id),
                            caption=text,
                            parse_mode="HTML"
                        )
                    else:
                        await bot.edit_message_text(
                            chat_id=int(digest_chat_id),
                            message_id=int(existing_msg_id),
                            text=text,
                            parse_mode="HTML"
                        )
                    logger.info(f"Updated cached digest message {existing_msg_id}")
                    return
                except Exception as e:
                    logger.info(f"Failed to edit cached message, creating new: {e}")
                    set_config('alternate_digest_message_id', None)
                    should_create_new = True
            else:
                should_create_new = True

        # Иначе - генерируем новый дайджест или обновляем данные
        else:
            logger.info("Генерируем новый или обновляем существующий дайджест")

            # === ЕЖЕДНЕВНЫЙ СБРОС SNAPSHOT ===
            # Чтобы в дайджесте каждый день могли появляться новые лидеры роста/падения,
            # раз в календарный день мы копируем текущую fissure в digest_fissure.
            from datetime import date
            today = date.today().isoformat()
            last_snapshot = get_config('last_fissure_digest_snapshot')

            if last_snapshot != today:
                logger.info(f"Новый день ({today}) — обновляем digest_fissure snapshot для расчёта суточного роста")
                update_digest_snapshot()
                user_cache.delete('digest_stats')
                _digest_state_container.set_digest_data(None)
                set_config('last_fissure_digest_snapshot', today)
                set_config('last_top_growth', None)
                set_config('last_top_drop', None)
                set_config('last_top_streak', None)

                # СБРОС: daily_best_growth обнуляем для нового дня
                logger.info(f"Сбрасываем daily_best_growth до 0 для нового дня")
                from database import Database
                db_local = Database()
                db_local.execute_query("UPDATE users SET daily_best_growth = 0 WHERE in_chat = TRUE")

            # Проверяем, нужно ли обновить данные из БД (раз в час или они пусты)
            if _digest_state_container.get_digest_data() is None or now - _digest_state_container.get_last_data_refresh() > _data_refresh_interval:
                logger.info("Обновляем данные для дайджеста из БД")
                _digest_state_container.set_digest_data(get_digest_stats())
                _digest_state_container.set_last_data_refresh(now)

            # То же для Dota данных
            if _digest_state_container.get_dota_data() is None:
                logger.info("Обновляем Dota данные для дайджеста из БД")
                _digest_state_container.set_dota_data(get_dota_week_top(limit=30))
            if _digest_state_container.get_dota_data() is None:
                logger.info("Dota данные пусты, пробуем get_dota_week_top_from_db")
                from database import get_dota_week_top_from_db
                _digest_state_container.set_dota_data(get_dota_week_top_from_db(limit=30))

            # Генерируем объединённый текст
            text = _build_digest_text_for_type("0")
            if not text:
                text = "<b>📊 Данные для дайджеста пока не доступны</b>\n\nПопробуйте позже!"

            next_type = "0"

            # === СОХРАНЯЕМ В КЕШ ПРИ СОЗДАНИИ НОВОГО СООБЩЕНИЯ ===
            if should_create_new:
                cache["text"] = text
                cache["type"] = next_type
                cache["created_at"] = now
                logger.info("Дайджест сгенерирован и сохранен в кеш (новое сообщение)")
            else:
                logger.info("Дайджест сгенерирован для обновления (редактируем существующее)")

        # === ОТПРАВКА ДАЙДЖЕСТА ===
        # Пропускаем редактирование если текст не изменился
        if _digest_state_container.get_last_text() == text:
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
                    _digest_state_container.set_current_type(next_type)
                    _digest_state_container.set_last_text(text)
                    set_config('alternate_digest_last_text', text)
                    if _digest_state_container.get_digest_data():
                        set_config('digest_fissure_data', json.dumps(_digest_state_container.get_digest_data()))

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
                elif _telegram_error_contains(e, "message to edit not found", "message can't be edited", "there is no message to edit"):
                    logger.info(f"Старое сообщение {last_message_id} удалено, создаём новое")
                    set_config('alternate_digest_message_id', None)
                    last_message_id = None
                    edited = False
                    should_create_new = True
                elif _telegram_error_contains(e, "message is not modified"):
                    logger.info("Сообщение не изменилось, пропускаем")
                    edited = True
                    _digest_state_container.set_current_type(next_type)
                    _digest_state_container.set_last_text(text)
                    set_config('alternate_digest_last_text', text)
                    if _digest_state_container.get_digest_data():
                        set_config('digest_fissure_data', json.dumps(_digest_state_container.get_digest_data()))
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
                        _digest_state_container.set_current_type(next_type)
                        _digest_state_container.set_last_text(text)
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
            original_msg_id = None
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

            # Генерируем геро-мета баннер (раз в 12 часов или при новом дайджесте)
            hero_meta_banner = None
            need_hero_meta = should_create_new or now - _digest_state_container.get_last_hero_meta_refresh() > 12 * 3600
            
            if need_hero_meta:
                try:
                    from hero_meta import get_hero_meta_image, clear_hero_meta_cache
                    if should_create_new:
                        clear_hero_meta_cache()
                    hero_meta_banner = await asyncio.wait_for(get_hero_meta_image(), timeout=90.0)
                    if hero_meta_banner:
                        set_config('last_hero_meta_update', int(now))
                        _digest_state_container.set_last_hero_meta_refresh(now)
                        logger.info("Hero meta banner generated for digest")
                        # Сохраняем оригинальный ID до попытки редактирования
                        original_msg_id = last_message_id
                        # Если баннер готов и сообщение существует - обновляем фото в существующем сообщении
                        if last_message_id:
                            try:
                                from io import BytesIO
                                from telegram import InputMediaPhoto
                                photo_buf = BytesIO(hero_meta_banner)
                                photo_buf.name = "hero_meta_banner.png"
                                await bot.edit_message_media(
                                    chat_id=int(digest_chat_id),
                                    message_id=int(last_message_id),
                                    media=InputMediaPhoto(media=photo_buf, caption=text, parse_mode="HTML")
                                )
                                logger.info(f"Обновлён баннер в существующем дайджесте {last_message_id}")
                                _set_digest_is_photo(True)
                                edited = True
                                _digest_state_container.set_current_type(next_type)
                                _digest_state_container.set_last_text(text)
                                set_config('alternate_digest_last_text', text)
                                if _digest_state_container.get_digest_data():
                                    set_config('digest_fissure_data', json.dumps(_digest_state_container.get_digest_data()))
                                start_fast_digest_loop(bot, int(digest_chat_id), int(last_message_id), True)
                                try:
                                    await bot.pin_chat_message(chat_id=int(digest_chat_id), message_id=int(last_message_id), disable_notification=True)
                                except Exception:
                                    pass
                                return
                            except Exception as e:
                                logger.warning(f"Не удалось обновить медиа в существующем сообщении: {e}")
                                try:
                                    await bot.edit_message_caption(
                                        chat_id=int(digest_chat_id),
                                        message_id=int(last_message_id),
                                        caption=text,
                                        parse_mode="HTML"
                                    )
                                    logger.info(f"Обновлён caption в существующем дайджесте {last_message_id}")
                                    _set_digest_is_photo(True)
                                    edited = True
                                    _digest_state_container.set_current_type(next_type)
                                    _digest_state_container.set_last_text(text)
                                    set_config('alternate_digest_last_text', text)
                                    if _digest_state_container.get_digest_data():
                                        set_config('digest_fissure_data', json.dumps(_digest_state_container.get_digest_data()))
                                    start_fast_digest_loop(bot, int(digest_chat_id), int(last_message_id), True)
                                    try:
                                        await bot.pin_chat_message(chat_id=int(digest_chat_id), message_id=int(last_message_id), disable_notification=True)
                                    except Exception:
                                        pass
                                    return
                                except Exception as e2:
                                    logger.warning(f"Не удалось обновить caption, создаём новое: {e2}")
                                    should_create_new = True
                                    set_config('alternate_digest_message_id', None)
                                    last_message_id = None
                    else:
                        logger.info("Hero meta banner skipped (no data)")
                except Exception as e:
                    logger.warning(f"Could not generate hero meta banner: {e}")
                    hero_meta_banner = None

            # Удаляем старое сообщение если есть
            if original_msg_id:
                try:
                    msg_id_int = int(original_msg_id)
                    if msg_id_int > 0:
                        await bot.delete_message(chat_id=int(digest_chat_id), message_id=msg_id_int)
                        logger.info(f"Удалено старое сообщение {original_msg_id}")
                except Exception as e:
                    logger.debug(f"Старое сообщение уже удалено: {e}")
                set_config('alternate_digest_message_id', None)

# Создаём новое сообщение
            try:
                from io import BytesIO
                if hero_meta_banner:
                    photo_buf = BytesIO(hero_meta_banner)
                    photo_buf.name = "hero_meta_banner.png"
                    for attempt in range(3):
                        try:
                            msg = await bot.send_photo(
                                chat_id=int(digest_chat_id),
                                photo=photo_buf,
                                caption=text,
                                parse_mode="HTML"
                            )
                            logger.info(f"Создан новый дайджест с фото {msg.message_id}")
                            _set_digest_is_photo(True)
                            break
                        except Exception as e:
                            if attempt < 2 and ("TimedOut" in str(type(e).__name__) or "timeout" in str(e).lower()):
                                logger.warning(f"send_photo timeout, retry {attempt + 1}/3")
                                await asyncio.sleep(2)
                                photo_buf.seek(0)
                                continue
                            raise
                else:
                    msg = await bot.send_message(
                        chat_id=int(digest_chat_id),
                        text=text,
                        parse_mode="HTML",
                        disable_web_page_preview=True
                    )
                    logger.info(f"Создан новый дайджест (текст) {msg.message_id}")
                    _set_digest_is_photo(False)

                set_config('alternate_digest_message_id', str(msg.message_id))
                set_config('alternate_digest_last_created', str(time.time()))
                _digest_state_container.set_current_type(next_type)
                _digest_state_container.set_last_text(text)
                set_config('alternate_digest_last_text', text)
                if _digest_state_container.get_digest_data():
                    set_config('digest_fissure_data', json.dumps(_digest_state_container.get_digest_data()))
                logger.info(f"alternate_digest_job: saved new message_id = {msg.message_id}")

                # Запускаем быстрый 15-секундный цикл (только в памяти)
                start_fast_digest_loop(bot, int(digest_chat_id), msg.message_id, _get_digest_is_photo())

                # Закрепляем новое сообщение
                try:
                    # Открепляем только старое сообщение дайджеста (если оно отличается от нового)
                    # ⚠️ БЫЛО: unpin_all_chat_messages — снимало ВСЕ закрепы в чате (правила, анонсы и т.д.)
                    if last_message_id and str(last_message_id) != str(msg.message_id):
                        try:
                            await bot.unpin_chat_message(
                                chat_id=int(digest_chat_id),
                                message_id=int(last_message_id)
                            )
                            logger.info(f"Откреплено старое сообщение дайджеста {last_message_id}")
                        except Exception as e:
                            logger.debug(f"Не удалось открепить старый дайджест: {e}")

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
                pass  # Creation flag no longer used (legacy from extraction)

    except Exception as e:
        logger.error(f"Ошибка в alternate_digest_job: {e}", exc_info=True)
        # Fallback: ensure cache is preserved for next attempt
        saved_last_text = get_config('alternate_digest_last_text')
        if saved_last_text and _digest_state_container.get_last_text() is None:
            _digest_state_container.set_last_text(saved_last_text)
            logger.info("alternate_digest_job: preserved last_text in cache after error")


async def morning_digest_job(context):
    """Утренний дайджест в 9:00 MSK — удаляет старый пост, сбрасывает hero meta кеш и создаёт новый"""
    from database import (
        get_config,
        get_digest_stats,
        get_dota_week_top,
        set_config,
        update_digest_snapshot,
        user_cache,
    )
    from main import is_rate_limited
    from hero_meta import clear_hero_meta_cache

    try:
        if is_rate_limited():
            logger.warning("morning_digest_job: skipped - bot is rate limited")
            return

        if not await claim_or_check_digest_leader():
            logger.info("morning_digest_job: skipped - not leader")
            return

        digest_chat_id = get_config('digest_chat_id')
        if not digest_chat_id:
            logger.info("morning_digest_job: no digest_chat_id configured")
            return

        bot = context.application.bot
        old_msg_id = get_config('alternate_digest_message_id')

        # Удаляем старое сообщение если есть
        if old_msg_id:
            try:
                msg_id_int = int(old_msg_id)
                if msg_id_int > 0:
                    await bot.delete_message(chat_id=int(digest_chat_id), message_id=msg_id_int)
                    logger.info(f"morning_digest_job: удалён старый дайджест {old_msg_id}")
            except Exception as e:
                logger.debug(f"morning_digest_job: старое сообщение уже удалено: {e}")
            set_config('alternate_digest_message_id', None)
            _digest_state_container.set_last_hero_meta_refresh(0)

        # Сбрасываем кеш hero meta чтобы взять свежие данные
        clear_hero_meta_cache()
        logger.info("morning_digest_job: hero meta cache cleared")

        # Принудительно создаём новый дайджест
        await alternate_digest_job(context)

    except Exception as e:
        logger.error(f"Ошибка в morning_digest_job: {e}", exc_info=True)


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
    _digest_state_container.set_is_photo_message(bool(value))
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
    return _digest_state_container.get_current_type() or default


def set_digest_type(value: str):
    """Устанавливает текущий тип дайджеста."""
    _digest_state_container.set_current_type(str(value))


def set_fissure_digest_data(stats: dict):
    """Сохраняет данные fissure-дайджеста (вызывается из refresh_digest_message)."""
    _digest_state_container.set_digest_data(stats)
    _digest_state_container.set_last_data_update(time.time())


def set_dota_last_text(text: str):
    """Кэширует последний текст Dota-дайджеста (чтобы не редактировать одинаковый)."""
    _digest_state_container.set_dota_last_text(text)


def get_dota_last_text():
    """Возвращает последний закешированный текст Dota-дайджеста."""
    return _digest_state_container.get_dota_last_text()
