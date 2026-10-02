"""Интеграционный тест: реальные хендлеры бота на временной SQLite-базе.

Путь игрока целиком: /tour -> кнопка «Принять участие» -> бот собирает
команды по рангам -> капитан жмёт «Мой матч» и сдаёт счёт -> сетка показывает
его галочку, а у соперника значков нет.
"""

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

DB = ROOT / "test_tournament_handlers.db"
DB.unlink(missing_ok=True)

# database.py читает DATABASE_URL при импорте, поэтому задаём переменную
# ДО первого импорта database.
os.environ["DATABASE_URL"] = "sqlite:///" + DB.as_posix()

import database as _db  # noqa: E402
import tournament as T  # noqa: E402

assert _db.DATABASE_URL == os.environ["DATABASE_URL"]

FAILURES = []
SENT = []


def check(name, condition, extra=""):
    print(("  OK   " if condition else "  FAIL ") + name + ((" -> " + extra) if extra else ""))
    if not condition:
        FAILURES.append(name)


class FakeUser:
    def __init__(self, uid, username="player"):
        self.id = uid
        self.username = username


class FakeChat:
    def __init__(self, cid):
        self.id = cid
        self.type = "group"

    async def send_message(self, text, parse_mode=None, reply_markup=None):
        SENT.append({"text": text, "markup": reply_markup})


class FakeMessage:
    """Сообщение в чате.

    Важная деталь реальности: у сообщения, которое отправил бот, from_user —
    сам бот, а не игрок. Поэтому автор сообщения нельзя использовать как
    зрителя сетки: зрителя нужно брать из нажавшего кнопку.
    """

    def __init__(self, user, chat, bot_author=True):
        self.from_user = FakeUser(0, "fissure_bot") if bot_author else user
        self.chat = chat
        self.text = ""
        self.markup = None

    async def reply_text(self, text, parse_mode=None, reply_markup=None,
                         disable_web_page_preview=False):
        self.text = text
        self.markup = reply_markup
        SENT.append({"text": text, "markup": reply_markup})


class FakeQuery:
    """callback_query.

    В реальности query.message — это сообщение САМОГО БОТА с кнопками,
    поэтому его from_user = бот, а не тот, кто нажал. Именно на этом
    спотыкалась старая логика выбора зрителя.
    """
    def __init__(self, data, user, chat):
        self.data = data
        self.from_user = user
        self.message = FakeMessage(user, chat, bot_author=True)
        self.alerts = []

    async def answer(self, text=None, show_alert=False):
        if text:
            self.alerts.append(text)

    async def edit_message_text(self, text, parse_mode=None, reply_markup=None):
        await self.message.reply_text(text, parse_mode, reply_markup)


class FakeUpdate:
    def __init__(self, user, chat, query=None):
        self.effective_user = user
        self.effective_chat = chat
        # Сообщение команды принадлежит игроку: from_user — он сам.
        self.effective_message = FakeMessage(user, chat, bot_author=False)
        self.callback_query = query


CTX = type("Ctx", (), {"args": []})()


import tournament_handlers as H  # noqa: E402

# Схему намеренно НЕ создаём заранее: первый вызов /tour должен сам
# разобраться с пустой базой — именно так падал прод до фикса.

# Ранги задаём сами, чтобы тест не зависел от профилей в БД.
RANK_BY_USER = {1: 80, 2: 70, 3: 70, 4: 60, 5: 50,
                6: 50, 7: 40, 8: 30, 9: 30, 10: 20}
H._user_rank_tier = lambda uid: RANK_BY_USER.get(uid, 0)
H._admin_id = lambda: 1

CHAT = FakeChat(-100777)


def run(coro):
    return asyncio.run(coro)


def last_text():
    return SENT[-1]["text"] if SENT else ""


def press(data, uid):
    """Нажимает кнопку с callback_data от имени игрока."""
    query = FakeQuery(data, FakeUser(uid), CHAT)
    update = FakeUpdate(FakeUser(uid), CHAT, query)
    if data.startswith(H.CB_JOIN):
        run(H.tour_join_callback(update, CTX))
    elif data.startswith(H.CB_SCORE):
        run(H.tour_score_callback(update, CTX))
    elif data.startswith(H.CB_START):
        run(H.tour_start_callback(update, CTX))
    elif data.startswith(H.CB_SERVER):
        run(H.tour_server_callback(update, CTX))
    elif data.startswith(H.CB_LOBBY):
        run(H.tour_lobby_callback(update, CTX))
    else:
        run(H.tour_bracket_callback(update, CTX))
    return query


