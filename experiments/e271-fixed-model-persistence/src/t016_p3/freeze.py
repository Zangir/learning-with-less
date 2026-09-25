"""Freeze exact source, runtime and executable bytes before later outcomes."""
import shutil
import subprocess
import unittest
import numpy as np
from t016_p0.integrity import check_file, verify_contract, verify_packet
from t016_p1.specification import P0_SHA
from t016_p3.common import *
from t016_p3.fixed_inference import fixed_identity


def main():
    if (OUT / 'execution-freeze.json').exists() or any((OUT / d).exists() for d in DATES):
        raise FileExistsError('A freeze or outcome directory already exists; preserve it')
    stage('preflight', 'No-fit fixtures, exact accepted-object and complete source bindings')
    suite = unittest.TestSuite()
    for folder in ('t016_p0', 't016_p1', 't016_p3'):
        suite.addTests(unittest.defaultTestLoader.discover(str(WORK / folder), 'test*.py', top_level_dir=str(WORK)))
    with (OUT / 'fixture-results.log').open('w', encoding='utf-8') as stream:
        result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    dump(OUT / 'fixture-results.json', {'utc': now(), 'tests': result.testsRun,
        'passed': result.wasSuccessful(), 'failures': len(result.failures), 'errors': len(result.errors),
        'later_source_rows_parsed': 0, 'new_fits': 0})
    assert result.wasSuccessful()
    author = verify_json_packet(FROZEN, FROZEN_SHA)
    review = verify_packet(REVIEW, REVIEW_SHA)
    runtime = read(FROZEN / 'runtime-identity.json')
    for record in runtime['library_files']:
        check_file(record['path'], record['sha256'])
    check_file(runtime['executable'], runtime['executable_sha256'])
    shutil.copyfile(FROZEN / 'runtime-identity.json', OUT / 'runtime-identity.json')
    index = read(INDEX)
    members = [{k: entry[k] for k in ('date', 'contract_file', 'contract_sha256')}
               for entry in index['contracts'] if entry['asset'] == 'BTC' and entry['date'] in DATES]
    members.sort(key=lambda entry: entry['date'])
    assert [entry['date'] for entry in members] == DATES
    bindings = []
    for member in members:
        contract, checked = verify_contract(Path(member['contract_file']), member['contract_sha256'], A)
        assert contract['date'] == member['date'] and contract['asset'] == 'BTC'
        assert contract['continuity']['max_age_ns'] == 1_500_000_000
        assert contract['continuity']['max_gap_ns'] == 2_000_000_000
        bindings.extend(checked)
    admission = OUT / 'source-admission.json'
    assert admission.exists()
    upstream = [check_file(record['path'], record['sha256_observed'])
                for record in read(admission)['observed_metadata_files'].values()]
    identity = fixed_identity(FROZEN)
    with np.load(FROZEN/'prepared-cohort.npz', allow_pickle=False) as previous:
        july = previous['dates'] == '2025-07-01'
        previous_block_end = int(previous['decision_ns'][july].max())+10_000_000_000
    protocol = {'operation': 'D039:T016:fixed-later-period-evaluation', 'experiment': 'E261',
        'frozen_utc': now(), 'seed': SEED, 'dates': DATES, 'asset': 'BTC', 'contracts': members,
        'restriction_utc': '[00:00:30,24:00:00)', 'complete_file_bindings': bindings + upstream,
        'accepted_R029_manifest': FROZEN_SHA, 'accepted_RV027_manifest': REVIEW_SHA,
        'inherited_P0_protocol_sha256': P0_SHA,
        'inherited_P1_protocol_sha256': '9017958555471c87c1c572233682506d1c69a03353bb9ad6b514b18827b31702',
        'objects_and_references': identity,
        'previous_observed_block_max_dependency_ns': previous_block_end,
        'opportunities': 'Unchanged P0 engine; recorded-only slots/cooldown, minute-frozen60cut levels,61past feature cuts',
        'labels': 'Unchanged P1 F/A/N first hit over10future cuts; require every future cut same segment and fresh BBO even after early hit; censor otherwise',
        'features': {'C': 446, 'P': 453, 'R': 1910, 'auxiliary_input': 440,
            'P_definition': 'X446 plus auxiliary3 common-coordinate predictions; no clipping',
            'mapping': 'Exact inherited P1 views and original frozen population scalers'},
        'eligibility': 'Exact common recorded events with complete history/label and full dependency interval within UTC month;130s separation from earlier observed block',
        'class_order': ['F', 'A', 'N'], 'loss': '0.5*sum((probability-onehot(label))**2)',
        'aggregation': {'primary': 'Equal arithmetic weight for each of exactly four daily means',
            'sensitivity': 'Pooled-event mean across the same four dates',
            'pairs': ['C-P', 'C-R', 'P-R'], 'pair_sign': 'Positive favors second arm',
            'no_inference': 'No CI, p-value, retirement or independent-replicate claim'},
        'failure_policy': 'Keep all four date slots. Contract/consumer/inference failure unavailable with exact reason and traceback; no replacement/retry/configuration change. Missing date or family support withholds complete four-day aggregation.',
        'examples': 'First chronological recorded past-eligible event in each family/date, chosen before labels; disclose final support including censoring',
        'auxiliary_diagnostics': 'All deduplicated past-eligible decision cuts before future filtering; seven target RMSE/MAE vs frozen Jan-Mar target mean; count first4<0,abs(imbalance)>1,distances<0 without clipping',
        'covariate_diagnostics': 'Per family/date/arm: fraction of frozen-scaled coordinates abs>3 and>5; maxabs; input-age quantiles and support counts. No outcome-dependent subgrouping.',
        'source_scope': 'Four dates previously retained/inspected for source/Q17; not pristine. RV013 admits Jan-JulQ18 only. Own normalized-input/consumer audit; no new raw authentication. Original December/January2026Q17 failure remains separate.',
        'budget': {'fits': 0, 'training_seconds': 0, 'logical_cpus': [16,17], 'memory_bytes': 8*1024**3},
        'fit_policy': 'Guard all estimator fit/fit_transform/partial_fit plus binning and PopulationScaler.from_training; forbid reselection/refit/new scaler/calibrator',
        'prior_results': 'May-Jul remain separately reported; never pooled with these later dates'}
    dump(OUT / 'extension-protocol.json', protocol)
    assert not subprocess.check_output(['git','status','--porcelain'], cwd=WORK, text=True).strip()
    head = subprocess.check_output(['git','rev-parse','HEAD'], cwd=WORK, text=True).strip()
    code = []
    for folder in ('t016_p0', 't016_p1', 't016_p2', 't016_p3'):
        for path in sorted((WORK / folder).glob('*.py')):
            rel = str(path.relative_to(WORK)).replace('\\','/')
            committed = subprocess.check_output(['git','show',head+':'+rel], cwd=WORK)
            assert committed == path.read_bytes(), rel
            target = OUT / 'code' / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
            code.append({'path': rel, 'sha256': sha(path)})
    files = ['extension-protocol.json','runtime-identity.json','source-admission.json','source-admission.md',
             'bounded_job.py','run_p3-evaluation_job.py','run_p3-evaluation.sh']
    freeze = {'frozen_utc': now(), 'operation': protocol['operation'], 'base_commit': BASE,
        'execution_commit': head, 'code': code, 'files': [{'path': name, 'sha256': sha(OUT/name)} for name in files],
        'new_strategy_outcomes_or_predictions_before_freeze': 0, 'new_fits_before_freeze': 0,
        'accepted_packet_members_checked': len(author), 'review_members_checked': len(review),
        'runtime_library_files_checked': len(runtime['library_files'])}
    dump(OUT / 'input-integrity.json', {'utc': now(), 'bindings': bindings + upstream,
        'accepted_author_manifest': FROZEN_SHA, 'review_manifest': REVIEW_SHA, 'all_passed': True})
    dump(OUT / 'execution-freeze.json', freeze)
    (OUT / 'execution-freeze.sha256').write_text(sha(OUT/'execution-freeze.json')+'\n', encoding='utf-8')
    stage('freeze-complete', 'Four dates and executable bound before any new event extraction or prediction')


if __name__ == '__main__':
    main()
