import os
import asyncio
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    MessageHandler,
    filters,
)

from config import BOT_TOKEN, RENDER_URL, PORT
from database import init_db
from handlers import (
    start, fissure, fissure_top, stats, boss, attack, shop, show_category_items,
    buy, potion, heal, pvp, handle_pvp_fight, fight, top, profile,
    handle_message, handle_pvp_buttons,
    talents, learn_talent, stats_distribute, add_stat, level_up_handler, achievements,
    add_str, add_agi, add_int, learn, level_up
)

# ================= ENTRY POINT =================

if __name__ == "__main__":
    WEBHOOK_PATH = f"webhook/{BOT_TOKEN}"
    app = ApplicationBuilder().token(BOT_TOKEN).post_init(init_db).build()

    # Сначала добавляем обработчики команд
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("boss", boss))
    app.add_handler(CommandHandler("attack", attack))
    app.add_handler(CommandHandler("shop", shop))
    app.add_handler(CommandHandler("buy", buy))
    app.add_handler(CommandHandler("potion", potion))
    app.add_handler(CommandHandler("heal", heal))
    app.add_handler(CommandHandler("pvp", pvp))
    app.add_handler(CommandHandler("fight", fight))
    app.add_handler(CommandHandler("top", top))
    app.add_handler(CommandHandler("fissure", fissure))
    app.add_handler(CommandHandler("fissure_top", fissure_top))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("profile", profile))
    app.add_handler(CommandHandler("talents", talents))
    app.add_handler(CommandHandler("level", level_up_handler))
    app.add_handler(CommandHandler("achievements", achievements))
    app.add_handler(CommandHandler("add_str", add_str))
    app.add_handler(CommandHandler("add_agi", add_agi))
    app.add_handler(CommandHandler("add_int", add_int))
    app.add_handler(CommandHandler("stats_distribute", stats_distribute))
    app.add_handler(CommandHandler("learn", learn))
    app.add_handler(CommandHandler("level_up", level_up))

    # Обработчик изучения талантов по кнопкам
    async def handle_talent_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
        text = update.message.text
        if text.startswith("/learn_"):
            talent_id = text.replace("/learn_", "")
            await learn_talent(update, context, talent_id)

    app.add_handler(MessageHandler(filters.TEXT & filters.Regex(r'^/learn_[a-z0-9]+$'), handle_talent_buttons))
    
    # Обработчики категорий магазина
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex(r'^(👟 Сапоги|🛡️ Броня|🗡️ Оружие|🛡️ Защита|🔮 Поддержка|🧪 Зелья)$'), 
                                   lambda update, context: show_category_items(update, context, update.message.text)))
    
    # Затем обработчик для PvP кнопок (специфичный)
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex(r'^/fight_\d+$'), handle_pvp_buttons))
    
    # И только потом общий обработчик текстовых сообщений
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Запускаем бота в режиме webhook для Render
    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=WEBHOOK_PATH,
        webhook_url=f"{RENDER_URL.rstrip('/')}/{WEBHOOK_PATH}",
        drop_pending_updates=True,
    )

</final_file_content>

IMPORTANT: For any future changes to this file, use the final_file_content shown above as your reference. This content reflects the current state of the file, including any auto-formatting (e.g., if you used single quotes but the formatter converted them to double quotes). Always base your SEARCH/REPLACE operations on this final version to ensure accuracy.

 <environment_details>
# Cursor Visible Files
bot.py

# Cursor Open Tabs
config.py
database.py
game_logic.py
handlers.py
bot.py

# Current Time
1/26/2026, 6:41:40 AM (Europe/Minsk, UTC+3:00)

# Context Window Usage
123,558 / 256K tokens used (48%)

# Current Mode
ACT MODE
