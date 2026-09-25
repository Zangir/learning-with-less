"""Frozen finite observer/probe ablation; retained controls are development data."""
from collections import Counter, defaultdict
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import resource
import time

from core import State, StateCapExceeded, initial_states, transition

ROOT = (Path(__file__).resolve().parents[2] / 'runtime')
OUT = ROOT / 'r4-controlled'
PROTOCOL_SHA = '6676e90eeec4e10c529edbbb04dc2853a612e1a697418d9f26bcfb155f612712'
CAP = 100000


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def observed_step(states, event, view, cancellable, count=None, cap=CAP):
    kind, quantity = event
    kinds = (kind,) if view == 'rich' or kind == 'A' else ('C', 'T')
    result = set()
    for state in states:
        for candidate in kinds:
            for after in transition(state, candidate, quantity, cancellable):
                if count is None or len(after.queue) == count:
                    result.add(after)
                    if len(result) > cap:
                        raise StateCapExceeded('Entire prefix unscored: observer state cap')
    return result


def metrics(states, probe):
    if not states:
        raise ValueError('Empty hypothesis set for a prescribed feasible control')
    values = sorted({state.filled for state in states})
    return {'fill_values': values, 'fill_fractions': [str(Fraction(v, probe)) for v in values],
            'hull_width': str(Fraction(values[-1] - values[0], probe)),
            'any_fill': sorted({int(v > 0) for v in values}),
            'full_fill': sorted({int(v == probe) for v in values}),
            'states': len(states)}


def fixture_truth(fixture):
    state = State(tuple((q, False) for q in fixture['ahead']) + ((fixture['probe'], True),))
    truth = [state]
    for i, (kind, quantity) in enumerate(fixture['events']):
        choices = transition(state, kind, quantity, True)
        if kind == 'C':
            pos = fixture['cancel_target_positions'][str(i)]
            amount, tagged = state.queue[pos]
            remainder = ((amount - quantity, tagged),) if amount > quantity else ()
            state = State(state.queue[:pos] + remainder + state.queue[pos + 1:], state.filled,
                          state.cancelled + (quantity if tagged else 0))
            if state not in choices:
                raise ValueError('Invalid prespecified fixture cancellation')
        else:
            state, = choices
        truth.append(state)
    if [len(s.queue) for s in truth] != fixture['counts']:
        raise ValueError('Fixture counts differ from its prescribed truth')
    return truth


def evaluate_case(case, deadline):
    rows, retained = [], {}
    for policy in ('protected', 'cancellation_permitted'):
        for view in ('rich', 'signed_delta'):
            volume = initial_states(case['ahead'], case['probe'], CAP)
            count = {s for s in volume if len(s.queue) == case['counts'][0]}
            failure = None
            for index, event in enumerate(case['events']):
                row = {'case_id': case['case_id'], 'family': case['family'], 'prefix': index + 1,
                       'view': view, 'probe_policy': policy, 'probe_units': case['probe'],
                       'ahead_units': case['ahead'], 'source_ref': case['source_ref'],
                       'protocol_sha256': PROTOCOL_SHA, 'origin': 'synthetic_diagnostic',
                       'admitted': False}
                if not failure:
                    try:
                        if time.monotonic() > deadline:
                            raise TimeoutError('Frozen total diagnostic budget exhausted')
                        volume = observed_step(volume, event, view, policy != 'protected')
                        count = observed_step(count, event, view, policy != 'protected', case['counts'][index + 1])
                        if not count or not count <= volume:
                            raise AssertionError('Nonempty count hypothesis nesting failed')
                        if 'truth' in case and case['truth'][index + 1] not in count:
                            raise AssertionError('Explicit fixture truth excluded')
                        if case['family'] == 'source' and index == 7:
                            assert case['terminal_truth'] in {s.filled for s in count}
                        if case['family'] == 'source' and policy == 'protected' and view == 'rich':
                            expected = case['source_events'][index]
                            assert sorted({s.filled for s in volume}) == expected['volume_only_fill_set']
                            assert sorted({s.filled for s in count}) == expected['count_fill_set']
                        for arm, states in (('volume', volume), ('count', count)):
                            if view == 'signed_delta' and (policy, 'rich', index, arm) in retained:
                                assert retained[(policy, 'rich', index, arm)] <= states
                            if policy == 'cancellation_permitted' and ('protected', view, index, arm) in retained:
                                assert retained[('protected', view, index, arm)] <= states
                            retained[(policy, view, index, arm)] = states
                        if view == 'signed_delta':
                            removed = sum(q for k, q in case['events'][:index + 1] if k != 'A')
                            assert max(s.filled for s in volume) == min(case['probe'], max(0, removed - case['ahead']))
                        wide, narrow = metrics(volume, case['probe']), metrics(count, case['probe'])
                        row.update(status='exact', volume=wide, count=narrow,
                                   strict_set_reduction=set(narrow['fill_values']) < set(wide['fill_values']),
                                   strict_hull_tightening=Fraction(narrow['hull_width']) < Fraction(wide['hull_width']))
                    except (StateCapExceeded, TimeoutError) as error:
                        failure = str(error)
                if failure:
                    row.update(status='unscored', reason=failure)
                rows.append(row)
    return rows


