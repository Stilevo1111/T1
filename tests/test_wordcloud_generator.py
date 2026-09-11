"""Tests for the chat wordcloud generator."""
import io
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from PIL import Image

from chat_wordcloud.config import WORDCLOUD_MIN_FONT_SIZE, WORDCLOUD_BACKGROUND_COLOR
from chat_wordcloud.generator import _resolve_font_path, _dilate_alpha_mask


def test_font_resolution_finds_loadable_font():
    """Font resolution should find a font that can render Cyrillic text."""
    font_path = _resolve_font_path()
    assert font_path is not None, "No loadable font found for wordcloud generation"
    assert Path(font_path).exists(), f"Font path does not exist: {font_path}"


def test_wordcloud_generates_nonblank_image():
    """generate_wordcloud_image should place words and produce a non-blank image."""
    from chat_wordcloud.generator import generate_wordcloud_image

    test_words = [
        ("фиссура", 150),
        ("игрок", 120),
        ("дота", 100),
        ("матч", 90),
        ("герой", 80),
        ("фарм", 70),
        ("игра", 60),
        ("ранг", 50),
        ("ммр", 45),
        ("стим", 40),
    ]

    img_bytes = generate_wordcloud_image(test_words)
    assert len(img_bytes) > 10000, f"Image too small ({len(img_bytes)} bytes), likely blank"

    img = Image.open(io.BytesIO(img_bytes))
    assert img.size == (1024, 1024)


def test_wordcloud_handles_single_word():
    """Single word should still produce a non-blank image."""
    from chat_wordcloud.generator import generate_wordcloud_image

    img_bytes = generate_wordcloud_image([("фиссура", 100)])
    assert len(img_bytes) > 10000, f"Image too small ({len(img_bytes)} bytes)"


def test_wordcloud_raises_on_no_words():
    """Empty word list should raise ValueError."""
    from chat_wordcloud.generator import generate_wordcloud_image
    import pytest

    with pytest.raises(ValueError):
        generate_wordcloud_image([])


def test_dilate_alpha_mask_expands_correctly():
    """Dilation should expand a single pixel into a (2*padding+1)^2 block."""
    import numpy as np

    alpha = np.zeros((10, 10), dtype=bool)
    alpha[5, 5] = True

    dilated = _dilate_alpha_mask(alpha, 2)
    assert np.sum(dilated) == 25  # 5x5 block

    dilated0 = _dilate_alpha_mask(alpha, 0)
    assert np.sum(dilated0) == 1  # unchanged


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-q"]))
