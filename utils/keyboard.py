"""Модуль для создания клавиатур"""

from telegram import ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton
from typing import List, Optional

# ================= КЛАВИАТУРЫ =================

MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [["👹 BOSS", "🛒 SHOP"], ["⚔️ PVP", "🏆 TOP"], ["🍆 FISSURE", "👤 ПРОФИЛЬ"], ["🎯 ТАЛАНТЫ"]],
    resize_keyboard=True,
)

FISSURE_KEYBOARD = ReplyKeyboardMarkup(
    [["🎲 ROLL"], ["📊 STATS", "⬅️ НАЗАД"]],
    resize_keyboard=True,
)

# Клавиатура категорий магазина
SHOP_CATEGORIES_KEYBOARD = ReplyKeyboardMarkup(
    [["👟 Сапоги", "🛡️ Броня"], ["🗡️ Оружие", "🛡️ Защита"], ["🔮 Поддержка", "🧪 Зелья"], ["⬅️ НАЗАД"]],
    resize_keyboard=True,
)

def create_talent_keyboard(talents_data: dict, user_talents: dict, user_level: int) -> Optional[InlineKeyboardMarkup]:
    """Создает inline-клавиатуру для талантов"""
    try:
        keyboard = []
        for branch_name, branch_talents in talents_data.items():
            for talent_id, talent_data in branch_talents.items():
                learned = user_talents.get(talent_data["id"], 0)
                max_level = talent_data["max_level"]
                
                # Проверяем требования
                can_learn = True
                if talent_data.get("requires"):
                    requires = talent_data["requires"]
                    if requires[0] == "min_level_10" and user_level < 10:
                        can_learn = False
                    else:
                        for req in requires:
                            if user_talents.get(req, 0) < 1:
                                can_learn = False
                
                if learned < max_level and can_learn:
                    level_text = f"{learned}/{max_level}" if learned > 0 else f"0/{max_level}"
                    button = InlineKeyboardButton(
                        f"{talent_data['name']} ({level_text})",
                        callback_data=f"learn_{talent_id}"
                    )
                    keyboard.append([button])
        
        return InlineKeyboardMarkup(keyboard) if keyboard else None
    except Exception as e:
        print(f"Ошибка создания клавиатуры талантов: {e}")
        return None

def create_pvp_keyboard(opponents: list) -> Optional[ReplyKeyboardMarkup]:
    """Создает клавиатуру для PvP противников"""
    try:
        if not opponents:
            return None
        
        keyboard = []
        for i, opponent in enumerate(opponents[:10]):  # Ограничиваем 10 противниками
            row = [f"👤 {opponent['username']} (MMR: {opponent['mmr']})"]
            keyboard.append(row)
            keyboard.append([f"/fight_{opponent['user_id']}"])
        
        keyboard.append(["⬅️ НАЗАД"])
        return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    except Exception as e:
        print(f"Ошибка создания клавиатуры PvP: {e}")
        return None