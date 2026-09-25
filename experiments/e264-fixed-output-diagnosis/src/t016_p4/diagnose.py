"""Pure arithmetic on fixed predictions, with temporal and population identities intact."""
import csv
import hashlib
import random
import numpy as np
from t016_p0.integrity import check_file
from t016_p4.common import *
from t016_p4.data import load_all
from t016_p4.guards import install_guards
from t016_p4.metrics import profile_loss, standardize, decompose, group_row_weights, weighting_gap

def gate():
    freeze=read(OUT/'execution-freeze.json')
    assert sha(OUT/'execution-freeze.json')==(OUT/'execution-freeze.sha256').read_text().strip()
    for entry in freeze['code']:assert sha(WORK/entry['path'])==entry['sha256']==sha(OUT/'code'/entry['path'])
    for entry in freeze['files']:check_file(OUT/entry['path'],entry['sha256'])
    runtime=read(OUT/'runtime-identity.json')
    for entry in runtime['library_files']:check_file(entry['path'],entry['sha256'])
    check_file(runtime['executable'],runtime['executable_sha256'])
    contract=read(OUT/'diagnostic-contract.json')
    for entry in contract['input_bindings']:check_file(entry['path'],entry['sha256'])
    return contract

def auxiliary(values,targets,mean):
    n=len(values)
    if not n:return {'n':0,'status':'unavailable'}
    error=values-targets;baseline=mean-targets
    rmse=np.sqrt(np.square(error).mean(axis=0));base=np.sqrt(np.square(baseline).mean(axis=0))
    violation=np.column_stack((values[:,:4]<0,np.abs(values[:,4])>1,values[:,5:]<0))
    return {'n':n,'status':'available','rmse':rmse.tolist(),'mae':np.abs(error).mean(axis=0).tolist(),
        'frozen_mean_rmse':base.tolist(),'frozen_mean_mae':np.abs(baseline).mean(axis=0).tolist(),
        'rmse_ratio':[float(a/b) if b>0 else None for a,b in zip(rmse,base)],
        'range_violation_counts':violation.sum(axis=0).tolist(),'range_violation_any':int(violation.any(axis=1).sum()),
        'range_violation_rate':float(violation.any(axis=1).mean()),'nonfinite':int((~np.isfinite(values)).any(axis=1).sum())}

def write_csv(name,rows):
    with (OUT/name).open('w',encoding='utf-8',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)

