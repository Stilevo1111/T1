"""Audit-focused regression tests for fixes verified in the codebase."""

from pathlib import Path

from bot_utils import clickable_name, format_time
from database import User


def test_format_time_russian_units():
    assert "ч" in format_time(3661)
    assert "м" in format_time(65)
    assert "h" not in format_time(3661)
    assert "m" not in format_time(65)
    assert "s" not in format_time(5)


def test_clickable_name_telegram_id_zero_no_crash():
    result = clickable_name("TestUser", telegram_id=0, steam_id=12345)
    assert isinstance(result, str)
    assert len(result) > 0
    assert "tg://user?id=0" in result or "https://steamcommunity.com/" in result or "TestUser" in result


def test_user_from_row_sqlite_indices():
    row = [0] * 50
    row[1] = 123
    row[39] = 42
    row[41] = 5
    row[42] = 3
    row[43] = 10
    user = User.from_row(row, db_type="sqlite")
    assert user.message_count == 42
    assert user.current_win_streak == 5
    assert user.current_lose_streak == 3
    assert user.best_lose_streak == 10


def test_no_duplicate_link_handler():
    main_path = Path(__file__).resolve().parent.parent / "main.py"
    content = main_path.read_text(encoding="utf-8")
    assert content.count('if data == "link":') == 1


def test_new_chat_members_service_message_welcomes_users(monkeypatch):
    import asyncio
    from datetime import UTC, datetime
    from types import SimpleNamespace

    from telegram import Chat, Message, Update, User

    import main

    chat = Chat(id=-100123, type="group")
    newcomer = User(id=123, first_name="Alice", username="alice", is_bot=False)
    bot = User(id=999, first_name="Fissure", is_bot=True)
    message = Message(
        message_id=1,
        date=datetime.now(UTC),
        chat=chat,
        new_chat_members=(newcomer, bot),
    )
    update = Update(update_id=1, message=message)
    context = SimpleNamespace(bot=SimpleNamespace(id=bot.id))
    calls = []

    async def fake_welcome(chat_id, user_obj, context):
        calls.append((chat_id, user_obj.id))

    monkeypatch.setattr(main, "_welcome_joined_member", fake_welcome)

    asyncio.run(main.welcome_new_members_message(update, context))

    assert calls == [(chat.id, newcomer.id)]


def test_welcome_joined_member_uses_first_name_without_username(monkeypatch):
    import asyncio
    from types import SimpleNamespace

    from telegram import User

    import main

    newcomer = User(id=123, first_name="Alice", is_bot=False)
    calls = []

    class FakeDatabase:
        def register_user(self, *args, **kwargs):
            calls.append(("register", args, kwargs))
            return newcomer.id

    async def send_message(**kwargs):
        calls.append(("send", kwargs))
        return SimpleNamespace(message_id=1)

    def set_user_in_chat(user_id, in_chat):
        calls.append(("in_chat", user_id, in_chat))
        return True

    monkeypatch.setattr(main, "Database", FakeDatabase)
    monkeypatch.setattr(main, "set_user_in_chat", set_user_in_chat)
    monkeypatch.setattr(main.random, "choice", lambda phrases: "welcome")
    context = SimpleNamespace(bot=SimpleNamespace(send_message=send_message))

    asyncio.run(main._welcome_joined_member(-100123, newcomer, context))

    assert calls[0] == (
        "register",
        (newcomer.id, newcomer.first_name, newcomer.first_name),
        {"source": "welcome"},
    )
    assert calls[1] == ("in_chat", newcomer.id, True)
    assert calls[2][0] == "send"
    assert calls[2][1]["text"] == '<a href="tg://user?id=123">Alice</a>, welcome'
    assert calls[2][1]["parse_mode"] == "HTML"


