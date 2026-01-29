import os
import logging
from telegram.ext import Application
import sys
import threading
import time
import requests
from flask import Flask, request, jsonify

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    stream=sys.stdout
)

logger = logging.getLogger(__name__)

# Создаем Flask сервер для health checks
app = Flask(__name__)

@app.route('/')
def home():
    return 'Fissure Bot is running!'

@app.route('/health')
def health():
    return jsonify({'status': 'ok', 'time': time.time()}), 200

@app.route('/webhook', methods=['POST'])
def webhook_proxy():
    """Прокси для webhook (если нужно)"""
    return '', 200

def keep_alive():
    """Пинг самого себя каждые 5 минут чтобы не заснуть"""
    url = "https://fissure-bot.onrender.com/health"
    while True:
        try:
            requests.get(url, timeout=5)
            print(f"✅ Keep-alive ping sent at {time.strftime('%H:%M:%S')}")
        except:
            print("⚠️ Keep-alive ping failed")
        time.sleep(300)  # 5 минут

# Запускаем Flask в отдельном потоке
def run_flask():
    app.run(host='0.0.0.0', port=5000)

# Запускаем keep-alive в отдельном потоке
keep_alive_thread = threading.Thread(target=keep_alive, daemon=True)
keep_alive_thread.start()

def main():
    """Быстрый запуск бота"""
    # Получаем переменные окружения
    TOKEN = os.getenv("BOT_TOKEN")
    
    if not TOKEN:
        logger.error("❌ BOT_TOKEN не установлен")
        return
    
    PORT = int(os.getenv("PORT", 10000))
    RENDER_URL = "https://fissure-bot.onrender.com"
    WEBHOOK_URL = f"{RENDER_URL}/webhook"
    
    logger.info(f"🚀 Быстрый запуск бота...")
    logger.info(f"🌐 Webhook: {WEBHOOK_URL}")
    
    # Создаем приложение
    application = Application.builder().token(TOKEN).build()
    
    # Регистрируем обработчики
    from handlers import register_handlers
    register_handlers(application)
    
    # Инициализируем БД (быстро, без лишних проверок)
    try:
        from database import init_db
        init_db()
        logger.info("✅ БД готова")
    except Exception as e:
        logger.warning(f"⚠️ БД: {e}")
    
    # Запускаем webhook с минимальными настройками
    logger.info("🔄 Запуск webhook...")
    application.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        webhook_url=WEBHOOK_URL,
        drop_pending_updates=True
    )

if __name__ == "__main__":
    main()
