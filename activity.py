# -*- coding: utf-8 -*-
"""
Модуль "Актив" для fissure бота
Бот-эхолокация: отслеживание активности в чате
"""
import time
import random
import datetime
import logging
import asyncio

logger = logging.getLogger(__name__)


# =====================
# ФРАЗЫ ДЛЯ ЭХОЛОКАЦИИ
# =====================

ACTIVITY_PHRASES_60 = [
    "🦇 Эх... тут кто-нибудь есть?",
    "🦇 Кто-нибудь живой? Аууу?",
    "🦇 Привет? Тишина в эфире...",
    "🦇 Эй! Тут кто-то есть?",
    "🦇 Или все вымерли? 👀",
    "🦇 Что, молчат все?",
    "🦇 Бота игнорят? 😢",
    "🦇 Хоть кто-то скажи что-ли...",
    "🦇 Эх... раньше было веселее...",
    "🦇 Блин, никого не слышно...",
    "🦇 Тут кто-то живой? Ауу?",
    "🦇 Эхо, отзовись! 👻",
    "🦇 Кто меня слышит?",
    "🦇 Тишина... Кто-нибудь?",
    "🦇 Блин, одному скучно...",
    "🦇 Эй! Есть кто?",
    "🦇 Кто там? Покажись!",
    "🦇 Ну и тишина тут у вас...",
    "🦇 Скучаю... Кто-то напишите!",
    "🦇 Аууу... никого?",
]

ACTIVITY_PHRASES_75 = [
    "🦇 Аууу... я слышу своё эхо. Это грустно.",
    "🦇 Эхо молчит в ответ... грустно.",
    "🦇 Тишина... только эхо отвечает. Печаль.",
    "🦇 Ну хоть кто-то! Аууу!!!",
    "🦇 Слушайте! Я же не железный!",
    "🦇 Без общения я заскучаю...",
    "🦇 Молчание - знак согласия? Или пофигизма?",
    "🦇 Эх... один я, один...",
    "🦇 Давайте хоть поругаемся!",
    "🦇 Эхо: *молчание* Ладно, я подожду...",
    "🦇 Аууу... Эхо: аууу... грустно.",
    "🦇 Ну вы даёте... Совсем молчите?",
    "🦇 Я уже себе отвечаю... 😔",
    "🦇 Эх, тишина - лучший собеседник... нет, не лучший.",
    "🦇 Аууу... кто-нибудь!",
    "🦇 Слушайте вы! Аууу!!!",
    "🦇 Эхо: Да... никто не отвечает...",
    "🦇 Без вас скучно...",
    "🦇 Молчание как в морге... аууу!",
    "🦇 Давайте уже хоть поругаемся!",
]

ACTIVITY_PHRASES_80 = [
    "🦇 Ладно, я пошёл в паблик играть. Если что, я в миде на Пудже.",
    "🦇 Скука! Иду в паблик - там веселее!",
    "🦇 Иду нагибать ноунитов в паблике!",
    "🦇 Пока! буду фармить в паблике!",
    "🦇 Без вас скучно! Иду искать приключения!",
    "🦇 Ладно, вы там как хотите, а я на Пудже в миде!",
    "🦇 Эх! Пойду покручу спины в паблике!",
    "🦇 Ну всё, я пошёл! вернусь через 5 минут!",
    "🦇 Скучать не буду - иду в паблик катать!",
    "🦇 Пока! Кто хочет - пишите, когда вернусь!",
    "🦇 Иду фармить крипов, не скучайте!",
    "🦇 Ладно, катаю в паблике!",
    "🦇 Пока! Буду нагибать! 💪",
    "🦇 Ухожу в паблик! Вернусь героем!",
    "🦇 Ну всё, я в катке!",
    "🦇 Иду искать ноунитов для фана!",
    "🦇 Без вас делать нечего - иду в паблик!",
    "🦇 Пока! Буду фармить!",
    "🦇 Ладно, хоть в катке будет весело!",
    "🦇 Ушёл в паблик! Кто со мной?",
]

