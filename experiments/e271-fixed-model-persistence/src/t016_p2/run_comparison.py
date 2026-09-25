"""Execute exactly the frozen 3+36 plan and retain every candidate output."""
import gc
import json
import random
import time
import traceback
import numpy as np
from threadpoolctl import threadpool_limits, threadpool_info
from t016_p0.integrity import check_file, verify_contract
from t016_p1.features import inverse_target_scaling, TARGET_NAMES
from t016_p2.common import *
from t016_p2.execution import FitLedger
from t016_p2.models import PopulationScaler, make_auxiliary, make_candidate
from t016_p2.metrics import (CLASS_ORDER, align_probabilities, half_brier, score_by_day,
    reference_predictions, select_candidate, assert_chronological_fold)
from t016_p2.embeddings import check_embedding


def frozen_gate():
    freeze = read(OUT / 'execution-freeze.json')
    for entry in freeze['code']:
        assert sha(WORK / entry['path']) == entry['sha256'] == sha(OUT / 'code' / entry['path'])
    for entry in freeze['files']:
        assert sha(OUT / entry['path']) == entry['sha256']
    runtime = read(OUT / 'runtime-identity.json')
    for entry in runtime['library_files']:
        assert sha(Path(entry['path'])) == entry['sha256']
    assert sha(Path(runtime['executable'])) == runtime['executable_sha256']
    verify_json_packet(SOURCE, SOURCE_SHA)
    assert freeze['predictive_fits_before_freeze'] == 0
    return read(OUT / 'comparison-config.json')


def save_scaler(path, scaler):
    np.savez_compressed(path, means=scaler.means, scales=scaler.scales)


def auxiliary_stage(data, config, ledger):
    indices = data['auxiliary_event_indices']
    X, target, dates = data['X'][indices, :440], data['targets'][indices], data['dates'][indices]
    predictions = np.full_like(target, np.nan)
    folds = np.full(len(indices), -1, dtype=np.int8)
    results = []
    for number, plan in enumerate(config['fit_plan'][:3]):
        fold = plan['fold']
        assert_chronological_fold(fold['train'], fold['predict'])
        train, predict = np.isin(dates, fold['train']), np.isin(dates, fold['predict'])
        assert train.any() and predict.any() and not np.any(train & predict)
        gap = int(data['auxiliary_dependency_min_ns'][predict].min() - data['auxiliary_dependency_max_ns'][train].max())
        assert gap >= 130_000_000_000
        x_scaler = PopulationScaler.from_training(X[train])
        y_scaler = PopulationScaler.from_training(target[train])
        estimator, fit = ledger.fit_once(plan, make_auxiliary(plan['seed']),
            x_scaler.transform(X[train]), y_scaler.transform(target[train]))
        folder = OUT / 'models' / plan['fit_id']
        save_scaler(folder / 'input-scaler.npz', x_scaler)
        save_scaler(folder / 'target-scaler.npz', y_scaler)
        detail = {'fit': fit, 'status': fit['status'], 'fold': fold, 'train_rows': int(train.sum()), 'predict_rows': int(predict.sum()),
            'train_future_censored_rows': int((data['y'][indices][train] < 0).sum()),
            'predict_future_censored_rows': int((data['y'][indices][predict] < 0).sum()),
            'actual_dependency_gap_ns': gap, 'target_coordinates': TARGET_NAMES, 'reconstruction': {}}
        if estimator is not None:
            try:
                standardized = estimator.predict(x_scaler.transform(X[predict]))
                common = inverse_target_scaling(standardized, y_scaler.means, y_scaler.scales)
                assert np.array_equal(common, y_scaler.inverse(standardized)) and np.isfinite(common).all()
                np.savez_compressed(folder / 'predictions.npz', auxiliary_indices=np.flatnonzero(predict),
                    standardized=standardized, common_coordinates=common, true_target=target[predict],
                    dates=dates[predict], train_indices=np.flatnonzero(train))
                for date in fold['predict']:
                    local = dates[predict] == date
                    errors = common[local] - target[predict][local]
                    mean_errors = y_scaler.means - target[predict][local]
                    detail['reconstruction'][date] = {'n': int(local.sum()),
                        'rmse': np.sqrt(np.square(errors).mean(axis=0)).tolist(),
                        'mae': np.abs(errors).mean(axis=0).tolist(),
                        'training_mean_rmse': np.sqrt(np.square(mean_errors).mean(axis=0)).tolist(),
                        'training_mean_mae': np.abs(mean_errors).mean(axis=0).tolist(),
                        'interpretation': 'Current-depth target reconstruction; not downstream prediction or strategy utility'}
                if fit['status'] == 'evaluable':
                    predictions[predict] = common
                    folds[predict] = number
            except Exception:
                detail['prediction_failure'] = traceback.format_exc()
                detail['status'] = 'not_evaluable'
                predictions[predict] = np.nan
                folds[predict] = -1
        dump(folder / 'auxiliary-result.json', detail)
        results.append(detail)
        del estimator
        gc.collect()
    np.savez_compressed(OUT / 'auxiliary-predictions.npz', predictions=predictions,
                        fold=folds, auxiliary_event_indices=indices, dates=dates)
    dump(OUT / 'auxiliary-results.json', results)
    return predictions[data['event_to_auxiliary_index']], results