# --- 1. /tour, пока турнира нет ---
run(H.tour_command(FakeUpdate(FakeUser(1), CHAT), CTX))
check("без турнира бот зовёт его создать", "/newtour" in last_text(), last_text())

# --- 2. Создание турнира: только администратор ---
run(H.newtour_command(FakeUpdate(FakeUser(999), CHAT), CTX))
check("чужой не может создать турнир", "администратор" in last_text(), last_text())

run(H.newtour_command(FakeUpdate(FakeUser(1), CHAT), CTX))
# /newtour отправляет два сообщения: приглашение и подсказку админу.
invite, hint = SENT[-2], SENT[-1]
check("админ создал турнир", "Боевой кубок" in invite["text"], invite["text"])
check("в приглашении кнопка участия",
      invite["markup"].inline_keyboard[0][0].callback_data.startswith(H.CB_JOIN))

tid = int(T.active_tournament(CHAT.id)['id'])
check("турнир сохранён", tid > 0, str(tid))
check("статус = registration", T.get_tournament(tid)['status'] == 'registration')
check("админу показана кнопка сетки",
      any(b.callback_data == f"{H.CB_BRACKET}{tid}"
          for r in hint["markup"].inline_keyboard for b in r),
      str([b.callback_data for r in hint["markup"].inline_keyboard for b in r]))
# Сразу после создания участников 0, поэтому кнопки старта ещё нет.
check("до записи кнопки старта нет",
      not any(b.callback_data.startswith(H.CB_START)
              for r in hint["markup"].inline_keyboard for b in r))

# --- 3. Запись через кнопку ---
# Девять игроков пишутся первыми, админ записывается последним — так его
# сообщение о записи несёт кнопки навигации.
for uid in range(2, 11):
    press(f"{H.CB_JOIN}{tid}", uid)

q_admin = press(f"{H.CB_JOIN}{tid}", 1)
check("записались все 10 игроков", T.count_players(tid) == 10, str(T.count_players(tid)))
check("после записи показан ранг игрока", "Ваш ранг" in q_admin.message.text,
      q_admin.message.text)

# Кнопка старта должна оставаться под рукой: раньше она была только в /tour,
# и запустить турнир без неё было невозможно.
kb_admin = q_admin.message.markup.inline_keyboard
check("админ после записи видит «Начать турнир»",
      any(btn.callback_data == f"{H.CB_START}{tid}" for row in kb_admin for btn in row),
      str([b.callback_data for r in kb_admin for b in r]))
check("админ после записи видит «Сетка»",
      any(btn.callback_data == f"{H.CB_BRACKET}{tid}"
          for row in kb_admin for btn in row))

q = press(f"{H.CB_JOIN}{tid}", 1)
check("повторная запись отклонена", "уже записаны" in q.message.text.lower(),
      q.message.text)
check("число участников не изменилось", T.count_players(tid) == 10)

# --- 4. /tour во время регистрации ---
# Проверяем на игроке, который ещё не записан: только у него виден ранг,
# кнопка участия и напоминание, что порога нет.
RANK_BY_USER[11] = 60
run(H.tour_command(FakeUpdate(FakeUser(11), CHAT), CTX))
check("не записанному показан его ранг", "Ancient" in last_text(), last_text())
check("сказано, что порога нет", "порога нет" in last_text().lower(), last_text())
check("не записанному есть кнопка участия",
      any(btn.callback_data == f"{H.CB_JOIN}{tid}"
          for row in SENT[-1]["markup"].inline_keyboard for btn in row))

# Уже записанному кнопки участия быть не должно.
run(H.tour_command(FakeUpdate(FakeUser(1), CHAT), CTX))
check("записанному кнопки участия нет",
      not any(btn.callback_data.startswith(H.CB_JOIN)
              for row in SENT[-1]["markup"].inline_keyboard for btn in row))

# --- 4б. Старт с одним участником не должен «залипать» ---
# _create_bracket выходит раньше, не переводя турнир в active, из-за чего
# кнопку «Начать» можно было нажимать бесконечно (видно в прод-логе).
solo_chat = FakeChat(-100999)
tid_solo = T.create_tournament("Одинокий", chat_id=solo_chat.id, created_by=1)
T.join(tid_solo, 1, "solo", 50)          # в турнире только админ
q_solo = press(f"{H.CB_START}{tid_solo}", 1)
check("старт с одним игроком отклонён",
      T.get_tournament(tid_solo)['status'] == 'registration',
      T.get_tournament(tid_solo)['status'])
