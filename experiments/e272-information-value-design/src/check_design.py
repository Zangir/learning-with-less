"""Exact finite-law design checks. No empirical rows, model objects or scoring are read."""
from collections import defaultdict
from datetime import datetime
from fractions import Fraction as F
import hashlib
import json
import shutil
from resource_guard import ROOT, record

PROGRAM = ROOT.parents[1]
K = 3


def sha(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def serial(value):
    if isinstance(value, F):
        return dict(exact=str(value), value=float(value))
    raise TypeError(type(value))


def save(name, value):
    (ROOT / name).write_text(json.dumps(value, default=serial, indent=2) + '\n')


def onehot(y):
    return tuple(F(int(k == y)) for k in range(K))


def norm2(v):
    return sum(t*t for t in v)


def difference(a, b):
    return tuple(x-y for x, y in zip(a, b))


def loss(p, y):
    return norm2(difference(p, onehot(y))) / 2


def conditional_mean(rows, key, target):
    mass, total = defaultdict(F), {}
    for row in rows:
        group, weight = key(row), row['p']
        mass[group] += weight
        total.setdefault(group, [F(0)] * K)
        total[group] = [a + weight*b for a, b in zip(total[group], target(row))]
    return {g: tuple(a/mass[g] for a in v) for g, v in total.items()}


def audit_law(name, rows, coarse, rich):
    assert sum(row['p'] for row in rows) == 1
    by_x = lambda r: r['x']
    by_xz = lambda r: (r['x'], r['z'])
    by_xs = lambda r: (r['x'], rich(r))
    posterior = lambda key: conditional_mean(rows, key, lambda r: onehot(r['y']))
    mx, mxz, mxs = posterior(by_x), posterior(by_xz), posterior(by_xs)
    ms = conditional_mean(rows, by_x, rich)
    average = lambda fn: sum(r['p'] * fn(r) for r in rows)
    delta = average(lambda r: norm2(difference(mxz[by_xz(r)], mx[by_x(r)]))) / 2
    delta_score = average(lambda r: norm2(difference(mxs[by_xs(r)], mx[by_x(r)]))) / 2
    risk_c = average(lambda r: loss(coarse(r), r['y']))
    risk_r = average(lambda r: loss(rich(r), r['y']))
    regret_c = average(lambda r: norm2(difference(coarse(r), mx[by_x(r)]))) / 2
    regret_r = average(lambda r: norm2(difference(rich(r), mxz[by_xz(r)]))) / 2
    assert risk_r-risk_c == -delta + regret_r-regret_c
    j = F(0)
    marginal = F(0)
    for row in rows:
        peers = [r for r in rows if r['x'] == row['x']]
        mass = sum(r['p'] for r in peers)
        replacement = sum(r['p']*loss(rich(r), row['y']) for r in peers) / mass
        j += row['p']*(replacement-loss(rich(row), row['y']))
        marginal += row['p']*(sum(r['p']*loss(rich(r), row['y']) for r in rows)-loss(rich(row), row['y']))
    covariance = average(lambda r: sum(a*b for a, b in zip(
        difference(mxz[by_xz(r)], mx[by_x(r)]), difference(rich(r), ms[by_x(r)]))))
    score_covariance = average(lambda r: sum(a*b for a, b in zip(
        difference(mxs[by_xs(r)], mx[by_x(r)]), difference(rich(r), ms[by_x(r)]))))
    variance = average(lambda r: norm2(difference(rich(r), ms[by_x(r)])))
    assert j == covariance == score_covariance
    assert F(0) <= delta_score <= delta and variance <= F(2, 3)
    assert j*j <= 2*delta_score*variance
    bound = j*j / (2*variance) if variance else F(0)
    return dict(name=name, law=rows, oracle_information_value=delta,
        score_information_value=delta_score, coarse_risk=risk_c, rich_risk=risk_r,
        rich_minus_coarse=risk_r-risk_c, coarse_regret=regret_c, rich_regret=regret_r,
        conditional_replacement=j, marginal_replacement=marginal, score_variance=variance,
        information_lower_bound=bound, decomposition_verified=True, covariance_identity_verified=True)


def verify_scoped_inputs():
    prior = {p.relative_to(ROOT.parent).as_posix(): sha(p)
             for p in ROOT.parent.rglob('*') if p.is_file() and ROOT not in p.parents}
    baseline = ROOT / 'preservation-before.json'
    if baseline.exists():
        assert json.loads(baseline.read_text()) == prior
    else:
        save('preservation-before.json', prior)
    reviewer = PROGRAM / 'cycle-20260922-2047/frozen/RV-040'
    assert sha(reviewer/'manifest.sha256') == '54f700426261cb4b102027ba84c27a92d5c86a7a8d85e246689c8ab45ba781cc'
    reviewer_entries = {line[66:]: line[:64] for line in (reviewer/'manifest.sha256').read_text().splitlines() if line}
    assert sha(reviewer/'report.md') == reviewer_entries['report.md']
    producer = PROGRAM / 'cycle-20260922-1946/frozen/R-042'
    manifest = producer/'artifact-manifest.json'
    assert sha(manifest) == 'd00223c9c733da20a6da6ecf9e7f70a04dbd55d456ee72abbfad396a578da86b'
    entries = {r['path']: r for r in json.loads(manifest.read_text())['files']}
    assert sha(producer/'report.md') == entries['report.md']['sha256']
    names = ['cycle-20260922-2047/frozen/RV-040/report.md',
        'cycle-20260922-2047/frozen/RV-040/manifest.sha256',
        'cycle-20260922-1946/frozen/R-042/report.md',
        'cycle-20260922-1946/frozen/R-042/artifact-manifest.json',
        'cycle-20260922-1441/frozen/RV-031/report.md',
        'cycle-20260922-2047/T012-context/architecture.md',
        'cycle-20260922-2047/T012-context/original-strategy-list.md',
        'cycle-20260922-2047/T012-context/strategy-catalog.md',
        'T-012/r9-contribution-triage/report.md', 'T-012/r9-contribution-triage/manifest.json',
        'T-012/r8-shift-label-novelty/atlas-imputation-iclr2025-primary.pdf',
        'T-012/r8-shift-label-novelty/atlas-imputation-iclr2025-primary.txt']
    save('scoped-input-identities.json', dict(at=datetime.now().astimezone().isoformat(),
        files=[dict(path=name, sha256=sha(PROGRAM/name), size_bytes=(PROGRAM/name).stat().st_size) for name in names],
        prior_files=len(prior), scope='Scoped report/metadata hashes only; no source/event/model replay',
        full_r042_manifest_replayed=False))
    assert shutil.disk_usage(Path.cwd()).free > 50 * 1024**3


def main():
    status = 'failed'
    try:
        verify_scoped_inputs()
        uniform = lambda r: (F(1,3),)*3
        half = lambda r: (F(1,2), F(1,2), F(0))
        truth = lambda r: onehot(r['z'])
        null = [dict(x=x, z=x, y=x, p=F(1,2)) for x in range(2)]
        xor = [dict(x=(a,b), z=a^b, y=a^b, p=F(1,4)) for a in range(2) for b in range(2)]
        informative = [dict(x=0, z=y, y=y, p=F(1,3)) for y in range(3)]
        cases = [audit_law('Redundant depth; coarse learner is imperfect', null, half, truth),
                 audit_law('Deterministic XOR feature; no new information', xor, half, truth),
                 audit_law('True information; correct rich score', informative, uniform, truth),
                 audit_law('True information; rich score ignores it', informative, uniform, uniform),
                 audit_law('True information; rich score uses it wrongly', informative, uniform,
                           lambda r: onehot((r['z']+1)%3))]
        assert cases[0]['oracle_information_value'] == 0 and cases[0]['marginal_replacement'] == F(1,2)
        assert cases[2]['conditional_replacement'] == F(2,3)
        assert cases[3]['conditional_replacement'] == 0 and cases[3]['oracle_information_value'] == F(1,3)
        assert cases[4]['conditional_replacement'] == -F(1,3)
        epsilon = F(1,8)
        # A plausible-looking replacement can still smuggle in the wrong null.
        approximate_j = sum(r['p'] * epsilon * loss(onehot(1-r['y']), r['y']) for r in null)
        assert approximate_j == epsilon and max(approximate_j-epsilon, F(0)) == 0
        constant = (F(3,4), F(1,4), F(0))
        source_world = [(0,0,F(1,2)), (1,1,F(1,2))]
        prior_target = [(0,0,F(3,4)), (1,1,F(1,4))]
        conditional_target = [(1,0,F(3,4)), (0,1,F(1,4))]
        assert all(x == y for x,y,p in source_world + prior_target)
        assert all(x != y for x,y,p in conditional_target)
        shift_risks = [sum(p*loss(constant,y) for x,y,p in world) for world in [prior_target,conditional_target]]
        assert shift_risks == [F(3,16), F(3,16)]
        save('analytical-checks.json', dict(scope='Exact synthetic finite laws; no data extraction, fitting or empirical scoring',
            reserved_seed=20260919, random_draws=0, cases=cases,
            approximate_sampler_null=dict(total_variation=epsilon, false_positive_contrast=approximate_j,
                                         bias_adjusted_lower_bound=F(0)),
            shift_counterexample=dict(common_source=source_world, prior_only=prior_target, changed_conditional=conditional_target,
                                      identical_fixed_score_risks=shift_risks,
                                      conditional_losses=[loss(constant,y) for y in range(2)]),
            new_fits=0, empirical_scoring=0, native_episodes=0))
        status = 'completed'
    finally:
        record('checks-resource.json', dict(status=status, new_fits=0, empirical_scoring=0, native_episodes=0))


if __name__ == '__main__':
    main()
