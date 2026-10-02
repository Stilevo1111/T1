"""Cooldown regression tests for /fissure and event handlers."""
from unittest.mock import patch, MagicMock, AsyncMock
import asyncio

import pytest

import fissure as fissure_module
from fissure import fissure
from database import user_cache


@pytest.fixture(autouse=True)
def _pin_roshan_chance(monkeypatch):
    """Keep Roshan out of these tests.

    fissure() draws Roshan on its own independent 20% roll (ROSHAN_DEFAULT_CHANCE)
    before it looks at multicast/zeus/techies, and returns immediately when it
    hits. The tests here only stub calculate_fissure_roll, so without this they
    ran against a real random number and failed roughly one run in five.
    """
    monkeypatch.setattr(fissure_module, "get_roshan_chance", lambda: 0.0)


def _setup_user(user_id, last_fissure=0.0, fissure=10.0):
    user_cache.clear()
    user_cache.set(user_id, {
        "telegram_id": user_id,
        "fissure": fissure,
        "last_fissure": last_fissure,
        "total_rolls": 0,
        "current_win_streak": 0,
        "current_lose_streak": 0,
    }, skip_dirty=True)


def _make_update(user_id):
    update = MagicMock()
    update.effective_user.id = user_id
    update.effective_user.username = "test"
    update.effective_user.first_name = "Test"
    update.message.chat_id = 1
    update.message.chat.type = "group"
    update.message.message_id = 10
    update.message.text = "/fissure"
    return update


def _make_context():
    context = MagicMock()
    context.job_queue = None
    context.bot.send_message = AsyncMock(return_value=MagicMock(message_id=100))
    context.bot.send_photo = AsyncMock(return_value=MagicMock(message_id=100))
    return context


@patch("fissure.update_last_message_id")
@patch("fissure.schedule_delete")
@patch("fissure.set_last_bot_message")
@patch("fissure.invalidate_digest_cache")
@patch("fissure.record_recent_fissure_roll")
@patch("fissure.maybe_persist_global_stats")
@patch("fissure.update_global_stats_on_event")
@patch("fissure.record_player_roll")
@patch("fissure.get_hero_quote", return_value="")
@patch("fissure.get_roll_text", return_value="OK")
@patch("fissure.apply_fissure_protection", return_value=(1, ""))
@patch("fissure.calculate_streak_bonus", return_value=(1, ""))
@patch("fissure.calculate_new_fissure", return_value=11.0)
@patch("fissure.calculate_fissure_roll", return_value=(1, "", False, False))
@patch("fissure.update_fissure")
@patch("fissure.get_user")
@patch("fissure.delete_fissure_user_and_last_messages", return_value=None)
@patch("fissure.is_rate_limited", return_value=False)
@patch("fissure.is_weekend_msk", return_value=False)
@patch("fissure.init_global_stats")
def test_normal_updates_last_fissure(
    mock_init_global_stats,
    mock_is_weekend,
    mock_is_rate_limited,
    mock_delete,
    mock_get_user,
    mock_update_fissure,
    mock_calculate_fissure_roll,
    mock_calculate_new_fissure,
    mock_calculate_streak_bonus,
    mock_apply_protection,
    mock_get_roll_text,
    mock_get_hero_quote,
    mock_record_player_roll,
    mock_update_global_stats,
    mock_persist_global_stats,
    mock_record_recent,
    mock_invalidate_digest,
    mock_set_last_bot_message,
    mock_schedule_delete,
    mock_update_last_message_id,
):
    _setup_user(101, last_fissure=0.0)
    mock_get_user.return_value = {
        "telegram_id": 101,
        "fissure": 10.0,
        "last_fissure": 0.0,
        "total_rolls": 0,
        "current_win_streak": 0,
        "current_lose_streak": 0,
    }

    with patch("fissure.main_menu", return_value=None), \
         patch("fissure.bot_can_delete", return_value=False), \
         patch("fissure.random.choice", return_value="OK"), \
         patch("time.time", return_value=100000.0):
        asyncio.run(fissure(_make_update(101), _make_context()))

    assert mock_update_fissure.called
    assert mock_update_fissure.call_args[0][2] == 100000.0