check("команды при одном игроке не созданы",
      T.list_teams(tid_solo) == [], str(T.list_teams(tid_solo)))
check("админу объяснили, сколько не хватает",
      any("Для старта нужно 10 участников, сейчас 1" in a for a in q_solo.alerts),
      str(q_solo.alerts))

# Кнопка старта не показывается, пока участников меньше двух.
SENT.clear()
run(H.tour_command(FakeUpdate(FakeUser(1), solo_chat), CTX))
check("при одном игроке кнопки старта нет",
      not any(b.callback_data.startswith(H.CB_START)
              for r in SENT[-1]["markup"].inline_keyboard for b in r))

# --- 5. Админ запускает турнир кнопкой (раньше вызывали build_teams вручную) ---
check("до старта турнир в регистрации",
      T.get_tournament(tid)['status'] == 'registration')
check("до старта матчей нет", T.current_match(tid, 1) is None)

# Кнопку «Начать» видит только админ.
run(H.tour_command(FakeUpdate(FakeUser(2), CHAT), CTX))
check("у обычного игрока нет кнопки «Начать»",
      not any(btn.callback_data.startswith(H.CB_START)
              for row in SENT[-1]["markup"].inline_keyboard for btn in row))

run(H.tour_command(FakeUpdate(FakeUser(1), CHAT), CTX))
check("у админа есть кнопка «Начать»",
      any(btn.callback_data == f"{H.CB_START}{tid}"
          for row in SENT[-1]["markup"].inline_keyboard for btn in row))

qs = press(f"{H.CB_START}{tid}", 1)
check("турнир запущен", T.get_tournament(tid)['status'] == 'active',
      T.get_tournament(tid)['status'])

teams = T.list_teams(tid)
check("бот собрал 2 команды по 5 человек",
      len(teams) == 2 and all(len(t['members']) == 5 for t in teams),
      str([len(t['members']) for t in teams]))
check("состав опубликован", any("Команды собраны" in s["text"] for s in SENT))
roster = next(s["text"] for s in SENT if "Команды собраны" in s["text"])
# Steam ID в общий чат не выводим: вход в лобби идёт по коду, а ID — личные данные.
check("в составе нет Steam ID", "7656119" not in roster and "steam_id" not in roster,
      roster[:120])
check("после старта матч появился", T.current_match(tid, 1) is not None)

run(H.tour_command(FakeUpdate(FakeUser(1), CHAT), CTX))
check("после старта бот показывает сетку", "Гранд-финал" in last_text(), last_text())
kb = SENT[-1]["markup"].inline_keyboard
check("у участника есть кнопка «Мой матч»",
      any(btn.callback_data.startswith(H.CB_SCORE)
          for row in kb for btn in row))
check("кнопка счёта ведёт на этот турнир",
      any(btn.callback_data == f"{H.CB_SCORE}{tid}"
          for row in kb for btn in row))

# Регресс: сетку по кнопке зритель должен получать персональной. Раньше id
# зрителя брался из query.message.from_user, а это автор сообщения бота,
# поэтому значки и кнопка «Мой матч» пропадали.
cap_probe = [m for m in teams[0]['members'] if m.get('is_captain')][0]['telegram_id']
qb = press(f"{H.CB_BRACKET}{tid}", cap_probe)
check("по кнопке сетка приходит тому, кто нажал",
      "Гранд-финал" in qb.message.text, qb.message.text)
check("по кнопке у участника есть «Мой матч»",
      any(btn.callback_data == f"{H.CB_SCORE}{tid}"
          for row in qb.message.markup.inline_keyboard for btn in row),
      str([b.callback_data for r in qb.message.markup.inline_keyboard for b in r]))

# --- 6. Кнопка «Мой матч» показывает варианты счёта ---
q = press(f"{H.CB_SCORE}{tid}", 1)
check("бот спрашивает счёт серии", "счёт" in q.message.text.lower(), q.message.text)
scores = [btn.callback_data for row in q.message.markup.inline_keyboard for btn in row]
check("есть все четыре варианта счёта",
      all(f"{H.CB_SCORE}{tid}:{s}" in scores for s in ("2:0", "2:1", "0:2", "1:2")),
      str(scores))

# --- 7. Капитан сдаёт счёт 2:1 ---
cap1 = [m for m in teams[0]['members'] if m.get('is_captain')][0]['telegram_id']
cap2 = [m for m in teams[1]['members'] if m.get('is_captain')][0]['telegram_id']

