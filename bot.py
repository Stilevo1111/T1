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
    handle_message, handle_pvp_buttons
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