@patch("fissure.update_last_message_id")
@patch("fissure.schedule_delete")
@patch("fissure.set_last_bot_message")
@patch("fissure.invalidate_digest_cache")
@patch("fissure.record_recent_fissure_roll")
@patch("fissure.maybe_persist_global_stats")
@patch("fissure.update_global_stats_on_event")
@patch("fissure.record_player_roll")
@patch("fissure.get_hero_quote", return_value="")
@patch("fissure.get_roll_text", return_value="OK")
@patch("fissure.apply_fissure_protection", return_value=(2, ""))
@patch("fissure.calculate_streak_bonus", return_value=(2, ""))
@patch("fissure.calculate_new_fissure", return_value=12.0)
@patch("fissure.calculate_fissure_roll", return_value=(2, "", False, False))
@patch("fissure.update_fissure")
@patch("fissure.get_user")
@patch("fissure.delete_fissure_user_and_last_messages", return_value=None)
@patch("fissure.is_rate_limited", return_value=False)
@patch("fissure.is_weekend_msk", return_value=False)
@patch("fissure.init_global_stats")
def test_multicast_updates_last_fissure(
    mock_init_global_stats,
    mock_is_weekend,
    mock_is_rate_limited,
    mock_delete,
    mock_get_user,
    mock_update_fissure,
    mock_calculate_fissure_roll,
    mock_calculate_new_fissure,
    mock_calculate_streak_bonus,
    mock_apply_protection,
    mock_get_roll_text,
    mock_get_hero_quote,
    mock_record_player_roll,
    mock_update_global_stats,
    mock_persist_global_stats,
    mock_record_recent,
    mock_invalidate_digest,
    mock_set_last_bot_message,
    mock_schedule_delete,
    mock_update_last_message_id,
):
    _setup_user(102, last_fissure=0.0)
    mock_get_user.return_value = {
        "telegram_id": 102,
        "fissure": 10.0,
        "last_fissure": 0.0,
        "total_rolls": 0,
        "current_win_streak": 0,
        "current_lose_streak": 0,
    }

    with patch("fissure.main_menu", return_value=None), \
         patch("fissure.bot_can_delete", return_value=False), \
         patch("random.random", side_effect=[0.30, 0.8, 0.3, 0.1]), \
         patch("fissure.random.choice", side_effect=["🍒", "🍒", "🍒", "OK"]), \
         patch("fissure.asyncio.sleep", return_value=None), \
         patch("time.time", return_value=100000.0):
        asyncio.run(fissure(_make_update(102), _make_context()))

    assert mock_update_fissure.called
    assert mock_update_fissure.call_args[0][2] == 100000.0


@patch("fissure.update_last_message_id")
@patch("fissure.schedule_delete")
@patch("fissure.set_last_bot_message")
@patch("fissure.invalidate_digest_cache")
@patch("fissure.record_recent_fissure_roll")
@patch("fissure.maybe_persist_global_stats")
@patch("fissure.update_global_stats_on_event")
@patch("fissure.record_player_roll")
@patch("fissure.send_fissure_cooldown_response")
@patch("fissure.get_random_cooldown_banner_path", return_value=None)
@patch("fissure.build_fissure_cooldown_bar_and_text", return_value="cooldown")
@patch("fissure.update_fissure")
@patch("fissure.get_user")
@patch("fissure.delete_fissure_user_and_last_messages", return_value=None)
@patch("fissure.is_rate_limited", return_value=False)
@patch("fissure.init_global_stats")
def test_repeat_within_cooldown_is_blocked(
    mock_init_global_stats,
    mock_is_rate_limited,
    mock_delete,
    mock_get_user,
    mock_update_fissure,
    mock_build_cooldown,
    mock_get_banner,
    mock_send_cooldown,
    mock_record_player_roll,
    mock_update_global_stats,
    mock_persist_global_stats,
    mock_record_recent,
    mock_invalidate_digest,
    mock_set_last_bot_message,
    mock_schedule_delete,
    mock_update_last_message_id,
):
    _setup_user(105, last_fissure=100000.0)
    mock_get_user.return_value = {
        "telegram_id": 105,
        "fissure": 10.0,
        "last_fissure": 100000.0,
        "total_rolls": 0,
        "current_win_streak": 0,
        "current_lose_streak": 0,
    }

    with patch("time.time", return_value=100050.0), \
         patch("fissure.main_menu", return_value=None), \
         patch("fissure.bot_can_delete", return_value=False):
        asyncio.run(fissure(_make_update(105), _make_context()))

    assert not mock_update_fissure.called
    assert mock_send_cooldown.called
