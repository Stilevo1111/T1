"""End-to-end test of the anti-spam guard inside a real PTB Application.

This reproduces the reported bug: a user who entered the chat and pressed a
command 100 times made the bot execute — and answer — all 100 commands.
"""
import asyncio
from datetime import UTC, datetime

import pytest
from telegram import Chat, Message, MessageEntity, Update, User
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

import antispam
from rate_limiter import chat_rate_limiter

CHAT = Chat(id=-100777, type="supergroup")
SPAMMER = User(id=555001, first_name="Masha", username="masha", is_bot=False)
OTHER = User(id=555002, first_name="Petr", username="petr", is_bot=False)

TOKEN = "123456:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"

MENU_BUTTONS = [
    "🎲 Ролл Фиссуры",
    "👤 Профиль",
    "🏆 Топ Фиссур",
    "🏆 Топ MMR",
    "🔎 Аналитика",
    "🔑 Привязать Аккаунт",
    "🎮 Поиск пати",
]


def _command_update(user, text="/profile", update_id=1, bot=None):
    entities = None
    if text.startswith("/"):
        entities = [MessageEntity(type="bot_command", offset=0, length=len(text))]
    message = Message(
        message_id=update_id,
        date=datetime.now(UTC),
        chat=CHAT,
        from_user=user,
        text=text,
        entities=entities,
    )
    if bot is not None:
        message.set_bot(bot)
    return Update(update_id=update_id, message=message)


@pytest.fixture(autouse=True)
def _clean():
    antispam.reset_state()
    chat_rate_limiter.reset()
    yield
    antispam.reset_state()
    chat_rate_limiter.reset()


def _build_app(executed):
    app = ApplicationBuilder().token(TOKEN).build()
    app._initialized = True
    # Pretend the bot is initialized — no network access in tests.
    app.bot._bot_user = User(id=999, first_name="Fissure", username="fissure_bot", is_bot=True)

    async def command(update, context):
        executed.append(update.effective_user.id)

    # Exactly how main.py wires it: the guard goes first, in its own group.
    app.add_handler(MessageHandler(filters.ALL, antispam.guard_handler), group=-2)
    app.add_handler(CallbackQueryHandler(antispam.guard_handler), group=-2)
    app.add_handler(CommandHandler("profile", command))
    # The reply-keyboard buttons go through menu_handler in the real bot.
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, command))
    return app


def test_spammer_cannot_make_the_bot_answer_every_command():
    executed = []
    app = _build_app(executed)

    async def scenario():
        for i in range(100):
            await app.process_update(_command_update(SPAMMER, update_id=i, bot=app.bot))

    asyncio.run(scenario())

    # 100 presses of the same command -> a single answer.
    assert len(executed) == 1
    assert len(executed) < 100


def test_three_fast_presses_get_only_one_answer():
    executed = []
    app = _build_app(executed)

    async def scenario():
        for i in range(3):
            await app.process_update(_command_update(SPAMMER, update_id=i, bot=app.bot))

    asyncio.run(scenario())

    assert len(executed) == 1


def test_a_newcomer_can_try_every_button():
    """Exploring the bot must never be punished."""
    executed = []
    app = _build_app(executed)

    async def scenario():
        for i, label in enumerate(MENU_BUTTONS):
            update = _command_update(SPAMMER, text=label, update_id=i, bot=app.bot)
            await app.process_update(update)

    asyncio.run(scenario())

    # Every different button went through.
    assert len(executed) == len(MENU_BUTTONS)


def test_repeating_a_button_is_nudged_but_other_buttons_still_work():
    executed = []
    app = _build_app(executed)

    async def scenario():
        await app.process_update(_command_update(SPAMMER, text="👤 Профиль", update_id=1, bot=app.bot))
        await app.process_update(_command_update(SPAMMER, text="👤 Профиль", update_id=2, bot=app.bot))
        await app.process_update(_command_update(SPAMMER, text="🏆 Топ Фиссур", update_id=3, bot=app.bot))

    asyncio.run(scenario())

    # The repeat was skipped, the other button went through.
    assert len(executed) == 2


def test_one_spammer_does_not_block_other_users():
    executed = []
    app = _build_app(executed)

    async def scenario():
        for i in range(100):
            await app.process_update(_command_update(SPAMMER, update_id=i, bot=app.bot))
        await app.process_update(_command_update(OTHER, update_id=1000, bot=app.bot))

    asyncio.run(scenario())

    # The innocent user's command still goes through.
    assert OTHER.id in executed
