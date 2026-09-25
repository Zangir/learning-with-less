"""Independent saved-output joins and arithmetic; no producer loader or metrics.

Explicit entry point only, after the prospective freeze and diagnostic execution.
The shared safety guard blocks learning, model deserialization and linear solves.
"""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import time
import traceback
import numpy as np
from t016_p4.guards import install_guards

ROOT = (Path(__file__).resolve().parents[2] / 'runtime')
OUT = ROOT/'T-016/r6-fixed-output-diagnosis'
WORK = Path(__file__).resolve().parents[1]
DATES = [f'2025-{m:02d}-01' for m in range(5,12)]
GROUPS = {'May-Jul':DATES[:3], 'Aug-Nov':DATES[3:]}
FAMILIES = ('breakout','rebound')
CLASSES = ('F','A','N')
METHODS = ('C','P','R','onehot-F','onehot-A','onehot-N','uniform','train-frequency')
CONTRASTS = {'P-C':('P','C'),'R-C':('R','C'),'R-P':('R','P'),
    'C-frequency':('C','train-frequency'),'P-frequency':('P','train-frequency'),
    'R-frequency':('R','train-frequency'),'frequency-uniform':('train-frequency','uniform')}
TARGETS = ['log1p_Qb','log1p_Qa','log1p_Nb','log1p_Na','depth_imbalance','Db_bps','Da_bps']
EXPECTED_MANIFESTS = {'R029':'9b803d7598f20f8e3e17291de769731806175ec7c4088373090834a0020b8bb0',
    'R031':'5450d4411bbfc91451b4b60b330c23da0eec5f31fabe628dcf9c26d9083b72c0'}
CHECKS, MAXIMUM, INPUTS = Counter(), {}, {}


def check(condition,message):
    if not condition:
        raise AssertionError(message)
    CHECKS['assertions'] += 1


def sha(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1<<20),b''):
            result.update(block)
    return result.hexdigest()


def bind(path,expected=None):
    path = Path(path); actual = sha(path)
    if expected is not None:
        check(actual == expected,'Input digest: '+str(path))
    INPUTS[str(path)] = actual
    return path


def read(path):
    return json.loads(bind(path).read_text(encoding='utf-8-sig'))


def lines(path):
    with bind(path).open(encoding='utf-8-sig') as stream:
        return [json.loads(line) for line in stream if line.strip()]


def npz(path,keys,current7=False):
    with np.load(bind(path),allow_pickle=False) as z:
        result = {key:z[key] for key in keys}
        if current7:
            check(z['X'].shape[1] == 446,'Saved X width')
            result['X_current7'] = z['X'][:,420:427].copy()
    return result


def close(actual,expected,context='arithmetic'):
    check(actual is not None and np.isfinite(actual) and np.isfinite(expected),context+': finite')
    error = abs(float(actual)-float(expected))
    MAXIMUM[context.split('/')[0]] = max(MAXIMUM.get(context.split('/')[0],0),error)
    check(error <= 1e-12+1e-12*abs(float(expected)),context+': residual')


def equal(actual,expected,context):
    if isinstance(expected,dict):
        check(isinstance(actual,dict) and set(actual)==set(expected),context+': fields')
        for key in expected:
            equal(actual[key],expected[key],context+'/'+str(key))
    elif isinstance(expected,(list,tuple)):
        check(isinstance(actual,(list,tuple)) and len(actual)==len(expected),context+': length')
        for a,e in zip(actual,expected):
            equal(a,e,context)
    elif isinstance(expected,(float,np.floating)):
        close(actual,expected,context)
    else:
        check(actual==expected,context+': value')


def exact(actual,expected,context):
    check(np.asarray(actual).shape==np.asarray(expected).shape and np.array_equal(actual,expected),context)


