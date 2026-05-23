# -*- coding: utf-8 -*-
"""
Roll system for fissure calculations.
Contains constants and pure calculation functions.
Extracted from main.py without any behavior changes.
"""

import random


# =====================
# ROLL SYSTEM CONSTANTS
# =====================

BASE_ROLLS = [-3, -1, 0, 1, 3, 5, 10, 20]
FATAL_ROLL = -10


# =====================
# ROLL TEXTS
# =====================

ROLL_TEXTS = {
    50: ["🔥🔥🔥 НЕВЕРОЯТНО! +50 см!", "💰 ДЖЕКПОТ! +50 см за раз!", "🦸 ЛЕГЕНДАРНО! +50 СМ!", "👑 ДОМИНИРУЕШЬ! +50 СМ!", "💀 БОЖЕСТВЕННО! +50 СМ!"],
    30: ["🚀 КОСМОС! +30 см!", "🍀 СУПЕР УДАЧА! +30 см!", "⚡ СИЛА УЛЬТЫ! +30 СМ!", "🔥 МЕГА КИЛЛ! +30 СМ!"],
    20: ["💪 MEGA УСПЕХ! +20 см!", "🎯 ТОЧНО В ДЕСЯТКУ! +20 см!", "🎯 ДВОЙНОЙ КИЛЛ! +20 СМ!", "💪 НЕУДЕРЖИМ! +20 СМ!"],
    15: ["🔥 МУЛЬТИБОНУС! +15 СМ!", "💥 ОТЛИЧНЫЙ РЕЗУЛЬТАТ! +15 СМ!", "🚀 РАСТИ! +15 СМ!"],
    12: ["💪 СИЛЬНО! +12 СМ!", "🎮 УЛУЧШЕНИЕ! +12 СМ!"],
    10: ["🌟 ЛЕГЕНДА! +10 см!", "🔥 ОГОНЬ! +10 см!", "🌟 ПЕРВАЯ КРОВЬ! +10 СМ!", "🎮 УБИЙСТВЕННАЯ СЕРИЯ! +10 СМ!"],
    9: ["📈 РАСТИ! +9 СМ!", "💪 НЕПЛОХО! +9 СМ!"],
    8: ["📈 ХОРОШО! +8 СМ!", "💪 ЕЩЁ! +8 СМ!"],
    7: ["👍 ЕСТЬ! +7 СМ!", "📈 НАРАЩИВАЕМ! +7 СМ!"],
    6: ["👍 ЕСТЬ! +6 СМ!", "📈 НАРАЩИВАЕМ! +6 СМ!"],
    5: ["🎉 УРА! +5 см!", "👍 ОТЛИЧНО! +5 см!", "✅ НОРМ! +5 СМ!", "👍 КРАСАВА! +5 СМ!"],
    4: ["✅ НЕПЛОХО! +4 СМ!", "💪 ПОТИХОНЬКУ! +4 СМ!"],
    3: ["😊 НЕПЛОХО! +3 см", "📈 РАСТЁМ! +3 см", "💪 НА! +3 СМ", "🔥 В ОГНЕ! +3 СМ"],
    2: ["✅ ЕСТЬ! +2 СМ!", "💪 ШАГ! +2 СМ!"],
    1: ["✅ OK! +1 см", "💪 ЕСТЬ РОСТ! +1 см", "🙄 ПОВЕЗЛО! +1 СМ", "🤔 МОГЛО БЫТЬ ХУЖЕ! +1 СМ"],
    0: ["❌ БЕЗ ИЗМЕНЕНИЙ", "💤 СТОИМ НА МЕСТЕ", "❌ НИЧЬЯ", "💤 АФК?"],
    -1: ["🤔 НЕМНОГО -1 см", "📉 МИНУС -1 см", "😬 ОЙ! -1 СМ", "💀 КОРМ! -1 СМ"],
    -2: ["📉 МИНУС -2 СМ", "😬 НЕМНОГО БОЛЬНО! -2 СМ"],
    -3: ["😬 ОЙ... -3 см", "⬇️ УПАЛ -3 см", "🤕 ДЕНАЙ! -3 СМ", "☠️ НАРЖАЛ! -3 СМ"],
    -4: ["⬇️ СКОЛЬЗИМ! -4 СМ", "😬 НЕУДАЧА! -4 СМ"],
    -5: ["😢 БОЛЬНО -5 см...", "💔 НЕУДАЧА -5 см", "💀 ПОПАЛ! -5 СМ...", "🎮 ГГ ВП... -5 СМ"],
    -6: ["💀 ПОПАЛ! -6 СМ...", "⬇️ УПАЛ! -6 СМ"],
    -7: ["😢 ОЙ! -7 СМ...", "💔 БОЛЬНО! -7 СМ"],
    -8: ["😢 НЕПРИЯТНО! -8 СМ...", "⬇️ КАПУТ! -8 СМ"],
    -9: ["😢 БОЛЬНО! -9 СМ...", "💀 КРИТИЧЕСКИЙ УРОН! -9 СМ"],
    -10: ["💥 КАТАСТРОФА! -10 см!!!", "🌋 АПОКАЛИПСИС! -10 см!!!", "😵 СЕРВЕР УПАЛ! -10 СМ!!!", "💥 ДИСКОННЕКТ! -10 СМ!!!"],
    -11: ["💥 УЖАС! -11 СМ!!!", "☠️ КРАШ! -11 СМ!!!"],
    -12: ["💀 БОЛЬНО! -12 СМ!!!", "🌋 ВУЛКАН! -12 СМ!!!"],
    -13: ["💥 ПОЛНЫЙ КРАХ! -13 СМ!!!", "☠️ ФИНАЛ! -13 СМ!!!"],
    -14: ["💀 НЕВОССТАНОВИМО! -14 СМ!!!", "🌋 АПОКАЛИПСИС! -14 СМ!!!"],
    -15: ["💀 ФАТАЛЬНЫЙ УРОН! -15 СМ!!!", "🌋 КОНЕЦ! -15 СМ!!!", "☠️ ОТПРАВЛЕН В СТАРТ! -15 СМ!!!"],
    75: ["🏆 ЛЕГЕНДАРНЫЙ РОЛЛ!!! +75 СМ!!!", "💥 МЕГАДРОП!!! +75 СМ!!!", "🎯 ШОТ! +75 СМ!!!"],
}

