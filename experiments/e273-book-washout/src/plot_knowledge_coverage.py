"""Build T-023 knowledge-coverage proxies from the sealed 11-hour metrics."""
from __future__ import annotations

import csv
import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from mpl_toolkits.axes_grid1.inset_locator import inset_axes
from plotly.subplots import make_subplots
import plotly.graph_objects as go


OUT = (Path(__file__).resolve().parents[1] / 'runtime')
if not OUT.exists():
    OUT = (Path(__file__).resolve().parents[1] / 'runtime')
WORKTREE_CODE = (Path(__file__).resolve().parents[1] / 'src')
if not WORKTREE_CODE.exists():
    WORKTREE_CODE = (Path(__file__).resolve().parents[1] / 'src')
SOURCE = OUT / "hourly_metrics.csv"
CHECKPOINT = OUT / "checkpoint.json"
MANIFEST = OUT / "manifest.json"
FINAL_LEGACY_TOTAL = 11_328
START = datetime(2025, 12, 1, tzinfo=timezone.utc)
ANOMALY_COLUMNS = [
    "anomaly_events", "duplicate_new_live", "new_after_remove", "update_after_remove",
    "remove_after_remove", "origSz_mismatch", "identity_changed",
]
BLUE = "#2563EB"
ORANGE = "#F59E0B"
TEAL = "#0F766E"
PURPLE = "#7C3AED"
INK = "#172033"
MUTED = "#5D687A"
GRID = "#DCE2EA"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_and_validate():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    checkpoint = json.loads(CHECKPOINT.read_text(encoding="utf-8"))
    with SOURCE.open(encoding="utf-8", newline="") as source:
        rows = list(csv.DictReader(source))
    assert manifest["operational_decision"] == "incomplete"
    assert len(rows) == int(manifest["completed_hours"]) == int(checkpoint["completed_hours"]) == 11
    assert [int(row["hour"]) for row in rows] == list(range(11))
    assert all(int(row[column]) == 0 for row in rows for column in ANOMALY_COLUMNS)

    coverage = []
    cumulative_new = 0
    cumulative_legacy = 0
    for hour_end, row in enumerate(rows, 1):
        assert int(row["legacy_total"]) == int(row["legacy_update"]) + int(row["legacy_remove"])
        assert int(row["btc_events"]) == sum(int(row[f"{kind}_events"]) for kind in ("new", "update", "remove"))
        cumulative_new += int(row["new_events"])
        cumulative_legacy += int(row["legacy_total"])
        cumulative_all = cumulative_new + cumulative_legacy
        assert cumulative_all == int(row["ever_seen_oids"])
        coverage.append({
            "timeline_hour_end": hour_end,
            "utc_end": (START + timedelta(hours=hour_end)).isoformat(),
            "source_hour_index": int(row["hour"]),
            "state": "complete_observed_hour",
            "hourly_btc_events": int(row["btc_events"]),
            "hourly_new_events": int(row["new_events"]),
            "hourly_legacy_update": int(row["legacy_update"]),
            "hourly_legacy_remove": int(row["legacy_remove"]),
            "hourly_legacy_total": int(row["legacy_total"]),
            "legacy_per_million_btc_events": float(row["legacy_per_million_btc_events"]),
            "cumulative_first_seen_new_oids": cumulative_new,
            "cumulative_legacy_oids": cumulative_legacy,
            "cumulative_all_first_seen_oids": cumulative_all,
            "reported_ever_seen_oids": int(row["ever_seen_oids"]),
            "observed_lifecycle_coverage_pct": 100 * cumulative_new / cumulative_all,
            "legacy_cohort_discovery_saturation_pct": 100 * cumulative_legacy / FINAL_LEGACY_TOTAL,
        })
    assert cumulative_legacy == FINAL_LEGACY_TOTAL == int(manifest["metrics"]["first_seen_legacy_total"])
    assert cumulative_all == int(checkpoint["seen_count"])
    return manifest, checkpoint, rows, coverage


def write_csv(coverage):
    fields = list(coverage[0])
    pre = {field: "" for field in fields}
    pre.update(
        timeline_hour_end=0,
        utc_end=START.isoformat(),
        state="pre_replay_origin",
        cumulative_first_seen_new_oids=0,
        cumulative_legacy_oids=0,
        cumulative_all_first_seen_oids=0,
        legacy_cohort_discovery_saturation_pct=0.0,
    )
    # Observed-lifecycle coverage is intentionally blank here: 0/0 is undefined.
    with (OUT / "knowledge_coverage_by_hour.csv").open("w", encoding="utf-8", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=fields)
        writer.writeheader()
        writer.writerow(pre)
        writer.writerows(coverage)


