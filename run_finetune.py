from balance_audit import run_simulation, summarize, distribution_bins, stats_for_list
import time

configs = {
    "CURRENT": {},
    "FINE_TUNED": {
        "zeus_damage": 0.020,
        "techies_damage_max": 4,
        "concentration": 2.5,
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
    bins = distribution_bins(players)
    print(f"{name}:")
    print(f"  mean={s['mean']:.1f} median={s['median']:.1f} p90={s['p90']:.1f} p95={s['p95']:.1f} p99={s['p99']:.1f}")
    print(f"  min={s['min']:.1f} max={s['max']:.1f}")
    print(f"  <=1={s['leq_1']} >=5={s['geq_5']} >=10={s['geq_10']} >=20={s['geq_20']} >=50={s['geq_50']} >=100={s['geq_100']}")
    print(f"  stuck_at_floor={s['stuck_at_floor']}")
    print(f"  Distribution:")
    for k, v in bins.items():
        pct = v / s['players'] * 100
        print(f"    {k}: {v} ({pct:.1f}%)")
    print(f"  Per-mechanic:")
    for mech, vals in contributions.items():
        st = stats_for_list(vals)
        print(f"    {mech}: mean={st['mean']:.3f} pos={st['positive_pct']:.1f}% neg={st['negative_pct']:.1f}%")
    print(f"  time={round(time.time()-t0,1)}s")
    print()
