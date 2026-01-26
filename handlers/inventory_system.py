"""Система инвентаря и экипировки"""

import logging
from typing import Dict, Any, List, Optional, Tuple

from database.real_database import db_manager

logger = logging.getLogger(__name__)

class InventoryManager:
    """Менеджер инвентаря и экипировки"""
    
    def __init__(self):
        # Определение типов предметов и их слотов
        self.item_slots = {
            'boots_of_speed': 'boots',
            'phase_boots': 'boots',
            'power_treads': 'boots',
            'arcane_boots': 'boots',
            'ring_of_protection': 'ring',
            'vanguard': 'offhand',
            'stout_shield': 'offhand',
            'blademail': 'offhand',
            'quelling_blade': 'weapon',
            'daedalus': 'weapon',
            'dagon': 'weapon',
            'monkey_king_bar': 'weapon',
            'ring_of_basilius': 'ring',
            'aghanims_scepter': 'offhand',
            'force_staff': 'offhand',
            'glimmer_cape': 'cloak',
            'healing_salve': 'consumable',
            'clarity_potion': 'consumable',
            'invisibility_potion': 'consumable',
            'speed_potion': 'consumable'
        }
        
        # Ограничения слотов
        self.slot_limits = {
            'boots': 1,
            'ring': 2,  # Можно носить 2 кольца
            'offhand': 1,
            'weapon': 1,
            'cloak': 1,
            'consumable': 99  # Ограничение на стаки
        }
    
    async def add_item(self, user_id: int, item_id: str, quantity: int = 1) -> bool:
        """Добавление предмета в инвентарь"""
        if item_id not in self.item_slots:
            return False
        
        # Проверяем ограничения слотов для не-расходников
        if self.item_slots[item_id] != 'consumable':
            current_equipped = await self.get_equipped_items(user_id)
            slot_type = self.item_slots[item_id]
            
            # Считаем количество уже экипированных предметов в этом слоте
            equipped_count = sum(1 for item in current_equipped if self.item_slots.get(item, '') == slot_type)
            
            if equipped_count >= self.slot_limits[slot_type]:
                return False  # Превышено количество слотов
        
        return await db_manager.add_item_to_inventory(user_id, item_id, quantity)
    
    async def equip_item(self, user_id: int, item_id: str) -> bool:
        """Экипировка предмета"""
        inventory = await db_manager.get_user_inventory(user_id)
        
        # Проверяем, есть ли предмет в инвентаре
        item_found = False
        for item in inventory:
            if item['item_id'] == item_id and item['quantity'] > 0:
                item_found = True
                break
        
        if not item_found:
            return False
        
        slot_type = self.item_slots.get(item_id)
        if not slot_type:
            return False
        
        # Снимаем предметы с того же слота
        await self._unequip_slot(user_id, slot_type)
        
        # Экипируем новый предмет
        with db_manager.get_connection() as conn:
            try:
                conn.execute("""
                    UPDATE inventory SET equipped = 1 
                    WHERE user_id = ? AND item_id = ?
                """, (user_id, item_id))
                conn.commit()
                return True
            except Exception as e:
                logger.error(f"Ошибка при экипировке предмета: {e}")
                return False
    
    async def unequip_item(self, user_id: int, item_id: str) -> bool:
        """Снятие предмета"""
        with db_manager.get_connection() as conn:
            try:
                conn.execute("""
                    UPDATE inventory SET equipped = 0 
                    WHERE user_id = ? AND item_id = ?
                """, (user_id, item_id))
                conn.commit()
                return True
            except Exception as e:
                logger.error(f"Ошибка при снятии предмета: {e}")
                return False
    
    async def _unequip_slot(self, user_id: int, slot_type: str) -> bool:
        """Снятие всех предметов с определенного слота"""
        with db_manager.get_connection() as conn:
            try:
                # Получаем все предметы в этом слоте
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT item_id FROM inventory 
                    WHERE user_id = ? AND equipped = 1
                """, (user_id,))
                
                equipped_items = [row[0] for row in cursor.fetchall()]
                
                # Снимаем предметы, которые используют этот слот
                for item_id in equipped_items:
                    if self.item_slots.get(item_id) == slot_type:
                        conn.execute("""
                            UPDATE inventory SET equipped = 0 
                            WHERE user_id = ? AND item_id = ?
                        """, (user_id, item_id))
                
                conn.commit()
                return True
            except Exception as e:
                logger.error(f"Ошибка при снятии слота: {e}")
                return False
    
    async def get_inventory(self, user_id: int) -> List[Dict[str, Any]]:
        """Получение полного инвентаря"""
        inventory = await db_manager.get_user_inventory(user_id)
        
        # Добавляем информацию о предметах
        for item in inventory:
            item['slot'] = self.item_slots.get(item['item_id'], 'unknown')
            item['is_equipped'] = bool(item.get('equipped', 0))
        
        return inventory
    
    async def get_equipped_items(self, user_id: int) -> List[str]:
        """Получение списка экипированных предметов"""
        inventory = await db_manager.get_user_inventory(user_id)
        return [item['item_id'] for item in inventory if item.get('equipped', 0)]
    
    async def use_consumable(self, user_id: int, item_id: str) -> Dict[str, Any]:
        """Использование расходного предмета"""
        if self.item_slots.get(item_id) != 'consumable':
            return {'success': False, 'message': 'Это не расходный предмет'}
        
        inventory = await db_manager.get_user_inventory(user_id)
        
        # Находим предмет в инвентаре
        item_found = None
        for item in inventory:
            if item['item_id'] == item_id and item['quantity'] > 0:
                item_found = item
                break
        
        if not item_found:
            return {'success': False, 'message': 'Предмет не найден в инвентаре'}
        
        # Используем предмет
        with db_manager.get_connection() as conn:
            try:
                # Уменьшаем количество
                conn.execute("""
                    UPDATE inventory SET quantity = quantity - 1
                    WHERE user_id = ? AND item_id = ? AND quantity > 0
                """, (user_id, item_id))
                
                # Если количество стало 0, удаляем запись
                conn.execute("""
                    DELETE FROM inventory 
                    WHERE user_id = ? AND item_id = ? AND quantity <= 0
                """, (user_id, item_id))
                
                conn.commit()
                
                # Применяем эффект предмета
                effect = await self._apply_consumable_effect(user_id, item_id)
                
                return {
                    'success': True,
                    'item_id': item_id,
                    'effect': effect
                }
            except Exception as e:
                logger.error(f"Ошибка при использовании расходника: {e}")
                return {'success': False, 'message': 'Ошибка при использовании предмета'}
    
    async def _apply_consumable_effect(self, user_id: int, item_id: str) -> Dict[str, Any]:
        """Применение эффекта расходного предмета"""
        effects = {
            'healing_salve': {'heal': 150, 'duration': 0},
            'clarity_potion': {'mana': 200, 'duration': 0},
            'invisibility_potion': {'invis': 1, 'duration': 30},
            'speed_potion': {'speed_boost': 50, 'duration': 60}
        }
        
        effect = effects.get(item_id, {})
        
        if 'heal' in effect:
            # Лечение
            user = await db_manager.get_user(user_id)
            max_hp = user.get('max_hp', 1000)
            current_hp = user.get('hp', 500)
            
            new_hp = min(max_hp, current_hp + effect['heal'])
            await db_manager.update_user(user_id, {'hp': new_hp})
            
            return {'type': 'heal', 'amount': effect['heal'], 'new_hp': new_hp}
        
        elif 'mana' in effect:
            # Восстановление маны
            user = await db_manager.get_user(user_id)
            max_mana = user.get('max_mana', 200)
            current_mana = user.get('mana', 100)
            
            new_mana = min(max_mana, current_mana + effect['mana'])
            await db_manager.update_user(user_id, {'mana': new_mana})
            
            return {'type': 'mana', 'amount': effect['mana'], 'new_mana': new_mana}
        
        elif 'invis' in effect:
            # Невидимость (временно)
            return {'type': 'invisibility', 'duration': effect['duration']}
        
        elif 'speed_boost' in effect:
            # Увеличение скорости (временно)
            return {'type': 'speed_boost', 'amount': effect['speed_boost'], 'duration': effect['duration']}
        
        return {'type': 'unknown', 'message': 'Неизвестный эффект'}
    
    async def get_item_stats(self, item_id: str) -> Dict[str, Any]:
        """Получение статистики предмета"""
        item_stats = {
            'boots_of_speed': {'speed': 20},
            'phase_boots': {'agi': 15, 'speed': 10},
            'power_treads': {'str': 10, 'agi': 10},
            'arcane_boots': {'int': 15, 'mana': 100},
            'ring_of_protection': {'armor': 5},
            'vanguard': {'hp': 300, 'block': 20},
            'stout_shield': {'armor': 10, 'block': 15},
            'blademail': {'armor': 15, 'reflect': 25},
            'quelling_blade': {'damage': 15},
            'daedalus': {'damage': 80, 'crit': 25},
            'dagon': {'int': 50, 'spell_damage': 30},
            'monkey_king_bar': {'damage': 60, 'agi': 30},
            'ring_of_basilius': {'int': 10, 'mana_regen': 5},
            'aghanims_scepter': {'int': 50, 'spell_power': 20},
            'force_staff': {'int': 20, 'mana': 200},
            'glimmer_cape': {'agi': 25, 'invis': 1},
            'healing_salve': {'heal': 150},
            'clarity_potion': {'mana': 200},
            'invisibility_potion': {'invis_time': 30},
            'speed_potion': {'speed': 50, 'duration': 60}
        }
        
        return item_stats.get(item_id, {})
    
    async def get_inventory_summary(self, user_id: int) -> Dict[str, Any]:
        """Получение сводки по инвентарю"""
        inventory = await self.get_inventory(user_id)
        
        summary = {
            'total_items': len(inventory),
            'equipped_items': [],
            'consumables': [],
            'equipment': [],
            'slot_usage': {}
        }
        
        for item in inventory:
            item_info = {
                'id': item['item_id'],
                'quantity': item['quantity'],
                'equipped': item['is_equipped'],
                'slot': item['slot']
            }
            
            if item['is_equipped']:
                summary['equipped_items'].append(item_info)
            elif item['slot'] == 'consumable':
                summary['consumables'].append(item_info)
            else:
                summary['equipment'].append(item_info)
            
            # Считаем использование слотов
            slot = item['slot']
            if slot != 'consumable':
                if slot not in summary['slot_usage']:
                    summary['slot_usage'][slot] = 0
                if item['is_equipped']:
                    summary['slot_usage'][slot] += 1
        
        return summary

# Глобальный экземпляр менеджера инвентаря
inventory_manager = InventoryManager()

# Функция для регистрации обработчиков инвентаря
def register_inventory_handlers(application):
    """Регистрация обработчиков инвентарной системы"""
    # Здесь можно добавить обработчики команд инвентаря
    pass

__all__ = ['InventoryManager', 'inventory_manager', 'register_inventory_handlers']
