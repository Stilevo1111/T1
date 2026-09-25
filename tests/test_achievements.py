"""Tests for achievement awarding.

A badge was handed out about ten times a day because `achievements` was part of
the whole-row save whitelist: any background job holding a stale user snapshot
rewrote the column, the badge was wiped, and the next message awarded it again.
The column now has a single owner and the write is a compare-and-swap.
"""
import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import achievements as ach  # noqa: E402
import database  # noqa: E402


@pytest.fixture(scope="module")
def store(tmp_path_factory):
    """A real SQLite users table, so the SQL is exercised for real.

    Module scoped because Database() caches its connection, which would
    otherwise leak one test's temporary file into the next.
    """
    db_path = tmp_path_factory.mktemp("ach") / "ach.db"
    database.DATABASE_URL = f"sqlite:///{db_path}"

    db = database.Database()
    db.execute_query(
        "CREATE TABLE IF NOT EXISTS users "
        "(telegram_id INTEGER PRIMARY KEY, achievements TEXT DEFAULT '{}')"
    )
    return db


@pytest.fixture
def user(store):
    """Reset the single test user before each test."""
    store.execute_query("DELETE FROM users")
    store.execute_query("INSERT INTO users (telegram_id, achievements) VALUES (?, ?)", (7, "{}"))
    return store


def _stub_get_user(monkeypatch, telegram_id=7, stale="{}"):
    """get_user returns a snapshot that may be out of date, like the real cache."""
    monkeypatch.setattr(
        database, "get_user", lambda tid, username=None: {"telegram_id": tid, "achievements": stale}
    )


def test_achievements_is_not_in_the_whole_row_whitelist():
    """The generic save must never rewrite the column any more."""
    assert "achievements" not in database._ALLOWED_USER_FIELDS


def test_award_is_persisted_once(user, monkeypatch):
    _stub_get_user(monkeypatch)

    first = ach.check_and_award(7, "message_count", 100)
    assert first == ["ah_msg100"]

    # A later message with the same or higher count must not re-award.
    for count in (101, 150, 400):
        assert ach.check_and_award(7, "message_count", count) == []

    row = user.execute_query(
        "SELECT achievements FROM users WHERE telegram_id = ?", (7,), fetch="one"
    )
    assert json.loads(row[0]) == {"ah_msg100": 1}


def test_stale_cache_does_not_re_award(user, monkeypatch):
    """A cache snapshot that predates the award must not cause a second one."""
    _stub_get_user(monkeypatch, stale="{}")

    assert ach.check_and_award(7, "message_count", 600) == ["ah_msg100", "ah_msg500"]
    # get_user keeps returning the pre-award "{}" snapshot.
    assert ach.check_and_award(7, "message_count", 900) == []


def test_concurrent_award_loses_the_swap(user, monkeypatch):
    """Two instances must not both win: the loser announces nothing."""
    _stub_get_user(monkeypatch)
    assert ach.check_and_award(7, "message_count", 100) == ["ah_msg100"]

    # Simulate the loser having read "{}" before the winner committed, so its
    # compare-and-swap compares against a value that is no longer stored.
    db_type = database.get_db_type()
    stored = user.execute_query(
        "SELECT achievements FROM users WHERE telegram_id = ?", (7,), fetch="one"
    )[0]
    assert not ach._store_if_unchanged(
        user, db_type, 7, "{}", {"ah_msg100": 1, "ah_msg500": 1}
    ), "stale compare must not overwrite the stored value"
    assert stored == json.dumps({"ah_msg100": 1})


def test_missing_user_is_not_awarded(monkeypatch):
    monkeypatch.setattr(database, "get_user", lambda tid, username=None: None)
    assert ach.check_and_award(999, "message_count", 1000) == []
