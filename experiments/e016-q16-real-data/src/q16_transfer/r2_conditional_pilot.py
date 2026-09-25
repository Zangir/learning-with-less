"""Conditional real-data model check; no empirical admission or FIFO certification.

The cohort is frozen from positive additions before future paths are constructed.
Every selected anchor gets a disposition, including failed model assumptions.
"""
from bisect import bisect_right
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime, timezone
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import resource
import time

from r2_adapter import evaluate_episode
from r2_selector import audit_selection, freeze_anchors

ROOT = (Path(__file__).resolve().parents[2] / 'runtime')
INPUT = ROOT / 'inputs/december-v2'
QUANTUM = '0.00000001'
SPEC = 'first-1000-positive-new-in-frozen-20s-regional-source-order/1'
LABELS = {'visible_new_order': 'A', 'observed_cancel': 'C',
          'matched_trade_decrease': 'T', 'zero_quantity_identity_cleanup': 'administrative'}


def save(name, data):
    (ROOT / name).write_text(json.dumps(data, indent=2) + '\n')


def decimal8(value):
    if type(value) is not int or value < 0:
        raise ValueError('Nonnegative integer source quantity required')
    return f'{value // 100000000}.{value % 100000000:08d}'


def level(row):
    return row['side'], row['price_units_1e8_usd']


def candidate(row):
    seq = row['source_diff_row_0based']
    return {'candidate_id': f'december-regional-{seq}', 'source_seq': seq,
            'decision': seq, 'available': seq, 'cohort_eligible': True,
            'eligibility_reasons': [], 'past_certificates': [
                {'ref': 'conditional-regional-initial-state-and-observed-birth-prefix', 'available': seq}]}


def normalize(rows, kind):
    diffs, fills, refs = [], [], []
    for row in rows:
        before, after = row['quantity_before_units_1e8_btc'], row['quantity_after_units_1e8_btc']
        change = ('remove' if row['kind'] == 'remove' else
                  {'new': {'sz': decimal8(after)}} if row['kind'] == 'new' else
                  {'update': {'origSz': decimal8(before), 'newSz': decimal8(after)}})
        diffs.append({'raw_seq': row['source_diff_row_0based'], 'coin': 'BTC',
                      'side': row['side'], 'px': decimal8(row['price_units_1e8_usd']),
                      'oid': row['local_order_token'], 'raw_book_diff': change})
        refs.append(f"identity_candidate_events.v2.jsonl:source-row-{row['source_diff_row_0based']}")
        if row['observed_label'] == 'matched_trade_decrease':
            fills.append({'oid': row['local_order_token'], 'sz': decimal8(before - after)})
            refs.append(f"raw-trades:row-{row['matching_trade_source_row_0based']}")
    stamp = rows[-1]['candidate_group_time_ns']
    return {'kind': kind, 'event_ns': stamp, 'available_ns': stamp,
            'diffs': diffs, 'fills': fills, 'evidence_refs': refs,
            'candidate_atomic_key': rows[0].get('candidate_taker_price_group_key'),
            'atomicity_certified': False}


def group_level(rows):
    """Group only contiguous equal trade keys, allowing intervening zero cleanup.

    A repeated key separated by another economic event remains unresolved. The
    key is a hypothesis about an action, never proof of an authenticated action.
    """
    result, keys = [], Counter()
    index = 0
    while index < len(rows):
        row = rows[index]
        kind = LABELS[row['observed_label']]
        end = index + 1
        if kind == 'T':
            key = row.get('candidate_taker_price_group_key')
            if not key:
                raise ValueError('Trade fragment lacks its candidate action key')
            while end < len(rows):
                following = end
                while following < len(rows) and LABELS[rows[following]['observed_label']] == 'administrative':
                    following += 1
                if (following < len(rows) and LABELS[rows[following]['observed_label']] == 'T'
                        and rows[following].get('candidate_taker_price_group_key') == key):
                    end = following + 1
                else:
                    break
            keys[key] += 1
        result.append(normalize(rows[index:end], kind))
        index = end
    repeated = {key for key, count in keys.items() if count > 1}
    for event in result:
        event['candidate_group_noncontiguous'] = event['candidate_atomic_key'] in repeated
    return result


