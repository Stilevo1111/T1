"""Модуль для создания клавиатур"""

from telegram import InlineKeyboardMarkup, InlineKeyboardButton
from typing import List, Optional

# ================= КЛАВИАТУРЫ =================

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

def create_pvp_keyboard(opponents: list) -> Optional[InlineKeyboardMarkup]:
    """Создает inline-клавиатуру для PvP противников"""
    try:
        if not opponents:
            return None
        
        keyboard = []
        for opponent in opponents:
            opponent_id = opponent['user_id']
            opponent_name = opponent['username']
            opponent_mmr = opponent['mmr']
            opponent_level = opponent['level']
            
            button_text = f"⚔️ {opponent_name} (Lvl {opponent_level}, MMR {opponent_mmr})"
            button = InlineKeyboardButton(button_text, callback_data=f"pvp_fight_{opponent_id}")
            keyboard.append([button])
        
        keyboard.append([InlineKeyboardButton("🔄 Обновить список", callback_data="pvp_refresh")])
        keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data="main_menu")])
        
        return InlineKeyboardMarkup(keyboard)
    except Exception as e:
        print(f"Ошибка создания клавиатуры PvP: {e}")
        return None
