"""
Dota 2 match list for the bot's web version.

Endpoint: /api/dota-matches

Returns the most recent real Dota 2 matches played by players linked to the bot,
in the same shape as the Dota 2 client match history: two teams, hero lineups,
kill score, duration, mode and start time.

Data flow:
  1. `public_player_matches` (filled by the bot on every /topmmr and MMR refresh)
     tells us WHICH matches bot players played. This is our index, so we never
     have to poll OpenDota for "who played what".
  2. OpenDota `/matches/{match_id}` fills in the details we do not store:
     duration, kill score, both lineups, game mode. Responses are cached in
     memory, so a page refresh costs nothing.

Everything degrades gracefully: if OpenDota is rate limited or a match detail
is missing, the match is still returned with whatever the bot already knows.
"""

from __future__ import annotations

import asyncio
import datetime
import logging
import os
import time

logger = logging.getLogger(__name__)

# How many matches the DB index scan fetches before we stop.
MAX_INDEX_ROWS = 500
# Cap on a single API response, to protect both OpenDota and the render budget.
DEFAULT_LIMIT = 20
MAX_LIMIT = 50
# Match details are immutable, so they can be cached for a long time.
MATCH_DETAIL_TTL = 3600  # 1 hour
# Full-list cache: keeps the page snappy when several visitors hit it at once.
LIST_CACHE_TTL = 60  # 1 minute

_detail_cache: dict[int, tuple[float, dict | None]] = {}
_list_cache: tuple[float, list] | None = None

OPEN_DOTA_MATCH_URL = "https://api.opendota.com/api/matches/{match_id}"
# Steam CDN portraits — the same art the Dota 2 client match list uses.
HERO_CDN_BASE = "https://cdn.cloudflare.steamstatic.com/apps/dota2/images/dota_react/heroes"

# Telegram Mini App. The very same /matches page is served both to a normal
# browser and to the Telegram web view; the SDK below makes Telegram-specific
# behaviour (viewport, theme) kick in automatically when present.
TELEGRAM_WEBAPP_JS = "https://telegram.org/js/telegram-web-app.js"
# Used when WEBHOOK_URL is not set (local runs, tests).
DEFAULT_PUBLIC_BASE = "https://fissure-bot.onrender.com"


# ============================================================
# DATABASE ACCESS
# ============================================================


def _read_all(sql: str, params: tuple = ()) -> list:
    """Run a read-only query in the calling thread and return all rows.

    Every caller runs inside `asyncio.to_thread`, and the executor may hand each
    call to a different worker thread. The SQLite pool in `database.py` is not
    thread-safe (a connection may only be used by the thread that created it),
    so for SQLite we open a dedicated connection for the duration of the query.
    Postgres connections are safe to share, so there we keep using the pool.
    """
    from database import (
        DATABASE_URL,
        get_connection,
        release_connection,
        urlparse,
    )

    scheme = (urlparse.urlparse(DATABASE_URL).scheme or "").lower()

    if scheme == "sqlite":
        import sqlite3

        url = DATABASE_URL or ""
        if url.startswith("sqlite:///"):
            path = url[10:]
        elif url.startswith("sqlite://"):
            path = url[9:]
        else:
            path = "fissure_bot.db"
        # A connection created here (and only used here) is thread-safe.
        conn = sqlite3.connect(path, timeout=10)
        try:
            cursor = conn.cursor()
            cursor.execute(sql, params)
            return list(cursor.fetchall() or [])
        finally:
            conn.close()

    if params:
        # Postgres uses %s placeholders, SQLite uses ?
        sql = sql.replace("?", "%s")
    conn = None
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(sql, params)
        return list(cursor.fetchall() or [])
    finally:
        if conn is not None:
            release_connection(conn)


# ============================================================
# DATABASE INDEX
# ============================================================


def _load_match_index(limit: int) -> list[dict]:
    """Read the newest bot-player matches from public_player_matches.

    The table has no NOT NULL on start_time, so rows without it are ordered
    last instead of poisoning the sort.
    """
    sql = f"""
        SELECT match_id,
               MAX(COALESCE(start_time, 0)) AS start_time,
               MAX(COALESCE(radiant_win, 0)) AS radiant_win,
               COUNT(*) AS player_rows
        FROM public_player_matches
        WHERE match_id IS NOT NULL
        GROUP BY match_id
        ORDER BY MAX(COALESCE(start_time, 0)) DESC, match_id DESC
        LIMIT {MAX_INDEX_ROWS}
    """
    try:
        rows = _read_all(sql)
    except Exception as e:
        logger.error("dota_matches: failed to read match index: %s", e)
        return []

    matches: list[dict] = []
    for row in rows:
        if not row:
            continue
        match_id = row[0]
        if match_id is None:
            continue
        matches.append(
            {
                "match_id": int(match_id),
                "start_time": int(row[1] or 0),
                "radiant_win": bool(row[2]),
                "bot_players": int(row[3] or 0),
            }
        )

    matches.sort(key=lambda m: (m["start_time"], m["match_id"]), reverse=True)
    return matches[:limit]


# Fallback index. public_player_matches is only filled by /topmmr and the MMR
# refresh, so right after linking a Steam account it can be empty; asking
# OpenDota for the players' latest games keeps the list alive from the start.
PLAYER_FALLBACK_COUNT = 8
PLAYER_FALLBACK_MATCHES = 3


def _linked_steam_ids(limit: int) -> list[int]:
    """Steam IDs of players linked to the bot, most active first.

    The ranking columns (`week_games`, `mmr`) are optional: fresh/partial
    databases may not have them, and an ORDER BY over a missing column would
    silently produce an empty list. Fall back to a plain scan in that case.
    """
    queries = (
        """
        SELECT steam_id
        FROM users
        WHERE steam_id IS NOT NULL
        ORDER BY COALESCE(week_games, 0) DESC, COALESCE(mmr, 0) DESC
        LIMIT ?
        """,
        "SELECT steam_id FROM users WHERE steam_id IS NOT NULL LIMIT ?",
    )
    for index, sql in enumerate(queries):
        try:
            rows = _read_all(sql, (limit,))
        except Exception as e:
            logger.error(
                "dota_matches: failed to list linked players (query %d): %s", index + 1, e
            )
            continue
        return [int(r[0]) for r in rows if r and r[0] is not None]
    return []


async def _index_from_linked_players(limit: int) -> list[dict]:
    """Build the match index straight from OpenDota when the DB index is empty."""
    from dota_mmr import get_recent_matches_async

    steam_ids = await asyncio.to_thread(_linked_steam_ids, PLAYER_FALLBACK_COUNT)
    if not steam_ids:
        return []

    results = await asyncio.gather(
        *(get_recent_matches_async(sid, PLAYER_FALLBACK_MATCHES) for sid in steam_ids),
        return_exceptions=True,
    )

    index: dict[int, dict] = {}
    for matches in results:
        if isinstance(matches, BaseException) or not matches:
            continue
        for match in matches:
            match_id = match.get("match_id")
            if match_id is None:
                continue
            entry = index.get(match_id)
            if entry is None:
                index[match_id] = {
                    "match_id": int(match_id),
                    "start_time": int(match.get("start_time") or 0),
                    "radiant_win": bool(match.get("radiant_win")),
                    "bot_players": 1,
                }
            else:
                # Several linked players in one match.
                entry["bot_players"] += 1
                entry["start_time"] = max(
                    entry["start_time"], int(match.get("start_time") or 0)
                )

    return sorted(
        index.values(), key=lambda m: (m["start_time"], m["match_id"]), reverse=True
    )[:limit]


# ============================================================
# PLAYER GAME LIST
# ============================================================
# Формат как в профиле Dota 2: строка = одна игра одного игрока
# (герой, ник, Победа/Поражение, дата, время, длительность).

PLAYER_GAMES_PLAYERS = 12    # сколько игроков бота опрашиваем
PLAYER_GAMES_PER_PLAYER = 8  # сколько последних игр каждого
# Сколько страница ждёт OpenDota, прежде чем отдать пустую историю.
# Раньше ожидание не ограничивалось (до 25с на игрока) и Mini App
# выглядел зависшим на белом экране.
GAMES_NET_TIMEOUT = 4


def _decorate_games(games: list[dict], heroes: dict) -> list[dict]:
    """Дописывает имя и иконку героя к строкам, прочитанным из БД."""
    out = []
    for g in games:
        hero_id = g.get("hero_id")
        g = dict(g)
        g["hero_name"] = _hero_name(hero_id, heroes) if hero_id is not None else "—"
        g["hero_icon"] = _hero_icon(hero_id, heroes) if hero_id is not None else ""
        out.append(g)
    return out


async def get_player_games(limit: int = DEFAULT_LIMIT) -> list[dict]:
    """Latest games of the players linked to the bot, newest first.

    Сначала берём из public_player_matches — туда кладёт матчи джоб
    обновления MMR, вместе с KDA и рангом. OpenDota остаётся запасным
    путём: если таблица пуста (первый запуск после деплоя или в ней
    ещё нет KDA), идём в сеть как раньше.
    """
    limit = max(1, min(int(limit or DEFAULT_LIMIT), MAX_LIMIT))
    heroes = await asyncio.to_thread(_hero_catalog)

    def _read():
        from database import get_recent_player_matches
        return get_recent_player_matches(limit=limit * 3)

    games = await asyncio.to_thread(_read)
    # Строки без KDA — наследие старой схемы: берём их из сети.
    games = [g for g in games if g.get("kills") or g.get("duration")]
    if games:
        return _decorate_games(games, heroes)

    # БД пуста (или ещё без KDA) — идём в OpenDota, но только коротко.
    # Раньше здесь страница ждала до 25 секунд на игрока, и Mini App
    # выглядел зависшим. Лучше пустая история, чем белый экран.
    from dota_mmr import get_recent_matches_async

    try:
        games = await asyncio.wait_for(_games_from_opendota(heroes, limit),
                                        timeout=GAMES_NET_TIMEOUT)
    except asyncio.TimeoutError:
        logger.warning(
            "История: OpenDota не ответил за %sс, показываем пусто",
            GAMES_NET_TIMEOUT)
        _warm_games_in_background()
        return []
    return games


def _warm_games_in_background():
    """Прогревает кеш матчей, не блокируя открытие страницы.

    Идея пользователя: приложение открывается сразу, а данные
    подтягиваются следом. Следующий заход уже отдаст историю.
    """
    async def _warm():
        try:
            await _games_from_opendota({}, DEFAULT_LIMIT)
        except Exception as e:
            logger.debug(f"Фоновое обновление истории не удалось: {e}")

    try:
        asyncio.get_running_loop().create_task(_warm())
    except RuntimeError:
        pass


