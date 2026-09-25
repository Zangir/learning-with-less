"""Render saved exact-check evidence and a query explorer; no new computation run."""
from pathlib import Path
import csv
import json
import os

os.environ.update(OMP_NUM_THREADS="2", OPENBLAS_NUM_THREADS="2", MKL_NUM_THREADS="2")
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

ROOT = Path(__file__).resolve().parents[1]


def box(ax, x, y, width, height, label, color="#eaf0f6"):
    ax.add_patch(FancyBboxPatch((x, y), width, height, boxstyle="round,pad=.014",
                              facecolor=color, edgecolor="#b9c9d6", linewidth=1))
    ax.text(x + width / 2, y + height / 2, label, ha="center", va="center", fontsize=11)


def arrow(ax, x, y, tx, ty):
    ax.annotate("", xy=(tx, ty), xytext=(x, y),
                arrowprops={"arrowstyle": "->", "color": "#58748b", "lw": 1.5})


def main():
    checks = json.loads((ROOT / "exact-checks.json").read_text())
    fixture = checks["fixtures"][0]
    with (ROOT / "primary_queries.csv").open() as stream:
        queries = list(csv.DictReader(stream))
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 11,
                         "axes.spines.top": False, "axes.spines.right": False})
    fig, axes = plt.subplots(1, 2, figsize=(14, 7), gridspec_kw={"width_ratios": [1.25, 1]})
    fig.suptitle("One reusable certificate, two descriptions of the same compiler", fontsize=19, weight="bold", y=.98)
    left, right = axes
    left.set(xlim=(0, 1), ylim=(0, 1))
    left.axis("off")
    left.set_title("A  Exact operation mapping", loc="left", weight="bold", pad=18)
    box(left, .12, .83, .76, .12, "Fixed coarse tape + supplied constraints\nD = 4; initial ahead in {1, 2}; 3 trades")
    box(left, .02, .61, .43, .13, "Restoration description\nFeasible queue-history DAG")
    box(left, .55, .61, .43, .13, "Direct certificate description\nSame sufficient states and DAG")
    arrow(left, .33, .82, .24, .75)
    arrow(left, .67, .82, .76, .75)
    box(left, .12, .37, .76, .15, "Identical shared computation\nBackward terminal viability + min-plus DP", "#deeee7")
    arrow(left, .24, .60, .38, .53)
    arrow(left, .76, .60, .62, .53)
    box(left, .12, .14, .76, .14, "Same cached lower envelope m[t]\nSame robust loss and post/cross answer", "#deeee7")
    arrow(left, .50, .36, .50, .29)
    left.text(.5, .035, "No unmatched operation or measured speed advantage", ha="center", color="#85473c", fontsize=11)
    horizons = list(range(5))
    right.set_title("B  Tiny fixed unit fixture, not a benchmark", loc="left", weight="bold", pad=18)
    right.plot(horizons, fixture["lower"], "o-", color="#167b66", lw=2.5, label="Exact lower service m[t]")
    right.plot(horizons, fixture["upper"], "s--", color="#426ca5", lw=1.8, label="Exact upper service (boundary check)")
    right.plot(horizons, fixture["unpruned_lower"], "x:", color="#b15d45", lw=1.5, label="Ignoring terminal viability")
    right.set(xlabel="Horizon (number of unit decrements)", ylabel="Cumulative shadow service (synthetic units)",
              xticks=horizons, yticks=range(4), ylim=(-.18, 3.5))
    right.grid(alpha=.15)
    right.text(.04, .96, "11 feasible histories\n135 exact query checks; 2 exact ties\nMinimum at final horizon = 1", transform=right.transAxes, va="top", linespacing=1.5)
    right.legend(loc="lower left", bbox_to_anchor=(-.03, - .27), fontsize=10, frameon=False)
    fig.text(.5, .025, "Retrospective conditional shadow-service certificate. No empirical coverage, causal order-insertion claim or fitted experiment.", ha="center", fontsize=10.5, color="#536474")
    fig.subplots_adjust(left=.04, right=.98, bottom=.22, top=.86, wspace=.28)
    fig.savefig(ROOT / "main_figure.png", dpi=180, facecolor="white")
    fig.savefig(ROOT / "main_figure.svg", facecolor="white")
    plt.close(fig)
    template = '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>E-254 exact certificate identity</title><style>body{max-width:1100px;margin:32px auto;padding:0 24px;font:17px/1.5 system-ui;color:#183247}img{width:100%}section{padding:24px;background:#eef4f7;border-radius:10px}label{display:inline-block;margin:8px 16px 8px 0}select{font:inherit;padding:6px}output{display:block;margin-top:20px;padding:16px;background:white}details{margin:22px 0}</style>
