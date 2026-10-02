"""Турнирный движок Fissure.Bot: раскладка по рангам, сетка, продвижение победителей.

Заменяет прежнюю фичу «Список матчей»: вместо ленты личных игр бот ведёт
настоящий турнир — регистрация через Mini App, автоматическая раскладка
команд по рангам (MMR не используется), BO3 до двух побед и сетка
с персональными значками для каждого участника.

Схема таблиц взята из TOURNAMENT_TZ.md и адаптирована: `min_mmr` заменён
на `rank_tier`, потому что в боте отбор идёт по рангам.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# -------------------------------------------------------------------
# Ранги
# -------------------------------------------------------------------
# Значения совпадают с rank_tier Dota 2: чем больше, тем выше ранг.
RANK_TIERS = [
    (10, "Herald"), (20, "Guardian"), (30, "Crusader"), (40, "Archon"),
    (50, "Legend"), (60, "Ancient"), (70, "Divine"), (80, "Immortal"),
]
RANK_BY_TIER = {tier: name for tier, name in RANK_TIERS}
RANK_ORDER = {name: tier for tier, name in RANK_TIERS}


def rank_name(tier: int | None) -> str:
    """Человеческое имя ранга по его номеру."""
    if not tier:
        return "Без ранга"
    return RANK_BY_TIER.get(int(tier), f"Ранг {tier}")


def rank_tier(name: str | None) -> int:
    """Номер ранга по имени; неизвестное имя даёт Herald.

    Имена рангов латинские, поэтому регистр не важен: сравниваем
    в нижнем регистре, чтобы 'Legend' и 'legend' совпали.
    """
    if not name:
        return 10
    key = name.strip().lower()
    for label, tier in RANK_ORDER.items():
        if label.lower() == key:
            return tier
    return 10


# -------------------------------------------------------------------
# Геометрия сетки (single elimination)
# -------------------------------------------------------------------
TEAM_SIZE = 5           # человек в команде
FIRST_ROUND_TEAMS = 8   # команд в первой сетке


def rounds_count(teams: int) -> int:
    """Сколько раундов нужно на N команд (8 -> 3, 4 -> 2)."""
    count = 0
    while teams > 1:
        teams = (teams + 1) // 2
        count += 1
    return count


def teams_needed(players: int, team_size: int = TEAM_SIZE) -> int:
    """Сколько команд ещё нужно, чтобы набрать полную сетку."""
    if team_size <= 0:
        return 0
    return max(0, (FIRST_ROUND_TEAMS * team_size - players) // team_size + 1)


# -------------------------------------------------------------------
# Регистрация
# -------------------------------------------------------------------
def create_tournament(title: str, chat_id: int, created_by: int,
                      team_size: int = TEAM_SIZE, best_of: int = 3) -> int:
    """Создаёт турнир и возвращает его id."""
    ensure_schema()
    q = _q()
    _write(
        f"INSERT INTO tournaments (title, chat_id, status, team_size, best_of, created_by)"
        f" VALUES ({q}, {q}, {q}, {q}, {q}, {q})",
        (title, chat_id, 'registration', team_size, best_of, created_by))
    row = _read(
        f"SELECT id FROM tournaments WHERE chat_id = {q} AND title = {q}"
        f" ORDER BY id DESC LIMIT 1", (chat_id, title))
    return int(_get(row[0], 'id', 0) or 0) if row else 0


def get_tournament(tid: int) -> dict | None:
    rows = _read(f"SELECT * FROM tournaments WHERE id = {_q()}", (tid,))
    return dict(rows[0]) if rows else None


def active_tournament(chat_id: int) -> dict | None:
    """Открытый или идущий турнир чата."""
    rows = _read(
        f"SELECT * FROM tournaments WHERE chat_id = {_q()}"
        f" AND status IN ({_q()}, {_q()}) ORDER BY id DESC LIMIT 1",
        (chat_id, 'registration', 'active'))
    return dict(rows[0]) if rows else None


def count_players(tid: int) -> int:
    rows = _read(
        f"SELECT COUNT(*) AS c FROM tournament_players WHERE tournament_id = {_q()}",
        (tid,))
    return int(_get(rows[0], 'c', 0) or 0) if rows else 0


def list_players(tid: int) -> list[dict]:
    return _read(
        f"SELECT telegram_id, username, rank_tier, steam_id, team_id, is_captain"
        f" FROM tournament_players WHERE tournament_id = {_q()}"
        f" ORDER BY rank_tier DESC, joined_at ASC", (tid,))


def join(tid: int, telegram_id: int, username: str,
         tier: int, steam_id: int | None = None) -> dict:
    """Записывает игрока. MMR не используется — только ранг.

    Возвращает {'ok': bool, 'reason': str, 'players': int, 'teams': int}.
    """
    q = _q()
    tournament = get_tournament(tid)
    if not tournament:
        return {'ok': False, 'reason': 'not_found'}
    if tournament.get('status') != 'registration':
        return {'ok': False, 'reason': 'closed'}

    already = _read(
        f"SELECT id FROM tournament_players"
        f" WHERE tournament_id = {q} AND telegram_id = {q}", (tid, telegram_id))
    if already:
        return {'ok': False, 'reason': 'already'}

    players = count_players(tid)
    if players >= int(tournament.get('max_players') or 40):
        return {'ok': False, 'reason': 'full'}

    _write(
        f"INSERT INTO tournament_players"
        f" (tournament_id, telegram_id, rank_tier, username, steam_id)"
        f" VALUES ({q}, {q}, {q}, {q}, {q})",
        (tid, telegram_id, int(tier or 10), username, steam_id))
    players += 1
    team_size = int(tournament.get('team_size') or TEAM_SIZE)
    return {'ok': True, 'players': players, 'teams': teams_needed(players, team_size)}

def _is_pg() -> bool:
    from database import DATABASE_URL
    from urllib.parse import urlparse
    return "postgres" in urlparse(DATABASE_URL).scheme


def _q() -> str:
    """Плейсхолдер: тот же, что понимает database.execute_query."""
    return "%s" if _is_pg() else "?"


def _get(row, name: str, index: int):
    """Достаёт поле строки.

    Postgres отдаёт dict с именами колонок, sqlite — кортежи, которые _read
    превращает в dict с числовыми ключами. Поэтому сначала пробуем имя,
    затем позицию.
    """
    if row is None:
        return None
    if isinstance(row, dict):
        if name in row:
            return row[name]
        return row.get(str(index))
    try:
        return row[index]
    except (IndexError, KeyError, TypeError):
        return None


def _read(sql: str, params: tuple = ()) -> list[dict]:
    """Чтение из БД.

    Для sqlite используем sqlite3.Row: он поддерживает и обращение по имени
    колонки, и по индексу. Для postgres database.execute_query уже отдаёт
    dict с именами.
    """
    from database import get_connection
    import sqlite3

    if not _is_pg():
        conn = get_connection()
        try:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute(sql, params or ())
            return [dict(r) for r in cur.fetchall()] or []
        finally:
            conn.row_factory = None
            conn.close()

    from database import Database
    rows = Database().execute_query(sql, params, fetch="all") or []
    return [dict(r) if isinstance(r, dict) else {str(i): v for i, v in enumerate(r)}
            for r in rows]

PG_SCHEMA = [
    """CREATE TABLE IF NOT EXISTS tournaments (
        id SERIAL PRIMARY KEY,
        title VARCHAR(255) NOT NULL,
        chat_id BIGINT,
        status VARCHAR(20) DEFAULT 'registration',
        min_rank VARCHAR(30) DEFAULT 'Любой',
        max_players INTEGER DEFAULT 40,
        team_size INTEGER DEFAULT 5,
        best_of INTEGER DEFAULT 3,
        created_by BIGINT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        started_at TIMESTAMP,
        finished_at TIMESTAMP
    )""",
    """CREATE TABLE IF NOT EXISTS tournament_players (
        id SERIAL PRIMARY KEY,
        tournament_id INTEGER NOT NULL,
        telegram_id BIGINT NOT NULL,
        rank_tier INTEGER DEFAULT 10,
        username VARCHAR(255),
        steam_id BIGINT,
        team_id INTEGER,
        is_captain BOOLEAN DEFAULT FALSE,
        joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""",
    """CREATE TABLE IF NOT EXISTS tournament_teams (
        id SERIAL PRIMARY KEY,
        tournament_id INTEGER NOT NULL,
        name VARCHAR(100) NOT NULL,
        seed INTEGER DEFAULT 0,
        captain_id BIGINT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""",
    """CREATE TABLE IF NOT EXISTS tournament_matches (
        id SERIAL PRIMARY KEY,
        tournament_id INTEGER NOT NULL,
        round INTEGER NOT NULL,
        position INTEGER NOT NULL,
        team1_id INTEGER,
        team2_id INTEGER,
        score1 INTEGER DEFAULT 0,
        score2 INTEGER DEFAULT 0,
        winner_team_id INTEGER,
        status VARCHAR(20) DEFAULT 'pending',
        lobby_code VARCHAR(16),
        lobby_server VARCHAR(64),
        lobby_name VARCHAR(255),
        lobby_password VARCHAR(64),
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""",
]

SQLITE_SCHEMA = [
    stmt.replace("SERIAL PRIMARY KEY", "INTEGER PRIMARY KEY AUTOINCREMENT")
        .replace("BIGINT", "INTEGER")
        .replace("VARCHAR(255)", "TEXT").replace("VARCHAR(100)", "TEXT")
        .replace("VARCHAR(64)", "TEXT").replace("VARCHAR(30)", "TEXT")
        .replace("VARCHAR(20)", "TEXT").replace("BOOLEAN DEFAULT FALSE", "INTEGER DEFAULT 0")
    for stmt in PG_SCHEMA
]


def ensure_schema() -> None:
    """Создаёт таблицы турнира, если их ещё нет (idempotent)."""
    for stmt in (PG_SCHEMA if _is_pg() else SQLITE_SCHEMA):
        try:
            _write(stmt)
        except Exception as e:  # pragma: no cover - зависит от реальной БД
            logger.error("tournament: не удалось создать таблицу: %s", e)
            raise
    logger.info("tournament: схема турниров готова")


def _write(sql: str, params: tuple = ()) -> int:
    from database import Database
    return Database().execute_query(sql, params)


# -------------------------------------------------------------------
# Раскладка по рангам
# -------------------------------------------------------------------
def balance_by_rank(players: list[dict], team_size: int = TEAM_SIZE) -> list[list[dict]]:
    """Делит игроков на равные по рангу команды.

    MMR не смотрим: сортируем по rank_tier и раскладываем «змейкой», чтобы
    в одной команде не оказались Immortal и Herald.
    """
    ordered = sorted(players, key=lambda p: -int(_get(p, 'rank_tier', 2) or 10))
    if not ordered:
        return []
    teams = max(1, len(ordered) // max(1, team_size))

    buckets: list[list[dict]] = [[] for _ in range(teams)]
    for index, player in enumerate(ordered):
        cycle = index // teams
        position = index % teams
        bucket = position if cycle % 2 == 0 else teams - 1 - position
        buckets[bucket].append(player)
    return [b for b in buckets if b]


def build_teams(tid: int, names: list[str] | None = None) -> list[dict]:
    """Создаёт команды и первую сетку. Уже созданные команды не трогает."""
    q = _q()
    tournament = get_tournament(tid)
    if not tournament:
        return []
    team_size = int(tournament.get('team_size') or TEAM_SIZE)

    existing = _read(
        f"SELECT COUNT(*) AS c FROM tournament_teams WHERE tournament_id = {q}", (tid,))
    if existing and int(_get(existing[0], 'c', 0) or 0) > 0:
        return list_teams(tid)

    players = list_players(tid)
    if not players:
        return []

    buckets = balance_by_rank(players, team_size)
    names = names or []
    for index, bucket in enumerate(buckets):
        name = names[index] if index < len(names) else f"Команда {index + 1}"
        # Капитан — игрок с самым высоким рангом в команде.
        captain = max(bucket, key=lambda p: int(_get(p, 'rank_tier', 2) or 10))
        _write(
            f"INSERT INTO tournament_teams (tournament_id, name, seed, captain_id)"
            f" VALUES ({q}, {q}, {q}, {q})", (tid, name, index + 1, _get(captain, 'telegram_id', 0)))
        row = _read(
            f"SELECT id FROM tournament_teams WHERE tournament_id = {q}"
            f" ORDER BY id DESC LIMIT 1", (tid,))
        if not row:
            continue
        team_id = int(_get(row[0], 'id', 0) or 0)
        for player in bucket:
            _write(
                f"UPDATE tournament_players SET team_id = {q}, is_captain = {q}"
                f" WHERE tournament_id = {q} AND telegram_id = {q}",
                (team_id, 1 if _get(player, 'telegram_id', 0) == _get(captain, 'telegram_id', 0) else 0,
                 tid, _get(player, 'telegram_id', 0)))

    _create_bracket(tid, len(buckets))
    return list_teams(tid)


def list_teams(tid: int) -> list[dict]:
    rows = _read(
        f"SELECT * FROM tournament_teams WHERE tournament_id = {_q()} ORDER BY seed, id", (tid,))
    teams = []
    for row in rows:
        team = dict(row)
        members = _read(
            f"SELECT telegram_id, username, rank_tier, is_captain, steam_id"
            f" FROM tournament_players WHERE team_id = {_q()}", (team['id'],))
        team['members'] = members
        team['avg_tier'] = int(
            sum(int(_get(m, 'rank_tier', 2) or 10) for m in members) / len(members)
        ) if members else 0
        teams.append(team)
    return teams


def player_team(tid: int, telegram_id: int) -> dict | None:
    """Команда игрока в конкретном турнире."""
    rows = _read(
        f"SELECT t.* FROM tournament_teams t"
        f" JOIN tournament_players p ON p.team_id = t.id"
        f" WHERE p.tournament_id = {_q()} AND p.telegram_id = {_q()}",
        (tid, telegram_id))
    if not rows:
        return None
    team = dict(rows[0])
    team['members'] = _read(
        f"SELECT telegram_id, username, rank_tier, is_captain, steam_id"
        f" FROM tournament_players WHERE team_id = {_q()}", (team['id'],))
    return team


# -------------------------------------------------------------------
# Сетка: создание, чтение, лобби
# -------------------------------------------------------------------
def _create_bracket(tid: int, teams_count: int) -> None:
    """Рисует всю сетку целиком, как в клиенте Dota.

    Матчи всех раундов создаются сразу, команды подставляются только в первый
    раунд. Благодаря этому `_advance` всегда находит строку следующего матча,
    а игроки видят полную сетку с первого дня, а не только сыгранную часть.
    """
    q = _q()
    if teams_count < 2:
        return
    teams = sorted(list_teams(tid), key=lambda t: t['seed'])

    size = 1
    while size < len(teams):
        size *= 2
    first_round = rounds_count(size)

    for rn in range(first_round, 0, -1):
        # В первом раунде size/2 матчей, в каждом следующем вдвое меньше.
        matches_in_round = size >> (first_round - rn + 1)
        for position in range(matches_in_round):
            a = b = None
            if rn == first_round:
                a = teams[position]['id'] if position < len(teams) else None
                other = position + matches_in_round
                b = teams[other]['id'] if other < len(teams) else None
            _write(
                f"INSERT INTO tournament_matches"
                f" (tournament_id, round, position, team1_id, team2_id, status)"
                f" VALUES ({q}, {q}, {q}, {q}, {q}, {q})",
                (tid, rn, position, a, b, 'pending'))

    # Команда без соперника (неполная пара) автоматически проходит дальше.
    # Делаем это после создания всех раундов, чтобы следующий матч уже существовал.
    if teams_count < size:
        rows = _read(
            f"SELECT id, position, team1_id, team2_id FROM tournament_matches"
            f" WHERE tournament_id = {q} AND round = {q} AND status = {q}",
            (tid, first_round, 'pending'))
        for row in rows:
            only = _get(row, 'team1_id') or _get(row, 'team2_id')
            if only and not (_get(row, 'team1_id') and _get(row, 'team2_id')):
                _advance(tid, first_round, int(_get(row, 'position', 0) or 0), int(only))

    _write(f"UPDATE tournaments SET status = {q}, started_at = CURRENT_TIMESTAMP"
           f" WHERE id = {q}", ('active', tid))


def bracket(tid: int) -> list[dict]:
    """Вся сетка по раундам; первый раунд (самый крупный) идёт последним."""
    rounds: dict[int, list[dict]] = {}
    for row in _read(
            f"SELECT * FROM tournament_matches WHERE tournament_id = {_q()}"
            f" ORDER BY round DESC, position", (tid,)):
        rounds.setdefault(int(row['round']), []).append(dict(row))

    names = {int(t['id']): t['name'] for t in list_teams(tid)}
    out = []
    for rn in sorted(rounds, reverse=True):
        matches = []
        for m in rounds[rn]:
            item = dict(m)
            item['name1'] = names.get(item.get('team1_id'))
            item['name2'] = names.get(item.get('team2_id'))
            matches.append(item)
        out.append({'round': rn, 'matches': matches})
    return out


def label_round(rn: int) -> str:
    """Название раунда (раунд 1 — финал)."""
    if rn <= 1:
        return "Гранд-финал"
    if rn == 2:
        return "Полуфинал"
    return f"{1 << (rn - 1)}-финал"


# -------------------------------------------------------------------
# Счёт BO3 и продвижение победителя
# -------------------------------------------------------------------
WINS_NEEDED = 2  # BO3: играем до двух побед


def report_score(tid: int, telegram_id: int, score1: int, score2: int) -> dict:
    """Фиксирует счёт от перспективы команды игрока.

    Возвращает {'ok', 'reason', 'finished', 'winner_team_id', 'advanced'}.
    """
    q = _q()
    match = current_match(tid, telegram_id)
    if not match:
        return {'ok': False, 'reason': 'no_match'}

    team = player_team(tid, telegram_id)
    if not team or team['id'] not in (match.get('team1_id'), match.get('team2_id')):
        return {'ok': False, 'reason': 'not_yours'}

    # Счёт всегда от перспективы команды, которая его отправил.
    is_first = match['team1_id'] == team['id']
    s1 = int(score1) if is_first else int(score2)
    s2 = int(score2) if is_first else int(score1)

    if s1 >= WINS_NEEDED:
        winner = match['team1_id']
    elif s2 >= WINS_NEEDED:
        winner = match['team2_id']
    else:
        # Серия ещё не закрыта — просто накапливаем счёт.
        _write(
            f"UPDATE tournament_matches SET score1 = {q}, score2 = {q},"
            f" updated_at = CURRENT_TIMESTAMP WHERE id = {q}",
            (s1, s2, match['id']))
        return {'ok': True, 'reason': 'series', 'finished': False,
                'score': [s1, s2], 'match_id': match['id']}

    _write(
        f"UPDATE tournament_matches SET score1 = {q}, score2 = {q},"
        f" winner_team_id = {q}, status = {q}, updated_at = CURRENT_TIMESTAMP"
        f" WHERE id = {q}",
        (s1, s2, winner, 'completed', match['id']))

    advanced = _advance(tid, int(match['round']), int(match['position']), int(winner))
    return {'ok': True, 'reason': 'done', 'finished': True,
            'winner_team_id': winner, 'score': [s1, s2],
            'match_id': match['id'], 'advanced': advanced}


def _advance(tid: int, rn: int, position: int, winner: int) -> bool:
    """Победитель идёт в следующий раунд: раунд −1, позиция // 2."""
    q = _q()
    if rn <= 1:
        _write(f"UPDATE tournaments SET status = {q},"
               f" finished_at = CURRENT_TIMESTAMP WHERE id = {q}", ('finished', tid))
        return False

    target_round = rn - 1
    target_position = position // 2
    slot = 'team1_id' if position % 2 == 0 else 'team2_id'

    row = _read(
        f"SELECT id FROM tournament_matches WHERE tournament_id = {q}"
        f" AND round = {q} AND position = {q} LIMIT 1",
        (tid, target_round, target_position))
    if row:
        _write(f"UPDATE tournament_matches SET {slot} = {q} WHERE id = {q}",
               (winner, _get(row[0], 'id', 0)))
    return True


def champion(tid: int) -> dict | None:
    """Чемпион турнира, если финал закрыт."""
    q = _q()
    rows = _read(
        f"SELECT m.score1, m.score2, t.name AS team_name FROM tournament_matches m"
        f" JOIN tournament_teams t ON t.id = m.winner_team_id"
        f" WHERE m.tournament_id = {q} AND m.round = {q} AND m.status = {q}"
        f" LIMIT 1", (tid, 1, 'completed'))
    return dict(rows[0]) if rows else None


def current_match(tid: int, telegram_id: int) -> dict | None:
    """Ближайший незакрытый матч, в котором играет команда игрока."""
    team = player_team(tid, telegram_id)
    if not team:
        return None
    for group in bracket(tid):
        for m in group['matches']:
            if m.get('status') == 'completed':
                continue
            if team['id'] in (m.get('team1_id'), m.get('team2_id')):
                m['group_round'] = group['round']
                return m
    return None


def set_lobby(match_id: int, code: str, server: str,
              name: str, password: str) -> None:
    """Параметры лобби: название, сервер, пароль и код."""
    q = _q()
    _write(
        f"UPDATE tournament_matches SET lobby_code = {q}, lobby_server = {q},"
        f" lobby_name = {q}, lobby_password = {q}, status = {q},"
        f" updated_at = CURRENT_TIMESTAMP WHERE id = {q}",
        (code, server, name, password, 'lobby', match_id))
