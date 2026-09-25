"""Render the same-prefix clock-coverage diagnostic from its recorded JSON."""
from pathlib import Path
import json
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

ROOT=Path(__file__).resolve().parents[1]/"runtime"
data=json.loads((ROOT/"clock_coverage.json").read_text())
total=data["btc_diff_rows"]
values=[data["naive_point_candidate_rows"],data["point_candidate_rows"]]
plt.rcParams.update({"font.family":"DejaVu Sans","font.size":12,"svg.fonttype":"none"})
fig=plt.figure(figsize=(12,6),facecolor="#F7F8FA")
fig.text(.055,.93,"OFFLINE DATA DIAGNOSTIC",fontsize=11,weight="bold",color="#986411")
fig.text(.055,.85,"1,777 additional timestamp candidates",fontsize=24,weight="bold",color="#12233A")
fig.text(.055,.795,"Same 91,868 BTC book changes · first 200,000 original interleaved diff lines",fontsize=12,color="#526173")
ax=fig.add_axes([.21,.455,.58,.27],facecolor="#F7F8FA")
colors=["#7291B7","#155FBA"]
for i,(value,color) in enumerate(zip(values,colors)):
    y=1-i
    ax.barh(y,100,color="#E2E6EB",height=.38)
    ax.barh(y,100*value/total,color=color,height=.38)
    ax.text(101.5,y,f"{100*value/total:.4f}%",va="center",fontsize=15,weight="bold",color="#12233A")
    ax.text(3,y,f"{value:,} / {total:,}",va="center",color="white",fontsize=12,weight="bold")
ax.set_yticks([1,0],["Status-only\njoin", "Trade-assisted\njoin"])
ax.set_xlim(0,100);ax.set_ylim(-.5,1.5)
ax.set_xticks([0,25,50,75,100]);ax.set_xlabel("Point timestamp candidates (%)",fontsize=10,color="#526173")
ax.tick_params(axis="both",length=0,labelcolor="#526173",pad=8)
for spine in ax.spines.values():spine.set_visible(False)
box=FancyBboxPatch((.055,.15),.89,.17,boxstyle="round,pad=0.012,rounding_size=0.018",transform=fig.transFigure,facecolor="#FFF0D8",edgecolor="#E9C589",linewidth=.8)
fig.add_artist(box)
fig.text(.075,.267,"REMAINING GATES",fontsize=10,weight="bold",color="#85590E")
fig.text(.075,.213,"8 unmatched updates   ·   1 time inversion (182.85 ms)   ·   Initial state uncertified",fontsize=13,color="#5D430F",weight="bold")
fig.text(.055,.075,"NO MARKET PERFORMANCE RESULT  ·  Offline matching does not certify causal data availability.",fontsize=10.3,color="#7A3C34",weight="bold")
fig.savefig(ROOT/"clock_coverage_progress.png",dpi=180,facecolor=fig.get_facecolor())
fig.savefig(ROOT/"clock_coverage_progress.svg",facecolor=fig.get_facecolor())
plt.close(fig)
print("rendered clock_coverage_progress.png and .svg")
