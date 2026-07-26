"""Audit-focused regression tests for fixes verified in the codebase."""

from pathlib import Path

import pytest

from bot_utils import clickable_name, format_time
from database import User


def test_format_time_russian_units():
    assert "ч" in format_time(3661)
    assert "м" in format_time(65)
    assert "h" not in format_time(3661)
    assert "m" not in format_time(65)
    assert "s" not in format_time(5)


def test_clickable_name_telegram_id_zero_no_crash():
    result = clickable_name("TestUser", telegram_id=0, steam_id=12345)
    assert isinstance(result, str)
    assert len(result) > 0
    assert "tg://user?id=0" in result or "https://steamcommunity.com/" in result or "TestUser" in result


def test_user_from_row_sqlite_indices():
    row = [0] * 50
    row[1] = 123
    row[39] = 42
    row[41] = 5
    row[42] = 3
    row[43] = 10
    user = User.from_row(row, db_type="sqlite")
    assert user.message_count == 42
    assert user.current_win_streak == 5
    assert user.current_lose_streak == 3
    assert user.best_lose_streak == 10


def test_no_duplicate_link_handler():
    main_path = Path(__file__).resolve().parent.parent / "main.py"
    content = main_path.read_text(encoding="utf-8")
    assert content.count('if data == "link":') == 1
