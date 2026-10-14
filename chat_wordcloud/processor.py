"""WordCloud text processing utilities."""
import logging
import re
import unicodedata
from collections import Counter, defaultdict

from chat_wordcloud.config import (
    STOP_WORDS,
    WORDCLOUD_DEBUG,
    WORDCLOUD_MAX_WORDS,
    WORDCLOUD_MIN_WORD_FREQUENCY,
)
from chat_wordcloud.curation import (
    PROFANITY_PLACEHOLDER,
    apply_flood_penalty,
    collapse_inflections,
    extract_phrases,
    mask_profanity,
    score_words,
    select_phrases,
)

logger = logging.getLogger(__name__)

# Bot-specific words to exclude (separate from general stopwords)
BOT_SYSTEM_WORDS = {
    # Bot commands & system
    "фиссура", "профиль", "ранг", "ммр", "старт", "меню", "кнопка",
    "ошибка", "успешно", "обновлено", "привязан", "steam", "stеam",
    "войс", "войсчат", "айди", "юзер", "чат", "бот", "команда",
    "кд", "кулдаун", "анализ", "статистика", "топ", "лидер",
    "добро", "пожаловать", "привет", "пока", "спасибо", "пожалуйста",
    # Bot message templates
    "хукаю", "график", "аналитик", "неделя", "чемпион", "фиссура",
    "фпс", "пинг", "лаги", "баг", "фича", "апдейт", "патч",
}

# Combined stopwords: general + bot-specific
EFFECTIVE_STOP_WORDS = STOP_WORDS | BOT_SYSTEM_WORDS

# Fixed regex: Unicode-aware word boundaries for Cyrillic + Latin.
# '*' is included solely so the profanity placeholder from
# chat_wordcloud.curation.mask_profanity survives tokenisation. Without it the
# placeholder was stripped here and the masked word vanished from the card
# entirely, which is exactly what masking is supposed to avoid. Real markdown
# emphasis never reaches this point: MARKDOWN_RE drops `[text](url)` links and
# '*bold*' degrades to 'bold' here, so no stray asterisks are left to tokenise.
WORD_RE = re.compile(r"[а-яёa-z0-9_+/*]+", re.IGNORECASE)
URL_RE = re.compile(r"https?://\S+|t\.me/\S+")
MENTION_RE = re.compile(r"@\w+")
HASHTAG_RE = re.compile(r"#\w+")
HTML_RE = re.compile(r"<[^>]+>")
MARKDOWN_RE = re.compile(r"\[.*?\]\(.*?\)")
CODE_RE = re.compile(r"`{1,3}.*?`{1,3}")
EMOJI_RE = re.compile(
    "["
    "\U0001F600-\U0001F64F"
    "\U0001F300-\U0001F5FF"
    "\U0001F680-\U0001F6FF"
    "\U0001F1E0-\U0001F1FF"
    "\U00002702-\U000027B0"
    "\U000024C2-\U0001F251"
    "\U0001f926-\U0001f937"
    "\u200d"
    "\u2640-\u2642"
    "\u2600-\u2B55"
    "\u23cf"
    "\ufe0f"
    "]+",
    flags=re.UNICODE,
)


COMBINING_MARK_RE = re.compile(r"[\u0300-\u036f\u1ab0-\u1aff\u1dc0-\u1dff\u20d0-\u20ff\ufe20-\ufe2f]")


def normalize_text(text: str) -> str:
    """Clean text keeping Cyrillic+Latin words."""
    # NFC, not NFKD: NFKD decomposes "й" into "и" + COMBINING BREVE, so
    # "жадный" became "жадныи" and "дедлайн" split into "дедлаи" + "н".
    # NFC composes instead of decomposes and keeps Cyrillic letters intact.
    # Any stray marks are removed as a safety net for odd input.
    text = COMBINING_MARK_RE.sub("", unicodedata.normalize("NFC", text))
    text = text.lower()
    text = URL_RE.sub(" ", text)
    text = MENTION_RE.sub(" ", text)
    text = HASHTAG_RE.sub(" ", text)
    text = HTML_RE.sub(" ", text)
    text = MARKDOWN_RE.sub(" ", text)
    text = CODE_RE.sub(" ", text)
    text = EMOJI_RE.sub(" ", text)
    # Keep only word chars (Cyrillic+Latin+digits+_+/*), replace rest with space.
    # '*' is kept for the profanity placeholder - see WORD_RE.
    text = re.sub(r"[^\w\s\-+/*]", " ", text, flags=re.UNICODE)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


# Longest token kept on a card. Beyond this a "word" is a run-on, a URL that
# survived normalisation, or a keyboard mash - never something a reader wants
# to see rendered at 60px.
MAX_WORD_LENGTH = 20