# --- 6б. Капитан создаёт лобби: название, сервер, пароль ---
run(H.tour_command(FakeUpdate(FakeUser(cap1), CHAT), CTX))
kb_cap = SENT[-1]["markup"].inline_keyboard
check("капитану показана кнопка «Создать лобби»",
      any(btn.callback_data == f"{H.CB_LOBBY}{tid}"
          for row in kb_cap for btn in row),
      str([b.callback_data for r in kb_cap for b in r]))

# cap2 тоже капитан (своей команды), поэтому проверяем обычного участника.
plain = [m['telegram_id'] for m in teams[1]['members']
         if not m.get('is_captain')][0]
run(H.tour_command(FakeUpdate(FakeUser(plain), CHAT), CTX))
kb_play = SENT[-1]["markup"].inline_keyboard
check("обычному участнику кнопки лобби нет",
      not any(btn.callback_data.startswith(H.CB_LOBBY)
              for row in kb_play for btn in row))
check("обычному участнику виден счёт своего матча",
      any(btn.callback_data.startswith(H.CB_SCORE)
          for row in kb_play for btn in row))

press(f"{H.CB_LOBBY}{tid}", cap1)
srv_btns = [b for row in SENT[-1]["markup"].inline_keyboard for b in row]
check("бот предложил выбрать сервер",
      any(b.callback_data.startswith(f"{H.CB_SERVER}{tid}:") for b in srv_btns),
      str([b.callback_data for b in srv_btns]))

# Чужой капитан лобби создать не может.
press(f"{H.CB_SERVER}{tid}:EU East", plain)
check("чужой не создаёт лобби",
      T.current_match(tid, cap1).get('lobby_server') != "EU East",
      str(T.current_match(tid, cap1).get('lobby_server')))

press(f"{H.CB_SERVER}{tid}:EU East", cap1)
saved = T.current_match(tid, cap1)
check("сервер сохранён", saved['lobby_server'] == "EU East", str(saved.get('lobby_server')))
check("пароль сохранён", bool(saved['lobby_password']), str(saved.get('lobby_password')))
check("название содержит турнир, команду и раунд",
      "Боевой кубок Fissure" in saved['lobby_name']
      and teams[0]['name'] in saved['lobby_name']
      and "Гранд-финал" in saved['lobby_name'],
      saved['lobby_name'])
check("код лобби сохранён", bool(saved['lobby_code']), str(saved.get('lobby_code')))
check("лобби опубликовано в чат", "Лобби к матчу" in last_text(), last_text())
check("в лобби указан соперник",
      any(t['name'] in last_text() for t in teams if t['id'] != teams[0]['id']))

# --- 6в. Капитан переименовывает команду ---
ctx_args = type("A", (), {"args": ["Team", "Zeus"]})()
run(H.teamname_command(FakeUpdate(FakeUser(cap1), CHAT), ctx_args))
name1 = [t['name'] for t in T.list_teams(tid) if t['id'] == teams[0]['id']][0]
name2_before = [t['name'] for t in T.list_teams(tid) if t['id'] == teams[1]['id']][0]
check("команда переименована капитаном", name1 == "Team Zeus", name1)

# Капитан другой команды переименовывает только свою — команду №1 не трогает.
run(H.teamname_command(FakeUpdate(FakeUser(cap2), CHAT),
                       type("A", (), {"args": ["Hacked"]})()))
name1_after = [t['name'] for t in T.list_teams(tid) if t['id'] == teams[0]['id']][0]
check("название чужой команды не изменилось", name1_after == "Team Zeus",
      f"{name1} -> {name1_after}")

# Обычный участник не переименовывает ничего.
run(H.teamname_command(FakeUpdate(FakeUser(plain), CHAT),
                       type("A", (), {"args": ["Hacked2"]})()))
check("участник не переименовывает команду",
      [t['name'] for t in T.list_teams(tid) if t['id'] == teams[0]['id']][0] == "Team Zeus")

press(f"{H.CB_SCORE}{tid}", cap2)
press(f"{H.CB_SCORE}{tid}:2:1", cap1)
check("после победы написано про чемпиона",
      "Чемпион" in last_text() or "следующий раунд" in last_text(), last_text())
check("турнир завершён", T.get_tournament(tid)['status'] == 'finished',
      T.get_tournament(tid)['status'])
champ = T.champion(tid)
check("чемпион — команда победителя", champ is not None, str(champ))

