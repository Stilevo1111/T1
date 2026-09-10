"""
Fast second-pass audit for roll_balancer coefficients.
"""

from __future__ import annotations

import os
import random
import sys
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from roll_balancer import (
    GlobalRollStats,
    anti_streak_modifier,
    bad_streak_protection,
    compute_final_weight,
    get_global_stats_snapshot,
    get_techies_chance,
    global_balance_modifier,
    good_streak_smoothing,
    init_global_stats,
    low_fissure_modifier,
    new_player_modifier,
    pity_modifier,
    record_player_roll,
    reset_global_stats,
    select_roll,
    update_global_stats_on_event,
)
from collections import deque

random.seed(42)


def _simulate_roll(fissure, history, global_stats, total_rolls=0):
    spread = min(50, max(5, int(fissure * 0.35)))
    if fissure < 10:
        neg_max = -max(1, min(spread, int(fissure)))
    else:
        neg_max = -spread

    history_deque = deque(history, maxlen=20)
    roll, _ = select_roll(
        spread=spread,
        history=history_deque,
        stats=global_stats,
        total_rolls=total_rolls,
        current_fissure=fissure,
        negative_max=neg_max,
        positive_max=spread,
    )
    if roll == 0:
        roll = random.choice([-1, 1])
    return roll


def audit_bad_streak():
    print("\n" + "=" * 60)
    print("1. BAD-STREAK PROTECTION AUDIT")
    print("=" * 60)

    scenarios = [
        ("light", [-3, -1, -2]),
        ("medium", [-5, -3, -1]),
        ("heavy", [-5, -5, -3, -3, -1, -5]),
        ("extreme", [-5, -5, -5, -5, -5, -5, -5]),
    ]

    random.seed(42)
    for name, hist in scenarios:
        reset_global_stats()
        init_global_stats()
        fissure = 0.1
        for v in hist:
            fissure = max(0.1, fissure + v)

        stats = get_global_stats_snapshot()
        positives = 0
        roll_values = []
        fixed_total_rolls = len(hist)
        for _ in range(5000):
            roll = _simulate_roll(fissure, hist, stats, total_rolls=fixed_total_rolls)
            if roll > 0:
                positives += 1
            fissure = max(0.1, fissure + roll)
            hist.append(roll)
            record_player_roll(999, roll)
            update_global_stats_on_event("roll", roll_value=roll)
            stats = get_global_stats_snapshot()
            roll_values.append(roll)

        print(f"\n  Scenario '{name}' (sum={sum(hist[:len(hist)-5000]) if len(hist)>5000 else sum(hist)}):")
        print(f"    Positive rolls: {positives}/5000 = {positives/50:.1f}%")
        print(f"    Mean roll: {sum(roll_values)/len(roll_values):.3f}")
        print(f"    Max roll: {max(roll_values)}")
        print(f"    Min roll: {min(roll_values)}")


def audit_new_player_bonus():
    print("\n" + "=" * 60)
    print("2. NEW PLAYER BONUS AUDIT")
    print("=" * 60)

    random.seed(42)
    milestones = [5, 10, 20, 50, 100]

    for milestone in milestones:
        reset_global_stats()
        init_global_stats()

        results = []
        for p in range(10_000):
            hist = []
            fissure = 0.1
            for i in range(milestone):
                stats = get_global_stats_snapshot()
                roll = _simulate_roll(fissure, hist, stats, total_rolls=i)
                fissure = max(0.1, fissure + roll)
                hist.append(roll)
                record_player_roll(p + 1, roll)
                update_global_stats_on_event("roll", roll_value=roll)
            results.append(fissure)

        results.sort()
        n = len(results)
        print(f"\n  After {milestone} rolls (10k players):")
        print(f"    Median: {results[n//2]:.1f}")
        print(f"    Mean: {sum(results)/n:.1f}")
        print(f"    p25: {results[n//4]:.1f}")
        print(f"    p75: {results[3*n//4]:.1f}")
        print(f"    p90: {results[9*n//10]:.1f}")
        print(f"    Stuck at 0.1: {sum(1 for r in results if r <= 0.1)/n*100:.1f}%")
        print(f"    >5 cm: {sum(1 for r in results if r > 5)/n*100:.1f}%")
        print(f"    >10 cm: {sum(1 for r in results if r > 10)/n*100:.1f}%")
        print(f"    >20 cm: {sum(1 for r in results if r > 20)/n*100:.1f}%")
        print(f"    >50 cm: {sum(1 for r in results if r > 50)/n*100:.1f}%")