def filter_words(text: str) -> list[str]:
    """Extract meaningful words from a single message."""
    text = normalize_text(text)
    # Find all word-like tokens (Unicode-aware)
    words = WORD_RE.findall(text)

    filtered = []
    for w in words:
        if len(w) < 2:
            continue
        if len(w) > MAX_WORD_LENGTH:
            continue
        if w.startswith("/"):
            continue
        # Asterisks reach us from two places: markdown emphasis ("**жир**", which
        # MARKDOWN_RE does not strip - it only handles links) and the profanity
        # placeholder ("***"). Strip emphasis marks so the word underneath
        # survives, but keep a token that is nothing but asterisks: that is the
        # placeholder, and dropping it would put the profane word back on the
        # card, which is exactly what mask_profanity exists to prevent.
        if "*" in w:
            core = w.strip("*")
            if not core:
                w = PROFANITY_PLACEHOLDER
            else:
                w = core
        if w in EFFECTIVE_STOP_WORDS:
            continue
        if w.isdigit():
            continue
        # Skip pure numbers with separators like "10/20"
        if re.fullmatch(r"[\d/]+", w):
            continue
        filtered.append(w)
    return filtered


def process_messages(messages: list[str]) -> Counter:
    """Process all messages into word frequency counter."""
    counter: Counter = Counter()
    for msg in messages:
        if not msg:
            continue
        words = filter_words(msg)
        counter.update(words)
    return counter


def get_top_words(
    counter: Counter,
    max_words: int = WORDCLOUD_MAX_WORDS,
    min_freq: int = WORDCLOUD_MIN_WORD_FREQUENCY,
) -> list[tuple[str, int]]:
    if not counter:
        return []

    total_words = sum(counter.values())
    unique_words = len(counter)

    # Adaptive minimum frequency
    if total_words <= 50 or unique_words <= 20:
        effective_min = 1
    elif total_words <= 200 or unique_words <= 60:
        effective_min = 2
    else:
        effective_min = min_freq

    filtered = [(w, c) for w, c in counter.items() if c >= effective_min]
    filtered.sort(key=lambda x: x[1], reverse=True)
    return filtered[:max_words]


def curate_words(
    messages: list[str] | list[tuple[str, int | None]],
    *,
    max_words: int = WORDCLOUD_MAX_WORDS,
    use_phrases: bool = True,
    use_flood_control: bool = True,
    max_phrase_count: int = 8,
) -> list[tuple[str, int]]:
    """Full curation pipeline: clean -> fold -> score -> rank.

    ``messages`` may be plain strings or ``(text, user_id)`` pairs; author ids
    are only needed for flood control, which is skipped otherwise.

    Steps, in order:

    1. tokenize each message (URLs, mentions, code and emoji already removed),
       masking profanity to ``***`` rather than dropping the word;
    2. fold inflected forms onto a shared stem, keeping the commonest spelling;
    3. damp words that a single account is responsible for;
    4. add multi-word expressions that occur more often than chance;
    5. rank by a novelty-aware score instead of raw frequency.
    """
    if not messages:
        return []

    texts: list[str] = []
    per_author: dict[int, Counter] = defaultdict(Counter)
    author_known = False

    for item in messages:
        if isinstance(item, tuple):
            text = item[0]
            user_id = item[1] if len(item) > 1 else None
            author_known = True
        else:
            text, user_id = item, None
        if not text:
            continue
        texts.append(text)
        if use_flood_control and author_known and user_id is not None:
            per_author[user_id].update(filter_words(mask_profanity(text)))

    if not texts:
        return []

    token_lists = [filter_words(mask_profanity(text)) for text in texts]
    counter: Counter = Counter()
    for tokens in token_lists:
        counter.update(tokens)
    if not counter:
        return []

    counter = collapse_inflections(counter)
    if use_flood_control and per_author:
        by_stem: dict[int, Counter] = defaultdict(Counter)
        for author, counts in per_author.items():
            for word, count in collapse_inflections(counts).items():
                by_stem[author][word] = count
        counter = apply_flood_penalty(counter, by_stem)

    if use_phrases:
        phrases = select_phrases(extract_phrases(token_lists), max_phrases=max_phrase_count)
        if phrases:
            phrase_words = set()
            for phrase in phrases:
                phrase_words.update(phrase.split())
            # A phrase replaces the words it is built from, otherwise the
            # card would show "кто мид" and "кто" and "мид" all at once.
            for word in phrase_words:
                counter.pop(word, None)
            counter.update(phrases)

    scored = score_words(counter, document_count=len(token_lists))
    return scored[:max_words]


def log_top_words(top_words: list[tuple[str, int]], label: str = "TOP 20 WORDS") -> None:
    if not WORDCLOUD_DEBUG or not top_words:
        return
    lines = [label]
    for i, (word, count) in enumerate(top_words[:20], start=1):
        lines.append(f"{i}. {word} — {count}")
    logger.info("\n".join(lines))
