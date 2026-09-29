"""Render the framed + mixed-orientation word cloud in three colour schemes.

This is the variant the design review picked: panel on, words rotated at mixed
angles. The open question was colouring, so the same layout is rendered with
the multi-colour "palette" ramp (one colour per word, cycled from the same
ACCENTS list the analytics chart uses) in three different palettes.

Usage:
    python scripts/preview_hud_palette.py
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from chat_wordcloud.hud import generate_hud_wordcloud  # noqa: E402

CHAT = [
    ("мид", 214), ("легенда", 187), ("импакт", 163), ("фраг", 148), ("вин", 132),
    ("поук", 119), ("ульт", 104), ("крина", 97), ("тим", 91), ("танк", 88),
    ("кд", 81), ("башня", 76), ("респ", 69), ("дедлайн", 64), ("про", 61),
    ("рейтинг", 57), ("см", 52), ("кс", 49), ("драфт", 45), ("пик", 43),
    ("трейл", 39), ("фарм", 36), ("инициация", 34), ("ротация", 31), ("вард", 29),
    ("смка", 27), ("оракул", 25), ("сигнал", 23), ("волна", 21), ("пуш", 19),
    ("гем", 18), ("крип", 16), ("аут", 15), ("бкб", 14), ("хард", 13),
]

SHOUT = [
    ("GG", 240), ("WP", 198), ("ХП", 176), ("ФРАГ", 158), ("ПУШ", 141),
    ("БАШНЯ", 127), ("РОСАТКА", 113), ("ЛЕС", 98), ("ДЖОНГЛ", 87),
    ("КРИПЫ", 76), ("РЕЛЮ", 68), ("РАШ", 61), ("ПАНК", 55), ("ПАРК", 49),
    ("ФАРМ", 44), ("ТЕМП", 40), ("РОТАЦИЯ", 36), ("ВАРД", 32), ("СМ", 29),
    ("ХЕРО", 26), ("БИЛД", 23), ("МАНЯ", 21), ("ПРО", 19), ("МЕТА", 17),
    ("ОРБ", 15), ("КОРЕ", 14), ("ИЛЛЮВИЯ", 13), ("ЛИА", 12), ("ДРАФТ", 11),
]

# Framed, mixed orientation, moderately dense. Only the palette differs.
LAYOUT = {
    "panel": True,
    "angles": [0] * 6 + [90, -90] * 2,
    "color_ramp": "palette",
    "max_font_size": 68,
    "relative_scaling": 0.58,
    "word_padding": 3,
    "bold_threshold": 0.45,
}

SCHEMES = [
    {
        "name": "A_rainbow_dark",
        "title": "ОБЛАКО СЛОВ ЧАТА",
        "subtitle": "РАМКА + СМЕШАННАЯ ОРИЕНТАЦИЯ  •  ПАЛИТРА A",
        "footer": "РАЗНОЦВЕТНЫЙ ТЕКСТ  •  КАЖДОЕ СЛОВО СВОЙ ЦВЕТ",
        "words": CHAT,
        "seed": 11,
        "force_shape": "diagonal",
        "force_base": (9, 12, 22),
        "force_accent": "#38bdf8",
        "note": "темный фон, диагональ",
    },
    {
        "name": "B_purple",
        "title": "ОБЛАКО СЛОВ ЧАТА",
        "subtitle": "РАМКА + СМЕШАННАЯ ОРИЕНТАЦИЯ  •  ПАЛИТРА B",
        "footer": "ФИОЛЕТОВОЕ СЕМЕЙСТВО  •  ГЛУБОКИЙ ФОН",
        "words": SHOUT,
        "seed": 23,
        "force_shape": "rays",
        "force_base": (20, 10, 32),
        "force_accent": "#a855f7",
        "note": "фиолетовая база, лучи",
    },
    {
        "name": "C_emerald",
        "title": "ОБЛАКО СЛОВ АНАЛИТИКИ",
        "subtitle": "РАМКА + СМЕШАННАЯ ОРИЕНТАЦИЯ  •  ПАЛИТРА C",
        "footer": "ХОЛОДНО-ЗЕЛЕНОЕ СЕМЕЙСТВО  •  СИНИЙ ФОН",
        "words": CHAT[:26],
        "seed": 37,
        "force_shape": "corner",
        "force_base": (5, 18, 30),
        "force_accent": "#22c55e",
        "note": "холодный сине-зелёный",
    },
]


def main() -> None:
    out_dir = PROJECT_ROOT / "charts" / "palette"
    out_dir.mkdir(parents=True, exist_ok=True)
    for scheme in SCHEMES:
        name = scheme["name"]
        words = scheme.pop("words")
        note = scheme.pop("note")
        scheme.pop("name")
        png = generate_hud_wordcloud(words, **LAYOUT, **scheme)
        target = out_dir / f"{name}.png"
        target.write_bytes(png)
        print(f"wrote {target.name} ({len(png)} bytes) - {note}")


if __name__ == "__main__":
    main()
