"""Обработчики команд, связанных с боссами"""

import logging
import time
import random
from typing import Dict, Any
from telegram import Update
from telegram.ext import ContextTypes

from database import get_user, update_user
from game_logic import (
    spawn_boss, check_level_restriction, calculate_character_stats, 
    calculate_damage_with_talents, calculate_dodge, get_meme_message,
    calculate_boss_reward, check_level_up_new, get_user_progress, get_next_level_exp,
    calculate_boss_strategy
)
from utils.formatters import format_boss_info, format_boss_strategy

logger = logging.getLogger(__name__)

async def boss(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /boss"""
    try:
        user_id = update.effective_user.id
        username = update.effective_user.username or update.effective_user.full_name
        user = await get_user(user_id, username)
        
        if not user:
            await update.message.reply_text("❌ Ошибка загрузки данных")
            return
        
        # Рассчитываем стратегию против босса
        strategy = calculate_boss_strategy(user, user.get('boss_level', 1))
        
        message_text = format_boss_info(user)
        
        # Добавляем рекомендации по стратегии
        if strategy["recommendations"]:
            message_text += "\n\n💡 Стратегия:\n"
            for rec in strategy["recommendations"]:
                message_text += f"   {rec}\n"
        
        # Добавляем оценку характеристик
        message_text += f"\n📊 Ваши характеристики:\n"
        message_text += f"   ⚔️ Урон: {strategy['damage_per_second']:.1f} в сек\n"
        message_text += f"   ❤️ Выживаемость: {strategy['survivability']:.1f}\n"
        message_text += f"   🎯 Общий балл: {strategy['overall_score']:.1f}\n"
        
        msg = await update.message.reply_text(
            message_text,
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"КРИТИЧЕСКАЯ ОШИБКА в функции boss: {e}", exc_info=True)
        await update.message.reply_text(
            "❌ Произошла ошибка при получении информации о боссе. Попробуйте позже."
        )

async def attack(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /attack - улучшенная версия с полным боем за один клик"""
    try:
        username = update.effective_user.username or update.effective_user.full_name
        user = await get_user(update.effective_user.id, username)
        
        # Проверяем HP
        if user["hp"] <= 0:
            await update.message.reply_text("💀 Ты мёртв")
            return

        # Проверяем, жив ли босс
        if user["boss_hp"] <= 0:
            # Создаем нового босса
            new_boss = spawn_boss()
            await update_user(
                update.effective_user.id,
                boss_name=new_boss["name"],
                boss_hp=new_boss["hp"],
                boss_max=new_boss["max"],
                boss_level=new_boss["min_level"],
                boss_ability=new_boss["ability"]
            )
            user = await get_user(update.effective_user.id, username)  # Обновляем данные
        
        # Проверка уровня
        if not check_level_restriction(user["level"], user["boss_level"], user["boss_level"]):
            await update.message.reply_text("❌ Босс слишком сильный для тебя")
            return

        # Рассчитываем характеристики
        stats = calculate_character_stats(user)
        
        # Начинаем бой до смерти одного из участников
        text = f"⚔️ БОЙ НАЧАЛСЯ! {user['username']} против {user['boss_name']}\n\n"
        text += f"📊 Начальные характеристики:\n"
        text += f"👤 Игрок: HP {user['hp']}/{stats['max_hp']}, Урон {stats['base_damage']}\n"
        text += f"👹 Босс: HP {user['boss_hp']}/{user['boss_max']}, Урон {user['boss_dmg']}\n\n"
        
        # Переменные для боя
        current_user_hp = user["hp"]
        current_boss_hp = user["boss_hp"]
        total_boss_dmg = user["boss_dmg"]
        round_num = 1
        max_rounds = 20  # Ограничение на количество раундов во избежание бесконечных боев
        
        # Боевые действия
        while current_user_hp > 0 and current_boss_hp > 0 and round_num <= max_rounds:
            text += f"--- РАУНД {round_num} ---\n"
            
            # Атака игрока
            dmg, is_crit = calculate_damage_with_talents(user)
            current_boss_hp -= dmg
            total_boss_dmg += dmg
            
            text += f"1. {user['username']} наносит {dmg} урона\n"
            if is_crit:
                text += "   💥 КРИТ! Я инвестировал в урон\n"
            text += f"   👹 HP босса: {max(0, current_boss_hp)}/{user['boss_max']}\n"
            
            # Проверка смерти босса
            if current_boss_hp <= 0:
                boss_name = user["boss_name"]
                text += f"\n🎉 {user['username']} ПОБЕДИЛ!\n"
                text += f"👹 Босс {boss_name} повержен!\n"
                text += get_meme_message("boss_kill", boss=boss_name)
                break
            
            # Атака босса
            boss_min_dmg = 5
            boss_max_dmg = 15
            if user.get('boss_ability'):
                # Парсим урон из способностей
                ability = user['boss_ability']
                if 'урон' in ability.lower():
                    import re
                    numbers = re.findall(r'\d+', ability)
                    if numbers:
                        boss_min_dmg = int(numbers[0])
                        boss_max_dmg = boss_min_dmg + 5
            
            boss_attack = random.randint(boss_min_dmg, boss_max_dmg)
            text += f"2. {user['boss_name']} контратакует на {boss_attack} урона\n"
            
            # Проверка уклонения игрока
            if calculate_dodge(user):
                text += f"   🛡️ {user['username']} уклонился от атаки!\n"
            else:
                current_user_hp -= boss_attack
                text += f"   💥 Босс попал!\n"
                text += f"   👤 HP игрока: {max(0, current_user_hp)}/{stats['max_hp']}\n"
                
                # Проверка смерти игрока
                if current_user_hp <= 0:
                    text += f"\n💀 {user['username']} ПОГИБ!\n"
                    text += get_meme_message("death")
                    break
            
            round_num += 1
            text += "\n"
        
        # Обработка результатов боя
        if current_boss_hp <= 0:
            # Победа игрока
            boss_name = user["boss_name"]
            gold_reward, exp_reward = calculate_boss_reward(boss_name)
            user_gold = user["gold"] + gold_reward
            user_exp = user["exp"] + exp_reward
            bosses_killed = user.get("bosses_killed", 0) + 1
            
            # Создаем нового босса
            new_boss = spawn_boss()
            
            # Проверка повышения уровня
            can_level_up, bonuses = check_level_up_new(user)
            if can_level_up:
                user_level = bonuses["new_level"]
                user_hp_max = user.get("hp_max", 100) + bonuses["hp_bonus"]
                user_hp = user_hp_max
                text += f"\n🎉 ДОСТИГНУТ УРОВЕНЬ {user_level}!\n"
                
                # Добавляем бонусы за уровень
                await update_user(
                    update.effective_user.id,
                    level=user_level,
                    hp=user_hp_max,
                    hp_max=user_hp_max,
                    unspent_stats=user.get("unspent_stats", 0) + bonuses["stats_points"],
                    talent_points=user.get("talent_points", 0) + bonuses.get("talent_points", 0),
                    exp=user_exp,
                    boss_hp=new_boss["hp"],
                    boss_name=new_boss["name"],
                    boss_max=new_boss["max"],
                    boss_level=new_boss["min_level"],
                    boss_dmg=total_boss_dmg,
                    boss_ability=new_boss["ability"],
                    gold=user_gold,
                    bosses_killed=bosses_killed
                )
                user = await get_user(update.effective_user.id, username)  # Обновляем данные
                stats = calculate_character_stats(user)  # Пересчитываем статы
            else:
                user_level = user["level"]
                user_hp_max = stats["max_hp"]
                user_hp = current_user_hp
            
            # Обновляем данные
            await update_user(
                update.effective_user.id,
                hp=user_hp,
                hp_max=user_hp_max,
                level=user_level,
                exp=user_exp,
                boss_hp=new_boss["hp"],
                boss_name=new_boss["name"],
                boss_max=new_boss["max"],
                boss_level=new_boss["min_level"],
                boss_dmg=total_boss_dmg,
                boss_ability=new_boss["ability"],
                gold=user_gold,
                bosses_killed=bosses_killed
            )
            
            text += f"\n💰 Награда: {gold_reward} золота, {exp_reward} опыта"
            text += f"\n🗡️ Общий урон по боссу: {total_boss_dmg}"
            text += f"\n👹 Новый босс: {new_boss['name']} (ур. {new_boss['min_level']})"
            
        elif current_user_hp <= 0:
            # Поражение игрока
            await update_user(
                update.effective_user.id,
                hp=0,
                boss_hp=current_boss_hp,
                boss_dmg=total_boss_dmg
            )
            text += f"\n💔 {user['username']} проиграл боссу {user['boss_name']}"
            text += f"\n👹 Босс остался с {current_boss_hp}/{user['boss_max']} HP"
            text += f"\n💡 Совет: купите лучшую экипировку и попробуйте снова!"
        else:
            # Ограничение раундов достигнуто
            text += f"\n⏱️ Бой прерван после {max_rounds} раундов (возможно, босс слишком сильный)"
            text += f"\n👤 HP игрока: {current_user_hp}/{stats['max_hp']}"
            text += f"\n👹 HP босса: {current_boss_hp}/{user['boss_max']}"
            
            # Обновляем HP босса
            await update_user(
                update.effective_user.id,
                hp=current_user_hp,
                boss_hp=current_boss_hp,
                boss_dmg=total_boss_dmg
            )
        
        msg = await update.message.reply_text(text)
    except Exception as e:
        logger.error(f"ОШИБКА в attack: {e}", exc_info=True)
        await update.message.reply_text("❌ Ошибка при атаке")

