"""Render a reproducible quality figure for the acquired development snapshots."""
import csv
import datetime as dt
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
ROOT=Path(__file__).resolve().parent
rows=[json.loads(line) for line in (ROOT/'btc_20251201_00.jsonl').read_text().splitlines()]
t=[row['raw']['data']['time'] for row in rows]
x=[(value-t[0])/60000 for value in t]
y=[float(row['raw']['data']['levels'][1][0]['px'])-float(row['raw']['data']['levels'][0][0]['px']) for row in rows]
gap=[0]+[(b-a)/1000 for a,b in zip(t,t[1:])]
# Keep the duplicate; the recorder did, too.
with (ROOT/'source_quality_figure.csv').open('w',newline='',encoding='utf-8') as handle:
    writer=csv.writer(handle);writer.writerow(['source_row_0based','exchange_time_ms','minutes_since_first_snapshot','bbo_spread_usdc_per_btc','previous_snapshot_gap_s'])
    writer.writerows(zip(range(len(rows)),t,x,y,gap))
plt.rcParams.update({'font.family':'DejaVu Sans','font.size':11})
fig,axes=plt.subplots(2,1,figsize=(11,6),sharex=True,gridspec_kw={'height_ratios':[1,1.15]})
fig.patch.set_facecolor('#f8fafc')
for ax in axes:
    ax.set_facecolor('#ffffff');ax.grid(axis='y',color='#dce3ed',linewidth=.7);ax.spines[['top','right']].set_visible(False)
axes[0].plot(x,y,color='#167589',linewidth=.75)
axes[0].set_ylabel('BBO spread\n(USDC / BTC)')
axes[0].set_title('December 1 development: independently initialized BTC snapshots',loc='left',weight='bold',pad=12)
axes[1].plot(x[1:],gap[1:],color='#324e9a',linewidth=.65)
axes[1].axhline(2,color='#ad6037',linestyle='--',linewidth=1.1,label='Declared raw-gap rejection boundary: 2 s')
axes[1].scatter([x[i] for i in range(1,len(t)) if t[i]==t[i-1]],[0]*sum(t[i]==t[i-1] for i in range(1,len(t))),s=22,color='#ad6037',zorder=4,label='Identical duplicate snapshot: preserved')
axes[1].set_ylim(-.08,2.2);axes[1].set_ylabel('Exchange timestamp\ngap (s)');axes[1].set_xlabel('Minutes since 00:00:08.727 UTC');axes[1].legend(loc='upper right',frameon=False,fontsize=9)
fig.text(.09,.02,'6,581 rows | median gap 0.540 s | max gap 1.218 s | 7 identical duplicates | sampled snapshots, not every event',fontsize=10,color='#334155')
fig.tight_layout(rect=[0,.055,1,1]);fig.savefig(ROOT/'source_quality_figure.png',dpi=160);fig.savefig(ROOT/'source_quality_figure.svg');plt.close(fig)
(ROOT/'source_quality_figure.html').write_text('''<!doctype html><html lang="en"><meta charset="utf-8"><title>BTC development snapshot quality</title><style>body{margin:2rem auto;max-width:1100px;font:16px system-ui;color:#1e293b;background:#f8fafc}img{width:100%}a{color:#0e7490}</style><h1>BTC development snapshot quality</h1><img src="source_quality_figure.svg" alt="BBO spread and snapshot interarrival gaps"><p>Source: pinned Hugging Face asiletto81/hl_btc December 2025 TAR, member data/20251201/0/l2Book/BTC.lz4. This figure describes recorded snapshots. It does not certify intermediate venue state or network latency.</p><p><a href="source_quality_figure.csv">Underlying data</a> · <a href="render_source_quality.py">Editable plotting source</a> · <a href="hour00_diagnostics/candidate_snapshot_diagnostics.json">Quality diagnostics</a></p></html>''',encoding='utf-8')
print('Rendered source_quality_figure.png/.svg/.html and underlying CSV')
