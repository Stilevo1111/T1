import os
import random
import time
import logging
import threading
from flask import Flask, request, jsonify
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters
from telegram.request import HTTPXRequest
import asyncio
import requests
from database import init_db, get_user, update_fissure, get_fissure_top

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise ValueError("❌ BOT_TOKEN не задан!")

COOLDOWN = 86400  # 24 часа
ROLLS = [-5, -3, -1, 0, 1, 3, 5, 10]

# Создаем Flask приложение для health checks
app = Flask(__name__)

# Глобальные переменные
bot_app = None
bot_start_time = time.time()

# Функция для self-ping (чтобы бот не засыпал)
def keep_alive():
    """Пингуем себя каждые 10 минут"""
    while True:
        try:
            # Получаем URL сервиса из переменных окружения
            service_url = os.getenv('RENDER_EXTERNAL_URL')
            if service_url:
                requests.get(f"{service_url}/health", timeout=10)
                logger.info("✅ Self-ping отправлен")
            else:
                logger.warning("⚠️ RENDER_EXTERNAL_URL не установлен")
        except Exception as e:
            logger.warning(f"⚠️ Self-ping не удался: {e}")
        time.sleep(600)  # 10 минут

@app.route('/')
def home():
    """Главная страница"""
    uptime = time.time() - bot_start_time
    hours = int(uptime // 3600)
    minutes = int((uptime % 3600) // 60)
    return f"""
    <html>
        <body>
            <h1>🤖 Telegram Fissure Bot</h1>
            <p>✅ Бот работает</p>
            <p>⏱️ Uptime: {hours}ч {minutes}м</p>
            <p><a href="/health">Health Check</a></p>
            <p><a href="/stats">Статистика</a></p>
        </body>
    </html>
    """

@app.route('/health')
def health():
    """Health check endpoint"""
    try:
        # Проверяем подключение к БД
        from database import get_connection
        conn = get_connection()
        conn.close()
        
        uptime = time.time() - bot_start_time
        return jsonify({
            "status": "healthy",
            "uptime": round(uptime, 2),
            "database": "connected",
            "timestamp": time.time()
        }), 200
    except Exception as e:
        return jsonify({
            "status": "unhealthy",
            "error": str(e),
            "timestamp": time.time()
        }), 500

@app.route('/stats')
def stats_page():
    """Страница статистики"""
    try:
        top_users = get_fissure_top(5)
        stats_text = "<h2>🏆 Топ-5 Фиссур</h2><ul>"
        for i, user in enumerate(top_users, 1):
            username = user['username'] or f"User {user['telegram_id']}"
            stats_text += f"<li>{i}. {username} — {user['fissure']:.1f} см</li>"
        stats_text += "</ul>"
        return stats_text
    except Exception as e:
        return f"<p>Ошибка: {str(e)}</p>"

# Telegram бот функции
def main_menu():
    keyboard = [
        [KeyboardButton("📈 Увеличить фиссуру")],
        [KeyboardButton("📏 Моя длина"), KeyboardButton("🏆 Топ")],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def format_time(seconds):
    h = seconds // 3600
    m = (seconds % 3600) // 60
    return f"{int(h)}ч {int(m)}м"

FISSURE_TEXTS = {
    10: "💀 ЛЕГЕНДА! +10 см!",
    5: "🎉 +5 см!",
    3: "🔥 +3 см",
    1: "🙂 +1 см",
    0: "🤷 Без изменений",
    -1: "😅 -1 см",
    -3: "📉 -3 см",
    -5: "💔 -5 см...",
}

async def fissure(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /fissure"""
    logger.info(f"Пользователь {update.effective_user.id} вызвал fissure")
    
    uid = update.effective_user.id
    user_obj = update.effective_user
    username = user_obj.username or user_obj.first_name
    now = time.time()
    
    try:
        user = get_user(uid, username)
        
        if now - user["last_fissure"] < COOLDOWN:
            wait = COOLDOWN - (now - user["last_fissure"])
            await update.message.reply_text(
                f"⏳ Фиссура ещё восстанавливается.\nЖди: {format_time(wait)}"
            )
            return

        roll = random.choice(ROLLS)
        new_fissure = max(0.1, user["fissure"] + roll)
        update_fissure(uid, new_fissure, now)
        
        logger.info(f"Пользователь {uid} использовал фиссуру. Новое время перезарядки: {now}")

        await update.message.reply_text(
            f"{FISSURE_TEXTS[roll]}\n📏 Теперь длина: {new_fissure:.1f} см"
        )
        
    except Exception as e:
        logger.error(f"Ошибка в fissure: {e}")
        await update.message.reply_text("❌ Ошибка при обработке запроса")

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать статистику"""
    logger.info(f"Пользователь {update.effective_user.id} вызвал stats")
    
    try:
        uid = update.effective_user.id
        user_obj = update.effective_user
        username = user_obj.username or user_obj.first_name
        user = get_user(uid, username)
        await update.message.reply_text(f"📏 Текущая длина фиссуры: {user['fissure']:.1f} см")
    except Exception as e:
        logger.error(f"Ошибка в stats: {e}")
        await update.message.reply_text("❌ Ошибка при получении статистики")

async def top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать топ"""
    logger.info(f"Пользователь {update.effective_user.id} вызвал top")
    
    try:
        top_users = get_fissure_top()
        logger.info(f"Получено {len(top_users)} пользователей для топа")
        
        if not top_users:
            await update.message.reply_text("🏆 Топ Фиссур:\n\nПока нет данных для отображения топа")
            return
            
        text = "🏆 Топ Фиссур:\n\n"
        for i, u in enumerate(top_users, 1):
            username = u['username'] or f"Пользователь {u['telegram_id']}"
            text += f"{i}. {username} — {u['fissure']:.1f} см\n"
        await update.message.reply_text(text)
    except Exception as e:
        logger.error(f"Ошибка в top: {e}")
        await update.message.reply_text("❌ Ошибка при получении топа")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    logger.info(f"Новый пользователь {update.effective_user.id}")
    
    try:
        uid = update.effective_user.id
        user_obj = update.effective_user
        username = user_obj.username or user_obj.first_name
        get_user(uid, username)
        await update.message.reply_text(
            "Добро пожаловать!\nЗдесь можно увеличить фиссуру 😈",
            reply_markup=main_menu()
        )
    except Exception as e:
        logger.error(f"Ошибка в start: {e}")
        await update.message.reply_text("❌ Ошибка при запуске бота")

async def menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик кнопок меню"""
    logger.info(f"Пользователь {update.effective_user.id} нажал кнопку: {update.message.text}")
    
    try:
        text = update.message.text

        if text == "📈 Увеличить фиссуру":
            await fissure(update, context)
        elif text == "📏 Моя длина":
            await stats(update, context)
        elif text == "🏆 Топ":
            await top(update, context)
        else:
            await update.message.reply_text("Используйте кнопки меню или команды")
    except Exception as e:
        logger.error(f"Ошибка в menu_handler: {e}")
        await update.message.reply_text("❌ Ошибка при обработке команды")

def run_flask():
    """Запуск Flask сервера"""
    port = int(os.getenv("PORT", 10000))
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)

def run_telegram_bot():
    """Запуск Telegram бота"""
    # Инициализируем базу данных
    init_db()
    
    # Настраиваем бота с увеличенными таймаутами
    request = HTTPXRequest(
        connection_pool_size=10,
        read_timeout=30,
        write_timeout=30,
        connect_timeout=30,
        pool_timeout=30
    )
    
    # Создаем приложение
    global bot_app
    bot_app = Application.builder().token(TOKEN).request(request).build()
    
    # Добавляем обработчики
    bot_app.add_handler(CommandHandler("start", start))
    bot_app.add_handler(CommandHandler("fissure", fissure))
    bot_app.add_handler(CommandHandler("stats", stats))
    bot_app.add_handler(CommandHandler("top", top))
    bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, menu_handler))
    
    logger.info("✅ Telegram бот запущен в режиме polling")
    
    # Запускаем polling
    bot_app.run_polling(
        drop_pending_updates=True,
        allowed_updates=Update.ALL_TYPES,
        close_loop=False  # Важно для работы с Flask
    )

def main():
    """Главная функция запуска"""
    # Запускаем self-ping в отдельном потоке
    ping_thread = threading.Thread(target=keep_alive, daemon=True)
    ping_thread.start()
    
    # Запускаем Flask в отдельном потоке
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    
    # Запускаем Telegram бота в основном потоке
    run_telegram_bot()

if __name__ == "__main__":
    main()