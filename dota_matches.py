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


def _read_all(sql: str) -> list:
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
            cursor.execute(sql)
            return list(cursor.fetchall() or [])
        finally:
            conn.close()

    conn = None
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(sql)
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
    """steam_id -> {telegram_id, username} for every player linked to the bot."""
    index: dict = {}
    try:
        # Row layout is positional, so the same query serves both backends.
        rows = _read_all(
            """
            SELECT steam_id, telegram_id, username, steam_nickname
            FROM users
            WHERE steam_id IS NOT NULL
            LIMIT 5000
            """
        )
        for row in rows:
            if not row or row[0] is None:
                continue
            index[int(row[0])] = {
                "telegram_id": row[1],
                "username": row[2] or row[3] or "Игрок",
            }
    except Exception as e:
        logger.error("dota_matches: failed to build bot steam index: %s", e)
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


PAGE_CSS = """
:root{--bg:#0a0a0f;--card:#12141c;--line:#23262f;--txt:#e8eaf0;--txt2:#9aa1b1;
--txt3:#6b7280;--acc:#ff8c42;--rad:#4ade80;--dire:#f87171}
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
