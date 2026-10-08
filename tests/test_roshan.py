"""Tests for the Roshan event (Aegis / Cheese items).

Covers the three things that can silently break this feature:

  1. Schema reachability — init_db() has a fast path that skips all DDL when
     schema_version already matches, so a column added only to the full block
     never appears on an already-deployed database.
  2. Item uniqueness — aegis/cheese exist in a single copy, so grant/consume
     must be atomic. A read-modify-write through the cache would let two Render
     instances hand out the same item, or spend one Aegis twice on one roll.
  3. Whole-row save safety — aegis/cheese must stay out of
     _ALLOWED_USER_FIELDS, otherwise a background job holding a stale snapshot
     reverts a just-awarded item (the bug that made achievements be removed
     from that whitelist in the first place).
"""

import re
import sqlite3
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import database  # noqa: E402
import roshan  # noqa: E402
from constants import ROSHAN_STEAL_TEXTS, ROSHAN_STEAL_WINDOW_SEC  # noqa: E402
from rolls import apply_aegis, apply_cheese, calculate_roshan_reward  # noqa: E402
from stats import get_event_chances, get_roshan_chance  # noqa: E402

BOT_USER_ID = 555000222
OTHER_USER_ID = 555000333


@pytest.fixture
def db_at(tmp_path):
    """Point the database module at a throwaway SQLite file and init the schema."""
    original_url = database.DATABASE_URL

    def _use(path):
        database.DATABASE_URL = "sqlite:///" + str(path).replace("\\", "/")
        database.user_cache.clear()
        database._pool.clear()
        database.init_db()

    yield _use

    database.DATABASE_URL = original_url
    database.user_cache.clear()
    database._pool.clear()


def _columns(path):
    conn = sqlite3.connect(str(path))
    try:
        return [row[1] for row in conn.execute("PRAGMA table_info(users)").fetchall()]
    finally:
        conn.close()


def _raw(path, column, telegram_id=BOT_USER_ID):
    conn = sqlite3.connect(str(path))
    try:
        row = conn.execute(
            f"SELECT {column} FROM users WHERE telegram_id = ?", (telegram_id,)
        ).fetchone()
    finally:
        conn.close()
    return None if row is None else row[0]


# =====================
# PURE FUNCTIONS
# =====================

def test_apply_aegis_absorbs_negative_roll():
    roll, consumed, text = apply_aegis(-20.0)
    assert consumed is True
    assert roll == 0.0
    assert "АЕГИС" in text


def test_apply_aegis_leaves_positive_roll_untouched():
    roll, consumed, text = apply_aegis(12.0)
    assert consumed is False
    assert roll == 12.0
    assert text == ""


def test_apply_aegis_does_not_fire_on_zero():
    roll, consumed, _ = apply_aegis(0.0)
    assert consumed is False
    assert roll == 0.0


def test_apply_cheese_boosts_positive_roll():
    roll, consumed, text = apply_cheese(12.0)
    assert consumed is True
    assert roll == 18.0
    assert "×1.5" in text


def test_apply_cheese_never_boosts_a_negative_roll():
    roll, consumed, _ = apply_cheese(-12.0)
    assert consumed is False
    assert roll == -12.0, "Cheese must not amplify a negative (possibly fatal) roll"


def test_roshan_shares_one_scale_with_the_other_unique_rolls():
    """Рошан — первое звено общей шкалы, а не отдельный бросок.

    Порядок прежний, но теперь все уникальные роллы выбираются одним
    броском: иначе шансы событий не складывались в одну таблицу и каждый
    жил своим random().
    """
    import inspect

    import fissure as fissure_module

    source = inspect.getsource(fissure_module.fissure)
    assert "roshan_end = get_roshan_chance()" in source
    assert "zeus_end = roshan_end + zeus_chance" in source
    assert "techies_end = zeus_end + techies_chance" in source
    assert "multicast_end = techies_end + multicast_chance" in source
    # Один бросок на всю шкалу: лишнего random() быть не должно.
    assert source.count("event_roll = random.random()") == 1