def test_join_handled_by_both_chat_member_and_service(monkeypatch):
    import asyncio
    from datetime import UTC, datetime
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from telegram import Chat, ChatMember, ChatMemberUpdated, Message, Update, User

    import main

    chat = Chat(id=-100123, type="group")
    newcomer = User(id=123, first_name="Alice", is_bot=False)
    bot_id = 999
    now = datetime.now(UTC)
    chat_update = ChatMemberUpdated(
        chat=chat,
        from_user=newcomer,
        date=now,
        old_chat_member=ChatMember(user=newcomer, status="left"),
        new_chat_member=ChatMember(user=newcomer, status="member"),
    )
    chat_member_update = Update(update_id=1, chat_member=chat_update)
    message = Message(
        message_id=2,
        date=now,
        chat=chat,
        new_chat_members=(newcomer,),
    )
    service_update = Update(update_id=2, message=message)
    context = SimpleNamespace(bot=SimpleNamespace(id=bot_id))
    fake_welcome = AsyncMock()
    monkeypatch.setattr(main, "_welcome_joined_member", fake_welcome)

    asyncio.run(main.welcome_new_member(chat_member_update, context))
    asyncio.run(main.welcome_new_members_message(service_update, context))

    # Both handlers should call _welcome_joined_member, but deduplication
    # ensures only the first one actually sends the welcome
    assert fake_welcome.call_count == 2


def test_leave_marks_user_inactive(monkeypatch):
    import asyncio
    from datetime import UTC, datetime
    from types import SimpleNamespace

    from telegram import Chat, ChatMember, ChatMemberUpdated, Update, User

    import main

    chat = Chat(id=-100123, type="group")
    newcomer = User(id=123, first_name="Alice", is_bot=False)
    now = datetime.now(UTC)
    chat_update = ChatMemberUpdated(
        chat=chat,
        from_user=newcomer,
        date=now,
        old_chat_member=ChatMember(user=newcomer, status="member"),
        new_chat_member=ChatMember(user=newcomer, status="left"),
    )
    update = Update(update_id=1, chat_member=chat_update)
    context = SimpleNamespace(bot=SimpleNamespace(id=999))
    calls = []

    def fake_delete(user_id):
        calls.append(user_id)
        return True

    monkeypatch.setattr(main, "delete_user", fake_delete)

    asyncio.run(main.welcome_new_member(update, context))

    assert calls == [newcomer.id]


def test_delete_user_preserves_last_fissure(monkeypatch):
    import sys
    import threading
    from types import SimpleNamespace

    import database

    class FakeCursor:
        def __init__(self):
            self.query = None
            self.params = None

        def execute(self, query, params=None):
            self.query = query
            self.params = params

        def close(self):
            pass

    class FakeConnection:
        def __init__(self):
            self.cursor_obj = FakeCursor()
            self.committed = False

        def cursor(self):
            return self.cursor_obj

        def commit(self):
            self.committed = True

    class FakeUserCache:
        def __init__(self):
            self._lock = threading.Lock()
            self._steam_index = {}
            self.deleted = []

        def delete(self, key):
            self.deleted.append(key)

    class FakeTopCache:
        def invalidate_top_cache(self):
            pass

    connection = FakeConnection()
    user_cache = FakeUserCache()
    monkeypatch.setattr(database, "get_connection", lambda: connection)
    monkeypatch.setattr(database, "get_db_type", lambda: "sqlite")
    monkeypatch.setattr(database, "release_connection", lambda conn: None)
    monkeypatch.setattr(database, "top_cache", FakeTopCache())
    monkeypatch.setattr(database, "user_cache", user_cache)
    monkeypatch.setitem(sys.modules, "main", SimpleNamespace())

    assert database.delete_user(123) is True
    assert connection.committed is True
    assert connection.cursor_obj.query == "UPDATE users SET in_chat = 0 WHERE telegram_id = ?"
    assert connection.cursor_obj.params == (123,)
    assert "last_fissure" not in connection.cursor_obj.query


def test_bot_added_sets_digest_chat(monkeypatch):
    import asyncio
    from datetime import UTC, datetime
    from types import SimpleNamespace

    from telegram import Chat, ChatMember, ChatMemberUpdated, Update, User

    import main

    chat = Chat(id=-100123, type="group")
    bot = User(id=999, first_name="Fissure", is_bot=True)
    now = datetime.now(UTC)
    chat_update = ChatMemberUpdated(
        chat=chat,
        from_user=bot,
        date=now,
        old_chat_member=ChatMember(user=bot, status="left"),
        new_chat_member=ChatMember(user=bot, status="member"),
    )
    update = Update(update_id=1, my_chat_member=chat_update)
    context = SimpleNamespace(bot=SimpleNamespace(id=bot.id))
    calls = []

    def fake_get_config(key):
        assert key == "digest_chat_id"
        return None

    def fake_set_config(key, value):
        calls.append((key, value))
        return True

    monkeypatch.setattr(main, "get_config", fake_get_config)
    monkeypatch.setattr(main, "set_config", fake_set_config)

    asyncio.run(main.welcome_new_member(update, context))

    assert calls == [("digest_chat_id", chat.id)]