def main():
    started = time.monotonic()
    if sha(OUT / 'protocol.json') != PROTOCOL_SHA:
        raise ValueError('Frozen protocol bytes changed')
    protocol = json.loads((OUT / 'protocol.json').read_text())
    bindings = []
    for entry in protocol['input_files']:
        path = (Path(__file__).resolve().parents[2] / 'runtime' / Path(entry['path']).name)
        actual = sha(path)
        if actual != entry['sha256']:
            raise ValueError(f'Frozen input changed: {path}')
        bindings.append({**entry, 'verified': True})
    source = json.loads((ROOT / 'original_baseline/logs/count_probe.json').read_text())
    records = source['records'][:64]
    assert [r['trial'] for r in records] == list(range(64)) and source['seed'] == 16029001
    cases = []
    for record in records:
        queue = record['initial'][0]
        cases.append({'case_id': f"source-{record['trial']}", 'family': 'source',
                      'ahead': sum(q for q, tag in queue if not tag), 'probe': 1,
                      'events': [e['event'] for e in record['events']],
                      'counts': [len(queue)] + [e['observed_count'] for e in record['events']],
                      'source_events': record['events'],
                      'terminal_truth': int(record['true_filled']),
                      'source_ref': {'file': str(ROOT / 'original_baseline/logs/count_probe.json'),
                                     'sha256': bindings[0]['sha256'], 'trial': record['trial']}})
    for fixture in protocol['fixtures']:
        cases.append({'case_id': fixture['id'], 'family': 'fixture', 'ahead': sum(fixture['ahead']),
                      'probe': fixture['probe'], 'events': fixture['events'], 'counts': fixture['counts'],
                      'truth': fixture_truth(fixture),
                      'source_ref': {'file': 'protocol.json', 'sha256': PROTOCOL_SHA, 'fixture_id': fixture['id']}})
    rows = []
    with (OUT / 'controlled_rows.jsonl').open('w') as stream:
        for case in cases:
            result = evaluate_case(case, started + 600)
            rows.extend(result)
            for row in result:
                stream.write(json.dumps(row) + '\n')
            stream.flush()
            print(json.dumps({'case': case['case_id'], 'rows': len(rows),
                              'seconds': time.monotonic() - started}), flush=True)
    assert len(rows) == protocol['expected_rows']
    grouped = defaultdict(list)
    for row in rows:
        grouped[(row['family'], row['view'], row['probe_policy'], row['prefix'])].append(row)
    summaries = []
    for key, batch in sorted(grouped.items()):
        exact = [r for r in batch if r['status'] == 'exact']
        summaries.append({'family': key[0], 'view': key[1], 'probe_policy': key[2], 'prefix': key[3],
                          'selected': len(batch), 'exact': len(exact),
                          'strict_set_reductions': sum(r['strict_set_reduction'] for r in exact),
                          'strict_hull_tightenings': sum(r['strict_hull_tightening'] for r in exact),
                          'mean_widths': {arm: str(sum((Fraction(r[arm]['hull_width']) for r in exact), Fraction()) / len(exact))
                                         if exact else None for arm in ('volume', 'count')}})
    summary = {'protocol_sha256': PROTOCOL_SHA, 'origin': 'synthetic_diagnostic', 'admitted': False,
               'source_seed': source['seed'], 'source_histories': 64, 'fixtures': 3, 'rows': len(rows),
               'dispositions': dict(Counter(r['status'] for r in rows)),
               'source_rich_protected_prefix_arm_parity_checks': 1024,
               'summaries': summaries, 'elapsed_seconds': time.monotonic() - started,
               'peak_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
               'source_and_fixture_baseline': 'Development controls, not untouched evaluation'}
    (OUT / 'controlled_summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    (OUT / 'input_verification.json').write_text(json.dumps(bindings, indent=2) + '\n')
    print(json.dumps({k: v for k, v in summary.items() if k != 'summaries'}, indent=2), flush=True)


if __name__ == '__main__':
    main()