ROLL_MEMES = {
    75: [
        "👁️ «Я ВИДЕЛ БУДУЩЕЕ — ТЕБЯ ТАМ НЕТ» (Войд)",
        "⚔️ «ЗА НАЙТСИЛЬВЕР!» (Мирана)",
        "🌑 «ИЗ МРАКА!» (НС)"
    ],
    50: [
        "💥 «ХАОС ДАНК!» (СиКей)",
        "🩹 «РАЗЛОМ ИСЦЕЛЯЕТСЯ!» (СК)",
        "🩸 «ЦАРСТВО КРОВИ!» (Блад)"
    ],
    30: [
        "🔥 «ДУХАМИ ЗАКЛИНАЮ!» (Эмбер)",
        "🛡️ «ЗА МОЙ НАРОД!» (Свен)",
        "⚜️ «КЛЯТВА ПРИНЕСЕНА!» (Омни)"
    ],
    20: [
        "🌹 «ПРОКЛЯТИЕ РОЗЫ!» (КоП)",
        "🔨 «Я НЕСУ МОЛОТ!» (Омни)",
        "🗡️ «ОДИН КЛИНОК — ОДНА ЦЕЛЬ» (Джагг)"
    ],
    15: [
        "✨ «Я — СВЕТ!» (КотЛ)",
        "🏹 «СТРАННИЦА ВОЗВРАЩАЕТСЯ» (ВР)",
        "😈 «ПЛАЧЬ ЕЩЁ!» (ЛЦ)"
    ],
    10: [
        "🚫 «МАГИЯ — ОТСТОЙ!» (АМ)",
        "👑 «ЗА ПОСЛЕДНЕГО КОРОЛЯ!» (ВК)",
        "🕳️ «БЕЗДНА ЗОВЁТ» (Войд)"
    ],
    9: [
        "👻 «ЗА ТВОЕЙ СПИНОЙ!» (Рики)",
        "🧈 «МЯГКИЙ, КАК МАСЛО» (ПА)",
        "🕷️ «ГНЕЗДО ЖДУ» (Бруд)"
    ],
    5: [
        "🍖 «СВЕЖЕЕ МЯСО!» (Падж)",
        "🐟 «ОХОТА НАЧИНАЕТСЯ» (Сларк)",
        "🐻 «КАЛЕЧИТЬ! УБИВАТЬ!» (Урса)"
    ],
    1: [
        "🪨 «БРОСАЙ МЕНЯ!» (Тайни)",
        "🪙 «ВЕЗУЧАЯ МОНЕТКА» (Гамблер)",
        "🧪 «МАЛЫЕ НАЧАЛА» (Мипо)"
    ],
    0: [
        "💤 «Я ОТДОХНУ ТЕПЕРЬ» (Висп)",
        "⏳ «ДРЕВНИЕ ЖДУТ» (Аганим)",
        "🧘 «СОЗЕРЦАНИЕ» (Элдер Т)"
    ],
    -1: [
        "😔 «Я ПОДВЁЛ» (Свен)",
        "😩 «НЕ ТАК» (Зевс)",
        "🌫️ «ВИДЕНИЕ ТУСКНЕЕТ» (Войд)"
    ],
    -5: [
        "🥶 «ПЛАМЯ ПОГАСЛО» (Лина)",
        "😖 «Я... СПОТКНУЛСЯ» (Эмбер)",
        "💔 «МОЯ ЧЕСТЬ... РАЗБИТА» (ЛЦ)"
    ],
    -10: [
        "🚨 «ДРЕВНИЙ АТАКУЮТ» (диктор)",
        "🏃‍♂️💨 «КОМАНДА ТЕБЯ БРОСИЛА» (игра)",
        "🌚 «ПОБЕДА ТЬМЫ» (Тьма)"
    ],
    -15: [
        "😭 «СВЕТ ПОВЕРЖЕН» (диктор)",
        "🎭 «ТВОЙ ММР — ЛОЖЬ» (Crownfall)",
        "🕳️ «ОБРАТНО В РАЗЛОМ» (СК)"
    ],
}

