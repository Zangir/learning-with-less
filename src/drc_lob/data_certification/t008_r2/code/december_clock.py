"""December diagnostic: source-ordered joins and strict-price regional candidates.
Not a causal release clock or an affirmative certificate. Integer units: 1e-8.
"""
from array import array
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
import csv, gzip, hashlib, heapq, json, platform, random, resource, struct, time

ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT/'T-001/data'
OUT = ROOT/'T-008/r2/december'
SEED=20260919
random.seed(SEED)
REC=struct.Struct('<QI?B?IIQIi?????BBII')
TERMINAL={2,4,5,7,10,11,12,13,14,16}
START=time.monotonic()
BASE_NS=1764547200000000000
BOUND=BASE_NS+3394_042151019
MIN_NS=BASE_NS+3300_000000000
SCALE=100000000

def units(x):
    v=Decimal(x)*SCALE
    assert v==v.to_integral_value()
    return int(v)
def decode(x): return (x&0x1fffffff)*10**(8-(x>>29))
def ns(s):
    a,_,b=s.rstrip('Z').partition('.')
    return int(datetime.fromisoformat(a).replace(tzinfo=timezone.utc).timestamp())*10**9+int((b+'000000000')[:9])
def iso(v):
    a,b=divmod(v,10**9)
    return datetime.fromtimestamp(a,timezone.utc).strftime('%Y-%m-%dT%H:%M:%S')+f'.{b:09d}Z'
def mark(s):
    x={'utc':datetime.now(timezone.utc).isoformat(),'elapsed_s':round(time.monotonic()-START,3),'note':s,'maxrss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}
    print(json.dumps(x),flush=True)
    with (OUT/'timing.log').open('a') as f: f.write(json.dumps(x)+'\n')
def dump(name,x): (OUT/name).write_text(json.dumps(x,indent=2)+'\n')
def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(2**20),b''): h.update(b)
    return h.hexdigest()

