"""Extend only fixed censored Q16 price levels using already retained December bytes."""
from bisect import bisect_right
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
import gzip, hashlib, json, os, random, resource, struct, time

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT/'T-008/r3/participant'
OLD = ROOT/'T-008/r2/december'
DATA = ROOT/'T-001/data'
SEED = 20260919
random.seed(SEED)
os.sched_setaffinity(0, {min(os.sched_getaffinity(0))})
resource.setrlimit(resource.RLIMIT_AS, (4*1024**3, 4*1024**3))
START = time.monotonic()
REC = struct.Struct('<QI?B?IIQIi?????BBII')


def token(oid): return hashlib.sha256(('T008-local-order-'+str(oid)).encode()).hexdigest()[:20]
def units(value):
    a, _, b = value.partition('.')
    assert len(b) <= 8
    return int(a)*100000000+int((b+'00000000')[:8])
def decode(value): return (value & 0x1fffffff)*10**(8-(value >> 29))
def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for data in iter(lambda:stream.read(1024**2),b''): h.update(data)
    return h.hexdigest()
def ns(value):
    a, _, b=value.rstrip('Z').partition('.')
    return int(datetime.fromisoformat(a).replace(tzinfo=timezone.utc).timestamp())*1000000000+int((b+'000000000')[:9])
def mark(note): print(json.dumps(dict(utc=datetime.now(timezone.utc).isoformat(),elapsed_s=time.monotonic()-START,note=note)),flush=True)


