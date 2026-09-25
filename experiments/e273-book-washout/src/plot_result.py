"""Render the frozen T-023 hourly discovery plot from the verified hourly CSV."""

import csv
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch


OUT = (Path(__file__).resolve().parents[1] / 'runtime')
if not OUT.exists():
    OUT = (Path(__file__).resolve().parents[1] / 'runtime')


def main():
    manifest = json.loads((OUT / "manifest.json").read_text(encoding="utf-8"))
    with (OUT / "hourly_metrics.csv").open(encoding="utf-8", newline="") as source:
        rows = list(csv.DictReader(source))
    hours = [int(row["hour"]) for row in rows]
    completed = int(manifest["completed_hours"])
    if hours != list(range(completed)):
        raise ValueError("CSV must contain exactly the manifest's complete chronological prefix")
    updates = [int(row["legacy_update"]) for row in rows]
    removes = [int(row["legacy_remove"]) for row in rows]
    if any(u + r != int(row["legacy_total"]) for u, r, row in zip(updates, removes, rows)):
        raise ValueError("Legacy counts do not reconcile")
    decision = str(manifest["operational_decision"]).upper()
    subtitle = f"{completed}/48 complete hours | 24+24 h operational test: {decision} | No full-book certificate"
    centers = [hour + 0.5 for hour in hours]
    blue, orange = "#176B99", "#E89C42"
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 11})
    fig, ax = plt.subplots(figsize=(12, 6.5))
    fig.subplots_adjust(left=0.075, right=0.985, top=0.82, bottom=0.23)
    fig.suptitle("BTC: first-seen legacy orders during empty-book replay", fontsize=17, weight="bold")
    ax.set_title(subtitle, fontsize=11, pad=20)
    ax.axvspan(24, 48, color="#EDF4F8", zorder=0)
    if completed < 48:
        ax.axvspan(completed, 48, facecolor="#E3E4E6", edgecolor="#B9BDC2", hatch="///", zorder=1)
    ax.bar(centers, updates, width=0.84, color=blue, label="First seen as update", zorder=3)
    ax.bar(centers, removes, width=0.84, bottom=updates, color=orange, label="First seen as remove", zorder=3)
    zeros = [h + 0.5 for h, u, r in zip(hours, updates, removes) if u + r == 0]
    if zeros:
        ax.scatter(zeros, [0] * len(zeros), s=20, marker="o", color="#334155", clip_on=False, zorder=4)
    ax.axvline(24, color="#3F4B58", linestyle="--", linewidth=1.5, zorder=4)
    ax.text(12, 0.97, "Warm-up · hours 0–23", ha="center", va="top", transform=ax.get_xaxis_transform())
    ax.text(36, 0.97, "Holdout · hours 24–47", ha="center", va="top", transform=ax.get_xaxis_transform())
    ax.set(xlim=(0, 48), xlabel="UTC hours since 2025-12-01 00:00", ylabel="First-seen legacy OIDs per hour")
    ax.set_xticks(range(0, 49, 4))
    ax.set_ylim(bottom=0, top=max([u + r for u, r in zip(updates, removes)] + [1]) * 1.28)
    ax.grid(axis="y", color="#CBD5E1", alpha=0.55, zorder=0)
    ax.spines[["top", "right"]].set_visible(False)
    handles, labels = ax.get_legend_handles_labels()
    if completed < 48:
        handles.append(Patch(facecolor="#E3E4E6", edgecolor="#B9BDC2", hatch="///"))
        labels.append("Unobserved / incomplete; not zero")
    fig.legend(handles, labels, loc="lower center", bbox_to_anchor=(0.5, 0.065), ncols=3, frameon=False)
    fig.text(0.02, 0.012, "T-023 / E-273 · Fixed window: Dec 1–3, 2025 UTC · Bars include only complete, gzip-verified members.\n"
             "A quiet diff prefix cannot rule out unchanged orders already resting before replay began.", fontsize=9, color="#475569")
    fig.savefig(OUT / "legacy_by_hour.png", dpi=180, facecolor="white")
    plt.close(fig)
    try:
        import plotly.graph_objects as go
    except ImportError:
        return
    chart = go.Figure()
    for counts, label, color in [(updates, "First seen as update", blue), (removes, "First seen as remove", orange)]:
        chart.add_bar(x=centers, y=counts, name=label, marker_color=color, width=0.84,
                      customdata=hours, hovertemplate="Hour %{customdata}<br>%{y:,} legacy OIDs<extra>%{fullData.name}</extra>")
    chart.add_vrect(x0=24, x1=48, fillcolor="#EDF4F8", line_width=0, layer="below")
    if completed < 48:
        chart.add_vrect(x0=completed, x1=48, fillcolor="#D9DCDF", opacity=0.85, line_width=0, layer="below",
                        annotation_text="Unobserved / incomplete ≠ zero", annotation_position="top right")
    chart.add_vline(x=24, line_dash="dash", line_color="#3F4B58")
    chart.update_layout(title={"text": "BTC: first-seen legacy orders<br><sup>" + subtitle + "</sup>"},
                        barmode="stack", template="plotly_white", height=540,
                        xaxis={"title": "UTC hours since 2025-12-01 00:00", "range": [0, 48], "dtick": 4},
                        yaxis={"title": "First-seen legacy OIDs per hour", "rangemode": "tozero"},
                        legend={"orientation": "h", "y": -0.18})
    chart.write_html(OUT / "legacy_by_hour.html", include_plotlyjs=True, full_html=True)
    print(f"Rendered {completed} complete hours: {OUT / 'legacy_by_hour.png'}")


if __name__ == "__main__":
    main()
