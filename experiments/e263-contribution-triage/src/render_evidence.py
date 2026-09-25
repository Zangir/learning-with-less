"""Render a contribution map and finite-record bounds from saved check outputs."""
import json
import re
import subprocess
from resource_guard import ROOT
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import plotly.graph_objects as go


def main():
    checked = json.loads((ROOT / 'analytical-checks.json').read_text())
    candidates = [
        dict(key='A', question='Known observation changes',
             prior='Mask-aware prediction\n+ consistency / distillation',
             missing='No distinct objective or\nfinite-budget improvement',
             memo='atlas-observation-operator-candidate.md'),
        dict(key='B', question='Constrained joint paths',
             prior='L2 flow / diffusion\n+ constrained samplers',
             missing='No new update rule,\nlaw or total-cost gain',
             memo='delta-path-generation-candidate.md'),
        dict(key='C', question='Missing / delayed labels',
             prior='Completion bounds\n+ online risk wrappers',
             missing='No sharper result under\nadmitted assumptions',
             memo='echo-censoring-risk-candidate.md')]
    rows = checked['completion_bounds']
    labels = ['Breakout: C - R', 'Breakout: C - P', 'Rebound: P - frequency']
    lower = [row['completion_lower']['value'] for row in rows]
    upper = [row['completion_upper']['value'] for row in rows]
    observed = [row['supported_only']['value'] for row in rows]
    centers = [(a + b) / 2 for a, b in zip(lower, upper)]
    half = [(b - a) / 2 for a, b in zip(lower, upper)]
    data = dict(candidates=candidates, labels=labels, lower=lower, upper=upper,
                supported_only=observed, centers=centers, half_widths=half,
                source='analytical-checks.json; accepted R031 figure_source.json',
                scope='Hypothetical complete-record outer bounds; not confidence intervals',
                new_fits=0, native_episodes=0)
    (ROOT / 'figure-data.json').write_text(json.dumps(data, indent=2) + '\n')
    plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 12,
                         'axes.spines.top': False, 'axes.spines.right': False})
    fig = plt.figure(figsize=(12, 6.1), facecolor='white', layout='constrained')
    grid = fig.add_gridspec(2, 1, height_ratios=[1.45, 1])
    ax = fig.add_subplot(grid[0])
    ax.axis('off')
    ax.set_xlim(0, 1)
    ax.set_ylim(-.25, 3.4)
    ax.text(0, 3.13, 'Three mechanisms; no current contribution survives',
            fontsize=17, weight='bold', color='#172b46')
    ax.text(0, 2.66, 'QUESTION', fontsize=10, weight='bold', color='#516274')
    ax.text(.35, 2.66, 'CLOSEST EXISTING MECHANISM', fontsize=10, weight='bold', color='#516274')
    ax.text(.69, 2.66, 'MISSING CONTRIBUTION', fontsize=10, weight='bold', color='#516274')
    for y, candidate in zip([2.14, 1.19, .24], candidates):
        ax.axhspan(y - .38, y + .39, color='#f0f4f8', zorder=0)
        ax.text(.013, y, candidate['key'], fontsize=15, weight='bold', va='center', color='#156b92')
        ax.text(.053, y, candidate['question'], fontsize=13, va='center')
        ax.text(.35, y, candidate['prior'], fontsize=12.5, va='center', linespacing=1.3)
        ax.text(.69, y, candidate['missing'], fontsize=12.5, va='center', color='#a63b32', linespacing=1.3)
    bx = fig.add_subplot(grid[1])
    for y, lo, hi, mid, obs in zip([2, 1, 0], lower, upper, centers, observed):
        bx.plot([lo, hi], [y, y], color='#156b92', linewidth=6, solid_capstyle='round')
        bx.scatter([obs], [y], color='#172b46', s=42, zorder=3)
        bx.text(hi + .0006, y, f'[{lo:+.5f}, {hi:+.5f}]', va='center', fontsize=11)
    bx.axvline(0, color='#667788', linestyle='--', linewidth=1)
    bx.set_yticks([2, 1, 0], labels, fontsize=12)
    bx.set_xlim(-.005, .024)
    bx.set_ylim(-.5, 2.8)
    bx.set_xticks([-.005, 0, .005, .01, .015, .02])
    bx.set_xlabel('Equal-day half-Brier difference: negative favors the left predictor', fontsize=12)
    bx.set_title('Two missing recorded labels cannot reverse these comparison signs', loc='left',
                 fontsize=14, weight='bold', pad=12)
    bx.grid(axis='x', alpha=.15)
    fig.savefig(ROOT / 'main_figure.png', dpi=190)
    fig.savefig(ROOT / 'main_figure.svg')
    plt.close(fig)

    interactive = go.Figure()
    interactive.add_trace(go.Scatter(x=centers, y=labels, mode='markers', name='Outer completion interval',
        marker=dict(size=10, color='#156b92'),
        error_x=dict(type='data', array=half, thickness=4, width=9),
        customdata=list(zip(lower, upper)),
        hovertemplate='%{y}<br>Interval [%{customdata[0]:+.8f}, %{customdata[1]:+.8f}]<extra></extra>'))
    interactive.add_trace(go.Scatter(x=observed, y=labels, mode='markers', name='Supported-only comparison',
        marker=dict(size=9, color='#172b46', symbol='diamond'),
        hovertemplate='%{y}<br>Supported-only: %{x:+.8f}<extra></extra>'))
    interactive.update_layout(template='plotly_white', height=390, margin=dict(l=190, r=25, t=35, b=80),
        xaxis_title='Equal-day half-Brier difference (lower favors the left predictor)',
        legend=dict(orientation='h', y=-.3), yaxis=dict(autorange='reversed'))
    interactive.add_vline(x=0, line_dash='dash', line_color='#667788')
    (ROOT / 'interactive-figure.json').write_text(interactive.to_json())
    cards = ''.join(f'<article><h2>{c["key"]}. {c["question"]}</h2><p>{c["prior"].replace(chr(10), " ")}</p>'
                    f'<p><b>No-go:</b> {c["missing"].replace(chr(10), " ")}</p>'
                    f'<a href="{c["memo"]}">Read mechanism memo</a></article>' for c in candidates)
    html = '''<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Remaining contribution triage</title>
<style>body{font:16px/1.55 system-ui,sans-serif;margin:32px auto;padding:0 22px;max-width:1100px;color:#172b46}
h1{line-height:1.15}h2{font-size:18px}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:18px}
article{background:#f0f4f8;padding:18px;border-radius:8px}a{color:#156b92}.scope{color:#516274}</style></head><body>
<p class="scope">E263 / D041 / T-012 r9 / 22 September 2026</p>
<h1>Three mechanisms. No current paper recommendation.</h1>
<p>These are contribution triage results. Every prospective test remains unexecuted.</p>
<div class="cards">''' + cards + '''</div><h2>Recorded-case completion bounds</h2>
<p>Hover for exact displayed values; click the legend to compare the supported-only points and outer intervals.
These are bounds from two missing recorded labels, not confidence intervals or future-risk guarantees.</p>'''
    html += interactive.to_html(full_html=False, include_plotlyjs=True, config={'displaylogo': False})
    html += '<p class="scope">Source: accepted R031 summaries; exact rational arithmetic on their saved decimals. Zero new fits or native episodes.</p></body></html>'
    (ROOT / 'contribution-map.html').write_text(html, encoding='utf-8')
    scripts = re.findall(r'<script[^>]*>([\s\S]*?)</script>', html)
    node = 'node'
    for script in scripts:
        subprocess.run([node, '--check'], input=script, text=True, encoding='utf-8', check=True, timeout=30)
    assert all(abs(c - row['half_width']['value']) < 1e-17 for c, row in zip(half, rows))
    (ROOT / 'figure-validation.json').write_text(json.dumps(dict(
        bounds_match=True, candidates=3, javascript_scripts_checked=len(scripts),
        browser_interaction_verified=False), indent=2) + '\n')


if __name__ == '__main__':
    main()
