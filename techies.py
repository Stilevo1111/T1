import random
import time
import asyncio
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from telegram.ext import ContextTypes

from bot_utils import make_clickable

logger = logging.getLogger(__name__)

BANNER_URL = "https://i.ibb.co/PzzFJwwk/Gemini-Generated-Image-e3k1zhe3k1zhe3k1.png"
TECHIES_BANNER_URL = BANNER_URL

SUCCESS_PHRASES = [
    "«Ха! Сегодня без взрывов. Скучно... но Фиссура цела 😮‍💨»",
    "«И это всё? Я уже приготовил детонатор... Ладно, живи 🧨»",
    "«Фух, пронесло. Буквально. Мина не сдетонировала 🧨»",
    "«Ты либо везучий, либо гений. Скорее первое 😏»",
    "«Где мой взрыв? Где бабах?! А, ты угадал... Счастливчик 🍀»",
    "«Скукота... Я хотел посмотреть на фейерверк 💥😒»",
    "«Ну и где большой бум? А, ты выжил... В следующий раз 🧨»",
    "«Целая Фиссура — это так скучно. Но ладно, заслужил 😤»",
]

FAIL_PHRASES = [
    "«Вот это я понимаю — ИСКУССТВО!»",
    "«БАБАХ! Ха-ха-ха-ха! 🧨💥»",
    "«Ой... Ну ты сам это выбрал. Я тут ни при чём 🤷‍♂️💥»",
    "«Я же говорил: не нажимай красную... Или синюю? А, неважно — БУМ 💣»",
    "«Ты нажал не туда, и теперь тут всё в дыму 💸»",
    "«Взрывчатка заложена, детонатор сработал 💔»",
    "«Ха-ха-ха! Ты что, думал там конфетка? Там был СЮРПРИЗ 🎉🧨»",
    "«Они тебя по кусочкам собирать будут! 💀»",
    "«Я только разогреваюсь! А ты уже без Фиссуры 🔥»",
]

_active_techies_sessions = {}

def generate_mines(count: int = 4) -> list[int]:
    return [random.randint(1, 10) for _ in range(count)]

async def _techies_timeout_fallback(bot, chat_id, msg_id, user_id, display_username, start_time, correct_button):
    """Fallback timeout handler using asyncio.sleep instead of job_queue"""
    await asyncio.sleep(15)
    
    session_key = f"{chat_id}_{user_id}"
    if session_key not in _active_techies_sessions:
        return
    
    del _active_techies_sessions[session_key]
    
    from database import get_user, update_fissure
    user = get_user(user_id)
    if not user:
        return
    
    current_fissure = user.get("fissure", 0) or 0
    mines = generate_mines()
    total_damage = sum(mines)
    
    new_fissure = max(0.1, current_fissure - total_damage)
    update_fissure(user_id, new_fissure, time.time(), 0)
    
    phrase = random.choice(FAIL_PHRASES)
    
    text = (
        f"🎲 {display_username}\n\n"
        "💥 БАБАХ!\n"
        f"😈 Techies: {phrase}\n\n"
    )
    for i, mine in enumerate(mines, 1):
        text += f"💣 Мина {i} - {mine} см\n"
    text += f"\n📏 {current_fissure:.1f} см → {new_fissure:.1f} см"
    
    try:
        await bot.edit_message_media(
            chat_id=chat_id,
            message_id=msg_id,
            media=InputMediaPhoto(media=TECHIES_BANNER_URL, caption=text, parse_mode="HTML"),
            reply_markup=None
        )
    except Exception as e:
        logger.error(f"_techies_timeout_fallback edit_message_media failed: {e}")
        try:
            await bot.edit_message_caption(
                chat_id=chat_id,
                message_id=msg_id,
                caption=text,
                reply_markup=None,
                parse_mode="HTML"
            )
        except Exception as e2:
            logger.error(f"_techies_timeout_fallback edit_message_caption also failed: {e2}")

