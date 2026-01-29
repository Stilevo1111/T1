import os
import asyncio
import logging
from telegram.ext import Application

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

async def main():
    # Получаем переменные окружения
    TOKEN = os.getenv("BOT_TOKEN")
    RENDER_URL = os.getenv("RENDER_EXTERNAL_URL")
    
    if not TOKEN:
        print("❌ BOT_TOKEN не установлен")
        return
    
    if not RENDER_URL:
        print("❌ RENDER_EXTERNAL_URL не установлен")
        return
    
    WEBHOOK_URL = f"{RENDER_URL}/webhook"
    
    # Создаем приложение
    application = Application.builder().token(TOKEN).build()
    
    # Регистрируем обработчики команд
    from handlers import register_handlers
    register_handlers(application)
    
    # Инициализируем базу данных
    from db_postgres import init_db
    init_db()
    
    # Устанавливаем webhook
    await application.bot.set_webhook(
        url=WEBHOOK_URL,
        secret_token=os.getenv("WEBHOOK_SECRET", "")
    )
    print(f"✅ Webhook установлен: {WEBHOOK_URL}")
    
    # Запускаем webhook сервер
    port = int(os.getenv("PORT", 10000))
    await application.run_webhook(
        listen="0.0.0.0",  # Важно для Render
        port=port,
        webhook_url=WEBHOOK_URL,
        secret_token=os.getenv("WEBHOOK_SECRET", "")
    )

if __name__ == "__main__":
    asyncio.run(main())
