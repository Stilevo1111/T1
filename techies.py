import random
import time
import asyncio
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, InputFile
from telegram.ext import ContextTypes

from bot_utils import make_clickable, record_recent_fissure_roll
from constants import get_banner_path

logger = logging.getLogger(__name__)
BANNER_URL = get_banner_path("techies")
TECHIES_BANNER_URL = BANNER_URL
TECHIES_TIMEOUT_SEC = 15

SUCCESS_PHRASES = [
    "Ха! Сегодня без взрывов. Скучно... но Фиссура цела.",
    "И это всё? Я уже приготовил детонатор... Ладно, живи.",
    "Фух, пронесло. Буквально. Мина не сдетонировала.",
    "Ты либо везучий, либо гений. Скорее первое.",
    "Где мой взрыв? Где бабах?! А, ты угадал... Счастливчик.",
    "Скукота... Я хотел посмотреть на фейерверк.",
    "Ну и где большой бум? А, ты выжил... В следующий раз.",
    "Целая Фиссура — это так скучно. Но ладно, заслужил.",
]

FAIL_PHRASES = [
    "Вот это я понимаю — ИСКУССТВО!",
    "БАБАХ! Ха-ха-ха-ха!",
    "Ой... Ну ты сам это выбрал. Я тут ни при чём.",
    "Я же говорил: не нажимай красную... Или синюю? А, неважно — БУМ.",
    "Ты нажал не туда, и теперь тут всё в дыму.",
    "Взрывчатка заложена, детонатор сработал.",
    "Ха-ха-ха! Ты что, думал там конфетка? Там был СЮРПРИЗ.",
    "Они тебя по кусочкам собирать будут!",
    "Я только разогреваюсь! А ты уже без Фиссуры.",
]

# session_key -> {chat_id, msg_id, user_id, correct_button, start_time, display_username, timeout_task}
_active_techies_sessions: dict[str, dict] = {}


def generate_mines(count: int = 4) -> list[int]:
    """Сгенерировать позиции мин (0/1) для мини-игры Техиес."""
    return [random.randint(1, 10) for _ in range(count)]


def _session_key(chat_id: int, user_id: int) -> str:
    return f"{chat_id}_{user_id}"


def _build_techies_keyboard(user_id: int, correct_button: str, start_time: float) -> InlineKeyboardMarkup:
    ts = int(start_time * 1000)
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🧨 Левая",
                callback_data=f"techies_left_{user_id}_{correct_button}_{ts}",
            ),
            InlineKeyboardButton(
                "🧨 Правая",
                callback_data=f"techies_right_{user_id}_{correct_button}_{ts}",
            ),
        ]
    ])


def _build_mine_text(display_username: str) -> str:
    return (
        f"🎲 {display_username}\n\n"
        "🧨 МИНА ЗАЛОЖЕНА!\n"
        "😈 Скви, Сплин и Спун 🗣️ Угадай, пока не бабахнуло...\n"
        f"⏱️ {TECHIES_TIMEOUT_SEC} секунд до взрыва!\n\n"
        "Одна кнопка сохранит Фиссуру,\n"
        "другая — взорвёт её на кусочки.\n"
        "Выбирай с умом, сапёр..."
    )


def _cancel_timeout_task(session: dict | None) -> None:
    if not session:
        return
    task = session.get("timeout_task")
    if task and not task.done():
        task.cancel()


def _pop_session(chat_id: int, user_id: int) -> dict | None:
    return _active_techies_sessions.pop(_session_key(chat_id, user_id), None)


async def _send_techies_result(bot, chat_id: int, msg_id: int, text: str) -> None:
    media = InputMediaPhoto(media=InputFile(str(TECHIES_BANNER_URL)), caption=text, parse_mode="HTML")
    try:
        await bot.edit_message_media(
            chat_id=chat_id,
            message_id=msg_id,
            media=media,
            reply_markup=None,
        )
        return
    except Exception as e:
        logger.error(f"techies edit_message_media failed: {e}")

    try:
        await bot.edit_message_caption(
            chat_id=chat_id,
            message_id=msg_id,
            caption=text,
            reply_markup=None,
            parse_mode="HTML",
        )
        return
    except Exception as e:
        logger.error(f"techies edit_message_caption failed: {e}")

    try:
        await bot.send_photo(
            chat_id=chat_id,
            photo=str(TECHIES_BANNER_URL),
            caption=text,
            parse_mode="HTML",
        )
    except Exception as e:
        logger.error(f"techies send_photo failed: {e}")


