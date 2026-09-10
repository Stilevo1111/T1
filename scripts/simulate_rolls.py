"""
Comprehensive simulation for the roll balancer system.

Run: python scripts/simulate_rolls.py

Simulates:
1. Normal player (100k rolls)
2. New players (100k players x 20 rolls)
3. Bad streak recovery
4. Good streak smoothing
5. Techies pity gaps
6. Economy balance
"""

from __future__ import annotations

import os
import random
import statistics
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from roll_balancer import (
    get_global_stats_snapshot,
    get_techies_chance,
    init_global_stats,
    record_player_roll,
    reset_global_stats,
    select_roll,
    update_global_stats_on_event,
)

random.seed(42)


def _simulate_roll(fissure: float, history: list, global_stats) -> int:
    spread = min(50, max(5, int(fissure * 0.35)))
    if fissure < 10:
        neg_max = -max(1, min(spread, int(fissure)))
    else:
        neg_max = -spread

    from collections import deque
    history_deque = deque(history, maxlen=20)
    roll, _ = select_roll(
        spread=spread,
        history=history_deque,
        stats=global_stats,
        total_rolls=len(history),
        current_fissure=fissure,
        negative_max=neg_max,
        positive_max=spread,
    )

    if roll == 0:
        roll = random.choice([-1, 1])

    return roll


def simulate_normal_player(num_rolls: int = 100_000) -> dict:
    random.seed(42)
    print(f"\n=== Normal Player: {num_rolls} rolls ===")
    reset_global_stats()
    init_global_stats()
    history = []
    fissure = 0.1
    stats = get_global_stats_snapshot()

    roll_values = []
    positive_count = 0
    negative_count = 0
    max_streak_same = 0
    current_same_streak = 0
    last_same = None

    max_gap_techies = 0
    current_gap = 0
    techies_count = 0

    for i in range(num_rolls):
        event_roll = random.random()
        techies_chance = get_techies_chance()
        if event_roll < 0.10:
            current_gap += 1
            continue
        elif event_roll < 0.10 + techies_chance:
            techies_count += 1
            update_global_stats_on_event("techies")
            stats = get_global_stats_snapshot()
            current_gap = 0
            continue
        elif event_roll < 0.10 + techies_chance + 0.15:
            pass

        roll = _simulate_roll(fissure, history, stats)
        roll_values.append(roll)
        fissure = max(0.1, fissure + roll)

        if roll == last_same:
            current_same_streak += 1
            max_streak_same = max(max_streak_same, current_same_streak)
        else:
            current_same_streak = 1
            last_same = roll

        if roll > 0:
            positive_count += 1
        elif roll < 0:
            negative_count += 1

        history.append(roll)
        record_player_roll(0, roll)
        update_global_stats_on_event("roll", roll_value=roll)
        stats = get_global_stats_snapshot()
        current_gap += 1

    max_gap_techies = max(max_gap_techies, current_gap)

    hist = Counter(roll_values)
    print(f"  Total rolls: {len(roll_values)}")
    print(f"  Positive: {positive_count} ({positive_count/len(roll_values)*100:.1f}%)")
    print(f"  Negative: {negative_count} ({negative_count/len(roll_values)*100:.1f}%)")
    print(f"  Mean roll: {statistics.mean(roll_values):.3f}")
    print(f"  Median roll: {statistics.median(roll_values):.1f}")
    print(f"  Max same-value streak: {max_streak_same}")
    print(f"  Techies events: {techies_count}")
    print(f"  Avg rolls between techies: {num_rolls/max(techies_count,1):.1f}")
    print(f"  Max gap without techies: {max_gap_techies}")
    print(f"  Final fissure: {fissure:.1f}")
    print(f"  Top 10 values: {hist.most_common(10)}")

    return {
        "roll_values": roll_values,
        "positive_pct": positive_count / len(roll_values),
        "negative_pct": negative_count / len(roll_values),
        "mean": statistics.mean(roll_values),
        "max_streak": max_streak_same,
        "techies_count": techies_count,
        "avg_techies_gap": num_rolls / max(techies_count, 1),
        "max_techies_gap": max_gap_techies,
        "final_fissure": fissure,
        "distribution": dict(hist),
    }


