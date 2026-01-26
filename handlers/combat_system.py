"""Система боев и экономики"""

import logging
import random
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import ContextTypes

from database.real_database import db_manager
from game_logic.level_system import CharacterStats

logger = logging.getLogger(__name__)

class CombatSystem:
    """Система боев и экономики"""
    
    def __init__(self):
        # Определение боссов
        self.bosses_db = {
            'rat_king': {
                'name': 'Крысиный Король',
                'level': 1,
                'hp': 500,
                'damage': 30,
                'armor': 2,
                'exp_reward': 50,
                'gold_reward': 25,
                'rarity': 'common'
            },
            'spider_queen': {
                'name': 'Королева Пауков',
                'level': 2,
                'hp': 800,
                'damage': 45,
                'armor': 3,
                'exp_reward': 80,
                'gold_reward': 40,
                'rarity': 'common'
            },
            'zombie_lord': {
                'name': 'Повелитель Зомби',
                'level': 2,
                'hp': 1000,
                'damage': 40,
                'armor': 4,
                'exp_reward': 75,
                'gold_reward': 35,
                'rarity': 'common'
            },
            'bat_swarm': {
                'name': 'Рой Летучих Мыши',
                'level': 1,
                'hp': 300,
                'damage': 25,
                'armor': 1,
                'exp_reward': 30,
                'gold_reward': 15,
                'rarity': 'common'
            },
            'fire_dragon': {
                'name': 'Огненный Дракон',
                'level': 10,
                'hp': 5000,
                'damage': 200,
                'armor': 20,
                'exp_reward': 500,
                'gold_reward': 250,
                'rarity': 'epic'
            },
            'death_knight': {
                'name': 'Рыцарь Смерти',
                'level': 8,
                'hp': 3500,
                'damage': 150,
                'armor': 15,
                'exp_reward': 350,
                'gold_reward': 175,
                'rarity': 'rare'
            },
            'thunder_god': {
                'name': 'Бог Грома',
                'level': 7,
                'hp': 3000,
                'damage': 180,
                'armor': 12,
                'exp_reward': 300,
                'gold_reward': 150,
                'rarity': 'rare'
            },
            'blood_demon': {
                'name': 'Кровавый Демон',
                'level': 6,
                'hp': 2500,
                'damage': 160,
                'armor': 10,
                'exp_reward': 250,
                'gold_reward': 125,
                'rarity': 'rare'
            }
        }
    
    async def attack_boss(self, user_id: int, boss_type: str) -> Dict[str, Any]:
        """Атака на босса"""
        user = await db_manager.get_user(user_id)
        if not user:
            return {'success': False, 'message': 'Пользователь не найден'}
        
        if boss_type not in self.bosses_db:
            return {'success': False, 'message': 'Босс не найден'}
        
        boss_data = self.bosses_db[boss_type]
        
        # Проверяем уровень пользователя
        user_level = user.get('level', 1)
        if user_level < boss_data['level']:
            return {'success': False, 'message': f'Требуется уровень {boss_data["level"]}'}
        
        # Получаем характеристики персонажа
        user_stats = await CharacterStats.get_full_character_stats(user_id)
        
        # Симуляция боя
        fight_result = await self._simulate_boss_fight(user_id, user_stats, boss_data)
        
        if not fight_result['success']:
            return fight_result
        
        # Обновляем статистику
        await self._update_boss_stats(user_id, fight_result)
        
        return fight_result

