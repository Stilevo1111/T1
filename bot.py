import os
import logging
from telegram.ext import Application, CommandHandler
import sys

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    stream=sys.stdout
)

logger = logging.getLogger(__name__)

async def start(update, context):
    """Простой обработчик команды /start"""
    logger.info(f"Получена команда /start от {update.effective_user.id}")
    await update.message.reply_text("Бот работает! ✅")

def main():
    """Минимальный рабочий бот"""
    # Получаем переменные окружения
    TOKEN = os.getenv("BOT_TOKEN")
    
    if not TOKEN:
        logger.error("❌ BOT_TOKEN не установлен")
        return
    
    PORT = int(os.getenv("PORT", 10000))
    RENDER_URL = "https://fissure-bot.onrender.com"  # Ваш URL
    WEBHOOK_URL = f"{RENDER_URL}/webhook"
    
    logger.info(f"🚀 Запуск бота...")
    logger.info(f"🌐 Webhook URL: {WEBHOOK_URL}")
    logger.info(f"🔌 Порт: {PORT}")
    
    # Создаем приложение
    application = Application.builder().token(TOKEN).build()
    
    # Регистрируем обработчики команд
    from handlers import register_handlers
    register_handlers(application)
    
    # Инициализируем базу данных
    from database import init_db
    init_db()
    
    # ЗАКОММЕНТИРУЙТЕ эти строки - webhook устанавливается автоматически в run_webhook
    # application.bot.delete_webhook(drop_pending_updates=True)
    # application.bot.set_webhook(url=WEBHOOK_URL)
    
    # Запускаем бота с webhook
    logger.info("🔄 Запуск webhook сервера...")
    application.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        webhook_url=WEBHOOK_URL,
        drop_pending_updates=True  # Автоматически удалит старый webhook
    )

if __name__ == "__main__":
    main()
