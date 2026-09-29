"""WordCloud rendered in the analytics-chart HUD design.

The analytics chart (weekly_analytics._create_visual_chart_sync) draws a dark
1200x800 card: a near-black base, one random accent, a rounded panel with a
thin accent outline, and a small geometric shape behind everything. This module
reuses that exact palette so both images look like they come from the same bot.
"""
from __future__ import annotations

import io
import logging
import math
import random
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from chat_wordcloud.config import (
    WORDCLOUD_MIN_FONT_SIZE,
    WORDCLOUD_RELATIVE_SCALING,
    WORDCLOUD_WORD_PADDING,
)
from chat_wordcloud.generator import (
    _dilate_alpha_mask,
    _render_rotated_word,
)

logger = logging.getLogger(__name__)

# Spiral placement budget, matching the OpenDota layout generator.
MAX_PLACEMENT_ATTEMPTS = 1500
ANGLE_STEP = 1.0
RADIUS_STEP = 16

HUD_WIDTH = 1200
HUD_HEIGHT = 800

# Panel frame, identical to the analytics chart.
PANEL_BOX = (30, 24, 1170, 776)
PANEL_RADIUS = 22
PANEL_FILL = (8, 10, 20, 220)

# Free area for words: inside the panel, below the header, above the footer.
HEADER_BOTTOM = 150
FOOTER_TOP = 700
WORD_AREA_PAD = 46

MAX_FONT_SIZE = 86
MIN_FONT_SIZE = WORDCLOUD_MIN_FONT_SIZE
MAX_WORDS = 110

# Same accent/secondary/bg choices the analytics chart draws from.
ACCENTS = ["#ff8c42", "#a855f7", "#22c55e", "#f43f5e", "#06b6d4", "#facc15", "#38bdf8"]
SECONDARIES = ["#22d3ee", "#f97316", "#38bdf8", "#fbbf24", "#a855f7", "#84cc16"]
BG_BASES = [(9, 12, 22), (20, 10, 32), (5, 18, 30), (30, 12, 18), (12, 24, 18)]

MUTED = "#94a3b8"
TEXT = "#f8fafc"
SUBTEXT = "#cbd5e1"

# 90% horizontal, 10% vertical - same readability rule as the OpenDota layout.
ANGLES = [0] * 9 + [90, -90]

_FONT_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"
_font_cache: dict[tuple[int, bool], ImageFont.FreeTypeFont] = {}


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    """Resolve a font the same way the analytics chart does."""
    key = (size, bold)
    cached = _font_cache.get(key)
    if cached is not None:
        return cached
    name = "NotoSans-Bold.ttf" if bold else "NotoSans-Regular.ttf"
    resolved = None
    for candidate in (
        _FONT_DIR / name,
        Path("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"),
    ):
        try:
            resolved = ImageFont.truetype(str(candidate), size)
            break
        except OSError:
            continue
    if resolved is None:
        resolved = ImageFont.load_default()
    _font_cache[key] = resolved
    return resolved


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _find_spiral_position(
    left: int,
    right: int,
    top: int,
    bottom: int,
    word_width: int,
    word_height: int,
    occupied_mask: np.ndarray,
    word_alpha: np.ndarray,
    center_x: int,
    center_y: int,
    rng: random.Random,
):
    """Place a word by spiralling out from the centre of the free word area.

    Same alpha-mask collision detection as the OpenDota layout, but bounded by
    an explicit rectangle so words can never land on the HUD header/footer.
    """
    max_radius = math.sqrt((right - left) ** 2 + (bottom - top) ** 2) / 2
    radius = 0.0
    angle = rng.random() * 2 * math.pi

    for _ in range(MAX_PLACEMENT_ATTEMPTS):
        x = int(center_x + radius * math.cos(angle) - word_width / 2)
        y = int(center_y + radius * math.sin(angle) - word_height / 2)

        inside = (
            x >= left
            and y >= top
            and x + word_width <= right
            and y + word_height <= bottom
        )
        if inside:
            region = occupied_mask[y : y + word_height, x : x + word_width]
            if not np.any(region[word_alpha]):
                return x, y

        angle += ANGLE_STEP
        radius += RADIUS_STEP / (2 * math.pi)
        if radius > max_radius:
            return None
    return None