def style_axis(axis):
    axis.spines[["top", "right"]].set_visible(False)
    axis.grid(axis="y", color=GRID, linewidth=0.8, zorder=0)
    axis.tick_params(colors=INK)
    axis.xaxis.label.set_color(INK)
    axis.yaxis.label.set_color(INK)


def draw_static(rows, coverage):
    hours = [int(row["hour"]) for row in rows]
    updates = [int(row["legacy_update"]) for row in rows]
    removes = [int(row["legacy_remove"]) for row in rows]
    totals = [u + r for u, r in zip(updates, removes)]
    ends = [point["timeline_hour_end"] for point in coverage]
    causal = [point["observed_lifecycle_coverage_pct"] for point in coverage]
    saturation = [0.0] + [point["legacy_cohort_discovery_saturation_pct"] for point in coverage]

    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10.5})
    fig = plt.figure(figsize=(15, 10), facecolor="white")
    grid = fig.add_gridspec(2, 2, height_ratios=[1.15, 1], hspace=0.46, wspace=0.22,
                           left=0.065, right=0.98, top=0.84, bottom=0.115)
    bars = fig.add_subplot(grid[0, :])
    causal_axis = fig.add_subplot(grid[1, 0])
    cohort_axis = fig.add_subplot(grid[1, 1])
    fig.suptitle("Legacy OIDs are still revealed in the 11th completed hour",
                 x=0.065, y=0.965, ha="left", fontsize=20, weight="bold", color=INK)
    fig.text(0.065, 0.91,
             "Observed-lifecycle coverage reaches 99.929849%, but it is not full-book completeness: silent initial orders keep the true denominator unknown.",
             fontsize=12, color=MUTED)

    bars.bar(hours, updates, color=BLUE, width=0.72, label="First seen by update", zorder=3)
    bars.bar(hours, removes, bottom=updates, color=ORANGE, width=0.72, label="First seen by remove", zorder=3)
    for hour, total in zip(hours, totals):
        bars.text(hour, total + 105, f"{total:,}", ha="center", va="bottom", fontsize=9, color=INK)
    bars.set_title("A · Newly revealed legacy OIDs by source hour", loc="left", fontsize=13, weight="bold", color=INK)
    bars.set(xlabel="Source hour index (0 = 00:00–01:00 UTC)", ylabel="Legacy OIDs first revealed")
    bars.set_xticks(hours)
    bars.set_ylim(0, 8_200)
    bars.legend(frameon=False, ncols=2, loc="upper right")
    style_axis(bars)

    detail = inset_axes(bars, width="46%", height="48%", loc="upper center", borderpad=1.5)
    detail.bar(hours[1:], updates[1:], color=BLUE, width=0.66)
    detail.bar(hours[1:], removes[1:], bottom=updates[1:], color=ORANGE, width=0.66)
    detail.set_title("Hours 1–10 detail", fontsize=9, weight="bold", color=INK)
    detail.set_xticks(hours[1:])
    detail.set_ylim(0, 900)
    detail.grid(axis="y", color=GRID, linewidth=0.6)
    detail.tick_params(labelsize=7.5, colors=INK)
    detail.spines[["top", "right"]].set_visible(False)

    causal_axis.plot(ends, causal, color=TEAL, linewidth=2.5, marker="o", markersize=5, zorder=3)
    causal_axis.fill_between(ends, causal, min(causal) - 0.03, color=TEAL, alpha=0.1)
    causal_axis.annotate(f"{causal[-1]:.6f}%", xy=(11, causal[-1]), xytext=(8.4, causal[-1] - 0.042),
                         arrowprops={"arrowstyle": "->", "color": TEAL}, color=TEAL, weight="bold")
    causal_axis.text(0.03, 0.08, "Pre-replay: undefined (0 / 0)", transform=causal_axis.transAxes,
                     color=MUTED, fontsize=9)
    causal_axis.set_title("B · Causal observed-lifecycle coverage", loc="left", fontsize=13, weight="bold", color=INK)
    causal_axis.set(xlabel="Complete hours replayed", ylabel="First-seen-new share of observed OIDs (%)",
                    xlim=(0, 11.4), ylim=(99.65, 100.0))
    causal_axis.set_xticks(range(0, 12))
    causal_axis.text(0.99, 0.02, "Zoomed y-axis", transform=causal_axis.transAxes, ha="right", color=MUTED, fontsize=8.5)
    style_axis(causal_axis)

    cohort_axis.plot(range(12), saturation, color=PURPLE, linewidth=2.5, marker="o", markersize=5, zorder=3)
    cohort_axis.fill_between(range(12), saturation, 0, color=PURPLE, alpha=0.1)
    cohort_axis.annotate("100% by construction", xy=(11, 100), xytext=(7.1, 82),
                         arrowprops={"arrowstyle": "->", "color": PURPLE}, color=PURPLE, weight="bold")
    cohort_axis.set_title("C · Post-hoc 11-hour legacy-cohort saturation", loc="left", fontsize=13, weight="bold", color=INK)
    cohort_axis.set(xlabel="Complete hours replayed", ylabel="Legacy-cohort saturation (%)",
                    xlim=(0, 11.4), ylim=(0, 104))
    cohort_axis.set_xticks(range(0, 12))
    cohort_axis.text(0.02, 0.06, "Retrospective denominator = 11,328\nNot knowable causally at earlier hours",
                     transform=cohort_axis.transAxes, color=MUTED, fontsize=9)
    style_axis(cohort_axis)

    fig.text(0.065, 0.035,
             "T-023 / E-273 · 11 complete hours; intended hours 11–47 remain unobserved · Decision stays INCOMPLETE.\n"
             "Observed-lifecycle coverage includes removed orders and cannot identify what fraction of the current live book is known.",
             color=MUTED, fontsize=10)
    fig.savefig(OUT / "knowledge_coverage_by_hour.png", dpi=180, facecolor="white")
    plt.close(fig)


