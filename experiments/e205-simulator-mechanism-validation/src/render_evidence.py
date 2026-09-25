"""Render preserved actual-engine traces; never execute the simulator."""
from pathlib import Path
import csv
import html
import json
import os

os.environ.update(OMP_NUM_THREADS='2', OPENBLAS_NUM_THREADS='2', MKL_NUM_THREADS='2')
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

ROOT = Path(__file__).resolve().parents[1]


def read(name):
    return json.loads((ROOT / name).read_text())


def main():
    protocol = read('protocol.json')
    episodes = [read(f'episodes/{s["name"]}.json') for s in protocol['episodes']]
    rows, depth, events = [], [], []
    for episode in episodes:
        for e in episode['events']:
            key = dict(episode=episode['name'], split=episode['split'], sequence=e['sequence'],
                       timestamp_ns=e['timestamp_ns'], offset_ns=e['offset_ns'])
            rows.extend(dict(**key, **r) for r in e['after'])
            depth.extend(dict(**key, **r) for r in e['l2'])
            events.append(dict(**key, operation=e['input']['msg'], order_id=e['input']['order']['order_id'],
                               visible_quantity=sum(r['quantity'] for r in e['after']),
                               native_event_path=f'episodes/{episode["name"]}.json#/events/{e["sequence"]}'))
    for name, records in [('rich_orders.csv',rows),('coarse_depth.csv',depth),('event_index.csv',events),
                          ('execution_trades.csv',read('trades.json'))]:
        with (ROOT / name).open('w', newline='', encoding='utf-8') as stream:
            writer = csv.DictWriter(stream, fieldnames=list(records[0]))
            writer.writeheader()
            writer.writerows(records)
    pair = episodes[-2:]
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':11,
                         'axes.spines.top':False,'axes.spines.right':False})
    fig, axes = plt.subplots(2,2,figsize=(13,8.4))
    fig.subplots_adjust(left=.065,right=.97,bottom=.10,top=.88,wspace=.28,hspace=.55)
    fig.suptitle('Actual ABIDES events: information loss and engine defects',fontsize=19,weight='bold',y=.98)
    fig.text(.5,.93,'Frozen source c4bf157 | seed 20260919 | synthetic scripts; no fitted model',ha='center',color='#596473')
    a,b,c,d = axes.flat
    x=[e['offset_ns'] for e in pair[0]['events']]
    y=[sum(r['quantity'] for r in e['l2']) for e in pair[0]['events']]
    a.step(x,y,where='post',lw=3,color='#176d86',label='Both histories: identical L2')
    a.scatter(x,y,color='#176d86')
    a.axvline(401,color='#8b5ca4',ls='--',label='Forecast cutoff: 401 ns')
    a.set(title='A  Aggregate depth cannot identify the cancellation',xlabel='Exchange time offset (ns)',ylabel='Visible bid quantity',xticks=x,ylim=(0,10))
    a.legend(fontsize=9,loc='lower left')
    colors={201:'#1b8b74',202:'#c9d5e0',203:'#c9d5e0'}
    for ypos,ep in zip([1.0,.2],pair):
        left=0
        for r in ep['events'][3]['after']:
            b.add_patch(Rectangle((left,ypos),r['quantity'],.45,color=colors[r['order_id']],ec='white'))
            b.text(left+r['quantity']/2,ypos+.225,f"{r['order_id']}\nq={r['quantity']}",ha='center',va='center',fontsize=10,color='white' if r['order_id']==201 else '#23384a')
            left+=r['quantity']
    b.set(title='B  Rich queues at the same 401 ns cutoff',xlim=(0,6),ylim=(0,1.7),xticks=[0,3,6],
          yticks=[1.225,.425],yticklabels=['Cancel ahead','Cancel behind'],xlabel='FIFO priority: front to back')
    b.text(3,1.52,'Green = the unchanged probe order 201',ha='center',fontsize=9,color='#176b5a')
    c.bar(['Cancel ahead','Cancel behind'],[3,1],color=['#1b8b74','#496a96'],width=.55)
    c.set(title='C  Common sell quantity 4: different probe fills',ylabel='Probe executed quantity',ylim=(0,3.7),yticks=[0,1,2,3])
    for index,value in enumerate([3,1]):
        c.text(index,value+.1,str(value),ha='center',weight='bold',fontsize=14)
    c.text(.5,.91,'Final aggregate quantity is 2 in both',transform=c.transAxes,ha='center',fontsize=9,color='#596473')
    d.bar(['Required after\nnon-head edit','Actual engine\nafter edit'],[6,5],color=['#6f879d','#b94f46'],width=.55)
    d.set(title='D  Non-head amendment corrupts the live queue',ylabel='Visible bid quantity',ylim=(0,7.6),yticks=[0,2,4,6])
    d.text(0,6.2,'101:q4 + 102:q2',ha='center',fontsize=10)
    d.text(1,5.2,'102:q2 + 102:q3',ha='center',fontsize=10,color='#9b342c')
    fig.text(.065,.027,'Source: saved exchange events and paired ORDER_EXECUTED messages. Panels A-C demonstrate ambiguity, not learnability or economic gain.',fontsize=10)
    fig.savefig(ROOT/'main_figure.png',dpi=180)
    fig.savefig(ROOT/'main_figure.svg')
    plt.close(fig)

    # The browser view reads the same frozen rows; it cannot secretly summon a simulator.
    payload=json.dumps(episodes,separators=(',',':')).replace('</','<\\/')
    page='''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>T-012 actual engine traces</title><style>body{font:16px system-ui;background:#f5f7fa;color:#203346;max-width:1250px;margin:40px auto;padding:0 20px}h1{font-size:30px}select,input{font:inherit;margin:10px;padding:8px}table{border-collapse:collapse;width:100%;background:white;margin:15px 0}th,td{text-align:left;padding:9px;border-bottom:1px solid #d8e0e8}th{background:#203346;color:white}pre{white-space:pre-wrap;background:white;padding:20px;overflow:auto}.note{color:#5d4654}img{width:100%}</style>
<h1>Actual engine, preserved events</h1><p>ABIDES c4bf157 · synthetic participants · seed 20260919. Read-only evidence viewer; no engine or model runs.</p>
<p class="note">The original run exited 1 on an additional history failure. The non-head amendment corrupts order identity. This packet is a diagnostic, not an unrestricted training dataset.</p>
<img src="main_figure.svg" alt="Identical depth paths, different probe fills, and the amendment defect">
<label>Episode<select id="episode"></select></label><label>Event<input id="event" type="range" min="0" value="0"></label><strong id="label"></strong>
<h2>Ordered rich state after the event</h2><div id="rich"></div><h2>Aggregate L2 after the same event</h2><div id="coarse"></div>
<details><summary>Actual input and engine output messages</summary><pre id="messages"></pre></details>
<script id="evidence" type="application/json">PAYLOAD</script><script>
const data=JSON.parse(document.getElementById('evidence').textContent);const choice=document.getElementById('episode'), slider=document.getElementById('event');
for(const e of data){const o=document.createElement('option');o.textContent=e.name;choice.append(o)}
function table(id,rows,keys){const t=document.createElement('table'),h=t.insertRow();for(const k of keys){const cell=document.createElement('th');cell.textContent=k;h.append(cell)}for(const row of rows){const r=t.insertRow();for(const k of keys)r.insertCell().textContent=String(row[k])}document.getElementById(id).replaceChildren(t)}
function draw(){const e=data[choice.selectedIndex].events[Number(slider.value)];document.getElementById('label').textContent=`sequence ${e.sequence} · ${e.offset_ns} ns · ${e.input.msg}`;table('rich',e.after,['side','price','order_id','participant','quantity','queue_position']);table('coarse',e.l2,['side','price','quantity']);document.getElementById('messages').textContent=JSON.stringify({input:e.input,outgoing:e.outgoing},null,2)}
choice.onchange=()=>{slider.max=data[choice.selectedIndex].events.length-1;slider.value=0;draw()};slider.oninput=draw;choice.onchange();
</script></html>'''.replace('PAYLOAD',payload)
    (ROOT/'trace-explorer.html').write_text(page,encoding='utf-8')
    embedded=page.split('<script id="evidence" type="application/json">')[1].split('</script>')[0]
    assert json.loads(embedded)==episodes
    metadata=dict(figure_source='code/render_evidence.py',episode_count=len(episodes),events=len(events),
                  rich_rows=len(rows),coarse_rows=len(depth),embedded_html_data_matches=True,
                  browser_ui_tested=False,browser_note='Local-file navigation was policy blocked in the prior task; no workaround or UI verification claimed.',
                  truth='native exchange post-event state and matched execution messages, not native order-history quantities')
    (ROOT/'figure_metadata.json').write_text(json.dumps(metadata,indent=2)+'\n')


if __name__=='__main__':
    main()
