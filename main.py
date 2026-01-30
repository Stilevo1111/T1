import os
import random
import time
import asyncio
import logging
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
from telegram.error import Conflict
from database import init_db, get_user, update_fissure, get_fissure_top, Database
from aiohttp import web

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

FISURE_TEXTS = {
    10: "💀 ЛЕГЕНДА! +10 см!",
    5: "🎉 +5 см!",
    3: "🔥 +3 см",
    1: "🙂 +1 см",
    0: "🤷 Без изменений",
    -1: "😅 -1 см",
    -3: "📉 -3 см",
    -5: "💔 -5 см...",
}

FISURE_PHRASES = {
    "up": ["Растёт… и ничего не спрашивает.", "Бот инвестирует в твой успех 💸"],
    "same": ["Стоит на месте… зато уверенно.", "Всё стабильно, как кофе утром ☕"],
    "down": ["Сжалась… тихо так, но гордо.", "Ну вот, маленький минус… как жизнь 😅"]
}

FISURE_MEMES = [
    "💀 Когда фиссура больше, чем твои амбиции",
    "🎉 Празднуем каждый сантиметр!",
    "🔥 Фиссура горит, как моя подписка на кофе ☕",
]

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

async def auto_delete(message, delay=30):
    """Удаляет сообщение через указанное количество секунд"""
    try:
        await asyncio.sleep(delay)
        await message.delete()
    except Exception as e:
        logger.debug(f"Не удалось удалить сообщение: {e}")

def schedule_message_deletion(message, delay=30):
    """Планирует удаление сообщения"""
    try:
        # Используем правильный способ создания фоновых задач
        context.application.create_task(auto_delete(message, delay))
    except Exception as e:
        logger.error(f"Ошибка при планировании удаления сообщения: {e}")

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
            msg = await update.message.reply_text(
                f"⏳ Фиссура ещё восстанавливается.\nЖди: {format_time(wait)}"
            )
            schedule_message_deletion(msg, 30)
            schedule_message_deletion(update.message, 10)
            return

        roll = random.choice(ROLLS)
        new_fissure = max(0.1, user["fissure"] + roll)
        update_fissure(uid, new_fissure, now)
        
        # Логируем успешное обновление времени перезарядки
        logger.info(f"Пользователь {uid} использовал фиссуру. Новое время перезарядки: {now}")

        if roll > 0:
            phrase = random.choice(FISURE_PHRASES["up"])
        elif roll < 0:
            phrase = random.choice(FISURE_PHRASES["down"])
        else:
            phrase = random.choice(FISURE_PHRASES["same"])

        meme = random.choice(FISURE_MEMES)

        msg = await update.message.reply_text(
            f"{FISURE_TEXTS[roll]}\n{phrase}\n\n{meme}\n📏 Теперь длина: {new_fissure:.1f} см"
        )
        schedule_message_deletion(msg, 30)
        schedule_message_deletion(update.message, 10)
        
    except Exception as e:
        logger.error(f"Ошибка в fissure: {e}")
        msg = await update.message.reply_text("❌ Ошибка при обработке запроса")
        schedule_message_deletion(msg, 10)
        schedule_message_deletion(update.message, 10)

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать статистику"""
    logger.info(f"Пользователь {update.effective_user.id} вызвал stats")
    
    try:
        uid = update.effective_user.id
        user_obj = update.effective_user
        username = user_obj.username or user_obj.first_name
        user = get_user(uid, username)
        msg = await update.message.reply_text(f"📏 Текущая длина фиссуры: {user['fissure']:.1f} см")
        schedule_message_deletion(msg, 30)
        schedule_message_deletion(update.message, 10)
    except Exception as e:
        logger.error(f"Ошибка в stats: {e}")
        msg = await update.message.reply_text("❌ Ошибка при получении статистики")
        schedule_message_deletion(msg, 10)
        schedule_message_deletion(update.message, 10)

async def top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать топ"""
    logger.info(f"Пользователь {update.effective_user.id} вызвал top")
    
    try:
        top_users = get_fissure_top()
        logger.info(f"Получено {len(top_users)} пользователей для топа")
        
        if not top_users:
            msg = await update.message.reply_text("🏆 Топ Фиссур:\n\nПока нет данных для отображения топа")
            schedule_message_deletion(msg, 30)
            return
            
        text = "🏆 Топ Фиссур:\n\n"
        for i, u in enumerate(top_users, 1):
            user_obj = update.effective_user
            username = u['username'] or f"Пользователь {u['telegram_id']}"
            text += f"{i}. {username} — {u['fissure']:.1f} см\n"
        msg = await update.message.reply_text(text)
        schedule_message_deletion(msg, 30)
        schedule_message_deletion(update.message, 10)
    except Exception as e:
        logger.error(f"Ошибка в top: {e}")
        msg = await update.message.reply_text("❌ Ошибка при получении топа")
        schedule_message_deletion(msg, 10)
        schedule_message_deletion(update.message, 10)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    logger.info(f"Новый пользователь {update.effective_user.id}")
    
    try:
        uid = update.effective_user.id
        user_obj = update.effective_user
        username = user_obj.username or user_obj.first_name
        get_user(uid, username)
        msg = await update.message.reply_text(
            "Добро пожаловать!\nЗдесь можно увеличить фиссуру 😈",
            reply_markup=main_menu()
        )
        schedule_message_deletion(msg, 30)
    except Exception as e:
        logger.error(f"Ошибка в start: {e}")
        msg = await update.message.reply_text("❌ Ошибка при запуске бота")
        schedule_message_deletion(msg, 10)
        schedule_message_deletion(update.message, 10)