# =====================
# CATEGORY PHRASES
# =====================

CATEGORY_PHRASES = {
    "up": [
        "💪 Растём!",
        "📏 Каждый см важен!",
        "✅ Фиссура одобряет!",
        "📈 Положительная динамика!",
        "🔥 Так держать!",
        "⬆️ Вверх и только вверх!"
    ],
    "down": [
        "😔 Небольшой откат!",
        "💪 Фиссура восстановится!",
        "🌅 Завтра новый день!",
        "⏳ Временный спад!",
        "💪 Не сдавайся!",
        "🎯 Это ещё не конец!"
    ],
    "same": [
        "🛡 Стабильность - это хорошо!",
        "💪 Держим позиции!",
        "➡️ Без изменений - тоже результат!",
        "⚓ Твёрдо как скала!",
        "📊 Постоянство важно!",
        "🏗️ Прочный фундамент!"
    ],
    "bonus_help": [
        "✨ СИСТЕМА ПОМОГЛА!",
        "🍀 Удачный расклад!",
        "🎁 БОНУС!",
        "🛡 КРИТИЧЕСКАЯ ПОДДЕРЖКА!",
        "💰 ДЖЕКПОТ!",
        "🚀 МНОЖИТЕЛЬ!"
    ],
    "fatal": [
        "💥 КРИТИЧЕСКИЙ УРОН!",
        "🔥 Но ты устоял!",
        "🦾 ВЫЖИЛ!",
        "🎮 Ещё в игре!",
        "💪 Стойкость!",
        "🏆 Никогда не сдавайся!"
    ],
}


# =====================
# ROLL CALCULATION FUNCTIONS
# =====================

def calculate_fissure_roll(current_fissure):
    """
    Calculates new roll based on current fissure size
    Returns: (roll_value, message, is_fatal, got_help)
    """
    if current_fissure >= 20:
        fatal_chance = 0.02  # 2% для фиссур 20+ см
        if random.random() < fatal_chance:
            return FATAL_ROLL, "FATAL DECREASE!", True, False

    # Единый баланс для всех фиссур
    if current_fissure < 5:
        if random.random() < 0.8:
            bonus_options = [
                (5, 30), (10, 25), (20, 20), (30, 15), (50, 10)
            ]
            values, weights = zip(*bonus_options)
            roll = random.choices(values, weights=weights)[0]
            return roll, "✨ МАКСИМАЛЬНАЯ ПОМОЩЬ!", False, True

        protected_rolls = [1, 3, 5, 10, 20]
        roll = random.choice(protected_rolls)
        return roll, "🛡 ЗАЩИЩЁННЫЙ РОЛЛ", False, True

    elif current_fissure < 20:
        if random.random() < 0.4:
            improved_options = [3, 5, 10, 20]
            roll = random.choice(improved_options)
            return roll, "🚀 УЛУЧШЕННЫЙ РОЛЛ!", False, True

    elif current_fissure < 100:
        if random.random() < 0.2:
            bonus = random.choice([5, 10, 20])
            return bonus, "🍀 УДАЧНЫЙ РОЛЛ!", False, False

    else:
        # Для очень больших фиссур - меньше бонусов
        if random.random() < 0.1:
            bonus = random.choice([5, 10, 20])
            return bonus, "🍀 УДАЧНЫЙ РОЛЛ!", False, False

    # Единый баланс для всех:
    # Расширенный диапазон: от -15 до +75
    # Уменьшен шанс выпадения -1 (Зевс) и 0
    weighted_rolls = [
        (-15, 3), (-10, 5), (-7, 7), (-5, 8), (-3, 7), (-1, 2), (0, 2),
        (1, 5), (3, 7), (5, 8), (7, 7), (10, 8), (15, 6), (20, 5),
        (30, 4), (50, 2), (75, 1)
    ]
    values, weights = zip(*weighted_rolls)
    roll = random.choices(values, weights=weights)[0]
    return roll, "", False, False


