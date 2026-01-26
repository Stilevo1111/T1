"""Обработчики команд, связанных с талантами и уровнями"""

import logging
from typing import Dict, Any
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes, CallbackQueryHandler

from database import get_user, update_user
from database.real_database import db_manager
from game_logic import (
    check_level_up_new, get_talent_info, can_learn_talent, apply_talent_effects, 
    get_user_achievements, get_user_progress, get_next_level_exp
)
from utils.formatters import format_talent_tree, format_achievements
from utils.keyboard import create_talent_keyboard

logger = logging.getLogger(__name__)

async def talents(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показать дерево талантов с улучшенным меню"""
    try:
        username = update.effective_user.username or update.effective_user.full_name
        user = await get_user(update.effective_user.id, username)
        
        # Импортируем TALENTS из game_logic
        from game_logic import TALENTS
        
        # Создаем улучшенное меню талантов
        text = "🌳 ДЕРЕВО ТАЛАНТОВ\n\n"
        text += f"🎯 Уровень: {user.get('level', 1)} | 🌟 Очки талантов: {user.get('talent_points', 0)}\n\n"
        text += "Выберите категорию талантов:\n\n"
        
        # Категории талантов
        categories = {
            'strength': '💪 Сила (PvP & Боссы)',
            'agility': '🏃‍♂️ Ловкость (PvP & Боссы)',
            'intelligence': '🧠 Интеллект (PvP & Боссы)',
            'hybrid': '🌟 Универсальные (PvP & Боссы)'
        }
        
        # Создаем клавиатуру с категориями
        keyboard = []
        row = []
        for category_id, category_name in categories.items():
            button = InlineKeyboardButton(category_name, callback_data=f"talents_category_{category_id}")
            row.append(button)
            if len(row) == 2:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)
        
        # Добавляем кнопки управления
        keyboard.append([InlineKeyboardButton("📊 Моя статистика", callback_data="talents_stats")])
        keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data="main_menu")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(text, reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"Ошибка в talents: {e}")
        await update.message.reply_text("❌ Произошла ошибка. Попробуйте позже.")

async def handle_talents_category(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик выбора категории талантов"""
    try:
        query = update.callback_query
        await query.answer()
        
        category = query.data.replace("talents_category_", "")
        username = update.effective_user.username or update.effective_user.full_name
        user = await get_user(update.effective_user.id, username)
        
        # Импортируем TALENTS из game_logic
        from game_logic import TALENTS
        
        # Фильтруем таланты по категории
        category_talents = {k: v for k, v in TALENTS.items() if v.get('category') == category}
        
        if not category_talents:
            await query.edit_message_text("❌ Категория не найдена")
            return
        
        # Формируем текст для категории
        category_names = {
            'strength': '💪 Сила',
            'agility': '🏃‍♂️ Ловкость', 
            'intelligence': '🧠 Интеллект',
            'hybrid': '🌟 Универсальные'
        }
        
        text = f"🌳 {category_names.get(category, category.upper())}\n\n"
        text += f"🎯 Уровень: {user.get('level', 1)} | 🌟 Очки талантов: {user.get('talent_points', 0)}\n\n"
        text += "Доступные таланты:\n\n"
        
        # Показываем таланты в категории
        learned_talents = user.get("talents", {})
        for talent_id, talent_data in category_talents.items():
            current_level = learned_talents.get(talent_id, 0)
            max_level = talent_data.get("max_level", 1)
            cost = talent_data.get("cost", 0)
            description = talent_data.get("description", "")
            level_req = talent_data.get("level_req", 1)
            prereqs = talent_data.get("prerequisites", [])
            
            # Проверяем доступность
            is_available = True
            if current_level >= max_level:
                status = "✅ Изучен"
            elif user.get("level", 1) < level_req:
                status = f"🔒 Требуется уровень {level_req}"
                is_available = False
            elif user.get("talent_points", 0) < cost:
                status = "💰 Недостаточно очков"
                is_available = False
            elif prereqs and not all(t in learned_talents for t in prereqs):
                status = "🔒 Требуются предыдущие таланты"
                is_available = False
            else:
                status = f"🎯 Изучить ({cost} очков)"
            
            text += f"🔸 <b>{talent_data['name']}</b> (ур. {current_level}/{max_level})\n"
            text += f"   {description}\n"
            text += f"   {status}\n\n"
        
        # Создаем клавиатуру с талантами
        keyboard = []
        row = []
        for talent_id in category_talents.keys():
            button = InlineKeyboardButton(f"Изучить {talent_id}", callback_data=f"learn_talent_{talent_id}")
            row.append(button)
            if len(row) == 2:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)
        
        keyboard.append([InlineKeyboardButton("⬅️ Назад к категориям", callback_data="talents_main")])
        keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data="main_menu")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='HTML')
    except Exception as e:
        logger.error(f"Ошибка в handle_talents_category: {e}")
        await query.edit_message_text("❌ Произошла ошибка. Попробуйте позже.")

