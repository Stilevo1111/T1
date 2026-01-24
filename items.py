# items.py
items = {
    # 🗡 ОРУЖИЕ
    "weapons": {
        "Daedalus": {"💪": 5, "🍀": 2, "🎯": "20% крит x2", "💰": 800, "🎁": ["Roshan"]},
        "Divine Rapier": {"💪": 10, "☠️": "50% урона", "⚠️": "теряется при поражении", "💰": 1500, "🎁": ["Roshan Prime"]},
        "Monkey King Bar": {"💪": 4, "🍀": 3, "⚡": "15% доп. урона", "💰": 1000, "🎁": ["Axe"]},
        "Desolator": {"💪": 4, "🩸": "10% урона по боссам", "💰": 900, "🎁": ["Shadow Fiend"]},
        "Battle Fury": {"💪": 3, "🌪": "шанс ударить всех (рейд)", "💰": 950, "🎁": ["Zeus"]},
        "Radiance": {"💪": 2, "🔥": "пассивный урон всем", "💰": 1200, "🎁": ["Invoker"]},
    },
    # 🛡 БРОНЯ
    "armor": {
        "Assault Cuirass": {"💪": 3, "🍀": 2, "🛡": "-15% входящего урона", "💰": 900, "🎁": ["Doom"]},
        "Blade Mail": {"🔄": "20% урона возвращается", "💰": 700, "🎁": ["Axe"]},
        "Vanguard": {"🛡": "-10% входящего урона", "💰": 600, "🎁": ["any"]},
        "Shiva's Guard": {"🍀": 3, "❄️": "уменьшает урон босса", "💰": 1200, "🎁": ["Invoker"]},
        "Heart of Tarrasque": {"💪": 5, "❤️": "+20% наград с рейда", "💰": 1500, "🎁": ["Roshan Prime"]},
    },
    # 👢 БОТИНКИ
    "boots": {
        "Power Treads": {"🔀": "+3 Сила или +3 Удача", "💰": 600, "🎁": ["any"]},
        "Boots of Travel": {"⏱": "нет кулдаунов на рейд-удар", "💰": 1200, "🎁": ["Zeus"]},
        "Phase Boots": {"💪": 2, "⚡": "+урон", "💰": 700, "🎁": ["any"]},
    },
    # 💍 АРТЕФАКТЫ
    "artifacts": {
        "Black King Bar": {"🛡": "иммунитет к эффектам (1 раз/день)", "💰": 1000, "🎁": ["Doom"]},
        "Scythe of Vyse": {"🛑": "15% шанс оглушить босса", "💰": 1100, "🎁": ["Invoker"]},
        "Aghanim's Scepter": {"⭐": "+1 к любой стате", "🧠": "уникальный бонус", "💰": 1500, "🎁": ["Roshan Prime"]},
    },
    # 🍀 УТИЛИТА
    "utility": {
        "Hand of Midas": {"⭐": "+25% EXP", "💰": 700, "🎁": ["Shadow Fiend"]},
        "Blink Dagger": {"⚡": "первый удар x2", "💰": 650, "🎁": ["Pudge"]},
    },
    # 🧿 РЕЛИКТЫ
    "relics": {
        "Aegis of the Immortal": {"☠️": "спасает от поражения", "⚠️": "одноразовый", "💰": 0, "🎁": ["Roshan"]},
        "Cheese": {"🎁": "удваивает награду рейда", "💰": 0, "🎁": ["Roshan"]},
    }
}

def get_all_items():
    """Возвращает все предметы в виде плоского словаря"""
    all_items = {}
    for category in items.values():
        all_items.update(category)
    return all_items

def get_item_info(item_name):
    """Получить информацию о предмете"""
    all_items = get_all_items()
    return all_items.get(item_name)

def format_item_description(item_name, item_data):
    """Форматировать описание предмета"""
    desc = f"**{item_name}**\n"
    for key, value in item_data.items():
        if key == "💰":
            desc += f"💰 Цена: {value} MMR\n"
        elif key == "🎁":
            desc += f"🎁 Дроп: {', '.join(value)}\n"
        else:
            desc += f"{key}: {value}\n"
    return desc