def load_inputs(contract):
    """Own direct saved-array joins, independent of the author's data loader."""
    lookup = {}
    for entry in contract['input_bindings']:
        path = bind(entry['path'],entry['sha256'])
        check(path.stat().st_size==entry['size_bytes'],'Input byte size')
        lookup[(entry['packet'],entry['relative_path'])] = path
    def path(packet,name):
        return lookup[(packet,name)]
    for packet,expected in EXPECTED_MANIFESTS.items():
        manifest_path = path(packet,'artifact-manifest.json')
        check(INPUTS[str(manifest_path)]==expected,'Accepted packet anchor')
        manifest = read(manifest_path)
        members = {r['path'].replace('\\','/'):r for r in manifest['files']}
        for entry in contract['input_bindings']:
            if entry['packet']==packet and entry['relative_path']!='artifact-manifest.json':
                member = members[entry['relative_path']]
                check(entry['sha256']==member['sha256'] and entry['size_bytes']==member['size_bytes'],'Manifest member binding')
    reference = read(path('R029','reference-results.json')); fixed = {}
    for family in FAMILIES:
        saved = reference[family]['train-frequency']['per_day']
        counts = [sum(saved[d]['class_counts'][k] for d in ('2025-02-01','2025-03-01')) for k in CLASSES]
        check(all(n>0 for n in counts),'Fixed training class support')
        fixed[family] = {f'onehot-{k}':[float(j==i) for j in range(3)] for i,k in enumerate(CLASSES)}
        fixed[family].update(uniform=[1/3]*3,**{'train-frequency':[n/sum(counts) for n in counts]})
        exact(contract['secondary_standardization']['weights'][family],fixed[family]['train-frequency'],'Frozen class weights')
    keys = ('event_ids','dates','families','y','matched','decision_ns','targets','roles','downstream_mask',
            'auxiliary_event_indices','event_to_auxiliary_index')
    old = npz(path('R029','prepared-cohort.npz'),keys,True)
    register = lines(path('R029','event-register.jsonl'))
    for field,key in [('event_ids','event_id'),('dates','date'),('families','family'),('decision_ns','decision_ns')]:
        exact(old[field],[r[key] for r in register],'Earlier event register '+field)
    exact(old['matched'],[r['matched_eligible'] for r in register],'Earlier saved masks')
    exact(old['y'],[-1 if r['label'] is None else CLASSES.index(r['label']) for r in register],'Earlier labels')
    unique,inverse = old['auxiliary_event_indices'],old['event_to_auxiliary_index']
    check(len(set(unique.tolist()))==len(unique) and len(inverse)==len(register),'Auxiliary mapping dimensions')
    exact(inverse[unique],np.arange(len(unique)),'Auxiliary inverse representatives')
    for field in ('dates','decision_ns','targets','X_current7'):
        exact(old[field][unique][inverse],old[field],'Auxiliary map '+field)
    auxiliary = npz(path('R029','auxiliary-predictions.npz'),('predictions','fold','auxiliary_event_indices','dates'))
    final = npz(path('R029','models/auxiliary-3/predictions.npz'),('auxiliary_indices','common_coordinates','true_target','dates'))
    exact(auxiliary['auxiliary_event_indices'],unique,'Auxiliary saved mapping')
    exact(auxiliary['dates'],old['dates'][unique],'Auxiliary dates')
    wanted = np.flatnonzero(np.isin(old['dates'][unique],['2025-04-01',*DATES[:3]]))
    exact(final['auxiliary_indices'],wanted,'Frozen auxiliary3 target population')
    exact(final['true_target'],old['targets'][unique][wanted],'Auxiliary current targets')
    exact(final['dates'],old['dates'][unique][wanted],'Auxiliary3 dates')
    exact(final['common_coordinates'],auxiliary['predictions'][wanted],'Frozen common auxiliary predictions')
    check(np.all(auxiliary['fold'][wanted]==2),'Auxiliary3 fold identity')
    old['auxiliary'] = auxiliary['predictions'][inverse]
    old_probs = {arm:np.full((len(register),3),np.nan) for arm in ('C','P','R')}
    selection = read(path('R029','selection.json'))
    for family in FAMILIES:
        indices = np.flatnonzero(old['downstream_mask']&(old['families']==family))
        for arm in ('C','P','R'):
            selected = npz(path('R029',f'selected-{family}-{arm}.npz'),('event_indices','probabilities'))
            exact(selected['event_indices'],indices,'Selected scored row indices')
            check(selection[family+'-'+arm]['status']=='evaluable' and selection[family+'-'+arm]['refit'] is False,'Unchanged selection')
            old_probs[arm][indices] = selected['probabilities']
    protocol = read(path('R031','extension-protocol.json'))
    for family in FAMILIES:
        equal(protocol['objects_and_references']['references'][family]['probabilities'],fixed[family],'Later fixed references')
    days = {}
    for date in DATES:
        if date in DATES[:3]:
            select = np.flatnonzero(old['dates']==date)
            day = {k:old[k][select] for k in ('event_ids','dates','families','y','matched','decision_ns','targets','auxiliary','X_current7')}
            day['saved_index'],day['metadata'] = select,[register[i] for i in select]
            day['saved_index_kind'] = 'R029 prepared-cohort global row'
            day['probs'] = {a:old_probs[a][select] for a in ('C','P','R')}
            exact(old['downstream_mask'][select],day['matched'],'Earlier matched downstream equality')
            check(np.all(old['roles'][select]=='descriptive_evaluation'),'Earlier fixed role')
        else:
            day = npz(path('R031',date+'/feature-vectors.npz'),('event_ids','families','y','matched','decision_ns','targets'),True)
            pred = npz(path('R031',date+'/predictions.npz'),('event_ids','families','labels','matched','decision_ns','auxiliary',*METHODS))
            for key in ('event_ids','families','matched','decision_ns'):
                exact(day[key],pred[key],'Later prediction row '+key)
            exact(day['y'],pred['labels'],'Later prediction label codes')
            day.update(dates=np.full(len(day['y']),date),auxiliary=pred['auxiliary'],saved_index=np.arange(len(day['y'])),
                metadata=lines(path('R031',date+'/events.jsonl')),saved_index_kind='R031 '+date+' event row',
                probs={name:pred[name] for name in METHODS})
            identity = read(path('R031',date+'/prediction-identity.json'))
            equal(identity['objects'],protocol['objects_and_references'],'Later frozen object identity')
            equal(identity['class_order'],list(CLASSES),'Later class order')
            for field,name in [('features_sha256',date+'/feature-vectors.npz'),('predictions_sha256',date+'/predictions.npz'),('protocol_sha256','extension-protocol.json')]:
                check(identity[field]==INPUTS[str(path('R031',name))],'Later prediction binding')
        n = len(day['y'])
        check(n>0 and len(set(day['event_ids'].tolist()))==n and np.all(np.diff(day['decision_ns'])>=0),'Recorded day population')
        exact(day['event_ids'],[r['event_id'] for r in day['metadata']],'Day metadata IDs')
        exact(day['families'],[r['family'] for r in day['metadata']],'Day metadata families')
        exact(day['decision_ns'],[r['decision_ns'] for r in day['metadata']],'Day metadata decisions')
        check(day['matched'].dtype==np.bool_ and np.isin(day['y'],[-1,0,1,2]).all()
              and np.isin(day['families'],FAMILIES).all() and np.all(day['y'][day['matched']]>=0),'Saved label/mask domain')
        for key in ('targets','auxiliary','X_current7'):
            check(day[key].shape==(n,7) and np.isfinite(day[key]).all(),'Finite current auxiliary '+key)
        for name in METHODS[3:]:
            expected = np.asarray([fixed[str(f)][name] for f in day['families']])
            if name in day['probs']:
                exact(day['probs'][name],expected,'Saved fixed reference')
            day['probs'][name] = expected
        for name in METHODS:
            p = day['probs'][name][day['matched']]
            check(p.shape==(int(day['matched'].sum()),3) and np.isfinite(p).all() and ((p>=0)&(p<=1)).all(),'Scored probability domain')
            check(np.max(np.abs(p.sum(axis=1)-1))<=1e-12,'Probability sum')
        days[date] = day
    scaler = npz(path('R029','models/auxiliary-3/target-scaler.npz'),('means','scales'))
    return days,fixed,scaler['means'],{'references':reference,'selection':selection,
        'candidates':read(path('R029','candidate-results.json')),'later':read(path('R031','evaluation-summary.json'))}


