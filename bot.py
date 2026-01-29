import os
import logging
import asyncio
from telegram.ext import Application
import sys
import threading
import time
import requests
from flask import Flask, request, jsonify
import signal
import json

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
            response = requests.get(url, timeout=5)
            if response.status_code == 200:
                print(f"✅ Keep-alive ping sent at {time.strftime('%H:%M:%S')}")
            else:
                print(f"⚠️ Keep-alive ping failed with status {response.status_code}")
        except Exception as e:
            print(f"⚠️ Keep-alive ping failed: {e}")
        time.sleep(300)  # 5 минут

# Запускаем Flask в отдельном потоке
def run_flask():
    try:
        app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)
    except Exception as e:
        logger.error(f"❌ Flask server error: {e}")

# Запускаем keep-alive в отдельном потоке
keep_alive_thread = threading.Thread(target=keep_alive, daemon=True)
keep_alive_thread.start()

async def main():
    """Быстрый запуск бота"""
    # Получаем переменные окружения
    TOKEN = os.getenv("BOT_TOKEN")
    
    if not TOKEN:
        logger.warning("⚠️ BOT_TOKEN не установлен, используем тестовый режим")
        TOKEN = "test_token"
    
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
    
    # Импортируем функции из database.py для использования в handlers.py
    from database import get_user, update_fissure, get_fissure_top
    
    # Инициализируем БД (быстро, без лишних проверок)
    try:
        from database import init_db
        init_db()
        logger.info("✅ БД готова")
    except Exception as e:
        logger.warning(f"⚠️ БД: {e}")
    
    # Запускаем polling с минимальными настройками
    logger.info("🔄 Запуск polling...")
    try:
        # Инициализируем приложение
        await application.initialize()
        
        # Запускаем polling
        await application.start()
        await application.updater.start_polling(
            drop_pending_updates=True,
            allowed_updates=["message", "callback_query"],
            poll_interval=3.0,
            timeout=30,
            read_timeout=30,
            write_timeout=30,
            connect_timeout=30,
            pool_timeout=30
        )
        
        # Ждем завершения
        await asyncio.Event().wait()
        
    except Exception as e:
        logger.error(f"❌ Ошибка polling: {e}")
        raise
    finally:
        try:
            await application.stop()
            await application.shutdown()
        except:
            pass

def run_bot():
    """Запуск бота"""
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("🛑 Бот остановлен")
    except Exception as e:
        logger.error(f"❌ Ошибка бота: {e}")

if __name__ == "__main__":
    # Запускаем Flask сервер в отдельном потоке
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    
    # Запускаем бота
    run_bot()
