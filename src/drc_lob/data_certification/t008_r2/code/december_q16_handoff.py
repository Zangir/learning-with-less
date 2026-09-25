"""Enumerate all count-one anchor candidates without filtering future outcomes."""
from pathlib import Path
from collections import Counter
import hashlib,json
ROOT=Path(__file__).resolve().parents[1]; D=ROOT/'december'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
counts={r['time_ns']:r['top5_counts'] for r in map(json.loads,(D/'candidate_group_counts.jsonl').read_text().splitlines())}
comp=list(map(json.loads,(D/'snapshot_comparison_rows.jsonl').read_text().splitlines()))
initial=json.loads((D/'identity_candidate_initial.json').read_text()); state={r['local_order_token']:dict(r) for r in initial['orders']}
manifest=json.loads((D/'identity_candidate_manifest.json').read_text()); start,end=manifest['start_ns'],manifest['end_ns']
events=list(map(json.loads,(D/'identity_candidate_labeled_events.jsonl').read_text().splitlines()))
idx=0; anchors=[]; matchcount=Counter()
for c in comp:
    if len(c['candidate_times_ns'])!=1: continue
    t=c['candidate_times_ns'][0]; counts_equal=counts[t]==c['snapshot_top5_order_counts']
    matchcount['unique_same_ms_count_rows']+=1; matchcount['all_top5_counts_equal']+=counts_equal
    if c['Q18_price_region']:
        matchcount['regional_count_rows']+=1; matchcount['regional_top5_counts_equal']+=counts_equal
    if not start<t<=end: continue
    while idx<len(events) and events[idx]['candidate_group_time_ns']<=t:
        e=events[idx]; token=e['local_order_token']
        if e['kind']=='remove' or e['quantity_after_units_1e8_btc']==0: state.pop(token,None)
        else: state[token]={'local_order_token':token,'side':e['side'],'price_units_1e8_usd':e['price_units_1e8_usd'],'quantity_units_1e8_btc':e['quantity_after_units_1e8_btc'],'observed_new_source_row_0based':e['source_new_row_0based']}
        idx+=1
    if not(c['unique_same_ms_terminal_top5_equal'] and counts_equal): continue
    for side,levels in enumerate(c['snapshot_top5']):
        for level,(price,q) in enumerate(levels):
            if c['snapshot_top5_order_counts'][side][level]!=1: continue
            s='B' if side==0 else 'A'
            same=[o for o in state.values() if o['side']==s and o['price_units_1e8_usd']==price and o['quantity_units_1e8_btc']>0]
            assert len(same)==1 and same[0]['quantity_units_1e8_btc']==q
            anchors.append({'anchor_index':len(anchors),'candidate_group_time_ns':t,'snapshot_event_time_ms':c['snapshot_event_time_ms'],'snapshot_source_row_0based':c['snapshot_source_row_0based'],'source_group_first_row_0based':c['candidate_source_first_row_0based'],'side':s,'price_units_1e8_usd':price,'quantity_units_1e8_btc':q,'positive_order_count':1,'local_order_token':same[0]['local_order_token'],'observed_new_source_row_0based':same[0]['observed_new_source_row_0based'],'selection':'all observed count-one top5 levels in source snapshot then side then level order, no future event/outcome filter','initial_within_level_priority':'trivial_one_positive_identity_at_cut','subsequent_FIFO_certified':False,'admitted':False})
(D/'count_one_anchor_candidates.json').write_text(json.dumps({'classification':'exploratory_real_data_candidate_not_admitted','anchor_count':len(anchors),'anchors':anchors},indent=2)+'\n')
(D/'snapshot_order_count_comparison.json').write_text(json.dumps({'classification':'exploratory_cross_source_count_consistency','counts':dict(matchcount)},indent=2)+'\n')
files=['identity_candidate_initial.json','identity_candidate_labeled_events.jsonl','identity_candidate_manifest.json','count_one_anchor_candidates.json','snapshot_order_count_comparison.json','conditional_proof.json']
handoff={'schema_version':'2.0.0-candidate','task':'T-008','scope':'Q16 bounded conditional observed identity/quantity candidate','admitted':False,'data_class':'exploratory_real','split':'December1_development','window_ns':[start,end],'units':{'price':'integer1e-8 USD/BTC','quantity':'integer1e-8 BTC','time':'Unix nanoseconds candidate group time; independent snapshots rounded to milliseconds'},'initial_positive_orders':manifest['initial_region_orders'],'source_order':'source_diff_row_0based strictly increasing; do not reorder across groups or invent within-group priority','zero_projection':'Identity may remain in lifecycle at zero size; positive queue count excludes it. Explicit later zero cleanup is flagged and non-economic. Consumers own horizon semantics.','observed_labels':manifest.get('label_counts',{}),'candidate_anchors':len(anchors),'anchor_selection':'All mirror-matched count-one top5 levels in this bounded interval, in original snapshot order; no survivor/fill/cap/outcome filtering. This is a candidate inventory, not the final consumer cohort.','initial_priority_fact':'A mirrored positive count of one, matching one replay identity and exact aggregate quantity, gives trivial initial within-level ordering conditional on source/time-state correspondence.','remaining_conditions':['Independent review of regional completeness and timestamp correspondence','Subsequent insertion queue priority is not authenticated; current ALO priority fees must not be applied retroactively','Size lattice does not establish legal historical minimum lot','Observed real fills/cancels are not counterfactual probe executions','Roundtrip receive times are unavailable; no receive-time claim','Eight-economic-event completeness and censoring/first1000 cohort selection are consumer responsibilities; keep all candidates'], 'files':{f:{'path':str(D/f),'sha256':sha(D/f)} for f in files}}
(ROOT/'q16_handoff.json').write_text(json.dumps(handoff,indent=2)+'\n')
print(json.dumps({'count_comparison':dict(matchcount),'anchors':len(anchors),'labels':manifest.get('label_counts')},indent=2))