def profile(labels,losses,weights=None):
    weights = [1.]*len(labels) if weights is None else list(weights)
    total_weight = math.fsum(weights); normalized = [float(w)/total_weight for w in weights]
    q,ell,counts = {},{},{}
    for k,name in enumerate(CLASSES):
        ids = [i for i,y in enumerate(labels) if y==k]
        mass = math.fsum(normalized[i] for i in ids)
        q[name],counts[name] = mass,len(ids)
        ell[name] = math.fsum(normalized[i]*float(losses[i]) for i in ids)/mass if mass else None
    return {'class_order':list(CLASSES),'n':len(labels),'class_counts':counts,'q':q,'ell':ell,
        'total_loss':math.fsum(w*float(v) for w,v in zip(normalized,losses)),'input_weight_sum':total_weight}


def standardized(record,fixed):
    missing = [k for k,w in zip(CLASSES,fixed) if w>0 and record['ell'][k] is None]
    components = None if missing else {k:float(w*record['ell'][k]) if w else 0. for k,w in zip(CLASSES,fixed)}
    return {'status':'unavailable' if missing else 'evaluable','value':None if missing else math.fsum(components.values()),
        'class_components':components,'missing_classes':missing,'reference_weights':dict(zip(CLASSES,fixed))}


def decomposition(earlier,later):
    absent_e = [k for k in CLASSES if earlier['ell'][k] is None]
    absent_l = [k for k in CLASSES if later['ell'][k] is None]
    missing = [k for k in CLASSES if k in absent_e or k in absent_l]
    result = {'status':'unavailable' if missing else 'evaluable','delta':later['total_loss']-earlier['total_loss'],
        'mix':None,'within':None,'mix_by_class':None,'within_by_class':None,'missing_classes':missing,
        'missing_by_group':{'earlier':absent_e,'later':absent_l},'reconciliation_residual':None}
    if not missing:
        mix = {k:(later['q'][k]-earlier['q'][k])*earlier['ell'][k] for k in CLASSES}
        within = {k:later['q'][k]*(later['ell'][k]-earlier['ell'][k]) for k in CLASSES}
        result.update(mix=math.fsum(mix.values()),within=math.fsum(within.values()),mix_by_class=mix,within_by_class=within)
        result['reconciliation_residual'] = result['delta']-result['mix']-result['within']
        close(result['reconciliation_residual'],0.,'decomposition_closure')
    return result