def apply_fissure_protection(current_fissure, roll, is_fatal):
    """Applies protection for small fissures on fatal rolls"""
    if is_fatal and current_fissure < 5:
        reduced_roll = max(-5, roll)
        protection_msg = f"🛡 УРОН СНИЖЕН! Было {roll}, теперь {reduced_roll}"
        return reduced_roll, protection_msg

    return roll, ""


def calculate_new_fissure(current_fissure, roll):
    """Calculates new fissure size with minimum 0.1"""
    new_value = current_fissure + roll
    return max(0.1, new_value)


# =====================
# MULTICAST
# =====================

MULTICAST_CASCADE = [0.75, 0.50, 0.40]

MULTICAST_TEXTS = {
    2: [
        "🧙‍♂️ «Эй, ты это видел? Ну конечно не видел, ты же тупой!»",
        "🧙‍♂️ «Одного раза мало? А два раза — в самый раз!»",
        "🧙‍♂️ «Я сказал — ещё раз! А ты что хотел?»",
        "🧙‍♂️ «Смотри сюда, сейчас опять будет! Или не будет? Будет!»",
        "🧙‍♂️ «Это не магия, это чистая удача. А удача — это тоже скилл!»"
    ],
    3: [
        "🧙‍♂️ «Три раза! Три! Считай, если умеешь. Один, два, три! Во!»",
        "🧙‍♂️ «Огр — сила! А два огра — три силы! Не понял? Сам не понял, но звучит круто!»",
        "🧙‍♂️ «Где твоя мана? А у нас есть! Потому что мы умные. Ну, умнее тебя точно.»",
        "🧙‍♂️ «Это не повезло, это мастерство. Мастерство быть везучим! Ха-ха!»",
        "🧙‍♂️ «Мы говорили, что мы великие? Нет? Ну, теперь говорим. МЫ ВЕЛИКИЕ!»"
    ],
    4: [
        "🧙‍♂️ «Четыре! Четыре раза, дурак! Наша дубина магии круче твоего посоха!»",
        "🧙‍♂️ «Кто тут главный волшебник? Я! А я? И я! Мы оба! А ты кто? Никто!»",
        "🧙‍♂️ «Дружба победила! Потому что две головы думают, а одна даже не знает, где уши.»",
        "🧙‍♂️ «Мы сейчас так ударим, что у тебя мана кончится ещё до того, как мы начали!»",
        "🧙‍♂️ «Это называется мультикаст. Запомни слово. Повтори. Не смог? То-то же!»"
    ]
}


def calculate_multicast(dice_value: int) -> tuple[int, str]:
    """Вычисляет множитель и текст для multicast по значению dice (1-64)"""
    if dice_value == 64:
        return 4, "\n🎰🎰🎰 <b>ДЖЕКПОТ!!!</b>\n🗣️ Ogre Magi <i>«КАКОВЫ ШАНСЫ?!»</i>"
    elif dice_value >= 48:  # 49-64
        return 3, f"\n{random.choice(MULTICAST_TEXTS[3])}"
    elif dice_value >= 16:  # 16-48
        return 2, f"\n{random.choice(MULTICAST_TEXTS[2])}"
    else:  # 1-15 - обычный ролл без мультикаста
        return 1, ""


