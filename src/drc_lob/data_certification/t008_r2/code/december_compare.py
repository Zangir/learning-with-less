"""Independent mirror comparison with explicit millisecond coarsening bounds."""
from pathlib import Path
import bisect, hashlib, json
from decimal import Decimal
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'december'
SRC=ROOT/'sources/btc_20251201_00.jsonl'
SCALE=100000000

def u(v):
    x=Decimal(v)*SCALE
    assert x==x.to_integral_value()
    return int(x)
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
rows=[json.loads(s) for s in (OUT/'candidate_group_states.jsonl').read_text().splitlines()]
rows=[r for r in rows if r['source_order_cut_unambiguous_under_candidate_anchors'] and r['next_anchor_time_ns']]
ts=[r['candidate_block_time_ns'] for r in rows]
counts={'snapshot_rows':0,'late_overlap':0,'unique_same_ms_group':0,'multiple_same_ms_groups':0,'no_same_ms_group':0,'top5_exact_same_ms':0,'BBO_exact_same_ms':0,'strict_previous_top5_exact':0,'snapshot_matches_rounding_compatible_state':0,'regional_top5_rows':0,'regional_top5_exact_same_ms':0,'regional_BBO_rows':0,'regional_BBO_exact_same_ms':0,'regional_top5_all_snapshot_rows':0,'regional_top5_all_snapshot_exact':0,'regional_bbo_all_snapshot_rows':0,'regional_bbo_all_snapshot_exact':0}
comparisons=[]
for source_row,line in enumerate(SRC.read_text().splitlines()):
    r=json.loads(line); d=r['raw']['data']; counts['snapshot_rows']+=1
    low=d['time']*1000000; high=low+1000000
    if low<ts[0] or low>ts[-1]+1000000: continue
    counts['late_overlap']+=1
    levels=[[[u(x['px']),u(x['sz'])] for x in side[:5]] for side in d['levels']]
    a=bisect.bisect_left(ts,low); b=bisect.bisect_left(ts,high)
    prev=bisect.bisect_right(ts,low)-1
    previous_equal=prev>=0 and rows[prev]['top5_observed_plus_known_inherited']==levels
    counts['strict_previous_top5_exact']+=previous_equal
    matched_same=[j for j in range(a,b) if rows[j]['top5_observed_plus_known_inherited']==levels]
    counts['snapshot_matches_rounding_compatible_state']+=bool(previous_equal or matched_same)
    same_equal=None; bbo_equal=None; q17=False; q18=False
    if b-a==1:
        counts['unique_same_ms_group']+=1
        c=rows[a]; same_equal=c['top5_observed_plus_known_inherited']==levels
        bbo_equal=[x[0] for x in c['top5_observed_plus_known_inherited']]==[x[0] for x in levels]
        counts['top5_exact_same_ms']+=same_equal; counts['BBO_exact_same_ms']+=bbo_equal
        q17=c['bbo_region_price_condition']; q18=c['strict_region_price_condition']
        counts['regional_top5_rows']+=q18; counts['regional_top5_exact_same_ms']+=q18 and same_equal
        counts['regional_BBO_rows']+=q17; counts['regional_BBO_exact_same_ms']+=q17 and bbo_equal
    else: counts['multiple_same_ms_groups' if b-a>1 else 'no_same_ms_group']+=1
    latest=b-1
    if latest>=0:
        counts['regional_top5_all_snapshot_rows']+=rows[latest]['strict_region_price_condition']
        counts['regional_top5_all_snapshot_exact']+=rows[latest]['strict_region_price_condition'] and rows[latest]['top5_observed_plus_known_inherited']==levels
        counts['regional_bbo_all_snapshot_rows']+=rows[latest]['bbo_region_price_condition']
        counts['regional_bbo_all_snapshot_exact']+=rows[latest]['bbo_region_price_condition'] and [x[0] for x in rows[latest]['top5_observed_plus_known_inherited']]==[x[0] for x in levels]
    comparisons.append({'snapshot_source_row_0based':source_row,'snapshot_event_time_ms':d['time'],'outer_time':r['time'],'rounding_bin_ns':[low,high],'candidate_times_ns':ts[a:b],'unique_same_ms_terminal_top5_equal':same_equal,'unique_same_ms_terminal_BBO_equal':bbo_equal,'strict_previous_terminal_top5_equal':previous_equal,'Q17_price_region':q17,'Q18_price_region':q18,'snapshot_top5':levels,'candidate_top5':rows[a]['top5_observed_plus_known_inherited'] if b-a==1 else None,'candidate_source_first_row_0based':rows[a]['first_diff_row_0based'] if b-a==1 else None,'snapshot_top5_order_counts':[[x['n'] for x in side[:5]] for side in d['levels']]})
result={'classification':'exploratory_real_data_cross_source_consistency_not_certificate','counts':counts,'join':'Exact exchange-millisecond bins only. Strict-prior comparison uses candidate time<=ms_lower_bound. Same-bin comparison is equality evidence at coarsened time, never an operational future-state feature join. All compatible candidate terminal cuts are preserved; no nearest-future join.','units':{'prices':'integer 1e-8 USD/BTC','size':'integer 1e-8 BTC','snapshot_time':'Unix milliseconds','candidate_time':'Unix nanoseconds'},'scope':'late existing hour; no receipt timing/FIFO/independent_day/market_performance claim','provenance':{'snapshot':str(SRC),'snapshot_sha256':sha(SRC),'candidate_sha256':sha(OUT/'candidate_group_states.jsonl'),'code_sha256':sha(Path(__file__))},'mismatches':[c for c in comparisons if c['unique_same_ms_terminal_top5_equal'] is False][:20]}
(OUT/'snapshot_comparison.json').write_text(json.dumps(result,indent=2)+'\n')
(OUT/'snapshot_comparison_rows.jsonl').write_text('\n'.join(json.dumps(c,separators=(',',':')) for c in comparisons)+'\n')
print(json.dumps(counts,indent=2))
