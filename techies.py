import random
import time

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from telegram.ext import ContextTypes

BANNER_URL = "https://i.ibb.co/PzzFJwwk/Gemini-Generated-Image-e3k1zhe3k1zhe3k1.png"

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

def generate_mines(count: int = 4) -> list[float]:
    return [round(random.uniform(0.0, 100.0), 1) for _ in range(count)]

TECHIES_BANNER_URL = "https://i.ibb.co/PzzFJwwk/Gemini-Generated-Image-e3k1zhe3k1zhe3k1.png"

async def handle_techies_event(bot, chat_id, user, user_obj, display_username, now, main_menu, set_last_bot_message, schedule_delete, update_fissure, update_last_message_id):
    correct_button = random.choice(["left", "right"])
    start_time = time.time()
    
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
    
    msg = await bot.send_photo(chat_id=chat_id, photo=TECHIES_BANNER_URL, caption=text, reply_markup=keyboard, parse_mode="HTML")
    set_last_bot_message(chat_id, msg.message_id)

async def techies_command(update: ContextTypes.DEFAULT_TYPE, context: ContextTypes.DEFAULT_TYPE):
    from database import get_user
    
    user_id = update.effective_user.id
    user = get_user(user_id)
    if not user:
        await update.message.reply_text("❌ Пользователь не найден")
        return
    
    correct_button = random.choice(["left", "right"])
    start_time = time.time()
    
    display_username = f"<a href=\"tg://user?id={user_id}\">{user.first_name}</a>"
    
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
    
    await update.message.reply_photo(
        photo=TECHIES_BANNER_URL,
        caption=text,
        reply_markup=keyboard,
        parse_mode="HTML"
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
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🧨 Левая", callback_data="noop"),
         InlineKeyboardButton("🧨 Правая", callback_data="noop")]
    ])
    
    if elapsed > 15 or button_pressed != correct_button:
        mines = generate_mines()
        total_damage = sum(mines)
        
        new_fissure = max(0.1, current_fissure - total_damage)
        update_fissure(user_id, new_fissure, time.time(), 0)
        
        phrase = random.choice(FAIL_PHRASES)
        
        text = (
            "💥 БАБАХ!\n"
            f"😈 Techies: {phrase}\n\n"
        )
        for i, mine in enumerate(mines, 1):
            text += f"💣 Мина {i} - {mine} см\n"
        text += f"\n📏 {current_fissure:.1f} см → {new_fissure:.1f} см"
    else:
        phrase = random.choice(SUCCESS_PHRASES)
        new_fissure = current_fissure
        text = f"😇 ОБЕЗВРЕЖЕНО!\n🩸 Techies: {phrase}\n\n📏 {current_fissure:.1f} см"
    
    await query.edit_message_media(media=InputMediaPhoto(media=TECHIES_BANNER_URL, caption=text), reply_markup=keyboard)
