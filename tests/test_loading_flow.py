"""Tests for the unified typed loading flow (loading_flow.py).

Covered:
  1. The label is typed chunk by chunk and then left in place - no spinner.
  2. Every frame differs from the previous one, so Telegram never answers
     "message is not modified".
  3. stop_loading() / delete_loading() cancel the typing task, so a deleted
     message is no longer edited.
  4. A message that vanished on its own stops the loop instead of raising.
  5. Send failure degrades to a falsy handle instead of crashing the handler.

The project has no pytest-asyncio, so async tests use asyncio.run like the rest
of the suite.
"""

import asyncio
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import loading_flow  # noqa: E402
from loading_flow import (  # noqa: E402
    LOADING_ICON,
    TYPED_LABEL,
    delete_loading,
    show_loading,
    stop_loading,
    stop_loading_by_id,
)


class _Msg:
    def __init__(self, message_id, chat_id):
        self.message_id = message_id
        self.chat_id = chat_id


class _Bot:
    """Minimal telegram.Bot stand-in that records every edit and delete."""

    def __init__(self, chat_id=1, gone_after=None, gone_error=None):
        self.chat_id = chat_id
        self.sent = []
        self.edits = []
        self.deletes = []
        self.gone_after = gone_after
        self.gone_error = gone_error or "Bad Request: message to edit not found"

    async def send_message(self, chat_id, text, parse_mode=None):
        self.sent.append(text)
        return _Msg(1000 + len(self.sent), chat_id)

    async def edit_message_text(self, chat_id, message_id, text, parse_mode=None):
        if self.gone_after is not None and len(self.edits) >= self.gone_after:
            raise RuntimeError(self.gone_error)
        self.edits.append(text)
        return _Msg(message_id, chat_id)

    async def delete_message(self, chat_id, message_id):
        self.deletes.append(message_id)
        self.gone_after = 0
        return True


@pytest.fixture(autouse=True)
def _fast_timing(monkeypatch):
    """Zero delays so each typing step costs a single loop iteration."""
    monkeypatch.setattr(loading_flow, "TYPE_INTERVAL", 0)
    monkeypatch.setattr(loading_flow, "MAX_EDIT_SECONDS", 30.0)


async def _spin(iterations=20):
    """Give the typing task `iterations` event-loop turns."""
    for _ in range(iterations):
        await asyncio.sleep(0)


def test_types_label_and_leaves_it_in_place():
    async def run():
        bot = _Bot()
        handle = await show_loading(bot, bot.chat_id, TYPED_LABEL)

        # Short label: sent with the first character already shown.
        assert bot.sent == [f"<b>{LOADING_ICON}{TYPED_LABEL[:1]}</b>"]

        await _spin()
        await stop_loading(handle)

        assert handle.message_id
        # The first typed chunk is skipped: it is what send_message showed, and
        # re-editing identical text makes Telegram reject the edit.
        assert bot.edits[0] == f"<b>{LOADING_ICON}{TYPED_LABEL[:2]}</b>"
        assert bot.sent[0] != bot.edits[0]
        # Every frame leads with the icon and ends up showing the full label.
        assert all(e.startswith(f"<b>{LOADING_ICON}") for e in bot.edits)
        assert bot.edits[-1] == f"<b>{LOADING_ICON}{TYPED_LABEL}</b>"
        # No spinner glyph and no typing cursor anywhere.
        assert not any(c in e for e in [bot.sent[0], *bot.edits] for c in "⠋⠙⠹⠸⠼▌")

    asyncio.run(run())


def test_short_label_is_typed_one_char_at_a_time():
    async def run():
        bot = _Bot()
        handle = await show_loading(bot, bot.chat_id, TYPED_LABEL)
        await _spin()
        await stop_loading(handle)

        frames = [bot.sent[0], *bot.edits]
        typed = [f[len(f"<b>{LOADING_ICON}"):-len("</b>")] for f in frames]
        assert typed == [
            TYPED_LABEL[: n + 1] for n in range(len(TYPED_LABEL))
        ], f"expected one new character per frame, got {typed}"
        assert len(frames) == len(TYPED_LABEL)

    asyncio.run(run())


def test_long_label_types_two_chars_per_frame():
    """A long label would take ~4s at one char per frame, so it chunks."""

    async def run():
        label = "Привязываю аккаунт Dota 2…"
        assert len(label) > loading_flow.SHORT_LABEL_CHARS
        bot = _Bot()
        handle = await show_loading(bot, bot.chat_id, label)
        await _spin(iterations=40)
        await stop_loading(handle)

        frames = [bot.sent[0], *bot.edits]
        assert len(frames) <= len(label) // 2 + 2
        assert frames[-1] == f"<b>{LOADING_ICON}{label}</b>"
        # Growth stays monotonic: each frame reveals strictly more text.
        sizes = [len(f) for f in frames]
        assert sizes == sorted(sizes)
        assert len(set(sizes)) == len(sizes)

    asyncio.run(run())


@pytest.mark.parametrize(
    "label, expected_chunk",
    [
        ("Хукаю...", 1),
        ("Хукаю график...", 2),
        ("Хукаю аналитику...", 2),
        ("Хукаю сравнение с Pro...", 2),
        ("Привязываю аккаунт Dota 2…", 2),
    ],
)
def test_chunk_depends_on_label_length(label, expected_chunk):
    assert loading_flow._chunk_for(label) == expected_chunk


