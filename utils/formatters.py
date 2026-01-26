"""Модуль для форматирования текста и сообщений"""

from typing import Dict, List, Optional
from game_logic import calculate_character_stats, get_user_progress, get_next_level_exp, calculate_boss_strategy

def format_stats_text(user: Dict, stats: Dict) -> str:
    """Форматирует текст статистики персонажа"""
    try:
        progress = get_user_progress(user)
        next_level_exp = get_next_level_exp(user["level"])
        
        text = (f"👤 ПРОФИЛЬ {user['username']}\n\n"
                f"🎮 Уровень: {user['level']} (Опыт: {user['exp']}/{next_level_exp})\n"
                f"📊 Винрейт: {user['mmr']} MMR\n"
                f"👹 Убито боссов: {user.get('bosses_killed', 0)}\n"
                f"🗡️ Общий урон по боссам: {user['boss_dmg']}\n\n"
                f"❤️ HP: {user['hp']}/{stats['max_hp']}\n"
                f"💪 STR: {stats['str_total']} (база: {user['str']})\n"
                f"🏃‍♂️ AGI: {stats['agi_total']} (база: {user['agi']})\n"
                f"🧠 INT: {stats['int_total']} (база: {user['int']})\n"
                f"⚔️ Урон: {stats['base_damage']}\n"
                f"🎯 Крит: {stats['crit_chance']:.1f}%\n"
                f"🛡️ Уклонение: {stats['dodge_chance']:.1f}%\n"
                f"💚 Реген: {stats['hp_regen']:.1f}% в минуту\n\n"
                f"📚 EXP: {user['exp']}\n"
                f"💰 Gold: {user['gold']}\n"
                f"🍆 Fissure: {user['fissure']:.1f} см\n\n")
        
        # Форматируем слоты для артефактов
        slots = user["items"] if user["items"] else [None] * 6
        artifacts_text = "🎒 СЛОТЫ АРТЕФАКТОВ:\n"
        for i, item in enumerate(slots, 1):
            if item:
                description = get_item_description(item)
                artifacts_text += f"  {i}. {item} — {description}\n"
            else:
                artifacts_text += f"  {i}. ПУСТО\n"
        
        text += artifacts_text + "\n"
        text += "💡 Подсказка: /buy ITEM — купить предмет, /potion TYPE — купить зелье"
        return text
    except Exception as e:
        print(f"Ошибка форматирования статистики: {e}")
        return "❌ Ошибка форматирования данных"

def format_boss_info(user: Dict) -> str:
    """Форматирует информацию о боссе"""
    try:
        boss_ability = user.get('boss_ability', 'Нет информации')
        return (f"👹 **{user['boss_name']}**\n"
                f"❤️ HP: {user['boss_hp']}/{user['boss_max']}\n"
                f"📊 Уровень: {user['boss_level']}\n"
                f"⚡ Способности: {boss_ability}\n\n"
                f"💢 Используйте /attack чтобы атаковать")
    except Exception as e:
        print(f"Ошибка форматирования информации о боссе: {e}")
        return "❌ Ошибка форматирования данных"

def format_boss_strategy(user: Dict, strategy: Dict) -> str:
    """Форматирует рекомендации по стратегии против босса"""
    try:
        text = "💡 Стратегия:\n"
        for rec in strategy["recommendations"]:
            text += f"   {rec}\n"
        
        text += f"\n📊 Ваши характеристики:\n"
        text += f"   ⚔️ Урон: {strategy['damage_per_second']:.1f} в сек\n"
        text += f"   ❤️ Выживаемость: {strategy['survivability']:.1f}\n"
        text += f"   🎯 Общий балл: {strategy['overall_score']:.1f}\n"
        return text
    except Exception as e:
        print(f"Ошибка форматирования стратегии: {e}")
        return "❌ Ошибка форматирования данных"

