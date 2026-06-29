"""
Модуль модерации: /mute — "молчанка" (кляп) за 10 см фиссуры.

✨ Два способа выдачи:
  СПОСОБ 1: /mute в ответ на сообщение
  СПОСОБ 2: /mute @username

При выдаче:
  ① Проверка: нельзя дать кляп себе
  ② Проверка баланса админа (нужно ≥ 10 см фиссуры)
  ③ Списывается 10 см без упоминания в чате
  ④ Бот пишет: "📢 {админ} дал(а) кляп {жертве}🤐 на 30 секунд!"
  ⑤ Сообщения закляпленного удаляются 30 секунд
  ⑥ Автоматическое снятие кляпа через 30 секунд
"""

import asyncio
import logging
import random
import time
from datetime import datetime, timedelta

from telegram import Update
from telegram.ext import CommandHandler, ContextTypes, MessageHandler

logger = logging.getLogger(__name__)

__all__ = [
    "register_handlers",
]

# ─── Настройки ───────────────────────────────────────────────────────────────
_MUTE_COST_CM = 10          # стоимость в см фиссуры
_MUTE_DURATION_SEC = 30     # длительность кляпа

# Разнообразные смайлы кляпа (без дубликатов)
_GAG_EMOJIS = [
    "🤐", "🔇", "🙊", "🧦", "🍌",
    "🤫", "🔕", "🦷", "🎭", "😶",
    "🤪🔇", "🤭", "🗣️", "🗯️", "💤",
    "🔜", "🙅", "🙆", "🤨",
]

# ─── Хранилища ───────────────────────────────────────────────────────────────
# Заакляпленные: {user_id: datetime_окончания}
_gagged_users: dict[int, datetime] = {}

# Кеш username → (user_id, время_кеширования)
_username_cache: dict[str, tuple[int, datetime]] = {}
_USERNAME_CACHE_TTL = timedelta(hours=1)

# Текущая задача автоснятия кляпа: victim_id → asyncio.Task
_gag_auto_release_tasks: dict[int, asyncio.Task] = {}


# ─── Вспомогательные методы ──────────────────────────────────────────────────

def _pick_gag_emoji(victim_id: int) -> str:
    """Случайный выбор смайла кляпа."""
    return random.choice(_GAG_EMOJIS)


def _get_gag_expiry(user_id: int) -> datetime | None:
    """Возвращает время окончания кляпа или None."""
    expiry = _gagged_users.get(user_id)
    if expiry is None:
        return None
    if datetime.now() >= expiry:
        # Устарел — чистим
        _gagged_users.pop(user_id, None)
        return None
    return expiry


def _is_gagged(user_id: int) -> bool:
    return _get_gag_expiry(user_id) is not None


# ─── Работа с фиссурой ───────────────────────────────────────────────────────

def add_fissure(user_id: int, amount_cm: float) -> None:
    """
    Добавить / отнять фиссуру у пользователя.

    Использует БД напрямую (как остальной бот), поэтому **не** делает flush
    кеша — изменения сразу попадают в базу.
    """
    from database import get_user, update_fissure

    user = get_user(user_id)
    if user is None:
        return

    current = float(user.get("fissure", 0.0))
    new_fissure = max(0.0, current + amount_cm)
    update_fissure(user_id, new_fissure, time.time(), 0)


# ─── Поиск пользователя по @username в чате ──────────────────────────────────