ACTIVITY_PHRASES_85 = [
    "🦇 Ну вы даёте. Я уже 0-5 слил, а вы всё молчите.",
    "🦇 Вернулся! Вы всё ещё молчите?",
    "🦇 Я покатался - а вы всё в астрале?",
    "🦇 0-5 слил, пока вас не было!",
    "🦇 Ну и группа... вообще никакой реакции!",
    "🦇 Эх! Хоть бы кто написал, пока я играл!",
    "🦇 Вернулся из паблика - а тут всё то же самое!",
    "🦇 Ну даёте... Даже не интересно!",
    "🦇 Играл, играл - а вы всё молчите!",
    "🦇 Вот что значит настоящая тишина!",
    "🦇 Я покатал, а вы всё молчите...",
    "🦇 Ну вы и молчуны!",
    "🦇 Вернулся - а тут пустота...",
    "🦇 Даже не знаю что сказать...",
    "🦇 Я в астрале от вашего молчания!",
    "🦇 Ну даёте... Я даже поиграть успел!",
    "🦇 5 минут прошли, а вы всё...",
    "🦇 Так и будете молчать?",
    "🦇 Я уже поиграл, а вы всё...",
    "🦇 Ну и дела... тишина и тишина...",
]

ACTIVITY_ECHO_REPLY = [
    "🦇 Эхо: Ауу... Эхо: Ауу... Эхо: Ауу... хватит, я понял.",
    "🦇 Ладно! Понял намёк! Больше не буду! 😢",
    "🦇 Эхо: *молчание* Эхо: *молчание* Ладно!",
    "🦇 Ну всё, я заткнулся! Больше не буду беспокоить!",
    "🦇 Понял! Эхо: тишина. Ладно, я понял!",
    "🦇 Аууу... Аууу... Хватит! Я всё понял!",
    "🦇 Эхо: Ауу... Эхо: Ауу... Ок, я замолкаю!",
    "🦇 Ну всё, я понял! Не буду надоедать!",
    "🦇 Ладно-ладно! Молчу! Жду когда напишут!",
    "🦇 Эхо: Ауу... *тишина* Ок, понял!",
    "🦇 Эхо: да... эхо: ладно... я замолкаю.",
    "🦇 Ладно! Понял! Молчу!",
    "🦇 Эх... тишина победила. Сдаюсь!",
    "🦇 Ок, ок! Замолкаю!",
    "🦇 Эхо: *молчание* - и я молчу!",
    "🦇 Ну всё, я понял! Больше ни слова!",
    "🦇 Понял намёк. заткнулся.",
    "🦇 Ладно! Без вопросов! Молчу!",
    "🦇 Эхо: аууу... а я: ладно, я понял!",
    "🦇 Окей, молчу. больше ни слова!",
]

ACTIVITY_SELF_REPLY = [
    "🦇 Есть. Я. И больше никого.",
    "🦇 Я тут. Как всегда. один.",
    "🦇 Эхо: да... эхо: да... ладно, я один.",
    "🦇 Тишина - мой лучший друг.",
    "🦇 Ответ: никто. Кроме меня.",
    "🦇 Как обычно - только я.",
    "🦇 Ну хоть эхо есть. Привет, эхо!",
    "🦇 Ладно, хоть стена откликнется... нет, не откликнется.",
    "🦇 Эх... только я и тишина.",
    "🦇 Я тут. Как обычно. один. 😢",
    "🦇 Ответов 0. Я один. Как всегда.",
    "🦇 Эхо: привет! Я: привет... грустно.",
    "🦇 Ну хоть я есть!",
    "🦇 Тишина... Ну ладно, я тут!",
    "🦇 Ответ: тишина. Но я есть!",
    "🦇 Как обычно - я и эхо.",
    "🦇 Ну хоть стена не отвечает...",
    "🦇 Я - единственный собеседник себе.",
    "🦇 Эх... один в тишине...",
    "🦇 Ладно, хоть я есть!",
]