def test_welcome_service_handler_is_rate_limited_and_registered():
    main_path = Path(__file__).resolve().parent.parent / "main.py"
    content = main_path.read_text(encoding="utf-8")
    assert "@rate_limit(tokens=1)\nasync def welcome_new_members_message" in content
    assert "ChatMemberHandler(welcome_new_member, ChatMemberHandler.ANY_CHAT_MEMBER)" in content
    assert "MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome_new_members_message)" in content


def test_techies_result_uploads_selected_image_bytes():
    import asyncio
    from unittest.mock import AsyncMock

    from telegram import InputFile

    import techies

    async def verify_image(image_path):
        bot = AsyncMock()
        bot.edit_message_media.return_value = AsyncMock()
        await techies._send_techies_result(bot, 1, 1, "test", image_path)
        media = bot.edit_message_media.await_args.kwargs["media"]
        assert isinstance(media.media, InputFile)
        assert media.media.filename == image_path.name
        assert media.media.input_file_content == image_path.read_bytes()

    asyncio.run(verify_image(techies.TECHIES_BASE_URL))
    asyncio.run(verify_image(techies.TECHIES_SUCCESS_URL))
    asyncio.run(verify_image(techies.TECHIES_EXPLOSION_URL))


def test_clear_hero_meta_cache_invalidates_redis(monkeypatch):
    import sys
    from types import SimpleNamespace

    import database
    import hero_meta

    deleted_keys = []

    class FakeCache:
        async def delete(self, key):
            deleted_keys.append(key)
            return True

    def set_config(key, value):
        pass

    monkeypatch.setattr(database, "set_config", set_config)
    monkeypatch.setitem(
        sys.modules,
        "cache",
        SimpleNamespace(cache=FakeCache()),
    )
    monkeypatch.setattr(
        hero_meta,
        "_hero_meta_cache",
        {"data": "old", "timestamp": 123},
    )

    hero_meta.clear_hero_meta_cache()

    assert deleted_keys == [hero_meta.HERO_META_REDIS_KEY]
    assert hero_meta._hero_meta_cache == {"data": None, "timestamp": 0}



def test_top_card_cache_reuses_unchanged_card_and_evicts_old_entries():
    import main

    main._TOP_CARD_CACHE.clear()
    calls = []

    def generator(value):
        calls.append(value)
        return f"card-{value}".encode()

    first = main.get_cached_top_card(generator, ("fissure", 1, "A"), value=1)
    second = main.get_cached_top_card(generator, ("fissure", 1, "A"), value=1)
    assert first == second == b"card-1"
    assert calls == [1]

    for i in range(main._TOP_CARD_CACHE_MAX_SIZE + 1):
        main.get_cached_top_card(generator, ("fissure", i, "A"), value=i)

    assert len(main._TOP_CARD_CACHE) == main._TOP_CARD_CACHE_MAX_SIZE
    assert ("fissure", 0, "A") not in main._TOP_CARD_CACHE


def test_top_cache_invalidation_supports_mmr_key():
    from database import top_cache

    top_cache.set("mmr_top_10", [{"telegram_id": 1}])
    top_cache.set("unrelated", "keep")

    top_cache.invalidate_top_cache()

    assert top_cache.get("mmr_top_10") is None
    assert top_cache.get("unrelated") == "keep"


def test_fissure_rank_has_expression_index():
    from pathlib import Path

    database_path = Path(__file__).resolve().parent.parent / "database.py"
    content = database_path.read_text(encoding="utf-8")
    assert "idx_users_fissure_rank ON users(COALESCE(fissure, 0) DESC)" in content



def test_profile_does_not_assign_fissure_tags():
    import main

    content = Path(main.__file__).read_text(encoding="utf-8")
    profile_start = content.index("async def _build_profile_progress_card")
    profile_end = content.index("async def refreshmmr", profile_start)
    profile_source = content[profile_start:profile_end]
    assert "add_user_tag(" not in profile_source
    assert "F1/F2/F3 are reconciled exclusively" in profile_source


