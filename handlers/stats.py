"""Обработчик команды /stats"""

from telegram import Update
from telegram.ext import ContextTypes

from database import get_user

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать длину фиссуры игрока"""
    user = update.effective_user
    user_data = await get_user(user.id, user.username or user.first_name)
    
    if not user_data:
        await update.message.reply_text("Сначала зарегистрируйтесь с помощью команды /start")
        return
    
    # Формируем сообщение с длиной фиссуры
    stats_text = f"""
📏 <b>Ваша фиссура</b>

Текущая длина: <b>{user_data['fissure']} см</b>

Продолжайте проходить трещины, чтобы увеличить свою фиссуру!
Используйте /fissure для прохождения трещины (раз в 24 часа).
"""
    
    await update.message.reply_text(stats_text, parse_mode='HTML')

def register_stats_handlers(application):
    """Регистрация обработчиков статистики"""
    from telegram.ext import CommandHandler
    application.add_handler(CommandHandler("stats", stats_command))