async def _games_from_opendota(heroes: dict, limit: int) -> list[dict]:
    """Старый путь: матчи из OpenDota для привязанных игроков."""
    from dota_mmr import get_recent_matches_async

    steam_ids = await asyncio.to_thread(_linked_steam_ids, PLAYER_GAMES_PLAYERS)
    if not steam_ids:
        return []
    bot_index = await asyncio.to_thread(_bot_steam_index)

    results = await asyncio.gather(
        *(get_recent_matches_async(sid, PLAYER_GAMES_PER_PLAYER) for sid in steam_ids),
        return_exceptions=True,
    )

    games: list[dict] = []
    seen: set[tuple[int, int]] = set()
    for steam_id, matches in zip(steam_ids, results):
        if isinstance(matches, BaseException) or not matches:
            continue
        linked = bot_index.get(steam_id) or {}
        for match in matches:
            match_id = match.get("match_id")
            if match_id is None:
                continue
            key = (steam_id, int(match_id))
            if key in seen:  # /matches иногда отдаёт дубли игрока
                continue
            seen.add(key)

            hero_id = match.get("hero_id")
            slot = match.get("player_slot")
            is_radiant = slot < 128 if slot is not None else True
            radiant_win = bool(match.get("radiant_win"))

            games.append(
                {
                    "match_id": int(match_id),
                    "start_time": int(match.get("start_time") or 0),
                    "duration": int(match.get("duration") or 0),
                    "mode": _mode_name(match.get("game_mode")),
                    # Победа игрока, а не команды: слот < 128 = Свет.
                    "win": (is_radiant and radiant_win) or (not is_radiant and not radiant_win),
                    "hero_id": hero_id,
                    "hero_name": _hero_name(hero_id, heroes) if hero_id is not None else "—",
                    "hero_icon": _hero_icon(hero_id, heroes) if hero_id is not None else "",
                    "personaname": match.get("personaname") or linked.get("username") or "Игрок",
                    "kills": int(match.get("kills") or 0),
                    "deaths": int(match.get("deaths") or 0),
                    "assists": int(match.get("assists") or 0),
                    "steam_id": steam_id,
                    "telegram_id": linked.get("telegram_id"),
                    "bot_username": linked.get("username"),
                    "avatar": linked.get("avatar"),
                    "rank_tier": linked.get("rank_tier"),
                }
            )

    games.sort(key=lambda g: (g["start_time"], g["match_id"]), reverse=True)
    return games[:limit]


# ============================================================
# OPENDOTA ENRICHMENT
# ============================================================


def _get_cached_detail(match_id: int) -> dict | None:
    cached = _detail_cache.get(match_id)
    if cached and (time.time() - cached[0]) < MATCH_DETAIL_TTL:
        return cached[1]
    return None


def _set_cached_detail(match_id: int, detail: dict | None) -> None:
    # Cap the cache so a long-running process cannot grow it forever.
    if len(_detail_cache) > 500:
        _detail_cache.clear()
    _detail_cache[match_id] = (time.time(), detail)


async def _fetch_match_detail(match_id: int) -> dict | None:
    cached = _get_cached_detail(match_id)
    if cached is not None:
        return cached

    detail = None
    try:
        from dota_mmr import _api_get_async

        data = await _api_get_async(OPEN_DOTA_MATCH_URL.format(match_id=match_id))
        if data and isinstance(data, dict):
            detail = data
    except Exception as e:
        logger.warning("dota_matches: OpenDota detail failed for %s: %s", match_id, e)

    _set_cached_detail(match_id, detail)
    return detail


def _hero_catalog() -> dict:
    try:
        from dota_mmr import get_local_heroes_data

        return get_local_heroes_data() or {}
    except Exception as e:
        logger.debug("dota_matches: local hero catalog unavailable: %s", e)
        return {}


def _hero_name(hero_id: int, heroes: dict) -> str:
    hero = heroes.get(hero_id) or {}
    return hero.get("name") or f"Герой #{hero_id}"


def _hero_icon(hero_id: int, heroes: dict) -> str:
    """Public hero portrait URL, Dota 2 client style.

    The local catalog stores filesystem paths, which a browser cannot use
    (and which would leak server paths), so we always hand out the Steam CDN
    URL that the Dota client itself uses.
    """
    hero = heroes.get(hero_id) or {}
    short_name = hero.get("short_name")
    if not short_name:
        return ""
    try:
        from hero_names import get_cdn_hero_name

        cdn_name = get_cdn_hero_name(short_name)
    except Exception:
        cdn_name = short_name
    return f"{HERO_CDN_BASE}/{cdn_name}.png"


def _mode_name(mode: int | None) -> str:
    return {
        0: "All Pick",
        1: "Captains Mode",
        2: "Random Draft",
        3: "Single Draft",
        4: "All Random",
        5: "Captains Draft",
        6: "Random Draft",
        7: "All Random Deathmatch",
        8: "1v1 Mid",
        9: "All Draft",
        10: "Captains Draft",
        11: "All Random",
        12: "Introductory",
        13: "Diretide",
        14: "Reverse Captains Draft",
        15: "Greeviling",
    }.get(mode, "Ranked")


def _team_lineup(match: dict, radiant: bool, heroes: dict) -> list[dict]:
    players = match.get("players") or []
    team: list[dict] = []
    for player in players:
        slot = player.get("player_slot")
        if slot is None:
            continue
        is_radiant = slot < 128
        if is_radiant != radiant:
            continue
        hero_id = player.get("hero_id")
        team.append(
            {
                "hero_id": hero_id,
                "hero_name": _hero_name(hero_id, heroes) if hero_id is not None else "—",
                "hero_icon": _hero_icon(hero_id, heroes) if hero_id is not None else "",
                "personaname": player.get("personaname") or "Аноним",
                "kills": player.get("kills") or 0,
                "deaths": player.get("deaths") or 0,
                "assists": player.get("assists") or 0,
                # Steam account id, used to mark bot players in the UI.
                "account_id": player.get("account_id"),
            }
        )
    return team


def _kill_score(value) -> int | None:
    """Kill score from OpenDota's match detail.

    `/matches/{id}` returns `radiant_score`/`dire_score` as plain integers, but
    older responses (and the public matches feed) wrap them as {"kills": n},
    so accept both shapes.
    """
    if value is None:
        return None
    if isinstance(value, dict):
        value = value.get("kills")
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _link_bot_players(match: dict, bot_steam_ids: dict) -> None:
    """Mark lineups that belong to a player linked to the bot."""
    from dota_mmr import account_id_to_steam64

    for side in ("radiant", "dire"):
        for player in match.get(side) or []:
            account_id = player.get("account_id")
            if not account_id:
                continue
            steam_id = account_id_to_steam64(account_id)
            linked = bot_steam_ids.get(steam_id)
            if linked:
                player["bot_username"] = linked.get("username") or "Игрок"
                player["telegram_id"] = linked.get("telegram_id")


def _bot_steam_index() -> dict:
    """steam_id -> {telegram_id, username, avatar} for every linked player."""
    index: dict = {}
    # Сначала пробуем запрос с аватаром. Если колонки вдруг нет (старая база),
    # откатываемся на запрос без неё — иначе страница осталась бы совсем пустой,
    # потому что индекс игроков строится целиком из этого SELECT.
    queries = (
        "SELECT steam_id, telegram_id, username, steam_nickname, avatar, rank_tier,"
        " week_games, week_wins"
        " FROM users WHERE steam_id IS NOT NULL LIMIT 5000",
        "SELECT steam_id, telegram_id, username, steam_nickname, avatar, rank_tier"
        " FROM users WHERE steam_id IS NOT NULL LIMIT 5000",
        "SELECT steam_id, telegram_id, username, steam_nickname, avatar"
        " FROM users WHERE steam_id IS NOT NULL LIMIT 5000",
        "SELECT steam_id, telegram_id, username, steam_nickname"
        " FROM users WHERE steam_id IS NOT NULL LIMIT 5000",
    )
    for query in queries:
        try:
            rows = _read_all(query)
        except Exception as e:
            logger.error("dota_matches: failed to build bot steam index: %s", e)
            continue

        for row in rows:
            if not row or row[0] is None:
                continue
            # Раскладка колонок позиционная и одинакова для обоих вариантов;
            # в запасном запросе avatar просто отсутствует.
            index[int(row[0])] = {
                "telegram_id": row[1],
                "username": row[2] or row[3] or "Игрок",
                # Аватар уже лежит в БД (заполняется при обновлении MMR),
                # поэтому карточка не требует ни одного дополнительного запроса.
                "avatar": row[4] if len(row) > 4 else None,
                # Ранг нужен, чтобы показать его в строке игры.
                "rank_tier": row[5] if len(row) > 5 else None,
            }
        break
    return index


# ============================================================
# PUBLIC API
# ============================================================


async def get_dota_matches(limit: int = DEFAULT_LIMIT, force: bool = False) -> list[dict]:
    """Return the newest Dota 2 matches played by bot players.

    Falls back to whatever the DB index knows if OpenDota is unavailable.
    """
    global _list_cache

    limit = max(1, min(int(limit or DEFAULT_LIMIT), MAX_LIMIT))

    if not force and _list_cache and (time.time() - _list_cache[0]) < LIST_CACHE_TTL:
        return _list_cache[1][:limit]

    index = await asyncio.to_thread(_load_match_index, limit)
    if not index:
        # Таблица заполняется только /topmmr, поэтому при пустой БД спрашиваем
        # OpenDota напрямую по игрокам, привязавшим аккаунт.
        index = await _index_from_linked_players(limit)
    if not index:
        return []

    heroes = await asyncio.to_thread(_hero_catalog)
    bot_steam_ids = await asyncio.to_thread(_bot_steam_index)

    details = await asyncio.gather(
        *(_fetch_match_detail(m["match_id"]) for m in index),
        return_exceptions=True,
    )

    result: list[dict] = []
    for base, detail in zip(index, details):
        if isinstance(detail, BaseException) or not detail:
            result.append(
                {
                    "match_id": base["match_id"],
                    "start_time": base["start_time"],
                    "duration": 0,
                    "radiant_win": base["radiant_win"],
                    "mode": "Ranked",
                    "radiant_score": None,
                    "dire_score": None,
                    "radiant": [],
                    "dire": [],
                    "bot_players": base["bot_players"],
                    "partial": True,
                }
            )
            continue

        match = {
            "match_id": base["match_id"],
            "start_time": detail.get("start_time") or base["start_time"],
            "duration": detail.get("duration") or 0,
            "radiant_win": bool(detail.get("radiant_win", base["radiant_win"])),
            "mode": _mode_name(detail.get("game_mode")),
            "radiant_score": _kill_score(detail.get("radiant_score")),
            "dire_score": _kill_score(detail.get("dire_score")),
            "radiant": _team_lineup(detail, True, heroes),
            "dire": _team_lineup(detail, False, heroes),
            "bot_players": base["bot_players"],
            "partial": False,
        }
        _link_bot_players(match, bot_steam_ids)
        result.append(match)

    result.sort(key=lambda m: (m.get("start_time") or 0), reverse=True)
    _list_cache = (time.time(), result)
    return result[:limit]


