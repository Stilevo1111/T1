import os
import json
import time
import random
import telebot
from telebot import types
from dotenv import load_dotenv
from threading import Thread
from http.server import HTTPServer, BaseHTTPRequestHandler
from items import items, get_all_items, get_item_info, format_item_description
from bosses import bosses, get_boss_by_name, get_random_boss, format_boss_info
from database import db

# Load .env file if it exists (for local development)
load_dotenv()

# Get token from environment variables (works both locally and on Render)
API_TOKEN = os.getenv("BOT_TOKEN")
DATA_FILE = "data.json"

if not API_TOKEN:
    print("Ошибка: BOT_TOKEN не найден в переменных окружения")
    print("Для локальной разработки: создайте файл .env с BOT_TOKEN=ваш_токен")
    print("Для Render: установите BOT_TOKEN в Environment Variables в настройках проекта")
    exit(1)

bot = telebot.TeleBot(API_TOKEN)

# ---------- AUTO-DELETE MESSAGES ----------
def schedule_message_deletion(chat_id, message_id, delay_seconds=30):
    """Schedule a message for deletion after a delay"""
    def delete_message():
        time.sleep(delay_seconds)
        try:
            bot.delete_message(chat_id, message_id)
        except Exception as e:
            # Message might already be deleted or other error
            pass
    
    # Run deletion in background thread
    Thread(target=delete_message, daemon=True).start()

def send_auto_delete_message(chat_id, text, delay_seconds=30, **kwargs):
    """Send a message that auto-deletes after delay"""
    msg = bot.send_message(chat_id, text, **kwargs)
    schedule_message_deletion(chat_id, msg.message_id, delay_seconds)
    return msg

# ---------- ХРАНЕНИЕ ----------
users = db.load_all()

def save(data=None):
    """Сохранить всех пользователей"""
    global users
    if data is not None:
        users = data
    db.save_all(users)

def save_user(user_id):
    """Сохранить конкретного пользователя"""
    user_id = str(user_id)
    if user_id in users:
        db.save_user(user_id, users[user_id])

def get_user(uid):
    uid = str(uid)
    if uid not in users:
        users[uid] = {
            "chat_mmr": 100,
            "wins": 0,
            "loses": 0,
            "fissure": 10.0,
            "last_fissure": 0,
            "inventory": [],  # список названий предметов
            "equipped": {},   # {"weapon": "Daedalus", "armor": None, ...}
            "boss_kills": 0,  # количество убитых боссов
            "last_raid": 0,   # время последнего рейда
            # Характеристики игрока
            "stats": {
                "strength": 10,      # Сила - влияет на урон
                "agility": 10,       # Ловкость - влияет на крит и уклонение
                "intelligence": 10,  # Интеллект - влияет на магический урон
                "crit_chance": 5,    # Шанс крита (%)
                "evasion": 5,        # Шанс уклонения (%)
                "armor": 0           # Броня - уменьшает получаемый урон
            }
        }
        save_user(uid)
    # Добавляем поля для старых пользователей
    if "inventory" not in users[uid]:
        users[uid]["inventory"] = []
    if "equipped" not in users[uid]:
        users[uid]["equipped"] = {}
    if "boss_kills" not in users[uid]:
        users[uid]["boss_kills"] = 0
    if "last_raid" not in users[uid]:
        users[uid]["last_raid"] = 0
    # Добавляем характеристики для старых пользователей
    if "stats" not in users[uid]:
        users[uid]["stats"] = {
            "strength": 10,
            "agility": 10,
            "intelligence": 10,
            "crit_chance": 5,
            "evasion": 5,
            "armor": 0
        }
    return users[uid]

# ---------- КНОПКИ ----------
def menu():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("👤 Профиль", "🌋 FISSURE")
    kb.add("⚔️ PvP", "🎰 Слоты")
    kb.add("👹 Рейд", "🎒 Инвентарь")
    kb.add("🏪 Магазин")
    return kb

# ---------- START ----------
@bot.message_handler(commands=["start"])
def start(msg):
    get_user(msg.from_user.id)
    bot.send_message(msg.chat.id, "🔥 Бот запущен\nFISSURE — мем, ни на что не влияет 😏", reply_markup=menu())

# ---------- ПРОФИЛЬ ----------
@bot.message_handler(func=lambda m: m.text == "👤 Профиль")
def profile(msg):
    u = get_user(msg.from_user.id)
    stats = u.get("stats", {})
    text = (
        f"👤 ПРОФИЛЬ\n\n"
        f"💬 Чат-MMR: {u['chat_mmr']}\n"
        f"🏆 Победы: {u['wins']}\n"
        f"💀 Поражения: {u['loses']}\n"
        f"👹 Боссов убито: {u.get('boss_kills', 0)}\n"
        f"🍆 FISSURE: {u['fissure']:.1f} см\n\n"
        f"📊 ХАРАКТЕРИСТИКИ:\n"
        f"💪 Сила: {stats.get('strength', 10)}\n"
        f"🤸 Ловкость: {stats.get('agility', 10)}\n"
        f"🧠 Интеллект: {stats.get('intelligence', 10)}\n"
        f"🎯 Крит: {stats.get('crit_chance', 5)}%\n"
        f"🛡 Уклонение: {stats.get('evasion', 5)}%\n"
        f"🛡 Броня: {stats.get('armor', 0)}"
    )
    bot.send_message(msg.chat.id, text)

