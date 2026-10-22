"""Tests for the Dota 2 match list served by the bot's web endpoints."""

import asyncio
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import dota_matches
import bot_utils

def test_get_recent_rolls_returns_newest_entries_first(monkeypatch):
    rolls = [
        {"ts": 300, "username": "newest"},
        {"ts": 100, "username": "oldest"},
        {"ts": 200, "username": "middle"},
    ]
    monkeypatch.setattr(bot_utils, "recent_fissure_rolls", rolls)

    assert [r["username"] for r in bot_utils.get_recent_rolls(2)] == [
        "newest", "middle"
    ]

SAMPLE = {
    "match_id": 8123456789,
    "start_time": 1700000000,
    "duration": 2345,
    "radiant_win": True,
    "mode": "Ranked",
    "radiant_score": 32,
    "dire_score": 18,
    "bot_players": 1,
    "partial": False,
    "radiant": [
        {
            "hero_id": 1,
            "hero_name": "Anti-Mage",
            "hero_icon": "/assets/anti-mage.webp",
            "personaname": "ZeusFan",
            "kills": 12,
            "deaths": 3,
            "assists": 9,
            "account_id": 500,
            "bot_username": "@zeus",
            "telegram_id": 777,
        },
        {
            "hero_id": 2,
            "hero_name": "Axe",
            "hero_icon": "",
            "personaname": "<script>alert(1)</script>",
            "kills": 3,
            "deaths": 5,
            "assists": 14,
            "account_id": 501,
        },
    ],
    "dire": [
        {
            "hero_id": 3,
            "hero_name": "Lion",
            "hero_icon": "",
            "personaname": "Rival",
            "kills": 10,
            "deaths": 7,
            "assists": 4,
            "account_id": 502,
        }
    ],
}


def test_mode_name_falls_back_to_ranked():
    assert dota_matches._mode_name(2) == "Random Draft"
    assert dota_matches._mode_name(999) == "Ranked"
    assert dota_matches._mode_name(None) == "Ranked"


def test_duration_formatting():
    assert dota_matches._fmt_duration(0) == "—"
    assert dota_matches._fmt_duration(65) == "1:05"
    assert dota_matches._fmt_duration(2345) == "39:05"


def test_kill_score_accepts_both_opendota_shapes():
    # /matches/{id} returns plain integers...
    assert dota_matches._kill_score(32) == 32
    assert dota_matches._kill_score(0) == 0
    # ...while the public matches feed wraps them into {"kills": n}.
    assert dota_matches._kill_score({"kills": 7}) == 7
    # Missing/garbage values never crash the render path.
    assert dota_matches._kill_score(None) is None
    assert dota_matches._kill_score({}) is None
    assert dota_matches._kill_score("n/a") is None


def test_escape_blocks_html_injection():
    out = dota_matches._esc('<script>alert(1)</script>')
    assert "<script>" not in out
    assert "&lt;script&gt;" in out


def test_team_split_uses_player_slot():
    detail = {
        "players": [
            {"player_slot": 0, "hero_id": 10, "personaname": "r1", "kills": 1,
             "deaths": 0, "assists": 0, "account_id": 1},
            {"player_slot": 128, "hero_id": 20, "personaname": "d1", "kills": 2,
             "deaths": 0, "assists": 0, "account_id": 2},
        ]
    }
    heroes = {10: {"name": "Keeper", "icon_url": "/k.webp"},
              20: {"name": "Lion", "icon_url": "/l.webp"}}
    radiant = dota_matches._team_lineup(detail, True, heroes)
    dire = dota_matches._team_lineup(detail, False, heroes)
    assert [p["personaname"] for p in radiant] == ["r1"]
    assert [p["personaname"] for p in dire] == ["d1"]
    assert radiant[0]["hero_name"] == "Keeper"


def test_team_lineup_handles_missing_heroes():
    lineup = dota_matches._team_lineup({"players": []}, True, {})
    assert lineup == []


def test_render_match_contains_both_teams_and_score():
    html = dota_matches.render_match(SAMPLE)
    assert "Свет" in html and "Тьма" in html
    assert "32 : 18" in html
    assert "Победа Света" in html
    assert "39:05" in html
    # Bot players are linked, plain opponents are not.
    assert "tg://user?id=777" in html
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_render_match_dire_win_flips_winner_class():
    dire_win = dict(SAMPLE, radiant_win=False)
    html = dota_matches.render_match(dire_win)
    assert "Победа Тьмы" in html
    assert 'class="match-side dire winner"' in html


def test_render_match_marks_partial():
    html = dota_matches.render_match(dict(SAMPLE, partial=True, radiant=[], dire=[]))
    assert "match-card partial" in html
    assert "состав недоступен" in html


def test_render_page_empty_state():
    html = dota_matches.render_page([], limit=20)
    assert "Пока нет матчей Dota 2" in html
    assert "<html" in html and "</html>" in html


def test_render_page_highlights_current_limit():
    html = dota_matches.render_page([SAMPLE], limit=50)
    assert '<a class="on" href="/matches?limit=50">' in html
    assert '<a class="" href="/matches?limit=20">' in html


def test_render_page_embeds_telegram_webapp_sdk():
    html = dota_matches.render_page([SAMPLE], limit=20)
    # The SDK + viewport make the same page work as a Telegram Mini App.
    assert dota_matches.TELEGRAM_WEBAPP_JS in html
    assert "viewport-fit=cover" in html
    assert "themeChanged" in html
    assert "tg.openLink" in html
    # ...and a plain browser load stays untouched.
    assert 'class="miniapp"' not in html


def test_render_page_miniapp_mode_keeps_flag_in_links():
    html = dota_matches.render_page([SAMPLE], limit=50, miniapp=True)
    assert 'class="miniapp"' in html
    # Switching 20/50 must not fall back to the browser page.
    assert '<a class="on" href="/matches?limit=50&miniapp=1">' in html
    assert '<a class="" href="/matches?limit=20&miniapp=1">' in html


def test_public_base_url_prefers_webhook_host(monkeypatch):
    monkeypatch.delenv("MINIAPP_URL", raising=False)
    monkeypatch.delenv("PUBLIC_BASE_URL", raising=False)
    monkeypatch.setenv("WEBHOOK_URL", "https://fissure-bot.onrender.com/webhook")
    assert dota_matches.public_base_url() == "https://fissure-bot.onrender.com"
    assert dota_matches.miniapp_url() == "https://fissure-bot.onrender.com/matches?miniapp=1"
    assert dota_matches.miniapp_url(miniapp=False) == "https://fissure-bot.onrender.com/matches"


def test_public_base_url_overrides_and_fallbacks(monkeypatch):
    monkeypatch.setenv("WEBHOOK_URL", "https://fissure-bot.onrender.com/webhook")

    monkeypatch.setenv("MINIAPP_URL", "https://example.com/app/")
    assert dota_matches.public_base_url() == "https://example.com/app"

    monkeypatch.delenv("MINIAPP_URL")
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://custom.host")
    assert dota_matches.public_base_url() == "https://custom.host"

    # Telegram opens Web Apps over HTTPS only, so http:// hosts are ignored.
    monkeypatch.delenv("PUBLIC_BASE_URL")
    monkeypatch.setenv("WEBHOOK_URL", "http://localhost:8080/webhook")
    assert dota_matches.public_base_url() == dota_matches.DEFAULT_PUBLIC_BASE

    monkeypatch.delenv("WEBHOOK_URL")
    assert dota_matches.public_base_url() == dota_matches.DEFAULT_PUBLIC_BASE


def test_get_dota_matches_uses_index_and_partial_fallback(monkeypatch):
    monkeypatch.setattr(
        dota_matches,
        "_load_match_index",
        lambda limit: [
            {"match_id": 1, "start_time": 100, "radiant_win": True, "bot_players": 1},
            {"match_id": 2, "start_time": 50, "radiant_win": False, "bot_players": 1},
        ],
    )
    monkeypatch.setattr(dota_matches, "_hero_catalog", lambda: {})
    monkeypatch.setattr(dota_matches, "_bot_steam_index", lambda: {})

    async def fake_fetch(match_id):
        if match_id != 1:
            return None  # OpenDota failed for the second match
        return {
            "start_time": 100,
            "duration": 1000,
            "radiant_win": True,
            "game_mode": 2,
            "radiant_score": 10,
            "dire_score": 5,
            "players": [
                {"player_slot": 0, "hero_id": 1, "personaname": "a",
                 "kills": 1, "deaths": 0, "assists": 0, "account_id": 1},
            ],
        }

    monkeypatch.setattr(dota_matches, "_fetch_match_detail", fake_fetch)
    dota_matches._list_cache = None
    dota_matches._detail_cache.clear()

    result = asyncio.run(dota_matches.get_dota_matches(limit=20, force=True))

    assert [m["match_id"] for m in result] == [1, 2]
    assert result[0]["partial"] is False
    assert result[0]["radiant_score"] == 10
    assert result[0]["mode"] == "Random Draft"
    assert result[1]["partial"] is True


