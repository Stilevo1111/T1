"""Convert the supplied Roshan artwork into the bot's banner format.

The source is 1024x500 (ratio 2.05) while the shipped banners are 1200x321
(ratio 3.74), so reaching the target ratio means keeping only the middle ~55%
of the source height. That crop is destructive, so:

  * the crop is anchored slightly above centre (42% from the top), because the
    subject in character artwork sits high and the bottom is usually empty;
  * CROP_TOP_FRACTION is a module constant so the anchor can be moved without
    touching the rest of the pipeline;
  * a full-height, uncropped WEBP is written next to the output so nothing from
    the source is lost if the crop turns out to be wrong.

Alpha is flattened onto the bot's panel background (8, 10, 20) rather than
black, which matches the panel colour used by scripts/banners_roll_style.py.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SRC = Path(r"C:\Users\akado\Downloads\Угадал1111.png")
OUT = ROOT / "images" / "banners" / "roshan.webp"
FULL_OUT = ROOT / "preview" / "roshan_full_ratio.webp"

TARGET_W, TARGET_H = 1200, 321
PANEL_BG = (8, 10, 20)
CROP_TOP_FRACTION = 0.42
QUALITY = 88


def main() -> int:
    if not SRC.exists():
        print(f"source not found: {SRC}")
        return 1

    im = Image.open(SRC)
    print(f"source: {im.size[0]}x{im.size[1]} {im.mode}")

    # Flatten alpha onto the panel colour.
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA")
        flat = Image.new("RGB", im.size, PANEL_BG)
        flat.paste(im, mask=im.split()[-1])
        im = flat
    else:
        im = im.convert("RGB")

    # Preserve the uncropped artwork at native width.
    FULL_OUT.parent.mkdir(parents=True, exist_ok=True)
    im.save(FULL_OUT, "WEBP", quality=QUALITY, method=6)

    # Crop vertically to the target ratio, anchored by CROP_TOP_FRACTION.
    target_ratio = TARGET_W / TARGET_H
    keep_h = round(im.size[0] / target_ratio)
    keep_h = min(keep_h, im.size[1])
    keep_w = min(im.size[0], round(keep_h * target_ratio))
    top = int(round((im.size[1] - keep_h) * CROP_TOP_FRACTION))
    left = (im.size[0] - keep_w) // 2

    cropped = im.crop((left, top, left + keep_w, top + keep_h))
    print(f"crop:   box=({left}, {top}, {left + keep_w}, {top + keep_h}) "
          f"keeping {keep_h}/{im.size[1]} of the source height")

    # Resample after cropping so we scale the smaller area only once.
    if cropped.size != (TARGET_W, TARGET_H):
        cropped = cropped.resize((TARGET_W, TARGET_H), Image.LANCZOS)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    cropped.save(OUT, "WEBP", quality=QUALITY, method=6)
    print(f"wrote {OUT} ({TARGET_W}x{TARGET_H}) {OUT.stat().st_size // 1024} KB")
    print(f"wrote {FULL_OUT} ({im.size[0]}x{im.size[1]}) {FULL_OUT.stat().st_size // 1024} KB (uncropped)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