def test_typing_stops_on_its_own():
    """After the label is typed the task must end, not keep editing."""

    async def run():
        bot = _Bot()
        handle = await show_loading(bot, bot.chat_id, TYPED_LABEL)
        await _spin(iterations=30)
        assert handle.stopped, "typing task must finish once the label is complete"

        count = len(bot.edits)
        await _spin()
        assert len(bot.edits) == count
        await stop_loading(handle)

    asyncio.run(run())


def test_frames_differ_from_previous():
    async def run():
        bot = _Bot()
        handle = await show_loading(bot, bot.chat_id, TYPED_LABEL)
        await _spin()
        await stop_loading(handle)
        frames = [bot.sent[0], *bot.edits]
        assert all(a != b for a, b in zip(frames, frames[1:]))

    asyncio.run(run())


def test_stop_loading_silences_animation():
    async def run():
        bot = _Bot()
        handle = await show_loading(bot, bot.chat_id, TYPED_LABEL)
        await _spin(2)
        await stop_loading(handle)

        count = len(bot.edits)
        await _spin()
        assert len(bot.edits) == count
        assert handle.stopped
        # Stopping twice must be safe.
        await stop_loading(handle)

    asyncio.run(run())


def test_delete_loading_stops_typing_before_deleting():
    """Regression: a deleted message must not be edited again afterwards."""

    async def run():
        bot = _Bot()
        handle = await show_loading(bot, bot.chat_id, TYPED_LABEL)
        await _spin(2)
        await delete_loading(bot, handle)

        assert bot.deletes == [handle.message_id]
        count = len(bot.edits)
        await _spin()
        assert len(bot.edits) == count, "typing continued after the message was deleted"

    asyncio.run(run())


def test_delete_loading_is_safe_without_handle():
    async def run():
        bot = _Bot()
        await delete_loading(bot, None)
        assert bot.deletes == []

    asyncio.run(run())


def test_delete_tolerates_already_deleted_message():
    class _Strict(_Bot):
        async def delete_message(self, chat_id, message_id):
            self.deletes.append(message_id)
            raise RuntimeError("Bad Request: message to delete not found")

    async def run():
        bot = _Strict()
        handle = await show_loading(bot, bot.chat_id, TYPED_LABEL)
        await delete_loading(bot, handle)  # must not raise
        assert bot.deletes == [handle.message_id]

    asyncio.run(run())


@pytest.mark.parametrize(
    "error",
    [
        "Bad Request: message to edit not found",
        "Bad Request: message can't be edited",
        "Bad Request: message can't be deleted",
        "Bad Request: message to delete not found",
    ],
)
def test_vanished_message_stops_loop(error):
    async def run():
        bot = _Bot(gone_after=2, gone_error=error)
        handle = await show_loading(bot, bot.chat_id, TYPED_LABEL)
        await _spin()
        assert handle.stopped, f"typing must stop when Telegram says: {error}"
        await stop_loading(handle)

        count = len(bot.edits)
        await _spin()
        assert len(bot.edits) == count

    asyncio.run(run())


def test_not_modified_is_not_treated_as_gone():
    class _Same(_Bot):
        async def edit_message_text(self, chat_id, message_id, text, parse_mode=None):
            self.edits.append(text)
            raise RuntimeError("Bad Request: message is not modified")

    async def run():
        bot = _Same()
        handle = await show_loading(bot, bot.chat_id, TYPED_LABEL)
        await _spin(3)
        await stop_loading(handle)
        assert len(bot.edits) > 1, "typing must continue on 'not modified'"

    asyncio.run(run())


def test_stop_loading_by_id():
    async def run():
        bot = _Bot()
        handle = await show_loading(bot, bot.chat_id, TYPED_LABEL)
        await _spin(2)
        await stop_loading_by_id(bot, bot.chat_id, handle.message_id)

        count = len(bot.edits)
        await _spin()
        assert len(bot.edits) == count

    asyncio.run(run())


def test_send_failure_returns_falsy_handle():
    class _Broken(_Bot):
        async def send_message(self, chat_id, text, parse_mode=None):
            raise RuntimeError("Bad Request: chat not found")

    async def run():
        handle = await show_loading(_Broken(), 5)
        assert not handle
        assert handle.message_id == 0
        await stop_loading(handle)
        await delete_loading(None, handle)

    asyncio.run(run())


def test_icon_never_split_into_broken_surrogates():
    """Emoji are surrogate pairs: a per-frame slice must not cut one in half."""
    label = "Хукаю..."

    async def run():
        bot = _Bot()
        handle = await show_loading(bot, bot.chat_id, label)
        await _spin()
        await stop_loading(handle)

        for frame in [bot.sent[0], *bot.edits]:
            body = frame[len("<b>"):-len("</b>")]
            assert body[0] == LOADING_ICON[0], (
                f"frame must lead with the hook icon: {frame!r}"
            )
            assert not any(0xD800 <= ord(c) <= 0xDFFF for c in body)

    asyncio.run(run())


def test_icon_is_optional():
    async def run():
        bot = _Bot()
        handle = await show_loading(bot, bot.chat_id, TYPED_LABEL, icon="")
        await _spin()
        await stop_loading(handle)
        assert bot.sent == [f"<b>{TYPED_LABEL[:1]}</b>"]

    asyncio.run(run())