# ============================================================
# HTML RENDERING (Dota 2 style match list)
# ============================================================

_HTML_ESCAPES = {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}


def _esc(value) -> str:
    return str("" if value is None else value).translate(str.maketrans(_HTML_ESCAPES))


def _fmt_duration(seconds: int | None) -> str:
    seconds = int(seconds or 0)
    if seconds <= 0:
        return "—"
    return f"{seconds // 60}:{seconds % 60:02d}"


def _fmt_ago(start_time: int | None) -> str:
    if not start_time:
        return "—"
    import datetime as _dt

    started = _dt.datetime.fromtimestamp(start_time, _dt.timezone.utc)
    delta = _dt.datetime.now(_dt.timezone.utc) - started
    total = int(delta.total_seconds())
    if total < 0:
        return started.strftime("%d.%m.%Y %H:%M")
    if total < 3600:
        return f"{total // 60} мин назад"
    if total < 86400:
        return f"{total // 3600} ч назад"
    return started.strftime("%d.%m.%Y %H:%M")


def _render_players(players: list[dict], winner: bool) -> str:
    if not players:
        return '<div class="team-row team-empty">состав недоступен</div>'

    rows = []
    for player in players:
        classes = "team-row" + (" winner" if winner else "")
        icon = ""
        if player.get("hero_icon"):
            icon = (
                f'<img class="hero-icon" src="{_esc(player["hero_icon"])}" '
                f'alt="{_esc(player["hero_name"])}" loading="lazy">'
            )
        # Bot players get a TG link, everyone else is shown as plain text.
        if player.get("telegram_id"):
            who = (
                f'<a class="pname bot" href="tg://user?id={int(player["telegram_id"])}">'
                f'{_esc(player.get("bot_username") or player["personaname"])}</a>'
            )
        else:
            who = f'<span class="pname">{_esc(player["personaname"])}</span>'

        rows.append(
            f'<div class="{classes}">'
            f"{icon}"
            f'<span class="pinfo">{who}'
            f'<span class="pname-sub">{_esc(player["hero_name"])}</span></span>'
            f'<span class="kda">{int(player.get("kills") or 0)}/'
            f'{int(player.get("deaths") or 0)}/'
            f'{int(player.get("assists") or 0)}</span>'
            f"</div>"
        )
    return "".join(rows)


def render_match(match: dict) -> str:
    """One match card, laid out like a row in the Dota 2 match history."""
    radiant_win = bool(match.get("radiant_win"))
    radiant_score = match.get("radiant_score")
    dire_score = match.get("dire_score")
    has_score = radiant_score is not None and dire_score is not None
    score = f"{radiant_score} : {dire_score}" if has_score else "—"

    return (
        f'<div class="match-card{" partial" if match.get("partial") else ""}">'
        f'<div class="match-side radiant{" winner" if radiant_win else ""}">'
        f'<div class="side-head"><span class="side-name">Свет</span>'
        f'<span class="side-kills">{radiant_score if radiant_score is not None else "—"}</span></div>'
        f'{_render_players(match.get("radiant") or [], radiant_win)}'
        f"</div>"
        f'<div class="match-mid">'
        f'<div class="result">{"Победа Света" if radiant_win else "Победа Тьмы"}</div>'
        f'<div class="score">{score}</div>'
        f'<div class="meta">{_esc(match.get("mode") or "Ranked")} · '
        f'{_fmt_duration(match.get("duration"))}</div>'
        f'<div class="ago">{_fmt_ago(match.get("start_time"))}</div>'
        f'<a class="dotapedia" href="https://www.opendota.com/matches/{int(match["match_id"])}" '
        f'target="_blank" rel="noopener">Матч #{int(match["match_id"])}</a>'
        f"</div>"
        f'<div class="match-side dire{" winner" if not radiant_win else ""}">'
        f'<div class="side-head"><span class="side-kills">{dire_score if dire_score is not None else "—"}</span>'
        f'<span class="side-name">Тьма</span></div>'
        f'{_render_players(match.get("dire") or [], not radiant_win)}'
        f"</div>"
        f"</div>"
    )


DISPLAY_TZ = "Europe/Moscow"
_MOSCOW_TZ = datetime.timezone(datetime.timedelta(hours=3))


def _local_stamp(timestamp: int | None) -> datetime.datetime | None:
    """Game start time in the timezone the community actually reads."""
    if not timestamp:
        return None
    try:
        moment = datetime.datetime.fromtimestamp(int(timestamp), datetime.timezone.utc)
    except (OverflowError, OSError, ValueError, TypeError):
        return None
    try:
        from zoneinfo import ZoneInfo

        return moment.astimezone(ZoneInfo(DISPLAY_TZ))
    except Exception:
        # Windows images may ship without the tzdata package.
        return moment.astimezone(_MOSCOW_TZ)


def render_game(game: dict) -> str:
    """Карточка игры в оформлении «Боевого кубока».

    Аватар игрока и иконка героя, ник, KDA вида «15 / 1 / 8», результат и
    дата с длительностью. Ряд предметов переносится на вторую строку сам,
    когда данные их дадут.
    """
    win = bool(game.get("win"))
    cls = "win" if win else "loss"
    # Буква вместо слова: «Победа»/«Поражение» съедали половину строки,
    # а W/L читаются с одного взгляда. Полное слово осталось в подсказке.
    res_word = "Победа" if win else "Поражение"
    res_letter = "W" if win else "L"
    shown_as = game.get("bot_username") or game.get("personaname") or "Игрок"

    avatar_url = (game.get("avatar") or "").strip()
    if avatar_url:
        face = (
            f'<img class="g-face" src="{_esc(avatar_url)}" '
            f'alt="{_esc(shown_as)}" loading="lazy">'
        )
    else:
        face = f'<span class="g-face g-hero">{_esc(shown_as[:1].upper())}</span>'

    if game.get("hero_icon"):
        hero = (
            f'<img class="g-hero" src="{_esc(game["hero_icon"])}" '
            f'alt="{_esc(game["hero_name"])}" loading="lazy">'
        )
    else:
        hero = '<span class="g-hero">—</span>'

    # Ранг игрока — из профиля, чтобы в играх был виден уровень, как в топе.
    # Иконка говорит о ранге сама, поэтому название под ником не дублируем.
    tier = game.get("rank_tier")
    if tier:
        rank = (f'<img class="g-rank-img" src="{_esc(rank_image(tier))}" '
                f'alt="" loading="lazy">')
    else:
        rank = '<span class="g-rank-img g-rank-blank">—</span>'

    name_html = _esc(shown_as)
    if game.get("telegram_id"):
        name_html = (
            f'<span class="g-nick" data-tg="{int(game["telegram_id"])}">'
            f'{name_html}</span>'
        )
    else:
        name_html = f'<span class="g-nick">{name_html}</span>'

    subtitle = _esc(game.get("hero_name") or "—")
    if (
        game.get("personaname")
        and game["personaname"] != shown_as
        and game["personaname"] != game.get("hero_name")
    ):
        subtitle += f' · {_esc(game["personaname"])}'

    kills = int(game.get("kills") or 0)
    deaths = int(game.get("deaths") or 0)
    assists = int(game.get("assists") or 0)

    items = ""
    for key in ("items", "item_icons"):
        raw = game.get(key)
        if raw:
            icons = "".join(
                f'<img class="g-hero" src="{_esc(i)}" alt="" loading="lazy">'
                for i in raw[:6] if i
            )
            if icons:
                items = f'<div class="g-line">{icons}</div>'
            break

    stamp = _local_stamp(int(game.get("start_time") or 0))
    date_txt = stamp.strftime("%d.%m") if stamp else "—"
    time_txt = stamp.strftime("%H:%M") if stamp else "—"

    match_id = int(game.get("match_id") or 0)
    account_id = int(game.get("account_id") or 0)

    # «Пати» больше не открывает «Поделиться»: приглашение уходило в диалог
    # контакта мимо чата, в котором играют. Кнопка шлёт HTTP-запрос с
    # initData, и бот зовёт того, кому эта игра принадлежит, — общий
    # подбор запускается только когда игрока определить нечем.
    # Ссылка на «Поделиться» осталась для обычного браузера, где
    # отправлять сигнал некуда.
    party_share = ("https://t.me/share/url?url="
                   + match_url(match_id)
                   + "&text=" + _tg_share_text(game, match_id))
    party_tg = int(game.get("telegram_id") or 0)
    # Dotabuff ведёт на профиль игрока этой игры, а не на матч: по кнопке
    # ищут историю конкретного человека. Надпись латиницей — как в самом
    # Dotabuff, чтобы читалось по-английски.
    db_url = (f"https://www.dotabuff.com/players/{account_id}"
              if account_id else
              (f"https://www.dotabuff.com/matches/{match_id}"
               if match_id else "https://www.dotabuff.com"))

    # Строка кликается и открывает панель, поэтому это div, а не ссылка:
    # ссылка раньше уводила на OpenDota и открывала новую вкладку.
    return (
        f'<div class="g-card {cls}" data-party="1" '
        f'data-party-share="{_esc(party_share)}" '
        f'data-party-tg="{party_tg}" '
        f'data-dota="{_esc(db_url)}" tabindex="0" role="button">'
        f'<div class="g-line">'
        f"{rank}{face}{hero}"
        f'<span class="g-who">{name_html}'
        f'<span class="g-heron">{_esc(subtitle)}</span></span>'
        f'<span class="g-kda"><b>{kills}</b> / {deaths} / {assists}</span>'
        f'<span class="g-res" title="{res_word}" aria-label="{res_word}">'
        f"{res_letter}</span>"
        f'<span class="g-when">{date_txt} · {time_txt} · '
        f'{_fmt_duration(game.get("duration"))}</span>'
        f'<span class="g-more" aria-hidden="true">'
        f'<svg viewBox="0 0 16 16" width="12" height="12">'
        f'<path d="M6 3.5 10.5 8 6 12.5" fill="none" stroke="currentColor" '
        f'stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>'
        f"</svg></span>"
        f"</div>"
        # Кнопки только со словами: иконки из линейных SVG на 13px читались
        # как каракули и ничего не добавляли — «Пати» и «Dotabuff» говорят сами.
        f'<div class="g-acts">'
        f'<span class="g-act" data-act="party">Пати</span>'
        f'<span class="g-act dotabuff" data-act="dota">Dotabuff</span>'
        f"</div>"
        f"{items}</div>"
    )


