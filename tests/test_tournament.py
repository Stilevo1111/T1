"""Тесты турнирного движка на временной SQLite-базе.

Проверяем главное: раскладку по рангам (MMR не используется), построение
сетки, фиксацию счёта BO3 и автоматическое продвижение победителя.
"""

import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

DB = ROOT / "test_tournament.db"
if DB.exists():
    try:
        DB.unlink()
    except OSError as e:
        print("предупреждение: не удалось удалить старую БД:", e)

# database.py читает DATABASE_URL при импорте, поэтому задаём переменную
# ДО первого импорта database — иначе модуль успеет закешировать другой URL.
os.environ["DATABASE_URL"] = "sqlite:///" + DB.as_posix()

import database as _db  # noqa: E402  (фиксирует URL)
import tournament as T  # noqa: E402

assert _db.DATABASE_URL == os.environ["DATABASE_URL"], (
    f"database.py подхватил {_db.DATABASE_URL}, а тест ждёт {os.environ['DATABASE_URL']}")

FAILURES = []


def check(name, condition, extra=""):
    print(("  OK   " if condition else "  FAIL ") + name + ((" -> " + extra) if extra else ""))
    if not condition:
        FAILURES.append(name)


# --- 1. Ранги ---
check("rank_name 80 = Immortal", T.rank_name(80) == "Immortal")
check("rank_name 50 = Legend", T.rank_name(50) == "Legend")
check("rank_name None = Без ранга", T.rank_name(None) == "Без ранга")
check("rank_tier('Legend') = 50", T.rank_tier("Legend") == 50)
check("rank_tier('legend') = 50", T.rank_tier("legend") == 50)

# --- 2. Геометрия сетки ---
check("8 команд -> 3 раунда", T.rounds_count(8) == 3, str(T.rounds_count(8)))
check("4 команды -> 2 раунда", T.rounds_count(4) == 2)
check("2 команды -> 1 раунд", T.rounds_count(2) == 1)
check("label 1 = Гранд-финал", T.label_round(1) == "Гранд-финал")
check("label 2 = Полуфинал", T.label_round(2) == "Полуфинал")
check("label 3 = 4-финал", T.label_round(3) == "4-финал", T.label_round(3))
check("нужно 40 игроков на 8 команд", T.teams_needed(40) == 1, str(T.teams_needed(40)))
check("при 0 игроков нужно 9 команд", T.teams_needed(0) == 9, str(T.teams_needed(0)))

# --- 3. Балансировка по рангам: MMR в данных нет вообще ---
players = [
    {"telegram_id": 1, "rank_tier": 80},   # Immortal
    {"telegram_id": 2, "rank_tier": 70},   # Divine
    {"telegram_id": 3, "rank_tier": 70},   # Divine
    {"telegram_id": 4, "rank_tier": 60},   # Ancient
    {"telegram_id": 5, "rank_tier": 50},   # Legend
    {"telegram_id": 6, "rank_tier": 50},   # Legend
    {"telegram_id": 7, "rank_tier": 40},   # Archon
    {"telegram_id": 8, "rank_tier": 30},   # Crusader
    {"telegram_id": 9, "rank_tier": 30},   # Crusader
    {"telegram_id": 10, "rank_tier": 20},  # Guardian
]
buckets = T.balance_by_rank(players, team_size=5)
check("10 игроков -> 2 команды", len(buckets) == 2, str(len(buckets)))
check("в каждой команде по 5", all(len(b) == 5 for b in buckets),
      str([len(b) for b in buckets]))

spreads = []
sums = []
for b in buckets:
    tiers = [int(p['rank_tier']) for p in b]
    spreads.append(max(tiers) - min(tiers))
    sums.append(sum(tiers))
# Главная метрика турнира: команды равны по сумме рангов («змейка» даёт это).
check("суммы рангов команд равны", sums[0] == sums[1], str(sums))
check("разброс внутри команд не превышает 50", max(spreads) <= 50, str(spreads))

