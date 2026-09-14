"""Verify /profile (generate_chart_only) persists analytics_cache to DB.

Previously only /analyze (generate_weekly_analytics) wrote analytics_cache,
so every /profile call re-fetched OpenDota and fell back to the default
banner whenever the API lagged. Now both paths save the cache.
"""
import asyncio
import json
import sys
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def _fake_matches():
    return [
        {
            "kills": 5, "deaths": 3, "assists": 12, "duration": 2400,
            "last_hits": 320, "creeps_stacked": 4, "denies": 8,
            "win": True, "hero_id": 1,
        }
        for _ in range(6)
    ]


def _patch_pipeline(chart_return=b"\x89PNG\r\n\x1a\n fake"):
    """Patch external deps so generate_chart_only runs without OpenDota.

    chart_return controls what _create_visual_chart returns after await
    (AsyncMock so the caller's `await` works).
    """
    patches = [
        mock.patch("database.get_user", return_value={"steam_id": "76561198307880427"}),
        mock.patch("weekly_analytics.is_opendota_rate_limited", return_value=False),
        mock.patch("weekly_analytics.get_last_matches", return_value=_fake_matches()),
        mock.patch("weekly_analytics._create_visual_chart", new=mock.AsyncMock(return_value=chart_return)),
        mock.patch("weekly_analytics._detect_role_from_hero_counts", new=mock.AsyncMock(return_value="CARRY")),
        mock.patch("weekly_analytics._calculate_imp", return_value=1.5),
    ]
    return patches


def test_chart_only_saves_analytics_cache():
    from weekly_analytics import generate_chart_only

    execute_calls = []

    fake_db = mock.MagicMock()
    fake_db.execute_query.side_effect = lambda sql, params=None: execute_calls.append((sql, params))

    patches = _patch_pipeline()
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], \
         mock.patch("weekly_analytics.Database", return_value=fake_db):
        result = asyncio.run(generate_chart_only(8789376291))

    assert result is not None
    assert result.get("image") == b"\x89PNG\r\n\x1a\n fake"
    assert result.get("history")
    assert result.get("matches")

    cache_writes = [c for c in execute_calls if "analytics_cache" in c[0]]
    assert len(cache_writes) == 1, f"Expected 1 analytics_cache write, got {len(cache_writes)}: {execute_calls}"

    sql, params = cache_writes[0]
    assert "UPDATE users SET analytics_cache" in sql
    assert params[2] == 8789376291
    assert params[0] is not None
    assert params[1] is not None

    # Verify the cached JSON is valid and contains expected keys
    cached = json.loads(params[0])
    assert "history" in cached
    assert "matches" in cached
    assert cached.get("role") == "CARRY"


def test_chart_only_skips_cache_save_on_error():
    """If chart generation returns None (no renderable history), cache must NOT be written."""
    from weekly_analytics import generate_chart_only

    execute_calls = []
    fake_db = mock.MagicMock()
    fake_db.execute_query.side_effect = lambda sql, params=None: execute_calls.append((sql, params))

    # _create_visual_chart returns None — e.g. all matches had imp_unavailable
    patches = _patch_pipeline(chart_return=None)

    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], \
         mock.patch("weekly_analytics.Database", return_value=fake_db):
        result = asyncio.run(generate_chart_only(8789376291))

    assert result is not None
    cache_writes = [c for c in execute_calls if "analytics_cache" in c[0]]
    assert len(cache_writes) == 0, f"Should not write cache on failure, got {cache_writes}"


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-q"]))