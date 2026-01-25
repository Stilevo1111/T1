import os
import time
import random
import logging
import asyncio
import asyncpg

from telegram import Update, ReplyKeyboardMarkup, BotCommand
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
        # Проверяем, есть ли уже таблица users
        table_exists = await conn.fetchval("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_schema = 'public' 
                AND table_name = 'users'
            )
        """)

        if not table_exists:
            # Создаем новую таблицу
            await conn.execute("""
                CREATE TABLE users (
                    user_id TEXT PRIMARY KEY,
                    username TEXT,
                    fissure REAL DEFAULT 10.0,
                    last_fissure DOUBLE PRECISION DEFAULT 0
                )
            """)
            logging.info("DB initialized - new table created")
        else:
            # Проверяем, есть ли поле username
            username_exists = await conn.fetchval("""
                SELECT EXISTS (
                    SELECT FROM information_schema.columns 
                    WHERE table_name = 'users' 
                    AND column_name = 'username'
                )
            """)

            if not username_exists:
                # Добавляем поле username
                await conn.execute("ALTER TABLE users ADD COLUMN username TEXT")
                # Обновляем существующих пользователей, устанавливая username в пустое значение
                await conn.execute("UPDATE users SET username = '' WHERE username IS NULL")
                logging.info("DB migration completed - username column added")
            else:
                logging.info("DB initialized - existing table with username column")


async def get_user(uid: int, username: str) -> dict:
    async with db_pool.acquire() as conn:
        user = await conn.fetchrow(
            "SELECT * FROM users WHERE user_id=$1",
            str(uid),
        )
        if not user:
            await conn.execute(
                "INSERT INTO users (user_id, username) VALUES ($1, $2)",
                str(uid),
                username,
            )
            user = await conn.fetchrow(
                "SELECT * FROM users WHERE user_id=$1",
                str(uid),
            )
        else:
            # обновляем имя пользователя, если оно изменилось
            if user["username"] != username:
                await conn.execute(
                    "UPDATE users SET username=$1 WHERE user_id=$2",
                    username,
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
            SELECT username, fissure
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

# ================= REGISTER COMMANDS =================

async def set_commands(app):
    """Регистрируем команды бота в Telegram, чтобы они показывались при вводе '/'."""
    commands = [
        BotCommand("start", "Запустить бота"),
        BotCommand("fissure", "Сделать ролл FISSURE"),
        BotCommand("top", "Показать топ игроков"),
        BotCommand("stats", "Показать твою статистику"),
    ]
    try:
        await app.bot.set_my_commands(commands)
        logging.info("Команды бота успешно зарегистрированы")
    except Exception as e:
        logging.error(f"Не удалось зарегистрировать команды: {e}")

# ================= BOT COMMANDS =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username or update.effective_user.full_name
    await get_user(update.effective_user.id, username)
    msg = await update.message.reply_text(
        "🔥 Бот запущен\nТвоя Фиссура — мем, ни на что не влияет 😏\n\n"
        "🍆 /FISSURE — ролл\n"
        "🏆 /TOP — рейтинг\n"
        "📊 /STATS — статистика",
        reply_markup=MAIN_KEYBOARD,
    )
    # Автоудаление стартового сообщения и команды /start через 30 секунд
    context.application.create_task(
        auto_delete(context, update.effective_chat.id, [msg.message_id, update.message.message_id])
    )


async def fissure(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    username = update.effective_user.username or update.effective_user.full_name
    user = await get_user(uid, username)
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

    # Автоудаление ответа и команды/сообщения пользователя
    msg_ids_to_delete = [msg.message_id]
    if update.message.text.startswith('/'):
        msg_ids_to_delete.append(update.message.message_id)
    
    context.application.create_task(
        auto_delete(context, update.effective_chat.id, msg_ids_to_delete)
    )


async def top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = await get_top()
    if not rows:
        msg = await update.message.reply_text("Топ пуст 😢")
    else:
        text = ["🏆 ТОП по длине:\n"]
        for i, row in enumerate(rows, 1):
            text.append(f"{i}. 👤 {row['username']} — {row['fissure']:.1f} см")
        msg = await update.message.reply_text("\n".join(text))

    # Автоудаление ответа и команды/сообщения пользователя
    msg_ids_to_delete = [msg.message_id]
    if update.message.text.startswith('/'):
        msg_ids_to_delete.append(update.message.message_id)
    
    context.application.create_task(
        auto_delete(context, update.effective_chat.id, msg_ids_to_delete)
    )


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    username = update.effective_user.username or update.effective_user.full_name
    user = await get_user(uid, username)
    msg = await update.message.reply_text(
        f"📊 Твоя фиссура:\n📏 {user['fissure']:.1f} см"
    )

    # Автоудаление ответа и команды/сообщения пользователя
    msg_ids_to_delete = [msg.message_id]
    if update.message.text.startswith('/'):
        msg_ids_to_delete.append(update.message.message_id)
    
    context.application.create_task(
        auto_delete(context, update.effective_chat.id, msg_ids_to_delete)
    )


# ================= BUTTON HANDLER =================

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "🍆 FISSURE":
        await fissure(update, context)
        # Автоудаление сообщения с названием кнопки
        context.application.create_task(
            auto_delete(context, update.effective_chat.id, [update.message.message_id])
        )
    elif text == "🏆 TOP":
        await top(update, context)
        # Автоудаление сообщения с названием кнопки
        context.application.create_task(
            auto_delete(context, update.effective_chat.id, [update.message.message_id])
        )
    elif text == "📊 STATS":
        await stats(update, context)
        # Автоудаление сообщения с названием кнопки
        context.application.create_task(
            auto_delete(context, update.effective_chat.id, [update.message.message_id])
        )

# ================= ENTRY POINT =================

if __name__ == "__main__":
    WEBHOOK_PATH = f"webhook/{BOT_TOKEN}"

    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .post_init(init_db)  # инициализация БД
        .build()
    )

    # Регистрация команд после init_db
    app.post_init(set_commands)

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
