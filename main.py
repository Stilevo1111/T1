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
        "Like losing 300 rubles in a taxi!",
        "Fissure went into reduction!"
    ],
    -5: [
        "Five centimeters into the unknown!",
        "Like spending 500 rubles on something unnecessary!",
        "Fissure is in depression!"
    ],
    -10: [
        "Ten centimeters... like they never existed!",
        "It's like losing your phone with wallet!",
        "Fissure experienced an earthquake!"
    ]
}

# =====================
# CATEGORY PHRASES
# =====================

CATEGORY_PHRASES = {
    "up": [
        "Growing... and asks nothing!",
        "Bot invests in your success!",
        "Who grew here?",
        "Growth is visible!"
    ],
    "same": [
        "All stable like morning coffee!",
        "Fissure is thinking about the meaning of life...",
        "At least it didn't decrease!",
        "Rest is also work!"
    ],
    "down": [
        "Shrunk... quietly but proudly!",
        "A bit shrank from modesty!",
        "Minus is not a verdict!",
        "Happens... (sighs)"
    ],
    "fatal": [
        "FISSURE IN SHOCK!",
        "CRITICAL DAMAGE!",
        "EVERYTHING IS BURNING!",
        "STRIKE OF FATE!"
    ],
    "bonus_help": [
        "SYSTEM TOOK YOU UNDER ITS WING!",
        "BOT DECIDED TO HELP A NEWBIE!",
        "MAGIC OF ALGORITHMS IN ACTION!",
        "GIFT FROM THE DEVELOPER!"
    ]
}

# =====================
# WELCOME PHRASES FOR NEW MEMBERS
# =====================

WELCOME_PHRASES = [
    "Hi, {name}! Glad to see you!",
    "{name}, welcome to the chat!",
    "{name} has joined us!",
    "Oh, newcomer! {name}, welcome!",
    "Finally! {name}, we've been waiting for you!",
    "{name}, welcome to our ranks!",
    "{name}, hello! Play Fissure!",
    "{name}, welcome, warrior!",
    "{name}, glad to have a new player!",
    "{name}, welcome! Press INCREASE!"
]

# =====================
# AUTO-DELETE MESSAGES STORAGE
# =====================

bot_messages = {}
AUTO_DELETE_TIME = 30  # Delete messages older than 30 seconds

def add_bot_message(chat_id: int, message_id: int):
    """Adds bot message to storage for auto-cleanup"""
    if chat_id not in bot_messages:
        bot_messages[chat_id] = {}
    bot_messages[chat_id][message_id] = time.time()
    logger.debug(f"Added message {message_id} for chat {chat_id}")

async def cleanup_old_messages(bot):
    """Deletes bot messages older than 30 seconds"""
    now = time.time()
    for chat_id in list(bot_messages.keys()):
        messages_to_delete = []
        for msg_id, timestamp in bot_messages[chat_id].items():
            if now - timestamp > AUTO_DELETE_TIME:
                messages_to_delete.append(msg_id)
        
        for msg_id in messages_to_delete:
            try:
                await bot.delete_message(chat_id, msg_id)
                del bot_messages[chat_id][msg_id]
                logger.debug(f"Auto-deleted message {msg_id} from chat {chat_id}")
            except Exception as e:
                logger.debug(f"Could not delete message {msg_id}: {e}")
                if msg_id in bot_messages[chat_id]:
                    del bot_messages[chat_id]
        
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
        [KeyboardButton("INCREASE")],
        [KeyboardButton("MY LENGTH"), KeyboardButton("TOP")],
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
        await context.bot.delete_message(update.message.chat_id, update.message.message_id)
        logger.info(f"User message deleted: {update.message.message_id}")
    except Exception as e:
        logger.error(f"Could not delete user message: {e}")

async def auto_delete_message(context: ContextTypes.DEFAULT_TYPE):
    """Auto-delete message after 30 seconds"""
    try:
        chat_id = context.job.data['chat_id']
        message_id = context.job.data['message_id']
        await context.bot.delete_message(chat_id, message_id)
        logger.debug(f"Auto-deleted message: {message_id}")
    except Exception as e:
        logger.debug(f"Could not auto-delete message: {e}")

