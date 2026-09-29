"""Tests for the HUD-styled word cloud (analytics chart design)."""
import io
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from chat_wordcloud.hud import (  # noqa: E402
    ACCENTS,
    BG_BASES,
    FOOTER_TOP,
    HEADER_BOTTOM,
    HUD_HEIGHT,
    HUD_WIDTH,
    PANEL_BOX,
    _hex_to_rgb,
    _word_color,
    generate_hud_wordcloud,
)

SAMPLE = [
    ("мид", 100),
    ("легенда", 80),
    ("импакт", 60),
    ("фраг", 45),
    ("поук", 30),
    ("ульт", 20),
    ("крина", 12),
    ("тим", 6),
]


def test_hud_wordcloud_uses_chart_canvas_size():
    """The card must match the analytics chart canvas (1200x800)."""
    png = generate_hud_wordcloud(SAMPLE, seed=1)
    assert Image.open(io.BytesIO(png)).size == (HUD_WIDTH, HUD_HEIGHT) == (1200, 800)


def test_hud_wordcloud_is_not_blank():
    """Words must actually render into the word area."""
    png = generate_hud_wordcloud(SAMPLE, seed=1)
    assert len(png) > 10000, f"Image too small ({len(png)} bytes), likely blank"

    arr = np.array(Image.open(io.BytesIO(png)).convert("RGB"))
    area = arr[HEADER_BOTTOM:FOOTER_TOP, PANEL_BOX[0] : PANEL_BOX[2]]
    bright = (area.sum(axis=2) > 300).sum()
    assert bright > 2000, f"word area looks empty ({bright} bright pixels)"


def test_hud_wordcloud_seed_is_reproducible():
    """Same seed must give byte-identical output, different seeds must not."""
    a = generate_hud_wordcloud(SAMPLE, seed=5)
    b = generate_hud_wordcloud(SAMPLE, seed=5)
    c = generate_hud_wordcloud(SAMPLE, seed=6)
    assert a == b, "same seed should reproduce the same card"
    assert a != c, "different seeds should pick different palettes"


def test_hud_palette_matches_analytics_chart():
    """Accents/bases must stay in sync with weekly_analytics chart colours."""
    import weekly_analytics

    source = Path(weekly_analytics.__file__).read_text(encoding="utf-8")
    for accent in ACCENTS:
        assert accent in source, f"{accent} is not used by the analytics chart"
    for base in BG_BASES:
        literal = f"({base[0]}, {base[1]}, {base[2]})"
        assert literal in source, f"{literal} is not used by the analytics chart"


def test_hud_word_ramp_goes_from_muted_to_accent():
    """Rare words must be muted and the most frequent word must wear the accent."""
    accent = _hex_to_rgb("#ff8c42")
    secondary = _hex_to_rgb("#22d3ee")
    muted = _hex_to_rgb("#94a3b8")

    hottest = _word_color(1.0, accent, secondary)
    coldest = _word_color(0.0, accent, secondary)

    assert hottest == accent, "most frequent word should use the accent colour"
    assert coldest == muted, "rarest word should use the muted colour"


def test_hud_words_stay_inside_the_panel():
    """No word may bleed over the panel frame or into the header/footer."""
    arr = np.array(
        Image.open(io.BytesIO(generate_hud_wordcloud(SAMPLE, seed=3))).convert("RGB")
    )
    panel_fill = np.array([8, 10, 20])
    # Header/footer bands are chrome-only: they must stay uniform panel fill.
    for row in (HEADER_BOTTOM - 4, FOOTER_TOP + 2):
        band = arr[row, PANEL_BOX[0] + 10 : PANEL_BOX[2] - 10]
        assert np.all(np.abs(band.astype(int) - panel_fill).sum(axis=1) < 40), (
            f"word pixels leaked into chrome band at row {row}"
        )


def test_hud_wordcloud_rejects_empty_input():
    with pytest.raises(ValueError):
        generate_hud_wordcloud([])


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
