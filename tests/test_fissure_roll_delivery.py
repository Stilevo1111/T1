"""Delivered-roll tests: what actually lands in the chat.

test_fissure_roll_flow.py asserts on the source text. These tests run the real
fissure.fissure() handler against a stubbed bot and stubbed storage, and check
the message the user receives: one banner carrying the complete caption, with no
typing animation and no follow-up messages.

redis is a declared dependency (requirements.txt), so fissure.py imports here.
If the environment cannot import it, the module is skipped instead of failing.
"""

import asyncio
import re
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

try:
    import fissure
except ImportError as exc:  # pragma: no cover - environment dependent
    pytest.skip(f"fissure.py dependencies are missing: {exc}", allow_module_level=True)


CAPTION_LIMIT = 1024  # Telegram refuses longer photo captions


# --- Telegram stubs -----------------------------------------------------------


class _Msg:
    def __init__(self, message_id, chat_id):
        self.message_id = message_id
        self.chat_id = chat_id


class _Chat:
    def __init__(self, chat_id, chat_type="private"):
        self.id = chat_id
        self.type = chat_type


class _User:
    def __init__(self, user_id=42, username="TestUser"):
        self.id = user_id
        self.username = username
        self.first_name = "Test"
        self.last_name = None


class _Message:
    def __init__(self, chat):
        self.chat = chat
        self.chat_id = chat.id
        self.message_id = 7
        self.text = "/fissure"


class _Update:
    def __init__(self, user, chat):
        self.effective_user = user
        self.effective_chat = chat
        self.effective_message = _Message(chat)


class _JobQueue:
    """Enough of the job queue for the digest hook to be a no-op."""

    def get_jobs_by_name(self, name):
        return []

    def run_once(self, *args, **kwargs):
        return _Msg(1, 1)


class _Context:
    def __init__(self, bot):
        self.bot = bot
        self.job_queue = _JobQueue()


class _Bot:
    """Records every message the roll tries to deliver."""

    def __init__(self):
        self.photos = []
        self.messages = []
        self.caption_edits = []
        self._ids = 100

    def _next_id(self):
        self._ids += 1
        return self._ids

    async def send_photo(self, chat_id, photo, caption=None, parse_mode=None,
                         reply_markup=None, **kwargs):
        if caption is not None and len(caption) > CAPTION_LIMIT:
            raise RuntimeError("Bad Request: message caption is too long")
        self.photos.append({
            "chat_id": chat_id,
            "photo": photo,
            "caption": caption,
            "parse_mode": parse_mode,
            "reply_markup": reply_markup,
        })
        return _Msg(self._next_id(), chat_id)

    async def send_message(self, chat_id, text, parse_mode=None,
                           reply_markup=None, **kwargs):
        self.messages.append(text)
        return _Msg(self._next_id(), chat_id)

    async def edit_message_caption(self, *args, **kwargs):
        self.caption_edits.append(kwargs)
        return True

    async def edit_message_text(self, *args, **kwargs):
        self.caption_edits.append(kwargs)
        return True

    async def delete_message(self, *args, **kwargs):
        return True

# --- HTML sanity --------------------------------------------------------------

_TAG_RE = re.compile(r"<[^<>]*>")
_ALLOWED_TAG = re.compile(r'^(?:<a href="tg://user\?id=\d+">|</a>)$')


def _assert_valid_html(caption):
    """The caption must survive parse_mode="HTML" in one piece.

    Telegram only accepts the tags it knows; an unescaped '<', '>' or '&' in the
    text makes it reject the whole caption, which would leave the banner without
    its roll text.
    """
    for tag in _TAG_RE.findall(caption):
        assert _ALLOWED_TAG.match(tag), f"unexpected HTML tag: {tag}"

    visible = _TAG_RE.sub("", caption)
    # Escaped entities are fine; a bare '<', '>' or '&' is not.
    for entity in ("&amp;", "&lt;", "&gt;", "&quot;", "&#39;"):
        visible = visible.replace(entity, "")
    for char in "<>&":
        assert char not in visible, f"unescaped {char!r} in caption text"

    assert caption.count("<a ") == caption.count("</a>"), "unbalanced <a> tag"