# ---------- FISSURE ----------
@bot.message_handler(func=lambda m: m.text == "🌋 FISSURE")
def fissure(msg):
    u = get_user(msg.from_user.id)
    now = time.time()
    remaining = 86400 - (now - u["last_fissure"])
    if remaining > 0:
        h = int(remaining / 3600)
        m = int((remaining % 3600) / 60)
        if h > 0:
            bot.send_message(msg.chat.id, f"⏳ Через {h} ч. {m} мин.")
        else:
            bot.send_message(msg.chat.id, f"⏳ Через {m} мин.")
        return

    roll = random.choice([-5, -3, -1, 0, 1, 3, 5, 10])
    u["fissure"] = max(0.1, u["fissure"] + roll)
    u["last_fissure"] = now
    save_user(msg.from_user.id)

    texts = {
        10: "💀 ЛЕГЕНДА! +10 см!",
        5: "🎉 +5 см!",
        3: "🔥 +3 см",
        1: "🙂 +1 см",
        0: "🤷 Без изменений",
        -1: "😅 -1 см",
        -3: "📉 -3 см",
        -5: "💔 -5 см..."
    }
    
    # Дополнительные фразы
    phrases = {
        10: ["Растёт… решительно и без совета.", "Увеличилась… без лишних слов."],
        5: ["Растёт… и ничего не спрашивает.", "Увеличилась… без лишних слов."],
        3: ["Растёт… и ничего не спрашивает.", "Увеличилась… без лишних слов."],
        1: ["Растёт… и ничего не спрашивает.", "Увеличилась… без лишних слов."],
        0: ["Стоит на месте… зато уверенно.", "Ни вверх, ни вниз… просто наблюдает.", "На месте… как старый добрый друг."],
        -1: ["Сжалась… тихо так, но гордо.", "Сократился… но с достоинством.", "Сжалась… слегка, но метко."],
        -3: ["Сжалась… тихо так, но гордо.", "Сократился… но с достоинством.", "Сократился… скромно, но заметно."],
        -5: ["Сжалась… тихо так, но гордо.", "Сократился… но с достоинством.", "Сократился… скромно, но заметно."]
    }
    
    phrase = random.choice(phrases[roll])
    bot.send_message(msg.chat.id, f"{texts[roll]}\n{phrase}\n📏 Теперь {u['fissure']:.1f} см")