async def handle_talents_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик просмотра статистики талантов"""
    try:
        query = update.callback_query
        await query.answer()
        
        username = update.effective_user.username or update.effective_user.full_name
        user = await get_user(update.effective_user.id, username)
        
        # Импортируем TALENTS из game_logic
        from game_logic import TALENTS
        
        learned_talents = user.get("talents", {})
        total_points = user.get("total_talent_points", 0)
        current_points = user.get("talent_points", 0)
        level = user.get("level", 1)
        
        # Рассчитываем бонусы от талантов
        total_str_bonus = 0
        total_agi_bonus = 0
        total_int_bonus = 0
        total_damage_bonus = 0
        total_armor_bonus = 0
        total_hp_bonus = 0
        
        for talent_id, level_talent in learned_talents.items():
            if talent_id in TALENTS:
                talent_data = TALENTS[talent_id]
                # Рассчитываем бонусы (упрощенный расчет)
                if 'str' in talent_data.get('stats', {}):
                    total_str_bonus += talent_data['stats']['str'] * level_talent
                if 'agi' in talent_data.get('stats', {}):
                    total_agi_bonus += talent_data['stats']['agi'] * level_talent
                if 'int' in talent_data.get('stats', {}):
                    total_int_bonus += talent_data['stats']['int'] * level_talent
        
        text = "📊 СТАТИСТИКА ТАЛАНТОВ\n\n"
        text += f"🎯 Уровень: {level}\n"
        text += f"🌟 Всего очков: {total_points}\n"
        text += f"🎯 Доступно: {current_points}\n"
        text += f"📚 Изучено талантов: {len(learned_talents)}\n\n"
        text += "📈 Бонусы от талантов:\n"
        text += f"  💪 Сила: +{total_str_bonus}\n"
        text += f"  🏃‍♂️ Ловкость: +{total_agi_bonus}\n"
        text += f"  🧠 Интеллект: +{total_int_bonus}\n\n"
        text += "⚔️ Влияние на бои:\n"
        text += "  • Все таланты влияют на PvP бои\n"
        text += "  • Все таланты влияют на боссов\n"
        text += "  • Бонусы применяются автоматически\n\n"
        text += "💡 Советы:\n"
        text += "  • Сила → больше урона и HP\n"
        text += "  • Ловкость → криты и уклонение\n"
        text += "  • Интеллект → мана и магия\n"
        text += "  • Гибридные → универсальные бонусы\n"
        
        keyboard = [
            [InlineKeyboardButton("⬅️ Назад", callback_data="talents_main")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text, reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"Ошибка в handle_talents_stats: {e}")
        await query.edit_message_text("❌ Произошла ошибка. Попробуйте позже.")

async def handle_talents_main(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Возврат в главное меню талантов"""
    try:
        query = update.callback_query
        await query.answer()
        await talents(update, context)
    except Exception as e:
        logger.error(f"Ошибка в handle_talents_main: {e}")