async def handle_attack_boss(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик атаки на босса"""
    try:
        user_id = update.effective_user.id
        boss_type = context.args[0] if context.args else None
        
        if not boss_type:
            await update.message.reply_text("Укажите тип босса")
            return
        
        result = await combat_system.attack_boss(user_id, boss_type)
        
        if result['success']:
            if result['result'] == 'win':
                message = f"🎉 Победа над {result['boss_name']}!\n"
                message += f"📊 Раундов: {result['rounds']}\n"
                message += f"💰 Получено: {result['exp_gained']} опыта, {result['gold_gained']} золота"
                
                if result.get('level_up', {}).get('level_up'):
                    message += f"\n🔥 Повышение уровня! Теперь вы {result['level_up']['new_level']} уровня"
            else:
                message = f"💀 Поражение от {result['boss_name']}\n"
                message += f"📊 Раундов: {result['rounds']}\n"
                message += f"❤️ Выжившие HP: {result['user_hp']}"
            
            await update.message.reply_text(message)
        else:
            await update.message.reply_text(f"❌ {result['message']}")
    except Exception as e:
        logger.error(f"Ошибка в handle_attack_boss: {e}")
        await update.message.reply_text("❌ Произошла ошибка")

    async def _simulate_boss_fight(self, user_id: int, user_stats: Dict[str, Any], boss_data: Dict[str, Any]) -> Dict[str, Any]:
        """Симуляция боя с боссом"""
        user_hp = user_stats['hp']
        boss_hp = boss_data['hp']
        
        round_num = 0
        max_rounds = 100
        log = []
        
        while user_hp > 0 and boss_hp > 0 and round_num < max_rounds:
            round_num += 1
            
            # Атака пользователя
            damage = self._calculate_boss_damage(user_stats, boss_data)
            boss_hp -= damage
            log.append(f"Раунд {round_num}: Вы нанесли {damage} урона боссу")
            
            if boss_hp <= 0:
                break
            
            # Атака босса
            damage = self._calculate_boss_attack(boss_data, user_stats)
            user_hp -= damage
            log.append(f"Раунд {round_num}: Босс нанес вам {damage} урона")
        
        # Определение результата
        if boss_hp <= 0:
            # Победа
            exp_gained = boss_data['exp_reward']
            gold_gained = boss_data['gold_reward']
            
            # Бонус за низкое HP
            if user_hp <= user_stats['max_hp'] * 0.1:
                exp_gained = int(exp_gained * 1.5)
                gold_gained = int(gold_gained * 1.5)
                log.append("🔥 Бонус за героизм! (Низкое HP)")
            
            # Обновляем пользователя
            await db_manager.update_user(user_id, {
                'exp': user.get('exp', 0) + exp_gained,
                'gold': user.get('gold', 0) + gold_gained,
                'hp': max(1, user_hp),
                'bosses_killed': user.get('bosses_killed', 0) + 1,
                'total_damage_dealt': user.get('total_damage_dealt', 0) + (boss_data['hp'] - boss_hp),
                'total_damage_taken': user.get('total_damage_taken', 0) + (user_stats['hp'] - user_hp)
            })
            
            # Проверка повышения уровня
            level_up_result = await self._check_level_up(user_id, user.get('exp', 0), exp_gained)
            
            return {
                'success': True,
                'result': 'win',
                'boss_name': boss_data['name'],
                'exp_gained': exp_gained,
                'gold_gained': gold_gained,
                'rounds': round_num,
                'log': log,
                'user_hp': max(1, user_hp),
                'level_up': level_up_result,
                'boss_type': boss_data['rarity']
            }
        
        else:
            # Поражение
            await db_manager.update_user(user_id, {
                'hp': 1,
                'bosses_lost': user.get('bosses_lost', 0) + 1,
                'total_damage_taken': user.get('total_damage_taken', 0) + (user_stats['hp'] - 1)
            })
            
            return {
                'success': True,
                'result': 'lose',
                'boss_name': boss_data['name'],
                'rounds': round_num,
                'log': log,
                'user_hp': 1
            }
    
    def _calculate_boss_damage(self, user_stats: Dict[str, Any], boss_data: Dict[str, Any]) -> int:
        """Рассчет урона пользователя по боссу"""
        base_damage = user_stats.get('damage', 50)
        
        # Модификаторы от характеристик
        str_bonus = user_stats.get('str', 10) * 2
        agi_bonus = user_stats.get('agi', 10) * 1.5
        int_bonus = user_stats.get('int', 10) * 1.2
        
        # Критический удар
        crit_chance = user_stats.get('crit', 5)
        crit_multiplier = 1.0
        if random.random() < crit_chance / 100:
            crit_multiplier = 2.0
        
        # Броня босса
        armor = boss_data['armor']
        armor_reduction = min(armor * 0.03, 0.5)  # Максимальное снижение на 50%
        
        total_damage = (base_damage + str_bonus + agi_bonus + int_bonus) * crit_multiplier
        final_damage = int(total_damage * (1 - armor_reduction))
        
        return max(final_damage, 1)
    
    def _calculate_boss_attack(self, boss_data: Dict[str, Any], user_stats: Dict[str, Any]) -> int:
        """Рассчет урона босса по пользователю"""
        base_damage = boss_data['damage']
        
        # Броня пользователя
        armor = user_stats.get('armor', 0)
        armor_reduction = min(armor * 0.05, 0.7)  # Максимальное снижение на 70%
        
        # Уклонение
        evasion = user_stats.get('evasion', 0)
        if random.random() < evasion / 100:
            return 0  # Промах
        
        final_damage = int(base_damage * (1 - armor_reduction))
        
        return max(final_damage, 1)
    
    async def _update_boss_stats(self, user_id: int, fight_result: Dict[str, Any]):
        """Обновление статистики боссов"""
        if fight_result['result'] == 'win':
            # Сохраняем информацию о победе
            with db_manager.get_connection() as conn:
                try:
                    conn.execute("""
                        INSERT INTO boss_fights (
                            user_id, boss_type, result, rounds, 
                            exp_gained, gold_gained, fight_log
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (
                        user_id, fight_result['boss_type'], 'win', 
                        fight_result['rounds'], fight_result['exp_gained'],
                        fight_result['gold_gained'], '\n'.join(fight_result['log'])
                    ))
                    conn.commit()
                except Exception as e:
                    logger.error(f"Ошибка при сохранении боя с боссом: {e}")
    
    async def _check_level_up(self, user_id: int, current_exp: int, new_exp_gained: int) -> Dict[str, Any]:
        """Проверка повышения уровня"""
        from game_logic.level_system import LevelSystem
        
        level_up_result = await LevelSystem.check_level_up(user_id, current_exp, new_exp_gained)
        
        if level_up_result['level_up']:
            logger.info(f"Пользователь {user_id} достиг уровня {level_up_result['new_level']}")
        
        return level_up_result
    
    async def get_boss_list(self, user_level: int) -> List[Dict[str, Any]]:
        """Получение списка доступных боссов"""
        available_bosses = []
        
        for boss_id, boss_data in self.bosses_db.items():
            if user_level >= boss_data['level']:
                available_bosses.append({
                    'id': boss_id,
                    'name': boss_data['name'],
                    'level': boss_data['level'],
                    'hp': boss_data['hp'],
                    'damage': boss_data['damage'],
                    'armor': boss_data['armor'],
                    'exp_reward': boss_data['exp_reward'],
                    'gold_reward': boss_data['gold_reward'],
                    'rarity': boss_data['rarity']
                })
        
        # Сортируем по уровню
        available_bosses.sort(key=lambda x: x['level'])
        
        return available_bosses
    
    async def get_boss_stats(self, user_id: int) -> Dict[str, Any]:
        """Получение статистики по боссам"""
        with db_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT 
                    bosses_killed, bosses_lost,
                    total_damage_dealt, total_damage_taken
                FROM users WHERE id = ?
            """, (user_id,))
            
            stats = dict(cursor.fetchone() or {})
            
            # Статистика боев
            cursor.execute("""
                SELECT COUNT(*) as total_fights,
                       AVG(rounds) as avg_rounds,
                       SUM(CASE WHEN result = 'win' THEN 1 ELSE 0 END) as wins,
                       SUM(CASE WHEN result = 'lose' THEN 1 ELSE 0 END) as losses
                FROM boss_fights WHERE user_id = ?
            """, (user_id,))
            
            fight_stats = dict(cursor.fetchone() or {})
            stats.update(fight_stats)
            
            return stats

# Глобальный экземпляр системы боев
combat_system = CombatSystem()

# Функция для регистрации обработчиков боя
def register_combat_handlers(application):
    """Регистрация обработчиков боевой системы"""
    # Здесь можно добавить обработчики команд боя
    pass

__all__ = ['CombatSystem', 'combat_system', 'register_combat_handlers']
