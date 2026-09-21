"""Альтернативные раскладки профиля (A/B/C) для сравнения. Не часть тестов."""
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from PIL import Image, ImageDraw  # noqa: E402

import dota_mmr as dm  # noqa: E402

OUT = Path(__file__).parent / "_profile_preview"
OUT.mkdir(exist_ok=True)
W, H, SS = dm.PROFILE_CARD_W, dm.PROFILE_CARD_H, dm.PROFILE_CARD_SS

DATA = dict(
    rank_tier=54, total_rolls=321, weekly_rolls=17, best_streak=11,
    message_count=23456, week_games=24, week_wins=15,
    dota_total_games=1874, dota_wins=982, fissure=42.7,
    tags=["weekly_mvp", "weekly_top2", "fissure_master"],
    award_counts={"weekly_mvp": 3, "weekly_top2": 2},
    top_heroes=[{"short_name": "axe", "picks": 12},
                {"short_name": "invoker", "picks": 9},
                {"short_name": "juggernaut", "picks": 7}],
)


def new_card():
    img = dm._profile_background().resize((W * SS, H * SS), Image.LANCZOS).convert("RGBA")
    return img, dm._ProfileCanvas(img, SS)


def save(img, path):
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "PNG")
    path.write_bytes(buf.getvalue())


def avatar_block(c, x, y, size, medal_size, radius=26):
    """Квадратная аватарка + медаль наполовину на фото."""
    c.rect(x + 6, y + 7, size, size, radius=radius, fill=(9, 12, 22, 170))
    mask = dm._profile_round_mask(c.p(size), c.p(radius))
    av = dm._profile_load_avatar(None, c.p(size))
    if av is None:
        ph = Image.new("RGBA", (c.p(size), c.p(size)), (0, 0, 0, 0))
        d = ImageDraw.Draw(ph)
        d.ellipse([c.p(size * 0.32), c.p(size * 0.22), c.p(size * 0.68), c.p(size * 0.58)],
                  fill=(76, 92, 124, 240))
        d.rounded_rectangle([c.p(size * 0.16), c.p(size * 0.64),
                             c.p(size * 0.84), c.p(size * 1.02)],
                            radius=c.p(size * 0.24), fill=(76, 92, 124, 240))
        av = ph
    c.paste(dm._profile_masked(av, mask), x, y)
    c.rect(x, y, size, size, radius=radius, outline=(255, 255, 255, 42), width=1.4)
    medal = dm._profile_rank_medal(DATA["rank_tier"], c.p(medal_size))
    if medal is not None:
        c.paste(medal, x + size / 2 - medal_size / 2, y + size - medal_size / 2, medal)


def get_awards():
    return dm._profile_awards(DATA["tags"], DATA["award_counts"], mmr=3760,
                              total_rolls=DATA["total_rolls"],
                              best_streak=DATA["best_streak"],
                              message_count=DATA["message_count"])


def award_tile(c, a, x, y, tile, icon_size=44):
    c.rect(x, y, tile, tile, radius=16, fill=(20, 24, 38, 190),
           outline=(*a["color"][:3], 130), width=1.4)
    icon = dm._profile_award_icon(a["icon"], c.p(icon_size), a["color"])
    if icon is not None:
        c.paste(icon, x + tile / 2 - icon_size / 2, y + 16)
    c.text((x + tile / 2, y + tile - 12),
           dm._profile_clean_text(a["label"], c.font(11, "bold")),
           11, dm._PC_WHITE, "bold", "ma")


def hero_tiles(c, heroes, x, y, tile, gap=12):
    for h in heroes:
        hero = dm._profile_hero_image(h["short_name"], c.p(tile))
        if hero is not None:
            c.paste(hero, x, y)
        c.rect(x, y, tile, tile, radius=10, outline=(255, 255, 255, 30), width=1)
        c.text((x + tile / 2, y + tile + 4), f"x{h['picks']}", 11, dm._PC_WHITE, "bold", "ma")
        x += tile + gap

