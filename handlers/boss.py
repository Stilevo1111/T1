import logging
from telegram import Update
from telegram.ext import ContextTypes, CommandHandler
from database import get_user, update_user
from game_logic import spawn_boss, calculate_boss_strategy

logger = logging.getLogger(__name__)

async def boss(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка команды /boss"""
    user_id = update.effective_user.id
    user = await get_user(user_id)
    
    if not user:
        await update.message.reply_text("Сначала зарегистрируйтесь с помощью /start")
        return
    
    boss_data = spawn_boss(user)
    
    if boss_data["success"]:
        strategy = calculate_boss_strategy(user, boss_data["boss"])
        await update.message.reply_text(f"👹 Босс появился!\n{boss_data['message']}\n\nСтратегия: {strategy}")
    else:
        await update.message.reply_text(f"❌ Ошибка: {boss_data['message']}")

def register_boss_handlers(application) -> None:
    """Регистрация обработчиков боссов"""
    try:
        # Команда /boss
        application.add_handler(CommandHandler("boss", boss))
        
        logger.info("Обработчики боссов зарегистрированы успешно")
    except Exception as e:
        logger.error(f"Ошибка регистрации обработчиков боссов: {e}")
        raise

__all__ = ['boss', 'register_boss_handlers']
