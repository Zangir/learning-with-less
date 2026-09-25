"""Render auditable participant-route evidence and a concise report source."""
from pathlib import Path
from datetime import datetime, timezone
import csv, hashlib, json
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import plotly.graph_objects as go

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'r3/participant'
cuts=json.loads((OUT/'actual_cut_summary.json').read_text())
q16=json.loads((OUT/'q16_observable_summary.json').read_text())
coverage=json.loads((OUT/'q16_actual_cut_summary.v3.0.1.json').read_text())['summary']
extension=json.loads((OUT/'q16_extension_contract.v3.json').read_text())
replay=json.loads((OUT/'replay_summary.json').read_text())
activation=json.loads((OUT/'activation_exception.json').read_text())
data=[]
for task in ('Q17','Q18'):
    total=cuts[task]['required_distinct_cuts']
    data.extend([dict(scope=task,evidence='Local checkpoint coverage under premises',count=total,total=total),
                 dict(scope=task,evidence='Equal to strictly past snapshot',count=cuts[task]['exact_replay_equals_strict_past_snapshot'],total=total)])
with (OUT/'main_figure_data.csv').open('w',newline='') as stream:
    writer=csv.DictWriter(stream,fieldnames=list(data[0]));writer.writeheader();writer.writerows(data)
plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10})
fig,ax=plt.subplots(figsize=(10,4.6))
colors=['#246b76','#d29836']
for i,evidence in enumerate(['Local checkpoint coverage under premises','Equal to strictly past snapshot']):
    selected=[r for r in data if r['evidence']==evidence]
    positions=[x+(i-.5)*.3 for x in range(2)]
    values=[100*r['count']/r['total'] for r in selected]
    bars=ax.bar(positions,values,width=.27,label=evidence,color=colors[i])
    for bar,row in zip(bars,selected):
        ax.text(bar.get_x()+bar.get_width()/2,bar.get_height()+2,f"{row['count']}/{row['total']}",ha='center',fontsize=11)
ax.set_xticks([0,1],['Q17: 16 diagnostic decisions','Q18: 112 diagnostic decisions'])
ax.set_ylim(0,122);ax.set_ylabel('Required cut states (%)')
ax.spines[['top','right']].set_visible(False)
ax.legend(loc='upper left',bbox_to_anchor=(0,-.17),frameon=False,ncol=2)
fig.suptitle('Snapshot corroboration does not identify continuously current state',x=.07,ha='left',fontsize=15,weight='bold')
fig.text(.07,.89,'Participant reconstruction remains conditional; every empirical-admission flag is false.',fontsize=10,color='#505050')
fig.subplots_adjust(top=.82,bottom=.27,left=.09,right=.98)
for suffix in ('png','svg','pdf'):fig.savefig(OUT/f'main_figure.{suffix}',dpi=180,bbox_inches='tight')
html=go.Figure()
for i,evidence in enumerate(['Local checkpoint coverage under premises','Equal to strictly past snapshot']):
    selected=[r for r in data if r['evidence']==evidence]
    html.add_bar(name=evidence,x=[r['scope'] for r in selected],y=[100*r['count']/r['total'] for r in selected],
        text=[f"{r['count']}/{r['total']}" for r in selected],customdata=[[r['count'],r['total']] for r in selected],
        hovertemplate='%{x}: %{customdata[0]} of %{customdata[1]} required cuts<extra>%{fullData.name}</extra>',marker_color=colors[i])
html.update_layout(title='Conditional participant reconstruction at required cuts',barmode='group',
    yaxis_title='Required cut states (%)',template='plotly_white',
    annotations=[dict(x=0,y=-.25,xref='paper',yref='paper',showarrow=False,text='All evidence exploratory; no exact timestamp, FIFO, native atomicity or empirical admission claim.')],margin=dict(b=130))