def aux_summary(predictions,targets,mean):
    n = len(targets)
    if not n:
        return {'n':0,'status':'unavailable'}
    rmse,mae,base_rmse,base_mae = [],[],[],[]
    flags = []
    for row in predictions:
        flags.append([bool(v<0) for v in row[:4]]+[bool(abs(row[4])>1)]+[bool(v<0) for v in row[5:]])
    for k in range(7):
        error = [float(p[k]-t[k]) for p,t in zip(predictions,targets)]
        baseline = [float(mean[k]-t[k]) for t in targets]
        rmse.append(math.sqrt(math.fsum(e*e for e in error)/n)); mae.append(math.fsum(abs(e) for e in error)/n)
        base_rmse.append(math.sqrt(math.fsum(e*e for e in baseline)/n)); base_mae.append(math.fsum(abs(e) for e in baseline)/n)
    any_count = sum(any(row) for row in flags)
    return {'n':n,'status':'available','rmse':rmse,'mae':mae,'frozen_mean_rmse':base_rmse,'frozen_mean_mae':base_mae,
        'rmse_ratio':[a/b if b>0 else None for a,b in zip(rmse,base_rmse)],
        'range_violation_counts':[sum(row[k] for row in flags) for k in range(7)],'range_violation_any':any_count,
        'range_violation_rate':any_count/n,'nonfinite':sum(not np.isfinite(row).all() for row in predictions)}


