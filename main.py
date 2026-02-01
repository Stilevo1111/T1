# -*- coding: utf-8 -*-
import os
import random
import time
import asyncio
import logging
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters, JobQueue, ChatMemberHandler
from telegram.error import Conflict
from database import init_db, get_user, update_fissure, get_fissure_top, update_last_message_id, Database
from aiohttp import web

# Logging setup
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    print("WARNING: BOT_TOKEN is not set!")
else:
    print("BOT_TOKEN found")

COOLDOWN = 86400  # 24 hours

# =====================
# ROLL SYSTEM
# =====================

BASE_ROLLS = [-3, -1, 0, 1, 3, 5, 10, 20]
FATAL_ROLL = -10

# =====================
# ROLL TEXTS
# =====================

ROLL_TEXTS = {
    50: ["INcredible! +50 cm!", "JACKPOT! +50 cm at once!"],
    30: ["COSMOS! +30 cm!", "SUPER LUCK! +30 cm!"],
    20: ["MEGA SUCCESS! +20 cm!", "BULLSEYE! +20 cm!"],
    10: ["LEGEND! +10 cm!", "FIRE! +10 cm!"],
    5: ["HOORAY! +5 cm!", "GREAT! +5 cm!"],
    3: ["NOT BAD! +3 cm", "GROWING! +3 cm"],
    1: ["OK! +1 cm", "THERE IS GROWTH! +1 cm"],
    0: ["NO CHANGES", "STANDING STILL"],
    -1: ["SOMEWHAT -1 cm", "MINUS EXISTS -1 cm"],
    -3: ["OOPS... -3 cm", "DROPPED -3 cm"],
    -5: ["PAINFUL -5 cm...", "FAIL -5 cm"],
    -10: ["CATASTROPHE! -10 cm!!!", "APOCALYPSE! -10 cm!!!"]
}

ROLL_MEMES = {
    50: [
        "Your fissure is bigger than someone's self-esteem!",
        "Random passerby: 'What is that big thing?'",
        "Now you can start your own OnlyFissures channel!"
    ],
    30: [
        "It's like finding 1000 rubles in old jeans!",
        "Now you can reach the remote without getting up!",
        "Congratulations accepted in rubles, dollars, and cm!"
    ],
    20: [
        "Your fissure grew bigger than Tesla stocks!",
        "Now it's not fissure, but fissURAAAA!",
        "Size matters! (it turned out)"
    ],
    10: [
        "It's like getting a bonus on Monday!",
        "Fissure: 'I'm growing up!'",
        "Now you're 10 cm closer to the ceiling!"
    ],
    5: [
        "It's like finding 500 rubles in your pocket!",
        "Average Russian is happy!",
        "Can measure with an Ikea ruler!"
    ],
    3: [
        "Three centimeters of happiness!",
        "Like three rubles in wallet - small but nice!",
        "Slowly but surely!"
    ],
    1: [
        "Small but fierce!",
        "One cm is better than zero cm!",
        "Fissure said: 'I'm trying!'"
    ],
    0: [
        "Stability is a sign of mastery!",
        "Fissure decided to rest!",
        "Neither decreased nor increased!"
    ],
    -1: [
        "Fissure is on a diet!",
        "One small step back for a big jump forward!",
        "One centimeter burned... like a match!"
    ],
    -3: [
        "Three centimeters to nowhere!",
        "Oops! The fissure sneezed!",
        "Gravity wins this round!"
    ],
    -5: [
        "When your fissure goes on strike!",
        "Minus five - like a bad review!",
        "Fissure: 'I need a vacation!'"
    ],
    -10: [
        "TOTAL ANNIHILATION!",
        "From hero to zero!",
        "The fissure has left the chat!"
    ]
}

