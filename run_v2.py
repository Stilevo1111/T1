from balance_audit import run_simulation, summarize, distribution_bins, stats_for_list
import time

t0 = time.time()
players, contributions = run_simulation(
    10000, 365,
    equal_negative=True,
    track_contributions=True,
)
s = summarize(players)
bins = distribution_bins(players)
print('V2 10k/365:')
print('mean', round(s['mean'],2), 'median', round(s['median'],2), 'p90', round(s['p90'],2), 'p95', round(s['p95'],2), 'p99', round(s['p99'],2))
print('min', round(s['min'],2), 'max', round(s['max'],2))
print('<=1', s['leq_1'], '>=5', s['geq_5'], '>=10', s['geq_10'], '>=20', s['geq_20'], '>=50', s['geq_50'], '>=100', s['geq_100'])
print('stuck_at_floor', s['stuck_at_floor'])
print('Distribution bins:')
for k, v in bins.items():
    pct = v / s['players'] * 100
    print(f'  {k}: {v} ({pct:.1f}%)')
print('Per-mechanic contributions:')
for name, vals in contributions.items():
    st = stats_for_list(vals)
    print(f'  {name}: mean={st["mean"]:.3f} median={st["median"]:.3f} pos={st["positive_pct"]:.1f}% neg={st["negative_pct"]:.1f}%')
print('time', round(time.time()-t0,1))
