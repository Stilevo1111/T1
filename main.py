import os
import random
import time
import asyncio
import logging
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
from database import init_db, get_user, update_fissure, get_fissure_top

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise ValueError("❌ BOT_TOKEN не задан!")

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
    "up": ["Растёт… и ничего не спрашивает.", "Бот инвестирует в твой успех 💸"],
    "same": ["Стоит на месте… зато уверенно.", "Всё стабильно, как кофе утром ☕"],
    "down": ["Сжалась… тихо так, но гордо.", "Ну вот, маленький минус… как жизнь 😅"]
}

FISURE_MEMES = [
    "💀 Когда фиссура больше, чем твои амбиции",
    "🎉 Празднуем каждый сантиметр!",
    "🔥 Фиссура горит, как моя подписка на кофе ☕",
]

def main_menu():
    keyboard = [
        [KeyboardButton("📈 Увеличить фиссуру")],
        [KeyboardButton("📏 Моя длина"), KeyboardButton("🏆 Топ")],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def format_time(seconds):
    h = seconds // 3600
    m = (seconds % 3600) // 60
    return f"{int(h)}ч {int(m)}м"

async def auto_delete(message, delay=30):
    await asyncio.sleep(delay)
    try:
        await message.delete()
    except Exception as e:
        logger.debug(f"Не удалось удалить сообщение: {e}")

async def fissure(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /fissure"""
    logger.info(f"Пользователь {update.effective_user.id} вызвал fissure")
    
    uid = update.effective_user.id
    username = update.effective_user.username
    now = time.time()
    
    try:
        user = get_user(uid, username)
        
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
        
    except Exception as e:
        logger.error(f"Ошибка в fissure: {e}")
        msg = await update.message.reply_text("❌ Ошибка при обработке запроса")
        asyncio.create_task(auto_delete(msg, 10))

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать статистику"""
    logger.info(f"Пользователь {update.effective_user.id} вызвал stats")
    
    try:
        uid = update.effective_user.id
        username = update.effective_user.username
        user = get_user(uid, username)
        msg = await update.message.reply_text(f"📏 Текущая длина фиссуры: {user['fissure']:.1f} см")
        asyncio.create_task(auto_delete(msg, 30))
    except Exception as e:
        logger.error(f"Ошибка в stats: {e}")
        msg = await update.message.reply_text("❌ Ошибка при получении статистики")
        asyncio.create_task(auto_delete(msg, 10))

async def top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать топ"""
    logger.info(f"Пользователь {update.effective_user.id} вызвал top")
    
    try:
        top_users = get_fissure_top()
        text = "🏆 Топ Фиссур:\n\n"
        for i, u in enumerate(top_users, 1):
            username = u['username'] or f"Пользователь {u['telegram_id']}"
            text += f"{i}. {username} — {u['fissure']:.1f} см\n"
        msg = await update.message.reply_text(text)
        asyncio.create_task(auto_delete(msg, 30))
    except Exception as e:
        logger.error(f"Ошибка в top: {e}")
        msg = await update.message.reply_text("❌ Ошибка при получении топа")
        asyncio.create_task(auto_delete(msg, 10))

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    logger.info(f"Новый пользователь {update.effective_user.id}")
    
    try:
        uid = update.effective_user.id
        username = update.effective_user.username
        get_user(uid, username)
        msg = await update.message.reply_text(
            "Добро пожаловать!\nЗдесь можно увеличить фиссуру 😈",
            reply_markup=main_menu()
        )
        asyncio.create_task(auto_delete(msg, 30))
    except Exception as e:
        logger.error(f"Ошибка в start: {e}")
        msg = await update.message.reply_text("❌ Ошибка при запуске бота")
        asyncio.create_task(auto_delete(msg, 10))

async def menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик кнопок меню"""
    logger.info(f"Пользователь {update.effective_user.id} нажал кнопку: {update.message.text}")
    
    try:
        text = update.message.text
        uid = update.effective_user.id
        username = update.effective_user.username
        get_user(uid, username)

        if text == "📈 Увеличить фиссуру":
            await fissure(update, context)
        elif text == "📏 Моя длина":
            await stats(update, context)
        elif text == "🏆 Топ":
            await top(update, context)
        else:
            msg = await update.message.reply_text("Используйте кнопки меню или команды")
            asyncio.create_task(auto_delete(msg, 10))
    except Exception as e:
        logger.error(f"Ошибка в menu_handler: {e}")
        msg = await update.message.reply_text("❌ Ошибка при обработке команды")
        asyncio.create_task(auto_delete(msg, 10))

async def main():
    """Запуск Telegram бота в режиме polling"""
    try:
        init_db()
        
        # Создаем Telegram бота с правильной настройкой таймаутов
        telegram_app = ApplicationBuilder().token(TOKEN).build()

        telegram_app.add_handler(CommandHandler("start", start))
        telegram_app.add_handler(CommandHandler("fissure", fissure))
        telegram_app.add_handler(CommandHandler("stats", stats))
        telegram_app.add_handler(CommandHandler("top", top))
        telegram_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, menu_handler))

        logger.info("✅ Telegram бот запущен")
        
        # Инициализируем приложение
        await telegram_app.initialize()
        
        # Запускаем polling вручную
        await telegram_app.start()
        await telegram_app.updater.start_polling(
            poll_interval=3.0,
            allowed_updates=None
        )
        
        # Ждем завершения (никогда не завершится без сигнала)
        await asyncio.Event().wait()
        
    except Exception as e:
        logger.error(f"❌ Критическая ошибка: {e}", exc_info=True)
        raise

if __name__ == "__main__":
    asyncio.run(main())