def inspect_diagnostics(contract,result,days,fixed,mean,accepted):
    losses,scored,examples,counts = {},[],[],{}
    for date,day in days.items():
        ids = np.flatnonzero(day['matched']); y = day['y'][ids]
        own = {name:np.array([.5*(math.fsum(float(v)*float(v) for v in p)+1)-float(p[int(k)])
                for p,k in zip(day['probs'][name][ids],y)]) for name in METHODS}
        own.update({name:own[a]-own[b] for name,(a,b) in CONTRASTS.items()})
        losses[date] = own
        scored.extend((date,int(i)) for i in ids)
        unique = {}; members = {}
        for i,t in enumerate(day['decision_ns']):
            t = int(t); unique.setdefault(t,i); members.setdefault(t,[]).append(i)
        for group in members.values():
            for i in group:
                for field in ('targets','auxiliary','X_current7'):
                    exact(day[field][i],day[field][group[0]],'Same-cut auxiliary join')
        first = list(unique.values())
        full = aux_summary(day['auxiliary'][first],day['targets'][first],mean)
        full['population'] = 'deduplicated past-eligible cuts before censoring'
        equal(result['auxiliary_full'][date],full,'auxiliary_full')
        counts[date] = {'recorded':len(day['y']),'scored':len(ids),'auxiliary':len(first),
            'censored':int((day['y']<0).sum()),'families':{}}
        for family in FAMILIES:
            local = np.flatnonzero(day['families'][ids]==family); chosen = ids[local]
            check(len(chosen)>0,'Every fixed family/date scored slot')
            counts[date]['families'][family] = len(chosen)
            for name,values in own.items():
                record = profile(y[local].tolist(),values[local].tolist())
                record['standardized'] = standardized(record,fixed[family]['train-frequency'])
                equal(result['daily'][family][date][name],record,'daily_profile')
                if name in METHODS:
                    if date in DATES[:3]:
                        if name in ('C','P','R'):
                            candidate = accepted['selection'][family+'-'+name]['selected']
                            prior = next(r for r in accepted['candidates'] if r['family']==family and r['arm']==name and r['candidate']==candidate)['scores']['per_day'][date]
                        else:
                            prior = accepted['references'][family][name]['per_day'][date]
                        close(prior['half_brier'],record['total_loss'],'accepted_daily')
                        check(prior['n']==len(chosen),'Accepted earlier date count')
                    else:
                        prior = next(r for d in accepted['later']['days'] if d['date']==date for r in d['scores'] if r['family']==family)
                        close(prior['scores'][name],record['total_loss'],'accepted_daily')
                        check(prior['n']==len(chosen),'Accepted later date count')
                if name in METHODS[3:]:
                    vector = fixed[family][name]
                    for k,label in enumerate(CLASSES):
                        if record['ell'][label] is not None:
                            close(record['ell'][label],.5*(math.fsum(p*p for p in vector)+1)-vector[k],'reference_conditional_invariant')
            matched = aux_summary(day['auxiliary'][chosen],day['targets'][chosen],mean)
            matched.update(population='exact scored family/date events',P_minus_C=math.fsum(own['P-C'][local])/len(local))
            equal(result['auxiliary_matched'][family][date],matched,'auxiliary_matched')
            i = min(chosen,key=lambda j:(int(day['decision_ns'][j]),str(day['event_ids'][j])))
            row = int(np.flatnonzero(ids==i)[0]); meta = day['metadata'][i]
            label = int(day['y'][i]); probabilities = {name:day['probs'][name][i].tolist() for name in METHODS}
            example = {'date':date,'family':family,'event_id':str(day['event_ids'][i]),'decision_ns':int(day['decision_ns'][i]),
                'matched':True,'selection':'First scored event per family/date, ordered by decision_ns then event_id',
                'y':label,'label':CLASSES[label],'saved_index':int(day['saved_index'][i]),'saved_index_kind':day['saved_index_kind'],
                'source_id':meta['source_id'],'source_ordinal':meta['decision_source_ordinal'],
                'X_current7':day['X_current7'][i].tolist(),'targets':day['targets'][i].tolist(),'auxiliary':day['auxiliary'][i].tolist(),
                'probabilities':probabilities,'saved_event_metadata':meta,'half_brier':{name:float(own[name][row]) for name in METHODS},
                'half_squared_error_by_probability_class':{name:[.5*(p-int(k==label))**2 for k,p in enumerate(probabilities[name])] for name in METHODS},
                'retrospective_class_standardization_factor':fixed[family]['train-frequency'][label]/(sum(day['y'][chosen]==label)/len(chosen)),
                'factor_scope':'Diagnostic identity using realized label/class mixture; never a model input or deployment adjustment'}
            examples.append(example)
    check(result['scored_events']==len(scored) and result['auxiliary_cuts']==sum(c['auxiliary'] for c in counts.values()),'Global diagnostic populations')
    equal(result['examples'],examples,'fixed_examples'); equal(read(OUT/'fixed-examples.json'),examples,'fixed_examples_file')
    event_losses = npz(OUT/'event-losses.npz',('event_ids','dates','families','y','decision_ns',*METHODS,*CONTRASTS))
    for field in ('event_ids','families','y','decision_ns'):
        exact(event_losses[field],[days[d][field][i] for d,i in scored],'Loss archive row '+field)
    exact(event_losses['dates'],[d for d,i in scored],'Loss archive dates')
    for name in (*METHODS,*CONTRASTS):
        expected = np.concatenate([losses[d][name] for d in DATES])
        check(np.max(np.abs(event_losses[name]-expected))<=1e-12,'Per-event loss archive '+name)
        MAXIMUM['event_loss'] = max(MAXIMUM.get('event_loss',0),float(np.max(np.abs(event_losses[name]-expected))))
    for family in FAMILIES:
        profiles = {}
        for group,dates in GROUPS.items():
            selected = [(d,i) for d,i in scored if d in dates and days[d]['families'][i]==family]
            counts_by_date = Counter(d for d,i in selected); n = len(selected)
            check(set(counts_by_date)==set(dates),'No group date silently dropped')
            labels = [int(days[d]['y'][i]) for d,i in selected]
            loss_indices = {d:{int(i):j for j,i in enumerate(np.flatnonzero(days[d]['matched']))} for d in dates}
            profiles[group] = {}
            for endpoint in ('equal_day','pooled'):
                weights = [1/(len(dates)*counts_by_date[d]) if endpoint=='equal_day' else 1/n for d,i in selected]
                profiles[group][endpoint] = {}
                for name in (*METHODS,*CONTRASTS):
                    values = [float(losses[d][name][loss_indices[d][i]]) for d,i in selected]
                    record = profile(labels,values,weights)
                    record['standardized'] = standardized(record,fixed[family]['train-frequency'])
                    equal(result['group_profiles'][family][group][endpoint][name],record,'group_profile')
                    profiles[group][endpoint][name] = record
                    if group=='Aug-Nov' and name in METHODS:
                        prior = accepted['later']['aggregate'][family]['equal_day' if endpoint=='equal_day' else 'pooled_event'][name]
                        close(record['total_loss'],prior,'accepted_group')
            for name in (*METHODS,*CONTRASTS):
                daily = {d:result['daily'][family][d][name]['total_loss'] for d in dates}
                equal_day = math.fsum(daily.values())/len(dates)
                pooled = math.fsum(counts_by_date[d]*daily[d] for d in dates)/n
                terms = {d:{'n':counts_by_date[d],'mean_loss':daily[d],'pooled_weight':counts_by_date[d]/n,
                    'equal_day_weight':1/len(dates),'contribution':(counts_by_date[d]/n-1/len(dates))*daily[d]} for d in dates}
                gap = {'status':'evaluable','pooled':pooled,'equal_day':equal_day,'gap':pooled-equal_day,'per_date':terms,
                    'reconciliation_residual':pooled-equal_day-math.fsum(v['contribution'] for v in terms.values())}
                equal(result['weighting_gap'][family][group][name],gap,'weighting_gap')
                close(profiles[group]['equal_day'][name]['total_loss'],equal_day,'original_equal_day_identity')
                close(profiles[group]['pooled'][name]['total_loss'],pooled,'original_pooled_identity')
        for endpoint in ('equal_day','pooled'):
            for name in (*METHODS,*CONTRASTS):
                expected = decomposition(profiles['May-Jul'][endpoint][name],profiles['Aug-Nov'][endpoint][name])
                equal(result['temporal_decomposition'][family][endpoint][name],expected,'temporal_decomposition')
                if name in METHODS[3:] and expected['status']=='evaluable':
                    close(expected['within'],0.,'fixed_reference_within_zero')
                if name in CONTRASTS and expected['status']=='evaluable':
                    a,b = CONTRASTS[name]
                    for component in ('delta','mix','within'):
                        pair = result['temporal_decomposition'][family][endpoint]
                        close(expected[component],pair[a][component]-pair[b][component],'contrast_decomposition_linearity')
    return counts


