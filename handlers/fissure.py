import logging
from telegram import Update
from telegram.ext import ContextTypes
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