async def menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик кнопок меню"""
    logger.info(f"Пользователь {update.effective_user.id} нажал кнопку: {update.message.text}")
    
    try:
        text = update.message.text
        uid = update.effective_user.id
        user_obj = update.effective_user
        username = user_obj.username or user_obj.first_name
        get_user(uid, username)

        # Удаляем сообщение от кнопки через 10 секунд
        schedule_message_deletion(update.message, 10)

        if text == "📈 Увеличить фиссуру":
            await fissure(update, context)
        elif text == "📏 Моя длина":
            await stats(update, context)
        elif text == "🏆 Топ":
            await top(update, context)
        else:
            msg = await update.message.reply_text("Используйте кнопки меню или команды")
            schedule_message_deletion(msg, 10)
    except Exception as e:
        logger.error(f"Ошибка в menu_handler: {e}")
        msg = await update.message.reply_text("❌ Ошибка при обработке команды")
        schedule_message_deletion(msg, 10)

    # Удаление сообщений с командами /fissure@DotaFull_bot, /top@DotaFull_bot, /stats@DotaFull_bot
    if update.message.text and any(cmd in update.message.text for cmd in ['/fissure@DotaFull_bot', '/top@DotaFull_bot', '/stats@DotaFull_bot']):
        await asyncio.sleep(10)
        try:
            await context.bot.delete_message(update.message.chat.id, update.message.message_id)
        except Exception as e:
            pass

async def health_check(request):
    """Health check endpoint for Render"""
    return web.Response(text="✅ Бот работает", status=200)

async def main():
    """Запуск Telegram бота в режиме webhook для Render"""
    try:
        init_db()
        
        # Создаем Telegram бота
        telegram_app = ApplicationBuilder().token(TOKEN).build()

        # Добавляем обработчики команд
        telegram_app.add_handler(CommandHandler("start", start))
        telegram_app.add_handler(CommandHandler("fissure", fissure))
        telegram_app.add_handler(CommandHandler("stats", stats))
        telegram_app.add_handler(CommandHandler("top", top))
        telegram_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, menu_handler))

        logger.info("✅ Telegram бот запущен в режиме webhook")
        
        # Инициализируем приложение
        await telegram_app.initialize()
        
        # Получаем URL для webhook
        port = int(os.getenv("PORT", 10000))
        webhook_path = "/webhook"

        service_name = os.getenv("RENDER_SERVICE_NAME", "fissure-bot")
        webhook_url = os.getenv("WEBHOOK_URL") or f"https://{service_name}.onrender.com{webhook_path}"
        
        # Единый aiohttp сервер
        web_app = web.Application()
        web_app.router.add_get("/health", health_check)

        # Устанавливаем webhook
        await telegram_app.bot.set_webhook(webhook_url)
        await telegram_app.start()

        # Telegram webhook endpoint
        web_app.router.add_post(webhook_path, telegram_app.webhook_handler)

        runner = web.AppRunner(web_app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", port)
        await site.start()
        
        logger.info(f"🚀 Webhook и health работают на одном порту {port}")
        logger.info(f"🏥 Health check доступен на /health")
        logger.info(f"📨 Webhook доступен на {webhook_path}")
        
        # Ждем завершения (никогда не завершится без сигнала)
        await asyncio.Event().wait()
        
    except Conflict as e:
        logger.error(f"❌ Конфликт webhook: {e}")
        logger.error("💡 Это может означать, что другой экземпляр бота уже использует этот токен")
        logger.error("💡 Убедитесь, что на Render запущен только один экземпляр бота")
        raise
    except Exception as e:
        logger.error(f"❌ Критическая ошибка: {e}", exc_info=True)
        raise

if __name__ == "__main__":
    asyncio.run(main())
