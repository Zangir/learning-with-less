"""Render analytic evidence only; plotted curves are not fitted measurements."""
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots

ROOT = (Path(__file__).resolve().parents[1] / 'runtime')
checks = json.loads((ROOT / 'exact-checks.json').read_text())
cells = checks['cells']
labels = [f"C={r['c']}, Z={r['z']}" for r in cells]
source = [r['source']['value'] for r in cells]
shifted = [r['shifted']['value'] for r in cells]
ratio = np.linspace(1, 24, 185)
rich = .04 * ratio
values = dict(labels=labels, source=source, shifted=shifted,
              relative_label_cost=ratio.tolist(), rich_variance_coefficient=rich.tolist(),
              outcome_coefficients=[.5275, .6775],
              interpretation='Exact raw unbiased estimators; stronger outcome controls may improve. No fits.')
(ROOT / 'figure-data.json').write_text(json.dumps(values, indent=2) + '\n')
plt.rcParams.update({'font.size': 10, 'axes.spines.top': False, 'axes.spines.right': False,
                     'font.family': 'DejaVu Sans', 'savefig.facecolor': 'white'})
fig, axes = plt.subplots(1, 2, figsize=(11, 3.5), gridspec_kw={'width_ratios': [1, 1.2]})
x = np.arange(4)
axes[0].plot(x, source, 'o-', color='#146b8c', label='Informative law')
axes[0].plot(x, shifted, 's--', color='#bd532c', label='Shifted law')
axes[0].set(xticks=x, xticklabels=labels, ylim=(.2, .9), ylabel='Full-fill probability',
            title='Same observable law, different responses')
axes[0].legend(fontsize=8, frameon=False)
axes[0].text(.02, .02, 'No-label minimax excess Brier = 0.0081', transform=axes[0].transAxes, fontsize=9)
axes[1].plot(ratio, rich, color='#146b8c', label='Rich labels: 0.04 × relative cost')
axes[1].axhline(.5275, color='#bd532c', linestyle='--', label='Outcome labels, e = 0.1')
axes[1].axhline(.6775, color='#775d97', linestyle=':', label='Outcome labels, e = 0.4')
axes[1].set(xlabel='Relative label price cH / cY (hypothetical)',
            ylabel='B × variance of raw estimate of e', xlim=(1, 24), ylim=(0, 1.03),
            title='The label price can reverse the preference')
axes[1].legend(fontsize=8, frameon=False, loc='upper left')
for ax in axes:
    ax.grid(axis='y', alpha=.18)
fig.tight_layout()
fig.savefig(ROOT / 'main_figure.png', dpi=180)
fig.savefig(ROOT / 'main_figure.svg')
plt.close(fig)
interactive = make_subplots(rows=1, cols=2, subplot_titles=[
    'Observable marginals do not identify this shift', 'Exact comparator-specific cost example'])
for name, data in [('Informative law', source), ('Shifted law', shifted)]:
    interactive.add_trace(go.Scatter(x=labels, y=data, mode='lines+markers', name=name), row=1, col=1)
for name, data in [('Rich labels', rich), ('Outcome labels, e=.1', np.full_like(ratio, .5275)),
                   ('Outcome labels, e=.4', np.full_like(ratio, .6775))]:
    interactive.add_trace(go.Scatter(x=ratio, y=data, name=name), row=1, col=2)
interactive.update_xaxes(title_text='Relative label price cH/cY', row=1, col=2)
interactive.update_yaxes(title_text='B × Var(raw e estimate)', row=1, col=2)
interactive.update_layout(template='plotly_white', height=480,
    title='Exact derivations; no model fits. Equal-supervision direct and structured outputs coincide.',
    legend=dict(orientation='h', y=-.25), margin=dict(b=130))
interactive.write_html(ROOT / 'label-cost-explorer.html', include_plotlyjs=True)