def format_pvp_opponents(opponents: List[Dict]) -> str:
    """Форматирует список PvP противников"""
    try:
        if not opponents:
            return "❌ Нет доступных противников"
        
        text = "⚔️ Доступные противники для PvP:\n\n"
        for i, row in enumerate(opponents, 1):
            text += f"{i}. 👤 {row['username']}\n"
            text += f"   📊 MMR: {row['mmr']} | Уровень: {row['level']}\n"
            text += f"   💪 STR: {row['str']} | 🏃‍♂️ AGI: {row['agi']} | 🧠 INT: {row['int']}\n"
            text += f"   ❤️ HP: {row['hp']}/{row['hp_max']}\n"
            text += f"   ⚔️ Урон: {row.get('damage', 0)} | 🛡️ Уклон: {row.get('dodge', 0):.1f}%\n"
            text += f"   /fight_{row['user_id']} — сразиться\n\n"
        return text
    except Exception as e:
        print(f"Ошибка форматирования списка противников: {e}")
        return "❌ Ошибка форматирования данных"

def format_achievements(user: Dict, achievements_list: List[str]) -> str:
    """Форматирует список достижений"""
    try:
        text = f"🏆 ДОСТИЖЕНИЯ - {user.get('title', 'Новичок')}\n\n"
        
        if achievements_list:
            text += "\n".join(achievements_list)
        else:
            text += "📭 Достижений пока нет. Играйте активнее!"
        
        text += f"\n\n📊 Прогресс:\n"
        text += f"👹 Убито боссов: {user.get('bosses_killed', 0)}/100\n"
        text += f"🌟 Изучено талантов: {user.get('total_talent_points', 0)}/30\n"
        text += f"📏 Длина фиссуры: {user['fissure']:.1f}/100 см\n"
        text += f"⚔️ MMR рейтинг: {user['mmr']}/2000\n"
        return text
    except Exception as e:
        print(f"Ошибка форматирования достижений: {e}")
        return "❌ Ошибка форматирования данных"

def format_talent_tree(user: Dict, talents_data: Dict) -> str:
    """Форматирует дерево талантов"""
    try:
        text = f"🌳 ДЕРЕВО ТАЛАНТОВ - Уровень {user['level']}\n"
        text += f"🎯 Доступно очков талантов: {user.get('talent_points', 0)}\n\n"
        
        for branch_name, branch_talents in talents_data.items():
            branch_title = {
                "warrior": "⚔️ ВЕТКА ВОИНА",
                "rogue": "👤 ВЕТКА ПЛУТА", 
                "mage": "🔮 ВЕТКА МАГА",
                "hybrid": "🌟 ГИБРИДНЫЕ ТАЛАНТЫ"
            }.get(branch_name, branch_name.upper())
            
            text += f"{branch_title}:\n"
            
            for talent_id, talent_data in branch_talents.items():
                learned = user.get("talents", {}).get(talent_data["id"], 0)
                max_level = talent_data["max_level"]
                
                # Проверяем требования
                can_learn = True
                requires_text = ""
                if talent_data.get("requires"):
                    requires = talent_data["requires"]
                    if requires[0] == "min_level_10" and user["level"] < 10:
                        can_learn = False
                        requires_text = " (требуется 10+ ур.)"
                    else:
                        for req in requires:
                            if user.get("talents", {}).get(req, 0) < 1:
                                can_learn = False
                                requires_text = f" (требуется: {req})"
                
                status = "✅" if learned > 0 else "🔓" if can_learn else "🔒"
                level_text = f"{learned}/{max_level}" if learned > 0 else f"0/{max_level}"
                
                text += f"{status} {talent_data['name']} [{level_text}]{requires_text}\n"
                text += f"   📖 {talent_data['description']}\n"
                text += f"   💰 Стоимость: {talent_data['cost']} очков\n\n"
        
        text += "\n💡 Используйте /learn TALENT_ID для изучения таланта"
        text += "\n/stats_distribute POINTS - распределить очки характеристик"
        return text
    except Exception as e:
        print(f"Ошибка форматирования дерева талантов: {e}")
        return "❌ Ошибка форматирования данных"

def get_item_description(item_name: str) -> str:
    """Получает описание предмета"""
    from game_logic import ITEMS
    if item_name in ITEMS:
        return ITEMS[item_name]["description"]
    return "Неизвестный предмет"