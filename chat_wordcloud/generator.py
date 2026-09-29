"""WordCloud image generation - OpenDota style with proper spiral placement."""
import io
import json
import logging
import math
import os
import random
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont
from scipy.ndimage import binary_dilation

from chat_wordcloud.config import (
    WORDCLOUD_ACCENT_COLOR,
    WORDCLOUD_ACCENT_SOFT,
    WORDCLOUD_BACKGROUND_COLOR,
    WORDCLOUD_BOTTOM_RESERVE,
    WORDCLOUD_COLORS,
    WORDCLOUD_DEBUG,
    WORDCLOUD_FONT_PATH,
    WORDCLOUD_HEAT_RAMP,
    WORDCLOUD_HEIGHT,
    WORDCLOUD_MAX_FONT_SIZE,
    WORDCLOUD_MAX_WORDS,
    WORDCLOUD_MIN_FONT_SIZE,
    WORDCLOUD_PANEL_COLOR,
    WORDCLOUD_RANDOM_STATE,
    WORDCLOUD_RELATIVE_SCALING,
    WORDCLOUD_SAFE_MARGIN,
    WORDCLOUD_TEXT_COLOR,
    WORDCLOUD_TEXT_MUTED,
    WORDCLOUD_TOP_RESERVE,
    WORDCLOUD_TOXIC_COLORS,
    WORDCLOUD_WIDTH,
    WORDCLOUD_WORD_PADDING,
    WORDCLOUD_WORKER_NICE,
)

logger = logging.getLogger(__name__)

# 90% horizontal, 10% vertical - clean readable layout
WORDCLOUD_ANGLES = [0] * 9 + [90, -90]

# Small padding around text before rotation
WORDCLOUD_GAP = 4

# Maximum placement attempts per word
MAX_PLACEMENT_ATTEMPTS = 1500

# Cache for binary_dilation kernels by padding size
_DILATE_KERNEL_CACHE: dict = {}


def _calculate_font_size(freq: float, max_freq: float) -> int:
    ratio = freq / max_freq if max_freq > 0 else 0
    return int(
        WORDCLOUD_MIN_FONT_SIZE
        + (WORDCLOUD_MAX_FONT_SIZE - WORDCLOUD_MIN_FONT_SIZE)
        * ratio ** WORDCLOUD_RELATIVE_SCALING
    )


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
    """Fallback random color (kept for the small-word filler pass)."""
    rgb_colors = [_hex_to_rgb(c) for c in WORDCLOUD_COLORS]
    lights = rgb_colors[:3]
    rest = rgb_colors[3:]
    toxic_rgb = [_hex_to_rgb(c) for c in WORDCLOUD_TOXIC_COLORS]

    r = rng.random()
    if r < 0.50:
        return rng.choice(lights)
    elif r < 0.85:
        return rng.choice(rest)
    else:
        return rng.choice(toxic_rgb)


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _frequency_color(ratio: float) -> tuple[int, int, int]:
    """Map normalized frequency to the heat ramp.

    ratio 0.0 -> cool blue (rare), ratio 1.0 -> hot red (most frequent).
    This makes popularity readable at a glance, unlike random colors.
    """
    ramp = [_hex_to_rgb(c) for c in WORDCLOUD_HEAT_RAMP]
    if len(ramp) == 1:
        return ramp[0]
    ratio = min(1.0, max(0.0, float(ratio)))
    scaled = ratio * (len(ramp) - 1)
    idx = int(scaled)
    if idx >= len(ramp) - 1:
        return ramp[-1]
    t = scaled - idx
    c1, c2 = ramp[idx], ramp[idx + 1]
    return (
        int(round(_lerp(c1[0], c2[0], t))),
        int(round(_lerp(c1[1], c2[1], t))),
        int(round(_lerp(c1[2], c2[2], t))),
    )


