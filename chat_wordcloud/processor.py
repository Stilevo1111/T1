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


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = text.lower()
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"t\.me/\S+", " ", text)
    text = re.sub(r"@\w+", " ", text)
    text = re.sub(r"#\w+", " ", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\[.*?\]\(.*?\)", " ", text)
    text = re.sub(r"`{1,3}.*?`{1,3}", " ", text)
    text = re.sub(r"[^\w\s\-+/]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def remove_emoji(text: str) -> str:
    emoji_pattern = re.compile(
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
    return emoji_pattern.sub(" ", text)


def filter_words(text: str) -> list[str]:
    text = remove_emoji(text)
    text = normalize_text(text)
    words = text.split()
    filtered = []
    for w in words:
        if len(w) < 2:
            continue
        if w.startswith("/"):
            continue
        if w in STOP_WORDS:
            continue
        if w.isdigit():
            continue
        if re.fullmatch(r"\d+", w):
            continue
        filtered.append(w)
    return filtered


def process_messages(messages: list[str]) -> Counter:
    counter: Counter = Counter()
    for msg in messages:
        if not msg:
            continue
        words = filter_words(msg)
        counter.update(words)
    return counter


def get_top_words(counter: Counter, max_words: int = WORDCLOUD_MAX_WORDS, min_freq: int = WORDCLOUD_MIN_WORD_FREQUENCY) -> list[tuple[str, int]]:
    if not counter:
        return []

    total_words = sum(counter.values())
    unique_words = len(counter)

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