def main():
    request_path=ROOT/'T-009/r3/q16_incomplete_horizons.json'
    requests=json.loads(request_path.read_text())
    levels={(r['side'],r['price_units_1e8_usd']) for r in requests}
    old_events=list(map(json.loads,(OLD/'identity_candidate_events.v2.jsonl').read_text().splitlines()))
    initial=json.loads((OLD/'identity_candidate_initial.v2.json').read_text())
    old_manifest=json.loads((OLD/'identity_candidate_manifest.v2.json').read_text())
    start_ns=old_manifest['end_ns']
    groups=[r for r in map(json.loads,(OLD/'candidate_group_states.jsonl').read_text().splitlines())
            if r['next_anchor_time_ns'] and r['source_order_cut_unambiguous_under_candidate_anchors']]
    starts=[r['first_diff_row_0based'] for r in groups]
    suffix_groups=[r for r in groups if r['candidate_block_time_ns']>start_ns]
    first_source=suffix_groups[0]['first_diff_row_0based']
    last_source=suffix_groups[-1]['last_diff_row_0based']
    resting={}
    birth={}
    for row in initial['orders']:
        if (row['side'],row['price_units_1e8_usd']) in levels:
            resting[row['local_order_token']]=row['quantity_units_1e8_btc']
            birth[row['local_order_token']]=row['observed_new_source_row_0based']
    for row in old_events:
        if (row['side'],row['price_units_1e8_usd']) not in levels: continue
        oid=row['local_order_token']
        if row['kind']=='new': birth[oid]=row['source_new_row_0based']
        if row['kind']=='remove': resting.pop(oid,None)
        else: resting[oid]=row['quantity_after_units_1e8_btc']
    extensions=[]
    needed_ids=set()
    stats=Counter()
    mark(f'Extend {len(requests)} fixed anchors at {len(levels)} price levels')
    with gzip.open(DATA/'book_diffs_20251201_00.gz','rb') as stream:
        for ordinal,line in enumerate(stream):
            if ordinal<first_source: continue
            if ordinal>last_source: break
            if b'"BTC"' not in line: continue
            row=json.loads(line)
            if row['coin']!='BTC': continue
            price=units(row['px']); side=row['side']
            if (side,price) not in levels: continue
            group=groups[bisect_right(starts,ordinal)-1]
            assert group['first_diff_row_0based']<=ordinal<=group['last_diff_row_0based']
            oid=token(row['oid']); needed_ids.add(row['oid'])
            raw=row['raw_book_diff']; kind='remove' if raw=='remove' else next(iter(raw))
            old=resting.get(oid)
            if kind=='new':
                assert oid not in resting
                quantity=units(raw['new']['sz']); birth[oid]=ordinal
            elif kind=='update':
                assert old==units(raw['update']['origSz']), (ordinal,old,raw)
                quantity=units(raw['update']['newSz'])
            else: quantity=0
            if kind=='remove': resting.pop(oid,None)
            else: resting[oid]=quantity
            event=dict(source_diff_row_0based=ordinal,candidate_group_time_ns=group['candidate_block_time_ns'],
                local_order_token=oid,kind=kind,side=side,price_units_1e8_usd=price,
                quantity_before_units_1e8_btc=old,quantity_after_units_1e8_btc=quantity,
                source_new_row_0based=birth.get(oid),cleanup_zero_size_remove=kind=='remove' and old==0,
                operation_semantics='lifecycle_assignment_not_fill_label',fifo_truth_certified=False,
                atomic_group_certified=False,closure_witness_source_row=group['next_anchor_row_0based'],
                closure_witness_time_ns=group['next_anchor_time_ns'])
            extensions.append(event); stats[kind]+=1
    mark(f'Raw suffix replay complete: {len(extensions)} price-level events')
    status=defaultdict(list)
    with gzip.open(DATA/'btc_20251201_00.data.gz','rb') as stream:
        ordinal=0
        for chunk in iter(lambda:stream.read(REC.size*32768),b''):
            for row in REC.iter_unpack(chunk):
                if row[7] in needed_ids and row[0]>start_ns:
                    status[(token(row[7]),row[0])].append(dict(status_source_row=ordinal,status_id=row[3],
                        quantity_units_1e8_btc=decode(row[6]),side='A' if row[4] else 'B',
                        price_units_1e8_usd=decode(row[5]),reduce_only=row[14]))
                ordinal+=1
    trades=defaultdict(list)
    with gzip.open(DATA/'trades_20251201_00.gz','rb') as stream:
        for ordinal,line in enumerate(stream):
            row=json.loads(line)
            if row['coin']!='BTC': continue
            stamp=ns(row['time'])
            if stamp<=start_ns: continue
            price=units(row['px']); quantity=units(row['sz']); resting_side='B' if row['side']=='A' else 'A'
            if (resting_side,price) not in levels: continue
            for leg in row['side_info']:
                if leg['oid'] not in needed_ids: continue
                oid=token(leg['oid'])
                others=[token(r['oid']) for r in row['side_info'] if r['oid']!=leg['oid']]
                trades[(oid,stamp,resting_side,price,quantity)].append(dict(source_trade_row=ordinal,
                    candidate_taker_token=others[0] if len(others)==1 else None,trade_time_text=row['time']))
    multiplicity=Counter()
    for event in extensions:
        if event['kind']=='update':
            key=(event['local_order_token'],event['candidate_group_time_ns'],event['side'],event['price_units_1e8_usd'],
                 event['quantity_before_units_1e8_btc']-event['quantity_after_units_1e8_btc'])
            multiplicity[key]+=1
    ordinals=Counter(); labels=Counter()
    for event in extensions:
        key=(event['local_order_token'],event['candidate_group_time_ns'])
        event['status_candidates']=status[key]
        if event['kind']=='new': event['observed_label']='visible_new_order'
        elif event['kind']=='remove':
            if event['cleanup_zero_size_remove']: event['observed_label']='zero_quantity_identity_cleanup'
            elif any(r['status_id'] in {2,4,7,10,11,12,13,14,16} for r in status[key]): event['observed_label']='observed_cancel'
            else: event['observed_label']='unresolved_positive_removal'
        else:
            lookup=key+(event['side'],event['price_units_1e8_usd'],event['quantity_before_units_1e8_btc']-event['quantity_after_units_1e8_btc'])
            candidates=trades[lookup]; index=ordinals[lookup];ordinals[lookup]+=1
            if len(candidates)==multiplicity[lookup] and all(r['candidate_taker_token'] for r in candidates):
                match=candidates[index];event['observed_label']='matched_trade_decrease'
                event['matching_trade_source_row_0based']=match['source_trade_row']
                event['candidate_taker_token']=match['candidate_taker_token']
                event['candidate_taker_price_group_key']=f"{match['candidate_taker_token']}:{key[1]}:{event['price_units_1e8_usd']}"
                event['candidate_taker_full_group_key']=f"{match['candidate_taker_token']}:{key[1]}"
                event['trade_time_text']=match['trade_time_text']
                event['trade_binding_rule']='exact maker/side/price/time/size; equal multiplicity preserving trade source order'
            else:
                event['observed_label']='unresolved_decrease'
                event['matching_trade_candidates']=candidates
        labels[event['observed_label']]+=1
    output=OUT/'q16_extension_events.v3.jsonl'
    assert not output.exists()
    output.write_text(''.join(json.dumps(r,separators=(',',':'))+'\n' for r in extensions))
    completion=[]
    all_rows=old_events+extensions
    for request in requests:
        sequence=[r for r in all_rows if (r['side'],r['price_units_1e8_usd'])==(request['side'],request['price_units_1e8_usd'])
                  and r['source_diff_row_0based']>request['anchor_source_seq']]
        economic=[];last_key=None;seen=Counter()
        for row in sequence:
            label=row['observed_label']
            if label=='zero_quantity_identity_cleanup': continue
            key=row.get('candidate_taker_price_group_key') if label=='matched_trade_decrease' else None
            if key is not None and key==last_key:
                economic[-1]['last_source_row']=row['source_diff_row_0based']
                economic[-1]['last_candidate_time_ns']=row['candidate_group_time_ns']
                economic[-1]['raw_event_rows'].append(row['source_diff_row_0based'])
            else:
                economic.append(dict(label=label,last_source_row=row['source_diff_row_0based'],
                    last_candidate_time_ns=row['candidate_group_time_ns'],raw_event_rows=[row['source_diff_row_0based']],candidate_trade_key=key))
                if key:seen[key]+=1
            last_key=key
        first_eight=economic[:8]
        completion.append(dict(episode_id=request['episode_id'],anchor_source_seq=request['anchor_source_seq'],
            original_completed_economic_events=request['completed_economic_events'],
            available_closed_candidate_economic_events=len(economic),eight_events_available=len(economic)>=8,
            first_eight_events=first_eight,
            unresolved_labels_before_eighth=sum(r['label'].startswith('unresolved') for r in first_eight),
            repeated_noncontiguous_trade_keys=sum(v>1 for v in seen.values()),
            empirical_admission=False,original_cohort_membership_preserved=True))
    (OUT/'q16_horizon_completion_candidates.json').write_text(json.dumps(completion,indent=2)+'\n')
    summary=dict(schema='t008-q16-fixed-cohort-extension/3',origin='exploratory_real',admitted=False,
        fixed_anchor_count=len(requests),target_level_count=len(levels),extension_start_exclusive_ns=start_ns,
        last_closed_candidate_group_ns=suffix_groups[-1]['candidate_block_time_ns'],extension_rows=len(extensions),
        labels=dict(labels),eight_closed_candidate_events_available=sum(r['eight_events_available'] for r in completion),
        still_incomplete=sum(not r['eight_events_available'] for r in completion),
        unresolved_labels_before_eighth=sum(r['unresolved_labels_before_eighth'] for r in completion),
        grouping_semantics='Original candidate contiguous taker/time/price projection retained; native atomicity unproved.',
        clock='Frozen candidate-group source-position map; no receipt/admission claim.',
        no_additional_market_data_acquired=True,runtime_s=time.monotonic()-START,
        peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,code_sha256=sha(Path(__file__)),
        inputs={str(p):sha(p) for p in (request_path,OLD/'identity_candidate_events.v2.jsonl',OLD/'identity_candidate_initial.v2.json',
             OLD/'candidate_group_states.jsonl',DATA/'book_diffs_20251201_00.gz',DATA/'btc_20251201_00.data.gz',DATA/'trades_20251201_00.gz')},
        files={p.name:dict(path=str(p),sha256=sha(p)) for p in (output,OUT/'q16_horizon_completion_candidates.json')})
    (OUT/'q16_extension_contract.v3.json').write_text(json.dumps(summary,indent=2)+'\n')
    mark('Fixed-cohort bounded extension complete')
    print(json.dumps(summary,indent=2),flush=True)


if __name__=='__main__':main()