def schedule_auto_delete(update: Update, context: ContextTypes.DEFAULT_TYPE, delay: int = 30):
    """Schedules auto-delete for user message"""
    context.job_queue.run_once(
        auto_delete_message,
        delay,
        data={
            'chat_id': update.message.chat_id,
            'message_id': update.message.message_id
        },
        name=f"auto_delete_{update.message.chat_id}_{update.message.message_id}"
    )

async def send_or_update_message(bot, chat_id, text, reply_markup=None, last_message_id=0):
    """Sends new message or updates existing one"""
    try:
        logger.info(f"send_or_update_message: chat_id={chat_id}, last_message_id={last_message_id}")
        msg = await bot.send_message(chat_id, text, reply_markup=reply_markup)
        logger.info(f"Sent message: {msg.message_id}")
        
        await delete_previous_message(bot, chat_id, last_message_id)
        
        return msg.message_id
    except Exception as e:
        logger.error(f"Send error: {e}")
        return 0

async def fissure(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for /fissure command"""
    logger.info(f"User {update.effective_user.id} called fissure")
    
    # Clean up old bot messages
    await cleanup_old_messages(context.bot)
    
    uid = update.effective_user.id
    user_obj = update.effective_user
    username = user_obj.username or user_obj.first_name
    now = time.time()
    
    try:
        user = get_user(uid, username)
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
            update_last_message_id(uid, message_id)
            return

        roll, special_message, is_fatal, got_help = calculate_fissure_roll(user["fissure"])
        roll, protection_msg = apply_fissure_protection(user["fissure"], roll, is_fatal)
        new_fissure = calculate_new_fissure(user["fissure"], roll)
        update_fissure(uid, new_fissure, now)
        
        logger.info(f"User {uid} used fissure. New cooldown: {now}")

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
            logger.info(f"Result sent to user {uid}")
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
            update_last_message_id(uid, message_id)
            
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
        uid = update.effective_user.id
        user_obj = update.effective_user
        username = user_obj.username or user_obj.first_name
        user = get_user(uid, username)
        logger.info(f"stats user data: {user}")
        
        text = f"Current fissure length: {user['fissure']:.1f} cm"
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
        logger.error(f"Error in stats: {e}")
        text = "Error getting stats"
        message_id = await send_or_update_message(
            context.bot,
            update.message.chat_id,
            text,
            main_menu(),
            user.get("last_message_id", 0) if 'user' in locals() else 0
        )
        if 'user' in locals():
            update_last_message_id(uid, message_id)

async def top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show top"""
    logger.info(f"User {update.effective_user.id} called top")
    
    # Clean up old bot messages
    await cleanup_old_messages(context.bot)
    
    try:
        uid = update.effective_user.id
        user_obj = update.effective_user
        username = user_obj.username or user_obj.first_name
        user = get_user(uid, username)
        logger.info(f"top user data: {user}")
        
        top_users = get_fissure_top()
        logger.info(f"Got {len(top_users)} users for top")
        
        if not top_users:
            text = "Top Fissures:\n\nNo data yet"
            message_id = await send_or_update_message(
                context.bot,
                update.message.chat_id,
                text,
                main_menu(),
                user.get("last_message_id", 0)
            )
            update_last_message_id(uid, message_id)
            return
            
        text = "Top Fissures:\n\n"
        for i, u in enumerate(top_users, 1):
            username = u['username'] or f"User {u['telegram_id']}"
            text += f"{i}. {username} - {u['fissure']:.1f} cm\n"
        
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
        logger.error(f"Error in top: {e}")
        text = "Error getting top"
        message_id = await send_or_update_message(
            context.bot,
            update.message.chat_id,
            text,
            main_menu(),
            user.get("last_message_id", 0) if 'user' in locals() else 0
        )
        if 'user' in locals():
            update_last_message_id(uid, message_id)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for /start command"""
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
    
    menu_buttons = ["INCREASE", "MY LENGTH", "TOP"]
    
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

        if text == "INCREASE":
            await fissure(update, context)
        elif text == "MY LENGTH":
            await stats(update, context)
        elif text == "TOP":
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
        app.add_handler(MessageHandler(filters.Regex(r'^(📈 Увеличить фиссуру|📏 Моя длина|🏆 Топ)
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
        app.add_handler(MessageHandler(filters.Regex(r'^(INCREASE|MY LENGTH|TOP)$'), menu_handler))
        app.add_handler(ChatMemberHandler(welcome_new_member, ChatMemberHandler.CHAT_MEMBER))

        logger.info("Telegram bot started in polling mode")
        
        await app.run_polling(drop_pending_updates=True)
        
    except Exception as e:
        logger.error(f"Critical error: {e}", exc_info=True)
        raise

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nBot stopped by user")
    except Exception as e:
        print(f"Bot start error: {e}")
        raise
), menu_handler))
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
        app.add_handler(MessageHandler(filters.Regex(r'^(INCREASE|MY LENGTH|TOP)$'), menu_handler))
        app.add_handler(ChatMemberHandler(welcome_new_member, ChatMemberHandler.CHAT_MEMBER))

        logger.info("Telegram bot started in polling mode")
        
        await app.run_polling(drop_pending_updates=True)
        
    except Exception as e:
        logger.error(f"Critical error: {e}", exc_info=True)
        raise

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nBot stopped by user")
    except Exception as e:
        print(f"Bot start error: {e}")
        raise
), menu_handler))
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
        app.add_handler(MessageHandler(filters.Regex(r'^(INCREASE|MY LENGTH|TOP)$'), menu_handler))
        app.add_handler(ChatMemberHandler(welcome_new_member, ChatMemberHandler.CHAT_MEMBER))

        logger.info("Telegram bot started in polling mode")
        
        await app.run_polling(drop_pending_updates=True)
        
    except Exception as e:
        logger.error(f"Critical error: {e}", exc_info=True)
        raise

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nBot stopped by user")
    except Exception as e:
        print(f"Bot start error: {e}")
        raise
), menu_handler))
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
        app.add_handler(MessageHandler(filters.Regex(r'^(INCREASE|MY LENGTH|TOP)$'), menu_handler))
        app.add_handler(ChatMemberHandler(welcome_new_member, ChatMemberHandler.CHAT_MEMBER))

        logger.info("Telegram bot started in polling mode")
        
        await app.run_polling(drop_pending_updates=True)
        
    except Exception as e:
        logger.error(f"Critical error: {e}", exc_info=True)
        raise

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nBot stopped by user")
    except Exception as e:
        print(f"Bot start error: {e}")
        raise
), menu_handler))
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
        app.add_handler(MessageHandler(filters.Regex(r'^(INCREASE|MY LENGTH|TOP)$'), menu_handler))
        app.add_handler(ChatMemberHandler(welcome_new_member, ChatMemberHandler.CHAT_MEMBER))

        logger.info("Telegram bot started in polling mode")
        
        await app.run_polling(drop_pending_updates=True)
        
    except Exception as e:
        logger.error(f"Critical error: {e}", exc_info=True)
        raise

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nBot stopped by user")
    except Exception as e:
        print(f"Bot start error: {e}")
        raise
), menu_handler))
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
        app.add_handler(MessageHandler(filters.Regex(r'^(INCREASE|MY LENGTH|TOP)$'), menu_handler))
        app.add_handler(ChatMemberHandler(welcome_new_member, ChatMemberHandler.CHAT_MEMBER))

        logger.info("Telegram bot started in polling mode")
        
        await app.run_polling(drop_pending_updates=True)
        
    except Exception as e:
        logger.error(f"Critical error: {e}", exc_info=True)
        raise

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nBot stopped by user")
    except Exception as e:
        print(f"Bot start error: {e}")
        raise
), menu_handler))
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
        app.add_handler(MessageHandler(filters.Regex(r'^(INCREASE|MY LENGTH|TOP)$'), menu_handler))
        app.add_handler(ChatMemberHandler(welcome_new_member, ChatMemberHandler.CHAT_MEMBER))

        logger.info("Telegram bot started in polling mode")
        
        await app.run_polling(drop_pending_updates=True)
        
    except Exception as e:
        logger.error(f"Critical error: {e}", exc_info=True)
        raise

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nBot stopped by user")
    except Exception as e:
        print(f"Bot start error: {e}")
        raise
), menu_handler))
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
        app.add_handler(MessageHandler(filters.Regex(r'^(INCREASE|MY LENGTH|TOP)$'), menu_handler))
        app.add_handler(ChatMemberHandler(welcome_new_member, ChatMemberHandler.CHAT_MEMBER))

        logger.info("Telegram bot started in polling mode")
        
        await app.run_polling(drop_pending_updates=True)
        
    except Exception as e:
        logger.error(f"Critical error: {e}", exc_info=True)
        raise

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nBot stopped by user")
    except Exception as e:
        print(f"Bot start error: {e}")
        raise