def check_multicast(fissure_size):
    """
    Каскадный мультикаст (генератор).
    Вызывается ТОЛЬКО когда мультикаст уже выбран.
    Yields: (step_number, extra_roll) на каждом шаге каскада.
    """
    for i, chance in enumerate(MULTICAST_CASCADE):
        if random.random() < chance:
            extra_roll, _, is_fatal, _ = calculate_fissure_roll(fissure_size)
            if not is_fatal:
                yield i + 2, extra_roll
        else:
            break


# Multicast slot animation helpers
SLOT_SYMBOLS = ["🍒", "🍋", "🍇", "💎", "🔥", "⚡", "7️⃣", "🎰"]


def slot_animation(level):
    """Генерирует слот-анимацию: 3 одинаковых = переход на уровень"""
    symbol = random.choice(SLOT_SYMBOLS)
    return f"🎰 {symbol}{symbol}{symbol}"


async def send_multicast_anim(chat_id, display_username, level, bot, is_test=False):
    """Анимация мультикаста с слот-машиной"""
    prefix = "🧪 ТЕСТ\n" if is_test else ""
    slot_text = slot_animation(level)
    return await bot.send_message(
        chat_id=chat_id,
        text=f"🎲 {display_username}\n\n{prefix}{slot_text}\n👹⚡ Мультикаст ×{level}!",
        parse_mode="HTML"
    )


async def handle_multicast_cascade(bot, chat_id, display_username, roll, event_roll, zeus_chance, multicast_chance, is_weekend, original_roll):
    """
    Handles the multicast (x2, x3, x4) slot animation and roll multiplication.
    Returns: (roll, cascade_count, multicast_text, slot_msg_ids, original_roll)
    This is extracted logic from the main fissure handler.
    """
    slot_msg_ids = []
    cascade_count = 1
    multicast_text = ""

    slot_emojis = ["🍒", "🍋", "🍇", "🔔", "💎"]

    if event_roll < zeus_chance + multicast_chance:
        # 🎰 МУЛЬТИКАСТ — слоты как в казино
        if random.random() < 0.75:
            cascade_count = 2
            jackpot_symbol = random.choice(slot_emojis)
            slots = [jackpot_symbol, jackpot_symbol, jackpot_symbol]

            msg = await bot.send_message(
                chat_id=chat_id,
                text=f"🎰 {' | '.join(slots)} | x2"
            )
            slot_msg_ids.append(msg.message_id)
            await asyncio.sleep(1)

            if random.random() < 0.25:
                cascade_count = 3
                jackpot_symbol = random.choice(slot_emojis)
                slots = [jackpot_symbol, jackpot_symbol, jackpot_symbol]

                msg = await bot.send_message(
                    chat_id=chat_id,
                    text=f"🎰 {' | '.join(slots)} | x3"
                )
                slot_msg_ids.append(msg.message_id)
                await asyncio.sleep(1)

                if random.random() < 0.15:
                    cascade_count = 4
                    jackpot_symbol = random.choice(slot_emojis)
                    slots = [jackpot_symbol, jackpot_symbol, jackpot_symbol]

                    msg = await bot.send_message(
                        chat_id=chat_id,
                        text=f"🎰 {' | '.join(slots)} | x4"
                    )
                    slot_msg_ids.append(msg.message_id)
                    await asyncio.sleep(0.5)
                else:
                    slots = random.sample(slot_emojis, 3)
                    msg = await bot.send_message(
                        chat_id=chat_id,
                        text=f"🎰 {' | '.join(slots)} | x4"
                    )
                    slot_msg_ids.append(msg.message_id)
                    await asyncio.sleep(0.5)
                    cascade_count = 3
            else:
                slots = random.sample(slot_emojis, 3)
                msg = await bot.send_message(
                    chat_id=chat_id,
                    text=f"🎰 {' | '.join(slots)} | x3"
                )
                slot_msg_ids.append(msg.message_id)
                await asyncio.sleep(0.5)
                cascade_count = 2
        else:
            multicast_count = 1

        if original_roll is not None:
            original_roll = roll
        roll = roll * cascade_count

        if cascade_count >= 4:
            increment_stat("multicast_x4")
        elif cascade_count >= 3:
            increment_stat("multicast_x3")
        elif cascade_count >= 2:
            increment_stat("multicast_x2")

        if cascade_count > 1:
            multicast_text = f"\n{random.choice(MULTICAST_TEXTS[cascade_count])}"

    return roll, cascade_count, multicast_text, slot_msg_ids, original_roll