def test_hero_icon_uses_public_cdn_and_never_leaks_paths():
    heroes = {1: {"name": "Anti-Mage", "short_name": "antimage",
                  "icon_url": "D:\\bot\\assets\\heroes_webp\\antimage.webp"}}
    icon = dota_matches._hero_icon(1, heroes)
    assert icon == dota_matches.HERO_CDN_BASE + "/antimage.png"
    assert ":" not in icon.replace("https://", "").replace("http://", "")
    # Unknown hero -> no icon instead of a broken path.
    assert dota_matches._hero_icon(999, heroes) == ""
    assert dota_matches._hero_icon(1, {}) == ""


def test_hero_icon_maps_renamed_cdn_heroes():
    # Steam renames some heroes: necrophos -> necrolyte.
    heroes = {2: {"name": "Necrophos", "short_name": "necrophos"}}
    assert dota_matches._hero_icon(2, heroes).endswith("/necrolyte.png")


class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows
        self.executed = None

    def execute(self, sql, params=()):
        self.executed = (sql, params)

    def fetchall(self):
        return self._rows

    def close(self):
        pass


class _FakeConn:
    def __init__(self, rows):
        self._cursor = _FakeCursor(rows)

    def cursor(self):
        return self._cursor


def test_read_all_opens_dedicated_sqlite_connection(tmp_path, monkeypatch):
    """SQLite-пул database.py не потокобезопасен, поэтому читаем своим соединением."""
    import sqlite3

    import database

    db = tmp_path / "read_all.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE t (a INTEGER, b TEXT)")
    con.executemany("INSERT INTO t VALUES (?, ?)", [(1, "x"), (2, "y")])
    con.commit()
    con.close()

    monkeypatch.setattr(database, "DATABASE_URL", "sqlite:///" + db.as_posix())

    pool_calls = []

    def pool_boom():
        pool_calls.append(1)
        raise AssertionError("пул database.py нельзя трогать из воркера для SQLite")

    monkeypatch.setattr(database, "get_connection", pool_boom)

    rows = dota_matches._read_all("SELECT a, b FROM t ORDER BY a")

    assert rows == [(1, "x"), (2, "y")]
    assert pool_calls == []


def test_read_all_uses_pool_for_postgres(monkeypatch):
    """Postgres-соединения потокобезопасны — общий пул сохраняется."""
    import database

    monkeypatch.setattr(database, "DATABASE_URL", "postgresql://user:pw@host:5432/db")
    conn = _FakeConn([(7,)])
    monkeypatch.setattr(database, "get_connection", lambda: conn)
    released = []
    monkeypatch.setattr(database, "release_connection", released.append)

    assert dota_matches._read_all("SELECT 7") == [(7,)]
    assert released == [conn]


def test_load_match_index_parses_positional_rows(monkeypatch):
    rows = [
        (333, 1700000000, 1, 2),
        (111, 1600000000, 0, 1),
        (222, 1700000000, 1, 1),
        (None, 0, 0, 1),  # skipped: no match_id
    ]
    seen = {}

    def fake_read_all(sql):
        seen["sql"] = sql
        return rows

    monkeypatch.setattr(dota_matches, "_read_all", fake_read_all)

    out = dota_matches._load_match_index(limit=10)

    assert [m["match_id"] for m in out] == [333, 222, 111]
    assert out[0]["radiant_win"] is True
    assert out[0]["bot_players"] == 2
    assert out[2]["radiant_win"] is False
    # Row order is re-sorted newest-first even if the DB hands them back shuffled.
    assert out[1]["start_time"] == 1700000000
    assert "public_player_matches" in seen["sql"]


def test_load_match_index_respects_limit(monkeypatch):
    rows = [(i, 1000 + i, 1, 1) for i in range(30)]
    monkeypatch.setattr(dota_matches, "_read_all", lambda sql: rows)

    out = dota_matches._load_match_index(limit=5)

    assert len(out) == 5
    assert [m["match_id"] for m in out] == [29, 28, 27, 26, 25]


def test_load_match_index_survives_db_failure(monkeypatch):
    def boom(sql):
        raise RuntimeError("db down")

    monkeypatch.setattr(dota_matches, "_read_all", boom)
    assert dota_matches._load_match_index(limit=5) == []


def test_linked_steam_ids_reads_users(monkeypatch):
    captured = {}

    def fake_read_all(sql, params=()):
        captured["sql"] = sql
        captured["params"] = params
        return [(111,), (222,)]

    monkeypatch.setattr(dota_matches, "_read_all", fake_read_all)

    assert dota_matches._linked_steam_ids(5) == [111, 222]
    assert captured["params"] == (5,)
    assert "steam_id" in captured["sql"]


def test_linked_steam_ids_survives_db_error(monkeypatch):
    def boom(sql, params=()):
        raise RuntimeError("db down")

    monkeypatch.setattr(dota_matches, "_read_all", boom)
    assert dota_matches._linked_steam_ids(5) == []


def test_linked_steam_ids_falls_back_when_sort_columns_missing(monkeypatch):
    seen = []

    def fake_read_all(sql, params=()):
        seen.append(sql)
        if "week_games" in sql:
            raise RuntimeError("no such column: week_games")
        return [(111,)]

    monkeypatch.setattr(dota_matches, "_read_all", fake_read_all)

    assert dota_matches._linked_steam_ids(5) == [111]
    assert len(seen) == 2


def test_player_fallback_index_merges_duplicates(monkeypatch):
    import dota_mmr

    monkeypatch.setattr(dota_matches, "_linked_steam_ids", lambda limit: [1, 2])

    async def fake_matches(steam_id, limit):
        if steam_id == 1:
            return [
                {"match_id": 100, "start_time": 500, "radiant_win": True},
                {"match_id": 200, "start_time": 400, "radiant_win": False},
            ]
        # Same game as player 1 (both linked) plus a newer one.
        return [
            {"match_id": 100, "start_time": 500, "radiant_win": True},
            {"match_id": 300, "start_time": 900, "radiant_win": True},
        ]

    monkeypatch.setattr(dota_mmr, "get_recent_matches_async", fake_matches)

    index = asyncio.run(dota_matches._index_from_linked_players(10))

    assert [m["match_id"] for m in index] == [300, 100, 200]
    assert index[1]["bot_players"] == 2


def test_get_dota_matches_falls_back_when_db_index_empty(monkeypatch):
    monkeypatch.setattr(dota_matches, "_load_match_index", lambda limit: [])

    async def fake_fallback(limit):
        return [{"match_id": 7, "start_time": 10, "radiant_win": True, "bot_players": 1}]

    monkeypatch.setattr(dota_matches, "_index_from_linked_players", fake_fallback)
    monkeypatch.setattr(dota_matches, "_hero_catalog", lambda: {})
    monkeypatch.setattr(dota_matches, "_bot_steam_index", lambda: {})

    async def fake_detail(match_id):
        return {
            "start_time": 10,
            "duration": 900,
            "radiant_win": True,
            "game_mode": 2,
            "radiant_score": 20,
            "dire_score": 10,
            "players": [],
        }

    monkeypatch.setattr(dota_matches, "_fetch_match_detail", fake_detail)
    dota_matches._list_cache = None
    dota_matches._detail_cache.clear()

    result = asyncio.run(dota_matches.get_dota_matches(limit=5, force=True))

    assert [m["match_id"] for m in result] == [7]
    assert result[0]["bot_players"] == 1


# --- Player game list (Dota 2 style rows) ---


def _patch_game_sources(monkeypatch, matches_by_steam):
    """Wire get_player_games to deterministic OpenDota answers."""
    import dota_mmr

    monkeypatch.setattr(
        dota_matches, "_linked_steam_ids", lambda limit: list(matches_by_steam)
    )
    monkeypatch.setattr(
        dota_matches,
        "_hero_catalog",
        lambda: {1: {"name": "Anti-Mage", "short_name": "antimage"}},
    )
    monkeypatch.setattr(
        dota_matches,
        "_bot_steam_index",
        lambda: {111: {"telegram_id": 777, "username": "zeus"}},
    )

    async def fake_matches(steam_id, limit):
        return matches_by_steam[steam_id]

    monkeypatch.setattr(dota_mmr, "get_recent_matches_async", fake_matches)


