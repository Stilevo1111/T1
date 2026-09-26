"""Tests for the digest cache timestamp restored after a restart.

`cache["created_at"]` only lives in process memory, so it is 0 after every
deploy. A 0 timestamp made the rotation check fire immediately, and a rotation
deletes the pinned digest and regenerates the hero meta banner, which walks
OpenDota again and is what trips the rate limit that emptied the banner.

The timestamp of the real last creation is kept in
alternate_digest_last_created, so a fresh process can restore it.
"""
import sys
import time
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import digest  # noqa: E402


@pytest.fixture
def config(monkeypatch):
    """A get_config stub backed by a plain dict."""
    store = {"value": None}

    def fake_get_config(key):
        if key == "alternate_digest_last_created":
            return store["value"]
        return None

    import database

    monkeypatch.setattr(database, "get_config", fake_get_config)
    return store


def test_restores_the_real_creation_time(config):
    """The known timestamp must come back, not a placeholder."""
    created = time.time() - 3600
    config["value"] = str(created)

    restored = digest._restore_created_at("112590")

    assert restored == pytest.approx(created, abs=1)
    # An hour old, so the rotation interval has not elapsed.
    assert time.time() - restored < digest.DIGEST_ROTATION_INTERVAL


def test_no_timestamp_and_no_message_means_create(config):
    """Nothing exists yet, so the first run must legitimately create."""
    config["value"] = None
    assert digest._restore_created_at(None) == 0.0
    assert digest._restore_created_at("") == 0.0


def test_message_without_timestamp_is_treated_as_fresh(config):
    """A post exists but the time is lost: edit it, do not rotate it.

    Returning 0 here would restore the bug for exactly the case that produced
    the empty banner, so the cache must look fresh instead.
    """
    config["value"] = None

    restored = digest._restore_created_at("112590")

    assert restored > 0
    assert time.time() - restored < digest.DIGEST_ROTATION_INTERVAL


@pytest.mark.parametrize("bad", ["0", "-5", "not-a-number", "", "   ", "9e18"])
def test_bad_timestamps_fall_back_safely(config, bad):
    config["value"] = bad
    # Never raise, and never invent a future timestamp.
    restored = digest._restore_created_at("112590")
    assert restored <= time.time() + 60


def test_restored_value_survives_the_rotation_check(config):
    """The restored timestamp must not trip the rotation comparison."""
    created = time.time() - 120
    config["value"] = str(created)
    restored = digest._restore_created_at("112590")

    now = time.time()
    assert (now - restored) <= digest.DIGEST_ROTATION_INTERVAL
