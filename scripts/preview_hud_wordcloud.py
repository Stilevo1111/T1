"""Render sample HUD-style word clouds into charts/ for visual review.

Usage:
    python scripts/preview_hud_wordcloud.py
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from chat_wordcloud.hud import generate_hud_wordcloud  # noqa: E402

CHAT_WORDS = [
    ("мид", 214), ("легенда", 187), ("импакт", 163), ("фраг", 148),
    ("вин", 132), ("поук", 119), ("ульт", 104), ("крина", 97),
    ("тим", 91), ("танк", 88), ("кд", 81), ("башня", 76),
    ("респ", 69), ("дедлайн", 64), ("про", 61), ("рейтинг", 57),
    ("см", 52), ("кс", 49), ("драфт", 45), ("пик", 43),
    ("трейл", 39), ("фарм", 36), ("инициация", 34), ("ротация", 31),
    ("вард", 29), ("смка", 27), ("оракул", 25), ("сигнал", 23),
    ("волна", 21), ("пуш", 19), ("гем", 18), ("крип", 16),
    ("аут", 15), ("бкб", 14), ("мид", 14), ("хард", 13),
    ("лайн", 12), ("джонгл", 11), ("деф", 10), ("офенс", 9),
]

ANALYTICS_WORDS = [
    ("ПОБЕД", 168), ("ИМПАКТ", 151), ("РОЛЬ", 133), ("МАТЧЕЙ", 124),
    ("СРЕДНИЙ", 112), ("ПОРАЖЕНИЙ", 98), ("УДАР", 87), ("ПОДДЕРЖКА", 76),
    ("КОРЕ", 68), ("ХЕРО", 61), ("СЛОТ", 57), ("ПРЕМЬЕРА", 52),
    ("ЛИНИЯ", 48), ("ПУШ", 44), ("ОБОРОНА", 41), ("ТЕМП", 38),
    ("ПРО", 35), ("АНАЛИЗ", 33), ("ГЕЙМ", 31), ("ТАЙМИНГ", 29),
    ("ПЛЮС", 27), ("МИНУС", 25), ("КАРТА", 24), ("РЕФРЕШ", 22),
    ("КЕШ", 20), ("ГРАФИК", 19), ("ИНДЕКС", 18), ("РАНГ", 17),
    ("ЗРИТЕЛИ", 16), ("МАТЧ", 15), ("ТУРНИР", 14), ("РЕЙТИНГ", 13),
]

SAMPLES = [
    (
        "charts/wordcloud_hud_chat.png",
        CHAT_WORDS,
        {
            "title": "ОБЛАКО СЛОВ ЧАТА",
            "subtitle": "01.08.2026 — 29.09.2026  •  30 ДНЕЙ",
            "footer": "СЛОВ: 38  •  СООБЩЕНИЙ: 12 480",
            "seed": 7,
        },
    ),
    (
        "charts/wordcloud_hud_analytics.png",
        ANALYTICS_WORDS,
        {
            "title": "ОБЛАКО СЛОВ АНАЛИТИКИ",
            "subtitle": "ПОСЛЕДНИЕ 10 МАТЧЕЙ  •  РОЛЬ: КОРЕ",
            "footer": "СРЕДНИЙ ИНДЕКС: 1.42  •  ПОБЕД: 6  •  ПОРАЖЕНИЙ: 4",
            "seed": 23,
        },
    ),
]


def main() -> None:
    out_dir = PROJECT_ROOT / "charts"
    out_dir.mkdir(parents=True, exist_ok=True)
    for relative, words, kwargs in SAMPLES:
        png = generate_hud_wordcloud(words, **kwargs)
        target = out_dir / Path(relative).name
        target.write_bytes(png)
        print(f"wrote {target.relative_to(PROJECT_ROOT)} ({len(png)} bytes)")


if __name__ == "__main__":
    main()
