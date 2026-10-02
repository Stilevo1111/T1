"""Живой интеграционный прогон: /api/dota-matches и /matches через реальные хендлеры.

Запуск:
    python tests/it_dota_matches_live.py

Скрипт сам создаёт временную SQLite-базу с матчами, подменяет OpenDota заглушкой
(сетевых вызовов нет) и проверяет, что оба эндпоинта отдают корректный контент.
Не является частью pytest-набора (файл намеренно назван it_*, а не test_*).
"""

import asyncio
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

try:  # Windows-консоль по умолчанию cp1251 и портит кириллицу в логе
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

DB_PATH = ROOT / "it_dota_matches.db"
STEAM_BASE = 76561197960265728  # account_id -> steam64


def account_id(steam_id: int) -> int:
    return steam_id - STEAM_BASE


def seed_database() -> None:
    if DB_PATH.exists():
        DB_PATH.unlink()
    now = int(time.time())
    con = sqlite3.connect(DB_PATH)
    con.execute(
        """CREATE TABLE public_player_matches (
            match_id INTEGER UNIQUE, hero_id INTEGER, player_slot INTEGER,
            radiant_win INTEGER, start_time INTEGER, steam_id INTEGER)"""
    )
    con.executemany(
        "INSERT OR IGNORE INTO public_player_matches VALUES (?,?,?,?,?,?)",
        [
            (9111000001, 1, 0, 1, now - 600, 76561198000000001),
            (9111000001, 2, 128, 1, now - 600, 76561198000000002),
            (9111000002, 5, 2, 0, now - 3600, 76561198000000001),
            (9111000003, 9, 129, 1, now - 7200, 76561198000000003),
        ],
    )
    con.execute(
        "CREATE TABLE users (steam_id INTEGER, telegram_id INTEGER, username TEXT, steam_nickname TEXT)"
    )
    con.executemany(
        "INSERT OR IGNORE INTO users VALUES (?,?,?,?)",
        [
            (76561198000000001, 111111, "@zeus", "ZeusFan"),
            (76561198000000003, 333333, "@lina", "LinaMain"),
        ],
    )
    con.commit()
    con.close()


seed_database()
os.environ["DATABASE_URL"] = "sqlite:///" + DB_PATH.as_posix()

import dota_matches  # noqa: E402  (после подмены DATABASE_URL)
import main  # noqa: E402

FAILURES = []


def check(name: str, condition: bool, extra: str = "") -> None:
    print(("  OK   " if condition else "  FAIL ") + name + ((" -> " + extra) if extra else ""))
    if not condition:
        FAILURES.append(name)


async def fake_detail(match_id: int) -> dict:
    """Заглушка OpenDota: два состава, счёт и режим Ranked."""
    now = int(time.time())
    radiant = [
        {"player_slot": 0, "hero_id": 1, "account_id": account_id(76561198000000001),
         "personaname": "ZeusFan", "kills": 12, "deaths": 3, "assists": 9},
        {"player_slot": 1, "hero_id": 2, "account_id": 2222,
         "personaname": "RandomGuy", "kills": 7, "deaths": 6, "assists": 11},
    ]
    dire = [
        {"player_slot": 128, "hero_id": 9, "account_id": 3333,
         "personaname": "Rival", "kills": 9, "deaths": 8, "assists": 4},
        {"player_slot": 129, "hero_id": 5, "account_id": 4444,
         "personaname": "<script>alert(1)</script>", "kills": 1, "deaths": 10, "assists": 2},
    ]
    win = match_id != 9111000002
    return {
        "start_time": now - 600,
        "duration": 2345,
        "radiant_win": win,
        "game_mode": 22,
        "radiant_score": 32 if win else 18,
        "dire_score": 18 if win else 32,
        "players": radiant + dire,
    }


dota_matches._fetch_match_detail = fake_detail


