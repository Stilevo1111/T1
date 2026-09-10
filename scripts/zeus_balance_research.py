"""
Zeus balance research - optimized version.
"""

from __future__ import annotations

import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from roll_balancer import (
    GlobalRollStats,
    get_global_stats_snapshot,
    init_global_stats,
    record_player_roll,
    reset_global_stats,
    select_roll,
    update_global_stats_on_event,
)
from collections import deque

random.seed(42)

MULTICAST_CHANCE = 0.15
ZEUS_CHANCE = 0.10
TECHIES_CHANCE = 0.15

X2_THRESHOLD = 0.75
X3_THRESHOLD = 0.25
X4_THRESHOLD = 0.15

TECHIES_SUCCESS_RATE = 2/3
TECHIES_MINES = 4
TECHIES_MINE_MIN = 1
TECHIES_MINE_MAX = 10


def _simulate_roll(fissure, history, global_stats, total_rolls=0):
    spread = min(50, max(5, int(fissure * 0.35)))
    neg_max = -max(1, min(spread, int(fissure))) if fissure < 10 else -spread
    h = deque(history, maxlen=20)
    roll, _ = select_roll(
        spread=spread,
        history=h,
        stats=global_stats,
        total_rolls=total_rolls,
        current_fissure=fissure,
        negative_max=neg_max,
        positive_max=spread,
    )
    if roll == 0:
        roll = random.choice([-1, 1])
    return roll


def _percentile(data, p):
    if not data:
        return 0
    s = sorted(data)
    idx = int(len(s) * p / 100)
    return s[min(idx, len(s) - 1)]


def simulate_economy(days, players=100, zeus_config=None):
    reset_global_stats()
    init_global_stats()

    fissures = [0.1] * players
    histories = [[] for _ in range(players)]
    initial = [0.1] * players

    zeus_total_damage = 0.0
    zeus_events = 0
    zeus_victims_total = 0

    for day in range(days):
        stats = get_global_stats_snapshot()
        for i in range(players):
            total_rolls = len(histories[i])
            event_roll = random.random()

            if event_roll < ZEUS_CHANCE:
                zeus_events += 1
                if zeus_config and zeus_config.get('type') != 'current':
                    ztype = zeus_config['type']
                    if ztype == 'A':
                        percent = zeus_config.get('percent', 0.01)
                        for j in range(players):
                            if j != i and fissures[j] > 0.1:
                                old = fissures[j]
                                fissures[j] = max(0.1, fissures[j] * (1 - percent))
                                zeus_total_damage += old - fissures[j]
                                zeus_victims_total += 1
                    elif ztype == 'B':
                        active = sum(1 for f in fissures if f > 0.1)
                        base_p = zeus_config.get('base_percent', 0.015)
                        max_p = zeus_config.get('max_percent', 0.035)
                        scale = zeus_config.get('scale', 0.00005)
                        percent = min(max_p, base_p + (active - 2) * scale)
                        for j in range(players):
                            if j != i and fissures[j] > 0.1:
                                old = fissures[j]
                                fissures[j] = max(0.1, fissures[j] * (1 - percent))
                                zeus_total_damage += old - fissures[j]
                                zeus_victims_total += 1
                    elif ztype == 'C':
                        percent = zeus_config.get('percent', 0.02)
                        max_victims = zeus_config.get('max_victims', 20)
                        candidates = [j for j in range(players) if j != i and fissures[j] > 0.1]
                        if candidates:
                            victims = random.sample(candidates, min(max_victims, len(candidates)))
                            for j in victims:
                                old = fissures[j]
                                fissures[j] = max(0.1, fissures[j] * (1 - percent))
                                zeus_total_damage += old - fissures[j]
                                zeus_victims_total += 1
                    elif ztype == 'D':
                        budget = zeus_config.get('budget_per_zeus', 50.0)
                        candidates = [(j, fissures[j]) for j in range(players) if j != i and fissures[j] > 0.1]
                        if candidates:
                            total_f = sum(f for _, f in candidates)
                            for j, f in candidates:
                                share = f / total_f if total_f > 0 else 1 / len(candidates)
                                damage = budget * share
                                old = fissures[j]
                                fissures[j] = max(0.1, fissures[j] - damage)
                                zeus_total_damage += old - fissures[j]
                                zeus_victims_total += 1
                    elif ztype == 'E':
                        percent = zeus_config.get('percent', 0.015)
                        max_victims = zeus_config.get('max_victims', 15)
                        candidates = [j for j in range(players) if j != i and fissures[j] > 0.1]
                        if candidates:
                            victims = candidates[:max_victims] if len(candidates) > max_victims else candidates
                            for j in victims:
                                old = fissures[j]
                                fissures[j] = max(0.1, fissures[j] * (1 - percent))
                                zeus_total_damage += old - fissures[j]
                                zeus_victims_total += 1
                else:
                    for j in range(players):
                        if j != i and fissures[j] > 0.1:
                            old = fissures[j]
                            fissures[j] = max(0.1, fissures[j] * 0.975)
                            zeus_total_damage += old - fissures[j]
                            zeus_victims_total += 1
                update_global_stats_on_event(event_type="zeus")
                continue

            if event_roll < ZEUS_CHANCE + TECHIES_CHANCE:
                if random.random() < TECHIES_SUCCESS_RATE:
                    pass
                else:
                    total_damage = sum(random.randint(TECHIES_MINE_MIN, TECHIES_MINE_MAX) for _ in range(TECHIES_MINES))
                    fissures[i] = max(0.1, fissures[i] - total_damage)
                update_global_stats_on_event(event_type="techies")
                continue

            roll = _simulate_roll(fissures[i], histories[i], stats, total_rolls=total_rolls)

            if event_roll < ZEUS_CHANCE + TECHIES_CHANCE + MULTICAST_CHANCE:
                cascade_count = 1
                x2 = random.random()
                if x2 < X2_THRESHOLD:
                    cascade_count = 2
                    x3 = random.random()
                    if x3 < X3_THRESHOLD:
                        cascade_count = 3
                        x4 = random.random()
                        if x4 < X4_THRESHOLD:
                            cascade_count = 4
                roll = roll * cascade_count
            fissures[i] = max(0.1, fissures[i] + roll)
            histories[i].append(roll)
            record_player_roll(i, roll)
            update_global_stats_on_event(event_type="roll", roll_value=roll)

    growths = [f - i for f, i in zip(fissures, initial)]
    return growths, {
        "zeus_events": zeus_events,
        "zeus_total_damage": zeus_total_damage,
        "zeus_victims_total": zeus_victims_total,
        "zeus_avg_damage_per_event": zeus_total_damage / max(zeus_events, 1),
        "zeus_avg_damage_per_victim": zeus_total_damage / max(zeus_victims_total, 1),
        "zeus_events_per_day": zeus_events / max(days, 1),
    }


