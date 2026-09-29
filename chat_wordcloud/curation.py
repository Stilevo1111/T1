"""Word curation for the chat word cloud.

The plain pipeline in :mod:`chat_wordcloud.processor` counts raw tokens, which
gives three poor results on a real game chat:

* inflected forms of one word show up as separate entries
  ("победа" / "побед" / "победили" / "победой");
* real expressions are lost, because only single words are counted
  ("росатка легла" becomes "росатка" + "легла");
* a single spammer, or one extremely common word, can dominate the card.

Everything here is a pure function over strings and counters so it can be
tested without a database. No third-party NLP dependency is used: a light
suffix stemmer is enough for game-chat slang and keeps ``requirements.txt``
untouched.
"""
import math
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta

# --- Russian light stemmer -------------------------------------------------
# Ordered longest-first, and up to three suffixes are removed so that a past
# tense form still folds onto the same root as its other inflections
# ("победа" / "побед" / "победили" / "победой" -> "побед").
_SUFFIXES = (
    "иями", "ями", "ами", "ого", "его", "ому", "ему", "ыми", "ими", "ился",
    "илась", "ились", "ений", "ания", "ения", "остью", "ость", "ешь", "ете",
    "ишь", "ите", "ует", "ают", "яют", "лся", "лась", "лись", "ть", "ешь",
    "ах", "ией", "ей", "ов", "ев", "ии", "ие", "ый", "ая", "ое", "ые", "ым",
    "им", "ой", "ом", "ем", "л", "у", "ю", "а", "я", "ы", "и", "о", "е", "ь",
)
_MIN_STEM = 4
_MAX_SUFFIX_STRIPS = 3

# Chat fillers: kept in the counter (so phrases like "кто мид" can be built)
# but heavily discounted in the final score instead of being dropped outright.
FILLER_WORDS = {
    "да", "нет", "а", "и", "ну", "ага", "угу", "ого", "даа", "хм", "хз",
    "кхм", "блин", "аа", "оо", "уу", "кажется", "видимо", "наверное",
    "чтото", "ктото", "какойто", "какой", "этот", "эта", "тут", "там",
}

# Masked rather than dropped: the word stays visible as *** so the card still
# reflects what the chat was about without printing the word itself.
# Matching is done per whole token on a *prefix* basis, never as a substring:
# a substring match for "еб" would also swallow "хлеб".
_PROFANITY_PREFIXES = (
    "хуй", "хуе", "хуя", "пизд", "ебан", "ебал", "ебат", "ёбан", "блядь",
    "бляд", "блят", "сук", "мудак", "мудил", "гандон", "долбоеб", "долбоёб",
    "ублюдок", "мраз", "сдохн", "залуп",
)
_PROFANITY_WORD_RE = re.compile(r"[а-яёa-z]+", re.IGNORECASE)

# Innocent words that a prefix rule would otherwise catch ("сукно" starts with
# the same three letters as the profanity stem). Checked before masking.
PROFANITY_ALLOWLIST = {"сукно", "сухарь", "хлеб", "хлебница"}

PROFANITY_PLACEHOLDER = "***"


def _is_profane_token(token: str) -> bool:
    lowered = token.lower()
    if lowered in PROFANITY_ALLOWLIST:
        return False
    return any(
        lowered == root or (lowered.startswith(root) and len(lowered) - len(root) <= 3)
        for root in _PROFANITY_PREFIXES
    )


def mask_profanity(text: str) -> str:
    """Replace profane words with ``***`` instead of deleting them.

    Deleting would silently drop a large share of an average game chat; masking
    keeps the card honest while keeping the screen clean.
    """
    return _PROFANITY_WORD_RE.sub(
        lambda m: PROFANITY_PLACEHOLDER if _is_profane_token(m.group(0)) else m.group(0),
        text,
    )


def stem_ru(word: str) -> str:
    """Fold common Russian inflections onto a shared stem.

    Deliberately shallow: at most two suffixes are stripped and the result is
    never shorter than ``_MIN_STEM`` characters, so short slang
    ("мид", "кд") survives untouched.
    """
    if len(word) <= _MIN_STEM or not any(ch.isalpha() for ch in word):
        return word
    stem = word
    for _ in range(_MAX_SUFFIX_STRIPS):
        for suffix in _SUFFIXES:
            if stem.endswith(suffix) and len(stem) - len(suffix) >= _MIN_STEM:
                stem = stem[: -len(suffix)]
                break
        else:
            break
    return stem


