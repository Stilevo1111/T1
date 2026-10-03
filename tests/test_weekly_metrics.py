"""Tests that the PRO comparison table never reports an unmeasured number.

OpenDota's /matches/{id} endpoint does not expose actions_per_min, stuns or
creeps_stacked, and for many matches omits hero_damage/tower_damage too. These
tests pin the rule that a metric we cannot measure renders as "—" instead of
falling back to a guess.
"""
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from weekly_analytics import (  # noqa: E402
    PRO_DB,
    _generate_report_text,
    _imp_available_keys,
    calculate_player_stats,
    get_analytics_pages,
)

ROLES = ["CARRY", "MID", "OFFLANE", "SUPPORT"]


def _match(**over):
    """A match as OpenDota returns it for a fully parsed game."""
    base = {
        "last_hits": 70, "denies": 4, "kills": 8, "deaths": 5, "assists": 10,
        "win": True, "duration": 2100, "gold_per_min": 480, "xp_per_min": 610,
        "gold": 12000, "gold_spent": 15000, "hero_damage": 18000,
        "tower_damage": 2400,
    }
    base.update(over)
    return base


# --- Availability ----------------------------------------------------------

def test_damage_is_none_when_the_api_did_not_send_it():
    """A ranked match arrives without damage fields; it must not be guessed."""
    matches = [_match(hero_damage=0, tower_damage=0) for _ in range(5)]
    stats = calculate_player_stats(matches)
    assert stats["h_dmg"] is None
    assert stats["t_dmg"] is None


def test_damage_averages_only_over_reported_matches():
    """Half the history parsed: average the half we have, do not dilute it."""
    matches = [_match() for _ in range(3)] + [
        _match(hero_damage=0, tower_damage=0) for _ in range(3)
    ]
    stats = calculate_player_stats(matches)
    assert stats["h_dmg"] == 18000
    assert stats["t_dmg"] == 2400


def test_damage_is_raw_not_thousands():
    """The /1000 scaling bug made 18000 damage render as 18.0."""
    matches = [_match() for _ in range(4)]
    assert calculate_player_stats(matches)["h_dmg"] == 18000


def test_removed_metrics_are_not_reported():
    """APM, Stacks and Util have no data source and must be gone."""
    stats = calculate_player_stats([_match() for _ in range(3)])
    for key in ("apm", "stacks", "util"):
        assert key not in stats


def test_empty_history_reports_nothing_measurable():
    stats = calculate_player_stats([])
    assert stats["gpm"] is None
    assert stats["h_dmg"] is None
    assert stats["kda"] is None


# --- Table rendering -------------------------------------------------------

def test_table_renders_dash_for_unmeasured_damage():
    matches = [_match(hero_damage=0, tower_damage=0) for _ in range(4)]
    table = _generate_report_text("CARRY", calculate_player_stats(matches))["detailed"]
    assert "H DMG        —" in table
    assert "T DMG        —" in table


def test_empty_history_table_renders_dashes_instead_of_raising():
    """/analyze died with "'>' not supported between NoneType and int".

    An empty history reports every metric as None, and the table used to run
    `user_stats.get('gpm', 0) > 0` on that None. Nothing is measurable here, so
    every player cell must render as "—" rather than crash the whole command.
    """
    stats = calculate_player_stats([])
    pro_table = _generate_report_text("CARRY", stats)["pro"]
    assert "YOU" in pro_table
    assert "—" in pro_table
    for page in get_analytics_pages("CARRY", stats):
        assert page["text"]


def test_null_match_fields_do_not_break_aggregation():
    """OpenDota and the cache JSON carry explicit nulls; treat them as missing."""
    matches = [_match(gold_per_min=None, duration=None, last_hits=None,
                      kills=None, deaths=None, xp_per_min=None) for _ in range(4)]
    stats = calculate_player_stats(matches)
    assert stats["gpm"] is None
    assert stats["wr"] == 100.0
    assert _generate_report_text("MID", stats)["detailed"]


def test_zero_gpm_is_reported_as_zero_not_as_a_dash():
    """A real zero is a measurement; only a missing field becomes "—"."""
    stats = {
        "wr": 50.0, "gpm": 0, "xpm": 0, "lh": 0, "lh_per_min": 0,
        "deny": 0, "deaths": 0, "h_dmg": 0, "t_dmg": 0,
        "kda_number": 0, "kda": "0/0/0",
    }
    you_row = _generate_report_text("CARRY", stats)["pro"].split("YOU")[1]
    assert "—" not in you_row


def test_table_never_prints_the_removed_rows():
    stats = calculate_player_stats([_match() for _ in range(4)])
    table = _generate_report_text("CARRY", stats)["detailed"]
    for label in ("Stacks", "Util", "APM"):
        assert f"\n{label}" not in table


def test_lh_per_min_is_reported_and_derived():
    matches = [_match() for _ in range(3)]
    stats = calculate_player_stats(matches)
    # 70 last hits over 35 minutes.
    assert stats["lh_per_min"] == 2.0
    for role in ROLES:
        bench = PRO_DB[role]["benchmarks"]
        assert bench["lh_per_min"] == pytest.approx(bench["lh"] / 10, abs=0.05)


# --- Impact score ----------------------------------------------------------

@pytest.mark.parametrize("role", ROLES)
def test_pro_benchmarks_have_no_unsourced_metrics(role):
    """None benchmarks are what exclude a metric from the impact formula."""
    bench = PRO_DB[role]["benchmarks"]
    assert bench["apm"] is None
    assert bench["utility"] is None
    assert "stacks" not in bench


@pytest.mark.parametrize("role", ROLES)
def test_impact_uses_only_verified_metrics(role):
    keys = _imp_available_keys(role)
    assert set(keys) == {"gpm", "kda"}
    assert "apm" not in keys
    assert "utility" not in keys


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
