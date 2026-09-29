"""Tests for the word-cloud curation layer (stems, phrases, scoring, month diff)."""
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from chat_wordcloud.curation import (  # noqa: E402
    PROFANITY_PLACEHOLDER,
    apply_flood_penalty,
    collapse_inflections,
    diff_periods,
    extract_phrases,
    mask_profanity,
    month_bounds,
    month_bounds_label,
    month_label,
    previous_month_bounds,
    score_words,
    select_phrases,
    stem_ru,
)
from chat_wordcloud.processor import curate_words, filter_words  # noqa: E402

# --- Stemmer ---------------------------------------------------------------

@pytest.mark.parametrize(
    "forms",
    [
        ["победа", "побед", "победили", "победой", "победу"],
        ["играть", "играли", "играл", "играем"],
        ["вард", "варды", "вардом"],
        ["легенда", "легенд", "легенды", "легенду"],
    ],
)
def test_inflections_share_one_stem(forms):
    """All forms of a word must fold onto a single stem."""
    assert len({stem_ru(f) for f in forms}) == 1


@pytest.mark.parametrize("short", ["мид", "кд", "имба", "вард", "пуш"])
def test_short_slang_survives_stemming(short):
    """Short game slang must not be mangled by suffix stripping."""
    assert stem_ru(short) == short


def test_stemming_is_idempotent():
    assert stem_ru(stem_ru("победили")) == stem_ru("победили")


def test_collapse_merges_forms_into_commonest_spelling():
    counter = Counter({"победа": 12, "побед": 9, "победили": 4, "вард": 5})
    merged = collapse_inflections(counter)
    assert merged["победа"] == 25
    assert "побед" not in merged
    assert merged["вард"] == 5


def test_collapse_keeps_distinct_words_separate():
    counter = Counter({"мид": 10, "вард": 8, "база": 6})
    assert dict(collapse_inflections(counter)) == dict(counter)


# --- Profanity -------------------------------------------------------------

@pytest.mark.parametrize(
    "text,expected",
    [
        ("блять это имба", f"{PROFANITY_PLACEHOLDER} это имба"),
        ("пиздец", PROFANITY_PLACEHOLDER),
        ("долбоеб", PROFANITY_PLACEHOLDER),
    ],
)
def test_profanity_is_masked_not_dropped(text, expected):
    assert mask_profanity(text) == expected


@pytest.mark.parametrize("innocent", ["хлеб", "сукно", "хорошо", "вард", "норм"])
def test_ordinary_words_are_not_masked(innocent):
    """A substring rule would swallow 'хлеб' (root 'еб') and 'сукно'."""
    assert mask_profanity(innocent) == innocent


def test_masking_preserves_surrounding_words():
    """Masking must not disturb punctuation or neighbouring text."""
    assert mask_profanity("GG, сука! gg") == f"GG, {PROFANITY_PLACEHOLDER}! gg"


# --- Token filtering -------------------------------------------------------

def test_overlong_tokens_are_dropped():
    """A 40-character 'word' is a run-on, not something to render at 60px."""
    assert filter_words("а" * 40) == []
    assert filter_words("а" * 19) == ["а" * 19]


@pytest.mark.parametrize(
    "text,expected",
    [
        ("жадный фарм", ["жадный", "фарм"]),
        ("дедлайн поджимает", ["дедлайн", "поджимает"]),
        ("красный ключ", ["красный", "ключ"]),
        ("толкнули базу", ["толкнули", "базу"]),
    ],
)
def test_normalization_keeps_short_i_intact(text, expected):
    """NFKD used to split 'й' into 'и' + a combining mark, mangling the word."""
    assert filter_words(text) == expected


def test_normalization_keeps_yo():
    assert "её" in filter_words("её посадили")


# --- Phrases ---------------------------------------------------------------

def test_sticky_bigrams_become_phrases():
    token_lists = [["кто", "мид"]] * 5 + [["кто", "бегает"], ["кто", "молчит"]]
    phrases = extract_phrases(token_lists)
    assert "кто мид" in phrases
    assert "кто бегает" not in phrases


def test_phrase_never_straddles_two_messages():
    token_lists = [["мид"], ["мид"]]
    assert extract_phrases(token_lists) == Counter()


def test_select_phrases_keeps_non_overlapping_expressions():
    """Overlapping candidates would render as word soup."""
    candidates = Counter({"кто мид": 9, "мид на": 8, "на позиции": 7, "вард ставлю": 5})
    selected = select_phrases(candidates, max_phrases=8)
    assert set(selected) == {"кто мид", "на позиции", "вард ставлю"}


def test_select_phrases_respects_the_cap():
    candidates = Counter({f"слово{i} два{i}": 10 - i for i in range(20)})
    assert len(select_phrases(candidates, max_phrases=3)) == 3


def test_select_phrases_rejects_overlapping_candidates():
    """'кто мид' and 'на позиции' are disjoint; 'мид на' overlaps both."""
    candidates = Counter({"кто мид": 9, "мид на": 8, "на позиции": 7})
    assert set(select_phrases(candidates)) == {"кто мид", "на позиции"}


# --- Scoring ---------------------------------------------------------------

def test_scoring_damps_a_dominant_word():
    """A runaway token must not take the whole card."""
    counter = Counter({"мид": 400, "вард": 40, "легенда": 40})
    scored = dict(score_words(counter, document_count=100))
    assert scored["мид"] < 400
    assert scored["мид"] > scored["вард"]


def test_fillers_are_discounted_but_survive():
    """'да' should rank low without disappearing from phrases entirely."""
    scored = dict(score_words(Counter({"мид": 50, "да": 40}), document_count=10))
    assert "да" in scored
    assert scored["да"] < scored["мид"]


