"""
Final economic audit before merge - optimized version.
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


def simulate_economy(days, players=2_000, use_floor=True):
    reset_global_stats()
    init_global_stats()

    fissures = [0.1] * players
    histories = [[] for _ in range(players)]
    initial = [0.1] * players

    snapshots = []
    for day in range(days):
        stats = get_global_stats_snapshot()
        for i in range(players):
            total_rolls = len(histories[i])
            roll = _simulate_roll(fissures[i], histories[i], stats, total_rolls=total_rolls)
            if use_floor:
                fissures[i] = max(0.1, fissures[i] + roll)
            else:
                fissures[i] = fissures[i] + roll
            histories[i].append(roll)
            record_player_roll(i, roll)
            update_global_stats_on_event("roll", roll_value=roll)

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
    return snapshots, growths, fissures


def simulate_newbie_long_term(players=2_000, days=180):
    reset_global_stats()
    init_global_stats()

    newbie_fissures = [0.1] * players
    normal_fissures = [0.1] * players
    newbie_histories = [[] for _ in range(players)]
    normal_histories = [[] for _ in range(players)]

    for day in range(days):
        stats = get_global_stats_snapshot()
        for i in range(players):
            nr = _simulate_roll(newbie_fissures[i], newbie_histories[i], stats, len(newbie_histories[i]))
            newbie_fissures[i] = max(0.1, newbie_fissures[i] + nr)
            newbie_histories[i].append(nr)
            record_player_roll(i, nr)
            update_global_stats_on_event("roll", roll_value=nr)

            tr = _simulate_roll(normal_fissures[i], normal_histories[i], stats, 100 + len(normal_histories[i]))
            normal_fissures[i] = max(0.1, normal_fissures[i] + tr)
            normal_histories[i].append(tr)
            record_player_roll(i + 100_000, tr)
            update_global_stats_on_event("roll", roll_value=tr)

    return newbie_fissures, normal_fissures


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
    print("FINAL ECONOMIC AUDIT BEFORE MERGE")
    print("=" * 70)

    # 1. Floor = 0.1 effect
    print("\n" + "=" * 70)
    print("1. FLOOR = 0.1 EFFECT")
    print("=" * 70)

    for days in [180, 365]:
        snaps, growths, _ = simulate_economy(days, players=2_000, use_floor=True)
        print_snapshots(snaps, f"Floor=0.1, {days} days")
        print_growth_table(growths, f"Growth after {days} days")

    # 2. No-floor comparison
    print("\n" + "=" * 70)
    print("2. NO-FLOOR COMPARISON")
    print("=" * 70)

    for days in [180, 365]:
        snaps, growths, _ = simulate_economy(days, players=2_000, use_floor=False)
        print_snapshots(snaps, f"No floor, {days} days")
        print_growth_table(growths, f"Growth after {days} days (no floor)")

    # 3. Real game economy
    print("\n" + "=" * 70)
    print("3. REAL GAME ECONOMY")
    print("=" * 70)

    for days in [30, 90, 180, 365]:
        _, growths, _ = simulate_economy(days, players=2_000, use_floor=True)
        print_growth_table(growths, f"Growth after {days} days")

    # 4. Newbie long-term
    print("\n" + "=" * 70)
    print("4. NEWBIE LONG-TERM IMPACT")
    print("=" * 70)

    newbie_fissures, normal_fissures = simulate_newbie_long_term(players=2_000, days=180)
    print(f"\n  After 180 days (2k players):")
    print(f"  {'Metric':<20} {'Newbie':>10} {'Normal':>10} {'Ratio':>10}")
    print(f"  {'Mean':<20} {sum(newbie_fissures)/len(newbie_fissures):>10.1f} {sum(normal_fissures)/len(normal_fissures):>10.1f} {sum(newbie_fissures)/len(newbie_fissures)/max(sum(normal_fissures)/len(normal_fissures),0.1):>10.2f}x")
    print(f"  {'Median':<20} {_percentile(newbie_fissures,50):>10.1f} {_percentile(normal_fissures,50):>10.1f}")
    print(f"  {'p90':<20} {_percentile(newbie_fissures,90):>10.1f} {_percentile(normal_fissures,90):>10.1f}")
    print(f"  {'p99':<20} {_percentile(newbie_fissures,99):>10.1f} {_percentile(normal_fissures,99):>10.1f}")
    print(f"  {'Max':<20} {max(newbie_fissures):>10.1f} {max(normal_fissures):>10.1f}")

    print("\n" + "=" * 70)
    print("FINAL VERDICT")
    print("=" * 70)
