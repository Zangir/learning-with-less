"""Render E-210 r2 results from saved tables; no fitting or data acquisition."""
from pathlib import Path
import csv
import json
import os

os.environ['OMP_NUM_THREADS'] = '2'
os.environ['OPENBLAS_NUM_THREADS'] = '2'
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.ticker import NullLocator
import plotly.graph_objects as go
from plotly.subplots import make_subplots

ROOT = Path(__file__).resolve().parents[1]


def read(name):
    with (ROOT / name).open() as f:
        return list(csv.DictReader(f))


def main():
    summary = read('finite_summary.csv')
    expected = read('expected_risk.csv')
    exact = json.loads((ROOT / 'population.json').read_text())
    metadata = json.loads((ROOT / 'run_metadata.json').read_text())
    blue, green, red, gray = '#225ea8', '#16816a', '#c64840', '#596779'
    plt.rcParams.update({'font.size': 11.5, 'axes.spines.top': False, 'axes.spines.right': False,
                         'axes.titleweight': 'bold', 'font.family': 'DejaVu Sans'})
    fig, axes = plt.subplots(2, 2, figsize=(14, 9))
    ax = axes[0, 0]
    support = list(range(4))
    for x, offset, color in ((0, -.18, blue), (1, .18, green)):
        ax.bar([v + offset for v in support], metadata['target_probabilities'][x], width=.34,
               color=color, label=f'Observed context X={x}')
    ax.set(xticks=support, ylim=(0, .65), xlabel='Hidden state A (synthetic volume units)',
           ylabel='Conditional probability', title='A  Same mean and entropy, different query risks')
    ax.text(.03, .92, 'Both means = 1.5; both source risks P(A <= 1) = 0.5',
            transform=ax.transAxes, color=gray, fontsize=10)
    ax.legend(frameon=False, fontsize=10, loc='upper center', bbox_to_anchor=(.5, .84))
    ax = axes[0, 1]
    ax.bar([0, 1, 2], [exact['compression_regret'], 0, 0], color=[red, blue, green], width=.6)
    ax.scatter([1, 2], [0, 0], color=[blue, green], zorder=3)
    ax.set(xticks=[0, 1, 2], xticklabels=['Exact mean / source\nsummary only', 'Direct CDF =\nposterior', 'Known-symmetry\nscalar'],
           ylim=(-.005, .10), ylabel='Population decision regret', title='B  A reusable scalar can also suffice')
    ax.text(0, .078, '0.075', ha='center', color=red, weight='bold')
    ax.text(.97, .92, 'Best calibrated decoder in each information class',
            ha='right', transform=ax.transAxes, color=gray, fontsize=10)
    ax.grid(axis='y', alpha=.15)
    interactive = make_subplots(rows=1, cols=2, subplot_titles=('RPS excess', 'Primary decision regret'))
    for family, color, label in [('universal', blue, 'Universal: posterior = direct CDF'),
                                 ('symmetric', green, 'Known symmetry: posterior = direct scalar')]:
        rows = [r for r in summary if r['family'] == family]
        references = [r for r in expected if r['family'] == family]
        sizes = [int(r['n_train']) for r in rows]
        for col, metric, base in [(0, 'rps', exact['bayes_rps']), (1, 'primary_regret', 0)]:
            ax = axes[1, col]
            y = [float(r[f'mean_{metric}']) - base for r in rows]
            low = [float(r[f'{metric}_ci_low']) - base for r in rows]
            high = [float(r[f'{metric}_ci_high']) - base for r in rows]
            error = [[v - lo for v, lo in zip(y, low)], [hi - v for v, hi in zip(y, high)]]
            ax.errorbar(sizes, y, yerr=error, fmt='o-', color=color, capsize=4, lw=2, label=label)
            expectation = [float(r['expected_rps_excess' if metric == 'rps' else 'expected_primary_regret']) for r in references]
            ax.plot(sizes, expectation, ':', color=color, alpha=.8)
            ax.set(xscale='log', xticks=sizes, xlabel='Training examples (400 paired datasets)')
            ax.set_xticklabels(sizes)
            ax.xaxis.set_minor_locator(NullLocator())
            ax.grid(axis='y', alpha=.17)
            interactive.add_trace(go.Scatter(x=sizes, y=y, mode='lines+markers', name=label,
                legendgroup=family, showlegend=col == 0,
                error_y=dict(type='data', symmetric=False, array=error[1], arrayminus=error[0])), row=1, col=col + 1)
    axes[1, 0].set(yscale='log', ylabel='Excess normalized ranked probability score',
                   title='C  Structural knowledge improves sample efficiency')
    axes[1, 0].legend(frameon=False, fontsize=9, loc='upper right')
    axes[1, 1].set(ylabel='Expected excess normalized decision cost',
                   title='D  Zero observed errors need a rare-error check', ylim=(-.0007, .0145))
    axes[1, 1].axhline(0, color=gray, lw=1)
    tail = {r['family']: float(r['expected_primary_regret']) for r in expected if r['n_train'] == '512'}
    axes[1, 1].text(.97, .92, 'n=512: zero errors in all 400 datasets\n'
        f"Expected regret: {tail['universal']:.2e} universal\n"
        f"                          {tail['symmetric']:.2e} symmetric",
        ha='right', va='top', transform=axes[1, 1].transAxes, fontsize=10, color=gray)
    fig.suptitle('Nonbinary ambiguity: equally supervised direct risks match reconstruction',
                 fontsize=18, x=.05, ha='left')
    fig.text(.05, .922, 'T-012 r2 / E-210 | Fixed coarsening | Two statistical families, each in two coordinates | Simulation only',
             color=gray, fontsize=11)
    fig.text(.05, .025, 'Error bars: pointwise 95% Monte Carlo intervals. Dotted curves: post-run deterministic expectations.\n'
             'Known symmetry changes the model prior and dimension for both coordinates; its benefit is not restoration-specific.',
             color=gray, fontsize=11)
    fig.subplots_adjust(left=.075, right=.98, top=.855, bottom=.14, wspace=.28, hspace=.43)
    fig.savefig(ROOT / 'main_figure.png', dpi=180)
    fig.savefig(ROOT / 'main_figure.svg')
    interactive.update_xaxes(type='log', title_text='Training examples')
    interactive.update_layout(template='plotly_white', title='E-210 r2: matched coordinates; structural prior comparison', height=560)
    interactive.write_html(ROOT / 'interactive.html', include_plotlyjs=True)
    print('Rendered main_figure.png, main_figure.svg and interactive.html')


if __name__ == '__main__':
    main()
