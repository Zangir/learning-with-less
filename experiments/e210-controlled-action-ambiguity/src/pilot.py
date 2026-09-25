"""E-210 r2: matched-supervision query reuse with exact decision arithmetic."""
from collections import Counter, defaultdict
from datetime import datetime, timezone
from fractions import Fraction as F
from pathlib import Path
import csv
import gzip
import hashlib
import json
import math
import os
import platform
import random
import resource
import statistics
import time

ROOT = Path(__file__).resolve().parents[1]
SEED = 20260919
REPLICATES = 400
SIZES = (32, 128, 512)
LAW = ((F(2, 5), F(1, 10), F(1, 10), F(2, 5)),
       (F(1, 10), F(2, 5), F(2, 5), F(1, 10)))
CDF = tuple(tuple(sum(p[:j + 1]) for j in range(3)) for p in LAW)
COSTS = (F(1, 10), F(1, 4), F(2, 5), F(1, 2), F(3, 5), F(3, 4), F(9, 10))
PRIMARY_QUERIES = ((0, F(3, 4)), (2, F(1, 4)))


def write_csv(name, rows):
    with (ROOT / name).open('w', newline='', encoding='utf-8') as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def distribution_from_cdf(cdf):
    return (cdf[0], cdf[1] - cdf[0], cdf[2] - cdf[1], 1 - cdf[2])


def fit(data):
    """Independent target aggregation; equality is checked, never assumed by copying."""
    result, counts_rows = {}, []
    for x in range(2):
        cell = [a for xx, a in data if xx == x]
        count = Counter(cell)
        n = len(cell)
        posterior = tuple(F(count[k] + 1, n + 4) for k in range(4))
        posterior_cdf = tuple(sum(posterior[:j + 1]) for j in range(3))
        direct_cdf = tuple(F(sum(a <= j for a in cell) + j + 1, n + 4) for j in range(3))
        extreme_rate = F(sum(a in (0, 3) for a in cell) + 2, n + 4)
        symmetric_direct = (extreme_rate / 2, F(1, 2), 1 - extreme_rate / 2)
        symmetric_posterior = tuple((posterior[k] + posterior[3 - k]) / 2 for k in range(4))
        symmetric_cdf = tuple(sum(symmetric_posterior[:j + 1]) for j in range(3))
        assert posterior_cdf == direct_cdf
        assert symmetric_cdf == symmetric_direct
        assert distribution_from_cdf(direct_cdf) == posterior
        result[x] = {'universal': direct_cdf, 'symmetric': symmetric_direct}
        counts_rows.append({'context': x, 'n_context': n, **{f'n_a{k}': count[k] for k in range(4)}})
    return result, counts_rows


def rps(predicted):
    return sum(float(q * (1 - q) + (predicted[x][j] - q) ** 2)
               for x in range(2) for j, q in enumerate(CDF[x])) / 6


def cost(predicted, threshold, cross_cost):
    # Rational comparisons keep the tie gremlin from the previous pilot out.
    return sum((1 - CDF[x][threshold]) if predicted[x][threshold] > 1 - cross_cost else cross_cost
               for x in range(2)) / 2


def latent_mean_mse(predicted):
    return sum(float(p * (sum(k * q for k, q in enumerate(distribution_from_cdf(predicted[x]))) - a) ** 2)
               for x in range(2) for a, p in enumerate(LAW[x])) / 2


def rank(rows):
    work = [list(map(F, row)) for row in rows]
    pivot = 0
    for col in range(len(work[0])):
        target = next((i for i in range(pivot, len(work)) if work[i][col]), None)
        if target is None:
            continue
        work[pivot], work[target] = work[target], work[pivot]
        scale = work[pivot][col]
        work[pivot] = [v / scale for v in work[pivot]]
        for i in range(len(work)):
            if i != pivot:
                scale = work[i][col]
                work[i] = [a - scale * b for a, b in zip(work[i], work[pivot])]
        pivot += 1
    return pivot


