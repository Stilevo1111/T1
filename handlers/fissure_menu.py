"""Меню для системы Fissure"""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CallbackQueryHandler
from telegram import Update

def get_fissure_menu_keyboard():
    """Получение клавиатуры меню Fissure"""
    keyboard = [
        [
            InlineKeyboardButton("🎲 РОЛЛ", callback_data="fissure_roll"),
            InlineKeyboardButton("🏆 ТОП", callback_data="fissure_top_menu")
        ],
        [
            InlineKeyboardButton("📊 СТАТИСТИКА", callback_data="fissure_stats_menu"),
            InlineKeyboardButton("⬅️ Назад", callback_data="main_menu")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

async def handle_fissure_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик меню Fissure"""
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        text="💥 *Меню Fissure:*\n\nВыберите действие:",
        reply_markup=get_fissure_menu_keyboard(),
        parse_mode='Markdown'
    )

async def handle_fissure_roll(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик кнопки РОЛЛ"""
    query = update.callback_query
    await query.answer()
    
    # Импортируем функцию fissure из handlers/fissure.py
    from handlers.fissure import fissure
    
    # Создаем фейковое сообщение для вызова функции fissure
    class FakeMessage:
        def __init__(self, chat_id, message_id):
            self.chat_id = chat_id
            self.message_id = message_id
            
        async def reply_text(self, text, **kwargs):
            # Отправляем сообщение в чат
            await context.bot.send_message(
                chat_id=self.chat_id,
                text=text,
                **kwargs
            )
            return self
    
    # Создаем фейковое сообщение
    fake_message = FakeMessage(query.message.chat_id, query.message.message_id)
    query.message.reply_text = fake_message.reply_text
    
    # Вызываем функцию fissure
    await fissure(update, context)

async def handle_fissure_top_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик кнопки ТОП"""
    query = update.callback_query
    await query.answer()
    
    # Импортируем функцию fissure_top из handlers/fissure.py
    from handlers.fissure import fissure_top
    
    # Создаем фейковое сообщение для вызова функции fissure_top
    class FakeMessage:
        def __init__(self, chat_id, message_id):
            self.chat_id = chat_id
            self.message_id = message_id
            
        async def reply_text(self, text, **kwargs):
            # Отправляем сообщение в чат
            await context.bot.send_message(
                chat_id=self.chat_id,
                text=text,
                **kwargs
            )
            return self
    
    # Создаем фейковое сообщение
    fake_message = FakeMessage(query.message.chat_id, query.message.message_id)
    query.message.reply_text = fake_message.reply_text
    
    # Вызываем функцию fissure_top
    await fissure_top(update, context)

async def handle_fissure_stats_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик кнопки СТАТИСТИКА"""
    query = update.callback_query
    await query.answer()
    
    # Импортируем функцию stats из handlers/fissure.py
    from handlers.fissure import stats as fissure_stats
    
    # Создаем фейковое сообщение для вызова функции stats
    class FakeMessage:
        def __init__(self, chat_id, message_id):
            self.chat_id = chat_id
            self.message_id = message_id
            
        async def reply_text(self, text, **kwargs):
            # Отправляем сообщение в чат
            await context.bot.send_message(
                chat_id=self.chat_id,
                text=text,
                **kwargs
            )
            return self
    
    # Создаем фейковое сообщение
    fake_message = FakeMessage(query.message.chat_id, query.message.message_id)
    query.message.reply_text = fake_message.reply_text
    
    # Вызываем функцию stats
    await fissure_stats(update, context)

def register_fissure_menu_handlers(app):
    """Регистрация обработчиков меню Fissure"""
    app.add_handler(CallbackQueryHandler(handle_fissure_menu, pattern='^fissure$'))
    app.add_handler(CallbackQueryHandler(handle_fissure_roll, pattern='^fissure_roll$'))
    app.add_handler(CallbackQueryHandler(handle_fissure_top_menu, pattern='^fissure_top_menu$'))
    app.add_handler(CallbackQueryHandler(handle_fissure_stats_menu, pattern='^fissure_stats_menu$'))

__all__ = [
    'get_fissure_menu_keyboard',
    'handle_fissure_menu',
    'handle_fissure_roll',
    'handle_fissure_top_menu',
    'handle_fissure_stats_menu',
    'register_fissure_menu_handlers'
]