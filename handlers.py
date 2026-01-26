import time
import random
import logging
import asyncio
from typing import Dict, List, Tuple, Optional
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes, CommandHandler, MessageHandler, filters, CallbackQueryHandler

from config import AUTO_DELETE_DELAY, COOLDOWN, MEMES
from database import get_user, update_user, get_fissure_top, update_fissure
from game_logic import (
    calculate_character_stats, calculate_damage, calculate_dodge, spawn_boss, 
    check_level_restriction, regenerate_hp, check_level_up, get_fissure_result,
    get_meme_message, get_items_by_category, get_item_description, get_potion_data,
    calculate_boss_reward, get_user_progress, get_next_level_exp,
    calculate_pvp_advantage, calculate_boss_strategy
)

# ================= KEYBOARD =================

MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [["👹 BOSS", "🛒 SHOP"], ["⚔️ PVP", "🏆 TOP"], ["🍆 FISSURE", "👤 ПРОФИЛЬ"]],
    resize_keyboard=True,
)

FISSURE_KEYBOARD = ReplyKeyboardMarkup(
    [["🎲 ROLL"], ["📊 STATS", "⬅️ НАЗАД"]],
    resize_keyboard=True,
)

# Клавиатура категорий магазина
SHOP_CATEGORIES_KEYBOARD = ReplyKeyboardMarkup(
    [["👟 Сапоги", "🛡️ Броня"], ["🗡️ Оружие", "🛡️ Защита"], ["🔮 Поддержка", "🧪 Зелья"], ["⬅️ НАЗАД"]],
    resize_keyboard=True,
)

# ================= UTILS =================

async def auto_delete(context: ContextTypes.DEFAULT_TYPE, chat_id: int, msg_ids: List[int]):
    """Автоматическое удаление сообщений через заданное время"""
    await asyncio.sleep(AUTO_DELETE_DELAY)
    for msg_id in msg_ids:
        try:
            await context.bot.delete_message(chat_id, msg_id)
        except Exception:
            pass

def format_stats_text(user: Dict, stats: Dict) -> str:
    """Форматирует текст статистики персонажа"""
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

def format_boss_info(user: Dict) -> str:
    """Форматирует информацию о боссе"""
    boss_ability = user.get('boss_ability', 'Нет информации')
    return (f"👹 **{user['boss_name']}**\n"
            f"❤️ HP: {user['boss_hp']}/{user['boss_max']}\n"
            f"📊 Уровень: {user['boss_level']}\n"
            f"⚡ Способности: {boss_ability}\n\n"
            f"💢 Используйте /attack чтобы атаковать")

# ================= COMMAND HANDLERS =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    username = update.effective_user.username or update.effective_user.full_name
    user = await get_user(update.effective_user.id, username)
    
    stats = calculate_character_stats(user)
    progress = get_user_progress(user)
    next_level_exp = get_next_level_exp(user["level"])
    
    msg = await update.message.reply_text(
        f"🎮 {user['username']}, ты в игре\n"
        f"Уровень: {user['level']} (Опыт: {user['exp']}/{next_level_exp})\n"
        f"HP: {user['hp']}/{stats['max_hp']}\n"
        f"STR: {stats['str_total']} | AGI: {stats['agi_total']} | INT: {stats['int_total']}\n"
        f"Gold: {user['gold']} | MMR: {user['mmr']}\n"
        f"🍆 Fissure: {user['fissure']:.1f} см\n\n"
        "Команды:\n"
        "/boss — посмотреть босса\n"
        "/attack — атаковать босса\n"
        "/shop — магазин\n"
        "/buy ITEM — купить предмет\n"
        "/potion TYPE — купить зелье\n"
        "/heal — восстановить HP\n"
        "/pvp — PvP\n"
        "/fight USER_ID — вызов на дуэль\n"
        "/top — таблица лидеров\n"
        "/fissure — ролл фиссуры\n"
        "/stats — статистика",
        reply_markup=MAIN_KEYBOARD,
    )
    # Автоудаление ответа
    context.application.create_task(
        auto_delete(context, update.effective_chat.id, [msg.message_id])
    )