html.write_html(OUT/'main_figure.html',include_plotlyjs=True)
report=f'''# T-008 r3 participant-linked December continuation

Role: Engineer. Seed: 20260919. This continuation preserves all r1/r2 bytes and performs no acquisition or model fitting. The result is a new conditional input route, not an affirmative empirical certificate.

## Exact consumer cuts and state arithmetic

An independent source-order replay processed {replay['counters']['btc_rows']:,} BTC lifecycle rows through the last closed late group. All 3,203 top-five quantity/count states match the frozen r2 reconstruction. The replay also retains top-20 quantities and positive identity counts. Its measured runtime was {replay['runtime_s']:.3f} seconds with {replay['peak_rss_kib']/1024:.1f} MiB peak RSS on one CPU.

The pinned third-party archive claims Hyperliquid collection. Among 549 overlapping late snapshots, compatible candidate states agree on both BBO prefixes in 549 cases, both top-five prefixes in 509, and all twenty levels in 430. These are quantity-and-count comparisons across same-millisecond candidate correspondence or no-change bins; they are not exact nanosecond observations. Common upstream custody remains possible.

The contract preserves the frozen r2 diagnostic decision phase and exports 352 distinct required cuts. Q17 has 16 decisions and 129 distinct feature/target/utility cuts. Its required offsets are 0, -1, -5, -20, +0.1, +0.5, +10, +10.1 and +10.5 seconds. Q18 has 112 decisions, with every one-second support cut from -75 through +10 and the exact +10.5 guard, totaling 309 distinct cuts. All required cuts have local checkpoint price coverage under the stated premises. Five overlapping twelve-opportunity Q17 sequences contain only one disjoint sequence. Neither task has a separately supported fit/selection/evaluation sequence here, so the handoff is for zero-fit feature and provenance diagnostics.

Only 26/129 Q17 and 62/309 Q18 states equal the latest strictly prior snapshot (where the entire millisecond uncertainty bin ends before the cut). Thus snapshot persistence is a distinct observation model. It cannot be silently substituted for conditional reconstructed venue state. The accompanying editable figure and CSV show these denominators explicitly.

## Premises, identifiability and availability

The new schema is `t008-participant-conditional/3`; its atomic-cut kind is `conditional_terminal_group_reconstruction`. It is intentionally incompatible with an affirmative shared producer gate. Every admission flag is false. Normalized rows bind raw participant source ranges and later closure witnesses, preserve exact integer units, and leave release/admission clocks null.

P1 requires complete relevant visible lifecycle and activation observations. P2 requires correct status/trade-to-group correspondence. L1 requires an archived snapshot to correspond to the specified candidate terminal identity state within its coarsened bin. L2 requires retained positive identities and quantities at that checkpoint to be real resting orders. P4 describes offline complete-group observation. Under these premises, exact positive quantity/count agreement excludes extra positive orders inside the matching prefix; later cuts remaining within that price region need no hour-wide trade-through P3 argument. The replacement does not authenticate L1 or P2.

Cross-order assignments commute at a closed terminal group when each order's own lifecycle is preserved. This does not establish intermediate state, native atomic actions, or same-price FIFO. Every required as-of cut's closure witness is later than the cut. A hypothetical exchange-time state and retrospective final support mask therefore cannot become a measured online admission guarantee.

## Q16 requested positions, activation and priority

The consumer's exact 8,895 after-event cuts and 1,000 before-insertion cuts were reproduced independently in positive volume and count without changing membership or moving any cut. Of the after-event cuts, 7,073 are inside their price-level candidate timestamp group. Earlier local checkpoint geometry covers 8,807 after-cut prices and 984 before-insertion prices; uncovered prices retain the older strict-clearing premise. Interior positions additionally require I1: exported same-price processing order equals the source observer's actual order. Terminal aggregate equality cannot establish I1.

All 392 candidate contiguous taker/time/price groups (559 maker fragments) pass a necessary birth-order FIFO consumption check, and none repeats noncontiguously at its price. Passing is only consistency: unexecuted queues and alternative native grouping remain unidentified. Of 13,283 visible additions, 13,282 have one exact same-time, side, price and quantity ordinary-open status match. The remaining order has status quantity 1.49969 BTC and visible residual 1.06103 BTC. Seven prior same-group maker rows sum to the exact 0.43866 BTC difference, supporting an aggressor-then-resting-residual interpretation. This arithmetic does not prove priority or engine semantics; no trigger-activation example occurs in these matched additions.

An auxiliary factual-label inventory uses the already frozen count-independent first 1,000 additions. Six actual orders have positive bound trade executions within each of the 1, 5 and 10-second candidate horizons. This calendar-time inventory differs from the original eight-economic-event protocol and is not a replacement experiment. Observed factual fills need no hypothetical-probe inference; original counterfactual and queue-model claims remain separate.

## Fixed-cohort horizon completion

Only the original 38 censored anchors' 25 price levels were extended using retained December bytes. The 770 appended rows comprise 379 visible additions, 376 status-supported cancellations, ten exact matched maker decreases and five zero-quantity cleanups. Seventeen anchors now have eight closed candidate economic events; 21 remain incomplete by the last retained closed group. No unresolved label enters an eighth-event candidate horizon. The original prefix/cohort and candidate grouping remain unchanged, with no new data, fill-based selection or empirical promotion. Consumer reconciliation and scientific review remain separate.

## Reproducibility and limitations

The immutable main contract SHA-256 is `21a6393bb664c757cfcc52d393198b003e4bac06c6bbaf52884535411727612e`. The Q16 extension contract SHA-256 is `8ce8e7831242082f13d1fb07349a00f5685c7dd30df0e7470ebd2a2ff9e5a055`. Inputs, raw source digests, executed code hashes and output bindings are preserved in the adjacent summaries. The replay took {replay['runtime_s']:.3f}s, activation/priority inventory {q16['runtime_s']:.3f}s, and bounded extension {extension['runtime_s']:.3f}s; maximum measured peak across these scans was {max(replay['peak_rss_kib'],q16['peak_rss_kib'],extension['peak_rss_kib'])/1024:.1f} MiB. Seven argument/boundary checks pass, alongside exact state/count/cut replay assertions.

Historical receipt clocks, exact snapshot nanosecond time, P1/P2/L1 authenticity, native action grouping, FIFO, legal lot quantum and hypothetical probe-fill truth remain unresolved. All rows are exploratory real evidence. The original late December route remains a participant-linked conditional route; an aggregate source pilot does not replace it.

Sessions used: `drc-lob-t008-r3-participant`, `drc-lob-t008-r3-q16`, and `drc-lob-t008-r3-q16-extension`; all completed and ended. No other sessions were changed.
'''
(OUT/'report.md').write_text(report,encoding='utf-8')
(OUT/'report_created.json').write_text(json.dumps(dict(utc=datetime.now(timezone.utc).isoformat(),
    figure_data_sha256=hashlib.sha256((OUT/'main_figure_data.csv').read_bytes()).hexdigest(),
    code_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()),indent=2)+'\n')
print('Rendered participant figure PNG/SVG/PDF/HTML and explanatory report.md')