def main():
    random.seed(SEED);np.random.seed(SEED)
    if (OUT/'diagnosis.json').exists():raise FileExistsError('Preserve the prior diagnostic run')
    ledger=install_guards();stage('diagnosis-start','Verify freeze; load only accepted saved prediction/label/auxiliary packets')
    contract=gate();data=load_all();scored=data['scored'];y=scored['y']
    assert set(scored['dates'])==set(DATES) and np.isin(y,[0,1,2]).all()
    losses={}
    for name in METHODS:
        p=scored['probs'][name]
        assert p.shape==(len(y),3) and np.isfinite(p).all() and ((p>=0)&(p<=1)).all()
        assert np.allclose(p.sum(axis=1),1,atol=1e-12,rtol=0)
        losses[name]=.5*np.square(p-np.eye(3)[y]).sum(axis=1)
    for name,(first,second) in CONTRASTS.items():losses[name]=losses[first]-losses[second]
    np.savez_compressed(OUT/'event-losses.npz',event_ids=scored['event_ids'],dates=scored['dates'],
        families=scored['families'],y=y,decision_ns=scored['decision_ns'],**losses)
    daily={};groups={};changes={};weighting={};daily_rows=[];group_rows=[];change_rows=[];weight_rows=[]
    for family in FAMILIES:
        fixed=contract['secondary_standardization']['weights'][family]
        assert np.array_equal(fixed,data['references'][family]['train-frequency'])
        fam=scored['families']==family;daily[family]={};groups[family]={};changes[family]={};weighting[family]={}
        for date in DATES:
            mask=fam&(scored['dates']==date);assert mask.any()
            daily[family][date]={}
            for name,loss in losses.items():
                item=profile_loss(y[mask],loss[mask]);item['standardized']=standardize(item,fixed)
                daily[family][date][name]=item
                daily_rows.append({'family':family,'date':date,'metric':name,'n':item['n'],'raw':item['total_loss'],
                    'standardized':item['standardized']['value'],**{'n_'+c:item['class_counts'][c] for c in 'FAN'},
                    **{'q_'+c:item['q'][c] for c in 'FAN'},**{'ell_'+c:item['ell'][c] for c in 'FAN'}})
        for group,dates in GROUPS.items():
            mask=fam&np.isin(scored['dates'],dates);groups[family][group]={};weighting[family][group]={}
            for endpoint in ('equal_day','pooled'):
                weights=group_row_weights(scored['dates'][mask],endpoint);groups[family][group][endpoint]={}
                for name,loss in losses.items():
                    item=profile_loss(y[mask],loss[mask],weights);item['standardized']=standardize(item,fixed)
                    groups[family][group][endpoint][name]=item
                    group_rows.append({'family':family,'group':group,'endpoint':endpoint,'metric':name,'n':item['n'],
                        'raw':item['total_loss'],'standardized_group_conditionals':item['standardized']['value'],
                        **{'q_'+c:item['q'][c] for c in 'FAN'},**{'ell_'+c:item['ell'][c] for c in 'FAN'}})
            for name in losses:
                means={d:daily[family][d][name]['total_loss'] for d in dates}
                counts={d:daily[family][d][name]['n'] for d in dates}
                item=weighting_gap(means,counts);weighting[family][group][name]=item
                for date,detail in item['per_date'].items():
                    weight_rows.append({'family':family,'group':group,'metric':name,'date':date,**detail})
        for endpoint in ('equal_day','pooled'):
            changes[family][endpoint]={}
            for name in losses:
                earlier=groups[family]['May-Jul'][endpoint][name];later=groups[family]['Aug-Nov'][endpoint][name]
                item=decompose(earlier,later);changes[family][endpoint][name]=item
                change_rows.append({'family':family,'endpoint':endpoint,'metric':name,'status':item['status'],
                    'delta':item['delta'],'mix':item['mix'],'within':item['within'],
                    **{'mix_'+c:item['mix_by_class'][c] if item['mix_by_class'] else None for c in 'FAN'},
                    **{'within_'+c:item['within_by_class'][c] if item['within_by_class'] else None for c in 'FAN'}})
    stage('auxiliary','Separate all past-eligible cuts from exact matched-family decision populations')
    pool=data['auxiliary_pool'];full_aux={};matched_aux={};auxrows=[]
    for date in DATES:
        mask=pool['dates']==date;full_aux[date]=auxiliary(pool['auxiliary'][mask],pool['targets'][mask],data['target_training_mean'])
        full_aux[date]['population']='deduplicated past-eligible cuts before censoring'
        for family in FAMILIES:
            mask=(scored['dates']==date)&(scored['families']==family)
            item=auxiliary(scored['auxiliary'][mask],scored['targets'][mask],data['target_training_mean'])
            item.update(population='exact scored family/date events',P_minus_C=daily[family][date]['P-C']['total_loss'])
            matched_aux.setdefault(family,{})[date]=item
            auxrows.append({'family':family,'date':date,'n':item['n'],'P_minus_C':item['P_minus_C'],
                'range_violation_rate':item['range_violation_rate'],**{'rmse_'+name:item['rmse'][i] for i,name in enumerate(data['target_names'])},
                **{'ratio_'+name:item['rmse_ratio'][i] for i,name in enumerate(data['target_names'])}})
    examples=[]
    for original in data['examples']:
        ex=dict(original);index=int(np.flatnonzero(scored['event_ids']==ex['event_id'])[0])
        label=int(y[index]);date=str(scored['dates'][index]);family=str(scored['families'][index])
        ex['half_brier']={name:float(losses[name][index]) for name in METHODS}
        ex['half_squared_error_by_probability_class']={name:(.5*np.square(scored['probs'][name][index]-np.eye(3)[label])).tolist() for name in METHODS}
        ex['retrospective_class_standardization_factor']=contract['secondary_standardization']['weights'][family][label]/daily[family][date]['C']['q']['FAN'[label]]
        ex['factor_scope']='Diagnostic identity using realized label/class mixture; never a model input or deployment adjustment'
        examples.append(ex)
    result={'operation':contract['operation'],'experiment':'E264','finished_utc':now(),'contract_sha256':sha(OUT/'diagnostic-contract.json'),
        'dates':DATES,'groups':GROUPS,'methods':METHODS,'contrasts':CONTRASTS,'target_names':data['target_names'],
        'scored_events':len(y),'auxiliary_cuts':len(pool['dates']),'daily':daily,'group_profiles':groups,
        'temporal_decomposition':changes,'weighting_gap':weighting,'auxiliary_full':full_aux,'auxiliary_matched':matched_aux,
        'examples':examples,'new_fits':0,'model_inference_calls':0,'solver_calls':0,'training_seconds':0}
    write_csv('daily-metrics.csv',daily_rows);write_csv('group-metrics.csv',group_rows)
    write_csv('decompositions.csv',change_rows);write_csv('weighting-contributions.csv',weight_rows);write_csv('matched-auxiliary.csv',auxrows)
    dump(OUT/'fixed-examples.json',examples)
    dump(OUT/'diagnosis.json',result)
    dump(OUT/'zero-fit-ledger.json',ledger)
    assert not ledger['forbidden_calls'] and not ledger['fit_guard']['attempts']
    checks=[check_file(entry['path'],entry['sha256']) for entry in contract['input_bindings']]
    dump(OUT/'post-integrity.json',{'utc':now(),'bindings':checks,'all_unchanged':True})
    stage('diagnosis-complete','All seven dates and fixed diagnostics retained; no fit, solver, inference or extraction')

if __name__=='__main__':main()