async def run() -> None:
    from aiohttp import web
    from aiohttp.test_utils import TestClient, TestServer

    app = web.Application()
    app.router.add_get("/api/dota-matches", main.dota_matches_api_handler)
    app.router.add_get("/matches", main.dota_matches_page_handler)

    async with TestClient(TestServer(app)) as client:
        print("\n[1] GET /api/dota-matches?limit=5")
        resp = await client.get("/api/dota-matches?limit=5")
        payload = await resp.json()
        check("status 200", resp.status == 200, str(resp.status))
        check("content-type json", "application/json" in resp.headers.get("Content-Type", ""))
        check("CORS header", resp.headers.get("Access-Control-Allow-Origin") == "*")
        check("payload keys", sorted(payload.keys()) == ["count", "generated_at", "matches"],
              str(sorted(payload.keys())))
        matches = payload["matches"]
        check("3 matches returned", len(matches) == 3, str(len(matches)))
        check("sorted newest first",
              [m["start_time"] for m in matches] == sorted([m["start_time"] for m in matches], reverse=True))
        first = matches[0]
        check("match has both lineups", len(first["radiant"]) == 2 and len(first["dire"]) == 2)
        check("score filled", first["radiant_score"] == 32 and first["dire_score"] == 18)
        check("mode decoded", first["mode"] == "Ranked", str(first["mode"]))
        check("duration filled", first["duration"] == 2345, str(first["duration"]))
        icon = first["radiant"][0]["hero_icon"]
        check("hero icon is Steam CDN", icon.startswith(dota_matches.HERO_CDN_BASE), icon)
        bot_player = first["radiant"][0]
        check("bot player linked",
              bot_player.get("bot_username") == "@zeus" and bot_player.get("telegram_id") == 111111,
              json.dumps(bot_player, ensure_ascii=False))
        check("no local filesystem paths leaked", "/assets/" not in json.dumps(payload))

        print("\n[2] GET /api/dota-matches?limit=2")
        payload2 = await (await client.get("/api/dota-matches?limit=2")).json()
        check("limit honoured", len(payload2["matches"]) == 2, str(len(payload2["matches"])))

        print("\n[3] GET /api/dota-matches?limit=999")
        payload3 = await (await client.get("/api/dota-matches?limit=999")).json()
        check("limit clamped to MAX_MATCH_LIMIT", len(payload3["matches"]) <= main.MAX_MATCH_LIMIT)

        print("\n[4] GET /matches")
        page = await client.get("/matches")
        html = await page.text()
        check("status 200", page.status == 200, str(page.status))
        check("content-type html", "text/html" in page.headers.get("Content-Type", ""))
        check("page has cards", html.count('class="match-card') == 3, str(html.count('class="match-card')))
        check("page has score", "32" in html and "18" in html)
        check("page has tg link", "tg://user?id=111111" in html)
        check("page has team names", "Свет" in html and "Тьма" in html)
        check("page has match id", "Матч #9111000001" in html)
        check("page escaped nickname", "&lt;script&gt;" in html)
        check("page has no local paths", "/assets/" not in html)
        check("page has hero CDN art", dota_matches.HERO_CDN_BASE in html)

        print("\n[4b] GET /matches (Telegram Mini App)")
        check("web page embeds Telegram WebApp SDK", dota_matches.TELEGRAM_WEBAPP_JS in html)
        check("web page has viewport-fit=cover", "viewport-fit=cover" in html)
        check("web page is not flagged as miniapp", 'class="miniapp"' not in html)

        mini = await client.get("/matches?miniapp=1")
        mini_html = await mini.text()
        check("miniapp status 200", mini.status == 200, str(mini.status))
        check("miniapp body flagged", 'class="miniapp"' in mini_html)
        check("miniapp keeps the flag in page-size links", "limit=50&miniapp=1" in mini_html,
              "href=/matches?limit=50&miniapp=1")
        check("miniapp injects the theme script", "themeChanged" in mini_html)
        check("miniapp opens external links via openLink", "tg.openLink" in mini_html)
        check("miniapp has the same cards", mini_html.count('class="match-card') == 3,
              str(mini_html.count('class="match-card')))

        print("\n[5] concurrent refresh (потоки + кеш + SQLite)")
        results = await asyncio.gather(
            *[dota_matches.get_dota_matches(limit=5, force=True) for _ in range(6)],
            return_exceptions=True,
        )
        errors = [r for r in results if isinstance(r, BaseException)]
        check("no cross-thread DB errors", not errors, repr(errors[:1]))
        check("all refreshes returned 3 matches",
              all(isinstance(r, list) and len(r) == 3 for r in results))

        print("\n[6] graceful partial (OpenDota недоступен)")
        async def failing_detail(match_id):
            raise RuntimeError("OpenDota 429")

        dota_matches._fetch_match_detail = failing_detail
        dota_matches._list_cache = None
        partial = await dota_matches.get_dota_matches(limit=5, force=True)
        check("matches still returned", len(partial) == 3, str(len(partial)))
        check("marked partial", all(m["partial"] for m in partial))
        check("DB data survived", partial[0]["match_id"] in (9111000001, 9111000002, 9111000003))
        check("bot_players counted from DB", all(m["bot_players"] >= 1 for m in partial))


asyncio.run(run())

# Windows не даёт удалить файл, пока жив хоть один дескриптор, поэтому чистим пул.
try:
    import database

    for _conns in (getattr(database, "_pool", {}) or {}).values():
        for _c in list(_conns):
            try:
                _c.close()
            except Exception:
                pass
        _conns.clear()
    if DB_PATH.exists():
        DB_PATH.unlink()
except Exception as exc:  # pragma: no cover - уборка не должна ронять прогон
    print("cleanup warning:", exc)

print("\n" + ("ВСЁ ПРОШЛО" if not FAILURES else "ПРОВАЛЕНО: " + ", ".join(FAILURES)))
sys.exit(1 if FAILURES else 0)