def run():
    mark('Count update multiplicities in preserved source order')
    update_n=Counter(); update_description={}
    with gzip.open(DATA/'book_diffs_20251201_00.gz','rb') as f:
        for row,line in enumerate(f):
            if b'"update"' not in line: continue
            r=json.loads(line)
            if r['coin']!='BTC': continue
            d=r['raw_book_diff']['update']; update_description[r['oid']]=(r['side'],units(r['px']))
            update_n[(r['oid'],units(d['origSz'])-units(d['newSz']))]+=1
    mark(f'Update keys {len(update_n)}')
    # A compact per-order tuple holds min/max insertion, zero, terminal times.
    clocks={}; status_stats=Counter(); last=0
    with gzip.open(DATA/'btc_20251201_00.data.gz','rb') as f:
        for chunk in iter(lambda:f.read(REC.size*32768),b''):
            assert len(chunk)%REC.size==0
            for r in REC.iter_unpack(chunk):
                t,oid=r[0],r[7]
                status_stats['rows']+=1
                status_stats['reversals']+=t<last
                last=t
                typ=0 if (r[3]==1 and not r[11] and r[16]!=2) or (r[11] and r[3]==9) else -1
                if typ<0 and r[3]!=1 and decode(r[6])==0: typ=2
                if typ<0 and r[3] in TERMINAL: typ=4
                if typ<0: continue
                a=clocks.get(oid)
                if a is None: a=array('q',[0]*6); clocks[oid]=a
                if a[typ]==0: a[typ]=t
                a[typ+1]=t
    mark(f'Status map {len(clocks)} ids')
    trades=defaultdict(list); trade_stats=Counter(); sweep=[]; last=0
    with gzip.open(DATA/'trades_20251201_00.gz','rt') as f:
        for row,line in enumerate(f):
            r=json.loads(line); t=ns(r['time'])
            trade_stats['all_rows']+=1; trade_stats['reversals']+=t<last; last=t
            if r['coin']!='BTC': continue
            trade_stats['btc_rows']+=1
            q=units(r['sz']); p=units(r['px'])
            for side in r['side_info']:
                key=(int(side['oid']),q)
                if key in update_n and update_description[key[0]] == ('B' if r['side']=='A' else 'A', p): trades[key].append((t,row))
            if t==BOUND:
                sweep.append({'source_trade_row_0based':row,'time_ns':t,'time_utc':iso(t),'aggressor_side':r['side'],'price_units_1e8_usd':p,'size_units_1e8_btc':q,'trade_dir_override':r.get('trade_dir_override'),'side_info_count':len(r['side_info']),'has_liquidation_field':('liquidation' in r),'liquidation':r.get('liquidation')})
    mark('Trade candidates ready; replay source order')
    dump('clearing_trade_group.json',sweep)
    counters=Counter(); ordinals=Counter(); active={}; known=set(); levels=[Counter(),Counter()]; heaps=[[],[]]
    def top5():
        ans=[]
        for s in (0,1):
            ps=[]
            while heaps[s] and len(ps)<5:
                h=heapq.heappop(heaps[s]); p=h if s else -h
                if levels[s][p]>0 and p not in ps: ps.append(p)
            for p in ps: heapq.heappush(heaps[s],p if s else -p)
            ans.append([[p,levels[s][p]] for p in ps])
        return ans
    exact_last=None; previous_exact_row=None; pending=[]; reversals=[]; missing=[]; groups=[]; samples=[]; inherited_after=[]
    current_t=None; group_first=None; group_last=None; group_unknown=0; prev_unknown_bridge=False
    output=(OUT/'candidate_group_states.jsonl').open('w')
    def finish(next_t,next_row,bridge):
        if current_t is None or current_t<MIN_NS: return
        book=top5(); good=(len(book[0])==5 and len(book[1])==5 and book[0][-1][0]>86931*SCALE and book[1][-1][0]<90376*SCALE and current_t>=BOUND)
        record={'candidate_block_time_ns':current_t,'time_utc':iso(current_t),'first_diff_row_0based':group_first,'last_diff_row_0based':group_last,'next_anchor_time_ns':next_t,'next_anchor_row_0based':next_row,'backward_bridge_from_previous_time':prev_unknown_bridge,'forward_unknown_bridge':bridge,'source_order_cut_unambiguous_under_candidate_anchors':not bridge and next_t is not None,'top5_observed_plus_known_inherited':book,'strict_region_price_condition':good,'bbo_region_price_condition':bool(book[0] and book[1] and book[0][0][0]>86931*SCALE and book[1][0][0]<90376*SCALE and current_t>=BOUND),'semantic_certification':False}
        output.write(json.dumps(record,separators=(',',':'))+'\n'); groups.append((current_t,good,not bridge and next_t is not None))
    with gzip.open(DATA/'book_diffs_20251201_00.gz','rt') as f:
        for row,line in enumerate(f):
            r=json.loads(line)
            if r['coin']!='BTC': continue
            counters['btc_rows']+=1; oid=r['oid']; side=int(r['side']=='A'); p=units(r['px']); raw=r['raw_book_diff']
            kind='remove' if raw=='remove' else next(iter(raw))
            counters[kind]+=1; a=clocks.get(oid); bounds=None; source='missing'
            if kind=='new' and a is not None and a[0]: bounds=(a[0],a[1]); source='illustrative_visible_insertion'
            elif kind=='remove' and a is not None:
                i=2 if a[2] else 4
                if a[i]: bounds=(a[i],a[i+1]); source='zero_or_terminal'
            elif kind=='update':
                key=(oid,units(raw[kind]['origSz'])-units(raw[kind]['newSz'])); ts=trades.get(key,[])
                if ts:
                    if len(ts)==update_n[key]: bounds=(ts[ordinals[key]][0],)*2; source='equal_multiplicity_trade_ordinal'
                    else: bounds=(ts[0][0],ts[-1][0]); source='ambiguous_trade_interval'
                ordinals[key]+=1
            t=bounds[0] if bounds and bounds[0]==bounds[1] else None
            counters[source]+=1
            if t is not None:
                if exact_last is not None and t<exact_last:
                    counters['exact_anchor_reversals']+=1
                    if len(reversals)<100: reversals.append({'source_diff_row_0based':row,'kind':kind,'side':r['side'],'price_units_1e8_usd':p,'previous_time_ns':exact_last,'time_ns':t,'previous_row':previous_exact_row,'source':source})
                if pending:
                    for m in pending:
                        m['previous_anchor_ns']=exact_last; m['next_anchor_ns']=t
                        if len(missing)<3000: missing.append(m)
                    counters['missing_bracket_equal']+=len(pending) if exact_last==t else 0
                    counters['missing_bracket_non_equal']+=len(pending) if exact_last!=t else 0
                if current_t!=t:
                    finish(t,row,bool(pending))
                    prev_unknown_bridge=bool(pending)
                    current_t=t; group_first=row; group_unknown=0
                pending=[]; exact_last=t; previous_exact_row=row
            else:
                pending.append({'source_diff_row_0based':row,'kind':kind,'side':r['side'],'price_units_1e8_usd':p,'bounds_ns':bounds,'clock_source':source})
            group_last=row
            old=active.get(oid)
            if old is not None: levels[old[0]][old[1]]-=old[2]
            if kind=='new':
                q=units(raw[kind]['sz']); known.add(oid)
            elif kind=='update': q=units(raw[kind]['newSz'])
            else: q=0
            if old is None and oid not in known:
                counters['inherited_first_seen']+=1
                if t is not None and t>=BOUND: inherited_after.append({'source_diff_row_0based':row,'time_ns':t,'kind':kind,'side':r['side'],'price_units_1e8_usd':p,'strict_cleared_region':(side==0 and p>86931*SCALE) or (side==1 and p<90376*SCALE)})
                known.add(oid)
            if kind=='remove': active.pop(oid,None)
            else: active[oid]=(side,p,q)
            if q>0: levels[side][p]+=q; heapq.heappush(heaps[side],p if side else -p)
            if t is not None and abs(t-BOUND)<150_000_000 and len(samples)<12:
                samples.append({'source_diff_row_0based':row,'candidate_time_ns':t,'candidate_time_utc':iso(t),'kind':kind,'side':r['side'],'price_units_1e8_usd':p,'post_quantity_units_1e8_btc':q,'clock_source':source})
            if counters['btc_rows']%1000000==0: mark(f"Replay {counters['btc_rows']} BTC records")
    finish(None,None,bool(pending)); output.close()
    eligible=[t for t,g,u in groups if g and u]
    intervals=[]
    for (t,g,u),(t2,g2,u2) in zip(groups,groups[1:]):
        if g and u and g2 and u2:
            if intervals and intervals[-1][1]==t: intervals[-1][1]=t2
            else: intervals.append([t,t2])
    out={'classification':'exploratory_real_data_diagnostic_not_certificate','experiment_ids':['E-200','E-201','E-203','E-204'],'seed':SEED,'units':{'price':'1e-8 USD/BTC','quantity':'1e-8 BTC','time':'Unix ns'},'candidate_rule':'pre-Dec illustrative insertion, terminal/zero removal, exact-size ordinal trade join; no sorting','counter':dict(counters),'status':dict(status_stats),'trades':dict(trade_stats),'sample_rows':samples,'reversals':reversals,'missing_event_examples_truncated_at':3000,'missing_events':missing,'unknown_initial_orders_first_seen_after_clearing':inherited_after,'late_group_count':len(groups),'strict_region_good_unambiguous_groups':len(eligible),'conditional_contiguous_intervals_ns':intervals,'maximum_conditional_interval_s':max([(b-a)/1e9 for a,b in intervals],default=0),'all_scopes_admitted':False,'assumptions_unproven':['source preserves complete chronological diff stream and native event group ordering','candidate joins identify actual exchange event group','ordinary executable price priority applies to sweep','complete activation for every relevant resting order'],'runtime_seconds':round(time.monotonic()-START,3),'peak_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,'environment':{'python':platform.python_version(),'platform':platform.platform(),'thread_limit':1},'code_sha256':sha(Path(__file__)),'input_sha256':{p.name:sha(p) for p in DATA.iterdir() if p.name in {'book_diffs_20251201_00.gz','btc_20251201_00.data.gz','trades_20251201_00.gz'}}}
    dump('candidate_diagnostic.json',out)
    dump('sample_rows.json',samples[:3])
    mark(f"Done: {dict(counters)}; max interval {out['maximum_conditional_interval_s']}")
if __name__=='__main__': run()
