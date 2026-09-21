#!/usr/bin/env python3
"""One-shot preview: two /profile variants from dota_mmr.generate_profile_card.

Exports:
  profile_full.png     — со стимом (герои + награды)
  profile_no_steam.png — без стима (как /start: ник + "ВСЕГО СООБЩЕНИЙ" + награды)
"""

import io
import os
import sys
from pathlib import Path

HERE = Path(__file__).parent
BOT_DIR = HERE  # .kilo/worktrees/hero-avatar-fix

if str(BOT_DIR) not in sys.path:
    sys.path.insert(0, str(BOT_DIR))

from dota_mmr import generate_profile_card

OUT = HERE / "profile_mockups" / "out"
OUT.mkdir(parents=True, exist_ok=True)


def main() -> None:
    p1 = generate_profile_card(
        username="seredin999",
        steam_nickname="Seredin",
        mmr=5000,
        rank_tier=55,
        fissure=0.5,
        total_rolls=12000,
        weekly_rolls=300,
        current_streak=12,
        best_streak=12,
        message_count=5000,
        week_games=10,
        week_wins=8,
        dota_total_games=500,
        dota_wins=300,
        top_heroes=[{"name": "Pudge", "short_name": "pudge"}],
        award_counts={"weekly_mvp": 2},
    )
    assert p1, "profile_full.png generation failed"
    (OUT / "profile_full.png").write_bytes(p1)

    p2 = generate_profile_card(
        username="newbie",
        steam_nickname=None,
        mmr=0,
        rank_tier=0,
        fissure=0.0,
        total_rolls=0,
        weekly_rolls=0,
        current_streak=0,
        best_streak=0,
        message_count=100,
        week_games=0,
        week_wins=0,
        dota_total_games=0,
        dota_wins=0,
        top_heroes=None,
    )
    assert p2, "profile_no_steam.png generation failed"
    (OUT / "profile_no_steam.png").write_bytes(p2)

    print(f"Wrote {OUT / 'profile_full.png'} ({len(p1)} bytes) and "
          f"{OUT / 'profile_no_steam.png'} ({len(p2)} bytes)")


if __name__ == "__main__":
    main()