def collapse_inflections(counter: Counter, *, min_count: int = 1) -> Counter:
    """Merge word forms that share a stem into the most frequent spelling.

    "победа": 12, "побед": 9, "победили": 4 -> {"победа": 25}.
    The surface form that survives is the most frequent one, so the card still
    reads naturally.
    """
    buckets: dict[str, Counter] = defaultdict(Counter)
    for word, count in counter.items():
        if count < min_count:
            continue
        buckets[stem_ru(word)][word] += count

    merged: Counter = Counter()
    for forms in buckets.values():
        if len(forms) == 1:
            merged.update(forms)
            continue
        winner = max(forms.items(), key=lambda kv: (kv[1], -len(kv[0]), kv[0]))[0]
        merged[winner] = sum(forms.values())
    return merged


# --- Phrases ---------------------------------------------------------------
# A bigram is kept only when the two words stick together far more often than
# chance would predict. "кто мид" survives; "кто орёт" does not.
_PHRASE_STOP_FIRST = {"какой", "это", "вот", "the", "a", "is"}
_PHRASE_MIN_LENGTH = 2
_PHRASE_MIN_COUNT = 2
_PHRASE_PMI_THRESHOLD = 2.0


def extract_phrases(
    token_lists: list[list[str]],
    *,
    min_count: int = _PHRASE_MIN_COUNT,
    pmi_threshold: float = _PHRASE_PMI_THRESHOLD,
) -> Counter:
    """Return multi-word expressions that occur more often than chance.

    ``token_lists`` is one already-filtered token list per message, so a phrase
    can never straddle a message boundary.
    """
    bigrams: Counter = Counter()
    unigrams: Counter = Counter()

    for tokens in token_lists:
        if not tokens:
            continue
        unigrams.update(tokens)
        for left, right in zip(tokens, tokens[1:]):
            if left in _PHRASE_STOP_FIRST or right in _PHRASE_STOP_FIRST:
                continue
            bigrams[(left, right)] += 1

    total_pairs = sum(bigrams.values())
    if not total_pairs:
        return Counter()

    phrases: Counter = Counter()
    for (left, right), count in bigrams.items():
        if count < min_count:
            continue
        # Pointwise mutual information: how far above chance the pair is.
        p_pair = count / total_pairs
        p_left = unigrams[left] / sum(unigrams.values())
        p_right = unigrams[right] / sum(unigrams.values())
        pmi = math.log2(p_pair / (p_left * p_right)) if p_left and p_right else 0.0
        if pmi >= pmi_threshold:
            phrases[f"{left} {right}"] = count
    return phrases


def select_phrases(
    phrases: Counter,
    *,
    max_phrases: int = 8,
) -> Counter:
    """Greedily keep the strongest phrases that do not share words.

    Without this, a chat with a repeating rhythm produces "кто мид", "мид на"
    and "на позиции" at once and the cloud turns into word soup. Candidates are
    taken strongest-first and any phrase reusing an already-chosen word is
    skipped, so the card shows several distinct expressions.
    """
    selected: Counter = Counter()
    used: set[str] = set()
    for phrase, count in phrases.most_common():
        if len(selected) >= max_phrases:
            break
        tokens = set(phrase.split())
        if tokens & used:
            continue
        selected[phrase] = count
        used |= tokens
    return selected


# --- Scoring ---------------------------------------------------------------


def apply_flood_penalty(
    counter: Counter,
    per_author: dict[str, Counter] | None,
    *,
    threshold: float = 0.6,
    min_count: int = 8,
    max_reduction: float = 0.5,
    min_authors: int = 3,
) -> Counter:
    """Downweight words that essentially one author is responsible for.

    ``per_author`` maps an author id to that author's own word counts.

    Three guards keep this from crushing legitimate topics:

    * ``min_count`` - a word said a couple of times cannot be a flood;
    * ``min_authors`` - with one or two active speakers there is nothing to
      spread a word across, so no penalty is applied at all;
    * ``max_reduction`` - even a 100% single-author word keeps half its weight,
      because a topic only one member ever raises is still a real topic.
    """
    if not per_author:
        return counter
    if not counter:
        return counter

    contributing = [counts for counts in per_author.values() if sum(counts.values())]
    if len(contributing) < min_authors:
        return counter

    adjusted: Counter = Counter()
    for word, count in counter.items():
        if count < min_count:
            adjusted[word] = count
            continue
        top_share = 0.0
        for author_counts in per_author.values():
            if author_counts[word]:
                top_share = max(top_share, author_counts[word] / count)
        if top_share <= threshold:
            adjusted[word] = count
            continue
        excess = (top_share - threshold) / (1.0 - threshold)
        adjusted[word] = max(1, int(round(count * (1.0 - max_reduction * excess))))
    return adjusted


