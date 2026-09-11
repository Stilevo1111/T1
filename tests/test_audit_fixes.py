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
