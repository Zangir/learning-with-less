"""Execute the one released day once, using only exact verified fitted objects."""
import random
import time
import traceback
import numpy as np
from threadpoolctl import threadpool_limits, threadpool_info
from t016_p0.integrity import check_file
from t016_p1.specification import P0_SHA
from t016_p1.features import X_NAMES, Z_NAMES, TARGET_NAMES
from t016_p3.fixed_inference import FixedInference
from t016_p5.common import *
from t016_p5.extraction import run_day
from t016_p5.guards import install
from t016_p5.metrics import score_family, make_joint, joint_verdict
from t016_p5.audit import run_audit

def frozen_gate():
    protocol = read(OUT/'execution-declaration.json')
    assert sha(OUT/'execution-declaration.json') == (OUT/'execution-declaration.sha256').read_text().strip()
    for entry in protocol['code']:
        assert sha(WORK/entry['path']) == sha(OUT/'code'/entry['path']) == entry['sha256']
    for entry in protocol['complete_file_bindings']:
        check_file(entry['path'],entry['sha256'])
    for entry in protocol['execution_support']:
        check_file(OUT/entry['path'],entry['sha256'])
    assert protocol['source_member']['date'] == DATE and protocol['execution_enabled']
    return protocol

def main():
    assert not (OUT/DATE).exists() and not (OUT/'evaluation.json').exists(), 'Preserve existing outcomes'
    random.seed(SEED); np.random.seed(SEED)
    started=time.monotonic()
    stage('execution-gate','Recheck frozen inputs before any extraction or object loading')
    protocol=frozen_gate()
    ledger=install()
    model=FixedInference(FROZEN)
    assert model.identity == protocol['objects_and_references']
    dump(OUT/'threadpool-runtime.json',threadpool_info())
    member=protocol['source_member']; protocol_sha=sha(OUT/'execution-declaration.json')
    stage('full-day-extraction',DATE+' unchanged source/event/feature/ten-cut consumer')
    before=time.monotonic()
    data=run_day(member,OUT/DATE,protocol_sha)
    extraction_seconds=time.monotonic()-before
    summary=data.pop('summary')
    if summary['recorded']:
        assert summary['dependency_min_ns']-member['earlier_dependency_end_ns']>=130_000_000_000
    stage('fixed-inference',str(summary['recorded'])+' recorded rows; both families, exact seven saved objects')
    before=time.monotonic()
    with threadpool_limits(limits=2):
        predicted=model.predict(data['X'],data['Z'],data['families'])
        references=model.reference_probabilities(data['families'])
    inference_seconds=time.monotonic()-before
    probabilities={arm:predicted[arm] for arm in ('C','P','R')} | references
    np.savez_compressed(OUT/DATE/'predictions.npz',event_ids=data['event_ids'],families=data['families'],
        labels=data['y'],matched=data['matched'],decision_ns=data['decision_ns'],
        auxiliary=predicted['aux_prediction'],auxiliary_standardized=predicted['aux_standardized'],**probabilities)
    families={}
    for family in ('breakout','rebound'):
        weights=model.identity['references'][family]['probabilities']['train-frequency']
        families[family], losses=score_family(data,probabilities,family,weights)
        mask=(data['families']==family)&data['matched']
        np.savez_compressed(OUT/DATE/('losses-'+family+'.npz'),event_ids=data['event_ids'][mask],
                            labels=data['y'][mask],**losses)
    examples=summary['examples']
    for example in examples:
        if not example['available']: continue
        i=data['event_ids'].tolist().index(example['event']['event_id'])
        example.update(probabilities={m:probabilities[m][i].tolist() for m in METHODS},
            X_current7_named=dict(zip(X_NAMES[420:427],data['X'][i,420:427].tolist())),
            auxiliary7_named=dict(zip(TARGET_NAMES,predicted['aux_prediction'][i].tolist())),
            observed_target7_named=dict(zip(TARGET_NAMES,data['targets'][i].tolist())),
            Z_current_first6_named=dict(zip(Z_NAMES[-24:-18],data['Z'][i,-24:-18].tolist())))
    dump(OUT/'real-column-examples.json',examples)
    estimate=predicted['aux_prediction']; _,unique=np.unique(data['decision_ns'],return_index=True)
    violations=np.column_stack((estimate[:,:4]<0,np.abs(estimate[:,4])>1,estimate[:,5:]<0))
    diagnostic={'population':'All deduplicated recorded past-eligible cuts before label support',
        'n':len(unique),'target_names':list(TARGET_NAMES),'clipping':False,
        'range_violation_counts':violations[unique].sum(axis=0).tolist(),
        'range_violation_any':int(violations[unique].any(axis=1).sum()),
        'rmse':np.sqrt(np.square(estimate[unique]-data['targets'][unique]).mean(axis=0)).tolist() if len(unique) else None}
    evaluation={'operation':protocol['operation'],'experiment':'E271','date':DATE,
        'source_id':SOURCE_ID,'protocol_sha256':protocol_sha,'families':families,
        'joint':make_joint(families['breakout']),'counts':summary['counts'],'availability':summary['availability'],
        'extraction_summary':summary,'auxiliary':diagnostic,'extraction_seconds':extraction_seconds,
        'inference_seconds':inference_seconds,'new_fits':0,'new_market_bytes':0,
        'acceptance':'Pending independent A6 result review','historical_results_rerun':False}
    dump(OUT/'evaluation-before-audit.json',evaluation)
    stage('audit','Independent source joins, integer labels, fixed inference replay and scalar loss/sign checks')
    before=time.monotonic()
    with threadpool_limits(limits=2):
        audit=run_audit(member=member,protocol=protocol,evaluation=evaluation,protocol_sha=protocol_sha,
            previous_end=member['earlier_dependency_end_ns'],p0_sha=P0_SHA,dest=OUT/DATE,
            output_path=OUT/'audit.json')
    for name,checked in audit['components'].items():
        component=evaluation['joint']['components'][name]
        component['audit']=checked
        if not checked['sign_agreement']:
            component['status']='unavailable'
            component['reason']='Audit sign disagreement; pending numerical review'
    evaluation['joint']['verdict']=joint_verdict(evaluation['joint']['components'])
    evaluation['joint']['scope']='One declared day only; own numerical audit complete; independent A6 acceptance pending'
    evaluation['audit_seconds']=time.monotonic()-before
    evaluation['elapsed_seconds']=time.monotonic()-started
    assert not ledger['solver_attempts'] and not ledger['fit_guard']['attempts']
    dump(OUT/'guard-receipt.json',ledger)
    dump(OUT/'evaluation.json',evaluation)
    dump(OUT/'resource-after-evaluation.json',resources())
    stage('evaluation-complete',evaluation['joint']['verdict']+'; all requested evidence retained')

if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        dump(OUT/'execution-checkpoint.json',{'utc':now(),'status':'unavailable_execution_checkpoint',
            'exception':repr(exc),'traceback':traceback.format_exc(),'resources':resources(),
            'no_cohort_narrowing':True,'no_replacement_date':True})
        raise
