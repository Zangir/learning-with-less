"""Consume the four frozen days with saved objects; no learning path exists."""
import gc
import hashlib
import random
import time
import traceback
import numpy as np
from threadpoolctl import threadpool_limits, threadpool_info
from t016_p0.integrity import check_file, verify_contract
from t016_p1.features import TARGET_NAMES
from t016_p2.metrics import half_brier
from t016_p3.common import *
from t016_p3.fixed_inference import FixedInference
from t016_p3.extraction import run_day


def frozen_gate():
    freeze = read(OUT / 'execution-freeze.json')
    assert sha(OUT/'execution-freeze.json') == (OUT/'execution-freeze.sha256').read_text().strip()
    for entry in freeze['code']:
        assert sha(WORK/entry['path']) == entry['sha256'] == sha(OUT/'code'/entry['path'])
    for entry in freeze['files']:
        check_file(OUT/entry['path'], entry['sha256'])
    runtime = read(OUT/'runtime-identity.json')
    for entry in runtime['library_files']:
        check_file(entry['path'], entry['sha256'])
    check_file(runtime['executable'], runtime['executable_sha256'])
    protocol = read(OUT/'extension-protocol.json')
    for entry in protocol['complete_file_bindings']:
        check_file(entry['path'], entry['sha256'])
    assert protocol['dates'] == DATES
    return protocol


def diagnostics(date, data, predicted, model):
    # A frozen ruler can measure drift without learning a new ruler.
    full = {'C':data['X'], 'P':np.column_stack((data['X'], predicted['aux_prediction'])),
            'R':np.column_stack((data['X'],data['Z']))}
    covariates = {}
    for family in FAMILIES:
        mask = data['families'] == family
        covariates[family] = {}
        for arm in ARMS:
            values = model.scalers[(family,arm)].transform(full[arm][mask])
            absolute = np.abs(values)
            covariates[family][arm] = {'recorded_rows': int(mask.sum()),
                'coordinate_fraction_abs_above3': float((absolute>3).mean()) if len(values) else None,
                'coordinate_fraction_abs_above5': float((absolute>5).mean()) if len(values) else None,
                'max_abs': float(absolute.max()) if len(values) else None}
    _, indices = np.unique(data['decision_ns'], return_index=True)
    target, estimate = data['targets'][indices], predicted['aux_prediction'][indices]
    errors = estimate-target
    baseline = model.auxiliary_target_scaler.means-target
    violations = np.column_stack((estimate[:,:4]<0, np.abs(estimate[:,4])>1, estimate[:,5:]<0))
    aux = {'population':'All deduplicated recorded past-eligible cuts before future support',
        'n':len(indices), 'target_names':TARGET_NAMES,
        'rmse': np.sqrt(np.square(errors).mean(axis=0)).tolist() if len(indices) else None,
        'mae': np.abs(errors).mean(axis=0).tolist() if len(indices) else None,
        'training_mean_rmse':np.sqrt(np.square(baseline).mean(axis=0)).tolist() if len(indices) else None,
        'training_mean_mae':np.abs(baseline).mean(axis=0).tolist() if len(indices) else None,
        'range_violation_counts':violations.sum(axis=0).tolist(),
        'range_violation_any':int(violations.any(axis=1).sum()),
        'nonfinite_predictions':int((~np.isfinite(estimate)).any(axis=1).sum()), 'clipping':False}
    with np.load(OUT/date/'cuts.npz',allow_pickle=False) as cuts:
        ages = cuts['age_ns'][cuts['valid_bbo']]/1e9
    return {'covariates':covariates, 'auxiliary':aux,
        'valid_grid_asof_age_seconds_quantiles': dict(zip(['min','q50','q90','q99','max'],
            np.quantile(ages,[0,.5,.9,.99,1]).tolist())) if len(ages) else None}


def score_date(date, data, predicted, references):
    records = []
    probabilities = {arm: predicted[arm] for arm in ARMS} | references
    for family in FAMILIES:
        mask = (data['families']==family) & data['matched']
        ids = data['event_ids'][mask]
        assert len(ids) == len(set(ids.tolist()))
        y = data['y'][mask]
        row = {'date':date, 'family':family, 'n':int(mask.sum()),
            'status':'evaluable' if len(ids) else 'unavailable',
            'classes':dict(zip(('F','A','N'),np.bincount(y,minlength=3).tolist())),
            'event_ids_sha256': hashlib.sha256('\n'.join(ids).encode()).hexdigest(),
            'scores':{}, 'paired':{}}
        losses = {}
        for name,p in probabilities.items():
            losses[name] = half_brier(y,p[mask])
            row['scores'][name] = float(losses[name].mean()) if len(ids) else None
        for first,second in (('C','P'),('C','R'),('P','R')):
            difference = losses[first]-losses[second]
            row['paired'][first+'-'+second] = float(difference.mean()) if len(ids) else None
            np.savez_compressed(OUT/date/f'paired-{family}-{first}-{second}.npz',
                event_ids=ids, labels=y, first=probabilities[first][mask],
                second=probabilities[second][mask], loss_difference=difference)
        records.append(row)
    return records


