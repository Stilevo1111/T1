"""
Roll system for fissure calculations.
Contains constants and pure calculation functions.
Extracted from main.py without any behavior changes.
"""

from __future__ import annotations

import random

# Type aliases (purely for readability, no runtime or behavior impact)
RollResult = tuple[float, str, bool, bool]
ProtectionResult = tuple[float, str]

__all__ = [
    # Constants
    "FATAL_ROLL",
    "ROLL_TEXTS",
    "ROLL_MEMES",
    "CATEGORY_PHRASES",
    "MULTICAST_TEXTS",
    # Calculation functions
    "calculate_fissure_roll",
    "apply_fissure_protection",
    "calculate_new_fissure",
    "calculate_streak_bonus",
]


# =====================
# ROLL SYSTEM CONSTANTS
# =====================

FATAL_ROLL = -10


# =====================
# ROLL TEXTS (organized by severity for maintainability)
# =====================

# === Positive Rolls ===
ROLL_TEXTS = {
    # Jackpot tier
    75: ["🏆 ЛЕГЕНДАРНЫЙ РОЛЛ!!! +75 СМ!!!", "💥 МЕГАДРОП!!! +75 СМ!!!", "🎯 ШОТ! +75 СМ!!!"],
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

    # Neutral / Small negative
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

    # Heavy negative / Fatal
    -10: ["💥 КАТАСТРОФА! -10 см!!!", "🌋 АПОКАЛИПСИС! -10 см!!!", "😵 СЕРВЕР УПАЛ! -10 СМ!!!", "💥 ДИСКОННЕКТ! -10 СМ!!!"],
    -11: ["💥 УЖАС! -11 СМ!!!", "☠️ КРАШ! -11 СМ!!!"],
    -12: ["💀 БОЛЬНО! -12 СМ!!!", "🌋 ВУЛКАН! -12 СМ!!!"],
    -13: ["💥 ПОЛНЫЙ КРАХ! -13 СМ!!!", "☠️ ФИНАЛ! -13 СМ!!!"],
    -14: ["💀 НЕВОССТАНОВИМО! -14 СМ!!!", "🌋 АПОКАЛИПСИС! -14 СМ!!!"],
    -15: ["💀 ФАТАЛЬНЫЙ УРОН! -15 СМ!!!", "🌋 КОНЕЦ! -15 СМ!!!", "☠️ ОТПРАВЛЕН В СТАРТ! -15 СМ!!!"],
}

# =====================
# ROLL MEMES (organized by severity)
# =====================

