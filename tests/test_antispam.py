"""Regression tests for the anti-spam system (antispam.py).

The original bug: a user who entered the chat and pressed a command 100
times made the bot execute — and answer — all 100 commands, flooding the
chat. The global token bucket in rate_limiter.py could not stop it because
it is not aware of who produced the traffic.

The fix applies the cooldown **per action** and answers a too-fast repeat
with a friendly "не торопись" instead of muting the user — a newcomer must
still be able to try every button.
"""
import asyncio
import time
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from telegram import Chat, Message, MessageEntity, Update, User
from telegram.ext import ApplicationHandlerStop

import antispam
from antispam import Action, SpamGuard

CHAT = Chat(id=-1001, type="supergroup")
USER = User(id=4242, first_name="Spammer", username="spammer", is_bot=False)
BOT = User(id=999, first_name="Fissure", is_bot=True)


def _make_update(user=USER, text="/profile", update_id=1, chat=CHAT):
    entities = None
    if text.startswith("/"):
        entities = [MessageEntity(type="bot_command", offset=0, length=len(text))]
    message = Message(
        message_id=update_id,
        date=datetime.now(),
        chat=chat,
        from_user=user,
        text=text,
        entities=entities,
    )
    return Update(update_id=update_id, message=message)


class _FakeContext:
    def __init__(self):
        self.bot = SimpleNamespace(send_message=_async_none())


def _async_none():
    async def _fn(*args, **kwargs):
        return None

    return _fn


@pytest.fixture(autouse=True)
def _clean_guard():
    antispam.reset_state()
    yield
    antispam.reset_state()


# --- the reported bug ------------------------------------------------------
def test_hundred_identical_commands_do_not_all_execute():
    """Mashing the same command 100 times must not get 100 bot replies."""
    guard = SpamGuard(action_cooldown=4.0)
    action = Action(key="cmd:/profile", label="/profile")

    allowed = sum(1 for _ in range(100) if guard.check(4242, action).allowed)

    assert allowed == 1
    assert allowed < 100


def test_repeating_the_same_action_is_answered_with_a_nudge():
    guard = SpamGuard(action_cooldown=4.0)
    action = Action(key="cmd:/profile", label="/profile", cooldown_override=4.0)
    t = 1000.0

    assert guard.check(1, action, now=t).allowed

    second = guard.check(1, action, now=t + 0.5)
    assert not second.allowed
    assert second.reason == "repeat"
    assert second.retry_after == pytest.approx(3.5)
    assert second.warn is True  # the user is told to wait


def test_different_actions_are_never_blocked():
    """A newcomer must be able to try every button."""
    guard = SpamGuard(action_cooldown=4.0)
    t = 1000.0

    for i, label in enumerate(
        [
            "🎲 Ролл Фиссуры",
            "👤 Профиль",
            "🏆 Топ Фиссур",
            "🏆 Топ MMR",
            "🔎 Аналитика",
            "🔑 Привязать Аккаунт",
            "🎮 Поиск пати",
        ]
    ):
        decision = guard.check(1, Action(key=f"btn:{label}", label=label), now=t + i * 0.1)
        assert decision.allowed, label


def test_action_is_allowed_again_after_the_cooldown():
    guard = SpamGuard(action_cooldown=4.0)
    action = Action(key="cmd:/profile", label="/profile", cooldown_override=4.0)
    t = 1000.0

    assert guard.check(1, action, now=t).allowed
    assert not guard.check(1, action, now=t + 1).allowed
    assert guard.check(1, action, now=t + 4.1).allowed


def test_expensive_commands_have_a_longer_cooldown():
    """/profile hits OpenDota, so it needs a longer breath than the default."""
    action = Action(key="cmd:/profile", label="/profile")
    assert action.cooldown(4.0) == 8.0


def test_nudge_message_is_sent_only_once_in_a_while():
    """The bot must not flood the chat with its own nudges."""
    guard = SpamGuard(action_cooldown=60.0, nudge_cooldown=30.0)
    action = Action(key="cmd:/profile", label="/profile", cooldown_override=60.0)
    t = 1000.0

    guard.check(1, action, now=t)
    assert guard.check(1, action, now=t + 0.1).warn is True
    assert guard.check(1, action, now=t + 0.2).warn is False
    assert guard.check(1, action, now=t + 0.3).warn is False
    # ...but after the nudge cooldown the bot speaks again.
    assert guard.check(1, action, now=t + 31).warn is True

def test_soft_rate_is_a_nudge_not_a_mute():
    """A user firing many different actions is slowed down, never silenced."""
    guard = SpamGuard(action_cooldown=4.0, soft_max_actions=5, soft_window_seconds=10)
    t = 1000.0

    for i in range(5):
        assert guard.check(1, Action(key=f"cmd:/x{i}", label=f"/x{i}"), now=t).allowed

    blocked = guard.check(1, Action(key="cmd:/x5", label="/x5"), now=t)
    assert not blocked.allowed
    assert blocked.reason == "flood"
    assert blocked.warn is True
    # No penalty: the user is not silenced, the action just waits.
    assert not hasattr(blocked, "penalty")

    # Denied attempts do not extend the flood window; once the accepted
    # actions age out, another action is allowed.
    assert guard.check(1, Action(key="cmd:/x6", label="/x6"), now=t + 11).allowed

