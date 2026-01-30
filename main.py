import os
import random
import time
import asyncio
import logging
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
from telegram.error import Conflict
from database import init_db, get_user, update_fissure, get_fissure_top, update_last_message_id, Database
from aiohttp import web

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    print("⚠️ BOT_TOKEN не задан! Бот будет работать в режиме ограниченного тестирования.")
    print("💡 Для полноценной работы получите токен у @BotFather в Telegram")
else:
    print("✅ BOT_TOKEN найден")

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

async def delete_previous_message(bot, chat_id, last_message_id):
    """Удаляет предыдущее сообщение бота"""
    try:
        if last_message_id and last_message_id > 0:
            await bot.delete_message(chat_id, last_message_id)
            logger.info(f"Удалено предыдущее сообщение: {last_message_id}")
    except Exception as e:
        logger.debug(f"Не удалось удалить предыдущее сообщение: {e}")

async def send_or_update_message(bot, chat_id, text, reply_markup=None, last_message_id=0):
    """Отправляет новое сообщение или обновляет существующее"""
    try:
        logger.info(f"send_or_update_message: chat_id={chat_id}, last_message_id={last_message_id}")
        # Сначала отправляем новое сообщение
        msg = await bot.send_message(chat_id, text, reply_markup=reply_markup)
        logger.info(f"Отправлено сообщение: {msg.message_id}")
        
        # Затем удаляем предыдущее сообщение
        await delete_previous_message(bot, chat_id, last_message_id)
        
        return msg.message_id
    except Exception as e:
        logger.error(f"Ошибка отправки сообщения: {e}")
        return 0

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
            text = f"⏳ Фиссура ещё восстанавливается.\nЖди: {format_time(wait)}"
            message_id = await send_or_update_message(
                context.bot,
                update.message.chat_id,
                text,
                None,
                user.get("last_message_id", 0)
            )
            update_last_message_id(uid, message_id)
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
        text = f"{FISURE_TEXTS[roll]}\n{phrase}\n\n{meme}\n📏 Теперь длина: {new_fissure:.1f} см"
        
        # Отправляем сообщение с удалением предыдущего
        message_id = await send_or_update_message(
            context.bot,
            update.message.chat_id,
            text,
            None,
            user.get("last_message_id", 0)
        )
        update_last_message_id(uid, message_id)
        
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
        
        text = f"📏 Текущая длина фиссуры: {user['fissure']:.1f} см"
        message_id = await send_or_update_message(
            context.bot,
            update.message.chat_id,
            text,
            None,
            user.get("last_message_id", 0)
        )
        update_last_message_id(uid, message_id)
        
    except Exception as e:
        logger.error(f"Ошибка в stats: {e}")
        text = "❌ Ошибка при получении статистики"
        message_id = await send_or_update_message(
            context.bot,
            update.message.chat_id,
            text,
            None,
            user.get("last_message_id", 0) if 'user' in locals() else 0
        )
        if 'user' in locals():
            update_last_message_id(uid, message_id)

async def top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать топ"""
    logger.info(f"Пользователь {update.effective_user.id} вызвал top")
    
    try:
        uid = update.effective_user.id
        user_obj = update.effective_user
        username = user_obj.username or user_obj.first_name
        user = get_user(uid, username)
        
        top_users = get_fissure_top()
        logger.info(f"Получено {len(top_users)} пользователей для топа")
        
        if not top_users:
            text = "🏆 Топ Фиссур:\n\nПока нет данных для отображения топа"
            message_id = await send_or_update_message(
                context.bot,
                update.message.chat_id,
                text,
                None,
                user.get("last_message_id", 0)
            )
            update_last_message_id(uid, message_id)
            return
            
        text = "🏆 Топ Фиссур:\n\n"
        for i, u in enumerate(top_users, 1):
            username = u['username'] or f"Пользователь {u['telegram_id']}"
            text += f"{i}. {username} — {u['fissure']:.1f} см\n"
        
        message_id = await send_or_update_message(
            context.bot,
            update.message.chat_id,
            text,
            None,
            user.get("last_message_id", 0)
        )
        update_last_message_id(uid, message_id)
        
    except Exception as e:
        logger.error(f"Ошибка в top: {e}")
        text = "❌ Ошибка при получении топа"
        message_id = await send_or_update_message(
            context.bot,
            update.message.chat_id,
            text,
            None,
            user.get("last_message_id", 0) if 'user' in locals() else 0
        )
        if 'user' in locals():
            update_last_message_id(uid, message_id)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    logger.info(f"Новый пользователь {update.effective_user.id}")
    
    try:
        uid = update.effective_user.id
        user_obj = update.effective_user
        username = user_obj.username or user_obj.first_name
        user = get_user(uid, username)
        
        text = "Добро пожаловать!\nЗдесь можно увеличить фиссуру 😈"
        message_id = await send_or_update_message(
            context.bot,
            update.message.chat_id,
            text,
            main_menu(),
            user.get("last_message_id", 0)
        )
        update_last_message_id(uid, message_id)
        
    except Exception as e:
        logger.error(f"Ошибка в start: {e}")
        text = "❌ Ошибка при запуске бота"
        message_id = await send_or_update_message(
            context.bot,
            update.message.chat_id,
            text,
            None,
            user.get("last_message_id", 0) if 'user' in locals() else 0
        )
        if 'user' in locals():
            update_last_message_id(uid, message_id)

async def menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик кнопок меню"""
    logger.info(f"Пользователь {update.effective_user.id} нажал кнопку: {update.message.text}")
    
    try:
        text = update.message.text
        uid = update.effective_user.id
        user_obj = update.effective_user
        username = user_obj.username or user_obj.first_name
        get_user(uid, username)

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