def test_periodic_tag_refresh_was_removed(monkeypatch):
    """Теги обновляются только на ролле фиссуры — таймер удалён.

    Коммит 92037cc убрал periodic_tag_refresh из main.py, чтобы не будить
    Neon по расписанию. Этот тест гарантирует, что таймер не вернётся.
    """
    import main

    content = Path(main.__file__).read_text(encoding="utf-8")
    assert "periodic_tag_refresh" not in content


def test_mmr_tags_use_weekly_top_source(monkeypatch):
    import asyncio
    import tags

    calls = []

    def fake_week_top(limit):
        calls.append(limit)
        return []

    monkeypatch.setattr(tags, "_MMR_TAG_REFRESH_LOCK", asyncio.Lock())
    monkeypatch.setattr("database.get_config", lambda key: "10" if key == "mmr_chat_id" else None)
    monkeypatch.setattr("database.get_dota_week_top_from_db", fake_week_top)
    asyncio.run(tags.refresh_mmr_top_tags(object()))
    assert calls == [10]


def test_weekly_reset_clears_previous_mmr_holder_state():
    import main

    content = Path(main.__file__).read_text(encoding="utf-8")
    reset_start = content.index("async def weekly_mmr_reset_job")
    reset_end = content.index("async def announce_weekly_mmr_winner", reset_start)
    reset_source = content[reset_start:reset_end]
    assert '("weekly_mvp", "weekly_top1", "weekly_top2", "weekly_top3")' in reset_source
    assert "'current_mmr_top1_telegram_id'" in reset_source
    assert "get_dota_week_top_from_db._cache = {}" in reset_source


def test_dead_fissure_master_refresh_removed():
    content = Path("fissure.py").read_text(encoding="utf-8")
    assert "refresh_fissure_master_tag" not in content


def test_mvp_ceremony_does_not_write_live_top_tags():
    import main

    content = Path(main.__file__).read_text(encoding="utf-8")
    start = content.index("async def announce_weekly_mmr_winner")
    end = content.index("async def refresh_digest_message", start)
    # The MMR job is defined between ceremony and refresh_digest_message;
    # limit this assertion to the ceremony itself.
    ceremony = content[start:content.index("async def claim_or_check_mmr_leader", start)]
    assert 'telegram_id, "weekly_mvp"' in ceremony
    assert "refresh_mmr_top_tags" not in ceremony
    assert 'add_user_tag(telegram_id, "weekly_top' not in ceremony


def test_mmr_job_refreshes_live_top_tags_immediately():
    import main

    content = Path(main.__file__).read_text(encoding="utf-8")
    start = content.index("async def update_all_mmr_job")
    end = content.index("async def refresh_digest_message", start)
    source = content[start:end]
    assert "get_dota_week_top_from_db._cache = {}" in source
    assert "await refresh_mmr_top_tags(context.bot)" in source



def test_text_profile_places_tags_last(monkeypatch):
    import main

    user = {
        "telegram_id": 1,
        "username": "player",
        "steam_id": 123,
        "fissure": 10.0,
        "total_rolls": 5,
        "current_streak": 1,
        "best_streak": 2,
        "weekly_mvp": 1,
        "weekly_top2": 0,
        "weekly_top3": 0,
    }
    monkeypatch.setattr(main, "format_user_tags", lambda uid: "• VIP")
    result = main._build_profile_text(
        user,
        type("User", (), {"username": "player", "id": 1})(),
        False,
        3,
        2,
        1,
        33,
    )
    assert result.index("🎮 Dota за неделю") < result.index("✨ <b>Награды недели</b>")
    assert result.index("✨ <b>Награды недели</b>") < result.index("🏷️ <b>Теги</b>")
    assert result.index("🏷️ <b>Теги</b>") > result.index("🎮 Dota за неделю")
    assert result.rstrip().endswith("• VIP")


def test_fissure_live_refresh_and_sqlite_filter_regression():
    fissure_source = Path("fissure.py").read_text(encoding="utf-8")
    database_source = Path("database.py").read_text(encoding="utf-8")
    assert "str(user_obj.id) in current_holders" in fissure_source
    assert "WHERE (in_chat = 1 OR in_chat IS NULL) ORDER BY fissure DESC LIMIT ?" in database_source


