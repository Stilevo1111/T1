"""Обработчики команд, связанных с талантами и уровнями"""

import logging
from typing import Dict, Any
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes

from database import get_user, update_user
from game_logic import (
    check_level_up_new, get_talent_info, can_learn_talent, apply_talent_effects, 
    get_user_achievements, get_user_progress, get_next_level_exp
)
from utils.formatters import format_talent_tree, format_achievements
from utils.keyboard import create_talent_keyboard

logger = logging.getLogger(__name__)

async def talents(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показать дерево талантов"""
    try:
        username = update.effective_user.username or update.effective_user.full_name
        user = await get_user(update.effective_user.id, username)
        
        # Импортируем TALENTS из game_logic
        from game_logic import TALENTS
        
        text = format_talent_tree(user, TALENTS)
        
        # Создаем inline-клавиатуру для талантов
        keyboard = create_talent_keyboard(TALENTS, user.get("talents", {}), user["level"])
        reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
        
        await update.message.reply_text(text, reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"Ошибка в talents: {e}")
        await update.message.reply_text("❌ Произошла ошибка. Попробуйте позже.")

async def handle_talent_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик нажатий на кнопки талантов"""
    try:
        query = update.callback_query
        await query.answer()
        
        talent_id = query.data.replace("learn_", "")
        await learn_talent(update, context, talent_id)
        await query.message.delete()  # Удаляем сообщение с кнопками
    except Exception as e:
        logger.error(f"Ошибка в handle_talent_buttons: {e}")

async def learn_talent(update: Update, context: ContextTypes.DEFAULT_TYPE, talent_id: str) -> None:
    """Изучить талант"""
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
        
        await update.message.reply_text(
            f"✅ Изучен талант: {talent['name']} (ур. {current_talents[talent_id]})\n"
            f"📊 {talent['description']}\n"
            f"🎯 Осталось очков: {talent_points - cost}"
        )
    except Exception as e:
        logger.error(f"Ошибка в learn_talent: {e}")
        await update.message.reply_text("❌ Произошла ошибка. Попробуйте позже.")

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