def aggregate(days):
    if [day['date'] for day in days] != DATES:
        raise ValueError('All four fixed date slots must be present in order')
    result = {}
    for family in FAMILIES:
        rows = [next((r for r in d.get('scores',[]) if r['family']==family),None) for d in days]
        available = all(r is not None and r['status']=='evaluable' for r in rows)
        result[family] = {'complete_four_dates':available, 'equal_day':None, 'pooled_event':None,
                          'paired_equal_day':None, 'paired_pooled_event':None}
        if available:
            count = sum(r['n'] for r in rows)
            result[family].update(n=count,
                equal_day={key:float(np.mean([r['scores'][key] for r in rows])) for key in rows[0]['scores']},
                pooled_event={key:float(sum(r['scores'][key]*r['n'] for r in rows)/count) for key in rows[0]['scores']},
                paired_equal_day={key:float(np.mean([r['paired'][key] for r in rows])) for key in rows[0]['paired']},
                paired_pooled_event={key:float(sum(r['paired'][key]*r['n'] for r in rows)/count) for key in rows[0]['paired']})
    return result


def main():
    random.seed(SEED); np.random.seed(SEED)
    if (OUT/'evaluation-summary.json').exists() or any((OUT/d).exists() for d in DATES):
        raise FileExistsError('Existing outcomes must be preserved; no silent rerun')
    stage('evaluation-integrity', 'Verify prospective freeze and all bound source/runtime bytes')
    protocol = frozen_gate()
    model = FixedInference(FROZEN)
    assert model.identity == protocol['objects_and_references']
    dump(OUT/'threadpool-runtime.json',threadpool_info())
    protocol_sha = sha(OUT/'extension-protocol.json')
    days = []
    previous_end = protocol['previous_observed_block_max_dependency_ns']
    for member in protocol['contracts']:
        date = member['date']; stage('day-start',date+' unchanged extraction and saved-model inference')
        start = time.perf_counter(); cpu = time.process_time()
        try:
            contract,_ = verify_contract(Path(member['contract_file']), member['contract_sha256'], A)
            data = run_day({**member,'earlier_dependency_end_ns':previous_end}, OUT/date, protocol_sha)
            extraction_seconds = time.perf_counter()-start
            events = lines(OUT/date/'events.jsonl')
            if events:
                earliest = min(e['dependency_min_ns'] for e in events)
                assert previous_end is None or earliest-previous_end>=130_000_000_000
                previous_end = max(e['dependency_max_ns'] for e in events)
            before = time.perf_counter()
            with threadpool_limits(limits=2):
                predicted = model.predict(data['X'],data['Z'],data['families'])
                references = model.reference_probabilities(data['families'])
            inference_seconds = time.perf_counter()-before
            np.savez_compressed(OUT/date/'predictions.npz',event_ids=data['event_ids'],families=data['families'],
                labels=data['y'], matched=data['matched'], decision_ns=data['decision_ns'],
                C=predicted['C'],P=predicted['P'],R=predicted['R'],
                auxiliary=predicted['aux_prediction'], auxiliary_standardized=predicted['aux_standardized'],
                **references)
            dump(OUT/date/'prediction-identity.json',{'protocol_sha256':protocol_sha,
                'objects_sha256':sha(OUT/'extension-protocol.json'), 'objects':model.identity,
                'features_sha256':sha(OUT/date/'feature-vectors.npz'),
                'predictions_sha256':sha(OUT/date/'predictions.npz'), 'class_order':['F','A','N'],
                'event_row_order':'Identical full recorded event order in features and predictions; matched flag only for scores'})
            scores = score_date(date,data,predicted,references)
            diag = diagnostics(date,data,predicted,model)
            dump(OUT/date/'diagnostics.json',diag)
            dump(OUT/date/'scores.json',scores)
            day = {'date':date,'status':'evaluable','source_contract_sha256':member['contract_sha256'],
                'extraction':data['summary'], 'scores':scores,'diagnostics':diag,
                'extraction_seconds':extraction_seconds,'inference_seconds':inference_seconds}
            del data, predicted, references
        except Exception as exc:
            (OUT/date).mkdir(exist_ok=True)
            day = {'date':date,'status':'unavailable','reason':type(exc).__name__+': '+str(exc),
                'traceback':traceback.format_exc(), 'scores':[], 'replacement':None}
            dump(OUT/date/'failure.json',day)
        day.update(total_seconds=time.perf_counter()-start,cpu_seconds=time.process_time()-cpu)
        dump(OUT/date/'day-result.json',day); days.append(day); gc.collect()
        stage('day-complete',date+' '+day['status'])
    stage('post-integrity','Recheck all frozen complete-file inputs after extraction and inference')
    checked = [check_file(entry['path'],entry['sha256']) for entry in protocol['complete_file_bindings']]
    dump(OUT/'fit-guard-ledger.json',model.guard_ledger)
    assert not model.guard_ledger['attempts']
    dump(OUT/'post-integrity.json',{'utc':now(),'bindings':checked,'all_unchanged':True})
    combined = aggregate(days)
    summary = {'operation':protocol['operation'],'experiment':'E261','finished_utc':now(),'dates':DATES,
        'protocol_sha256':protocol_sha,'days':days,'aggregate':combined,'new_fits':0,'training_seconds':0,
        'complete_four_date_evaluation':all(d['status']=='evaluable' for d in days)
            and all(row['complete_four_dates'] for row in combined.values()),
        'prior_May_July_results':'Separate accepted R029 comparison; never pooled here'}
    dump(OUT/'evaluation-summary.json',summary)
    stage('evaluation-complete','Four fixed date slots retained; zero fits; no scientific acceptance conferred')


if __name__ == '__main__':
    main()