def test_repeated_blocked_attempts_do_not_extend_flood_window():
    guard = SpamGuard(
        action_cooldown=4.0,
        soft_max_actions=2,
        soft_window_seconds=10,
    )
    t = 1000.0
    assert guard.check(1, Action(key="a", label="a"), now=t).allowed
    assert guard.check(1, Action(key="b", label="b"), now=t + 1).allowed
    assert guard.check(1, Action(key="a", label="a"), now=t + 2).reason == "repeat"
    assert guard.check(1, Action(key="a", label="a"), now=t + 11).allowed


# --- action extraction -----------------------------------------------------
def test_extract_action_for_command():
    action = antispam.extract_action(_make_update(text="/profile"))
    assert action is not None
    assert action.key == "cmd:/profile"
    assert action.label == "/profile"


def test_extract_action_for_menu_button():
    action = antispam.extract_action(_make_update(text="👤 Профиль"))
    assert action is not None
    assert action.key == "btn:👤 Профиль"


def test_extract_action_ignores_ordinary_chat():
    assert antispam.extract_action(_make_update(text="привет, как дела?")) is None


def test_extract_action_ignores_service_messages():
    service = Update(
        update_id=5,
        message=Message(
            message_id=5,
            date=datetime.now(),
            chat=CHAT,
            new_chat_members=(USER,),
        ),
    )
    assert antispam.extract_action(service) is None


# --- the PTB guard ---------------------------------------------------------
def test_guard_handler_blocks_and_stops_the_update():
    antispam.reset_state()
    update = _make_update(update_id=1)
    context = _FakeContext()

    # First command is fine.
    asyncio.run(antispam.guard_handler(update, context))

    # The next one repeats too fast -> the update is cancelled.
    with pytest.raises(ApplicationHandlerStop):
        asyncio.run(antispam.guard_handler(update, context))


def test_guard_lets_the_user_try_another_button_right_away():
    antispam.reset_state()
    context = _FakeContext()

    asyncio.run(antispam.guard_handler(_make_update(text="/profile"), context))

    with pytest.raises(ApplicationHandlerStop):
        asyncio.run(antispam.guard_handler(_make_update(text="/profile"), context))

    # A different action is not blocked at all.
    asyncio.run(antispam.guard_handler(_make_update(text="/top"), context))


def test_guard_ignores_bots():
    assert antispam.check_update(_make_update(user=BOT)) is None


def test_ordinary_chat_is_never_charged():
    antispam.reset_state()
    for i in range(50):
        update = _make_update(text="привет, как дела?", update_id=i)
        assert antispam.check_update(update) is None


# --- the global limiter must not be the anti-spam --------------------------
def test_per_chat_limiter_caps_the_whole_chat():
    """The API limiter is a safety net for the chat, not for the user."""
    from rate_limiter import chat_rate_limiter, rate_limit, telegram_rate_limiter

    chat_rate_limiter.reset()
    telegram_rate_limiter.tokens = float(telegram_rate_limiter.bucket_size)
    telegram_rate_limiter.last_update = time.monotonic()
    executed = 0

    @rate_limit(tokens=1)
    async def handler(update, context):
        nonlocal executed
        executed += 1

    async def run():
        for _ in range(100):
            await handler(_make_update(), None)

    asyncio.run(run())

    # The burst is bounded, so a flood cannot produce 100 replies at once.
    assert executed <= chat_rate_limiter.bucket_size
    assert executed < 100
    chat_rate_limiter.reset()


# --- the moderation gag must actually work ---------------------------------
def test_mute_gag_filter_is_registered_before_the_commands():
    """The gag filter must not be shadowed by another handler of group 0."""
    from pathlib import Path

    main_source = (Path(__file__).resolve().parent.parent / "main.py").read_text(
        encoding="utf-8"
    )
    mute_source = (Path(__file__).resolve().parent.parent / "mute.py").read_text(
        encoding="utf-8"
    )

    # The gag filter lives in its own group, otherwise python-telegram-bot
    # only ever runs the first matching handler of a group (menu_handler).
    assert "callback=on_message, block=True), group=-1" in mute_source
    # And it has to be registered before the group 0 handlers.
    assert main_source.index("register_mute_handlers(app)") < main_source.index(
        'app.add_handler(CommandHandler("start", start))'
    )


def test_do_give_gag_accepts_the_arguments_its_callers_pass():
    """Regression: the signature did not match the call sites (/mute was dead)."""
    import inspect

    import mute

    params = inspect.signature(mute._do_give_gag).parameters
    assert "admin" in params
    assert "victim" in params
    assert "target_id" not in params


def test_gagged_user_message_is_deleted_and_command_is_stopped():
    import mute

    deleted = []

    async def _delete():
        deleted.append(True)

    message = SimpleNamespace(delete=_delete)
    update = SimpleNamespace(
        effective_message=message,
        effective_user=SimpleNamespace(id=4242),
        effective_chat=SimpleNamespace(id=-1001, type="supergroup"),
    )

    mute._gagged_users[4242] = datetime.now() + timedelta(seconds=30)
    try:
        context = _FakeContext()
        context.bot.get_chat_member = _async_none()

        with pytest.raises(ApplicationHandlerStop):
            asyncio.run(mute.on_message(update, context))

        assert deleted, "the gagged message must be deleted"
    finally:
        mute._gagged_users.pop(4242, None)


def test_gag_does_not_stop_commands_of_normal_users():
    import mute

    update = SimpleNamespace(
        effective_message=SimpleNamespace(delete=_async_none()),
        effective_user=SimpleNamespace(id=4243),
        effective_chat=SimpleNamespace(id=-1001, type="supergroup"),
    )
    context = _FakeContext()
    context.bot.get_chat_member = _async_none()

    asyncio.run(mute.on_message(update, context))  # must not raise