def simulate_new_players(num_players: int = 100_000, rolls_per_player: int = 20) -> dict:
    random.seed(42)
    print(f"\n=== New Players: {num_players} players x {rolls_per_player} rolls ===")
    reset_global_stats()
    init_global_stats()

    results = []
    stuck_at_0_1 = 0
    total_growth = 0.0
    max_growth = 0.0
    positive_first_roll = 0
    stats = get_global_stats_snapshot()

    for p in range(num_players):
        history = []
        fissure = 0.1
        player_id = p + 1
        stats = get_global_stats_snapshot()

        for i in range(rolls_per_player):
            event_roll = random.random()
            techies_chance = get_techies_chance()
            if event_roll < 0.10 + techies_chance:
                update_global_stats_on_event("techies")
                stats = get_global_stats_snapshot()
                continue
            if event_roll < 0.10 + techies_chance + 0.15:
                pass

            roll = _simulate_roll(fissure, history, stats)
            fissure = max(0.1, fissure + roll)
            history.append(roll)
            record_player_roll(player_id, roll)
            update_global_stats_on_event("roll", roll_value=roll)
            stats = get_global_stats_snapshot()

            if i == 0 and roll > 0:
                positive_first_roll += 1

        growth = fissure - 0.1
        results.append(growth)
        total_growth += growth
        max_growth = max(max_growth, growth)
        if fissure <= 0.1:
            stuck_at_0_1 += 1

    avg_growth = total_growth / num_players
    print(f"  Stuck at 0.1: {stuck_at_0_1} ({stuck_at_0_1/num_players*100:.1f}%)")
    print(f"  Avg growth after {rolls_per_player} rolls: {avg_growth:.2f} cm")
    print(f"  Max growth: {max_growth:.1f} cm")
    print(f"  Positive first roll: {positive_first_roll} ({positive_first_roll/num_players*100:.1f}%)")
    print(f"  Mean of growths: {statistics.mean(results):.2f}")
    print(f"  Median of growths: {statistics.median(results):.2f}")

    final_fissures = [0.1 + g for g in results]
    buckets = defaultdict(int)
    for f in final_fissures:
        if f < 1:
            buckets["<1"] += 1
        elif f < 5:
            buckets["1-5"] += 1
        elif f < 10:
            buckets["5-10"] += 1
        elif f < 20:
            buckets["10-20"] += 1
        else:
            buckets["20+"] += 1
    print(f"  Final fissure distribution: {dict(buckets)}")

    return {
        "stuck_pct": stuck_at_0_1 / num_players,
        "avg_growth": avg_growth,
        "max_growth": max_growth,
        "positive_first_roll_pct": positive_first_roll / num_players,
        "final_distribution": dict(buckets),
    }


def simulate_bad_streak_recovery() -> dict:
    random.seed(42)
    print("\n=== Bad Streak Recovery ===")
    reset_global_stats()
    init_global_stats()

    history = [-5, -5, -3, -3, -1, -5]
    fissure = 0.1
    for v in history:
        fissure = max(0.1, fissure + v)

    print(f"  Initial history: {history}")
    print(f"  Initial fissure: {fissure:.1f}")

    positive_first_5 = 0
    total_first_5 = 5
    stats = get_global_stats_snapshot()
    for i in range(total_first_5):
        roll = _simulate_roll(fissure, history, stats)
        if roll > 0:
            positive_first_5 += 1
        fissure = max(0.1, fissure + roll)
        history.append(roll)
        record_player_roll(999, roll)
        update_global_stats_on_event("roll", roll_value=roll)
        stats = get_global_stats_snapshot()

    print(f"  Positive in first 5 rolls after bad streak: {positive_first_5}/{total_first_5} ({positive_first_5/total_first_5*100:.1f}%)")
    print("  Expected without protection: ~40-50%")
    return {"positive_first_5_pct": positive_first_5 / total_first_5}


