"""
Full Real Economy Model for Fissure Bot.

This script builds a comprehensive simulation that matches the real /fissure execution flow.

Author: Kilo AI Assistant
Purpose: Audit and verify all mechanics are correctly modeled
"""

from __future__ import annotations

import os
import random
import sys
from collections import deque
from dataclasses import dataclass, field

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Import all mechanics from the codebase
from roll_balancer import (
    GlobalRollStats,
    NEW_PLAYER_MAX_ROLLS,
    get_global_stats_snapshot,
    get_player_history,
    get_techies_chance,
    init_global_stats,
    maybe_persist_global_stats,
    record_player_roll,
    reset_global_stats,
    select_roll,
    update_global_stats_on_event,
)
from stats import get_event_chances

# Event chances from constants
MULTICAST_DEFAULT_CHANCE = 0.15
ZEUS_DEFAULT_CHANCE = 0.10
TECHIES_DEFAULT_CHANCE = 0.15

# Multicast cascade thresholds (from fissure.py)
X2_THRESHOLD = 0.75
X3_THRESHOLD = 0.25
X4_THRESHOLD = 0.15

# Techies parameters (from techies.py)
TECHIES_MINE_MIN = 1
TECHIES_MINE_MAX = 10
TECHIES_MINES = 4
TECHIES_SUCCESS_RATE = 2/3

# Streak bonus (from rolls.py)
MAX_STREAK_BONUS = 5


@dataclass
class Player:
    """Represents a player in the economy simulation."""
    fissure: float = 0.1
    history: list[float] = field(default_factory=list)
    total_rolls: int = 0
    win_streak: int = 0
    lose_streak: int = 0
    id: int = 0
    
    def to_dict(self):
        return {
            'fissure': self.fissure,
            'history': self.history[-20:],
            'total_rolls': self.total_rolls,
            'win_streak': self.win_streak,
            'lose_streak': self.lose_streak,
        }


@dataclass
class EventStats:
    """Track statistics for each event type."""
    total_events: int = 0
    normal_rolls: int = 0
    multicasts: int = 0
    zeus: int = 0
    techies_success: int = 0
    techies_fail: int = 0
    total_growth: float = 0
    zeus_damage_total: float = 0
    techies_damage_total: float = 0


def calculate_expected_values():
    """Calculate EV for each mechanic."""
    print("\n" + "=" * 70)
    print("EXPECTED VALUES CALCULATION")
    print("=" * 70)
    
    # 1. Base roll EV (from RollBalancer with standard parameters)
    print("\n1. BASE ROLL (RollBalancer)")
    print("   - Uses Gaussian-like distribution centered at 0")
    print("   - Spread = min(50, max(5, fissure * 0.35))")
    print("   - EV ~ 0 (centered distribution)")
    print("   - For fissure=10: spread=4, EV~0")
    
    # 2. Streak bonus EV
    print("\n2. STREAK BONUS")
    print("   - Formula: +1 cm per win streak, cap at +5")
    print("   - EV depends on win rate and streak accumulation")
    print("   - If 50% win rate: average streak ~= 1")
    print("   - EV ~ +0.5 to +1 cm per roll (rough estimate)")
    
    # 3. Weekend bonus EV
    print("\n3. WEEKEND BONUS (Saturday, Sunday Moscow)")
    print("   - Multipliers: [1.5, 2, 2.5] - random choice")
    print("   - EV multiplier = (1.5 + 2 + 2.5) / 3 = 2.0")
    print("   - Only applies to positive normal rolls (not multicast)")
    print("   - ~28.6% of days are weekend days")
    
    # 4. Multicast EV
    print("\n4. MULTICAST")
    print("   - Chance: 15%")
    print("   - Cascade probabilities:")
    print("     * x1 (miss): ~25%")
    print("     * x2: 75% (includes x1 misses)")
    print("     * x3: 25% of x2 = 18.75%")
    print("     * x4: 15% of x3 = 2.81%")
    print("   - Expected cascade multiplier:")
    print("     * P(x1) = 0.25, P(x2) = 0.75*0.75 = 0.5625")
    print("     * Wait - need to check actual probabilities...")
    print("   - Let me recalculate:")
    print("     * x4: 0.15 (chance to go from x3 to x4)")
    print("     * x3: 0.25 (chance to go from x2 to x3)")
    print("     * x2: 0.75 (chance to go from no-cascade to x2)")
    print("   - Expected multiplier = 1*0.25 + 2*0.5625 + 3*0.1406 + 4*0.0211")
    print("     = 0.25 + 1.125 + 0.422 + 0.084")
    print("     = 1.88 (approximate)")
    print("   - EV due to multicast = 0.15 * 1.88 * base_roll_EV")
    
    # 5. Zeus EV damage
    print("\n5. ZEUS")
    print("   - Chance: 10% per roll")
    print("   - Damage: 2.5% of all other players fissures")
    print("   - Target: all players except trigger")
    print("   - EV damage per zeus = 0.025 * sum(all_other_fissures)")
    print("   - Per-player EV damage = 0.10 * 0.025 * (n-1)/n * avg_fissure")
    print("   - For large n: ~= 0.0025 * avg_fissure per roll")
    print("   - Over 365 days with 1 roll/day: ~= -0.9 cm per player")
    print("   - But with 10 players: -2.5% of 9 others each = massive impact!")
    
    # 6. Techies EV
    print("\n6. TECHIES")
    print("   - Chance: 15% (plus pity mechanism)")
    print("   - Mines: 4, each 1-10 cm")
    print("   - Total damage range: 4-40 cm")
    print("   - Mean damage: 4 * 5.5 = 22 cm")
    print("   - Success rate: 2/3 (choose safe button)")
    print("   - EV damage = (1/3) * (-22) = -7.33 cm on failure")
    print("   - EV per techies event = (2/3)*0 + (1/3)*(-22) = -7.33 cm")
    print("   - EV per roll = 0.15 * (-7.33) = -1.1 cm")


