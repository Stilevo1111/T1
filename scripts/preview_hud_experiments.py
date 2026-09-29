"""Render five deliberately different HUD word cloud experiments into charts/.

Each variant changes the *layout*, not just the words, so they can be compared
as design options: density, focus, rotation, asymmetry and full-bleed.

Usage:
    python scripts/preview_hud_experiments.py
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from chat_wordcloud.hud import (  # noqa: E402
    FOOTER_TOP,
    HEADER_BOTTOM,
    PANEL_BOX,
    generate_hud_wordcloud,
)

CHAT = [
    ("мид", 214), ("легенда", 187), ("импакт", 163), ("фраг", 148), ("вин", 132),
    ("поук", 119), ("ульт", 104), ("крина", 97), ("тим", 91), ("танк", 88),
    ("кд", 81), ("башня", 76), ("респ", 69), ("дедлайн", 64), ("про", 61),
    ("рейтинг", 57), ("см", 52), ("кс", 49), ("драфт", 45), ("пик", 43),
    ("трейл", 39), ("фарм", 36), ("инициация", 34), ("ротация", 31), ("вард", 29),
    ("смка", 27), ("оракул", 25), ("сигнал", 23), ("волна", 21), ("пуш", 19),
    ("гем", 18), ("крип", 16), ("аут", 15), ("бкб", 14), ("хард", 13),
    ("лайн", 12), ("джонгл", 11), ("деф", 10), ("офенс", 9), ("натион", 8),
    ("снайп", 8), ("апек", 7), ("бит", 7), ("ультимейт", 6), ("кемп", 6),
    ("спас", 5), ("стак", 5), ("нб", 5), ("активити", 4), ("дебафф", 4),
]

ANALYTICS = [
    ("ПОБЕД", 168), ("ИМПАКТ", 151), ("РОЛЬ", 133), ("МАТЧЕЙ", 124),
    ("СРЕДНИЙ", 112), ("ПОРАЖЕНИЙ", 98), ("УДАР", 87), ("ПОДДЕРЖКА", 76),
    ("КОРЕ", 68), ("ХЕРО", 61), ("СЛОТ", 57), ("ПРЕМЬЕРА", 52), ("ЛИНИЯ", 48),
    ("ПУШ", 44), ("ОБОРОНА", 41), ("ТЕМП", 38), ("ПРО", 35), ("АНАЛИЗ", 33),
    ("ГЕЙМ", 31), ("ТАЙМИНГ", 29), ("ПЛЮС", 27), ("МИНУС", 25), ("КАРТА", 24),
    ("РЕФРЕШ", 22), ("КЕШ", 20), ("ГРАФИК", 19), ("ИНДЕКС", 18), ("РАНГ", 17),
    ("ЗРИТЕЛИ", 16), ("МАТЧ", 15), ("ТУРНИР", 14), ("РЕЙТИНГ", 13),
]

SHOUT = [
    ("GG", 240), ("WP", 198), ("ХП", 176), ("ФРАГ", 158), ("ПУШ", 141),
    ("БАШНЯ", 127), ("РОСАТКА", 113), ("ЛЕС", 98), ("ДЖОНГЛ", 87),
    ("КРИПЫ", 76), ("РЕЛЮ", 68), ("РАШ", 61), ("ПАНК", 55), ("ПАРК", 49),
    ("ФАРМ", 44), ("ТЕМП", 40), ("РОТАЦИЯ", 36), ("ВАРД", 32), ("СМ", 29),
    ("ХЕРО", 26), ("БИЛД", 23), ("МАНЯ", 21), ("ПРО", 19), ("МЕТА", 17),
]

NEUTRAL = [
    ("аналитика", 120), ("график", 104), ("матчи", 92), ("победы", 85),
    ("поражения", 78), ("герои", 71), ("роли", 65), ("рейтинги", 59),
    ("команды", 54), ("турниры", 49), ("сезон", 45), ("неделя", 41),
    ("форма", 38), ("динамика", 35), ("сравнение", 32), ("детали", 29),
    ("индекс", 27), ("позиции", 25), ("темп", 23), ("фарм", 21),
    ("тим", 19), ("драфт", 18), ("пик", 17), ("бан", 16), ("идея", 15),
]

# Variants differ in layout knobs, not only in words.
EXPERIMENTS = [
    {
        "name": "01_dense_heat",
        "words": CHAT,
        "note": "dense packing, small font, heat ramp",
        "kwargs": {
            "title": "ОБЛАКО СЛОВ ЧАТА",
            "subtitle": "ПЛОТНЫЙ ВАРИАНТ  •  50 СЛОВ  •  HEAT",
            "footer": "МАЛЕНЬКИЙ КЕГЛЬ  •  ПЛОТНАЯ УПАКОВКА  •  HEAT-РАМПА",
            "seed": 11,
            "max_font_size": 46,
            "relative_scaling": 0.72,
            "word_padding": 1,
            "color_ramp": "heat",
            "bold_threshold": 0.9,
            "force_accent": "#ef4444",
            "force_shape": "diagonal",
        },
    },
    {
        "name": "02_focus_mono",
        "words": ANALYTICS[:10],
        "note": "focus on big words, mono ramp, horizontal only",
        "kwargs": {
            "title": "ОБЛАКО СЛОВ АНАЛИТИКИ",
            "subtitle": "ФОКУС  •  10 СЛОВ  •  МОНОТОН",
            "footer": "КРУПНЫЙ КЕГЛЬ  •  ШИРОКИЕ ОТСТУПЫ  •  МОНО-РАМПА",
            "seed": 4,
            "max_font_size": 96,
            "relative_scaling": 0.62,
            "word_padding": 9,
            "color_ramp": "monotone",
            "bold_threshold": 0.3,
            "angles": [0],
            "force_accent": "#38bdf8",
            "force_shape": "orb",
        },
    },
    {
        "name": "03_rotated_wall",
        "words": SHOUT,
        "note": "many vertical words, wall of rotated labels",
        "kwargs": {
            "title": "СТЕНА СЛОВ",
            "subtitle": "ПОВОРОТ  •  30% ВЕРТИКАЛЬНЫХ  •  СЖАТЫЙ КЕГЛЬ",
            "footer": "СМЕШАННАЯ ОРИЕНТАЦИЯ  •  ПЛОТНАЯ СЕТКА",
            "seed": 19,
            "max_font_size": 62,
            "relative_scaling": 0.55,
            "word_padding": 2,
            "color_ramp": "accent",
            "bold_threshold": 0.5,
            "angles": [0] * 7 + [90, -90] * 3,
            "force_accent": "#facc15",
            "force_shape": "rays",
        },
    },
    {
        "name": "04_asymmetric_column",
        "words": NEUTRAL,
        "note": "words in left column only, asymmetric instead of centered",
        "kwargs": {
            "title": "КОЛОНКА СЛОВ",
            "subtitle": "АСИММЕТРИЯ  •  ЛЕВАЯ КОЛОНКА  •  INVERSE-РАМПА",
            "footer": "ВЫРАЖЕННАЯ КОЛОНКА  •  ПУСТОЕ ПРАВОЕ ПОЛЕ",
            "seed": 8,
            "max_font_size": 64,
            "relative_scaling": 0.5,
            "word_area": (PANEL_BOX[0] + 26, HEADER_BOTTOM, PANEL_BOX[0] + 566, FOOTER_TOP),
            "word_padding": 3,
            "color_ramp": "inverse",
            "bold_threshold": 0.4,
            "force_accent": "#a855f7",
            "force_shape": "corner",
        },
    },
    {
        "name": "05_fullbleed",
        "words": CHAT[:26],
        "note": "no panel, words full-bleed over backdrop shape",
        "kwargs": {
            "title": "ПОЛНОЕ ПОЛЕ",
            "subtitle": "БЕЗ ПАНЕЛИ  •  FULL-BLEED  •  HEAT",
            "footer": "СЛОВА ПОВЕРХ ФОНА  •  БЕЗ РАМКИ",
            "seed": 33,
            "max_font_size": 88,
            "relative_scaling": 0.45,
            "word_area": (46, 120, PANEL_BOX[2] - 46, 620),
            "word_padding": 6,
            "color_ramp": "heat",
            "bold_threshold": 0.6,
            "panel": False,
            "force_accent": "#f43f5e",
            "force_shape": "diagonal",
        },
    },
]


def main() -> None:
    out_dir = PROJECT_ROOT / "charts" / "experiments"
    out_dir.mkdir(parents=True, exist_ok=True)
    for experiment in EXPERIMENTS:
        png = generate_hud_wordcloud(experiment["words"], **experiment["kwargs"])
        target = out_dir / f"{experiment['name']}.png"
        target.write_bytes(png)
        print(f"wrote {target.relative_to(PROJECT_ROOT)} ({len(png)} bytes) - {experiment['note']}")


if __name__ == "__main__":
    main()
