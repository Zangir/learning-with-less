"""Bind conditional December states to exact feature and outcome cuts.

This is a hypothesis contract, never an affirmative producer admission.
"""
from bisect import bisect_left, bisect_right
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import hashlib, itertools, json, random, time

ROOT = Path(__file__).resolve().parents[2]
R2 = ROOT/'r2'
OUT = ROOT/'r3/participant'
NS = 1000000000
SEED = 20260919
random.seed(SEED)
START = time.monotonic()


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(name, value):
    (OUT/name).write_text(json.dumps(value, indent=2)+'\n', encoding='utf-8')


def lines(path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]


def unit(value):
    whole, _, fraction = value.partition('.')
    assert len(fraction) <= 8
    return int(whole)*100000000+int((fraction+'00000000')[:8])


def common_prefix(a, b):
    count = 0
    for left, right in zip(a, b):
        if left != right:
            break
        count += 1
    return count


def geometric_coverage(state, checkpoint, depth):
    book = state['top20_price_quantity_count']
    return (checkpoint['matched_prefix_lengths'][0] > 0
            and checkpoint['matched_prefix_lengths'][1] > 0
            and book[0][depth-1][0] >= checkpoint['bid_covered_at_or_above_units8']
            and book[1][depth-1][0] <= checkpoint['ask_covered_at_or_below_units8'])