ACTIVITY_NIGHT = [
    "🦇 Спокойной ночи, дотеры. Если кто не спит — играйте тихо, я молчу.",
    "🦇 Спокойной ночи! 💤",
    "🦇 Спокойной ночи! Завтра будет новый день.",
    "🦇 Спокойной ночи! Zzz...",
    "🦇 Спокойной ночи! Я тоже спать.",
    "🦇 Спокойной ночи! Вижу, все уснули. 💤",
    "🦇 Ночная тишина... Спокойной ночи!",
    "🦇 Zzz... Спокойной ночи!",
    "🦇 Ладно, спокойной ночи! До утра!",
    "🦇 Все спят? Спокойной ночи! 💤",
    "🦇 Спокойной ночи! Сладких снов!",
    "🦇 Ночь! Все спят - я тоже.",
    "🦇 Спокойной ночи, народ!",
    "🦇 Zzz... иду спать. Спокойной ночи!",
    "🦇 Ночная смена - я спит. Спокойной ночи!",
    "🦇 Спокойной ночи! До завтра!",
    "🦇 Все в сон? Я тоже на боковую!",
    "🦇 Ночной дозор... завершён. Спокойной ночи!",
    "🦇 Ладно, спокойной ночи! Завтра будет день!",
    "🦇 Спокойной ночи! Кто не спит - тот молчит! 😴",
]

ACTIVITY_MORNING = [
    "🦇 Доброе утро! Чай, кофе, калибровка?",
    "🦇 Утро! Кто на катку? ☕🎮",
    "🦇 Доброе утро! Всем кофе и каток!",
    "🦇 Утречко! Готовы к каточке? 🎮",
    "🦇 Доброе утро! Время катать!",
    "🦇 Утро наступило! Кто на катку?",
    "🦇 Доброе утро! Начинаем день с катки!",
    "🦇 Солнце встало! Каток ждёт! 🎮",
    "🦇 Утро! Кофе, завтрак, катка!",
    "🦇 Доброе утро! Все на катку!",
    "🦇 Утро! Кто не спал - тот молодец!",
    "🦇 Доброе утро! Как спалось?",
    "🦇 Утречко! Всем привет!",
    "🦇 Доброе утро! Новый день - новые катки!",
    "🦇 Утро! Солнце встало, народ просыпайся!",
    "🦇 Доброе утро! Кто готов к катке?",
    "🦇 Утро! Всем привет из утренней смены!",
    "🦇 Доброе утро! Начинаем день!",
    "🦇 Утречко! кто не выспался - пьём кофе! ☕",
    "🦇 Доброе утро! Все на катку!",
]

ACTIVITY_USER_REPLY = [
    "🦇 Ура! Я не один! {username}, ты мой герой!",
    "🦇 Ооо! {username} тут! Давайте общаться! 🎉",
    "🦇 Наконец-то! {username}, ты меня спас от скуки!",
    "🦇 {username} написал(а)! Я так рад(а)!",
    "🦇 Даешь активность! {username} на связи! 💪",
    "🦇 Спасибо {username}! Не дал(а) мне помереть от скуки!",
    "🦇 Эх, {username} - герой дня!",
    "🦇 {username} - ты топ! Спасибо что пишешь!",
    "🦇 Наконец-то жизнь в чате! {username}, уважаю!",
    "🦇 {username} - легенда чата!",
    "🦇 Ооо! {username}! Давно не виделись!",
    "🦇 Привет {username}! Рад видеть!",
    "🦇 {username}! Ты вернул(а) меня к жизни!",
    "🦇 Наконец-то кто-то! {username}, ты крут!",
    "🦇 Эй! {username}! Я скучал!",
    "🦇 {username}, ты мой спаситель!",
    "🦇 Опа! {username} на связи!",
    "🦇 Дааа! {username} тут! Ура!",
    "🦇 {username} - герой! Спасибо что пишешь!",
    "🦇 Наконец-то! {username}, ты лучший!",
]

