"""Модуль для создания интерактивного меню с кнопками"""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram import Update

def get_main_menu_keyboard():
    """Получение клавиатуры основного меню"""
    keyboard = [
        [
            InlineKeyboardButton("👤 Профиль", callback_data="profile"),
            InlineKeyboardButton("📊 Статистика", callback_data="stats")
        ],
        [
            InlineKeyboardButton("👹 Боссы", callback_data="boss_menu"),
            InlineKeyboardButton("⚔️ PvP", callback_data="pvp_menu")
        ],
        [
            InlineKeyboardButton("🛒 Магазин", callback_data="shop_menu"),
            InlineKeyboardButton("🌟 Таланты", callback_data="talents_menu")
        ],
        [
            InlineKeyboardButton("🏆 Рейтинги", callback_data="top_menu"),
            InlineKeyboardButton("💥 Фиссура", callback_data="fissure")
        ],
        [
            InlineKeyboardButton("❓ Помощь", callback_data="help")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_boss_menu_keyboard():
    """Получение клавиатуры меню боссов"""
    keyboard = [
        [
            InlineKeyboardButton("👁️ Информация о боссе", callback_data="boss"),
            InlineKeyboardButton("⚔️ Атаковать босса", callback_data="attack")
        ],
        [
            InlineKeyboardButton("⬅️ Назад", callback_data="main_menu")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_pvp_menu_keyboard():
    """Получение клавиатуры меню PvP"""
    keyboard = [
        [
            InlineKeyboardButton("👥 Список противников", callback_data="pvp"),
            InlineKeyboardButton("🔥 Вызов на дуэль", callback_data="fight")
        ],
        [
            InlineKeyboardButton("⬅️ Назад", callback_data="main_menu")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_shop_menu_keyboard():
    """Получение клавиатуры меню магазина"""
    keyboard = [
        [
            InlineKeyboardButton("👟 Сапоги", callback_data="shop_category_boots"),
            InlineKeyboardButton("🛡️ Броня", callback_data="shop_category_armor")
        ],
        [
            InlineKeyboardButton("🗡️ Оружие", callback_data="shop_category_weapons"),
            InlineKeyboardButton("🔮 Поддержка", callback_data="shop_category_support")
        ],
        [
            InlineKeyboardButton("🧪 Зелья", callback_data="shop_category_potions"),
            InlineKeyboardButton("🛒 Купить", callback_data="buy")
        ],
        [
            InlineKeyboardButton("💚 Зелье", callback_data="potion"),
            InlineKeyboardButton("🏥 Лечение", callback_data="heal")
        ],
        [
            InlineKeyboardButton("⬅️ Назад", callback_data="main_menu")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_talents_menu_keyboard():
    """Получение клавиатуры меню талантов"""
    keyboard = [
        [
            InlineKeyboardButton("🌳 Дерево талантов", callback_data="talents"),
            InlineKeyboardButton("⬆️ Повысить уровень", callback_data="level_up")
        ],
        [
            InlineKeyboardButton("🎓 Изучить талант", callback_data="learn"),
            InlineKeyboardButton("📊 Распределить очки", callback_data="stats_distribute")
        ],
        [
            InlineKeyboardButton("⬅️ Назад", callback_data="main_menu")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_top_menu_keyboard():
    """Получение клавиатуры меню рейтингов"""
    keyboard = [
        [
            InlineKeyboardButton("👑 По уровню", callback_data="top_level"),
            InlineKeyboardButton("⚔️ По MMR", callback_data="top_mmr")
        ],
        [
            InlineKeyboardButton("💎 По опыту", callback_data="top_exp"),
            InlineKeyboardButton("💰 По золоту", callback_data="top_gold")
        ],
        [
            InlineKeyboardButton("🗡️ По урону", callback_data="top_damage"),
            InlineKeyboardButton("📏 По фиссуре", callback_data="fissure_top")
        ],
        [
            InlineKeyboardButton("🏆 Достижения", callback_data="achievements")
        ],
        [
            InlineKeyboardButton("⬅️ Назад", callback_data="main_menu")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_help_keyboard():
    """Получение клавиатуры помощи"""
    keyboard = [
        [
            InlineKeyboardButton("📖 Команды", callback_data="help_commands"),
            InlineKeyboardButton("🎮 Игровой процесс", callback_data="help_gameplay")
        ],
        [
            InlineKeyboardButton("❓ FAQ", callback_data="help_faq"),
            InlineKeyboardButton("💡 Советы", callback_data="help_tips")
        ],
        [
            InlineKeyboardButton("⬅️ Назад", callback_data="main_menu")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

async def handle_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка callback-запросов меню"""
    query = update.callback_query
    await query.answer()
    
    callback_data = query.data
    
    if callback_data == "main_menu":
        await query.edit_message_text(
            text="Выберите действие:",
            reply_markup=get_main_menu_keyboard()
        )
    
    elif callback_data == "profile":
        # Импортируем здесь, чтобы избежать circular imports
        from handlers.main import profile
        await profile(update, context)
    
    elif callback_data == "stats":
        from handlers.main import stats
        await stats(update, context)
    
    elif callback_data == "boss_menu":
        await query.edit_message_text(
            text="Меню боссов:",
            reply_markup=get_boss_menu_keyboard()
        )
    
    elif callback_data == "pvp_menu":
        await query.edit_message_text(
            text="Меню PvP:",
            reply_markup=get_pvp_menu_keyboard()
        )
    
    elif callback_data == "shop_menu":
        await query.edit_message_text(
            text="Меню магазина:",
            reply_markup=get_shop_menu_keyboard()
        )
    
    elif callback_data == "talents_menu":
        await query.edit_message_text(
            text="Меню талантов:",
            reply_markup=get_talents_menu_keyboard()
        )
    
    elif callback_data == "top_menu":
        await query.edit_message_text(
            text="Меню рейтингов:",
            reply_markup=get_top_menu_keyboard()
        )
    
    elif callback_data == "help":
        await query.edit_message_text(
            text="Меню помощи:",
            reply_markup=get_help_keyboard()
        )
    
    elif callback_data in ["boss", "attack", "pvp", "fight", "buy", "potion", "heal", 
                          "talents", "level_up", "learn", "fissure", "fissure_top", 
                          "achievements"]:
        # Перенаправляем на соответствующие обработчики
        command_handlers = {
            "boss": "handlers.boss.boss",
            "attack": "handlers.boss.attack", 
            "pvp": "handlers.pvp.pvp",
            "fight": "handlers.pvp.fight",
            "buy": "handlers.shop.buy",
            "potion": "handlers.heal.potion",
            "heal": "handlers.heal.heal",
            "talents": "handlers.talents.talents",
            "level_up": "handlers.talents.level_up",
            "learn": "handlers.talents.learn",
            "fissure": "handlers.fissure.fissure",
            "fissure_top": "handlers.top.fissure_top",
            "achievements": "handlers.top.achievements"
        }
        
        if callback_data in command_handlers:
            module_path = command_handlers[callback_data]
            module_name, func_name = module_path.rsplit(".", 1)
            module = __import__(module_name, fromlist=[func_name])
            handler_func = getattr(module, func_name)
            await handler_func(update, context)

__all__ = [
    'get_main_menu_keyboard',
    'get_boss_menu_keyboard', 
    'get_pvp_menu_keyboard',
    'get_shop_menu_keyboard',
    'get_talents_menu_keyboard',
    'get_top_menu_keyboard',
    'get_help_keyboard',
    'handle_menu_callback'
]