def freeze_protocol():
    protocol = {
        'origin': 'exploratory_real', 'admitted': False, 'frozen_utc': datetime.now(timezone.utc).isoformat(),
        'selection': SPEC, 'maximum_anchors': 1000, 'horizon': 'eight subsequent economic events at the same price',
        'probe_policy': 'actual newly visible positive order, cancellable; no survivor selection',
        'observer_arms': 'same A/C/T kinds and exact quantities; count arm additionally sees initial and post-event positive counts',
        'primary_target': 'exact attainable minimum and maximum fill fractions; their hull width, not claimed continuous support',
        'secondary_targets': ['any-fill ambiguity', 'full-fill ambiguity'],
        'quantity_quantum': QUANTUM,
        'lattice_status': 'exact representational integer grid for observed sizes; conservative relative to legal sizes only if those sizes lie on this grid, which is not certified',
        'initial_state': 'conditional regional positive identities from T008, ordered by observed birth source ordinal as a hypothesis',
        'grouping': 'contiguous same candidate taker+exchange-group-ns+price keys in each level stream; zero cleanup may intervene',
        'repeated_noncontiguous_trade_key': 'unresolved; never split into independently asserted atomic trades',
        'clock': 'offline exchange-time coordinate; available_ns equals event_ns by explicit modeling convention, not receipt evidence',
        'singleton_selection': 'not used; count-conditioned selection would leak count information to the volume arm',
        'conditional_premises': ['regional initial identity completeness and source correspondence',
                                 'birth source order equals FIFO priority and additions append',
                                 'candidate trade grouping equals an atomic action at the level',
                                 'observed labels correctly reconcile executions and cancellations'],
        'limits': {'solver_call_timeout_ms': 2000, 'scoring_wall_seconds': 1200, 'cpu_threads': 1, 'memory_gib': 8},
        'failure_policy': 'retain every selected anchor; no replacement, no success-only population claim; FIFO failures reject the joint state/grouping/priority model',
        'empirical_admission': 'none; results are conditional model diagnostics pending relevant-level evidence and independent review',
    }
    save('conditional_protocol.json', protocol)
    return protocol