ACTIVITY_PROVOCATION_1 = [
    "🦇 Спорим, никто не напишет следующую минуту?",
    "🦇 Ставлю 100 рублей - тишина на минуту!",
    "🦇 Кто сейчас напишет - тот красава!",
    "🦇 Нужен волшебник! Кто напишет первым?",
    "🦇 Жду... жду... кто первый?",
    "🦇 Скучно... никто не хочет со мной пообщаться?",
    "🦇 Народ! Кто живой? Отзовитесь!",
    "🦇 Эй! Есть кто? Или я тут один буду?",
    "🦇 Одиночество - это когда я тут один.",
    "🦇 Ну и день сегодня... никого нет.",
    "🦇 Спорим, я выиграю? Тишина - 1, я - 0!",
    "🦇 Кто не спит - тот напиши хоть что-то!",
    "🦇 Ну давайте! Кто первый?",
    "🦇 Народ! Просыпайтесь!",
    "🦇 Эй! Кто живой?",
    "🦇 Ставлю что тишина победит!",
    "🦇 Давайте уже хоть что-то напишите!",
    "🦇 Скука... Кто со мной?",
    "🦇 Жду... Или никого нет?",
    "🦇 Эй! Есть кто?",
]

ACTIVITY_PROVOCATION_1_REPLY = [
    "🦇 Выиграл. Фу таким быть.",
    "🦇 Точно, никто не написал. Ну и ладно!",
    "🦇 Ха! Я был прав - вы все спите!",
    "🦇 Ладно, я пошутил. Но вы правда молчите!",
    "🦇 Эх... никто не рискнул. Ну да ладно!",
    "🦇 А могли бы выиграть! Но нет - спите!",
    "🦇 Ваше молчание - мой выигрыш. Спасибо! 😄",
    "🦇 Ставка не состоялась. Но тишина победила!",
    "🦇 Ну что... тишина 1, вы 0. Победила дружба!",
    "🦇 Эх, а я верил в вас... но вы молчите.",
    "🦇 Тишина - мой лучший друг!",
    "🦇 Точно, никто не рискнул!",
    "🦇 Вау... Тишина... Победа за мной!",
    "🦇 Ну ладно, я выиграл!",
    "🦇 Эх, а вы могли бы выиграть...",
    "🦇 Ставка выиграна! Тишина - чемпион!",
    "🦇 Как обычно - я прав!",
    "🦇 Ладно, забейте! Я всё равно выиграл!",
    "🦇 Это была лёгкая победа!",
    "🦇 Ну что... Я победил!",
]

ACTIVITY_PROVOCATION_2 = [
    "🦇 Кто сейчас играет — киньте +, кто не играет — киньте -.",
    "🦇 Опрос! + играет, - не играет! Голосуем!",
    "🦇 Народ! Кидайте + если вкатываете, - если отдыхаете!",
    "🦇 Давайте узнаем кто тут катки! + за игру, - против!",
    "🦇 Проверим активность! + = в игре, - = афк",
    "🦇 Голосуем, товарищи! + и - в чат!",
    "🦇 Напишите + если хотите катку, - если лень!",
    "🦇 Кто готов к бою? + не хочет играть? -",
    "🦇 Давайте посчитаем! + играет, - отдыхает!",
    "🦇 Эй геймеры! + катка vs - афк",
    "🦇 + Кто вкатывает? - Кто отдыхает?",
    "🦇 Опрос! + за игру, - против!",
    "🦇 Народ! Проверяем кто онлайн! +-",
    "🦇 Давайте! + играем vs - отдыхаем!",
    "🦇 Голосуем! + в игре vs - afk",
    "🦇 + Катка vs - Отдых - ваш выбор!",
    "🦇 Проверим состав! + играем? - нет?",
    "🦇 Эй! + кто за катку? - кто против?",
    "🦇 Народ! + vs - - выбирайте!",
    "🦇 Кто на катку? + Не хочешь? -",
]

