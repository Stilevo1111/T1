import json
import time
import random
import asyncio
from aiogram import Bot, Dispatcher, executor, types

API_TOKEN = "ВСТАВЬ_СВОЙ_ТОКЕН_СЮДА"
DATA_FILE = "data.json"

bot = Bot(API_TOKEN)
dp = Dispatcher(bot)

# ---------- ХРАНЕНИЕ ----------
def load():
    try:
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    except:
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
            "last_fissure": 0
        }
        save(users)
    return users[uid]

# ---------- КНОПКИ ----------
def menu():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("👤 Профиль", "🌋 FISSURE")
    kb.add("⚔️ PvP", "🎰 Слоты")
    return kb

# ---------- АВТОУДАЛЕНИЕ ----------
async def autodel(msg, t=30):
    await asyncio.sleep(t)
    try:
        await msg.delete()
    except:
        pass

# ---------- START ----------
@dp.message_handler(commands=["start"])
async def start(msg: types.Message):
    get_user(msg.from_user.id)
    await msg.answer("🔥 Бот запущен\nFISSURE — мем, ни на что не влияет 😏", reply_markup=menu())

# ---------- ПРОФИЛЬ ----------
@dp.message_handler(lambda m: m.text == "👤 Профиль")
async def profile(msg):
    u = get_user(msg.from_user.id)
    text = (
        f"👤 ПРОФИЛЬ\n\n"
        f"💬 Чат-MMR: {u['chat_mmr']}\n"
        f"🏆 Победы: {u['wins']}\n"
        f"💀 Поражения: {u['loses']}\n"
        f"🍆 FISSURE: {u['fissure']:.1f} см"
    )
    m = await msg.answer(text)
    asyncio.create_task(autodel(m))

# ---------- FISSURE ----------
@dp.message_handler(lambda m: m.text == "🌋 FISSURE")
async def fissure(msg):
    u = get_user(msg.from_user.id)
    now = time.time()
    if now - u["last_fissure"] < 86400:
        h = int((86400 - (now - u["last_fissure"])) / 3600)
        m = await msg.answer(f"⏳ Через {h} ч.")
        asyncio.create_task(autodel(m))
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

    m = await msg.answer(f"{texts[roll]}\n📏 Теперь {u['fissure']:.1f} см")
    asyncio.create_task(autodel(m))

# ---------- PvP ----------
@dp.message_handler(lambda m: m.text == "⚔️ PvP")
async def pvp(msg):
    u = get_user(msg.from_user.id)
    if u["chat_mmr"] < 10:
        m = await msg.answer("❌ Мало чат-MMR")
        asyncio.create_task(autodel(m))
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
    m = await msg.answer(text)
    asyncio.create_task(autodel(m))

# ---------- СЛОТЫ ----------
@dp.message_handler(lambda m: m.text == "🎰 Слоты")
async def slots(msg):
    u = get_user(msg.from_user.id)
    if u["chat_mmr"] < 10:
        m = await msg.answer("❌ Нужно минимум 10 чат-MMR")
        asyncio.create_task(autodel(m))
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
    m = await msg.answer(text)
    asyncio.create_task(autodel(m))

# ---------- RUN ----------
if __name__ == "__main__":
    executor.start_polling(dp, skip_updates=True)