def run():
    started = time.monotonic()
    protocol = freeze_protocol()
    handoff = json.loads((INPUT / 'q16_handoff.v2.json').read_text())
    for name, descriptor in handoff['files'].items():
        if hashlib.sha256((INPUT / name).read_bytes()).hexdigest() != descriptor['sha256']:
            raise ValueError(f'Frozen producer digest mismatch: {name}')
    rows = [json.loads(line) for line in (INPUT / 'identity_candidate_events.v2.jsonl').read_text().splitlines()]
    initial = json.loads((INPUT / 'identity_candidate_initial.v2.json').read_text())
    if any(a['source_diff_row_0based'] >= b['source_diff_row_0based'] for a, b in zip(rows, rows[1:])):
        raise ValueError('Producer source sequence is not strictly increasing')
    candidates = [candidate(row) for row in rows if row['kind'] == 'new' and row['quantity_after_units_1e8_btc'] > 0]
    frozen = freeze_anchors(candidates, specification=SPEC)
    save('conditional_selection_frozen.json', frozen)
    audit_selection([candidate(row) for row in rows if row['kind'] == 'new'
                     and row['quantity_after_units_1e8_btc'] > 0], frozen, specification=SPEC)
    selected = {item['source_seq']: item['candidate_id'] for item in frozen['selected']}
    print(json.dumps({'stage': 'cohort_frozen_before_future_construction', 'selected': len(selected),
                      'all_candidates': len(candidates), 'last_selected_source_seq': max(selected)}), flush=True)

    states, by_level, anchors, replay_errors = defaultdict(dict), defaultdict(list), [], []
    for row in initial['orders']:
        states[level(row)][row['local_order_token']] = {
            'quantity': row['quantity_units_1e8_btc'], 'birth': row['observed_new_source_row_0based']}
    tainted = defaultdict(list)
    for row in rows:
        key, oid, seq = level(row), row['local_order_token'], row['source_diff_row_0based']
        state = states[key]
        before, after = row['quantity_before_units_1e8_btc'], row['quantity_after_units_1e8_btc']
        error = None
        if row['kind'] == 'new':
            if oid in state:
                error = 'duplicate new identity'
            state[oid] = {'quantity': after, 'birth': row['source_new_row_0based']}
        else:
            if oid not in state:
                if before != 0:
                    error = 'unknown positive identity'
                # Initial files intentionally contain only positive identities.
            elif state[oid]['quantity'] != before:
                error = 'source old quantity differs from replay'
            if row['kind'] == 'remove':
                state.pop(oid, None)
            elif oid in state:
                state[oid]['quantity'] = after
            else:
                error = error or 'unknown update identity'
        if error:
            issue = {'source_seq': seq, 'reason': error}
            replay_errors.append(issue)
            tainted[key].append(issue)
        by_level[key].append(row)
        if seq in selected:
            ordered = sorted(state.items(), key=lambda item: item[1]['birth'])
            anchors.append({'episode_id': selected[seq], 'coin': 'BTC', 'side': key[0],
                'px': decimal8(key[1]), 'probe_id': oid, 'probe_cancellable': True,
                'initial': [{'oid': token, 'sz': decimal8(value['quantity'])} for token, value in ordered],
                'start_ns': row['candidate_group_time_ns'], 'initial_available_ns': row['candidate_group_time_ns'],
                'initial_raw_seq': seq, 'horizon_complete': True,
                'initial_birth_ordinals': [value['birth'] for _, value in ordered],
                'past_replay_errors': deepcopy(tainted[key]), 'level_key': key})
    grouped = {key: group_level(stream) for key, stream in by_level.items()}
    last_group_time = max(row['candidate_group_time_ns'] for row in rows)
    for stream in grouped.values():
        for event in stream:
            event['candidate_group_right_boundary_closed'] = (event['kind'] != 'T'
                                                              or event['event_ns'] < last_group_time)
    grouped_starts = {key: [event['diffs'][0]['raw_seq'] for event in stream] for key, stream in grouped.items()}
    for episode in anchors:
        key = tuple(episode.pop('level_key'))
        position = bisect_right(grouped_starts[key], episode['initial_raw_seq'])
        events, economic = [], 0
        for event in grouped[key][position:]:
            events.append(event)
            economic += event['kind'] != 'administrative'
            if economic == 8:
                break
        episode['events'] = events
        episode['horizon_complete'] = economic == 8
    save('conditional_episodes.json', {'origin': 'exploratory_real', 'admitted': False, 'episodes': anchors})
    save('conditional_replay_audit.json', {'source_events': len(rows), 'replay_errors': replay_errors,
        'grouped_events': sum(map(len, grouped.values())), 'independent_source_audit_required': True})

    score_start, results = time.monotonic(), []
    with (ROOT / 'conditional_results.jsonl').open('w') as output:
        for episode in anchors:
            begin = time.monotonic()
            base = {'episode_id': episode['episode_id'], 'source_seq': episode['initial_raw_seq'],
                    'origin': 'exploratory_real', 'admitted': False}
            try:
                if time.monotonic() - score_start > protocol['limits']['scoring_wall_seconds']:
                    result = {'status': 'unresolved', 'reason': 'Predeclared global wall budget exhausted'}
                elif episode['past_replay_errors']:
                    result = {'status': 'unresolved', 'reason': 'Past positive replay inconsistency'}
                elif any(e['candidate_group_noncontiguous'] for e in episode['events']):
                    result = {'status': 'unresolved', 'reason': 'Noncontiguous candidate atomic trade key'}
                elif any(not e['candidate_group_right_boundary_closed'] for e in episode['events']):
                    result = {'status': 'censored', 'reason': 'Candidate trade group touches the unclosed right boundary'}
                else:
                    result = evaluate_episode(episode, QUANTUM, 'exploratory_real', timeout_ms=2000)
            except ValueError as exc:
                result = {'status': 'model_invariant_failure', 'reason': str(exc)}
            result = {**base, **result, 'elapsed_seconds': time.monotonic() - begin}
            output.write(json.dumps(result) + '\n')
            output.flush()
            results.append(result)
            if len(results) % 50 == 0:
                print(json.dumps({'anchors': len(results), 'seconds': time.monotonic() - score_start,
                                  'dispositions': dict(Counter(r['status'] for r in results))}), flush=True)
    scored = [r for r in results if r['status'] == 'scored']
    widths = {arm: [Fraction(r['projections'][arm]['maximum_fill_units'] - r['projections'][arm]['minimum_fill_units'],
                            r['probe_units']) for r in scored] for arm in ('volume', 'count')}
    summary = {'origin': 'exploratory_real', 'admitted': False, 'eligible_empirical_episodes': 0,
        'selected': len(anchors), 'all_positive_new_candidates': len(candidates),
        'dispositions': dict(Counter(r['status'] for r in results)),
        'failure_reasons': dict(Counter(r.get('reason', 'solver projection unresolved') for r in results if r['status'] != 'scored')),
        'joint_fifo_model_incompatible_in_cohort': any('FIFO' in r.get('reason', '') for r in results),
        'conditional_scored_subset': {'size': len(scored), 'population_estimand': False,
            'mean_fill_hull_width': {a: str(sum(v) / len(v)) if v else None for a, v in widths.items()},
            'strict_fill_hull_reductions': sum(c < v for c, v in zip(widths['count'], widths['volume'])),
            'fraction_ambiguous': {a: sum(w > 0 for w in v) for a, v in widths.items()},
            'any_fill_ambiguous': {a: sum(len(r['projections'][a]['any_fill']) > 1 for r in scored) for a in widths},
            'full_fill_ambiguous': {a: sum(len(r['projections'][a]['full_fill']) > 1 for r in scored) for a in widths},
            'observed_probe_any_fill': sum(r['truth']['filled_units'] > 0 for r in scored),
            'observed_probe_cancellation': sum(r['truth']['cancelled_units'] > 0 for r in scored)},
        'elapsed_seconds': time.monotonic() - started,
        'scoring_seconds': time.monotonic() - score_start,
        'peak_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}
    save('conditional_summary.json', summary)
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == '__main__':
    run()
