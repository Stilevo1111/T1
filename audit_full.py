#!/usr/bin/env python3
"""
Production RollBalancer Audit - With Dynamics Enabled
"""

import random
import math
from collections import deque, Counter
from typing import Optional

MIN_MODIFIER = 0.1
MAX_MODIFIER = 8.0

NEW_PLAYER_HIGH_BOOST_ROLLS = 3
NEW_PLAYER_MEDIUM_BOOST_ROLLS = 6
BAD_STREAK_THRESHOLD = -12
BAD_STREAK_LOOKBACK = 8
BAD_STREAK_MAX_BOOST = 1.35
GOOD_STREAK_THRESHOLD = 15
GOOD_STREAK_LOOKBACK = 8
GOOD_STREAK_MIN_PENALTY = 0.6
EXTREME_VALUE_PITY_START = 40
EXTREME_VALUE_PITY_MAX_ADD = 2.5
EXTREME_PITY_PER_ROLL = 0.04

NEW_PLAYER_MAX_ROLLS = 12


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
    enable_new_player: bool = True,
    enable_low_fissure: bool = True,
    enable_global_balance: bool = True,
    enable_pity: bool = True,
    enable_streak: bool = True,
) -> int:
    if negative_max is None:
        negative_max = -spread
    if positive_max is None:
        positive_max = spread

    candidates = [v for v in range(negative_max, positive_max + 1) if v != 0]
    weights = []
    for v in candidates:
        w = base_weight(v, spread)
        
        if enable_streak:
            w *= anti_streak_modifier(history, v)
            w *= player_balance_modifier(history, v)
        
        if enable_new_player:
            w *= new_player_modifier(total_rolls, v)
        
        if enable_low_fissure:
            w *= low_fissure_modifier(current_fissure, v)
        
        if enable_global_balance and stats.total_rolls >= 200:
            w *= global_balance_modifier(stats, v)
        
        if enable_pity:
            w *= pity_modifier(stats, v)
        
        w = max(MIN_MODIFIER, min(MAX_MODIFIER, w))
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
        "most_common": counter.most_common(5),
    }


FISSURE_VALUES = [0.1, 1, 5, 10, 20, 50, 100, 150]


