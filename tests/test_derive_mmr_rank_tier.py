"""Tests for the shared _derive_mmr_rank_tier helper in database.py.

Regression for the bug where top-MMR and weekly top derived rank via a rough
`mmr // 73` approximation, producing inconsistent ranks across cache layers.
"""

import database


def _derive(rank_tier, mmr):
    return database._derive_mmr_rank_tier(rank_tier, mmr)


def test_returns_rank_tier_when_present():
    assert _derive(13, 2500) == 13
    assert _derive(88, 5400) == 88


def test_zero_rank_tier_and_zero_mmr_returns_zero():
    assert _derive(None, 0) == 0
    assert _derive(0, None) == 0
    assert _derive(0, 0) == 0


def test_derives_rank_tier_from_mmr():
    # rank_tier missing -> derive from mmr via mmr_to_rank_tier (pure function)
    assert _derive(None, 1150) is not None
    assert isinstance(_derive(None, 1150), int)


def test_mmr_below_threshold_returns_zero():
    # mmr < 1000 => mmr_to_rank_tier returns 0
    assert _derive(None, 700) == 0


def test_no_dead_inline_import_in_callers():
    """4 call sites of the helper must replace the old `mmr // 73` hack."""
    import io
    from pathlib import Path

    src = Path(__file__).resolve().parent.parent.joinpath("database.py").read_text(
        encoding="utf-8"
    )
    # No leftover raw approximation in the top-building functions
    assert "(u[3] // 73 if u[3] else 0)" not in src
    assert "u[7] if u[7] else (u[4] // 73 if u[4] else 0)" not in src
    assert src.count("_derive_mmr_rank_tier(") >= 4