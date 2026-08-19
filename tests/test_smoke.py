"""Smoke tests to verify the bot modules can be imported without errors.
These tests do not start the bot or change any behavior.
"""

import importlib
import sys
from pathlib import Path

# Add project root to path so we can import modules
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def test_core_modules_import():
    """Core modules should import cleanly."""
    modules = [
        "database",
        "main",
        "digest",
        "dota_mmr",
        "rate_limiter",
        "mute",
        "hero_meta",
        "rolls",
        "stats",
        "bot_utils",
        "fissure",
        "constants",
        "party",
    ]

    for mod_name in modules:
        mod = importlib.import_module(mod_name)
        assert mod is not None, f"Failed to import {mod_name}"


def test_digest_has_public_api():
    """digest.py should expose the public helper functions we use from main."""
    import digest

    required = [
        "get_digest_type",
        "set_digest_type",
        "set_fissure_digest_data",
        "set_dota_last_text",
        "get_dota_last_text",
        "claim_or_check_digest_leader",
    ]

    for name in required:
        assert hasattr(digest, name), f"Missing public API: {name}"


def test_rolls_has_public_api():
    """rolls.py should expose the calculation and text functions used by main."""
    import rolls

    required = [
        "calculate_fissure_roll",
        "apply_fissure_protection",
        "calculate_new_fissure",
    ]

    for name in required:
        assert hasattr(rolls, name), f"Missing public API from rolls: {name}"


def test_rolls_calculations_are_pure_and_stable():
    """Pure calculation functions from rolls.py must work and never raise for valid inputs.
    This protects against accidental breakage during future extractions.
    """
    from rolls import apply_fissure_protection, calculate_fissure_roll, calculate_new_fissure

    # Test a range of fissure sizes
    for size in [0.1, 1, 5, 10, 19, 20, 50, 100]:
        roll, msg, is_fatal, got_help = calculate_fissure_roll(size)
        assert isinstance(roll, (int, float))
        assert isinstance(is_fatal, bool)
        assert isinstance(got_help, bool)

        new_size = calculate_new_fissure(size, roll)
        assert new_size >= 0.1

        protected, _ = apply_fissure_protection(size, roll, is_fatal)
        assert isinstance(protected, (int, float))

    print('test_rolls_calculations_are_pure_and_stable: PASSED')


def test_multicast_texts_import():
    """MULTICAST_TEXTS should be importable from rolls (used in fissure multicasts)."""
    from rolls import MULTICAST_TEXTS
    assert isinstance(MULTICAST_TEXTS, dict)
    assert 2 in MULTICAST_TEXTS
    assert 3 in MULTICAST_TEXTS
    assert 4 in MULTICAST_TEXTS


def test_fissure_module_has_multicast_texts():
    """fissure.py should have access to MULTICAST_TEXTS for multicast rolls."""
    import fissure
    assert hasattr(fissure, 'MULTICAST_TEXTS')


def test_start_cooldown_lru():
    """Start cooldown should have LRU protection to prevent memory leaks."""
    from main import _USER_START_COOLDOWN, _start_cooldown_cleanup_if_needed, _START_COOLDOWN_MAX_SIZE
    import time

    # Test LRU function exists
    assert callable(_start_cooldown_cleanup_if_needed)
    assert _START_COOLDOWN_MAX_SIZE == 1000

    # Clear cache first
    _USER_START_COOLDOWN.clear()

    # Add test entries
    for uid in range(1100):
        _USER_START_COOLDOWN[uid] = time.time()

    assert len(_USER_START_COOLDOWN) == 1100

    _start_cooldown_cleanup_if_needed()

    assert len(_USER_START_COOLDOWN) <= 1000
    print('test_start_cooldown_lru: PASSED')


def test_party_has_public_api():
    """party.py should expose the public helper functions used by main."""
    import party

    required = [
        "party_command",
        "get_week_wr",
        "build_inline_keyboard",
    ]

    for name in required:
        assert hasattr(party, name), f"Missing public API from party: {name}"


def test_party_week_wr_calculation():
    """get_week_wr should calculate correct winrate percentages."""
    from party import get_week_wr

    assert get_week_wr({"week_games": 0, "week_wins": 0}) == 0
    assert get_week_wr({"week_games": 10, "week_wins": 5}) == 50
    assert get_week_wr({"week_games": 10, "week_wins": 7}) == 70
    assert get_week_wr({"week_games": 3, "week_wins": 1}) == 33


def test_party_inline_keyboard_format():
    """build_inline_keyboard should create correct 2x4 button layout."""
    from party import build_inline_keyboard
    from telegram import InlineKeyboardMarkup

    players = [
        {"username": "user1", "steam_nickname": "Nick1"},
        {"username": "user2", "steam_nickname": "Nick2"},
        {"username": "user3", "steam_nickname": "Nick3"},
        {"username": "user4", "steam_nickname": "Nick4"},
        {"username": "user5", "steam_nickname": "Nick5"},
        {"username": "user6", "steam_nickname": "Nick6"},
        {"username": "user7", "steam_nickname": "Nick7"},
        {"username": "user8", "steam_nickname": "Nick8"},
    ]

    keyboard = build_inline_keyboard(players)

    assert isinstance(keyboard, InlineKeyboardMarkup), "Keyboard should be InlineKeyboardMarkup"
    keyboard_rows = keyboard.inline_keyboard
    assert len(keyboard_rows) == 2, "Keyboard should have 2 rows"
    assert len(keyboard_rows[0]) == 4, "First row should have 4 buttons"
    assert len(keyboard_rows[1]) == 4, "Second row should have 4 buttons"

    for row in keyboard_rows:
        for btn in row:
            assert hasattr(btn, 'text')
            assert hasattr(btn, 'switch_inline_query_current_chat')