async def _techies_timeout_job(context):
    data = context.job.data
    chat_id = data['chat_id']
    msg_id = data['msg_id']
    user_id = data['user_id']
    display_username = data['display_username']
    start_time = data['start_time']
    correct_button = data['correct_button']
    
    session_key = f"{chat_id}_{user_id}"
    if session_key in _active_techies_sessions:
        del _active_techies_sessions[session_key]
    
    from database import get_user, update_fissure
    user = get_user(user_id)
    if not user:
        return
    
    current_fissure = user.get("fissure", 0) or 0
    mines = generate_mines()
    total_damage = sum(mines)
    
    new_fissure = max(0.1, current_fissure - total_damage)
    update_fissure(user_id, new_fissure, time.time(), 0)
    
    phrase = random.choice(FAIL_PHRASES)
    
    text = (
        f"🎲 {display_username}\n\n"
        "💥 БАБАХ!\n"
        f"😈 Techies: {phrase}\n\n"
    )
    for i, mine in enumerate(mines, 1):
        text += f"💣 Мина {i} - {mine} см\n"
    text += f"\n📏 {current_fissure:.1f} см → {new_fissure:.1f} см"
    
    bot = context.application.bot
    try:
        await bot.edit_message_media(
            chat_id=chat_id,
            message_id=msg_id,
            media=InputMediaPhoto(media=TECHIES_BANNER_URL, caption=text, parse_mode="HTML"),
            reply_markup=None
        )
    except Exception as e:
        logger.error(f"edit_message_media failed: {e}, trying edit_message_caption")
        try:
            await bot.edit_message_caption(
                chat_id=chat_id,
                message_id=msg_id,
                caption=text,
                reply_markup=None,
                parse_mode="HTML"
            )
        except Exception as e2:
            logger.error(f"edit_message_caption also failed: {e2}")

async def handle_techies_event(bot, chat_id, user, user_obj, display_username, now, main_menu, set_last_bot_message, schedule_delete, update_fissure, update_last_message_id, job_queue=None):
    correct_button = random.choice(["left", "right"])
    start_time = time.time()
    
    session_key = f"{chat_id}_{user_obj.id}"
    _active_techies_sessions[session_key] = True
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🧨 Левая", callback_data=f"techies_left_{user_obj.id}_{correct_button}_{int(start_time*1000)}"),
         InlineKeyboardButton("🧨 Правая", callback_data=f"techies_right_{user_obj.id}_{correct_button}_{int(start_time*1000)}")]
    ])
    
    text = (
        f"🎲 {display_username}\n\n"
        "🧨 МИНА ЗАЛОЖЕНА!\n"
        "😈 Techies: «Угадай, пока не бабахнуло...»\n"
        "⏱️ 15 секунд до взрыва!\n\n"
        "Одна кнопка сохранит Фиссуру,\n"
        "другая — взорвёт её к чертям.\n"
        "Выбирай с умом, сапёр... 💣"
    )
    
    msg = await bot.send_photo(chat_id=chat_id, photo=BANNER_URL, caption=text, reply_markup=keyboard, parse_mode="HTML")
    set_last_bot_message(chat_id, user_obj.id, msg.message_id)
    
    logger.info(f"handle_techies_event: job_queue={job_queue is not None}, scheduling timeout for {chat_id}_{msg.message_id}")
    
    if job_queue:
        job_queue.run_once(
            _techies_timeout_job,
            15,
            data={
                'chat_id': chat_id,
                'msg_id': msg.message_id,
                'user_id': user_obj.id,
                'display_username': display_username,
                'start_time': start_time,
                'correct_button': correct_button
            },
            name=f"techies_timeout_{chat_id}_{msg.message_id}"
        )
    else:
        # Fallback: schedule timeout using asyncio
        asyncio.create_task(_techies_timeout_fallback(bot, chat_id, msg.message_id, user_obj.id, display_username, start_time, correct_button))