def audit_newbie_vs_normal():
    print("\n" + "=" * 60)
    print("3. NEWBIE VS NORMAL PLAYER COMPARISON")
    print("=" * 60)

    random.seed(42)
    milestones = [5, 10, 20, 50, 100]

    for milestone in milestones:
        reset_global_stats()
        init_global_stats()

        newbie_results = []
        normal_results = []

        for p in range(10_000):
            newbie_hist = []
            normal_hist = []
            newbie_fissure = 0.1
            normal_fissure = 0.1

            for i in range(milestone):
                stats = get_global_stats_snapshot()

                newbie_roll = _simulate_roll(newbie_fissure, newbie_hist, stats, total_rolls=i)
                newbie_fissure = max(0.1, newbie_fissure + newbie_roll)
                newbie_hist.append(newbie_roll)
                record_player_roll(p + 1, newbie_roll)
                update_global_stats_on_event("roll", roll_value=newbie_roll)

                normal_roll = _simulate_roll(normal_fissure, normal_hist, stats, total_rolls=100 + i)
                normal_fissure = max(0.1, normal_fissure + normal_roll)
                normal_hist.append(normal_roll)
                record_player_roll(p + 100001, normal_roll)
                update_global_stats_on_event("roll", roll_value=normal_roll)

            newbie_results.append(newbie_fissure)
            normal_results.append(normal_fissure)

        newbie_mean = sum(newbie_results) / len(newbie_results)
        normal_mean = sum(normal_results) / len(normal_results)
        print(f"\n  After {milestone} rolls:")
        print(f"    Newbie mean: {newbie_mean:.1f}, Normal mean: {normal_mean:.1f}")
        print(f"    Ratio: {newbie_mean/max(normal_mean, 0.1):.2f}x")


def audit_long_term_economy():
    print("\n" + "=" * 60)
    print("4. LONG-TERM ECONOMY (180 days, 10k players)")
    print("=" * 60)

    random.seed(42)
    reset_global_stats()
    init_global_stats()

    fissures = [0.1] * 10_000
    histories = [[] for _ in range(10_000)]

    for day in range(180):
        stats = get_global_stats_snapshot()
        for i in range(10_000):
            total_rolls = len(histories[i])
            roll = _simulate_roll(fissures[i], histories[i], stats, total_rolls=total_rolls)
            fissures[i] = max(0.1, fissures[i] + roll)
            histories[i].append(roll)
            record_player_roll(i, roll)
            update_global_stats_on_event("roll", roll_value=roll)

        if day % 30 == 0:
            current_vals = sorted(fissures)
            n = len(current_vals)
            print(f"\n  Day {day}:")
            print(f"    Mean: {sum(current_vals)/n:.1f}")
            print(f"    Median: {current_vals[n//2]:.1f}")
            print(f"    p90: {current_vals[9*n//10]:.1f}")
            print(f"    p99: {current_vals[99*n//100]:.1f}")
            print(f"    Max: {max(current_vals):.1f}")
            print(f"    Stuck at 0.1: {sum(1 for v in current_vals if v <= 0.1)/n*100:.2f}%")
            print(f"    >100: {sum(1 for v in current_vals if v > 100)/n*100:.2f}%")

    final = sorted(fissures)
    n = len(final)
    print(f"\n  Final (day 180):")
    print(f"    Mean: {sum(final)/n:.1f}")
    print(f"    Median: {final[n//2]:.1f}")
    print(f"    p90: {final[9*n//10]:.1f}")
    print(f"    p99: {final[99*n//100]:.1f}")
    print(f"    Max: {max(final):.1f}")
    print(f"    Stuck at 0.1: {sum(1 for v in final if v <= 0.1)/n*100:.2f}%")
    print(f"    >100: {sum(1 for v in final if v > 100)/n*100:.2f}%")


def audit_techies_pity():
    print("\n" + "=" * 60)
    print("5. TECHIES PITY PERCENTILES")
    print("=" * 60)

    random.seed(42)
    reset_global_stats()
    init_global_stats()

    gaps = []
    current_gap = 0
    pity_activated = 0

    for i in range(100_000):
        event_roll = random.random()
        techies_chance = get_techies_chance()
        if techies_chance > 0.15:
            pity_activated += 1
        if event_roll < 0.10:
            current_gap += 1
            continue
        elif event_roll < 0.10 + techies_chance:
            gaps.append(current_gap)
            update_global_stats_on_event("techies")
            current_gap = 0
        else:
            current_gap += 1
            update_global_stats_on_event("roll", roll_value=1)

    if not gaps:
        gaps = [0]

    gaps.sort()
    n = len(gaps)
    print(f"  Total events: 100000")
    print(f"  Techies count: {n}")
    print(f"  Pity activated: {pity_activated} times")
    print(f"  Mean gap: {sum(gaps)/n:.1f}")
    print(f"  Median gap: {gaps[n//2]:.1f}")
    print(f"  p95 gap: {gaps[95*n//100]:.1f}")
    print(f"  p99 gap: {gaps[99*n//100]:.1f}")
    print(f"  Max gap: {max(gaps)}")
    print(f"  Gaps > 100: {sum(1 for g in gaps if g > 100)}")
    print(f"  Gaps > 200: {sum(1 for g in gaps if g > 200)}")