def test_party_inline_keyboard_fewer_players():
    """build_inline_keyboard should handle fewer than 8 players."""
    from party import build_inline_keyboard
    from telegram import InlineKeyboardMarkup

    players = [
        {"username": "user1", "steam_nickname": "Nick1"},
        {"username": "user2", "steam_nickname": "Nick2"},
    ]

    keyboard = build_inline_keyboard(players)

    assert isinstance(keyboard, InlineKeyboardMarkup), "Keyboard should be InlineKeyboardMarkup"
    keyboard_rows = keyboard.inline_keyboard
    assert len(keyboard_rows) == 2, "Keyboard should have 2 rows (second may be empty)"
    assert len(keyboard_rows[0]) == 2, "First row should have 2 buttons"


def test_party_config_defaults():
    """Party module should have configurable limits with sensible defaults."""
    import party

    assert hasattr(party, 'PARTY_MAX_ABOVE')
    assert hasattr(party, 'PARTY_MAX_BELOW')
    assert party.PARTY_MAX_ABOVE == 4
    assert party.PARTY_MAX_BELOW == 4


def test_rolls_fatal_threshold():
    """Rolls <= -10 must be fatal."""
    from rolls import calculate_fissure_roll, FATAL_ROLL
    import random
    random.seed(42)
    for _ in range(200):
        roll, _, is_fatal, _ = calculate_fissure_roll(20)
        if roll <= FATAL_ROLL:
            assert is_fatal is True
        if is_fatal:
            assert roll <= FATAL_ROLL


def test_rolls_zero_is_remapped():
    """Zero roll should be remapped to +/-1."""
    from rolls import calculate_fissure_roll
    import random
    random.seed(99)
    for _ in range(300):
        roll, _, _, _ = calculate_fissure_roll(10)
        assert roll != 0, "Zero roll should be remapped"


def test_rolls_spread_scales_with_fissure():
    """Roll spread should increase with fissure size."""
    from rolls import calculate_fissure_roll
    import random
    random.seed(123)
    small_rolls = [calculate_fissure_roll(1)[0] for _ in range(200)]
    big_rolls = [calculate_fissure_roll(100)[0] for _ in range(200)]
    assert max(big_rolls) > max(small_rolls)
    assert abs(min(big_rolls)) > abs(min(small_rolls))


def test_rolls_small_fissure_protection():
    """Small fissures should have reduced negative range."""
    from rolls import calculate_fissure_roll
    import random
    random.seed(456)
    rolls = [calculate_fissure_roll(3)[0] for _ in range(500)]
    assert min(rolls) >= -3, f"Small fissure should not lose more than size: got {min(rolls)}"


def test_apply_fissure_protection():
    """Protection should reduce fatal damage for small fissures."""
    from rolls import apply_fissure_protection
    reduced, msg = apply_fissure_protection(3, -15, True)
    assert reduced == -5
    assert "УРОН СНИЖЕН" in msg

    reduced, msg = apply_fissure_protection(10, -15, True)
    assert reduced == -15
    assert msg == ""


def test_calculate_new_fissure_minimum():
    """New fissure should never go below 0.1."""
    from rolls import calculate_new_fissure
    assert calculate_new_fissure(0.5, -10) == 0.1
    assert calculate_new_fissure(5, -20) == 0.1
    assert calculate_new_fissure(10, 5) == 15


def test_calculate_streak_bonus():
    """Streak bonus should cap at +5 and only apply to positive rolls."""
    from rolls import calculate_streak_bonus
    new_roll, text = calculate_streak_bonus(10, 5)
    assert new_roll == 10
    assert "СТРИК" in text

    new_roll, text = calculate_streak_bonus(3, 5)
    assert new_roll == 8
    assert "СТРИК" in text

    new_roll, text = calculate_streak_bonus(10, -5)
    assert new_roll == -5
    assert text == ""


def test_roll_texts_coverage():
    """All rolls from -50 to +50 should have text entries."""
    from rolls import ROLL_TEXTS
    for v in range(-50, 51):
        assert v in ROLL_TEXTS, f"Missing ROLL_TEXTS entry for {v}"
        assert len(ROLL_TEXTS[v]) > 0


def test_get_roll_text_returns_string():
    """get_roll_text should always return a non-empty string."""
    from rolls import get_roll_text
    for v in [-50, -10, -1, 0, 1, 10, 50]:
        text = get_roll_text(v)
        assert isinstance(text, str)
        assert len(text) > 0


def test_get_hero_quote_format():
    """Hero quotes should contain hero name and text."""
    from rolls import get_hero_quote
    for v in [-5, 0, 5]:
        quote = get_hero_quote(v)
        assert "🗣️" in quote
        assert len(quote) > 5


def test_multicast_texts_keys():
    """Multicast texts should exist for 2, 3, 4."""
    from rolls import MULTICAST_TEXTS
    for key in [2, 3, 4]:
        assert key in MULTICAST_TEXTS
        assert len(MULTICAST_TEXTS[key]) > 0


def test_fissure_cooldown_bar_logic():
    """Cooldown bar should calculate remaining time correctly."""
    from fissure import build_fissure_cooldown_bar_and_text, COOLDOWN
    import time
    now = time.time()
    last = now - 3600
    text = build_fissure_cooldown_bar_and_text(now, last, COOLDOWN, lambda s: f"{int(s//3600)}h")
    assert "Восстанавливается" in text
    assert "23h" in text


def test_techies_timeout_worker_exists():
    """Techies module should expose timeout worker."""
    import techies
    assert hasattr(techies, '_techies_timeout_worker')


def test_mute_gag_timeout_job_exists():
    """Mute module should expose gag timeout job."""
    import mute
    assert hasattr(mute, '_gag_timeout_job')


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-q"]))
