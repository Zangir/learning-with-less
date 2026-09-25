"""Extend only the frozen r2 censored horizons using an immutable producer ledger."""
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
from r2_conditional_pilot import group_level, level

TASK = (Path(__file__).resolve().parents[2] / 'runtime')
R2 = TASK / 'r2'
ROOT = TASK / 'r3/horizon-completion'
INPUT = ROOT / 'inputs'


def sha(path):
    with Path(path).open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def save(name, value):
    (ROOT / name).write_text(json.dumps(value, indent=2)+'\n')


def validate_membership(episodes, inventory):
    expected = [(e['episode_id'], e['initial_raw_seq']) for e in episodes]
    actual = [(e['episode_id'], e['anchor_source_seq']) for e in inventory]
    if expected != actual or len(set(expected)) != len(expected):
        raise ValueError('Extension changed frozen censored-anchor membership or source order')


def validate_rows(base_rows, extension, allowed_levels, start_ns, end_ns):
    previous = max(row['source_diff_row_0based'] for row in base_rows)
    previous_time = start_ns
    last_in_group = {}
    for row in extension:
        seq, stamp = row['source_diff_row_0based'], row['candidate_group_time_ns']
        if seq <= previous or not start_ns < stamp <= end_ns or stamp < previous_time:
            raise ValueError('Extension overlaps, reverses or leaves the frozen source/time interval')
        if level(row) not in allowed_levels:
            raise ValueError('Extension adds a level outside the original incomplete anchors')
        if row['closure_witness_time_ns'] <= stamp or row['closure_witness_source_row'] <= seq:
            raise ValueError('Candidate closure requires a strictly later source/time witness')
        previous, previous_time = seq, stamp
        last_in_group[stamp] = seq
    for row in extension:
        if row['closure_witness_source_row'] <= last_in_group[row['candidate_group_time_ns']]:
            raise ValueError('Closure witness precedes the end of the candidate group')


def stable_event(event):
    return {key: event[key] for key in ('kind', 'event_ns', 'available_ns', 'diffs', 'fills',
                                       'candidate_atomic_key')}


def extend_episode(original, rows, base_max_time):
    suffix = [row for row in rows if row['source_diff_row_0based'] > original['initial_raw_seq']]
    events = group_level(suffix)
    source = {row['source_diff_row_0based']: row for row in suffix}
    consumed, economic = [], 0
    for event in events:
        fragments = [source[diff['raw_seq']] for diff in event['diffs']]
        witnesses = [{'source_row': row['closure_witness_source_row'],
                      'candidate_time_ns': row['closure_witness_time_ns']}
                     for row in fragments if 'closure_witness_source_row' in row]
        event['candidate_group_right_boundary_closed'] = (event['kind'] != 'T'
                                                         or event['event_ns'] < base_max_time or bool(witnesses))
        event['candidate_closure_witnesses'] = witnesses
        event['closure_scope'] = 'candidate source/time group only; native atomicity and release time unproved'
        consumed.append(event)
        economic += event['kind'] != 'administrative'
        if economic == 8:
            break
    old = original['events']
    if [stable_event(e) for e in consumed[:len(old)]] != [stable_event(e) for e in old]:
        raise ValueError('Extension altered the previously consumed physical/economic prefix')
    result = deepcopy(original)
    result.update(events=consumed, horizon_complete=economic == 8)
    if result['initial'] != original['initial']:
        raise ValueError('Original initial identities changed')
    return result