def _draw_background(width: int, height: int) -> Image.Image:
    """Dark vertical gradient with a subtle radial accent glow."""
    base = _hex_to_rgb(WORDCLOUD_BACKGROUND_COLOR)
    top = tuple(min(255, c + 12) for c in base)
    bottom = tuple(max(0, c - 6) for c in base)

    bg = Image.new("RGB", (width, height), base)
    draw = ImageDraw.Draw(bg)
    for y in range(height):
        t = y / max(1, height - 1)
        color = tuple(
            int(round(_lerp(top[i], bottom[i], t))) for i in range(3)
        )
        draw.line([(0, y), (width, y)], fill=color)

    # Soft accent glow near the top center for depth.
    glow = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    gdraw = ImageDraw.Draw(glow)
    accent = _hex_to_rgb(WORDCLOUD_ACCENT_COLOR)
    cx, cy = width // 2, int(height * 0.18)
    max_r = int(width * 0.55)
    steps = 26
    for i in range(steps, 0, -1):
        t = i / steps
        r = int(max_r * t)
        alpha = int(10 * (1 - t))
        if alpha <= 0:
            continue
        gdraw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(*accent, alpha))
    glow = glow.filter(ImageFilter.GaussianBlur(radius=28))
    bg = Image.alpha_composite(bg.convert("RGBA"), glow)
    return bg


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

    kernel = _DILATE_KERNEL_CACHE.get(padding)
    if kernel is None:
        kernel = np.ones((2 * padding + 1, 2 * padding + 1), dtype=bool)
        _DILATE_KERNEL_CACHE[padding] = kernel
    return binary_dilation(alpha, structure=kernel)