def population():
    rows = []
    compressed = {x: (F(1, 4), F(1, 2), F(3, 4)) for x in range(2)}
    truth = {x: CDF[x] for x in range(2)}
    for model, pred in [('full_observation_oracle', truth), ('mean_or_source_only_oracle', compressed)]:
        for threshold in range(3):
            for c in COSTS:
                value, best = cost(pred, threshold, c), cost(truth, threshold, c)
                rows.append({'reference': model, 'threshold': threshold, 'cross_cost': float(c),
                             'expected_cost': float(value), 'bayes_cost': float(best),
                             'regret': float(value - best)})
    primary_best = sum(cost(truth, j, c) for j, c in PRIMARY_QUERIES) / 2
    compressed_cost = sum(cost(compressed, j, c) for j, c in PRIMARY_QUERIES) / 2
    assert all(sum(a * p for a, p in enumerate(law)) == F(3, 2) for law in LAW)
    assert CDF[0][1] == CDF[1][1] == F(1, 2)
    assert sorted(LAW[0]) == sorted(LAW[1])  # Equal entropy, different task-relevant shape.
    assert primary_best == F(17, 40) and compressed_cost - primary_best == F(3, 40)
    assert rank([(1, 1, 0, 0)]) == 1
    assert rank([(1, 0, 0, 0), (1, 1, 0, 0), (1, 1, 1, 0)]) == 3
    metadata = {'population_mean': 1.5, 'source_threshold_1_risk': 0.5,
                'same_entropy': True, 'primary_bayes_cost': float(primary_best),
                'compression_oracle_cost': float(compressed_cost), 'compression_regret': 0.075,
                'bayes_rps': rps(truth), 'compression_oracle_rps': rps(compressed),
                'source_loss_span_rank_mod_constants': 1, 'all_threshold_rank_mod_constants': 3,
                'symmetric_distribution_family_dimension_per_context': 1}
    return rows, metadata


def monte_carlo():
    rng = random.Random(SEED)
    result_rows, prediction_rows, count_rows, sample_rows = [], [], [], []
    query_values = defaultdict(list)
    targets = dict(zip(range(2), CDF))
    raw_path = ROOT / 'training_rows.csv.gz'
    with gzip.open(raw_path, 'wt', newline='', encoding='utf-8') as file:
        writer = csv.writer(file)
        writer.writerow(['dataset', 'row', 'context_x', 'observed_depth_units', 'hidden_a_train_only_units',
                         'target_threshold0', 'target_threshold1', 'target_threshold2'])
        for replicate in range(REPLICATES):
            data = []
            for index in range(max(SIZES)):
                x, u = rng.randrange(2), rng.random()
                a = next(k for k in range(4) if u < float(sum(LAW[x][:k + 1])))
                data.append((x, a))
                row = [replicate, index, x, 4, a, int(a <= 0), int(a <= 1), int(a <= 2)]
                writer.writerow(row)
                if replicate == 0 and index < 3:
                    sample_rows.append(dict(zip(['dataset', 'row', 'context_x', 'observed_depth_units',
                        'hidden_a_train_only_units', 'target_threshold0', 'target_threshold1', 'target_threshold2'], row)))
            for n in SIZES:
                fitted, counts = fit(data[:n])
                for item in counts:
                    count_rows.append({'dataset': replicate, 'n_train': n, **item})
                for family in ('universal', 'symmetric'):
                    pred = {x: fitted[x][family] for x in range(2)}
                    primary = sum(cost(pred, j, c) for j, c in PRIMARY_QUERIES) / 2
                    best = sum(cost(targets, j, c) for j, c in PRIMARY_QUERIES) / 2
                    result_rows.append({'dataset': replicate, 'n_train': n, 'family': family,
                        'rps': rps(pred), 'primary_cost': float(primary), 'primary_regret': float(primary - best),
                        'latent_mean_mse': latent_mean_mse(pred)})
                    for x in range(2):
                        prediction_rows.append({'dataset': replicate, 'n_train': n, 'family': family, 'context': x,
                            **{f'F{j}_exact': str(pred[x][j]) for j in range(3)},
                            **{f'F{j}': float(pred[x][j]) for j in range(3)}})
                    for j in range(3):
                        for c in COSTS:
                            query_values[(n, family, j, c)].append(float(cost(pred, j, c) - cost(targets, j, c)))
            if (replicate + 1) % 100 == 0:
                print(f'datasets completed: {replicate + 1}/{REPLICATES}', flush=True)
    query_summary = []
    for (n, family, j, c), values in sorted(query_values.items()):
        mean, se = statistics.mean(values), statistics.stdev(values) / math.sqrt(REPLICATES)
        query_summary.append({'n_train': n, 'family': family, 'threshold': j, 'cross_cost': float(c),
                              'mean_regret': mean, 'mc_ci_low': mean - 1.96 * se, 'mc_ci_high': mean + 1.96 * se})
    return result_rows, prediction_rows, count_rows, sample_rows, query_summary


