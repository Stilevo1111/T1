# -*- coding: utf-8 -*-
"""Script to add Dota 2 commands to main.py"""

def add_dota_commands():
    with open('main.py', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 1. Add import for dota_mmr
    if 'import dota_mmr' not in content:
        content = content.replace(
            'from database import init_db, get_user, update_fissure, get_fissure_top, update_last_message_id, Database, get_user_rank, decrease_inactive_fissure, get_config, set_config, get_digest_stats, update_player_positions, update_digest_snapshot, get_weekly_digest_stats, update_weekly_digest_snapshot',
            'from database import init_db, get_user, update_fissure, get_fissure_top, update_last_message_id, Database, get_user_rank, decrease_inactive_fissure, get_config, set_config, get_digest_stats, update_player_positions, update_digest_snapshot, get_weekly_digest_stats, update_weekly_digest_snapshot\nimport dota_mmr'
        )
    
    # 2. Add handler functions before menu_handler
    handler_functions = '''

async def link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /link command - link Steam account"""
    try:
        user = update.effective_user
        if not user:
            return
        
        args = context.args
        if not args:
            await update.message.reply_text(
                "📎 <b>Привязка Steam аккаунта</b>\\n\\n"
                "Используйте: /link <SteamID или никнейм>\\n\\n"
                "Пример: /link 123456789\\n"
                "Пример: /link Dendi",
                parse_mode='HTML'
            )
            return
        
        identifier = args[0]
        result = dota_mmr.register_steam(user.id, identifier)
        
        if result.get('success'):
            await update.message.reply_text(
                f"✅ <b>Steam аккаунт привязан!</b>\\n\\n"
                f"🎮 Nickname: {result.get('nickname', 'N/A')}\\n"
                f"📊 MMR: {result.get('mmr', 'N/A')}\\n"
                f"🎮 Игр: {result.get('games', 'N/A')}",
                parse_mode='HTML'
            )
        else:
            await update.message.reply_text(
                f"❌ Ошибка: {result.get('error', 'Неизвестная ошибка')}"
            )
    except Exception as e:
        logger.error(f"Error in link command: {e}")
        await update.message.reply_text("❌ Произошла ошибка при обработке команды")


async def topmmr(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /topmmr command - show top players by MMR"""
    try:
        result = dota_mmr.get_week_top(limit=10)
        
        if not result:
            await update.message.reply_text(
                "🏆 <b>Топ игроков по MMR</b>\\n\\n"
                "Пока нет данных о игроках. "
                "Используйте /link для привязки Steam!",
                parse_mode='HTML'
            )
            return
        
        text = "🏆 <b>Топ игроков по MMR</b>\\n\\n"
        for i, player in enumerate(result, 1):
            text += f"{i}. {player.get('nickname', 'N/A')} - {player.get('mmr', 0)} MMR\\n"
        
        await update.message.reply_text(text, parse_mode='HTML')
    except Exception as e:
        logger.error(f"Error in topmmr command: {e}")
        await update.message.reply_text("❌ Произошла ошибка при обработке команды")


async def ruiner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /Ruiner command - show user's Dota stats"""
    try:
        user = update.effective_user
        if not user:
            return
        
        # Check if Steam is linked
        if not dota_mmr.is_steam_linked(user.id):
            await update.message.reply_text(
                "❌ Steam аккаунт не привязан!\\n"
                "Используйте /link <SteamID или никнейм> для привязки."
            )
            return
        
        result = dota_mmr.get_user_dota_stats(user.id)
        
        if result:
            text = (
                f"🎮 <b>Статистика Dota 2</b>\\n\\n"
                f"Ник: {result.get('nickname', 'N/A')}\\n"
                f"📊 MMR: {result.get('mmr', 'N/A')}\\n"
                f"🎮 Игр: {result.get('games', 0)}\\n"
                f"✅ Побед: {result.get('wins', 0)}\\n"
                f"📈 Винрейт: {result.get('winrate', 0)}%"
            )
            await update.message.reply_text(text, parse_mode='HTML')
        else:
            await update.message.reply_text("❌ Не удалось получить статистику")
    except Exception as e:
        logger.error(f"Error in Ruiner command: {e}")
        await update.message.reply_text("❌ Произошла ошибка при обработке команды")

'''
    
    # Insert handler functions before menu_handler
    content = content.replace(
        'async def menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):',
        handler_functions + 'async def menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):'
    )
    
    # 3. Add command handlers in webhook mode section
    content = content.replace(
        'app.add_handler(CommandHandler("setdigestchat", set_digest_chat))\n        app.add_handler(MessageHandler(filters.Regex(r\'^/start@DotaFull_bot$\'), start))',
        'app.add_handler(CommandHandler("setdigestchat", set_digest_chat))\n        app.add_handler(CommandHandler("link", link))\n        app.add_handler(CommandHandler("topmmr", topmmr))\n        app.add_handler(CommandHandler("Ruiner", ruiner))\n        app.add_handler(MessageHandler(filters.Regex(r\'^/start@DotaFull_bot$\'), start))'
    )
    
    with open('main.py', 'w', encoding='utf-8') as f:
        f.write(content)
    
    print("Successfully added Dota 2 commands to main.py")

if __name__ == '__main__':
    add_dota_commands()