def test_every_unique_roll_has_the_same_chance():
    """Рошан, Зевс, Техиес и мультикаст выпадают одинаково часто.

    Рошан раньше стоял на отдельном броске с 20% и выпадал вдвое чаще
    остальных — из-за этого события нельзя было сравнить по одному числу.
    """
    roshan = get_roshan_chance()
    multicast, zeus, techies = get_event_chances()
    assert roshan == zeus == techies == multicast, "уникальные роллы должны совпадать"
    assert roshan == pytest.approx(0.10)
    # Обычный ролл остаётся самой частой долей.
    assert 4 * roshan < 1.0


def test_roshan_reward_has_floor_and_cap():
    assert calculate_roshan_reward(0) == 5.0, "new users still get a visible reward"
    assert calculate_roshan_reward(10) == 5.0
    assert calculate_roshan_reward(100) == 8.0
    assert calculate_roshan_reward(400) == 20.0
    assert calculate_roshan_reward(10_000) == 20.0, "cap must stop leaders snowballing"


def test_roshan_reward_never_exceeds_cap():
    for fissure in range(0, 2000, 17):
        assert 5.0 <= calculate_roshan_reward(fissure) <= 20.0


# =====================
# SCHEMA
# =====================

def test_sqlite_schema_has_item_columns(tmp_path, db_at):
    path = tmp_path / "schema.db"
    db_at(path)
    columns = _columns(path)
    assert "aegis" in columns
    assert "cheese" in columns


def test_fast_init_repairs_legacy_db(tmp_path, db_at):
    """schema_version already matches -> init_db takes the short path.

    This is the migration that actually matters in production, because every
    deployed database is already on the current schema_version.
    """
    path = tmp_path / "legacy.db"
    db_at(path)
    database.Database().register_user(BOT_USER_ID, "legacy_tester", "Legacy")

    conn = sqlite3.connect(str(path))
    conn.execute("ALTER TABLE users DROP COLUMN aegis")
    conn.commit()
    conn.close()
    assert "aegis" not in _columns(path)

    database.user_cache.clear()
    database._pool.clear()
    database.init_db()

    assert "aegis" in _columns(path)
    assert _raw(path, "aegis") == 0


def test_items_are_not_in_whole_row_whitelist():
    """A whole-row save must never rewrite the item columns.

    They are written only by their own atomic UPDATE, so a stale snapshot from
    a background job could otherwise silently revert a grant.
    """
    assert "aegis" not in database._ALLOWED_USER_FIELDS
    assert "cheese" not in database._ALLOWED_USER_FIELDS


# =====================
# ITEM LIFECYCLE
# =====================

def test_item_roundtrip(tmp_path, db_at):
    path = tmp_path / "items.db"
    db_at(path)
    database.Database().register_user(BOT_USER_ID, "item_tester", "Item")

    assert database.has_item(BOT_USER_ID, "aegis") is False
    assert database.grant_item(BOT_USER_ID, "aegis") is True
    assert _raw(path, "aegis") == 1, "grant must reach the DB file"

    database.user_cache.clear()
    assert database.has_item(BOT_USER_ID, "aegis") is True
    assert database.get_user(BOT_USER_ID)["aegis"] == 1

    assert database.consume_item(BOT_USER_ID, "aegis") is True
    assert _raw(path, "aegis") == 0


def test_grant_is_idempotent_single_copy(tmp_path, db_at):
    """The second grant must fail: items exist in exactly one copy."""
    path = tmp_path / "once.db"
    db_at(path)
    database.Database().register_user(BOT_USER_ID, "once_tester", "Once")

    assert database.grant_item(BOT_USER_ID, "cheese") is True
    assert database.grant_item(BOT_USER_ID, "cheese") is False
    assert _raw(path, "cheese") == 1, "must still be a single copy"


def test_consume_is_idempotent(tmp_path, db_at):
    """A roll must never spend the same item twice."""
    path = tmp_path / "spend.db"
    db_at(path)
    database.Database().register_user(BOT_USER_ID, "spend_tester", "Spend")
    database.grant_item(BOT_USER_ID, "aegis")

    assert database.consume_item(BOT_USER_ID, "aegis") is True
    assert database.consume_item(BOT_USER_ID, "aegis") is False, "nothing left to spend"
    assert _raw(path, "aegis") == 0