async def learn_talent(update: Update, context: ContextTypes.DEFAULT_TYPE, talent_id: str) -> None:
    """Изучить талант с улучшенной логикой"""
    try:
        username = update.effective_user.username or update.effective_user.full_name
        user = await get_user(update.effective_user.id, username)
        
        # Проверяем возможность изучения таланта
        can_learn, message = can_learn_talent(user, talent_id)
        if not can_learn:
            await update.message.reply_text(f"❌ {message}")
            return
        
        # Получаем информацию о таланте
        talent = get_talent_info(talent_id)
        if not talent:
            await update.message.reply_text("❌ Такого таланта не существует")
            return
        
        # Проверяем текущий уровень таланта
        current_level = user.get("talents", {}).get(talent_id, 0)
        if current_level >= talent["max_level"]:
            await update.message.reply_text("❌ Талант уже изучен на максимальный уровень")
            return
        
        # Проверяем очки талантов
        talent_points = user.get("talent_points", 0)
        cost = talent["cost"]
        
        if talent_points < cost:
            await update.message.reply_text("❌ Недостаточно очков талантов")
            return
        
        # Изучаем талант
        current_talents = user.get("talents", {})
        current_talents[talent_id] = current_talents.get(talent_id, 0) + 1
        
        # Применяем эффект таланта
        effect = apply_talent_effects(user, talent_id, current_talents[talent_id])
        
        # Обновляем пользователя
        await update_user(
            update.effective_user.id,
            talents=current_talents,
            talent_points=talent_points - cost,
            total_talent_points=user.get("total_talent_points", 0) + 1,
            **effect  # Применяем эффекты таланта
        )
        
        # Формируем сообщение об успехе
        text = f"✅ ТАЛАНТ ИЗУЧЕН!\n\n"
        text += f"🔸 <b>{talent['name']}</b> (ур. {current_talents[talent_id]})\n"
        text += f"📊 {talent['description']}\n\n"
        text += f"🎯 Осталось очков: {talent_points - cost}\n\n"
        text += f"⚔️ ВЛИЯНИЕ НА БОИ:\n"
        text += f"  • PvP бои: {talent.get('pvp_effect', 'Улучшает характеристики')}\n"
        text += f"  • Боссы: {talent.get('boss_effect', 'Улучшает характеристики')}\n\n"
        text += f"💡 Используйте /talents для просмотра всех талантов"
        
        await update.message.reply_text(text, parse_mode='HTML')
    except Exception as e:
        logger.error(f"Ошибка в learn_talent: {e}")
        await update.message.reply_text("❌ Произошла ошибка. Попробуйте позже.")

async def handle_learn_talent_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик нажатия на кнопку изучения таланта"""
    try:
        query = update.callback_query
        await query.answer()
        
        talent_id = query.data.replace("learn_talent_", "")
        username = update.effective_user.username or update.effective_user.full_name
        user = await get_user(update.effective_user.id, username)
        
        # Проверяем возможность изучения таланта
        can_learn, message = can_learn_talent(user, talent_id)
        if not can_learn:
            await query.edit_message_text(f"❌ {message}")
            return
        
        # Получаем информацию о таланте
        talent = get_talent_info(talent_id)
        if not talent:
            await query.edit_message_text("❌ Такого таланта не существует")
            return
        
        # Проверяем текущий уровень таланта
        current_level = user.get("talents", {}).get(talent_id, 0)
        if current_level >= talent["max_level"]:
            await query.edit_message_text("❌ Талант уже изучен на максимальный уровень")
            return
        
        # Проверяем очки талантов
        talent_points = user.get("talent_points", 0)
        cost = talent["cost"]
        
        if talent_points < cost:
            await query.edit_message_text("❌ Недостаточно очков талантов")
            return
        
        # Изучаем талант
        current_talents = user.get("talents", {})
        current_talents[talent_id] = current_talents.get(talent_id, 0) + 1
        
        # Применяем эффект таланта
        effect = apply_talent_effects(user, talent_id, current_talents[talent_id])
        
        # Обновляем пользователя
        await update_user(
            update.effective_user.id,
            talents=current_talents,
            talent_points=talent_points - cost,
            total_talent_points=user.get("total_talent_points", 0) + 1,
            **effect  # Применяем эффекты таланта
        )
        
        # Формируем сообщение об успехе
        text = f"✅ ТАЛАНТ ИЗУЧЕН!\n\n"
        text += f"🔸 <b>{talent['name']}</b> (ур. {current_talents[talent_id]})\n"
        text += f"📊 {talent['description']}\n\n"
        text += f"🎯 Осталось очков: {talent_points - cost}\n\n"
        text += f"⚔️ ВЛИЯНИЕ НА БОИ:\n"
        text += f"  • PvP бои: {talent.get('pvp_effect', 'Улучшает характеристики')}\n"
        text += f"  • Боссы: {talent.get('boss_effect', 'Улучшает характеристики')}\n\n"
        text += f"💡 Используйте /talents для просмотра всех талантов"
        
        keyboard = [
            [InlineKeyboardButton("⬅️ Назад к категории", callback_data=f"talents_category_{talent.get('category', 'strength')}")],
            [InlineKeyboardButton("⬅️ Назад", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='HTML')
    except Exception as e:
        logger.error(f"Ошибка в handle_learn_talent_callback: {e}")
        await query.edit_message_text("❌ Произошла ошибка. Попробуйте позже.")

async def learn(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /learn"""
    try:
        talent_id = context.args[0] if context.args else None
        if not talent_id:
            await update.message.reply_text("❌ Укажите ID таланта: /learn TALENT_ID")
            return
        await learn_talent(update, context, talent_id)
    except Exception as e:
        logger.error(f"Ошибка в learn: {e}")
        await update.message.reply_text("❌ Произошла ошибка при изучении таланта")

