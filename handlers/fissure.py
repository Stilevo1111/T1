"""Обработчики команд, связанных с фиссурой"""

import logging
import time
from typing import Dict, Any
from telegram import Update
from telegram.ext import ContextTypes

from database import get_user, get_fissure_top, update_fissure
from game_logic import get_fissure_result, get_meme_message
from utils.formatters import format_stats_text
from utils.keyboard import FISSURE_KEYBOARD
from handlers.fissure_system import fissure_system

logger = logging.getLogger(__name__)

# Константы
COOLDOWN = 86400  # 24 часа в секундах
AUTO_DELETE_DELAY = 30  # секунд

async def fissure(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /fissure"""
    try:
        username = update.effective_user.username or update.effective_user.full_name
        user = await get_user(update.effective_user.id, username)
        now = time.time()
        remaining = COOLDOWN - (now - user["last_fissure"])
        
        if remaining > 0:
            hours = int(remaining // 3600)
            minutes = int((remaining % 3600) // 60)
            msg = await update.message.reply_text(
                f"⏳ Через {hours} ч. {minutes} мин."
            )
            context.application.create_task(
                auto_delete(context, update.effective_chat.id, [msg.message_id])
            )
        else:
            # Получаем текущую длину фиссуры пользователя
            current_length = user["fissure"]
            new_value, text, phrase = get_fissure_result_with_length(current_length)
            await update_fissure(update.effective_user.id, new_value, now)
            msg = await update.message.reply_text(
                f"{text}\n{phrase}\n📏 Теперь {new_value:.1f} см"
            )
            context.application.create_task(
                auto_delete(context, update.effective_chat.id, [msg.message_id])
            )
    except Exception as e:
        logger.error(f"Ошибка в команде /fissure: {e}")
        if update and update.message:
            await update.message.reply_text("❌ Произошла ошибка. Попробуйте позже.")

async def fissure_top(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /fissure_top"""
    try:
        rows = await get_fissure_top()
        if not rows:
            await update.message.reply_text("Топ пуст 😢")
        else:
            text = ["🏆 ТОП по длине фиссуры:\n"]
            for i, row in enumerate(rows, 1):
                text.append(f"{i}. 👤 {row['username']} — {row['fissure']:.1f} см")
            await update.message.reply_text("\n".join(text))
    except Exception as e:
        logger.error(f"Ошибка в команде /fissure_top: {e}")
        if update and update.message:
            await update.message.reply_text("❌ Произошла ошибка. Попробуйте позже.")

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /stats для фиссуры"""
    try:
        username = update.effective_user.username or update.effective_user.full_name
        user = await get_user(update.effective_user.id, username)
        stats = calculate_character_stats(user)
        
        msg = await update.message.reply_text(
            f"📊 Твоя Фиссура:\n📏 {user['fissure']:.1f} см",
            reply_markup=FISSURE_KEYBOARD
        )
        context.application.create_task(
            auto_delete(context, update.effective_chat.id, [msg.message_id])
        )
    except Exception as e:
        logger.error(f"Ошибка в команде /stats (fissure): {e}")
        if update and update.message:
            await update.message.reply_text("❌ Произошла ошибка. Попробуйте позже.")

async def grow_fissure(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /grow_fissure - контроль роста Fissure"""
    try:
        user_id = update.effective_user.id
        result = await fissure_system.grow_fissure(user_id)
        
        if result['success']:
            message = result['message']
            if 'explosion' in result and result['explosion']:
                message += "\n\n💥 Fissure взорвалась! Получите мощный эффект!"
            
            await update.message.reply_text(message)
        else:
            await update.message.reply_text(f"❌ {result['message']}")
    except Exception as e:
        logger.error(f"Ошибка в команде /grow_fissure: {e}")
        if update and update.message:
            await update.message.reply_text("❌ Произошла ошибка. Попробуйте позже.")

async def auto_delete(context: ContextTypes.DEFAULT_TYPE, chat_id: int, msg_ids: list) -> None:
    """Автоматическое удаление сообщений через заданное время"""
    import asyncio
    await asyncio.sleep(AUTO_DELETE_DELAY)
    for msg_id in msg_ids:
        try:
            await context.bot.delete_message(chat_id, msg_id)
        except Exception:
            pass

# Импортируем calculate_character_stats для использования в stats
from game_logic import calculate_character_stats

def get_fissure_result() -> tuple[float, str, str]:
    """Получает результат броска фиссуры с новыми шутками"""
    import random
    
    # Вероятности как в ТЗ
    rolls = [
        (-5, 5),   # -5 см: 5%
        (-3, 10),  # -3 см: 10%
        (-1, 15),  # -1 см: 15%
        (0, 20),   # +0 см: 20%
        (1, 20),   # +1 см: 20%
        (3, 15),   # +3 см: 15%
        (5, 10),   # +5 см: 10%
        (10, 5)    # +10 см: 5%
    ]
    
    # Выбираем результат на основе вероятностей
    roll = random.choices([r[0] for r in rolls], weights=[r[1] for r in rolls])[0]
    
    # Текущая длина фиссуры (берем из базы, но для примера используем 0.1)
    current_length = 0.1  # Это будет подставляться из реального пользователя
    new_value = max(0.1, current_length + roll)  # Минимум 0.1 см
    
    # Тексты для разных результатов
    if roll > 0:
        text = f"🎉 +{roll} см!"
        phrase = "Твоя фиссура стала длиннее! 💪"
    elif roll < 0:
        text = f"💔 {roll} см..."
        # Шутки при уменьшении (аналогично пенису)
        phrases_down = [
            "Не переживай, размер не главное... хотя и обидно.",
            "Сохрани энергию для следующего броска!",
            "Это временно, фиссура восстановится!",
            "Главное - не сдаваться!",
            "Бывает и такое, не расстраивайся!"
        ]
        phrase = random.choice(phrases_down)
    else:
        text = "🤷 Без изменений"
        phrase = "Ничего не изменилось, но ты молодец!"
    
    return new_value, text, phrase

def get_fissure_result_with_length(current_length: float) -> tuple[float, str, str]:
    """Получает результат броска фиссуры с учетом текущей длины"""
    import random
    
    # Вероятности как в ТЗ
    rolls = [
        (-5, 5),   # -5 см: 5%
        (-3, 10),  # -3 см: 10%
        (-1, 15),  # -1 см: 15%
        (0, 20),   # +0 см: 20%
        (1, 20),   # +1 см: 20%
        (3, 15),   # +3 см: 15%
        (5, 10),   # +5 см: 10%
        (10, 5)    # +10 см: 5%
    ]
    
    # Выбираем результат на основе вероятностей
    roll = random.choices([r[0] for r in rolls], weights=[r[1] for r in rolls])[0]
    
    # Рассчитываем новую длину
    new_value = max(0.1, current_length + roll)  # Минимум 0.1 см
    
    # Тексты для разных результатов
    if roll > 0:
        text = f"🎉 +{roll} см!"
        phrase = "Твоя фиссура стала длиннее! 💪"
    elif roll < 0:
        text = f"💔 {roll} см..."
        # Шутки при уменьшении (аналогично пенису)
        phrases_down = [
            "Не переживай, размер не главное... хотя и обидно.",
            "Сохрани энергию для следующего броска!",
            "Это временно, фиссура восстановится!",
            "Главное - не сдаваться!",
            "Бывает и такое, не расстраивайся!"
        ]
        phrase = random.choice(phrases_down)
    else:
        text = "🤷 Без изменений"
        phrase = "Ничего не изменилось, но ты молодец!"
    
    return new_value, text, phrase