async def get_user_by_username_in_chat(
    chat_id: int,
    username: str,
    context: ContextTypes.DEFAULT_TYPE,
) -> dict | None:
    """
    Найти пользователя Telegram по сокращённому username (без @) среди участников чата.

    Стратегия поиска:
      1. Проверить кеш (username → user_id).
      2. Уточнить через get_chat_member() — пользователь мог переименоваться.
      3. Если в кеше нет — перебрать администраторов чата (bech <= 50, дешево по API).
      4. Если админов мало — опросить участников через get_chat_member до обнаружения.
    """
    username = username.lstrip("@").lower().strip()
    if not username:
        return None

    bot = context.bot

    # ① Кеш
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

    # ② Администраторы — быстрый путь
    try:
        admins = await bot.get_chat_administrators(chat_id)
        for admin in admins:
            u = admin.user
            if u.username and u.username.lower() == username:
                _username_cache[username] = (u.id, datetime.now())
                return {"telegram_id": u.id, "username": u.username}
    except Exception:
        logger.debug(f"get_chat_administrators failed for chat {chat_id}")

    # ③ чтение из БД по username (если бот уже видел такого)
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


# ─── Основная логика выдачи кляпа ───────────────────────────────────────────

async def _do_give_gag(
    admin: dict,
    victim: dict,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> bool:
    """Выдать кляп жертве, списать 10 см фиссуры с админа."""
    admin_id   = admin["telegram_id"]
    victim_id  = victim["telegram_id"]
    chat_id    = update.effective_chat.id
    chat_type  = str(update.effective_chat.type)

    is_self_mute = (admin_id == victim_id)

    # ── 1. Проверка баланса (не списываем, если мутим себя) ─────────────────────
    if not is_self_mute:
        current = get_current_fissure(admin_id)
        if current < _MUTE_COST_CM:
            await context.bot.send_message(
                chat_id,
                f"💸 Недостаточно фиссур! "
                f"Нужно {_MUTE_COST_CM} см, а у тебя только {current:.1f} см."
            )
            try:
                await update.message.delete()
            except Exception:
                pass
            return False

        # ── 2. Списываем фиссуру (только если не мутим себя) ────────────────────
        add_fissure(admin_id, -_MUTE_COST_CM)

    # ── 4. Удаляем команду /mute из чата ────────────────────────────────────
    try:
        await update.message.delete()
    except Exception:
        logger.debug(f"Could not delete /mute command message in {chat_id}", exc_info=True)

    # ── 5. «Кладём» кляп на жертву ─────────────────────────────────────────
    expiry = datetime.now() + timedelta(seconds=_MUTE_DURATION_SEC)
    _gagged_users[victim_id] = expiry

    # ── 6. Анонс в чат (отдельным сообщением, не реплай) ───────────────────
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
        f"👤 {admin_link} дал(а) кляп {gag_emoji} {victim_link} на 30 секунд."
    )
    announce_msg = await context.bot.send_message(
        chat_id=chat_id,
        text=announcement,
        parse_mode="HTML",
    )
    # Удалить анонс тоже через 30 секунд
    try:
        from main import schedule_delete
        schedule_delete(
            context.bot, chat_id, announce_msg.message_id,
            _MUTE_DURATION_SEC, context.job_queue
        )
    except Exception:
        logger.debug("schedule_delete import failed, using asyncio fallback", exc_info=True)
        asyncio.create_task(_delayed_delete(context.bot, chat_id, announce_msg.message_id, _MUTE_DURATION_SEC))

    # ── 6. Запускаем автоснятие ─────────────────────────────────────────────
    _schedule_gag_release(victim_id, chat_id, chat_type, context)

    return True


async def _delayed_delete(bot, chat_id: int, msg_id: int, delay: int) -> None:
    """Fallback: удалить сообщение через delay секунд."""
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
    """Запускает фоновую задачу, которая снимет кляп и уведомит чат."""
    # Отменяем предыдущую задачу, если есть
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
    """Фоновая задача: ждёт истечения кляпа, потом снимает его."""
    expiry = _gagged_users.get(victim_id)
    if not expiry:
        return

    wait = (expiry - datetime.now()).total_seconds()
    if wait > 0:
        await asyncio.sleep(wait)

    # Снимаем кляп
    _gagged_users.pop(victim_id, None)
    _gag_auto_release_tasks.pop(victim_id, None)

    # Уведомляем чат (только в группе/супергруппе)
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
                text=f"🗣 Кляп снят у @{name}",
            )
            # Удаляем уведомление через 10 секунд
            asyncio.create_task(_delayed_delete(
                context.bot, chat_id, notify_msg.message_id, 10
            ))
        except Exception:
            logger.debug(f"Gag release notify failed for {victim_id} in {chat_id}", exc_info=True)