def downstream_stage(data, predicted, config, ledger):
    proposal = config['accepted_proposal']
    results, selections, references, embeddings = [], {}, {}, []
    selected_arrays = {}
    full = {'C': data['X'], 'P': np.column_stack((data['X'], predicted)),
            'R': np.column_stack((data['X'], data['Z']))}
    for family in ('breakout', 'rebound'):
        family_mask = data['downstream_mask'] & (data['families'] == family)
        index = np.flatnonzero(family_mask)
        train = data['roles'][index] == 'downstream_train'
        selection = data['roles'][index] == 'selection'
        y, dates = data['y'][index], data['dates'][index]
        assert set(y[train]) == set(y[selection]) == {0, 1, 2}
        references[family] = {name: score_by_day(y, p, dates)
            for name, p in reference_predictions(y[train], len(y)).items()}
        scalers = {arm: PopulationScaler.from_training(values[index][train])
                   for arm, values in full.items() if np.isfinite(values[index]).all()}
        for arm in ('C', 'R'):
            assert np.array_equal(scalers['C'].means, scalers[arm].means[:446])
            assert np.array_equal(scalers['C'].scales, scalers[arm].scales[:446])
        for arm in ('C', 'P', 'R'):
            candidates, probabilities = {}, {}
            arm_id = family + '-' + arm
            if arm not in scalers:
                selections[arm_id] = {'status': 'not_evaluable', 'selected': None, 'reason': 'auxiliary predictions unavailable'}
                for plan in [p for p in config['fit_plan'][3:] if p['family'] == family and p['arm'] == arm]:
                    blocked = {'fit': {'fit_id': plan['fit_id'], 'status': 'not_attempted', 'actual_fit': False},
                        'family': family, 'arm': arm, 'candidate': plan['candidate']['id'], 'status': 'not_evaluable',
                        'selection_score': None, 'scores': None, 'failure_reason': 'auxiliary predictions unavailable'}
                    results.append(blocked)
                    dump(OUT / 'models' / plan['fit_id'] / 'result.json', blocked)
                continue
            transformed = scalers[arm].transform(full[arm][index])
            scaler_dir = OUT / 'scalers'
            scaler_dir.mkdir(exist_ok=True)
            save_scaler(scaler_dir / (arm_id + '.npz'), scalers[arm])
            for plan in [p for p in config['fit_plan'][3:] if p['family'] == family and p['arm'] == arm]:
                candidate = plan['candidate']; identifier = plan['fit_id']
                estimator, fit = ledger.fit_once(plan, make_candidate(candidate, proposal, plan['seed']),
                                                 transformed[train], y[train])
                result = {'fit': fit, 'family': family, 'arm': arm, 'candidate': candidate['id'],
                    'status': fit['status'], 'selection_score': None, 'scores': None,
                    'train_rows': int(train.sum()), 'selection_rows': int(selection.sum()),
                    'shared_row_ids_sha256': hashlib.sha256(json.dumps(data['event_ids'][index].tolist()).encode()).hexdigest()}
                folder = OUT / 'models' / identifier
                if estimator is not None:
                    try:
                        began, cpu = time.perf_counter(), time.process_time()
                        p = align_probabilities(estimator.predict_proba(transformed), estimator.classes_)
                        result['prediction_wall_seconds'] = time.perf_counter() - began
                        result['prediction_cpu_seconds'] = time.process_time() - cpu
                        np.savez_compressed(folder / 'predictions.npz', event_indices=index, probabilities=p,
                            labels=y, dates=dates, train_mask=train, selection_mask=selection, classes=np.asarray(CLASS_ORDER))
                        scored = score_by_day(y, p, dates)
                        if fit['status'] == 'evaluable':
                            result['scores'] = scored
                            result['selection_score'] = score_by_day(y[selection], p[selection], dates[selection])['equal_day_half_brier']
                            probabilities[candidate['id']] = p
                        else:
                            result['diagnostic_scores_not_valid_for_selection'] = scored
                        if arm == 'C':
                            rich = scalers['R'].transform(full['R'][index])
                            checks = {role: check_embedding(estimator, transformed[mask], rich[mask])
                                      for role, mask in [('training', train), ('April', selection)]}
                            embedding = {'fit_id': identifier, 'fit_status': fit['status'], 'checks': checks,
                                'predictive_refits': 0, 'passed': all(c['passed'] for c in checks.values())}
                            embeddings.append(embedding)
                            dump(folder / 'rich-embedding.json', embedding)
                            if not embedding['passed']:
                                result.update(status='not_evaluable', selection_score=None, scores=None,
                                              failure_reason='required_embedding_check_failed')
                    except Exception:
                        result.update(status='not_evaluable', selection_score=None, scores=None,
                                      prediction_failure=traceback.format_exc())
                candidates[candidate['id']] = result['selection_score'] if result['status'] == 'evaluable' else None
                dump(folder / 'result.json', result)
                results.append(result)
                del estimator
                gc.collect()
            selected = select_candidate(candidates, proposal['menu'])
            selections[arm_id] = {'status': 'evaluable' if selected else 'not_evaluable', 'selected': selected,
                'selection_scores': candidates, 'rule': 'Full frozen menu required; minimum April half-Brier; exact ties menu order',
                'selection_rows': int(selection.sum()), 'refit': False}
            if selected:
                selected_arrays[arm_id] = {'indices': index, 'probabilities': probabilities[selected]}
            dump(OUT / 'selection.json', selections)
    dump(OUT / 'candidate-results.json', results)
    dump(OUT / 'reference-results.json', references)
    dump(OUT / 'embedding-results.json', embeddings)
    paired = []
    for family in ('breakout', 'rebound'):
        for left, right in [('C', 'P'), ('C', 'R'), ('P', 'R')]:
            a, b = selected_arrays.get(family+'-'+left), selected_arrays.get(family+'-'+right)
            if a is None or b is None:
                paired.append({'family': family, 'pair': left+'-'+right, 'status': 'not_evaluable'})
                continue
            assert np.array_equal(a['indices'], b['indices'])
            index = a['indices']; delta = half_brier(data['y'][index], a['probabilities']) - half_brier(data['y'][index], b['probabilities'])
            days = {date: {'n': int((data['dates'][index] == date).sum()),
                'mean_difference': float(delta[data['dates'][index] == date].mean())} for date in sorted(set(data['dates'][index]))}
            paired.append({'family': family, 'pair': left+'-'+right, 'status': 'evaluable',
                'positive_favors': right, 'per_day': days, 'interpretation': 'Paired descriptive differences; no population confidence interval'})
            np.savez_compressed(OUT / f'paired-{family}-{left}-{right}.npz', event_indices=index, difference=delta)
    for name, values in selected_arrays.items():
        np.savez_compressed(OUT / ('selected-' + name + '.npz'), event_indices=values['indices'], probabilities=values['probabilities'])
    dump(OUT / 'paired-results.json', paired)
    examples = read(OUT / 'stage-examples.json')
    for example in examples:
        example['model_outputs'] = {}
        if not example['downstream_eligible']:
            example['prediction_status'] = 'Not predicted: unchanged January warmup example is outside downstream roles'
            continue
        for arm in ('C','P','R'):
            name = example['family'] + '-' + arm
            values = selected_arrays.get(name)
            if values is not None:
                row = int(np.flatnonzero(values['indices'] == example['row_index'])[0])
                example['model_outputs'][arm] = dict(zip(CLASS_ORDER, values['probabilities'][row].tolist()))
            else:
                example['model_outputs'][arm] = {'status': 'not_evaluable', 'reason': selections[name]}
        values = predicted[example['row_index']]
        example['predicted_common_auxiliary_targets'] = values.tolist() if np.isfinite(values).all() else None
        example['auxiliary_prediction_status'] = 'available' if np.isfinite(values).all() else 'not_evaluable'
    dump(OUT / 'verified-model-examples.json', examples)
    return results, selections, embeddings


