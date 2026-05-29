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
        "function_fixed",
        "dota_mmr",
        "rate_limiter",
        "mute",
        "hero_meta",
        "rolls",
        "stats",
        "bot_utils",
        "fissure",
        "constants",
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
    from rolls import calculate_fissure_roll, calculate_new_fissure, apply_fissure_protection

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


if __name__ == "__main__":
    # Allow running directly: python -m pytest tests/test_smoke.py -q
    import pytest
    sys.exit(pytest.main([__file__, "-q"]))
