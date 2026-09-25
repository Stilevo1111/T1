"""Generate ten visual concepts for the analytics chart.

Every option keeps a smooth line, hero nodes, and colored hero outlines.
Run from the repository root: python scripts/generate_analytics_chart_options.py
"""
from pathlib import Path
import os
import random
import sys
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from hero_names import get_cdn_hero_name

OUT = Path("charts/options")
OUT.mkdir(parents=True, exist_ok=True)
_rng = random.Random(os.getenv("ANALYTICS_THEME_SEED"))
W, H = 1200, 800
NAMES = ["neon_arcade", "dark_fantasy", "clean_esports", "retro_rpg", "cyber_hud", "bloodline", "ice_clash", "royal_neon", "toxic_core", "sunset_ranked"]
COLORS = [("#ff8c42", "#22d3ee"), ("#a855f7", "#f97316"), ("#22c55e", "#38bdf8"), ("#f43f5e", "#fbbf24"), ("#06b6d4", "#a855f7"), ("#ef4444", "#f59e0b"), ("#38bdf8", "#e0e7ff"), ("#facc15", "#8b5cf6"), ("#84cc16", "#22d3ee"), ("#fb7185", "#fdba74")]

def rgba(hex_color, alpha):
    h=hex_color.lstrip("#")
    return tuple(int(h[i:i+2],16) for i in (0,2,4))+(alpha,)

def font(size, bold=False):
    p = Path("assets/fonts") / ("NotoSans-Bold.ttf" if bold else "NotoSans-Regular.ttf")
    try: return ImageFont.truetype(str(p), size)
    except OSError: return ImageFont.load_default()

def _smooth_curve(points, samples_per_segment=80):
    """Bezier/Catmull-style curve that cannot overshoot match values."""
    out = []
    for i in range(len(points) - 1):
        p0 = points[max(i - 1, 0)]
        p1 = points[i]
        p2 = points[i + 1]
        p3 = points[min(i + 2, len(points) - 1)]
        c1 = (p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6)
        c2 = (p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6)
        lo, hi = min(p1[1], p2[1]), max(p1[1], p2[1])
        c1 = (c1[0], max(lo, min(hi, c1[1])))
        c2 = (c2[0], max(lo, min(hi, c2[1])))
        for step in range(samples_per_segment):
            t = step / samples_per_segment
            q = 1 - t
            out.append((
                q**3*p1[0] + 3*q*q*t*c1[0] + 3*q*t*t*c2[0] + t**3*p2[0],
                q**3*p1[1] + 3*q*q*t*c1[1] + 3*q*t*t*c2[1] + t**3*p2[1],
            ))
    out.append(points[-1])
    return out


DEMO_HEROES = ["juggernaut", "puck", "axe", "lion", "phantom_assassin", "invoker", "tiny", "oracle", "ursa", "rubick"]
HERO_DIR = Path("assets/heroes_webp")

def hero_icon(hero_name, size=56):
    cdn_name = get_cdn_hero_name(hero_name)
    path = HERO_DIR / f"{cdn_name}.webp"
    if not path.exists():
        path = HERO_DIR / f"{hero_name}.webp"
    if not path.exists():
        return None
    with Image.open(path) as source:
        source.load()
        # Keep the original RGBA alpha; do not crop or force a square mask.
        return source.convert("RGBA").resize((size, size), Image.Resampling.LANCZOS)


def make(name, accent, secondary, index):
    accent = _rng.choice(COLORS)[0]
    secondary = _rng.choice(COLORS)[1]
    bg_base = _rng.choice([(9, 12, 22), (20, 10, 32), (5, 18, 30), (30, 12, 18), (12, 24, 18)])
    layout = _rng.choice(["diagonal", "orb", "rays", "corner"])
    accent = _rng.choice([accent, secondary])
    bg = Image.new("RGBA",(W,H),(*bg_base,255)); d=ImageDraw.Draw(bg,"RGBA")
    d.rectangle((0,0,W,H), fill=(*bg_base,255))
    if layout == "diagonal":
        d.polygon([(0,0),(W,0),(W,180),(0,320)], fill=rgba(accent,28))
    elif layout == "orb":
        d.ellipse((650,-260,1350,440), fill=rgba(secondary,24))
    elif layout == "rays":
        d.polygon([(0,H),(W,H),(W,520),(0,680)], fill=rgba(accent,18))
    else:
        d.polygon([(0,0),(420,0),(0,400)], fill=rgba(secondary,18))
    d.rounded_rectangle((30,24,1170,776),22,fill=(8,10,20,220),outline=rgba(accent,190),width=3)
    d.text((58,48), "ИСТОРИЯ МАТЧЕЙ",font=font(24,True),fill=accent)
    d.text((58,88),"РОЛЬ: НЕ ОПРЕДЕЛЕНА  •  ПОСЛЕДНИЕ 10 МАТЧЕЙ",font=font(18),fill="#cbd5e1")
    # Explicit 0..2 index scale, so every point has an understandable meaning.
    left, right, top, bottom = 145, 1085, 175, 690
    values = [0.72, 0.91, 0.64, 1.18, 1.42, 1.09, 1.67, 1.31, 1.88, 1.54]
    pts = [(left + (right - left) * i / 9, bottom - (bottom - top) * value / 2) for i, value in enumerate(values)]
    for value in (0, 0.5, 1.0, 1.5, 2.0):
        y = bottom - (bottom - top) * value / 2
        d.text((72, y - 11), f"{value:.1f}", font=font(16, True), fill="#94a3b8")
    path=Image.new("RGBA",(W*2,H*2),(0,0,0,0)); pd=ImageDraw.Draw(path)
    expanded=[(x*2,y*2) for x,y in _smooth_curve(pts)]
    pd.line(expanded,fill=rgba(accent,255),width=14,joint="curve")
    path=path.resize((W,H),Image.Resampling.LANCZOS)
    bg=Image.alpha_composite(bg,path); d=ImageDraw.Draw(bg,"RGBA")
    for i,(x,y) in enumerate(pts):
        win=i%2==0; col=secondary if win else "#fb7185"
        d.ellipse((x-27,y-27,x+27,y+27),fill=(14,18,32,255),outline=col,width=6)
        icon = hero_icon(DEMO_HEROES[i % len(DEMO_HEROES)], size=48)
        if icon is not None:
            bg.alpha_composite(icon, (int(x - 24), int(y - 24)))
        else:
            d.ellipse((x-12,y-12,x+12,y+12),fill=col)
        d.text((int(x-18), int(y-52)), f"{values[i]:.2f}", font=font(15, True), fill="#f8fafc")
    d.text((58,700),f"СРЕДНИЙ ИНДЕКС: {sum(values)/len(values):.2f}  •  ПОБЕД: 6  •  ПОРАЖЕНИЙ: 3",font=font(25,True),fill="#f8fafc")
    d.text((58,744),"ЛИНИЯ = ДИНАМИКА ИНДЕКСА  •  ИКОНКА = ГЕРОЙ  •  ЦВЕТ = РЕЗУЛЬТАТ МАТЧА",font=font(16),fill="#94a3b8")
    bg.convert("RGB").save(OUT/f"analytics_{index+1:02d}_{name}.jpg",quality=92,optimize=True)

for i,(name,colors) in enumerate(zip(NAMES,COLORS)): make(name,*colors,i)
print(f"Created {len(NAMES)} options in {OUT}")