ACTIVITY_PROVOCATION_3 = [
    "🦇 Самый активный за сегодня получит роль \"Голос чата\"!",
    "🦇 Тот, кто больше всех напишет сегодня - получит титул!",
    "🦇 Сегодняшний топ чата получит звание! Пишите больше!",
    "🦇 Кто активнее всех сегодня - тому +1 к карме!",
    "🦇 Фармеры активности, внимание! Самый пишущий получит приз!",
    "🦇 Топ флудер дня получит корону! Давайте, соревнуемся!",
    "🦇 Сегодняшний чемпион чата будет награжден! Пишите, кто хочет!",
    "🦇 Активненькие! Кто больше всех напишет - получит звание!",
    "🦇 Ежедневный челлендж: напиши больше всех - получишь славу!",
    "🦇 Пиши больше всех сегодня и стань легендой чата!",
    "🦇 Сегодняшний чемпион флуда получит титул!",
    "🦇 Кто больше всех пишет - тому слава!",
    "🦇 Активность = уважение! Пишите больше!",
    "🦇 Топ чата сегодня - кто угодно может стать!",
    "🦇 Фармим сообщения! Топ получит приз!",
    "🦇 Давайте! Самый активный сегодня - герой!",
    "🦇 Соревнуемся! Кто больше всех напишет?",
    "🦇 Сегодняшний чемпион - будь ты им!",
    "🦇 Флудеры, внимание! Соревнование началось!",
    "🦇 Кто хочет стать легендой? Пишите больше всех!",
]


# =====================
# ГЛОБАЛЬНОЕ СОСТОЯНИЕ (per chat_id)
# =====================

chat_last_activity = {}
last_bot_message_time = {}
last_auuu_message_time = {}
last_60min_message_time = {}
bot_is_away = {}
bot_return_time = {}

sent_night_message = {}
sent_morning_greeting = {}
sent_60min_message = {}
sent_75min_message = {}
sent_80min_message = {}
sent_85min_message = {}
sent_echo_reply = {}
sent_self_reply = {}
sent_provocation_1 = {}
sent_provocation_2 = {}
sent_provocation_3 = {}
sent_provocation_1_replied = {}
provocation_1_sent_time = {}

daily_message_count = {}
current_voice_of_chat = {}
previous_voice_of_chat = {}


# =====================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# =====================

def get_chat_id(config_func):
    return config_func('digest_chat_id')


def update_chat_activity(chat_id):
    chat_last_activity[chat_id] = time.time()


# =====================
# ГОЛОС ЧАТА - СИСТЕМА РОЛЕЙ
# =====================

async def give_voice_of_chat_role(bot, chat_id, telegram_id, give=True):
    try:
        from database import get_user
        user = get_user(telegram_id)
        if not user:
            return
        
        username = user.get('username') or str(telegram_id)
        
        if give:
            text = f"🎖️ {username} становится \"Голосом чата\"! Поздравляем! 🏆"
        else:
            text = f"👋 {username} теряет статус \"Голос чата\". Новый день - новый лидер!"
        
        msg = await bot.send_message(chat_id=chat_id, text=text)
        await asyncio.sleep(10)
        try:
            await bot.delete_message(chat_id=chat_id, message_id=msg.message_id)
        except:
            pass
    except Exception as e:
        logger.error(f"Error in give_voice_of_chat_role: {e}")


async def activity_send_and_delete(bot, chat_id, text, delete_after=15):
    try:
        msg = await bot.send_message(chat_id=chat_id, text=text)
        await asyncio.sleep(delete_after)
        try:
            await bot.delete_message(chat_id=chat_id, message_id=msg.message_id)
        except:
            pass
    except Exception as e:
        logger.debug(f"Error in activity_send_and_delete: {e}")


async def activity_send_permanent(bot, chat_id, text):
    """Отправляет сообщение которое не удаляется"""
    try:
        await bot.send_message(chat_id=chat_id, text=text)
    except Exception as e:
        logger.debug(f"Error in activity_send_permanent: {e}")