def test_player_games_win_depends_on_player_slot(monkeypatch):
    _patch_game_sources(
        monkeypatch,
        {
            111: [
                # Radiant player in a won match -> win.
                {"match_id": 1, "start_time": 300, "duration": 1800,
                 "player_slot": 0, "hero_id": 1, "radiant_win": True,
                 "personaname": "ZeusFan", "game_mode": 2},
                # Dire player in the same won match -> loss.
                {"match_id": 2, "start_time": 200, "duration": 1800,
                 "player_slot": 128, "hero_id": 1, "radiant_win": True,
                 "personaname": "ZeusFan", "game_mode": 2},
                # Dire player in a lost match -> win.
                {"match_id": 3, "start_time": 100, "duration": 900,
                 "player_slot": 128, "hero_id": 1, "radiant_win": False,
                 "personaname": "ZeusFan", "game_mode": 2},
            ]
        },
    )

    games = asyncio.run(dota_matches.get_player_games(limit=10))

    assert [g["match_id"] for g in games] == [1, 2, 3]  # newest first
    assert [g["win"] for g in games] == [True, False, True]
    assert games[0]["hero_name"] == "Anti-Mage"
    assert games[0]["hero_icon"].endswith("antimage.png")
    assert games[0]["telegram_id"] == 777
    assert games[0]["bot_username"] == "zeus"
    assert games[0]["mode"] == "Random Draft"  # game_mode 2


def test_player_games_skips_duplicates_and_missing_fields(monkeypatch):
    _patch_game_sources(
        monkeypatch,
        {
            111: [
                {"match_id": 10, "start_time": 50, "player_slot": 0,
                 "radiant_win": True, "personaname": "ZeusFan"},
                # OpenDota sometimes repeats the same game for one player.
                {"match_id": 10, "start_time": 50, "player_slot": 0,
                 "radiant_win": True, "personaname": "ZeusFan"},
                {"start_time": 40, "player_slot": 0, "radiant_win": True},
            ]
        },
    )

    games = asyncio.run(dota_matches.get_player_games(limit=10))

    assert len(games) == 1
    assert games[0]["match_id"] == 10
    assert games[0]["duration"] == 0
    assert games[0]["hero_name"] == "—"


def test_player_games_survives_player_failure_and_empty_db(monkeypatch):
    import dota_mmr

    monkeypatch.setattr(dota_matches, "_linked_steam_ids", lambda limit: [111, 222])
    monkeypatch.setattr(dota_matches, "_hero_catalog", lambda: {})
    monkeypatch.setattr(dota_matches, "_bot_steam_index", lambda: {})

    async def fake_matches(steam_id, limit):
        if steam_id == 111:
            raise RuntimeError("opendota 500")
        return [{"match_id": 5, "start_time": 1, "player_slot": 0,
                 "radiant_win": True, "personaname": "Other"}]

    monkeypatch.setattr(dota_mmr, "get_recent_matches_async", fake_matches)

    games = asyncio.run(dota_matches.get_player_games(limit=10))
    assert [g["match_id"] for g in games] == [5]

    monkeypatch.setattr(dota_matches, "_linked_steam_ids", lambda limit: [])
    assert asyncio.run(dota_matches.get_player_games(limit=10)) == []

def test_render_games_page_has_dota_style_columns():
    games = [
        {
            "match_id": 8123456789,
            "start_time": 1700000000,
            "duration": 2345,
            "mode": "Ranked",
            "win": True,
            "hero_id": 1,
            "hero_name": "Anti-Mage",
            "hero_icon": "/am.webp",
            "personaname": "ZeusFan",
            "steam_id": 111,
            "telegram_id": 777,
            "bot_username": "zeus",
        },
        {
            "match_id": 5,
            "start_time": 1699990000,
            "duration": 0,
            "mode": "Ranked",
            "win": False,
            "hero_id": 2,
            "hero_name": "<script>alert(1)</script>",
            "hero_icon": "",
            "personaname": "Rival",
            "steam_id": 222,
            "telegram_id": None,
            "bot_username": None,
        },
    ]

    html = dota_matches.render_games_page(games, limit=10, miniapp=True)

    assert 'class="miniapp"' in html
    # Результат — буква W/L в компактном квадрате, слово ушло в подсказку.
    assert 'class="g-res" title="Победа" aria-label="Победа">W</span>' in html
    assert ('class="g-res" title="Поражение" aria-label="Поражение">L</span>'
            in html)
    # Ник открывает профиль через data-атрибут + обработчик клика:
    # вложенная <a> внутри <a> невалидна, поэтому ссылки в href нет.
    assert 'data-tg="777"' in html
    assert "tg://user?id=" in html
    assert "15.11" in html  # date column (Europe/Moscow), compact format
    assert "39:05" in html  # duration column
    assert "—" in html  # zero duration
    assert "dotabuff.com/matches/8123456789" in html
    assert "zeus · 1/1" in html  # per-player filter chip
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_render_game_card_in_cup_style():
    """Карточка игры: аватар, герой, ник, KDA — в оформлении кубка."""
    game = {
        "match_id": 42, "start_time": 100, "duration": 60, "win": True,
        "hero_id": 8, "hero_name": "Juggernaut", "hero_icon": "http://h/jugg.png",
        "personaname": "Wawashik", "bot_username": "Wawashik",
        "kills": 15, "deaths": 1, "assists": 8,
        "steam_id": 1, "telegram_id": 777, "avatar": "http://a/ava.jpg",
    }
    html = dota_matches.render_games_page([game], limit=5)
    row = dota_matches.render_game(game)

    assert 'class="g-face" src="http://a/ava.jpg"' in html   # аватар
    assert 'class="g-hero" src="http://h/jugg.png"' in html   # иконка героя
    assert "<b>15</b> / 1 / 8" in html                        # KDA
    assert 'class="g-card win"' in row                        # победа
    # Слово «Победа» больше не растягивает строку: только буква W.
    assert 'class="g-res" title="Победа" aria-label="Победа">W</span>' in row
    assert "Поражение" not in row
    # Строка больше не ссылка: клик открывает панель с «Пати» и «ДотаБаф».
    assert "<a" not in row
    assert 'data-act="party"' in row and 'data-act="dota"' in row
    assert "dotabuff.com/matches/42" in row
    assert "t.me/share/url" in row
    assert 'data-tg="777"' in row                             # переход в профиль
    assert "g-items" not in row                               # предметов нет


def test_party_button_signals_the_bot_to_run_the_existing_matcher():
    """Кнопка «Пати» зовёт готовый подбор, а не пишет своё приглашение.

    Окно «Поделиться» Telegram отправляло приглашение в диалог контакта,
    минуя чат, в котором все играют. Теперь кнопка отправляет Mini App-сигнал,
    и бот запускает party_for_user — тот же подбор, что у команды /party.
    """
    game = {
        "match_id": 42, "start_time": 100, "duration": 60, "win": True,
        "hero_id": 8, "hero_name": "Juggernaut", "hero_icon": "",
        "personaname": "Wawashik", "bot_username": "Wawashik",
        "kills": 1, "deaths": 0, "assists": 1,
        "steam_id": 1, "telegram_id": 777,
    }
    row = dota_matches.render_game(game)
    assert 'data-party="1"' in row
    # Ссылка на «Поделиться» осталась запасным путём для обычного браузера.
    assert 'data-party-share="' in row and "t.me/share/url" in row
    # Сигнал уходит в бот, а не текстом команды: /party не должен вклиниться
    # в разбор аргументов существующей команды party.py.
    assert "/party" not in row


def test_party_button_posts_to_the_api_not_to_a_chat_dialog():
    """Кнопка «Пати» шлёт HTTP-запрос, а не открывает «Поделиться».

    Окно «Поделиться» Telegram отправляло приглашение в диалог контакта,
    минуя чат, в котором все играют.
    """
    game = {
        "match_id": 42, "start_time": 100, "duration": 60, "win": True,
        "hero_id": 8, "hero_name": "Juggernaut", "hero_icon": "",
        "personaname": "Wawashik", "bot_username": "Wawashik",
        "kills": 1, "deaths": 0, "assists": 1,
        "steam_id": 1, "telegram_id": 777,
    }
    row = dota_matches.render_game(game)
    assert 'data-party="1"' in row
    # Ссылка на «Поделиться» осталась запасным путём для обычного браузера.
    assert 'data-party-share="' in row and "t.me/share/url" in row
    # Никакой команды /party в разметке: она живёт в party.py.
    assert "/party" not in row


def test_party_button_uses_the_api_and_not_senddata():
    """sendData здесь не работает — страница открыта инлайн-кнопкой.

    Telegram.WebApp.sendData работает только при запуске Mini App с кнопки
    клавиатуры. Матчи открывают инлайн-кнопкой web_app=, поэтому сигнал
    молча терялся и в чат ничего не приходило. Страница шлёт HTTP-запрос
    с initData вместо sendData.
    """
    assert ".sendData(" not in dota_matches.GAME_ACTS_JS
    assert "/api/party" in dota_matches.GAME_ACTS_JS
    assert "initData" in dota_matches.GAME_ACTS_JS


