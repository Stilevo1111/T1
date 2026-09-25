"""Tests for the Fissure roll flow.

The roll posts its banner first and types the result into the picture caption,
in the background, with no separate loading message. Multicast posts the same
banner but types nothing, and Techies keeps its own flow untouched.

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


def test_roll_posts_picture_then_types_caption():
    """The roll has no separate loading message: the picture comes first and
    its caption is typed underneath it."""
    content = _source()
    assert "show_photo_with_typing(" in content
    assert "🎲 Хукаю кости..." in content
    # No separate "Подбрасываю кости..." message for the roll any more.
    assert "Подбрасываю кости" not in content


def test_multicast_has_no_typing():
    """Multicast must show only the final banner, nothing is typed."""
    content = _source()
    assert 'label=("" if is_multicast else "🎲 Хукаю кости..."),' in content


def test_roll_has_no_orphan_loading_message():
    """The roll posts the picture directly, so there is no loading message
    that a failed banner could leave stranded in the chat."""
    content = _source()
    assert "anim_msg" not in content
    assert "delete_loading" not in content


def test_roll_falls_back_to_a_plain_message():
    """If the banner cannot be posted, the roll must still reach the chat."""
    content = _source()
    assert "if result_msg is None:" in content
    assert "Could not send roll banner" in content


def test_techies_flow_is_untouched():
    content = _source()
    techies_branch = content[content.index("handle_techies_event("):]
    assert "show_loading" not in techies_branch.split("return")[0]
    # Techies keeps its own animation in techies.py.
    assert "handle_techies_event(" in content


def test_multicast_falls_back_to_a_plain_banner():
    """With no loading handle, finish_loading must be a no-op, not an error."""
    import loading_flow

    async def run():
        bot = _Bot()
        result = await loading_flow.finish_loading(
            bot, None, text="Мультикаст ×3", media="roll_fatal.webp"
        )
        assert result is None
        assert not bot.media_edits
        assert not bot.deletes

    asyncio.run(run())


def _roll_with_caption(caption, label="", media="roll_normal.webp", **kw):
    """Post a roll picture and let its caption finish typing.

    Returns the bot stub and the message. `bot.at_return` is a snapshot of the
    caption edits recorded by the moment the caller got control back, which is
    what proves the typing does not block the roll handler.
    """
    bot = _Bot()
    interval = loading_flow.TYPE_INTERVAL
    loading_flow.TYPE_INTERVAL = 0.0

    async def run():
        msg = await loading_flow.show_photo_with_typing(
            bot, 1, media=media, caption=caption, label=label, **kw
        )
        bot.at_return = list(bot.caption_edits)
        # Drain the background animation inside this same loop, since the task
        # belongs to the loop that created it.
        while loading_flow._typing_tasks:
            await asyncio.gather(*list(loading_flow._typing_tasks))
        return msg

    try:
        msg = asyncio.run(run())
    finally:
        loading_flow.TYPE_INTERVAL = interval
    return bot, msg


def test_photo_appears_first_then_caption_is_typed():
    caption = "🎲 TestUser\n\nПроклял Акадо на 12 см!\n\n📏 41.2 см → 29.2 см"
    bot, msg = _roll_with_caption(
        caption, label="🎲 Хукаю кости...", reply_markup="markup"
    )

    assert msg is not None
    # The picture is posted first, carrying only the label as its caption.
    assert bot.photos[0][0] == "roll_normal.webp"
    assert bot.photos[0][1] == "<b>🎲 Хукаю кости...</b>"

    # The handler got control back before any typing happened, so the database
    # write and cooldown are not stuck behind a three second animation.
    assert bot.at_return == []

    # The caption is then typed out, growing until it is complete.
    assert bot.caption_edits, "caption must be typed after the picture"
    for a, b in zip(bot.caption_edits, bot.caption_edits[1:]):
        assert len(b) >= len(a), "caption must never shrink"
    assert bot.caption_edits[-1] == caption


def test_photo_caption_typing_without_label_starts_empty():
    """Multicast passes no label: the picture shows with an ellipsis caption."""
    bot, _ = _roll_with_caption("Мультикаст ×3", label="", media="roll_fatal.webp")
    assert bot.photos[0][1] == "…"
    assert bot.caption_edits[-1] == "Мультикаст ×3"


def test_caption_frames_never_split_emoji_or_html():
    """Frames are plain text, so no frame can cut a tag or an emoji in half."""
    caption = "<b>🎲 TestUser</b>\n\nПроклял Акадо на 12 см!\n📏 41 см"
    bot, _ = _roll_with_caption(caption, parse_mode="HTML")

    # Every frame before the last is tag-free and free of lone surrogates.
    for text in bot.caption_edits[:-1]:
        assert "<b>" not in text
        assert not any("\ud800" <= c <= "\udfff" for c in text)
    # The last frame is the real, formatted caption.
    assert bot.caption_edits[-1] == caption


def test_photo_send_failure_returns_none():
    class _NoPhoto(_Bot):
        async def send_photo(self, chat_id, photo, caption=None, parse_mode=None,
                             reply_markup=None):
            raise RuntimeError("Bad Request: chat not found")

    async def run():
        bot = _NoPhoto()
        result = await loading_flow.show_photo_with_typing(
            bot, 1, media="x.webp", caption="text"
        )
        assert result is None
        assert not bot.caption_edits

    asyncio.run(run())


def test_zeus_uses_loading_too():
    content = _source()
    assert "⚡ Гремит гром..." in content
    assert "show_photo_with_typing(" in content


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
        self.photos = []
        self.caption_edits = []
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

    async def send_photo(self, chat_id, photo, caption=None, parse_mode=None,
                         reply_markup=None):
        self.photos.append((photo, caption))
        return _Msg(500, chat_id)

    async def edit_message_caption(self, chat_id, message_id, caption,
                                   parse_mode=None):
        self.caption_edits.append(caption)
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
