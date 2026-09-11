"""WordCloud image generation - OpenDota style with proper spiral placement."""
import io
import json
import logging
import math
import os
import random
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from chat_wordcloud.config import (
    WORDCLOUD_BACKGROUND_COLOR,
    WORDCLOUD_COLORS,
    WORDCLOUD_DEBUG,
    WORDCLOUD_FONT_PATH,
    WORDCLOUD_HEIGHT,
    WORDCLOUD_MAX_FONT_SIZE,
    WORDCLOUD_MAX_WORDS,
    WORDCLOUD_MIN_FONT_SIZE,
    WORDCLOUD_RANDOM_STATE,
    WORDCLOUD_SAFE_MARGIN,
    WORDCLOUD_WIDTH,
    WORDCLOUD_WORD_PADDING,
)
from chat_wordcloud.processor import scale_frequencies

logger = logging.getLogger(__name__)

# 90% horizontal, 10% vertical - clean readable layout
WORDCLOUD_ANGLES = [0] * 9 + [90, -90]

# Small padding around text before rotation
WORDCLOUD_GAP = 4

# Maximum placement attempts per word
MAX_PLACEMENT_ATTEMPTS = 8000


def _resolve_font_path() -> str | None:
    env_font = os.environ.get("WORDCLOUD_FONT_PATH", "")
    candidates = [
        Path(env_font) if env_font else None,
        WORDCLOUD_FONT_PATH,
        Path("C:/Windows/Fonts/NotoSans-Regular.ttf"),
        Path("C:/Windows/Fonts/DejaVuSans.ttf"),
        Path("/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf"),
        Path("/usr/share/fonts/TTF/NotoSans-Regular.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    ]
    for p in candidates:
        if p is not None and p.exists():
            try:
                test_font = ImageFont.truetype(str(p), WORDCLOUD_MIN_FONT_SIZE)
                test_bbox = test_font.getbbox("фиссура")
                if test_bbox[2] - test_bbox[0] > 0 and test_bbox[3] - test_bbox[1] > 0:
                    logger.info(f"WordCloud font resolved: {p}")
                    return str(p)
                else:
                    logger.warning(
                        f"WordCloud font {p} loads but cannot render Cyrillic "
                        f"(bbox={test_bbox})"
                    )
            except Exception as e:
                logger.warning(f"WordCloud font candidate {p} failed to load: {e}")
    logger.error("WordCloud font resolution: no loadable font found")
    return None


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    hex_color = hex_color.lstrip("#")
    return tuple(int(hex_color[i : i + 2], 16) for i in (0, 2, 4))


def _get_dota_color(rng):
    """Get a random Dota-style color as a tuple for PIL.
    65% light (white/gray), 35% muted red/burgundy.
    """
    rgb_colors = [_hex_to_rgb(c) for c in WORDCLOUD_COLORS]
    lights = rgb_colors[:3]
    reds = rgb_colors[3:]
    if rng.random() < 0.65:
        return rng.choice(lights)
    else:
        return rng.choice(reds)


def _get_word_bbox(word, font):
    """Get the bounding box of a word with given font."""
    bbox = font.getbbox(word)
    width = bbox[2] - bbox[0]
    height = bbox[3] - bbox[1]
    return width, height


def _dilate_alpha_mask(alpha: np.ndarray, padding: int) -> np.ndarray:
    """Dilate a boolean alpha mask by `padding` pixels for collision detection.

    The padding expands the collision area around text without affecting
    the visual image (text is rendered with transparent gaps).
    """
    if padding <= 0:
        return alpha

    from scipy.ndimage import binary_dilation

    kernel = np.ones((2 * padding + 1, 2 * padding + 1), dtype=bool)
    return binary_dilation(alpha, structure=kernel)


def _render_rotated_word(word, font, color, angle):
    """Render a word to a rotated RGBA image.
    Returns (rotated_img, width, height) or (None, 0, 0) on failure.
    The returned width/height are the ACTUAL dimensions of the rotated image.
    """
    tmp = Image.new("RGBA", (1, 1), (0, 0, 0, 0))
    tmp_draw = ImageDraw.Draw(tmp)
    bbox = tmp_draw.textbbox((0, 0), word, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]

    if tw <= 0 or th <= 0:
        return None, 0, 0

    pad = WORDCLOUD_GAP + WORDCLOUD_WORD_PADDING
    text_img = Image.new("RGBA", (tw + pad * 2, th + pad * 2), (0, 0, 0, 0))
    text_draw = ImageDraw.Draw(text_img)
    text_draw.text((pad - bbox[0], pad - bbox[1]), word, font=font, fill=color)

    rotated = text_img.rotate(
        angle, resample=Image.Resampling.BICUBIC, expand=True
    )
    return rotated, rotated.width, rotated.height


def _rects_overlap(r1, r2):
    """Check if two rectangles overlap. Each rect is (x, y, width, height)."""
    x1, y1, w1, h1 = r1
    x2, y2, w2, h2 = r2

    if x1 + w1 <= x2 or x2 + w2 <= x1:
        return False
    if y1 + h1 <= y2 or y2 + h2 <= y1:
        return False

    return True


def _find_spiral_position(
    canvas_width,
    canvas_height,
    word_width,
    word_height,
    occupied_mask,
    word_alpha,
    center_x,
    center_y,
    rng,
):
    """Find a position for a word using spiral search from center.
    Uses actual rotated dimensions and alpha mask collision detection.
    """
    max_radius = math.sqrt(canvas_width**2 + canvas_height**2) / 2
    safe_margin = WORDCLOUD_SAFE_MARGIN

    angle_step = 0.5
    radius_step = 12
    current_radius = 0
    current_angle = rng.random() * 2 * math.pi

    for _ in range(MAX_PLACEMENT_ATTEMPTS):
        x = int(center_x + current_radius * math.cos(current_angle) - word_width / 2)
        y = int(center_y + current_radius * math.sin(current_angle) - word_height / 2)

        # Strict canvas bounds check with safe margin
        if (
            x < safe_margin
            or y < safe_margin
            or x + word_width > canvas_width - safe_margin
            or y + word_height > canvas_height - safe_margin
        ):
            current_angle += angle_step
            current_radius += radius_step / (2 * math.pi)
            if current_radius > max_radius:
                return None
            continue

        # Alpha mask collision check against occupied pixels
        if word_alpha is not None and occupied_mask is not None:
            region = occupied_mask[y : y + word_height, x : x + word_width]
            if np.any(region[word_alpha]):
                current_angle += angle_step
                current_radius += radius_step / (2 * math.pi)
                if current_radius > max_radius:
                    return None
                continue

        return x, y

    return None


def generate_wordcloud_image(top_words: list[tuple[str, int]]) -> bytes:
    if not top_words:
        raise ValueError("No words provided for wordcloud")

    logger.info(f"generate_wordcloud_image: generating with {len(top_words)} words")

    font_path = _resolve_font_path()
    if not font_path:
        raise FileNotFoundError(
            f"WordCloud font with Cyrillic support not found. Tried: {WORDCLOUD_FONT_PATH}"
        )

    logger.debug(f"Using font: {font_path}")

    # Scale frequencies for font size (sqrt scaling)
    frequencies = scale_frequencies(top_words)
    max_freq = max(frequencies.values()) if frequencies else 1

    # Sort by frequency - most important words first
    sorted_words = sorted(top_words, key=lambda x: frequencies.get(x[0], 0), reverse=True)

    # Create canvas
    canvas_width = WORDCLOUD_WIDTH
    canvas_height = WORDCLOUD_HEIGHT
    base_img = Image.new("RGBA", (canvas_width, canvas_height), WORDCLOUD_BACKGROUND_COLOR)

    # Random generator for placement
    rng = random.Random(WORDCLOUD_RANDOM_STATE)

    # Center of canvas
    center_x = canvas_width // 2
    center_y = canvas_height // 2

    # Occupied mask for alpha-collision detection
    occupied_mask = np.zeros((canvas_height, canvas_width), dtype=bool)

    # Track placed words for debug
    debug_positions = []
    placed_count = 0
    placed_word_set = set()
    placement_failures = []

    def try_place(word, count, current_font_size):
        nonlocal placed_count
        try:
            current_font = ImageFont.truetype(font_path, current_font_size)
        except Exception:
            return False

        angle = rng.choice(WORDCLOUD_ANGLES)
        color = _get_dota_color(rng)

        # Pre-render rotated word to get ACTUAL dimensions and alpha mask
        rotated, rw, rh = _render_rotated_word(word, current_font, color, angle)
        if rotated is None:
            return False

        # Extract alpha mask for collision detection (only text pixels)
        word_alpha = np.array(rotated.split()[-1], dtype=bool)

        # Dilate alpha mask by WORD_PADDING for collision detection.
        # This creates a buffer zone between words without adding visible padding.
        collision_alpha = _dilate_alpha_mask(word_alpha, WORDCLOUD_WORD_PADDING)

        # Use ACTUAL rotated dimensions for placement search
        pos = _find_spiral_position(
            canvas_width,
            canvas_height,
            rw,
            rh,
            occupied_mask,
            collision_alpha,
            center_x,
            center_y,
            rng,
        )

        if pos:
            x, y = pos
            base_img.paste(rotated, (x, y), rotated)

            # Update occupied mask with placed word's collision alpha (dilated) for consistent collision detection
            occupied_mask[y : y + rh, x : x + rw][collision_alpha] = True

            placed_count += 1
            placed_word_set.add(word)

            if WORDCLOUD_DEBUG:
                debug_positions.append(
                    {
                        "word": word,
                        "frequency": count,
                        "font_size": current_font_size,
                        "x": x,
                        "y": y,
                        "rotation": angle,
                        "width": rw,
                        "height": rh,
                    }
                )

            return True
        return False

    # First pass: place words in frequency order
    for idx, (word, count) in enumerate(sorted_words[: WORDCLOUD_MAX_WORDS]):
        if not word or len(word) < 2:
            continue

        freq = frequencies.get(word, 1)
        font_size = int(
            WORDCLOUD_MIN_FONT_SIZE
            + (WORDCLOUD_MAX_FONT_SIZE - WORDCLOUD_MIN_FONT_SIZE)
            * (freq / max_freq) ** 0.5
        )
        font_size = max(WORDCLOUD_MIN_FONT_SIZE, min(WORDCLOUD_MAX_FONT_SIZE, font_size))

        try:
            ImageFont.truetype(font_path, font_size)
        except Exception as e:
            logger.debug(f"Could not load font size {font_size}: {e}")
            continue

        placed = False
        min_font_tried = False
        for size_reduction in range(100):
            current_font_size = font_size - size_reduction
            if current_font_size < WORDCLOUD_MIN_FONT_SIZE:
                current_font_size = WORDCLOUD_MIN_FONT_SIZE
                min_font_tried = True

            if try_place(word, count, current_font_size):
                placed = True
                break

            if min_font_tried and current_font_size == WORDCLOUD_MIN_FONT_SIZE:
                break

        if not placed:
            logger.debug(f"Could not place word '{word}' after trying smaller sizes")
            placement_failures.append(word)

    # Second pass: try to fill empty spaces with remaining small words
    small_words = [
        (w, c)
        for w, c in sorted_words[: WORDCLOUD_MAX_WORDS]
        if w and len(w) >= 2 and w not in placed_word_set
    ]
    small_words.sort(key=lambda x: x[1])

    for word, count in small_words:
        try:
            small_font = ImageFont.truetype(font_path, WORDCLOUD_MIN_FONT_SIZE)
        except Exception:
            continue

        color = _get_dota_color(rng)
        angle = rng.choice(WORDCLOUD_ANGLES)

        rotated, rw, rh = _render_rotated_word(word, small_font, color, angle)
        if rotated is None:
            continue

        word_alpha = np.array(rotated.split()[-1], dtype=bool)
        collision_alpha = _dilate_alpha_mask(word_alpha, WORDCLOUD_WORD_PADDING)

        pos = _find_spiral_position(
            canvas_width,
            canvas_height,
            rw,
            rh,
            occupied_mask,
            collision_alpha,
            center_x,
            center_y,
            rng,
        )

        if pos:
            x, y = pos
            base_img.paste(rotated, (x, y), rotated)
            occupied_mask[y : y + rh, x : x + rw][collision_alpha] = True
            placed_count += 1

            if WORDCLOUD_DEBUG:
                debug_positions.append(
                    {
                        "word": word,
                        "frequency": count,
                        "font_size": WORDCLOUD_MIN_FONT_SIZE,
                        "x": x,
                        "y": y,
                        "rotation": angle,
                        "width": rw,
                        "height": rh,
                    }
                )

    logger.info(f"Successfully placed {placed_count}/{len(sorted_words[:WORDCLOUD_MAX_WORDS])} words")

    if placed_count == 0:
        logger.error(
            f"WordCloud placed 0 words! Failures for first 20: {placement_failures[:20]}"
        )

    # Verify no words are clipped or out of bounds
    issues = []
    if WORDCLOUD_DEBUG:
        safe_margin = WORDCLOUD_SAFE_MARGIN
        for dp in debug_positions:
            x, y, w, h = dp["x"], dp["y"], dp["width"], dp["height"]
            if x < safe_margin or y < safe_margin:
                issues.append(f"{dp['word']}: out of safe margin at ({x}, {y})")
            if x + w > canvas_width - safe_margin or y + h > canvas_height - safe_margin:
                issues.append(f"{dp['word']}: exceeds canvas bounds at ({x}, {y}, {w}, {h})")

        # Check for non-opaque alpha pixels outside safe margin
        alpha = np.array(base_img.split()[-1])
        if np.any(alpha[:safe_margin, :] != 255) or np.any(alpha[-safe_margin:, :] != 255):
            issues.append("Alpha pixels found in top/bottom margin")
        if np.any(alpha[:, :safe_margin] != 255) or np.any(alpha[:, -safe_margin:] != 255):
            issues.append("Alpha pixels found in left/right margin")

        if issues:
            logger.warning(f"WordCloud verification issues: {issues}")
        else:
            logger.info("WordCloud verification passed: no clipping or boundary violations")

        # Save debug files
        try:
            debug_dir = Path("debug_output")
            debug_dir.mkdir(exist_ok=True)

            base_img.save(debug_dir / "debug_wordcloud.png")

            with open(debug_dir / "debug_word_positions.json", "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "canvas_size": (canvas_width, canvas_height),
                        "safe_margin": safe_margin,
                        "placed_count": len(debug_positions),
                        "words": debug_positions,
                        "issues": issues,
                    },
                    f,
                    ensure_ascii=False,
                    indent=2,
                )
            logger.info(f"Debug files saved to {debug_dir}")
        except Exception as e:
            logger.warning(f"Could not save debug files: {e}")

    # Save image
    buf = io.BytesIO()
    base_img.save(buf, format="PNG", optimize=True)
    buf.seek(0)
    result_bytes = buf.getvalue()
    logger.info(f"WordCloud image generated: {len(result_bytes)} bytes, size={base_img.size}")
    return result_bytes


def test_wordcloud_placement():
    """Test that artificial words of various sizes place without clipping."""
    font_path = _resolve_font_path()
    if not font_path:
        logger.warning("Font not found, skipping placement test")
        return

    test_words = [
        ("ОЧЕНЬБОЛЬШОЕСЛОВО", 100),
        ("БОЛЬШОЕ", 80),
        ("СРЕДНЕЕ", 50),
        ("маленькое", 30),
        ("оченьмаленькое", 20),
    ]

    frequencies = {w: c for w, c in test_words}
    max_freq = max(frequencies.values())

    sorted_words = sorted(test_words, key=lambda x: frequencies.get(x[0], 0), reverse=True)

    canvas_width = WORDCLOUD_WIDTH
    canvas_height = WORDCLOUD_HEIGHT
    base_img = Image.new("RGBA", (canvas_width, canvas_height), WORDCLOUD_BACKGROUND_COLOR)
    rng = random.Random(WORDCLOUD_RANDOM_STATE)
    center_x = canvas_width // 2
    center_y = canvas_height // 2
    occupied_mask = np.zeros((canvas_height, canvas_width), dtype=bool)

    for word, count in sorted_words:
        freq = frequencies.get(word, 1)
        font_size = int(
            WORDCLOUD_MIN_FONT_SIZE
            + (WORDCLOUD_MAX_FONT_SIZE - WORDCLOUD_MIN_FONT_SIZE)
            * (freq / max_freq) ** 0.5
        )
        font_size = max(WORDCLOUD_MIN_FONT_SIZE, min(WORDCLOUD_MAX_FONT_SIZE, font_size))

        # Try size reduction for each word (like generate_wordcloud_image)
        word_placed = False
        min_font_tried = False
        for size_reduction in range(100):
            current_font_size = font_size - size_reduction
            if current_font_size < WORDCLOUD_MIN_FONT_SIZE:
                current_font_size = WORDCLOUD_MIN_FONT_SIZE
                min_font_tried = True

            try:
                font = ImageFont.truetype(font_path, current_font_size)
            except Exception:
                continue

            color = (255, 255, 255)
            angle = rng.choice(WORDCLOUD_ANGLES)

            rotated, rw, rh = _render_rotated_word(word, font, color, angle)
            if rotated is None:
                continue

            word_alpha = np.array(rotated.split()[-1], dtype=bool)
            collision_alpha = _dilate_alpha_mask(word_alpha, WORDCLOUD_WORD_PADDING)

            pos = _find_spiral_position(
                canvas_width,
                canvas_height,
                rw,
                rh,
                occupied_mask,
                collision_alpha,
                center_x,
                center_y,
                rng,
            )

            if pos:
                x, y = pos
                base_img.paste(rotated, (x, y), rotated)
                occupied_mask[y : y + rh, x : x + rw][collision_alpha] = True
                print(f"Placed '{word}' at ({x}, {y}) size {rw}x{rh} angle {angle}")
                word_placed = True
                break

            if min_font_tried and current_font_size == WORDCLOUD_MIN_FONT_SIZE:
                break

        if not word_placed:
            print(f"Could not place '{word}' at any size")

    # Verify no clipping
    safe_margin = WORDCLOUD_SAFE_MARGIN
    alpha = np.array(base_img.split()[-1])
    issues = []

    for y in range(safe_margin):
        if np.any(alpha[y, :] != 255):
            issues.append("Alpha in top margin")
            break
    for y in range(canvas_height - safe_margin, canvas_height):
        if np.any(alpha[y, :] != 255):
            issues.append("Alpha in bottom margin")
            break
    for x in range(safe_margin):
        if np.any(alpha[:, x] != 255):
            issues.append("Alpha in left margin")
            break
    for x in range(canvas_width - safe_margin, canvas_width):
        if np.any(alpha[:, x] != 255):
            issues.append("Alpha in right margin")
            break

    if issues:
        print(f"TEST FAILED: {issues}")
    else:
        print("TEST PASSED: No clipping detected")

    # Save test image
    debug_dir = Path("debug_output")
    debug_dir.mkdir(exist_ok=True)
    base_img.save(debug_dir / "test_wordcloud_placement.png")
    print(f"Test image saved to {debug_dir / 'test_wordcloud_placement.png'}")
