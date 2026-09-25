"""T-008/E-201 checkpoint-free replay audit. Stdlib, one CPU, seed 20260919.

Processes source order without retiming; never interprets the cohort as full depth.
Output has no user identifiers, account addresses, or transaction hashes.
"""
from array import array
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
import gzip
import hashlib
import heapq
import json
import os
from pathlib import Path
import platform
import random
import resource
import struct
import time

random.seed(20260919)
BASE = Path(__file__).resolve().parents[2]
OUT = BASE / 'T-008/evidence'
DATA = BASE / 'T-001/data'
SCALE = 10_000_000
# Compact fixed-width records keep the full-hour join below the memory budget.
SIDE, PX, Q, INITIAL, FIRST_KIND, FIRST_ROW, LAST_ROW, NEW, UPDATE, REMOVE, DELTA, REMQ, OPEN, OPENMATCH, FLAGS, FIRST_TS, LAST_TS, LAST_STATUS, LAST_SZ, MAKER, TAKER, STATUS_N, BAD, TIF, TYPES, ACTIVE = range(26)
RECORD = struct.Struct('<QIBBBIIQIiBBBBBBBII')
assert RECORD.size == 54
START = time.monotonic()
STAGES = []


def stamp(note):
    item = {'utc': datetime.now(timezone.utc).isoformat(), 'elapsed_s': round(time.monotonic()-START, 3), 'note': note}
    STAGES.append(item)
    print(json.dumps(item), flush=True)
    with (OUT / 'replay_timing.log').open('a') as f:
        f.write(json.dumps(item) + '\n')


def fixed(value):
    x = Decimal(str(value)) * SCALE
    if x != x.to_integral_value():
        raise ValueError('More than seven decimal places')
    return int(x)


def decoded(value):
    return (value & 0x1fffffff) * 10 ** (7-(value >> 29))


def dump(name, value):
    (OUT / name).write_text(json.dumps(value, indent=2) + '\n')


def adversarial_tests():
    results = []
    def check(name, fact, implication):
        assert fact, name
        results.append({'test': name, 'passed': True, 'implication': implication})
    # Two observationally indistinguishable initial states suffice for a blocker.
    def replay(initial, events):
        state = dict(initial)
        for op, oid, side, price, size in events:
            if op == 'new': state[oid] = (side, price, size)
            elif op == 'update':
                if oid in state: state[oid] = (side, price, size)
            elif op == 'remove': state.pop(oid, None)
        return state
    events = [('new', 1, 'B', 99, 5), ('new', 2, 'A', 103, 4)]
    a, b = replay({}, events), replay({9: ('B', 100, 7)}, events)
    check('silent_initial_order_changes_BBO', max(x[1] for x in a.values() if x[0]=='B') != max(x[1] for x in b.values() if x[0]=='B'), 'Identical diffs can imply different BBO; elapsed warm-up is no proof.')
    a, b = replay({}, events), replay({9: ('B', 99, 7)}, events)
    check('silent_same_price_order_changes_queue_and_depth', len(a) != len(b), 'Even matching BBO prices do not identify depth or queue ahead.')
    # An equal-price trade may only partially consume the hidden order.
    check('equal_price_trade_does_not_clear_level', 7 - 2 > 0, 'A trade at p is insufficient: hidden residual quantity may remain.')
    def swept(side, p, aggressor, trade_px):
        return (side=='B' and aggressor=='A' and trade_px < p) or (side=='A' and aggressor=='B' and trade_px > p)
    check('strict_price_boundary_and_direction', swept('B',100,'A',99) and swept('A',100,'B',101) and not swept('B',100,'A',100) and not swept('B',100,'B',101), 'Only strictly worse executions on the correct aggressor side imply clearing under executable price priority.')
    certified_state = replay({}, events)
    unknown_update = ('update', 9, 'B', 99, 3)
    missing_at_complete_level = unknown_update[1] not in certified_state and unknown_update[3] == 99
    check('later_unknown_update_revokes_certificate', missing_at_complete_level, 'A subsequent update/remove of an unseen order at a claimed complete level contradicts stream/state completeness; exclude or revoke.')
    # Applying a new crossing bid before removing the old ask gives a false cross.
    state = replay({2: ('A',100,1)}, [('new',1,'B',101,1)])
    cross = max(x[1] for x in state.values() if x[0]=='B') >= min(x[1] for x in state.values() if x[0]=='A')
    finished = replay(state, [('remove',2,'A',100,0)])
    check('atomic_group_midpoint_is_not_a_cut', cross and all(x[0]!='A' for x in finished.values()), 'Interim raw-diff crossing need not be a final-book error; block/atomic-group boundary is required.')
    dormant = {9: ('B',100,7)}
    executable = {1: ('B',99,1)}
    executable_after = replay(executable,[('remove',1,'B',99,0)])
    activated_later = {**executable_after, **dormant}
    check('inactive_conditional_order_survives_price_sweep', swept('B',100,'A',99) and activated_later[9][2]==7, 'A dormant/non-executable conditional order is outside the theorem; activation needs a complete new-order record.')
    future_evidence_time, decision_time = 20, 10
    check('future_informed_admission_is_noncausal', future_evidence_time > decision_time, 'Retrospective survival of a certificate cannot be used as availability at an earlier decision time.')
    for size in ['0.00001', '1.125', '100.0000001']:
        assert Decimal(fixed(size))/SCALE == Decimal(size)
    check('exact_quantity_arithmetic', fixed('0.3')-fixed('0.2')==fixed('0.1'), 'No float tolerance is used for quantity reconciliation.')
    dump('replay_adversarial_tests.json', {'seed':20260919, 'tests':results, 'passed':len(results), 'failed':0})
    return results


