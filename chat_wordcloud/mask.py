"""WordCloud mask creation for Dota 2 logo."""
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from chat_wordcloud.config import WORDCLOUD_HEIGHT, WORDCLOUD_MASK_PATH, WORDCLOUD_WIDTH


def _load_mask_image(path: Path) -> Image.Image:
    img = Image.open(path)
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    return img


def _alpha_to_binary_mask(img: Image.Image, threshold: int = 80) -> np.ndarray:
    alpha = np.array(img.split()[-1])
    gray = np.array(img.convert("L"))
    mask = np.where((alpha > threshold) | (gray > threshold), 255, 0).astype(np.uint8)
    return mask


def _dilate_mask(mask: np.ndarray, iterations: int = 2) -> np.ndarray:
    from scipy.ndimage import binary_dilation

    structure = np.ones((3, 3), dtype=bool)
    dilated = binary_dilation(mask > 0, structure=structure, iterations=iterations)
    return (dilated * 255).astype(np.uint8)


def _create_fallback_dota_mask(width: int, height: int) -> np.ndarray:
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    cx, cy = width // 2, height // 2
    r = int(min(width, height) * 0.42)

    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(255, 255, 255, 255))

    cut_r = int(r * 0.72)
    draw.ellipse([cx - cut_r, cy - cut_r, cx + cut_r, cy + cut_r], fill=(0, 0, 0, 0))

    slash_w = max(width * 0.08, 12)
    draw.polygon(
        [
            (cx - slash_w, cy - r - 4),
            (cx + slash_w, cy - r - 4),
            (cx + slash_w, cy + r + 4),
            (cx - slash_w, cy + r + 4),
        ],
        fill=(0, 0, 0, 0),
    )

    alpha = np.array(img.split()[-1])
    return np.where(alpha > 80, 255, 0).astype(np.uint8)


def create_dota_mask() -> np.ndarray | None:
    path = WORDCLOUD_MASK_PATH
    if path is None:
        return _create_fallback_dota_mask(WORDCLOUD_WIDTH, WORDCLOUD_HEIGHT)
    path = Path(path)
    if path.exists():
        img = _load_mask_image(path)
        mask = _alpha_to_binary_mask(img)
        mask = _dilate_mask(mask, iterations=1)
        return mask
    return _create_fallback_dota_mask(WORDCLOUD_WIDTH, WORDCLOUD_HEIGHT)
