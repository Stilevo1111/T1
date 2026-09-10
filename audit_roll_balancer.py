#!/usr/bin/env python3
"""
Production RollBalancer Audit Script
Generates 1,000,000 roll simulations for various fissure states.
"""

import random
import math
from collections import deque, Counter
from typing import Optional

MIN_MODIFIER = 0.1
MAX_MODIFIER = 8.0

NEW_PLAYER_MAX_ROLLS = 12
BAD_STREAK_THRESHOLD = -12
BAD_STREAK_LOOKBACK = 8
BAD_STREAK_MAX_BOOST = 1.35
GOOD_STREAK_THRESHOLD = 15
GOOD_STREAK_LOOKBACK = 8
GOOD_STREAK_MIN_PENALTY = 0.6
EXTREME_VALUE_PITY_START = 40
EXTREME_VALUE_PITY_MAX_ADD = 2.5
EXTREME_PITY_PER_ROLL = 0.04


class GlobalRollStats:
    def __init__(self):
        self.total_rolls = 0
        self.histogram = {}
        self.last_techies_rolls_ago = 0
        self.last_extreme_positive_ago = 0
        self.last_extreme_negative_ago = 0


def base_weight(value: int, spread: int) -> float:
    if spread <= 0:
        return 1.0
    distance = abs(value) / spread
    return math.exp(-3.0 * distance * distance)


def anti_streak_modifier(history: deque, value: float) -> float:
    if not history:
        return 1.0
    streak = 0
    for past in reversed(history):
        if past == value:
            streak += 1
        else:
            break
    if streak == 0:
        return 1.0
    return max(MIN_MODIFIER, 0.6 ** streak)


def bad_streak_protection(history: deque, value: float) -> float:
    if value <= 0:
        return 1.0
    recent = list(history)[-BAD_STREAK_LOOKBACK:] if len(history) >= BAD_STREAK_LOOKBACK else list(history)
    if not recent:
        return 1.0
    recent_sum = sum(recent)
    if recent_sum < BAD_STREAK_THRESHOLD:
        boost = 1.0 + min(BAD_STREAK_MAX_BOOST - 1.0, abs(recent_sum) / 30.0)
        return min(MAX_MODIFIER, boost)
    return 1.0


def good_streak_smoothing(history: deque, value: float) -> float:
    if value <= 0:
        return 1.0
    recent = list(history)[-GOOD_STREAK_LOOKBACK:] if len(history) >= GOOD_STREAK_LOOKBACK else list(history)
    if not recent:
        return 1.0
    recent_sum = sum(recent)
    if recent_sum > GOOD_STREAK_THRESHOLD:
        penalty = max(GOOD_STREAK_MIN_PENALTY, 1.0 - (recent_sum - GOOD_STREAK_THRESHOLD) / 60.0)
        return penalty
    return 1.0


def new_player_modifier(total_rolls: int, value: float) -> float:
    if total_rolls > NEW_PLAYER_MAX_ROLLS:
        return 1.0

    abs_val = abs(value)
    if value <= 0:
        base_reduce = 0.7 if total_rolls <= NEW_PLAYER_HIGH_BOOST_ROLLS else (
            0.8 if total_rolls <= NEW_PLAYER_MEDIUM_BOOST_ROLLS else 0.9
        )
        extra = 0.25 * min(1.0, abs_val / 5.0)
        return base_reduce + extra * (1.0 - base_reduce)
    else:
        base_boost = 0.35 if total_rolls <= NEW_PLAYER_HIGH_BOOST_ROLLS else (
            0.18 if total_rolls <= NEW_PLAYER_MEDIUM_BOOST_ROLLS else 0.08
        )
        magnitude_factor = max(0.4, 1.0 - 0.15 * max(0, abs_val - 1))
        extra = base_boost * magnitude_factor
        return 1.0 + extra


NEW_PLAYER_HIGH_BOOST_ROLLS = 3
NEW_PLAYER_MEDIUM_BOOST_ROLLS = 6