def main():
    random.seed(SEED); np.random.seed(SEED)
    with threadpool_limits(limits=2):
        config = frozen_gate()
        dump(OUT / 'threadpool-runtime.json', threadpool_info())
        data = load_arrays()
        ledger = FitLedger(config['fit_plan'])
        predicted, auxiliary = auxiliary_stage(data, config, ledger)
        candidates, selections, embeddings = downstream_stage(data, predicted, config, ledger)
        stage('post-input-integrity', 'Fresh complete contract and frozen packet hashes after all attempts')
        post = []
        for member in read(SOURCE / 'cohort-protocol.json')['contracts']:
            _, checks = verify_contract(member['contract_file'], member['contract_sha256'], ARTIFACTS)
            post.extend(checks)
        before = read(OUT / 'input-integrity.json')['bindings']
        assert [(x['path'],x['sha256']) for x in before] == [(x['path'],x['sha256']) for x in post]
        verify_json_packet(SOURCE, SOURCE_SHA)
        dump(OUT / 'post-integrity.json', {'utc': now(), 'bindings': post, 'all_unchanged': True})
        complete = (len(ledger.attempted) == 39 and all(v['status']=='evaluable' for v in selections.values())
                    and all(v['status']=='evaluable' for v in auxiliary))
        summary = {'utc': now(), 'operation': config['operation'], 'status': 'complete_evaluable' if complete else 'partial_not_evaluable',
            'actual_predictive_fits': len(ledger.attempted), 'auxiliary_fits': sum(k.startswith('auxiliary') for k in ledger.attempted),
            'downstream_fits': sum(not k.startswith('auxiliary') for k in ledger.attempted), 'optional_refits': 0,
            'candidate_count': len(candidates), 'failed_candidates': [r['fit']['fit_id'] for r in candidates if r['status']!='evaluable'],
            'unattempted_fit_ids': [p['fit_id'] for p in config['fit_plan'] if p['fit_id'] not in ledger.attempted],
            'selected': selections, 'required_embedding_checks': len(embeddings),
            'all_executed_embeddings_pass': all(e['passed'] for e in embeddings),
            'cohort_rows': 4160, 'matched_downstream_rows': 3724, 'source_inputs_unchanged': True,
            'scientific_acceptance': 'pending independent review', 'no_new_market_data': True,
            'no_confidence_intervals': True, 'no_profit_or_original_goal_closure_claim': True}
        dump(OUT / 'comparison-summary.json', summary)
        stage('comparison-complete', f'{summary["status"]}; {len(ledger.attempted)} actual predictor fits, no retries/refits')


if __name__ == '__main__':
    main()
