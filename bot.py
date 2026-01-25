import os
import time
import random
import logging
import asyncio
import asyncpg
import telebot
from telebot import types

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

MAIN_KEYBOARD = types.ReplyKeyboardMarkup(resize_keyboard=True)
MAIN_KEYBOARD.add("🍆 FISSURE", "🏆 TOP", "📊 STATS")

# ================= AUTO DELETE =================

async def auto_delete(context: ContextTypes.DEFAULT_TYPE, chat_id: int, msg_ids: list[int]):
    await asyncio.sleep(AUTO_DELETE_DELAY)
    for msg_id in msg_ids:
        try:
            await context.bot.delete_message(chat_id, msg_id)
        except Exception:
            pass

# ================= BOT COMMANDS =================

bot = telebot.TeleBot(BOT_TOKEN)

@bot.message_handler(commands=["start"])
def start(m):
    username = m.from_user.username or m.from_user.first_name
    asyncio.run(get_user(m.from_user.id, username))
    bot.reply_to(m,
        "🔥 Бот запущен\nТвоя Фиссура — мем, ни на что не влияет 😏\n\n"
        "🍆 /FISSURE — ролл\n"
        "🏆 /TOP — рейтинг\n"
        "📊 /STATS — статистика",
        reply_markup=MAIN_KEYBOARD
    )

@bot.message_handler(commands=["fissure"])
def fissure(m):
    asyncio.run(fissure_async(m))

async def fissure_async(m):
    uid = m.from_user.id
    username = m.from_user.username or m.from_user.first_name
    user = await get_user(uid, username)
    now = time.time()
    remaining = COOLDOWN - (now - user["last_fissure"])

    if remaining > 0:
        bot.reply_to(m, f"⏳ Через {int(remaining // 3600)} ч. {(int(remaining) % 3600) // 60} мин.")
    else:
        roll = random.choice(ROLLS)
        new_value = max(0.1, user["fissure"] + roll)
        await update_user(uid, new_value, now)

        phrase = (
            random.choice(PHRASES["up"]) if roll > 0 else
            random.choice(PHRASES["down"]) if roll < 0 else
            random.choice(PHRASES["same"])
        )

        bot.reply_to(m, f"{TEXTS[roll]}\n{phrase}\n📏 Теперь {new_value:.1f} см")

@bot.message_handler(commands=["top"])
def top(m):
    asyncio.run(top_async(m))

async def top_async(m):
    rows = await get_top()
    if not rows:
        bot.reply_to(m, "Топ пуст 😢")
    else:
        text = ["🏆 ТОП по длине:\n"]
        for i, row in enumerate(rows, 1):
            text.append(f"{i}. 👤 {row['username']} — {row['fissure']:.1f} см")
        bot.reply_to(m, "\n".join(text))

@bot.message_handler(commands=["stats"])
def stats(m):
    asyncio.run(stats_async(m))

async def stats_async(m):
    uid = m.from_user.id
    username = m.from_user.username or m.from_user.first_name
    user = await get_user(uid, username)
    bot.reply_to(m, f"📊 Твоя фиссура:\n📏 {user['fissure']:.1f} см")

# ================= BUTTON HANDLER =================

@bot.message_handler(func=lambda message: True)
def handle_message(m):
    text = m.text
    if text == "🍆 FISSURE":
        asyncio.run(fissure_async(m))
    elif text == "🏆 TOP":
        asyncio.run(top_async(m))
    elif text == "📊 STATS":
        asyncio.run(stats_async(m))

# ================= ENTRY POINT =================

if __name__ == "__main__":
    # Инициализация базы данных
    asyncio.run(init_db(None))
    
    # Запуск бота
    bot.infinity_polling()
