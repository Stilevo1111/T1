"""Обработчики для расширенного меню"""

import logging
from typing import Dict, Any
from telegram import Update, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from database import get_user
from game_logic import calculate_character_stats
from utils.formatters import format_stats_text
from handlers.menu import (
    get_main_menu_keyboard, get_boss_menu_keyboard, get_pvp_menu_keyboard,
    get_shop_menu_keyboard, get_talents_menu_keyboard, get_top_menu_keyboard,
    get_daily_menu_keyboard, get_quests_menu_keyboard, get_help_keyboard,
    get_shop_category_keyboard, get_talents_category_keyboard
)

logger = logging.getLogger(__name__)

async def handle_boss_strongest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик самых сильных боссов"""
    query = update.callback_query
    await query.answer()
    
    user = await get_user(update.effective_user.id, update.effective_user.username)
    
    # Фиктивные данные для примера
    strongest_bosses = [
        "🔥 Infernal Dragon (Level 10)",
        "💀 Death Knight (Level 8)", 
        "⚡ Thunder God (Level 7)",
        "🩸 Blood Demon (Level 6)"
    ]
    
    text = "👹 *Самые сильные боссы:*\n\n" + "\n".join(f"• {boss}" for boss in strongest_bosses)
    text += "\n\n💡 *Совет:* Начните с более слабых боссов и укрепляйте персонажа!"
    
    await query.edit_message_text(
        text=text,
        reply_markup=get_boss_menu_keyboard(),
        parse_mode='Markdown'
    )

async def handle_boss_weakest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик самых слабых боссов"""
    query = update.callback_query
    await query.answer()
    
    user = await get_user(update.effective_user.id, update.effective_user.username)
    
    # Фиктивные данные для примера
    weakest_bosses = [
        "🐀 Rat King (Level 1)",
        "🕷️ Spider Queen (Level 2)", 
        "🧟 Zombie Lord (Level 2)",
        "🦇 Bat Swarm (Level 1)"
    ]
    
    text = "💀 *Самые слабые боссы:*\n\n" + "\n".join(f"• {boss}" for boss in weakest_bosses)
    text += "\n\n💡 *Совет:* Отлично для новичков и тренировки!"
    
    await query.edit_message_text(
        text=text,
        reply_markup=get_boss_menu_keyboard(),
        parse_mode='Markdown'
    )

