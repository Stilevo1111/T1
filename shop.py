# shop.py
from items import items

def buy_item(player, slot, item_name):
    for category in items:
        if item_name in items[category]:
            cost = items[category][item_name]["💰"]
            if player.mmr >= cost:
                player.mmr -= cost
                player.equip(slot, item_name)
                print(f"{player.name} купил {item_name} за {cost} MMR")
                return True
            else:
                print(f"{player.name} не хватает MMR для {item_name}")
                return False
    print(f"Предмет {item_name} не найден")
    return False
