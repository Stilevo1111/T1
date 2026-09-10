from balance_audit import run_simulation, summarize, distribution_bins, stats_for_list
import time

configs = {
    "CURRENT": {},
    "V1": {
        "zeus_chance": 0.07,
        "techies_chance": 0.10,
        "multicast_chance": 0.10,
        "techies_damage_max": 3,
        "zeus_damage": 0.015,
        "concentration": 2.0,
        "low_high": 1.15,
        "low_mid": 1.10,
        "streak_cap": 3,
        "pity_start": 60,
        "positive_boost": 0.20,
        "negative_boost": 0.50,
        "equal_negative": True,
    },
    "V2": {
        "equal_negative": True,
    },
}

for name, kwargs in configs.items():
    t0 = time.time()
    players, contributions = run_simulation(
        10000, 365,
        track_contributions=True,
        **kwargs,
    )
    s = summarize(players)
    print(f"{name}: mean={s['mean']:.1f} median={s['median']:.1f} p90={s['p90']:.1f} p95={s['p95']:.1f} p99={s['p99']:.1f} stuck={s['stuck_at_floor']}")