async def handle_boss_damage(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик боссов по урону"""
    query = update.callback_query
    await query.answer()
    
    user = await get_user(update.effective_user.id, update.effective_user.username)
    
    # Фиктивные данные для примера
    damage_bosses = [
        "🔥 Fire Dragon - 500 урона",
        "⚡ Thunder God - 450 урона", 
        "💀 Death Knight - 400 урона",
        "🩸 Blood Demon - 350 урона"
    ]
    
    text = "🗡️ *Боссы по урону:*\n\n" + "\n".join(f"• {boss}" for boss in damage_bosses)
    text += "\n\n💡 *Совет:* Высокий урон = быстрое прохождение!"
    
    await query.edit_message_text(
        text=text,
        reply_markup=get_boss_menu_keyboard(),
        parse_mode='Markdown'
    )

async def handle_boss_tank(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик боссов по живучести"""
    query = update.callback_query
    await query.answer()
    
    user = await get_user(update.effective_user.id, update.effective_user.username)
    
    # Фиктивные данные для примера
    tank_bosses = [
        "🪨 Stone Golem - 5000 HP",
        "🔥 Lava Beast - 4500 HP", 
        "💀 Bone Dragon - 4000 HP",
        "🩸 Flesh Giant - 3500 HP"
    ]
    
    text = "🛡️ *Боссы по живучести:*\n\n" + "\n".join(f"• {boss}" for boss in tank_bosses)
    text += "\n\n💡 *Совет:* Выбирайте тактику для долгих боев!"
    
    await query.edit_message_text(
        text=text,
        reply_markup=get_boss_menu_keyboard(),
        parse_mode='Markdown'
    )

async def handle_pvp_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик статистики PvP"""
    query = update.callback_query
    await query.answer()
    
    user = await get_user(update.effective_user.id, update.effective_user.username)
    
    # Фиктивные данные для примера
    stats_text = f"""
📊 *Ваша PvP статистика:*

• Побед: {user.get('pvp_wins', 5)}
• Поражений: {user.get('pvp_losses', 2)}
• MMR: {user.get('mmr', 1200)}
• Соотношение: 2.5:1
• Лучшая серия: 3 победы

🏆 *Рейтинг:* #{user.get('pvp_rank', 150)} в топе
"""
    
    await query.edit_message_text(
        text=stats_text,
        reply_markup=get_pvp_menu_keyboard(),
        parse_mode='Markdown'
    )

async def handle_pvp_top_mmr(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик лучших MMR"""
    query = update.callback_query
    await query.answer()
    
    # Фиктивные данные для примера
    top_players = [
        "👑 Player1 - MMR: 2500",
        "🏆 Player2 - MMR: 2300", 
        "⚔️ Player3 - MMR: 2100",
        "🗡️ Player4 - MMR: 1900",
        "🛡️ Player5 - MMR: 1800"
    ]
    
    text = "🎯 *Лучшие MMR игроки:*\n\n" + "\n".join(f"{i+1}. {player}" for i, player in enumerate(top_players))
    text += f"\n\n💡 *Ваш MMR:* {1200} (#{150})"
    
    await query.edit_message_text(
        text=text,
        reply_markup=get_pvp_menu_keyboard(),
        parse_mode='Markdown'
    )


async def handle_top_mmr(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик топа по MMR"""
    query = update.callback_query
    await query.answer()
    
    # Фиктивные данные для примера
    top_mmr = [
        "👑 MMR 2500 - Player1",
        "🏆 MMR 2300 - Player2", 
        "⚔️ MMR 2100 - Player3",
        "🗡️ MMR 1900 - Player4",
        "🛡️ MMR 1800 - Player5"
    ]
    
    text = "⚔️ *Топ игроков по MMR:*\n\n" + "\n".join(f"{i+1}. {player}" for i, player in enumerate(top_mmr))
    
    await query.edit_message_text(
        text=text,
        reply_markup=get_top_menu_keyboard(),
        parse_mode='Markdown'
    )


async def handle_daily_claim(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик получения ежедневной награды"""
    query = update.callback_query
    await query.answer()
    
    user = await get_user(update.effective_user.id, update.effective_user.username)
    
    # Фиктивные данные для примера
    daily_reward = 50
    new_gold = user.get('gold', 200) + daily_reward
    
    text = f"""
🎁 *Ежедневная награда получена!*

+{daily_reward} золота

💰 *Ваш баланс:* {new_gold}

⏰ *Следующая награда:* через 24 часа
"""
    
    await query.edit_message_text(
        text=text,
        reply_markup=get_daily_menu_keyboard(),
        parse_mode='Markdown'
    )

async def handle_daily_calendar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик календаря ежедневных наград"""
    query = update.callback_query
    await query.answer()
    
    # Фиктивные данные для примера
    calendar = """
📅 *Календарь наград:*

Пн  Вт  Ср  Чт  Пт  Сб  Вс
[✓] [✓] [✓] [✗] [✗] [✗] [✗]

💎 *Текущая серия:* 3 дня
🎁 *Награда за серию:* +100 золота
"""
    
    await query.edit_message_text(
        text=calendar,
        reply_markup=get_daily_menu_keyboard(),
        parse_mode='Markdown'
    )

async def handle_daily_bonuses(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик ежедневных бонусов"""
    query = update.callback_query
    await query.answer()
    
    bonuses = """
💎 *Доступные ежедневные бонусы:*

• 🎁 Стартовый бонус: +100 золота
• ⚡ Энергия: +50 к урону на 1 час
• ❤️ Здоровье: +20% HP
• 🛡️ Защита: +10% брони на 2 часа

💡 *Совет:* Используйте бонусы для прохождения сложных боссов!
"""
    
    await query.edit_message_text(
        text=bonuses,
        reply_markup=get_daily_menu_keyboard(),
        parse_mode='Markdown'
    )

async def handle_daily_timer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик таймера ежедневных наград"""
    query = update.callback_query
    await query.answer()
    
    timer = """
⏰ *Таймеры:*

🎁 Ежедневная награда: 23:45:12
⚡ Энергия: 1:23:45
❤️ Здоровье: 4:56:78
🛡️ Защита: 2:34:56

💡 *Совет:* Следите за таймерами для максимальной эффективности!
"""
    
    await query.edit_message_text(
        text=timer,
        reply_markup=get_daily_menu_keyboard(),
        parse_mode='Markdown'
    )

async def handle_quests_active(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик активных квестов"""
    query = update.callback_query
    await query.answer()
    
    quests = """
📋 *Активные квесты:*

1. 🗡️ Победить 5 боссов
   Прогресс: 2/5
   Награда: +100 опыта

2. ⚔️ Выиграть 3 PvP боя
   Прогресс: 1/3
   Награда: +50 золота

3. 💰 Заработать 1000 золота
   Прогресс: 350/1000
   Награда: +200 золота

💡 *Совет:* Выполняйте квесты для получения дополнительных наград!
"""
    
    await query.edit_message_text(
        text=quests,
        reply_markup=get_quests_menu_keyboard(),
        parse_mode='Markdown'
    )

async def handle_quests_completed(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик завершенных квестов"""
    query = update.callback_query
    await query.answer()
    
    completed = """
✅ *Завершенные квесты:*

1. 🗡️ Победить 10 боссов
   Награда: +500 опыта

2. ⚔️ Выиграть 5 PvP боев
   Награда: +250 золота

3. 💰 Заработать 5000 золота
   Награда: +1000 золота

🏆 *Всего получено:* +850 опыта, +1250 золота

💡 *Совет:* Продолжайте выполнять квесты для роста!
"""
    
    await query.edit_message_text(
        text=completed,
        reply_markup=get_quests_menu_keyboard(),
        parse_mode='Markdown'
    )

async def handle_quests_daily(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик ежедневных квестов"""
    query = update.callback_query
    await query.answer()
    
    daily_quests = """
🎯 *Ежедневные квесты:*

1. 🗡️ Атаковать босса 3 раза
   Награда: +50 опыта

2. ⚔️ Сыграть 2 PvP боя
   Награда: +30 золота

3. 💰 Заработать 200 золота
   Награда: +40 золота

⏰ *Сбрасываются:* каждый день в 00:00

💡 *Совет:* Ежедневные квесты - быстрый путь к прокачке!
"""
    
    await query.edit_message_text(
        text=daily_quests,
        reply_markup=get_quests_menu_keyboard(),
        parse_mode='Markdown'
    )

async def handle_quests_weekly(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик недельных квестов"""
    query = update.callback_query
    await query.answer()
    
    weekly_quests = """
🏆 *Недельные квесты:*

1. 🗡️ Победить 50 боссов
   Награда: +1000 опыта, редкий предмет

2. ⚔️ Выиграть 20 PvP боев
   Награда: +500 золота, +50 MMR

3. 💰 Заработать 5000 золота
   Награда: +1000 золота, бонус к урону

⏰ *Сбрасываются:* каждую неделю в воскресенье

💡 *Совет:* Недельные квесты дают самые ценные награды!
"""
    
    await query.edit_message_text(
        text=weekly_quests,
        reply_markup=get_quests_menu_keyboard(),
        parse_mode='Markdown'
    )

async def handle_quests_rewards(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик наград квестов"""
    query = update.callback_query
    await query.answer()
    
    rewards = """
💎 *Награды за квесты:*

📊 *Опыт:* +1500 (всего)
💰 *Золото:* +850 (всего)
🎁 *Предметы:* 3 редких, 5 обычных
⚡ *Бонусы:* +10% урона на 1 час

🏆 *Достижения:*
• Новичок (10 квестов)
• Искатель приключений (50 квестов)
• Мастер квестов (100 квестов)

💡 *Совет:* Чем больше квестов - тем лучше награды!
"""
    
    await query.edit_message_text(
        text=rewards,
        reply_markup=get_quests_menu_keyboard(),
        parse_mode='Markdown'
    )

async def handle_quests_progress(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик прогресса квестов"""
    query = update.callback_query
    await query.answer()
    
    progress = """
📊 *Прогресс квестов:*

🎯 Ежедневные: 2/3 (67%)
🏆 Недельные: 1/3 (33%)
📋 Общие: 15/25 (60%)

🔥 *Активная серия:* 5 дней подряд
💎 *Общая эффективность:* 85%

💡 *Совет:* Поддерживайте серию для бонусов!
"""
    
    await query.edit_message_text(
        text=progress,
        reply_markup=get_quests_menu_keyboard(),
        parse_mode='Markdown'
    )

async def handle_help_commands(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команд помощи"""
    query = update.callback_query
    await query.answer()
    
    commands = """
📖 *Список всех команд:*

👤 *Профиль:*
• /profile - Просмотр профиля
• /stats - Статистика персонажа

👹 *Боссы:*
• /boss - Информация о боссе
• /attack - Атаковать босса

⚔️ *PvP:*
• /pvp - Список противников
• /fight USER_ID - Вызов на дуэль

🛒 *Магазин:*
• /shop - Магазин
• /buy ITEM - Купить предмет
• /potion TYPE - Купить зелье
• /heal - Восстановить HP

🌟 *Таланты:*
• /talents - Дерево талантов
• /level_up - Повысить уровень
• /learn TALENT_ID - Изучить талант

🏆 *Рейтинги:*
• /top - Таблица лидеров
• /fissure_top - Топ по фиссуре
• /achievements - Достижения

💥 *Фиссура:*
• /fissure - Ролл фиссуры

💡 *Совет:* Используйте /start для вызова меню!
"""
    
    await query.edit_message_text(
        text=commands,
        reply_markup=get_help_keyboard(),
        parse_mode='Markdown'
    )

async def handle_help_gameplay(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик игрового процесса помощи"""
    query = update.callback_query
    await query.answer()
    
    gameplay = """
🎮 *Как играть в Fissure Bot:*

1. *Начало:*
   • Используйте /start для знакомства с меню
   • Просмотрите свой профиль через /profile
   • Изучите доступные команды

2. *Прокачка:*
   • Атакуйте боссов через /attack
   • Участвуйте в PvP боях через /pvp
   • Выполняйте квесты для получения наград

3. *Развитие:*
   • Повышайте уровень через /level_up
   • Изучайте таланты через /talents
   • Покупайте улучшения в магазине

4. *Стратегия:*
   • Балансируйте характеристики
   • Выбирайте подходящие предметы
   • Участвуйте в рейтингах

💡 *Совет:* Регулярно проверяйте /top для отслеживания прогресса!
"""
    
    await query.edit_message_text(
        text=gameplay,
        reply_markup=get_help_keyboard(),
        parse_mode='Markdown'
    )

async def handle_help_faq(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик FAQ помощи"""
    query = update.callback_query
    await query.answer()
    
    faq = """
❓ *Часто задаваемые вопросы:*

**Q: Как быстро прокачаться?**
A: Атакуйте боссов, участвуйте в PvP, выполняйте квесты

**Q: Где найти редкие предметы?**
A: В магазине, за выполнение квестов, в PvP

**Q: Как увеличить MMR?**
A: Побеждайте сильных противников в PvP

**Q: Что такое Fissure?**
A: Случайный бонус/штраф, влияющий на характеристики

**Q: Как сбросить таланты?**
A: Пока не доступно, но планируется в будущем

**Q: Почему не работает команда?**
A: Проверьте интернет-соединение и попробуйте снова

💡 *Совет:* Если проблема не решена - напишите в поддержку!
"""
    
    await query.edit_message_text(
        text=faq,
        reply_markup=get_help_keyboard(),
        parse_mode='Markdown'
    )

async def handle_help_tips(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик советов помощи"""
    query = update.callback_query
    await query.answer()
    
    tips = """
💡 *Полезные советы и подсказки:*

**🔥 Для новичков:**
• Начинайте с слабых боссов
• Выполняйте ежедневные квесты
• Балансируйте характеристики

**⚡ Для опытных:**
• Участвуйте в PvP для MMR
• Ищите редкие предметы
• Следите за рейтингами

**💎 Для профи:**
• Оптимизируйте таланты
• Используйте стратегии в PvP
• Планируйте развитие персонажа

**🎯 Общие советы:**
• Регулярно проверяйте /top
• Используйте /fissure для бонусов
• Сохраняйте золото на важные покупки

🏆 *Главное:* Наслаждайтесь игрой и помогайте другим!
"""
    
    await query.edit_message_text(
        text=tips,
        reply_markup=get_help_keyboard(),
        parse_mode='Markdown'
    )

__all__ = [
    'handle_boss_strongest', 'handle_boss_weakest', 'handle_boss_damage', 'handle_boss_tank',
    'handle_pvp_stats', 'handle_pvp_top_mmr', 'handle_top_mmr',
    'handle_daily_claim', 'handle_daily_calendar',
    'handle_daily_bonuses', 'handle_daily_timer', 'handle_quests_active', 'handle_quests_completed',
    'handle_quests_daily', 'handle_quests_weekly', 'handle_quests_rewards', 'handle_quests_progress',
    'handle_help_commands', 'handle_help_gameplay', 'handle_help_faq', 'handle_help_tips'
]

def register_menu_handlers(app):
    """Регистрация обработчиков меню"""
    # Регистрация callback-обработчиков для меню
    from telegram.ext import CallbackQueryHandler
    
    app.add_handler(CallbackQueryHandler(handle_boss_strongest, pattern='^boss_strongest$'))
    app.add_handler(CallbackQueryHandler(handle_boss_weakest, pattern='^boss_weakest$'))
    app.add_handler(CallbackQueryHandler(handle_boss_damage, pattern='^boss_damage$'))
    app.add_handler(CallbackQueryHandler(handle_boss_tank, pattern='^boss_tank$'))
    
    app.add_handler(CallbackQueryHandler(handle_pvp_stats, pattern='^pvp_stats$'))
    app.add_handler(CallbackQueryHandler(handle_pvp_top_mmr, pattern='^pvp_top_mmr$'))
    
    app.add_handler(CallbackQueryHandler(handle_top_mmr, pattern='^top_mmr$'))
    
    app.add_handler(CallbackQueryHandler(handle_daily_claim, pattern='^daily_claim$'))
    app.add_handler(CallbackQueryHandler(handle_daily_calendar, pattern='^daily_calendar$'))
    app.add_handler(CallbackQueryHandler(handle_daily_bonuses, pattern='^daily_bonuses$'))
    app.add_handler(CallbackQueryHandler(handle_daily_timer, pattern='^daily_timer$'))
    
    app.add_handler(CallbackQueryHandler(handle_quests_active, pattern='^quests_active$'))
    app.add_handler(CallbackQueryHandler(handle_quests_completed, pattern='^quests_completed$'))
    app.add_handler(CallbackQueryHandler(handle_quests_daily, pattern='^quests_daily$'))
    app.add_handler(CallbackQueryHandler(handle_quests_weekly, pattern='^quests_weekly$'))
    app.add_handler(CallbackQueryHandler(handle_quests_rewards, pattern='^quests_rewards$'))
    app.add_handler(CallbackQueryHandler(handle_quests_progress, pattern='^quests_progress$'))
    
    app.add_handler(CallbackQueryHandler(handle_help_commands, pattern='^help_commands$'))
    app.add_handler(CallbackQueryHandler(handle_help_gameplay, pattern='^help_gameplay$'))
    app.add_handler(CallbackQueryHandler(handle_help_faq, pattern='^help_faq$'))
    app.add_handler(CallbackQueryHandler(handle_help_tips, pattern='^help_tips$'))
