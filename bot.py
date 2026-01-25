import os
import logging
import asyncpg
import random
import time
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

API_TOKEN = os.environ.get("BOT_TOKEN")
PORT = int(os.environ.get("PORT", 10000))
RENDER_URL = os.environ.get("RENDER_EXTERNAL_URL")
DATABASE_URL = os.environ.get("DATABASE_URL")

if not API_TOKEN or not RENDER_URL or not DATABASE_URL:
    raise Exception("BOT_TOKEN, RENDER_EXTERNAL_URL или DATABASE_URL не найдены")

RENDER_URL = RENDER_URL.strip().rstrip('/')
if RENDER_URL.startswith("https://https://"):
    RENDER_URL = RENDER_URL.replace("https://https://", "https://", 1)
elif RENDER_URL.startswith("http://http://"):
    RENDER_URL = RENDER_URL.replace("http://http://", "http://", 1)

if not RENDER_URL.startswith("http://") and not RENDER_URL.startswith("https://"):
    RENDER_URL = f"https://{RENDER_URL}"

# --- DB ---
async def init_db():
    conn = await asyncpg.connect(DATABASE_URL)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY,
            fissure REAL DEFAULT 10.0,
            last_fissure DOUBLE PRECISION DEFAULT 0
        )
    """)
    await conn.close()

async def get_user(conn, uid):
    uid = int(uid)
    user = await conn.fetchrow("SELECT * FROM users WHERE user_id = $1", uid)
    if not user:
        await conn.execute("INSERT INTO users (user_id) VALUES ($1)", uid)
        user = await conn.fetchrow("SELECT * FROM users WHERE user_id = $1", uid)
    return dict(user)

async def update_user(conn, uid, fissure, last_fissure):
    await conn.execute(
        "UPDATE users SET fissure=$1, last_fissure=$2 WHERE user_id=$3",
        fissure, last_fissure, int(uid)
    )

# --- Bot commands ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = await asyncpg.connect(DATABASE_URL)
    await get_user(conn, update.effective_user.id)
    await conn.close()
    await update.message.reply_text(
        "🔥 Бот запущен\nFISSURE — мем, ни на что не влияет 😏"
    )

async def fissure(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = await asyncpg.connect(DATABASE_URL)
    u = await get_user(conn, update.effective_user.id)
    now = time.time()
    remaining = 86400 - (now - u["last_fissure"])
    if remaining > 0:
        h = int(remaining / 3600)
        m = int((remaining % 3600) / 60)
        await update.message.reply_text(
            f"⏳ Через {h} ч. {m} мин." if h > 0 else f"⏳ Через {m} мин."
        )
        await conn.close()
        return

    roll = random.choice([-5, -3, -1, 0, 1, 3, 5, 10])
    new_fissure = max(0.1, u["fissure"] + roll)
    await update_user(conn, update.effective_user.id, new_fissure, now)
    await conn.close()

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
        0: ["Стоит на месте… зато уверенно.", "На месте… как старый добрый друг."],
        -1: ["Сжалась… тихо так, но гордо.", "Сократился… но с достоинством."],
        -3: ["Сжалась… тихо так, но гордо.", "Сократился… но заметно."],
        -5: ["Сжалась… тихо так, но гордо.", "Сократился… скромно, но заметно."]
    }

    phrase = random.choice(phrases[roll])
    await update.message.reply_text(f"{texts[roll]}\n{phrase}\n📏 Теперь {new_fissure:.1f} см")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "🌋 FISSURE":
        await fissure(update, context)

# --- Запуск без asyncio.run() ---
if __name__ == "__main__":
    import asyncio

    application = ApplicationBuilder().token(API_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Инициализация БД перед запуском
    asyncio.run(init_db())

    webhook_url = f"{RENDER_URL}/webhook/{API_TOKEN}"
    logging.info(f"Webhook установлен: {webhook_url}")

    # Запускаем вебхук (set_webhook выполняется внутри run_webhook)
    application.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        webhook_url=webhook_url,
        drop_pending_updates=True
    )