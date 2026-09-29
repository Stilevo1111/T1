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


@pytest.mark.parametrize("ramp", ["accent", "heat", "monotone", "inverse", "palette"])
def test_every_color_ramp_renders(ramp):
    """All ramps must produce a non-blank card."""
    png = generate_hud_wordcloud(SAMPLE, seed=2, color_ramp=ramp)
    assert len(png) > 10000
    Image.open(io.BytesIO(png)).size == (HUD_WIDTH, HUD_HEIGHT)


def test_palette_ramp_cycles_through_distinct_accents():
    """palette must give neighbouring words different colours, not one flat hue."""
    accent = _hex_to_rgb("#ff8c42")
    secondary = _hex_to_rgb("#22d3ee")
    colors = [
        _word_color(0.5, accent, secondary, ramp="palette", index=i) for i in range(len(ACCENTS))
    ]
    assert len(set(colors)) == len(ACCENTS), "palette ramp repeated a colour"
    # Frequency still drives brightness, so size and colour agree.
    bright = _word_color(1.0, accent, secondary, ramp="palette", index=0)
    dim = _word_color(0.0, accent, secondary, ramp="palette", index=0)
    assert sum(bright) > sum(dim)


def test_palette_ramp_wraps_around_the_accent_list():
    """Indices past the palette length must wrap instead of raising."""
    accent = _hex_to_rgb("#ff8c42")
    secondary = _hex_to_rgb("#22d3ee")
    assert _word_color(
        0.5, accent, secondary, ramp="palette", index=len(ACCENTS)
    ) == _word_color(0.5, accent, secondary, ramp="palette", index=0)


def test_inverse_ramp_flips_brightness():
    """inverse must put the accent on rare words and muted on frequent ones."""
    accent = _hex_to_rgb("#ff8c42")
    secondary = _hex_to_rgb("#22d3ee")
    muted = _hex_to_rgb("#94a3b8")
    assert _word_color(0.0, accent, secondary, ramp="inverse") == accent
    assert _word_color(1.0, accent, secondary, ramp="inverse") == muted
    # ...whereas the default ramp is the other way around.
    assert _word_color(1.0, accent, secondary, ramp="accent") == accent
    assert _word_color(0.0, accent, secondary, ramp="accent") == muted


def test_heat_ramp_is_monotonic_in_warmth():
    """heat must go from a cool colour to a hot one as frequency rises."""
    accent = _hex_to_rgb("#ff8c42")
    secondary = _hex_to_rgb("#22d3ee")
    cool = _word_color(0.0, accent, secondary, ramp="heat")
    hot = _word_color(1.0, accent, secondary, ramp="heat")
    assert hot[0] > cool[0], "hot end must be redder"
    assert hot[2] < cool[2], "hot end must be less blue"


def test_word_area_confines_words_to_the_given_box():
    """A narrow word_area must push text away from the right-hand side."""
    base = {
        "seed": 2,
        "panel": False,
        "force_base": (9, 12, 22),
        "force_shape": "diagonal",
    }
    narrow = np.array(
        Image.open(
            io.BytesIO(
                generate_hud_wordcloud(SAMPLE, word_area=(76, HEADER_BOTTOM, 560, FOOTER_TOP), **base)
            )
        ).convert("RGB")
    )
    wide = np.array(
        Image.open(io.BytesIO(generate_hud_wordcloud(SAMPLE, **base))).convert("RGB")
    )

    def right_ink(arr):
        return (arr[:, 600:].sum(axis=2) > 300).sum()

    # The relative check is the meaningful one: the backdrop shape is bright on
    # both cards, so only a *difference* proves the words actually moved.
    assert right_ink(narrow) < right_ink(wide), "narrow word_area still painted the right side"
    changed = (narrow[:, 600:] != wide[:, 600:]).any(axis=2).sum()
    assert changed > 200, f"word_area had no effect on the right side ({changed} px)"


def test_panel_can_be_disabled():
    """panel=False must leave the card without the rounded frame."""
    with_panel = np.array(
        Image.open(io.BytesIO(generate_hud_wordcloud(SAMPLE, seed=2, panel=True))).convert("RGB")
    )
    without = np.array(
        Image.open(io.BytesIO(generate_hud_wordcloud(SAMPLE, seed=2, panel=False))).convert("RGB")
    )
    assert not np.array_equal(with_panel, without), "panel toggle had no effect"


def test_angles_restriction_changes_layout():
    """Restricting angles to horizontal must change the rendered result."""
    mixed = generate_hud_wordcloud(SAMPLE, seed=9, angles=[0, 90, -90])
    horizontal = generate_hud_wordcloud(SAMPLE, seed=9, angles=[0])
    assert mixed != horizontal


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