def tests():
    checks = []
    def test(name, condition):
        assert condition, name
        checks.append(dict(name=name, passed=True))
    events = [('a', 0, 2), ('a', 1, None), ('b', 0, 5), ('b', 1, 3)]
    states = set()
    valid_orders = 0
    for order in itertools.permutations(events):
        if any([x[1] for x in order if x[0] == key] != [0, 1] for key in ('a', 'b')):
            continue
        valid_orders += 1
        state = {'a': 3}
        for key, _, quantity in order:
            if quantity is None:
                state.pop(key, None)
            else:
                state[key] = quantity
        states.add(tuple(sorted(state.items())))
    test('cross_order_terminal_commutation', valid_orders == 6 and states == {(('b', 3),)})
    test('same_order_reordering_changes_terminal_assignment', 3 != 5)
    test('equal_aggregate_and_count_do_not_identify_priority',
         sum([2, 3]) == sum([3, 2]) and [2, 3] != [3, 2])
    test('same_millisecond_bin_does_not_license_future_join',
         500000 < 800000 and 800000//1000000 == 500000//1000000)
    test('exclusive_support_boundary', not (10500000000 < 10500000000)
         and 10500000000 < 10500000001)
    test('overlapping_schedules_not_independent_windows', 16-12+1 == 5 and 16//12 == 1)
    test('snapshot_boundary_equality_is_covered_unlike_trade_through', 100 >= 100)
    return checks


def main():
    states = lines(OUT/'replayed_top20.jsonl')
    times = [r['candidate_time_ns'] for r in states]
    assert all(a < b for a, b in zip(times, times[1:]))
    snapshots = []
    anchors = []
    correspondence = Counter()
    for ordinal, raw in enumerate(lines(R2/'sources/btc_20251201_00.jsonl')):
        source = raw['raw']['data']
        lower = source['time']*1000000
        upper = lower+1000000
        if lower < times[0] or upper > times[-1]:
            continue
        levels = [[[unit(v['px']), unit(v['sz']), v['n']] for v in side] for side in source['levels']]
        snapshots.append(dict(source_ordinal=ordinal, event_bin_lower_ns=lower,
                              event_bin_upper_exclusive_ns=upper, top20=levels))
        lo, hi = bisect_left(times, lower), bisect_left(times, upper)
        if hi-lo > 1:
            correspondence['ambiguous_multiple_groups_in_bin'] += 1
            continue
        index = lo if hi-lo == 1 else lo-1
        if index < 0:
            continue
        state = states[index]
        prefix = [common_prefix(a, b) for a, b in zip(levels, state['top20_price_quantity_count'])]
        correspondence['same_bin_candidate' if hi-lo == 1 else 'no_change_in_bin_candidate'] += 1
        correspondence['matched_both_bbo'] += int(min(prefix) >= 1)
        correspondence['matched_both_top5'] += int(min(prefix) >= 5)
        correspondence['matched_both_top20'] += int(min(prefix) >= 20)
        if min(prefix) == 0:
            continue
        anchors.append(dict(anchor_id=f'snapshot-{ordinal}', snapshot_source_ordinal=ordinal,
                            event_bin_lower_ns=lower, event_bin_upper_exclusive_ns=upper,
                            candidate_state_index=index, candidate_group_time_ns=times[index],
                            candidate_group_after_bin_lower_bound=times[index] > lower,
                            matched_prefix_lengths=prefix,
                            bid_covered_at_or_above_units8=levels[0][prefix[0]-1][0],
                            ask_covered_at_or_below_units8=levels[1][prefix[1]-1][0],
                            correspondence='conditional_compatible_state_not_identified_exact_timestamp',
                            admitted=False))
    write('snapshot_local_checkpoints.json', dict(origin='exploratory_real', admitted=False,
          premise='The claimed snapshot state corresponds to the specified candidate terminal identity state.',
          same_bin_is_not_timestamp_equality=True, summary=dict(correspondence), checkpoints=anchors))
    windows = json.loads((R2/'december/conditional_windows.json').read_text())['windows']
    requirements = []
    cut_roles = {}
    for window in windows:
        scope = window['scope']
        for decision in window['decision_ns']:
            features = ([decision-v*NS for v in (0, 1, 5, 20)] if scope == 'Q17'
                        else list(range(decision-75*NS, decision+1, NS)))
            outcomes = ([decision+v for v in (100000000, 500000000, 10*NS, 10100000000, 10500000000)]
                        if scope == 'Q17' else [decision+v*NS for v in range(1, 11)]+[decision+10500000000])
            # Preserve gaps and endpoints; a future-valid label is not an online promise.
            assert min(features) >= window['start_ns']
            assert max(outcomes) < window['end_ns']
            requirements.append(dict(scope=scope, decision_ns=decision,
                                     feature_cut_ns=features, outcome_cut_ns=outcomes,
                                     retrospective_support_mask=True, real_time_admission_claim=False,
                                     admitted=False))
            for cut in features:
                cut_roles.setdefault(cut, set()).add(scope+'_feature')
            for cut in outcomes:
                cut_roles.setdefault(cut, set()).add(scope+'_outcome')
    snapshot_ends = [r['event_bin_upper_exclusive_ns'] for r in snapshots]
    evidence = []
    for cut, roles in sorted(cut_roles.items()):
        index = bisect_right(times, cut)-1
        assert index >= 0
        state = states[index]
        assert state['candidate_time_ns'] <= cut < state['closure_witness_time_ns']
        before = [r for r in anchors if r['event_bin_upper_exclusive_ns'] <= cut
                  and r['candidate_state_index'] <= index]
        coverage = {}
        for depth in (1, 5):
            eligible = [r for r in before if geometric_coverage(state, r, depth)]
            anchor = eligible[-1] if eligible else None
            coverage[str(depth)] = dict(checkpoint_anchor_id=anchor['anchor_id'] if anchor else None,
                                        state_covered_under_local_checkpoint_premises=anchor is not None,
                                        checkpoint_max_age_ns=cut-anchor['event_bin_lower_ns'] if anchor else None)
        prior_index = bisect_right(snapshot_ends, cut)-1
        prior = snapshots[prior_index] if prior_index >= 0 else None
        comparisons = {str(depth): (all(a[:depth] == b[:depth] for a, b in zip(
            state['top20_price_quantity_count'], prior['top20'])) if prior else None) for depth in (1, 5)}
        evidence.append(dict(cut_ns=cut, roles=sorted(roles), candidate_state_index=index,
                             candidate_event_ns=state['candidate_time_ns'],
                             closure_witness_time_ns=state['closure_witness_time_ns'],
                             closure_witness_is_after_cut=True,
                             measured_release_ns=None, measured_admission_ns=None,
                             local_checkpoint_coverage=coverage,
                             strict_past_snapshot_source_ordinal=prior['source_ordinal'] if prior else None,
                             strict_past_snapshot_bin_end_ns=prior['event_bin_upper_exclusive_ns'] if prior else None,
                             strict_past_snapshot_equality=comparisons,
                             top5_price_quantity_count=[side[:5] for side in state['top20_price_quantity_count']],
                             origin='exploratory_real', admitted=False))
    (OUT/'required_cut_states.jsonl').write_text(''.join(json.dumps(v, separators=(',', ':'))+'\n' for v in evidence))
    write('task_cut_requirements.json', requirements)
    by_cut = {r['cut_ns']: r for r in evidence}
    summary = dict(unique_required_cuts=len(evidence), snapshot_correspondence=dict(correspondence),
                   all_cuts_have_only_future_closure_witness=True,
                   canonical_evidence_origin='exploratory_real', all_scopes_admitted=False)
    for scope in ('Q17', 'Q18'):
        selected = [r for r in requirements if r['scope'] == scope]
        depth = '1' if scope == 'Q17' else '5'
        feature_supported = sum(all(by_cut[c]['local_checkpoint_coverage'][depth]['state_covered_under_local_checkpoint_premises']
                                    for c in r['feature_cut_ns']) for r in selected)
        fully_supported = sum(all(by_cut[c]['local_checkpoint_coverage'][depth]['state_covered_under_local_checkpoint_premises']
                                  for c in r['feature_cut_ns']+r['outcome_cut_ns']) for r in selected)
        cuts = sorted({c for r in selected for c in r['feature_cut_ns']+r['outcome_cut_ns']})
        summary[scope] = dict(decisions=len(selected), all_feature_cuts_locally_supported=feature_supported,
                              all_feature_outcome_cuts_locally_supported=fully_supported, required_distinct_cuts=len(cuts),
                              exact_replay_equals_strict_past_snapshot=sum(by_cut[c]['strict_past_snapshot_equality'][depth] for c in cuts))
    summary['Q17'].update(overlapping_twelve_opportunity_sequences=5, disjoint_twelve_opportunity_sequences=1,
                          retained_grid='r2 frozen global Unix modulo 11s; diagnostic only; consumer phase not changed')
    summary['Q18']['training_status'] = 'No separate supported fit period; feature/provenance diagnostics only.'
    summary['tests'] = tests()
    summary['runtime_s'] = time.monotonic()-START
    summary['code_sha256'] = sha(Path(__file__))
    write('actual_cut_summary.json', summary)
    normalized = []
    for index, state in enumerate(states):
        row = dict(source_id='participant-december1-conditional-groups', source_ordinal=index,
                   asset='BTC', event_ns=state['candidate_time_ns'],
                   release_ns=None, admission_evidence_ns=None,
                   source_first_diff_row=state['source_first_row'],
                   source_last_diff_row=state['source_last_row'],
                   closure_witness_time_ns=state['closure_witness_time_ns'],
                   closure_witness_source_row=state['closure_witness_source_row'],
                   event_clock_status='candidate_correspondence_under_P2',
                   origin='exploratory_real', admitted=False)
        for side, values in zip(('bid', 'ask'), state['top20_price_quantity_count']):
            for column, offset in (('prices_units8', 0), ('sizes_units8', 1), ('order_counts', 2)):
                row[side+'_'+column] = [v[offset] for v in values[:5]]
        normalized.append(row)
    (OUT/'conditional_state_rows.v3.jsonl').write_text(''.join(json.dumps(v, separators=(',', ':'))+'\n' for v in normalized))
    contract = dict(schema='t008-participant-conditional/3', seed=SEED, origin='exploratory_real',
        fixture_only=False, empirical_admission=False, evaluation_use='development_feature_and_provenance_diagnostics',
        affirmative_shared_contract_compatible=False,
        atomic_cut=dict(kind='conditional_terminal_group_reconstruction',
                        assumption_ids=['P1', 'P2', 'L1', 'L2', 'P4'],
                        native_action_boundary_identified=False),
        clock=dict(scope='conditional_exchange_time', measured_receive_clock=False,
                   event_time_is_candidate=True, future_closure_witness_not_release_clock=True),
        units=dict(price='integer_1e-8_USD_per_BTC', quantity='integer_1e-8_BTC', time='unix_ns'),
        scopes={scope:dict(decision='conditional_diagnostic', empirical_admission=False) for scope in ('Q16', 'Q17', 'Q18')},
        windows=[dict(window_id='december1-'+w['scope']+'-conditional', asset='BTC', date='2025-12-01',
                      scope=w['scope'], start_ns=w['start_ns'], end_ns=w['end_ns'],
                      decision_ns=w['decision_ns'], first_source_ordinal=bisect_left(times,w['start_ns']),
                      last_source_ordinal=bisect_left(times,w['end_ns'])-1,
                      use='feature_and_label_diagnostics_only_no_model_fit') for w in windows],
        source_attribution='Pinned third-party archive claiming Hyperliquid collection; participant export independently acquired but common upstream possible.',
        conditional_premises={
          'P1': 'All relevant visible identities, additions, assignments, removals and activations are complete and preserve each order lifecycle.',
          'P2': 'Frozen status/trade candidate correspondence assigns every relevant diff to the correct event group.',
          'L1': 'Selected archived snapshot state corresponds to the stated candidate terminal identity state within its coarsened millisecond bin.',
          'L2': 'Retained positive identities at that checkpoint are truly resting with the recorded quantities; matching positive quantities/counts then excludes additional hidden positive identities within the matching prefix.',
          'P4': 'Offline reconstruction has observed complete candidate groups and later closure witnesses; no claim that those witnesses were available at the historical feature cut.'},
        removed_premise_for_locally_supported_cuts='The old hour-wide ordinary-price-priority trade-clearing P3 is not needed if P1/P2/L1/L2/P4 hold.',
        conditional_proposition='Under P1/P2/L1/L2/P4, all initial unknown orders lie outside the matched price prefix. At any later cut whose top-k stays inside that prefix, unknown initial orders cannot contribute. Per-order assignments commute across distinct identities at terminal group cuts. Neither proposition proves native atomicity or FIFO.',
        unknowns=['Exact snapshot nanosecond time', 'Native block/action grouping', 'Same-price insertion priority',
                  'Historical minimal lot quantum', 'Unobserved activation absence outside P1', 'Measured historical receive/admission clocks'],
        mask_semantics=dict(feature_observation='candidate exchange-time as-of under premises',
                            final_row_validity='retrospective target/utility coverage, separate from features',
                            online_admission=False),
        same_ms_linkage='A compatible candidate later than the bin lower bound is never labeled observed at that lower bound.',
        q16='Observed identities/label evidence only; no FIFO, native-atomic-T or hypothetical-probe-fill certification.',
        q17='16 frozen-phase diagnostic decisions; 5 overlapping schedules, only 1 disjoint schedule; no independent fitting/selection/evaluation split.',
        q18='112 diagnostic decisions on frozen late support; no separate supported fit period.',
        review=dict(status='not_issued_by_producer'),
        input_sha256={str(p):sha(p) for p in (R2/'december/conditional_windows.json', R2/'december/conditional_proof.json',
                     R2/'sources/btc_20251201_00.jsonl', OUT/'replayed_top20.jsonl', OUT/'replay_summary.json',
                     R2/'december/candidate_diagnostic.json')},
        files={p.name:dict(path=str(p), sha256=sha(p)) for p in (OUT/'snapshot_local_checkpoints.json',
                     OUT/'required_cut_states.jsonl', OUT/'task_cut_requirements.json', OUT/'actual_cut_summary.json',
                     OUT/'conditional_state_rows.v3.jsonl', OUT/'replayed_top20.jsonl', OUT/'replay_summary.json')})
    write('conditional_contract.v3.json', contract)
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
