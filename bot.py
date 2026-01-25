import os
import time
import random
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
# На Render .env не используется, токен берётся из переменных окружения
API_TOKEN = os.getenv("BOT_TOKEN")

if not API_TOKEN:
    print("BOT_TOKEN не найден в переменных окружения")
    exit(1)

users = {}

def get_user(uid):
    uid = str(uid)
    if uid not in users:
        users[uid] = {"fissure": 10.0, "last_fissure": 0}
    return users[uid]

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    get_user(update.effective_user.id)
    await update.message.reply_text("🔥 Бот запущен\nFISSURE — мем, ни на что не влияет 😏")

async def fissure(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = get_user(update.effective_user.id)
    now = time.time()
    remaining = 86400 - (now - u["last_fissure"])
    if remaining > 0:
        h = int(remaining / 3600)
        m = int((remaining % 3600) / 60)
        await update.message.reply_text(f"⏳ Через {h} ч. {m} мин." if h > 0 else f"⏳ Через {m} мин.")
        return

    roll = random.choice([-5, -3, -1, 0, 1, 3, 5, 10])
    u["fissure"] = max(0.1, u["fissure"] + roll)
    u["last_fissure"] = now

    texts = {
        10: "💀 ЛЕГЕНДА! +10 см!",
        5: "🎉 +5 см!",
        3: "🔥 +3 см",
        1: "🙂 +1 см",
        0: "🤷 Без изменений",
        -1: "😅 -1 см",
        -3: "📉 -3 см",
        -5: "💔 -5 см..."
    }
    
    phrases = {
        10: ["Растёт… решительно и без совета.", "Увеличилась… без лишних слов."],
        5: ["Растёт… и ничего не спрашивает.", "Увеличилась… без лишних слов."],
        3: ["Растёт… и ничего не спрашивает.", "Увеличилась… без лишних слов."],
        1: ["Растёт… и ничего не спрашивает.", "Увеличилась… без лишних слов."],
        0: ["Стоит на месте… зато уверенно.", "Ни вверх, ни вниз… просто наблюдает.", "На месте… как старый добрый друг."],
        -1: ["Сжалась… тихо так, но гордо.", "Сократился… но с достоинством.", "Сжалась… слегка, но метко."],
        -3: ["Сжалась… тихо так, но гордо.", "Сократился… но с достоинством.", "Сократился… скромно, но заметно."],
        -5: ["Сжалась… тихо так, но гордо.", "Сократился… но с достоинством.", "Сократился… скромно, но заметно."]
    }
    
    phrase = random.choice(phrases[roll])
    await update.message.reply_text(f"{texts[roll]}\n{phrase}\n📏 Теперь {u['fissure']:.1f} см")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "🌋 FISSURE":
        await fissure(update, context)

if __name__ == "__main__":
    application = Application.builder().token(API_TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Запуск polling (Render friendly)
    application.run_polling(
        allowed_updates=[],
        drop_pending_updates=True,
    )