if __name__ == "__main__":
    print("=" * 70)
    print("ZEUS BALANCE RESEARCH")
    print("=" * 70)

    zeus_configs = [
        ("CURRENT", {"type": "current"}),
        ("OPTION A (-1%)", {"type": "A", "percent": 0.01}),
        ("OPTION B (diminishing)", {"type": "B", "base_percent": 0.015, "max_percent": 0.035, "scale": 0.00005}),
        ("OPTION C (cap 20 victims)", {"type": "C", "percent": 0.02, "max_victims": 20}),
        ("OPTION D (fixed budget 50cm)", {"type": "D", "budget_per_zeus": 50.0}),
        ("OPTION E (-1.5% + cap 15)", {"type": "E", "percent": 0.015, "max_victims": 15}),
    ]

    player_counts = [10, 50, 100, 500, 1000, 5000]
    days_list = [180, 365]

    for days in days_list:
        print(f"\n{'='*70}")
        print(f"PERIOD: {days} DAYS")
        print(f"{'='*70}")

        for players in player_counts:
            print(f"\n--- Players: {players} ---")
            for name, config in zeus_configs:
                growths, stats = simulate_economy(days, players=players, zeus_config=config)
                mean_growth = sum(growths) / len(growths)
                p99_growth = _percentile(growths, 99)
                gt100 = sum(1 for g in growths if g > 100) / len(growths) * 100
                zeus_damage_per_event = stats.get('zeus_avg_damage_per_event', 0)
                zeus_events = stats.get('zeus_events', 0)
                zeus_victims = stats.get('zeus_victims_total', 0)
                print(f"  {name:<25}: mean={mean_growth:>7.1f}, p99={p99_growth:>7.1f}, >100={gt100:>5.2f}%, zeus_dmg={zeus_damage_per_event:>6.1f}, victims={zeus_victims:>6}")

    print("\n" + "=" * 70)
    print("ANALYSIS COMPLETE")
    print("=" * 70)