def test_party_button_invites_the_owner_of_the_card():
    """Кнопка зовёт игрока этой карточки, а не запускает общий подбор.

    Владелец матча известен странице, поэтому вместо списка из восьми
    ников в чат уходит адресное приглашение.
    """
    game = {
        "match_id": 42, "start_time": 100, "duration": 60, "win": True,
        "hero_id": 8, "hero_name": "Juggernaut", "hero_icon": "",
        "personaname": "Wawashik", "bot_username": "Wawashik",
        "kills": 1, "deaths": 0, "assists": 1, "steam_id": 1,
    }
    row = dota_matches.render_game(dict(game, telegram_id=4242))
    assert 'data-party-tg="4242"' in row
    # Страница шлёт id игрока вместе с initData.
    assert "tg: parseInt(card.dataset.partyTg, 10) || 0" in dota_matches.GAME_ACTS_JS
    # Запись без игрока остаётся с пустым id — тогда бот откатится на подбор.
    assert 'data-party-tg="0"' in dota_matches.render_game(game)


def test_party_endpoint_invites_the_named_player():
    """Эндпоинт зовёт указанного игрока, а подбор оставляет запасным путём."""
    import inspect

    import main as main_module

    source = inspect.getsource(main_module.party_api_handler)
    assert "invite_to_party" in source
    assert 'payload or {}).get("tg")' in source
    # Себя пригласить нельзя, и неизвестный игрок не должен ломать кнопку.
    assert "target_tg != tg_id" in source
    assert "party_for_user" in source


def test_invite_message_asks_the_player_by_name():
    """Текст приглашения адресный: игрок, пригласивший и его ранг с WR."""
    import asyncio
    from types import SimpleNamespace

    import party

    sent = {}

    class Bot:
        async def send_message(self, chat_id, text, parse_mode=None, **kwargs):
            sent["chat_id"] = chat_id
            sent["text"] = text
            return SimpleNamespace(message_id=1)

    context = SimpleNamespace(bot=Bot())
    inviter = {"telegram_id": 1, "username": "Stilevo", "rank_tier": 20,
               "week_games": 10, "week_wins": 4}
    target = {"telegram_id": 2, "username": "nasteni4", "rank_tier": 0,
              "week_games": 0, "week_wins": 0}

    asyncio.run(party.invite_to_party(-100123, inviter, target, context))

    assert sent["chat_id"] == -100123
    assert "Готов к игре?" in sent["text"]
    assert "приглашает тебя в пати!" in sent["text"]
    assert "nasteni4" in sent["text"] and "Stilevo" in sent["text"]
    assert "WR: 40% за неделю." in sent["text"]
    # Без игр за неделю процент выдумывать нельзя.
    sent.clear()
    asyncio.run(party.invite_to_party(
        -100123,
        {"telegram_id": 1, "username": "a", "rank_tier": 0, "week_games": 0},
        target, context,
    ))
    assert "WR: 0%" not in sent["text"]
    assert "Нет игр за неделю." in sent["text"]


def test_party_endpoint_validates_init_data():
    """Эндпоинт проверяет подпись initData и берёт официальный чат."""
    import inspect

    import main as main_module

    source = inspect.getsource(main_module.party_api_handler)
    assert "_validate_telegram_init_data" in source
    # Без валидной подписи эндпоинт не вызывает подбор.
    assert "unauthorized" in source
    assert "party_for_user" in source
    assert "digest_chat_id" in source


def test_init_data_signature_check_rejects_forged_data():
    """Подпись сверяется по алгоритму Telegram, подделка не проходит."""
    import main as main_module

    assert main_module._validate_telegram_init_data("", "token") is None
    assert main_module._validate_telegram_init_data("hash=abc", "") is None
    # Подпись из правильных полей, но чужой хеш.
    assert main_module._validate_telegram_init_data(
        "user=%7B%22id%22%3A1%7D&hash=deadbeef", "123:ABC",
    ) is None


def test_dotabuff_button_leads_to_the_player_not_the_match():
    """По кнопке ищут историю человека, а не конкретный матч."""
    game = {
        "match_id": 42, "start_time": 100, "duration": 60, "win": True,
        "hero_id": 8, "hero_name": "AM", "hero_icon": "",
        "personaname": "p", "bot_username": "p",
        "kills": 1, "deaths": 0, "assists": 2,
        "steam_id": 1, "telegram_id": 777, "account_id": 999888777,
    }
    row = dota_matches.render_game(game)
    assert 'data-dota="https://www.dotabuff.com/players/999888777"' in row
    # Подпись латиницей — как в самом Dotabuff.
    assert "Dotabuff</span>" in row and "ДотаБаф" not in row

    no_account = dict(game, account_id=None)
    # Без account_id остаётся матч, а не пустая ссылка на профиль.
    assert "dotabuff.com/matches/42" in dota_matches.render_game(no_account)


def test_top_ranks_tab_is_ordered_like_the_top_mmr_page():
    """Порядок вкладки «Топ рангов» повторяет ORDER BY страницы топа.

    Раньше mmr_sort_key начинал с ранга, а get_dota_week_top — со статистики,
    из-за чего одна и та же таблица показывалась в боте и на странице
    в разном порядке. Сверяем оба ключа на одной и той же выборке.
    """
    high_tier_no_games = {"username": "a", "steam_nickname": "a", "mmr": 9000,
                          "rank_tier": 80, "week_games": 0, "week_wins": 0}
    # Ранг выше, а результат хуже: именно такие игроки различают «сначала
    # ранг» и «сначала статистика». На странице топа такой игрок ниже.
    lucky_high_tier = {"username": "b", "steam_nickname": "b", "mmr": 1000,
                       "rank_tier": 75, "week_games": 10, "week_wins": 4}
    strong_active = {"username": "c", "steam_nickname": "c", "mmr": 2000,
                     "rank_tier": 20, "week_games": 10, "week_wins": 10}

    ordered = sorted([high_tier_no_games, lucky_high_tier, strong_active],
                     key=dota_matches.mmr_sort_key)
    # Активные игроки выше безыгравших, даже с высшим рангом.
    assert [p["username"] for p in ordered] == ["c", "b", "a"]
    # Внутри активных главная метрика — разница побед, а не ранг: у b ранг
    # выше, но 4W/6L против 10W/0L, поэтому b ниже.
    assert dota_matches.mmr_sort_key(strong_active) < \
           dota_matches.mmr_sort_key(lucky_high_tier)
    html = dota_matches.render_games_page(
        [], limit=5, tab="mmr",
        mmr_players=[lucky_high_tier, strong_active, high_tier_no_games],
    )
    assert 'class="g-sort-b on" data-sort="stats"' in html


def test_render_game_without_avatar_falls_back_to_initial():
    """Без аватара показываем круг с первой буквой ника."""
    game = {
        "match_id": 43, "start_time": 100, "duration": 60, "win": False,
        "hero_id": 8, "hero_name": "AM", "hero_icon": "",
        "personaname": "seredin", "bot_username": "seredin",
        "kills": 0, "deaths": 0, "assists": 0,
        "steam_id": 1, "telegram_id": None, "avatar": None,
    }
    html = dota_matches.render_games_page([game], limit=5)
    assert 'class="g-face g-hero"' in html
    assert ">S<" in html
    assert 'title="Поражение" aria-label="Поражение">L</span>' in html
    assert "Поражение<" not in html          # слова в строке больше нет


def test_render_mmr_tab_matches_top_page():
    """Вкладка «Топ MMR» повторяет поля страницы топа: #, ранг, игрок, статистика."""
    players = [
        {"username": "low", "steam_nickname": "low", "mmr": 1000,
         "rank_tier": 30, "week_games": 4, "week_wins": 1},
        {"username": "high", "steam_nickname": "high", "mmr": 5000,
         "rank_tier": 80, "week_games": 10, "week_wins": 8},
        {"username": "idle", "steam_nickname": "idle", "mmr": 4000,
         "rank_tier": 60, "week_games": 0, "week_wins": 0},
    ]
    html = dota_matches.render_games_page([], limit=5, tab="mmr",
                                          mmr_players=players)

    # Подписи колонок уступили место общему ряду сортировки.
    for title in ("Сортировка", "Ранг", "Статистика"):
        assert title in html
    assert "Место" not in html            # пустая подпись-заглушка убрана
    assert "#" not in html.split("</style>", 1)[-1].split("</head>")[0]
    assert 'data-sort="name"' not in html            # по нику больше не сортируем
    assert "/images/ranks/" in html                  # раздаёт сам бот, не внешний хост
    # rank_tier=80 — Бессмертный, у него единственная локальная иконка rank_8_5.
    assert "rank_8_5.webp" in html and "rank_3_1.webp" in html
    assert "80%" in html and 'class="g-wr-fill"' in html
    assert "8W/2L" in html and 'class="g-wr-none"' in html
    assert html.index("high") < html.index("low") < html.index("idle")