def simulate_good_streak_smoothing() -> dict:
    random.seed(42)
    print("\n=== Good Streak Smoothing ===")
    reset_global_stats()
    init_global_stats()

    history = [10, 5, 5, 3, 10]
    fissure = 0.1
    for v in history:
        fissure = max(0.1, fissure + v)

    print(f"  Initial history: {history}")
    print(f"  Initial fissure: {fissure:.1f}")

    big_positive_first_5 = 0
    total_first_5 = 5
    stats = get_global_stats_snapshot()
    for i in range(total_first_5):
        roll = _simulate_roll(fissure, history, stats)
        if roll >= 8:
            big_positive_first_5 += 1
        fissure = max(0.1, fissure + roll)
        history.append(roll)
        record_player_roll(888, roll)
        update_global_stats_on_event("roll", roll_value=roll)
        stats = get_global_stats_snapshot()

    print(f"  Big positive (>=8) in first 5 rolls after good streak: {big_positive_first_5}/{total_first_5} ({big_positive_first_5/total_first_5*100:.1f}%)")
    print("  Expected without smoothing: ~15-25%")
    return {"big_positive_first_5_pct": big_positive_first_5 / total_first_5}


def simulate_techies_pity() -> dict:
    random.seed(42)
    print("\n=== Techies Pity ===")
    reset_global_stats()
    init_global_stats()

    gaps = []
    current_gap = 0
    total_events = 50_000

    for i in range(total_events):
        event_roll = random.random()
        techies_chance = get_techies_chance()
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

    print(f"  Total events: {total_events}")
    print(f"  Techies count: {len(gaps)}")
    print(f"  Avg gap between techies: {statistics.mean(gaps):.1f}")
    print(f"  Median gap: {statistics.median(gaps):.1f}")
    print(f"  Max gap: {max(gaps)}")
    print(f"  Gaps > 100: {sum(1 for g in gaps if g > 100)}")
    print(f"  Gaps > 200: {sum(1 for g in gaps if g > 200)}")
    return {
        "techies_count": len(gaps),
        "avg_gap": statistics.mean(gaps),
        "max_gap": max(gaps),
        "gaps_over_100": sum(1 for g in gaps if g > 100),
        "gaps_over_200": sum(1 for g in gaps if g > 200),
    }


def simulate_economy_balance() -> dict:
    random.seed(42)
    print("\n=== Economy Balance (10 players x 500 rolls each) ===")
    reset_global_stats()
    init_global_stats()

    all_growths = []
    final_fissures = []
    stats = get_global_stats_snapshot()

    for p in range(10):
        history = []
        fissure = 0.1
        for i in range(500):
            event_roll = random.random()
            techies_chance = get_techies_chance()
            if event_roll < 0.10 + techies_chance:
                update_global_stats_on_event("techies")
                stats = get_global_stats_snapshot()
                continue
            if event_roll < 0.10 + techies_chance + 0.15:
                pass

            roll = _simulate_roll(fissure, history, stats)
            fissure = max(0.1, fissure + roll)
            history.append(roll)
            record_player_roll(p + 1, roll)
            update_global_stats_on_event("roll", roll_value=roll)
            stats = get_global_stats_snapshot()
            all_growths.append(roll)
        final_fissures.append(fissure)

    mean_growth = statistics.mean(all_growths)
    print(f"  Mean roll value: {mean_growth:.4f}")
    print(f"  Positive mean: {statistics.mean([r for r in all_growths if r > 0]):.4f}")
    print(f"  Negative mean: {statistics.mean([r for r in all_growths if r < 0]):.4f}")
    print(f"  Avg final fissure: {statistics.mean(final_fissures):.1f}")
    print(f"  Min final fissure: {min(final_fissures):.1f}")
    print(f"  Max final fissure: {max(final_fissures):.1f}")
    return {
        "mean_roll": mean_growth,
        "avg_final_fissure": statistics.mean(final_fissures),
    }