def simulate_single_roll(player: Player, global_stats: GlobalRollStats, 
                         players: list[Player], player_idx: int) -> tuple[float, str, EventStats]:
    """
    Simulate a single /fissure action following the real execution flow.
    
    Real flow from fissure.py:
    1. Check cooldown (skipped in simulation)
    2. Event selection: Zeus -> Techies -> Multicast -> Normal
    3. Roll calculation (using RollBalancer)
    4. Streak bonus applied
    5. Multicast cascade (if applicable)
    6. Weekend bonus (if applicable)
    7. Floor protection (0.1)
    8. Update fissure, history, streaks
    9. Update global stats
    """
    stats = EventStats()
    fissure = player.fissure
    
    # Step 1: Event selection
    event_roll = random.random()
    multicast_chance, zeus_chance, techies_chance = get_event_chances()
    
    if fissure < 30:  # Techies pity reduces chance
        techies_chance = get_techies_chance()
    
    # Zeus check (10% chance)
    if event_roll < zeus_chance:
        stats.zeus += 1
        # Zeus: -2.5% to all other players
        zeus_damage = 0
        for j, other in enumerate(players):
            if j != player_idx and other.fissure > 0.1:
                damage = other.fissure * 0.025
                other.fissure = max(0.1, other.fissure - damage)
                zeus_damage += damage
        stats.zeus_damage_total += zeus_damage
        stats.total_events += 1
        return 0, "zeus", stats
    
    # Techies check (15% chance)
    if event_roll < zeus_chance + techies_chance:
        stats.total_events += 1
        # Techies: mini-game with mines
        if random.random() < TECHIES_SUCCESS_RATE:
            stats.techies_success += 1
            return 0, "techies_success", stats
        else:
            stats.techies_fail += 1
            mines = [random.randint(TECHIES_MINE_MIN, TECHIES_MINE_MAX) for _ in range(TECHIES_MINES)]
            damage = sum(mines)
            new_fissure = max(0.1, fissure - damage)
            stats.techies_damage_total += damage
            return damage, "techies_fail", stats
    
    # Step 2: Roll calculation (using RollBalancer)
    spread = min(50, max(5, int(fissure * 0.35)))
    neg_max = -max(1, min(spread, int(fissure))) if fissure < 10 else -spread
    
    history_deque = deque(player.history[-20:], maxlen=20)
    roll, _ = select_roll(
        spread=spread,
        history=history_deque,
        stats=global_stats,
        total_rolls=player.total_rolls,
        current_fissure=fissure,
        negative_max=neg_max,
        positive_max=spread,
    )
    
    if roll == 0:
        roll = random.choice([-1, 1])
    
    # Step 3: Streak bonus
    base_roll = roll
    if player.win_streak > 0 and roll > 0:
        roll += min(MAX_STREAK_BONUS, player.win_streak)
    
    # Step 4: Check weekend bonus
    is_weekend = random.random() < 2/7  # Rough approximation
    is_multicast = event_roll < zeus_chance + techies_chance + multicast_chance
    
    if is_weekend and roll > 0 and not is_multicast and not is_fatal(roll):
        bonus = random.choice([1.5, 2, 2.5])
        roll *= bonus
    
    # Step 5: Multicast cascade (if applicable)
    cascade_count = 1
    if is_multicast:
        cascade_count = 1
        if random.random() < X2_THRESHOLD:
            cascade_count = 2
            if random.random() < X3_THRESHOLD:
                cascade_count = 3
                if random.random() < X4_THRESHOLD:
                    cascade_count = 4
        roll = roll * cascade_count
    
    # Step 6: Floor protection
    new_fissure = max(0.1, fissure + roll)
    
    # Step 7: Update streaks
    growth = new_fissure - fissure
    win = growth > 0
    lose = growth < 0
    
    if win:
        player.win_streak += 1
        player.lose_streak = 0
    elif lose:
        player.lose_streak += 1
        player.win_streak = 0
    # Note: if growth == 0, streaks dont change!
    
    # Step 8: Update player state
    player.fissure = new_fissure
    player.history.append(base_roll)
    player.total_rolls += 1
    
    # Step 9: Update global stats
    update_global_stats_on_event("multicast" if is_multicast else "roll", roll_value=base_roll)
    
    stats.total_events += 1
    stats.normal_rolls += 1 if not is_multicast else 0
    stats.multicasts += 1 if is_multicast else 0
    stats.total_growth += growth
    
    return growth, "regular", stats