def _tg_share_text(game: dict, match_id: int) -> str:
    """Текст приглашения в пати, который уходит через «Поделиться»."""
    who = game.get("bot_username") or game.get("personaname") or "игрок"
    hero = game.get("hero_name") or "герой"
    return f"Позову тебя в пати на Dota 2! Погнали играть 💪 ({who}, {hero})"


def match_url(match_id: int) -> str:
    """Ссылка на матч на Dotabuff."""
    return f"https://www.dotabuff.com/matches/{match_id}"


# Ранги раздаёт сам бот (aiohttp static /images/ranks/…): внешний хост
# seredin999.onrender.com отдавал 503, и иконки пропадали из страниц.
RANKS_BASE = "/images/ranks"

# Ранги Dota 2 по-русски: чем больше номер, тем выше ранг.
RANK_TIERS = [
    (10, "Герой"), (20, "Страж"), (30, "Рыцарь"),
    (40, "Героиня"), (50, "Легенда"), (60, "Титан"),
    (70, "Божество"), (80, "Бессмертный"),
]


def rank_image(tier) -> str:
    """Иконка ранга — та же, что на странице топа MMR.

    Страницу и картинки раздаёт сам бот, поэтому путь относительный.
    """
    try:
        rt = int(tier or 0)
    except (TypeError, ValueError):
        rt = 0
    if rt <= 0:
        return f"{RANKS_BASE}/rank_1_1.webp"
    tier_no, star = rt // 10, rt % 10
    if tier_no == 8:
        # Бессмертный (8-й тир) — единственная иконка rank_8_5, как в
        # карточке профиля: rank_8_1..8_4 в assets нет, и ссылка на них
        # при локальной раздаче давала бы 404.
        star = 5
    elif star == 0:
        star = 1          # без звёзд показываем с одной
    if 1 <= tier_no <= 8 and 1 <= star <= 5:
        return f"{RANKS_BASE}/rank_{tier_no}_{star}.webp"
    return f"{RANKS_BASE}/rank_1_1.webp"


def mmr_sort_key(player: dict):
    """Порядок ровно как в get_dota_week_top: сначала статистика, потом ранг.

    Ключи повторяют ORDER BY страницы топа (database.py): игроки без игр за
    неделю всегда внизу и между собой упорядочены по рангу, а у играющих
    главная метрика — разница побед, затем игры, MMR и ранг. Раньше здесь
    ранг стоял первым, и вкладка «Топ рангов» показывала другой порядок,
    чем /topmmr в боте.
    """
    tier = int(player.get("rank_tier") or 0)
    games = int(player.get("week_games") or 0)
    if games == 0:
        return (1, -tier)
    wins = int(player.get("week_wins") or 0)
    net = wins - (games - wins)
    mmr = int(player.get("mmr") or 0)
    return (0, -net, -games, -mmr, -tier)


def _wr_color(wr: int) -> str:
    """Цвет процента — от зелёного к красному, как на сайте."""
    if wr >= 60:
        return "#7fd18a"
    if wr >= 50:
        return "#c9d16b"
    if wr >= 40:
        return "#e8b45c"
    return "#ef6a5a"


def mmr_sort_keys(player: dict) -> dict:
    """Значения для клиентской сортировки (те же, что на странице топа)."""
    games = int(player.get("week_games") or 0)
    wins = int(player.get("week_wins") or 0)
    wr = round(wins / games * 100) if games else 0
    return {
        "rank_tier": int(player.get("rank_tier") or 0),
        "stats": wins - (games - wins),
        "name": (player.get("steam_nickname")
                 or player.get("username") or "").lower(),
        "games": games,
    }


# Метки не-ролловых событий. Без них на вкладке «Роллы» награда Рошана,
# удар Зевса и урон Техиса читались как обычные приросты (+8, +0, -55) —
# отсюда ощущение бреда. Старые записи без event_type считаются роллом.
_ROLL_EVENT_BADGES = {
    "roshan": "⚔ Рошан",
    "zeus": "⚡ Зевс",
    "techies": "💣 Техис",
}


def render_roll(roll: dict) -> str:
    """Строка истории роллов: кто крутил, на сколько и сколько стало."""
    try:
        ts = float(roll.get("ts") or 0)
    except (TypeError, ValueError):
        ts = 0.0

    when = _local_stamp(ts)
    time_txt = when.strftime("%d.%m %H:%M") if when else "—"

    who = (roll.get("username") or "Игрок")[:25]
    growth = float(roll.get("growth") or 0)
    fissure = float(roll.get("fissure") or 0)
    cascade = int(roll.get("cascade") or 1)

    # Аватар приходит из bot_utils без картинки, поэтому берём его по
    # никнейму из тех же данных, что уже отдаёт страница роллов.
    avatar = (roll.get("avatar") or "").strip()
    if avatar:
        face = (f'<img class="g-face" src="{_esc(avatar)}" alt="" '
                f'loading="lazy">')
    else:
        face = f'<span class="g-face g-hero">{_esc(who[:1].upper())}</span>'

    sign = "+" if growth >= 0 else ""
    # Минусовой ролл — это откат, он должен читаться как тревожный.
    gain_cls = "g-gain" if growth >= 0 else "g-gain neg"
    # Каскад — цепочка фисса, поэтому выделяем её отдельной меткой.
    chain = (f'<span class="g-rc-x">x{cascade}</span>' if cascade > 1 else "")
    # Тип события: не-ролловые события (Рошан/Зевс/Техис) помечаем, иначе
    # их прирост неотличим от обычного ролла.
    ev_badge = _ROLL_EVENT_BADGES.get(roll.get("event_type") or "roll", "")
    ev = f'<span class="g-rc-ev">{ev_badge}</span>' if ev_badge else ""

    return (
        f'<div class="g-card g-roll" data-name="{_esc(who.lower())}" '
        # Время целым: %g печатал бы 1.7e+09, а по нему ещё и сортировать.
        f'data-ts="{int(ts)}" '
        f'data-growth="{growth:g}" data-fissure="{fissure:g}">'
        f'<div class="g-line">'
        f'{face}'
        f'<span class="g-who">'
        f'<span class="g-nick">{_esc(who)}</span>'
        f'<span class="g-heron">{time_txt}</span></span>'
        f'<span class="{gain_cls}">{sign}{_fmt_num(growth)}</span>'
        f"{ev}"
        f"{chain}"
        f'<span class="g-fissure">{_fmt_num(fissure)}</span>'
        f"</div></div>"
    )


def _fmt_num(value: float) -> str:
    """Число без хвоста .0 — в разрядах он только шумит."""
    if abs(value - round(value)) < 0.05:
        return f"{int(round(value)):,}".replace(",", " ")
    return f"{value:,.1f}".replace(",", " ")


def render_mmr_row(player: dict, place: int, sort_keys: dict | None = None,
                   games_href: str = "") -> str:
    """Строка топа MMR: тот же набор полей, что на странице топа."""
    nick = (player.get("steam_nickname") or player.get("username") or "Аноним")

    games = int(player.get("week_games") or 0)
    wins = int(player.get("week_wins") or 0)

    if games > 0:
        wr = round(wins / games * 100)
        losses = games - wins
        color = _wr_color(wr)
        stats = (
            f'<span class="g-wr-num" style="color:{color}">{wr}%</span>'
            f'<span class="g-wr-track">'
            f'<span class="g-wr-fill" style="width:{wr}%;background:{color}"></span>'
            f"</span>"
            f'<span class="g-wr-wl">{wins}W/{losses}L</span>'
        )
    else:
        stats = '<span class="g-wr-none">—</span>'

    top = place <= 3
    avatar = (player.get("avatar") or "").strip()
    face = (f'<img class="g-face" src="{_esc(avatar)}" alt="" loading="lazy">'
            if avatar else '<span class="g-face g-hero">—</span>')

    keys = sort_keys or mmr_sort_keys(player)
    attrs = " ".join(f'data-{k}="{v}"' for k, v in keys.items())

    # Под героем — кнопка на историю игр этого игрока: из топа за ним
    # и смотрели бы, но раньше приходилось сначала открывать фильтр.
    history = ""
    if games_href:
        history = (f'<a class="g-igames" href="{games_href}">История игр</a>')

    return (
        f'<div class="g-card g-mmr{" top3" if top else ""}" {attrs}>'
        f'<div class="g-line">'
        f'<span class="g-rank{" top" if top else ""}">{place}</span>'
        f'<img class="g-rank-img" '
        f'src="{_esc(rank_image(player.get("rank_tier")))}" '
        f'alt="" loading="lazy">'
        f"{face}"
        f'<span class="g-who"><span class="g-nick">{_esc(nick)}</span>'
        f"{history}"
        f"</span>"
        f'<span class="g-wr">{stats}</span>'
        f"</div></div>"
    )


