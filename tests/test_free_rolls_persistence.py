"""Regression tests for free_rolls persistence (Techies bonus rolls).

Bugs covered:
  1. 'free_rolls' was missing from database._ALLOWED_USER_FIELDS, so
     _save_user_to_db_immediately() overwrote every other column but silently
     dropped free_rolls (an awarded roll disappeared on the next save).
  2. The SQLite schema never had the free_rolls column (only PostgreSQL got it
     through _PG_ENSURE_COLUMNS), so add_free_roll() failed on SQLite.
"""

import sqlite3
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import database  # noqa: E402

BOT_USER_ID = 555000111


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


def _raw(path, column, telegram_id=BOT_USER_ID):
    conn = sqlite3.connect(str(path))
    try:
        row = conn.execute(
            f"SELECT {column} FROM users WHERE telegram_id = ?", (telegram_id,)
        ).fetchone()
    finally:
        conn.close()
    return None if row is None else row[0]


def _columns(path):
    conn = sqlite3.connect(str(path))
    try:
        return [row[1] for row in conn.execute("PRAGMA table_info(users)").fetchall()]
    finally:
        conn.close()


def test_field_whitelists_include_free_rolls():
    """Otherwise the immediate-save UPDATE drops/never writes free_rolls."""
    assert "free_rolls" in database._ALLOWED_USER_FIELDS
    assert "free_rolls" in database._NUMERIC_USER_FIELDS


def test_sqlite_schema_has_free_rolls(tmp_path, db_at):
    path = tmp_path / "schema.db"
    db_at(path)
    assert "free_rolls" in _columns(path)


def test_free_rolls_roundtrip_is_persisted(tmp_path, db_at):
    path = tmp_path / "roundtrip.db"
    db_at(path)
    database.Database().register_user(BOT_USER_ID, "fr_tester", "FR")
    database.user_cache.clear()

    assert _raw(path, "free_rolls") == 0
    assert database.get_free_rolls(BOT_USER_ID) == 0

    assert database.add_free_roll(BOT_USER_ID, count=1) == 1
    database.user_cache.clear()
    assert _raw(path, "free_rolls") == 1, "awarded roll must reach the DB file"
    assert database.get_free_rolls(BOT_USER_ID) == 1

    assert database.consume_free_roll(BOT_USER_ID) is True
    database.user_cache.clear()
    assert _raw(path, "free_rolls") == 0
    assert database.get_free_rolls(BOT_USER_ID) == 0

    assert database.consume_free_roll(BOT_USER_ID) is False, "no roll left to consume"
    assert _raw(path, "free_rolls") == 0


def test_free_rolls_read_back_from_db(tmp_path, db_at):
    """A fresh cache read must see the stored value (get_user maps free_rolls)."""
    path = tmp_path / "readback.db"
    db_at(path)
    database.Database().register_user(BOT_USER_ID, "fr_tester", "FR")
    database.add_free_roll(BOT_USER_ID, count=3)
    database.user_cache.clear()

    user = database.get_user(BOT_USER_ID)
    assert user is not None
    assert user["free_rolls"] == 3


def test_fast_init_adds_missing_column_to_legacy_db(tmp_path, db_at):
    """schema_version already matches -> init_db takes the short path and must
    still add the column for old SQLite files."""
    path = tmp_path / "legacy.db"
    db_at(path)
    database.Database().register_user(BOT_USER_ID, "fr_tester", "FR")

    conn = sqlite3.connect(str(path))
    conn.execute("ALTER TABLE users DROP COLUMN free_rolls")
    conn.commit()
    conn.close()
    assert "free_rolls" not in _columns(path)

    database.user_cache.clear()
    database._pool.clear()
    database.init_db()  # short path: "schema up to date"

    assert "free_rolls" in _columns(path)
    assert _raw(path, "free_rolls") == 0

    database.add_free_roll(BOT_USER_ID, count=2)
    database.user_cache.clear()
    assert _raw(path, "free_rolls") == 2
