#!/usr/bin/env python3
"""
CURRENT vs V1 balance comparison.
"""

import random
import math
import time
from collections import deque
from dataclasses import dataclass

random.seed(42)

# =====================
# Shared constants
# =====================
FATAL_ROLL = -10
COOLDOWN_SECONDS = 24 * 60 * 60
SIMULATION_DAYS = 365

ZEUS_CHANCE = 0.10
TECHIES_CHANCE = 0.15
MULTICAST_CHANCE = 0.15
WEEKEND_BONUS_MULTIPLIERS = [1.5, 2.0]

MIN_MODIFIER = 0.1
MAX_MODIFIER = 8.0
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
NEW_PLAYER_HIGH_BOOST_ROLLS = 3
NEW_PLAYER_MEDIUM_BOOST_ROLLS = 6
TECHIES_BASE_CHANCE = 0.15
TECHIES_PITY_START = 35
TECHIES_PITY_MAX_ADD = 0.25
TECHIES_CHANCE_CAP = 0.40


@dataclass
class GlobalRollStats:
    total_rolls: int = 0
    histogram: dict = None
    last_techies_rolls_ago: int = 0
    last_extreme_positive_ago: int = 0
    last_extreme_negative_ago: int = 0

    def __post_init__(self):
        if self.histogram is None:
            self.histogram = {}


def base_weight(value: int, spread: int, concentration: float = 3.0) -> float:
    if spread <= 0:
        return 1.0
    distance = abs(value) / spread
    return math.exp(-concentration * distance * distance)


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


def new_player_modifier(total_rolls: int, value: float, positive_boost: float = 0.35, negative_boost: float = 0.70) -> float:
    if total_rolls > NEW_PLAYER_MAX_ROLLS:
        return 1.0
    abs_val = abs(value)
    if value <= 0:
        base_reduce = negative_boost if total_rolls <= NEW_PLAYER_HIGH_BOOST_ROLLS else (
            0.8 if total_rolls <= NEW_PLAYER_MEDIUM_BOOST_ROLLS else 0.9
        )
        extra = 0.25 * min(1.0, abs_val / 5.0)
        return base_reduce + extra * (1.0 - base_reduce)
    base_boost = positive_boost if total_rolls <= NEW_PLAYER_HIGH_BOOST_ROLLS else (
        0.18 if total_rolls <= NEW_PLAYER_MEDIUM_BOOST_ROLLS else 0.08
    )
    magnitude_factor = max(0.4, 1.0 - 0.15 * max(0, abs_val - 1))
    return 1.0 + base_boost * magnitude_factor


def low_fissure_modifier(current_fissure: float, value: float, low_high: float = 1.35, low_mid: float = 1.25) -> float:
    if value <= 0:
        return 1.0
    if current_fissure < 1.0:
        return low_high
    elif current_fissure < 5.0:
        return low_mid
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


def pity_modifier(stats: GlobalRollStats, value: float, pity_start: int = EXTREME_VALUE_PITY_START) -> float:
    abs_val = abs(value)
    if abs_val < 10:
        return 1.0
    if value > 0:
        rolls_ago = stats.last_extreme_positive_ago
    else:
        rolls_ago = stats.last_extreme_negative_ago
    if rolls_ago < pity_start:
        return 1.0
    pity = min(EXTREME_VALUE_PITY_MAX_ADD, (rolls_ago - pity_start) * EXTREME_PITY_PER_ROLL)
    return 1.0 + pity


def compute_final_weight(
    value: int,
    spread: int,
    history: deque,
    stats: GlobalRollStats,
    total_rolls: int,
    current_fissure: float,
    *,
    concentration: float = 3.0,
    low_high: float = 1.35,
    low_mid: float = 1.25,
    pity_start: int = EXTREME_VALUE_PITY_START,
    positive_boost: float = 0.35,
    negative_boost: float = 0.70,
) -> float:
    w = base_weight(value, spread, concentration)
    w *= anti_streak_modifier(history, value)
    w *= player_balance_modifier(history, value)
    w *= new_player_modifier(total_rolls, value, positive_boost=positive_boost, negative_boost=negative_boost)
    w *= low_fissure_modifier(current_fissure, value, low_high=low_high, low_mid=low_mid)
    w *= global_balance_modifier(stats, value)
    w *= pity_modifier(stats, value, pity_start=pity_start)
    return max(MIN_MODIFIER, min(MAX_MODIFIER, w))


