"""Tests for the Roshan closing message (build_result_text).

The old text was a public group announcement built from second-person quotes
("Ты забрал АЕГИС!"). In a chat that reads as addressed to every reader, and
because each winner drew a different random quote, the same line named a
different person to different people. It also never mentioned who killed
Roshan, and reduced the players who pressed and came away empty-handed to a
bare count.
"""

import re

from constants import (
    ROSHAN_AEGIS_TEXTS,
    ROSHAN_CHEESE_TEXTS,
    ROSHAN_EMPTY_PIT_TEXTS,
    ROSHAN_LOSER_TEXTS,
    ROSHAN_RESULT_FOOTERS,
)
from roshan import ITEM_LABELS, build_result_text


def _render(awarded, winner_names, loser_names, killer="went_Dr", reward=12.3):
    return build_result_text(killer, reward, awarded, winner_names, loser_names)


def test_killer_is_credited_with_the_reward():
    text = _render({1: "aegis"}, {1: "mikhessssha"}, ["vasya"])
    assert "went_Dr" in text
    assert "+12.3" in text


def test_every_winner_is_named():
    text = _render(
        {1: "aegis", 2: "cheese"}, {1: "went_Dr", 2: "mikhessssha"}, [],
    )
    assert "went_Dr" in text
    assert "mikhessssha" in text


def test_players_who_pressed_and_got_nothing_are_named():
    text = _render({1: "aegis"}, {1: "mikhessssha"}, ["vasya", "petya"])
    assert "vasya" in text
    assert "petya" in text
    # The old wording only ever gave a number.
    assert not re.search(r"Остались ни с чем:\s*\d", text)


def test_item_quotes_are_third_person():
    """A group announcement must not address anyone as 'ты'."""
    for quote in ROSHAN_AEGIS_TEXTS + ROSHAN_CHEESE_TEXTS:
        assert not re.search(r"\b[Тт]ы\b|\bтебе\b|\bтвой\b|\bтвоя\b", quote), quote


def test_item_lines_do_not_repeat_the_item_emoji():
    """The label already carries the emoji; the quote used to add a second one."""
    awarded = {1: "aegis", 2: "cheese"}
    names = {1: "went_Dr", 2: "mikhessssha"}
    text = _render(awarded, names, [])

    for uid, item in awarded.items():
        label = ITEM_LABELS[item]
        quote_line = [ln for ln in text.splitlines() if label in ln and "→" in ln]
        assert len(quote_line) == 1, text
        # Only the label carries an emoji, not the whole line twice.
        assert text.count(label) >= 1


def test_losers_get_a_pool_line():
    text = _render({1: "aegis"}, {1: "mikhessssha"}, ["vasya", "petya"])
    assert any(line in text for line in ROSHAN_LOSER_TEXTS)
    assert "vasya" in text and "petya" in text


def test_no_loser_line_when_everyone_got_something():
    text = _render({1: "aegis"}, {1: "mikhessssha"}, [])
    assert "не досталось" not in text


def test_empty_window_says_the_pit_is_empty():
    """The wording varies, so assert one of the pool lines, not a fixed phrase."""
    text = _render({}, {}, [])
    assert any(line in text for line in ROSHAN_EMPTY_PIT_TEXTS)
    assert "на дне" in text


def test_footer_is_present():
    text = _render({1: "aegis"}, {1: "mikhessssha"}, ["vasya"])
    assert any(f in text for f in ROSHAN_RESULT_FOOTERS)


def test_message_has_no_double_blank_line():
    text = _render({1: "aegis"}, {1: "mikhessssha"}, ["vasya"])
    assert "\n\n\n" not in text
    assert text == text.strip()