def test_items_are_independent(tmp_path, db_at):
    path = tmp_path / "both.db"
    db_at(path)
    database.Database().register_user(BOT_USER_ID, "both_tester", "Both")

    assert database.grant_item(BOT_USER_ID, "aegis") is True
    assert database.grant_item(BOT_USER_ID, "cheese") is True
    assert _raw(path, "aegis") == 1
    assert _raw(path, "cheese") == 1

    assert database.consume_item(BOT_USER_ID, "aegis") is True
    assert database.has_item(BOT_USER_ID, "aegis") is False
    assert database.has_item(BOT_USER_ID, "cheese") is True


def test_unknown_item_is_rejected(tmp_path, db_at):
    path = tmp_path / "unknown.db"
    db_at(path)
    database.Database().register_user(BOT_USER_ID, "unknown_tester", "Unknown")

    with pytest.raises(ValueError):
        database.grant_item(BOT_USER_ID, "exodia")
    with pytest.raises(ValueError):
        database.consume_item(BOT_USER_ID, "exodia; DROP TABLE users")


def test_items_persist_across_cache_clear(tmp_path, db_at):
    path = tmp_path / "persist.db"
    db_at(path)
    database.Database().register_user(BOT_USER_ID, "persist_tester", "Persist")
    database.grant_item(BOT_USER_ID, "aegis")

    database.user_cache.clear()
    user = database.get_user(BOT_USER_ID)
    assert user["aegis"] == 1
    assert user["cheese"] == 0


# =====================
# ROSHAN SESSIONS
# =====================