# --- 8. Персональная сетка: значки только на своём пути ---
run(H.tour_command(FakeUpdate(FakeUser(cap1), CHAT), CTX))
text_win = last_text()
check("победитель видит свою галочку", T.MARK_WIN in text_win, text_win)

run(H.tour_command(FakeUpdate(FakeUser(cap2), CHAT), CTX))
text_lose = last_text()
check("проигравший видит свой крестик", T.MARK_LOSS in text_lose, text_lose)
check("проигравший не видит галок", T.MARK_WIN not in text_lose, text_lose)

run(H.tour_command(FakeUpdate(FakeUser(999), CHAT), CTX))
text_out = last_text()
check("посторонний не видит значков",
      T.MARK_WIN not in text_out and T.MARK_LOSS not in text_out, text_out)

# --- 9. Чужой не может сдать счёт ---
teams2 = T.build_teams(T.create_tournament("Проверка", chat_id=-100888, created_by=1))
before = T.get_tournament(tid)['status']
press(f"{H.CB_SCORE}{tid}:2:0", 424242)
check("счёт от постороннего не изменил турнир",
      T.get_tournament(tid)['status'] == before)

# --- 12. Тестовый турнир вдвоём: /newtour Дуэль 1 ---
# Размер команды задаётся последним числом, чтобы можно было прогнать весь
# сценарий, не собирая две команды по пять человек.
title_a, size_a = H._parse_newtour_args(["Тест", "кубок"])
check("название без числа", title_a == "Тест кубок" and size_a == 5, f"{title_a}/{size_a}")
title_b, size_b = H._parse_newtour_args(["Тест", "1"])
check("размер 1 распознан", title_b == "Тест" and size_b == 1, f"{title_b}/{size_b}")
title_c, size_c = H._parse_newtour_args(["5"])
check("только число — это размер, не название", bool(title_c) and size_c == 5,
      f"{title_c}/{size_c}")
_, size_d = H._parse_newtour_args(["Тест", "99"])
check("неправдоподобный размер игнорируется", size_d == 5, str(size_d))

duel_chat = FakeChat(-100777)
SENT.clear()
run(H.newtour_command(FakeUpdate(FakeUser(1), duel_chat),
                      type("C", (), {"args": ["Дуэль", "1"]})()))
check("турнир вдвоём создан", "Дуэль" in SENT[-2]["text"], SENT[-2]["text"])
tid_duel = int(T.active_tournament(duel_chat.id)['id'])
check("размер команды = 1", T.get_tournament(tid_duel)['team_size'] == 1,
      str(T.get_tournament(tid_duel)['team_size']))

press(f"{H.CB_JOIN}{tid_duel}", 1)
press(f"{H.CB_JOIN}{tid_duel}", 2)
check("двое записались", T.count_players(tid_duel) == 2, str(T.count_players(tid_duel)))

press(f"{H.CB_START}{tid_duel}", 1)
check("турнир вдвоём стартовал", T.get_tournament(tid_duel)['status'] == 'active',
      T.get_tournament(tid_duel)['status'])
teams_duel = T.list_teams(tid_duel)
check("получилось 2 команды по 1 игроку",
      len(teams_duel) == 2 and all(len(t['members']) == 1 for t in teams_duel),
      str([len(t['members']) for t in teams_duel]))

run(H.tour_command(FakeUpdate(FakeUser(1), duel_chat), CTX))
check("видна сетка с матчем", "Гранд-финал" in last_text(), last_text())

cap_d = [m for m in teams_duel[0]['members'] if m.get('is_captain')][0]['telegram_id']
press(f"{H.CB_LOBBY}{tid_duel}", cap_d)
press(f"{H.CB_SERVER}{tid_duel}:EU East", cap_d)
check("лобби создано и в дуэли", bool(T.current_match(tid_duel, cap_d)['lobby_code']))

press(f"{H.CB_SCORE}{tid_duel}:2:0", cap_d)
check("победитель дуэли определён", T.champion(tid_duel) is not None,
      str(T.champion(tid_duel)))
check("турнир вдвоём завершён", T.get_tournament(tid_duel)['status'] == 'finished',
      T.get_tournament(tid_duel)['status'])

DB.unlink(missing_ok=True)
print()
if FAILURES:
    print(f"ПРОВАЛЕНО ({len(FAILURES)}): " + ", ".join(FAILURES[:5]))
    sys.exit(1)
print("ВСЁ ПРОШЛО")