def low_fissure_modifier(current_fissure: float, value: float) -> float:
    if value <= 0:
        return 1.0
    if current_fissure < 1.0:
        return 1.35
    elif current_fissure < 5.0:
        return 1.25
    return 1.0


def player_balance_modifier(history: deque, value: float) -> float:
    return bad_streak_protection(history, value) * good_streak_smoothing(history, value)


def global_balance_modifier(stats: GlobalRollStats, value: float) -> float:
    total = stats.total_rolls
    if total < 200:
        return 1.0
    count = stats.histogram.get(str(int(value)), 0)
    expected = total / 20.0
    ratio = count / max(expected, 1.0)
    if ratio > 2.0:
        return max(MIN_MODIFIER, 1.0 - (ratio - 2.0) * 0.15)
    elif ratio < 0.3:
        return min(MAX_MODIFIER, 1.0 + (0.3 - ratio) * 0.4)
    return 1.0


def pity_modifier(stats: GlobalRollStats, value: float) -> float:
    abs_val = abs(value)
    if abs_val < 10:
        return 1.0

    if value > 0:
        rolls_ago = stats.last_extreme_positive_ago
    else:
        rolls_ago = stats.last_extreme_negative_ago

    if rolls_ago < EXTREME_VALUE_PITY_START:
        return 1.0

    pity = min(EXTREME_VALUE_PITY_MAX_ADD, (rolls_ago - EXTREME_VALUE_PITY_START) * EXTREME_PITY_PER_ROLL)
    return 1.0 + pity


def compute_final_weight(
    value: int,
    spread: int,
    history: deque,
    stats: GlobalRollStats,
    total_rolls: int,
    current_fissure: float,
) -> float:
    w = base_weight(value, spread)
    w *= anti_streak_modifier(history, value)
    w *= player_balance_modifier(history, value)
    w *= new_player_modifier(total_rolls, value)
    w *= low_fissure_modifier(current_fissure, value)
    w *= global_balance_modifier(stats, value)
    w *= pity_modifier(stats, value)
    return max(MIN_MODIFIER, min(MAX_MODIFIER, w))


def select_roll(
    spread: int,
    history: deque,
    stats: GlobalRollStats,
    total_rolls: int,
    current_fissure: float,
    negative_max: Optional[int] = None,
    positive_max: Optional[int] = None,
) -> int:
    if negative_max is None:
        negative_max = -spread
    if positive_max is None:
        positive_max = spread

    candidates = [v for v in range(negative_max, positive_max + 1) if v != 0]
    weights = []
    for v in candidates:
        w = compute_final_weight(v, spread, history, stats, total_rolls, current_fissure)
        weights.append(w)

    selected = random.choices(candidates, weights=weights, k=1)[0]

    if selected == 0:
        selected = random.choice([-1, 1])

    return selected


def calculate_spread(current_fissure: float) -> int:
    return min(50, max(5, int(current_fissure * 0.35)))


def calculate_negative_max(current_fissure: float, spread: int) -> int:
    if current_fissure < 10:
        return -max(1, min(spread, int(current_fissure)))
    return -spread


def run_simulation(fissure: float, n_rolls: int = 1_000_000, disable_all: bool = True) -> dict:
    spread = calculate_spread(fissure)
    negative_max = calculate_negative_max(fissure, spread)
    positive_max = spread

    results = []
    history = deque(maxlen=20)
    stats = GlobalRollStats()

    for i in range(n_rolls):
        if disable_all:
            candidates = [v for v in range(negative_max, positive_max + 1) if v != 0]
            weights = [1.0] * len(candidates)
            selected = random.choices(candidates, weights=weights, k=1)[0]
        else:
            selected = select_roll(
                spread=spread,
                history=history,
                stats=stats,
                total_rolls=i,
                current_fissure=fissure,
                negative_max=negative_max,
                positive_max=positive_max,
            )

        if selected == 0:
            selected = random.choice([-1, 1])

        results.append(selected)
        history.append(selected)
        stats.total_rolls += 1

    return {
        "results": results,
        "spread": spread,
        "negative_max": negative_max,
        "positive_max": positive_max,
    }