def test_roshan_schema_is_created(tmp_path, db_at):
    path = tmp_path / "roshan.db"
    db_at(path)
    roshan.ensure_roshan_schema()

    conn = sqlite3.connect(str(path))
    try:
        tables = {
            r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    finally:
        conn.close()
    assert "roshan_sessions" in tables
    assert "roshan_claimers" in tables


def test_claimer_registers_only_once(tmp_path, db_at):
    """Pressing the button repeatedly must not occupy several slots."""
    path = tmp_path / "claim.db"
    db_at(path)
    roshan.ensure_roshan_schema()
    database.Database().register_user(OTHER_USER_ID, "claimer", "Claimer")

    roshan.create_session("1_2", chat_id=1, msg_id=2, killer_id=BOT_USER_ID,
                          killer_name="killer", reward=8.0)

    assert roshan.add_claimer("1_2", OTHER_USER_ID) is True
    assert roshan.add_claimer("1_2", OTHER_USER_ID) is False
    assert roshan.load_claimers("1_2") == [OTHER_USER_ID]


def test_claim_rejected_after_resolution(tmp_path, db_at):
    path = tmp_path / "closed.db"
    db_at(path)
    roshan.ensure_roshan_schema()
    database.Database().register_user(OTHER_USER_ID, "late", "Late")

    roshan.create_session("1_3", chat_id=1, msg_id=3, killer_id=BOT_USER_ID,
                          killer_name="killer", reward=8.0)
    assert roshan.claim_resolution("1_3") is True
    assert roshan.add_claimer("1_3", OTHER_USER_ID) is False


def test_resolution_happens_exactly_once(tmp_path, db_at):
    """Two Render instances may both resolve; only one may win.

    This is the guard that stops a duplicated Aegis payout.
    """
    path = tmp_path / "once_resolve.db"
    db_at(path)
    roshan.ensure_roshan_schema()

    roshan.create_session("1_4", chat_id=1, msg_id=4, killer_id=BOT_USER_ID,
                          killer_name="killer", reward=8.0)

    assert roshan.claim_resolution("1_4") is True
    assert roshan.claim_resolution("1_4") is False
    assert roshan.claim_resolution("1_4") is False


def test_distribute_gives_every_claimer_one_item(tmp_path, db_at):
    path = tmp_path / "distribute.db"
    db_at(path)
    roshan.ensure_roshan_schema()
    for uid in (BOT_USER_ID, OTHER_USER_ID, 555000444):
        database.Database().register_user(uid, f"u{uid}", f"U{uid}")

    roshan.create_session("1_5", chat_id=1, msg_id=5, killer_id=999,
                          killer_name="killer", reward=8.0)
    for uid in (BOT_USER_ID, OTHER_USER_ID, 555000444):
        roshan.add_claimer("1_5", uid)

    awarded = roshan.distribute_items("1_5")

    assert len(awarded) == 3, "every claimer gets exactly one item"
    all_items = {"aegis", "cheese", "refresher"}
    for uid, items in awarded.items():
        assert len(items) == 1, "each claimer gets exactly one item"
        item = items[0]
        assert item in all_items, f"item must be one of {all_items}"
        assert database.has_item(uid, item) is True
        # Check that claimer doesn't have the other items
        for other in all_items - {item}:
            assert database.has_item(uid, other) is False


def test_distribute_skips_claimers_who_already_hold_all(tmp_path, db_at):
    """A claimer who already holds all 3 items gets nothing."""
    path = tmp_path / "full.db"
    db_at(path)
    roshan.ensure_roshan_schema()
    database.Database().register_user(BOT_USER_ID, "rich", "Rich")
    database.grant_item(BOT_USER_ID, "aegis")
    database.grant_item(BOT_USER_ID, "cheese")
    database.grant_item(BOT_USER_ID, "refresher")

    roshan.create_session("1_6", chat_id=1, msg_id=6, killer_id=999,
                          killer_name="killer", reward=8.0)
    roshan.add_claimer("1_6", BOT_USER_ID)

    awarded = roshan.distribute_items("1_6")
    assert awarded == {}, "nothing to hand out, and nothing is consumed"


def test_unknown_session_loads_as_none(tmp_path, db_at):
    path = tmp_path / "missing.db"
    db_at(path)
    roshan.ensure_roshan_schema()
    assert roshan.load_session("does-not-exist") is None
    assert roshan.load_claimers("does-not-exist") == []


def test_callback_data_fits_telegram_limit():
    """Telegram rejects callback_data over 64 bytes."""
    session_id = f"{1234567890123}_{1789123456.789}"
    keyboard = roshan.build_roshan_keyboard(session_id)
    data = keyboard.inline_keyboard[0][0].callback_data
    assert data == f"roshan_steal_{session_id}"
    assert len(data.encode("utf-8")) <= 64


def test_every_steal_prompt_states_the_window_and_the_lottery():
    """The flavour rotates, the rules must not.

    A variant that dropped the window or the "random item" part would make
    players lose a fair press to bad wording, so both are asserted per line.
    """
    for text in ROSHAN_STEAL_TEXTS:
        assert "{window}" in text, text
        assert re.search(r"случайн|лотере|достанется", text), text


def test_announcement_names_the_items_and_the_steal_prompt():
    text = roshan.build_roshan_text("went_Dr")
    assert "АЕГИС" in text and "СЫР" in text
    assert str(ROSHAN_STEAL_WINDOW_SEC) in text


def test_steal_button_is_labelled_by_the_action():
    # "Своровать", because both items are stealable - the old label said
    # "Украсть АЕГИС" while the button actually handed out the cheese too.
    # It also read "🔓 В яму", naming the place rather than the action.
    keyboard = roshan.build_roshan_keyboard("1_7")
    label = keyboard.inline_keyboard[0][0].text
    assert "Своровать" in label
    assert "🧀" not in label
    assert "🧿" not in label


def test_roshan_emojis_do_not_collide_with_other_mechanics():
    """Roshan owns its emoji set; the classics belong to other events."""
    import pathlib
    import re

    emoji = re.compile(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]")
    src = pathlib.Path(roshan.__file__).parent
    own = set()
    for name in ("roshan.py", "constants.py"):
        text = pathlib.Path(src / name).read_text(encoding="utf-8-sig")
        if name == "constants.py":
            start = text.index("ROSHAN_TEXTS = [")
            end = text.index("# Texts", start)
            text = text[start:end]
        else:
            text = text[text.index("logger = logging"):]
        own |= set(emoji.findall(text))

    assert "🧀" in own, "cheese keeps its emoji by request"
    # ⚡ is Zeus and 🛡 is not ours to take.
    assert "⚡" not in own
    assert "🛡" not in own
    assert "⚔" not in own


# =====================
# WIRING
# =====================

def test_roshan_callback_branch_exists_in_main():
    """The dispatcher must recognise roshan_ prefixes."""
    source = (PROJECT_ROOT / "main.py").read_text(encoding="utf-8-sig")
    assert 'data.startswith("roshan_")' in source
    assert "handle_roshan_button" in source


def test_roshan_schema_is_initialised_on_startup():
    source = (PROJECT_ROOT / "main.py").read_text(encoding="utf-8-sig")
    assert "ensure_roshan_schema" in source


def test_roshan_event_is_rolled_in_fissure():
    source = (PROJECT_ROOT / "fissure.py").read_text(encoding="utf-8-sig")
    assert "get_roshan_chance" in source
    assert "handle_roshan_event" in source
    assert "apply_aegis" in source
    assert "apply_cheese" in source


def test_used_items_appear_in_the_roll_message():
    """The roll text must state that an item was spent."""
    source = (PROJECT_ROOT / "fissure.py").read_text(encoding="utf-8-sig")
    assert "aegis_text" in source
    assert "cheese_text" in source


def test_multicast_chance_was_rebalanced():
    """Roshan has to be paid for somewhere, otherwise plain rolls shrink.

    All four unique rolls sit on one scale at the same 10%, so together they
    take 40% and the plain roll keeps the remaining 60%.
    """
    from constants import (
        MULTICAST_DEFAULT_CHANCE,
        ROSHAN_DEFAULT_CHANCE,
        TECHIES_DEFAULT_CHANCE,
        ZEUS_DEFAULT_CHANCE,
    )
    from stats import get_roshan_chance

    assert get_roshan_chance() == 0.10

    ladder = ZEUS_DEFAULT_CHANCE + TECHIES_DEFAULT_CHANCE + MULTICAST_DEFAULT_CHANCE
    plain_roll = 1 - ROSHAN_DEFAULT_CHANCE - ladder
    assert plain_roll > 0.50, f"plain rolls must stay the majority, got {plain_roll:.3f}"


class _DeadMessageBot:
    """A bot whose message is already gone: every edit raises, as Telegram does.

    Reproduces the reported bug: a second /fissure inside the 45s window used
    to delete the drop message, so the window worker could not edit it and the
    result was swallowed. The result must still reach the group.
    """

    def __init__(self):
        self.sent = []

    async def edit_message_caption(self, **kwargs):
        raise RuntimeError("message to edit not found")

    async def edit_message_text(self, **kwargs):
        raise RuntimeError("message to edit not found")

    async def send_message(self, **kwargs):
        self.sent.append(kwargs)


def test_result_is_sent_as_a_new_message_when_the_drop_is_gone(monkeypatch):
    """The result is not lost just because the original message vanished."""
    import asyncio

    # The DB is reached through asyncio.to_thread, and a SQLite connection
    # cannot cross threads, so the session is stubbed out instead. What is under
    # test is the edit-then-send fallback, not the storage.
    monkeypatch.setattr(roshan, "load_session", lambda sid: {
        "session_id": sid, "chat_id": -100, "msg_id": 4242,
        "killer_id": BOT_USER_ID, "killer_name": "went_Dr", "reward": 12.3,
        "resolved": 0,
    })
    monkeypatch.setattr(roshan, "claim_resolution", lambda sid: True)
    monkeypatch.setattr(roshan, "distribute_items", lambda sid: {OTHER_USER_ID: "aegis"})
    monkeypatch.setattr(roshan, "load_claimers", lambda sid: [OTHER_USER_ID])

    bot = _DeadMessageBot()
    asyncio.run(roshan.resolve_session(bot, "dead_1"))

    assert len(bot.sent) == 1, "result must be posted even if the edit fails"
    assert "went_Dr" in bot.sent[0]["text"]


def test_drop_message_is_not_registered_as_deletable():
    """A roll during the window must not delete the drop.

    set_last_bot_message is a "delete this before the next roll" slot, and
    fissure.py wipes it via delete_last_bot_message. Registering the Roshan
    drop there took the button away mid-window, so nobody could register.
    """
    source = (PROJECT_ROOT / "roshan.py").read_text(encoding="utf-8-sig")
    body = source[source.index("async def handle_roshan_event"):]
    assert "set_last_bot_message(chat_id" not in body


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