<h1>One reusable certificate, the same direct compiler</h1><p>E-254 / T-012 r4. Exact constructed software fixtures; no fitted experiment, performance benchmark or market observation.</p>
<img src="main_figure.svg" alt="Shared compiler mapping and exact service envelopes">
<section><h2>Explore the 135 saved exact queries</h2><p>Every displayed value is read from the rational-arithmetic check output. No model is fitted or simulated in this page.</p>
<label>Horizon <select id="h">__HORIZONS__</select></label><label>Order size <select id="v">__SIZES__</select></label>
<label>Loss <select id="g"><option>linear</option><option>square</option><option>miss</option></select></label>
<label>Crossing loss <select id="c"><option>1/4</option><option selected>1/2</option><option>3/4</option></select></label><output id="result"></output></section>
<details open><summary><b>What the equality means</b></summary><p>For a nonempty feasible-history set and nondecreasing shortfall loss g, the worst post loss is g(1 − min(size,m[horizon])/size). A direct compiler can use the same complete queue states, terminal constraints, viability pass and min-plus recursion. Enumeration is a small independent oracle, not the computational comparator.</p></details>
<details><summary><b>What the certificate does not establish</b></summary><p>Truth must belong to the stipulated feasible set. The completed tape and terminal trade count make this retrospective. Adaptive query selection within the frozen family is covered by the same pointwise implication; changed observations, priority, quote time or impact require a new contract. Coordinate minima need not form a joint history. Robust loss, minimax regret, empirical coverage and causal forecasting are distinct.</p></details>
<p><a href="report.pdf">PDF report</a> · <a href="candidate-spec.md">Exact contract</a> · <a href="primary_queries.csv">Saved rational queries</a> · <a href="synthetic_examples.csv">Traceable synthetic examples</a></p>
<script>const rows=__ROWS__;const ui=Object.fromEntries(['h','v','g','c','result'].map(id=>[id,document.getElementById(id)]));function update(){const q=rows.find(r=>r.horizon===ui.h.value&&r.size===ui.v.value&&r.loss===ui.g.value&&r.cross_cost===ui.c.value);ui.result.textContent=`Enumeration: ${q.enumerated_worst_loss} | Shared certificate: ${q.compiled_bound} | Action: ${q.action} | Exact tie: ${q.tie}`;}for(const id of ['h','v','g','c'])ui[id].addEventListener('change',update);update();</script></html>'''
    template = template.replace("__ROWS__", json.dumps(queries))
    template = template.replace("__HORIZONS__", "".join(f'<option>{x}</option>' for x in range(5)))
    template = template.replace("__SIZES__", "".join(f'<option>{x}</option>' for x in (1, 2, 3)))
    (ROOT / "query-explorer.html").write_text(template, encoding="utf-8")
    (ROOT / "figure_metadata.json").write_text(json.dumps({"inputs": ["exact-checks.json", "primary_queries.csv"],
          "type": "Exact unit-fixture evidence and operation mapping", "performance_comparison": False}, indent=2) + "\n")


if __name__ == "__main__":
    main()
