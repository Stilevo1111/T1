"""Tests for the Dota 2 match list served by the bot's web endpoints."""

import asyncio
import re
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
    assert "Победа" in row
    # Строка больше не ссылка: клик открывает панель с «Пати» и «ДотаБаф».
    assert "<a" not in row
    assert 'data-act="party"' in row and 'data-act="dota"' in row
    assert "dotabuff.com/matches/42" in row
    assert "t.me/share/url" in row
    assert 'data-tg="777"' in row                             # переход в профиль
    assert "g-items" not in row                               # предметов нет


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
    assert "Поражение" in html


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

    for title in ("Место", "Ранг", "Статистика"):
        assert title in html
    assert "#" not in html.split("</style>", 1)[-1].split("</head>")[0]
    assert 'data-sort="name"' not in html            # по нику больше не сортируем
    assert "seredin999.onrender.com/images/ranks/" in html
    assert "rank_8_1.webp" in html and "rank_3_1.webp" in html
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
    assert "Божество" in row                      # 75 = Божество 5 звёзд
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
    """В строке игры виден ранг игрока."""
    game = {
        "match_id": 7, "start_time": 100, "duration": 60, "win": True,
        "hero_id": 8, "hero_name": "AM", "hero_icon": "",
        "personaname": "p", "bot_username": "p",
        "kills": 1, "deaths": 0, "assists": 2,
        "steam_id": 1, "telegram_id": None, "rank_tier": 65,
    }
    row = dota_matches.render_game(game)
    assert "Титан" in row                        # 65 = Титан 5 звёзд
    assert "rank_6_5.webp" in row

    no_rank = dict(game, rank_tier=None)
    assert "Без ранга" in dota_matches.render_game(no_rank)


def test_game_row_rank_looks_like_the_ranking_tab():
    """Ранг в истории подан так же, как в топе: иконка + название под ником.

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
    assert "Титан" in row                          # название под ником
    assert "g-rank-mini" not in row               # отдельной плашки больше нет
    assert 'class="g-rank-img"' in top_row         # топ не тронут


def test_ranking_header_padding_matches_row():
    """Шапка топра стоит по тем же бокам, что и строки под ней."""
    players = [{"username": "a", "steam_nickname": "a", "mmr": 1,
                "rank_tier": 50, "week_games": 1, "week_wins": 1}]
    html = dota_matches.render_games_page([], limit=5, tab="mmr",
                                          mmr_players=players)
    css = html.split("</style>", 1)[0].replace("\n", "")
    head_pad = re.search(r"\.g-mmr-head\{padding:0 (\d+)px 8px\}", css)
    row_pad = re.search(r"\.g-line\{display:flex;align-items:center;gap:10px;"
                        r"padding:\S+ (\d+)px", css)
    assert head_pad and row_pad
    assert head_pad.group(1) == row_pad.group(1)     # иначе колонки съедут


def test_sort_header_is_outlined_not_underlined():
    """Активная колонка обведена, а не подчёркнута."""
    css = dota_matches.GAMES_CSS.replace("\n", "")
    assert ".g-hp.on{" in css
    assert "box-shadow:inset 0 0 0 1px rgba(232,180,92,.45)" in css
    assert ".g-hp.on{border-bottom" not in css
    # Стрелки подсказывают, что сортировать можно по любой колонке,
    # поэтому они видны у всех, а не только у активной.
    assert ".g-hp .ar{" in css and "opacity:.28" in css


def test_mmr_tab_headers_are_sortable():
    """Заголовки топра кликабельны, как на странице топа."""
    players = [{"username": "a", "steam_nickname": "a", "mmr": 0,
                "rank_tier": 50, "week_games": 1, "week_wins": 1}]
    html = dota_matches.render_games_page([], limit=5, tab="mmr",
                                          mmr_players=players)
    assert 'data-sort="rank_tier"' in html
    # По нику не сортируем: заголовок «Игрок» стал пустой подписью колонки.
    assert 'data-sort="name"' not in html
    assert 'data-sort="stats"' in html
    assert "RANKS" not in html or "g-mmr-head" in html
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




def test_get_dota_matches_clamps_limit(monkeypatch):
    seen = {}

    def fake_index(limit):
        seen["limit"] = limit
        return []

    monkeypatch.setattr(dota_matches, "_load_match_index", fake_index)
    dota_matches._list_cache = None

    asyncio.run(dota_matches.get_dota_matches(limit=9999, force=True))
    assert seen["limit"] == dota_matches.MAX_LIMIT
