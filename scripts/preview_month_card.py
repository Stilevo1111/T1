"""Render a month word-cloud card from a synthetic chat, end to end.

Exercises the real pipeline (curate_words -> diff_periods -> card) on a
generated month of messages, so the layout can be reviewed without waiting for
real chat data.

Usage:
    python scripts/preview_month_card.py
"""
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from chat_wordcloud.curation import diff_periods, month_bounds_label  # noqa: E402
from chat_wordcloud.hud import generate_hud_wordcloud  # noqa: E402
from chat_wordcloud.processor import curate_words  # noqa: E402

# Current month: a Dota meta debate. The same users also talk about the old
# meta, so the month diff has something meaningful to show.
CURRENT = [
    ("кто мид", 34), ("мид на фарме", 22), ("легенда слишком жирная", 26),
    ("патч вышел", 30), ("новый герой имба", 28), ("баланс поломался", 24),
    ("вард на миде", 19), ("играем с рошакой", 21), ("имба патча", 17),
    ("кто саппорт", 14), ("росатка легла", 20), ("см отжал", 12),
    ("ульт дамагер", 11), ("дедлайн поджимает", 9), ("крина не работает", 10),
    ("тим не собрался", 13), ("рейтинг упал", 8), ("фрагов мало", 7),
    ("драфт пикнул", 9), ("кто на лёгком", 8), ("башня пала", 6),
    ("толкнули базу", 7), ("ищем мид", 8), ("жадный фарм", 6),
]
# Previous month: the old meta, mostly absent now.
PREVIOUS = [
    ("легенда", 60), ("см", 55), ("мид", 50), ("вард", 30),
    ("драфт", 25), ("фарм", 22), ("пик", 20), ("бан", 18),
]


def main() -> None:
    messages = [(text, i % 9) for i, (text, _n) in enumerate(CURRENT) for _ in range(2)]
    # One loud account, to show the flood control working.
    messages += [("кто мид", 4242)] * 30

    top_words = curate_words(messages, max_words=40)
    prev_words = curate_words([(w, i % 5) for i, (w, _n) in enumerate(PREVIOUS)],
                              max_words=40, use_phrases=False)
    rising, fading = diff_periods(
        Counter(dict(top_words)),
        Counter(dict(prev_words)),
        current_days=29,
        previous_days=31,
    )

    print(f"words kept: {len(top_words)}")
    for word, score in top_words[:12]:
        print(f"  {word:26} {score}")
    print(f"rising: {[w for w, _ in rising[:5]]}")
    print(f"fading: {[w for w, _ in fading[:5]]}")

    rising_label = "НОВЫЕ: " + ", ".join(w for w, _ in rising[:5]) if rising else ""
    png = generate_hud_wordcloud(
        top_words,
        title="ОБЛАКО СЛОВ ЧАТА",
        subtitle=f"{month_bounds_label(datetime.now())}  •  СРАВНЕНИЕ С ПРОШЛЫМ МЕСЯЦЕМ",
        footer=rising_label or "БЕЗ ИЗМЕНЕНИЙ",
        seed=17,
        color_ramp="palette",
        angles=[0] * 6 + [90, -90] * 2,
        max_font_size=66,
        relative_scaling=0.58,
        word_padding=3,
    )

    out_dir = PROJECT_ROOT / "charts" / "experiments"
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / "06_month_curated.png"
    target.write_bytes(png)
    print(f"wrote {target.relative_to(PROJECT_ROOT)} ({len(png)} bytes)")


if __name__ == "__main__":
    main()
