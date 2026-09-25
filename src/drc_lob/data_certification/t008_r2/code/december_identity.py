"""Observed identity ledger and L2 count crosscheck; no authenticated FIFO claim."""
from pathlib import Path
from collections import Counter
from decimal import Decimal
import bisect,gzip,hashlib,json,resource,time,struct
from datetime import datetime, timezone
ROOT=Path(__file__).resolve().parents[3]
OUT=ROOT/'T-008/r2/december'
SCALE=100000000
START=1764550602779577841
STOP=START+20_000000000

def u(v): return int(Decimal(v)*SCALE)
def token(oid): return hashlib.sha256(('T008-local-order-'+str(oid)).encode()).hexdigest()[:20]
rows=[json.loads(x) for x in (OUT/'candidate_group_states.jsonl').read_text().splitlines()]
rows=[x for x in rows if x['next_anchor_time_ns'] and x['source_order_cut_unambiguous_under_candidate_anchors']]
starts=[r['first_diff_row_0based'] for r in rows]; ends={r['last_diff_row_0based']:r for r in rows}
active={}; first_new={}; wanted=set(); level_counts=[Counter(),Counter()]; initial=None; ledger=(OUT/'identity_candidate_events.jsonl').open('w'); countout=(OUT/'candidate_group_counts.jsonl').open('w'); n=0; started=time.monotonic(); lookups=[]
with gzip.open(ROOT/'T-001/data/book_diffs_20251201_00.gz','rt') as f:
    for source_row,line in enumerate(f):
        raw=json.loads(line)
        if raw['coin']!='BTC': continue
        oid=raw['oid']; side=0 if raw['side']=='B' else 1; px=u(raw['px']); d=raw['raw_book_diff']; kind='remove' if d=='remove' else next(iter(d)); old=active.get(oid)
        if old and old[2]>0: level_counts[old[0]][old[1]]-=1
        if kind=='new': q=u(d['new']['sz']); first_new[oid]=source_row
        elif kind=='update': q=u(d['update']['newSz'])
        else: q=0
        if kind=='remove': active.pop(oid,None)
        else: active[oid]=(side,px,q)
        if q>0: level_counts[side][px]+=1
        idx=bisect.bisect_right(starts,source_row)-1
        if idx>=0:
            cut=rows[idx]; stamp=cut['candidate_block_time_ns']
            inside=(side==0 and px>86931*SCALE) or (side==1 and px<90376*SCALE)
            if START<stamp<=STOP and inside:
                wanted.add(oid)
                out={'source_diff_row_0based':source_row,'candidate_group_time_ns':stamp,'local_order_token':token(oid),'kind':kind,'side':raw['side'],'price_units_1e8_usd':px,'quantity_before_units_1e8_btc':old[2] if old else None,'quantity_after_units_1e8_btc':q,'source_new_row_0based':first_new.get(oid),'cleanup_zero_size_remove':kind=='remove' and old is not None and old[2]==0,'operation_semantics':'lifecycle_assignment_not_fill_label','fifo_truth_certified':False}
                ledger.write(json.dumps(out,separators=(',',':'))+'\n'); n+=1
        if source_row in ends:
            cut=ends[source_row]; stamp=cut['candidate_block_time_ns']
            countout.write(json.dumps({'time_ns':stamp,'top5_counts':[[level_counts[s][p] for p,q in levels] for s,levels in enumerate(cut['top5_observed_plus_known_inherited'])]},separators=(',',':'))+'\n')
            if stamp==START:
                initial=[{'local_order_token':token(k),'side':'B' if s==0 else 'A','price_units_1e8_usd':p,'quantity_units_1e8_btc':q,'observed_new_source_row_0based':first_new.get(k),'priority_claim':'none'} for k,(s,p,q) in active.items() if q>0 and ((s==0 and p>86931*SCALE) or (s==1 and p<90376*SCALE))]
                (OUT/'identity_candidate_initial.json').write_text(json.dumps({'time_ns':START,'source_last_row_0based':source_row,'classification':'conditional_regional_observed_identity_state_not_fifo_truth','orders':initial},indent=2)+'\n')
        if source_row%2000000==0: print(source_row,len(active),flush=True)
