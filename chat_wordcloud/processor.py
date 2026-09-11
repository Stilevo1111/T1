"""WordCloud text processing utilities."""
import math
import re
import unicodedata
from collections import Counter

from chat_wordcloud.config import (
    STOP_WORDS,
    WORDCLOUD_DEBUG,
    WORDCLOUD_MAX_WORDS,
    WORDCLOUD_MIN_WORD_FREQUENCY,
)

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

# Fixed regex: Unicode-aware word boundaries for Cyrillic + Latin
WORD_RE = re.compile(r"[а-яёa-z0-9_+/]+", re.IGNORECASE)
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


def normalize_text(text: str) -> str:
    """Clean text keeping Cyrillic+Latin words."""
    text = unicodedata.normalize("NFKD", text)
    text = text.lower()
    text = URL_RE.sub(" ", text)
    text = MENTION_RE.sub(" ", text)
    text = HASHTAG_RE.sub(" ", text)
    text = HTML_RE.sub(" ", text)
    text = MARKDOWN_RE.sub(" ", text)
    text = CODE_RE.sub(" ", text)
    text = EMOJI_RE.sub(" ", text)
    # Keep only word chars (Cyrillic+Latin+digits+_+/), replace rest with space
    text = re.sub(r"[^\w\s\-+/]", " ", text, flags=re.UNICODE)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def filter_words(text: str) -> list[str]:
    """Extract meaningful words from a single message."""
    text = normalize_text(text)
    # Find all word-like tokens (Unicode-aware)
    words = WORD_RE.findall(text)

    filtered = []
    for w in words:
        if len(w) < 2:
            continue
        if w.startswith("/"):
            continue
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


def scale_frequencies(top_words: list[tuple[str, int]]) -> dict[str, float]:
    scaled = {}
    for word, count in top_words:
        scaled[word] = math.sqrt(count)
    return scaled


def log_top_words(top_words: list[tuple[str, int]], label: str = "TOP 20 WORDS") -> None:
    if not WORDCLOUD_DEBUG or not top_words:
        return
    lines = [label]
    for i, (word, count) in enumerate(top_words[:20], start=1):
        lines.append(f"{i}. {word} — {count}")
    logger = __import__("logging").getLogger(__name__)
    logger.info("\n".join(lines))