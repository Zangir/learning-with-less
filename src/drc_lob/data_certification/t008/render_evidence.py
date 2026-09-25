"""Render the T-008 diagnostic figure and non-identifying real examples."""
from pathlib import Path
from datetime import datetime, timezone
import csv
import json
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "evidence"
r = json.loads((DATA / "clock_forensics.json").read_text())
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 11, "axes.spines.top": False,
                     "axes.spines.right": False, "savefig.facecolor": "white"})
fig, axes = plt.subplots(1, 2, figsize=(13, 5.8), gridspec_kw={"width_ratios": [1, 1.2]})
fig.subplots_adjust(top=.76, bottom=.29, left=.075, right=.97, wspace=.48)
fig.suptitle("Clock coverage is not a replay certificate", x=.075, ha="left", fontsize=21, fontweight="bold")
fig.text(.075, .87, "T-008 | Real BTC development data | Nominal December 1, 2025 hour 0", fontsize=12, color="#475569")
ax = axes[0]
labels = ["No trades in acquired hour", "Only later trades of residual"]
values = [7, 1]
ax.barh([0, 1], values[::-1], color=["#64748b", "#b45309"], height=.42)
ax.set_yticks([])
for y, label in enumerate(labels[::-1]):
    ax.text(.05, y + .3, label, fontsize=10, va="bottom")
ax.set_ylim(-.4, 1.6)
for y, value in enumerate(values[::-1]):
    ax.text(value+.12, y, str(value), va="center", fontweight="bold")
ax.set_xlim(0, 8)
ax.set_xticks(range(0,9,2))
ax.set_xlabel("Orders among the eight unmatched updates")
ax.set_title("A  Quantity reductions are not automatically fills", loc="left", pad=18, fontsize=12)
ax.grid(axis="x", alpha=.15)
ax.set_axisbelow(True)
ax = axes[1]
times = [.438936879, .621791702, .701285964]
ys = [2, 1, 0]
names = ["Stop-limit open status", "Preceding diff: removal", "Stop-limit triggered status"]
colors = ["#b45309", "#334155", "#0f766e"]
for t,y,label,color in zip(times,ys,names,colors):
    ax.scatter(t*1000,y,s=90,color=color,zorder=3)
    ax.text(t*1000,y+.19,label,ha="center",fontsize=10,color=color)
ax.plot([times[1]*1000,times[0]*1000],[1,2],ls="--",color="#b45309")
ax.plot([times[1]*1000,times[2]*1000],[1,0],ls=":",color="#0f766e")
ax.text(548, 1.62, "legacy: -182.855 ms", fontsize=10, color="#b45309", rotation=0)
ax.text(663, .63, "trigger candidate", fontsize=9, color="#0f766e",ha="center")
ax.set_xlim(380,775)
ax.set_ylim(-.35,2.5)
ax.set_yticks([])
ax.set_xlabel("Milliseconds after 2025-12-01 00:01:27 UTC")
ax.set_title("B  Lifecycle state changes the time interpretation", loc="left", pad=18, fontsize=12)
ax.grid(axis="x",alpha=.15)
fig.text(.075,.13,"Q16 queue episodes: uncertified     Q17 BBO windows: uncertified     Q18 top-five windows: uncertified",
         fontsize=12,fontweight="bold",color="#991b1b")
fig.text(.075,.07,"No receipt clock or initial checkpoint. Trigger substitution is a matching diagnostic.\n"
         "Original source order and legacy inversion retained; no model or market-performance estimate.",fontsize=10,color="#475569")
fig.savefig(ROOT / "main_figure.png",dpi=180)
fig.savefig(ROOT / "main_figure.svg")
plt.close(fig)
figure_data={"quantity_reduction_categories":{"no_trades_in_acquired_hour":7,"only_later_residual_trades":1},
 "inversion_timestamps_ns":[1764547287438936879,1764547287621791702,1764547287701285964],
 "legacy_backward_ns":182854823,"source":"evidence/clock_forensics.json",
 "interpretation":"Observed lifecycle diagnostic; no final event/receipt clock or replay certification."}
(ROOT / "main_figure_data.json").write_text(json.dumps(figure_data,indent=2)+"\n")
examples=[]
for row in [r["missing_updates"][0],r["missing_updates"][1]]:
    examples.append({"source_file":"book_diffs_20251201_00.gz","zero_based_row":row["raw_diff_index"],
      "kind":row["kind"],"side":row["side"],"price_usd_per_btc":row["price_usd"],
      "old_size_btc":format(row["original_size_units_1e8_btc"]/100_000_000,".8f"),
      "new_size_btc":format(row["new_size_units_1e8_btc"]/100_000_000,".8f"),
      "event_time_utc":"","note":"No corresponding recorded execution; exact event time uncertified."})
row=r["clock_reversals"][0]["current"]
examples.append({"source_file":"book_diffs_20251201_00.gz","zero_based_row":row["raw_diff_index"],
 "kind":"new","side":row["side"],"price_usd_per_btc":row["price_usd"],"old_size_btc":"",
 "new_size_btc":format(row["new_size_units_1e8_btc"]/100_000_000,".8f"),
 "event_time_utc":"","note":"Stop-limit: open 00:01:27.438936879; triggered 00:01:27.701285964 UTC, Dec 1; neither is receipt time."})
with (ROOT/"sample_rows.csv").open("w",newline="") as out:
    writer=csv.DictWriter(out,fieldnames=examples[0].keys())
    writer.writeheader()
    writer.writerows(examples)
html="""<!doctype html><html lang="en"><meta charset="utf-8"><title>T-008 clock and replay gate</title>
<style>body{font-family:system-ui;max-width:1200px;margin:40px auto;padding:0 24px;color:#172033}
img{width:100%}table{border-collapse:collapse;font-size:14px}td,th{padding:10px;border:1px solid #cbd5e1}
th{background:#172033;color:white}p{line-height:1.5}</style><h1>T-008: Clock and replay certification</h1>
<p>These are development-data diagnostics. No Q16/Q17/Q18 real-market scope is certified.</p>
<img src="main_figure.svg" alt="Quantity reductions without trades and stop-limit timestamp interpretation">
<h2>Non-identifying real sample rows</h2><p>Prices: USD per BTC. Sizes: BTC. Rows: zero-based within the frozen T-001 member.
Empty event time means unavailable as a certified timestamp. Source hashes and provenance: manifest.json.</p>"""
import html as html_module
html+="<table><tr>"+"".join("<th>"+html_module.escape(k)+"</th>" for k in examples[0])+"</tr>"
for row in examples:
    html+="<tr>"+"".join("<td>"+html_module.escape(str(v))+"</td>" for v in row.values())+"</tr>"
html+="</table><p><a href='shared_data_contract.json'>Machine contract</a> · <a href='report.md'>Full evidence report</a> · <a href='main_figure_data.json'>Figure data</a></p></html>"
(ROOT/"index.html").write_text(html,encoding="utf-8")
print("Rendered main_figure.png/svg, main_figure_data.json, sample_rows.csv, index.html")
