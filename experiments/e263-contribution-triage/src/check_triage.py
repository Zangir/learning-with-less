"""Audit accepted packets and small analytical witnesses, without executing models."""
from fractions import Fraction as F
from pathlib import Path
from datetime import datetime
from decimal import Decimal
import hashlib
import json
from resource_guard import ROOT, record

PROGRAM = ROOT.parents[1]


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def save(name, value):
    (ROOT / name).write_text(json.dumps(value, indent=2) + '\n')


def rational(value):
    return dict(exact=str(value), value=float(value))


def verify_inputs():
    prior = {p.relative_to(ROOT.parent).as_posix(): sha(p)
             for p in ROOT.parent.rglob('*') if p.is_file() and ROOT not in p.parents}
    baseline = ROOT / 'preservation-before.json'
    if baseline.exists():
        assert json.loads(baseline.read_text()) == prior, 'Prior artifacts changed'
    else:
        save('preservation-before.json', prior)
    packets = [
        ('R030', 'cycle-20260922-1122/frozen-R-030', 'manifest.json',
         'fc88f6062ce906ba19b0694e0dace043018f153b30746f0a404378ba1c2d9d2e'),
        ('RV028', 'cycle-20260922-1222/frozen-RV-028', 'manifest.json', None),
        ('R031', 'cycle-20260922-1122/frozen-R-031', 'artifact-manifest.json',
         '5450d4411bbfc91451b4b60b330c23da0eec5f31fabe628dcf9c26d9083b72c0'),
        ('RV029', 'cycle-20260922-1222/frozen-RV-029', 'manifest.sha256',
         'f0e2cb0530e5e65fb563729b9399062c439d20e2105b6636618fdf66243bab9f'),
        ('R020', 'q18-full-day-review-handoff/frozen-T008-r4', 'manifest.json',
         '7c32bbee2a00483b10364bda93306d75e0f96700aa40ee7c58474b023f7aff6a')]
    checked = []
    for name, relative, manifest, expected in packets:
        folder = PROGRAM / relative
        identity = sha(folder / manifest)
        if expected:
            assert identity == expected, name
        if manifest.endswith('.json'):
            raw = json.loads((folder / manifest).read_text())
            raw = raw.get('files', raw.get('artifacts'))
            entries = raw if isinstance(raw, list) else [dict(path=k, **v) for k, v in raw.items()]
        else:
            entries = [dict(sha256=line[:64], path=line[66:])
                       for line in (folder / manifest).read_text().splitlines() if line]
        for item in entries:
            path = folder / item['path']
            assert path.resolve().is_relative_to(folder.resolve())
            assert sha(path) == item['sha256'], (name, item['path'])
        checked.append(dict(name=name, manifest_sha256=identity, members=len(entries), all_match=True))
    save('input-verification.json', dict(at=datetime.now().astimezone().isoformat(),
        prior_files=len(prior), checked_packets=checked,
        RV018_scope='Read accepted review and corrected assessment; no repeat raw-source decoding'))