def run_all_simulations():
    print("=" * 60)
    print("FISSURE BOT ROLL BALANCER SIMULATION")
    print("=" * 60)

    results = {}
    results["normal"] = simulate_normal_player(100_000)
    results["new_players"] = simulate_new_players(100_000, 20)
    results["bad_streak"] = simulate_bad_streak_recovery()
    results["good_streak"] = simulate_good_streak_smoothing()
    results["techies_pity"] = simulate_techies_pity()
    results["economy"] = simulate_economy_balance()

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)

    print("\n[NORMAL PLAYER]")
    print(f"  Mean roll: {results['normal']['mean']:.4f}")
    print(f"  Positive %: {results['normal']['positive_pct']*100:.1f}%")
    print(f"  Max same streak: {results['normal']['max_streak']}")
    print(f"  Avg techies gap: {results['normal']['avg_techies_gap']:.1f}")
    print(f"  Max techies gap: {results['normal']['max_techies_gap']}")

    print("\n[NEW PLAYERS]")
    print(f"  Stuck at 0.1: {results['new_players']['stuck_pct']*100:.1f}%")
    print(f"  Avg growth: {results['new_players']['avg_growth']:.2f} cm")
    print(f"  Positive first roll: {results['new_players']['positive_first_roll_pct']*100:.1f}%")

    print("\n[BAD STREAK RECOVERY]")
    print(f"  Positive % in first 5 after bad streak: {results['bad_streak']['positive_first_5_pct']*100:.1f}%")

    print("\n[GOOD STREAK SMOOTHING]")
    print(f"  Big positive (>=8) in first 5 after good streak: {results['good_streak']['big_positive_first_5_pct']*100:.1f}%")

    print("\n[TECHIES PITY]")
    print(f"  Max gap: {results['techies_pity']['max_gap']}")
    print(f"  Gaps > 200: {results['techies_pity']['gaps_over_200']}")

    print("\n[ECONOMY]")
    print(f"  Mean roll: {results['economy']['mean_roll']:.4f}")
    print(f"  Avg final fissure: {results['economy']['avg_final_fissure']:.1f}")

    print("\n" + "=" * 60)
    print("VALIDATION CHECKS")
    print("=" * 60)

    checks = []
    checks.append(("New players stuck < 15%", results['new_players']['stuck_pct'] < 0.15))
    checks.append(("New players avg growth > 3cm", results['new_players']['avg_growth'] > 3.0))
    checks.append(("Bad streak first 5 positive > 55%", results['bad_streak']['positive_first_5_pct'] > 0.55))
    checks.append(("Good streak first 5 big positive < 20%", results['good_streak']['big_positive_first_5_pct'] < 0.20))
    checks.append(("Techies max gap < 500", results['techies_pity']['max_gap'] < 500))
    checks.append(("Economy mean roll ~ 0 (slight positive)", -0.2 < results['economy']['mean_roll'] < 0.3))
    checks.append(("Normal player positive ~ 45-55%", 0.40 < results['normal']['positive_pct'] < 0.60))
    checks.append(("Techies gaps > 200 = 0", results['techies_pity']['gaps_over_200'] == 0))

    all_passed = True
    for name, passed in checks:
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {name}")
        if not passed:
            all_passed = False

    print("\n" + "=" * 60)
    if all_passed:
        print("ALL CHECKS PASSED!")
    else:
        print("SOME CHECKS FAILED - review parameters")
    print("=" * 60)


if __name__ == "__main__":
    run_all_simulations()