# ---------- A: аватар слева, статы справа сеткой, полоса наград внизу ----------
def variant_a():
    img, c = new_card()
    av_x, av_y, av_s = 40.0, 36.0, 220.0
    avatar_block(c, av_x, av_y, av_s, 150.0)
    tx = av_x + av_s + 28
    c.text((tx, 48), "@seredin999", 40, dm._PC_WHITE, "bold", "la")
    c.text((tx + 4, 104), "Seredin999", 18, dm._PC_GREY, "regular", "la")
    hero_tiles(c, DATA["top_heroes"], tx, 150.0, 60.0)
    gx, gy, cw = 640.0, 44.0, 250.0
    pairs = [("БРОСКИ", dm._profile_num(DATA["total_rolls"]), f"за неделю {DATA['weekly_rolls']}"),
             ("WR НЕДЕЛИ", "63%", f"{DATA['week_wins']}W · 9L"),
             ("СООБЩЕНИЯ", dm._profile_num(DATA["message_count"]), f"стрик {DATA['best_streak']}"),
             ("FISSURE", f"{DATA['fissure']:.1f}", "коэф. мастерства")]
    for i, (lab, val, sub) in enumerate(pairs):
        x = gx + (i % 2) * cw
        y = gy + (i // 2) * 92
        c.text((x, y), lab, 12, dm._PC_GREY, "bold", "la")
        c.text((x, y + 18), val, 26, dm._PC_WHITE, "bold", "la")
        c.text((x + cw - 30, y + 26), sub, 12, dm._PC_GREY, "regular", "ra")
    c.line(40, 320, W - 40, 320, (255, 255, 255, 26), 1)
    c.text_tracked((40, 340), "НАГРАДЫ", 12, dm._PC_GOLD_LIGHT)
    ax, ay, tile = 40.0, 368.0, 122.0
    for a in get_awards()[:9]:
        award_tile(c, a, ax, ay, tile)
        ax += tile + 14
    return img


# ---------- B: центрированный, статы столбцами по бокам, награды по центру ----------
def variant_b():
    img, c = new_card()
    av_s, medal_s = 180.0, 132.0
    avatar_block(c, (W - av_s) / 2, 30.0, av_s, medal_s)
    c.text((W / 2, 232), "@seredin999", 38, dm._PC_WHITE, "bold", "ma")
    c.text((W / 2, 284), "Seredin999 · позиция 2", 16, dm._PC_GREY, "regular", "ma")
    left = [("БРОСКИ", dm._profile_num(DATA["total_rolls"])),
            ("СООБЩЕНИЯ", dm._profile_num(DATA["message_count"])),
            ("FISSURE", f"{DATA['fissure']:.1f}")]
    right = [("WR НЕДЕЛИ", "63%"),
             ("ИГР В DOTA", dm._profile_num(DATA["dota_total_games"])),
             ("ПОБЕДЫ", dm._profile_num(DATA["dota_wins"]))]
    for i, (lab, val) in enumerate(left):
        y = 120 + i * 100
        c.text((70, y), lab, 12, dm._PC_GREY, "bold", "la")
        c.text((70, y + 20), val, 30, dm._PC_WHITE, "bold", "la")
    for i, (lab, val) in enumerate(right):
        y = 120 + i * 100
        c.text((W - 70, y), lab, 12, dm._PC_GREY, "bold", "ra")
        c.text((W - 70, y + 20), val, 30, dm._PC_WHITE, "bold", "ra")
    awards = get_awards()
    total_w = len(awards) * 130 + (len(awards) - 1) * 14
    ax, ay = (W - total_w) / 2, 372.0
    for a in awards:
        award_tile(c, a, ax, ay, 130.0, icon_size=46)
        ax += 130 + 14
    return img


# ---------- C: аватар-полоса слева во всю высоту, крупные метрики справа ----------
def variant_c():
    img, c = new_card()
    av_s, medal_s = 272.0, 156.0
    avatar_block(c, 36.0, 36.0, av_s, medal_s)
    c.rect(36, 356, av_s, 208, radius=18, fill=(12, 15, 26, 150))
    c.text((54, 376), "ГЕРОИ НЕДЕЛИ", 12, dm._PC_GOLD_LIGHT, "bold", "la")
    hero_tiles(c, DATA["top_heroes"], 54, 400.0, 62.0, gap=10)
    tx = 360.0
    c.text((tx, 48), "@seredin999", 44, dm._PC_WHITE, "bold", "la")
    c.text((tx + 4, 110), "Seredin999 · позиция 2", 18, dm._PC_GREY, "regular", "la")
    metrics = [("БРОСКИ", dm._profile_num(DATA["total_rolls"]), f"+{DATA['weekly_rolls']} за неделю"),
               ("WR НЕДЕЛИ", "63%", f"{DATA['week_wins']}W · 9L"),
               ("FISSURE", f"{DATA['fissure']:.1f}", "рекорд 118.4")]
    for i, (lab, val, sub) in enumerate(metrics):
        x = tx + i * 272
        c.text((x, 168), lab, 12, dm._PC_GREY, "bold", "la")
        c.text((x, 188), val, 40, dm._PC_GOLD_LIGHT, "bold", "la")
        c.text((x, 244), sub, 12, dm._PC_GREY, "regular", "la")
    c.line(tx, 300, W - 40, 300, (255, 255, 255, 26), 1)
    c.text_tracked((tx, 320), "НАГРАДЫ", 12, dm._PC_GOLD_LIGHT)
    ax, ay, tile = tx, 348.0, 130.0
    for i, a in enumerate(get_awards()):
        if i == 4:
            ax, ay = tx, ay + tile + 16
        award_tile(c, a, ax, ay, tile)
        ax += tile + 14
    return img


for name, fn in {"alt_A_band": variant_a, "alt_B_center": variant_b,
                 "alt_C_split": variant_c}.items():
    out = OUT / f"{name}.png"
    save(fn(), out)
    print("OK  ", name, out)
