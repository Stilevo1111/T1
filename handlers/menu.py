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
            InlineKeyboardButton("🎁 Ежедневные", callback_data="daily_rewards"),
            InlineKeyboardButton("🎯 Квесты", callback_data="quests")
        ],
        [
            InlineKeyboardButton("❓ Помощь", callback_data="help")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_daily_menu_keyboard():
    """Получение клавиатуры ежедневных наград"""
    keyboard = [
        [
            InlineKeyboardButton("🎁 Получить награду", callback_data="daily_claim"),
            InlineKeyboardButton("📅 Календарь", callback_data="daily_calendar")
        ],
        [
            InlineKeyboardButton("💎 Бонусы", callback_data="daily_bonuses"),
            InlineKeyboardButton("⏰ Таймер", callback_data="daily_timer")
        ],
        [
            InlineKeyboardButton("⬅️ Назад", callback_data="main_menu")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_quests_menu_keyboard():
    """Получение клавиатуры квестов"""
    keyboard = [
        [
            InlineKeyboardButton("📋 Активные", callback_data="quests_active"),
            InlineKeyboardButton("✅ Завершенные", callback_data="quests_completed")
        ],
        [
            InlineKeyboardButton("🎯 Ежедневные", callback_data="quests_daily"),
            InlineKeyboardButton("🏆 Недельные", callback_data="quests_weekly")
        ],
        [
            InlineKeyboardButton("💎 Награды", callback_data="quests_rewards"),
            InlineKeyboardButton("📊 Прогресс", callback_data="quests_progress")
        ],
        [
            InlineKeyboardButton("⬅️ Назад", callback_data="main_menu")
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
            InlineKeyboardButton("💰 Баланс", callback_data="shop_balance"),
            InlineKeyboardButton("🎁 Специальное", callback_data="shop_special")
        ],
        [
            InlineKeyboardButton("⬅️ Назад", callback_data="main_menu")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_shop_category_keyboard(category: str):
    """Получение клавиатуры категорий магазина"""
    if category == "boots":
        keyboard = [
            [
                InlineKeyboardButton("👟 Boots of Speed", callback_data="buy_item_boots_of_speed"),
                InlineKeyboardButton("🥾 Phase Boots", callback_data="buy_item_phase_boots")
            ],
            [
                InlineKeyboardButton("🥿 Power Treads", callback_data="buy_item_power_treads"),
                InlineKeyboardButton("👢 Arcane Boots", callback_data="buy_item_arcane_boots")
            ],
            [
                InlineKeyboardButton("⬅️ Назад", callback_data="shop_menu")
            ]
        ]
    elif category == "armor":
        keyboard = [
            [
                InlineKeyboardButton("🛡️ Ring of Protection", callback_data="buy_item_ring_of_protection"),
                InlineKeyboardButton("🪖 Vanguard", callback_data="buy_item_vanguard")
            ],
            [
                InlineKeyboardButton("🦺 Stout Shield", callback_data="buy_item_stout_shield"),
                InlineKeyboardButton("🪖 Blademail", callback_data="buy_item_blademail")
            ],
            [
                InlineKeyboardButton("⬅️ Назад", callback_data="shop_menu")
            ]
        ]
    elif category == "weapons":
        keyboard = [
            [
                InlineKeyboardButton("🗡️ Quelling Blade", callback_data="buy_item_quelling_blade"),
                InlineKeyboardButton("⚔️ Daedalus", callback_data="buy_item_daedalus")
            ],
            [
                InlineKeyboardButton("🏹 Dagon", callback_data="buy_item_dagon"),
                InlineKeyboardButton("🗡️ Monkey King Bar", callback_data="buy_item_monkey_king_bar")
            ],
            [
                InlineKeyboardButton("⬅️ Назад", callback_data="shop_menu")
            ]
        ]
    elif category == "support":
        keyboard = [
            [
                InlineKeyboardButton("🔮 Ring of Basilius", callback_data="buy_item_ring_of_basilius"),
                InlineKeyboardButton("⚡ Aghanim's Scepter", callback_data="buy_item_aghanims_scepter")
            ],
            [
                InlineKeyboardButton("🛡️ Force Staff", callback_data="buy_item_force_staff"),
                InlineKeyboardButton("🔮 Glimmer Cape", callback_data="buy_item_glimmer_cape")
            ],
            [
                InlineKeyboardButton("⬅️ Назад", callback_data="shop_menu")
            ]
        ]
    elif category == "potions":
        keyboard = [
            [
                InlineKeyboardButton("💚 Healing Salve", callback_data="buy_item_healing_salve"),
                InlineKeyboardButton("🧪 Clarity Potion", callback_data="buy_item_clarity_potion")
            ],
            [
                InlineKeyboardButton("🛡️ Invisibility Potion", callback_data="buy_item_invisibility_potion"),
                InlineKeyboardButton("⚡ Speed Potion", callback_data="buy_item_speed_potion")
            ],
            [
                InlineKeyboardButton("⬅️ Назад", callback_data="shop_menu")
            ]
        ]
    else:
        keyboard = [
            [
                InlineKeyboardButton("⬅️ Назад", callback_data="shop_menu")
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
            InlineKeyboardButton("💪 Сила", callback_data="talents_str"),
            InlineKeyboardButton("🏃 Ловкость", callback_data="talents_agi")
        ],
        [
            InlineKeyboardButton("🧠 Интеллект", callback_data="talents_int"),
            InlineKeyboardButton("🔀 Гибрид", callback_data="talents_hybrid")
        ],
        [
            InlineKeyboardButton("⬅️ Назад", callback_data="main_menu")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_talents_category_keyboard(category: str):
    """Получение клавиатуры категорий талантов"""
    if category == "talents_str":
        keyboard = [
            [
                InlineKeyboardButton("💪 +10 к силе", callback_data="learn_talent_str_1"),
                InlineKeyboardButton("🔥 +15% урона", callback_data="learn_talent_str_2")
            ],
            [
                InlineKeyboardButton("🛡️ +10% брони", callback_data="learn_talent_str_3"),
                InlineKeyboardButton("❤️ +15% HP", callback_data="learn_talent_str_4")
            ],
            [
                InlineKeyboardButton("⬅️ Назад", callback_data="talents_menu")
            ]
        ]
    elif category == "talents_agi":
        keyboard = [
            [
                InlineKeyboardButton("🏃 +10 к ловкости", callback_data="learn_talent_agi_1"),
                InlineKeyboardButton("🎯 +15% крита", callback_data="learn_talent_agi_2")
            ],
            [
                InlineKeyboardButton("💨 +10% уклонения", callback_data="learn_talent_agi_3"),
                InlineKeyboardButton("⚡ +15% скорости", callback_data="learn_talent_agi_4")
            ],
            [
                InlineKeyboardButton("⬅️ Назад", callback_data="talents_menu")
            ]
        ]
    elif category == "talents_int":
        keyboard = [
            [
                InlineKeyboardButton("🧠 +10 к интеллекту", callback_data="learn_talent_int_1"),
                InlineKeyboardButton("🔮 +15% маг. урона", callback_data="learn_talent_int_2")
            ],
            [
                InlineKeyboardButton("⚡ +10% маны", callback_data="learn_talent_int_3"),
                InlineKeyboardButton("🛡️ +15% маг. защиты", callback_data="learn_talent_int_4")
            ],
            [
                InlineKeyboardButton("⬅️ Назад", callback_data="talents_menu")
            ]
        ]
    elif category == "talents_hybrid":
        keyboard = [
            [
                InlineKeyboardButton("🌟 Универсальный +5 ко всем", callback_data="learn_talent_hybrid_1"),
                InlineKeyboardButton("⚡ +10% ко всем характеристикам", callback_data="learn_talent_hybrid_2")
            ],
            [
                InlineKeyboardButton("🎯 +5% ко всем типам урона", callback_data="learn_talent_hybrid_3"),
                InlineKeyboardButton("🛡️ +5% ко всем типам защиты", callback_data="learn_talent_hybrid_4")
            ],
            [
                InlineKeyboardButton("⬅️ Назад", callback_data="talents_menu")
            ]
        ]
    else:
        keyboard = [
            [
                InlineKeyboardButton("⬅️ Назад", callback_data="talents_menu")
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
            InlineKeyboardButton("🏆 Достижения", callback_data="achievements"),
            InlineKeyboardButton("🔥 По победам", callback_data="top_wins")
        ],
        [
            InlineKeyboardButton("💀 По поражениям", callback_data="top_losses"),
            InlineKeyboardButton("📊 По соотношению", callback_data="top_ratio")
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
            InlineKeyboardButton("🏆 Мои победы", callback_data="pvp_wins"),
            InlineKeyboardButton("💀 Мои поражения", callback_data="pvp_losses")
        ],
        [
            InlineKeyboardButton("📊 Статистика", callback_data="pvp_stats"),
            InlineKeyboardButton("🎯 Лучшие MMR", callback_data="pvp_top_mmr")
        ],
        [
            InlineKeyboardButton("⬅️ Назад", callback_data="main_menu")
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
            InlineKeyboardButton("🏆 Самые сильные", callback_data="boss_strongest"),
            InlineKeyboardButton("💀 Самые слабые", callback_data="boss_weakest")
        ],
        [
            InlineKeyboardButton("🗡️ По урону", callback_data="boss_damage"),
            InlineKeyboardButton("🛡️ По живучести", callback_data="boss_tank")
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
    
    elif callback_data == "daily_rewards":
        await query.edit_message_text(
            text="Меню ежедневных наград:",
            reply_markup=get_daily_menu_keyboard()
        )
    
    elif callback_data == "quests":
        await query.edit_message_text(
            text="Меню квестов:",
            reply_markup=get_quests_menu_keyboard()
        )
    
    elif callback_data.startswith("shop_category_"):
        category = callback_data.replace("shop_category_", "")
        await query.edit_message_text(
            text=f"Категория: {category.upper()}",
            reply_markup=get_shop_category_keyboard(category)
        )
    
    elif callback_data.startswith("talents_"):
        category = callback_data
        await query.edit_message_text(
            text=f"Таланты: {category.replace('talents_', '').upper()}",
            reply_markup=get_talents_category_keyboard(category)
        )
    
    # Импортируем боевую систему
    from handlers.combat_system import (
        handle_attack_boss, handle_buy_item_menu, handle_learn_talent_menu, handle_daily_reward
    )
    
    # Словарь обработчиков для боевой системы
    combat_handlers = {
        "attack": handle_attack_boss,
        "buy_item_boots_of_speed": handle_buy_item_menu,
        "buy_item_phase_boots": handle_buy_item_menu,
        "buy_item_power_treads": handle_buy_item_menu,
        "buy_item_arcane_boots": handle_buy_item_menu,
        "buy_item_ring_of_protection": handle_buy_item_menu,
        "buy_item_vanguard": handle_buy_item_menu,
        "buy_item_stout_shield": handle_buy_item_menu,
        "buy_item_blademail": handle_buy_item_menu,
        "buy_item_quelling_blade": handle_buy_item_menu,
        "buy_item_daedalus": handle_buy_item_menu,
        "buy_item_dagon": handle_buy_item_menu,
        "buy_item_monkey_king_bar": handle_buy_item_menu,
        "buy_item_ring_of_basilius": handle_buy_item_menu,
        "buy_item_aghanims_scepter": handle_buy_item_menu,
        "buy_item_force_staff": handle_buy_item_menu,
        "buy_item_glimmer_cape": handle_buy_item_menu,
        "buy_item_healing_salve": handle_buy_item_menu,
        "buy_item_clarity_potion": handle_buy_item_menu,
        "buy_item_invisibility_potion": handle_buy_item_menu,
        "buy_item_speed_potion": handle_buy_item_menu,
        "learn_talent_str_1": handle_learn_talent_menu,
        "learn_talent_str_2": handle_learn_talent_menu,
        "learn_talent_str_3": handle_learn_talent_menu,
        "learn_talent_str_4": handle_learn_talent_menu,
        "learn_talent_agi_1": handle_learn_talent_menu,
        "learn_talent_agi_2": handle_learn_talent_menu,
        "learn_talent_agi_3": handle_learn_talent_menu,
        "learn_talent_agi_4": handle_learn_talent_menu,
        "learn_talent_int_1": handle_learn_talent_menu,
        "learn_talent_int_2": handle_learn_talent_menu,
        "learn_talent_int_3": handle_learn_talent_menu,
        "learn_talent_int_4": handle_learn_talent_menu,
        "learn_talent_hybrid_1": handle_learn_talent_menu,
        "learn_talent_hybrid_2": handle_learn_talent_menu,
        "learn_talent_hybrid_3": handle_learn_talent_menu,
        "learn_talent_hybrid_4": handle_learn_talent_menu,
        "daily_claim": handle_daily_reward
    }
    
    # Проверяем и вызываем соответствующий обработчик боевой системы
    if callback_data in combat_handlers:
        handler_func = combat_handlers[callback_data]
        await handler_func(update, context)
    
    # Импортируем обработчики для расширенного меню
    from handlers.menu_handlers import (
        handle_boss_strongest, handle_boss_weakest, handle_boss_damage, handle_boss_tank,
        handle_pvp_stats, handle_pvp_top_mmr, handle_top_level, handle_top_mmr,
        handle_top_exp, handle_top_gold, handle_top_damage, handle_top_wins,
        handle_top_losses, handle_top_ratio, handle_daily_claim, handle_daily_calendar,
        handle_daily_bonuses, handle_daily_timer, handle_quests_active, handle_quests_completed,
        handle_quests_daily, handle_quests_weekly, handle_quests_rewards, handle_quests_progress,
        handle_help_commands, handle_help_gameplay, handle_help_faq, handle_help_tips
    )
    
    # Словарь обработчиков для расширенного меню
    extended_handlers = {
        "boss_strongest": handle_boss_strongest,
        "boss_weakest": handle_boss_weakest,
        "boss_damage": handle_boss_damage,
        "boss_tank": handle_boss_tank,
        "pvp_stats": handle_pvp_stats,
        "pvp_top_mmr": handle_pvp_top_mmr,
        "top_level": handle_top_level,
        "top_mmr": handle_top_mmr,
        "top_exp": handle_top_exp,
        "top_gold": handle_top_gold,
        "top_damage": handle_top_damage,
        "top_wins": handle_top_wins,
        "top_losses": handle_top_losses,
        "top_ratio": handle_top_ratio,
        "daily_claim": handle_daily_claim,
        "daily_calendar": handle_daily_calendar,
        "daily_bonuses": handle_daily_bonuses,
        "daily_timer": handle_daily_timer,
        "quests_active": handle_quests_active,
        "quests_completed": handle_quests_completed,
        "quests_daily": handle_quests_daily,
        "quests_weekly": handle_quests_weekly,
        "quests_rewards": handle_quests_rewards,
        "quests_progress": handle_quests_progress,
        "help_commands": handle_help_commands,
        "help_gameplay": handle_help_gameplay,
        "help_faq": handle_help_faq,
        "help_tips": handle_help_tips
    }
    
    # Проверяем и вызываем соответствующий обработчик
    if callback_data in extended_handlers:
        handler_func = extended_handlers[callback_data]
        await handler_func(update, context)
    
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
            try:
                module_path = command_handlers[callback_data]
                module_name, func_name = module_path.rsplit(".", 1)
                module = __import__(module_name, fromlist=[func_name])
                handler_func = getattr(module, func_name)
                await handler_func(update, context)
            except Exception as e:
                logger.error(f"Ошибка при вызове обработчика {callback_data}: {e}")
                await query.edit_message_text(
                    text=f"❌ Ошибка при выполнении команды {callback_data}",
                    reply_markup=get_main_menu_keyboard()
                )

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