async def fissure(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /fissure"""
    username = update.effective_user.username or update.effective_user.full_name
    user = await get_user(update.effective_user.id, username)
    now = time.time()
    remaining = COOLDOWN - (now - user["last_fissure"])
    if remaining > 0:
        msg = await update.message.reply_text(
            f"⏳ Через {int(remaining // 3600)} ч. {(int(remaining) % 3600) // 60} мин."
        )
        # Автоудаление ответа
        context.application.create_task(
            auto_delete(context, update.effective_chat.id, [msg.message_id])
        )
    else:
        new_value, text, phrase = get_fissure_result()
        await update_fissure(update.effective_user.id, new_value, now)
        msg = await update.message.reply_text(
            f"{text}\n{phrase}\n📏 Теперь {new_value:.1f} см"
        )
        # Автоудаление ответа
        context.application.create_task(
            auto_delete(context, update.effective_chat.id, [msg.message_id])
        )


async def fissure_top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /fissure_top"""
    rows = await get_fissure_top()
    if not rows:
        await update.message.reply_text("Топ пуст 😢")
    else:
        text = ["🏆 ТОП по длине фиссуры:\n"]
        for i, row in enumerate(rows, 1):
            text.append(f"{i}. 👤 {row['username']} — {row['fissure']:.1f} см")
        await update.message.reply_text("\n".join(text))


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /stats"""
    username = update.effective_user.username or update.effective_user.full_name
    user = await get_user(update.effective_user.id, username)
    stats = calculate_character_stats(user)
    
    msg = await update.message.reply_text(
        f"📊 Твоя Фиссура:\n📏 {user['fissure']:.1f} см"
    )

    context.application.create_task(
        auto_delete(context, update.effective_chat.id, [msg.message_id])
    )


async def boss(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /boss"""
    try:
        user_id = update.effective_user.id
        username = update.effective_user.username or update.effective_user.full_name
        
        logging.info(f"=== ФУНКЦИЯ BOSS ВЫЗВАНА ===")
        logging.info(f"Для пользователя: {username} (ID: {user_id})")
        
        # Получаем данные пользователя
        user = await get_user(user_id, username)
        logging.info(f"Данные пользователя получены: boss_name={user.get('boss_name')}")
        
        if not user:
            logging.error("Не удалось получить данные пользователя")
            await update.message.reply_text("❌ Ошибка загрузки данных")
            return
        
        # Проверяем наличие необходимых полей
        boss_name = user.get('boss_name', 'Неизвестный босс')
        boss_hp = user.get('boss_hp', 0)
        boss_max = user.get('boss_max', 1)
        boss_level = user.get('boss_level', 1)
        boss_ability = user.get('boss_ability', 'Нет информации')
        
        # Рассчитываем стратегию против босса
        strategy = calculate_boss_strategy(user, boss_level)
        
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
        
        logging.info(f"Отправляю сообщение: {message_text}")
        
        msg = await update.message.reply_text(
            message_text,
            reply_markup=MAIN_KEYBOARD,
            parse_mode='Markdown'
        )
        
        # Автоудаление ответа
        context.application.create_task(
            auto_delete(context, update.effective_chat.id, [msg.message_id])
        )
        
        logging.info("Сообщение успешно отправлено")
        
    except Exception as e:
        logging.error(f"КРИТИЧЕСКАЯ ОШИБКА в функции boss: {e}", exc_info=True)
        await update.message.reply_text(
            "❌ Произошла ошибка при получении информации о боссе. Попробуйте позже.",
            reply_markup=MAIN_KEYBOARD
        )


async def attack(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /attack"""
    try:
        username = update.effective_user.username or update.effective_user.full_name
        logging.info(f"=== НАЧАЛО АТАКИ === Пользователь: {username}")
        
        # Получаем пользователя
        user = await get_user(update.effective_user.id, username)
        logging.info(f"Пользователь получен: {user['username']}, HP: {user['hp']}")
        
        # Рассчитываем характеристики
        stats = calculate_character_stats(user)
        logging.info(f"Характеристики рассчитаны: max_hp={stats['max_hp']}")
        
        # Проверяем HP
        if user["hp"] <= 0:
            await update.message.reply_text("💀 Ты мёртв")
            return
        logging.info(f"HP пользователя: {user['hp']}/{stats['max_hp']}")

        # Проверяем уровень босса
        logging.info(f"Босс: {user['boss_name']}, HP: {user['boss_hp']}/{user['boss_max']}, уровень: {user['boss_level']}")
        
        # Проверка уровня
        if not check_level_restriction(user["level"], user["boss_level"], user["boss_level"]):
            await update.message.reply_text("❌ Босс слишком сильный для тебя")
            return
        logging.info("Проверка уровня пройдена")

        # Форматируем информацию о боссе
        boss_info = format_boss_info(user)
        logging.info(f"Информация о боссе сформирована: {boss_info[:100]}...")
        
        # Рассчитываем урон игрока
        dmg, is_crit = calculate_damage(user)
        logging.info(f"Урон игрока рассчитан: {dmg}, крит: {is_crit}")
        
        # Рассчитываем HP босса после атаки
        boss_hp = user["boss_hp"] - dmg
        total_boss_dmg = user["boss_dmg"] + dmg
        logging.info(f"HP босса после атаки: {boss_hp}/{user['boss_max']}")
        
        # Формируем текст атаки
        text = boss_info + f"⚔️ {user['username']} нанёс {dmg} урона"
        if is_crit:
            text += "\n" + get_meme_message("crit")
        logging.info("Текст атаки сформирован")

        # Атака босса
        # Проверяем тип boss_dmg - может быть числом или диапазоном
        boss_dmg = user["boss_dmg"]
        if isinstance(boss_dmg, int):
            # Если boss_dmg - это число, используем его как максимальный урон
            boss_attack = random.randint(1, boss_dmg)
        elif isinstance(boss_dmg, (list, tuple)) and len(boss_dmg) == 2:
            # Если boss_dmg - это диапазон [min, max], используем как есть
            boss_attack = random.randint(boss_dmg[0], boss_dmg[1])
        else:
            # По умолчанию - случайный урон от 1 до 10
            boss_attack = random.randint(1, 10)
        
        text += f"\n👹 Босс контратакует на {boss_attack} урона"
        logging.info(f"Урон босса: {boss_attack}")
        
        # Проверка уклонения
        if calculate_dodge(user):
            text += f"\n🛡️ {user['username']} уклонился от атаки!"
            user_hp = user["hp"]
            logging.info("Игрок уклонился от атаки")
        else:
            user_hp = user["hp"] - boss_attack
            text += f"\n💥 Босс попал!"
            logging.info(f"Игрок получил урон: {boss_attack}, HP: {user_hp}/{stats['max_hp']}")
            
            if user_hp <= 0:
                text += "\n" + get_meme_message("death")
                user_hp = 0

        # Проверка смерти босса
        if boss_hp <= 0:
            boss_name = user["boss_name"]
            text += f"\n" + get_meme_message("boss_kill", boss=boss_name)
            logging.info(f"Босс {boss_name} повержен!")
            
            # Адаптированные награды
            gold_reward, exp_reward = calculate_boss_reward(boss_name)
            logging.info(f"Награда: {gold_reward} золота, {exp_reward} опыта")
            
            user_gold = user["gold"] + gold_reward
            user_exp = user["exp"] + exp_reward
            
            # Увеличиваем счетчик убитых боссов
            bosses_killed = user.get("bosses_killed", 0) + 1
            
            new_boss = spawn_boss()
            boss_hp = new_boss["hp"]
            boss_name = new_boss["name"]
            boss_max = new_boss["max"]
            boss_level = new_boss["min_level"]
            boss_dmg = 0
            boss_ability = new_boss["ability"]
            logging.info(f"Новый босс: {boss_name}, HP: {boss_hp}/{boss_max}, уровень: {boss_level}")
            
            # Проверка уровня
            if check_level_up(user):
                user_level = user["level"] + 1
                user_hp_max = stats["max_hp"] + 20  # +20 HP за уровень
                user_hp = user_hp_max
                text += f"\n🎉 Достигнут уровень {user_level}!"
                logging.info(f"Пользователь достиг уровня {user_level}")
            else:
                user_level = user["level"]
                user_hp_max = stats["max_hp"]
        else:
            user_gold = user["gold"]
            user_exp = user["exp"]
            bosses_killed = user.get("bosses_killed", 0)
            boss_name = user["boss_name"]
            boss_max = user["boss_max"]
            boss_level = user["boss_level"]
            boss_ability = user["boss_ability"]
            user_level = user["level"]
            user_hp_max = stats["max_hp"]

        # Восстановление HP до 100% и установка кулдауна
        text += f"\n💚 Вы восстановили HP до 100%\n"
        text += f"⏳ Босс кулдаун: 1 минута\n"
        logging.info(f"Финальные данные: HP: {user_hp_max}/{user_hp_max}, уровень: {user_level}, золото: {user_gold}, опыт: {user_exp}")

        # Обновляем данные
        await update_user(
            update.effective_user.id,
            hp=user_hp_max,  # Восстанавливаем HP до максимума
            hp_max=user_hp_max,
            level=user_level,
            exp=user_exp,
            boss_hp=boss_hp,
            boss_name=boss_name,
            boss_max=boss_max,
            boss_level=boss_level,
            boss_dmg=total_boss_dmg,  # Сохраняем общее количество урона по боссу
            boss_ability=boss_ability,
            gold=user_gold,
            bosses_killed=bosses_killed
        )
        logging.info("Данные пользователя успешно обновлены")
        
        msg = await update.message.reply_text(text)
        # Автоудаление ответа
        context.application.create_task(
            auto_delete(context, update.effective_chat.id, [msg.message_id])
        )
        logging.info("Сообщение об атаке успешно отправлено")
        
    except Exception as e:
        logging.error(f"КРИТИЧЕСКАЯ ОШИБКА в функции attack: {e}", exc_info=True)
        await update.message.reply_text(
            "❌ Произошла ошибка при атаке босса. Попробуйте позже.",
            reply_markup=MAIN_KEYBOARD
        )


async def shop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /shop"""
    msg = await update.message.reply_text("🛒 Выберите категорию:", reply_markup=SHOP_CATEGORIES_KEYBOARD)
    # Автоудаление ответа
    context.application.create_task(
        auto_delete(context, update.effective_chat.id, [msg.message_id])
    )


async def show_category_items(update: Update, context: ContextTypes.DEFAULT_TYPE, category: str):
    """Показывает предметы в выбранной категории"""
    items_in_category = get_items_by_category(category)
    if not items_in_category:
        await update.message.reply_text("❌ В этой категории нет предметов")
        return
    
    text = f"🛒 {category}:\n\n"
    for item_name, item_data in items_in_category.items():
        text += f"🗡️ {item_name}\n"
        text += f"   💰 {item_data['gold']}g\n"
        if 'description' in item_data:
            text += f"   📖 {item_data['description']}\n"
        if 'dmg' in item_data:
            text += f"   ⚔️ +{item_data['dmg']} урона\n"
        if 'str' in item_data:
            text += f"   💪 +{item_data['str']} силы\n"
        if 'agi' in item_data:
            text += f"   🏃‍♂️ +{item_data['agi']} ловкости\n"
        if 'int' in item_data:
            text += f"   🧠 +{item_data['int']} интеллекта\n"
        if 'hp' in item_data:
            text += f"   ❤️ +{item_data['hp']} HP\n"
        if 'crit' in item_data:
            text += f"   🎯 +{item_data['crit']}% крита\n"
        if 'dodge' in item_data:
            text += f"   🛡️ +{item_data['dodge']}% уклонения\n"
        if 'heal' in item_data:
            text += f"   💚 +{item_data['heal']} HP\n"
        if 'exp' in item_data:
            text += f"   📚 +{item_data['exp']} опыта\n"
        text += "\n"
    text += "/buy ITEM — купить предмет"
    await update.message.reply_text(text)


async def buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /buy"""
    username = update.effective_user.username or update.effective_user.full_name
    user = await get_user(update.effective_user.id, username)
    stats = calculate_character_stats(user)
    
    try:
        item_name = context.args[0] if context.args else None
    except:
        await update.message.reply_text("❌ Укажите предмет для покупки")
        return

    if item_name not in get_items_by_category("Все"):
        await update.message.reply_text("❌ Нет такого предмета")
        return

    item_data = get_items_by_category("Все")[item_name]
    cost = item_data["gold"]
    
    if user["gold"] < cost:
        await update.message.reply_text("💰 Мало золота")
        return

    # Проверка слотов
    items = user["items"] if user["items"] else [None] * 6
    if None not in items:
        await update.message.reply_text("🎒 Слоты заняты")
        return

    # Покупка предмета
    items[items.index(None)] = item_name
    await update_user(update.effective_user.id, items=items, gold=user["gold"] - cost)
    msg = await update.message.reply_text(f"✅ Куплен {item_name}")
    # Автоудаление ответа
    context.application.create_task(
        auto_delete(context, update.effective_chat.id, [msg.message_id])
    )


async def potion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /potion"""
    username = update.effective_user.username or update.effective_user.full_name
    user = await get_user(update.effective_user.id, username)
    stats = calculate_character_stats(user)
    
    try:
        potion_type = context.args[0] if context.args else None
    except:
        await update.message.reply_text("❌ Укажите тип зелья (Minor/Major/Ultimate)")
        return

    potion_data = get_potion_data(potion_type)
    if not potion_data:
        await update.message.reply_text("❌ Нет такого зелья")
        return

    cost = potion_data["gold"]
    
    if user["gold"] < cost:
        await update.message.reply_text("💰 Мало золота")
        return

    # Покупка зелья
    new_hp = min(user["hp"] + potion_data["heal"], stats["max_hp"])
    await update_user(update.effective_user.id, hp=new_hp, gold=user["gold"] - cost)
    msg = await update.message.reply_text(f"🧪 {potion_type} зелье использовано. HP восстановлено")
    # Автоудаление ответа
    context.application.create_task(
        auto_delete(context, update.effective_chat.id, [msg.message_id])
    )


async def heal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /heal"""
    username = update.effective_user.username or update.effective_user.full_name
    user = await get_user(update.effective_user.id, username)
    stats = calculate_character_stats(user)
    
    # Регенерация HP
    new_hp, last_heal = regenerate_hp(user)
    if new_hp != user["hp"]:
        await update_user(update.effective_user.id, hp=new_hp, last_heal=last_heal)
        msg = await update.message.reply_text(f"💚 HP восстановлено до {new_hp}/{stats['max_hp']}")
        # Автоудаление ответа
        context.application.create_task(
            auto_delete(context, update.effective_chat.id, [msg.message_id])
        )
    else:
        msg = await update.message.reply_text("💚 HP уже восстановлено")
        # Автоудаление ответа
        context.application.create_task(
            auto_delete(context, update.effective_chat.id, [msg.message_id])
        )


async def pvp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /pvp"""
    username = update.effective_user.username or update.effective_user.full_name
    user = await get_user(update.effective_user.id, username)
    stats = calculate_character_stats(user)
    
    # Получаем список игроков для PvP (исключая самого пользователя)
    from database import db_pool
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT username, mmr, level, str, agi, int, hp, hp_max, user_id
            FROM users 
            WHERE user_id != $1 AND mmr >= $2
            ORDER BY mmr DESC
            LIMIT 10
        """, str(update.effective_user.id), user["mmr"] * 0.5)
    
    if not rows:
        await update.message.reply_text("❌ Нет доступных противников")
        return
    
    text = "⚔️ Доступные противники для PvP:\n\n"
    for i, row in enumerate(rows, 1):
        # Создаем временного пользователя для расчета характеристик противника
        enemy_user = {
            "username": row['username'],
            "mmr": row['mmr'],
            "level": row['level'],
            "str": row['str'],
            "agi": row['agi'],
            "int": row['int'],
            "hp": row['hp'],
            "hp_max": row['hp_max'],
            "items": [None] * 6  # Предполагаем, что у противника нет предметов для упрощения
        }
        enemy_stats = calculate_character_stats(enemy_user)
        
        # Рассчитываем преимущество
        advantage = calculate_pvp_advantage(user, enemy_user)
        
        text += f"{i}. 👤 {row['username']}\n"
        text += f"   📊 MMR: {row['mmr']} | Уровень: {row['level']}\n"
        text += f"   💪 STR: {row['str']} | 🏃‍♂️ AGI: {row['agi']} | 🧠 INT: {row['int']}\n"
        text += f"   ❤️ HP: {row['hp']}/{row['hp_max']}\n"
        text += f"   ⚔️ Урон: {enemy_stats['base_damage']} | 🛡️ Уклон: {enemy_stats['dodge_chance']:.1f}%\n"
        
        # Показываем преимущество
        if advantage["advantage"] > 5:
            text += f"   🎯 Вы в преимуществе: +{advantage['advantage']:.1f}%\n"
        elif advantage["advantage"] < -5:
            text += f"   ⚠️ Вы в劣势е: {advantage['advantage']:.1f}%\n"
        else:
            text += f"   ⚖️ Равные шансы\n"
        
        text += f"   /fight_{row['user_id']} — сразиться\n\n"
    
    msg = await update.message.reply_text(text)
    # Автоудаление ответа
    context.application.create_task(
        auto_delete(context, update.effective_chat.id, [msg.message_id])
    )


async def handle_pvp_fight(update: Update, context: ContextTypes.DEFAULT_TYPE, enemy_id: int):
    """Обработчик PvP боя по кнопке из списка PvP"""
    username = update.effective_user.username or update.effective_user.full_name
    user1 = await get_user(update.effective_user.id, username)
    stats1 = calculate_character_stats(user1)
    
    # Получаем информацию о противнике из базы данных
    from database import db_pool
    async with db_pool.acquire() as conn:
        enemy_data = await conn.fetchrow("SELECT username FROM users WHERE user_id = $1", str(enemy_id))
        enemy_username = enemy_data["username"] if enemy_data else f"Player{enemy_id}"
    
    user2 = await get_user(enemy_id, enemy_username)
    stats2 = calculate_character_stats(user2)
    
    if time.time() - user1["last_pvp"] < 600:
        await update.message.reply_text("⏳ КД PvP")
        return

    # Проверка MMR
    if user2["mmr"] < user1["mmr"] * 0.5:
        await update.message.reply_text("❌ Противник слишком слабый")
        return

    # Информация о противнике
    text = f"👤 Противник: {user2['username']}\n"
    text += f"📊 MMR: {user2['mmr']} | Уровень: {user2['level']}\n"
    text += f"💪 STR: {user2['str']} | 🏃‍♂️ AGI: {user2['agi']} | 🧠 INT: {user2['int']}\n"
    text += f"❤️ HP: {user2['hp']}/{user2['hp_max']}\n"
    text += f"🎒 Экипировка: {', '.join([item or 'Пусто' for item in user2['items']]) if user2['items'] else 'Пусто'}\n\n"
    
    # Боевые действия с короткими логами
    text += "⚔️ БОЙ НАЧАЛСЯ!\n\n"
    
    # Раунд 1
    dmg1, is_crit1 = calculate_damage(user1)
    dmg2, is_crit2 = calculate_damage(user2)
    
    text += f"1. {user1['username']} наносит {dmg1} урона\n"
    if is_crit1:
        text += "   💥 КРИТ! Я инвестировал в урон\n"
    
    user2_hp = max(0, user2["hp"] - dmg1)
    text += f"2. {user2['username']} наносит {dmg2} урона\n"
    if is_crit2:
        text += "   💥 КРИТ! Я инвестировал в урон\n"
    
    user1_hp = max(0, user1["hp"] - dmg2)
    
    # Раунд 2
    if user1_hp > 0 and user2_hp > 0:
        dmg1, is_crit1 = calculate_damage(user1)
        dmg2, is_crit2 = calculate_damage(user2)
        
        text += f"3. {user1['username']} наносит {dmg1} урона\n"
        if is_crit1:
            text += "   💥 КРИТ! Я инвестировал в урон\n"
        
        user2_hp = max(0, user2_hp - dmg1)
        text += f"4. {user2['username']} наносит {dmg2} урона\n"
        if is_crit2:
            text += "   💥 КРИТ! Я инвестировал в урон\n"
        
        user1_hp = max(0, user1_hp - dmg2)
    
    # Определение победителя
    if user1_hp > user2_hp:
        winner = user1
        loser = user2
        text += f"\n🏆 ПОБЕДИТЕЛЬ: {user1['username']}!\n"
    else:
        winner = user2
        loser = user1
        text += f"\n🏆 ПОБЕДИТЕЛЬ: {user2['username']}!\n"
    
    # Передача MMR и опыта
    mmr_change = 20
    exp_change = 50
    
    winner_mmr = winner["mmr"] + mmr_change
    loser_mmr = loser["mmr"] - mmr_change
    winner_exp = winner["exp"] + exp_change
    loser_exp = loser["exp"] + exp_change // 2  # Проигравший получает немного опыта
    
    text += f"\n📊 ИЗМЕНЕНИЯ:\n"
    text += f"🥇 {winner['username']}: +{mmr_change} MMR, +{exp_change} EXP\n"
    text += f"🥈 {loser['username']}: -{mmr_change} MMR, +{exp_change // 2} EXP\n"
    
    # Восстановление HP до 100% и установка кулдауна
    text += f"\n💚 Оба игрока восстановили HP до 100%\n"
    text += f"⏳ PvP кулдаун: 5 минут\n"
    
    # Шутка в конце
    jokes = [
        "Шутка: Проигравший теперь знает, что ботинки нужно завязывать tighter!",
        "Шутка: Победитель теперь может хвастаться, что он сильнее, чем его противник!",
        "Шутка: Проигравший обещал купить себе лучшие предметы и вернуться за реваншем!",
        "Шутка: Победитель теперь может позволить себе купить новое зелье!",
        "Шутка: Проигравший сказал, что это была тактическая сдача!"
    ]
    text += f"\n{random.choice(jokes)}"
    
    # Обновление данных
    await update_user(update.effective_user.id, hp=stats1["max_hp"], mmr=winner_mmr if winner == user1 else loser_mmr, exp=winner_exp if winner == user1 else loser_exp, last_pvp=time.time())
    await update_user(enemy_id, hp=stats2["max_hp"], mmr=winner_mmr if winner == user2 else loser_mmr, exp=winner_exp if winner == user2 else loser_exp, last_pvp=time.time())
    
    msg = await update.message.reply_text(text)
    # Автоудаление ответа
    context.application.create_task(
        auto_delete(context, update.effective_chat.id, [msg.message_id])
    )


async def fight(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /fight"""
    username = update.effective_user.username or update.effective_user.full_name
    user1 = await get_user(update.effective_user.id, username)
    stats1 = calculate_character_stats(user1)
    
    try:
        enemy_id = int(context.args[0]) if context.args else None
    except:
        await update.message.reply_text("❌ Укажите ID противника")
        return

    user2 = await get_user(enemy_id, f"Player{enemy_id}")
    stats2 = calculate_character_stats(user2)
    
    if time.time() - user1["last_pvp"] < 600:
        await update.message.reply_text("⏳ КД PvP")
        return

    # Проверка MMR
    if user2["mmr"] < user1["mmr"] * 0.5:
        await update.message.reply_text("❌ Противник слишком слабый")
        return

    # Информация о противнике
    text = f"👤 Противник: {user2['username']}\n"
    text += f"📊 MMR: {user2['mmr']} | Уровень: {user2['level']}\n"
    text += f"💪 STR: {user2['str']} | 🏃‍♂️ AGI: {user2['agi']} | 🧠 INT: {user2['int']}\n"
    text += f"❤️ HP: {user2['hp']}/{user2['hp_max']}\n"
    text += f"🎒 Экипировка: {', '.join([item or 'Пусто' for item in user2['items']]) if user2['items'] else 'Пусто'}\n\n"
    
    # Боевые действия с короткими логами
    text += "⚔️ БОЙ НАЧАЛСЯ!\n\n"
    
    # Раунд 1
    dmg1, is_crit1 = calculate_damage(user1)
    dmg2, is_crit2 = calculate_damage(user2)
    
    text += f"1. {user1['username']} наносит {dmg1} урона\n"
    if is_crit1:
        text += "   💥 КРИТ! Я инвестировал в урон\n"
    
    user2_hp = max(0, user2["hp"] - dmg1)
    text += f"2. {user2['username']} наносит {dmg2} урона\n"
    if is_crit2:
        text += "   💥 КРИТ! Я инвестировал в урон\n"
    
    user1_hp = max(0, user1["hp"] - dmg2)
    
    # Раунд 2
    if user1_hp > 0 and user2_hp > 0:
        dmg1, is_crit1 = calculate_damage(user1)
        dmg2, is_crit2 = calculate_damage(user2)
        
        text += f"3. {user1['username']} наносит {dmg1} урона\n"
        if is_crit1:
            text += "   💥 КРИТ! Я инвестировал в урон\n"
        
        user2_hp = max(0, user2_hp - dmg1)
        text += f"4. {user2['username']} наносит {dmg2} урона\n"
        if is_crit2:
            text += "   💥 КРИТ! Я инвестировал в урон\n"
        
        user1_hp = max(0, user1_hp - dmg2)
    
    # Определение победителя
    if user1_hp > user2_hp:
        winner = user1
        loser = user2
        text += f"\n🏆 ПОБЕДИТЕЛЬ: {user1['username']}!\n"
    else:
        winner = user2
        loser = user1
        text += f"\n🏆 ПОБЕДИТЕЛЬ: {user2['username']}!\n"
    
    # Передача MMR и опыта
    mmr_change = 20
    exp_change = 50
    
    winner_mmr = winner["mmr"] + mmr_change
    loser_mmr = loser["mmr"] - mmr_change
    winner_exp = winner["exp"] + exp_change
    loser_exp = loser["exp"] + exp_change // 2  # Проигравший получает немного опыта
    
    text += f"\n📊 ИЗМЕНЕНИЯ:\n"
    text += f"🥇 {winner['username']}: +{mmr_change} MMR, +{exp_change} EXP\n"
    text += f"🥈 {loser['username']}: -{mmr_change} MMR, +{exp_change // 2} EXP\n"
    
    # Восстановление HP до 100% и установка кулдауна
    text += f"\n💚 Оба игрока восстановили HP до 100%\n"
    text += f"⏳ PvP кулдаун: 5 минут\n"
    
    # Шутка в конце
    jokes = [
        "Шутка: Проигравший теперь знает, что ботинки нужно завязывать tighter!",
        "Шутка: Победитель теперь может хвастаться, что он сильнее, чем его противник!",
        "Шутка: Проигравший обещал купить себе лучшие предметы и вернуться за реваншем!",
        "Шутка: Победитель теперь может позволить себе купить новое зелье!",
        "Шутка: Проигравший сказал, что это была тактическая сдача!"
    ]
    text += f"\n{random.choice(jokes)}"
    
    # Обновление данных
    await update_user(update.effective_user.id, hp=stats1["max_hp"], mmr=winner_mmr if winner == user1 else loser_mmr, exp=winner_exp if winner == user1 else loser_exp, last_pvp=time.time())
    await update_user(enemy_id, hp=stats2["max_hp"], mmr=winner_mmr if winner == user2 else loser_mmr, exp=winner_exp if winner == user2 else loser_exp, last_pvp=time.time())
    
    msg = await update.message.reply_text(text)
    # Автоудаление ответа
    context.application.create_task(
        auto_delete(context, update.effective_chat.id, [msg.message_id])
    )


async def top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /top"""
    # Показываем топ по росту фиссуры
    rows = await get_fissure_top()
    if not rows:
        await update.message.reply_text("Топ пуст 😢")
        return
    
    text = ["🏆 ТОП по длине фиссуры:\n"]
    for i, row in enumerate(rows, 1):
        text.append(f"{i}. 👤 {row['username']} — {row['fissure']:.1f} см")
    
    msg = await update.message.reply_text("\n".join(text))
    # Автоудаление ответа
    context.application.create_task(
        auto_delete(context, update.effective_chat.id, [msg.message_id])
    )


async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /profile"""
    username = update.effective_user.username or update.effective_user.full_name
    user = await get_user(update.effective_user.id, username)
    stats = calculate_character_stats(user)
    
    text = format_stats_text(user, stats)
    
    msg = await update.message.reply_text(text)
    # Автоудаление ответа
    context.application.create_task(
        auto_delete(context, update.effective_chat.id, [msg.message_id])
    )


# ================= MESSAGE HANDLERS =================

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик текстовых сообщений"""
    text = update.message.text
    user_id = update.effective_user.id
    logging.info(f"=== ОБРАБОТКА СООБЩЕНИЯ ===")
    logging.info(f"Пользователь: {user_id}")
    logging.info(f"Текст: '{text}'")
    logging.info(f"Длина текста: {len(text)}")
    
    if text == "👹 BOSS":
        logging.info("Сработала обработка кнопки BOSS")
        await boss(update, context)
    elif text == "🛒 SHOP":
        await shop(update, context)
    elif text == "⚔️ PVP":
        await pvp(update, context)
    elif text == "🏆 TOP":
        await top(update, context)
    elif text == "👤 ПРОФИЛЬ":
        await profile(update, context)
    elif text == "📊 STATS":
        await stats(update, context)
    elif text == "🍆 FISSURE":
        await update.message.reply_text("🍆 Меню фиссуры", reply_markup=FISSURE_KEYBOARD)
    elif text == "🎲 ROLL":
        await fissure(update, context)
    elif text == "⬅️ НАЗАД":
        await update.message.reply_text("⬅️ Вернулись в главное меню", reply_markup=MAIN_KEYBOARD)
    # Обработка категорий магазина
    elif text == "👟 Сапоги":
        await show_category_items(update, context, "Сапоги")
    elif text == "🛡️ Броня":
        await show_category_items(update, context, "Броня")
    elif text == "🗡️ Оружие":
        await show_category_items(update, context, "Оружие")
    elif text == "🛡️ Защита":
        await show_category_items(update, context, "Защита")
    elif text == "🔮 Поддержка":
        await show_category_items(update, context, "Поддержка")
    elif text == "🧪 Зелья":
        await show_category_items(update, context, "Зелья")
    else:
        logging.warning(f"Неизвестная команда: '{text}'")
        await update.message.reply_text(
            f"Неизвестная команда. Используйте кнопки меню ниже.",
            reply_markup=MAIN_KEYBOARD
        )


async def handle_pvp_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик кнопок PvP из списка противников"""
    text = update.message.text
    if text.startswith("/fight_"):
        try:
            enemy_id = int(text.replace("/fight_", ""))
            await handle_pvp_fight(update, context, enemy_id)
        except ValueError:
            await update.message.reply_text("❌ Неверный ID противника")