# ---------- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ДЛЯ БОЕВ ----------
def calculate_player_stats(u):
    """Рассчитывает боевые характеристики игрока"""
    stats = u.get("stats", {})
    inventory = u.get("inventory", [])
    
    # Базовые характеристики
    strength = stats.get("strength", 10)
    agility = stats.get("agility", 10)
    intelligence = stats.get("intelligence", 10)
    crit_chance = stats.get("crit_chance", 5)
    evasion = stats.get("evasion", 5)
    armor = stats.get("armor", 0)
    
    # Бонусы от предметов
    item_damage_bonus = 0
    item_defense_bonus = 0
    item_crit_bonus = 0
    item_evasion_bonus = 0
    
    for item_name in inventory:
        item_data = get_item_info(item_name)
        if item_data:
            item_damage_bonus += item_data.get("💪", 0) * 5  # Каждый 💪 дает +5 урона
            if "🛡" in item_data:
                item_defense_bonus += 10
            if "🎯" in item_data:
                item_crit_bonus += 5  # Каждый 🎯 дает +5% к криту
            if "🤸" in item_data:
                item_evasion_bonus += 5  # Каждый 🤸 дает +5% к уклонению
    
    # Итоговые характеристики
    total_damage = 20 + (u['fissure'] * 2) + (strength * 2) + item_damage_bonus
    total_hp = 100 + (u['chat_mmr'] // 10) + (strength * 5)
    total_crit = crit_chance + (agility // 2) + item_crit_bonus
    total_evasion = evasion + (agility // 3) + item_evasion_bonus
    total_armor = armor + item_defense_bonus + (intelligence // 2)
    
    return {
        "damage": max(1, total_damage),
        "hp": max(1, total_hp),
        "crit_chance": min(95, total_crit),  # Максимум 95% крита
        "evasion": min(50, total_evasion),  # Максимум 50% уклонения
        "armor": max(0, total_armor)
    }

def calculate_damage_with_stats(player_stats, target_defense, is_crit=False):
    """Рассчитывает урон с учетом характеристик"""
    base_damage = player_stats["damage"]
    if is_crit:
        base_damage *= 2
    
    # Учет защиты цели
    final_damage = max(1, base_damage - target_defense)
    return final_damage

def check_evasion(evasion_chance):
    """Проверяет уклонение"""
    return random.randint(1, 100) <= evasion_chance

# ---------- PvP ----------
@bot.message_handler(func=lambda m: m.text == "⚔️ PvP")
def pvp_menu(msg):
    u = get_user(msg.from_user.id)
    
    # Проверка MMR
    if u["chat_mmr"] < 10:
        bot.send_message(msg.chat.id, "❌ Нужно минимум 10 чат-MMR")
        return
    
    # Проверка дневного лимита
    now = time.time()
    today = time.strftime("%Y-%m-%d", time.localtime(now))
    last_reset = u.get("pvp_last_reset", "")
    pvp_today = u.get("pvp_today", 0)
    
    # Сброс лимита если новый день
    if last_reset != today:
        u["pvp_today"] = 0
        u["pvp_last_reset"] = today
        pvp_today = 0
    
    # Проверка лимита
    if pvp_today >= 3:
        hours_left = 24 - time.localtime(now).tm_hour
        bot.send_message(msg.chat.id, f"❌ Дневной лимит PvP исчерпан! (3 боя)\n🔄 Сброс через {hours_left} часов")
        return
    
    # Меню PvP
    text = "⚔️ PVP АРЕНА\n\n"
    text += f"💰 Ваш баланс: {u['chat_mmr']} MMR\n"
    text += f"⚔️ Бои сегодня: {pvp_today}/3\n\n"
    text += "Выберите оппонента:\n"
    text += "• /pvp_bot - Бой с ботом\n"
    text += "• /pvp_random - Случайный игрок\n"
    text += "• /pvp_stats - Статистика PvP"
    
    bot.send_message(msg.chat.id, text)

@bot.message_handler(func=lambda m: m.text == "/pvp_stats")
def pvp_stats(msg):
    u = get_user(msg.from_user.id)
    win_rate = 0
    if u["wins"] + u["loses"] > 0:
        win_rate = round((u["wins"] / (u["wins"] + u["loses"])) * 100, 1)
    
    text = "📊 СТАТИСТИКА ПВП\n\n"
    text += f"🏆 Побед: {u['wins']}\n"
    text += f"💀 Поражений: {u['loses']}\n"
    text += f"📈 Винрейт: {win_rate}%\n"
    text += f"⚔️ Бои сегодня: {u.get('pvp_today', 0)}/3"
    
    bot.send_message(msg.chat.id, text)

@bot.message_handler(func=lambda m: m.text == "/pvp_bot")
def pvp_bot(msg):
    u = get_user(msg.from_user.id)
    
    # Проверка MMR
    if u["chat_mmr"] < 10:
        bot.send_message(msg.chat.id, "❌ Нужно минимум 10 чат-MMR")
        return
    
    # Проверка дневного лимита
    now = time.time()
    today = time.strftime("%Y-%m-%d", time.localtime(now))
    last_reset = u.get("pvp_last_reset", "")
    pvp_today = u.get("pvp_today", 0)
    
    if last_reset != today:
        u["pvp_today"] = 0
        u["pvp_last_reset"] = today
        pvp_today = 0
    
    if pvp_today >= 3:
        hours_left = 24 - time.localtime(now).tm_hour
        bot.send_message(msg.chat.id, f"❌ Дневной лимит PvP исчерпан! (3 боя)\n🔄 Сброс через {hours_left} часов")
        return
    
    # Генерируем виртуального бота
    bot_names = [
        "🔥 Огненный Рыцарь", "⚡ Молниеносный", "🛡 Стальной Страж", 
        "🗡 Теневой Убийца", "🏹 Лучник Смерти", "🔨 Молот Грома",
        "🌪 Буревой Волк", "🧊 Ледяной Дракон", "💀 Костяной Король"
    ]
    
    bot_name = random.choice(bot_names)
    
    # Характеристики бота зависят от MMR игрока
    if u["chat_mmr"] < 50:
        bot_hp = random.randint(80, 120)
        bot_damage = random.randint(15, 25)
        bot_defense = random.randint(5, 10)
        bot_win_chance = 40
    elif u["chat_mmr"] < 200:
        bot_hp = random.randint(120, 180)
        bot_damage = random.randint(20, 35)
        bot_defense = random.randint(10, 15)
        bot_win_chance = 55
    else:
        bot_hp = random.randint(180, 250)
        bot_damage = random.randint(30, 50)
        bot_defense = random.randint(15, 25)
        bot_win_chance = 70
    
    # Бой с ботом
    u["pvp_today"] = pvp_today + 1
    
    # Рассчитываем характеристики игрока с учетом статов
    player_stats = calculate_player_stats(u)
    player_hp = player_stats["hp"]
    player_damage = player_stats["damage"]
    player_crit = player_stats["crit_chance"]
    player_evasion = player_stats["evasion"]
    player_defense = player_stats["armor"]
    
    # Симуляция боя
    current_bot_hp = bot_hp
    current_player_hp = player_hp
    turns = 0
    max_turns = 20
    
    battle_log = f"⚔️ БОЙ С {bot_name.upper()}!\n\n"
    battle_log += f"👤 ВАШИ ХАРАКТЕРИСТИКИ:\n"
    battle_log += f"  ❤️ HP: {player_hp}\n"
    battle_log += f"  ⚔️ Урон: {int(player_damage)}\n"
    battle_log += f"  🎯 Крит: {player_crit}%\n"
    battle_log += f"  🛡 Уклонение: {player_evasion}%\n"
    battle_log += f"  🛡 Защита: {player_defense}\n\n"
    battle_log += f"👹 ХАРАКТЕРИСТИКИ БОТА:\n"
    battle_log += f"  ❤️ HP: {bot_hp}\n"
    battle_log += f"  ⚔️ Урон: {bot_damage}\n"
    battle_log += f"  🛡 Защита: {bot_defense}\n\n"
    
    while current_bot_hp > 0 and current_player_hp > 0 and turns < max_turns:
        turns += 1
        
        # Удар игрока
        # Проверяем крит
        is_crit = random.randint(1, 100) <= player_crit
        # Рассчитываем урон
        dmg = calculate_damage_with_stats(player_stats, bot_defense, is_crit)
        current_bot_hp -= dmg
        battle_log += f"Ход {turns}: Вы наносите {dmg} урона" + (" 💥 КРИТ!" if is_crit else "") + "\n"
        
        if current_bot_hp <= 0:
            break
        
        # Удар бота
        # Проверяем уклонение игрока
        if check_evasion(player_evasion):
            battle_log += f"       {bot_name} атакует, но вы уклоняетесь! 🤸\n"
        else:
            bot_dmg = random.randint(bot_damage - 2, bot_damage + 2)
            # Учет защиты игрока
            final_bot_dmg = max(1, bot_dmg - player_defense)
            current_player_hp -= final_bot_dmg
            battle_log += f"       {bot_name} наносит {final_bot_dmg} урона\n"
        
        if current_player_hp <= 0:
            break
    
    # Результат боя
    if current_bot_hp <= 0:
        # Победа
        u["chat_mmr"] += 30
        u["wins"] += 1
        win_phrases = [
            "Ты сегодня в ударе! 💪",
            "Бот плачет в углу! 😂",
            "Легко как 2 пальца! 👌",
            "Ты просто машина! 🤖",
            "Бот просит пощады! 🙏"
        ]
        battle_log += f"\n🎉 ПОБЕДА!\n"
        battle_log += f"{random.choice(win_phrases)}\n"
        battle_log += f"💰 +30 MMR\n"
        battle_log += f"📊 Баланс: {u['chat_mmr']} MMR"
    else:
        # Поражение
        u["chat_mmr"] -= 15
        u["loses"] += 1
        lose_phrases = [
            "Бот тебя уделал! 😵",
            "Позорище! 😳",
            "Ты сегодня не в форме! 🤡",
            "Бот смеется над тобой! 🤖",
            "Попробуй еще, может повезет! 🤞"
        ]
        battle_log += f"\n💀 ПОРАЖЕНИЕ!\n"
        battle_log += f"{random.choice(lose_phrases)}\n"
        battle_log += f"💰 -15 MMR\n"
        battle_log += f"📊 Баланс: {u['chat_mmr']} MMR"
    
    battle_log += f"\n⚔️ Бои сегодня: {u['pvp_today']}/3"
    
    save_user(msg.from_user.id)
    bot.send_message(msg.chat.id, battle_log)

@bot.message_handler(func=lambda m: m.text == "/pvp_random")
def pvp_random(msg):
    u = get_user(msg.from_user.id)
    
    # Проверка MMR
    if u["chat_mmr"] < 10:
        bot.send_message(msg.chat.id, "❌ Нужно минимум 10 чат-MMR")
        return
    
    # Проверка дневного лимита
    now = time.time()
    today = time.strftime("%Y-%m-%d", time.localtime(now))
    last_reset = u.get("pvp_last_reset", "")
    pvp_today = u.get("pvp_today", 0)
    
    if last_reset != today:
        u["pvp_today"] = 0
        u["pvp_last_reset"] = today
        pvp_today = 0
    
    if pvp_today >= 3:
        hours_left = 24 - time.localtime(now).tm_hour
        bot.send_message(msg.chat.id, f"❌ Дневной лимит PvP исчерпан! (3 боя)\n🔄 Сброс через {hours_left} часов")
        return
    
    # Поиск случайного противника (в реальной системе здесь был бы поиск по базе)
    # Для упрощения делаем симуляцию с "виртуальным" противником
    u["pvp_today"] = pvp_today + 1
    
    # Генерируем виртуального противника из мира Dota 2
    opponent_name = random.choice([
        "🔥 Лесной Тролль", "⚡ Молниеносный Гоблин", "🛡 Каменный Страж", 
        "🗡 Теневой Разбойник", "🏹 Лучник-Эльф", "🔨 Гном-Механик",
        "🌪 Волк-Призрак", "🧊 Ледяной Голем", "💀 Скелет-Воин"
    ])
    
    # Сложность противника
    opponent_level = random.choice(["слабый", "средний", "сильный"])
    
    if opponent_level == "слабый":
        player_win_chance = 70
    elif opponent_level == "средний":
        player_win_chance = 50
    else:
        player_win_chance = 30
    
    win = random.randint(1, 100) <= player_win_chance
    
    # Юмористические фразы для победы над игроком
    win_player_phrases = [
        "Ты просто легенда! 🤖",
        "Противник плачет! 😂",
        "Ты всех уделал! 💪",
        "Легко как бутылку открыть! 🍾",
        "Ты сегодня неудержим! 🚀"
    ]
    
    # Юмористические фразы для поражения от игрока
    lose_player_phrases = [
        "Тебя жестко уделали! 😵",
        "Противник слишком силён! 💀",
        "Ты сегодня не в форме! 🤡",
        "Позорище! 😳",
        "Попробуй тренироваться больше! 🏋️"
    ]
    
    if win:
        reward = random.randint(25, 45)  # Увеличил награду за игроков
        u["chat_mmr"] += reward
        u["wins"] += 1
        text = f"🏆 ПОБЕДА над {opponent_level} противником!\n{random.choice(win_player_phrases)}\n💰 +{reward} MMR"
    else:
        penalty = random.randint(12, 22)  # Увеличил штраф за игроков
        u["chat_mmr"] -= penalty
        u["loses"] += 1
        text = f"💀 ПОРАЖЕНИЕ от {opponent_level} противника!\n{random.choice(lose_player_phrases)}\n💰 -{penalty} MMR"
    
    text += f"\n📊 Баланс: {u['chat_mmr']} MMR"
    text += f"\n⚔️ Бои сегодня: {u['pvp_today']}/3"
    
    save_user(msg.from_user.id)
    bot.send_message(msg.chat.id, text)

# ---------- СЛОТЫ ----------
@bot.message_handler(func=lambda m: m.text == "🎰 Слоты")
def slots_menu(msg):
    u = get_user(msg.from_user.id)
    
    # Проверка MMR
    if u["chat_mmr"] < 5:
        bot.send_message(msg.chat.id, "❌ Нужно минимум 5 чат-MMR")
        return
    
    # Проверка дневного лимита
    now = time.time()
    today = time.strftime("%Y-%m-%d", time.localtime(now))
    last_reset = u.get("slots_last_reset", "")
    spins_today = u.get("slots_spins_today", 0)
    
    # Сброс лимита если новый день
    if last_reset != today:
        u["slots_spins_today"] = 0
        u["slots_last_reset"] = today
        spins_today = 0
    
    # Проверка лимита
    if spins_today >= 5:
        hours_left = 24 - time.localtime(now).tm_hour
        bot.send_message(msg.chat.id, f"❌ Дневной лимит исчерпан! (5 спинов)\n🔄 Сброс через {hours_left} часов")
        return
    
    # Меню слотов
    text = "🎰 СЛОТ-МАШИНА\n\n"
    text += f"💰 Ваш баланс: {u['chat_mmr']} MMR\n"
    text += f"🎰 Спины сегодня: {spins_today}/5\n\n"
    text += "Выберите ставку:\n"
    text += "• /spin_5 - Ставка 5 MMR (обычная)\n"
    text += "• /spin_10 - Ставка 10 MMR (премиум)\n"
    text += "• /spin_25 - Ставка 25 MMR (VIP)\n\n"
    text += "Чем выше ставка, тем больше шансы и выигрыши!"
    
    bot.send_message(msg.chat.id, text)

@bot.message_handler(func=lambda m: m.text.startswith("/spin_"))
def play_slots(msg):
    try:
        bet_amount = int(msg.text[6:])
    except:
        bot.send_message(msg.chat.id, "❌ Неверная ставка")
        return
    
    valid_bets = [5, 10, 25]
    if bet_amount not in valid_bets:
        bot.send_message(msg.chat.id, f"❌ Неверная ставка. Доступно: {valid_bets}")
        return
    
    u = get_user(msg.from_user.id)
    now = time.time()
    today = time.strftime("%Y-%m-%d", time.localtime(now))
    
    # Проверка MMR
    if u["chat_mmr"] < bet_amount:
        bot.send_message(msg.chat.id, f"❌ Недостаточно MMR. Нужно: {bet_amount}, у вас: {u['chat_mmr']}")
        return
    
    # Проверка дневного лимита
    last_reset = u.get("slots_last_reset", "")
    spins_today = u.get("slots_spins_today", 0)
    
    if last_reset != today:
        u["slots_spins_today"] = 0
        u["slots_last_reset"] = today
        spins_today = 0
    
    if spins_today >= 5:
        hours_left = 24 - time.localtime(now).tm_hour
        bot.send_message(msg.chat.id, f"❌ Дневной лимит исчерпан! (5 спинов)\n🔄 Сброс через {hours_left} часов")
        return
    
    # Спин!
    u["chat_mmr"] -= bet_amount
    u["slots_spins_today"] = spins_today + 1
    
    # Генерация результатов
    symbols = ["🍒", "🍋", "🍇", "🍉", "💎", "7️⃣", "👑"]
    reels = [random.choice(symbols) for _ in range(3)]
    
    # Анимация спина
    spin_msg = bot.send_message(msg.chat.id, "🎰 Кручу...")
    time.sleep(0.5)
    
    # Показываем результат
    result_line = f"🎰 | {' | '.join(reels)} |"
    bot.edit_message_text(result_line, chat_id=spin_msg.chat.id, message_id=spin_msg.message_id)
    
    # Определяем выигрыш
    if reels[0] == reels[1] == reels[2]:  # Джекпот (3 одинаковых)
        if reels[0] == "7️⃣":
            multiplier = 20
            emoji = "🎉"
            text = "🎰 ДЖЕКПОТ! 7️⃣7️⃣7️⃣"
        elif reels[0] == "👑":
            multiplier = 15
            emoji = "👑"
            text = "🎰 КОРОЛЕВСКИЙ! 👑👑👑"
        elif reels[0] == "💎":
            multiplier = 12
            emoji = "💎"
            text = "🎰 БРИЛЛИАНТ! 💎💎💎"
        else:
            multiplier = 8
            emoji = "✨"
            text = f"🎰 ТРИ {reels[0]}! {reels[0]}{reels[0]}{reels[0]}"
        
        win_amount = bet_amount * multiplier
        u["chat_mmr"] += win_amount
        
    elif reels[0] == reels[1] or reels[1] == reels[2] or reels[0] == reels[2]:  # Пара
        if "💎" in reels:
            multiplier = 4
            emoji = "💎"
            text = "🎰 ПАРА БРИЛЛИАНТОВ!"
        elif "7️⃣" in reels:
            multiplier = 3
            emoji = "7️⃣"
            text = "🎰 ПАРА СЕМИРОК!"
        else:
            multiplier = 2
            emoji = "✨"
            text = "🎰 ПАРА!"
        
        win_amount = bet_amount * multiplier
        u["chat_mmr"] += win_amount
        
    else:  # Проигрыш - может забрать дополнительные MMR
        loss_roll = random.randint(1, 100)
        if loss_roll > 70:  # 30% шанс проиграть дополнительно
            loss_multiplier = random.choice([1, 2, 3])  # 1x, 2x или 3x ставку
            loss_amount = bet_amount * loss_multiplier
            u["chat_mmr"] -= loss_amount
            emoji = "💀"
            text = f"🎰 ЧЕРНАЯ ПОЛОСА! -{loss_amount} MMR"
        else:  # 70% шанс просто проиграть ставку
            emoji = "💸"
            text = "🎰 МИМО!"
            loss_amount = 0  # Уже вычли ставку выше
    
    # Формируем сообщение
    if reels[0] == reels[1] == reels[2] or (reels[0] == reels[1] or reels[1] == reels[2] or reels[0] == reels[2]):
        result_text = f"{emoji} {text}\n\n"
        result_text += f"💰 Ставка: {bet_amount} MMR\n"
        result_text += f"💵 Выигрыш: {win_amount} MMR\n"
        result_text += f"📊 Баланс: {u['chat_mmr']} MMR"
    else:
        if loss_amount > 0:
            result_text = f"{emoji} {text}\n\n"
            result_text += f"💰 Ставка: {bet_amount} MMR\n"
            result_text += f"💸 Потери: {loss_amount} MMR\n"
            result_text += f"📊 Баланс: {u['chat_mmr']} MMR"
        else:
            result_text = f"{emoji} {text}\n\n"
            result_text += f"💰 Ставка: {bet_amount} MMR\n"
            result_text += f"📊 Баланс: {u['chat_mmr']} MMR"
    
    result_text += f"\n🎰 Спины сегодня: {u['slots_spins_today']}/5"
    
    bot.send_message(msg.chat.id, result_text)
    save_user(msg.from_user.id)

# ---------- ИНВЕНТАРЬ ----------
@bot.message_handler(func=lambda m: m.text == "🎒 Инвентарь")
def inventory(msg):
    u = get_user(msg.from_user.id)
    inv = u.get("inventory", [])
    stats = u.get("stats", {})
    
    text = "🎒 ИНВЕНТАРЬ\n\n"
    
    # Показываем характеристики игрока
    text += "📊 ВАШИ ХАРАКТЕРИСТИКИ:\n"
    text += f"💪 Сила: {stats.get('strength', 10)}\n"
    text += f"🤸 Ловкость: {stats.get('agility', 10)}\n"
    text += f"🧠 Интеллект: {stats.get('intelligence', 10)}\n"
    text += f"🎯 Крит: {stats.get('crit_chance', 5)}%\n"
    text += f"🛡 Уклонение: {stats.get('evasion', 5)}%\n"
    text += f"🛡 Броня: {stats.get('armor', 0)}\n\n"
    
    # Показываем 6 слотов
    text += "📦 ПРЕДМЕТЫ:\n"
    for i in range(6):
        if i < len(inv):
            item_name = inv[i]
            item_data = get_item_info(item_name)
            if item_data:
                text += f"📦 {item_name}\n"
                for key, value in item_data.items():
                    if key not in ["💰", "🎁"]:
                        text += f"  {key}: {value}\n"
        else:
            text += f"📦 ПУСТОЙ СЛОТ {i+1}\n"
        text += "\n"
    
    # Кнопка "Назад" в интерфейсе действий
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("⬅️ Назад")
    
    bot.send_message(msg.chat.id, text, reply_markup=kb)

# ---------- МАГАЗИН ----------
@bot.message_handler(func=lambda m: m.text == "🏪 Магазин")
def shop(msg):
    text = "🏪 МАГАЗИН АРТЕФАКТОВ\n\n"
    text += "Выберите категорию:\n\n"
    text += "🗡 /weapons - Оружие\n"
    text += "🛡 /armor - Броня\n"
    text += "👢 /boots - Ботинки\n"
    text += "💍 /artifacts - Артефакты\n"
    text += "🍀 /utility - Утилита\n"
    bot.send_message(msg.chat.id, text)

@bot.message_handler(commands=["weapons", "armor", "boots", "artifacts", "utility"])
def show_category(msg):
    category_map = {
        "weapons": "🗡 ОРУЖИЕ",
        "armor": "🛡 БРОНЯ",
        "boots": "👢 БОТИНКИ",
        "artifacts": "💍 АРТЕФАКТЫ",
        "utility": "🍀 УТИЛИТА"
    }
    
    cmd = msg.text[1:]  # убираем /
    if cmd not in items:
        return
    
    text = f"{category_map.get(cmd, cmd.upper())}\n\n"
    
    for item_name, item_data in items[cmd].items():
        text += f"▫️ **{item_name}**\n"
        for key, value in item_data.items():
            if key == "💰":
                text += f"  💰 {value} MMR\n"
            elif key != "🎁":
                text += f"  {key}: {value}\n"
        text += f"  Купить: /buy_{item_name.replace(' ', '_')}\n\n"
    
    # Кнопка "Назад" в интерфейсе действий
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("⬅️ Назад")
    
    bot.send_message(msg.chat.id, text, parse_mode="Markdown", reply_markup=kb)

@bot.message_handler(func=lambda m: m.text.startswith("/buy_"))
def buy_item(msg):
    item_name = msg.text[5:].replace("_", " ")
    item_data = get_item_info(item_name)
    
    if not item_data:
        bot.send_message(msg.chat.id, "❌ Предмет не найден")
        return
    
    u = get_user(msg.from_user.id)
    price = item_data.get("💰", 0)
    
    if u["chat_mmr"] < price:
        bot.send_message(msg.chat.id, f"❌ Недостаточно MMR\nНужно: {price}\nУ вас: {u['chat_mmr']}")
        return
    
    # Проверяем есть ли уже такой предмет
    if item_name in u.get("inventory", []):
        bot.send_message(msg.chat.id, f"❌ У вас уже есть {item_name}")
        return
    
    # Покупаем
    u["chat_mmr"] -= price
    if "inventory" not in u:
        u["inventory"] = []
    u["inventory"].append(item_name)
    save_user(msg.from_user.id)
    
    bot.send_message(msg.chat.id, f"✅ Куплено: {item_name}\n💰 Потрачено: {price} MMR\n💰 Осталось: {u['chat_mmr']} MMR")

# ---------- РЕЙД НА БОССОВ ----------
@bot.message_handler(func=lambda m: m.text == "👹 Рейд")
def raid_menu(msg):
    u = get_user(msg.from_user.id)
    now = time.time()
    cooldown = 3600  # 1 час
    remaining = cooldown - (now - u.get("last_raid", 0))
    
    if remaining > 0:
        m = int(remaining / 60)
        bot.send_message(msg.chat.id, f"⏳ Следующий рейд через {m} мин.")
        return
    
    # Получаем текущего босса (по количеству убитых)
    current_boss_index = u.get("boss_kills", 0) % len(bosses)
    current_boss = bosses[current_boss_index]
    
    text = "👹 РЕЙД НА БОССОВ\n\n"
    text += f"🏆 Ваш прогресс: {u.get('boss_kills', 0)} боссов убито\n\n"
    
    # Показываем прогресс по боссам
    total_bosses = len(bosses)
    current_boss_index = u.get("boss_kills", 0) % total_bosses
    next_boss_index = (current_boss_index + 1) % total_bosses
    
    text += f"📊 Прогресс: {current_boss_index + 1}/{total_bosses}\n"
    text += f"🎯 Следующий: {bosses[next_boss_index]['name']}\n\n"
    
    text += f"👹 ТЕКУЩИЙ БОСС:\n"
    text += f"**{current_boss['name']}** (HP: {current_boss['HP']})\n"
    text += f"⚔️ Урон: {current_boss['damage'][0]}-{current_boss['damage'][1]}\n"
    text += f"💫 Эффект: {current_boss['effect']}\n"
    text += f"🎁 Лут: {', '.join(current_boss['loot'])}\n\n"
    text += f"Атаковать: /raid_fight"
    
    bot.send_message(msg.chat.id, text, parse_mode="Markdown")

@bot.message_handler(func=lambda m: m.text == "/raid_fight")
def start_raid(msg):
    u = get_user(msg.from_user.id)
    now = time.time()
    cooldown = 3600  # 1 час
    remaining = cooldown - (now - u.get("last_raid", 0))
    
    if remaining > 0:
        m = int(remaining / 60)
        bot.send_message(msg.chat.id, f"⏳ Следующий рейд через {m} мин.")
        return
    
    # Получаем текущего босса (по количеству убитых)
    current_boss_index = u.get("boss_kills", 0) % len(bosses)
    boss = bosses[current_boss_index].copy()
    
    # Рассчитываем характеристики игрока с учетом статов
    player_stats = calculate_player_stats(u)
    player_hp = player_stats["hp"]
    player_damage = player_stats["damage"]
    player_crit = player_stats["crit_chance"]
    player_evasion = player_stats["evasion"]
    player_defense = player_stats["armor"]
    
    # Симуляция боя
    boss_hp = boss["HP"]
    turns = 0
    max_turns = 20
    
    battle_log = f"⚔️ БОЙ С {boss['name'].upper()}!\n\n"
    battle_log += f"🏆 Ваш прогресс: {u.get('boss_kills', 0)} боссов убито\n\n"
    battle_log += f"👤 ВАШИ ХАРАКТЕРИСТИКИ:\n"
    battle_log += f"  ❤️ HP: {player_hp}\n"
    battle_log += f"  ⚔️ Урон: {int(player_damage)}\n"
    battle_log += f"  🎯 Крит: {player_crit}%\n"
    battle_log += f"  🛡 Уклонение: {player_evasion}%\n"
    battle_log += f"  🛡 Защита: {player_defense}\n\n"
    battle_log += f"👹 ХАРАКТЕРИСТИКИ БОССА:\n"
    battle_log += f"  ❤️ HP: {boss_hp}\n"
    battle_log += f"  ⚔️ Урон: {boss['damage'][0]}-{boss['damage'][1]}\n"
    battle_log += f"  💫 Эффект: {boss['effect']}\n\n"
    
    while boss_hp > 0 and player_hp > 0 and turns < max_turns:
        turns += 1
        
        # Удар игрока
        # Проверяем крит
        is_crit = random.randint(1, 100) <= player_crit
        # Рассчитываем урон
        dmg = calculate_damage_with_stats(player_stats, 0, is_crit)  # Боссы не имеют защиты в этой системе
        boss_hp -= dmg
        battle_log += f"Ход {turns}: Вы наносите {dmg} урона" + (" 💥 КРИТ!" if is_crit else "") + "\n"
        
        if boss_hp <= 0:
            break
        
        # Удар босса
        # Проверяем уклонение игрока
        if check_evasion(player_evasion):
            battle_log += f"       {boss['name']} атакует, но вы уклоняетесь! 🤸\n"
        else:
            boss_dmg = random.randint(boss["damage"][0], boss["damage"][1])
            # Учет защиты игрока
            final_boss_dmg = max(1, boss_dmg - player_defense)
            player_hp -= final_boss_dmg
            battle_log += f"       {boss['name']} наносит {final_boss_dmg} урона\n"
        
        if player_hp <= 0:
            break
    
    # Результат
    if boss_hp <= 0:
        # Победа
        u["boss_kills"] = u.get("boss_kills", 0) + 1
        u["last_raid"] = now
        
        # Награды
        mmr_reward = random.randint(50, 150)
        u["chat_mmr"] += mmr_reward
        
        # Шанс дропа предмета
        drop_chance = 30  # 30%
        dropped_item = None
        if random.randint(1, 100) <= drop_chance:
            available_loot = [item for item in boss["loot"] if item not in u.get("inventory", [])]
            if available_loot:
                dropped_item = random.choice(available_loot)
                if "inventory" not in u:
                    u["inventory"] = []
                u["inventory"].append(dropped_item)
        
        save_user(msg.from_user.id)
        
        battle_log += f"\n🎉 ПОБЕДА!\n"
        battle_log += f"💰 +{mmr_reward} MMR\n"
        if dropped_item:
            battle_log += f"🎁 Получен предмет: {dropped_item}!\n"
        else:
            battle_log += f"🎁 Предметы не выпали (шанс 30%)\n"
        
        # Показываем следующего босса
        next_boss_index = u.get("boss_kills", 0) % len(bosses)
        next_boss = bosses[next_boss_index]
        battle_log += f"\n👹 Следующий босс: **{next_boss['name']}** (HP: {next_boss['HP']})"
        
    else:
        # Поражение
        u["last_raid"] = now
        save_user(msg.from_user.id)
        
        battle_log += f"\n💀 ПОРАЖЕНИЕ!\n"
        battle_log += f"Босс остался с {boss_hp} HP\n"
        battle_log += f"Попробуйте снова через 1 час\n"
    
    bot.send_message(msg.chat.id, battle_log, parse_mode="Markdown")

# ---------- КНОПКА НАЗАД ----------
@bot.message_handler(func=lambda m: m.text == "⬅️ Назад")
def go_back(msg):
    bot.send_message(msg.chat.id, "⬅️ Возвращаемся в главное меню", reply_markup=menu())

# ---------- HTTP SERVER (для Render) ----------
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(b'Bot is running')
    
    def log_message(self, format, *args):
        # Отключаем логи HTTP сервера
        pass

def run_http_server():
    port = int(os.getenv('PORT', 10000))
    server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
    print(f"HTTP сервер запущен на порту {port}")
    server.serve_forever()

# ---------- RUN ----------
if __name__ == "__main__":
    # Запускаем HTTP сервер в отдельном потоке (для Render)
    http_thread = Thread(target=run_http_server, daemon=True)
    http_thread.start()
    
    print("Бот запущен...")
    bot.infinity_polling()
