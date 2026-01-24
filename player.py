# player.py
import random
from items import items

class Player:
    def __init__(self, name, mmr=1000, hp=1000):
        self.name = name
        self.mmr = mmr
        self.exp = 0
        self.hp = hp
        self.items = {"weapon": None, "armor": None, "boots": None, "artifact": None, "utility": None, "relic": None}
        self.damage_done = 0

    def equip(self, slot, item_name):
        self.items[slot] = item_name

    def calculate_damage(self):
        base = random.randint(1, 10)
        bonus = 0
        crit = False
        weapon = self.items.get("weapon")
        if weapon and weapon in items["weapons"]:
            bonus += items["weapons"][weapon]["💪"]
            if "🎯" in items["weapons"][weapon] and random.randint(1,100) <= 20:
                base *= 2
                crit = True
        total = base + bonus
        self.damage_done += total
        return total, crit

    def take_damage(self, dmg):
        armor = self.items.get("armor")
        if armor and armor in items["armor"] and "🛡" in items["armor"][armor]:
            reduction = int(dmg * 0.15)
            dmg -= reduction
        self.hp -= dmg
        return dmg