def select_roll(
    spread: int,
    history: deque,
    stats: GlobalRollStats,
    total_rolls: int,
    current_fissure: float,
    negative_max: int,
    positive_max: int,
    *,
    concentration: float = 3.0,
    low_high: float = 1.35,
    low_mid: float = 1.25,
    pity_start: int = EXTREME_VALUE_PITY_START,
    positive_boost: float = 0.35,
    negative_boost: float = 0.70,
) -> int:
    candidates = [v for v in range(negative_max, positive_max + 1) if v != 0]
    weights = []
    for v in candidates:
        w = compute_final_weight(
            v,
            spread,
            history,
            stats,
            total_rolls,
            current_fissure,
            concentration=concentration,
            low_high=low_high,
            low_mid=low_mid,
            pity_start=pity_start,
            positive_boost=positive_boost,
            negative_boost=negative_boost,
        )
        weights.append(w)
    selected = random.choices(candidates, weights=weights, k=1)[0]
    if selected == 0:
        selected = random.choice([-1, 1])
    return selected


def calc_spread(current_fissure: float) -> int:
    return min(50, max(5, int(current_fissure * 0.35)))


def calc_negative_max(current_fissure: float, spread: int, equal_negative: bool = False) -> int:
    if equal_negative:
        return -spread
    if current_fissure < 10:
        return -max(1, min(spread, int(current_fissure)))
    return -spread


def calculate_fissure_roll(
    current_fissure: float,
    history: deque,
    stats: GlobalRollStats,
    total_rolls: int,
    *,
    concentration: float = 3.0,
    low_high: float = 1.35,
    low_mid: float = 1.25,
    pity_start: int = EXTREME_VALUE_PITY_START,
    positive_boost: float = 0.35,
    negative_boost: float = 0.70,
    equal_negative: bool = False,
) -> int:
    spread = calc_spread(current_fissure)
    negative_max = calc_negative_max(current_fissure, spread, equal_negative=equal_negative)
    positive_max = spread
    roll = select_roll(
        spread,
        history,
        stats,
        total_rolls,
        current_fissure,
        negative_max,
        positive_max,
        concentration=concentration,
        low_high=low_high,
        low_mid=low_mid,
        pity_start=pity_start,
        positive_boost=positive_boost,
        negative_boost=negative_boost,
    )
    if roll == 0:
        roll = random.choice([-1, 1])
    return roll


def apply_fissure_protection(current_fissure: float, roll: int) -> int:
    if roll <= FATAL_ROLL and current_fissure < 5:
        return max(-5, roll)
    return roll


def calculate_new_fissure(current_fissure: float, roll: int) -> float:
    new_value = current_fissure + roll
    if new_value < 0.1:
        return 0.1
    return new_value


def calculate_streak_bonus(current_win_streak: int, base_roll: int, streak_cap: int = 5) -> tuple[int, str]:
    if current_win_streak > 0 and base_roll > 0:
        streak_bonus = min(streak_cap, current_win_streak)
        return base_roll + streak_bonus, f"🔥 СТРИК x{current_win_streak}: +{streak_bonus} см."
    return base_roll, ""


def get_techies_chance(stats: GlobalRollStats, base_chance: float = TECHIES_BASE_CHANCE) -> float:
    if stats.last_techies_rolls_ago < TECHIES_PITY_START:
        return base_chance
    pity = min(TECHIES_PITY_MAX_ADD, (stats.last_techies_rolls_ago - TECHIES_PITY_START) * 0.003)
    return min(TECHIES_CHANCE_CAP, base_chance + pity)


# =====================
# Player and simulation
# =====================

class Player:
    __slots__ = ("id", "fissure", "last_fissure_time", "total_rolls", "history", "current_win_streak")

    def __init__(self, player_id: int):
        self.id = player_id
        self.fissure = 0.1
        self.last_fissure_time = 0.0
        self.total_rolls = 0
        self.history = deque(maxlen=20)
        self.current_win_streak = 0


