"""Reconcile accepted evidence and freeze runnable bytes before any predictor fit."""
import importlib.metadata
import random
import shutil
import stat
import subprocess
import sys
import unittest
import numpy as np
from t016_p0.integrity import check_file, verify_contract, verify_packet
from t016_p1.features import X_NAMES, Z_NAMES, TARGET_NAMES
from t016_p2.common import *
from t016_p2.data import load_cohort, example_snippets
from t016_p2.models import make_auxiliary, make_candidate


def main():
    random.seed(SEED); np.random.seed(SEED)
    assert not (OUT / 'execution-freeze.json').exists(), 'Preserve existing executable freeze'
    assert not (OUT / 'fit-ledger.jsonl').exists(), 'Preflight cannot follow a predictive fit'
    stage('preflight-tests', 'No-fit fixtures before preparation and all predictive fits')
    suite = unittest.defaultTestLoader.discover(str(WORK / 't016_p2'), 'test_*.py', top_level_dir=str(WORK))
    for package, pattern in [('t016_p0', 'test_engine.py'), ('t016_p1', 'test_p1.py')]:
        suite.addTests(unittest.defaultTestLoader.discover(str(WORK / package), pattern, top_level_dir=str(WORK)))
    with (OUT / 'logs/preflight-fixtures.log').open('w', encoding='utf-8') as stream:
        result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    dump(OUT / 'fixture-results.json', {'utc': now(), 'tests': result.testsRun, 'failures': len(result.failures),
        'errors': len(result.errors), 'passed': result.wasSuccessful(), 'predictive_fits': 0})
    assert result.wasSuccessful() and result.testsRun > 55
    stage('fresh-integrity', 'Full R027/RV025 packet hashes and all authoritative seven-contract bindings')
    accepted = verify_json_packet(SOURCE, SOURCE_SHA)
    review = verify_packet(REVIEW, REVIEW_SHA)
    check_file(SOURCE / 'cohort-protocol.json', PROTOCOL_SHA)
    protocol = read(SOURCE / 'cohort-protocol.json')
    bindings = []
    for member in protocol['contracts']:
        _, checks = verify_contract(member['contract_file'], member['contract_sha256'], ARTIFACTS)
        bindings.extend(checks)
    index = ARTIFACTS / 'T-008/r3/interface/full_day_startup30/q18_required_subset/dataset_index.q18.v2.3.1.json'
    index_check = check_file(index, protocol['index_sha256'])
    predecessor = read(SOURCE / 'input-integrity.json')['bindings']
    assert [(x['path'], x['sha256']) for x in bindings] == [(x['path'], x['sha256']) for x in predecessor]
    dump(OUT / 'input-integrity.json', {'utc': now(), 'source_packet_sha256': SOURCE_SHA,
        'source_packet_members': accepted, 'review_bindings': review, 'index': index_check,
        'bindings': bindings, 'entries': len(bindings), 'unique_files': len({x['path'] for x in bindings}),
        'all_match_accepted_R027': True})
    stage('rehydrate', 'Exact accepted views, populations, chronology and fixed example snippets')
    data = load_cohort()
    keys = ['X', 'Z', 'targets', 'y', 'event_ids', 'dates', 'families', 'roles', 'decision_ns',
            'matched', 'downstream_mask', 'event_to_auxiliary_index']
    arrays = {key: data[key] for key in keys}
    arrays['auxiliary_event_indices'] = data['auxiliary']['event_indices']
    for field in ('dependency_min_ns', 'dependency_max_ns'):
        arrays['auxiliary_' + field] = np.asarray([r[field] for r in data['auxiliary']['records']], dtype=np.int64)
    np.savez_compressed(OUT / 'prepared-cohort.npz', **arrays)
    dump(OUT / 'data-verification.json', data['metadata'])
    dump(OUT / 'stage-examples.json', example_snippets(data))
    with (OUT / 'event-register.jsonl').open('w', encoding='utf-8') as stream:
        for event, label, member in zip(data['events'], data['labels'], data['population']):
            record = {key: event[key] for key in ['event_id', 'family', 'decision_ns', 'source_id',
                'decision_source_ordinal', 'contract_sha256', 'feature_vector_sha256', 'Z_vector_sha256',
                'dependency_min_ns', 'dependency_max_ns']}
            record.update(date=member['date'], role=member['role'], matched_eligible=member['matched_eligible'],
                          label=label['label'], censor_reason=label['censor_reason'])
            stream.write(json.dumps(record) + '\n')
    proposal = protocol['future_comparison_proposal']
    plan = []
    for i, fold in enumerate(proposal['auxiliary_folds'], 1):
        seed = SEED + i
        plan.append({'fit_id': f'auxiliary-{i}', 'kind': 'auxiliary', 'seed': seed,
            'fold': fold, 'parameters': make_auxiliary(seed).get_params()})
    for family in ('breakout', 'rebound'):
        for arm in ('C', 'P', 'R'):
            for candidate in proposal['menu']:
                seed = SEED + len(plan) + 1
                plan.append({'fit_id': family + '-' + arm + '-' + candidate['id'], 'kind': 'downstream',
                    'family': family, 'arm': arm, 'candidate': candidate, 'seed': seed,
                    'parameters': make_candidate(candidate, proposal, seed).get_params()})
    assert len(plan) == 39 and len(set(p['seed'] for p in plan)) == 39
    config = {'operation': 'D037:T016:frozen-CPR-comparison', 'experiment': 'E259',
        'accepted_protocol_sha256': PROTOCOL_SHA, 'accepted_proposal': proposal, 'fit_plan': plan,
        'authorization': {'predictive_fits': 39, 'auxiliary': 3, 'downstream': 36, 'optional_refits': 0},
        'base_seed': SEED, 'derived_seeds': 'base_seed + one-based fit-plan index; deterministic solvers may not consume seed',
        'full_menu_failure': 'Any required candidate missing/nonfinite/nonconverged score withholds arm/family selection. Valid candidate diagnostics remain visible; never select from a reduced menu.',
        'post_selection': 'No refit, calibration, threshold optimization or model revision',
        'auxiliary_solver': 'Dense deterministic Cholesky implementation of the fixed alpha=1 multioutput ridge',
        'logistic_loss': 'Pinned sklearn lbfgs with exactly three encoded classes uses multinomial loss',
        'references': 'Onehot F/A/N, uniform, family training-only frequency, identical rows across arms',
        'metrics': {'primary': 'mean 0.5*sum_k(p_k-onehot_k)^2; equal day mean',
                    'per_class': 'unscaled marginal one-vs-rest Brier plus descriptive true-class-conditional half-Brier',
                    'paired_sign': 'Brier(first arm)-Brier(second arm); positive favors second'},
        'examples': 'Eight unchanged prior January cases are downstream-ineligible; first accepted May-hour event per family added prospectively',
        'prefix_wording': '1495 finalized-horizon records =1490 non-null +5 censored; predecessor untouched',
        'schema': {'C': X_NAMES, 'P': X_NAMES + ['predicted.' + x for x in TARGET_NAMES], 'R': X_NAMES + Z_NAMES},
        'resource_limits': {'logical_cpus': [16, 17], 'aggregate_memory_bytes': 8*1024**3, 'watchdog_seconds': 3600},
        'source_acquisition': False, 'confirmatory_inference': False}
    dump(OUT / 'comparison-config.json', config)
    versions = {name: importlib.metadata.version(name) for name in ['numpy','scipy','scikit-learn','joblib','threadpoolctl','psutil']}
    runtime = [{'path': str(path), 'sha256': sha(path)} for path in sorted(PACKAGES.rglob('*'))
               if path.is_file() and path.suffix.lower() in ('.py','.pyd','.dll')]
    dump(OUT / 'runtime-identity.json', {'python': sys.version, 'executable': sys.executable,
        'executable_sha256': sha(Path(sys.executable)), 'versions': versions, 'library_files': runtime,
        'installation_report_sha256': sha(OUT / 'dependency-install-report.json')})
    code = []
    for folder in ('t016_p0', 't016_p1', 't016_p2'):
        for path in sorted((WORK / folder).glob('*.py')):
            relative = path.relative_to(WORK)
            destination = OUT / 'code' / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, destination)
            code.append({'path': relative.as_posix(), 'sha256': sha(path)})
    commit = subprocess.check_output(['git','rev-parse','HEAD'], cwd=WORK, text=True).strip()
    assert not subprocess.check_output(['git','status','--porcelain'], cwd=WORK, text=True).strip()
    for entry in code:
        blob = subprocess.check_output(['git','show',commit+':'+entry['path']], cwd=WORK)
        assert hashlib.sha256(blob).hexdigest() == entry['sha256']
    frozen_files = ['comparison-config.json','runtime-identity.json','prepared-cohort.npz','input-integrity.json',
                    'data-verification.json','stage-examples.json','event-register.jsonl','fixture-results.json',
                    'bounded_job.py','run_preflight_job.py','run_comparison_job.py']
    freeze = {'frozen_utc': now(), 'operation': config['operation'], 'base_commit': BASE_COMMIT,
        'execution_commit': commit, 'predictive_fits_before_freeze': 0, 'code': code,
        'files': [{'path': name, 'sha256': sha(OUT/name)} for name in frozen_files],
        'accepted_packet_sha256': SOURCE_SHA, 'accepted_protocol_sha256': PROTOCOL_SHA}
    dump(OUT / 'execution-freeze.json', freeze)
    for name in frozen_files + ['execution-freeze.json']:
        (OUT / name).chmod(stat.S_IREAD)
    stage('execution-frozen', f'Exact 39-fit plan and all code/config/input bytes frozen at {commit}; zero fits so far')


if __name__ == '__main__':
    main()