CATEGORY_PHRASES = {
    "up": [
        "Growing strong!",
        "Every cm counts!",
        "Fissure approves!",
        "Positive dynamics!",
        "Keep it up!",
        "On the rise!"
    ],
    "down": [
        "A small setback!",
        "Fissure will recover!",
        "Tomorrow is a new day!",
        "Temporary decline!",
        "Stay strong!",
        "This is not the end!"
    ],
    "same": [
        "Stability is good!",
        "Holding the line!",
        "No changes - also a result!",
        "Steady as she goes!",
        "Consistency matters!",
        "Solid foundation!"
    ],
    "bonus_help": [
        "SYSTEM HELP ACTIVATED!",
        "Lucky break!",
        "Bonus achieved!",
        "Critical support!",
        "Jackpot mode!",
        "Bonus multiplier!"
    ],
    "fatal": [
        "CRITICAL HIT!",
        "But you stayed!",
        "SURVIVED!",
        "Still in the game!",
        "Resilience!",
        "Never give up!"
    ]
}

WELCOME_PHRASES = [
    "Welcome, {name}! Your fissure journey begins now!",
    "Nice to see you, {name}! Time to grow!",
    "{name} joined! The fissure community grows!",
    "Hello, {name}! Let's increase together!",
    "{name} is here! New opportunities await!",
    "Welcome, {name}! Your fissure awaits!",
    "Nice to have you, {name}! Let's get bigger!",
    "{name} joined the fissure club!",
    "Hey, {name}! Time to measure!",
    "{name} is ready to grow!"
]

bot_messages = {}
AUTO_DELETE_TIME = 30

def add_bot_message(chat_id: int, message_id: int):
    if chat_id not in bot_messages:
        bot_messages[chat_id] = {}
    bot_messages[chat_id][message_id] = time.time()

async def cleanup_old_messages(bot):
    now = time.time()
    for chat_id in list(bot_messages.keys()):
        for msg_id, timestamp in list(bot_messages[chat_id].items()):
            if now - timestamp > AUTO_DELETE_TIME:
                try:
                    await bot.delete_message(chat_id, msg_id)
                    del bot_messages[chat_id][msg_id]
                except:
                    pass
        if not bot_messages[chat_id]:
            del bot_messages[chat_id]

def calculate_fissure_roll(current_fissure):
    """
    Calculates new roll based on current fissure size
    Returns: (roll_value, message, is_fatal, got_help)
    """
    if current_fissure >= 5:
        fatal_chance = min(0.05, current_fissure / 500)
        if random.random() < fatal_chance:
            return FATAL_ROLL, "FATAL DECREASE!", True, False
    
    if current_fissure < 0.5:
        if random.random() < 0.8:
            bonus_options = [
                (5, 30), (10, 25), (20, 20), (30, 15), (50, 10)
            ]
            values, weights = zip(*bonus_options)
            roll = random.choices(values, weights=weights)[0]
            return roll, "MAXIMUM SYSTEM HELP!", False, True
        
        protected_rolls = [0, 1, 3, 5, 10, 20]
        roll = random.choice(protected_rolls)
        return roll, "PROTECTED ROLL", False, True
    
    elif current_fissure < 2:
        if random.random() < 0.4:
            improved_options = [3, 5, 10, 20]
            roll = random.choice(improved_options)
            return roll, "IMPROVED ROLL!", False, True
        
        weighted_rolls = [
            (-3, 5), (-1, 10), (0, 15), (1, 20), (3, 20), (5, 15), (10, 10), (20, 5)
        ]
        values, weights = zip(*weighted_rolls)
        roll = random.choices(values, weights=weights)[0]
        return roll, "", False, False
    
    elif current_fissure < 20:
        if random.random() < 0.2:
            bonus = random.choice([5, 10, 20])
            return bonus, "LUCKY ROLL!", False, False
        
        weighted_rolls = [
            (-3, 10), (-1, 15), (0, 20), (1, 20), (3, 15), (5, 10), (10, 7), (20, 3)
        ]
        values, weights = zip(*weighted_rolls)
        roll = random.choices(values, weights=weights)[0]
        return roll, "", False, False
    
    else:
        risky_rolls = [
            (-3, 15), (-1, 20), (0, 15), (1, 15), (3, 10), (5, 10), (10, 5), (20, 3), (50, 2)
        ]
        values, weights = zip(*risky_rolls)
        roll = random.choices(values, weights=weights)[0]
        return roll, "", False, False