def draw_html(rows, coverage):
    hours = [int(row["hour"]) for row in rows]
    updates = [int(row["legacy_update"]) for row in rows]
    removes = [int(row["legacy_remove"]) for row in rows]
    ends = [point["timeline_hour_end"] for point in coverage]
    causal = [point["observed_lifecycle_coverage_pct"] for point in coverage]
    saturation = [0.0] + [point["legacy_cohort_discovery_saturation_pct"] for point in coverage]
    figure = make_subplots(rows=2, cols=2, specs=[[{"colspan": 2}, None], [{}, {}]],
                           subplot_titles=("A · Newly revealed legacy OIDs", "B · Causal observed-lifecycle coverage",
                                           "C · Post-hoc 11-hour legacy-cohort saturation"),
                           vertical_spacing=0.19, horizontal_spacing=0.1)
    figure.add_bar(x=hours, y=updates, name="First seen by update", marker_color=BLUE,
                   hovertemplate="Source hour %{x}<br>%{y:,} legacy OIDs<extra>First seen by update</extra>", row=1, col=1)
    figure.add_bar(x=hours, y=removes, name="First seen by remove", marker_color=ORANGE,
                   hovertemplate="Source hour %{x}<br>%{y:,} legacy OIDs<extra>First seen by remove</extra>", row=1, col=1)
    figure.add_scatter(x=ends, y=causal, name="Observed-lifecycle coverage", mode="lines+markers",
                       line={"color": TEAL, "width": 3}, marker={"size": 7},
                       hovertemplate="%{x} complete hours<br>%{y:.9f}%<extra>Causal observed-lifecycle proxy</extra>", row=2, col=1)
    figure.add_scatter(x=list(range(12)), y=saturation, name="Post-hoc cohort saturation", mode="lines+markers",
                       line={"color": PURPLE, "width": 3}, marker={"size": 7},
                       hovertemplate="%{x} complete hours<br>%{y:.9f}%<extra>Post-hoc 11-hour cohort</extra>", row=2, col=2)
    figure.update_layout(
        barmode="stack", template="plotly_white", height=900,
        title={"text": "11-hour replay: observed knowledge-coverage proxies"
                       "<br><sup>Neither proxy is full-book completeness; silent initial orders make the true denominator unknown.</sup>"},
        legend={"orientation": "h", "y": -0.1}, margin={"l": 75, "r": 35, "t": 125, "b": 130},
        annotations=list(figure.layout.annotations) + [
            {"text": "Endpoint: 99.929849%", "x": 11, "y": causal[-1], "xref": "x2", "yref": "y2",
             "showarrow": True, "arrowhead": 2, "ax": -90, "ay": 35, "font": {"color": TEAL}},
            {"text": "100% by construction", "x": 11, "y": 100, "xref": "x3", "yref": "y3",
             "showarrow": True, "arrowhead": 2, "ax": -100, "ay": 45, "font": {"color": PURPLE}},
            {"text": "Pre-replay causal ratio is undefined (0/0). Post-hoc saturation starts at 0%. "
                     "Hours 11–47 are unobserved; E-273 remains INCOMPLETE.",
             "x": 0, "y": -0.19, "xref": "paper", "yref": "paper", "showarrow": False, "xanchor": "left",
             "align": "left", "font": {"color": MUTED, "size": 12}},
        ],
    )
    figure.update_xaxes(title_text="Source hour index", dtick=1, row=1, col=1)
    figure.update_yaxes(title_text="Legacy OIDs first revealed", row=1, col=1)
    figure.update_xaxes(title_text="Complete hours replayed", dtick=1, range=[0, 11.4], row=2, col=1)
    figure.update_yaxes(title_text="First seen via new / all observed (%)", range=[99.65, 100], row=2, col=1)
    figure.update_xaxes(title_text="Complete hours replayed", dtick=1, range=[0, 11.4], row=2, col=2)
    figure.update_yaxes(title_text="Revealed / final 11-hour legacy cohort (%)", range=[0, 104], row=2, col=2)
    figure.write_html(OUT / "knowledge_coverage_by_hour.html", include_plotlyjs=True, full_html=True,
                      config={"responsive": True, "displaylogo": False})