def test_render_mmr_tab_shows_no_mmr_numbers():
    """В боте только ранги: числовой MMR не показываем нигде."""
    player = {"username": "a", "steam_nickname": "alpha", "mmr": 6123,
              "rank_tier": 75, "week_games": 8, "week_wins": 6}
    row = dota_matches.render_mmr_row(player, 1)
    html = dota_matches.render_games_page([], limit=5, tab="mmr",
                                          mmr_players=[player])

    assert "6123" not in row and "MMR" not in row
    assert "rank_7_5.webp" in row                # 75 = Божество 5 звёзд
    assert "Божество" not in row                  # иконка уже говорит сама
    assert "alpha" in row and "6W/2L" in row
    # Числа MMR нет и в самой странице вне блока стилей.
    body = html.split("</style>", 1)[-1]
    assert "6123" not in body and "MMR" not in body


def test_rank_tier_with_stars_is_named_correctly():
    """Номер ранга хранит звёзды: 75 — Божество, а не «Ранг 75»."""
    assert dota_matches._rank_icon(75) == "Божество"
    assert dota_matches._rank_icon(80) == "Бессмертный"
    assert dota_matches._rank_icon(30) == "Рыцарь"
    assert dota_matches._rank_icon(None) == "Без ранга"


def test_mmr_row_shows_avatar_and_sort_keys():
    """В топе есть аватар, иконка ранга и данные для сортировки."""
    player = {"username": "u", "steam_nickname": "Nick", "mmr": 1,
              "rank_tier": 60, "week_games": 10, "week_wins": 7,
              "avatar": "http://a/ava.jpg"}
    row = dota_matches.render_mmr_row(player, 1)

    assert 'class="g-face" src="http://a/ava.jpg"' in row   # аватар
    assert "rank_6_1.webp" in row                            # иконка ранга
    assert 'data-rank_tier="60"' in row                     # ключи сортировки
    assert 'data-name="nick"' in row
    assert 'data-games="10"' in row
    assert 'data-stats="4"' in row                           # 7W/3L = +4


def test_mmr_row_without_avatar_shows_placeholder():
    player = {"username": "u", "steam_nickname": "N", "mmr": 0,
              "rank_tier": 50, "week_games": 0, "week_wins": 0,
              "avatar": None}
    row = dota_matches.render_mmr_row(player, 4)
    assert 'class="g-face g-hero"' in row
    assert ">" in row


def test_game_row_shows_player_rank():
    """В строке игры видна иконка ранга игрока."""
    game = {
        "match_id": 7, "start_time": 100, "duration": 60, "win": True,
        "hero_id": 8, "hero_name": "AM", "hero_icon": "",
        "personaname": "p", "bot_username": "p",
        "kills": 1, "deaths": 0, "assists": 2,
        "steam_id": 1, "telegram_id": None, "rank_tier": 65,
    }
    row = dota_matches.render_game(game)
    assert "rank_6_5.webp" in row          # 65 = Титан 5 звёзд

    no_rank = dict(game, rank_tier=None)
    assert 'class="g-rank-img g-rank-blank"' in dota_matches.render_game(no_rank)


def test_rank_name_in_words_is_not_duplicated_next_to_the_icon():
    """Иконка ранга говорит о ранге сама — название под ником лишнее.

    Раньше в строке игры было «Титан · AM», а в топе «Божество» под ником,
    хотя иконка ранга уже стояла рядом в обоих местах.
    """
    game = {"match_id": 7, "start_time": 100, "duration": 60, "win": True,
            "hero_id": 8, "hero_name": "AM", "hero_icon": "",
            "personaname": "p", "bot_username": "p",
            "kills": 1, "deaths": 0, "assists": 2,
            "steam_id": 1, "telegram_id": None, "rank_tier": 65}
    row = dota_matches.render_game(game)
    assert "Титан" not in row
    assert "Без ранга" not in row
    assert "g-heron" in row and ">AM</span>" in row   # остался только герой

    top_row = dota_matches.render_mmr_row(
        {"username": "p", "steam_nickname": "p", "rank_tier": 65}, 1,
    )
    assert "Титан" not in top_row
    assert "g-heron" not in top_row


def test_game_row_rank_looks_like_the_ranking_tab():
    """Ранг в истории подан так же, как в топе: та же иконка g-rank-img.

    Раньше здесь была отдельная «плашка», из-за чего вкладки выглядели
    по-разному; теперь обе используют один и тот же g-rank-img.
    """
    game = {"match_id": 7, "start_time": 100, "duration": 60, "win": True,
            "hero_id": 8, "hero_name": "AM", "hero_icon": "",
            "personaname": "p", "bot_username": "p",
            "kills": 1, "deaths": 0, "assists": 2,
            "steam_id": 1, "telegram_id": None, "rank_tier": 65}
    row = dota_matches.render_game(game)
    top_row = dota_matches.render_mmr_row({"username": "p", "steam_nickname": "p",
                                           "rank_tier": 65}, 1)

    assert 'class="g-rank-img" src=' in row          # та же иконка, что в топе
    assert "g-rank-mini" not in row               # отдельной плашки больше нет
    assert 'class="g-rank-img"' in top_row         # топ не тронут


def test_ranking_header_padding_matches_row():
    """Ряд сортировки стоит по тем же бокам, что и строки под ним."""
    players = [{"username": "a", "steam_nickname": "a", "mmr": 1,
                "rank_tier": 50, "week_games": 1, "week_wins": 1}]
    html = dota_matches.render_games_page([], limit=5, tab="mmr",
                                          mmr_players=players)
    css = html.split("</style>", 1)[0].replace("\n", "")
    head_pad = re.search(r"\.g-sort\{[^}]*padding:0 (\d+)px", css)
    # Именно строка топра: у строки роллов свой .g-line с другими
    # отступами, и раньше регулярка цеплялась к ней.
    row_pad = re.search(r"\.g-line\{display:flex;align-items:center;gap:10px;"
                        r"padding:7px (\d+)px", css)
    assert head_pad and row_pad
    assert head_pad.group(1) == row_pad.group(1)     # иначе колонки съедут


def test_sort_header_is_outlined_not_underlined():
    """Активный пункт списка обведен, а не подчёркнут."""
    css = dota_matches.GAMES_CSS.replace("\n", "")
    assert ".g-sort-b.on{" in css
    assert "background:rgba(232,180,92,.12)" in css
    assert ".g-sort-b.on{border-bottom" not in css
    # Стрелка — только у активной: у неактивных она пряталась через
    # opacity, из-за чего ряд получал разную ширину по вкладкам.
    assert ".g-sort-b.on .g-sort-ar{opacity:1}" in css
    assert ".g-sort-ar{" in css


def test_sort_control_is_a_collapsed_button_like_the_player_picker():
    """Сортировка свёрнута в одну кнопку и раскрывается по клику.

    Вариантов всего два-три, но лежали они рядом всегда и на телефоне
    съедали строку целиком. Теперь это тот же приём, что у выбора
    игрока: кнопка с текущим признаком и список внутри.
    """
    css = dota_matches.GAMES_CSS.replace("\n", "")
    assert ".g-sort-btn{" in css and ".g-sort-menu{display:none" in css
    assert ".g-sort.open .g-sort-menu{display:flex}" in css
    assert ".g-sort.open .g-sort-chev{transform:rotate(180deg)}" in css
    assert ".g-sort.open .g-sort-btn{" in css
    # Ряд с кнопками больше не рисуется — вместо него одна кнопка.
    assert ".g-sort{display:flex" not in css
    # Ни одного правила, которое ставит кнопку в колонку сетки.
    assert "justify-self:end" not in css
    assert ".g-card.g-mmr .g-sort-b{" not in css
    # Старого общего заголовка больше нет — он и был источником наездов.
    assert ".g-mmr-head" not in css


def test_sort_menu_shows_the_active_option_and_the_script_opens_it():
    """На кнопке подписан текущий признак, список открыт по клику."""
    html = dota_matches.render_games_page([], tab="mmr", mmr_players=[
        {"username": "a", "steam_nickname": "a", "mmr": 0,
         "rank_tier": 50, "week_games": 1, "week_wins": 1},
    ])
    assert '<div class="g-sort" data-rows=".g-card.g-mmr">' in html
    assert '<button type="button" class="g-sort-btn" aria-expanded="false">' in html
    # Активный вариант отмечен в списке и подписан на кнопке.
    assert '<button type="button" class="g-sort-b on" data-sort="stats"' in html
    assert '<span class="g-sort-t">Статистика ↓</span>' in html
    # Скрипт умеет открывать список и переносит выбор на кнопку.
    assert "setOpen(!bar.classList.contains('open'))" in html
    assert "cap.textContent" in html
    assert "setOpen(false);" in html


def test_mmr_tab_headers_are_sortable():
    """Кнопки топра кликабельны, как на странице топа."""
    players = [{"username": "a", "steam_nickname": "a", "mmr": 0,
                "rank_tier": 50, "week_games": 1, "week_wins": 1}]
    html = dota_matches.render_games_page([], limit=5, tab="mmr",
                                          mmr_players=players)
    assert 'data-sort="rank_tier"' in html
    # По нику не сортируем: в топе важнее ранг и результат.
    assert 'data-sort="name"' not in html
    assert 'data-sort="stats"' in html
    assert 'class="g-sort"' in html
    # Скрипт сортировки подключён.
    assert "data-sort" in html and "g-card.g-mmr" in html