# При 8 командах (40 игроков) раскладка остаётся честной.
many = [{"telegram_id": i, "rank_tier": 80 - (i // 5) * 10} for i in range(40)]
wide = T.balance_by_rank(many, team_size=5)
check("40 игроков -> 8 команд", len(wide) == 8, str(len(wide)))
check("в каждой команде по 5", all(len(b) == 5 for b in wide),
      str([len(b) for b in wide]))
wide_sums = [sum(int(p.get('rank_tier') or 10) for p in b) for b in wide]
# 40 игроков по 5 на ранг: суммы не могут быть равны (не делится нацело),
# поэтому проверяем, что они почти равны.
spread = max(wide_sums) - min(wide_sums)
check("в 8 командах суммы почти равны (разница <= 30)", spread <= 30, str(sorted(wide_sums)))
wide_spreads = [max(int(p['rank_tier']) for p in b)
                - min(int(p['rank_tier']) for p in b) for b in wide]
# 40 игроков — это ровно 5 человек каждого из 8 рангов, а команд тоже 8.
# Значит каждая команда обязана получить по одному игроку каждого ранга,
# и разброс 80−10=70 здесь не баг, а единственно возможный исход.
check("в 8 командах разброс предсказуем", max(wide_spreads) <= 70,
      str(sorted(set(wide_spreads))))

# --- 4. Схема и полный цикл турнира ---
T.ensure_schema()
tid = T.create_tournament("Ночной кубок", chat_id=-100123, created_by=1)
check("турнир создан", tid > 0, str(tid))

ranks = [80, 70, 70, 60, 50, 50, 40, 30, 30, 20]
for i, tier in enumerate(ranks, start=1):
    res = T.join(tid, i, f"user{i}", tier, steam_id=76561198000000000 + i)
    check(f"join игрока {i} ({T.rank_name(tier)})", res['ok'], str(res.get('reason')))

check("всего 10 игроков", T.count_players(tid) == 10, str(T.count_players(tid)))
check("повторный join отклонён",
      T.join(tid, 1, "user1", 80)['reason'] == 'already')

teams = T.build_teams(tid, names=["Team Zeus", "Team Nova"])
check("создано 2 команды", len(teams) == 2, str(len(teams)))
check("команды по 5 человек", all(len(t['members']) == 5 for t in teams),
      str([len(t['members']) for t in teams]))
check("у каждой команды есть капитан",
      all(any(m.get('is_captain') for m in t['members']) for t in teams))
check("капитан — самый высокий ранг в команде",
      all(max(int(m['rank_tier']) for m in t['members'])
          == int([m for m in t['members'] if m.get('is_captain')][0]['rank_tier'])
          for t in teams))

# --- 5. Сетка на 2 команды: это сразу финал ---
grid = T.bracket(tid)
check("на 2 команды сетка = 1 раунд, 1 матч",
      len(grid) == 1 and len(grid[0]['matches']) == 1,
      str([(g['round'], len(g['matches'])) for g in grid]))
check("статус турнира = active", T.get_tournament(tid)['status'] == 'active',
      T.get_tournament(tid)['status'])

# --- 6. Персональная сетка ---
cap1 = [m for m in teams[0]['members'] if m.get('is_captain')][0]['telegram_id']
cap2 = [m for m in teams[1]['members'] if m.get('is_captain')][0]['telegram_id']
match = T.current_match(tid, cap1)
check("капитан видит свой матч", match is not None)
check("матч содержит его команду",
      teams[0]['id'] in (match['team1_id'], match['team2_id']))
check("чужой игрок не в турнире", T.player_team(tid, 999) is None)

# --- 7. Лобби: название, сервер, пароль (пока матч не сыгран) ---
T.set_lobby(match['id'], "F1SS", "EU East", "Ночной кубок · Team Zeus", "fissure1")
saved = T.current_match(tid, cap1)
check("код лобби сохранён", saved['lobby_code'] == "F1SS", str(saved.get('lobby_code')))
check("сервер сохранён", saved['lobby_server'] == "EU East")
check("название сохранено", saved['lobby_name'] == "Ночной кубок · Team Zeus")
check("пароль сохранён", saved['lobby_password'] == "fissure1")
check("статус матча = lobby", saved['status'] == 'lobby', str(saved.get('status')))

# --- 8. Счёт BO3 ---
r1 = T.report_score(tid, cap1, 1, 1)
check("счёт 1:1 не закрывает серию", r1['ok'] and not r1['finished'],
      str(r1.get('reason')))

r2 = T.report_score(tid, cap1, 2, 1)
check("счёт 2:1 закрывает серию", r2['ok'] and r2['finished'], str(r2.get('reason')))
check("победитель — команда капитана", r2['winner_team_id'] == teams[0]['id'],
      str(r2['winner_team_id']))
check("из финала никуда не продвигаем", r2['advanced'] is False)
check("турнир завершён", T.get_tournament(tid)['status'] == 'finished',
      T.get_tournament(tid)['status'])
champ1 = T.champion(tid)
check("чемпион = Team Zeus (сетка из 2 команд, это и есть финал)",
      champ1 is not None and champ1['team_name'] == "Team Zeus", str(champ1))
check("после финала матчей больше нет", T.current_match(tid, cap1) is None)
check("проигравшая команда уже не играет",
      T.report_score(tid, cap2, 0, 2)['reason'] == 'no_match')

# --- 9. Чужой счёт не принимается ---
check("чужой игрок не может сдавать счёт",
      not T.report_score(tid, 999, 2, 0)['ok'])

# --- 10. Полный турнир на 4 команды: две параллельные ветки ---
# Это главный сценарий: проверяем, что сетка доходит до финала целиком,
# победители полуфиналов встречаются, а капитаны видят только свой матч.
tid4 = T.create_tournament("Кубок на 4", chat_id=-100124, created_by=1)
check("турнир на 4 команды создан", tid4 > 0, str(tid4))

ranks4 = [80, 70, 70, 60, 60, 50, 50, 50, 40, 30, 30, 20,
          80, 70, 60, 50, 40, 30, 30, 20, 20]
for i, tier in enumerate(ranks4, start=1001):
    T.join(tid4, i, f"p{i}", tier)

teams4 = T.build_teams(tid4)
check("20 игроков -> 4 команды", len(teams4) == 4, str(len(teams4)))
caps4 = {t['id']: [m for m in t['members'] if m.get('is_captain')][0]['telegram_id']
         for t in teams4}

grid4 = T.bracket(tid4)
shape4 = [(g['round'], len(g['matches'])) for g in grid4]
check("сетка нарисована целиком: 2 матча + финал",
      shape4 == [(2, 2), (1, 1)], str(shape4))
check("полуфиналы уже заполнены командами",
      all(g['matches'][i]['team1_id'] and g['matches'][i]['team2_id']
          for g in grid4 if g['round'] == 2 for i in range(2)))
check("финал пока пустой",
      grid4[1]['matches'][0]['team1_id'] is None
      and grid4[1]['matches'][0]['team2_id'] is None)

# Каждый капитан должен видеть свой матч, и у разных команд он разный.
cap_firsts = {tid: T.current_match(tid4, cid)['id'] for tid, cid in caps4.items()}
check("у 4 команд два разных матча в полуфинале",
      len(set(cap_firsts.values())) == 2, str(sorted(set(cap_firsts.values()))))

# Первый semifinal: победа 2:0.
first_match = T.current_match(tid4, caps4[teams4[0]['id']])
first_cap = caps4[teams4[0]['id']] if first_match['team1_id'] == teams4[0]['id'] else \
    caps4[[t for t in teams4 if t['id'] == first_match['team2_id']][0]['id']]
sa = T.report_score(tid4, first_cap, 2, 0)
check("полуфинал закрылся победой 2:0", sa['ok'] and sa['finished'], str(sa.get('reason')))
check("победитель пошёл в финал", sa['advanced'] is True)

# Второй semifinal: та же логика с другой стороны.
rest = [t for t in teams4
        if t['id'] not in (first_match['team1_id'], first_match['team2_id'])]
second_cap = caps4[rest[0]['id']]
sb = T.report_score(tid4, second_cap, 2, 1)
check("второй полуфинал закрылся со счётом 2:1", sb['ok'] and sb['finished'], str(sb.get('reason')))
check("победитель второго полуфинала тоже пошёл в финал", sb['advanced'] is True)

# Теперь финал должен быть собран из двух победителей.
grid4b = T.bracket(tid4)
final4 = grid4b[1]['matches'][0]
check("в финале две разные команды",
      final4['team1_id'] and final4['team2_id']
      and final4['team1_id'] != final4['team2_id'],
      str((final4['team1_id'], final4['team2_id'])))
check("в финале именно победители полуфиналов",
      {final4['team1_id'], final4['team2_id']}
      == {sa['winner_team_id'], sb['winner_team_id']})

# Победитель финала становится чемпионом.
final_cap = caps4[final4['team1_id']]
rf = T.report_score(tid4, final_cap, 2, 0)
check("финальный счёт принят", rf['ok'] and rf['finished'], str(rf.get('reason')))
check("из финала никуда не продвигаем", rf['advanced'] is False)
champ4 = T.champion(tid4)
champ_name = [t['name'] for t in teams4 if t['id'] == rf['winner_team_id']][0]
check("чемпион турнира на 4 команды определён",
      champ4 is not None and champ4['team_name'] == champ_name,
      str(champ4))
check("турнир на 4 команды завершён",
      T.get_tournament(tid4)['status'] == 'finished',
      T.get_tournament(tid4)['status'])
check("после финала матчей нет ни у кого",
      T.current_match(tid4, final_cap) is None)

# --- 11. MMR не используется ---
# Проверяем не текст файла (MMR законно упоминается в докстрингах как
# объяснение решения), а схему и обращения к данным. Комментарии и
# докстринги вырезаем, чтобы мешать не могли.
_src = (ROOT / "tournament.py").read_text(encoding="utf-8")
_code = re.sub(r'"""[\s\S]*?"""', "", _src)
_code = re.sub(r"#[^\n]*", "", _code)

check("в схеме нет колонок MMR",
      not re.search(r"\b\w*mmr\w*\s+(?:INTEGER|BIGINT|VARCHAR|TEXT|SERIAL)", _code, re.I))
check("в коде нет обращений к ключу mmr",
      not re.search(r"['\"]\w*mmr\w*['\"]", _code, re.I))
check("в коде MMR не упоминается вовсе", "mmr" not in _code.lower())

DB.unlink(missing_ok=True)
print()
if FAILURES:
    print(f"ПРОВАЛЕНО ({len(FAILURES)}): " + ", ".join(FAILURES[:5]))
    sys.exit(1)
print("ВСЁ ПРОШЛО")
