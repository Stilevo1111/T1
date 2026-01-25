#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Новая система рейдов для Fissure Bot - СОВМЕСТНОЕ УБИЙСТВО БОССОВ
Простая и надежная реализация без сложных зависимостей
"""

import time
import random
from typing import Dict, List, Tuple
from raid_manager import raid_manager

# Конфигурация рейдов
RAID_COOLDOWN = 3600  # 1 час в секундах
PLAYER_DEATH_COOLDOWN = 7200  # 2 часа оглушение после смерти
BOSS_RESET_TIME = 3600  # 1 час возрождение босса

# Список боссов с большим HP для совместного убийства
BOSSES = [
    {
        "name": "Roshan",
        "max_hp": 1000,
        "damage_range": (25, 40),
        "loot": ["Daedalus", "Aegis of the Immortal", "Cheese", "Radiance"],
        "exp_reward": 100,
        "description": "Древний страж подземелий"
    },
    {
        "name": "Ancient Dragon",
        "max_hp": 1500,
        "damage_range": (30, 50),
        "loot": ["Dragon Scale", "Fire Sword", "Dragon Heart", "Dragon Claw"],
        "exp_reward": 150,
        "description": "Огненный дракон древности"
    },
    {
        "name": "Ice Titan",
        "max_hp": 2000,
        "damage_range": (35, 55),
        "loot": ["Frost Blade", "Ice Shield", "Titan's Helm", "Frost Heart"],
        "exp_reward": 200,
        "description": "Ледяной великан севера"
    },
    {
        "name": "Shadow Demon",
        "max_hp": 1200,
        "damage_range": (40, 60),
        "loot": ["Shadow Dagger", "Demon Cloak", "Soul Stone", "Demon Heart"],
        "exp_reward": 120,
        "description": "Теневой демон из преисподней"
    },
    {
        "name": "Fire Elemental",
        "max_hp": 800,
        "damage_range": (20, 45),
        "loot": ["Fire Staff", "Elemental Orb", "Flame Ring", "Fire Core"],
        "exp_reward": 80,
        "description": "Огненный элементаль пустыни"
    },
    {
        "name": "Thunder God",
        "max_hp": 2500,
        "damage_range": (50, 75),
        "loot": ["Thunder Hammer", "Lightning Rod", "Storm Crown", "Thunder Heart"],
        "exp_reward": 250,
        "description": "Бог грома и молний"
    }
]

def get_current_boss() -> Dict:
    """Получить текущего босса через менеджер"""
    return raid_manager.get_current_boss_info()

def calculate_player_stats(user_data: Dict) -> Dict:
    """Рассчитать боевые характеристики игрока"""
    base_damage = 20
    base_hp = 100
    
    # Базовые характеристики от fissure
    fissure_bonus = user_data.get("fissure", 10.0) * 2
    hp_bonus = int(user_data.get("chat_mmr", 100) / 10)
    
    # Статы игрока
    stats = user_data.get("stats", {})
    strength = stats.get("strength", 0)
    agility = stats.get("agility", 0)
    intelligence = stats.get("intelligence", 0)
    
    # Итоговые характеристики
    total_damage = base_damage + fissure_bonus + (strength * 2)
    total_hp = base_hp + hp_bonus + (strength * 5)
    crit_chance = 5 + (agility // 2)
    evasion = 5 + (agility // 3)
    armor = intelligence // 2
    
    return {
        "damage": max(1, total_damage),
        "hp": max(1, total_hp),
        "crit_chance": min(95, crit_chance),
        "evasion": min(50, evasion),
        "armor": max(0, armor)
    }

def simulate_raid_attack(user_data: Dict, boss: Dict, boss_current_hp: int) -> Tuple[Dict, str]:
    """Симуляция атаки игрока на босса"""
    player_stats = calculate_player_stats(user_data)
    player_damage = player_stats["damage"]
    player_crit = player_stats["crit_chance"]
    player_evasion = player_stats["evasion"]
    player_defense = player_stats["armor"]
    
    boss_min_dmg, boss_max_dmg = boss["damage_range"]
    
    # Лог атаки
    attack_log = f"⚔️ АТАКА НА {boss['name'].upper()}!\n\n"
    attack_log += f"👤 ВАШИ ХАРАКТЕРИСТИКИ:\n"
    attack_log += f"  ⚔️ Урон: {int(player_damage)}\n"
    attack_log += f"  🎯 Крит: {player_crit}%\n"
    attack_log += f"  🛡 Уклонение: {player_evasion}%\n"
    attack_log += f"  🛡 Защита: {player_defense}\n\n"
    attack_log += f"👹 ХАРАКТЕРИСТИКИ БОССА:\n"
    attack_log += f"  ❤️ HP: {boss_current_hp}/{boss['max_hp']}\n"
    attack_log += f"  ⚔️ Урон: {boss_min_dmg}-{boss_max_dmg}\n\n"
    
    # Атака игрока
    is_crit = random.randint(1, 100) <= player_crit
    if is_crit:
        dmg = int(player_damage * 2)
        attack_log += f"💥 КРИТИЧЕСКИЙ удар! Нанесено {dmg} урона!\n"
    else:
        dmg = int(player_damage)
        attack_log += f"🗡 Нанесено {dmg} урона\n"
    
    new_boss_hp = max(0, boss_current_hp - dmg)
    attack_log += f"❤️ HP босса: {boss_current_hp} → {new_boss_hp}\n\n"
    
    # Ответный удар босса (если босс еще жив)
    if new_boss_hp > 0:
        if random.randint(1, 100) <= player_evasion:
            attack_log += f"🛡 Вы уклонились от атаки {boss['name']}! 🤸\n"
        else:
            boss_dmg = random.randint(boss_min_dmg, boss_max_dmg)
            # Учет защиты игрока
            final_boss_dmg = max(1, boss_dmg - player_defense)
            attack_log += f"👹 {boss['name']} контратакует и наносит {final_boss_dmg} урона\n"
    else:
        attack_log += f"🎉 БОСС ПОВАЛЕН!\n"
    
    result = {
        "damage_dealt": dmg,
        "boss_hp_after": new_boss_hp,
        "boss_hp_max": boss['max_hp'],
        "boss_was_killed": new_boss_hp == 0,
        "player_stats": player_stats
    }
    
    return result, attack_log

def get_raid_status() -> Dict:
    """Получить статус текущего рейда через менеджер"""
    boss_info = raid_manager.get_current_boss_info()
    return {
        "boss": boss_info,
        "current_hp": boss_info["current_hp"],
        "total_damage": 0,
        "killers": raid_manager.get_killers_info(),
        "last_reset": boss_info.get("last_reset", time.time())
    }

def format_raid_menu(user_data: Dict) -> str:
    """Сформировать текст меню рейда через менеджер"""
    return raid_manager.format_raid_status()

def handle_raid_button(user_data: Dict) -> str:
    """Обработка нажатия кнопки Рейды через менеджер"""
    return raid_manager.format_raid_status()

def handle_raid_attack(user_data: Dict) -> Tuple[str, Dict]:
    """Обработка команды /raid_attack через менеджер"""
    user_id = str(user_data.get("user_id", "unknown"))
    status = get_raid_status()
    boss = status["boss"]
    current_hp = status["current_hp"]
    
    # Проверка кулдауна после смерти
    now = time.time()
    last_death = user_data.get("last_raid_death", 0)
    death_remaining = PLAYER_DEATH_COOLDOWN - (now - last_death)
    
    if death_remaining > 0:
        remaining_hours = int(death_remaining / 3600)
        remaining_min = int((death_remaining % 3600) / 60)
        return f"💀 Вы оглушены после смерти!\nОсталось: {remaining_hours} ч. {remaining_min} мин.", {}
    
    # Проверка кулдауна атаки
    last_raid = user_data.get("last_raid", 0)
    raid_remaining = RAID_COOLDOWN - (now - last_raid)
    
    if raid_remaining > 0:
        remaining_min = int(raid_remaining / 60)
        return f"⏳ Следующая атака через {remaining_min} мин.", {}
    
    # Проводим атаку
    result, attack_log = simulate_raid_attack(user_data, boss, current_hp)
    
    # Обновляем данные пользователя
    user_data["last_raid"] = now
    
    # Обновляем данные в менеджере рейдов
    attack_result = raid_manager.attack_boss(user_id, result["damage_dealt"])
    
    if attack_result["boss_was_killed"]:
        # Босс убит - начисляем награду
        exp_reward = boss["exp_reward"]
        user_data["chat_mmr"] = user_data.get("chat_mmr", 100) + exp_reward
        
        # Шанс дропа лута (50%)
        drop_item = None
        if random.randint(1, 100) <= 50:
            available_loot = boss["loot"]
            drop_item = random.choice(available_loot)
            if "inventory" not in user_data:
                user_data["inventory"] = []
            user_data["inventory"].append(drop_item)
        
        attack_log += f"\n🎉 БОСС ПОВАЛЕН!\n"
        attack_log += f"💰 Получено: {exp_reward} MMR\n"
        if drop_item:
            attack_log += f"🎁 Выпал предмет: {drop_item}!\n"
        else:
            attack_log += f"🎁 Предметы не выпали (шанс 50%)\n"
        attack_log += f"\n👹 БОСС ВОЗРОДИТСЯ ЧЕРЕЗ 1 ЧАС"
    else:
        # Босс еще жив
        attack_log += f"\n💥 Нанесено урона: {result['damage_dealt']}\n"
        attack_log += f"❤️ Осталось HP: {attack_result['boss_hp_after']}/{attack_result['boss_hp_max']}"
    
    return attack_log, attack_result

# Функции для работы с базой данных (заглушки для интеграции)
def get_boss_data() -> Dict:
    """Получить данные о текущем боссе из базы"""
    # В реальной системе: return db.get_raid_boss()
    return {
        "name": "Roshan",
        "max_hp": 1000,
        "current_hp": 1000,
        "damage_range": [25, 40],
        "loot": ["Daedalus", "Aegis of the Immortal", "Cheese"],
        "exp_reward": 100,
        "last_reset": time.time()
    }

def update_boss_hp(new_hp: int):
    """Обновить HP босса в базе данных"""
    # В реальной системе: db.update_raid_boss_hp(new_hp)
    pass

def add_damage_to_leaderboard(user_id: str, damage: int):
    """Добавить урон в таблицу лидеров"""
    # В реальной системе: db.add_raid_damage(user_id, damage)
    pass

def reset_boss_if_needed():
    """Сбросить босса если прошло достаточно времени"""
    # В реальной системе: проверка времени и сброс HP
    pass