def summarize(rows):
    summary, differences = [], []
    lookup = {(r['dataset'], r['n_train'], r['family']): r for r in rows}
    for n in SIZES:
        for family in ('universal', 'symmetric'):
            item = {'n_train': n, 'family': family, 'datasets': REPLICATES}
            for metric in ('rps', 'primary_cost', 'primary_regret', 'latent_mean_mse'):
                values = [lookup[i, n, family][metric] for i in range(REPLICATES)]
                mean, se = statistics.mean(values), statistics.stdev(values) / math.sqrt(REPLICATES)
                item.update({f'mean_{metric}': mean, f'{metric}_ci_low': mean - 1.96 * se,
                             f'{metric}_ci_high': mean + 1.96 * se})
            summary.append(item)
        for metric in ('rps', 'primary_cost', 'latent_mean_mse'):
            values = [lookup[i, n, 'symmetric'][metric] - lookup[i, n, 'universal'][metric] for i in range(REPLICATES)]
            mean, se = statistics.mean(values), statistics.stdev(values) / math.sqrt(REPLICATES)
            differences.append({'n_train': n, 'contrast': 'symmetric minus universal', 'metric': metric,
                                'mean_difference': mean, 'mc_ci_low': mean - 1.96 * se, 'mc_ci_high': mean + 1.96 * se})
    return summary, differences


def main():
    started = time.perf_counter()
    print(f'E-210 r2 seed={SEED} start={datetime.now(timezone.utc).isoformat()}', flush=True)
    pop_rows, exact = population()
    result, predictions, counts, samples, query_summary = monte_carlo()
    summary, differences = summarize(result)
    for name, rows in [('population.csv', pop_rows), ('finite_results.csv', result), ('predictions.csv', predictions),
                       ('training_counts.csv', counts), ('samples.csv', samples), ('query_summary.csv', query_summary),
                       ('finite_summary.csv', summary), ('paired_differences.csv', differences)]:
        write_csv(name, rows)
    checks = {'status': 'passed', 'exact_fraction_coordinate_equalities': REPLICATES * len(SIZES) * 2 * 2,
              'posterior_direct_max_difference': 0, 'symmetric_posterior_direct_max_difference': 0,
              'population_equal_mean_and_source_and_entropy': True, 'cdf_inversion': True,
              'primary_population_regret_3_over_40': True, 'loss_span_ranks_verified': True,
              'tie_rule': 'Fraction comparison: post iff success probability > 1-cross_cost',
              'empty_context_prior': 'Dirichlet(1,1,1,1) and matched threshold/shape pseudocounts',
              'no_distillation_or_independent_algorithm_claim': True}
    for name, content in [('population.json', exact), ('checks.json', checks)]:
        (ROOT / name).write_text(json.dumps(content, indent=2), encoding='utf-8')
    metadata = {'experiment': 'E-210', 'revision': 'r2', 'seed': SEED, 'independent_datasets': REPLICATES,
        'nested_training_sizes': SIZES, 'generated_rows': REPLICATES * max(SIZES),
        'hidden_support': [0, 1, 2, 3], 'target_probabilities': [[float(p) for p in law] for law in LAW],
        'runtime_seconds': time.perf_counter() - started, 'max_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        'cpu_affinity': sorted(os.sched_getaffinity(0)), 'memory_cap_bytes': resource.getrlimit(resource.RLIMIT_AS)[0],
        'python': platform.python_version(), 'platform': platform.platform(), 'executed_utc': datetime.now(timezone.utc).isoformat(),
        'code_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'protocol_sha256': hashlib.sha256((ROOT / 'protocol.md').read_bytes()).hexdigest()}
    (ROOT / 'run_metadata.json').write_text(json.dumps(metadata, indent=2), encoding='utf-8')
    print(json.dumps(metadata, indent=2), flush=True)
    print('Completed: all prespecified checks passed. Simulation only.', flush=True)


if __name__ == '__main__':
    main()
