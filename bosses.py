# bosses.py
bosses = [
    {"name": "Roshan", "HP": 8000, "damage": (25, 40), "effect": "10% крит", "loot": ["Daedalus", "Aegis of the Immortal", "Cheese"]},
    {"name": "Doom", "HP": 7000, "damage": (30, 45), "effect": "отключает предметы на 1 удар", "loot": ["Black King Bar", "Assault Cuirass"]},
    {"name": "Zeus", "HP": 9000, "damage": (20, 50), "effect": "каждые 3 хода удар по случайному игроку", "loot": ["Boots of Travel"]},
    {"name": "Axe", "HP": 6500, "damage": (35, 55), "effect": "контратакует", "loot": ["Blade Mail"]},
    {"name": "Shadow Fiend", "HP": 6000, "damage": (25, 45), "effect": "ворует EXP", "loot": ["Hand of Midas"]},
    {"name": "Invoker", "HP": 7500, "damage": (20, 40), "effect": "случайные эффекты", "loot": ["Scythe of Vyse"]},
    {"name": "Roshan Prime", "HP": 12000, "damage": (50, 80), "effect": "ярость <30% HP", "loot": ["Divine Rapier"]}
]

def get_boss_by_name(name):
    """Получить босса по имени"""
    for boss in bosses:
        if boss["name"] == name:
            return boss.copy()  # возвращаем копию чтобы не изменять оригинал
    return None

def get_random_boss():
    """Получить случайного босса"""
    import random
    return random.choice(bosses).copy()

def format_boss_info(boss):
    """Форматировать информацию о боссе"""
    return (
        f"👹 **{boss['name']}**\n"
        f"❤️ HP: {boss['HP']}\n"
        f"⚔️ Урон: {boss['damage'][0]}-{boss['damage'][1]}\n"
        f"💫 Эффект: {boss['effect']}\n"
        f"🎁 Лут: {', '.join(boss['loot'])}"
    )
