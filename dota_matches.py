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


async def get_player_games(limit: int = DEFAULT_LIMIT) -> list[dict]:
    """Latest games of the players linked to the bot, newest first."""
    from dota_mmr import get_recent_matches_async

    limit = max(1, min(int(limit or DEFAULT_LIMIT), MAX_LIMIT))
    steam_ids = await asyncio.to_thread(_linked_steam_ids, PLAYER_GAMES_PLAYERS)
    if not steam_ids:
        return []

    heroes = await asyncio.to_thread(_hero_catalog)
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
    tier = game.get("rank_tier")
    if tier:
        rank = (f'<img class="g-rank-mini" src="{_esc(rank_image(tier))}" '
                f'alt="{_esc(_rank_icon(tier))}" loading="lazy">'
                f'<span class="g-rank-name">{_esc(_rank_icon(tier))}</span>')
    else:
        rank = '<span class="g-rank-none">без ранга</span>'

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

    return (
        f'<div class="g-card {cls}">'
        f'<a class="g-line" '
        f'href="https://www.opendota.com/matches/{int(game["match_id"])}" '
        f'target="_blank" rel="noopener">'
        f"{face}{hero}"
        f'<span class="g-who">{name_html}'
        f'<span class="g-heron">{rank} · {subtitle}</span></span>'
        f'<span class="g-kda"><b>{kills}</b> / {deaths} / {assists}</span>'
        f'<span class="g-res">{"Победа" if win else "Поражение"}</span>'
        f'<span class="g-when">{date_txt} · {time_txt} · '
        f'{_fmt_duration(game.get("duration"))}</span>'
        f"</a>{items}</div>"
    )


RANKS_BASE = "https://seredin999.onrender.com/images/ranks"

# Ранги Dota 2: чем больше номер, тем выше ранг.
RANK_TIERS = [
    (10, "Herald"), (20, "Guardian"), (30, "Crusader"), (40, "Archon"),
    (50, "Legend"), (60, "Ancient"), (70, "Divine"), (80, "Immortal"),
]


def rank_image(tier) -> str:
    """Иконка ранга — та же, что на странице топа MMR.

    Страницу отдаёт бот, а картинки лежат на сайте, поэтому ссылка абсолютная.
    """
    try:
        rt = int(tier or 0)
    except (TypeError, ValueError):
        rt = 0
    if rt <= 0:
        return f"{RANKS_BASE}/rank_1_1.webp"
    tier_no, star = rt // 10, rt % 10
    if star == 0:          # без звёзд показываем с одной
        star = 1
    if 1 <= tier_no <= 8 and 1 <= star <= 5:
        return f"{RANKS_BASE}/rank_{tier_no}_{star}.webp"
    return f"{RANKS_BASE}/rank_1_1.webp"


def mmr_sort_key(player: dict):
    """Порядок топа как на сайте: ранг, затем разница побед, затем игры.

    Игроки без игр за неделю всегда внизу — поэтому им ставим 1, а не 0.
    """
    tier = int(player.get("rank_tier") or 0)
    games = int(player.get("week_games") or 0)
    wins = int(player.get("week_wins") or 0)
    net = wins - (games - wins)
    return (1 if games == 0 else 0, -tier, -net, -games)


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


