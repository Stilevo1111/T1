import os
import time
import random
import logging
import asyncio
import asyncpg

from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ================= CONFIG =================

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
RENDER_URL = os.getenv("RENDER_EXTERNAL_URL")
PORT = int(os.getenv("PORT", 10000))

if not all([BOT_TOKEN, DATABASE_URL, RENDER_URL]):
    raise RuntimeError("Не заданы BOT_TOKEN / DATABASE_URL / RENDER_EXTERNAL_URL")

COOLDOWN = 86400
AUTO_DELETE_DELAY = 30  # секунд

# ================= DATABASE =================

db_pool: asyncpg.Pool | None = None


async def init_db(app):
    global db_pool
    db_pool = await asyncpg.create_pool(DATABASE_URL)

    async with db_pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id TEXT PRIMARY KEY,
                fissure REAL DEFAULT 10.0,
                last_fissure DOUBLE PRECISION DEFAULT 0
            )
        """)
    logging.info("DB initialized")


async def get_user(uid: int) -> dict:
    async with db_pool.acquire() as conn:
        user = await conn.fetchrow(
            "SELECT * FROM users WHERE user_id=$1",
            str(uid),
        )
        if not user:
            await conn.execute(
                "INSERT INTO users (user_id) VALUES ($1)",
                str(uid),
            )
            user = await conn.fetchrow(
                "SELECT * FROM users WHERE user_id=$1",
                str(uid),
            )
        return dict(user)


async def update_user(uid: int, fissure: float, ts: float):
    async with db_pool.acquire() as conn:
        await conn.execute(
            "UPDATE users SET fissure=$1, last_fissure=$2 WHERE user_id=$3",
            fissure,
            ts,
            str(uid),
        )


async def get_top(limit: int = 10):
    async with db_pool.acquire() as conn:
        return await conn.fetch("""
            SELECT user_id, fissure
            FROM users
            ORDER BY fissure DESC
            LIMIT $1
        """, limit)

# ================= GAME DATA =================

ROLLS = [-5, -3, -1, 0, 1, 3, 5, 10]

TEXTS = {
    10: "💀 ЛЕГЕНДА! +10 см!",
    5: "🎉 +5 см!",
    3: "🔥 +3 см",
    1: "🙂 +1 см",
    0: "🤷 Без изменений",
    -1: "😅 -1 см",
    -3: "📉 -3 см",
    -5: "💔 -5 см...",
}

PHRASES = {
    "up": ["Растёт… и ничего не спрашивает.", "Увеличилась… без лишних слов."],
    "same": ["Стоит на месте… зато уверенно.", "На месте… как старый добрый друг."],
    "down": ["Сжалась… тихо так, но гордо.", "Сократился… но с достоинством."],
}

# ================= KEYBOARD =================

MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [["🍆 FISSURE", "🏆 TOP"], ["📊 STATS"]],
    resize_keyboard=True,
)

# ================= AUTO DELETE =================

async def auto_delete(context: ContextTypes.DEFAULT_TYPE, chat_id: int, msg_ids: list[int]):
    await asyncio.sleep(AUTO_DELETE_DELAY)
    for msg_id in msg_ids:
        try:
            await context.bot.delete_message(chat_id, msg_id)
        except Exception:
            pass

# ================= BOT COMMANDS =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await get_user(update.effective_user.id)
    msg = await update.message.reply_text(
        "🔥 Бот запущен\n\n"
        "🍆 FISSURE — ролл\n"
        "🏆 TOP — рейтинг\n"
        "📊 STATS — статистика",
        reply_markup=MAIN_KEYBOARD,
    )
    # Не удаляем стартовое сообщение, чтобы кнопки оставались


async def fissure(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    user = await get_user(uid)
    now = time.time()
    remaining = COOLDOWN - (now - user["last_fissure"])

    if remaining > 0:
        msg = await update.message.reply_text(
            f"⏳ Через {int(remaining // 3600)} ч. {(int(remaining) % 3600) // 60} мин."
        )
    else:
        roll = random.choice(ROLLS)
        new_value = max(0.1, user["fissure"] + roll)
        await update_user(uid, new_value, now)

        phrase = (
            random.choice(PHRASES["up"]) if roll > 0 else
            random.choice(PHRASES["down"]) if roll < 0 else
            random.choice(PHRASES["same"])
        )

        msg = await update.message.reply_text(
            f"{TEXTS[roll]}\n{phrase}\n📏 Теперь {new_value:.1f} см"
        )

    # Автоудаление ответа
    context.application.create_task(
        auto_delete(context, update.effective_chat.id, [msg.message_id])
    )


async def top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = await get_top()
    if not rows:
        msg = await update.message.reply_text("Топ пуст 😢")
    else:
        text = ["🏆 ТОП по длине:\n"]
        for i, row in enumerate(rows, 1):
            text.append(f"{i}. 👤 {row['user_id']} — {row['fissure']:.1f} см")
        msg = await update.message.reply_text("\n".join(text))

    context.application.create_task(
        auto_delete(context, update.effective_chat.id, [msg.message_id])
    )


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await get_user(update.effective_user.id)
    msg = await update.message.reply_text(
        f"📊 Твоя статистика:\n📏 {user['fissure']:.1f} см"
    )

    context.application.create_task(
        auto_delete(context, update.effective_chat.id, [msg.message_id])
    )


# ================= BUTTON HANDLER =================

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "🍆 FISSURE":
        await fissure(update, context)
    elif text == "🏆 TOP":
        await top(update, context)
    elif text == "📊 STATS":
        await stats(update, context)

# ================= ENTRY POINT =================

if __name__ == "__main__":
    WEBHOOK_PATH = f"webhook/{BOT_TOKEN}"

    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .post_init(init_db)
        .build()
    )

    # Хендлеры команд
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("fissure", fissure))
    app.add_handler(CommandHandler("top", top))
    app.add_handler(CommandHandler("stats", stats))

    # Хендлер кнопок
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Запуск webhook
    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=WEBHOOK_PATH,
        webhook_url=f"{RENDER_URL.rstrip('/')}/{WEBHOOK_PATH}",
        drop_pending_updates=True,
    )