def apply_fissure_protection(current_fissure, roll, is_fatal):
    """Applies protection for small fissures on fatal rolls"""
    if is_fatal and current_fissure < 5:
        reduced_roll = max(-5, roll)
        protection_msg = f"DAMAGE REDUCED! Was {roll}, now {reduced_roll}"
        return reduced_roll, protection_msg
    
    return roll, ""

def calculate_new_fissure(current_fissure, roll):
    """Calculates new fissure size with minimum 0.1"""
    new_value = current_fissure + roll
    return max(0.1, new_value)

def main_menu():
    keyboard = [
        [KeyboardButton("📈 Увеличить фиссуру")],
        [KeyboardButton("📏 Моя длина"), KeyboardButton("🏆 Топ")],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def format_time(seconds):
    h = seconds // 3600
    m = (seconds % 3600) // 60
    return f"{int(h)}h {int(m)}m"

async def delete_previous_message(bot, chat_id, last_message_id):
    """Deletes previous bot message"""
    try:
        if last_message_id and last_message_id > 0:
            await bot.delete_message(chat_id, last_message_id)
            logger.info(f"Deleted previous message: {last_message_id}")
    except Exception as e:
        logger.debug(f"Could not delete previous message: {e}")

async def delete_user_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Deletes user message"""
    try:
        logger.info(f"Deleting user message: {update.message.message_id}")
        await context.bot.delete_message(
            chat_id=update.message.chat_id,
            message_id=update.message.message_id
        )
    except Exception as e:
        logger.debug(f"Could not delete user message: {e}")

async def send_or_update_message(bot, chat_id, text, reply_markup=None, last_message_id=None):
    """Sends or updates a message"""
    try:
        if last_message_id and last_message_id > 0:
            try:
                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=last_message_id,
                    text=text,
                    reply_markup=reply_markup
                )
                return last_message_id
            except:
                pass
        result = await bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=reply_markup
        )
        return result.message_id
    except Exception as e:
        logger.error(f"Error sending message: {e}")
        return None

async def fissure(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Increase fissure"""
    logger.info(f"User {update.effective_user.id} called fissure")
    
    await cleanup_old_messages(context.bot)
    
    user_obj = update.effective_user
    username = user_obj.username or user_obj.first_name
    now = time.time()
    
    try:
        user = get_user(user_obj.id, username)
        logger.info(f"user data: {user}")
        
        if now - user["last_fissure"] < COOLDOWN:
            wait = COOLDOWN - (now - user["last_fissure"])
            text = f"Fissure is still recovering. Wait: {format_time(wait)}"
            message_id = await send_or_update_message(
                context.bot,
                update.message.chat_id,
                text,
                main_menu(),
                user.get("last_message_id", 0)
            )
            update_last_message_id(user_obj.id, message_id)
            return

        roll, special_message, is_fatal, got_help = calculate_fissure_roll(user["fissure"])
        roll, protection_msg = apply_fissure_protection(user["fissure"], roll, is_fatal)
        new_fissure = calculate_new_fissure(user["fissure"], roll)
        update_fissure(user_obj.id, new_fissure, now)
        
        logger.info(f"User {user_obj.id} used fissure. New cooldown: {now}")

        roll_key = min(roll, 50)
        roll_key = max(roll_key, -10)
        
        if roll_key in ROLL_TEXTS:
            result_text = random.choice(ROLL_TEXTS[roll_key])
        else:
            result_text = f"{'+' if roll > 0 else ''}{roll} cm"
        
        if is_fatal:
            category = "fatal"
        elif got_help:
            category = "bonus_help"
        elif roll > 0:
            category = "up"
        elif roll < 0:
            category = "down"
        else:
            category = "same"
        
        if roll_key in ROLL_MEMES and random.random() < 0.5:
            extra_text = random.choice(ROLL_MEMES[roll_key])
        else:
            extra_text = random.choice(CATEGORY_PHRASES[category])
        
        text = f"{result_text}\n{extra_text}\n\nLength now: {new_fissure:.1f} cm"
        
        if is_fatal and protection_msg:
            text = f"{text}\n\n{protection_msg}"
        
        try:
            # Send as NEW message with keyboard (Telegram doesn't show keyboard with reply)
            result_msg = await context.bot.send_message(
                chat_id=update.message.chat_id,
                text=text,
                reply_markup=main_menu()
            )
            logger.info(f"Result sent to user {user_obj.id}")
            add_bot_message(result_msg.chat_id, result_msg.message_id)
            # Delete user's message
            try:
                await delete_user_message(update, context)
            except Exception as e:
                logger.error(f"Could not delete user message: {e}")
                
        except Exception as e:
            logger.error(f"Send error: {e}")
            message_id = await send_or_update_message(
                context.bot,
                update.message.chat_id,
                text,
                main_menu(),
                user.get("last_message_id", 0)
            )
            update_last_message_id(user_obj.id, message_id)
            
            try:
                await delete_user_message(update, context)
                add_bot_message(update.message.chat_id, message_id)
            except Exception as e:
                logger.error(f"Delete error: {e}")
        
    except Exception as e:
        logger.error(f"Error in fissure: {e}")
        await update.message.reply_text("Error processing request")

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show stats"""
    logger.info(f"User {update.effective_user.id} called stats")
    
    # Clean up old bot messages
    await cleanup_old_messages(context.bot)
    
    try:
        user_obj = update.effective_user
        username = user_obj.username or user_obj.first_name
        user = get_user(user_obj.id, username)
        
        last_fissure_time = user["last_fissure"]
        now = time.time()
        time_since_last = now - last_fissure_time
        remaining_cooldown = max(0, COOLDOWN - time_since_last)
        
        if remaining_cooldown > 0:
            wait_text = f"Recovery: {format_time(remaining_cooldown)}"
        else:
            wait_text = "Ready to increase!"
        
        text = (
            f"📊 Your Stats\n\n"
            f"📏 Current length: {user['fissure']:.1f} cm\n"
            f"📈 Total growth: {user['total_growth']:.1f} cm\n"
            f"🔄 Total rolls: {user['total_rolls']}\n"
            f"⏰ {wait_text}"
        )
        
        try:
            result_msg = await context.bot.send_message(
                chat_id=update.message.chat_id,
                text=text,
                reply_markup=main_menu()
            )
            add_bot_message(result_msg.chat_id, result_msg.message_id)
            try:
                await delete_user_message(update, context)
            except Exception as e:
                logger.debug(f"Could not delete user message: {e}")
        except Exception as e:
            logger.error(f"Send error: {e}")
            message_id = await send_or_update_message(
                context.bot,
                update.message.chat_id,
                text,
                main_menu(),
                user.get("last_message_id", 0)
            )
            update_last_message_id(user_obj.id, message_id)
        
    except Exception as e:
        logger.error(f"Error in stats: {e}")
        await update.message.reply_text("Error getting stats")

async def top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show top users"""
    logger.info(f"User {update.effective_user.id} called top")
    
    # Clean up old bot messages
    await cleanup_old_messages(context.bot)
    
    try:
        top_users = get_fissure_top(10)
        
        if not top_users:
            text = "No users yet. Be the first!"
        else:
            text = "🏆 Top 10 Fissures\n\n"
            for i, user in enumerate(top_users, 1):
                name = user.get('username', 'Unknown')[:15]
                text += f"{i}. {name}: {user['fissure']:.1f} cm\n"
        
        try:
            result_msg = await context.bot.send_message(
                chat_id=update.message.chat_id,
                text=text,
                reply_markup=main_menu()
            )
            add_bot_message(result_msg.chat_id, result_msg.message_id)
            try:
                await delete_user_message(update, context)
            except Exception as e:
                logger.debug(f"Could not delete user message: {e}")
        except Exception as e:
            logger.error(f"Send error: {e}")
            user_obj = update.effective_user
            user = get_user(user_obj.id, user_obj.username or user_obj.first_name)
            message_id = await send_or_update_message(
                context.bot,
                update.message.chat_id,
                text,
                main_menu(),
                user.get("last_message_id", 0)
            )
            update_last_message_id(user_obj.id, message_id)
        
    except Exception as e:
        logger.error(f"Error in top: {e}")
        await update.message.reply_text("Error getting top")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    logger.info(f"New user {update.effective_user.id}")
    
    # Clean up old bot messages
    await cleanup_old_messages(context.bot)
    
    try:
        uid = update.effective_user.id
        user_obj = update.effective_user
        username = user_obj.username or user_obj.first_name
        user = get_user(uid, username)
        logger.info(f"start user data: {user}")
        
        text = "Welcome! You can increase your fissure here"
        message_id = await send_or_update_message(
            context.bot,
            update.message.chat_id,
            text,
            main_menu(),
            user.get("last_message_id", 0)
        )
        update_last_message_id(uid, message_id)
        
        try:
            await delete_user_message(update, context)
            add_bot_message(update.message.chat_id, message_id)
        except Exception as e:
            logger.error(f"Delete error: {e}")
        
    except Exception as e:
        logger.error(f"Error in start: {e}")
        text = "Error starting bot"
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
    """Menu button handler"""
    text = update.message.text
    
    menu_buttons = ["📈 Увеличить фиссуру", "📏 Моя длина", "🏆 Топ"]
    
    if text not in menu_buttons:
        return
    
    logger.info(f"User {update.effective_user.id} pressed button: {text}")
    
    # Clean up old bot messages
    await cleanup_old_messages(context.bot)
    
    try:
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
    except Exception as e:
        logger.error(f"Error in menu_handler: {e}")
        await update.message.reply_text("Error processing command")

    try:
        await context.bot.delete_message(update.message.chat_id, update.message.message_id)
    except Exception as e:
        logger.debug(f"Could not delete message: {e}")

async def health_check(request):
    """Health check endpoint for Render"""
    return web.Response(text="Bot is working", status=200)

async def welcome_new_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Welcome new chat member"""
    try:
        chat_id = update.my_chat_member.chat.id
        new_user = update.my_chat_member.new_chat_member
        
        if new_user.status in ['member', 'administrator']:
            name = new_user.user.first_name or "Friend"
            
            welcome_text = random.choice(WELCOME_PHRASES).format(name=name)
            
            await context.bot.send_message(
                chat_id=chat_id,
                text=welcome_text
            )
            logger.info(f"Welcome sent for {name}")
            
    except Exception as e:
        logger.error(f"Error in welcome_new_member: {e}")

async def wake_up_callback(context: ContextTypes.DEFAULT_TYPE):
    """Periodic wake-up to prevent sleeping"""
    logger.info("Wake-up: bot is active")

def setup_wake_up(job_queue: JobQueue):
    """Sets up periodic wake-up every 14 minutes"""
    wake_up_interval = 14 * 60
    job_queue.run_repeating(wake_up_callback, wake_up_interval, first=60)
    logger.info(f"Wake-up configured: every {wake_up_interval} seconds")

async def main():
    """Start Telegram bot in webhook mode for Render"""
    if not TOKEN:
        logger.error("BOT_TOKEN not set! Bot cannot start.")
        return
    
    try:
        init_db()
        
        app = ApplicationBuilder().token(TOKEN).job_queue(JobQueue()).build()

        app.add_handler(CommandHandler("start", start))
        app.add_handler(CommandHandler("fissure", fissure))
        app.add_handler(CommandHandler("stats", stats))
        app.add_handler(CommandHandler("top", top))
        app.add_handler(MessageHandler(filters.Regex(r'^/start@DotaFull_bot$'), start))
        app.add_handler(MessageHandler(filters.Regex(r'^/fissure@DotaFull_bot$'), fissure))
        app.add_handler(MessageHandler(filters.Regex(r'^/stats@DotaFull_bot$'), stats))
        app.add_handler(MessageHandler(filters.Regex(r'^/top@DotaFull_bot$'), top))
        app.add_handler(MessageHandler(filters.Regex(r'^(📈 Увеличить фиссуру|📏 Моя длина|🏆 Топ)$'), menu_handler))
        app.add_handler(ChatMemberHandler(welcome_new_member, ChatMemberHandler.CHAT_MEMBER))

        webhook_url = os.getenv("WEBHOOK_URL")
        if not webhook_url:
            logger.error("WEBHOOK_URL not set!")
            return
            
        await app.bot.set_webhook(url=webhook_url)
        await app.initialize()
        
        logger.info("Telegram bot started in webhook mode")
        logger.info(f"Webhook URL: {webhook_url}")
        
        setup_wake_up(app.job_queue)
        
        from aiohttp import web
        
        async def handle_webhook(request):
            """Handle incoming webhook requests"""
            try:
                update_data = await request.json()
                logger.info(f"Webhook received: {update_data.get('update_id', 'unknown')}")
                update = Update.de_json(update_data, app.bot)
                logger.info(f"Update parsed: {update}")
                await app.process_update(update)
                logger.info(f"Update processed")
                return web.Response(status=200)
            except Exception as e:
                logger.error(f"Webhook error: {e}", exc_info=True)
                return web.Response(status=500)
        
        web_app = web.Application()
        web_app.router.add_post('/webhook', handle_webhook)
        web_app.router.add_get('/health', health_check)
        
        runner = web.AppRunner(web_app)
        await runner.setup()
        site = web.TCPSite(runner, '0.0.0.0', int(os.getenv('PORT', 8080)))
        await site.start()
        
        logger.info("Web server started")
        
        while True:
            await asyncio.sleep(3600)
            
    except Exception as e:
        logger.error(f"Critical error: {e}", exc_info=True)
        raise

async def main_polling():
    """Start Telegram bot in polling mode for local testing"""
    if not TOKEN:
        logger.error("BOT_TOKEN not set!")
        return
    
    try:
        init_db()
        
        app = ApplicationBuilder().token(TOKEN).job_queue(JobQueue()).build()

        app.add_handler(CommandHandler("start", start))
        app.add_handler(CommandHandler("fissure", fissure))
        app.add_handler(CommandHandler("stats", stats))
        app.add_handler(CommandHandler("top", top))
        app.add_handler(MessageHandler(filters.Regex(r'^/start@DotaFull_bot$'), start))
        app.add_handler(MessageHandler(filters.Regex(r'^/fissure@DotaFull_bot$'), fissure))
        app.add_handler(MessageHandler(filters.Regex(r'^/stats@DotaFull_bot$'), stats))
        app.add_handler(MessageHandler(filters.Regex(r'^/top@DotaFull_bot$'), top))
        app.add_handler(MessageHandler(filters.Regex(r'^(📈 Увеличить фиссуру|📏 Моя длина|🏆 Топ)$'), menu_handler))
        app.add_handler(ChatMemberHandler(welcome_new_member, ChatMemberHandler.CHAT_MEMBER))

        logger.info("Telegram bot started in polling mode")
        
        await app.run_polling(drop_pending_updates=True)
        
    except Exception as e:
        logger.error(f"Critical error: {e}", exc_info=True)
        raise

if __name__ == "__main__":
    if os.getenv("WEBHOOK_URL"):
        asyncio.run(main())
    else:
        asyncio.run(main_polling())