ROLL_MEMES = {
    # === Positive ===
    75: [
        "👁️ Войд: «Я видел будущее — тебя там нет»",
        "⚔️ Мирана: «За Найтсливер!»",
        "🌑 НС: «Из Мрака!»"
    ],
    50: [
        "💥 СиКей: «Хаос Данк!»",
        "🩹 СК: «Разлом исцеляется!»",
        "🩸 Блад: «Царство Крови!»"
    ],
    30: [
        "🔥 Эмбер: «Духами заклинаю!»",
        "🛡️ Свен: «За мой народ!»",
        "⚜️ Омни: «Клятва принесена!»"
    ],
    20: [
        "🌹 КоП: «Проклятие Розы!»",
        "🔨 Омни: «Я несу молот!»",
        "🗡️ Джагг: «Один клинок — одна цель»"
    ],
    15: [
        "✨ КотЛ: «Я — Свет!»",
        "🏹 ВР: «Странница возвращается»",
        "😈 ЛЦ: «Плачь ещё!»"
    ],
    10: [
        "🚫 АМ: «Магия — отстой!»",
        "👑 ВК: «За последнего короля!»",
        "🕳️ Войд: «Бездна зовёт»"
    ],
    9: [
        "👻 Рики: «За твоей спиной!»",
        "🧈 ПА: «Мягкий, как масло»",
        "🕷️ Бруд: «Гнездо жду»"
    ],
    5: [
        "🍖 Падж: «Свежее мясо!»",
        "🐟 Сларк: «Охота начинается»",
        "🐻 Урса: «Калечить! Убивать!»"
    ],
    1: [
        "🪨 Тайни: «Бросай меня!»",
        "🪙 Гамблер: «Везучая монетка»",
        "🧪 Мипо: «Малые начала»"
    ],

    # === Neutral / Negative ===
    0: [
        "💤 Висп: «Я отдохну теперь»",
        "⏳ Аганим: «Древние ждут»",
        "🧘 Элдер Т: «Созерцание»"
    ],
    -1: [
        "😔 Свен: «Я подвёл»",
        "😩 Зевс: «Не так»",
        "🌫️ Войд: «Видение тускнеет»"
    ],
    -5: [
        "🥶 Лина: «Пламя погасло»",
        "😖 Эмбер: «Я... споткнулся»",
        "💔 ЛЦ: «Моя честь... разбита»"
    ],
    -10: [
        "🚨 диктор: «Древний атакуют»",
        "🏃‍♂️💨 игра: «Команда тебя бросила»",
        "🌚 Тьма: «Победа тьмы»"
    ],
    -15: [
        "😭 диктор: «Свет повержен»",
        "🎭 Crownfall: «Твой MMR — ложь»",
        "🕳️ СК: «Обратно в разлом»"
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


# --- Private helpers (pure, no side effects, behavior unchanged) ---

def _get_early_game_roll(current_fissure: float) -> RollResult | None:
    """Early game protection and big bonus for very small fissures (< 5)."""
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
    return None


def _get_improved_roll(current_fissure: float) -> float | None:
    """Medium fissure bonus rolls."""
    if 5 <= current_fissure < 20 and random.random() < 0.4:
        improved_options = [3, 5, 10, 20]
        return random.choice(improved_options)
    return None


def _get_lucky_bonus(current_fissure: float) -> float | None:
    """Lucky bonus for large fissures."""
    if current_fissure >= 20:
        chance = 0.2 if current_fissure < 100 else 0.1
        if random.random() < chance:
            return random.choice([5, 10, 20])
    return None


def _weighted_choice(weighted: list[tuple[float, int]]) -> float:
    """Generic weighted random choice."""
    values, weights = zip(*weighted)
    return random.choices(values, weights=weights)[0]


# =====================
# ROLL CALCULATION FUNCTIONS
# =====================

def calculate_fissure_roll(current_fissure: float) -> RollResult:
    """
    Calculates new roll based on current fissure size.
    Returns: RollResult = (roll_value, message, is_fatal, got_help)
    """
    # Fatal chance for very large fissures
    if current_fissure >= 20:
        if random.random() < 0.02:
            return FATAL_ROLL, "FATAL DECREASE!", True, False

    # Early game strong protection / big help
    early = _get_early_game_roll(current_fissure)
    if early:
        return early

    # Medium fissure improvement
    improved = _get_improved_roll(current_fissure)
    if improved is not None:
        return improved, "🚀 УЛУЧШЕННЫЙ РОЛЛ!", False, True

    # Lucky bonus for big fissures
    lucky = _get_lucky_bonus(current_fissure)
    if lucky is not None:
        return lucky, "🍀 УДАЧНЫЙ РОЛЛ!", False, False

    # Normal balanced distribution (-15 ... +75)
    # Reduced chance for -1 and 0
    weighted_rolls: list[tuple[float, int]] = [
        (-15, 3), (-10, 5), (-7, 7), (-5, 8), (-3, 7), (-1, 2), (0, 2),
        (1, 5), (3, 7), (5, 8), (7, 7), (10, 8), (15, 6), (20, 5),
        (30, 4), (50, 2), (75, 1)
    ]
    roll = _weighted_choice(weighted_rolls)
    return roll, "", False, False


def apply_fissure_protection(current_fissure: float, roll: float, is_fatal: bool) -> ProtectionResult:
    """Applies protection for small fissures on fatal rolls"""
    if is_fatal and current_fissure < 5:
        reduced_roll = max(-5, roll)
        protection_msg = f"🛡 УРОН СНИЖЕН! Было {roll}, теперь {reduced_roll}"
        return reduced_roll, protection_msg

    return roll, ""


def calculate_streak_bonus(current_win_streak: int, base_roll: float) -> tuple[float, str]:
    """Streak bonus: +1cm per win streak (only for positive rolls)."""
    if current_win_streak > 0 and base_roll > 0:
        streak_bonus = current_win_streak
        new_roll = base_roll + streak_bonus
        streak_text = f"🔥 СТРИК x{current_win_streak}: +{streak_bonus} СМ"
        return new_roll, streak_text
    return base_roll, ""


# =====================
# MULTICAST (legacy constants kept for fissure handler text selection)
# =====================

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