def test_scoring_empty_counter_returns_empty():
    assert score_words(Counter()) == []


# --- Flood control ---------------------------------------------------------

def test_flood_control_shrinks_a_single_author_word():
    # Three speakers share "вард" (20 each = 60); one account says "мид" 390
    # of 400 times.
    counter = Counter({"мид": 400, "вард": 60})
    per = {
        "u1": Counter({"мид": 4, "вард": 20}),
        "u2": Counter({"мид": 3, "вард": 20}),
        "u3": Counter({"мид": 3, "вард": 20}),
        "spammer": Counter({"мид": 390}),
    }
    adjusted = apply_flood_penalty(counter, per)
    assert adjusted["мид"] < counter["мид"]
    assert adjusted["вард"] == counter["вард"]


def test_flood_control_keeps_itself_disabled_for_tiny_chats():
    """With two speakers there is nothing to spread a word across."""
    counter = Counter({"мид": 400})
    per = {"u1": Counter({"мид": 390}), "u2": Counter({"мид": 10})}
    assert apply_flood_penalty(counter, per) == counter


def test_flood_control_ignores_rare_words():
    """A word said twice cannot be a flood."""
    counter = Counter({"мид": 2})
    per = {"u1": Counter({"мид": 2}), "u2": Counter({"мид": 1}), "u3": Counter({"мид": 1})}
    assert apply_flood_penalty(counter, per) == counter


# --- Calendar month --------------------------------------------------------

def test_month_bounds_cover_the_whole_month():
    start, end = month_bounds(datetime(2026, 9, 29, 15, 30))
    assert start == datetime(2026, 9, 1)
    assert end == datetime(2026, 10, 1)


def test_month_bounds_roll_over_december():
    start, end = month_bounds(datetime(2026, 12, 5))
    assert (start, end) == (datetime(2026, 12, 1), datetime(2027, 1, 1))


def test_previous_month_crosses_the_year_boundary():
    prev_start, prev_end = previous_month_bounds(datetime(2026, 1, 15))
    assert (prev_start, prev_end) == (datetime(2025, 12, 1), datetime(2026, 1, 1))


def test_month_labels():
    assert month_label(datetime(2026, 9, 29)) == "сентябрь 2026"
    assert month_bounds_label(datetime(2026, 9, 29)) == "01.09 — 30.09.2026"
    assert month_bounds_label(datetime(2026, 2, 3)) == "01.02 — 28.02.2026"


# --- Period diff -----------------------------------------------------------

def test_diff_finds_rising_and_fading_words():
    current = Counter({"патч": 50, "мид": 40, "легенда": 5})
    previous = Counter({"легенда": 60, "мид": 40, "старыйгерой": 40})
    rising, fading = diff_periods(current, previous)
    assert "патч" in dict(rising)
    assert "легенда" in dict(fading)
    # An unchanged word belongs to neither list.
    assert "мид" not in dict(rising)
    assert "мид" not in dict(fading)


def test_diff_ignores_rare_words():
    rising, fading = diff_periods(Counter({"патч": 1}), Counter({"легенда": 1}))
    assert rising == [] and fading == []


def test_diff_normalises_by_period_length():
    """A busier month must not make every unchanged word look 'rising'."""
    current = Counter({"легенда": 40, "патч": 10})
    previous = Counter({"легенда": 20, "легенда_старый": 30})
    rising, _ = diff_periods(
        current, previous, current_days=30, previous_days=15
    )
    names = dict(rising)
    # 40/30 per day vs 20/15 per day: the rate barely moved, so it is not new.
    assert "легенда" not in names
    assert "патч" in names


# --- Full pipeline ---------------------------------------------------------

def _chat(users=6, rounds=20, spammer_rounds=0):
    messages = []
    for i in range(rounds):
        u = i % users
        messages.append(("мид фармлю легенда", u))
        messages.append(("кто мид на позиции", u))
        messages.append(("росатка легла рошатка выглядит имба", u))
        messages.append(("вард ставлю база", u))
    for i in range(spammer_rounds):
        messages.append(("спамспамспамспамспамспамспамспамспамспам", 999))
    return messages


def test_curation_folds_forms_and_extracts_phrases():
    result = dict(curate_words(_chat(), max_words=30))
    # The repeated phrasing must show up as expressions, not as single words.
    phrases = [word for word in result if " " in word]
    assert phrases
    # A word absorbed into an expression must not also stand alone, otherwise
    # the card shows "кто мид" next to "кто" and "мид".
    for phrase in phrases:
        for token in phrase.split():
            assert token not in result


def test_curation_removes_gibberish_runs():
    result = dict(curate_words(_chat(spammer_rounds=40), max_words=30))
    assert not any(len(word) > 20 for word in result)


def test_curation_accepts_plain_strings():
    """Legacy callers pass bare message strings, without author ids."""
    result = curate_words(["мид легенда", "кто мид", "мид легенда"], max_words=10)
    assert result
    assert all(isinstance(word, str) for word, _ in result)


def test_curation_handles_empty_input():
    assert curate_words([]) == []
    assert curate_words(["", None]) == []


def test_curation_can_be_disabled_to_legacy_behaviour():
    """use_phrases=False must return single words only."""
    result = curate_words(_chat(), max_words=30, use_phrases=False)
    assert all(" " not in word for word, _ in result)


def test_curation_scores_are_positive_ints():
    for _, score in curate_words(_chat(), max_words=30):
        assert isinstance(score, int) and score >= 1


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
