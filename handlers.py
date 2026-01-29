from telegram.ext import CommandHandler, MessageHandler, ContextTypes, filters
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
import random
import time
import asyncio
import logging

logger = logging.getLogger(__name__)

# Импорт функций БД внутри функций, чтобы избежать циклических импортов
def import_db():
    from database import get_user, update_fissure, get_fissure_top
    return get_user, update_fissure, get_fissure_top

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
    """Удалить сообщение через указанное время"""
    try:
        await asyncio.sleep(delay)
        await message.delete()
    except Exception as e:
        logger.debug(f"Не удалось удалить сообщение: {e}")

async def fissure(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /fissure"""
    logger.info(f"Пользователь {update.effective_user.id} вызвал fissure")
    
    get_user, update_fissure, _ = import_db()
    
    uid = update.effective_user.id
    username = update.effective_user.username or update.effective_user.first_name
    now = time.time()
    
    try:
        # Получаем пользователя
        user = get_user(uid, username)
        
        # Проверяем кулдаун
        if now - user["last_fissure"] < COOLDOWN:
            wait = COOLDOWN - (now - user["last_fissure"])
            msg = await update.message.reply_text(
                f"⏳ Фиссура ещё восстанавливается.\nЖди: {format_time(wait)}"
            )
            asyncio.create_task(auto_delete(msg, 30))
            return
        
        # Бросаем кубик
        roll = random.choice(ROLLS)
        new_fissure = max(0.1, user["fissure"] + roll)
        
        # Обновляем в БД
        update_fissure(uid, new_fissure, now)
        
        # Формируем ответ
        response = f"{FISURE_TEXTS[roll]}\n"
        response += f"📏 Теперь длина: {new_fissure:.1f} см"
        
        if roll > 0:
            response += "\n\n🎉 Растёт… и ничего не спрашивает."
        elif roll < 0:
            response += "\n\n😅 Сжалась… тихо так, но гордо."
        else:
            response += "\n\n🤷 Стоит на месте… зато уверенно."
        
        msg = await update.message.reply_text(response)
        asyncio.create_task(auto_delete(msg, 30))
        
    except Exception as e:
        logger.error(f"Ошибка в fissure: {e}")
        msg = await update.message.reply_text("❌ Ошибка при обработке запроса")
        asyncio.create_task(auto_delete(msg, 10))

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать статистику"""
    logger.info(f"Пользователь {update.effective_user.id} вызвал stats")
    
    get_user, _, _ = import_db()
    
    uid = update.effective_user.id
    username = update.effective_user.username or update.effective_user.first_name
    
    try:
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
    
    _, _, get_fissure_top = import_db()
    
    try:
        top_users = get_fissure_top()
        text = "🏆 Топ Фиссур:\n\n"
        for i, u in enumerate(top_users[:10], 1):
            username = u['username'] or f"User {u['telegram_id']}"
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
    
    get_user, _, _ = import_db()
    
    uid = update.effective_user.id
    username = update.effective_user.username or update.effective_user.first_name
    
    try:
        # Регистрируем пользователя если нужно
        get_user(uid, username)
        
        welcome_text = (
            "👋 Добро пожаловать в Fissure Bot!\n\n"
            "Здесь можно увеличить свою фиссуру 😈\n\n"
            "Доступные команды:\n"
            "• Нажмите кнопку '📈 Увеличить фиссуру' для броска\n"
            "• '📏 Моя длина' - текущая статистика\n"
            "• '🏆 Топ' - таблица лидеров\n\n"
            "Сообщения автоматически удаляются через 30 секунд"
        )
        
        msg = await update.message.reply_text(
            welcome_text,
            reply_markup=main_menu()
        )
        asyncio.create_task(auto_delete(msg, 30))
    except Exception as e:
        logger.error(f"Ошибка в start: {e}")
        msg = await update.message.reply_text("❌ Ошибка при запуске бота")
        asyncio.create_task(auto_delete(msg, 10))

async def menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик кнопок меню"""
    text = update.message.text
    uid = update.effective_user.id
    
    logger.info(f"Пользователь {uid} нажал кнопку: {text}")
    
    if text == "📈 Увеличить фиссуру":
        await fissure(update, context)
    elif text == "📏 Моя длина":
        await stats(update, context)
    elif text == "🏆 Топ":
        await top(update, context)
    else:
        msg = await update.message.reply_text("Используйте кнопки меню или команды")
        asyncio.create_task(auto_delete(msg, 10))

def register_handlers(application):
    """Регистрация всех обработчиков"""
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("fissure", fissure))
    application.add_handler(CommandHandler("stats", stats))
    application.add_handler(CommandHandler("top", top))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, menu_handler))
