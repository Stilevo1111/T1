import logging
from telegram.ext import ContextTypes, CommandHandler, MessageHandler, filters
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
import threading
import time
import requests
import random

# Импортируем функции из database.py
from database import get_user, update_fissure, get_fissure_top

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
    user = update.effective_user
    user_id = user.id
    username = user.username
    
    logger.info(f"📨 Текст от {user_id}: {text}")
    
    if text == "📈 Увеличить фиссуру":
        # Получаем текущего пользователя
        user_data = get_user(user_id, username)
        
        # Бросаем кубик (1-6)
        roll = random.randint(1, 6)
        
        # Увеличиваем фиссуру
        new_fissure = user_data['fissure'] + roll
        update_fissure(user_id, new_fissure, time.time())
        
        await update.message.reply_text(
            f"🎲 Вы бросили: {roll}\n"
            f"📏 Ваша фиссура: {user_data['fissure']:.1f} → {new_fissure:.1f}"
        )
        
    elif text == "📏 Моя длина":
        user_data = get_user(user_id, username)
        await update.message.reply_text(
            f"📏 Ваша фиссура: {user_data['fissure']:.1f}\n"
            f"📅 Последнее обновление: {user_data['last_fissure']}"
        )
        
    elif text == "🏆 Топ":
        top_users = get_fissure_top(10)
        if top_users:
            message = "🏆 Топ пользователей:\n\n"
            for i, u in enumerate(top_users, 1):
                message += f"{i}. @{u['username'] or 'Аноним'}: {u['fissure']:.1f}\n"
        else:
            message = "🏆 Топ пока пуст"
        
        await update.message.reply_text(message)
        
    else:
        await update.message.reply_text("Используй кнопки меню! 📱")

def register_handlers(application):
    """Регистрация обработчиков"""
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