def compute_stats(results: list) -> dict:
    n = len(results)
    sorted_results = sorted(results)

    mean = sum(results) / n
    counter = Counter(results)
    median = sorted_results[n // 2]

    p10_idx = int(n * 0.10)
    p50_idx = int(n * 0.50)
    p90_idx = int(n * 0.90)
    p99_idx = int(n * 0.99)

    positive = sum(1 for r in results if r > 0)
    negative = sum(1 for r in results if r < 0)
    zero = sum(1 for r in results if r == 0)

    max_val = max(results)
    min_val = min(results)

    most_common = counter.most_common(5)

    pos_20_plus = sum(1 for r in results if r >= 20)
    neg_20_minus = sum(1 for r in results if r <= -20)

    return {
        "mean": mean,
        "median": median,
        "p10": sorted_results[p10_idx],
        "p50": sorted_results[p50_idx],
        "p90": sorted_results[p90_idx],
        "p99": sorted_results[p99_idx],
        "positive_pct": positive / n * 100,
        "negative_pct": negative / n * 100,
        "zero_pct": zero / n * 100,
        "min": min_val,
        "max": max_val,
        "most_common": most_common,
        "pos_20_plus_pct": pos_20_plus / n * 100,
        "neg_20_minus_pct": neg_20_minus / n * 100,
    }


def print_distribution_details(results: list, limit: int = 101):
    counter = Counter(results)
    sorted_keys = sorted(counter.keys())

    print("\nDetailed Value Distribution:")
    print("=" * 50)
    print(f"{'Value':>8} | {'Count':>10} | {'Probability %':>15}")
    print("-" * 50)

    for v in sorted_keys:
        count = counter[v]
        prob = count / len(results) * 100
        print(f"{v:>8} | {count:>10} | {prob:>15.6f}")


def check_range_breach(results: list, expected_min: int, expected_max: int):
    within = sum(1 for r in results if expected_min <= r <= expected_max)
    outside = len(results) - within
    print(f"\nRange Check: [{expected_min}, {expected_max}]")
    print(f"  Within range: {within}/{len(results)} ({within/len(results)*100:.2f}%)")
    print(f"  Outside range: {outside}/{len(results)} ({outside/len(results)*100:.2f}%)")


FISSURE_VALUES = [0.1, 1, 5, 10, 20, 50, 100, 150]

print("=" * 80)
print("BASELINE ROLLBALANCER AUDIT (All Dynamics Disabled)")
print("=" * 80)
print("\nRunning 1,000,000 rolls per fissure value...")

baseline_results = {}

for fissure in FISSURE_VALUES:
    print(f"\nSimulating fissure={fissure}...")
    sim = run_simulation(fissure, 1_000_000, disable_all=True)
    stats = compute_stats(sim["results"])
    baseline_results[fissure] = {"sim": sim, "stats": stats}

    print(f"\n  Spread: {sim['spread']}")
    print(f"  Range: [{sim['negative_max']}, {sim['positive_max']}]")
    print(f"  Mean (E[roll]): {stats['mean']:.6f}")
    print(f"  Median: {stats['median']}")
    print(f"  P10: {stats['p10']}")
    print(f"  P50: {stats['p50']}")
    print(f"  P90: {stats['p90']}")
    print(f"  P99: {stats['p99']}")
    print(f"  Min: {stats['min']}, Max: {stats['max']}")
    print(f"  Positive: {stats['positive_pct']:.2f}%, Negative: {stats['negative_pct']:.2f}%, Zero: {stats['zero_pct']:.2f}%")


print("\n" + "=" * 80)
print("SUMMARY TABLE (Baseline - All Dynamics Disabled)")
print("=" * 80)
print(f"{'Fissure':>8} | {'Spread':>6} | {'Raw EV':>10} | {'Pos %':>8} | {'Neg %':>8} | {'P50':>5} | {'P90':>5}")
print("-" * 80)
for fissure in FISSURE_VALUES:
    stats = baseline_results[fissure]["stats"]
    sim = baseline_results[fissure]["sim"]
    print(f"{fissure:>8.1f} | {sim['spread']:>6} | {stats['mean']:>10.6f} | {stats['positive_pct']:>7.2f}% | {stats['negative_pct']:>7.2f}% | {stats['p50']:>5} | {stats['p90']:>5}")


print("\n" + "=" * 80)
print("RANGE VERIFICATION")
print("=" * 80)
for fissure in FISSURE_VALUES:
    sim = baseline_results[fissure]["sim"]
    results = sim["results"]
    print(f"\nFissure {fissure}:")
    print(f"  Expected range: [{sim['negative_max']}, {sim['positive_max']}]")
    print(f"  Actual range: [{min(results)}, {max(results)}]")
    check_range_breach(results, sim['negative_max'], sim['positive_max'])


print("\n" + "=" * 80)
print("DETAILED DISTRIBUTION (Selected Fissure Values)")
print("=" * 80)

for fissure in [0.1, 1, 10, 100]:
    sim = baseline_results[fissure]["sim"]
    results = sim["results"]
    print(f"\n--- Fissure: {fissure} ---")
    print_distribution_details(results)


print("\n" + "=" * 80)
print("FLOOR HIT ANALYSIS")
print("=" * 80)

for fissure in [0.1, 1, 5, 10]:
    sim = baseline_results[fissure]["sim"]
    results = sim["results"]
    floor = sim['negative_max']
    hits = sum(1 for r in results if r == floor)
    print(f"Fissure {fissure}: Floor ({floor}) hit {hits}/{len(results)} ({hits/len(results)*100:.4f}%)")


print("\n" + "=" * 80)
print("HIGH/LOW FISSURE SPECIFIC ANALYSIS")
print("=" * 80)

print("\n--- Fissure 0.1 ---")
sim = baseline_results[0.1]["sim"]
results = sim["results"]
positive = sum(1 for r in results if r > 0)
print(f"Possible roll values: {sorted(set([r for r in results if r > 0]))}")
print(f"Positive %: {positive/len(results)*100:.4f}%")
print(f"Rolls at +1: {sum(1 for r in results if r == 1)/len(results)*100:.4f}%")

print("\n--- Fissure 1 ---")
sim = baseline_results[1]["sim"]
results = sim["results"]
positive = sum(1 for r in results if r > 0)
print(f"Possible roll values: {sorted(set(results))}")
print(f"Positive %: {positive/len(results)*100:.4f}%")
print(f"Rolls at +1: {sum(1 for r in results if r == 1)/len(results)*100:.4f}%")

print("\n--- Fissure 100 ---")
sim = baseline_results[100]["sim"]
results = sim["results"]
pos_20 = sum(1 for r in results if r >= 20)
neg_20 = sum(1 for r in results if r <= -20)
print(f"Max positive roll: {max(results)}")
print(f"Max negative roll: {min(results)}")
print(f"P(roll >= +20): {pos_20/len(results)*100:.4f}%")
print(f"P(roll <= -20): {neg_20/len(results)*100:.4f}%")

print("\n" + "=" * 80)
print("FINAL SUMMARY TABLE")
print("=" * 80)
print(f"{'Fissure':>8} | {'Raw EV':>12} | {'Final EV':>12} | {'Positive %':>12} | {'Negative %':>12} | {'Floor Hit %':>12}")
print("-" * 80)
for fissure in FISSURE_VALUES:
    stats = baseline_results[fissure]["stats"]
    sim = baseline_results[fissure]["sim"]
    floor_hits = sum(1 for r in sim["results"] if r == sim["negative_max"])
    floor_pct = floor_hits / len(sim["results"]) * 100
    print(f"{fissure:>8.1f} | {stats['mean']:>12.6f} | {stats['mean']:>12.6f} | {stats['positive_pct']:>11.2f}% | {stats['negative_pct']:>11.2f}% | {floor_pct:>11.4f}%")

print("\n" + "=" * 80)
print("ANALYSIS COMPLETE")
print("=" * 80)