def write_note(coverage, manifest):
    end = coverage[-1]
    note = f"""# T-023 observed knowledge-coverage follow-up

## ELI5

The replay begins in the middle of an ongoing market. An order first seen through `new` is like seeing a person enter a room: its observable story starts at the beginning. An order first seen through `update` or `remove` is like first noticing someone when they move or leave: they were already present before observation began.

The **causal observed-lifecycle coverage** asks: among every OID observed so far, what fraction first appeared through `new`? It does not look into the future. After 11 complete hours, the answer is **{end['observed_lifecycle_coverage_pct']:.9f}%**: **{end['cumulative_first_seen_new_oids']:,} / {end['cumulative_all_first_seen_oids']:,}**. Its complement, **{100 - end['observed_lifecycle_coverage_pct']:.9f}%**, consists of the {end['cumulative_legacy_oids']:,} OIDs first revealed through `update` or `remove`.

The **11-hour legacy-cohort discovery saturation** asks a different, retrospective question: what fraction of all {FINAL_LEGACY_TOTAL:,} legacy OIDs that were eventually observed in this sealed 11-hour prefix had been discovered by each earlier hour? It reaches **100.000000000%** at hour 11 by construction. Earlier values use a denominator that was unavailable at those earlier times, so this curve is explicitly post-hoc and conditional on stopping after 11 hours.

## Why `new_events` equals first-seen-new here

The replay increments `new_events` for every `new` event, checks whether its OID was already in the persistent `seen` set, and records either `duplicate_new_live` or `new_after_remove` if a `new` OID had been seen before. Across all 11 sealed rows, those anomaly counts and every other transition-anomaly count are zero. Therefore every counted `new` was unseen and cumulative `new_events` is exactly the cumulative first-seen-new count.

The arithmetic independently reconciles at every hour end:

`cumulative new_events + cumulative legacy_total = reported ever_seen_oids`

At the endpoint, **{end['cumulative_first_seen_new_oids']:,} + {end['cumulative_legacy_oids']:,} = {end['cumulative_all_first_seen_oids']:,}**, matching the sealed checkpoint's `seen_count`.

## What neither percentage means

Neither curve estimates the percentage of the full live book known. Initial orders that remain unchanged throughout the prefix never emit a diff, so they are absent from both numerator and denominator. The number of such silent orders is unknown. The observed-lifecycle proxy also includes OIDs that were later removed, so it is not current-live-book coverage.

Hours 11–47 remain unobserved, and the experiment decision remains **{manifest['operational_decision'].upper()}**. The pre-replay causal ratio is `0/0` and therefore undefined; only the retrospective saturation curve has a valid 0% origin.

## Exact endpoints

- Causal observed-lifecycle coverage: **{end['observed_lifecycle_coverage_pct']:.9f}%**.
- Retrospective 11-hour legacy-cohort discovery saturation: **{end['legacy_cohort_discovery_saturation_pct']:.9f}%**.
- True full-live-book knowledge percentage: **not identifiable from this diff prefix**.
"""
    (OUT / "KNOWLEDGE_COVERAGE.md").write_text(note, encoding="utf-8")


