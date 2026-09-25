"""Export the saved restricted mechanism data and render its evidence; no engine runs."""
from pathlib import Path
import csv
import json
import os

os.environ.update(OMP_NUM_THREADS='2',OPENBLAS_NUM_THREADS='2',MKL_NUM_THREADS='2')
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT=(Path(__file__).resolve().parents[1] / 'runtime')


def read(name):
    return json.loads((ROOT/name).read_text(encoding='utf-8-sig'))


def save(name,value):
    (ROOT/name).write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8')


def csv_file(name,records):
    with (ROOT/name).open('w',newline='',encoding='utf-8') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)


def fills(episode,cutoff=503):
    return sum(r['body']['order']['quantity'] for r in episode['receipts']['1']
               if r['body']['msg']=='ORDER_EXECUTED' and r['body']['order']['order_id']==201
               and r['delivery_ns']<=cutoff)


def main():
    protocol,validation=read('protocol.json'),read('validation.json')
    episodes={s['name']:read(f'episodes/{s["name"]}.json') for s in protocol['episodes']}
    event_rows,feed_rows,rich_rows,trades,coverage=[],[],[],[],[]
    features,labels,index=[],[],[]
    for spec in protocol['episodes']:
        episode=episodes[spec['name']]
        matches=0
        for event in episode['events']:
            key=dict(episode=spec['name'],sequence=event['sequence'],exchange_ns=event['offset_ns'])
            event_rows.append(dict(**key,operation=event['input']['msg'],order_id=event['input']['order']['order_id'],
                accepted=event['accepted'],rejection=event['rejection'],publication_ns=event['offset_ns'],
                observer_delivery_ns=event['offset_ns']+2,source=f'episodes/{spec["name"]}.json#/events/{event["sequence"]}'))
            rich_rows.extend(dict(**key,**{k:v for k,v in r.items() if k!='time_placed_ns'}) for r in event['after'])
            emitted=[m['body']['order'] for m in event['outgoing'] if m['body']['msg']=='ORDER_EXECUTED']
            for j in range(0,len(emitted),2):
                incoming,resting=emitted[j:j+2]
                trades.append(dict(**key,match_index=j//2,aggressor_order=incoming['order_id'],
                    resting_order=resting['order_id'],quantity=incoming['quantity'],price=incoming['fill_price']))
                matches+=1
        for received in episode['observations']:
            payload=received['payload']
            for level in payload['levels']:
                feed_rows.append(dict(episode=spec['name'],sequence=payload['sequence'],exchange_ns=payload['exchange_ns'],
                     publication_ns=payload['publish_ns'],delivery_ns=received['delivery_ns'],**level))
        coverage.append(dict(episode=spec['name'],split=spec['split'],seed=spec['stream_seed'],
            actions=len(episode['events']),rejected=sum(not e['accepted'] for e in episode['events']),
            matches=matches,feed_packets=len(episode['observations']),
            probe_fill_by_503=fills(episode) if spec['cutoff_ns'] is not None else None))
        if spec['cutoff_ns'] is not None:
            features.append(episode['admissible'])
            state=[e for e in episode['events'] if e['offset_ns']<=spec['cutoff_ns']][-1]['after']
            probe=next(r for r in state if r['order_id']==201)
            ahead=sum(r['quantity'] for r in state if r['side']==probe['side'] and r['price']==probe['price']
                      and r['queue_position']<probe['queue_position'])
            labels.append(dict(probe_fill_by_delivery_503=fills(episode),rich_queue_ahead_at_exchange_403=ahead))
            index.append(dict(row=len(features)-1,episode=spec['name'],split=spec['split'],seed=spec['stream_seed'],
                              cutoff_ns=spec['cutoff_ns'],label_horizon_delivery_ns=503))
    for name,records in [('event_index.csv',event_rows),('delivered_depth.csv',feed_rows),('rich_orders.csv',rich_rows),
                         ('execution_trades.csv',trades),('scenario_coverage.csv',coverage),('dataset_index.csv',index)]:
        csv_file(name,records)
    save('dataset_features.json',features)
    save('dataset_labels.json',labels)
    assert features[0]==features[1] and labels[0]['probe_fill_by_delivery_503']==3 and labels[1]['probe_fill_by_delivery_503']==1
    save('dataset_contract.json',dict(features='dataset_features.json',labels='dataset_labels.json',audit_index='dataset_index.csv',
         rows=len(features),feature_keys=['coarse','own_receipts','own_submissions'],
         audit_index_is_not_a_predictor=True,rich_labels_are_not_observed_inputs=True,
         demonstrated_question='Synthetic probe fill by503ns using only messages delivered and own submissions sent by403ns',
         excluded_claims=['recoverability','generalization','economic gain','realism']))
    summary=dict(episodes=len(episodes),primary_actions=len(event_rows),primary_feed_packets=sum(c['feed_packets'] for c in coverage),
        rejected_requests=sum(c['rejected'] for c in coverage),matched_trades=len(trades),
        checks=validation['check_count'],patched_or_delivery_failures=len(validation['patched_or_delivery_failures']),
        upstream_control_failures=len(validation['upstream_control_failures']),replay_pairs=len(validation['replays']),
        causal_prefixes=len(validation['prefixes']),engine_runs=sum(protocol['run_counts'].values()),
        legacy_probe_fills=[fills(episodes[n]) for n in ('legacy_cancel_ahead','legacy_cancel_behind')],
        coverage=coverage,feature_rows=len(features),actual_engine='locally patched ABIDES; upstream retained separately')
    save('summary.json',summary)

    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':11,'axes.spines.top':False,'axes.spines.right':False})
    fig,axes=plt.subplots(2,2,figsize=(13.6,8.8))
    fig.subplots_adjust(left=.07,right=.98,bottom=.095,top=.89,wspace=.30,hspace=.56)
    fig.suptitle('Restricted engine: corrected labels and delivered observations',fontsize=19,weight='bold',y=.98)
    fig.text(.5,.935,'Native ABIDES + two local repair lines | base seed 20260919 | fixed mechanism checks, no learner',ha='center',color='#596473')
    a,b,c,d=axes.flat
    boundary=episodes['seeded_check_20262002']
    pending=next(e for e in boundary['events'] if e['input']['order']['order_id']==206)
    received=next(o for o in boundary['observations'] if o['payload']['sequence']==pending['sequence'])
    sent=next(s for s in boundary['submissions'] if s['own_order_id']==206)['sent_ns']
    a.axvline(boundary['cutoff_ns'],color='#8b5ca4',ls='--',label='Forecast cutoff')
    previous=boundary['admissible']['coarse'][-1]
    a.plot([previous['payload']['publish_ns'],previous['delivery_ns']],[0,0],'-o',color='#176d86',lw=2,label='Previous depth packet')
    a.plot([sent,pending['offset_ns'],received['delivery_ns']],[1,1,1],'-o',color='#1b8b74',lw=2,label='Own order / later packet')
    for x,y,label in [(401,0,'Publish401'),(403,0,'Receive403'),(sent,1,'Send402'),(pending['offset_ns'],1,'Publish403'),(received['delivery_ns'],1,'Receive405')]:
        a.text(x,y+.18,label,ha='center',fontsize=9,rotation=0)
    a.set(title='A  Published does not mean observed',xlim=(400.5,405.5),ylim=(-.45,1.55),yticks=[],xticks=[401,402,403,404,405],xlabel='Synthetic time offset (ns)')
    a.text(.5,-.28,'At403: own send is known; its feed and acknowledgment are not.',transform=a.transAxes,ha='center',fontsize=9)
    pair=episodes['legacy_cancel_ahead']
    x=[o['delivery_ns'] for o in pair['observations']]
    y=[sum(r['quantity'] for r in o['payload']['levels']) for o in pair['observations']]
    b.step(x,y,where='post',lw=3,color='#176d86')
    b.scatter(x,y,color='#176d86')
    b.axvline(403,color='#8b5ca4',ls='--')
    b.set(title='B  Both legacy branches deliver the same depth',xlabel='Actual observer delivery time (ns)',ylabel='Visible bid quantity',xticks=x,ylim=(0,10))
    b.text(.5,.92,'Private cancellation identity never enters the feed',transform=b.transAxes,ha='center',fontsize=9)
    c.bar(['Cancel ahead','Cancel behind'],summary['legacy_probe_fills'],color=['#1b8b74','#496a96'],width=.55)
    c.set(title='C  Same delivered inputs; different later fills',ylabel='Probe filled by503ns',ylim=(0,3.7),yticks=[0,1,2,3])
    for i,q in enumerate(summary['legacy_probe_fills']): c.text(i,q+.12,str(q),ha='center',weight='bold',fontsize=14)
    c.text(.5,.91,'An ambiguity result, not inferred recoverability',transform=c.transAxes,ha='center',fontsize=9)
    old=read('controls/diagnostic_nonhead.json')['events'][-1]['after']
    new=episodes['diagnostic_nonhead']['events'][-1]['after']
    for row,state in enumerate([old,new]):
        left=0
        for order in state:
            color='#b94f46' if row==0 else ('#1b8b74' if order['order_id']==101 else '#496a96')
            d.barh(row,order['quantity'],left=left,color=color,edgecolor='white',height=.5)
            d.text(left+order['quantity']/2,row,f"{order['order_id']}:q{order['quantity']}",ha='center',va='center',color='white',fontsize=10)
            left+=order['quantity']
    d.set(title='D  The local repair preserves non-head identity',yticks=[0,1],yticklabels=['Upstream','Patched'],xlim=(0,6.5),xlabel='Visible queue quantity')
    d.invert_yaxis()
    fig.text(.07,.025,'Source: actual native-engine captures, delivered participant packets and independent reconstruction. Upstream failures remain preserved controls.',fontsize=10)
    fig.savefig(ROOT/'main_figure.png',dpi=180)
    fig.savefig(ROOT/'main_figure.svg')
    plt.close(fig)

    viewer=[]
    for name,ep in episodes.items():
        viewer.append(dict(name=name,observations=ep['observations'],submissions=ep['submissions'],
                           cutoff_ns=ep['cutoff_ns'],admissible=ep['admissible']))
    payload=json.dumps(viewer,separators=(',',':')).replace('</','<\\/')
    page='''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Restricted simulator delivery evidence</title>
<style>body{max-width:1200px;margin:35px auto;padding:0 20px;background:#f5f7fa;color:#203346;font:16px system-ui}h1{font-size:30px}img{width:100%}select,input{font:inherit;margin:10px;padding:8px}table{border-collapse:collapse;width:100%;background:white;margin:15px 0}th,td{text-align:left;padding:9px;border-bottom:1px solid #d8e0e8}th{background:#203346;color:white}pre{background:white;padding:20px;white-space:pre-wrap;overflow-wrap:anywhere}.note{color:#665267}</style>
<h1>What has actually arrived?</h1><p>Restricted local ABIDES repair. Read-only captured-message explorer; no simulator or learner runs.</p><p class="note">Scenario labels are audit metadata and are excluded from dataset_features.json. The validated forecast cutoff is403ns.</p><img src="main_figure.svg" alt="Delivery boundary, indistinguishable depth histories, probe fills and corrected queue">
<label>Audit scenario<select id="episode"></select></label><label>Observer time<input id="time" type="range" min="0" max="950" value="403"></label><strong id="clock"></strong>
<h2>Packets received by this time</h2><div id="packets"></div><h2>Own submissions already sent</h2><pre id="own"></pre><details><summary>Exact validated forecast input at403ns</summary><pre id="features"></pre></details>
<script id="evidence" type="application/json">PAYLOAD</script><script>
const data=JSON.parse(document.getElementById('evidence').textContent),select=document.getElementById('episode'),slider=document.getElementById('time');
for(const e of data){const o=document.createElement('option');o.textContent=e.name;select.append(o)}
function draw(){const e=data[select.selectedIndex],now=Number(slider.value);document.getElementById('clock').textContent=now+'ns';const table=document.createElement('table'),header=table.insertRow();for(const key of ['sequence','exchange','publication','delivery','levels']){const th=document.createElement('th');th.textContent=key;header.append(th)}for(const o of e.observations.filter(o=>o.delivery_ns<=now)){const row=table.insertRow();for(const value of [o.payload.sequence,o.payload.exchange_ns,o.payload.publish_ns,o.delivery_ns,JSON.stringify(o.payload.levels)])row.insertCell().textContent=String(value)}document.getElementById('packets').replaceChildren(table);document.getElementById('own').textContent=JSON.stringify(e.submissions.filter(s=>s.sent_ns<=now),null,2);document.getElementById('features').textContent=e.cutoff_ns===null?'Diagnostic scenario has no forecast cutoff.':JSON.stringify(e.admissible,null,2)}select.onchange=draw;slider.oninput=draw;draw();
</script></html>'''.replace('PAYLOAD',payload)
    (ROOT/'trace-explorer.html').write_text(page,encoding='utf-8')
    embedded=page.split('<script id="evidence" type="application/json">')[1].split('</script>')[0]
    assert json.loads(embedded)==viewer
    script=page.split('</script><script>')[1].split('</script>')[0]
    (ROOT/'trace-explorer.js').write_text(script,encoding='utf-8')
    save('export-validation.json',dict(feature_rows=len(features),actual_feature_objects_match=True,
        paired_features_equal=features[0]==features[1],figure_source='code/render_evidence.py',
        html_embedded_data_match=True,browser_interaction_tested=False,
        browser_note='Prior local-file navigation was policy-blocked; no workaround attempted.',
        rows=dict(events=len(event_rows),rich=len(rich_rows),delivered_depth=len(feed_rows),trades=len(trades))))
    print(json.dumps(summary,indent=2))


if __name__=='__main__': main()