def run_full_audit(fissure: float, n_rolls: int = 1_000_000):
    spread = calculate_spread(fissure)
    negative_max = calculate_negative_max(fissure, spread)
    positive_max = spread

    print(f"\n{'='*80}")
    print(f"FISSURE = {fissure} | Spread = {spread} | Range = [{negative_max}, {positive_max}]")
    print("=" * 80)

    results_baseline = []
    results_streak = []
    results_pity = []
    results_newbie = []
    results_lowfi = []
    results_global = []
    results_all = []

    history_baseline = deque(maxlen=20)
    history_streak = deque(maxlen=20)
    history_pity = deque(maxlen=20)
    history_newbie = deque(maxlen=20)
    history_lowfi = deque(maxlen=20)
    history_global = deque(maxlen=20)
    history_all = deque(maxlen=20)

    stats_baseline = GlobalRollStats()
    stats_streak = GlobalRollStats()
    stats_pity = GlobalRollStats()
    stats_newbie = GlobalRollStats()
    stats_lowfi = GlobalRollStats()
    stats_global = GlobalRollStats()
    stats_all = GlobalRollStats()

    for i in range(n_rolls):
        candidates = [v for v in range(negative_max, positive_max + 1) if v != 0]
        weights = [1.0] * len(candidates)
        selected = random.choices(candidates, weights=weights, k=1)[0]
        if selected == 0:
            selected = random.choice([-1, 1])
        results_baseline.append(selected)

        selected = select_roll(
            spread=spread, history=history_streak, stats=stats_streak,
            total_rolls=len(results_streak), current_fissure=fissure,
            negative_max=negative_max, positive_max=positive_max,
            enable_new_player=True, enable_low_fissure=True, enable_global_balance=True,
            enable_pity=True, enable_streak=True
        )
        if selected == 0:
            selected = random.choice([-1, 1])
        results_streak.append(selected)
        history_streak.append(selected)
        stats_streak.total_rolls += 1

        selected = select_roll(
            spread=spread, history=history_pity, stats=stats_pity,
            total_rolls=len(results_pity), current_fissure=fissure,
            negative_max=negative_max, positive_max=positive_max,
            enable_new_player=True, enable_low_fissure=True, enable_global_balance=True,
            enable_pity=True, enable_streak=False
        )
        if selected == 0:
            selected = random.choice([-1, 1])
        results_pity.append(selected)
        history_pity.append(selected)
        stats_pity.total_rolls += 1

        selected = select_roll(
            spread=spread, history=history_newbie, stats=stats_newbie,
            total_rolls=len(results_newbie), current_fissure=fissure,
            negative_max=negative_max, positive_max=positive_max,
            enable_new_player=False, enable_low_fissure=True, enable_global_balance=True,
            enable_pity=True, enable_streak=True
        )
        if selected == 0:
            selected = random.choice([-1, 1])
        results_newbie.append(selected)
        history_newbie.append(selected)
        stats_newbie.total_rolls += 1

        selected = select_roll(
            spread=spread, history=history_lowfi, stats=stats_lowfi,
            total_rolls=len(results_lowfi), current_fissure=fissure,
            negative_max=negative_max, positive_max=positive_max,
            enable_new_player=True, enable_low_fissure=False, enable_global_balance=True,
            enable_pity=True, enable_streak=True
        )
        if selected == 0:
            selected = random.choice([-1, 1])
        results_lowfi.append(selected)
        history_lowfi.append(selected)
        stats_lowfi.total_rolls += 1

        selected = select_roll(
            spread=spread, history=history_global, stats=stats_global,
            total_rolls=len(results_global), current_fissure=fissure,
            negative_max=negative_max, positive_max=positive_max,
            enable_new_player=True, enable_low_fissure=True, enable_global_balance=False,
            enable_pity=True, enable_streak=True
        )
        if selected == 0:
            selected = random.choice([-1, 1])
        results_global.append(selected)
        history_global.append(selected)
        stats_global.total_rolls += 1

        selected = select_roll(
            spread=spread, history=history_all, stats=stats_all,
            total_rolls=len(results_all), current_fissure=fissure,
            negative_max=negative_max, positive_max=positive_max,
            enable_new_player=True, enable_low_fissure=True, enable_global_balance=True,
            enable_pity=True, enable_streak=True
        )
        if selected == 0:
            selected = random.choice([-1, 1])
        results_all.append(selected)
        history_all.append(selected)
        stats_all.total_rolls += 1

    return {
        "baseline": results_baseline,
        "all": results_all,
        "streak": results_streak,
        "pity": results_pity,
        "newbie": results_newbie,
        "lowfi": results_lowfi,
        "global": results_global,
    }


print("Loading...")

print("\n" + "=" * 80)
print("FULL ROLLBALANCER AUDIT - 1,000,000 rolls per fissure")
print("="*80)

FINAL_DATA = []