async def health_check(request):
    """Health check endpoint for Render"""
    return web.Response(text="✅ Бот работает", status=200)

async def main():
    """Запуск Telegram бота в webhook режиме для Render"""
    if not TOKEN:
        logger.error("❌ BOT_TOKEN не задан! Бот не может запуститься.")
        return
    
    try:
        init_db()
        
        # Создаем веб-приложение для webhook
        app = ApplicationBuilder().token(TOKEN).build()

        # Добавляем обработчики команд
        app.add_handler(CommandHandler("start", start))
        app.add_handler(CommandHandler("fissure", fissure))
        app.add_handler(CommandHandler("stats", stats))
        app.add_handler(CommandHandler("top", top))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, menu_handler))

        # Получаем webhook URL из переменных окружения
        webhook_url = os.getenv("WEBHOOK_URL")
        if not webhook_url:
            logger.error("❌ WEBHOOK_URL не задан! Укажите URL для webhook.")
            return
            
        # Настраиваем webhook
        await app.bot.set_webhook(url=webhook_url)
        
        # Инициализируем приложение перед обработкой webhook
        await app.initialize()
        
        logger.info("✅ Telegram бот запущен в режиме webhook")
        logger.info(f"📡 Webhook URL: {webhook_url}")
        
        # Создаем веб-сервер с aiohttp
        from aiohttp import web
        
        async def handle_webhook(request):
            """Обработка входящих webhook запросов"""
            try:
                update_data = await request.json()
                update = Update.de_json(update_data, app.bot)
                await app.process_update(update)
                return web.Response(status=200)
            except Exception as e:
                logger.error(f"Ошибка обработки webhook: {e}")
                return web.Response(status=500)
        
        # Создаем приложение
        web_app = web.Application()
        web_app.router.add_post('/webhook', handle_webhook)
        web_app.router.add_get('/health', health_check)
        
        # Запускаем веб-сервер
        runner = web.AppRunner(web_app)
        await runner.setup()
        site = web.TCPSite(runner, '0.0.0.0', int(os.getenv('PORT', 8080)))
        await site.start()
        
        logger.info("🌐 Веб-сервер запущен")
        
        # Бесконечный цикл для поддержания работы
        while True:
            await asyncio.sleep(3600)
            
    except Exception as e:
        logger.error(f"❌ Критическая ошибка: {e}", exc_info=True)
        raise

async def main_polling():
    """Запуск Telegram бота в режиме polling для локального тестирования"""
    if not TOKEN:
        logger.error("❌ BOT_TOKEN не задан! Бот не может запуститься.")
        return
    
    try:
        init_db()
        
        # Создаем Telegram бота
        app = ApplicationBuilder().token(TOKEN).build()

        # Добавляем обработчики команд
        app.add_handler(CommandHandler("start", start))
        app.add_handler(CommandHandler("fissure", fissure))
        app.add_handler(CommandHandler("stats", stats))
        app.add_handler(CommandHandler("top", top))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, menu_handler))

        logger.info("✅ Telegram бот запущен в режиме polling")
        
        # Запускаем бота в режиме polling
        await app.run_polling(drop_pending_updates=True)
        
    except Exception as e:
        logger.error(f"❌ Критическая ошибка: {e}", exc_info=True)
        raise

if __name__ == "__main__":
    # Запускаем бота с использованием современного подхода asyncio
    try:
        # Используем asyncio.run() для чистого запуска
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 Бот остановлен пользователем")
    except Exception as e:
        print(f"❌ Ошибка запуска бота: {e}")
        raise
