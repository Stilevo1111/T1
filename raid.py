# raid.py
import random
from bosses import bosses

def raid(players, boss_index=0):
    if boss_index >= len(bosses):
        boss_index = 0
    boss = bosses[boss_index].copy()
    boss_hp = boss["HP"]
    print(f"🎯 На рейде: {boss['name']} (HP: {boss_hp})")
    
    rounds = 0
    while boss_hp > 0 and any(p.hp > 0 for p in players):
        # Игроки наносят урон
        for player in players:
            if player.hp <= 0:
                continue
            dmg, crit = player.calculate_damage()
            boss_hp -= dmg
        # Босс наносит урон игрокам
        for player in players:
            if player.hp <= 0:
                continue
            dmg_to_player = random.randint(*boss["damage"])
            taken = player.take_damage(dmg_to_player)
            print(f"{boss['name']} наносит {taken} урона {player.name} (HP: {player.hp})")
        rounds += 1

    # Распределение лута
    players_sorted = sorted(players, key=lambda x: x.damage_done, reverse=True)
    loot = boss["loot"]
    for i, player in enumerate(players_sorted):
        if i < len(loot):
            print(f"{player.name} нанес {player.damage_done} урона и получает: {loot[i]}")
            # экипируем в свободный слот
            if player.items["weapon"] is None:
                player.equip("weapon", loot[i])
            elif player.items["artifact"] is None:
                player.equip("artifact", loot[i])
        else:
            print(f"{player.name} нанес {player.damage_done} урона и получает: ничего")
    for player in players:
        player.damage_done = 0

    print(f"🔥 Босс {boss['name']} побежден! Новый босс появляется.")
    return (boss_index + 1) % len(bosses)
