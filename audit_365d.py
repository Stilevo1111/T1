#!/usr/bin/env python3
"""
365-day economic simulation.
Models fissure evolution for many players under real /fissure flow with cooldown and events.
Outputs distribution metrics at the end.
"""

import random
import math
from collections import deque

random.seed(42)

# ===== Exact production pieces =====
MIN_MODIFIER = 0.1
MAX_MODIFIER = 8.0
BAD_STREAK_THRESHOLD = -12
BAD_STREAK_LOOKBACK = 8
BAD_STREAK_MAX_BOOST = 1.35
GOOD_STREAK_THRESHOLD = 15
GOOD_STREAK_LOOKBACK = 8
GOOD_STREAK_MIN_PENALTY = 0.6
EXTREME_VALUE_PITY_START = 40
EXTREME_PITY_PER_ROLL = 0.04
NEW_PLAYER_MAX_ROLLS = 12
NEW_PLAYER_HIGH_BOOST_ROLLS = 3
NEW_PLAYER_MEDIUM_BOOST_ROLLS = 6
COOLDOWN_SECONDS = 24 * 60 * 60
SIMULATION_DAYS = 365


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
    base_boost = 0.35 if total_rolls <= NEW_PLAYER_HIGH_BOOST_ROLLS else (
        0.18 if total_rolls <= NEW_PLAYER_MEDIUM_BOOST_ROLLS else 0.08
    )
    magnitude_factor = max(0.4, 1.0 - 0.15 * max(0, abs_val - 1))
    return 1.0 + base_boost * magnitude_factor


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
    pity = min(2.5, (rolls_ago - EXTREME_VALUE_PITY_START) * EXTREME_PITY_PER_ROLL)
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
    negative_max: int,
    positive_max: int,
) -> int:
    candidates = [v for v in range(negative_max, positive_max + 1) if v != 0]
    weights = []
    for v in candidates:
        w = compute_final_weight(v, spread, history, stats, total_rolls, current_fissure)
        weights.append(w)

    selected = random.choices(candidates, weights=weights, k=1)[0]

    if selected == 0:
        selected = random.choice([-1, 1])

    return selected


def calc_spread(current_fissure: float) -> int:
    return min(50, max(5, int(current_fissure * 0.35)))


def calc_negative_max(current_fissure: float, spread: int) -> int:
    if current_fissure < 10:
        return -max(1, min(spread, int(current_fissure)))
    return -spread


def calculate_fissure_roll(
    current_fissure: float,
    history: deque,
    stats: GlobalRollStats,
    total_rolls: int,
) -> int:
    spread = calc_spread(current_fissure)
    negative_max = calc_negative_max(current_fissure, spread)
    positive_max = spread

    history_deque = history if isinstance(history, deque) else deque(history, maxlen=20)

    roll = select_roll(
        spread=spread,
        history=history_deque,
        stats=stats,
        total_rolls=total_rolls,
        current_fissure=current_fissure,
        negative_max=negative_max,
        positive_max=positive_max,
    )

    if roll == 0:
        roll = random.choice([-1, 1])

    return roll


def apply_protection(current_fissure: float, roll: int) -> int:
    if roll <= -10 and current_fissure < 5:
        return max(-5, roll)
    return roll


def clamp_fissure(new_value: float) -> float:
    if new_value < 0.1:
        return 0.1
    return new_value


class Player:
    __slots__ = ("id", "fissure", "last_fissure_time", "total_rolls", "history")

    def __init__(self, player_id: int):
        self.id = player_id
        self.fissure = 0.1
        self.last_fissure_time = 0.0
        self.total_rolls = 0
        self.history = deque(maxlen=20)


# ===== Simulation =====

