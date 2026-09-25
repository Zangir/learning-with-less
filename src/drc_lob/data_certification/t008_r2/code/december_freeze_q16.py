"""Freeze Q16 exploratory inputs with explicit counterparty-based candidate groups."""
from pathlib import Path
from collections import Counter
from decimal import Decimal
import gzip,hashlib,json,os,shutil
ROOT=Path(__file__).resolve().parents[1]; D=ROOT/'december'; DATA=ROOT.parents[1]/'T-001/data'
def tok(oid):return hashlib.sha256(('T008-local-order-'+str(oid)).encode()).hexdigest()[:20]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def fixed(s):return int(Decimal(s)*100000000)
def write_atomic(path,obj):
    temp=path.with_suffix(path.suffix+'.tmp'); temp.write_text(json.dumps(obj,indent=2)+'\n',encoding='utf-8'); os.replace(temp,path)
events=list(map(json.loads,(D/'identity_candidate_labeled_events.jsonl').read_text().splitlines()))
needed={e['matching_trade_source_row_0based']:e for e in events if e['observed_label']=='matched_trade_decrease'}
assert len(needed)==559
trade_rows={}
with gzip.open(DATA/'trades_20251201_00.gz','rt') as f:
    for row,line in enumerate(f):
        if row in needed: trade_rows[row]=json.loads(line)
assert len(trade_rows)==len(needed)
keys=Counter()
for e in events:
    e['atomic_group_certified']=False
    if e['observed_label']=='matched_trade_decrease':
        r=trade_rows[e['matching_trade_source_row_0based']]
        assert r['coin']=='BTC' and r['side']!=e['side'] and fixed(r['px'])==e['price_units_1e8_usd']
        assert fixed(r['sz'])==e['quantity_before_units_1e8_btc']-e['quantity_after_units_1e8_btc']
        parts=[tok(x['oid']) for x in r['side_info']]
        assert len(parts)==2 and parts.count(e['local_order_token'])==1
        other=next(x for x in parts if x!=e['local_order_token'])
        e['candidate_taker_token']=other
        e['candidate_taker_price_group_key']=f"{other}:{e['candidate_group_time_ns']}:{e['price_units_1e8_usd']}"
        e['candidate_taker_full_group_key']=f"{other}:{e['candidate_group_time_ns']}"
        e['trade_time_text']=r['time']
        e['atomicity_limit']='Counterparty/time/price grouping is a candidate grouping only. Original action/block envelope is absent; do not treat each maker fragment as one atomic T, nor certify group membership solely from equal time.'
        keys[e['candidate_taker_price_group_key']]+=1
path=D/'identity_candidate_events.v2.jsonl'; assert not path.exists()
temp=path.with_suffix('.jsonl.tmp'); temp.write_text('\n'.join(json.dumps(e,separators=(',',':')) for e in events)+'\n',encoding='utf-8');os.replace(temp,path)
for src,dst in [('identity_candidate_initial.json','identity_candidate_initial.v2.json'),('count_one_anchor_candidates.json','count_one_anchor_candidates.v2.json'),('snapshot_order_count_comparison.json','snapshot_order_count_comparison.v2.json')]:
    assert not (D/dst).exists();shutil.copyfile(D/src,D/dst)
manifest=json.loads((D/'identity_candidate_manifest.json').read_text()); manifest['candidate_taker_price_groups']=len(keys);manifest['candidate_groups_with_multiple_maker_legs']=sum(v>1 for v in keys.values()); manifest['largest_candidate_maker_legs_per_group']=max(keys.values());manifest['atomic_groups_certified']=False;manifest['freeze_code_sha256']=sha(Path(__file__));manifest['files']={n:sha(D/n) for n in ['identity_candidate_events.v2.jsonl','identity_candidate_initial.v2.json','count_one_anchor_candidates.v2.json','snapshot_order_count_comparison.v2.json']};write_atomic(D/'identity_candidate_manifest.v2.json',manifest)
h=json.loads((ROOT/'q16_handoff.json').read_text());h['schema_version']='2.0.1-candidate-frozen';h['immutable_inputs']=True;h['observed_atomic_trade_groups_certified']=False;h['candidate_trade_grouping']='candidate_taker_price_group_key=(other trade leg local token,candidate exchange-group ns,price8) is bound to actual matching trade rows. Original action/block identity is absent; grouping is diagnostic, never an accepted atomic T label.';h['files']={n:{'path':str(D/n),'sha256':sha(D/n)} for n in ['identity_candidate_events.v2.jsonl','identity_candidate_initial.v2.json','count_one_anchor_candidates.v2.json','snapshot_order_count_comparison.v2.json','identity_candidate_manifest.v2.json','conditional_proof.json']};h['freeze_code_sha256']=sha(Path(__file__));write_atomic(ROOT/'q16_handoff.v2.json',h);write_atomic(ROOT/'q16_handoff.json',h)
print(json.dumps({'events_sha256':sha(path),'handoff_sha256':sha(ROOT/'q16_handoff.v2.json'),'candidate_price_groups':len(keys),'multileg_groups':sum(v>1 for v in keys.values()),'event_rows':len(events)},indent=2))