def run_simulation(
    n_players: int,
    n_days: int,
    *,
    zeus_chance: float = ZEUS_CHANCE,
    techies_chance: float = TECHIES_CHANCE,
    multicast_chance: float = MULTICAST_CHANCE,
    techies_damage_max: int = 5,
    zeus_damage: float = 0.025,
    concentration: float = 3.0,
    low_high: float = 1.35,
    low_mid: float = 1.25,
    streak_cap: int = 5,
    pity_start: int = EXTREME_VALUE_PITY_START,
    positive_boost: float = 0.35,
    negative_boost: float = 0.70,
    equal_negative: bool = False,
    weekend: bool = False,
    track_contributions: bool = False,
):
    players = [Player(i) for i in range(n_players)]
    stats = GlobalRollStats()
    contributions = {
        "normal": [],
        "multicast": [],
        "zeus": [],
        "techies": [],
        "weekend": [],
        "streak": [],
    }

    for day in range(n_days):
        day_ts = day * COOLDOWN_SECONDS
        for p in players:
            if day_ts - p.last_fissure_time >= COOLDOWN_SECONDS:
                p.last_fissure_time = day_ts
                p.total_rolls += 1

                event_roll = random.random()
                if event_roll < zeus_chance:
                    before = p.fissure
                    p.fissure = max(0.1, p.fissure * (1 - zeus_damage))
                    if track_contributions:
                        contributions["zeus"].append(p.fissure - before)
                    stats.total_rolls += 1
                    continue

                dynamic_techies_chance = get_techies_chance(stats, base_chance=techies_chance)
                if event_roll < zeus_chance + dynamic_techies_chance:
                    before = p.fissure
                    damage = random.randint(1, techies_damage_max)
                    p.fissure = max(0.1, p.fissure - damage)
                    if track_contributions:
                        contributions["techies"].append(p.fissure - before)
                    stats.last_techies_rolls_ago = 0
                    stats.total_rolls += 1
                    continue
                else:
                    stats.last_techies_rolls_ago += 1

                is_weekend = weekend
                is_multicast = event_roll < zeus_chance + dynamic_techies_chance + multicast_chance
                if is_multicast:
                    cascade_count = random.choices([1, 2, 3, 4], weights=[0.40, 0.45, 0.13, 0.02], k=1)[0]
                else:
                    cascade_count = 1

                base_roll = calculate_fissure_roll(
                    current_fissure=p.fissure,
                    history=p.history,
                    stats=stats,
                    total_rolls=p.total_rolls,
                    concentration=concentration,
                    low_high=low_high,
                    low_mid=low_mid,
                    pity_start=pity_start,
                    positive_boost=positive_boost,
                    negative_boost=negative_boost,
                    equal_negative=equal_negative,
                )

                streak_bonus = 0
                if is_multicast:
                    base_roll_before_streak = base_roll
                    current_win_streak = p.current_win_streak
                    streak_roll, streak_text = calculate_streak_bonus(current_win_streak, base_roll, streak_cap=streak_cap)
                    streak_bonus = streak_roll - base_roll_before_streak
                    base_roll = streak_roll
                    final_roll = base_roll * cascade_count
                else:
                    current_win_streak = p.current_win_streak
                    streak_roll, streak_text = calculate_streak_bonus(current_win_streak, base_roll, streak_cap=streak_cap)
                    streak_bonus = streak_roll - base_roll
                    final_roll = streak_roll

                if is_weekend and final_roll > 0:
                    bonus_multiplier = random.choice(WEEKEND_BONUS_MULTIPLIERS)
                    weekend_delta = final_roll * (bonus_multiplier - 1.0)
                    if track_contributions:
                        contributions["weekend"].append(weekend_delta)
                    final_roll = final_roll * bonus_multiplier
                else:
                    if track_contributions:
                        contributions["weekend"].append(0.0)

                final_roll = apply_fissure_protection(p.fissure, final_roll)
                old_fissure = p.fissure
                p.fissure = calculate_new_fissure(p.fissure, final_roll)
                actual_delta = p.fissure - old_fissure

                if is_multicast:
                    if track_contributions:
                        contributions["multicast"].append(actual_delta)
                else:
                    if track_contributions:
                        contributions["normal"].append(actual_delta)

                if track_contributions:
                    contributions["streak"].append(streak_bonus)

                p.history.append(final_roll if not is_multicast else final_roll / cascade_count)
                p.current_win_streak = p.current_win_streak + 1 if final_roll > 0 else 0

                stats.total_rolls += 1
                if abs(final_roll) >= 10:
                    if final_roll > 0:
                        stats.last_extreme_positive_ago = 0
                    else:
                        stats.last_extreme_negative_ago = 0
                else:
                    stats.last_extreme_positive_ago += 1
                    stats.last_extreme_negative_ago += 1

    if track_contributions:
        return players, contributions
    return players