def _mix(c1: tuple[int, int, int], c2: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return tuple(int(round(_lerp(c1[i], c2[i], t))) for i in range(3))


def _draw_backdrop(
    base: tuple[int, int, int], accent: tuple[int, int, int], secondary: tuple[int, int, int], shape: str
) -> Image.Image:
    """Dark base + one low-alpha geometric shape, matching the chart backdrop."""
    canvas = Image.new("RGBA", (HUD_WIDTH, HUD_HEIGHT), (*base, 255))
    draw = ImageDraw.Draw(canvas, "RGBA")

    if shape == "diagonal":
        draw.polygon(
            [(0, 0), (HUD_WIDTH, 0), (HUD_WIDTH, 180), (0, 320)],
            fill=(*accent, 28),
        )
    elif shape == "orb":
        draw.ellipse((650, -260, 1350, 440), fill=(*secondary, 24))
    elif shape == "rays":
        draw.polygon(
            [(0, HUD_HEIGHT), (HUD_WIDTH, HUD_HEIGHT), (HUD_WIDTH, 520), (0, 680)],
            fill=(*accent, 18),
        )
    else:  # corner
        draw.polygon(
            [(0, 0), (520, 0), (0, 420)],
            fill=(*secondary, 22),
        )
    return canvas


def _draw_panel(canvas: Image.Image, accent: tuple[int, int, int]) -> Image.Image:
    draw = ImageDraw.Draw(canvas, "RGBA")
    draw.rounded_rectangle(
        PANEL_BOX, PANEL_RADIUS, fill=PANEL_FILL, outline=(*accent, 190), width=3
    )
    return canvas


def _font_size_for(ratio: float, max_font_size: int, relative_scaling: float) -> int:
    """Map normalized frequency to a font size (top word is always the largest)."""
    return int(
        MIN_FONT_SIZE
        + (max_font_size - MIN_FONT_SIZE) * (ratio ** relative_scaling)
    )


def _word_color(
    ratio: float,
    accent: tuple[int, int, int],
    secondary: tuple[int, int, int],
    *,
    ramp: str = "accent",
) -> tuple[int, int, int]:
    """Map normalized frequency to a colour.

    ramp="accent"  - muted -> secondary -> accent (default, matches the chart)
    ramp="heat"    - cool blue -> green -> amber -> hot (frequency as heat)
    ramp="monotone"- dim accent -> full accent only (two-tone, max contrast)
    ramp="inverse" - accent for rare words, muted for frequent (upside-down)
    """
    muted = _hex_to_rgb(MUTED)
    if ramp == "monotone":
        return _mix(_scale_rgb(accent, 0.45), accent, ratio)
    if ramp == "inverse":
        return _mix(accent, muted, ratio)
    if ramp == "heat":
        heat = [
            _hex_to_rgb(c)
            for c in ("#38bdf8", "#22c55e", "#facc15", "#f97316", "#ef4444")
        ]
        scaled = min(1.0, max(0.0, ratio)) * (len(heat) - 1)
        idx = int(scaled)
        if idx >= len(heat) - 1:
            return heat[-1]
        return _mix(heat[idx], heat[idx + 1], scaled - idx)
    if ratio >= 0.55:
        return _mix(accent, secondary, (1.0 - ratio) / 0.45)
    return _mix(muted, secondary, min(1.0, ratio / 0.55))


def _scale_rgb(color: tuple[int, int, int], factor: float) -> tuple[int, int, int]:
    return tuple(max(0, min(255, int(round(c * factor)))) for c in color)


def generate_hud_wordcloud(
    top_words: list[tuple[str, int]],
    *,
    title: str = "ОБЛАКО СЛОВ",
    subtitle: str = "",
    footer: str = "",
    seed: int | None = None,
    # --- layout knobs: each variant picks its own so cards differ structurally ---
    max_font_size: int = MAX_FONT_SIZE,
    relative_scaling: float = WORDCLOUD_RELATIVE_SCALING,
    angles: list[int] | None = None,
    word_area: tuple[int, int, int, int] | None = None,
    word_padding: int = WORDCLOUD_WORD_PADDING,
    color_ramp: str = "accent",
    bold_threshold: float = 0.55,
    force_shape: str | None = None,
    force_accent: str | None = None,
    force_base: tuple[int, int, int] | None = None,
    panel: bool = True,
) -> bytes:
    """Render a word cloud in the analytics HUD design and return PNG bytes.

    `seed` makes the accent/background/shape choice reproducible, so the same
    call with the same seed always produces the same card. The keyword knobs let
    a caller explore genuinely different layouts (rotation, density, area,
    palette) instead of only different words.
    """
    if not top_words:
        raise ValueError("No words provided for wordcloud")

    rng = random.Random(seed)
    accent_hex = force_accent or rng.choice(ACCENTS)
    secondary_hex = rng.choice(SECONDARIES)
    accent = _hex_to_rgb(accent_hex)
    secondary = _hex_to_rgb(secondary_hex)
    base = force_base or rng.choice(BG_BASES)
    shape = force_shape or rng.choice(("diagonal", "orb", "rays", "corner"))
    angle_choices = list(angles) if angles else list(ANGLES)

    logger.info(
        "generate_hud_wordcloud: %d words, accent=%s shape=%s ramp=%s max_font=%d",
        len(top_words), accent_hex, shape, color_ramp, max_font_size,
    )

    canvas = _draw_backdrop(base, accent, secondary, shape)
    if panel:
        canvas = _draw_panel(canvas, accent)

    words = [(w, c) for w, c in top_words if w and len(w) >= 2][:MAX_WORDS]
    words.sort(key=lambda item: item[1], reverse=True)
    max_count = words[0][1] if words else 1

    if word_area:
        left, top, right, bottom = word_area
    else:
        left = PANEL_BOX[0] + WORD_AREA_PAD
        right = PANEL_BOX[2] - WORD_AREA_PAD
        top = HEADER_BOTTOM
        bottom = FOOTER_TOP
    center_x = (left + right) // 2
    center_y = (top + bottom) // 2

    occupied = np.zeros((HUD_HEIGHT, HUD_WIDTH), dtype=bool)
    placed = 0

    for word, count in words:
        ratio = (count / max_count) if max_count else 0.0
        size = _font_size_for(ratio, max_font_size, relative_scaling)
        color = _word_color(ratio, accent, secondary, ramp=color_ramp)

        done = False
        for shrink in range(12):
            font_size = max(MIN_FONT_SIZE, size - shrink * 2)
            font = _font(font_size, bold=ratio >= bold_threshold)
            angle = rng.choice(angle_choices)

            rotated, rw, rh = _render_rotated_word(word, font, (*color, 255), angle)
            if rotated is None:
                continue

            alpha = np.array(rotated.split()[-1], dtype=bool)
            collision = _dilate_alpha_mask(alpha, word_padding)
            if collision.shape != (rh, rw):
                continue

            pos = _find_spiral_position(
                left, right, top, bottom,
                rw, rh, occupied, collision, center_x, center_y, rng,
            )
            if pos:
                x, y = pos
                canvas.alpha_composite(rotated, (x, y))
                region = occupied[y : y + rh, x : x + rw]
                region[collision] = True
                placed += 1
                done = True
                break
            if font_size == MIN_FONT_SIZE:
                break

        if not done:
            logger.debug("hud wordcloud: could not place '%s'", word)

    draw = ImageDraw.Draw(canvas, "RGBA")
    draw.text((58, 48), title, font=_font(24, True), fill=accent_hex)
    if subtitle:
        draw.text((58, 88), subtitle, font=_font(18), fill=SUBTEXT)
    if footer:
        draw.text((58, 700), footer, font=_font(25, True), fill=TEXT)

    buffer = io.BytesIO()
    canvas.convert("RGB").save(buffer, format="PNG", optimize=True)
    logger.info("hud wordcloud rendered: %d/%d words placed", placed, len(words))
    return buffer.getvalue()