def _rank_icon(tier) -> str:
    """Название ранга для подписи.

    Список держим здесь, а не берём из модуля турнира: страница матчей
    должна работать независимо от него.
    """
    if not tier:
        return "Без ранга"
    value = int(tier)
    for base, name in RANK_TIERS:
        if base == (value // 10) * 10:
            return name
    return f"Ранг {value}"


GAMES_CSS = """
/* ── Список матчей в оформлении «Боевого кубока» ───────────────────────── */
body{background:#07080c}
.g-screen{width:1180px;max-width:100%;margin:0 auto;position:relative;overflow:hidden;
 border:1px solid #232a38;border-radius:6px;background:linear-gradient(180deg,#12161d,#0a0c12 260px);
 box-shadow:0 18px 48px -28px #000}
/* Тёплое свечение сверху — как в сцене кубка. Держим его слабым и позади
   текста, иначе он подсвечивает заголовок и вкладки. */
.g-screen::before{content:"";position:absolute;left:0;right:0;top:0;height:220px;
 background:radial-gradient(70% 100% at 50% 0,rgba(230,98,42,.14),transparent 72%);
 pointer-events:none;z-index:0}
.g-top .g-sp{flex:1}

/* ── Вкладки ───────────────────────────────────────────────────────────── */
/* Переключатель вкладок: сегментированный блок, ничего не наезжает. */
.g-tabs{display:inline-flex;align-items:stretch;gap:4px;margin:14px 14px 0;
 padding:4px;background:#0d1118;border:1px solid #232a38;border-radius:8px;
 position:relative;z-index:2;max-width:100%;overflow:hidden}
.g-tab{font-size:10.5px;font-weight:800;letter-spacing:.11em;text-transform:uppercase;
 padding:9px 18px;border-radius:5px;border:1px solid transparent;background:transparent;
 color:#8e97aa;text-decoration:none;white-space:nowrap;
 transition:color .18s ease,background .18s ease,border-color .18s ease,
 box-shadow .18s ease,transform .18s ease}
.g-tab:hover{color:#dbe1eb;background:rgba(255,255,255,.04)}
.g-tab:active{transform:scale(.98)}
.g-tab.on{color:#f7e3c0;background:linear-gradient(180deg,rgba(232,171,63,.28),rgba(201,136,31,.12));
 border-color:rgba(232,180,92,.55);box-shadow:inset 0 1px 0 rgba(255,255,255,.06)}

.g-body{padding:16px 20px 22px;position:relative;z-index:2}

/* ── Карточка игры: при клике справа выезжают действия ── */
.g-card{cursor:pointer}
.g-card .g-more{margin-left:auto;display:inline-flex;color:#5b6478;
 transition:transform .2s ease,color .2s ease}
.g-card.open .g-more{transform:rotate(90deg);color:#e8b45c}
/* Раскрытая карточка — строка смахивает влево, действия встают
   справа от неё (а не падают вторым рядом под ней). */
.g-card.open{display:flex;align-items:center;gap:8px}
.g-card.open .g-line{flex:1 1 auto;min-width:0}
.g-acts{display:flex;gap:6px;flex-shrink:0;max-height:0;overflow:hidden;opacity:0;
  flex-direction:column;transition:max-height .24s ease,opacity .2s ease}
.g-card.open .g-acts{max-height:none;opacity:1}
.g-act{display:inline-flex;align-items:center;justify-content:center;
  padding:7px 14px;border-radius:8px;background:linear-gradient(180deg,#1d2431,#171d26);
  border:1px solid #2c3444;color:#ccd5e4;font:700 10px/1 Inter,sans-serif;
  letter-spacing:.04em;text-transform:uppercase;white-space:nowrap;
  cursor:pointer;transition:border-color .16s ease,color .16s ease,
  background .16s ease,transform .12s ease}
.g-act:hover{border-color:rgba(232,180,92,.55);color:#f7e3c0;
  background:linear-gradient(180deg,#232b3a,#1b222d);transform:translateY(-1px)}
.g-act:active{transform:translateY(0)}
.g-act.dotabuff:hover{border-color:rgba(214,69,69,.6);color:#f0a5a5;
  background:linear-gradient(180deg,#2a1e21,#1e171a)}

/* Под героем в топе рангов: тихая ссылка на историю игр игрока. */
.g-igames{display:inline-block;margin-top:3px;font-size:9.5px;font-weight:800;
  letter-spacing:.1em;text-transform:uppercase;color:#6f7a90;text-decoration:none;
  border-bottom:1px solid rgba(232,180,92,.3);padding-bottom:1px;
  transition:color .16s ease,border-color .16s ease}
.g-igames:hover{color:#e8b45c;border-color:rgba(232,180,92,.75)}

/* ── История роллов ── */
.g-card.g-roll .g-line{display:flex;align-items:center;gap:10px;padding:9px 11px}
.g-gain{font-size:13px;font-weight:900;color:#7fd18a;font-variant-numeric:tabular-nums;
 white-space:nowrap;flex-shrink:0;margin-left:auto}
.g-gain.neg{color:#ef6a5a}
.g-fissure{font-size:11.5px;color:#8e97aa;font-variant-numeric:tabular-nums;
 white-space:nowrap;flex-shrink:0;min-width:54px;text-align:right}
.g-rc-x{font-size:9.5px;font-weight:800;color:#e8b45c;background:rgba(232,180,92,.12);
 border:1px solid rgba(232,180,92,.25);border-radius:4px;padding:1px 5px;flex-shrink:0}
.g-rc-ev{font-size:9.5px;font-weight:800;color:#9fb0d0;background:rgba(120,140,180,.12);
 border:1px solid rgba(120,140,180,.3);border-radius:4px;padding:1px 5px;flex-shrink:0}

/* ── Вкладка «Топ рангов»: те же поля, что на странице топа ─────────────── */
.g-card.g-mmr .g-line{display:grid;
 grid-template-columns:34px 34px 30px minmax(0,1fr) 210px;align-items:center;gap:10px}
/* Сортировка повторяет выбор игрока: свёрнутая кнопка с текущим
   признаком сортировки, а список вариантов раскрывается по клику.
   Вариантов два-три, держать их на виду незачем — они занимали ряд
   целиком и сдвигали список вниз на телефоне. */
.g-sort{position:relative;padding:0 10px 10px;user-select:none}
.g-sort-btn{width:100%;display:flex;align-items:center;gap:9px;padding:9px 12px;
  background:#0e131b;border:1px solid #222a37;border-radius:8px;cursor:pointer;
  color:#dbe1eb;font:600 11px/1.2 Inter,sans-serif;transition:border-color .18s ease,background .18s ease}
.g-sort-btn:hover{border-color:#39445a;background:#111823}
.g-sort-ic{display:inline-flex;color:#7d879b}
.g-sort-t{flex:1;text-align:left;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.g-sort-chev{display:inline-flex;color:#7d879b;transition:transform .22s ease}
.g-sort.open .g-sort-chev{transform:rotate(180deg)}
.g-sort.open .g-sort-btn{border-color:rgba(232,180,92,.4);color:#f7e3c0}
.g-sort-menu{display:none;margin-top:8px;padding:8px;background:#0b0f16;
  border:1px solid #222a37;border-radius:10px;flex-direction:column;gap:5px}
.g-sort.open .g-sort-menu{display:flex}
.g-sort-b{position:relative;display:flex;align-items:center;justify-content:space-between;gap:10px;
  padding:7px 10px;border:0;border-radius:6px;background:transparent;
  font:inherit;font-size:11px;font-weight:800;letter-spacing:.08em;
  text-transform:uppercase;color:#9aa4b7;white-space:nowrap;cursor:pointer;text-align:left;
  transition:color .15s ease,background .15s ease}
.g-sort-b:hover{background:rgba(255,255,255,.05);color:#eef2f8}
.g-sort-b.on{background:rgba(232,180,92,.12);color:#f7e3c0}
/* Стрелка — только у активной. У неактивных места нет, чтобы ряд
   не рвался при смене колонки. */
.g-sort-ar{width:0;height:0;border-left:3.5px solid transparent;
  border-right:3.5px solid transparent;border-top:4px solid #e8b45c;
  opacity:0;transition:opacity .18s ease,transform .18s ease}
.g-sort-b.on .g-sort-ar{opacity:1}
.g-sort-b.on:not([data-dir="up"]) .g-sort-ar{transform:rotate(180deg)}
.g-rank-img{width:26px;height:26px;object-fit:contain;flex-shrink:0}
.g-rank-blank{display:grid;place-items:center;color:#4a5262;font-size:12px}
/* Ранг в строке игры: иконка в рамке с названием, оба мелкие —
   они живут в строке подписи рядом с именем героя. */
.g-rank-mini{display:inline-flex;align-items:center;gap:4px;padding:1px 6px 1px 4px;
 border-radius:4px;background:rgba(232,180,92,.09);border:1px solid rgba(232,180,92,.2);
 vertical-align:-3px;margin-right:5px}
.g-rank-mini img{width:11px;height:11px;object-fit:contain;flex-shrink:0;display:block}
.g-rank-name{color:#f2d9a0;font-weight:700;font-size:9px;line-height:1}
.g-rank-none{color:#4a5262;font-size:9px}
.g-face{width:26px;height:26px;border-radius:50%;flex-shrink:0;object-fit:cover;
 background:#1b212c;display:grid;place-items:center;font-size:10px;color:#5a6478}
.g-wr{display:flex;align-items:center;gap:8px;justify-content:flex-end}
.g-wr-num{font-size:11.5px;font-weight:800;min-width:34px;text-align:right;
 font-variant-numeric:tabular-nums}
.g-wr-track{flex:1;height:5px;border-radius:3px;background:#1b212c;
 box-shadow:inset 0 0 0 1px #262d3a;overflow:hidden;max-width:96px}
.g-wr-fill{display:block;height:100%;border-radius:3px;
 transition:width .3s cubic-bezier(.2,.7,.3,1)}
.g-wr-wl{font-size:10.5px;color:#8e97aa;font-variant-numeric:tabular-nums;white-space:nowrap}
.g-wr-none{font-size:11.5px;color:#5b6478}
.g-card.g-mmr.top3{border-color:rgba(232,180,92,.35)}

.g-card{background:#12161d;border:1px solid #262d3a;border-radius:2px;
 transition:border-color .18s ease,transform .18s cubic-bezier(.2,.7,.3,1),box-shadow .18s ease}
.g-card:hover{border-color:rgba(232,180,92,.55);transform:translateX(3px);
 box-shadow:0 6px 18px -10px rgba(0,0,0,.8)}
.g-card + .g-card{margin-top:6px}
.g-line{display:flex;align-items:center;gap:10px;padding:7px 10px;text-decoration:none;color:inherit}
.g-hero{width:26px;height:26px;border-radius:3px;flex-shrink:0;object-fit:cover;
 background:#1b212c;display:grid;place-items:center;font-size:10px;color:#5a6478}
.g-who{min-width:0;flex:1;display:flex;flex-direction:column}
.g-nick{font-size:12px;font-weight:700;color:#dbe1eb;white-space:nowrap;overflow:hidden;
 text-overflow:ellipsis}
.g-nick:hover{color:#e8b45c}
.g-heron{font-size:9.5px;color:#6f7889;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.g-kda{font-size:11.5px;color:#8e97aa;font-variant-numeric:tabular-nums;white-space:nowrap;
 flex-shrink:0}
.g-kda b{color:#f2f5fa}
.g-res{width:19px;height:19px;display:grid;place-items:center;border-radius:5px;
 font-size:10px;font-weight:800;line-height:1;text-transform:uppercase;
 flex-shrink:0}
.g-card.win .g-res{color:#7fd18a;background:rgba(127,209,138,.12);
 box-shadow:inset 0 0 0 1px rgba(127,209,138,.3)}
.g-card.loss .g-res{color:#ef6a5a;background:rgba(239,106,90,.12);
 box-shadow:inset 0 0 0 1px rgba(239,106,90,.28)}
.g-when{font-size:10px;color:#5b6478;font-variant-numeric:tabular-nums;white-space:nowrap;
 flex-shrink:0}
.g-bar{display:flex;gap:8px;flex-wrap:wrap;padding:0 0 14px}

/* Выбор игрока: свёрнутая кнопка + выпадающий список ников. */
.g-pick{position:relative;padding-bottom:14px;margin-bottom:-14px}
.g-pick-btn{width:100%;display:flex;align-items:center;gap:9px;padding:9px 12px;
 background:#0e131b;border:1px solid #222a37;border-radius:8px;cursor:pointer;
 color:#dbe1eb;font:600 11px/1.2 Inter,sans-serif;transition:border-color .18s ease,background .18s ease}
.g-pick-btn:hover{border-color:#39445a;background:#111823}
.g-pick-ic{display:inline-flex;color:#7d879b}
.g-pick-t{flex:1;text-align:left;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.g-pick-ar{display:inline-flex;color:#7d879b;transition:transform .22s ease}
.g-pick.open .g-pick-ar{transform:rotate(180deg)}
.g-pick.open .g-pick-btn{border-color:rgba(232,180,92,.4);color:#f7e3c0}
.g-pick-menu{display:none;margin-top:8px;padding:8px;background:#0b0f16;
 border:1px solid #222a37;border-radius:10px;flex-direction:column;gap:5px}
.g-pick.open .g-pick-menu{display:flex}
.g-pick-menu a{display:flex;align-items:center;justify-content:space-between;gap:10px;
 padding:7px 10px;border-radius:6px;font-size:11px;color:#9aa4b7;transition:background .15s ease,color .15s ease}
.g-pick-menu a:hover{background:rgba(255,255,255,.05);color:#eef2f8}
.g-pick-menu a.on{background:rgba(232,180,92,.12);color:#f7e3c0;font-weight:700}
.g-bar a{font-size:10px;padding:5px 11px;border-radius:3px;border:1px solid #262d3a;
 background:#12161d;color:#8e97aa;text-decoration:none;transition:all .18s ease}
.g-bar a:hover{border-color:#39445a;color:#dbe1eb}
.g-bar a.on{border-color:rgba(232,180,92,.7);color:#f7e3c0;
 background:linear-gradient(180deg,rgba(232,171,63,.26),rgba(201,136,31,.10))}
.g-empty{font-size:11px;color:#6f7889;text-align:center;padding:26px 10px}
.g-foot{padding:0 20px 20px;font-size:9px;letter-spacing:.12em;text-transform:uppercase;
 color:#3c4454;position:relative;z-index:2}

/* ── Карточка топа рангов ── */
.g-rank{width:26px;height:26px;border-radius:3px;flex-shrink:0;display:grid;place-items:center;
 font-size:10.5px;font-weight:900;color:#8e97aa;background:#1b212c;
 box-shadow:inset 0 0 0 1px #2a3340;font-variant-numeric:tabular-nums}
.g-rank.top{color:#f7e3c0;background:linear-gradient(180deg,rgba(232,171,63,.3),rgba(201,136,31,.12));
 box-shadow:inset 0 0 0 1px rgba(232,180,92,.75)}
.g-face{width:26px;height:26px;border-radius:50%;flex-shrink:0;object-fit:cover;background:#1b212c}
.g-mmr{font-size:13px;font-weight:900;color:#e8b45c;font-variant-numeric:tabular-nums;
 white-space:nowrap;flex-shrink:0}
.g-wr{font-size:10px;color:#6f7889;font-variant-numeric:tabular-nums;white-space:nowrap;
 flex-shrink:0}
.g-card.top3 .g-nick{color:#f7e3c0}

@media(max-width:640px){
 /* На телефоне всё, что меньше ~12px, просто не читается: держим
    подписи, имена и цифры выше этого порога, а не ужимаем их. */
 .g-screen{border-radius:0;border-left:0;border-right:0}
 .g-body{padding-left:14px;padding-right:14px}
 .g-tabs{margin:12px 14px 0;width:calc(100% - 28px)}
 .g-tab{flex:1 1 0;padding:12px 10px;text-align:center;font-size:13px;
 letter-spacing:.03em;min-width:0}

 /* История игр: ники, герои и ранг крупнее, KDA и результат — в размер
    пальца. Дата прячем осознанно: на телефоне важнее кто и сколько убил. */
 .g-line{gap:9px;padding:11px 10px}
 .g-who{font-size:14px}
 .g-heron{display:block;font-size:12px;color:#7c869c;margin-top:3px}
 .g-when{display:none}
 .g-kda{font-size:13px}
 .g-res{width:22px;height:22px;font-size:12px}
 .g-rank-img{width:26px;height:26px}
 .g-face,.g-hero{width:30px;height:30px}
 .g-hero{font-size:12px}
 .g-more{width:16px;height:16px}
 .g-acts{max-height:0}
 .g-card.open .g-acts{max-height:none;opacity:1}
 .g-act{font-size:11px;padding:10px 14px;flex-shrink:0;letter-spacing:.05em}

 /* Топ рангов: колонки шире, подписи и проценты крупнее. */
 .g-card.g-mmr .g-line{grid-template-columns:30px 28px 28px minmax(0,1fr) 96px;
 gap:7px}
 .g-rank{width:30px;height:30px;font-size:12.5px}
 .g-rank-img,.g-face{width:26px;height:26px}
.g-nick{font-size:14px}
  .g-heron{font-size:11.5px}
  /* Кнопку истории игр на телефоне тоже не мельчим. */
  .g-igames{font-size:11.5px;margin-top:5px;padding:4px 0}
  .g-sort{padding:0 10px 10px}
  .g-sort-btn{padding:12px;font-size:13.5px}
  .g-sort-b{font-size:13px;padding:11px 10px;letter-spacing:.04em}
 .g-wr{font-size:12px}
 .g-wr-track{display:none}
 .g-wr-num{min-width:30px;font-size:13px}
 .g-wr-wl{font-size:11px}

 /* Панель выбора игрока — крупные строки, попадать пальцем. */
 .g-pick-btn{padding:12px;font-size:13.5px}
 .g-pick-menu a{font-size:13px;padding:11px 10px}
 .g-bar a{font-size:12px;padding:8px 12px}
 .g-empty{font-size:13px}
}
"""

def sort_btn(key: str, label: str, default: bool = False) -> str:
    """Пункт выпадающего списка сортировки.

    Ключ — имя data-атрибута в строке (rank_tier, stats, growth,
    fissure, name). Переставляет строки общий SORT_JS, поэтому
    разметка не знает, на какой вкладке она находится.
    """
    on = " on" if default else ""
    return (f'<button type="button" class="g-sort-b{on}" '
            f'data-sort="{key}" data-label="{_esc(label)}">{_esc(label)}'
            f'<span class="g-sort-ar"></span></button>')


SORT_ICON = ('<span class="g-sort-ic" aria-hidden="true">'
             '<svg viewBox="0 0 16 16" width="13" height="13">'
             '<path d="M4 3v10M4 13l-2.2-2.6M4 13l2.2-2.6M12 13V3M12 3L9.8 5.6'
             'M12 3l2.2 2.6" fill="none" stroke="currentColor" stroke-width="1.4" '
             'stroke-linecap="round" stroke-linejoin="round"/></svg></span>')
SORT_CHEVRON = ('<span class="g-sort-chev" aria-hidden="true">'
                '<svg viewBox="0 0 16 16" width="11" height="11">'
                '<path d="M4 6.5 8 10.5 12 6.5" fill="none" stroke="currentColor" '
                'stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/>'
                '</svg></span>')


def sort_bar(options: list[tuple[str, str]], rows: str) -> str:
    """Свёрнутая кнопка сортировки и её раскрывающийся список.

    Устроена как панель выбора игрока: на кнопке только текущий признак,
    варианты лежат внутри и раскрываются по клику. Первым в options идёт
    активный вариант — он же подписан на кнопке и отмечен в списке.
    """
    default_key, default_label = options[0]
    menu = "".join(
        sort_btn(key, label, default=key == default_key) for key, label in options
    )
    return (
        f'<div class="g-sort" data-rows="{rows}">'
        f'<button type="button" class="g-sort-btn" aria-expanded="false">'
        f'{SORT_ICON}'
        f'<span class="g-sort-t">{_esc(default_label)} '
        f'{"↑" if default_key == "ts" else "↓"}</span>'
        f'{SORT_CHEVRON}'
        f"</button>"
        f'<div class="g-sort-menu">{menu}</div>'
        f"</div>"
    )


def render_games_page(
    games: list[dict],
    limit: int = DEFAULT_LIMIT,
    player: str = "",
    miniapp: bool = False,
    tab: str = "games",
    mmr_players: list[dict] | None = None,
    rolls: list[dict] | None = None,
) -> str:
    """Страница матчей и топа MMR в оформлении «Боевого кубока»."""
    suffix = "&miniapp=1" if miniapp else ""
    # 'ranks' — понятное имя вкладки, 'mmr' оставлен для старых ссылок.
    tab = ("rolls" if tab == "rolls" else
           "mmr" if tab in ("ranks", "mmr") else "games")

    # Счётчики по игрокам питают чипы фильтра.
    players: dict[str, dict] = {}
    for game in games:
        key = str(game.get("bot_username") or game.get("personaname") or "Игрок")
        entry = players.setdefault(key, {"wins": 0, "games": 0})
        entry["games"] += 1
        if game.get("win"):
            entry["wins"] += 1

    def chip(key: str, label: str) -> str:
        href = f"/games?limit={limit}{suffix}"
        if key:
            href = f"/games?player={_esc(key)}&limit={limit}{suffix}"
        on = " on" if tab == "games" and key == player else ""
        return f'<a class="{on.strip()}" href="{href}">{_esc(label)}</a>'

    chips = [chip("", "Все игроки")]
    for key, stats in sorted(
        players.items(), key=lambda kv: (-kv[1]["games"], kv[0].lower())
    )[:10]:
        chips.append(chip(key, f"{key} · {stats['wins']}/{stats['games']}"))

    if player:
        games = [
            g
            for g in games
            if str(g.get("bot_username") or g.get("personaname") or "Игрок") == player
        ]

    if tab == "mmr":
        rows = sorted(mmr_players or [], key=mmr_sort_key)
        # Сортировка одна на обе вкладки: свёрнутая кнопка .g-sort,
        # строки переставляет общий скрипт SORT_JS.
        head = sort_bar(
            [("stats", "Статистика"), ("rank_tier", "Ранг")],
            ".g-card.g-mmr",
        )
        # Данные для клиентской сортировки кладём в data-* самой строки.
        body = head + (
            "".join(render_mmr_row(
                p, i, sort_keys=mmr_sort_keys(p),
                games_href=games_href_for(p),
            )
                    for i, p in enumerate(rows, 1))
            or '<div class="g-empty">Рейтинг пока пуст.</div>')
    elif tab == "rolls":
        # История роллов приходит с самой страницы бота, newest first.
        items = list(rolls or [])
        # Первым идёт «Последние»: лог роллов читают сверху вниз по времени,
        # и по нику он с первого взгляда терял смысл.
        head = sort_bar(
            [("ts", "Последние"), ("name", "Игрок"),
             ("growth", "Прирост"), ("fissure", "Фиссура")],
            ".g-card.g-roll",
        )
        body = head + ("".join(render_roll(r) for r in items[:limit * 4]) or (
            '<div class="g-empty">Роллов пока нет.<br>'
            "Крутаните фисс — и он появится здесь.</div>"))
    else:
        body = "".join(render_game(g) for g in games) or (
            '<div class="g-empty">Пока нет игр.<br>'
            "Привяжите Steam в боте — и последние игры появятся здесь.</div>")

    def tab_link(key: str, label: str) -> str:
        paths = {"games": "/matches", "mmr": "/matches?tab=ranks",
                 "rolls": "/matches?tab=rolls"}
        href = paths.get(key, "/matches")
        if miniapp:
            href += "?miniapp=1" if key == "games" else "&miniapp=1"
        on = " on" if key == tab else ""
        return f'<a class="g-tab{on}" href="{href}">{label}</a>'

    # Заголовка на странице нет, но имя вкладки браузера нужно.
    page_title = ("История роллов — Fissure.Bot" if tab == "rolls" else
                  "Топ рангов — Fissure.Bot" if tab == "mmr" else \
                  "История игр — Fissure.Bot")

    body_class = ' class="miniapp"' if miniapp else ""
# Чипы — это фильтр по игрокам, он нужен только в истории игр.
    # В топе рангов каждая строка уже игрок, фильтр там лишний.
    # Список игроков свёрнут под одну кнопку: на телефоне он занимал
    # пол-экрана, а нужен редко. Раскрывается по клику, без перезагрузки.
    chips_bar = ""
    if tab == "games":
        sel = player or ""
        btn_label = _esc(player) if player else "Все игроки"
        chips_bar = (
            '<div class="g-pick' + (" open" if player else "") + '">'
            f'<button type="button" class="g-pick-btn" aria-expanded="'
            f'{"true" if player else "false"}">'
            '<span class="g-pick-ic">'
            '<svg viewBox="0 0 16 16" width="13" height="13" aria-hidden="true">'
            '<circle cx="6" cy="5" r="2.4" fill="none" stroke="currentColor" '
            'stroke-width="1.4"/><path d="M2 13c0-2.2 1.8-3.6 4-3.6s4 1.4 4 3.6" '
            'fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/>'
            "</svg></span>"
            f'<span class="g-pick-t">{btn_label}</span>'
            '<span class="g-pick-ar">'
            '<svg viewBox="0 0 16 16" width="11" height="11" aria-hidden="true">'
            '<path d="M4 6.5 8 10.5 12 6.5" fill="none" stroke="currentColor" '
            'stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/>'
            "</svg></span>"
            "</button>"
            f'<div class="g-pick-menu">{"".join(chips)}</div>'
            "</div>"
        )
    return (
        "<!DOCTYPE html>\n"
        '<html lang="ru">\n<head>\n'
        '<meta charset="UTF-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">\n'
        f"<title>{page_title}</title>\n"
        '<meta name="description" content="Последние игры игроков Fissure.Bot и топ MMR.">\n'
        f'<script src="{TELEGRAM_WEBAPP_JS}"></script>\n'
        f"<style>{PAGE_CSS}{GAMES_CSS}</style>\n"
        f"</head>\n<body{body_class}>\n"
        # Страница начинается с переключателя вкладок: логотип, заголовок
        # и подпись убраны — только список.
        '<div class="g-screen">\n'
        f'<div class="g-tabs">{tab_link("games", "История")}{tab_link("mmr", "Топ рангов")}'
        f'{tab_link("rolls", "Ролл")}</div>\n'
        f'<div class="g-body">{chips_bar}{body}</div>\n'
        "</div>\n"
        f"<script>{TELEGRAM_INIT_JS}</script>\n"
        f"<script>{GAME_ACTS_JS}</script>\n"
        f"<script>{PICKER_JS}</script>\n"
        # Ник открывает профиль в Telegram. Раньше это была вложенная <a>
        # внутри <a>, что невалидно, поэтому вешаем переход на data-атрибут.
        "<script>document.addEventListener('click',function(e){var p=e.target"
        ".closest('[data-tg]');if(!p)return;e.preventDefault();e.stopPropagation();"
        "open('tg://user?id='+p.dataset.tg);});</script>\n"
        f"<script>{SORT_JS}</script>\n"
        '<script>setTimeout(function(){ location.reload(); }, 60000);</script>\n'
        "</body>\n</html>"
    )


PAGE_CSS = """
:root{--bg:#0a0a0f;--card:#12141c;--line:#23262f;--txt:#e8eaf0;--txt2:#9aa1b1;
--txt3:#6b7280;--acc:#ff8c42;--rad:#4ade80;--dire:#f87171;--win:#4ade80;--loss:#f87171}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--txt);padding-bottom:env(safe-area-inset-bottom);
-webkit-tap-highlight-color:transparent;
font-family:Inter,system-ui,-apple-system,'Segoe UI',Roboto,sans-serif}
.wrap{max-width:1100px;margin:0 auto;padding:28px 16px 60px}
/* Opened as a Telegram Mini App: tighter paddings, room for the safe area. */
body.miniapp .wrap{padding:14px 12px 40px}
body.miniapp h1{font-size:22px}
body.miniapp .bar a{padding:9px 16px}
h1{font-size:26px;margin:0 0 6px}
.sub{color:var(--txt2);font-size:14px;margin:0 0 20px}
.live{display:inline-block;width:8px;height:8px;border-radius:50%;background:#22c55e;
margin-right:6px;animation:p 2s infinite}
@keyframes p{0%,100%{opacity:1}50%{opacity:.3}}
.bar{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:18px}
.bar a{border:1px solid var(--line);background:var(--card);color:var(--txt2);
padding:8px 14px;border-radius:999px;font:600 13px Inter,sans-serif;text-decoration:none}
.bar a:hover{color:var(--txt);border-color:var(--acc)}
.bar a.on{background:var(--acc);border-color:var(--acc);color:#fff}
.empty{text-align:center;color:var(--txt2);padding:60px 20px}
.match-card{display:grid;grid-template-columns:1fr 200px 1fr;gap:12px;background:var(--card);
border:1px solid var(--line);border-radius:14px;padding:14px;margin-bottom:10px;
transition:border-color .2s,transform .2s}
.match-card:hover{border-color:#3a3f4d;transform:translateY(-2px)}
.match-card.partial{opacity:.6}
.match-side{min-width:0}
.side-head{display:flex;justify-content:space-between;align-items:center;font-size:12px;
letter-spacing:.06em;text-transform:uppercase;color:var(--txt3);margin-bottom:8px;
padding-bottom:6px;border-bottom:1px solid var(--line)}
.side-kills{font-size:16px;font-weight:800}
.match-side.radiant .side-kills{color:var(--rad)}
.match-side.dire .side-kills{color:var(--dire)}
.team-row{display:flex;align-items:center;gap:8px;padding:5px 0;font-size:13px}
.team-row.winner{color:var(--txt)}
.hero-icon{width:26px;height:26px;border-radius:50%;object-fit:cover;flex-shrink:0;
background:#22252e}
.pinfo{display:flex;flex-direction:column;min-width:0;flex:1}
.pname{color:var(--txt2);text-decoration:none;white-space:nowrap;overflow:hidden;
text-overflow:ellipsis}
.pname.bot{color:var(--acc);font-weight:600}
.pname-sub{font-size:11px;color:var(--txt3);white-space:nowrap;overflow:hidden;
text-overflow:ellipsis}
.kda{font-variant-numeric:tabular-nums;color:var(--txt3);font-size:12px;white-space:nowrap}
.team-row.winner .kda{color:var(--txt2)}
.team-empty{color:var(--txt3);font-style:italic}
.match-mid{text-align:center;display:flex;flex-direction:column;gap:4px;
justify-content:center;border-left:1px solid var(--line);border-right:1px solid var(--line)}
.result{font-size:12px;font-weight:800;letter-spacing:.04em;text-transform:uppercase}
.score{font-size:24px;font-weight:800;font-variant-numeric:tabular-nums}
.meta{font-size:11px;color:var(--txt3)}
.ago{font-size:11px;color:var(--txt3)}
.dotapedia{font-size:11px;color:var(--txt3);text-decoration:none}
.dotapedia:hover{color:var(--acc)}
footer{color:var(--txt3);font-size:12px;text-align:center;margin-top:26px}
@media(max-width:820px){
.match-card{grid-template-columns:1fr;gap:8px}
.match-mid{border:0;border-top:1px solid var(--line);border-bottom:1px solid var(--line);
order:-1;padding:8px 0}
}
"""


# Injected at the end of the page. It only does something inside Telegram:
# a normal browser load has no window.Telegram and the script exits at once.
TELEGRAM_INIT_JS = """
(function () {
  var tg = window.Telegram && window.Telegram.WebApp;
  if (!tg) { return; }

  function rgba(hex, alpha) {
    if (!hex || hex.charAt(0) !== '#') { return null; }
    var h = hex.slice(1);
    if (h.length === 3) { h = h[0] + h[0] + h[1] + h[1] + h[2] + h[2]; }
    if (h.length !== 6) { return null; }
    var n = parseInt(h, 16);
    return 'rgba(' + ((n >> 16) & 255) + ',' + ((n >> 8) & 255) + ',' + (n & 255) + ',' + alpha + ')';
  }

  function applyTheme() {
    var p = tg.themeParams || {};
    var root = document.documentElement.style;
    if (p.bg_color) { root.setProperty('--bg', p.bg_color); }
    if (p.secondary_bg_color) {
      root.setProperty('--card', p.secondary_bg_color);
      root.setProperty('--card-soft', rgba(p.secondary_bg_color, 0.6) || p.secondary_bg_color);
    }
    if (p.text_color) { root.setProperty('--txt', p.text_color); }
    if (p.hint_color) {
      root.setProperty('--txt2', p.hint_color);
      root.setProperty('--txt3', rgba(p.hint_color, 0.7) || p.hint_color);
    }
    if (p.separator_color) { root.setProperty('--line', p.separator_color); }
    if (p.button_color) { root.setProperty('--acc', p.button_color); }
  }

  try { tg.ready(); tg.expand(); } catch (e) {}
  document.body.classList.add('miniapp');
  applyTheme();
  if (tg.onEvent) { tg.onEvent('themeChanged', applyTheme); }

  // External links must leave the web view, otherwise the Mini App is replaced.
  document.addEventListener('click', function (ev) {
    var link = ev.target && ev.target.closest ? ev.target.closest('a[target="_blank"]') : null;
    if (!link || !tg.openLink) { return; }
    ev.preventDefault();
    tg.openLink(link.href);
  });
})();
"""


def public_base_url() -> str:
    """Public HTTPS host Telegram opens Web App buttons on.

    The webhook already lives on a public HTTPS domain, so that host is the
    natural home for the Mini App too. `MINIAPP_URL` / `PUBLIC_BASE_URL`
    override it (local runs, a custom domain).
    """
    override = (os.getenv("MINIAPP_URL") or os.getenv("PUBLIC_BASE_URL") or "").strip()
    if override:
        return override.rstrip("/")
    webhook = (os.getenv("WEBHOOK_URL") or "").strip()
    # Telegram refuses anything but HTTPS, so http:// hosts fall through.
    if webhook.startswith("https://"):
        base = webhook.split("/webhook", 1)[0].rstrip("/")
        if base:
            return base
    return DEFAULT_PUBLIC_BASE


def miniapp_url(miniapp: bool = True) -> str:
    """Ready-to-use WebAppInfo URL of the match list page."""
    url = f"{public_base_url()}/matches"
    return f"{url}?miniapp=1" if miniapp else url


def ranks_url(miniapp: bool = True) -> str:
    """WebAppInfo URL of the ranking tab of the match list page.

    Отдельная от miniapp_url(): кнопка «Весь список» должна открывать
    именно топ рангов, а не историю игр.
    """
    url = f"{public_base_url()}/matches?tab=ranks"
    return f"{url}&miniapp=1" if miniapp else url


def rolls_url(miniapp: bool = True) -> str:
    """WebAppInfo URL вкладки с историей роллов."""
    url = f"{public_base_url()}/matches?tab=rolls"
    return f"{url}&miniapp=1" if miniapp else url


def games_href_for(player: dict, limit: int = DEFAULT_LIMIT) -> str:
    """Ссылка на историю игр игрока из топа рангов.

    Ключ вкладки игр — это bot_username, а он пишется в БД как username,
    а если тот пуст, как steam_nickname, поэтому берём их в том же порядке.
    Без ключа возвращаем пустую строку: строка останется без кнопки.
    """
    key = str(player.get("username") or player.get("steam_nickname") or "").strip()
    if not key:
        return ""
    return f"/matches?player={_esc(key)}&limit={limit}&miniapp=1"


PICKER_JS = """
// Выбор игрока: список ников свёрнут под кнопку и раскрывается по клику.
// Разметки тегов здесь быть не должно: страница оборачивает константу сама,
// а лишняя пара тегов делает блок синтаксически невалидным.
(function(){
  var pick = document.querySelector('.g-pick');
  if (!pick) return;
  var btn = pick.querySelector('.g-pick-btn');
  function setOpen(on){
    pick.classList.toggle('open', on);
    btn.setAttribute('aria-expanded', on ? 'true' : 'false');
  }
  btn.addEventListener('click', function(e){
    e.stopPropagation();
    setOpen(!pick.classList.contains('open'));
  });
  // Клик по нику уводит на страницу с фильтром, клик мимо — закрывает.
  pick.addEventListener('click', function(e){ e.stopPropagation(); });
  document.addEventListener('click', function(){ setOpen(false); });
  document.addEventListener('keydown', function(e){
    if (e.key === 'Escape') setOpen(false);
  });
})();
"""
GAME_ACTS_JS = """
// Клик по строке игры раскрывает действия справа: пати и Dotabuff.
(function(){
  var tg = window.Telegram && window.Telegram.WebApp;

  function askParty(card){
    // Подбор по кнопке «Пати» больше не запускается: игрок, которому
    // принадлежит карточка, известен, поэтому зовём его сразу. Общий
    // подбор остаётся только там, где игрока определить нечем.
    //
    // Telegram.WebApp.sendData не годится: он работает только если Mini App
    // открыта кнопкой клавиатуры, а страницу открывают инлайн-кнопкой, и
    // сигнал молча терялся. Поэтому шлём HTTP-запрос с initData — бот
    // проверяет подпись и сам пишет приглашение в игровой чат.
    if (tg && tg.initData) {
      fetch('/api/party', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          initData: tg.initData,
          tg: parseInt(card.dataset.partyTg, 10) || 0
        })
      }).then(function(r){
        return r.json().then(function(d){ return {ok: r.ok && d.ok, d: d}; });
      }).then(function(res){
        if (res.ok) {
          if (tg.showAlert) {
            tg.showAlert((res.d && res.d.invited) ? 'Приглашение отправлено'
                                                  : 'Подбор отправлен в игровой чат');
          }
        } else {
          var why = (res.d && res.d.error) || 'ошибка';
          if (tg.showAlert) tg.showAlert('Не получилось: ' + why);
        }
      }).catch(function(){
        if (tg.showAlert) tg.showAlert('Нет связи с ботом');
      });
      return;
    }
    // Вне Telegram подпись получить нечем — остаётся ссылка на «Поделиться».
    window.open(card.dataset.partyShare || '', '_blank');
  }

  document.querySelectorAll('.g-card[data-party]').forEach(function(card){
    function toggle(){
      var open = card.classList.contains('open');
      document.querySelectorAll('.g-card.open').forEach(function(c){
        if (c !== card) c.classList.remove('open');
      });
      card.classList.toggle('open', !open);
    }
    card.addEventListener('click', function(e){
      var act = e.target.closest('[data-act]');
      if (!act) { toggle(); return; }   // клик по строке — раскрыть
      e.stopPropagation();
      if (act.dataset.act === 'party') {
        askParty(card);
      } else {
        window.open(card.dataset.dota, '_blank');
      }
    });
    card.addEventListener('keydown', function(e){
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggle(); }
    });
  });
})();
"""

SORT_JS = """
// Одна сортировка на обе вкладки.
// Разметка лишь говорит, какой колонкой сортировать (data-sort) и где
// лежат строки (data-rows) — порядок, переключение направления и
// перерисовка номеров делает этот код, поэтому вкладкам не нужен
// свой скрипт.
(function(){
  var bar = document.querySelector('.g-sort');
  if (!bar) return;
  var sel = bar.dataset.rows;
  if (!sel) return;
  var sign = {};                     // колонка -> 1 (↑) / -1 (↓)
  var cap = bar.querySelector('.g-sort-t');
  var trigger = bar.querySelector('.g-sort-btn');

  // Список свёрнут, как панель выбора игрока: открыт по клику, закрыт
  // кликом мимо и Escape.
  function setOpen(on){
    bar.classList.toggle('open', on);
    if (trigger) trigger.setAttribute('aria-expanded', on ? 'true' : 'false');
  }
  if (trigger){
    trigger.addEventListener('click', function(e){
      e.stopPropagation();
      setOpen(!bar.classList.contains('open'));
    });
  }
  bar.addEventListener('click', function(e){ e.stopPropagation(); });
  document.addEventListener('click', function(){ setOpen(false); });
  document.addEventListener('keydown', function(e){
    if (e.key === 'Escape') setOpen(false);
  });

  // Колонка, активная на старте, уже отсортирована по убыванию.
  var first = bar.querySelector('[data-sort].on');
  if (first) sign[first.dataset.sort] = -1;

  function rows(){
    return Array.prototype.slice.call(document.querySelectorAll(sel));
  }
  function value(row, key){
    var n = parseFloat(row.dataset[key]);
    return isNaN(n) ? 0 : n;
  }
  // Номера мест и подсветка топ-3 должны следовать за порядком строк.
  function paint(){
    rows().forEach(function(r, i){
      var n = r.querySelector('.g-rank');
      if (n) n.textContent = i + 1;
      r.classList.toggle('top3', i < 3);
    });
  }
  // Выбранный вариант едет на кнопку — на ней видно, чем сейчас
  // отсортировано, даже когда список свёрнут.
  function caption(b, s){
    if (!cap) return;
    cap.textContent = (b.dataset.label || '') + (s === 1 ? ' ↑' : ' ↓');
  }
  bar.addEventListener('click', function(e){
    var b = e.target.closest('[data-sort]');
    if (!b || !bar.contains(b)) return;
    var key = b.dataset.sort;
    if (!(key in sign)) sign[key] = key === 'name' ? 1 : -1;
    else sign[key] = -sign[key];
    var s = sign[key];
    rows().sort(function(a, c){
      // В топе без игр всегда внизу — как на странице рейтинга.
      if ('games' in a.dataset && 'games' in c.dataset){
        var ga = value(a, 'games'), gc = value(c, 'games');
        if ((ga === 0) !== (gc === 0)) return ga === 0 ? 1 : -1;
      }
      if (key === 'name')            // по нику — по алфавиту, не по длине
        return String(a.dataset.name || '').localeCompare(
          String(c.dataset.name || ''), 'ru') * s;
      return (value(a, key) - value(c, key)) * s;
    }).forEach(function(r){ bar.parentNode.appendChild(r); });

    // Подсветку переносим, а не пересоздаём кнопки — ряд не прыгает.
    bar.querySelectorAll('[data-sort]').forEach(function(el){
      var on = el === b;
      el.classList.toggle('on', on);
      if (on) el.dataset.dir = s === 1 ? 'up' : 'down';
      else delete el.dataset.dir;
    });
    caption(b, s);
    paint();
    setOpen(false);
  });
})();
"""


def render_page(matches: list[dict], limit: int = DEFAULT_LIMIT, miniapp: bool = False) -> str:
    """Full HTML page with the match list rendered server-side.

    The same markup serves two audiences: the public web page and the Telegram
    Mini App (`?miniapp=1`, and any other load inside the Telegram web view —
    there the injected script flags itself). That way there is only one list
    to maintain, and the page keeps working in a plain browser.
    """
    body = (
        "".join(render_match(m) for m in matches)
        if matches
        else (
            '<div class="empty">Пока нет матчей Dota 2.<br>'
            "Как только игроки бота сыграют — они появятся здесь.</div>"
        )
    )
    # Keep the Mini App mode when switching the page size.
    suffix = "&miniapp=1" if miniapp else ""
    options = "".join(
        f'<a class="{"on" if n == limit else ""}" href="/matches?limit={n}{suffix}">{n} матчей</a>'
        for n in (20, 50)
    )
    body_class = ' class="miniapp"' if miniapp else ""
    return (
        "<!DOCTYPE html>\n"
        '<html lang="ru">\n<head>\n'
        '<meta charset="UTF-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">\n'
        "<title>Матчи Dota 2 — Fissure.Bot</title>\n"
        '<meta name="description" content="Список последних матчей Dota 2, сыгранных '
        'игроками Fissure.Bot: команды, герои, счёт и длительность.">\n'
        f'<script src="{TELEGRAM_WEBAPP_JS}"></script>\n'
        f"<style>{PAGE_CSS}</style>\n"
        f"</head>\n<body{body_class}>\n"
        '<div class="wrap">\n'
        "<h1>Матчи Dota 2</h1>\n"
        '<p class="sub"><span class="live"></span>Реальные игры игроков Fissure.Bot — '
        "обновляется раз в минуту</p>\n"
        f'<div class="bar">{options}</div>\n'
        f'<div id="list">{body}</div>\n'
        "<footer>Fissure.Bot · данные OpenDota</footer>\n"
        "</div>\n"
        f"<script>{TELEGRAM_INIT_JS}</script>\n"
        '<script>setTimeout(function(){ location.reload(); }, 60000);</script>\n'
        "</body>\n</html>"
    )
