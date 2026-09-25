"""Draw the accepted-evidence-to-question map and exact synthetic contrast figure."""
import json
from resource_guard import ROOT
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch


def main():
    data = json.loads((ROOT/'analytical-checks.json').read_text())
    boxes = [
        dict(x=.01,y=.58,w=.29,h=.33,color='#eaf2ed',title='ACCEPTED / R042',
             text='Raw R-C > 0; fixed mixture < 0\nStrict conjunction contradicted\nOne exposed day; fixed learners'),
        dict(x=.355,y=.58,w=.29,h=.33,color='#edf2f7',title='SCIENTIFIC DISTINCTION',
             text='Fitted gap = - information value\n+ rich regret - coarse regret\nThe gap does not identify either part'),
        dict(x=.70,y=.58,w=.29,h=.33,color='#edf2f7',title='ONE NEXT QUESTION',
             text='Does the frozen rich score contain\nuseful signal beyond all coarse X?\nSmaller target than all depth'),
        dict(x=.01,y=.08,w=.29,h=.33,color='#edf2f7',title='KNOWN DIAGNOSTIC',
             text='Conditional score replacement\nSame predictor; no refit\nJ > 0 can witness useful information'),
        dict(x=.355,y=.08,w=.29,h=.33,color='#fff4df',title='PROPOSED / UNTESTED GATE',
             text='Justify score law given full X\n+ temporal uncertainty + exposure\nA fitted sampler alone is insufficient'),
        dict(x=.70,y=.08,w=.29,h=.33,color='#fbecea',title='CURRENT DISPOSITION',
             text='NO-GO for real information claim\nNO-GO for a paper contribution\nFeasibility decision before scoring')]
    fig, ax = plt.subplots(figsize=(12, 4.2), layout='constrained')
    ax.set(xlim=(0,1), ylim=(0,1))
    ax.axis('off')
    for b in boxes:
        ax.add_patch(FancyBboxPatch((b['x'],b['y']),b['w'],b['h'], boxstyle='round,pad=.006',
            linewidth=0, facecolor=b['color']))
        ax.text(b['x']+.015,b['y']+b['h']-.06,b['title'],fontsize=10.4,weight='bold',color='#1d3a51')
        ax.text(b['x']+.015,b['y']+.16,b['text'],fontsize=11.7,linespacing=1.5,va='center',color='#22313c')
    for start,end in [((.30,.745),(.35,.745)),((.645,.745),(.695,.745)),
                      ((.30,.245),(.35,.245)),((.645,.245),(.695,.245))]:
        ax.annotate('',xy=end,xytext=start,arrowprops=dict(arrowstyle='->',color='#516c80',lw=1.5))
    ax.annotate('evaluate a different quantity',xy=(.16,.42),xytext=(.71,.48),fontsize=10,
                color='#516c80',arrowprops=dict(arrowstyle='->',connectionstyle='angle3',color='#516c80'))
    fig.savefig(ROOT/'main_figure.png',dpi=190)
    fig.savefig(ROOT/'main_figure.svg')
    plt.close(fig)
    labels=['Redundant','XOR feature','Useful score','Uninformative score','Wrong score']
    fig, ax=plt.subplots(figsize=(10,3.8),layout='constrained')
    values={key:[case[key]['value'] for case in data['cases']] for key in
            ['oracle_information_value','rich_minus_coarse','conditional_replacement']}
    for offset,key,label,color in [(-.24,'oracle_information_value','Oracle information value','#19718b'),
        (0,'rich_minus_coarse','Fitted R-C loss','#9a6877'),(.24,'conditional_replacement','Conditional replacement J','#ca8c2b')]:
        ax.bar([i+offset for i in range(5)],values[key],width=.23,label=label,color=color)
    ax.axhline(0,color='#526575',lw=.7)
    ax.set_xticks(range(5),labels)
    ax.set_ylabel('Half-Brier scale')
    ax.set_title('Exact synthetic witnesses; no fitted models or market observations',loc='left',fontsize=12)
    ax.legend(ncols=3,fontsize=9,loc='lower center',bbox_to_anchor=(.5,-.28))
    ax.spines[['top','right']].set_visible(False)
    fig.savefig(ROOT/'synthetic_witnesses.png',dpi=180)
    fig.savefig(ROOT/'synthetic_witnesses.svg')
    plt.close(fig)
    mermaid='''flowchart LR
  E["Accepted: raw + / fixed mixture - / F +"] --> D["Fitted gap = - information value + regret difference"]
  D --> Q["Question: conditional outcome signal in frozen rich score"]
  Q --> T["Known conditional replacement diagnostic"]
  T --> G["UNTESTED: conditional-law, temporal and exposure gate"]
  G --> N["CURRENT NO-GO: no real-data release or paper claim"]
'''
    (ROOT/'evidence-to-question.mmd').write_text(mermaid)
    (ROOT/'figure-data.json').write_text(json.dumps(dict(boxes=boxes,labels=labels,values=values,
        synthetic_only=True,empirical_scoring=0,proposal_tested=False),indent=2)+'\n')
    cards=''.join(f'<details><summary>{c["name"]}</summary><p>Oracle value: {c["oracle_information_value"]["exact"]}; '
        f'fitted R-C: {c["rich_minus_coarse"]["exact"]}; conditional J: {c["conditional_replacement"]["exact"]}.</p></details>'
        for c in data['cases'])
    html='''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Information value before another learner</title><style>body{font:16px/1.55 system-ui,sans-serif;color:#22313c;max-width:1120px;margin:28px auto;padding:0 24px}
h1{line-height:1.2}img{max-width:100%;height:auto}details{padding:12px;background:#edf2f7;margin:10px 0}summary{cursor:pointer;font-weight:600}
a{color:#19718b}.tag{color:#9a4939;font-weight:650}</style></head><body><p>E272 / D058 / T-012 r10</p>
<h1>Information value before another learner</h1><p class="tag">No current paper claim. Real-data diagnostic remains untested and gated.</p>
<img src="main_figure.svg" alt="Accepted evidence to the proposed conditional information question">
<h2>Exact synthetic witnesses</h2><p>Open a case for exact fractions. These are finite probability laws, not market results.</p>'''+cards+'''
<img src="synthetic_witnesses.svg" alt="Oracle information value, fitted contrast and conditional replacement differ across five laws">
<p><a href="report.pdf">Compiled report</a> · <a href="next-test.md">Bounded next-test specification</a> · <a href="analytical-checks.json">Exact checks</a></p>
</body></html>'''
    (ROOT/'evidence-to-question.html').write_text(html,encoding='utf-8')
    assert len(values['conditional_replacement'])==5
    assert values['conditional_replacement']==[0,0,2/3,0,-1/3]
    (ROOT/'figure-validation.json').write_text(json.dumps(dict(exact_values_match=True,
        standalone_svg_and_html=True,external_javascript=False,browser_interaction_verified=False),indent=2)+'\n')


if __name__=='__main__':
    main()