async def check_activity_job(context, config_func=None):
    global chat_last_activity, last_bot_message_time, last_auuu_message_time, last_60min_message_time
    global bot_is_away, bot_return_time
    global sent_night_message, sent_morning_greeting
    global sent_60min_message, sent_75min_message, sent_80min_message, sent_85min_message
    global sent_echo_reply, sent_self_reply
    global sent_provocation_1, sent_provocation_2, sent_provocation_3
    global daily_message_count, current_voice_of_chat, previous_voice_of_chat
    global provocation_1_sent_time
    
    if config_func is None:
        from database import get_config
        config_func = get_config
    
    now = time.time()
    chat_id = config_func('digest_chat_id')
    
    if not chat_id:
        return
    
    if chat_id not in chat_last_activity:
        chat_last_activity[chat_id] = now
    if chat_id not in last_bot_message_time:
        last_bot_message_time[chat_id] = 0
    if chat_id not in last_auuu_message_time:
        last_auuu_message_time[chat_id] = 0
    if chat_id not in last_60min_message_time:
        last_60min_message_time[chat_id] = 0
    if chat_id not in bot_is_away:
        bot_is_away[chat_id] = False
    if chat_id not in bot_return_time:
        bot_return_time[chat_id] = 0
    
    last_activity = chat_last_activity.get(chat_id, now)
    last_bot_msg_time = last_bot_message_time.get(chat_id, 0)
    last_auuu = last_auuu_message_time.get(chat_id, 0)
    last_60min = last_60min_message_time.get(chat_id, 0)
    is_away = bot_is_away.get(chat_id, False)
    return_time = bot_return_time.get(chat_id, 0)
    
    if is_away:
        if now >= return_time:
            bot_is_away[chat_id] = False
        else:
            return
    
    msk_hour = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=3)).hour
    time_since_last_message = now - last_activity
    
    # === УТРЕННЕЕ СООБЩЕНИЕ В 09:00 ===
    if msk_hour == 9:
        morning_sent = sent_morning_greeting.get(chat_id, False)
        if not morning_sent and now - last_bot_msg_time >= 60:
            text = random.choice(ACTIVITY_MORNING)
            await activity_send_permanent(context.bot, chat_id, text)
            last_bot_message_time[chat_id] = now
            sent_morning_greeting[chat_id] = True
        return
    
    # === ВЕЧЕРНЕЕ СООБЩЕНИЕ В 23:00 ===
    if msk_hour == 23:
        night_sent = sent_night_message.get(chat_id, False)
        if not night_sent and now - last_bot_msg_time >= 60:
            text = random.choice(ACTIVITY_NIGHT)
            await activity_send_permanent(context.bot, chat_id, text)
            last_bot_message_time[chat_id] = now
            sent_night_message[chat_id] = True
        return
    
    # Сброс флагов в полночь (00:00)
    if msk_hour == 0:
        sent_morning_greeting[chat_id] = False
        sent_night_message[chat_id] = False
        # Сброс счётчика бонусной фиссуры
        from main import daily_fissure_rolls
        daily_fissure_rolls = 0
    
    # Сброс флага ночи в 09:00 (чтобы не зависло)
    
    if msk_hour >= 0 and msk_hour < 8:
        sent_morning_greeting[chat_id] = False
        sent_provocation_1[chat_id] = False
        sent_provocation_2[chat_id] = False
        sent_provocation_3[chat_id] = False
        
        if time_since_last_message >= 3600 and time_since_last_message < 5400:
            night_sent = sent_night_message.get(chat_id, False)
            if not night_sent and now - last_bot_msg_time >= 60:
                text = random.choice(ACTIVITY_NIGHT)
                await activity_send_and_delete(context.bot, chat_id, text, delete_after=15)
                last_bot_message_time[chat_id] = now
                sent_night_message[chat_id] = True
        return
    
    if msk_hour >= 10:
        prev, new = reset_daily_stats(chat_id)
        
        if prev:
            await give_voice_of_chat_role(context.bot, chat_id, prev, give=False)
        if new:
            await give_voice_of_chat_role(context.bot, chat_id, new, give=True)
        
        sent_night_message[chat_id] = False
        sent_morning_greeting[chat_id] = False
        sent_60min_message[chat_id] = False
        sent_75min_message[chat_id] = False
        sent_80min_message[chat_id] = False
        sent_85min_message[chat_id] = False
        sent_echo_reply[chat_id] = False
        sent_self_reply[chat_id] = False
        sent_provocation_1[chat_id] = False
        sent_provocation_2[chat_id] = False
        sent_provocation_3[chat_id] = False
    
    if time_since_last_message >= 3600 and time_since_last_message < 4500:
        min60_sent = sent_60min_message.get(chat_id, False)
        if not min60_sent and now - last_bot_msg_time >= 60:
            text = random.choice(ACTIVITY_PHRASES_60)
            await activity_send_and_delete(context.bot, chat_id, text, delete_after=15)
            last_bot_message_time[chat_id] = now
            last_60min_message_time[chat_id] = now
            sent_60min_message[chat_id] = True
    
    elif time_since_last_message >= 4500 and time_since_last_message < 4800:
        min75_sent = sent_75min_message.get(chat_id, False)
        if not min75_sent and now - last_bot_msg_time >= 60:
            text = random.choice(ACTIVITY_PHRASES_75)
            await activity_send_and_delete(context.bot, chat_id, text, delete_after=15)
            last_bot_message_time[chat_id] = now
            last_auuu_message_time[chat_id] = now
            sent_75min_message[chat_id] = True
    
    elif time_since_last_message >= 4800 and time_since_last_message < 5100:
        min80_sent = sent_80min_message.get(chat_id, False)
        if not min80_sent and now - last_bot_msg_time >= 60:
            text = random.choice(ACTIVITY_PHRASES_80)
            await activity_send_and_delete(context.bot, chat_id, text, delete_after=15)
            last_bot_message_time[chat_id] = now
            bot_is_away[chat_id] = True
            bot_return_time[chat_id] = now + 300
            sent_80min_message[chat_id] = True
    
    elif time_since_last_message >= 5100 and time_since_last_message < 5400:
        min85_sent = sent_85min_message.get(chat_id, False)
        is_away_now = bot_is_away.get(chat_id, False)
        if not min85_sent and not is_away_now and now - last_bot_msg_time >= 60:
            text = random.choice(ACTIVITY_PHRASES_85)
            await activity_send_and_delete(context.bot, chat_id, text, delete_after=15)
            last_bot_message_time[chat_id] = now
            sent_85min_message[chat_id] = True
    
    elif (last_auuu > 0 and 
          now - last_auuu >= 60 and 
          now - last_auuu < 120 and
          now - last_activity >= 60 and
          not bot_is_away.get(chat_id, False)):
        echo_sent = sent_echo_reply.get(chat_id, False)
        if not echo_sent and now - last_bot_msg_time >= 60:
            text = random.choice(ACTIVITY_ECHO_REPLY)
            await activity_send_and_delete(context.bot, chat_id, text, delete_after=15)
            last_bot_message_time[chat_id] = now
            last_auuu_message_time[chat_id] = 0
            sent_echo_reply[chat_id] = True
    
    elif (last_60min > 0 and 
          now - last_60min >= 30 and 
          now - last_60min < 60 and
          now - last_activity >= 30 and
          not sent_self_reply.get(chat_id, False) and
          not bot_is_away.get(chat_id, False)):
        if not sent_self_reply.get(chat_id, False) and now - last_bot_msg_time >= 60:
            text = random.choice(ACTIVITY_SELF_REPLY)
            await activity_send_and_delete(context.bot, chat_id, text, delete_after=15)
            last_bot_message_time[chat_id] = now
            sent_self_reply[chat_id] = True
    
    elif time_since_last_message >= 5400 and time_since_last_message < 5700:
        prov1_sent = sent_provocation_1.get(chat_id, False)
        if not prov1_sent and now - last_bot_msg_time >= 60:
            text = random.choice(ACTIVITY_PROVOCATION_1)
            await activity_send_and_delete(context.bot, chat_id, text, delete_after=15)
            last_bot_message_time[chat_id] = now
            sent_provocation_1[chat_id] = True
            provocation_1_sent_time[chat_id] = now
    
    if chat_id in provocation_1_sent_time:
        sent_time = provocation_1_sent_time.get(chat_id, 0)
        if now - sent_time >= 60 and now - sent_time < 120:
            prov1_replied = sent_provocation_1_replied.get(chat_id, False)
            if not prov1_replied:
                text = random.choice(ACTIVITY_PROVOCATION_1_REPLY)
                await activity_send_and_delete(context.bot, chat_id, text, delete_after=15)
                last_bot_message_time[chat_id] = now
                provocation_1_sent_time.pop(chat_id, None)
    
    elif time_since_last_message >= 7200 and time_since_last_message < 7500:
        prov2_sent = sent_provocation_2.get(chat_id, False)
        if not prov2_sent and now - last_bot_msg_time >= 60:
            text = random.choice(ACTIVITY_PROVOCATION_2)
            await activity_send_and_delete(context.bot, chat_id, text, delete_after=15)
            last_bot_message_time[chat_id] = now
            sent_provocation_2[chat_id] = True
    
    elif time_since_last_message >= 9000 and time_since_last_message < 9300:
        prov3_sent = sent_provocation_3.get(chat_id, False)
        if not prov3_sent and now - last_bot_msg_time >= 60:
            text = random.choice(ACTIVITY_PROVOCATION_3)
            await activity_send_and_delete(context.bot, chat_id, text, delete_after=15)
            last_bot_message_time[chat_id] = now
            sent_provocation_3[chat_id] = True