ledger.close();countout.close()
# Bind observed fill/cancel labels to the same exact source group and local token.
status={}; REC=struct.Struct('<QI?B?IIQIi?????BBII')
def dec(v): return (v&0x1fffffff)*10**(8-(v>>29))
with gzip.open(ROOT/'T-001/data/btc_20251201_00.data.gz','rb') as f:
    for b in iter(lambda:f.read(REC.size*32768),b''):
        for j,v in enumerate(REC.iter_unpack(b)):
            if v[7] in wanted and START<v[0]<=STOP:
                key=(token(v[7]),v[0]); status.setdefault(key,[]).append({'status_id':v[3],'quantity_units_1e8_btc':dec(v[6]),'side':'A' if v[4] else 'B','price_units_1e8_usd':dec(v[5]),'reduce_only':v[14]})
trades={}
with gzip.open(ROOT/'T-001/data/trades_20251201_00.gz','rt') as f:
    for row,line in enumerate(f):
        r=json.loads(line)
        if r['coin']!='BTC': continue
        z,_,frac=r['time'].rstrip('Z').partition('.')
        t=int(datetime.fromisoformat(z).replace(tzinfo=timezone.utc).timestamp())*10**9+int((frac+'000000000')[:9])
        if not START<t<=STOP: continue
        for leg in r['side_info']:
            if leg['oid'] in wanted:
                key=(token(leg['oid']),t,'B' if r['side']=='A' else 'A',u(r['px']),u(r['sz']))
                trades.setdefault(key,[]).append(row)
label_counts=Counter(); ordinals=Counter(); labeled=[]
for line in (OUT/'identity_candidate_events.jsonl').read_text().splitlines():
    e=json.loads(line); kind=e['kind']; key=(e['local_order_token'],e['candidate_group_time_ns']); v=status.get(key,[])
    e['status_candidates']=v
    if kind=='update':
        match=(key[0],key[1],e['side'],e['price_units_1e8_usd'],e['quantity_before_units_1e8_btc']-e['quantity_after_units_1e8_btc'])
        candidates=trades.get(match,[]); ordinal=ordinals[match]; ordinals[match]+=1
        e['matching_trade_source_row_0based']=candidates[ordinal] if ordinal<len(candidates) else None
        e['observed_label']='matched_trade_decrease' if ordinal<len(candidates) else 'unresolved_decrease'
    elif kind=='remove':
        e['observed_label']='zero_quantity_identity_cleanup' if e['cleanup_zero_size_remove'] else ('observed_cancel' if any(s['status_id'] in {2,4,7,10,11,12,13,14,16} for s in v) else 'unresolved_positive_removal')
    else: e['observed_label']='visible_new_order'
    label_counts[e['observed_label']]+=1; labeled.append(e)
(OUT/'identity_candidate_labeled_events.jsonl').write_text('\n'.join(json.dumps(e,separators=(',',':')) for e in labeled)+'\n')
summary={'classification':'exploratory_real_data_candidate_not_Q16_admission','start_ns':START,'end_ns':STOP,'duration_seconds':20,'initial_region_orders':len(initial),'initial_region_orders_without_observed_birth':sum(x['observed_new_source_row_0based'] is None for x in initial),'event_rows':n,'label_counts':dict(label_counts),'units':{'price':'integer1e-8 USD/BTC','size':'integer1e-8 BTC','time':'Unix ns'},'source_ids':'Local one-way order tokens, no account addresses','scope_limit':'Counts/identities under regional completeness assumptions. Source row order is preserved but is NOT authenticated historical FIFO. Decrements remain lifecycle changes unless separately matched to trades.','runtime_s':time.monotonic()-started,'peak_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,'code_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
(OUT/'identity_candidate_manifest.json').write_text(json.dumps(summary,indent=2)+'\n'); print(json.dumps(summary),flush=True)