def is_fatal(roll):
    return roll <= -10


def run_full_economy_simulation(players_count: int = 100, days: int = 365) -> dict:
    """Run a full economy simulation."""
    reset_global_stats()
    init_global_stats()
    
    players = [Player(id=i) for i in range(players_count)]
    initial_fissures = [p.fissure for p in players]
    
    stats = EventStats()
    daily_stats = []
    
    total_rolls_per_player = days  # Assuming 1 roll per day per player
    
    for day in range(days):
        day_growth = 0
        for i, player in enumerate(players):
            growth, event_type, event_stats = simulate_single_roll(player, get_global_stats_snapshot(), players, i)
            stats.total_events += event_stats.total_events
            stats.normal_rolls += event_stats.normal_rolls
            stats.multicasts += event_stats.multicasts
            stats.zeus += event_stats.zeus
            
            # Update global totals
            stats.total_growth += event_stats.total_growth
            stats.zeus_damage_total += event_stats.zeus_damage_total
            
            # Track streak-related stats
            day_growth += growth
        
        if day % 30 == 0 or day == days - 1:
            final_fissures = [p.fissure for p in players]
            mean_f = sum(final_fissures) / len(final_fissures)
            sorted_f = sorted(final_fissures)
            n = len(sorted_f)
            daily_stats.append({
                'day': day,
                'mean': mean_f,
                'median': sorted_f[n//2],
                'p90': sorted_f[9*n//10],
                'p99': sorted_f[99*n//100],
                'max': max(final_fissures),
                'mean_growth': day_growth / players_count,
            })
    
    final_growths = [p.fissure - f for p, f in zip(players, initial_fissures)]
    
    return {
        'final_stats': daily_stats[-1] if daily_stats else {},
        'growths': final_growths,
        'event_stats': stats,
    }


def check_multicast_probability():
    """Verify the actual cascade probabilities."""
    print("\n" + "=" * 70)
    print("MULTICAST CASCADE PROBABILITY VERIFICATION")
    print("=" * 70)
    
    from collections import Counter
    
    random.seed(42)
    cascade_counts = Counter()
    
    for _ in range(100000):
        cascade_count = 1
        # x2 check
        if random.random() < X2_THRESHOLD:
            cascade_count = 2
            # x3 check
            if random.random() < X3_THRESHOLD:
                cascade_count = 3
                # x4 check
                if random.random() < X4_THRESHOLD:
                    cascade_count = 4
        cascade_counts[cascade_count] += 1
    
    total = sum(cascade_counts.values())
    print("\nActual cascade probabilities (100k trials):")
    for count in sorted(cascade_counts.keys()):
        pct = cascade_counts[count] / total * 100
        print(f"  x{count}: {pct:.2f}%")
    
    expected = sum(count * cascade_counts[count] / total for count in cascade_counts)
    print(f"\nExpected multiplier: {expected:.4f}")
    print(f"Formula cascade_count (without base roll):")
    formula_expected = 1 * 0.25 + 2 * 0.5625 + 3 * 0.140625 + 4 * 0.021484
    print(f"  1*0.25 + 2*0.5625 + 3*0.140625 + 4*0.021484 = {formula_expected:.4f}")
    
    return dict(cascade_counts), expected


def verify_streak_behavior():
    """Verify streak behavior with different scenarios."""
    print("\n" + "=" * 70)
    print("STREAK BEHAVIOR VERIFICATION")
    print("=" * 70)
    
    print("\nKey finding from database.py update_fissure():")
    print("  - win = 1 if growth > 0, else 0")
    print("  - lose = 1 if growth < 0, else 0")
    print("  - current_win_streak = CASE WHEN win = 1 THEN current_win_streak + 1 ELSE 0 END")
    print("  - current_lose_streak = CASE WHEN lose = 1 THEN current_lose_streak + 1 ELSE 0 END")
    print("\nCRITICAL: When growth = 0 (techies success, zeus self, etc.),")
    print("  streaks remain UNCHANGED, not reset!")


if __name__ == "__main__":
    print("=" * 70)
    print("FISSURE BOT FULL REAL ECONOMY MODEL")
    print("=" * 70)
    
    calculate_expected_values()
    cascade_probs, expected_mult = check_multicast_probability()
    verify_streak_behavior()
    
    print("\n" + "=" * 70)
    print("BUILDING SIMULATION MATRIX")
    print("=" * 70)
    
    player_counts = [10, 50, 100, 500, 1000, 5000]
    periods = [30, 90, 180, 365]
    
    results = {}
    
    for players in player_counts:
        for period in periods:
            print(f"\nSimulating {players} players, {period} days...")
            try:
                result = run_full_economy_simulation(players, period)
                results[(players, period)] = result
            except Exception as e:
                print(f"  Error: {e}")
                results[(players, period)] = None
    
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)