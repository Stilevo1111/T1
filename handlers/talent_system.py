"""Система талантов с бонусами"""

import logging
from typing import Dict, Any, List, Optional

from database.real_database import db_manager

logger = logging.getLogger(__name__)

class TalentManager:
    """Менеджер талантов"""
    
    def __init__(self):
        # Определение талантов
        self.talents_db = {
            # Сила (Strength)
            'str_1': {
                'name': 'Сила I',
                'description': '+10 к Силе',
                'cost': 50,
                'category': 'strength',
                'level': 1,
                'prerequisites': [],
                'stats': {'str': 10}
            },
            'str_2': {
                'name': 'Сила II',
                'description': 'Увеличивает урон на 15%',
                'cost': 100,
                'category': 'strength',
                'level': 2,
                'prerequisites': ['str_1'],
                'stats': {'damage_mult': 1.15}
            },
            'str_3': {
                'name': 'Сила III',
                'description': 'Увеличивает броню на 10%',
                'cost': 150,
                'category': 'strength',
                'level': 3,
                'prerequisites': ['str_2'],
                'stats': {'armor_mult': 1.10}
            },
            'str_4': {
                'name': 'Сила IV',
                'description': 'Увеличивает максимальное HP на 15%',
                'cost': 200,
                'category': 'strength',
                'level': 4,
                'prerequisites': ['str_3'],
                'stats': {'hp_mult': 1.15}
            },
            
            # Ловкость (Agility)
            'agi_1': {
                'name': 'Ловкость I',
                'description': '+10 к Ловкости',
                'cost': 50,
                'category': 'agility',
                'level': 1,
                'prerequisites': [],
                'stats': {'agi': 10}
            },
            'agi_2': {
                'name': 'Ловкость II',
                'description': 'Увеличивает критический урон на 15%',
                'cost': 100,
                'category': 'agility',
                'level': 2,
                'prerequisites': ['agi_1'],
                'stats': {'crit_mult': 1.15}
            },
            'agi_3': {
                'name': 'Ловкость III',
                'description': 'Увеличивает уклонение на 10%',
                'cost': 150,
                'category': 'agility',
                'level': 3,
                'prerequisites': ['agi_2'],
                'stats': {'evasion_mult': 1.10}
            },
            'agi_4': {
                'name': 'Ловкость IV',
                'description': 'Увеличивает скорость атаки на 15%',
                'cost': 200,
                'category': 'agility',
                'level': 4,
                'prerequisites': ['agi_3'],
                'stats': {'speed_mult': 1.15}
            },
            
            # Интеллект (Intelligence)
            'int_1': {
                'name': 'Интеллект I',
                'description': '+10 к Интеллекту',
                'cost': 50,
                'category': 'intelligence',
                'level': 1,
                'prerequisites': [],
                'stats': {'int': 10}
            },
            'int_2': {
                'name': 'Интеллект II',
                'description': 'Увеличивает силу заклинаний на 15%',
                'cost': 100,
                'category': 'intelligence',
                'level': 2,
                'prerequisites': ['int_1'],
                'stats': {'spell_damage_mult': 1.15}
            },
            'int_3': {
                'name': 'Интеллект III',
                'description': 'Увеличивает максимальную ману на 10%',
                'cost': 150,
                'category': 'intelligence',
                'level': 3,
                'prerequisites': ['int_2'],
                'stats': {'mana_mult': 1.10}
            },
            'int_4': {
                'name': 'Интеллект IV',
                'description': 'Увеличивает магическую защиту на 15%',
                'cost': 200,
                'category': 'intelligence',
                'level': 4,
                'prerequisites': ['int_3'],
                'stats': {'magic_resist_mult': 1.15}
            },
            
            # Гибридные таланты
            'hybrid_1': {
                'name': 'Гибрид I',
                'description': '+5 к каждой характеристике',
                'cost': 100,
                'category': 'hybrid',
                'level': 1,
                'prerequisites': [],
                'stats': {'str': 5, 'agi': 5, 'int': 5}
            },
            'hybrid_2': {
                'name': 'Гибрид II',
                'description': 'Увеличивает все характеристики на 10%',
                'cost': 200,
                'category': 'hybrid',
                'level': 2,
                'prerequisites': ['hybrid_1'],
                'stats': {'all_stats_mult': 1.10}
            },
            'hybrid_3': {
                'name': 'Гибрид III',
                'description': 'Увеличивает весь урон на 5%',
                'cost': 250,
                'category': 'hybrid',
                'level': 3,
                'prerequisites': ['hybrid_2'],
                'stats': {'all_damage_mult': 1.05}
            },
            'hybrid_4': {
                'name': 'Гибрид IV',
                'description': 'Увеличивает всю защиту на 5%',
                'cost': 250,
                'category': 'hybrid',
                'level': 4,
                'prerequisites': ['hybrid_3'],
                'stats': {'all_defense_mult': 1.05}
            }
        }
    
    async def get_available_talents(self, user_id: int) -> List[Dict[str, Any]]:
        """Получение доступных для изучения талантов"""
        learned_talents = await db_manager.get_learned_talents(user_id)
        user = await db_manager.get_user(user_id)
        
        if not user:
            return []
        
        available_talents = []
        
        for talent_id, talent_data in self.talents_db.items():
            # Проверяем, не изучен ли уже талант
            if talent_id in learned_talents:
                continue
            
            # Проверяем пререквизиты
            if not self._check_prerequisites(talent_data['prerequisites'], learned_talents):
                continue
            
            # Проверяем уровень пользователя
            user_level = user.get('level', 1)
            if user_level < talent_data['level']:
                continue
            
            # Проверяем, есть ли деньги
            user_gold = user.get('gold', 0)
            if user_gold < talent_data['cost']:
                continue
            
            available_talents.append({
                'id': talent_id,
                'name': talent_data['name'],
                'description': talent_data['description'],
                'cost': talent_data['cost'],
                'category': talent_data['category'],
                'level': talent_data['level'],
                'can_learn': True
            })
        
        return available_talents
    
    def _check_prerequisites(self, prerequisites: List[str], learned_talents: List[str]) -> bool:
        """Проверка выполнения пререквизитов"""
        for prereq in prerequisites:
            if prereq not in learned_talents:
                return False
        return True
    
    async def learn_talent(self, user_id: int, talent_id: str) -> Dict[str, Any]:
        """Изучение таланта"""
        if talent_id not in self.talents_db:
            return {'success': False, 'message': 'Талант не найден'}
        
        talent_data = self.talents_db[talent_id]
        learned_talents = await db_manager.get_learned_talents(user_id)
        user = await db_manager.get_user(user_id)
        
        if not user:
            return {'success': False, 'message': 'Пользователь не найден'}
        
        # Проверяем, не изучен ли уже талант
        if talent_id in learned_talents:
            return {'success': False, 'message': 'Талант уже изучен'}
        
        # Проверяем пререквизиты
        if not self._check_prerequisites(talent_data['prerequisites'], learned_talents):
            return {'success': False, 'message': 'Не выполнены пререквизиты'}
        
        # Проверяем уровень
        user_level = user.get('level', 1)
        if user_level < talent_data['level']:
            return {'success': False, 'message': 'Недостаточный уровень'}
        
        # Проверяем деньги
        user_gold = user.get('gold', 0)
        if user_gold < talent_data['cost']:
            return {'success': False, 'message': 'Недостаточно золота'}
        
        # Изучаем талант
        success = await db_manager.learn_talent(user_id, talent_id)
        if not success:
            return {'success': False, 'message': 'Ошибка при изучении таланта'}
        
        # Списываем деньги
        await db_manager.update_user(user_id, {
            'gold': user_gold - talent_data['cost'],
            'talents_learned': user.get('talents_learned', 0) + 1
        })
        
        return {
            'success': True,
            'talent_name': talent_data['name'],
            'cost': talent_data['cost'],
            'stats': talent_data['stats']
        }
    
    async def get_user_talents(self, user_id: int) -> Dict[str, Any]:
        """Получение изученных талантов пользователя"""
        learned_talents = await db_manager.get_learned_talents(user_id)
        
        talents_by_category = {
            'strength': [],
            'agility': [],
            'intelligence': [],
            'hybrid': []
        }
        
        for talent_id in learned_talents:
            if talent_id in self.talents_db:
                talent_data = self.talents_db[talent_id]
                talents_by_category[talent_data['category']].append({
                    'id': talent_id,
                    'name': talent_data['name'],
                    'description': talent_data['description'],
                    'level': talent_data['level'],
                    'stats': talent_data['stats']
                })
        
        # Сортируем таланты по уровню
        for category in talents_by_category:
            talents_by_category[category].sort(key=lambda x: x['level'])
        
        return talents_by_category
    
    async def get_talent_tree(self) -> Dict[str, Any]:
        """Получение полного древа талантов"""
        tree = {
            'strength': [],
            'agility': [],
            'intelligence': [],
            'hybrid': []
        }
        
        for talent_id, talent_data in self.talents_db.items():
            tree[talent_data['category']].append({
                'id': talent_id,
                'name': talent_data['name'],
                'description': talent_data['description'],
                'cost': talent_data['cost'],
                'level': talent_data['level'],
                'prerequisites': talent_data['prerequisites'],
                'stats': talent_data['stats']
            })
        
        # Сортируем по уровню
        for category in tree:
            tree[category].sort(key=lambda x: x['level'])
        
        return tree
    
    async def get_talent_bonuses(self, user_id: int) -> Dict[str, Any]:
        """Получение бонусов от изученных талантов"""
        learned_talents = await db_manager.get_learned_talents(user_id)
        
        # Инициализируем бонусы
        bonuses = {
            'str': 0, 'agi': 0, 'int': 0,
            'damage_mult': 1.0, 'armor_mult': 1.0, 'hp_mult': 1.0,
            'evasion_mult': 1.0, 'speed_mult': 1.0, 'spell_damage_mult': 1.0,
            'mana_mult': 1.0, 'magic_resist_mult': 1.0,
            'all_stats_mult': 1.0, 'all_damage_mult': 1.0, 'all_defense_mult': 1.0
        }
        
        for talent_id in learned_talents:
            if talent_id in self.talents_db:
                talent_stats = self.talents_db[talent_id]['stats']
                
                for stat, value in talent_stats.items():
                    if stat in bonuses:
                        if isinstance(value, float):
                            bonuses[stat] *= value
                        else:
                            bonuses[stat] += value
        
        return bonuses
    
    async def get_talent_progress(self, user_id: int) -> Dict[str, Any]:
        """Получение прогресса по талантам"""
        learned_talents = await db_manager.get_learned_talents(user_id)
        user = await db_manager.get_user(user_id)
        
        if not user:
            return {'progress': 0, 'total_talents': 0, 'learned_talents': 0}
        
        total_talents = len(self.talents_db)
        learned_count = len(learned_talents)
        
        # Рассчитываем прогресс по категориям
        categories_progress = {}
        for category in ['strength', 'agility', 'intelligence', 'hybrid']:
            category_talents = [t for t in self.talents_db.values() if t['category'] == category]
            learned_category = [t for t in learned_talents if self.talents_db[t]['category'] == category]
            
            categories_progress[category] = {
                'total': len(category_talents),
                'learned': len(learned_category),
                'progress': int((len(learned_category) / len(category_talents)) * 100) if category_talents else 0
            }
        
        return {
            'progress': int((learned_count / total_talents) * 100) if total_talents > 0 else 0,
            'total_talents': total_talents,
            'learned_talents': learned_count,
            'categories': categories_progress,
            'user_level': user.get('level', 1),
            'user_gold': user.get('gold', 0)
        }

