import logging
from telegram.ext import ContextTypes, CommandHandler, MessageHandler, filters
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
import threading
import time
import requests

logger = logging.getLogger(__name__)

def main_menu():
    keyboard = [
        [KeyboardButton("📈 Увеличить фиссуру")],
        [KeyboardButton("📏 Моя длина"), KeyboardButton("🏆 Топ")],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start - максимально быстрый"""
    try:
        user = update.effective_user
        logger.info(f"🚀 /start от {user.id} (@{user.username})")
        
        # Немедленный ответ
        await update.message.reply_text(
            f"👋 Привет, {user.first_name}!\n\n"
            "Я - Fissure Bot! Используй кнопки ниже:",
            reply_markup=main_menu()
        )
        logger.info(f"✅ Ответ отправлен {user.id}")
        
    except Exception as e:
        logger.error(f"❌ Ошибка в /start: {e}")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик текстовых сообщений"""
    text = update.message.text
    user_id = update.effective_user.id
    
    logger.info(f"📨 Текст от {user_id}: {text}")
    
    if text == "📈 Увеличить фиссуру":
        await update.message.reply_text("🎲 Бросок кубика...")
    elif text == "📏 Моя длина":
        await update.message.reply_text("📏 Загружаю статистику...")
    elif text == "🏆 Топ":
        await update.message.reply_text("🏆 Загружаю топ...")
    else:
        await update.message.reply_text("Используй кнопки меню! 📱")

def register_handlers(application):
    """Регистрация обработчиков"""
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
