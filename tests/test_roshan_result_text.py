"""Tests for the Roshan closing message (build_result_text).

The message is a public group announcement and has to answer two questions:
who walked off with which artifact, and what that artifact does next. It used
to answer neither well - the artifact lines carried random flavour quotes
instead of the effect, and the players who pressed and came away empty-handed
were reduced to a bare count.
"""

import re

from roshan import ITEM_DESCRIPTIONS, ITEM_LABELS, build_result_text

EMOJI = re.compile(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]")


def _render(awarded, winner_names, loser_names, killer="went_Dr", reward=12.3):
    return build_result_text(killer, reward, awarded, winner_names, loser_names)


def test_killer_is_credited_with_the_reward():
    text = _render({1: "aegis"}, {1: "mikhessssha"}, ["vasya"])
    assert "went_Dr" in text
    assert "+12.3" in text


def test_names_the_artifact_that_was_stolen():
    text = _render(
        {1: "aegis", 2: "cheese"}, {1: "went_Dr", 2: "mikhessssha"}, [],
    )
    assert "АЕГИС" in text
    assert "СЫР" in text


def test_names_every_recipient():
    text = _render(
        {1: "aegis", 2: "cheese"}, {1: "went_Dr", 2: "mikhessssha"}, [],
    )
    assert "went_Dr" in text
    assert "mikhessssha" in text


def test_states_what_each_artifact_does():
    """The point of the message: the effect, not a joke about it."""
    text = _render(
        {1: "aegis", 2: "cheese"}, {1: "went_Dr", 2: "mikhessssha"}, [],
    )
    for item in ("aegis", "cheese"):
        assert ITEM_DESCRIPTIONS[item] in text


def test_players_who_got_nothing_are_named():
    text = _render({1: "aegis"}, {1: "mikhessssha"}, ["vasya", "petya"])
    assert "vasya" in text
    assert "petya" in text
    # The old wording gave a number with no names.
    assert not re.search(r"Остались ни с чем:\s*\d", text)


def test_no_flavour_quotes_survive_in_the_result():
    """Second-person banter has no place in a public announcement."""
    text = _render(
        {1: "aegis", 2: "cheese"}, {1: "went_Dr", 2: "mikhessssha"}, ["vasya"],
    )
    assert not re.search(r"\b[Тт]ы\b|\bтебе\b|\bтвой\b|\bтвоя\b", text)


def test_artifact_line_carries_one_emoji():
    text = _render({1: "aegis", 2: "cheese"}, {1: "went_Dr", 2: "mikhessssha"}, [])
    for line in text.splitlines():
        for label in ITEM_LABELS.values():
            if label in line:
                assert not EMOJI.sub("", label).strip() or line.count(EMOJI.findall(label)[0]) == 1


def test_empty_window_is_stated_plainly():
    text = _render({}, {}, [])
    assert "никто" in text.lower()


def test_no_loser_line_when_everyone_got_something():
    text = _render({1: "aegis"}, {1: "mikhessssha"}, [])
    assert "Ничего не досталось" not in text


def test_message_has_no_trailing_or_double_blank_lines():
    text = _render({1: "aegis"}, {1: "mikhessssha"}, ["vasya"])
    assert "\n\n\n" not in text
    assert text == text.strip()


def test_html_is_balanced():
    """Names are bolded; an unbalanced tag would make Telegram reject the edit."""
    for text in (
        _render({1: "aegis"}, {1: "mikhessssha"}, ["vasya"]),
        _render({}, {}, []),
    ):
        assert text.count("<b>") == text.count("</b>")