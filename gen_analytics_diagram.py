import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
import numpy as np

fig, ax = plt.subplots(1, 1, figsize=(16, 22))
ax.set_xlim(0, 100)
ax.set_ylim(0, 200)
ax.axis('off')
fig.patch.set_facecolor('#1a1a2e')

# Title
ax.text(50, 192, u'\U0001f50d ANALYTICS - SCHEME OF WORK', fontsize=18, fontweight='bold',
        ha='center', va='center', color='#f4c430', fontfamily='sans-serif')
ax.text(50, 185, '=================================================', fontsize=10,
        ha='center', va='center', color='#555588')

# Colors
c_start = '#2d9a2e'
c_proc = '#1e5799'
c_api = '#9b59b6'
c_calc = '#e67e22'
c_out = '#2ecc71'
c_nav = '#e74c3c'

def box(text, x, y, w, h, color, fs=9, bold=False):
    box_patch = FancyBboxPatch((x, y), w, h, boxstyle='round,pad=0.3',
                               facecolor=color, edgecolor='white', linewidth=1.2, alpha=0.92)
    ax.add_patch(box_patch)
    ax.text(x+w/2, y+h/2, text, fontsize=fs, fontfamily='sans-serif',
            fontweight='bold' if bold else 'normal',
            ha='center', va='center', color='white', wrap=True)

def arrow(sx, sy, ex, ey, text='', fs=7):
    ax.annotate('', xy=(ex, ey), xytext=(sx, sy),
                arrowprops=dict(arrowstyle='->', color='#aaaaaa', lw=2,
                                connectionstyle='arc3,rad=0.1'))
    if text:
        mx, my = (sx+ex)/2, (sy+ey)/2
        ax.text(mx, my+3, text, fontsize=fs, ha='center', va='bottom',
                color='#cccccc', fontfamily='sans-serif', style='italic')

# Step 1
box(u'User clicks\n"Analytics"', 25, 165, 50, 14, c_start, 8, True)
arrow(50, 165, 50, 150)

# Step 2
box('analyze_command()\nclears old messages', 25, 138, 50, 13, c_proc, 8)
arrow(50, 138, 50, 130)

# Step 3
box('generate_weekly_analytics()\nchecks 1h cache', 12, 117, 76, 12, c_api, 8)
arrow(50, 117, 50, 110)

# Step 4
box('get_weekly_matches()\nOpenDota - last 10 games', 12, 97, 76, 12, c_api, 8)
arrow(50, 97, 25, 88)
arrow(50, 97, 75, 88)

# Step 5 - detect role
box(u'detect_role_from_history()\n1) Hero role >60% → dominant role\n2) Else stats: lane, GPM, XPM, KDA', 3, 75, 45, 12, c_calc, 7, True)
arrow(25, 75, 50, 68)

# Step 5b - icon loading
box('load_heroes() + load_hero_roles()\nhero names and roles cache', 55, 75, 45, 12, c_api, 7)
arrow(75, 75, 75, 68)
arrow(75, 68, 50, 68)

# Step 6 - calculations block
box('Per-game metrics:', 30, 55, 40, 8, c_calc, 8, True)

sub_items = [
    (u'GPM / XPM / LH / DN', 52, 48),
    ('KDA = (K+A)/max(D,1)', 52, 43),
    ('Utility = stuns+heals+stacks+w', 52, 38),
    ('IMP = weighted vs PRO benchmarks', 52, 33),
]
for txt, tx, ty in sub_items:
    box(txt, tx, ty, 36, 4.5, '#1a3a5c', 6)
    if ty > 34:
        arrow(50, ty+4.5, 50, ty+1)

arrow(50, 33, 50, 28)

# Step 7 - chart
box('create_visual_chart()\nIMP chart + hero icons', 18, 18, 64, 8, '#8e44ad', 8, True)
arrow(50, 18, 50, 11)

# Step 8 - pages
box('get_analytics_pages()\n3 pages stored in user_data', 18, 0, 64, 10, '#27ae60', 8, True)

# Pages detail
for i, (px, label) in enumerate([(5, 'vs PRO'), (33, u'Detailed')]):
    box(label, px, -16, 26, 7, c_out, 7)
    arrow(px+13, -9, px+13, -2)

# Navigation block (right side)
box('Inline Keyboard Nav:', 68, 155, 30, 8, c_nav, 8, True)

nav_items = [
    ('page_0 / page_1 / page_2', 68, 143),
    (u'Back  <-  analytics_prev', 68, 135),
    ('Next  ->  analytics_next', 68, 127),
    ('Close  ❌  analytics_close', 68, 119),
]
for txt, tx, ty in nav_items:
    box(txt, tx, ty, 30, 7, '#34495e', 7, False)
    if ty > 119:
        arrow(83, ty+7, 83, ty-1)

# Feedback arrow from _show_analytics_page
arrow(83, 119, 83, 105)
box('_show_analytics_page()\nedit caption text', 68, 96, 30, 9, c_proc, 7, True)

# Cache note
box(u'CACHE: analytics_cache 1h\ntotal_stats for quick hash check', 2, -30, 96, 10, '#555588', 7)

# Legend
legend_items = [
    ('#2d9a2e', 'Entry point'),
    ('#1e5799', 'Processing'),
    ('#9b59b6', 'API / Cache'),
    ('#e67e22', 'Calculation'),
    ('#2ecc71', 'Output pages'),
    ('#e74c3c', 'Navigation'),
]
for i, (col, label) in enumerate(legend_items):
    row = i // 3
    col2 = i % 3
    bx = 5 + col2 * 32
    by = -48 - row * 9
    box('', bx, by, 4, 4, col)
    ax.text(bx+5, by+2, label, fontsize=7, color='#cccccc', fontfamily='sans-serif')

plt.tight_layout()
fig.savefig('analytics_flow.png', dpi=150, facecolor='#1a1a2e', bbox_inches='tight')
plt.close()
print('Done - analytics_flow.png created')