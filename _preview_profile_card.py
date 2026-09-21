"""Одноразовый визуальный прогон generate_profile_card (не часть тестов)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import dota_mmr  # noqa: E402

OUT = Path(__file__).parent / "_profile_preview"
OUT.mkdir(exist_ok=True)

CASES = {
    "01_uncalibrated": dict(),
    "02_recruit1": dict(mmr=150, rank_tier=11, fissure=3.2, total_rolls=4,
                        current_streak=1, username="новичок"),
    "03_legend4": dict(
        mmr=3760, rank_tier=54, fissure=42.7, total_rolls=321,
        weekly_rolls=17, current_streak=3, best_streak=11, message_count=23456,
        week_games=24, week_wins=15, dota_total_games=1874, dota_wins=982,
        username="seredin999", steam_nickname="Seredin999",
        position=2, tags=["weekly_mvp", "weekly_top2", "fissure_master"],
        award_counts={"weekly_mvp": 3, "weekly_top2": 2},
    ),
    "04_titan": dict(mmr=6120, rank_tier=85, fissure=118.4, total_rolls=912,
                     best_streak=27, message_count=41000, username="titan",
                     week_games=31, week_wins=24, position=1,
                     tags=["weekly_mvp", "fissure_master"],
                     award_counts={"weekly_mvp": 6}),
    "05_heroes": dict(
        mmr=2450, rank_tier=41, username="hero_lover", fissure=15.5, total_rolls=64,
        top_heroes=[{"short_name": "axe", "picks": 12},
                    {"short_name": "invoker", "picks": 9},
                    {"short_name": "juggernaut", "picks": 7}],
        tags=["fissure_master"],
    ),
    # Проверка фиксов: 9 наград (было обрезание за канвас) + эмодзи в нике (был «тофу»)
    "06_nine_awards": dict(
        mmr=6200, rank_tier=85, fissure=214.9, total_rolls=380, best_streak=15,
        message_count=25000, username="🛡️legenda", steam_nickname="Legend🔥",
        position=1, week_games=29, week_wins=22,
        tags=["weekly_mvp", "weekly_top2", "weekly_top3", "fissure_master", "admin_custom"],
        award_counts={"weekly_mvp": 9, "weekly_top2": 4, "weekly_top3": 2},
    ),
    # Ещё одна непокрытая ветка: steam_id есть, рейтинга нет → «—» серым / «нет рейтинга»
    "07_no_rank": dict(steam_id=76561198000000000, username="без_ранга",
                       fissure=7.0, total_rolls=12, message_count=42),
}

for name, kwargs in CASES.items():
    data = dota_mmr.generate_profile_card(**kwargs)
    if not data:
        print("FAIL", name)
        continue
    out = OUT / f"{name}.png"
    out.write_bytes(data)
    print("OK  ", name, out)