def test_render_mmr_tab_accepts_ranks_alias():
    """Вкладка открывается и по tab=ranks, и по прежнему tab=mmr."""
    players = [{"username": "a", "steam_nickname": "a", "mmr": 1,
                "rank_tier": 50, "week_games": 1, "week_wins": 1}]
    html = dota_matches.render_games_page([], limit=5, tab="ranks",
                                          mmr_players=players)
    assert 'class="g-tab on" href="/matches?tab=ranks"' in html
    assert "Рейтинг пока пуст." not in html        # это games-пустышка
    assert "1W/0L" in html


def test_render_mmr_tab_sorts_no_games_last():
    """Игрок без игр за неделю всегда в конце топа."""
    players = [
        {"username": "a", "steam_nickname": "a", "mmr": 9000, "rank_tier": 80,
         "week_games": 0, "week_wins": 0},
        {"username": "b", "steam_nickname": "b", "mmr": 1000, "rank_tier": 20,
         "week_games": 3, "week_wins": 1},
    ]
    html = dota_matches.render_games_page([], limit=5, tab="mmr",
                                          mmr_players=players)
    assert html.index(">b<") < html.index(">a<")
def test_render_games_page_filters_by_player():
    games = [
        {"match_id": 1, "start_time": 10, "duration": 60, "mode": "Ranked", "win": True,
         "hero_id": 1, "hero_name": "AM", "hero_icon": "", "personaname": "A",
         "steam_id": 1, "telegram_id": None, "bot_username": "aaa"},
        {"match_id": 2, "start_time": 9, "duration": 60, "mode": "Ranked", "win": False,
         "hero_id": 1, "hero_name": "AM", "hero_icon": "", "personaname": "B",
         "steam_id": 2, "telegram_id": None, "bot_username": "bbb"},
    ]

    html = dota_matches.render_games_page(games, limit=10, player="aaa")
    assert html.count('class="g-card') == 1
    assert "matches/1" in html and "matches/2" not in html

    empty = dota_matches.render_games_page([], limit=10)
    assert "Пока нет игр" in empty


def test_mobile_text_is_never_tiny():
    """На телефоне ничего не должно быть мельче 11px.

    Ужимание подписей до 8-9px делало страницу нечитаемой.
    """
    css = dota_matches.GAMES_CSS.replace("\n", "")
    assert "@media(max-width:640px){" in css
    mobile = css.split("@media(max-width:640px){", 1)[1]
    sizes = [float(x) for x in re.findall(r"font-size:([0-9.]+)px", mobile)]
    assert sizes, "в мобильных правилах не найдено ни одного font-size"
    too_small = [s for s in sizes if s < 11]
    assert not too_small, f"слишком мелкий шрифт на мобильном: {too_small}"
    # Основные элементы заметно крупнее, а не 8-10px.
    who = re.search(r"\.g-who\{font-size:([0-9.]+)px\}", mobile)
    tab = re.search(r"\.g-tab\{[^}]*font-size:([0-9.]+)px", mobile)
    assert who and float(who.group(1)) >= 14
    assert tab and float(tab.group(1)) >= 12


def test_upstream_outage_is_logged_once():
    """Падение OpenDota не забивает лог одинаковыми строками."""
    import dota_mmr

    assert hasattr(dota_mmr, "_log_upstream_outage")
    assert dota_mmr.OUTAGE_LOG_EVERY >= 60, "пауза между сообщениями слишком короткая"
    # На 521/522 ставится общая пауза вместо ретрая каждого запроса.
    src = (PROJECT_ROOT / "dota_mmr.py").read_text(encoding="utf-8")
    assert "resp.status in (521, 522)" in src
    assert "set_opendota_rate_limited(120)" in src


def test_topmmr_caption_offers_the_full_list():
    """/topmmr ведёт кнопкой на страницу приложения, а не ссылкой в тексте.

    Обычный <a href> открывает встроенный браузер Telegram, поэтому
    приложение цепляется кнопкой под сообщением.
    """
    import main

    src = (PROJECT_ROOT / "main.py").read_text(encoding="utf-8")
    assert "seredin999.onrender.com/top-mmr" not in src   # ссылка на сайт убрана
    assert "Весь список" in src
    # Отдельный хелпер: кнопка должна открывать вкладку рангов, а не историю.
    assert dota_matches.ranks_url().endswith("tab=ranks&miniapp=1")
    assert dota_matches.ranks_url() != dota_matches.miniapp_url()

    button = main.app_link_markup(
        [("📋 Весь список", dota_matches.ranks_url())], "private"
    ).inline_keyboard[0][0]
    assert button.text == "📋 Весь список"
    assert button.web_app.url == dota_matches.ranks_url()


def test_top_fissure_opens_the_roll_history_in_the_app():
    """Топ фиссур ведёт кнопкой «ИСТОРИЯ РОЛЛОВ», а не ссылкой на сайт."""
    import main

    src = (PROJECT_ROOT / "main.py").read_text(encoding="utf-8")
    assert "seredin999.onrender.com/fissure-logs" not in src
    assert "ИСТОРИЯ РОЛЛОВ" in src
    assert dota_matches.rolls_url().endswith("tab=rolls&miniapp=1")
    assert dota_matches.rolls_url() != dota_matches.miniapp_url()

    button = main.app_link_markup(
        [("📜 ИСТОРИЯ РОЛЛОВ", dota_matches.rolls_url())], "private"
    ).inline_keyboard[0][0]
    assert button.web_app.url == dota_matches.rolls_url()


def test_app_buttons_fall_back_to_links_in_groups():
    """В группе web_app-кнопку Telegram не примет — там нужна обычная ссылка.

    Топы зовут в групповом чате, поэтому кнопка под ними обязана быть
    url-кнопкой: иначе в группе её просто не будет.
    """
    import main

    for chat_type in ("group", "supergroup", "channel"):
        button = main.app_link_markup(
            [("📋 Весь список", dota_matches.ranks_url())], chat_type
        ).inline_keyboard[0][0]
        assert button.web_app is None
        assert button.url == dota_matches.ranks_url()
    # В личке — наоборот, полноценная кнопка приложения.
    private = main.app_link_markup(
        [("📋 Весь список", dota_matches.ranks_url())], "private"
    ).inline_keyboard[0][0]
    assert private.url is None and private.web_app is not None


def test_digest_post_has_the_match_history_button_instead_of_a_site_link():
    """Под постом дайджеста — кнопка на историю матчей, а ссылка в тексте убрана.

    Дайджест закрепляется в группе, где web_app запрещён, поэтому кнопка
    всегда url: страница открывается во встроенном браузере. Кнопка ведёт
    на историю матчей, а не на историю роллов: роллы и так видны в чате.
    """
    import digest

    src = (PROJECT_ROOT / "digest.py").read_text(encoding="utf-8")
    assert "seredin999.onrender.com/fissure-bot" not in src
    assert "Подробнее на сайте" not in src

    button = digest.digest_keyboard().inline_keyboard[0][0]
    assert button.text == "📜 ИСТОРИЯ МАТЧЕЙ"
    assert button.web_app is None
    assert button.url == dota_matches.miniapp_url()
    assert button.url != dota_matches.rolls_url()


def test_every_digest_edit_reattaches_the_match_history_button():
    """Правка дайджеста не должна снимать кнопку.

    Telegram удаляет инлайн-клавиатуру у сообщения, которое редактируют без
    reply_markup. Значит дайджест, созданный в 9:00 с кнопкой, терял её на
    первом же обновлении текста и до следующей ротации висел без неё.
    Проверяем структурно: каждый вызов edit_message_* обязан нести
    reply_markup=digest_keyboard().
    """
    import ast

    source = (PROJECT_ROOT / "digest.py").read_text(encoding="utf-8")
    edits = [
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in ("edit_message_text", "edit_message_caption")
    ]
    assert edits, "digest.py должен редактировать сообщение дайджеста"

    without_button = []
    for call in edits:
        has_button = any(
            kw.arg == "reply_markup"
            and isinstance(kw.value, ast.Call)
            and isinstance(kw.value.func, ast.Name)
            and kw.value.func.id == "digest_keyboard"
            for kw in call.keywords
        )
        if not has_button:
            without_button.append(call.lineno)

    assert not without_button, (
        "эти правки дайджеста снимают кнопку ИСТОРИЯ МАТЧЕЙ: "
        f"digest.py:{without_button}"
    )


