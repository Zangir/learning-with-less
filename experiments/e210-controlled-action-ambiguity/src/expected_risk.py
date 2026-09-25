"""Post-run deterministic diagnostic; integrate finite-sample risks without new seeds."""
from fractions import Fraction as F
from pathlib import Path
import csv
import json
import math
import resource
import time

ROOT = Path(__file__).resolve().parents[1]
SIZES = (32, 128, 512)
CDF = ((F(2, 5), F(1, 2), F(3, 5)), (F(1, 10), F(1, 2), F(9, 10)))
QUERIES = ((0, F(3, 4)), (2, F(1, 4)))


def binomial(n, p):
    """Relative masses grow out from the mode, so tiny endpoint mass cannot erase the law."""
    p = float(p)
    mode = int((n + 1) * p)
    mass = [0.0] * (n + 1)
    mass[mode] = 1.0
    for k in range(mode, 0, -1):
        mass[k - 1] = mass[k] * k / (n - k + 1) * (1 - p) / p
    for k in range(mode, n):
        mass[k + 1] = mass[k] * (n - k) / (k + 1) * p / (1 - p)
    total = math.fsum(mass)
    return [v / total for v in mass]


def mean_risks(n, family):
    weights = binomial(n, F(1, 2))
    rps_excess, regret = 0.0, 0.0
    for k, wk in enumerate(weights):
        denominator = (k + 4) ** 2
        for x in range(2):
            if family == 'universal':
                rps_excess += wk * sum(float(k * q * (1 - q) + (j + 1 - 4 * q) ** 2) / denominator
                                       for j, q in enumerate(CDF[x])) / 6
            else:
                e = 2 * CDF[x][0]
                rps_excess += wk * float(F(1, 4) * k * e * (1 - e) + (1 - 2 * e) ** 2) / denominator / 3
            for j, cross in QUERIES:
                q = CDF[x][j]
                best_post = q > 1 - cross
                success_prob = q if family == 'universal' else 2 * CDF[x][0]
                masses = binomial(k, success_prob)
                wrong = []
                for s, probability in enumerate(masses):
                    if family == 'universal':
                        prediction = F(s + j + 1, k + 4)
                    else:
                        tail = F(s + 2, 2 * (k + 4))
                        prediction = tail if j == 0 else 1 - tail
                    if (prediction > 1 - cross) != best_post:
                        wrong.append(probability)
                # Integrate regret directly instead of subtracting nearly equal expected costs.
                regret += wk * math.fsum(wrong) * float(abs(q - (1 - cross))) / 4
    return {'n_train': n, 'family': family, 'expected_rps': 29 / 150 + rps_excess,
            'expected_rps_excess': rps_excess, 'expected_primary_regret': regret,
            'expected_primary_cost': 17 / 40 + regret}


def checks():
    for n in (0, 1, 4, 16, 64, 512):
        for p in (0.1, 0.4, 0.5, 0.8, 0.9):
            masses = binomial(n, p)
            assert abs(math.fsum(masses) - 1) < 1e-13
            assert abs(math.fsum(k * v for k, v in enumerate(masses)) - n * p) < 1e-9
            if n <= 16:
                direct = [math.comb(n, k) * p ** k * (1 - p) ** (n - k) for k in range(n + 1)]
                assert max(abs(a - b) for a, b in zip(masses, direct)) < 1e-13


def main():
    started = time.perf_counter()
    checks()
    rows = [mean_risks(n, family) for n in SIZES for family in ('universal', 'symmetric')]
    with (ROOT / 'expected_risk.csv').open('w', newline='', encoding='utf-8') as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    record = {'status': 'passed', 'scope': 'Post-run deterministic integration, no new stochastic experiment',
              'finite_population_model': 'Context counts Binomial(n,.5); target counts conditional Binomial',
              'uncertainty': 'Floating-point evaluation of finite sums, not Monte Carlo confidence intervals',
              'numerical_checks': 'Probability normalization, first moments, small-n direct binomial sums',
              'zero_of_400_one_sided_95_error_probability_upper': 1 - 0.05 ** (1 / 400),
              'runtime_seconds': time.perf_counter() - started,
              'max_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}
    (ROOT / 'expected_risk_metadata.json').write_text(json.dumps(record, indent=2), encoding='utf-8')
    print(json.dumps({'rows': rows, **record}, indent=2), flush=True)


if __name__ == '__main__':
    main()
