"""Функции регистрации для всех систем"""

from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters

def register_combat_handlers(app: Application):
    """Регистрация обработчиков боевой системы"""
    from handlers.combat_system import handle_attack_boss
    
    # Регистрируем команду атаки на босса
    app.add_handler(CommandHandler("attack_boss", handle_attack_boss))

def register_pvp_handlers(app: Application):
    """Регистрация обработчиков PvP системы"""
    from handlers.pvp import pvp, fight, handle_pvp_fight_callback, handle_pvp_refresh
    
    # Основные команды PvP
    app.add_handler(CommandHandler("pvp", pvp))
    app.add_handler(CommandHandler("fight", fight))
    
    # Callback-обработчики для PvP
    app.add_handler(CallbackQueryHandler(handle_pvp_fight_callback, pattern=r"^pvp_fight_\d+$"))
    app.add_handler(CallbackQueryHandler(handle_pvp_refresh, pattern=r"^pvp_refresh$"))

def register_quest_handlers(app: Application):
    """Регистрация обработчиков системы квестов"""
    from handlers.quest_system import quests, daily_rewards, daily_calendar, daily_bonuses, daily_timer
    from handlers.quest_system import handle_quests_active, handle_quests_completed, handle_quests_daily
    from handlers.quest_system import handle_quests_weekly, handle_quests_rewards, handle_quests_progress
    
    # Основные команды квестов
    app.add_handler(CommandHandler("quests", quests))
    app.add_handler(CommandHandler("daily_rewards", daily_rewards))
    app.add_handler(CommandHandler("daily_calendar", daily_calendar))
    app.add_handler(CommandHandler("daily_bonuses", daily_bonuses))
    app.add_handler(CommandHandler("daily_timer", daily_timer))
    
    # Callback-обработчики для квестов
    app.add_handler(CallbackQueryHandler(handle_quests_active, pattern=r"^quests_active$"))
    app.add_handler(CallbackQueryHandler(handle_quests_completed, pattern=r"^quests_completed$"))
    app.add_handler(CallbackQueryHandler(handle_quests_daily, pattern=r"^quests_daily$"))
    app.add_handler(CallbackQueryHandler(handle_quests_weekly, pattern=r"^quests_weekly$"))
    app.add_handler(CallbackQueryHandler(handle_quests_rewards, pattern=r"^quests_rewards$"))
    app.add_handler(CallbackQueryHandler(handle_quests_progress, pattern=r"^quests_progress$"))

def register_inventory_handlers(app: Application):
    """Регистрация обработчиков системы инвентаря"""
    from handlers.inventory_system import inventory, equip_item, unequip_item, use_item
    
    # Основные команды инвентаря
    app.add_handler(CommandHandler("inventory", inventory))
    app.add_handler(CommandHandler("equip", equip_item))
    app.add_handler(CommandHandler("unequip", unequip_item))
    app.add_handler(CommandHandler("use", use_item))

def register_talent_handlers(app: Application):
    """Регистрация обработчиков системы талантов"""
    from handlers.talent_system import talents, learn_talent, level_up, stats_distribute
    from handlers.talent_system import add_str, add_agi, add_int, handle_talents_category
    from handlers.talent_system import handle_talents_stats, handle_talents_main, handle_learn_talent_callback
    
    # Основные команды талантов
    app.add_handler(CommandHandler("talents", talents))
    app.add_handler(CommandHandler("learn_talent", learn_talent))
    app.add_handler(CommandHandler("level_up", level_up))
    app.add_handler(CommandHandler("stats_distribute", stats_distribute))
    app.add_handler(CommandHandler("add_str", add_str))
    app.add_handler(CommandHandler("add_agi", add_agi))
    app.add_handler(CommandHandler("add_int", add_int))
    
    # Callback-обработчики для талантов
    app.add_handler(CallbackQueryHandler(handle_talents_category, pattern=r"^talents_category_"))
    app.add_handler(CallbackQueryHandler(handle_talents_stats, pattern=r"^talents_stats$"))
    app.add_handler(CallbackQueryHandler(handle_talents_main, pattern=r"^talents_main$"))
    app.add_handler(CallbackQueryHandler(handle_learn_talent_callback, pattern=r"^learn_talent_"))

def register_fissure_handlers(app: Application):
    """Регистрация обработчиков системы Fissure"""
    from handlers.fissure_system import fissure, fissure_top, stats as fissure_stats
    from handlers.fissure_system import handle_fissure_growth, handle_fissure_finish
    
    # Основные команды Fissure
    app.add_handler(CommandHandler("fissure", fissure))
    app.add_handler(CommandHandler("fissure_top", fissure_top))
    app.add_handler(CommandHandler("fissure_stats", fissure_stats))
    
    # Callback-обработчики для Fissure
    app.add_handler(CallbackQueryHandler(handle_fissure_growth, pattern=r"^fissure_growth_"))
    app.add_handler(CallbackQueryHandler(handle_fissure_finish, pattern=r"^fissure_finish$"))

def register_achievement_handlers(app: Application):
    """Регистрация обработчиков системы достижений"""
    from handlers.achievement_system import achievements, achievement_progress, achievement_rewards
    from handlers.achievement_system import handle_achievement_claim, handle_achievement_info
    
    # Основные команды достижений
    app.add_handler(CommandHandler("achievements", achievements))
    app.add_handler(CommandHandler("achievement_progress", achievement_progress))
    app.add_handler(CommandHandler("achievement_rewards", achievement_rewards))
    
    # Callback-обработчики для достижений
    app.add_handler(CallbackQueryHandler(handle_achievement_claim, pattern=r"^achievement_claim_"))
    app.add_handler(CallbackQueryHandler(handle_achievement_info, pattern=r"^achievement_info_"))

__all__ = [
    'register_combat_handlers',
    'register_pvp_handlers',
    'register_quest_handlers',
    'register_inventory_handlers',
    'register_talent_handlers',
    'register_fissure_handlers',
    'register_achievement_handlers'
]
