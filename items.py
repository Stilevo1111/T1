"""Система предметов для бота Fissure"""

# Словарь предметов с их характеристиками
items = {
    "weapons": {
        "Daedalus": {
            "💪": 3,  # +3 к силе
            "🎯": 5,  # +5% к криту
            "💰": 100,
            "🎁": "Случайный предмет"
        },
        "Mjolnir": {
            "💪": 5,  # +5 к силе
            "🛡": 2,  # +2 к броне
            "💰": 150,
            "🎁": "Энергия"
        },
        "Excalibur": {
            "💪": 4,  # +4 к силе
            "🤸": 3,  # +3% к уклонению
            "💰": 120,
            "🎁": "Опыт"
        }
    },
    "armor": {
        "Dragon Scale": {
            "🛡": 5,  # +5 к броне
            "💪": 2,  # +2 к силе
            "💰": 80,
            "🎁": "Здоровье"
        },
        "Shadow Cloak": {
            "🤸": 8,  # +8% к уклонению
            "💪": 1,  # +1 к силе
            "💰": 90,
            "🎁": "Скорость"
        },
        "Titanium Plate": {
            "🛡": 8,  # +8 к броне
            "💪": 3,  # +3 к силе
            "💰": 110,
            "🎁": "Щит"
        }
    },
    "boots": {
        "Winged Boots": {
            "🤸": 10,  # +10% к уклонению
            "💪": 1,   # +1 к силе
            "💰": 60,
            "🎁": "Полет"
        },
        "Boots of Speed": {
            "🤸": 6,   # +6% к уклонению
            "💪": 2,   # +2 к силе
            "💰": 70,
            "🎁": "Ускорение"
        },
        "Iron Boots": {
            "💪": 3,   # +3 к силе
            "🛡": 3,   # +3 к броне
            "💰": 65,
            "🎁": "Стабильность"
        }
    },
    "artifacts": {
        "Amulet of Power": {
            "💪": 4,   # +4 к силе
            "💰": 100,
            "🎁": "Сила"
        },
        "Ring of Agility": {
            "🤸": 12,  # +12% к уклонению
            "💰": 95,
            "🎁": "Ловкость"
        },
        "Crown of Intellect": {
            "💪": 2,   # +2 к силе
            "🛡": 2,   # +2 к броне
            "💰": 130,
            "🎁": "Мудрость"
        }
    },
    "utility": {
        "Health Potion": {
            "💪": 1,   # +1 к силе
            "💰": 20,
            "🎁": "Полное восстановление HP"
        },
        "Energy Drink": {
            "💪": 2,   # +2 к силе
            "💰": 25,
            "🎁": "Энергия на 1 час"
        },
        "Lucky Charm": {
            "🎯": 10,  # +10% к криту
            "💰": 50,
            "🎁": "Удача"
        },
        "Training Manual": {
            "💪": 3,   # +3 к силе
            "💰": 40,
            "🎁": "Опыт"
        }
    }
}

def get_all_items():
    """Получить все предметы"""
    all_items = {}
    for category, category_items in items.items():
        all_items.update(category_items)
    return all_items

def get_item_info(item_name):
    """Получить информацию о предмете"""
    all_items = get_all_items()
    return all_items.get(item_name)

def format_item_description(item_name, item_data):
    """Форматировать описание предмета"""
    description = f"**{item_name}**\n"
    for key, value in item_data.items():
        if key == "💰":
            description += f"  💰 {value} MMR\n"
        elif key == "🎁":
            description += f"  🎁 {value}\n"
        else:
            description += f"  {key}: {value}\n"
    return description

def format_boss_info(boss):
    """Форматировать информацию о боссе"""
    return (
        f"**{boss['name']}**\n"
        f"HP: {boss['HP']}\n"
        f"Урон: {boss['damage'][0]}-{boss['damage'][1]}\n"
        f"Эффект: {boss['effect']}\n"
        f"Лут: {', '.join(boss['loot'])}"
    )

def get_boss_by_name(name):
    """Получить босса по имени"""
    for boss in bosses:
        if boss['name'] == name:
            return boss
    return None

def get_random_boss():
    """Получить случайного босса"""
    return random.choice(bosses)

# Список боссов
bosses = [
    {
        "name": "Голем",
        "HP": 100,
        "damage": [10, 15],
        "effect": "Медленный",
        "loot": ["Dragon Scale", "Health Potion", "Training Manual"]
    },
    {
        "name": "Дракон",
        "HP": 150,
        "damage": [15, 25],
        "effect": "Огненное дыхание",
        "loot": ["Mjolnir", "Amulet of Power", "Energy Drink"]
    },
    {
        "name": "Тень",
        "HP": 80,
        "damage": [20, 30],
        "effect": "Невидимость",
        "loot": ["Shadow Cloak", "Ring of Agility", "Lucky Charm"]
    },
    {
        "name": "Гидра",
        "HP": 200,
        "damage": [12, 18],
        "effect": "Регенерация",
        "loot": ["Excalibur", "Crown of Intellect", "Winged Boots"]
    },
    {
        "name": "Левиафан",
        "HP": 250,
        "damage": [18, 28],
        "effect": "Затопление",
        "loot": ["Titanium Plate", "Boots of Speed", "Iron Boots"]
    }
]

if __name__ == "__main__":
    print("Items module loaded successfully")