# --- Fissure wiring -----------------------------------------------------------


def _stub(monkeypatch, *, roll=12.0, chances=(0.0, 0.0, 0.0), fissure_value=100.0,
          weekend=False):
    """Replace storage, events and randomness with deterministic doubles."""

    async def _noop_async(*args, **kwargs):
        return None

    def _noop(*args, **kwargs):
        return None

    monkeypatch.setattr(fissure, "delete_fissure_user_and_last_messages", _noop_async)
    monkeypatch.setattr(fissure, "handle_techies_event", _noop_async)
    # The anti-spam window is module state; give every run a clean one.
    monkeypatch.setattr(fissure, "_user_fissure_processing", {})
    monkeypatch.setattr(fissure, "is_rate_limited", lambda: False)
    monkeypatch.setattr(fissure, "is_weekend_msk", lambda: weekend)
    monkeypatch.setattr(fissure, "get_event_chances", lambda: chances)
    monkeypatch.setattr(fissure, "calculate_fissure_roll", lambda current: (roll, "", False, False))
    monkeypatch.setattr(fissure, "get_free_rolls", lambda telegram_id: 0)
    monkeypatch.setattr(fissure, "consume_free_roll", _noop)
    monkeypatch.setattr(fissure, "get_user", lambda telegram_id, username=None: {
        "fissure": fissure_value,
        "last_fissure": 0,
        "current_win_streak": 0,
    })
    monkeypatch.setattr(fissure, "update_user_field", _noop)
    monkeypatch.setattr(fissure, "update_fissure", _noop)
    monkeypatch.setattr(fissure, "update_last_message_id", _noop)
    monkeypatch.setattr(fissure, "set_last_bot_message", _noop)
    monkeypatch.setattr(fissure, "add_bot_message", _noop)
    monkeypatch.setattr(fissure, "schedule_delete", _noop)
    monkeypatch.setattr(fissure, "record_recent_fissure_roll", _noop)
    monkeypatch.setattr(fissure, "invalidate_digest_cache", _noop)
    monkeypatch.setattr(fissure, "get_fissure_rank", lambda telegram_id: {"rank": 999})
    monkeypatch.setattr(fissure, "get_banner_path", lambda name: f"{name}.webp")
    monkeypatch.setattr(fissure, "main_menu", lambda: "MENU")
    monkeypatch.setattr(
        fissure, "zeus_strike",
        lambda percent=0.01, exclude_telegram_id=None: (3, 12.5, 500.0),
    )


def _run_roll(monkeypatch, *, user=None, **kwargs):
    """Run one /fissure and return the bot stub, i.e. what the chat received."""
    bot = _Bot()
    context = _Context(bot)
    update = _Update(user or _User(), _Chat(1))
    _stub(monkeypatch, **kwargs)
    asyncio.run(fissure.fissure(update, context))
    return bot


# --- Tests --------------------------------------------------------------------


def test_normal_roll_delivers_banner_with_full_caption(monkeypatch):
    bot = _run_roll(monkeypatch, roll=12.0)

    assert len(bot.photos) == 1, "the roll must post exactly one banner"
    photo = bot.photos[0]
    assert photo["photo"] == "roll_normal.webp"
    assert photo["parse_mode"] == "HTML"
    assert photo["reply_markup"] == "MENU"

    caption = photo["caption"]
    assert caption, "the banner must carry the roll caption"
    assert "📏 100.0 см → 112.0 см" in caption
    assert "TestUser" in caption
    assert 'href="tg://user?id=42"' in caption
    # Username, hero quote/result and the new size are separate paragraphs.
    assert caption.count("\n\n") >= 2
    assert len(caption) <= CAPTION_LIMIT
    _assert_valid_html(caption)

    # The caption is complete on arrival: nothing is typed afterwards.
    assert bot.caption_edits == [], "no caption edits may follow the banner"
    assert bot.messages == [], "no loading/placeholder message may be posted"