def synthetic_absence_checks():
    complete = profile([0,1,2],[.1,.2,.3])
    absent = profile([0,1],[.1,.2])
    results = {}
    for name,early,later in [('new_class',absent,complete),('disappearing_class',complete,absent),('absent_both',absent,absent)]:
        item = decomposition(early,later)
        check(item['status']=='unavailable' and item['mix'] is None and item['within'] is None and item['delta'] is not None,'Conservative absence oracle')
        results[name] = item
    check(standardized(absent,[1/3]*3)['status']=='unavailable','Missing standardized support oracle')
    return results


def main():
    target = OUT/'audit-results.json'
    if target.exists():
        raise FileExistsError('Preserve the issued audit receipt')
    started = time.perf_counter(); ledger = install_guards()
    receipt = {'status':'failed','new_fits':0,'model_inference_calls':0,'solver_calls':0,'training_seconds':0}
    try:
        check(not ledger['forbidden_calls'] and not ledger['fit_guard']['attempts'],'Fresh zero-operation guard')
        freeze = read(OUT/'execution-freeze.json')
        check(INPUTS[str(OUT/'execution-freeze.json')]==(OUT/'execution-freeze.sha256').read_text().strip(),'Execution freeze hash')
        for record in freeze['code']:
            check(sha(WORK/record['path'])==record['sha256']==sha(OUT/'code'/record['path']),'Frozen audit/source code')
        contract = read(OUT/'diagnostic-contract.json'); result = read(OUT/'diagnosis.json')
        check(contract['dates']==result['dates']==DATES and contract['groups']==result['groups']==GROUPS,'Fixed dates/groups')
        equal(result['methods'],list(METHODS),'Eight methods'); equal(result['contrasts'],{k:list(v) for k,v in CONTRASTS.items()},'Seven contrasts')
        equal(contract['class_order'],list(CLASSES),'Fixed F/A/N order'); equal(result['target_names'],TARGETS,'Seven target coordinates')
        check(result['contract_sha256']==INPUTS[str(OUT/'diagnostic-contract.json')],'Result contract binding')
        for key in ('new_fits','model_inference_calls','solver_calls','training_seconds'):
            check(result[key]==0,'No new operation '+key)
        producer_ledger = read(OUT/'zero-fit-ledger.json')
        check(not producer_ledger['forbidden_calls'] and not producer_ledger['fit_guard']['attempts'],'Producer zero-operation ledger')
        check(read(OUT/'post-integrity.json')['all_unchanged'],'Producer preserved input receipt')
        days,fixed,mean,accepted = load_inputs(contract)
        receipt['populations'] = inspect_diagnostics(contract,result,days,fixed,mean,accepted)
        receipt['synthetic_absence_oracle'] = synthetic_absence_checks()
        check(not ledger['forbidden_calls'] and not ledger['fit_guard']['attempts'] and ledger['fit_guard']['actual_fit_calls']==0,'Audit zero operation attempts')
        for path,expected in INPUTS.items():
            check(sha(path)==expected,'Audit input preservation')
        receipt['status'] = 'passed'
    except Exception as exc:
        receipt.update(error=type(exc).__name__+': '+str(exc),traceback=traceback.format_exc())
        raise
    finally:
        receipt.update(finished_utc=datetime.now(timezone.utc).isoformat(),elapsed_seconds=time.perf_counter()-started,
            checks=dict(CHECKS),max_residuals=MAXIMUM,input_sha256=INPUTS,zero_operation_ledger=ledger,
            independence={'shared_code':['t016_p4.guards.install_guards safety guard only'],
                'not_imported':['t016_p4.data','t016_p4.metrics','t016_p4.diagnose'],
                'scope':'Direct accepted NPZ/JSON joins, own row losses and weighted class arithmetic; no source, estimator, inference or solver',
                'synthetic_limit':'Absence fixtures validate the independent oracle; actual production status fields are separately compared.',
                'interpretation':'Exact descriptive accounting, not causal explanation, inference, endpoint replacement or scientific-goal closure.'})
        target.write_text(json.dumps(receipt,indent=2,allow_nan=False)+'\n',encoding='utf-8')
        print(json.dumps({'status':receipt['status'],'elapsed_seconds':receipt['elapsed_seconds'],'checks':dict(CHECKS),'max_residuals':MAXIMUM}),flush=True)


if __name__ == '__main__':
    main()
