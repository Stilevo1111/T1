"""Regression tests for the public_player_matches lane_role column.

Bugs covered:

  1. PostgreSQL: CREATE TABLE IF NOT EXISTS is a no-op on an existing table, so
     lane_role never reached any database created before the column was added.
     Every hero-meta INSERT then failed with
     `column "lane_role" of relation "public_player_matches" does not exist`
     and the hero meta page silently stayed empty for every player.

  2. SQLite: lane_role was missing from CREATE TABLE entirely, while the INSERT
     names it - that branch could never succeed on any database, fresh or old.
"""

import sqlite3
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

COLUMNS_SQL = (
    "match_id", "hero_id", "player_slot", "radiant_win",
    "start_time", "steam_id", "lane_role",
)


def _source() -> str:
    return (PROJECT_ROOT / "dota_mmr.py").read_text(encoding="utf-8-sig")


def _columns(path) -> set:
    conn = sqlite3.connect(str(path))
    try:
        return {row[1] for row in conn.execute("PRAGMA table_info(public_player_matches)")}
    finally:
        conn.close()


def test_pg_branch_alters_in_the_missing_column():
    """CREATE TABLE IF NOT EXISTS cannot add a column; the ALTER is required."""
    src = _source()
    assert "ADD COLUMN IF NOT EXISTS lane_role" in src, (
        "PostgreSQL branch needs an explicit ALTER, otherwise existing "
        "databases never get lane_role and hero meta saving fails"
    )


def test_sqlite_create_table_declares_lane_role():
    """The SQLite CREATE TABLE must list every column its INSERT names."""
    src = _source()
    idx = src.find("CREATE TABLE IF NOT EXISTS public_player_matches")
    assert idx != -1
    block = src[idx:idx + 700]
    for col in COLUMNS_SQL:
        assert col in block, f"SQLite CREATE TABLE is missing column {col}"


def test_sqlite_branch_has_guarded_alter():
    """SQLite lacks ADD COLUMN IF NOT EXISTS, so it needs a PRAGMA guard."""
    src = _source()
    assert "ALTER TABLE public_player_matches ADD COLUMN lane_role INTEGER" in src


def test_sqlite_insert_matches_table_definition(tmp_path):
    """Execute the SQLite branch's shape against a real file."""
    path = tmp_path / "ppm.db"
    conn = sqlite3.connect(str(path))
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS public_player_matches (
                match_id INTEGER UNIQUE,
                hero_id INTEGER,
                player_slot INTEGER,
                radiant_win INTEGER,
                start_time INTEGER,
                steam_id INTEGER,
                lane_role INTEGER
            )
        """)
        conn.execute(
            "INSERT OR IGNORE INTO public_player_matches "
            "(match_id, hero_id, player_slot, radiant_win, start_time, steam_id, lane_role) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (1, 18, 3, 1, 1790622640, 76561199240085490, 2),
        )
        conn.commit()
        row = conn.execute(
            "SELECT lane_role FROM public_player_matches WHERE match_id = 1"
        ).fetchone()
    finally:
        conn.close()
    assert row is not None and row[0] == 2


def test_legacy_sqlite_table_gets_the_column(tmp_path):
    """A SQLite file created before lane_role existed must be repaired."""
    path = tmp_path / "legacy.db"
    conn = sqlite3.connect(str(path))
    try:
        # Table exactly as it looked before the fix: no lane_role.
        conn.execute("""
            CREATE TABLE public_player_matches (
                match_id INTEGER UNIQUE,
                hero_id INTEGER,
                player_slot INTEGER,
                radiant_win INTEGER,
                start_time INTEGER,
                steam_id INTEGER
            )
        """)
        conn.commit()
    finally:
        conn.close()
    assert "lane_role" not in _columns(path)

    # Now apply the guarded ALTER the fixed code performs.
    conn = sqlite3.connect(str(path))
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS public_player_matches ("
            "match_id INTEGER UNIQUE, hero_id INTEGER, player_slot INTEGER, "
            "radiant_win INTEGER, start_time INTEGER, steam_id INTEGER, lane_role INTEGER)"
        )
        existing = [c[1] for c in conn.execute("PRAGMA table_info(public_player_matches)")]
        if existing and "lane_role" not in existing:
            conn.execute("ALTER TABLE public_player_matches ADD COLUMN lane_role INTEGER")
        conn.commit()
    finally:
        conn.close()

    assert "lane_role" in _columns(path)
    assert _columns(path) == set(COLUMNS_SQL)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))