def update_manifest(manifest, coverage):
    code_target = OUT / "code/plot_knowledge_coverage.py"
    code_target.parent.mkdir(exist_ok=True)
    shutil.copy2(Path(__file__), code_target)
    end = coverage[-1]
    new_artifacts = [
        "knowledge_coverage_by_hour.png", "knowledge_coverage_by_hour.html",
        "knowledge_coverage_by_hour.csv", "KNOWLEDGE_COVERAGE.md", "code/plot_knowledge_coverage.py",
    ]
    for name in new_artifacts:
        path = OUT / name
        manifest["artifacts"][name] = {"bytes": path.stat().st_size, "sha256": sha256(path)}
    manifest["knowledge_coverage_follow_up"] = {
        "source": "sealed hourly_metrics.csv and checkpoint.json only",
        "hourly_metrics_sha256": sha256(SOURCE),
        "checkpoint_sha256": sha256(CHECKPOINT),
        "complete_hours": 11,
        "cumulative_first_seen_new_oids": end["cumulative_first_seen_new_oids"],
        "cumulative_legacy_oids": end["cumulative_legacy_oids"],
        "cumulative_all_first_seen_oids": end["cumulative_all_first_seen_oids"],
        "observed_lifecycle_coverage_pct": end["observed_lifecycle_coverage_pct"],
        "legacy_cohort_discovery_saturation_pct": end["legacy_cohort_discovery_saturation_pct"],
        "first_seen_new_justification": "all duplicate/impossible transition counters are zero and cumulative identity reconciles each hour",
        "causal_pre_replay_value": None,
        "causal_pre_replay_reason": "undefined 0/0",
        "true_full_live_book_knowledge_pct": None,
        "true_full_live_book_knowledge_reason": "silent initial orders and their denominator are unobserved",
        "decision_unchanged": manifest["operational_decision"] == "incomplete",
        "implementation_commit": subprocess.check_output(
            ["git", "-C", str(WORKTREE_CODE.parents[1]), "rev-parse", "HEAD"], text=True
        ).strip(),
    }
    manifest["knowledge_coverage_follow_up_utc"] = datetime.now(timezone.utc).isoformat()
    other_bytes = sum(path.stat().st_size for path in OUT.rglob("*") if path.is_file() and path != MANIFEST)
    for _ in range(10):
        encoded = (json.dumps(manifest, indent=2) + "\n").encode("utf-8")
        retained = other_bytes + len(encoded)
        if manifest.get("retained_bytes_after_knowledge_coverage") == retained:
            break
        manifest["retained_bytes_after_knowledge_coverage"] = retained
    MANIFEST.write_bytes((json.dumps(manifest, indent=2) + "\n").encode("utf-8"))
    assert manifest["retained_bytes_after_knowledge_coverage"] == sum(
        path.stat().st_size for path in OUT.rglob("*") if path.is_file()
    )


def main():
    manifest, _, rows, coverage = load_and_validate()
    write_csv(coverage)
    draw_static(rows, coverage)
    draw_html(rows, coverage)
    write_note(coverage, manifest)
    update_manifest(manifest, coverage)
    end = coverage[-1]
    print(json.dumps({
        "complete_hours": len(rows),
        "first_seen_new": end["cumulative_first_seen_new_oids"],
        "legacy": end["cumulative_legacy_oids"],
        "all_first_seen": end["cumulative_all_first_seen_oids"],
        "observed_lifecycle_coverage_pct": end["observed_lifecycle_coverage_pct"],
        "posthoc_legacy_saturation_pct": end["legacy_cohort_discovery_saturation_pct"],
        "decision": manifest["operational_decision"],
    }, indent=2))


if __name__ == "__main__":
    main()
