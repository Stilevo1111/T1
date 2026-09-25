"""Tests for the Fissure roll flow.

The roll now types a single live message ("Подбрасываю кости...") and then
converts that very message into the result banner. Multicast no longer sends
separate slot messages, and Techies keeps its own flow untouched.

fissure.py cannot be imported here (no redis package), so these tests assert on
the source and on loading_flow, which is where the behaviour lives.
"""

import asyncio
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import loading_flow  # noqa: E402
from loading_flow import finish_loading, show_loading, stop_loading  # noqa: E402

FISSURE_PATH = PROJECT_ROOT / "fissure.py"


def _source():
    return FISSURE_PATH.read_text(encoding="utf-8-sig")


def test_multicast_sends_no_slot_messages():
    """Multicast must not post its own 🎰 slot messages anymore."""
    content = _source()
    assert "slot_msg_ids" not in content
    assert "slot_emojis" not in content
    # The slot line was the only place a bare 🎰 was sent to the chat.
    code = "\n".join(
        line for line in content.splitlines() if not line.lstrip().startswith("#")
    )
    assert "🎰" not in code, "multicast slot messages must be gone"


def test_roll_types_one_live_message():
    content = _source()
    assert 'show_loading(context.bot, chat_id, "Подбрасываю кости...")' in content
    # The result is produced by converting the loading message in place.
    assert "finish_loading(" in content


def test_fallback_deletes_the_loading_message():
    """If the banner cannot replace the loading, it must not be left behind."""
    content = _source()
    assert "delete_loading(context.bot, anim_msg)" in content


def test_techies_flow_is_untouched():
    content = _source()
    techies_branch = content[content.index("handle_techies_event("):]
    assert "show_loading" not in techies_branch.split("return")[0]
    # Techies keeps its own animation in techies.py.
    assert "handle_techies_event(" in content


def test_zeus_uses_loading_too():
    content = _source()
    assert 'show_loading(context.bot, chat_id, "Гремит гром...")' in content
    assert "loading=zeus_loading" in content


# --- finish_loading behaviour -------------------------------------------------


class _Msg:
    def __init__(self, message_id, chat_id):
        self.message_id = message_id
        self.chat_id = chat_id


class _Bot:
    """Bot stub that records edits; media conversion is opt-in."""

    def __init__(self, supports_media=True):
        self.sent = []
        self.edits = []
        self.media_edits = []
        self.markup_edits = []
        self.deletes = []
        self.supports_media = supports_media

    async def send_message(self, chat_id, text, parse_mode=None):
        self.sent.append(text)
        return _Msg(100 + len(self.sent), chat_id)

    async def edit_message_text(self, chat_id, message_id, text, parse_mode=None,
                                reply_markup=None):
        self.edits.append(text)
        return _Msg(message_id, chat_id)

    async def edit_message_media(self, chat_id, message_id, media):
        if not self.supports_media:
            raise RuntimeError("Bad Request: unsupported media")
        self.media_edits.append(media)
        return _Msg(message_id, chat_id)

    async def edit_message_reply_markup(self, chat_id, message_id, reply_markup):
        self.markup_edits.append(reply_markup)
        return _Msg(message_id, chat_id)

    async def delete_message(self, chat_id, message_id):
        self.deletes.append(message_id)
        return True


@pytest.fixture(autouse=True)
def _fast(monkeypatch):
    monkeypatch.setattr(loading_flow, "TYPE_INTERVAL", 0)
    monkeypatch.setattr(loading_flow, "MAX_EDIT_SECONDS", 30.0)


def test_finish_loading_converts_message_into_banner():
    async def run():
        bot = _Bot()
        handle = await show_loading(bot, 1, "Подбрасываю кости...")
        for _ in range(5):
            await asyncio.sleep(0)

        result = await finish_loading(
            bot, handle, text="Проклял на 12 см", media="banner.webp",
            reply_markup="markup",
        )

        assert result is not None
        assert bot.media_edits, "result must be an in-place media conversion"
        assert not bot.deletes, "the loading message must be reused, not deleted"
        caption = bot.media_edits[0].caption
        assert caption == "Проклял на 12 см"
        assert bot.markup_edits == ["markup"]
        assert handle.stopped

    asyncio.run(run())


def test_finish_loading_falls_back_to_text():
    async def run():
        bot = _Bot()
        handle = await show_loading(bot, 1, "Хукаю...")
        for _ in range(3):
            await asyncio.sleep(0)

        result = await finish_loading(bot, handle, text="готово", media=None)

        assert result is not None
        assert bot.edits[-1] == "готово"
        assert not bot.media_edits

    asyncio.run(run())


def test_finish_loading_returns_none_when_media_fails():
    """Caller must be able to fall back to a fresh message."""
    async def run():
        bot = _Bot(supports_media=False)
        handle = await show_loading(bot, 1, "Хукаю...")
        for _ in range(3):
            await asyncio.sleep(0)

        result = await finish_loading(bot, handle, text="готово", media="banner.webp")
        assert result is None
        assert handle.stopped, "typing must stop even when the conversion fails"

    asyncio.run(run())


def test_finish_loading_without_handle_is_noop():
    async def run():
        bot = _Bot()
        assert await finish_loading(bot, None, text="x") is None
        assert not bot.edits

    asyncio.run(run())


def test_finish_loading_stops_typing_before_editing():
    """No typing frame may land after the result is written."""
    async def run():
        bot = _Bot()
        handle = await show_loading(bot, 1, "Подбрасываю кости...")
        for _ in range(2):
            await asyncio.sleep(0)

        await finish_loading(bot, handle, text="готово")
        count = len(bot.edits)
        for _ in range(5):
            await asyncio.sleep(0)

        assert len(bot.edits) == count
        await stop_loading(handle)

    asyncio.run(run())
