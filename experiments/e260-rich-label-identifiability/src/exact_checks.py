"""Exact label-channel calculations; no model fitting or simulator imports."""
from fractions import Fraction as F
from itertools import product
import json
from resource_guard import ROOT, record


def dot(left, right):
    return sum(a * b for a, b in zip(left, right))


def moments(values, probabilities):
    mean = dot(values, probabilities)
    return mean, dot([v * v for v in values], probabilities) - mean * mean


def encoded(value):
    if isinstance(value, F):
        return {"exact": str(value), "value": float(value)}
    if isinstance(value, dict):
        return {key: encoded(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [encoded(item) for item in value]
    return value


def main():
    kernels = [(F(9, 10), F(1, 4), F(1, 5)),
               (F(9, 10), F(17, 20), F(1, 5))]
    family = lambda e: (e, 1 - 2 * e, e)
    source = [family(F(1, 10)), family(F(2, 5))]
    shifted = list(reversed(source))
    cells = []
    for c, z in product(range(2), repeat=2):
        p, other = dot(source[c], kernels[z]), dot(shifted[c], kernels[z])
        mid = (p + other) / 2
        assert abs(p - other) == F(9, 50)
        cells.append(dict(c=c, z=z, source=p, shifted=other, minimax=mid))
    bayes = sum(row['source'] * (1 - row['source']) for row in cells) / 4
    lower = sum((row['source'] - row['shifted']) ** 2 / 4 for row in cells) / 4
    frozen_excess = 4 * lower
    assert (bayes, lower, bayes + lower, bayes + frozen_excess) == (
        F(2169, 10000), F(81, 10000), F(9, 40), F(2493, 10000))

    # New descriptors do not make the same label count twice as information.
    variance_rows = []
    for e in (F(1, 10), F(2, 5)):
        q = family(e)
        h_mean, h_var = moments([F(1, 2), F(0), F(1, 2)], q)
        assert h_mean == e and h_var == e * (F(1, 2) - e)
        y_vars = []
        for z in range(2):
            p = dot(q, kernels[z])
            a, b = (F(1, 4), F(3, 5)) if z == 0 else (F(17, 20), F(-3, 5))
            mean, var = moments([-a / b, (1 - a) / b], [1 - p, p])
            assert mean == e
            y_vars.append(var)
        outcome_var = sum(y_vars) / 2
        variance_rows.append(dict(e=e, h_variance_times_n=h_var,
                                  y_variance_times_n=outcome_var,
                                  raw_estimator_cost_ratio=outcome_var / h_var))
    assert [r['raw_estimator_cost_ratio'] for r in variance_rows] == [F(211, 16), F(271, 16)]

    # An explicit extension drops the r7 symmetric-family restriction.
    null_vector = (1, -14, 13)
    assert sum(null_vector) == 0 and dot(null_vector, kernels[0]) == 0
    q_plus = tuple(F(1, 3) + F(v, 100) for v in null_vector)
    q_minus = tuple(F(1, 3) - F(v, 100) for v in null_vector)
    assert min(q_plus + q_minus) > 0
    old = dot(q_plus, kernels[0])
    assert old == dot(q_minus, kernels[0]) == F(9, 20)
    new_plus, new_minus = dot(q_plus, kernels[1]), dot(q_minus, kernels[1])
    assert (new_plus, new_minus) == (F(283, 500), F(367, 500))
    new_lower = (new_plus - new_minus) ** 2 / 4
    assert new_lower == F(441, 62500)
    # With both old kernels, the simplex normalization completes full rank.
    matrix = [(F(1), F(1), F(1)), *kernels]
    a, b, c = matrix[0]
    d, e, f = matrix[1]
    g, h, i = matrix[2]
    determinant = a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g)
    assert determinant == F(21, 50)

    identities = 0
    contexts = kernels + [(F(1), F(0), F(0)), (F(1, 2), F(1, 3), F(1, 7))]
    for n in range(1, 9):
        for counts in product(range(n + 1), repeat=2):
            if sum(counts) > n:
                continue
            counts = (*counts, n - sum(counts))
            posterior = tuple(F(count, n) for count in counts)
            for kernel in contexts:
                structured = dot(posterior, kernel)
                direct = sum(counts[h] * kernel[h] for h in range(3)) / n
                assert structured == direct
                identities += 1
    out = dict(scope='Exact arithmetic, not fitted or simulated results',
               reserved_seed=20260919, random_draws=0, fits=0, native_episodes=0,
               cells=cells, bayes_brier=bayes, no_label_minimax_excess=lower,
               no_label_minimax_brier=bayes + lower,
               frozen_ideal_predictor_shift_brier=bayes + frozen_excess,
               variance_comparators=variance_rows,
               rank_extension=dict(q_plus=q_plus, q_minus=q_minus, old_probability=old,
                                   new_plus=new_plus, new_minus=new_minus,
                                   new_context_minimax_excess=new_lower,
                                   two_context_determinant=determinant),
               compiled_direct_equalities=identities)
    (ROOT / 'exact-checks.json').write_text(json.dumps(encoded(out), indent=2) + '\n')
    record('checks-resource.json', dict(status='completed', fits=0, native_episodes=0,
                                       compiled_direct_equalities=identities))


if __name__ == '__main__':
    main()