async def techies_command(update: ContextTypes.DEFAULT_TYPE, context: ContextTypes.DEFAULT_TYPE):
    from database import get_user
    
    user_id = update.effective_user.id
    user = get_user(user_id)
    if not user:
        await update.message.reply_text("❌ Пользователь не найден")
        return
    
    correct_button = random.choice(["left", "right"])
    start_time = time.time()
    
    username = user.get("username")
    display_username = make_clickable(username or (user.first_name if user else "Гость"), user_id)
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🧨 Левая", callback_data=f"techies_left_{user_id}_{correct_button}_{int(start_time*1000)}"),
         InlineKeyboardButton("🧨 Правая", callback_data=f"techies_right_{user_id}_{correct_button}_{int(start_time*1000)}")]
    ])
    
    text = (
        f"🎲 {display_username}\n\n"
        "🧨 МИНА ЗАЛОЖЕНА!\n"
        "😈 Techies: «Угадай, пока не бабахнуло...»\n"
        "⏱️ 15 секунд до взрыва!\n\n"
        "Одна кнопка сохранит Фиссуру,\n"
        "другая — взорвёт её к чертям.\n"
        "Выбирай с умом, сапёр... 💣"
    )
    
    msg = await update.message.reply_photo(
        photo=TECHIES_BANNER_URL,
        caption=text,
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    
    if context.application.job_queue:
        context.application.job_queue.run_once(
            _techies_timeout_job,
            15,
            data={
                'chat_id': update.effective_chat.id,
                'msg_id': msg.message_id,
                'user_id': user_id,
                'display_username': display_username,
                'start_time': start_time,
                'correct_button': correct_button
            },
            name=f"techies_timeout_{update.effective_chat.id}_{msg.message_id}"
        )

async def handle_techies_button(update: ContextTypes.DEFAULT_TYPE, context: ContextTypes.DEFAULT_TYPE):
    from database import get_user, update_fissure
    
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    data = query.data.split("_")
    
    if len(data) < 5 or data[0] != "techies":
        return
    
    _, button_pressed, initiator_id, correct_button, start_time_str = data[:5]
    initiator_id = int(initiator_id)
    
    if user_id != initiator_id:
        await query.answer("🧨 Это не твоя мина, бродяга!", show_alert=True)
        return
    
    session_key = f"{query.message.chat_id}_{user_id}"
    if session_key not in _active_techies_sessions:
        return
    del _active_techies_sessions[session_key]
    
    try:
        start_time = float(start_time_str) / 1000
    except ValueError:
        start_time = 0
    
    elapsed = time.time() - start_time
    
    user = get_user(user_id)
    if not user:
        await query.edit_message_text("❌ Ошибка: пользователь не найден")
        return
    
    current_fissure = user.get("fissure", 0) or 0
    
    username = query.from_user.username
    display_username = make_clickable(username or query.from_user.first_name or "Гость", user_id)
    
    if elapsed > 15 or button_pressed != correct_button:
        mines = generate_mines()
        total_damage = sum(mines)
        
        new_fissure = max(0.1, current_fissure - total_damage)
        update_fissure(user_id, new_fissure, time.time(), 0)
        
        phrase = random.choice(FAIL_PHRASES)
        
        text = (
            f"🎲 {display_username}\n\n"
            "💥 БАБАХ!\n"
            f"😈 Techies: {phrase}\n\n"
        )
        for i, mine in enumerate(mines, 1):
            text += f"💣 Мина {i} - {mine} см\n"
        text += f"\n📏 {current_fissure:.1f} см → {new_fissure:.1f} см"
    else:
        phrase = random.choice(SUCCESS_PHRASES)
        new_fissure = current_fissure
        text = f"🎲 {display_username}\n\n😇 ОБЕЗВРЕЖЕНО!\n🩸 Techies: {phrase}\n\n📏 {current_fissure:.1f} см"
    
    await query.edit_message_media(media=InputMediaPhoto(media=TECHIES_BANNER_URL, caption=text, parse_mode="HTML"), reply_markup=None)