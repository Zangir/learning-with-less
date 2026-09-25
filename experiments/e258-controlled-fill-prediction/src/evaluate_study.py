"""Fit the fixed candidates only after complete native validity, then score all arms."""
from datetime import datetime,timezone
from hashlib import sha256
from itertools import product
from pathlib import Path
import csv
import json
import time
import numpy as np
from models import fit_models,predict_models,reconstruction_predictions,MODEL_NAMES
from exact_reference import law_probs,flow_probs,survival,bayes,analytic_references,likelihood_certificate

ROOT=(Path(__file__).resolve().parents[1] / 'runtime')
COSTS=[.2,.4,.55,.7,.85]
REF_NAMES=['exact_coarse_current','exact_coarse_source','exact_rich','context_only','exact_unconditional']
ALL_NAMES=list(MODEL_NAMES)+REF_NAMES
np.random.seed(20260919)


def save(name,value):
    (ROOT/name).write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8')


def predictions(bundle,feature,h,condition):
    out=predict_models(bundle,feature,h)
    c,z=feature['C'],feature['Z']
    out.update(exact_coarse_current=bayes(c,z,condition),exact_coarse_source=bayes(c,z,bundle['source_condition']),
        exact_rich=survival(h,z),context_only=bayes(c,z,'zero'),exact_unconditional=.55)
    assert all(np.isfinite(p) and 0<=p<=1 for p in out.values())
    assert out['distribution_y']==out['direct_compiled_y']
    assert out['distribution_h']==out['direct_soft_h']
    return out


def loss(y,p,c):
    action=p>c
    return c*action*(1-y)+(1-c)*(1-action)*y


def scalar_scores(y,p,weights=None):
    average=lambda values:float(np.average(values,weights=weights))
    clipped=np.clip(p,1e-9,1-1e-9)
    return dict(brier=average((p-y)**2),log_loss=average(-y*np.log(clipped)-(1-y)*np.log1p(-clipped)),
                costs={str(c):average(loss(y,p,c)) for c in COSTS})


def verify_fit(bundle,training):
    checks=[]
    def check(name,actual,expected,tolerance=1e-10):
        error=float(np.max(np.abs(np.asarray(actual)-np.asarray(expected))))
        checks.append(dict(name=name,max_abs_error=error,tolerance=tolerance,passed=error<=tolerance))
        assert error<=tolerance,(name,error,tolerance)
    h_counts=np.zeros((2,3));success=np.zeros((2,2));total=np.zeros((2,2))
    for r in training:
        c,z=r['features']['C'],r['features']['Z']
        h_counts[c,r['H']]+=1;success[c,z]+=r['Y'];total[c,z]+=1
    check('direct_beta',bundle['direct_y'],(success+1)/(total+2))
    check('H_posterior',bundle['queue_auxiliary_h']['q_by_c'],(h_counts+.5)/(h_counts.sum(axis=1,keepdims=True)+1.5))
    g=np.array([[survival(h,z) for h in range(3)] for z in range(2)])
    for c in range(2):
        q=np.array(bundle['distribution_y']['q_by_c'][c]);p=g@q
        check(f'posterior_sum_C{c}',q.sum(),1)
        assert np.min(q)>=-1e-12
        gradient=-(g.T@((success[c]+1)/p-(total[c]-success[c]+1)/(1-p)))
        directions=np.eye(3)-q
        worst=float(np.min(directions@gradient))
        checks.append(dict(name=f'convex_optimality_C{c}',minimum_directional_derivative=worst,tolerance=1e-6,passed=worst>=-1e-6))
        assert worst>=-1e-6
        certificate=likelihood_certificate(q,success[c],total[c])
        assert certificate['kkt_pass']
        checks.append(dict(name=f'independent_likelihood_certificate_C{c}',**certificate))
    for c,z,k,q,side in product(range(2),range(2),[2,4],[2,3],['bid','ask']):
        features=dict(C=c,Z=z,K=k,Q=q,side=side)
        out=[predict_models(bundle,features,h) for h in range(3)]
        for name in MODEL_NAMES:
            if name!='current_rich_y':check(f'no_hidden_H_{c}_{z}_{k}_{q}_{side}_{name}',[v[name] for v in out],[out[0][name]]*3)
        check(f'compiled_Y_{c}_{z}_{k}_{q}_{side}',out[0]['distribution_y'],out[0]['direct_compiled_y'],0)
        check(f'direct_soft_H_{c}_{z}_{k}_{q}_{side}',out[0]['distribution_h'],out[0]['direct_soft_h'],0)
        check(f'independent_Y_projection_{c}_{z}_{k}_{q}_{side}',out[0]['distribution_y'],g[z]@bundle['distribution_y']['q_by_c'][c])
        check(f'independent_H_projection_{c}_{z}_{k}_{q}_{side}',out[0]['distribution_h'],g[z]@bundle['queue_auxiliary_h']['q_by_c'][c])
    return checks


