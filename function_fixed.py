import logging
import time
import asyncio
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

DOTA_DIGEST_HEADER = "🎮 DOTA ДАЙДЖЕСТ 📊"
DOTA_DIGEST_FOOTER = "🔺 = лучший винрейт за неделю\n🔻 = худший винрейт за неделю\n🔸 = текущий стрик побед"

async def alternate_digest_job(context):
    """Чередование утреннего и Dota дайджестов (редактирование существующего, создание нового только при необходимости)"""
    from main import is_rate_limited, _digest_state_lock, _digest_cache, _digest_state, DIGEST_DATA_REFRESH_INTERVAL, _data_refresh_interval, make_clickable, bot_can_delete
    from database import get_config, set_config, get_digest_stats, get_dota_week_top
    try:
        now = time.time()
        
        # Проверяем глобальный rate limit
        if is_rate_limited():
            logger.warning(f"alternate_digest_job: skipped - bot is rate limited")
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
            
            # При первом запуске после деплоя сбрасываем тип на "0"
            if _digest_state.get("last_data_update") == 0:
                _digest_state["type"] = "0"
                logger.info("alternate_digest_job: сброшен тип на 0 после перезапуска")
            
            logger.info("Запуск alternate_digest_job")
            
            # Получаем ID чата для дайджеста (из кеша, не БД)
            digest_chat_id = _digest_state.get("chat_id") or get_config('digest_chat_id')
            if digest_chat_id:
                _digest_state["chat_id"] = digest_chat_id
            logger.info(f"alternate_digest_job: digest_chat_id = {digest_chat_id}")
            if not digest_chat_id:
                logger.info("Чат для дайджеста не настроен")
                return
            
            bot = context.application.bot
        
        now = time.time()
        
        # === УМНАЯ СИСТЕМА КЕШИРОВАНИЯ ДАЙДЖЕСТОВ ===
        # CREATE NEW MESSAGE only on rotation or empty cache + no existing message
        # EDIT EXISTING when TTL expires or data refreshes
        cache = _digest_cache
        should_create_new = False
        should_refresh_data = False
        
        # 1. Rotation interval (48h) - CREATE NEW MESSAGE
        if now - cache["created_at"] > cache["rotation_interval"]:
            should_create_new = True
            logger.info(f"Время ротации дайджеста ({cache['rotation_interval']}с), создаём новое сообщение")
        
        # 2. Empty cache and no existing message_id - CREATE NEW
        elif cache["text"] is None and not get_config('alternate_digest_message_id'):
            should_create_new = True
            logger.info("Кеш пуст и нет сохранённого сообщения, создаём новое")
        
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

                        players_with_streak = [p for p in valid_players if p.get('week_current_streak', 0) > 0]
                        top_streak_player = max(players_with_streak, key=lambda p: p.get('week_current_streak', 0)) if players_with_streak else None

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

                        streak_player = top_streak_player.get('steam_nickname', 'None') if top_streak_player else 'None'
                        streak_wins = top_streak_player.get('week_current_streak', 0) if top_streak_player else 0
                        streak_id = top_streak_player.get('telegram_id') if top_streak_player else None

                        if top_player and top_player != "None":
                            top_part = f"🔺{make_clickable(top_player, top_id)}: {top_wins}W/{top_losses}L ≈{top_winrate}%"
                        else:
                            top_part = "🔺—"

                        if bottom_player and bottom_player != "None":
                            bottom_part = f"🔻{make_clickable(bottom_player, bottom_id)}: {bottom_wins}W/{bottom_losses}L ≈{bottom_winrate}%"
                        else:
                            bottom_part = "🔻—"

                        if streak_player and streak_player != "None" and streak_wins > 0:
                            streak_part = f"🔸{make_clickable(streak_player, streak_id)}: {streak_wins}"
                        else:
                            streak_part = "🔸—"

                        text = f"<b>{top_part}\n{bottom_part}\n{streak_part}</b>\n\n🦞Дота Дайджест."

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
                # Проверяем, нужно ли обновить данные из БД
                if _digest_state.get("dota_data") is None or now - _digest_state.get("last_data_refresh", 0) > _data_refresh_interval:
                    logger.info("Обновляем данные для Dota-дайджеста из БД")
                    mmr_top = get_dota_week_top(limit=10)
                    _digest_state["dota_data"] = mmr_top
                    _digest_state["last_data_refresh"] = now
                else:
                    mmr_top = _digest_state["dota_data"]
                
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
                        valid_players_sorted = sorted(valid_players, key=lambda p: (p.get('week_wins', 0) - (p.get('week_games', 0) - p.get('week_wins', 0)), p.get('week_games', 0)), reverse=True)
                        
                        if len(valid_players_sorted) >= 2:
                            top_by_net = valid_players_sorted[0]
                            for p in reversed(valid_players_sorted):
                                if p.get('telegram_id') != top_by_net.get('telegram_id'):
                                    bottom_by_net = p
                                    break
                            else:
                                bottom_by_net = valid_players_sorted[-1]
                        elif len(valid_players_sorted) == 1:
                            top_by_net = valid_players_sorted[0]
                            bottom_by_net = valid_players_sorted[0]
                        else:
                            top_by_net = None
                            bottom_by_net = None
                        
                        players_with_streak = [p for p in valid_players if p.get('week_current_streak', 0) > 0]
                        top_streak_player = max(players_with_streak, key=lambda p: p.get('week_current_streak', 0)) if players_with_streak else None
                        
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
                            
                            streak_player = top_streak_player.get('steam_nickname', 'None') if top_streak_player else 'None'
                            streak_wins = top_streak_player.get('week_current_streak', 0) if top_streak_player else 0
                            streak_id = top_streak_player.get('telegram_id') if top_streak_player else None
                            
                            if top_player and top_player != "None":
                                top_part = f"🔺{make_clickable(top_player, top_id)}: {top_wins}W/{top_losses}L ≈{top_winrate}%"
                            else:
                                top_part = "🔺—"
                            
                            if bottom_player and bottom_player != "None":
                                bottom_part = f"🔻{make_clickable(bottom_player, bottom_id)}: {bottom_wins}W/{bottom_losses}L ≈{bottom_winrate}%"
                            else:
                                bottom_part = "🔻—"
                            
                            if streak_player and streak_player != "None" and streak_wins > 0:
                                streak_part = f"🔸{make_clickable(streak_player, streak_id)}: {streak_wins}"
                            else:
                                streak_part = "🔸—"
                            
                            dota_text = f"<b>{top_part}\n{bottom_part}\n{streak_part}</b>\n\n🦞Дота Дайджест."
                        
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
        last_created_str = get_config('alternate_digest_last_created')
        if last_created_str:
            try:
                last_created = float(last_created_str)
                if now - last_created < 5:  # 5 second cooldown to prevent dual worker spam
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
        is_photo_message = _digest_state.get("is_photo_message", False)

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
                error_str = str(e).lower()
                is_rate_limit = "429" in error_str or "too many requests" in error_str or "retry after" in error_str
                logger.info(f"Ошибка редактирования: {e}")
                if is_rate_limit:
                    logger.warning(f"Rate limited by Telegram, skipping edit")
                    _digest_state["last_text"] = text
                    _digest_state["last_run"] = 0
                    return
                if "bad request" in error_str:
                    logger.warning(f"Bad request for message {last_message_id}, resetting message_id")
                    set_config('alternate_digest_message_id', None)
                    last_message_id = None
                    edited = False
                elif "message to edit not found" in error_str or "message can't be edited" in error_str:
                    logger.info(f"Старое сообщение {last_message_id} удалено, создаём новое")
                    set_config('alternate_digest_message_id', None)
                    last_message_id = None
                elif "message is not modified" in error_str:
                    logger.info(f"Сообщение не изменилось, пропускаем")
                    edited = True
                    _digest_state["type"] = next_type
                    _digest_state["last_text"] = text
                    try:
                        await bot.pin_chat_message(chat_id=int(digest_chat_id), message_id=msg_id_int, disable_notification=True)
                        logger.info(f"Закреплён дайджест {last_message_id}")
                    except Exception as e:
                        logger.debug(f"Не удалось закрепить: {e}")
                elif "there is no text in the message to edit" in error_str:
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
                        _digest_state["is_photo_message"] = True
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

        # Если не удалось редактировать - создаём новое
        logger.info(f"alternate_digest_job: edited = {edited}, will create new message")
        if not edited:
            # Генерируем геро-мета баннер
            hero_meta_banner = None
            try:
                from hero_meta import get_hero_meta_image
                import asyncio
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

            # Проверяем анти-спам
            if last_message_id is not None:
                # Есть старое состояние — используем 60-секундный check
                last_created_str = get_config('alternate_digest_last_created')
                last_created = float(last_created_str) if last_created_str and last_created_str.strip() else 0
                time_since_last = now - last_created
                if time_since_last < 60:
                    logger.info(f"Пропускаем - прошло всего {time_since_last:.0f} сек с последнего создания")
                    return
            else:
                # last_message_id = None — старое сообщение не найдено в БД
                # Сбрасываем last_created чтобы не обойти анти-спам, и ВЫХОДИМ
                # Новое сообщение создастся только когда основной цикл (с editing) снова попробует
                # и не найдёт редактируемого сообщения — а это будет после очередного тика, на новых данных
                stale_ts = get_config('alternate_digest_last_created') or "0"
                try:
                    if now - float(stale_ts) < 120:
                        set_config('alternate_digest_last_created', "0")
                except (ValueError, TypeError):
                    pass
                logger.info("last_message_id = None, пропускаем создание (ждём следующего тика)")
                return

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
                    _digest_state["is_photo_message"] = True
                else:
                    msg = await bot.send_message(
                        chat_id=int(digest_chat_id),
                        text=text,
                        parse_mode="HTML"
                    )
                    logger.info(f"Создан новый дайджест (текст) {msg.message_id}")
                    _digest_state["is_photo_message"] = False

                set_config('alternate_digest_message_id', str(msg.message_id))
                set_config('alternate_digest_last_created', str(time.time()))
                _digest_state["type"] = next_type
                _digest_state["last_text"] = text
                logger.info(f"alternate_digest_job: saved new message_id = {msg.message_id}")

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
                                    if "message not found" in str(e).lower() or "message to delete not found" in str(e).lower():
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

# =====================
# ROLL SYSTEM
# =====================