def summarize(players):
    values = [p.fissure for p in players]
    values.sort()
    n = len(values)
    total = sum(values)

    def pct(p):
        idx = int(n * p)
        idx = min(idx, n - 1)
        return values[idx]

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
        "min": values[0],
        "max": values[-1],
        "leq_0_1": count_at_most(0.1 + 1e-9),
        "leq_1": count_at_most(1.0 + 1e-9),
        "geq_1": count_at_least(1.0 - 1e-9),
        "geq_5": count_at_least(5.0 - 1e-9),
        "geq_10": count_at_least(10.0 - 1e-9),
        "geq_20": count_at_least(20.0 - 1e-9),
        "geq_50": count_at_least(50.0 - 1e-9),
        "geq_100": count_at_least(100.0 - 1e-9),
        "stuck_at_floor": count_at_most(0.11),
    }


def distribution_bins(players):
    bins = {
        "0.1-1": 0,
        "1-5": 0,
        "5-10": 0,
        "10-20": 0,
        "20-50": 0,
        "50-100": 0,
        "100+": 0,
    }
    for p in players:
        if p.fissure <= 1:
            bins["0.1-1"] += 1
        elif p.fissure <= 5:
            bins["1-5"] += 1
        elif p.fissure <= 10:
            bins["5-10"] += 1
        elif p.fissure <= 20:
            bins["10-20"] += 1
        elif p.fissure <= 50:
            bins["20-50"] += 1
        elif p.fissure <= 100:
            bins["50-100"] += 1
        else:
            bins["100+"] += 1
    return bins


def stats_for_list(values):
    n = len(values)
    if n == 0:
        return {"mean": 0.0, "median": 0.0, "p10": 0.0, "p90": 0.0, "p99": 0.0,
                "positive_pct": 0.0, "negative_pct": 0.0, "zero_pct": 0.0}
    values_sorted = sorted(values)
    mean = sum(values) / n
    median = values_sorted[n // 2]
    p10 = values_sorted[int(n * 0.10)]
    p90 = values_sorted[int(n * 0.90)]
    p99 = values_sorted[int(n * 0.99)]
    positive = sum(1 for v in values if v > 0)
    negative = sum(1 for v in values if v < 0)
    zero = sum(1 for v in values if v == 0)
    return {
        "mean": mean,
        "median": median,
        "p10": p10,
        "p90": p90,
        "p99": p99,
        "positive_pct": positive / n * 100,
        "negative_pct": negative / n * 100,
        "zero_pct": zero / n * 100,
    }


if __name__ == "__main__":
    print("Running CURRENT economy simulation 10k/365...")
    t0 = time.time()
    players, contributions = run_simulation(
        10000, 365,
        track_contributions=True,
    )
    s = summarize(players)
    bins = distribution_bins(players)

    print(f"mean={s['mean']:.2f} median={s['median']:.2f} p90={s['p90']:.2f} p95={s['p95']:.2f} p99={s['p99']:.2f}")
    print(f"min={s['min']:.2f} max={s['max']:.2f}")
    print(f"<=1={s['leq_1']} >=5={s['geq_5']} >=10={s['geq_10']} >=20={s['geq_20']} >=50={s['geq_50']} >=100={s['geq_100']}")
    print(f"stuck_at_floor={s['stuck_at_floor']}")
    print("Distribution bins:")
    for k, v in bins.items():
        print(f"  {k}: {v} ({v/s['players']*100:.1f}%)")

    print("\nPer-mechanic contributions:")
    for name, vals in contributions.items():
        st = stats_for_list(vals)
        print(f"{name}: mean={st['mean']:.3f} median={st['median']:.3f} pos={st['positive_pct']:.1f}% neg={st['negative_pct']:.1f}%")

    total_events = sum(len(v) for v in contributions.values())
    print(f"\nTotal tracked events: {total_events}")
    print(f"Simulation time: {time.time()-t0:.1f}s")