for fissure in FISSURE_VALUES:
    data = run_full_audit(fissure, 1_000_000)
    
    stats_baseline = compute_stats(data["baseline"])
    stats_all = compute_stats(data["all"])
    stats_streak = compute_stats(data["streak"])
    stats_pity = compute_stats(data["pity"])
    stats_newbie = compute_stats(data["newbie"])
    stats_lowfi = compute_stats(data["lowfi"])
    stats_global = compute_stats(data["global"])

    FINAL_DATA.append({
        "fissure": fissure,
        "baseline": stats_baseline,
        "all": stats_all,
        "streak": stats_streak,
        "pity": stats_pity,
        "newbie": stats_newbie,
        "lowfi": stats_lowfi,
        "global": stats_global,
    })

    print(f"\n{'='*80}")
    print(f"FISSURE = {fissure}")
    print("=" * 80)
    print(f"\n{'Scenario':<20} | {'EV':>10} | {'Pos %':>8} | {'Neg %':>8} | {'P50':>5} | {'P90':>5} | {'P99':>5}")
    print("-" * 80)
    print(f"{'BASELINE (uniform)':<20} | {stats_baseline['mean']:>10.4f} | {stats_baseline['positive_pct']:>7.2f}% | {stats_baseline['negative_pct']:>7.2f}% | {stats_baseline['p50']:>5} | {stats_baseline['p90']:>5} | {stats_baseline['p99']:>5}")
    print(f"{'ALL MECHANICS':<20} | {stats_all['mean']:>10.4f} | {stats_all['positive_pct']:>7.2f}% | {stats_all['negative_pct']:>7.2f}% | {stats_all['p50']:>5} | {stats_all['p90']:>5} | {stats_all['p99']:>5}")
    print(f"{'- anti-streak':<20} | {stats_streak['mean']:>10.4f} | {stats_streak['positive_pct']:>7.2f}% | {stats_streak['negative_pct']:>7.2f}% | {stats_streak['p50']:>5} | {stats_streak['p90']:>5} | {stats_streak['p99']:>5}")
    print(f"{'+ pity':<18} | {stats_pity['mean']:>10.4f} | {stats_pity['positive_pct']:>7.2f}% | {stats_pity['negative_pct']:>7.2f}% | {stats_pity['p50']:>5} | {stats_pity['p90']:>5} | {stats_pity['p99']:>5}")
    print(f"{'+ newbie':<18} | {stats_newbie['mean']:>10.4f} | {stats_newbie['positive_pct']:>7.2f}% | {stats_newbie['negative_pct']:>7.2f}% | {stats_newbie['p50']:>5} | {stats_newbie['p90']:>5} | {stats_newbie['p99']:>5}")
    print(f"{'+ low-fissure':<18} | {stats_lowfi['mean']:>10.4f} | {stats_lowfi['positive_pct']:>7.2f}% | {stats_lowfi['negative_pct']:>7.2f}% | {stats_lowfi['p50']:>5} | {stats_lowfi['p90']:>5} | {stats_lowfi['p99']:>5}")
    print(f"{'+ global balance':<18} | {stats_global['mean']:>10.4f} | {stats_global['positive_pct']:>7.2f}% | {stats_global['negative_pct']:>7.2f}% | {stats_global['p50']:>5} | {stats_global['p90']:>5} | {stats_global['p99']:>5}")

print("\n" + "=" * 80)
print("FINAL SUMMARY TABLE")
print("=" * 80)
print(f"{'Fissure':>8} | {'Baseline EV':>12} | {'Final EV':>12} | {'Pos %':>10} | {'Neg %':>10} | {'P50':>5}")
print("-" * 80)
for d in FINAL_DATA:
    print(f"{d['fissure']:>8.1f} | {d['baseline']['mean']:>12.6f} | {d['all']['mean']:>12.6f} | {d['all']['positive_pct']:>9.2f}% | {d['all']['negative_pct']:>9.2f}% | {d['all']['p50']:>5}")


print("\n" + "=" * 80)
print("FLOOR HIT ANALYSIS")
print("=" * 80)
for f in FISSURE_VALUES[:4]:
    d = next(x for x in FINAL_DATA if x['fissure'] == f)
    spread = min(50, max(5, int(f * 0.35)))
    neg_max = -max(1, min(spread, int(f))) if f < 10 else -spread
    floor = neg_max
    data = d['all']
    results = data['baseline']
    
    floor_hits = sum(1 for r in results if r == floor)
    
    print(f"\nFissure {f}: Floor ({floor})")
    print(f"  Floor hit: {floor_hits}/1,000,000 ({floor_hits/10000:.2f}%)")