def _render_rotated_word(word, font, color, angle):
    """Render a word to a rotated RGBA image.
    Returns (rotated_img, width, height) or (None, 0, 0) on failure.
    The returned width/height are the ACTUAL dimensions of the rotated image.
    """
    bbox = font.getbbox(word)
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
    # Never place words under the drawn card chrome (header/footer panels).
    top_limit = safe_margin + WORDCLOUD_TOP_RESERVE
    bottom_limit = canvas_height - safe_margin - WORDCLOUD_BOTTOM_RESERVE
    if bottom_limit <= top_limit:
        top_limit, bottom_limit = safe_margin, canvas_height - safe_margin

    angle_step = 1.0
    radius_step = 16
    current_radius = 0
    current_angle = rng.random() * 2 * math.pi

    for _ in range(MAX_PLACEMENT_ATTEMPTS):
        x = int(center_x + current_radius * math.cos(current_angle) - word_width / 2)
        y = int(center_y + current_radius * math.sin(current_angle) - word_height / 2)

        # Strict canvas bounds check with safe margin and reserved panels
        if (
            x < safe_margin
            or y < top_limit
            or x + word_width > canvas_width - safe_margin
            or y + word_height > bottom_limit
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


def _ui_font(font_path: str, size: int):
    """Bold UI font for the card chrome (title/legend), falls back gracefully."""
    try:
        return ImageFont.truetype(font_path, size)
    except Exception:
        try:
            return ImageFont.truetype(font_path, max(8, int(size * 0.8)))
        except Exception:
            return ImageFont.load_default()


def _draw_chrome(
    base_img: Image.Image,
    top_words,
    period_label: str,
    message_count: int,
    rising_label: str = "",
) -> None:
    """Draw the OpenDota-style header, frequency legend and footer in-place."""
    width, height = base_img.size
    draw = ImageDraw.Draw(base_img, "RGBA")
    font_path = _resolve_font_path() or ""

    title_font = _ui_font(font_path, 34)
    sub_font = _ui_font(font_path, 18)
    legend_font = _ui_font(font_path, 15)
    foot_font = _ui_font(font_path, 15)

    accent = _hex_to_rgb(WORDCLOUD_ACCENT_COLOR) + (255,)
    accent_soft = _hex_to_rgb(WORDCLOUD_ACCENT_SOFT) + (255,)
    text = _hex_to_rgb(WORDCLOUD_TEXT_COLOR) + (255,)
    muted = _hex_to_rgb(WORDCLOUD_TEXT_MUTED) + (255,)
    panel = _hex_to_rgb(WORDCLOUD_PANEL_COLOR) + (215,)

    # --- Header bar ---
    draw.rectangle([0, 0, width, 86], fill=panel)
    draw.rectangle([0, 86, width, 88], fill=accent)
    draw.text((28, 16), "ОБЛАКО СЛОВ ЧАТА", font=title_font, fill=text)
    draw.text((30, 56), period_label, font=sub_font, fill=muted)
    if rising_label:
        draw.text((30, 78), rising_label, font=legend_font, fill=accent)

    # Top-3 words preview on the right of the header.
    x_cursor = width - 28
    for idx, (word, count) in enumerate(top_words[:3]):
        label = f"{word} · {count}"
        w = draw.textlength(label, font=legend_font)
        chip_w = int(w) + 22
        chip_h = 28
        if idx == 0:
            chip_fill = accent
        elif idx == 1:
            chip_fill = accent_soft
        else:
            chip_fill = (139, 148, 158, 230)
        chip = [x_cursor - chip_w, 20, x_cursor, 20 + chip_h]
        draw.rounded_rectangle(chip, radius=chip_h // 2, fill=chip_fill)
        chip_text = (13, 13, 17, 255) if idx < 2 else (240, 246, 252, 255)
        draw.text((chip[0] + 11, 24), label, font=legend_font, fill=chip_text)
        x_cursor -= chip_w + 10

    # --- Footer: frequency legend + context ---
    foot_h = 62
    fy = height - foot_h
    draw.rectangle([0, fy, width, height], fill=panel)
    draw.rectangle([0, fy, width, fy + 2], fill=accent)

    lx = 28
    ly = fy + 14
    draw.text((lx, ly), "Реже", font=foot_font, fill=muted)
    lx += int(draw.textlength("Реже ", font=foot_font)) + 6
    for i in range(40):
        ratio = i / 39
        c = _frequency_color(ratio)
        x = lx + i * 12
        y = ly + 4
        draw.rounded_rectangle([x, y, x + 10, y + 16], radius=5, fill=(*c, 255))
    lx += 40 * 12 + 6
    draw.text((lx, ly), "Чаще", font=foot_font, fill=muted)

    msg_text = f"Сообщений: {message_count}" if message_count else "Сообщения: нет данных"
    draw.text(
        (width - 28 - int(draw.textlength(msg_text, font=foot_font)), ly),
        msg_text,
        font=foot_font,
        fill=muted,
    )


def generate_wordcloud_image(
    top_words: list[tuple[str, int]],
    *,
    period_label: str = "",
    message_count: int = 0,
    rising_label: str = "",
) -> bytes:
    if not top_words:
        raise ValueError("No words provided for wordcloud")

    logger.info(f"generate_wordcloud_image: generating with {len(top_words)} words")

    font_path = _resolve_font_path()
    if not font_path:
        raise FileNotFoundError(
            f"WordCloud font with Cyrillic support not found. Tried: {WORDCLOUD_FONT_PATH}"
        )

    logger.debug(f"Using font: {font_path}")

    frequencies = {word: float(count) for word, count in top_words}
    max_freq = max(frequencies.values()) if frequencies else 1

    # Sort by frequency - most important words first
    sorted_words = sorted(top_words, key=lambda x: frequencies.get(x[0], 0), reverse=True)

    # Create canvas with the styled background
    canvas_width = WORDCLOUD_WIDTH
    canvas_height = WORDCLOUD_HEIGHT
    base_img = _draw_background(canvas_width, canvas_height)

    # Random generator for placement
    rng = random.Random(WORDCLOUD_RANDOM_STATE)

    # Center of the free word area (between the drawn header and footer).
    center_x = canvas_width // 2
    center_y = (WORDCLOUD_TOP_RESERVE + canvas_height - WORDCLOUD_BOTTOM_RESERVE) // 2

    # Occupied mask for alpha-collision detection
    occupied_mask = np.zeros((canvas_height, canvas_width), dtype=bool)

    # Track placed words for debug
    debug_positions = []
    placed_count = 0
    placed_word_set = set()
    placement_failures = []

    # Font cache to avoid repeated truetype() calls
    font_cache: dict[int, ImageFont.FreeTypeFont] = {}

    def get_font(size: int) -> ImageFont.FreeTypeFont | None:
        if size in font_cache:
            return font_cache[size]
        try:
            font = ImageFont.truetype(font_path, size)
            font_cache[size] = font
            return font
        except Exception:
            return None

    def try_place(word, count, current_font_size):
        nonlocal placed_count
        current_font = get_font(current_font_size)
        if current_font is None:
            return False

        angle = rng.choice(WORDCLOUD_ANGLES)
        # Color encodes frequency: hot = popular, cool = rare.
        ratio = (frequencies.get(word, 1) / max_freq) if max_freq > 0 else 0.0
        color = _frequency_color(ratio)

        # Pre-render rotated word to get ACTUAL dimensions and alpha mask
        rotated, rw, rh = _render_rotated_word(word, current_font, color, angle)
        if rotated is None:
            return False

        # Extract alpha mask for collision detection (only text pixels)
        word_alpha = np.array(rotated.split()[-1], dtype=bool)

        # Dilate alpha mask by WORD_PADDING for collision detection.
        # This creates a buffer zone between words without adding visible padding.
        collision_alpha = _dilate_alpha_mask(word_alpha, WORDCLOUD_WORD_PADDING)
        if collision_alpha.shape != (rh, rw):
            logger.warning(
                f"Skipping word '{word}': collision mask shape {collision_alpha.shape} "
                f"does not match rendered size {(rh, rw)}"
            )
            return False

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
            occupied_region = occupied_mask[y : y + rh, x : x + rw]
            occupied_region[collision_alpha] = True

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
    for word, count in sorted_words[: WORDCLOUD_MAX_WORDS]:
        if not word or len(word) < 2:
            continue

        freq = frequencies.get(word, 1)
        font_size = _calculate_font_size(freq, max_freq)

        if get_font(font_size) is None:
            continue

        placed = False
        for size_reduction in range(10):
            current_font_size = font_size - size_reduction * 2
            if current_font_size < WORDCLOUD_MIN_FONT_SIZE:
                current_font_size = WORDCLOUD_MIN_FONT_SIZE

            if try_place(word, count, current_font_size):
                placed = True
                break

            if current_font_size == WORDCLOUD_MIN_FONT_SIZE:
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
    small_words = small_words[:40]

    for word, count in small_words:
        small_font = get_font(WORDCLOUD_MIN_FONT_SIZE)
        if small_font is None:
            continue

        color = _frequency_color((frequencies.get(word, 1) / max_freq) if max_freq > 0 else 0.0)
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
            occupied_region = occupied_mask[y : y + rh, x : x + rw]
            occupied_region[collision_alpha] = True
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
    if WORDCLOUD_DEBUG and placed_count > 0:
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

    # Draw the OpenDota-style card chrome (header, top words, legend, footer)
    # on top of the placed words so every card explains its own data.
    try:
        _draw_chrome(base_img, sorted_words, period_label, message_count, rising_label)
    except Exception as e:
        logger.warning(f"Could not draw wordcloud chrome: {e}")

    # Save image
    buf = io.BytesIO()
    base_img.convert("RGB").save(buf, format="PNG", optimize=True)
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
        font_size = _calculate_font_size(freq, max_freq)

        # Try size reduction for each word (like generate_wordcloud_image)
        word_placed = False
        for size_reduction in range(10):
            current_font_size = font_size - size_reduction * 2
            if current_font_size < WORDCLOUD_MIN_FONT_SIZE:
                current_font_size = WORDCLOUD_MIN_FONT_SIZE

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
                occupied_region = occupied_mask[y : y + rh, x : x + rw]
                occupied_region[collision_alpha] = True
                print(f"Placed '{word}' at ({x}, {y}) size {rw}x{rh} angle {angle}")
                word_placed = True
                break

            if current_font_size == WORDCLOUD_MIN_FONT_SIZE:
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
