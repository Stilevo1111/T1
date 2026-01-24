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

# ---------- ХРАНЕНИЕ ----------
def load():
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)

users = load()

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
            "equipped": {}    # {"weapon": "Daedalus", "armor": None, ...}
        }
        save(users)
    # Добавляем поля для старых пользователей
    if "inventory" not in users[uid]:
        users[uid]["inventory"] = []
    if "equipped" not in users[uid]:
        users[uid]["equipped"] = {}
    return users[uid]

# ---------- КНОПКИ ----------
def menu():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("👤 Профиль", "🌋 FISSURE")
    kb.add("⚔️ PvP", "🎰 Слоты")
    kb.add("🎒 Инвентарь", "🏪 Магазин")
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
    text = (
        f"👤 ПРОФИЛЬ\n\n"
        f"💬 Чат-MMR: {u['chat_mmr']}\n"
        f"🏆 Победы: {u['wins']}\n"
        f"💀 Поражения: {u['loses']}\n"
        f"🍆 FISSURE: {u['fissure']:.1f} см"
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
    save(users)

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

# ---------- PvP ----------
@bot.message_handler(func=lambda m: m.text == "⚔️ PvP")
def pvp(msg):
    u = get_user(msg.from_user.id)
    if u["chat_mmr"] < 10:
        bot.send_message(msg.chat.id, "❌ Мало чат-MMR")
        return

    win = random.choice([True, False])
    if win:
        u["chat_mmr"] += 20
        u["wins"] += 1
        text = "🏆 ПОБЕДА! +20 чат-MMR"
    else:
        u["chat_mmr"] -= 10
        u["loses"] += 1
        text = "💀 ПОРАЖЕНИЕ! -10 чат-MMR"

    save(users)
    bot.send_message(msg.chat.id, text)

# ---------- СЛОТЫ ----------
@bot.message_handler(func=lambda m: m.text == "🎰 Слоты")
def slots(msg):
    u = get_user(msg.from_user.id)
    if u["chat_mmr"] < 10:
        bot.send_message(msg.chat.id, "❌ Нужно минимум 10 чат-MMR")
        return

    u["chat_mmr"] -= 10
    roll = random.randint(1, 100)

    if roll > 90:
        u["chat_mmr"] += 50
        text = "🎰 ДЖЕКПОТ! +50"
    elif roll > 60:
        u["chat_mmr"] += 20
        text = "🎉 Выигрыш +20"
    else:
        text = "💸 Проигрыш"

    save(users)
    bot.send_message(msg.chat.id, text)

# ---------- ИНВЕНТАРЬ ----------
@bot.message_handler(func=lambda m: m.text == "🎒 Инвентарь")
def inventory(msg):
    u = get_user(msg.from_user.id)
    inv = u.get("inventory", [])
    
    if not inv:
        bot.send_message(msg.chat.id, "🎒 Инвентарь пуст\n\nПокупайте предметы в 🏪 Магазине!")
        return
    
    text = "🎒 ИНВЕНТАРЬ\n\n"
    for item_name in inv:
        item_data = get_item_info(item_name)
        if item_data:
            text += f"▫️ {item_name}\n"
            for key, value in item_data.items():
                if key not in ["💰", "🎁"]:
                    text += f"  {key}: {value}\n"
            text += "\n"
    
    bot.send_message(msg.chat.id, text)

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
    
    bot.send_message(msg.chat.id, text, parse_mode="Markdown")

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
    save(users)
    
    bot.send_message(msg.chat.id, f"✅ Куплено: {item_name}\n💰 Потрачено: {price} MMR\n💰 Осталось: {u['chat_mmr']} MMR")

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