def test_mmr_row_links_to_the_player_game_history():
    """Под героем в топе рангов — кнопка на историю игр этого игрока."""
    player = {"username": "wawa", "steam_nickname": "ZeusFan",
              "week_games": 10, "week_wins": 7, "mmr": 5000,
              "rank_tier": 60, "wins": 12, "losses": 8}
    href = dota_matches.games_href_for(player)
    # Ключ вкладки игр — bot_username, а он равен username, иначе steam_nickname.
    assert "player=wawa" in href and "miniapp=1" in href
    assert dota_matches.games_href_for({"steam_nickname": "ZeusFan"}).count("player=ZeusFan") == 1
    assert dota_matches.games_href_for({}) == ""      # без ключа кнопки нет

    row = dota_matches.render_mmr_row(player, 1, games_href=href)
    assert '<a class="g-igames" ' in row and f'href="{href}"' in row
    # Под героем, внутри блока с ником, а не отдельной строкой.
    assert row.index("g-igames") > row.index("g-who")
    assert row.index("g-igames") < row.index("g-wr")
    # Без ссылки строка остаётся без кнопки.
    assert "g-igames" not in dota_matches.render_mmr_row(player, 2)


def test_rolls_tab_sorts_by_recency_first():
    """Лог роллов открывается по времени: сверху последние.

    Первым вариантом раньше стоял «Игрок», и список сразу переставлялся по
    алфавиту — свежие роллы оказывались внизу и терялись.
    """
    rolls = [{"ts": 1700000000, "user_id": 1, "username": "wawa",
              "growth": 12.5, "fissure": 340.0, "cascade": 3},
             {"ts": 1700000300, "user_id": 2, "username": "frost",
              "growth": -4.0, "fissure": 120.0, "cascade": 1}]
    html = dota_matches.render_games_page([], tab="rolls", rolls=rolls)

    assert 'data-ts="1700000300"' in html and 'data-ts="1700000000"' in html
    assert '<button type="button" class="g-sort-b on" data-sort="ts" ' in html
    assert '<span class="g-sort-t">Последние ↑</span>' in html
    # Остальные признаки на месте — их просто выбирают вручную.
    for key in ("name", "growth", "fissure"):
        assert f'data-sort="{key}"' in html


def test_rolls_tab_is_a_third_tab():
    """Роллы — третья вкладка рядом с историей и топом рангов."""
    rolls = [{"ts": 1700000000, "user_id": 1, "username": "wawa",
              "growth": 12.5, "fissure": 340.0, "cascade": 3},
             {"ts": 1700000100, "user_id": 2, "username": "frost",
              "growth": -4.0, "fissure": 120.0, "cascade": 1}]
    html = dota_matches.render_games_page([], tab="rolls", rolls=rolls)
    body = html.split("</style>", 1)[-1]

    assert body.count('<a class="g-tab') == 3
    assert 'href="/matches?tab=rolls"' in body
    assert body.count("g-card g-roll") == 2
    assert "+12.5" in body and "-4" in body          # прирост и откат
    assert ">x3<" in body                            # метка каскада
    assert "Роллов пока нет" in dota_matches.render_games_page([], tab="rolls")
    # Роллы приходят из bot_utils, а не из OpenDota.
    src = (PROJECT_ROOT / "main.py").read_text(encoding="utf-8")
    assert "from bot_utils import get_recent_rolls" in src


def test_sort_js_has_no_literal_escape_and_opens_rows():
    """Регрессии сортировки и раскрытия строк.

    Стрелки писались как «\\u25BC» и попадали в страницу буквально,
    а обработчик клика по строке делал return вместо toggle(), поэтому
    панель «Пати» / «ДотаБаф» не появлялась.
    """
    sort_js = dota_matches.SORT_JS
    assert "\\u25BC" not in sort_js, "стрелка должна быть CSS-треугольником"
    assert "String.fromCharCode" not in sort_js, "укоды символов больше не нужны"
    # Клик должен ловиться только своим рядом сортировки.
    assert "bar.contains(b)" in sort_js
    # Один скрипт на обе вкладки: старых копий не осталось.
    assert not hasattr(dota_matches, "RANKS_SORT_JS")
    assert not hasattr(dota_matches, "ROLLS_SORT_JS")

    acts_js = dota_matches.GAME_ACTS_JS
    assert "if (!act) { toggle(); return; }" in acts_js, \
        "клик по строке обязан раскрывать карточку"


def test_js_constants_carry_no_script_tags_of_their_own():
    """Константы не должны приносить свои теги <script>.

    Страница оборачивает каждую из них в <script>…</script> сама, поэтому
    лишняя пара внутри давала вложенный тег: браузер закрывал блок на
    первой обёртке и весь JS страницы падал. Кнопки сортировки переставали
    нажиматься, а строки — раскрываться.
    """
    for name in ("TELEGRAM_INIT_JS", "GAME_ACTS_JS", "PICKER_JS", "SORT_JS"):
        src = getattr(dota_matches, name)
        assert "script>" not in src, f"{name} содержит тег script"

    players = [{"username": "a", "steam_nickname": "a", "mmr": 1,
                "rank_tier": 50, "week_games": 1, "week_wins": 1}]
    for tab in ("games", "mmr", "rolls"):
        html = dota_matches.render_games_page([], limit=5, tab=tab,
                                              mmr_players=players, miniapp=True)
        body = html.split("</style>", 1)[-1]
        assert body.count("<script") == body.count("</script>"), tab
        assert "<script><script" not in body, tab


def test_rolls_have_avatars_and_sorting():
    """В роллах есть аватар и те же кнопки сортировки, что и в топе."""
    rolls = [{"ts": 1700000000, "username": "wawa", "growth": 12.5,
              "fissure": 340.0, "cascade": 3, "avatar": "http://a/1.jpg"},
             {"ts": 1700000100, "username": "frost", "growth": -4.0,
              "fissure": 120.0, "cascade": 1, "avatar": None}]
    html = dota_matches.render_games_page([], tab="rolls", rolls=rolls)
    body = html.split("</style>", 1)[-1]

    assert 'class="g-face" src="http://a/1.jpg"' in body   # аватар из users
    assert "g-face g-hero" in body                        # заглушка без него
    assert 'data-sort="name"' in body
    assert 'data-sort="growth"' in body
    assert 'data-sort="fissure"' in body
    assert 'data-name="wawa"' in body and 'data-growth="12.5"' in body
    # Общий для вкладок ряд сортировки указывает на свои строки.
    assert 'class="g-sort" data-rows=".g-card.g-roll"' in body
    # Селектор строк берётся из data-rows, а не зашивается в скрипт.
    assert "bar.dataset.rows" in dota_matches.SORT_JS
    assert "document.querySelectorAll(sel)" in dota_matches.SORT_JS
    # Минусовой ролл читается как тревожный, а не зелёный.
    assert "g-gain neg" in body
    # Аватары подставляет обработчик: bot_utils их не хранит.
    src = (PROJECT_ROOT / "main.py").read_text(encoding="utf-8")
    assert "_attach_roll_avatars" in src


def test_rank_images_served_from_own_origin():
    """Картинки рангов раздаёт сам бот, а не лёгкий внешний хост.

    RANKS_BASE раньше указывал на seredin999.onrender.com, который отдаёт 503,
    и иконки пропадали из страницы. Путь стал относительным — браузер тянет его
    со своей же страницы, где aiohttp раздаёт /images/ranks/.
    """
    from dota_matches import RANKS_BASE, rank_image

    assert RANKS_BASE.startswith("/"), "путь должен быть относительным (свой origin)"
    assert "onrender.com" not in RANKS_BASE, "внешний мёртвый хост больше не используется"
    assert rank_image(34).startswith("/images/ranks/rank_")
    assert rank_image(85).endswith("rank_8_5.webp")   # Титан — только 5-я звезда
    assert rank_image(0).endswith("rank_1_1.webp")    # фолбэк без ранга


def test_non_roll_events_get_a_badge():
    """Рошан/Зевс/Техис на вкладке «Роллы» помечены, а не выглядят как роллы.

    Раньше event_type не выводился, и награда Рошана (+8), удар Зевса (+0) и
    урон Техиса (-55) читались как обычные приросты — отсюда «бред».
    """
    rolls = [
        {"ts": 1, "username": "a", "growth": 8.0, "fissure": 250.0,
         "cascade": 0, "event_type": "roshan"},
        {"ts": 2, "username": "b", "growth": 0.0, "fissure": 90.0,
         "cascade": 0, "event_type": "zeus"},
        {"ts": 3, "username": "c", "growth": -55.0, "fissure": 40.0,
         "cascade": 0, "event_type": "techies"},
    ]
    body = dota_matches.render_games_page(
        [], tab="rolls", rolls=rolls).split("</style>", 1)[-1]

    assert "⚔ Рошан" in body
    assert "⚡ Зевс" in body
    assert "💣 Техис" in body
    assert body.count('class="g-rc-ev"') == 3