def audit_anti_streak():
    print("\n" + "=" * 60)
    print("6. ANTI-STREAK DISTRIBUTION")
    print("=" * 60)

    random.seed(42)
    for target in [1, 3, 5, 10]:
        streaks = []
        current_streak = 0
        last = None

        for _ in range(20_000):
            history = deque([last] if last is not None else [], maxlen=20)
            stats = GlobalRollStats()
            roll, _ = select_roll(10, history, stats, 0, 0.1)
            if roll == 0:
                roll = random.choice([-1, 1])

            if roll == target:
                if last == target:
                    current_streak += 1
                else:
                    current_streak = 1
            else:
                current_streak = 0
            last = roll
            streaks.append(current_streak)

        c = Counter(streaks)
        total = len(streaks)
        print(f"\n  Target value: {target}")
        print(f"    Max streak: {max(streaks)}")
        print(f"    p95 streak: {sorted(streaks)[95*total//100]}")
        print(f"    p99 streak: {sorted(streaks)[99*total//100]}")
        print(f"    Distribution (top 10): {dict(sorted(c.items(), key=lambda x: x[0], reverse=True)[:10])}")


def audit_global_balance():
    print("\n" + "=" * 60)
    print("7. GLOBAL BALANCE OSCILLATION TEST")
    print("=" * 60)

    random.seed(42)
    reset_global_stats()
    init_global_stats()

    history = []

    for i in range(20_000):
        fissure = max(0.1, 10 + sum(history[-50:]) if history else 10)
        stats = get_global_stats_snapshot()
        roll = _simulate_roll(fissure, history, stats, total_rolls=i)
        history.append(roll)
        record_player_roll(0, roll)
        update_global_stats_on_event("roll", roll_value=roll)

    stats = get_global_stats_snapshot()
    total = stats.total_rolls
    print(f"\n  After 20000 rolls:")
    print(f"  {'Value':<6} {'Count':<8} {'Expected':<10} {'Ratio':<8} {'Modifier':<10}")
    for v in range(-10, 11):
        if v == 0:
            continue
        count = stats.histogram.get(str(v), 0)
        expected = total / 20
        ratio = count / max(expected, 1)
        mod = global_balance_modifier(stats, v)
        print(f"  {v:<6} {count:<8} {expected:<10.0f} {ratio:<8.2f} {mod:<10.3f}")


def audit_expected_value():
    print("\n" + "=" * 60)
    print("8. EXPECTED VALUE PER ROLL")
    print("=" * 60)

    random.seed(42)
    scenarios = [
        ("newbie_rolls_1_5", 3, 0.1),
        ("newbie_rolls_6_10", 8, 2.0),
        ("newbie_rolls_11_20", 15, 5.0),
        ("normal_low_fissure", 100, 0.5),
        ("normal_mid_fissure", 100, 5.0),
        ("normal_high_fissure", 100, 50.0),
        ("bad_streak", 100, 0.1),
    ]

    for name, total_rolls, fissure in scenarios:
        reset_global_stats()
        init_global_stats()
        history = []
        if name == "bad_streak":
            history = [-5, -5, -3, -3, -1, -5]
            for v in history:
                fissure = max(0.1, fissure + v)

        values = []
        for _ in range(5000):
            stats = get_global_stats_snapshot()
            roll = _simulate_roll(fissure, history, stats, total_rolls=total_rolls)
            values.append(roll)

        pos = [v for v in values if v > 0]
        neg = [v for v in values if v < 0]
        print(f"\n  {name}:")
        print(f"    Mean: {sum(values)/len(values):.4f}")
        print(f"    Positive%: {len(pos)/len(values)*100:.1f}%, mean={sum(pos)/max(len(pos),1):.2f}")
        print(f"    Negative%: {len(neg)/len(values)*100:.1f}%, mean={sum(neg)/max(len(neg),1):.2f}")


if __name__ == "__main__":
    audit_bad_streak()
    audit_new_player_bonus()
    audit_newbie_vs_normal()
    audit_long_term_economy()
    audit_techies_pity()
    audit_anti_streak()
    audit_global_balance()
    audit_expected_value()