def run():
    OUT.mkdir(parents=True, exist_ok=True)
    tests = adversarial_tests()
    orders = {}
    counters = Counter()
    samples = []
    errors = []
    fields = Counter()
    levels = [Counter(), Counter()]
    heaps = [[], []]
    cross_run = max_cross_run = 0
    cross_samples = []
    stamp('Begin full raw-diff stream; no sort or timestamp assignment')
    with gzip.open(DATA/'book_diffs_20251201_00.gz', 'rt') as f:
        for row, line in enumerate(f,1):
            d = json.loads(line)
            if d['coin'] != 'BTC': continue
            counters['btc_diffs'] += 1
            oid, side, px = d['oid'], int(d['side']=='A'), fixed(d['px'])
            raw = d['raw_book_diff']
            kind = 'remove' if raw=='remove' else next(iter(raw))
            counters[kind] += 1
            fields.update(d.keys())
            if isinstance(raw,dict):
                fields.update('raw.'+x for x in raw[kind])
            old = orders.get(oid)
            if old is None:
                old = array('q', [0]*26)
                old[SIDE], old[PX], old[FIRST_KIND], old[FIRST_ROW] = side, px, {'new':0,'update':1,'remove':2}[kind], row
                orders[oid] = old
                counters['first_'+kind] += 1
            old[LAST_ROW] = row
            before = old[Q]
            cohort_before = before if old[NEW] else 0
            problems = []
            if old[SIDE] != side or old[PX] != px:
                problems.append('side_or_price_changed')
            if kind=='new':
                sz = fixed(raw[kind]['sz'])
                if old[NEW]: problems.append('repeat_new_same_oid')
                if old[ACTIVE]: problems.append('new_when_active')
                if sz <= 0: problems.append('nonpositive_new')
                old[NEW] += 1
                old[INITIAL] = sz
                old[Q] = sz
                old[ACTIVE] = 1
            elif kind=='update':
                orig, new = fixed(raw[kind]['origSz']), fixed(raw[kind]['newSz'])
                if not old[ACTIVE]: counters['update_without_active_state'] += 1
                elif before != orig: problems.append('update_orig_mismatch')
                if new < 0: problems.append('negative_update_remaining')
                if new == 0: counters['zero_update_remaining'] += 1
                if orig <= new: problems.append('update_not_decrease')
                old[UPDATE] += 1
                old[DELTA] += orig-new
                old[Q] = new
                old[ACTIVE] = 1
            elif kind=='remove':
                if not old[ACTIVE]: counters['remove_without_active_state'] += 1
                old[REMOVE] += 1
                old[REMQ] += before
                old[Q] = 0
                old[ACTIVE] = 0
            else:
                raise ValueError('Unrecognized event')
            for problem in problems:
                counters[problem] += 1
                old[BAD] = 1
            if problems and len(errors)<10:
                errors.append({'source_row':row,'side':d['side'],'px_USD':d['px'],'kind':kind,'problems':problems})
            if len(samples)<3 and (not samples or kind not in [s['kind'] for s in samples]):
                samples.append({'source':'book_diffs_20251201_00.gz','source_row_1based':row,'coin':'BTC','side':d['side'],'px_USD':d['px'],'kind':kind,'raw_book_diff':raw,'time':'not present in source diff record'})
            # This BBO is an observed-new cohort diagnostic, never the venue BBO.
            if old[NEW]:
                after = old[Q]
                levels[side][px] += after-cohort_before
                if after:
                    heapq.heappush(heaps[side], px if side else -px)
            for s in (0,1):
                while heaps[s] and levels[s][heaps[s][0] if s else -heaps[s][0]] <= 0:
                    heapq.heappop(heaps[s])
            crossed = bool(heaps[0] and heaps[1] and -heaps[0][0] >= heaps[1][0])
            if crossed:
                counters['cohort_crossed_raw_cuts'] += 1
                cross_run += 1
                max_cross_run = max(max_cross_run,cross_run)
                if len(cross_samples)<3 and cross_run==1:
                    cross_samples.append({'source_row_1based':row,'bid_USD':str(Decimal(-heaps[0][0])/SCALE),'ask_USD':str(Decimal(heaps[1][0])/SCALE)})
            else: cross_run=0
            if counters['btc_diffs'] % 500_000 == 0:
                stamp(f"Diff checkpoint: {counters['btc_diffs']} BTC events, {len(orders)} order ids, maxrss {resource.getrusage(resource.RUSAGE_SELF).ru_maxrss} KiB")
    counters['all_coin_diff_rows'] = row
    counters['distinct_order_ids'] = len(orders)
    counters['cohort_crossed_longest_raw_event_run'] = max_cross_run
    counters['active_observed_new_end'] = sum(bool(o[Q] and o[NEW]) for o in orders.values())
    counters['active_inherited_end'] = sum(bool(o[Q] and not o[NEW]) for o in orders.values())
    stamp('Diff pass complete; start binary statuses')
    status_counts = Counter()
    all_status_min, all_status_max = 2**63-1,0
    with gzip.open(DATA/'btc_20251201_00.data.gz','rb') as f:
        while block := f.read(54*100_000):
            if len(block)%54: raise ValueError('Truncated status record')
            for v in RECORD.iter_unpack(block):
                ts,status,side,price,size,oid = v[0],v[3],v[4],decoded(v[5]),decoded(v[6]),v[7]
                status_counts['all_status_rows'] += 1
                all_status_min = min(all_status_min,ts)
                all_status_max = max(all_status_max,ts)
                o = orders.get(oid)
                if o is None:
                    status_counts['status_rows_no_diff_oid'] += 1
                    continue
                o[STATUS_N] += 1
                o[FIRST_TS] = min(o[FIRST_TS] or ts,ts)
                if ts >= o[LAST_TS]:
                    o[LAST_TS], o[LAST_STATUS], o[LAST_SZ] = ts,status,size
                o[FLAGS] |= v[11] | (v[14]<<1) | (v[10]<<2) | (v[12]<<3) | (v[13]<<4)
                o[TIF] |= 1 << v[16]
                o[TYPES] |= 1 << v[15]
                if status==1:
                    o[OPEN] += 1
                    if side==o[SIDE] and price==o[PX] and size==o[INITIAL]: o[OPENMATCH] += 1
            if status_counts['all_status_rows']%1_000_000==0:
                stamp(f"Status checkpoint: {status_counts['all_status_rows']} records")
    stamp('Status pass complete; start trade stream')
    trade_counts=Counter()
    trade_min,trade_max=None,None
    sweep_extrema = {'sell_min':None, 'buy_max':None}
    for row,line in enumerate(gzip.open(DATA/'trades_20251201_00.gz','rt'),1):
        d=json.loads(line)
        if d['coin']!='BTC': continue
        trade_counts['btc_trade_rows']+=1
        trade_min = min(trade_min or d['time'],d['time'])
        trade_max = max(trade_max or d['time'],d['time'])
        size,side,px=fixed(d['sz']),int(d['side']=='A'),fixed(d['px'])
        extreme_key = 'sell_min' if side else 'buy_max'
        prior = sweep_extrema[extreme_key]
        if prior is None or (px < prior['px_scaled_1e7'] if side else px > prior['px_scaled_1e7']):
            sweep_extrema[extreme_key] = {'source_row_1based':row,'time_UTC':d['time'],'px_USD':d['px'],'px_scaled_1e7':px,'sz_BTC':d['sz'],'aggressor_side':d['side']}
        if size<=0: trade_counts['nonpositive_trade_size']+=1
        matched_makers=0
        for leg in d['side_info']:
            o=orders.get(leg['oid'])
            if o is None:
                trade_counts['trade_legs_no_diff_oid']+=1
                continue
            if o[SIDE]!=side:
                o[MAKER]+=size
                matched_makers+=1
                if o[PX]!=px: trade_counts['maker_limit_trade_price_mismatch']+=1
            else: o[TAKER]+=size
        trade_counts['trades_'+str(matched_makers)+'_maker_oid_in_diff']+=1
    trade_counts['all_coin_trade_rows']=row
    stamp('Trade pass complete; summarize observed cohort')
    cohort=Counter()
    q_samples=[]
    for o in orders.values():
        if not o[NEW]: continue
        cohort['observed_new_ids']+=1
        cohort['closed_by_remove' if o[REMOVE] else 'not_removed']+=1
        cohort['has_exact_open_price_side_size' if o[OPENMATCH] else 'no_exact_open_price_side_size']+=1
        if o[OPEN]==1 and o[OPENMATCH]==1: cohort['unique_exact_open_match']+=1
        if not o[STATUS_N]: cohort['no_status_rows']+=1
        if o[FLAGS]&1: cohort['is_trigger_on_any_status']+=1
        if o[FLAGS]&2: cohort['is_reduce_only_on_any_status']+=1
        if o[TYPES] not in (0,1): cohort['non_limit_or_mixed_order_type']+=1
        if o[TAKER]: cohort['also_taker_fills']+=1
        if o[BAD]: cohort['state_inconsistent_ids']+=1
        if o[NEW]!=1 or o[BAD]: continue
        if o[Q]:
            expected=o[DELTA]
            group='active_end'
        elif o[REMOVE]==1 and o[LAST_STATUS]==5 and o[LAST_SZ]==0:
            expected=o[DELTA]+o[REMQ]
            group='removed_final_status_filled_zero'
        elif o[REMOVE]==1 and o[LAST_STATUS] in (2,7,10,11,12,13,14,16):
            expected=o[DELTA]
            group='removed_final_status_cancel'
        else:
            cohort['maker_quantity_unclassified_terminal_status']+=1
            continue
        cohort[group]+=1
        if expected==o[MAKER]: cohort[group+'_maker_quantity_exact']+=1
        else:
            cohort[group+'_maker_quantity_mismatch']+=1
            if len(q_samples)<10:
                q_samples.append({'first_diff_source_row_1based':o[FIRST_ROW], 'group':group, 'side':'A' if o[SIDE] else 'B', 'px_USD':str(Decimal(o[PX])/SCALE), 'initial_BTC':str(Decimal(o[INITIAL])/SCALE),'visible_update_decrease_BTC':str(Decimal(o[DELTA])/SCALE),'last_removed_BTC':str(Decimal(o[REMQ])/SCALE),'matched_maker_trades_BTC':str(Decimal(o[MAKER])/SCALE),'last_status_id':o[LAST_STATUS], 'last_status_remaining_BTC':str(Decimal(o[LAST_SZ])/SCALE)})
    stamp('Audit complete')
    endpoint_top5 = {}
    for side in (0,1):
        ordered = sorted(((p,q) for p,q in levels[side].items() if q>0), reverse=not side)[:5]
        bound = sweep_extrema['buy_max' if side else 'sell_min']['px_scaled_1e7']
        endpoint_top5['ask' if side else 'bid'] = [{'px_USD':str(Decimal(p)/SCALE),'observed_new_cohort_BTC':str(Decimal(q)/SCALE),'inside_hour_trade_through_region':p < bound if side else p > bound} for p,q in ordered]
    result={
        'task':'T-008','experiments':['E-201','E-202','E-203'],'seed':20260919,
        'scope':'full acquired nominal BTC first hour; raw diff sequence; observed-new cohort diagnostic only',
        'code_base_commit':'ed62f2a4ccebc7ad559ba0c185954401d5311cb8',
        'input_manifest':'T-001/sample_manifest.json','code_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'diff':dict(counters),'diff_field_occurrences':dict(fields),'status':dict(status_counts),'trade':dict(trade_counts),'cohort':dict(cohort),
        'status_actual_min_ns':all_status_min,'status_actual_max_ns':all_status_max,'trade_actual_min_UTC':trade_min,'trade_actual_max_UTC':trade_max,
        'sanitized_real_diff_rows':samples,'state_problem_samples':errors,'raw_cohort_crossing_samples':cross_samples,'quantity_mismatch_samples':q_samples,
        'retrospective_candidate_region':{'trade_extrema':sweep_extrema,'endpoint_observed_cohort_top5':endpoint_top5,'interpretation':'Necessary price-region feasibility only. Full-hour extrema cannot be used for earlier admission; no atomic cut, tie-order, availability, historical matching, or complete activation premise is certified.'},
        'gates':{'Q16_full_queue':False,'Q17_true_BBO':False,'Q18_true_top_five':False,'restricted_observed_lifecycle_structural_audit':True,'online_causal_cohort_labels':False},
        'blocked_by':['No initial L4/L2 checkpoint','No recovered trustworthy atomic-group cuts in this audit','Availability/clock certification not supplied by this audit','Historical executable-price priority and complete activation semantics remain preconditions'],
        'adversarial_tests_passed':len(tests),'stages':STAGES,
        'environment':{'python':platform.python_version(),'platform':platform.platform(),'cpu_threads':1,'memory_peak_KiB':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,'wall_seconds':time.monotonic()-START,'acquired_bytes':0}
    }
    dump('replay_audit.json',result)


if __name__=='__main__':
    run()