# Глобальный экземпляр менеджера талантов
talent_manager = TalentManager()

async def talents(update, context):
    """Обработчик команды /talents - показывает доступные таланты"""
    user_id = update.effective_user.id
    
    try:
        # Получаем доступные таланты
        available_talents = await talent_manager.get_available_talents(user_id)
        user_talents = await talent_manager.get_user_talents(user_id)
        progress = await talent_manager.get_talent_progress(user_id)
        
        if not available_talents and not any(user_talents.values()):
            message = "Пока нет доступных талантов. Повышайте уровень, чтобы открыть новые таланты!"
        else:
            message_parts = ["🔮 *Таланты*"]
            
            # Прогресс
            message_parts.append(f"\n📊 *Прогресс:* {progress['progress']}% ({progress['learned_talents']}/{progress['total_talents']})")
            
            # Изученные таланты
            learned_count = 0
            for category, talents in user_talents.items():
                if talents:
                    learned_count += len(talents)
                    message_parts.append(f"\n*{category.capitalize()} таланты:*")
                    for talent in talents:
                        message_parts.append(f"• {talent['name']} (Lvl {talent['level']})")
            
            if learned_count == 0:
                message_parts.append("\n*Изученные таланты:* Нет")
            
            # Доступные для изучения
            if available_talents:
                message_parts.append("\n*Доступные для изучения:*")
                for talent in available_talents:
                    message_parts.append(f"• {talent['name']} - {talent['description']} (Цена: {talent['cost']} золота)")
            
            message = "\n".join(message_parts)
        
        await update.message.reply_text(message, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Ошибка при отображении талантов: {e}")
        await update.message.reply_text("Произошла ошибка при получении талантов. Попробуйте позже.")

async def learn_talent(update, context):
    """Обработчик команды /learn_talent - изучает талант"""
    user_id = update.effective_user.id
    
    if not context.args:
        await update.message.reply_text("Используйте: /learn_talent <название_таланта>")
        return
    
    talent_id = context.args[0].lower()
    
    try:
        result = await talent_manager.learn_talent(user_id, talent_id)
        
        if result['success']:
            await update.message.reply_text(f"✅ Вы изучили талант '{result['talent_name']}' за {result['cost']} золота!")
        else:
            await update.message.reply_text(f"❌ {result['message']}")
            
    except Exception as e:
        logger.error(f"Ошибка при изучении таланта: {e}")
        await update.message.reply_text("Произошла ошибка при изучении таланта. Попробуйте позже.")

async def level_up(update, context):
    """Обработчик команды /level_up - показывает информацию о повышении уровня"""
    user_id = update.effective_user.id
    
    try:
        user = await db_manager.get_user(user_id)
        if not user:
            await update.message.reply_text("Пользователь не найден.")
            return
        
        level = user.get('level', 1)
        exp = user.get('exp', 0)
        exp_needed = user.get('exp_needed', 100)
        
        message = f"""
📈 *Повышение уровня*

Текущий уровень: {level}
Опыт: {exp}/{exp_needed}

При повышении уровня вы получаете:
• +10 к максимальному HP
• +5 к максимальной мане
• +1 к силе, ловкости и интеллекту
• 1 очко для распределения характеристик
"""
        
        await update.message.reply_text(message, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Ошибка при отображении информации о повышении уровня: {e}")
        await update.message.reply_text("Произошла ошибка. Попробуйте позже.")

async def stats_distribute(update, context):
    """Обработчик команды /stats_distribute - распределяет очки характеристик"""
    user_id = update.effective_user.id
    
    if not context.args or len(context.args) != 2:
        await update.message.reply_text("Используйте: /stats_distribute <характеристика> <количество>")
        await update.message.reply_text("Характеристики: str, agi, int")
        return
    
    stat = context.args[0].lower()
    try:
        amount = int(context.args[1])
    except ValueError:
        await update.message.reply_text("Количество должно быть числом.")
        return
    
    if stat not in ['str', 'agi', 'int']:
        await update.message.reply_text("Неверная характеристика. Используйте: str, agi, int")
        return
    
    try:
        user = await db_manager.get_user(user_id)
        if not user:
            await update.message.reply_text("Пользователь не найден.")
            return
        
        available_points = user.get('stat_points', 0)
        
        if amount <= 0:
            await update.message.reply_text("Количество должно быть положительным числом.")
            return
        
        if amount > available_points:
            await update.message.reply_text(f"Недостаточно очков характеристик. Доступно: {available_points}")
            return
        
        # Обновляем характеристики
        current_stat = user.get(stat, 10)
        new_stat = current_stat + amount
        new_points = available_points - amount
        
        await db_manager.update_user(user_id, {
            stat: new_stat,
            'stat_points': new_points
        })
        
        await update.message.reply_text(f"✅ Вы распределили {amount} очков в {stat}. Новое значение: {new_stat}")
        
    except Exception as e:
        logger.error(f"Ошибка при распределении характеристик: {e}")
        await update.message.reply_text("Произошла ошибка. Попробуйте позже.")

async def add_str(update, context):
    """Обработчик команды /add_str - добавляет 1 очко в силу"""
    user_id = update.effective_user.id
    
    try:
        user = await db_manager.get_user(user_id)
        if not user:
            await update.message.reply_text("Пользователь не найден.")
            return
        
        available_points = user.get('stat_points', 0)
        
        if available_points <= 0:
            await update.message.reply_text("Недостаточно очков характеристик.")
            return
        
        current_str = user.get('str', 10)
        new_str = current_str + 1
        new_points = available_points - 1
        
        await db_manager.update_user(user_id, {
            'str': new_str,
            'stat_points': new_points
        })
        
        await update.message.reply_text(f"✅ Вы добавили 1 очко в Силу. Новое значение: {new_str}")
        
    except Exception as e:
        logger.error(f"Ошибка при добавлении силы: {e}")
        await update.message.reply_text("Произошла ошибка. Попробуйте позже.")

async def add_agi(update, context):
    """Обработчик команды /add_agi - добавляет 1 очко в ловкость"""
    user_id = update.effective_user.id
    
    try:
        user = await db_manager.get_user(user_id)
        if not user:
            await update.message.reply_text("Пользователь не найден.")
            return
        
        available_points = user.get('stat_points', 0)
        
        if available_points <= 0:
            await update.message.reply_text("Недостаточно очков характеристик.")
            return
        
        current_agi = user.get('agi', 10)
        new_agi = current_agi + 1
        new_points = available_points - 1
        
        await db_manager.update_user(user_id, {
            'agi': new_agi,
            'stat_points': new_points
        })
        
        await update.message.reply_text(f"✅ Вы добавили 1 очко в Ловкость. Новое значение: {new_agi}")
        
    except Exception as e:
        logger.error(f"Ошибка при добавлении ловкости: {e}")
        await update.message.reply_text("Произошла ошибка. Попробуйте позже.")

async def add_int(update, context):
    """Обработчик команды /add_int - добавляет 1 очко в интеллект"""
    user_id = update.effective_user.id
    
    try:
        user = await db_manager.get_user(user_id)
        if not user:
            await update.message.reply_text("Пользователь не найден.")
            return
        
        available_points = user.get('stat_points', 0)
        
        if available_points <= 0:
            await update.message.reply_text("Недостаточно очков характеристик.")
            return
        
        current_int = user.get('int', 10)
        new_int = current_int + 1
        new_points = available_points - 1
        
        await db_manager.update_user(user_id, {
            'int': new_int,
            'stat_points': new_points
        })
        
        await update.message.reply_text(f"✅ Вы добавили 1 очко в Интеллект. Новое значение: {new_int}")
        
    except Exception as e:
        logger.error(f"Ошибка при добавлении интеллекта: {e}")
        await update.message.reply_text("Произошла ошибка. Попробуйте позже.")

async def handle_talents_category(update, context):
    """Обработчик callback для категорий талантов"""
    query = update.callback_query
    category = query.data.replace('talents_category_', '')
    
    try:
        user_talents = await talent_manager.get_user_talents(query.from_user.id)
        available_talents = await talent_manager.get_available_talents(query.from_user.id)
        
        message_parts = [f"🔮 *Таланты - {category.capitalize()}*"]
        
        # Изученные таланты
        learned_talents = user_talents.get(category, [])
        if learned_talents:
            message_parts.append("\n*Изученные:*")
            for talent in learned_talents:
                message_parts.append(f"• {talent['name']} (Lvl {talent['level']})")
        else:
            message_parts.append("\n*Изученные:* Нет")
        
        # Доступные для изучения
        category_available = [t for t in available_talents if t['category'] == category]
        if category_available:
            message_parts.append("\n*Доступные для изучения:*")
            for talent in category_available:
                message_parts.append(f"• {talent['name']} - {talent['description']} (Цена: {talent['cost']} золота)")
        else:
            message_parts.append("\n*Доступные для изучения:* Нет")
        
        message = "\n".join(message_parts)
        
        await query.edit_message_text(message, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Ошибка при обработке callback талантов: {e}")
        await query.answer("Произошла ошибка. Попробуйте позже.")

async def handle_talents_stats(update, context):
    """Обработчик callback для статистики талантов"""
    query = update.callback_query
    user_id = query.from_user.id
    
    try:
        bonuses = await talent_manager.get_talent_bonuses(user_id)
        progress = await talent_manager.get_talent_progress(user_id)
        
        message_parts = ["📊 *Статистика талантов*"]
        
        # Бонусы
        message_parts.append("\n*Бонусы от талантов:*")
        for stat, value in bonuses.items():
            if value != 1.0 and value != 0:
                if isinstance(value, float):
                    message_parts.append(f"• {stat}: x{value:.2f}")
                else:
                    message_parts.append(f"• {stat}: +{value}")
        
        # Прогресс по категориям
        message_parts.append("\n*Прогресс по категориям:*")
        for category, data in progress['categories'].items():
            message_parts.append(f"• {category.capitalize()}: {data['learned']}/{data['total']} ({data['progress']}%)")
        
        message = "\n".join(message_parts)
        
        await query.edit_message_text(message, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Ошибка при обработке callback статистики талантов: {e}")
        await query.answer("Произошла ошибка. Попробуйте позже.")

async def handle_talents_main(update, context):
    """Обработчик callback для возврата в главное меню талантов"""
    query = update.callback_query
    user_id = query.from_user.id
    
    try:
        user_talents = await talent_manager.get_user_talents(user_id)
        progress = await talent_manager.get_talent_progress(user_id)
        
        message_parts = ["🔮 *Таланты*"]
        message_parts.append(f"\n📊 *Прогресс:* {progress['progress']}% ({progress['learned_talents']}/{progress['total_talents']})")
        
        # Категории
        categories = ['strength', 'agility', 'intelligence', 'hybrid']
        for category in categories:
            talents_count = len(user_talents.get(category, []))
            message_parts.append(f"• {category.capitalize()}: {talents_count} талантов")
        
        message = "\n".join(message_parts)
        
        await query.edit_message_text(message, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Ошибка при обработке callback главного меню талантов: {e}")
        await query.answer("Произошла ошибка. Попробуйте позже.")

async def handle_learn_talent_callback(update, context):
    """Обработчик callback для изучения таланта"""
    query = update.callback_query
    talent_id = query.data.replace('learn_talent_', '')
    
    try:
        result = await talent_manager.learn_talent(query.from_user.id, talent_id)
        
        if result['success']:
            await query.answer(f"Вы изучили талант '{result['talent_name']}' за {result['cost']} золота!")
            
            # Обновляем сообщение
            await talents(update, context)
        else:
            await query.answer(f"Ошибка: {result['message']}", show_alert=True)
        
    except Exception as e:
        logger.error(f"Ошибка при обработке callback изучения таланта: {e}")
        await query.answer("Произошла ошибка. Попробуйте позже.")

# Функция для регистрации обработчиков талантов
def register_talent_handlers(application):
    """Регистрация обработчиков талантной системы"""
    # Здесь можно добавить обработчики команд талантов
    pass

__all__ = ['TalentManager', 'talent_manager', 'talents', 'learn_talent', 'level_up', 'stats_distribute', 
           'add_str', 'add_agi', 'add_int', 'handle_talents_category', 'handle_talents_stats', 
           'handle_talents_main', 'handle_learn_talent_callback', 'register_talent_handlers']