def analytical_checks():
    # Equal outputs across unequal information sets can throw away the useful bit.
    ys = [F(0), F(1)]
    coarse = F(1, 2)
    coarse_risk = sum((coarse - y) ** 2 for y in ys) / 2
    fine_risk = sum((y - y) ** 2 for y in ys) / 2
    assert coarse_risk == F(1, 4) and fine_risk == 0
    assert sum(ys) / 2 == coarse

    # Snapshot-valid paths can agree marginally and disagree on a joint event.
    laws = [[(0, 0), (1, 1)], [(0, 1), (1, 0)]]
    marginal = [[sum(F(path[t], 2) for path in law) for t in range(2)] for law in laws]
    assert marginal[0] == marginal[1] == [F(1, 2), F(1, 2)]
    joint = [sum(F(u * v, 2) for u, v in law) for law in laws]
    assert joint == [F(1, 2), F(0)]
    snapshot_paths = [[[dict(bid=99, ask=101, bid_size=1 + bit, ask_size=1) for bit in path]
                       for path in law] for law in laws]
    assert all(s['bid'] < s['ask'] and min(s['bid_size'], s['ask_size']) > 0
               for law in snapshot_paths for path in law for s in path)
    worlds = [['F'] * 8, ['F'] * 4 + ['A'] * 4]
    assert worlds[0][:4] == worlds[1][:4]
    selective_world_risks = [sum(F(y != 'F') for y in world) / 8 for world in worlds]
    assert selective_world_risks == [F(0), F(1, 2)]

    saved = PROGRAM / 'cycle-20260922-1122/frozen-R-031'
    summary = json.loads((saved / 'figures/figure_source.json').read_text(), parse_float=Decimal)
    pairs = [('breakout', 'C', 'R', '2025-10-01'), ('breakout', 'C', 'P', '2025-10-01'),
             ('rebound', 'P', 'train-frequency', '2025-08-01')]
    bounds = []
    for family, left, right, missing_date in pairs:
        rows = [r for r in summary['rows'] if r['family'] == family]
        center = F(0)
        radius = F(0)
        observed = F(0)
        for row in rows:
            delta = F(row['scores'][left]) - F(row['scores'][right])
            n = row['n']
            missing = int(row['date'] == missing_date)
            observed += delta / 4
            center += F(n, n + missing) * delta / 4
            radius += F(missing, n + missing) / 4
        lower, upper = center - radius, center + radius
        assert upper < 0 if family == 'breakout' else lower > 0
        bounds.append(dict(family=family, difference=f'{left}-{right}',
            supported_only=rational(observed), completion_lower=rational(lower),
            completion_upper=rational(upper), half_width=rational(radius)))

    examples = json.loads((saved / 'verified-examples.json').read_text())
    example = examples[0]
    assert example['date'] == '2025-08-01' and example['family'] == 'rebound'
    label = example['label_record']
    assert label['label'] == 'A' and label['complete_future_support']
    price_scale = F(1, 2 * 10**8)
    movement = (label['future_refs'][0]['mid2'] - example['event']['decision_mid2']) * price_scale
    epsilon = F(example['event']['epsilon2']['numerator'], example['event']['epsilon2']['denominator']) * price_scale
    assert movement == -18 and movement < -epsilon
    prob = example['probabilities']['P']
    loss = .5 * (sum(p*p for p in prob) + 1) - prob[1]
    one_hot_loss = sum((p - y) ** 2 for p, y in zip(prob, [0, 1, 0])) / 2
    assert abs(loss - one_hot_loss) < 1e-15
    assert round(loss, 8) == .03536465
    save('retained-genuine-example.json', example)
    save('analytical-checks.json', dict(scope='Exact witnesses and arithmetic on frozen summaries; no empirical replay',
        candidate_A=dict(coarse_brier=rational(coarse_risk), fine_brier=rational(fine_risk),
                         tower_identity=True, forced_invariance_fine_penalty=rational(coarse_risk)),
        candidate_B=dict(laws=laws, paths=snapshot_paths, identical_marginals=True,
                         joint_event_probabilities=[rational(v) for v in joint],
                         native_lifecycle_validity_claimed=False),
        candidate_C=dict(observed_half_brier=0, observationally_equal=True,
                         full_record_world_risks=[rational(v) for v in selective_world_risks]),
        completion_bounds=bounds,
        completion_scope='Outer finite-record bounds for hypothetical completed labels; not new scored results, sharp intervals or future guarantees',
        retained_example=dict(event_id=example['event']['event_id'], saved_input_sha256=sha(saved/'verified-examples.json'),
            movement=rational(movement), epsilon=rational(epsilon), recomputed_half_brier=loss),
        reserved_seed=20260919, random_draws=0, new_fits=0, native_episodes=0))


def main():
    status = 'failed'
    try:
        verify_inputs()
        analytical_checks()
        status = 'completed'
    finally:
        record('checks-resource.json', dict(status=status, new_fits=0, native_episodes=0))


if __name__ == '__main__':
    main()
