from telegram.ext import CommandHandler, MessageHandler, filters

def register_handlers(application):
    # Команда /start
    async def start(update, context):
        user = update.effective_user
        from db_postgres import get_user, add_user
        
        # Проверяем есть ли пользователь в базе
        db_user = get_user(user.id)
        if not db_user:
            # Добавляем нового пользователя
            add_user(
                telegram_id=user.id,
                username=user.username,
                first_name=user.first_name,
                last_name=user.last_name
            )
            await update.message.reply_text(f"Привет, {user.first_name}! Вы зарегистрированы.")
        else:
            await update.message.reply_text(f"С возвращением, {user.first_name}!")
    
    application.add_handler(CommandHandler("start", start))