def test_top_commands_use_expected_limits_and_mmr_format():
    import main

    content = Path(main.__file__).read_text(encoding="utf-8")
    assert "asyncio.to_thread(get_fissure_top, 15)" in content
    assert 'lines.append(f" └ {week_wins}W • {week_losses}L • {wr}%")' in content
    assert 'top_text += f" └ {user_week_wins}W • {user_week_losses}L • {user_wr}%"' in content
    topmmr_start = content.index("async def topmmr")
    topmmr_end = content.index("async def", topmmr_start + 10)
    assert "WR {wr}%" not in content[topmmr_start:topmmr_end]





def test_weekly_award_grant_is_idempotent(monkeypatch):
    import database

    calls = []

    class FakeCursor:
        def __init__(self):
            self.first_fetch = True

        def execute(self, sql, params=()):
            calls.append((sql, params))

        def fetchone(self):
            if self.first_fetch:
                self.first_fetch = False
                return {"value": "2026-09-21"}
            return {"weekly_mvp": 2, "weekly_top2": 1, "weekly_top3": 0}

        def close(self):
            pass

    class FakeConn:
        def cursor(self, **kwargs):
            return FakeCursor()

        def commit(self):
            calls.append(("commit", ()))

        def rollback(self):
            calls.append(("rollback", ()))

    monkeypatch.setattr(database, "get_connection", lambda: FakeConn())
    monkeypatch.setattr(database, "get_db_type", lambda: "postgresql")
    monkeypatch.setattr(database, "release_connection", lambda conn: None)
    monkeypatch.setattr(database, "get_user", lambda uid: None)

    # The fake cursor returns a dict; emulate the real count projection by
    # keeping this test focused on the early-return branch for an existing marker.
    result = database.grant_weekly_mmr_awards(
        "2026-09-21", [(1, 1), (2, 2), (3, 3)]
    )
    assert result is not None
    assert not any("UPDATE users SET" in sql for sql, _ in calls)
    assert not any("INSERT INTO bot_config" in sql for sql, _ in calls)


def test_ceremony_uses_atomic_award_grant():
    import main

    content = Path(main.__file__).read_text(encoding="utf-8")
    start = content.index("async def announce_weekly_mmr_winner")
    end = content.index("async def claim_or_check_mmr_leader", start)
    ceremony = content[start:end]
    assert "grant_weekly_mmr_awards" in ceremony
    assert "increment_weekly_mmr_award" not in ceremony
    assert "tag_set = await add_user_tag" in ceremony


def test_startup_uses_full_weekly_reset():
    import main

    content = Path(main.__file__).read_text(encoding="utf-8")
    assert "await weekly_mmr_reset_job(SimpleNamespace(bot=app.bot))" in content
    assert "Startup: weekly stats reset for" not in content


def test_startup_has_monday_champion_catchup():
    import main

    content = Path(main.__file__).read_text(encoding="utf-8")
    assert "Понедельник после 9:00 MSK" in content
    assert "weekly champion catch-up announced on Monday startup" in content



def test_weekly_top1_has_display_priority():
    from tags import TAG_PRIORITY

    assert TAG_PRIORITY["weekly_top1"] > TAG_PRIORITY["weekly_top2"]
    assert TAG_PRIORITY["weekly_top2"] > TAG_PRIORITY["weekly_top3"]
    assert TAG_PRIORITY["weekly_mvp"] > TAG_PRIORITY["weekly_top1"]


def test_tag_persistence_survives_telegram_failure(monkeypatch):
    import asyncio
    import tags

    saved = []
    monkeypatch.setattr(tags, "get_user_tags", lambda uid: [])
    monkeypatch.setattr(tags, "_save_user_tags", lambda uid, values: saved.append(list(values)))

    async def reject(bot, uid, chat_id):
        return False

    monkeypatch.setattr(tags, "_apply_best_tag", reject)
    added = asyncio.run(tags.add_user_tag(1, "F1", bot=object(), chat_id=10))
    assert added is False
    assert saved[-1] == ["F1"]

    monkeypatch.setattr(tags, "get_user_tags", lambda uid: ["F1"])
    removed = asyncio.run(tags.remove_user_tag(1, "F1", bot=object(), chat_id=10))
    assert removed is True
    assert saved[-1] == []
