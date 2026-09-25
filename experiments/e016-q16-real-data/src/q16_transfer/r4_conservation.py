"""Count-free explanations of saved conditional outcomes; no new real scoring."""
from collections import Counter
import json
import time

from adapter import units
from r4_controlled import ROOT, OUT, PROTOCOL_SHA, sha


def conservation_bounds(ahead, probe, events):
    traded = sum(q for kind, q in events if kind == 'T')
    cancelled = sum(q for kind, q in events if kind == 'C')
    low = max(0, min(traded - ahead, probe - cancelled))
    high = min(probe, max(0, traded - ahead + cancelled))
    remaining_ahead, exposure = ahead, 0
    for kind, quantity in events:
        if kind == 'T':
            exposure += max(0, quantity - remaining_ahead)
        if kind != 'A':
            remaining_ahead = max(0, remaining_ahead - quantity)
    return {'aggregate_lower': low, 'aggregate_upper': high,
            'chronological_upper': min(probe, exposure),
            'signed_delta_exact_upper': min(probe, max(0, traded + cancelled - ahead)),
            'total_trade': traded, 'total_cancel': cancelled}


def jsonl(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def main():
    started = time.monotonic()
    if sha(OUT / 'protocol.json') != PROTOCOL_SHA:
        raise ValueError('Frozen protocol changed')
    protocol = json.loads((OUT / 'protocol.json').read_text())
    for entry in protocol['input_files']:
        path = (Path(__file__).resolve().parents[2] / 'runtime' / Path(entry['path']).name)
        if sha(path) != entry['sha256']:
            raise ValueError('Source binding changed')
    primary = jsonl(ROOT / 'r2/conditional_results.jsonl')
    completion = {r['episode_id']: r for r in json.loads((ROOT / 'r2/terminal_depletion_completion.json').read_text())['results']}
    extension = {r['episode_id']: r for r in jsonl(ROOT / 'r3/horizon-completion/extension_results.jsonl')}
    original_episodes = json.loads((ROOT / 'r2/conditional_episodes.json').read_text())['episodes']
    expanded = json.loads((ROOT / 'r3/horizon-completion/expanded_episodes.json').read_text())['episodes']
    episodes = {e['episode_id']: e for e in original_episodes + expanded}
    stages = {'r2_primary': primary,
              'r2_computational_completion': [completion.get(r['episode_id'], r) for r in primary],
              'r3_observation_extension': [extension.get(r['episode_id'], completion.get(r['episode_id'], r)) for r in primary]}
    all_rows, summaries = [], {}
    for stage, records in stages.items():
        certificates, coarsening = Counter(), Counter()
        for saved in records:
            row = {'stage': stage, 'episode_id': saved['episode_id'], 'saved_status': saved['status'],
                   'origin': 'conditional_development_explanation', 'admitted': False}
            if saved['status'] != 'scored':
                all_rows.append(row)
                continue
            episode = episodes[saved['episode_id']]
            probe = saved['probe_units']
            ahead = sum(units(o['sz'], '0.00000001') for o in episode['initial']) - probe
            events = [(e['kind'], e['quantity_units']) for e in saved['observed_events']]
            bound = conservation_bounds(ahead, probe, events)
            wide = saved['projections']['volume']
            lower, upper = wide['minimum_fill_units'], wide['maximum_fill_units']
            assert bound['aggregate_lower'] <= lower <= upper <= min(bound['aggregate_upper'], bound['chronological_upper'])
            if bound['total_trade'] == 0:
                certificate = 'no_labelled_trades'
            elif bound['aggregate_lower'] == bound['aggregate_upper']:
                certificate = 'aggregate_singleton_with_trades'
            elif bound['chronological_upper'] == 0:
                certificate = 'chronological_shielding_only'
            else:
                certificate = 'requires_richer_sequence_reasoning'
            if certificate != 'requires_richer_sequence_reasoning':
                assert lower == upper
            masked_upper = bound['signed_delta_exact_upper']
            assert masked_upper >= upper
            ambiguous = masked_upper > lower
            coarsening['proved_ambiguous'] += ambiguous
            coarsening['not_decided_by_maximum_witness'] += not ambiguous
            certificates[certificate] += 1
            row.update(ahead_units=ahead, probe_units=probe, bounds=bound,
                       certificate=certificate, saved_fill_units=lower,
                       signed_delta_ambiguity_certified=ambiguous,
                       source_ref={'episode_id': saved['episode_id'], 'stage': stage,
                                   'input_binding': 'protocol.json/input_files'})
            all_rows.append(row)
        summaries[stage] = {'selected': len(records), 'dispositions': dict(Counter(r['status'] for r in records)),
                            'certificates': dict(certificates), 'signed_delta_count_hidden': dict(coarsening)}
    (OUT / 'conservation_rows.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in all_rows))
    result = {'protocol_sha256': PROTOCOL_SHA, 'stages': summaries,
              'interpretation': 'Sufficient certificates on retained development evidence. Coarsening ambiguity follows from two feasible witnesses; no masked count inference or empirical admission.',
              'elapsed_seconds': time.monotonic() - started}
    (OUT / 'conservation_summary.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2), flush=True)


if __name__ == '__main__':
    main()