async def _apply_techies_explosion(
    bot, session: dict, record_roll=None
) -> None:
    """Применить результат взрыва Техиес: уменьшить/сохранить фиссуру и отправить ответ."""
    from database import get_user, update_user_field

    user_id = session["user_id"]
    user = get_user(user_id)
    if not user:
        return

    current_fissure = user.get("fissure", 0) or 0
    mines = session.get("mines", generate_mines())
    total_damage = sum(mines)
    new_fissure = max(0.1, current_fissure - total_damage)
    update_user_field(user_id, "fissure", new_fissure)

    username = user.get("username") or str(user_id)
    if record_roll:
        record_roll(user_id, username, -total_damage, new_fissure, cascade=0)

    phrase = random.choice(FAIL_PHRASES)
    text = (
        f"🎲 {session['display_username']}\n\n"
        "💥 БАБАХ!\n"
        f"💣 Скви, Сплин и Спун 🗣️ {phrase}\n\n"
    )
    for i, mine in enumerate(mines, 1):
        text += f"💣 Мина {i} - {mine} см\n"
    text += f"\n📏 {current_fissure:.1f} см → {new_fissure:.1f} см"

    await _send_techies_result(bot, session["chat_id"], session["msg_id"], text)


async def _techies_timeout_worker(bot, session_key: str, record_roll=None) -> None:
    try:
        await asyncio.sleep(TECHIES_TIMEOUT_SEC)
    except asyncio.CancelledError:
        return

    session = _active_techies_sessions.pop(session_key, None)
    if not session:
        return

    logger.info(f"techies timeout fired for {session_key}")
    await _apply_techies_explosion(bot, session, record_roll=record_roll)


def _start_techies_session(
    bot, chat_id: int, user_id: int, msg_id: int, correct_button: str, start_time: float, display_username: str, record_roll=None
) -> dict:
    """Создать сессию мини-игры Техиес (выбрать правильную кнопку, запустить таймаут)."""
    session_key = _session_key(chat_id, user_id)
    _cancel_timeout_task(_active_techies_sessions.get(session_key))

    task = asyncio.create_task(
        _techies_timeout_worker(bot, session_key, record_roll=record_roll),
        name=f"techies_timeout_{chat_id}_{msg_id}",
    )
    _active_techies_sessions[session_key] = {
        "chat_id": chat_id,
        "msg_id": msg_id,
        "user_id": user_id,
        "correct_button": correct_button,
        "start_time": start_time,
        "display_username": display_username,
        "timeout_task": task,
        "mines": generate_mines(),
    }
    logger.info(f"techies session started: {session_key}, msg_id={msg_id}")


async def handle_techies_event(
    bot,
    chat_id,
    user,
    user_obj,
    display_username,
    now,
    main_menu,
    set_last_bot_message,
    schedule_delete,
    update_fissure,
    update_last_message_id,
    job_queue=None,
    record_recent_fissure_roll=None,
) -> None:
    """Обработать запуск мини-игры Техиес (inline-кнопка)."""
    correct_button = random.choice(["left", "right"])
    start_time = time.time()
    current_fissure = user.get("fissure", 0) or 0

    keyboard = _build_techies_keyboard(user_obj.id, correct_button, start_time)
    text = _build_mine_text(display_username)

    msg = await bot.send_photo(
        chat_id=chat_id,
        photo=str(TECHIES_BANNER_URL),
        caption=text,
        reply_markup=keyboard,
        parse_mode="HTML",
    )
    set_last_bot_message(chat_id, user_obj.id, msg.message_id)
    update_fissure(user_obj.id, current_fissure, now, 0, last_message_id=msg.message_id)

    _start_techies_session(
        bot,
        chat_id,
        user_obj.id,
        msg.message_id,
        correct_button,
        start_time,
        display_username,
        record_roll=record_recent_fissure_roll,
    )


