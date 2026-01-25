import os
import time
import random
import logging
import asyncio
import asyncpg
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ================= CONFIG =================

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
RENDER_URL = os.getenv("RENDER_EXTERNAL_URL")
PORT = int(os.getenv("PORT", 10000))

if not all([BOT_TOKEN, DATABASE_URL, RENDER_URL]):
    raise RuntimeError("Не заданы BOT_TOKEN / DATABASE_URL / RENDER_EXTERNAL_URL")

# ================= DATABASE =================

db_pool: asyncpg.Pool | None = None


async def init_db(app):
    global db_pool
    db_pool = await asyncpg.create_pool(DATABASE_URL)

    async with db_pool.acquire() as conn:
        # Проверяем, есть ли уже таблица users
        table_exists = await conn.fetchval("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_schema = 'public' 
                AND table_name = 'users'
            )
        """)

        if not table_exists:
            # Создаем новую таблицу
            await conn.execute("""
                CREATE TABLE users (
                    user_id TEXT PRIMARY KEY,
                    username TEXT,
                    level INTEGER DEFAULT 1,
                    hp INTEGER DEFAULT 100,
                    hp_max INTEGER DEFAULT 100,
                    str INTEGER DEFAULT 5,
                    agi INTEGER DEFAULT 5,
                    int INTEGER DEFAULT 5,
                    gold INTEGER DEFAULT 200,
                    mmr INTEGER DEFAULT 1000,
                    exp INTEGER DEFAULT 0,
                    items TEXT[] DEFAULT ARRAY[NULL,NULL,NULL,NULL,NULL,NULL],
                    boss_dmg INTEGER DEFAULT 0,
                    last_pvp DOUBLE PRECISION DEFAULT 0,
                    last_heal DOUBLE PRECISION DEFAULT 0,
                    boss_hp INTEGER DEFAULT 3000,
                    boss_name TEXT DEFAULT 'Shadow Fiend',
                    boss_max INTEGER DEFAULT 3000,
                    boss_level INTEGER DEFAULT 1
                )
            """)
            logging.info("DB initialized - new table created")
        else:
            # Проверяем, есть ли поля для новой системы
            new_fields = await conn.fetchval("""
                SELECT EXISTS (
                    SELECT FROM information_schema.columns 
                    WHERE table_name = 'users' 
                    AND column_name = 'level'
                )
            """)

            if not new_fields:
                # Добавляем новые поля для RPG системы
                await conn.execute("""
                    ALTER TABLE users ADD COLUMN level INTEGER DEFAULT 1,
                    ADD COLUMN exp INTEGER DEFAULT 0,
                    ADD COLUMN last_heal DOUBLE PRECISION DEFAULT 0,
                    ADD COLUMN boss_level INTEGER DEFAULT 1
                """)
                logging.info("DB migration completed - RPG fields added")
            else:
                logging.info("DB initialized - existing table with RPG fields")


async def get_user(uid: int, username: str) -> dict:
    async with db_pool.acquire() as conn:
        user = await conn.fetchrow(
            "SELECT * FROM users WHERE user_id=$1",
            str(uid),
        )
        if not user:
            await conn.execute(
                "INSERT INTO users (user_id, username) VALUES ($1, $2)",
                str(uid),
                username,
            )
            user = await conn.fetchrow(
                "SELECT * FROM users WHERE user_id=$1",
                str(uid),
            )
        else:
            # обновляем имя пользователя, если оно изменилось
            if user["username"] != username:
                await conn.execute(
                    "UPDATE users SET username=$1 WHERE user_id=$2",
                    username,
                    str(uid),
                )
        return dict(user)


async def update_user(uid: int, **kwargs):
    async with db_pool.acquire() as conn:
        set_clause = ", ".join([f"{k}=${i+1}" for i, k in enumerate(kwargs.keys())])
        values = list(kwargs.values()) + [str(uid)]
        await conn.execute(
            f"UPDATE users SET {set_clause} WHERE user_id=${len(values)}",
            *values
        )


async def get_top_by_stat(stat: str, limit: int = 10):
    async with db_pool.acquire() as conn:
        return await conn.fetch(f"""
            SELECT username, {stat}
            FROM users
            ORDER BY {stat} DESC
            LIMIT $1
        """, limit)

# ================= GAME DATA =================

# Мем-комментарии
MEMES = {
    "crit": [
        "💥 КРИТ! Я инвестировал в урон",
        "🔥 Минус лицо",
        "😈 Это было больно",
        "🎯 Точно в цель!",
        "⚡️ Супер удар!"
    ],
    "dodge": [
        "🌀 Я вообще-то тут не стоял",
        "😎 Уклон — стиль жизни",
        "💨 Слишком медленно!",
        "🎭 Фехтование, мать его!",
        "🏃‍♂️ Быстрее ветра!"
    ],
    "death": [
        "💀 Это был тактический фид",
        "🪦 Я ещё вернусь",
        "⚰️ Пора на кладбище",
        "👻 Смерть — не повод для грусти",
        "⚰️ Вечная память"
    ],
    "boss_kill": [
        "🏆 {boss} повержен!",
        "🔥 Мы его взяли!",
        "💀 Босс упал!",
        "🎯 Цель уничтожена!",
        "🔥 Это был эпик бой!"
    ]
}

# Предметы
ITEMS = {
    "Sword": {"gold": 200, "dmg": 10},
    "Boots": {"gold": 150, "agi": 5, "dodge": 5},
    "Armor": {"gold": 250, "hp": 50},
    "Daedalus": {"gold": 500, "crit": 15, "dmg": 20},
    "BKB": {"gold": 400, "hp": 100},
    "Potion": {"gold": 50, "heal": 50}
}

# Зелья
POTIONS = {
    "Minor": {"gold": 50, "heal": 20},
    "Major": {"gold": 120, "heal": 50},
    "Ultimate": {"gold": 300, "heal": 100}
}

# Боссы
BOSSES = [
    {"name": "Shadow Fiend", "hp": 2600, "dmg": [25, 45], "min_level": 1, "max_level": 10},
    {"name": "Axe", "hp": 2800, "dmg": [35, 55], "min_level": 5, "max_level": 12},
    {"name": "Doom", "hp": 2500, "dmg": [30, 45], "min_level": 7, "max_level": 14},
    {"name": "Zeus", "hp": 3200, "dmg": [20, 50], "min_level": 8, "max_level": 15},
    {"name": "Invoker", "hp": 2700, "dmg": [20, 40], "min_level": 10, "max_level": 18},
    {"name": "Roshan", "hp": 3000, "dmg": [25, 40], "min_level": 12, "max_level": 20},
    {"name": "Roshan Prime", "hp": 4500, "dmg": [50, 80], "min_level": 20, "max_level": 30}
]

# ================= UTILS =================

def get_item_bonus(user, stat):
    bonus = 0
    if user["items"]:
        for item_name in user["items"]:
            if item_name and item_name in ITEMS and stat in ITEMS[item_name]:
                bonus += ITEMS[item_name][stat]
    return bonus

def calculate_damage(user):
    base_dmg = user["str"] + random.randint(1, 10)
    item_dmg = get_item_bonus(user, "dmg")
    total_dmg = base_dmg + item_dmg
    
    # Критический удар
    crit_chance = user["agi"] * 2 + get_item_bonus(user, "crit")
    is_crit = random.randint(1, 100) <= crit_chance
    if is_crit:
        total_dmg *= 2
    
    return total_dmg, is_crit

def calculate_dodge(user):
    dodge_chance = user["agi"] + get_item_bonus(user, "dodge")
    return random.randint(1, 100) <= dodge_chance

def spawn_boss():
    boss = random.choice(BOSSES)
    return {
        "name": boss["name"],
        "hp": boss["hp"],
        "max": boss["hp"],
        "dmg": boss["dmg"],
        "min_level": boss["min_level"],
        "max_level": boss["max_level"]
    }

def check_level_restriction(user_level, boss_min, boss_max):
    return boss_min <= user_level <= boss_max

def regenerate_hp(user):
    current_time = time.time()
    if current_time - user["last_heal"] >= 60:  # Каждую минуту
        regen_amount = int(user["hp_max"] * 0.05)  # 5% от макс HP
        new_hp = min(user["hp"] + regen_amount, user["hp_max"])
        return new_hp, current_time
    return user["hp"], user["last_heal"]

def check_level_up(user):
    exp_needed = user["level"] * 100
    if user["exp"] >= exp_needed:
        return True
    return False

# ================= KEYBOARD =================

MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [["👹 BOSS", "🛒 SHOP"], ["⚔️ PVP", "🏆 TOP"], ["📊 STATS"]],
    resize_keyboard=True,
)

# ================= BOT COMMANDS =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username or update.effective_user.full_name
    user = await get_user(update.effective_user.id, username)
    
    await update.message.reply_text(
        f"🎮 {user['username']}, ты в игре\n"
        f"Уровень: {user['level']}\n"
        f"HP: {user['hp']}/{user['hp_max']}\n"
        f"STR: {user['str']} | AGI: {user['agi']} | INT: {user['int']}\n"
        f"Gold: {user['gold']} | MMR: {user['mmr']}\n\n"
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
        "/stats — статистика",
        reply_markup=MAIN_KEYBOARD,
    )

async def boss(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username or update.effective_user.full_name
    user = await get_user(update.effective_user.id, username)
    
    await update.message.reply_text(
        f"👹 {user['boss_name']}\n"
        f"HP: {user['boss_hp']}/{user['boss_max']}\n"
        f"Уровень: {user['boss_level']}\n"
        f"/attack — атаковать"
    )

async def attack(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username or update.effective_user.full_name
    user = await get_user(update.effective_user.id, username)
    
    # Регенерация HP
    new_hp, last_heal = regenerate_hp(user)
    if new_hp != user["hp"]:
        await update_user(update.effective_user.id, hp=new_hp, last_heal=last_heal)
        user["hp"] = new_hp

    if user["hp"] <= 0:
        await update.message.reply_text("💀 Ты мёртв")
        return

    # Проверка уровня
    if not check_level_restriction(user["level"], user["boss_level"], user["boss_level"]):
        await update.message.reply_text("❌ Босс слишком сильный для тебя")
        return

    # Атака игрока
    dmg, is_crit = calculate_damage(user)
    boss_hp = user["boss_hp"] - dmg
    boss_dmg = user["boss_dmg"] + dmg
    
    text = f"⚔️ {user['username']} нанёс {dmg} урона"
    if is_crit:
        text += "\n" + random.choice(MEMES["crit"])

    # Атака босса
    boss_attack = random.randint(*user["boss_dmg"])
    
    # Проверка уклонения
    if calculate_dodge(user):
        text += f"\n🛡️ {user['username']} уклонился от атаки!"
    else:
        user_hp = user["hp"] - boss_attack
        text += f"\n👹 Босс ударил на {boss_attack}"
        
        if user_hp <= 0:
            text += "\n" + random.choice(MEMES["death"])
            user_hp = 0
    else:
        user_hp = user["hp"]

    # Проверка смерти босса
    if boss_hp <= 0:
        boss_name = user["boss_name"]
        text += f"\n" + random.choice(MEMES["boss_kill"]).format(boss=boss_name)
        user_gold = user["gold"] + 100
        user_exp = user["exp"] + 50
        new_boss = spawn_boss()
        boss_hp = new_boss["hp"]
        boss_name = new_boss["name"]
        boss_max = new_boss["max"]
        boss_level = new_boss["min_level"]
        boss_dmg = 0
        
        # Проверка уровня
        if check_level_up(user):
            user_level = user["level"] + 1
            user_hp_max = user["hp_max"] + 5
            user_hp = user_hp_max
            text += f"\n🎉 Достигнут уровень {user_level}!"
        else:
            user_level = user["level"]
            user_hp_max = user["hp_max"]
    else:
        user_gold = user["gold"]
        user_exp = user["exp"]
        boss_name = user["boss_name"]
        boss_max = user["boss_max"]
        boss_level = user["boss_level"]
        user_level = user["level"]
        user_hp_max = user["hp_max"]

    # Обновляем данные
    await update_user(
        update.effective_user.id,
        hp=user_hp,
        hp_max=user_hp_max,
        level=user_level,
        exp=user_exp,
        boss_hp=boss_hp,
        boss_name=boss_name,
        boss_max=boss_max,
        boss_level=boss_level,
        boss_dmg=boss_dmg,
        gold=user_gold
    )
    
    await update.message.reply_text(text)

async def shop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = "🛒 Магазин:\n"
    for item_name, item_data in ITEMS.items():
        text += f"{item_name} — {item_data['gold']}g\n"
    text += "\n/buy ITEM — купить предмет"
    await update.message.reply_text(text)

async def buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username or update.effective_user.full_name
    user = await get_user(update.effective_user.id, username)
    
    try:
        item_name = context.args[0] if context.args else None
    except:
        await update.message.reply_text("❌ Укажите предмет для покупки")
        return

    if item_name not in ITEMS:
        await update.message.reply_text("❌ Нет такого предмета")
        return

    item_data = ITEMS[item_name]
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
    await update.message.reply_text(f"✅ Куплен {item_name}")

async def potion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username or update.effective_user.full_name
    user = await get_user(update.effective_user.id, username)
    
    try:
        potion_type = context.args[0] if context.args else None
    except:
        await update.message.reply_text("❌ Укажите тип зелья (Minor/Major/Ultimate)")
        return

    if potion_type not in POTIONS:
        await update.message.reply_text("❌ Нет такого зелья")
        return

    potion_data = POTIONS[potion_type]
    cost = potion_data["gold"]
    
    if user["gold"] < cost:
        await update.message.reply_text("💰 Мало золота")
        return

    # Покупка зелья
    new_hp = min(user["hp"] + potion_data["heal"], user["hp_max"])
    await update_user(update.effective_user.id, hp=new_hp, gold=user["gold"] - cost)
    await update.message.reply_text(f"🧪 {potion_type} зелье использовано. HP восстановлено")

async def heal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username or update.effective_user.full_name
    user = await get_user(update.effective_user.id, username)
    
    # Регенерация HP
    new_hp, last_heal = regenerate_hp(user)
    if new_hp != user["hp"]:
        await update_user(update.effective_user.id, hp=new_hp, last_heal=last_heal)
        await update.message.reply_text(f"💚 HP восстановлено до {new_hp}/{user['hp_max']}")
    else:
        await update.message.reply_text("💚 HP уже восстановлено")

async def pvp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⚔️ Напиши /fight USER_ID")

async def fight(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username or update.effective_user.full_name
    user1 = await get_user(update.effective_user.id, username)
    
    try:
        enemy_id = int(context.args[0]) if context.args else None
    except:
        await update.message.reply_text("❌ Укажите ID противника")
        return

    user2 = await get_user(enemy_id, f"Player{enemy_id}")
    
    if time.time() - user1["last_pvp"] < 600:
        await update.message.reply_text("⏳ КД PvP")
        return

    # Проверка MMR
    if user2["mmr"] < user1["mmr"] * 0.5:
        await update.message.reply_text("❌ Противник слишком слабый")
        return

    # Боевые действия
    dmg1, _ = calculate_damage(user1)
    dmg2, _ = calculate_damage(user2)
    
    user2_hp = max(0, user2["hp"] - dmg1)
    user1_hp = max(0, user1["hp"] - dmg2)
    
    text = f"{user1['username']} ➜ {dmg1}\n{user2['username']} ➜ {dmg2}"
    
    if user1_hp > user2_hp:
        user1_mmr = user1["mmr"] + 20
        user1_gold = user1["gold"] + 50
        user2_mmr = user2["mmr"] - 10
        user2_gold = max(0, user2["gold"] - 20)
        text += f"\n🏆 Победил {user1['username']}"
    else:
        user2_mmr = user2["mmr"] + 20
        user2_gold = user2["gold"] + 50
        user1_mmr = user1["mmr"] - 10
        user1_gold = max(0, user1["gold"] - 20)
        text += f"\n🏆 Победил {user2['username']}"

    await update_user(update.effective_user.id, hp=user1_hp, mmr=user1_mmr, gold=user1_gold, last_pvp=time.time())
    await update_user(enemy_id, hp=user2_hp, mmr=user2_mmr, gold=user2_gold)
    
    await update.message.reply_text(text)

async def top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    stat = context.args[0] if context.args else "mmr"
    limit = 10
    
    if stat not in ["mmr", "gold", "boss_dmg"]:
        await update.message.reply_text("❌ Неверная статистика. Доступно: mmr, gold, boss_dmg")
        return
    
    rows = await get_top_by_stat(stat, limit)
    if not rows:
        await update.message.reply_text("Топ пуст 😢")
        return
    
    text = f"🏆 ТОП по {stat}:\n"
    for i, row in enumerate(rows, 1):
        text += f"{i}. 👤 {row['username']} — {row[stat]}\n"
    
    await update.message.reply_text(text)

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username or update.effective_user.full_name
    user = await get_user(update.effective_user.id, username)
    
    items_str = ", ".join([item or "Пусто" for item in user["items"]]) if user["items"] else "Пусто"
    
    text = (f"📊 Статистика {user['username']}:\n"
            f"Уровень: {user['level']}\n"
            f"HP: {user['hp']}/{user['hp_max']}\n"
            f"STR: {user['str']} | AGI: {user['agi']} | INT: {user['int']}\n"
            f"EXP: {user['exp']}\n"
            f"Gold: {user['gold']} | MMR: {user['mmr']}\n"
            f"Урон по боссам: {user['boss_dmg']}\n"
            f"Предметы: {items_str}")
    
    await update.message.reply_text(text)

# ================= BUTTON HANDLER =================

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "👹 BOSS":
        await boss(update, context)
    elif text == "🛒 SHOP":
        await shop(update, context)
    elif text == "⚔️ PVP":
        await pvp(update, context)
    elif text == "🏆 TOP":
        await top(update, context)
    elif text == "📊 STATS":
        await stats(update, context)

# ================= ENTRY POINT =================

if __name__ == "__main__":
    app = ApplicationBuilder().token(BOT_TOKEN).post_init(init_db).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("boss", boss))
    app.add_handler(CommandHandler("attack", attack))
    app.add_handler(CommandHandler("shop", shop))
    app.add_handler(CommandHandler("buy", buy))
    app.add_handler(CommandHandler("potion", potion))
    app.add_handler(CommandHandler("heal", heal))
    app.add_handler(CommandHandler("pvp", pvp))
    app.add_handler(CommandHandler("fight", fight))
    app.add_handler(CommandHandler("top", top))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    app.run_polling()