async def level_up(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /level_up"""
    await level_up_handler(update, context)

async def add_str(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Добавить очки к силе"""
    await add_stat(update, context, "str")

async def add_agi(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Добавить очки к ловкости"""
    await add_stat(update, context, "agi")

async def add_int(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Добавить очки к интеллекту"""
    await add_stat(update, context, "int")

async def stats_distribute(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Распределить очки характеристик"""
    try:
        username = update.effective_user.username or update.effective_user.full_name
        user = await get_user(update.effective_user.id, username)
        
        try:
            points_to_distribute = int(context.args[0]) if context.args else None
            if points_to_distribute is None:
                # Показываем текущее распределение
                unspent = user.get("unspent_stats", 0)
                text = f"📊 РАСПРЕДЕЛЕНИЕ ХАРАКТЕРИСТИК\n"
                text += f"💪 Доступно очков: {unspent}\n"
                text += f"Текущие характеристики:\n"
                text += f"  💪 Сила: {user['str']}\n"
                text += f"  🏃‍♂️ Ловкость: {user['agi']}\n"
                text += f"  🧠 Интеллект: {user['int']}\n\n"
                text += "💡 Используйте:\n"
                text += "/add_str POINTS - добавить к силе\n"
                text += "/add_agi POINTS - добавить к ловкости\n"
                text += "/add_int POINTS - добавить к интеллекту\n"
                await update.message.reply_text(text)
                return
            
            if points_to_distribute > user.get("unspent_stats", 0):
                await update.message.reply_text("❌ Недостаточно очков характеристик")
                return
                
        except ValueError:
            await update.message.reply_text("❌ Укажите количество очков числом")
    except Exception as e:
        logger.error(f"Ошибка в stats_distribute: {e}")
        await update.message.reply_text("❌ Произошла ошибка. Попробуйте позже.")

async def add_stat(update: Update, context: ContextTypes.DEFAULT_TYPE, stat_type: str) -> None:
    """Добавить очки к характеристике"""
    try:
        username = update.effective_user.username or update.effective_user.full_name
        user = await get_user(update.effective_user.id, username)
        
        try:
            points = int(context.args[0]) if context.args else 1
        except ValueError:
            await update.message.reply_text("❌ Укажите количество очков числом")
            return
        
        if points <= 0:
            await update.message.reply_text("❌ Укажите положительное число")
            return
        
        if points > user.get("unspent_stats", 0):
            await update.message.reply_text("❌ Недостаточно очков характеристик")
            return
        
        # Обновляем характеристику
        current_stat = user[stat_type]
        new_stat = current_stat + points
        
        await update_user(
            update.effective_user.id,
            **{stat_type: new_stat},
            unspent_stats=user.get("unspent_stats", 0) - points
        )
        
        stat_names = {"str": "💪 Силу", "agi": "🏃‍♂️ Ловкость", "int": "🧠 Интеллект"}
        await update.message.reply_text(
            f"✅ Добавлено {points} очков к {stat_names[stat_type]}\n"
            f"📊 Новое значение: {new_stat}\n"
            f"🎯 Осталось очков: {user.get('unspent_stats', 0) - points}"
        )
    except Exception as e:
        logger.error(f"Ошибка в add_stat: {e}")
        await update.message.reply_text("❌ Произошла ошибка. Попробуйте позже.")

async def level_up_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик повышения уровня"""
    try:
        username = update.effective_user.username or update.effective_user.full_name
        user = await get_user(update.effective_user.id, username)
        
        can_level_up, bonuses = check_level_up_new(user)
        
        if not can_level_up:
            next_level_exp = get_next_level_exp(user["level"])
            needed_exp = next_level_exp - user["exp"]
            await update.message.reply_text(
                f"📊 До следующего уровня нужно: {needed_exp} опыта\n"
                f"🎯 Текущий опыт: {user['exp']}/{next_level_exp}"
            )
            return
        
        # Применяем бонусы уровня
        new_hp_max = user.get("hp_max", 100) + bonuses["hp_bonus"]
        new_level = bonuses["new_level"]
        
        await update_user(
            update.effective_user.id,
            level=new_level,
            hp=new_hp_max,
            hp_max=new_hp_max,
            unspent_stats=user.get("unspent_stats", 0) + bonuses["stats_points"],
            talent_points=user.get("talent_points", 0) + bonuses.get("talent_points", 0)
        )
        
        # Формируем сообщение о повышении
        text = f"🎉 ПОЗДРАВЛЯЕМ! 🎉\n"
        text += f"Вы достигли {new_level} уровня!\n\n"
        text += f"📊 Полученные бонусы:\n"
        text += f"  ❤️ +{bonuses['hp_bonus']} максимального HP\n"
        text += f"  🎯 +{bonuses['stats_points']} очков характеристик\n"
        
        if bonuses.get("talent_points", 0) > 0:
            text += f"  🌟 +{bonuses['talent_points']} очков талантов\n"
        
        if bonuses.get("title"):
            await update_user(update.effective_user.id, title=bonuses["title"])
            text += f"  🏆 Новый титул: {bonuses['title']}\n"
        
        text += f"\n💡 Используйте:\n"
        text += f"/talents - чтобы изучить таланты\n"
        text += f"/stats_distribute - чтобы распределить характеристики\n"
        
        if new_level in [5, 10, 15, 20, 25, 30]:
            text += f"\n🌟 ДОСТИЖЕНИЕ: Достигнут юбилейный уровень!\n"
        
        await update.message.reply_text(text)
    except Exception as e:
        logger.error(f"Ошибка в level_up_handler: {e}")
        await update.message.reply_text("❌ Произошла ошибка. Попробуйте позже.")

async def achievements(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Достижения игрока"""
    try:
        username = update.effective_user.username or update.effective_user.full_name
        user = await get_user(update.effective_user.id, username)
        
        achievements_list = get_user_achievements(user)
        text = format_achievements(user, achievements_list)
        await update.message.reply_text(text)
    except Exception as e:
        logger.error(f"Ошибка в achievements: {e}")
        await update.message.reply_text("❌ Произошла ошибка. Попробуйте позже.")

# Регистрация обработчиков колбэков
def register_talent_callbacks(application):
    """Регистрация обработчиков колбэков для талантов"""
    application.add_handler(CallbackQueryHandler(handle_talents_category, pattern=r"^talents_category_"))
    application.add_handler(CallbackQueryHandler(handle_talents_stats, pattern=r"^talents_stats$"))
    application.add_handler(CallbackQueryHandler(handle_talents_main, pattern=r"^talents_main$"))
    application.add_handler(CallbackQueryHandler(handle_learn_talent_callback, pattern=r"^learn_talent_"))