def run_simulation(n_players: int, n_days: int):
    players = [Player(i) for i in range(n_players)]
    global_stats = GlobalRollStats()

    # Event probabilities per production rules
    zeus_chance = 0.01
    techies_chance = 0.05
    multicast_chance = 0.10

    # Time stepping: each step = 1 day
    # Players roll when cooldown expired; with daily stepping most will roll every day.
    for day in range(n_days):
        day_ts = day * COOLDOWN_SECONDS
        for p in players:
            if day_ts - p.last_fissure_time >= COOLDOWN_SECONDS:
                p.last_fissure_time = day_ts
                p.total_rolls += 1

                event_roll = random.random()
                if event_roll < zeus_chance:
                    affected = 0
                    total_cm = 0.0
                    for q in players:
                        if q.id != p.id:
                            reduction = q.fissure * 0.025
                            q.fissure = clamp_fissure(q.fissure - reduction)
                            affected += 1
                            total_cm += reduction
                    p.fissure = clamp_fissure(p.fissure * 0.975)
                    continue

                if event_roll < zeus_chance + techies_chance:
                    damage = random.randint(1, 5)
                    p.fissure = clamp_fissure(p.fissure - damage)
                    continue

                is_multicast = event_roll < zeus_chance + techies_chance + multicast_chance
                if is_multicast:
                    cascade_count = random.choices(
                        [1, 2, 3, 4],
                        weights=[0.25, 0.50, 0.20, 0.05],
                        k=1,
                    )[0]
                else:
                    cascade_count = 1

                roll = calculate_fissure_roll(
                    current_fissure=p.fissure,
                    history=p.history,
                    stats=global_stats,
                    total_rolls=p.total_rolls,
                )

                if is_multicast:
                    roll = roll * cascade_count

                roll = apply_protection(p.fissure, roll)
                p.fissure = clamp_fissure(p.fissure + roll)
                p.history.append(roll)

                global_stats.total_rolls += 1
                if abs(roll) >= 10:
                    if roll > 0:
                        global_stats.last_extreme_positive_ago = 0
                    else:
                        global_stats.last_extreme_negative_ago = 0
                else:
                    global_stats.last_extreme_positive_ago += 1
                    global_stats.last_extreme_negative_ago += 1

    return players


def percentile(sorted_values, p):
    if not sorted_values:
        return 0.0
    idx = int(len(sorted_values) * p)
    idx = min(idx, len(sorted_values) - 1)
    return sorted_values[idx]


def summarize(players):
    values = [p.fissure for p in players]
    values.sort()
    n = len(values)
    total = sum(values)

    def pct(p):
        return percentile(values, p)

    def count_at_most(limit):
        return sum(1 for v in values if v <= limit)

    def count_at_least(limit):
        return sum(1 for v in values if v >= limit)

    return {
        "players": n,
        "mean": total / n,
        "median": pct(0.5),
        "p10": pct(0.10),
        "p90": pct(0.90),
        "p95": pct(0.95),
        "p99": pct(0.99),
        "pmax": values[-1],
        "leq_0_1": count_at_most(0.1 + 1e-9),
        "leq_1": count_at_most(1.0 + 1e-9),
        "geq_5": count_at_least(5.0 - 1e-9),
        "geq_10": count_at_least(10.0 - 1e-9),
        "geq_20": count_at_least(20.0 - 1e-9),
        "geq_50": count_at_least(50.0 - 1e-9),
        "geq_100": count_at_least(100.0 - 1e-9),
        "stuck_at_floor": count_at_most(0.11),
    }


if __name__ == "__main__":
    print(f"Running 365-day simulation for 100,000 players...")
    players = run_simulation(n_players=100000, n_days=SIMULATION_DAYS)
    stats = summarize(players)

    print("\nFinal fissure distribution:")
    print(f"  Players: {stats['players']}")
    print(f"  Mean: {stats['mean']:.2f} cm")
    print(f"  Median: {stats['median']:.2f} cm")
    print(f"  P10: {stats['p10']:.2f} cm")
    print(f"  P90: {stats['p90']:.2f} cm")
    print(f"  P95: {stats['p95']:.2f} cm")
    print(f"  P99: {stats['p99']:.2f} cm")
    print(f"  Max: {stats['pmax']:.2f} cm")
    print(f"  Stuck at floor (<=0.11): {stats['stuck_at_floor']} ({stats['stuck_at_floor']/stats['players']*100:.2f}%)")
    print(f"  <= 1 cm: {stats['leq_1']} ({stats['leq_1']/stats['players']*100:.2f}%)")
    print(f"  >= 5 cm: {stats['geq_5']} ({stats['geq_5']/stats['players']*100:.2f}%)")
    print(f"  >= 10 cm: {stats['geq_10']} ({stats['geq_10']/stats['players']*100:.2f}%)")
    print(f"  >= 20 cm: {stats['geq_20']} ({stats['geq_20']/stats['players']*100:.2f}%)")
    print(f"  >= 50 cm: {stats['geq_50']} ({stats['geq_50']/stats['players']*100:.2f}%)")
    print(f"  >= 100 cm: {stats['geq_100']} ({stats['geq_100']/stats['players']*100:.2f}%)")