def metrics(results):
    scored = [row for row in results if row['status'] == 'scored']
    widths = {arm: [Fraction(row['projections'][arm]['maximum_fill_units']
                             - row['projections'][arm]['minimum_fill_units'], row['probe_units'])
                    for row in scored] for arm in ('volume','count')}
    return {'selected':len(results), 'dispositions':dict(Counter(row['status'] for row in results)),
        'strict_bound_tightenings':sum(c < v for c,v in zip(widths['count'],widths['volume'])),
        'mean_fill_hull_width':{arm:str(sum(values)/len(values)) if values else None for arm,values in widths.items()},
        'ambiguous_fill_fraction':{arm:sum(value>0 for value in values) for arm,values in widths.items()},
        'any_fill_ambiguous':{arm:sum(len(row['projections'][arm]['any_fill'])>1 for row in scored) for arm in widths},
        'full_fill_ambiguous':{arm:sum(len(row['projections'][arm]['full_fill'])>1 for row in scored) for arm in widths},
        'observed_probe_any_fill':sum(row['truth']['filled_units']>0 for row in scored),
        'observed_probe_cancellation':sum(row['truth']['cancelled_units']>0 for row in scored),
        'population_estimand':False, 'eligible_empirical_episodes':0}


def run():
    started = time.monotonic()
    contract_path = INPUT / 'q16_extension_contract.v3.json'
    if sha(contract_path) != '8ce8e7831242082f13d1fb07349a00f5685c7dd30df0e7470ebd2a2ff9e5a055':
        raise ValueError('Frozen extension contract changed')
    contract = json.loads(contract_path.read_text())
    if (contract['schema'] != 't008-q16-fixed-cohort-extension/3' or contract['origin'] != 'exploratory_real'
            or contract['admitted'] is not False):
        raise ValueError('Unexpected producer scope/origin')
    verified = {}
    for name, expected in contract['inputs'].items():
        if sha(name) != expected:
            raise ValueError(f'Producer source digest mismatch: {name}')
        verified[name] = expected
    for name, descriptor in contract['files'].items():
        if sha(INPUT/name) != descriptor['sha256']:
            raise ValueError(f'Producer payload digest mismatch: {name}')
        verified[name] = descriptor['sha256']
    if sha(R2/'manifest.json') != '15b69f1893d444a663e321fc9312f5cdd3d78ea47751a627bdde4b7fb94774e9':
        raise ValueError('Frozen r2 manifest changed')
    old_manifest = json.loads((R2/'manifest.json').read_text())
    names = ['conditional_episodes.json', 'conditional_results.jsonl', 'terminal_depletion_completion.json',
             'inputs/december-v2/identity_candidate_events.v2.jsonl']
    for name in names:
        if sha(R2/name) != old_manifest['artifact_files'][name]['sha256']:
            raise ValueError(f'Frozen r2 evidence changed: {name}')
    original = json.loads((R2/names[0]).read_text())['episodes']
    primary = [json.loads(line) for line in (R2/names[1]).read_text().splitlines()]
    target_ids = {row['episode_id'] for row in primary if row['status']=='censored'}
    targets = [episode for episode in original if episode['episode_id'] in target_ids]
    inventory = json.loads((INPUT/'q16_horizon_completion_candidates.json').read_text())
    validate_membership(targets, inventory)
    if len(targets) != contract['fixed_anchor_count'] or len(targets) != 38:
        raise ValueError('Unexpected frozen incomplete cohort size')
    base = [json.loads(line) for line in (R2/names[3]).read_text().splitlines()]
    extension = [json.loads(line) for line in (INPUT/'q16_extension_events.v3.jsonl').read_text().splitlines()]
    allowed = {(episode['side'], int(Fraction(episode['px'])*100000000)) for episode in targets}
    validate_rows(base, extension, allowed, contract['extension_start_exclusive_ns'],
                  contract['last_closed_candidate_group_ns'])
    if len(extension) != contract['extension_rows'] or len(allowed) != contract['target_level_count']:
        raise ValueError('Extension row/level count differs from producer contract')
    save('protocol.json', {'frozen_utc':datetime.now(timezone.utc).isoformat(), 'origin':'exploratory_real',
        'admitted':False, 'selection':'Only the original 38 r2 censored anchors; all retained, no replacement',
        'horizon':'same eight economic candidate events, extended only through retained December1 hour',
        'unchanged':['initial identities/quantities','birth-order FIFO hypothesis','probe cancellation policy',
                     'candidate grouping','integer1e-8 observed grid','paired observer information'],
        'release_clock':'offline candidate exchange time; future closure witnesses are not receipt evidence',
        'solver_timeout_ms_per_query':2000, 'scoring_wall_budget_seconds':600,
        'primary_results':'r2 primary and computational completion preserved unchanged',
        'contract_sha256':sha(contract_path), 'cohort_ids':[e['episode_id'] for e in targets]})
    levels = defaultdict(list)
    for row in base+extension:
        levels[level(row)].append(row)
    expanded = [extend_episode(episode, levels[(episode['side'], int(Fraction(episode['px'])*100000000))],
                               max(row['candidate_group_time_ns'] for row in base+extension)) for episode in targets]
    for episode, supplied in zip(expanded, inventory):
        economic = [event for event in episode['events'] if event['kind']!='administrative']
        if episode['horizon_complete'] != supplied['eight_events_available']:
            raise ValueError('Consumer horizon completeness differs from producer inventory')
        if [event['diffs'][-1]['raw_seq'] for event in economic] != [e['last_source_row'] for e in supplied['first_eight_events']]:
            raise ValueError('Consumer candidate-event boundaries differ from producer inventory')
    save('expanded_episodes.json', {'origin':'exploratory_real','admitted':False,'episodes':expanded})
    save('input_verification.json', {'all_digests_match':True,'verified_inputs':verified,
        'old_prefix_preserved_for':len(expanded),'same_membership':True,
        'complete_horizons':sum(e['horizon_complete'] for e in expanded),
        'candidate_closure_not_native_action_evidence':True})
    print(json.dumps({'stage':'verified_and_frozen','anchors':len(expanded),
                      'complete':sum(e['horizon_complete'] for e in expanded)}),flush=True)
    results, score_start = [], time.monotonic()
    with (ROOT/'extension_results.jsonl').open('w') as output:
        for episode in expanded:
            try:
                if time.monotonic()-score_start > 600:
                    result={'episode_id':episode['episode_id'],'status':'unresolved','reason':'Frozen wall budget exhausted'}
                elif any(e['candidate_group_noncontiguous'] or not e['candidate_group_right_boundary_closed']
                         for e in episode['events']):
                    result={'episode_id':episode['episode_id'],'status':'unresolved','reason':'Candidate grouping/closure unresolved'}
                else:
                    result=evaluate_episode(episode,'0.00000001','exploratory_real',timeout_ms=2000)
            except ValueError as exc:
                result={'episode_id':episode['episode_id'],'status':'model_invariant_failure','reason':str(exc)}
            result.update(origin='exploratory_real', admitted=False, stage='r3_fixed_cohort_horizon_extension')
            results.append(result)
            output.write(json.dumps(result)+'\n')
            output.flush()
            print(json.dumps({'processed':len(results),'episode_id':episode['episode_id'],'status':result['status']}),flush=True)
    completed = {row['episode_id']:row for row in json.loads((R2/'terminal_depletion_completion.json').read_text())['results']}
    replacements = {row['episode_id']:row for row in results}
    combined = [replacements.get(row['episode_id'],completed.get(row['episode_id'],row)) for row in primary]
    if [row['episode_id'] for row in combined] != [row['episode_id'] for row in primary]:
        raise ValueError('Combined analysis changed cohort membership')
    save('summary.json', {'origin':'exploratory_real','admitted':False,'real_replication_complete':False,
        'extension_only':metrics(results),'combined_fixed1000_secondary':metrics(combined),
        'original_r2_primary':{'scored':961,'censored':38,'unresolved':1},
        'original_r2_computational_completion':{'scored':962,'censored':38,'unresolved':0},
        'r2_primary_unchanged':sha(R2/'conditional_results.jsonl')==old_manifest['artifact_files']['conditional_results.jsonl']['sha256'],
        'failure_reasons':dict(Counter(row.get('reason','unspecified') for row in results if row['status']!='scored')),
        'elapsed_seconds':time.monotonic()-started,'peak_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss})
    print((ROOT/'summary.json').read_text(),flush=True)


if __name__=='__main__':
    run()
