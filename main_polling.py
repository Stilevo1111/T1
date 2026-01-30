import os
import random
import time
import logging
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters
from database import init_db, get_user, update_fissure, get_fissure_top
import asyncio

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

FISSURE_TEXTS = {
    10: "💀 ЛЕГЕНДА! +10 см!",
    5: "🎉 +5 см!",
    3: "🔥 +3 см",
    1: "🙂 +1 см",
    0: "🤷 Без изменений",
    -1: "😅 -1 см",
    -3: "📉 -3 см",
    -5: "💔 -5 см...",
}

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

async def fissure(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /fissure"""
    logger.info(f"Пользователь {update.effective_user.id} вызвал fissure")
    
    uid = update.effective_user.id
    user_obj = update.effective_user
    username = user_obj.username or user_obj.first_name
    now = time.time()
    
    try:
        user = get_user(uid, username)
        
        if now - user["last_fissure"] < COOLDOWN:
            wait = COOLDOWN - (now - user["last_fissure"])
            await update.message.reply_text(
                f"⏳ Фиссура ещё восстанавливается.\nЖди: {format_time(wait)}"
            )
            return

        roll = random.choice(ROLLS)
        new_fissure = max(0.1, user["fissure"] + roll)
        update_fissure(uid, new_fissure, now)
        
        logger.info(f"Пользователь {uid} использовал фиссуру. Новое время перезарядки: {now}")

        await update.message.reply_text(
            f"{FISSURE_TEXTS[roll]}\n📏 Теперь длина: {new_fissure:.1f} см"
        )
        
    except Exception as e:
        logger.error(f"Ошибка в fissure: {e}")
        await update.message.reply_text("❌ Ошибка при обработке запроса")

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать статистику"""
    logger.info(f"Пользователь {update.effective_user.id} вызвал stats")
    
    try:
        uid = update.effective_user.id
        user_obj = update.effective_user
        username = user_obj.username or user_obj.first_name
        user = get_user(uid, username)
        await update.message.reply_text(f"📏 Текущая длина фиссуры: {user['fissure']:.1f} см")
    except Exception as e:
        logger.error(f"Ошибка в stats: {e}")
        await update.message.reply_text("❌ Ошибка при получении статистики")

async def top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать топ"""
    logger.info(f"Пользователь {update.effective_user.id} вызвал top")
    
    try:
        top_users = get_fissure_top()
        logger.info(f"Получено {len(top_users)} пользователей для топа")
        
        if not top_users:
            await update.message.reply_text("🏆 Топ Фиссур:\n\nПока нет данных для отображения топа")
            return
            
        text = "🏆 Топ Фиссур:\n\n"
        for i, u in enumerate(top_users, 1):
            username = u['username'] or f"Пользователь {u['telegram_id']}"
            text += f"{i}. {username} — {u['fissure']:.1f} см\n"
        await update.message.reply_text(text)
    except Exception as e:
        logger.error(f"Ошибка в top: {e}")
        await update.message.reply_text("❌ Ошибка при получении топа")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    logger.info(f"Новый пользователь {update.effective_user.id}")
    
    try:
        uid = update.effective_user.id
        user_obj = update.effective_user
        username = user_obj.username or user_obj.first_name
        get_user(uid, username)
        await update.message.reply_text(
            "Добро пожаловать!\nЗдесь можно увеличить фиссуру 😈",
            reply_markup=main_menu()
        )
    except Exception as e:
        logger.error(f"Ошибка в start: {e}")
        await update.message.reply_text("❌ Ошибка при запуске бота")

async def menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик кнопок меню"""
    logger.info(f"Пользователь {update.effective_user.id} нажал кнопку: {update.message.text}")
    
    try:
        text = update.message.text

        if text == "📈 Увеличить фиссуру":
            await fissure(update, context)
        elif text == "📏 Моя длина":
            await stats(update, context)
        elif text == "🏆 Топ":
            await top(update, context)
        else:
            await update.message.reply_text("Используйте кнопки меню или команды")
    except Exception as e:
        logger.error(f"Ошибка в menu_handler: {e}")
        await update.message.reply_text("❌ Ошибка при обработке команды")

def main():
    """Запуск бота в режиме polling"""
    # Инициализируем базу данных
    init_db()
    
    # Создаем приложение
    application = Application.builder().token(TOKEN).build()
    
    # Добавляем обработчики
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("fissure", fissure))
    application.add_handler(CommandHandler("stats", stats))
    application.add_handler(CommandHandler("top", top))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, menu_handler))
    
    logger.info("✅ Бот запущен в режиме polling")
    
    # Запускаем polling
    application.run_polling(
        drop_pending_updates=True,
        allowed_updates=Update.ALL_TYPES
    )

if __name__ == "__main__":
    # Создаем новый event loop для избежания конфликтов
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    # Запускаем бота
    loop.run_until_complete(main())
