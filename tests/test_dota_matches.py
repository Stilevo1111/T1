"""Tests for the Dota 2 match list served by the bot's web endpoints."""

import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import dota_matches


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
    assert "Победа" in html and "Поражение" in html
    # Ник открывает профиль через data-атрибут + обработчик клика:
    # вложенная <a> внутри <a> невалидна, поэтому ссылки в href нет.
    assert 'data-tg="777"' in html
    assert "tg://user?id=" in html
    assert "15.11" in html  # date column (Europe/Moscow), compact format
    assert "39:05" in html  # duration column
    assert "—" in html  # zero duration
    assert "opendota.com/matches/8123456789" in html
    assert "zeus · 1/1" in html  # per-player filter chip
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_render_game_is_a_single_line_with_avatar_and_kda():
    """Строка игры: аватар, бейдж героя, ник, KDA — всё в одну линию."""
    game = {
        "match_id": 42, "start_time": 10, "duration": 60, "win": True,
        "hero_id": 8, "hero_name": "Juggernaut", "hero_icon": "http://h/jugg.png",
        "personaname": "Wawashik", "bot_username": "Wawashik",
        "kills": 15, "deaths": 1, "assists": 8,
        "steam_id": 1, "telegram_id": 777, "avatar": "http://a/ava.jpg",
    }
    html = dota_matches.render_games_page([game], limit=5)
    row = dota_matches.render_game(game)

    assert 'class="g-face-img" src="http://a/ava.jpg"' in html  # аватар
    assert 'class="g-hero" src="http://h/jugg.png"' in html     # бейдж героя
    assert 'class="g-kda"' in html                              # блок KDA
    assert "<b>15</b>" in html and ">1<" in html and ">8<" in html
    assert html.count('class="g-row win"') == 1
    # Строка сама является ссылкой на OpenDota, поэтому <a> в ней ровно
    # один: вложенных ссылок быть не может (это невалидный HTML).
    assert row.count("<a") == 1
    assert 'data-tg="777"' in row
    assert "g-head" not in html          # шапки колонок больше нет
    assert "g-items" not in row          # предметов пока нет — блок скрыт
    assert "prefers-reduced-motion" in html  # анимации отключаются настройкой


def test_render_game_without_avatar_falls_back_to_initial():
    """Без аватара показываем цветной круг с первой буквой ника."""
    game = {
        "match_id": 43, "start_time": 10, "duration": 60, "win": False,
        "hero_id": 8, "hero_name": "AM", "hero_icon": "",
        "personaname": "seredin", "bot_username": "seredin",
        "kills": 0, "deaths": 0, "assists": 0,
        "steam_id": 1, "telegram_id": None, "avatar": None,
    }
    html = dota_matches.render_games_page([game], limit=5)
    assert "g-face-ph" in html
    assert ">S<" in html


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
    assert html.count('class="g-row') == 1
    assert "matches/1" in html and "matches/2" not in html

    empty = dota_matches.render_games_page([], limit=10)
    assert "Пока нет игр" in empty




def test_get_dota_matches_clamps_limit(monkeypatch):
    seen = {}

    def fake_index(limit):
        seen["limit"] = limit
        return []

    monkeypatch.setattr(dota_matches, "_load_match_index", fake_index)
    dota_matches._list_cache = None

    asyncio.run(dota_matches.get_dota_matches(limit=9999, force=True))
    assert seen["limit"] == dota_matches.MAX_LIMIT