async def techies_command(update: ContextTypes.DEFAULT_TYPE, context: ContextTypes.DEFAULT_TYPE):
    """Команда /techies: запустить мини-игру со случайным взрывом/сохранением фиссуры."""
    from database import get_user

    user_id = update.effective_user.id
    user = get_user(user_id)
    if not user:
        await update.message.reply_text("❌ Пользователь не найден")
        return

    correct_button = random.choice(["left", "right"])
    start_time = time.time()
    username = user.get("username")
    display_username = make_clickable(username or update.effective_user.first_name or "Гость", user_id)

    keyboard = _build_techies_keyboard(user_id, correct_button, start_time)
    text = _build_mine_text(display_username)

    msg = await update.message.reply_photo(
        photo=str(TECHIES_BANNER_URL),
        caption=text,
        reply_markup=keyboard,
        parse_mode="HTML",
    )

    _start_techies_session(
        context.bot,
        update.effective_chat.id,
        user_id,
        msg.message_id,
        correct_button,
        start_time,
        display_username,
        record_roll=record_recent_fissure_roll,
    )


async def handle_techies_button(update: ContextTypes.DEFAULT_TYPE, context: ContextTypes.DEFAULT_TYPE, record_recent_fissure_roll=None):
    """Обработать нажатие кнопки в мини-игре Техиес (попал/не попал в мину)."""
    from database import get_user, update_user_field

    query = update.callback_query
    user_id = query.from_user.id
    data = query.data.split("_")

    if len(data) < 5 or data[0] != "techies":
        await query.answer()
        return

    _, button_pressed, initiator_id, correct_button, start_time_str = data[:5]
    initiator_id = int(initiator_id)

    if user_id != initiator_id:
        await query.answer("🧨 Это не твоя мина, бродяга!", show_alert=True)
        return

    session = _pop_session(query.message.chat_id, user_id)
    if not session:
        await query.answer("💥 Мина уже сдетонировала!", show_alert=True)
        return

    _cancel_timeout_task(session)
    await query.answer()

    try:
        start_time = float(start_time_str) / 1000
    except ValueError:
        start_time = session.get("start_time", 0)

    elapsed = time.time() - start_time
    user = get_user(user_id)
    if not user:
        await query.edit_message_text("❌ Ошибка: пользователь не найден")
        return

    current_fissure = user.get("fissure", 0) or 0
    username = query.from_user.username
    display_username = make_clickable(username or query.from_user.first_name or "Гость", user_id)

    if elapsed > TECHIES_TIMEOUT_SEC or button_pressed != correct_button:
        mines = generate_mines()
        total_damage = sum(mines)
        new_fissure = max(0.1, current_fissure - total_damage)
        update_user_field(user_id, "fissure", new_fissure)
        if record_recent_fissure_roll:
            record_recent_fissure_roll(
                user_id, username or str(user_id), -total_damage, new_fissure, cascade=0, event_type="techies"
            )

        phrase = random.choice(FAIL_PHRASES)
        text = (
            f"🎲 {display_username}\n\n"
            "💥 БАБАХ!\n"
            f"💣 Скви, Сплин и Спун 🗣️ {phrase}\n\n"
        )
        for i, mine in enumerate(mines, 1):
            text += f"💣 Мина {i} - {mine} см\n"
        text += f"\n📏 {current_fissure:.1f} см → {new_fissure:.1f} см"
    else:
        phrase = random.choice(SUCCESS_PHRASES)
        text = (
            f"🎲 {display_username}\n\n"
            f"😇 ОБЕЗВРЕЖЕНО!\n💣 Скви, Сплин и Спун 🗣️ {phrase}\n\n"
            f"📏 {current_fissure:.1f} см"
        )
        if record_recent_fissure_roll:
            record_recent_fissure_roll(user_id, username or str(user_id), 0, current_fissure, cascade=0)

    await _send_techies_result(context.bot, query.message.chat_id, query.message.message_id, text)