def test_plain_roll_and_old_records_carry_no_event_badge():
    """Обычный ролл, мультикаст и старые записи без event_type — без метки."""
    rolls = [
        {"ts": 1, "username": "a", "growth": 7.0, "fissure": 200.0, "cascade": 1},
        {"ts": 2, "username": "b", "growth": 3.0, "fissure": 150.0,
         "cascade": 3, "event_type": "multicast"},
        {"ts": 3, "username": "c", "growth": -4.0, "fissure": 120.0,
         "cascade": 1, "event_type": "roll"},
    ]
    body = dota_matches.render_games_page(
        [], tab="rolls", rolls=rolls).split("</style>", 1)[-1]

    assert "g-rc-ev" not in body, "обычные роллы не должны получать метку события"
    assert ">x3<" in body, "каскад мультикаста по-прежнему виден"


def test_roll_column_header_calls_the_value_fissure_not_max():
    """Колонка показывает текущую фиссуру, а не максимум — подпись не врёт."""
    rolls = [{"ts": 1, "username": "a", "growth": 1.0, "fissure": 10.0, "cascade": 1}]
    html = dota_matches.render_games_page([], tab="rolls", rolls=rolls)
    assert 'data-sort="fissure"' in html
    assert "Фиссура" in html
    assert "Максимум" not in html


def test_ranking_header_has_no_empty_cells():
    """В ряду сортировки нет пустых заглушек, перехватывающих клики."""
    players = [{"username": "a", "steam_nickname": "a", "mmr": 1,
                "rank_tier": 50, "week_games": 2, "week_wins": 1}]
    html = dota_matches.render_games_page([], tab="mmr", mmr_players=players)
    head = re.search(r'<div class="g-sort"[^>]*>(.*?)</div>', html,
                     re.S).group(1)

    assert '<span class="g-hp"></span>' not in head
    assert '<button type="button"' in head          # кнопки, а не подписи
    assert head.count("data-sort=") == 2            # Ранг и Статистика
    assert 'data-sort="rank_tier"' in head
    # Подписи не в общей сетке с колонками — иначе снова наезжают.
    css = dota_matches.GAMES_CSS.replace("\n", "")
    assert ".g-sort-btn{" in css


def test_history_repairs_its_own_schema():
    """Страница сама добавляет недостающие колонки.

    ALTER жил только в MMR-джобе, который после деплоя ещё не успевал
    отработать, и каждый запрос в лог падал с «column m.duration does
    not exist».
    """
    import sqlite3

    from database import ensure_match_history_columns

    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE public_player_matches ("
        " match_id INTEGER UNIQUE, hero_id INTEGER, player_slot INTEGER,"
        " radiant_win INTEGER, start_time INTEGER, steam_id INTEGER)"
    )
    assert ensure_match_history_columns(conn, False) is True
    cols = {c[1] for c in conn.execute("PRAGMA table_info(public_player_matches)")}
    assert {"kills", "deaths", "assists", "duration"} <= cols
    # Повторный вызов ничего не меняет.
    assert ensure_match_history_columns(conn, False) is False
    conn.close()

    # Таблицы ещё нет — ждём джоб, но не падаем.
    fresh = sqlite3.connect(":memory:")
    assert ensure_match_history_columns(fresh, False) is False
    fresh.close()


def test_history_reads_from_the_shared_match_table():
    """История берётся из public_player_matches, а не из повторного OpenDota."""
    src = (PROJECT_ROOT / "database.py").read_text(encoding="utf-8")
    assert "def get_recent_player_matches" in src
    # Колонки KDA и длительности нужны и записываются джобом MMR.
    mmr = (PROJECT_ROOT / "dota_mmr.py").read_text(encoding="utf-8")
    for col in ("kills", "deaths", "assists", "duration"):
        # Postgres добавляет колонку явным ALTER, SQLite — в цикле.
        assert f"ADD COLUMN IF NOT EXISTS {col} INTEGER" in mmr, col
    assert 'for _col in ("kills", "deaths", "assists", "duration")' in mmr
    assert "kills, deaths, assists, duration" in mmr
    # Страница идёт в БД, но при старой схеме откатывается в сеть.
    dm = (PROJECT_ROOT / "dota_matches.py").read_text(encoding="utf-8")
    assert "get_recent_player_matches" in dm
    assert "return _decorate_games" in dm
    assert "get_recent_matches_async" in dm      # запасной путь сохранён


def test_history_falls_back_to_opendota_when_db_is_empty():
    """Пустая или старая таблица не оставляет страницу без игр."""
    import dota_mmr
    from dota_matches import get_player_games

    saved_api = dota_mmr.get_recent_matches_async
    saved_cache = dict(dota_mmr._user_matches_cache)
    dota_mmr._user_matches_cache.clear()

    async def fake(sid, limit):
        return [{"match_id": 5, "hero_id": 8, "player_slot": 0,
                 "radiant_win": True, "start_time": 1700000000,
                 "duration": 2000, "kills": 3, "deaths": 1, "assists": 5,
                 "personaname": "p", "steam_id": sid}]

    dota_mmr.get_recent_matches_async = fake
    old_linked = dota_matches._linked_steam_ids
    old_index = dota_matches._bot_steam_index
    old_heroes = dota_matches._hero_catalog
    dota_matches._linked_steam_ids = lambda n: [111]
    dota_matches._bot_steam_index = lambda: {111: {}}
    dota_matches._hero_catalog = lambda: {}
    try:
        games = asyncio.run(get_player_games(limit=5))
    finally:
        dota_mmr.get_recent_matches_async = saved_api
        dota_mmr._user_matches_cache.clear()
        dota_mmr._user_matches_cache.update(saved_cache)
        dota_matches._linked_steam_ids = old_linked
        dota_matches._bot_steam_index = old_index
        dota_matches._hero_catalog = old_heroes

    assert len(games) == 1
    assert games[0]["match_id"] == 5


def test_matches_cache_is_shared_across_callers():
    """Разные вызовы делят один кеш: восемь матчей покрывают запрос на три.

    Раньше ключ был (steam_id, limit), поэтому страница матчей, апдейт
    профиля и OBS качали одно и то же заново, не видя чужой кеш.
    """
    import dota_mmr

    calls: list[int] = []

    async def fake_api(url, params):
        calls.append(params.get("limit", 5))
        return [{"match_id": i, "lobby_type": 7, "game_mode": 22}
                for i in range(params.get("limit", 5))]

    saved = (dota_mmr._api_get_async, dota_mmr._is_not_found,
             dota_mmr._mark_not_found, dict(dota_mmr._user_matches_cache))
    dota_mmr._api_get_async = fake_api
    dota_mmr._is_not_found = lambda url: False
    dota_mmr._mark_not_found = lambda url: None
    dota_mmr._user_matches_cache.clear()
    try:
        async def run():
            eight = await dota_mmr.get_recent_matches_async(111, 8)
            three = await dota_mmr.get_recent_matches_async(111, 3)
            eight_again = await dota_mmr.get_recent_matches_async(111, 8)
            return eight, three, eight_again

        eight, three, eight_again = asyncio.run(run())
    finally:
        (dota_mmr._api_get_async, dota_mmr._is_not_found,
         dota_mmr._mark_not_found) = saved[:3]
        dota_mmr._user_matches_cache.clear()
        dota_mmr._user_matches_cache.update(saved[3])

    assert len(eight) == 8 and len(three) == 3 and len(eight_again) == 8
    assert calls == [8], f"OpenDota должен быть дёрнут один раз, было {calls}"


def test_ranks_tab_does_not_fetch_games():
    """Вкладка «Топ рангов» не ходит в OpenDota — она берёт топ из БД."""
    source = (PROJECT_ROOT / "main.py").read_text(encoding="utf-8")
    # get_player_games живёт только в ветке else, а не общим вызовом.
    body = source.split("async def games_page_handler", 1)[1]
    body = body.split("\nasync def ", 1)[0]
    # Ищем именно вызов, а не импорт в шапке функции.
    call = "games = await get_player_games"
    assert call in body
    assert body.index("if tab == 'mmr':") < body.index(call)
    # Вызов живёт в ветке else, то есть только для истории игр.
    assert "\n        else:\n            games = await get_player_games" in body




def test_get_dota_matches_clamps_limit(monkeypatch):
    seen = {}

    def fake_index(limit):
        seen["limit"] = limit
        return []

    monkeypatch.setattr(dota_matches, "_load_match_index", fake_index)
    dota_matches._list_cache = None

    asyncio.run(dota_matches.get_dota_matches(limit=9999, force=True))
    assert seen["limit"] == dota_matches.MAX_LIMIT


def test_css_has_no_broken_comments():
    """В стилях нет оборванных CSS-комментариев.

    Строка вида «/─ Вкладки» без открывающей звёздочки — не комментарий,
    а мусор в селекторе. Браузер выбрасывал вместе с ней следующее правило
    (.g-tabs), и сегментированная рамка вкладок пропадала.
    """
    for name in ("GAMES_CSS", "PAGE_CSS"):
        css = getattr(dota_matches, name)
        assert css.count("/*") == css.count("*/"), f"{name}: незакрытый комментарий"
        broken = re.findall(r"(?m)^[ \t]*/(?![/*])", css)
        assert not broken, f"{name}: комментарий без «/*» — {len(broken)} шт."
