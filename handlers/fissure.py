import logging
from telegram import Update
from telegram.ext import ContextTypes, CommandHandler, CallbackQueryHandler

from database import get_user, update_user
from game_logic import get_fissure_result, get_user_progress

logger = logging.getLogger(__name__)

async def fissure(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка команды /fissure"""
    user_id = update.effective_user.id
    user = await get_user(user_id)
    
    if not user:
        await update.message.reply_text("Сначала зарегистрируйтесь с помощью /start")
        return
    
    result = get_fissure_result(user)
    
    if result["success"]:
        await update.message.reply_text(f"🎉 Вы прошли трещину!\n{result['message']}")
        await update_user(user_id, result["updates"])
    else:
        await update.message.reply_text(f"💥 Вы провалились в трещину!\n{result['message']}")

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать статистику пользователя"""
    user_id = update.effective_user.id
    user = await get_user(user_id)
    
    if not user:
        await update.message.reply_text("Сначала зарегистрируйтесь с помощью /start")
        return
    
    progress = get_user_progress(user)
    await update.message.reply_text(f"Статистика трещин:\n{progress}")

def register_fissure_callbacks(application) -> None:
    """Регистрация callback обработчиков трещин"""
    # Пока нет callback-обработчиков для трещин, но функция должна существовать
    # для совместимости с системой регистрации обработчиков
    pass

def register_fissure_handlers(application) -> None:
    """Регистрация обработчиков трещин"""
    # Команда /fissure
    application.add_handler(CommandHandler("fissure", fissure))
    
    # Команда /stats
    application.add_handler(CommandHandler("stats", stats))
    
    # Callback обработчики
    register_fissure_callbacks(application)

__all__ = ['fissure', 'stats', 'register_fissure_handlers', 'register_fissure_callbacks']