# ─── Фильтр удаления сообщений закляпленных ──────────────────────────────────

GAG_FILTER_FLAG = "mute"

async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Middleware-фильтр: удаляет сообщения от пользователей с активным кляпом."""
    if not update.effective_message:
        return

    user = update.effective_user
    if user is None:
        return

    user_id = user.id
    if not _is_gagged(user_id):
        return

    if await _can_admin_bypass(context, update):
        return

    try:
        await update.effective_message.delete()
    except Exception:
        logger.debug("Failed to delete gagged message", exc_info=True)


async def _can_admin_bypass(
    context: ContextTypes.DEFAULT_TYPE,
    update: Update,
) -> bool:
    """Администраторы могут обходить кляп."""
    try:
        chat_id  = update.effective_chat.id
        user_id  = update.effective_user.id
        member = await context.bot.get_chat_member(chat_id, user_id)
        status  = member.status
        return status in ("creator", "administrator")
    except Exception:
        return False


# ─── Команда /mute ───────────────────────────────────────────────────────────

_MUTE_USAGE = (
    "🤪 <b>Замутить пользователя</b> — цена 10 фиссур.\n"
    "<code>/mute @username</code> или <code>/mute</code> в ответ на его сообщение"
)


async def mute_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик /mute — два способа выдачи кляпа."""
    if not update.message or not update.effective_user:
        return

    chat = update.effective_chat
    if chat.type == "private":
        chat_id = update.effective_chat.id
        await context.bot.send_message(chat_id, "⛔ Команда работает только в группах и супергруппах!")
        try:
            await update.message.delete()
        except Exception:
            pass
        return

    admin_id = update.effective_user.id
    chat_id = update.effective_chat.id

    # ──────────────────────────────────────────────────────────────────────────
    # СПОСОБ 1: /mute в ответ на сообщение
    # ──────────────────────────────────────────────────────────────────────────
    if update.message.reply_to_message:
        victim_tg = update.message.reply_to_message.from_user
        if victim_tg is None:
            await context.bot.send_message(chat_id, "❌ Не удалось определить автора сообщения.")
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

    # ──────────────────────────────────────────────────────────────────────────
    # СПОСОБ 2: /mute @username
    # ──────────────────────────────────────────────────────────────────────────
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

        # No @-аргументов найдено — возможно, забыли @
        await context.bot.send_message(
            chat_id,
            "❌ Укажи username с @, например:\n/mute @username"
        )
        try:
            await update.message.delete()
        except Exception:
            pass
        return

    # Ничего не подошло — справка
    await context.bot.send_message(chat_id, f"❓ {_MUTE_USAGE}", parse_mode="HTML")
    try:
        await update.message.delete()
    except Exception:
        pass


# ─── Вспомогательные проверки ─────────────────────────────────────────────────

def get_current_fissure(user_id: int) -> float:
    """Возвращает текущую фиссуру пользователя (из БД)."""
    try:
        from database import get_user
        user = get_user(user_id)
        if user:
            return float(user.get("fissure", 0.0))
    except Exception:
        logger.debug(f"get_current_fissure error for {user_id}", exc_info=True)
    return 0.0


# ─── Публичный API модуля ─────────────────────────────────────────────────────

def register_handlers(application) -> None:
    """
    Зарегистрировать все обработчики модуля в Application.

    Принимает Application из python-telegram-bot v20.
    """
    # Команда /mute
    application.add_handler(CommandHandler("mute", mute_command))

    # Фильтр сообщений: удаляет сообщения закляпленных
    # block=False → не перехватывает обновление, другие хендлеры continue работать
    application.add_handler(
        MessageHandler(filters=None, callback=on_message, block=False)
    )