def test_multicast_roll_delivers_banner_with_full_caption(monkeypatch):
    # Pin the hidden cascade roll so the multicast branch always reaches x4.
    monkeypatch.setattr(fissure.random, "random", lambda: 0.0)
    bot = _run_roll(monkeypatch, roll=12.0, chances=(1.0, 0.0, 0.0))

    assert len(bot.photos) == 1
    photo = bot.photos[0]
    assert photo["photo"] == "roll_fatal.webp"

    caption = photo["caption"]
    assert "МУЛЬТИКАСТ×4" in caption
    assert "📏 100.0 см → 148.0 см" in caption
    assert len(caption) <= CAPTION_LIMIT
    _assert_valid_html(caption)

    assert bot.caption_edits == []
    assert bot.messages == []


def test_zeus_event_delivers_banner_with_full_caption(monkeypatch):
    bot = _run_roll(monkeypatch, chances=(0.0, 1.0, 0.0))

    assert len(bot.photos) == 1
    photo = bot.photos[0]
    assert photo["photo"] == "zeus.webp"
    assert photo["parse_mode"] == "HTML"

    caption = photo["caption"]
    assert "💀 Все Фиссуры" in caption
    assert "🎁 Ты не пострадал" in caption
    assert "📏" in caption
    assert len(caption) <= CAPTION_LIMIT
    _assert_valid_html(caption)

    assert bot.caption_edits == []
    assert bot.messages == []


def test_roll_caption_escapes_a_hostile_username(monkeypatch):
    """A name with markup characters must not break parse_mode=HTML."""
    bot = _run_roll(monkeypatch, user=_User(username="<b>Evil</b> & Co"))

    caption = bot.photos[0]["caption"]
    _assert_valid_html(caption)
    assert "<b>Evil</b>" not in caption
    assert "Evil" in caption
    assert 'href="tg://user?id=42"' in caption


def test_roll_still_reaches_the_chat_when_the_banner_fails(monkeypatch):
    """A Telegram failure on the banner must not swallow the roll."""

    class _NoPhoto(_Bot):
        async def send_photo(self, chat_id, photo, caption=None, parse_mode=None,
                             reply_markup=None, **kwargs):
            raise RuntimeError("Bad Request: chat not found")

    bot = _NoPhoto()
    _stub(monkeypatch)
    asyncio.run(fissure.fissure(_Update(_User(), _Chat(1)), _Context(bot)))

    assert bot.photos == []
    assert bot.messages, "the roll text must still be delivered as a message"
    assert "📏 100.0 см → 112.0 см" in bot.messages[0]
    assert not bot.messages[0].startswith("❌ Ошибка обработки запроса")


def test_multicast_miss_slot_stays_a_plain_roll(monkeypatch):
    """The x1 cascade is an intentional miss, not a broken multiplier.

    fissure.py keeps x1 as the multicast baseline and skips the weekend bonus
    for it (the `not is_multicast` check). If that ever changes, this test shows
    it was a deliberate decision rather than an accident.
    """
    monkeypatch.setattr(fissure.random, "random", lambda: 0.9)
    bot = _run_roll(monkeypatch, roll=12.0, chances=(1.0, 0.0, 0.0), weekend=True)

    assert len(bot.photos) == 1
    photo = bot.photos[0]
    assert photo["photo"] == "roll_normal.webp", "an x1 miss uses the normal banner"

    caption = photo["caption"]
    assert "МУЛЬТИКАСТ" not in caption, "no multiplier indicator for x1"
    assert "ВЫХОДНОЙ" not in caption, "the weekend bonus skips multicast slots"
    assert "📏 100.0 см → 112.0 см" in caption
    _assert_valid_html(caption)

    assert bot.caption_edits == []
    assert bot.messages == []

