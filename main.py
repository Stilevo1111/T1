import os
import random
import time
import asyncio
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
from db_postgres import init_db, get_user, update_fissure, get_fissure_top

TOKEN = os.getenv("BOT_TOKEN")

COOLDOWN = 86400  # 24 часа
ROLLS = [-5, -3, -1, 0, 1, 3, 5, 10]

FISURE_TEXTS = {
    10: "💀 ЛЕГЕНДА! +10 см!",
    5: "🎉 +5 см!",
    3: "🔥 +3 см",
    1: "🙂 +1 см",
    0: "🤷 Без изменений",
    -1: "😅 -1 см",
    -3: "📉 -3 см",
    -5: "💔 -5 см...",
}

FISURE_PHRASES = {
    "up": [
        "Растёт… и ничего не спрашивает.",
        "Увеличилась… без лишних слов.",
        "Кажется, у нас рекордный рост сегодня!",
        "Бот инвестирует в твой успех 💸",
        "Смело врываемся в топ!",
        "Фиссура набирает мощь, как я в выходные 😏",
        "Сегодня тебе повезло… или нет 😎"
    ],
    "same": [
        "Стоит на месте… зато уверенно.",
        "На месте… как старый добрый друг.",
        "Фиссура делает паузу… стратегически 🧠",
        "Ничего не изменилось, но настроение хорошее!",
        "Всё стабильно, как кофе утром ☕",
        "Мир наблюдает… и молчит"
    ],
    "down": [
        "Сжалась… тихо так, но гордо.",
        "Сократился… но с достоинством.",
        "Ну вот, маленький минус… как жизнь 😅",
        "Фиссура решила проверить твою терпимость 🤏",
        "Неудача? Нет, просто тренировка характера!",
        "Оптимистичный взгляд: завтра будет + 😎"
    ]
}

FISURE_MEMES = [
    "💀 Когда фиссура больше, чем твои амбиции",
    "🎉 Празднуем каждый сантиметр!",
    "🔥 Фиссура горит, как моя подписка на кофе ☕",
    "📉 Не падай духом, фиссура любит тебя",
    "😅 Сжалась, но держится… как твой Wi-Fi",
    "🤷 Неизвестно, что происходит, но весело",
    "🚀 Ракета фиссуры взлетает!",
    "🥳 Каждый сантиметр — маленький праздник",
    "🫣 Шок и трепет… фиссура это сделала!",
    # Отсылки и пасхалки
    "🧙 Как сказал бы Гэндальф: “Ты не пройдёшь… если фиссура не растёт!”",
    "🎮 Фиссура растёт быстрее, чем твой FPS в CS:GO",
    "🦸 Сила фиссуры сильнее, чем у Халка 💪",
    "🕹️ Это как пауза в Mario, только фиссура не останавливается",
    "💾 Сохрани прогресс! Фиссура апнула +10",
    "🧩 Фиссура — как баг в коде, только полезный",
    "🛡️ Фиссура защищает твои мечты, как щит в Dark Souls",
    "⚡ Это уровень эпика, словно ульта в LoL готова!"
]

# ---------- КЛАВИАТУРА ----------
def main_menu():
    keyboard = [
        [KeyboardButton("📈 Увеличить фиссуру")],
        [KeyboardButton("📏 Моя длина"), KeyboardButton("🏆 Топ")],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# ---------- ВСПОМОГАТЕЛЬНОЕ ----------
def format_time(seconds):
    h = seconds // 3600
    m = (seconds % 3600) // 60
    return f"{int(h)}ч {int(m)}м"

async def auto_delete(message, delay=30):
    """Удаляет сообщение через delay секунд."""
    await asyncio.sleep(delay)
    try:
        await message.delete()
    except:
        pass  # Если сообщение уже удалено или нет прав

# ---------- ИГРОВАЯ ЛОГИКА ----------
async def fissure(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    username = update.effective_user.username
    user = get_user(uid, username)
    now = time.time()

    # Удаляем команду пользователя через 30 сек
    asyncio.create_task(auto_delete(update.message, 30))

    if now - user["last_fissure"] < COOLDOWN:
        wait = COOLDOWN - (now - user["last_fissure"])
        msg = await update.message.reply_text(
            f"⏳ Фиссура ещё восстанавливается.\nЖди: {format_time(wait)}"
        )
        asyncio.create_task(auto_delete(msg, 30))
        return

    roll = random.choice(ROLLS)
    new_fissure = max(0.1, user["fissure"] + roll)
    update_fissure(uid, new_fissure, now)

    if roll > 0:
        phrase = random.choice(FISURE_PHRASES["up"])
    elif roll < 0:
        phrase = random.choice(FISURE_PHRASES["down"])
    else:
        phrase = random.choice(FISURE_PHRASES["same"])

    meme = random.choice(FISURE_MEMES)

    msg = await update.message.reply_text(
        f"{FISURE_TEXTS[roll]}\n{phrase}\n\n{meme}\n📏 Теперь длина: {new_fissure:.1f} см"
    )
    asyncio.create_task(auto_delete(msg, 30))

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    asyncio.create_task(auto_delete(update.message, 30))
    uid = update.effective_user.id
    username = update.effective_user.username
    user = get_user(uid, username)
    msg = await update.message.reply_text(f"📏 Текущая длина фиссуры: {user['fissure']:.1f} см")
    asyncio.create_task(auto_delete(msg, 30))

async def top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    asyncio.create_task(auto_delete(update.message, 30))
    top_users = get_fissure_top()
    text = "🏆 Топ Фиссур:\n\n"
    for i, u in enumerate(top_users, 1):
        username = u['username'] if u['username'] else f"Пользователь {u['uid']}"
        text += f"{i}. {username} — {u['fissure']:.1f} см\n"
    msg = await update.message.reply_text(text)
    asyncio.create_task(auto_delete(msg, 30))

# ---------- МЕНЮ ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    asyncio.create_task(auto_delete(update.message, 30))
    uid = update.effective_user.id
    username = update.effective_user.username
    get_user(uid, username)  # Сохраняем пользователя в базу
    msg = await update.message.reply_text(
        "Добро пожаловать!\nЗдесь можно увеличить фиссуру 😈",
        reply_markup=main_menu()
    )
    asyncio.create_task(auto_delete(msg, 30))

async def menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    asyncio.create_task(auto_delete(update.message, 30))
    text = update.message.text
    
    # Сохраняем пользователя в базу при любом взаимодействии
    uid = update.effective_user.id
    username = update.effective_user.username
    get_user(uid, username)

    if text == "📈 Увеличить фиссуру":
        await fissure(update, context)
    elif text == "📏 Моя длина":
        await stats(update, context)
    elif text == "🏆 Топ":
        await top(update, context)

# ---------- ЗАПУСК ----------
def main():
    init_db()
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("fissure", fissure))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("top", top))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, menu_handler))

    print("Bot started")
    app.run_polling()

if __name__ == "__main__":
    main()