def score_words(
    counter: Counter,
    *,
    document_count: int = 0,
    fillers: set[str] | None = FILLER_WORDS,
    filler_factor: float = 0.25,
    dominance_penalty: float = 0.6,
    min_score: float = 1.0,
) -> list[tuple[str, int]]:
    """Rank words by "how interesting is this", not just "how often said".

    Combines three corrections on top of raw frequency:

    * a mild IDF term, so a word that appears in every message counts less
      than one that characterises the period;
    * a discount for conversational fillers ("да", "ага", "блин");
    * a sublinear damping of the very top word, so one runaway token cannot
      take the whole card.
    """
    if not counter:
        return []

    total = sum(counter.values())
    if not total:
        return []

    documents = max(1, document_count)
    scored: list[tuple[str, float]] = []
    for word, count in counter.items():
        score = float(count)

        # Sublinear damping + mild IDF novelty bonus.
        score *= count ** (dominance_penalty - 1.0)
        if document_count:
            idf = math.log((documents + 1) / (count / max(1, total) * documents + 1)) + 1.0
            score *= max(1.0, idf)

        if fillers and word in fillers:
            score *= filler_factor

        if score >= min_score:
            scored.append((word, score))

    scored.sort(key=lambda kv: (-kv[1], kv[0]))
    return [(word, max(1, int(round(score)))) for word, score in scored]


# --- Calendar month --------------------------------------------------------

MONTH_NAMES_RU = (
    "январь", "февраль", "март", "апрель", "май", "июнь",
    "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь",
)
MONTH_NAMES_RU_GEN = (
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
)


def month_bounds(moment: datetime) -> tuple[datetime, datetime]:
    """Return ``(start, end)`` of the calendar month containing ``moment``."""
    start = moment.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)
    return start, end


def previous_month_bounds(moment: datetime) -> tuple[datetime, datetime]:
    """Return the bounds of the month immediately before ``moment``'s month."""
    start, _ = month_bounds(moment)
    prev_end = start
    prev_start = prev_end - timedelta(days=1)
    prev_start = prev_start.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return prev_start, prev_end


def month_label(moment: datetime) -> str:
    """Human label for the month, e.g. ``сентябрь 2026``."""
    return f"{MONTH_NAMES_RU[moment.month - 1]} {moment.year}"


def month_bounds_label(moment: datetime) -> str:
    """Compact range label, e.g. ``01.09 — 30.09.2026``."""
    start, end = month_bounds(moment)
    last_day = end - timedelta(days=1)
    return f"{start.strftime('%d.%m')} — {last_day.strftime('%d.%m.%Y')}"


def diff_periods(
    current: Counter,
    previous: Counter,
    *,
    min_count: int = 2,
    current_days: float = 1.0,
    previous_days: float = 1.0,
) -> tuple[list[tuple[str, int]], list[tuple[str, int]]]:
    """Compare two periods, returning ``(rising, fading)`` words.

    ``rising`` are words that are frequent now and were rare (or absent)
    before — the "what the chat is about this month" list. ``fading`` are the
    ones that were big last period and are now gone.

    Counts are normalised to a per-day rate before comparing. Comparing raw
    shares would mark a word as "rising" purely because the current month had
    less traffic overall, which is exactly the noise this function exists to
    remove. ``current_days``/``previous_days`` default to 1, i.e. equal-length
    periods, so callers that do not care can ignore them.
    """
    current_days = max(1.0, current_days)
    previous_days = max(1.0, previous_days)

    rising: list[tuple[str, int]] = []
    for word, count in current.items():
        if count < min_count:
            continue
        now_rate = count / current_days
        was_rate = previous.get(word, 0) / previous_days
        if was_rate == 0:
            rising.append((word, count))
        elif now_rate > was_rate * 1.25:
            rising.append((word, count))

    fading: list[tuple[str, int]] = []
    for word, count in previous.items():
        if count < min_count:
            continue
        was_rate = count / previous_days
        now_rate = current.get(word, 0) / current_days
        if now_rate == 0:
            fading.append((word, count))
        elif was_rate > now_rate * 1.25:
            fading.append((word, count))

    rising.sort(key=lambda kv: (-kv[1], kv[0]))
    fading.sort(key=lambda kv: (-kv[1], kv[0]))
    return rising, fading
