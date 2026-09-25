"""Tests for the unified animated loading flow (loading_flow.py).

Covered:
  1. The label is typed chunk by chunk, then the spinner keeps running.
  2. Every frame is distinct, so Telegram never answers "message is not modified".
  3. stop_loading() cancels the animation: no edits arrive after the result.
  4. A deleted message stops the loop instead of raising.
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
    CURSOR,
    FRAMES,
    TYPED_LABEL,
    show_loading,
    stop_loading,
    stop_loading_by_id,
)


class _Msg:
    def __init__(self, message_id, chat_id):
        self.message_id = message_id
        self.chat_id = chat_id


class _Bot:
    """Minimal telegram.Bot stand-in that records every edit."""

    def __init__(self, chat_id=1, deleted_after=None):
        self.chat_id = chat_id
        self.sent = []
        self.edits = []
        self.deleted_after = deleted_after

    async def send_message(self, chat_id, text, parse_mode=None):
        self.sent.append(text)
        return _Msg(1000 + len(self.sent), chat_id)

    async def edit_message_text(self, chat_id, message_id, text, parse_mode=None):
        if self.deleted_after is not None and len(self.edits) >= self.deleted_after:
            raise RuntimeError("Bad Request: message to edit not found")
        self.edits.append(text)
        return _Msg(message_id, chat_id)


@pytest.fixture(autouse=True)
def _fast_timing(monkeypatch):
    """Zero delays so each animation step costs a single loop iteration."""
    monkeypatch.setattr(loading_flow, "TYPE_INTERVAL", 0)
    monkeypatch.setattr(loading_flow, "SPIN_INTERVAL", 0)
    monkeypatch.setattr(loading_flow, "MAX_EDIT_SECONDS", 30.0)


async def _spin(iterations=20):
    """Give the animation task `iterations` event-loop turns."""
    for _ in range(iterations):
        await asyncio.sleep(0)


def test_types_label_then_spins():
    async def run():
        bot = _Bot()
        handle = await show_loading(bot, bot.chat_id, TYPED_LABEL)

        assert bot.sent == [f"<b>{TYPED_LABEL[:1]}{CURSOR}</b>"]

        await _spin()
        await stop_loading(handle)

        assert handle.message_id
        assert len(bot.edits) >= 2
        # Growing prefix while typing...
        assert bot.edits[0] == f"<b>{TYPED_LABEL[:2]}{CURSOR}</b>"
        assert bot.edits[1] == f"<b>{TYPED_LABEL[:4]}{CURSOR}</b>"
        # ...then the spinner takes over with the full label.
        assert f"<b>{TYPED_LABEL}</b>" not in bot.edits
        spinner_frames = {f"<b>{f} {TYPED_LABEL}</b>" for f in FRAMES}
        assert spinner_frames & set(bot.edits)

    asyncio.run(run())


def test_frames_are_unique():
    """Telegram rejects an edit that does not change the text.

    The spinner cycles through FRAMES, so only *consecutive* frames must differ.
    """

    async def run():
        bot = _Bot()
        handle = await show_loading(bot, bot.chat_id, TYPED_LABEL)
        await _spin(iterations=len(FRAMES) * 3)
        await stop_loading(handle)
        assert len(bot.edits) > len(FRAMES)
        assert all(a != b for a, b in zip(bot.edits, bot.edits[1:]))

    asyncio.run(run())


def test_stop_loading_silences_animation():
    async def run():
        bot = _Bot()
        handle = await show_loading(bot, bot.chat_id, TYPED_LABEL)
        await _spin()
        await stop_loading(handle)

        count = len(bot.edits)
        await _spin()
        assert len(bot.edits) == count
        assert handle.stopped
        # Stopping twice must be safe.
        await stop_loading(handle)

    asyncio.run(run())


def test_deleted_message_stops_loop():
    async def run():
        bot = _Bot(deleted_after=2)
        handle = await show_loading(bot, bot.chat_id, TYPED_LABEL)
        await _spin()
        assert handle.stopped, "animation must stop once the message is gone"
        await stop_loading(handle)

        count = len(bot.edits)
        await _spin()
        assert len(bot.edits) == count

    asyncio.run(run())


def test_stop_loading_by_id():
    async def run():
        bot = _Bot()
        handle = await show_loading(bot, bot.chat_id, TYPED_LABEL)
        await _spin()
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

    asyncio.run(run())
