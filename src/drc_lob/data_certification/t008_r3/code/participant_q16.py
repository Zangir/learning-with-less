"""Audit observable activation and necessary FIFO consistency without certifying priority."""
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
import gzip, hashlib, json, os, random, resource, struct, time

ROOT = Path(__file__).resolve().parents[3]
OLD = ROOT/'T-008/r2/december'
OUT = ROOT/'T-008/r3/participant'
SEED = 20260919
random.seed(SEED)
os.sched_setaffinity(0, {min(os.sched_getaffinity(0))})
resource.setrlimit(resource.RLIMIT_AS, (4*1024**3, 4*1024**3))
RECORD = struct.Struct('<QI?B?IIQIi?????BBII')
START = time.monotonic()


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024**2), b''):
            h.update(chunk)
    return h.hexdigest()


def dump(name, value):
    (OUT/name).write_text(json.dumps(value, indent=2)+'\n')


def decode(value):
    return (value & 0x1fffffff)*10**(8-(value >> 29))


def token(value):
    return hashlib.sha256(('T008-local-order-'+str(value)).encode()).hexdigest()[:20]


def main():
    events = list(map(json.loads, (OLD/'identity_candidate_events.v2.jsonl').read_text().splitlines()))
    initial = json.loads((OLD/'identity_candidate_initial.v2.json').read_text())
    manifest = json.loads((OLD/'identity_candidate_manifest.v2.json').read_text())
    births = {e['local_order_token']: e for e in events if e['kind'] == 'new'}
    assert len(births) == 13283
    candidates = defaultdict(list)
    status_path = ROOT/'T-001/data/btc_20251201_00.data.gz'
    status_count = 0
    with gzip.open(status_path, 'rb') as stream:
        for chunk in iter(lambda: stream.read(RECORD.size*32768), b''):
            assert len(chunk) % RECORD.size == 0
            for row in RECORD.iter_unpack(chunk):
                ordinal = status_count
                status_count += 1
                if not manifest['start_ns'] <= row[0] < manifest['end_ns']:
                    continue
                key = token(row[7])
                if key not in births:
                    continue
                event = births[key]
                side = 'A' if row[4] else 'B'
                if (row[0] != event['candidate_group_time_ns'] or side != event['side']
                    or decode(row[5]) != event['price_units_1e8_usd']
                    or decode(row[6]) != event['quantity_after_units_1e8_btc']):
                    continue
                insert = ((row[3] == 1 and not row[11] and row[16] != 2)
                          or (row[11] and row[3] == 9))
                candidates[key].append(dict(status_source_row=ordinal, event_time_ns=row[0],
                    status_id=row[3], is_trigger=row[11], triggered=row[10], reduce_only=row[14],
                    order_type_id=row[15], tif_id=row[16],
                    historical_illustrative_insertion_predicate=insert))
    activation = []
    totals = Counter()
    for key, event in births.items():
        rows = candidates[key]
        good = [r for r in rows if r['historical_illustrative_insertion_predicate']]
        totals['new_orders'] += 1
        totals['with_matching_status'] += bool(rows)
        totals['with_matching_illustrative_insertion'] += bool(good)
        totals['with_unique_matching_illustrative_insertion'] += len(good) == 1
        totals['trigger_activation_candidates'] += any(r['is_trigger'] for r in good)
        activation.append(dict(source_diff_row=event['source_diff_row_0based'],
            local_order_token=key, matching_status_candidates=rows, fifo_priority_certified=False,
            interpretation='Visible-new/status correspondence; illustrative predicate is not core-engine authentication.'))
    dump('activation_correspondence.json', dict(summary=dict(totals), evidence=activation,
         raw_status_sha256=sha(status_path), historical_priority_identified=False))
    by_level = defaultdict(list)
    initial_by_level = defaultdict(list)
    for order in initial['orders']:
        initial_by_level[(order['side'], order['price_units_1e8_usd'])].append(order)
    for event in events:
        by_level[(event['side'], event['price_units_1e8_usd'])].append(event)
    group_audit = []
    audit = Counter()
    for level, sequence in by_level.items():
        resting = {r['local_order_token']: r['quantity_units_1e8_btc'] for r in initial_by_level[level]}
        birth_row = {r['local_order_token']: r['observed_new_source_row_0based'] for r in initial_by_level[level]}
        economic = [r for r in sequence if r['observed_label'] != 'zero_quantity_identity_cleanup']
        seen_keys = Counter()
        index = 0
        while index < len(economic):
            event = economic[index]
            key = event['local_order_token']
            if event['observed_label'] != 'matched_trade_decrease':
                before = event['quantity_before_units_1e8_btc']
                if before is not None:
                    assert resting.get(key, 0) == before
                after = event['quantity_after_units_1e8_btc']
                if event['kind'] == 'new':
                    assert key not in resting
                    birth_row[key] = event['source_new_row_0based']
                if after:
                    resting[key] = after
                else:
                    resting.pop(key, None)
                index += 1
                continue
            group_key = event['candidate_taker_price_group_key']
            group = []
            while index < len(economic) and economic[index].get('candidate_taker_price_group_key') == group_key:
                group.append(economic[index])
                index += 1
            seen_keys[group_key] += 1
            amount = sum(e['quantity_before_units_1e8_btc']-e['quantity_after_units_1e8_btc'] for e in group)
            remaining = amount
            expected = {}
            for oid in sorted(resting, key=lambda oid: birth_row[oid]):
                quantity = min(resting[oid], remaining)
                if quantity:
                    expected[oid] = quantity
                    remaining -= quantity
                if remaining == 0:
                    break
            actual = Counter()
            for e in group:
                oid = e['local_order_token']
                assert resting.get(oid, 0) == e['quantity_before_units_1e8_btc']
                actual[oid] += e['quantity_before_units_1e8_btc']-e['quantity_after_units_1e8_btc']
                if e['quantity_after_units_1e8_btc']:
                    resting[oid] = e['quantity_after_units_1e8_btc']
                else:
                    resting.pop(oid, None)
            consistent = remaining == 0 and expected == dict(actual)
            audit['candidate_contiguous_trade_groups'] += 1
            audit['maker_fragments'] += len(group)
            audit['fifo_necessary_condition_pass'] += consistent
            audit['fifo_necessary_condition_fail'] += not consistent
            group_audit.append(dict(candidate_group_key=group_key,
                source_rows=[r['source_diff_row_0based'] for r in group],
                raw_trade_rows=[r['matching_trade_source_row_0based'] for r in group],
                expected_fifo_maker_decrements=expected, observed_maker_decrements=dict(actual),
                source_birth_order_fifo_consistent=consistent, native_atomic_group_certified=False,
                priority_inference='Necessary consistency only; cannot identify priority for unexecuted queues.'))
        audit['repeated_noncontiguous_group_keys'] += sum(v > 1 for v in seen_keys.values())
    dump('priority_necessary_condition_audit.json', dict(summary=dict(audit), groups=group_audit,
         interpretation='Observed candidate grouped executions can falsify the birth-order FIFO hypothesis; passing does not prove historical FIFO or hypothetical probe fills.'))
    selected = json.loads((ROOT/'T-009/r2/conditional_selection_frozen.json').read_text())['selected']
    selected_rows = {r['source_seq'] for r in selected}
    assert len(selected_rows) == 1000
    observed = []
    for birth in events:
        if birth['source_diff_row_0based'] not in selected_rows:
            continue
        oid = birth['local_order_token']
        changes = [e for e in events if e['local_order_token'] == oid and e['source_diff_row_0based'] > birth['source_diff_row_0based']]
        item = dict(source_birth_row=birth['source_diff_row_0based'], local_order_token=oid,
                    initial_probe_quantity_units8=birth['quantity_after_units_1e8_btc'], horizons={})
        for seconds in (1, 5, 10):
            cutoff = birth['candidate_group_time_ns']+seconds*1000000000
            rows = [e for e in changes if e['candidate_group_time_ns'] <= cutoff]
            trades = [e for e in rows if e['observed_label'] == 'matched_trade_decrease']
            cancels = [e for e in rows if e['observed_label'] == 'observed_cancel']
            item['horizons'][str(seconds)] = dict(end_ns=cutoff, source_support_complete_under_candidate_clock=cutoff < manifest['end_ns'],
                observed_fill_units8=sum(e['quantity_before_units_1e8_btc']-e['quantity_after_units_1e8_btc'] for e in trades),
                observed_cancel_units8=sum(e['quantity_before_units_1e8_btc']-e['quantity_after_units_1e8_btc'] for e in cancels),
                exact_bound_trade_source_rows=[e['matching_trade_source_row_0based'] for e in trades],
                cancelled_probe_allowed=True, counterfactual=False)
        observed.append(item)
    dump('observed_probe_labels.json', dict(cohort='Same frozen count-independent first-1000 positive-new source-prefix cohort as T009 r2.',
         original_eight_atomic_event_horizon=False,
         purpose='Auxiliary observed factual-label inventory at fixed candidate exchange-time horizons; not replacement original Q16.',
         grouping_requirement='No native atomic grouping required for arithmetic sum of exact maker-row executions through a candidate time cut.',
         fifo_requirement='None for factual observed fills; FIFO remains necessary for claimed original model semantics.',
         probes=observed))
    label_stats = {}
    for seconds in ('1', '5', '10'):
        rows = [r['horizons'][seconds] for r in observed]
        label_stats[seconds] = dict(probes=len(rows), complete=sum(r['source_support_complete_under_candidate_clock'] for r in rows),
            positive_observed_fill_probes=sum(r['observed_fill_units8'] > 0 for r in rows))
    summary = dict(seed=SEED, activation=dict(totals), priority_necessary_consistency=dict(audit),
        factual_fixed_time_probe_labels=label_stats, empirical_admission=False,
        actual_factual_executions_are_not_counterfactual_truth=True,
        runtime_s=time.monotonic()-START, peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        code_sha256=sha(Path(__file__)),
        source_hashes={str(p):sha(p) for p in (OLD/'identity_candidate_events.v2.jsonl', OLD/'identity_candidate_initial.v2.json',
           OLD/'identity_candidate_manifest.v2.json', ROOT/'T-009/r2/conditional_selection_frozen.json', status_path)})
    dump('q16_observable_summary.json', summary)
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == '__main__':
    main()