async def on_user_message(context, username, telegram_id=None, config_func=None):
    from database import get_config
    
    if config_func is None:
        config_func = get_config
    
    chat_id = config_func('digest_chat_id')
    if not chat_id:
        return
    
    if telegram_id:
        increment_message_count(chat_id, telegram_id)
    
    if chat_id in sent_provocation_1 and sent_provocation_1.get(chat_id, False):
        if not sent_provocation_1_replied.get(chat_id, False):
            sent_provocation_1_replied[chat_id] = True
            if chat_id in provocation_1_sent_time:
                provocation_1_sent_time.pop(chat_id, None)
    
    text = random.choice(ACTIVITY_USER_REPLY).format(username=username)
    await activity_send_and_delete(context.bot, chat_id, text, delete_after=15)


def increment_message_count(chat_id, telegram_id):
    global daily_message_count
    if chat_id not in daily_message_count:
        daily_message_count[chat_id] = {}
    daily_message_count[chat_id][telegram_id] = daily_message_count[chat_id].get(telegram_id, 0) + 1


def get_top_user_today(chat_id=None):
    global daily_message_count
    
    if chat_id:
        chat_counts = daily_message_count.get(chat_id, {})
        if not chat_counts:
            return None
        top_user = max(chat_counts.items(), key=lambda x: x[1])
        if top_user[1] > 0:
            return top_user[0]
        return None
    
    if not daily_message_count:
        return None
    
    all_users = {}
    for chat_id, counts in daily_message_count.items():
        for user_id, count in counts.items():
            all_users[user_id] = all_users.get(user_id, 0) + count
    
    if not all_users:
        return None
    
    top_user = max(all_users.items(), key=lambda x: x[1])
    if top_user[1] > 0:
        return top_user[0]
    return None


def reset_daily_stats(chat_id):
    global daily_message_count, current_voice_of_chat, previous_voice_of_chat
    
    prev = current_voice_of_chat.get(chat_id)
    new = get_top_user_today(chat_id)
    
    if prev:
        previous_voice_of_chat[chat_id] = prev
    current_voice_of_chat[chat_id] = new
    
    if chat_id in daily_message_count:
        daily_message_count[chat_id] = {}
    
    return prev, new