def exact_metrics(bundle,condition):
    ys=[];weights=[];outputs={name:[] for name in ALL_NAMES}
    for c,z,k,q,side,h,j in product(range(2),range(2),[2,4],[2,3],['bid','ask'],range(3),range(4)):
        feature=dict(C=c,Z=z,K=k,Q=q,side=side)
        volume=[q-1,q,q+k,q+2*k][j]
        ys.append(int(volume>=h*k+q))
        weights.append(law_probs(condition,c)[h]*flow_probs(z)[j]/32)
        for name,p in predictions(bundle,feature,h,condition).items():outputs[name].append(p)
    y=np.array(ys);w=np.array(weights)
    assert abs(w.sum()-1)<1e-12
    metrics={name:scalar_scores(y,np.array(p),w) for name,p in outputs.items()}
    bayes_risk=metrics['exact_coarse_current']['brier']
    for name in metrics:
        if name not in ('current_rich_y','exact_rich'):
            extra=float(np.dot(w,(np.array(outputs[name])-np.array(outputs['exact_coarse_current']))**2))
            assert abs(metrics[name]['brier']-bayes_risk-extra)<1e-12
            metrics[name]['coarse_estimation_excess']=extra
    return metrics


def main():
    started=time.perf_counter()
    protocol=json.loads((ROOT/'protocol.json').read_text())
    validation=json.loads((ROOT/'study-validation.json').read_text())
    assert validation.get('valid') is True and validation['completed_captures']==3212, 'Native validity gate not satisfied.'
    assert sha256((ROOT/'validated_rows.jsonl').read_bytes()).hexdigest()==validation['validated_rows_sha256']
    assert validation['validated_row_count']==3200
    assert validation['exact_reference']['survival']==[[survival(h,z) for h in range(3)] for z in range(2)]
    for cell in validation['exact_reference']['cells']:
        assert cell['probability']==bayes(cell['C'],cell['Z'],cell['condition'])
    for name,value in json.loads((ROOT/'freeze.json').read_text())['sha256'].items():
        assert sha256((ROOT/name).read_bytes()).hexdigest()==value,name
    rows=[json.loads(line) for line in (ROOT/'validated_rows.jsonl').read_text().splitlines()]
    rows=[r for r in rows if r['metadata']['role'] in ('train','selection','test')]
    assert len(rows)==2816
    assert len({r['metadata']['group_id'] for r in rows})==len(rows)
    assert not (ROOT/'fit-invocations.jsonl').exists(),'No unrecorded repeat of learned fits.'
    fit_count=0;bundles={};fit_checks=[]
    def log_fit(record):
        nonlocal fit_count
        fit_count+=1
        assert fit_count<=24
        record.update(invocation=fit_count)
        with (ROOT/'fit-invocations.jsonl').open('a',encoding='utf-8') as stream:stream.write(json.dumps(record)+'\n')
    for condition in ['zero','informative']:
        training=[dict(features=r['features'],**r['labels']) for r in rows
                  if r['metadata']['condition']==condition and r['metadata']['role']=='train']
        assert len(training)==512
        for n in [128,512]:
            bundle=fit_models(training,n,condition,log_fit)
            key=f'{condition}-{n}'
            bundles[key]=bundle
            save(f'model-{key}.json',bundle)
            checks=verify_fit(bundle,training[:n])
            fit_checks.append(dict(bundle=key,checks=checks))
            print(f'Fitted and checked {key}: cumulative {fit_count}/24 learned invocations',flush=True)
    assert fit_count==24
    save('model-validation.json',dict(passed=True,bundles=fit_checks,checked_invocations=fit_count))
    pools={};sample_records=[]
    with (ROOT/'all-model-outputs.jsonl').open('x',encoding='utf-8') as stream:
        for row in rows:
            meta,features,labels=row['metadata'],row['features'],row['labels']
            source='informative' if meta['condition']=='shift' else meta['condition']
            for n in [128,512]:
                bundle=bundles[f'{source}-{n}']
                probs=predictions(bundle,features,labels['H'],meta['condition'])
                recon=reconstruction_predictions(bundle,features)
                record=dict(metadata=meta,training_size=n,source_condition=source,features=features,labels=labels,
                    in_fit=meta['role']=='train' and meta['row_index']<n,predictions=probs,reconstruction=recon)
                stream.write(json.dumps(record)+'\n')
                if meta['role'] in ['selection','test']:
                    pools.setdefault((meta['condition'],meta['role'],n),[]).append(record)
                if meta['row_index']<2 and meta['role']=='test':sample_records.append(record)
    summary=[];calibration=[];contrasts=[];exact=[];decision_baselines=[]
    comparison_pairs=[('distribution_y','direct_y'),('point_y','distribution_y'),('distribution_h','direct_y'),
        ('point_mean_h','distribution_h'),('distribution_h','direct_soft_h'),('distribution_y','direct_compiled_y'),
        ('current_rich_y','distribution_y'),('distribution_y','unconditional_y'),('distribution_h','context_only')]
    for pool_index,((condition,role,n),records) in enumerate(sorted(pools.items())):
        y=np.array([r['labels']['Y'] for r in records]);h=np.array([r['labels']['H'] for r in records])
        probability={name:np.array([r['predictions'][name] for r in records]) for name in ALL_NAMES}
        decision_baselines.append(dict(condition=condition,role=role,training_size=n,episodes=len(records),
            always_act={str(c):float(c*(1-y).mean()) for c in COSTS},
            always_abstain={str(c):float((1-c)*y.mean()) for c in COSTS}))
        indices=None
        if role=='test':
            rng=np.random.default_rng(protocol['evaluation']['bootstrap_seed']+pool_index)
            indices=rng.integers(0,len(records),size=(1000,len(records)))
        for name,p in probability.items():
            metrics=scalar_scores(y,p)
            result=dict(condition=condition,role=role,training_size=n,model=name,episodes=len(records),**metrics)
            if indices is not None:
                result['brier_ci95']=np.quantile(((p-y)**2)[indices].mean(axis=1),[.025,.975]).tolist()
            if name in records[0]['reconstruction']:
                predicted=np.array([r['reconstruction'][name]['probabilities'] for r in records])
                mean=predicted@np.array([0,1,2])
                result['rank_mse']=float(np.mean((mean-h)**2))
                result['categorical_brier']=float(np.mean(np.sum((predicted-np.eye(3)[h])**2,axis=1)))
            bin_number=np.minimum((p*5).astype(int),4)
            ece=0
            for b in range(5):
                keep=bin_number==b
                if not keep.any():continue
                avg=float(p[keep].mean());observed=float(y[keep].mean())
                ece+=keep.mean()*abs(avg-observed)
                calibration.append(dict(condition=condition,role=role,training_size=n,model=name,bin=b,
                    n=int(keep.sum()),mean_probability=avg,observed_full_fill=observed))
            result['ece5']=float(ece)
            result['cells']=[dict(C=c,Z=z,n=int(sum(r['features']['C']==c and r['features']['Z']==z for r in records)),
                mean_probability=float(np.mean([r['predictions'][name] for r in records if r['features']['C']==c and r['features']['Z']==z])),
                observed_full_fill=float(np.mean([r['labels']['Y'] for r in records if r['features']['C']==c and r['features']['Z']==z])))
                for c,z in product(range(2),range(2))]
            if name in ('current_rich_y','exact_rich'):
                result['rich_cells']=[dict(H=hidden,Z=z,n=int(((h==hidden)&np.array([r['features']['Z']==z for r in records])).sum()),
                    mean_probability=float(np.mean([r['predictions'][name] for r in records if r['labels']['H']==hidden and r['features']['Z']==z])),
                    observed_full_fill=float(np.mean([r['labels']['Y'] for r in records if r['labels']['H']==hidden and r['features']['Z']==z])))
                    for hidden,z in product(range(3),range(2))]
            summary.append(result)
        if role=='test':
            for left,right in comparison_pairs:
                delta=(probability[left]-y)**2-(probability[right]-y)**2
                item=dict(condition=condition,training_size=n,left=left,right=right,metric='Brier',difference=float(delta.mean()),
                          ci95=np.quantile(delta[indices].mean(axis=1),[.025,.975]).tolist(),decisions=[])
                for c in COSTS:
                    d=loss(y,probability[left],c)-loss(y,probability[right],c)
                    item['decisions'].append(dict(cost=c,difference=float(d.mean()),
                        ci95=np.quantile(d[indices].mean(axis=1),[.025,.975]).tolist()))
                contrasts.append(item)
            source='informative' if condition=='shift' else condition
            exact.append(dict(condition=condition,training_size=n,metrics=exact_metrics(bundles[f'{source}-{n}'],condition)))
    save('metrics.json',summary);save('calibration.json',calibration);save('paired-contrasts.json',contrasts)
    save('decision-baselines.json',decision_baselines)
    save('exact-population-metrics.json',exact)
    save('analytic-references.json',{c:analytic_references(c) for c in ['zero','informative','shift']})
    save('verified-stage-samples.json',sample_records)
    columns=['condition','role','training_size','model','episodes','brier','log_loss','ece5','rank_mse','categorical_brier']
    with (ROOT/'metrics.csv').open('w',newline='',encoding='utf-8') as stream:
        writer=csv.DictWriter(stream,fieldnames=columns,extrasaction='ignore');writer.writeheader();writer.writerows(summary)
    save('study-summary.json',dict(completed=True,learned_fit_invocations=fit_count,bundles=list(bundles),
        outcomes=2816,prediction_rows=5632,probability_outputs_per_row=len(ALL_NAMES),test_pools=3,
        selection_used_to_choose=False,test_used_to_tune=False,training_sizes_nested=True,
        learned_downstream=False,zero_fit_identity_controls=['distribution_y=direct_compiled_y','distribution_h=direct_soft_h'],
        supervision='Y-only main comparison; H-supervised diagnostic separate; rich benchmark current H only',
        bootstrap_replicates=1000,bootstrap_unit='independent episode',intervals_conditional_on_training=True,
        seconds=time.perf_counter()-started,finished_at=datetime.now(timezone.utc).isoformat(),
        validated_rows_sha256=sha256((ROOT/'validated_rows.jsonl').read_bytes()).hexdigest(),
        predictions_sha256=sha256((ROOT/'all-model-outputs.jsonl').read_bytes()).hexdigest()))
    print(json.dumps(dict(completed=True,learned_fit_invocations=fit_count,seconds=time.perf_counter()-started)))


if __name__=='__main__':main()
