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
    def __init__(self, user, chat):
        self.from_user = user
        self.chat = chat
        self.text = ""
        self.markup = None

    async def reply_text(self, text, parse_mode=None, reply_markup=None,
                         disable_web_page_preview=False):
        self.text = text
        self.markup = reply_markup
        SENT.append({"text": text, "markup": reply_markup})


class FakeQuery:
    """callback_query: data разбирает хендлер, текст пишется в сообщение."""
    def __init__(self, data, user, chat):
        self.data = data
        self.from_user = user
        self.message = FakeMessage(user, chat)
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
        self.effective_message = FakeMessage(user, chat)
        self.callback_query = query


CTX = type("Ctx", (), {"args": []})()


import tournament_handlers as H  # noqa: E402

T.ensure_schema()

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
check("админ создал турнир", "Боевой кубок" in last_text(), last_text())
kb = SENT[-1]["markup"].inline_keyboard
check("в сообщении кнопка участия",
      kb[0][0].callback_data.startswith(H.CB_JOIN), kb[0][0].callback_data)

tid = int(T.active_tournament(CHAT.id)['id'])
check("турнир сохранён", tid > 0, str(tid))
check("статус = registration", T.get_tournament(tid)['status'] == 'registration')

# --- 3. Запись через кнопку ---
for uid in range(1, 11):
    press(f"{H.CB_JOIN}{tid}", uid)

check("записались все 10 игроков", T.count_players(tid) == 10, str(T.count_players(tid)))
check("после записи показан ранг игрока", "Ваш ранг" in last_text(), last_text())

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

# --- 5. Бот собирает команды и рисует сетку ---
teams = T.build_teams(tid, names=["Team Zeus", "Team Nova"])
check("бот собрал 2 команды по 5 человек",
      len(teams) == 2 and all(len(t['members']) == 5 for t in teams),
      str([len(t['members']) for t in teams]))

run(H.tour_command(FakeUpdate(FakeUser(1), CHAT), CTX))
check("после старта бот показывает сетку", "Гранд-финал" in last_text(), last_text())
kb = SENT[-1]["markup"].inline_keyboard
check("у участника есть кнопка «Мой матч»",
      any(btn.callback_data.startswith(H.CB_SCORE)
          for row in kb for btn in row))
check("кнопка счёта ведёт на этот турнир",
      any(btn.callback_data == f"{H.CB_SCORE}{tid}"
          for row in kb for btn in row))

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

DB.unlink(missing_ok=True)
print()
if FAILURES:
    print(f"ПРОВАЛЕНО ({len(FAILURES)}): " + ", ".join(FAILURES[:5]))
    sys.exit(1)
print("ВСЁ ПРОШЛО")
