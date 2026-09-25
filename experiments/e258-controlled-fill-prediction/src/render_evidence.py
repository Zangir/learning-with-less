"""Render the frozen study outputs without generating worlds or fitting models."""
from pathlib import Path
import json
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import plotly.graph_objects as go
from plotly.subplots import make_subplots

ROOT=(Path(__file__).resolve().parents[1] / 'runtime')
CONDITIONS=['zero','informative','shift']
LABELS={'unconditional_y':'Unconditional Y','direct_y':'Direct Y','distribution_y':'Distribution Y',
    'point_y':'Point Y','distribution_h':'Distribution H (privileged training)',
    'point_mean_h':'Point mean H (privileged training)','current_rich_y':'Current rich Y',
    'exact_coarse_current':'Exact coarse law','exact_rich':'Exact current-rich law'}
COLORS={'direct_y':'#3c698c','distribution_y':'#21816b','distribution_h':'#76549a',
        'point_mean_h':'#c06b47','point_y':'#b6534e','current_rich_y':'#525d68','exact_coarse_current':'#171d26'}


def read(name):return json.loads((ROOT/name).read_text())


def main():
    metrics=read('metrics.json');exact=read('exact-population-metrics.json');contrasts=read('paired-contrasts.json')
    selected=['direct_y','distribution_y','distribution_h','point_mean_h','current_rich_y']
    exact_lookup={(r['condition'],r['training_size']):r['metrics'] for r in exact}
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,'axes.spines.top':False,'axes.spines.right':False,
        'axes.labelcolor':'#22303c','text.color':'#22303c','axes.titlepad':12})
    fig,axes=plt.subplots(2,2,figsize=(13,9.3),layout='constrained')
    fig.suptitle('Hidden queue uncertainty: native-grounded finite-law study',fontsize=17,weight='bold')
    ax=axes[0,0]
    x=np.arange(3)
    for c,(values,color) in enumerate([([.1,.8,.1],'#21816b'),([.4,.2,.4],'#3c698c')]):
        ax.bar(x+(c-.5)*.33,values,width=.30,label=f'Cue C={c}',color=color)
    ax.set(xticks=x,xticklabels=['H=0','H=1','H=2'],ylim=(0,.94),ylabel='Conditional probability',
           title='A  Equal queue means, different tails')
    ax.text(.5,.91,'Both means: E[H | C] = 1',transform=ax.transAxes,ha='center')
    ax.legend(frameon=False,loc='upper right')
    ax=axes[0,1]
    for model in selected:
        values=[exact_lookup[c,512][model]['brier'] for c in CONDITIONS]
        style='--' if model=='direct_y' else '-'
        ax.plot(range(3),values,style,marker='o',label=LABELS[model],color=COLORS[model])
    ax.plot(range(3),[exact_lookup[c,512]['exact_coarse_current']['brier'] for c in CONDITIONS],':',color='#171d26',label='Exact coarse law')
    ax.set(xticks=range(3),xticklabels=['Queue-uninformative','Informative','Association shift'],ylabel='Expected Brier (lower is better)',
           title='B  Fitted-model risk under the enumerated law, n=512')
    ax.legend(frameon=False,fontsize=8.2,loc='upper center',bbox_to_anchor=(.5,-.16),ncol=2)
    ax=axes[1,0]
    for n,offset,color in [(128,-.09,'#3c698c'),(512,.09,'#21816b')]:
        rows=[next(r for r in contrasts if r['condition']==c and r['training_size']==n and r['left']=='distribution_y' and r['right']=='direct_y') for c in CONDITIONS]
        values=np.array([r['difference'] for r in rows]);interval=np.array([r['ci95'] for r in rows])
        ax.errorbar(np.arange(3)+offset,values,yerr=np.array([values-interval[:,0],interval[:,1]-values]),
            fmt='o',capsize=4,color=color,label=f'n={n}')
    ax.axhline(0,color='#939da4',lw=1)
    ax.set(xticks=range(3),xticklabels=['Queue-uninformative','Informative','Association shift'],
           ylabel='Test Brier: distribution Y minus direct Y',title='C  Same-supervision paired test comparison')
    ax.legend(frameon=False);ax.text(.5,.03,'95% episode-bootstrap intervals; conditional on these fits',transform=ax.transAxes,ha='center',fontsize=8)
    ax=axes[1,1]
    costs=[.2,.4,.55,.7,.85]
    for model in ['direct_y','distribution_y','distribution_h','point_mean_h','current_rich_y']:
        table=exact_lookup['shift',512]
        regret=[table[model]['costs'][str(c)]-table['exact_coarse_current']['costs'][str(c)] for c in costs]
        ax.plot(costs,regret,marker='o',linestyle='--' if model=='direct_y' else '-',color=COLORS[model],label=LABELS[model])
    ax.axhline(0,color='#939da4',lw=1)
    ax.set(xlabel='Prespecified decision cost c',ylabel='Expected loss minus shifted coarse Bayes',
           title='D  Shift decisions using frozen informative fits')
    ax.text(.5,.03,'Negative rich-state values use extra current information; not profits',transform=ax.transAxes,ha='center',fontsize=8)
    for ax in axes.flat:ax.grid(axis='y',alpha=.17)
    fig.savefig(ROOT/'main_figure.png',dpi=190);fig.savefig(ROOT/'main_figure.svg');plt.close(fig)
    calibration=read('calibration.json')
    fig,axes=plt.subplots(1,3,figsize=(12,3.6),layout='constrained')
    for ax,condition in zip(axes,CONDITIONS):
        ax.plot([0,1],[0,1],':',color='#a2aab0')
        for model in ['direct_y','distribution_y','distribution_h','current_rich_y']:
            rows=[r for r in calibration if r['condition']==condition and r['role']=='test' and r['training_size']==512 and r['model']==model]
            ax.plot([r['mean_probability'] for r in rows],[r['observed_full_fill'] for r in rows],
                marker='o',color=COLORS[model],label=LABELS[model],linestyle='--' if model=='direct_y' else '-')
        ax.set(title=condition,xlabel='Mean predicted probability',ylabel='Observed full-fill fraction',xlim=(0,1),ylim=(0,1));ax.grid(alpha=.15)
    axes[1].legend(frameon=False,fontsize=7,loc='lower right')
    fig.savefig(ROOT/'calibration.png',dpi=180);fig.savefig(ROOT/'calibration.svg');plt.close(fig)
    interactive=make_subplots(rows=1,cols=2,subplot_titles=['Observed test Brier (n=512)','Law-enumerated fitted-model Brier (n=512)'])
    for model in selected:
        rows=[next(r for r in metrics if r['condition']==c and r['role']=='test' and r['training_size']==512 and r['model']==model) for c in CONDITIONS]
        y=[r['brier'] for r in rows]
        interactive.add_trace(go.Scatter(x=CONDITIONS,y=y,name=LABELS[model],mode='lines+markers',line_color=COLORS[model],
            error_y=dict(type='data',symmetric=False,array=[r['brier_ci95'][1]-r['brier'] for r in rows],
                         arrayminus=[r['brier']-r['brier_ci95'][0] for r in rows])),row=1,col=1)
        interactive.add_trace(go.Scatter(x=CONDITIONS,y=[exact_lookup[c,512][model]['brier'] for c in CONDITIONS],
            name=LABELS[model],showlegend=False,mode='lines+markers',line_color=COLORS[model]),row=1,col=2)
    interactive.update_layout(title='E258 controlled fill study · identical episode eligibility · synthetic law only',template='plotly_white',height=620)
    interactive.write_html(ROOT/'study-explorer.html',include_plotlyjs=True,full_html=True)
    (ROOT/'figure-data.json').write_text(json.dumps(dict(test_metrics=metrics,exact_metrics=exact,contrasts=contrasts),indent=2)+'\n')
    # Examples are preselected indices, not a hunt for photogenic outcomes.
    examples=[]
    for name in ['support-001','support-005','support-193','informative-test-0000','shift-test-0000']:
        capture=read('episodes/'+name+'.json')
        state=[e for e in capture['events'] if e['offset_ns']<=403][-1]['after']
        examples.append(dict(name=name,admissible=capture['admissible'],privileged_current_queue=state,
                             future_event=capture['events'][-1],own_actual_receipts=capture['receipts']['1']))
    (ROOT/'raw-stage-examples.json').write_text(json.dumps(examples,indent=2)+'\n')
    (ROOT/'figure-validation.json').write_text(json.dumps(dict(source='saved model outputs and law-enumerated metrics only',
        models_refit=False,native_executed=False,html_embeds_local_plotly=True,browser_interaction_verified=False,
        examples='fixed first-index/native-support examples, rich fields labeled separately'),indent=2)+'\n')
    print('Saved main/calibration PNG+SVG, editable Python, Plotly HTML and raw delivered examples.')


if __name__=='__main__':main()
