"""Regression tests for Techies damage and explosion outcome.

Bugs covered:
  1. Damage was 4 mines x 1-5 cm = up to 20 cm, which could strip more than
     half of a mid-sized fissure in one event. Capped at 1-3 cm per mine.

  2. `handle_techies_button` picked the result image from
     `button_pressed != explosive_button`, ignoring the timeout branch. A player
     who let the timer run out saw the SUCCESS image together with the
     "BAKAH!" explosion text, plus a "roll again" button that should only
     appear on a clean defuse.

  3. The same function rolled fresh mines instead of using the ones planted
     when the session started, so a game that detonated by button press and a
     game that detonated by timeout could disagree on the damage.
"""

import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import database  # noqa: E402
import techies  # noqa: E402

USER_ID = 555
CHAT_ID = 100


class _FakeChat:
    def __init__(self):
        self.id = CHAT_ID
        self.type = "supergroup"


class _FakeUser:
    def __init__(self):
        self.id = USER_ID
        self.username = "tester"
        self.first_name = "Test"
        self.is_bot = False


class _FakeMessage:
    def __init__(self):
        self.message_id = 4242
        self.chat_id = CHAT_ID
        self.chat = _FakeChat()
        self.from_user = _FakeUser()


class _FakeQuery:
    def __init__(self, data):
        self.data = data
        self.from_user = _FakeUser()
        self.message = _FakeMessage()

    async def answer(self, text=None, show_alert=False):
        return None


class _FakeUpdate:
    def __init__(self, data):
        self.callback_query = _FakeQuery(data)


class _FakeContext:
    def __init__(self):
        self.bot = object()


def _callback(button_pressed, explosive, elapsed_ms):
    ts = int((techies.time.time() - elapsed_ms / 1000.0) * 1000)
    return f"techies_{button_pressed}_{USER_ID}_{explosive}_{ts}"


def _plant(mines, explosive="red"):
    techies._active_techies_sessions[techies._session_key(CHAT_ID, USER_ID)] = {
        "chat_id": CHAT_ID,
        "msg_id": 4242,
        "user_id": USER_ID,
        "explosive_button": explosive,
        "start_time": 0,
        "display_username": "tester",
        "timeout_task": None,
        "mines": list(mines),
    }


def _run(monkeypatch, data, mines, fissure=27.0, explosive="red"):
    """Play one Techies button press and report the outcome."""
    _plant(mines, explosive)

    applied = {}
    sent = {}

    async def fake_send(bot, chat_id, msg_id, text, image_path=None, reply_markup=None):
        sent["text"] = text
        sent["image_path"] = image_path
        sent["reply_markup"] = reply_markup

    monkeypatch.setattr(database, "get_user", lambda uid: {
        "fissure": fissure, "username": "tester",
    })
    monkeypatch.setattr(
        database, "update_user_field",
        lambda uid, field, value: applied.update({field: value}),
    )
    monkeypatch.setattr(database, "add_free_roll", lambda uid, count=1: 1)
    monkeypatch.setattr(techies, "_send_techies_result", fake_send)
    monkeypatch.setattr(techies, "schedule_delete", lambda *a, **k: None)

    asyncio.run(techies.handle_techies_button(_FakeUpdate(data), _FakeContext()))
    return applied, sent


def test_mine_damage_is_capped():
    assert techies.TECHIES_MINE_MAX_DAMAGE == 3
    totals = {sum(techies.generate_mines()) for _ in range(2000)}
    assert min(totals) == 4
    assert max(totals) == 12


def test_timeout_detonation_uses_explosion_image(monkeypatch):
    # Pressed a safe button, but far too late - the mine went off on its own.
    applied, sent = _run(
        monkeypatch, _callback("green", "red", 99_000), [3, 3, 3, 3], explosive="red",
    )

    assert applied["fissure"] == 27.0 - 12
    assert sent["image_path"] == techies.TECHIES_EXPLOSION_URL
    assert "БАБАХ" in sent["text"]


def test_timeout_detonation_offers_no_roll_again(monkeypatch):
    _, sent = _run(
        monkeypatch, _callback("green", "red", 99_000), [1, 1, 1, 1], explosive="red",
    )

    assert sent["reply_markup"] is None


def test_button_detonation_uses_planted_mines(monkeypatch):
    # Hit the explosive button: damage must be the planted mines, not a re-roll.
    applied, sent = _run(
        monkeypatch, _callback("red", "red", 1_000), [1, 1, 1, 1], explosive="red",
    )

    assert applied["fissure"] == 27.0 - 4
    assert sent["image_path"] == techies.TECHIES_EXPLOSION_URL


def test_clean_defuse_shows_success_image_and_keeps_fissure(monkeypatch):
    applied, sent = _run(
        monkeypatch, _callback("green", "red", 1_000), [1, 1, 1, 1], explosive="red",
    )

    assert "fissure" not in applied
    assert sent["image_path"] == techies.TECHIES_SUCCESS_URL
    assert sent["reply_markup"] is not None
