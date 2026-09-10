"""
Full economic audit with ALL mechanics included.

Simulates:
- Normal roll (60%)
- Multicast (15%) with cascade x1-x4
- Zeus (10%) - global -2.5% to all except triggerer
- Techies (15%) - user-specific mini-game
- Cooldown: 1 action per day per user
- Floor = 0.1

Compares:
A) Base economy (normal rolls only)
B) Full economy (all mechanics)
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

# Event chances from constants.py
MULTICAST_CHANCE = 0.15
ZEUS_CHANCE = 0.10
TECHIES_CHANCE = 0.15

# Multicast cascade probabilities
X2_THRESHOLD = 0.75
X3_THRESHOLD = 0.25
X4_THRESHOLD = 0.15

# Techies
TECHIES_SUCCESS_RATE = 2/3  # 2 out of 3 buttons are safe
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


def simulate_economy(days, players=2_000, include_specials=True):
    reset_global_stats()
    init_global_stats()

    fissures = [0.1] * players
    histories = [[] for _ in range(players)]
    initial = [0.1] * players

    # Track special event contributions
    zeus_hits = 0
    techies_hits = 0
    multicast_hits = 0
    normal_hits = 0
    total_actions = 0

    snapshots = []
    for day in range(days):
        stats = get_global_stats_snapshot()
        for i in range(players):
            total_rolls = len(histories[i])
            event_roll = random.random()

            if include_specials and event_roll < ZEUS_CHANCE:
                # Zeus: -2.5% to ALL except triggerer
                zeus_hits += 1
                total_actions += 1
                for j in range(players):
                    if j != i and fissures[j] > 0.1:
                        reduction = fissures[j] * 0.025
                        fissures[j] = max(0.1, fissures[j] - reduction)
                update_global_stats_on_event(event_type="zeus")
                continue

            if include_specials and event_roll < ZEUS_CHANCE + TECHIES_CHANCE:
                # Techies
                techies_hits += 1
                total_actions += 1
                if random.random() < TECHIES_SUCCESS_RATE:
                    # Success: no change
                    pass
                else:
                    # Failure: lose sum of 4 mines (1-10 each)
                    total_damage = sum(random.randint(TECHIES_MINE_MIN, TECHIES_MINE_MAX) for _ in range(TECHIES_MINES))
                    fissures[i] = max(0.1, fissures[i] - total_damage)
                update_global_stats_on_event(event_type="techies")
                continue

            # Roll event (normal or multicast)
            roll = _simulate_roll(fissures[i], histories[i], stats, total_rolls=total_rolls)

            if include_specials and event_roll < ZEUS_CHANCE + TECHIES_CHANCE + MULTICAST_CHANCE:
                # Multicast
                multicast_hits += 1
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
            else:
                normal_hits += 1

            total_actions += 1
            fissures[i] = max(0.1, fissures[i] + roll)
            histories[i].append(roll)
            record_player_roll(i, roll)
            update_global_stats_on_event(event_type="roll", roll_value=roll)

        if day % 30 == 0 or day == days - 1:
            vals = sorted(fissures)
            n = len(vals)
            snapshots.append({
                "day": day,
                "mean": sum(vals) / n,
                "median": vals[n // 2],
                "p90": vals[9 * n // 10],
                "p95": vals[95 * n // 100],
                "p99": vals[99 * n // 100],
                "max": max(vals),
                "stuck_0.1": sum(1 for v in vals if v <= 0.1) / n * 100,
                "gt_10": sum(1 for v in vals if v > 10) / n * 100,
                "gt_50": sum(1 for v in vals if v > 50) / n * 100,
                "gt_100": sum(1 for v in vals if v > 100) / n * 100,
                "gt_200": sum(1 for v in vals if v > 200) / n * 100,
                "gt_500": sum(1 for v in vals if v > 500) / n * 100,
            })

    growths = [f - i for f, i in zip(fissures, initial)]
    return snapshots, growths, fissures, {
        "zeus_hits": zeus_hits,
        "techies_hits": techies_hits,
        "multicast_hits": multicast_hits,
        "normal_hits": normal_hits,
        "total_actions": total_actions,
    }


def print_snapshots(snapshots, label):
    print(f"\n=== {label} ===")
    print(f"{'Day':<6} {'Mean':>8} {'Median':>8} {'p90':>8} {'p95':>8} {'p99':>8} {'Max':>8} {'0.1%':>8} {'>10%':>8} {'>50%':>8} {'>100%':>8}")
    for s in snapshots:
        print(f"{s['day']:<6} {s['mean']:>8.1f} {s['median']:>8.1f} {s['p90']:>8.1f} {s['p95']:>8.1f} {s['p99']:>8.1f} {s['max']:>8.1f} {s['stuck_0.1']:>7.2f}% {s['gt_10']:>7.2f}% {s['gt_50']:>7.2f}% {s['gt_100']:>7.2f}%")


def print_growth_table(growths, label):
    g = sorted(growths)
    n = len(g)
    print(f"\n  {label}")
    print(f"    Mean: {sum(g)/n:.1f}")
    print(f"    Median: {g[n//2]:.1f}")
    print(f"    p10: {g[n//10]:.1f}")
    print(f"    p90: {g[9*n//10]:.1f}")
    print(f"    p99: {g[99*n//100]:.1f}")
    print(f"    Max: {max(g):.1f}")


if __name__ == "__main__":
    print("=" * 70)
    print("FULL ECONOMIC AUDIT WITH ALL MECHANICS")
    print("=" * 70)

    # 1. Base economy (normal rolls only)
    print("\n" + "=" * 70)
    print("A) BASE ECONOMY (NORMAL ROLLS ONLY)")
    print("=" * 70)

    for days in [30, 90, 180, 365]:
        snaps, growths, _, _ = simulate_economy(days, players=2_000, include_specials=False)
        print_snapshots(snaps, f"Base, {days} days")
        print_growth_table(growths, f"Growth after {days} days")

    # 2. Full economy (all mechanics)
    print("\n" + "=" * 70)
    print("B) FULL ECONOMY (ALL MECHANICS)")
    print("=" * 70)

    for days in [30, 90, 180, 365]:
        snaps, growths, _, stats = simulate_economy(days, players=2_000, include_specials=True)
        print_snapshots(snaps, f"Full, {days} days")
        print_growth_table(growths, f"Growth after {days} days")
        print(f"\n  Event stats for {days} days:")
        print(f"    Zeus: {stats['zeus_hits']} ({stats['zeus_hits']/max(stats['total_actions'],1)*100:.1f}%)")
        print(f"    Techies: {stats['techies_hits']} ({stats['techies_hits']/max(stats['total_actions'],1)*100:.1f}%)")
        print(f"    Multicast: {stats['multicast_hits']} ({stats['multicast_hits']/max(stats['total_actions'],1)*100:.1f}%)")
        print(f"    Normal: {stats['normal_hits']} ({stats['normal_hits']/max(stats['total_actions'],1)*100:.1f}%)")

    # 3. Direct comparison
    print("\n" + "=" * 70)
    print("C) COMPARISON: FULL vs BASE")
    print("=" * 70)

    for days in [180, 365]:
        _, base_growths, _, _ = simulate_economy(days, players=2_000, include_specials=False)
        _, full_growths, _, _ = simulate_economy(days, players=2_000, include_specials=True)

        base_mean = sum(base_growths) / len(base_growths)
        full_mean = sum(full_growths) / len(full_growths)
        delta = full_mean - base_mean

        base_p99 = _percentile(base_growths, 99)
        full_p99 = _percentile(full_growths, 99)
        p99_delta = full_p99 - base_p99

        base_gt100 = sum(1 for g in base_growths if g > 100) / len(base_growths) * 100
        full_gt100 = sum(1 for g in full_growths if g > 100) / len(full_growths) * 100

        base_gt500 = sum(1 for g in base_growths if g > 500) / len(base_growths) * 100
        full_gt500 = sum(1 for g in full_growths if g > 500) / len(full_growths) * 100

        print(f"\n  {days} days:")
        print(f"    Base mean: {base_mean:.1f}, Full mean: {full_mean:.1f}, Delta: {delta:+.1f}")
        print(f"    Base p99: {base_p99:.1f}, Full p99: {full_p99:.1f}, Delta: {p99_delta:+.1f}")
        print(f"    Base >100: {base_gt100:.2f}%, Full >100: {full_gt100:.2f}%, Delta: {full_gt100-base_gt100:+.2f}%")
        print(f"    Base >500: {base_gt500:.2f}%, Full >500: {full_gt500:.2f}%, Delta: {full_gt500-base_gt500:+.2f}%")

    print("\n" + "=" * 70)
    print("VERDICT")
    print("=" * 70)
