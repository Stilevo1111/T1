#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Менеджер рейдов для Fissure Bot
Управление боссами, таблицей лидеров и возрождением
"""

import time
import json
from typing import Dict, List, Tuple
from raid_system import BOSSES, BOSS_RESET_TIME

# Файл для хранения данных рейдов
RAID_DATA_FILE = "raid_data.json"

class RaidManager:
    def __init__(self):
        self.raid_data = self.load_raid_data()
    
    def load_raid_data(self) -> Dict:
        """Загрузить данные рейдов из файла"""
        try:
            with open(RAID_DATA_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except FileNotFoundError:
            return self.get_default_raid_data()
        except json.JSONDecodeError:
            return self.get_default_raid_data()
    
    def save_raid_data(self):
        """Сохранить данные рейдов в файл"""
        try:
            with open(RAID_DATA_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.raid_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Ошибка сохранения данных рейдов: {e}")
    
    def get_default_raid_data(self) -> Dict:
        """Получить стандартные данные рейдов"""
        return {
            "current_boss": 0,  # Индекс текущего босса
            "boss_hp": BOSSES[0]["max_hp"],
            "boss_max_hp": BOSSES[0]["max_hp"],
            "last_reset": time.time(),
            "leaderboard": {},  # {user_id: damage}
            "killers": []  # Список ID убийц
        }
    
    def get_current_boss_info(self) -> Dict:
        """Получить информацию о текущем боссе"""
        boss_index = self.raid_data["current_boss"]
        boss = BOSSES[boss_index].copy()
        boss["current_hp"] = self.raid_data["boss_hp"]
        boss["max_hp"] = self.raid_data["boss_max_hp"]
        return boss
    
    def attack_boss(self, user_id: str, damage: int) -> Dict:
        """Атака на босса"""
        current_hp = self.raid_data["boss_hp"]
        new_hp = max(0, current_hp - damage)
        
        # Обновляем HP босса
        self.raid_data["boss_hp"] = new_hp
        
        # Добавляем урон в таблицу лидеров
        if user_id not in self.raid_data["leaderboard"]:
            self.raid_data["leaderboard"][user_id] = 0
        self.raid_data["leaderboard"][user_id] += damage
        
        # Проверяем убийство
        boss_was_killed = new_hp == 0
        if boss_was_killed:
            # Добавляем убийцу
            if user_id not in self.raid_data["killers"]:
                self.raid_data["killers"].append(user_id)
        
        # Сохраняем изменения
        self.save_raid_data()
        
        return {
            "damage_dealt": damage,
            "boss_hp_after": new_hp,
            "boss_hp_max": self.raid_data["boss_max_hp"],
            "boss_was_killed": boss_was_killed,
            "current_leaderboard": self.get_leaderboard()
        }
    
    def reset_boss_if_needed(self) -> bool:
        """Сбросить босса если прошло достаточно времени"""
        now = time.time()
        last_reset = self.raid_data["last_reset"]
        
        if now - last_reset >= BOSS_RESET_TIME:
            # Следующий босс
            current_boss_index = self.raid_data["current_boss"]
            next_boss_index = (current_boss_index + 1) % len(BOSSES)
            
            # Обновляем данные
            self.raid_data["current_boss"] = next_boss_index
            self.raid_data["boss_hp"] = BOSSES[next_boss_index]["max_hp"]
            self.raid_data["boss_max_hp"] = BOSSES[next_boss_index]["max_hp"]
            self.raid_data["last_reset"] = now
            self.raid_data["leaderboard"] = {}
            self.raid_data["killers"] = []
            
            self.save_raid_data()
            return True
        
        return False
    
    def get_leaderboard(self, limit: int = 10) -> List[Tuple[str, int]]:
        """Получить таблицу лидеров"""
        leaderboard = self.raid_data["leaderboard"]
        sorted_leaderboard = sorted(leaderboard.items(), key=lambda x: x[1], reverse=True)
        return sorted_leaderboard[:limit]
    
    def get_killers_info(self) -> List[str]:
        """Получить список убийц босса"""
        return self.raid_data["killers"]
    
    def format_raid_status(self) -> str:
        """Форматировать статус рейда для вывода"""
        boss_info = self.get_current_boss_info()
        current_hp = boss_info["current_hp"]
        max_hp = boss_info["max_hp"]
        hp_percent = (current_hp / max_hp) * 100
        
        text = "👹 РЕЙД НА БОССОВ\n\n"
        text += f"👹 ТЕКУЩИЙ БОСС: **{boss_info['name']}**\n"
        text += f"📜 Описание: {boss_info['description']}\n\n"
        text += f"❤️ HP: {current_hp}/{max_hp} ({hp_percent:.1f}%)\n"
        text += f"⚔️ Урон: {boss_info['damage_range'][0]}-{boss_info['damage_range'][1]}\n\n"
        text += f"🎁 НАГРАДА ЗА УБИЙСТВО:\n"
        text += f"  💰 Опыт: {boss_info['exp_reward']} MMR\n"
        text += f"  🎁 Лут: {', '.join(boss_info['loot'])}\n\n"
        text += f"Атаковать: /raid_attack"
        
        return text
    
    def format_leaderboard(self) -> str:
        """Форматировать таблицу лидеров для вывода"""
        leaderboard = self.get_leaderboard()
        if not leaderboard:
            return "📊 Таблица лидеров пуста"
        
        text = "📊 ТАБЛИЦА ЛИДЕРОВ РЕЙДОВ\n\n"
        for i, (user_id, damage) in enumerate(leaderboard, 1):
            text += f"{i}. Игрок {user_id[-4:]}: {damage} урона\n"
        
        return text

# Глобальный экземпляр менеджера рейдов
raid_manager = RaidManager()

# Функции для интеграции с ботом
def get_raid_status() -> Dict:
    """Получить статус текущего рейда"""
    return raid_manager.get_current_boss_info()

def attack_boss(user_id: str, damage: int) -> Dict:
    """Атаковать босса"""
    return raid_manager.attack_boss(user_id, damage)

def reset_boss_if_needed() -> bool:
    """Сбросить босса если нужно"""
    return raid_manager.reset_boss_if_needed()

def format_raid_menu() -> str:
    """Получить меню рейдов"""
    return raid_manager.format_raid_status()

def format_leaderboard() -> str:
    """Получить таблицу лидеров"""
    return raid_manager.format_leaderboard()

def get_killers_info() -> List[str]:
    """Получить информацию об убийцах"""
    return raid_manager.get_killers_info()