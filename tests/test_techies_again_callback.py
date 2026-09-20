"""Regression tests for the Techies "🎲 Ещё один ролл!" callback
(callback_data = "techies_again_<user_id>").

Bugs covered:
  1. The generic `data.startswith("techies_")` branch used to swallow
     "techies_again_<id>" before it could reach fissure(), because
     handle_techies_button() expects >= 5 underscore-separated parts.
  2. fissure() reads `update.effective_message`, so every synthetic update built
     inside button_callback must expose that attribute (otherwise the real
     python-telegram-bot Update triggers AttributeError).
"""

import asyncio
import sys
import types
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import database  # noqa: E402
import main  # noqa: E402
import techies  # noqa: E402

USER_ID = 555


class _FakeChat:
    def __init__(self, chat_id, chat_type):
        self.id = chat_id
        self.type = chat_type


class _FakeUser:
    def __init__(self, user_id):
        self.id = user_id
        self.is_bot = False
        self.first_name = "Test"
        self.username = "tester"
        self.last_name = None
        self.language_code = "ru"


class _FakeMessage:
    def __init__(self, chat_id, chat_type):
        self.message_id = 4242
        self.chat_id = chat_id
        self.chat = _FakeChat(chat_id, chat_type)
        self.from_user = _FakeUser(USER_ID)


class _FakeCallbackQuery:
    def __init__(self, data, chat_id, chat_type):
        self.data = data
        self.from_user = _FakeUser(USER_ID)
        self.message = _FakeMessage(chat_id, chat_type)
        self.answers = []

    async def answer(self, text=None, show_alert=False):
        self.answers.append((text, show_alert))

    async def edit_message_text(self, *args, **kwargs):
        return None


class _FakeUpdate:
    def __init__(self, data, chat_id=100, chat_type="supergroup"):
        self.update_id = 77
        self.callback_query = _FakeCallbackQuery(data, chat_id, chat_type)
        self.effective_chat = self.callback_query.message.chat
        self.effective_user = self.callback_query.from_user


class _FakeContext:
    def __init__(self):
        self.bot = types.SimpleNamespace()
        self.job_queue = None


def _patch_handlers(monkeypatch, calls):
    async def fake_fissure(update, context):
        calls["fissure"].append(update)

    async def fake_techies(update, context, record_recent_fissure_roll=None):
        calls["techies"].append(update)

    monkeypatch.setattr(main, "fissure", fake_fissure)
    monkeypatch.setattr(techies, "handle_techies_button", fake_techies)


def test_techies_again_branch_precedes_generic_techies_branch():
    """Order guard: the specific branch must be checked before the generic one."""
    src = (PROJECT_ROOT / "main.py").read_text(encoding="utf-8")
    assert src.index('data.startswith("techies_again_")') < src.index('data.startswith("techies_")')


def test_techies_again_rolls_fissure(monkeypatch):
    calls = {"fissure": [], "techies": []}
    _patch_handlers(monkeypatch, calls)
    update = _FakeUpdate(f"techies_again_{USER_ID}")

    asyncio.run(main.button_callback(update, _FakeContext()))

    assert len(calls["fissure"]) == 1, "fissure() must be called for techies_again_"
    assert calls["techies"] == [], "generic techies handler must not swallow techies_again_"

    synthetic = calls["fissure"][0]
    assert synthetic.effective_message is not None
    assert synthetic.effective_message.text == "/fissure"
    assert synthetic.effective_chat.id == 100
    assert synthetic.effective_chat.type == "supergroup"
    assert synthetic.effective_user.id == USER_ID
    assert update.callback_query.answers == [("🎲 Запускаю ещё один ролл!", False)]


def test_techies_again_rejects_foreign_user(monkeypatch):
    """The button is bound to one user id — others get an alert, not a free roll."""
    calls = {"fissure": [], "techies": []}
    _patch_handlers(monkeypatch, calls)
    update = _FakeUpdate(f"techies_again_{USER_ID + 1}")

    asyncio.run(main.button_callback(update, _FakeContext()))

    assert calls["fissure"] == []
    assert update.callback_query.answers == [("🧨 Это не твоя мина, бродяга!", True)]


def test_generic_techies_button_still_reaches_handler(monkeypatch):
    calls = {"fissure": [], "techies": []}
    _patch_handlers(monkeypatch, calls)
    update = _FakeUpdate(f"techies_{USER_ID}_2_1700000000000")

    asyncio.run(main.button_callback(update, _FakeContext()))

    assert len(calls["techies"]) == 1
    assert calls["fissure"] == []


def test_roll_fissure_menu_button_exposes_effective_message(monkeypatch):
    """Synthetic update for the menu button must also carry effective_message."""
    calls = {"fissure": [], "techies": []}
    _patch_handlers(monkeypatch, calls)
    # the branch does `from database import get_user` at call time
    monkeypatch.setattr(
        database, "get_user",
        lambda telegram_id, username=None: {
            "telegram_id": telegram_id, "username": username, "fissure": 1.0, "free_rolls": 0,
        },
    )
    update = _FakeUpdate("roll_fissure")

    asyncio.run(main.button_callback(update, _FakeContext()))

    assert len(calls["fissure"]) == 1
    assert calls["fissure"][0].effective_message.text == "/fissure"


def test_fissure_module_uses_effective_message_only():
    """fissure() must not depend on update.message / is not a callback-only handler."""
    src = (PROJECT_ROOT / "fissure.py").read_text(encoding="utf-8")
    assert "update.message" not in src
    assert "msg = update.effective_message" in src
