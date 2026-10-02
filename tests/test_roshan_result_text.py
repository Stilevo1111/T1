"""Tests for the Roshan closing message (build_result_text).

The message is a public group announcement and has to answer two questions:
who walked off with which artifact, and what that artifact does next. It used
to answer neither well - the artifact lines carried random flavour quotes
instead of the effect, and the players who pressed and came away empty-handed
were reduced to a bare count.
"""

import re

from constants import ROSHAN_AEGIS_EFFECTS, ROSHAN_CHEESE_EFFECTS
from roshan import ITEM_EFFECTS, ITEM_LABELS, build_result_text

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
    """The point of the message: the real effect, drawn from the pool."""
    text = _render(
        {1: "aegis", 2: "cheese"}, {1: "went_Dr", 2: "mikhessssha"}, [],
    )
    for item in ("aegis", "cheese"):
        assert any(effect in text for effect in ITEM_EFFECTS[item])


def test_aegis_label_says_it_protects_against_a_negative_roll():
    """apply_aegis zeroes a negative roll; the label has to say which sign it eats.

    The pool was once full of sentences ("минус обнулится полностью; плюс
    АЕГИС не потратит"). Short labels were requested instead, so the requirement
    is the sign being named, not the positive-roll caveat spelled out.
    """
    for effect in ROSHAN_AEGIS_EFFECTS:
        assert re.search(r"минус", effect), effect


def test_cheese_label_says_it_scales_a_positive_roll():
    """apply_cheese multiplies a positive roll by 1.5 and leaves a minus alone.

    The label is deliberately the plain "усиление плюса": the exact multiplier
    is not needed in the award announcement, because apply_cheese prints
    "🧀 СЫР ×1.5 = +18.0 см (было +12.0 см)" on the roll that actually fires.
    """
    assert any(re.search(r"плюс|умножение|усиление|жирн", effect)
               for effect in ROSHAN_CHEESE_EFFECTS)


def test_effect_labels_stay_short():
    """These are inline labels on one line each, not paragraphs."""
    for effect in ROSHAN_AEGIS_EFFECTS + ROSHAN_CHEESE_EFFECTS:
        assert len(effect) <= 30, effect


def test_one_line_per_artifact():
    """No stacked header/indent columns - that was the overloaded layout."""
    text = _render(
        {1: "aegis", 2: "cheese"}, {1: "went_Dr", 2: "mikhessssha"}, ["vasya"],
    )
    artifact_lines = [
        line for line in text.splitlines()
        if any(label in line for label in ITEM_LABELS.values())
    ]
    assert len(artifact_lines) == 2
    for line in artifact_lines:
        assert line.startswith(tuple(EMOJI.findall("".join(ITEM_LABELS.values()))))
        assert not line.startswith(" "), "no indentation under an artifact"


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