def render_mmr_row(player: dict, place: int, sort_keys: dict | None = None) -> str:
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

    return (
        f'<div class="g-card g-mmr{" top3" if top else ""}" {attrs}>'
        f'<div class="g-line">'
        f'<span class="g-rank{" top" if top else ""}">{place}</span>'
        f'<img class="g-rank-img" '
        f'src="{_esc(rank_image(player.get("rank_tier")))}" '
        f'alt="" loading="lazy">'
        f"{face}"
        f'<span class="g-who"><span class="g-nick">{_esc(nick)}</span>'
        f'<span class="g-heron">{_rank_icon(player.get("rank_tier"))}</span></span>'
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

/─ Вкладки
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

/─ Карточка игры
/* ── Вкладка «Топ MMR»: те же поля, что на странице топа ─────────────── */
.g-mmr-head,.g-card.g-mmr .g-line{display:grid;
 grid-template-columns:34px 34px 30px minmax(0,1fr) 210px;align-items:center;gap:10px}
.g-mmr-head{padding:2px 10px 8px}
.g-hp{font-size:9px;font-weight:800;letter-spacing:.14em;text-transform:uppercase;color:#6f7889;
 cursor:pointer;user-select:none;transition:color .18s ease;padding:2px 0}
.g-hp:hover{color:#dbe1eb}
.g-hp.right{text-align:right}
.g-hp .ar{color:#e8b45c;margin-left:3px}
.g-rank-img{width:26px;height:26px;object-fit:contain;justify-self:center}
/* Мини-ранг в строке игры. */
.g-rank-mini{width:12px;height:12px;object-fit:contain;vertical-align:-2px;
 margin-right:3px}
.g-rank-name{color:#8e97aa}
.g-rank-none{color:#4a5262}
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
.g-res{font-size:9px;font-weight:800;letter-spacing:.1em;text-transform:uppercase;
 padding:3px 8px;border-radius:999px;white-space:nowrap;flex-shrink:0}
.g-card.win .g-res{color:#7fd18a;background:rgba(127,209,138,.12);
 box-shadow:inset 0 0 0 1px rgba(127,209,138,.3)}
.g-card.loss .g-res{color:#ef6a5a;background:rgba(239,106,90,.12);
 box-shadow:inset 0 0 0 1px rgba(239,106,90,.28)}
.g-when{font-size:10px;color:#5b6478;font-variant-numeric:tabular-nums;white-space:nowrap;
 flex-shrink:0}
.g-bar{display:flex;gap:8px;flex-wrap:wrap;padding:0 0 14px}
.g-bar a{font-size:10px;padding:5px 11px;border-radius:3px;border:1px solid #262d3a;
 background:#12161d;color:#8e97aa;text-decoration:none;transition:all .18s ease}
.g-bar a:hover{border-color:#39445a;color:#dbe1eb}
.g-bar a.on{border-color:rgba(232,180,92,.7);color:#f7e3c0;
 background:linear-gradient(180deg,rgba(232,171,63,.26),rgba(201,136,31,.10))}
.g-empty{font-size:11px;color:#6f7889;text-align:center;padding:26px 10px}
.g-foot{padding:0 20px 20px;font-size:9px;letter-spacing:.12em;text-transform:uppercase;
 color:#3c4454;position:relative;z-index:2}

─ Карточка топа MMR
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
 .g-screen{border-radius:0;border-left:0;border-right:0}
 .g-body{padding-left:14px;padding-right:14px}
 .g-tabs{margin:12px 14px 0;width:calc(100% - 28px)}   /* вровень с текстом */
 .g-tab{flex:1 1 0;padding:9px 10px;text-align:center;font-size:10px;
 letter-spacing:.06em;min-width:0}                      /* не обрезаются */
 .g-heron,.g-when{display:none}
 .g-kda{font-size:11px}
 .g-top{padding:0 10px}
 .g-slot.m{display:none}
 .g-mmr-head,.g-card.g-mmr .g-line{grid-template-columns:28px 26px 26px minmax(0,1fr) 88px;
 gap:6px}
 .g-rank-img,.g-face{width:22px;height:22px}
 .g-wr-track{display:none}
 .g-wr-num{min-width:28px;font-size:11px}
 .g-wr-wl{font-size:9.5px}
}
"""

def render_games_page(
    games: list[dict],
    limit: int = DEFAULT_LIMIT,
    player: str = "",
    miniapp: bool = False,
    tab: str = "games",
    mmr_players: list[dict] | None = None,
) -> str:
    """Страница матчей и топа MMR в оформлении «Боевого кубока»."""
    suffix = "&miniapp=1" if miniapp else ""
    # 'ranks' — понятное имя вкладки, 'mmr' оставлен для старых ссылок.
    tab = "mmr" if tab in ("ranks", "mmr") else "games"

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
        # Заголовки кликабельные — сортировка как на странице топа.
        head = (
            '<div class="g-mmr-head">'
            '<span class="g-hp">#</span>'
            '<span class="g-hp" data-sort="rank_tier">Ранг<span class="ar">▼</span></span>'
            '<span class="g-hp" data-sort="name">Игрок</span>'
            '<span class="g-hp right" data-sort="stats">Статистика</span>'
            "</div>"
        )
        # Данные для клиентской сортировки кладём в data-* самой строки.
        body = head + (
            "".join(render_mmr_row(p, i, sort_keys=mmr_sort_keys(p))
                    for i, p in enumerate(rows, 1))
            or '<div class="g-empty">Рейтинг пока пуст.</div>')
    else:
        body = "".join(render_game(g) for g in games) or (
            '<div class="g-empty">Пока нет игр.<br>'
            "Привяжите Steam в боте — и последние игры появятся здесь.</div>")

    def tab_link(key: str, label: str) -> str:
        href = "/matches" if key == "games" else "/matches?tab=ranks"
        if miniapp:
            href += "?miniapp=1" if key == "games" else "&miniapp=1"
        on = " on" if key == tab else ""
        return f'<a class="g-tab{on}" href="{href}">{label}</a>'

    # Заголовка на странице нет, но имя вкладки браузера нужно.
    page_title = "Топ рангов — Fissure.Bot" if tab == "mmr" else \
        "История игр — Fissure.Bot"

    body_class = ' class="miniapp"' if miniapp else ""
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
        f'<div class="g-tabs">{tab_link("games", "История")}{tab_link("mmr", "Топ рангов")}</div>\n'
        f'<div class="g-body"><div class="g-bar">{"".join(chips)}</div>{body}</div>\n'
        "</div>\n"
        f"<script>{TELEGRAM_INIT_JS}</script>\n"
        # Ник открывает профиль в Telegram. Раньше это была вложенная <a>
        # внутри <a>, что невалидно, поэтому вешаем переход на data-атрибут.
        "<script>document.addEventListener('click',function(e){var p=e.target"
        ".closest('[data-tg]');if(!p)return;e.preventDefault();e.stopPropagation();"
        "open('tg://user?id='+p.dataset.tg);});</script>\n"
        f"{RANKS_SORT_JS}"
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


RANKS_SORT_JS = """
<script>
// Сортировка топа по клику на заголовок — как на странице рейтинга.
(function(){
  var head = document.querySelector('.g-mmr-head');
  if (!head) return;
  var dir = {};                       // колонка -> 1 / -1
  function rows(){
    return Array.prototype.slice.call(
      document.querySelectorAll('.g-card.g-mmr'));
  }
  function value(row, key){
    var v = parseInt(row.dataset[key] || '0', 10);
    return isNaN(v) ? 0 : v;
  }
  function paint(){
    rows().forEach(function(r, i){
      r.querySelector('.g-rank').textContent = i + 1;
      r.classList.toggle('top3', i < 3);
    });
  }
  head.addEventListener('click', function(e){
    var h = e.target.closest('[data-sort]');
    if (!h) return;
    var key = h.dataset.sort;
    dir[key] = dir[key] === 1 ? -1 : 1;
    var sign = dir[key];
    rows().sort(function(a, b){
      // Без игр всегда внизу — как на сайте.
      var ga = value(a, 'games'), gb = value(b, 'games');
      if ((ga === 0) !== (gb === 0)) return ga === 0 ? 1 : -1;
      if (key === 'name'){
        return (a.dataset.name > b.dataset.name ? 1 : -1) * sign;
      }
      return (value(a, key) - value(b, key)) * sign;
    }).forEach(function(r){ head.parentNode.appendChild(r); });
    head.querySelectorAll('.ar').forEach(function(s){ s.remove(); });
    h.insertAdjacentHTML('beforeend',
      '<span class="ar">' + (sign === 1 ? '\\u25BC' : '\\u25B2') + '</span>');
    paint();
  });
})();
</script>
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
