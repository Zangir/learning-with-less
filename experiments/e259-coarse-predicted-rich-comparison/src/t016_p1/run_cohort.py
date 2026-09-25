"""Execute the prospectively frozen seven-day P1 cohort, never predictive fitting."""
from collections import Counter
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from bisect import bisect_right
import gc
import json
import random
import subprocess
import sys
import unittest
import numpy as np

from t016_p0.engine import NS, Observations, extract, retrospective_support, stable_hash
from t016_p0.integrity import check_file, file_hash, read_json, verify_contract, verify_packet, now
from t016_p0.run_p0 import load_restriction
from t016_p1.labels import label_event
from t016_p1.features import views, readiness_reason, X_NAMES, Z_NAMES, AUX_INPUT_NAMES
from t016_p1.specification import DATES, ROLES, P0_SHA, INDEX_SHA, specification
from t016_p1.cohort_io import load_day, compact_cuts, dump_json, dump_lines

random.seed(20260919)
np.random.seed(20260919)
WORK=Path(__file__).resolve().parents[1]
A=Path(__file__).resolve().parents[2] / 'runtime'
OUT=A/'T-016/r3-p1-cohort'
P0=A/'cycle-20260922-0515/frozen-R-025'
REVIEW=A/'cycle-20260922-0616/frozen-RV-023'
FREEZE_SHA='9017958555471c87c1c572233682506d1c69a03353bb9ad6b514b18827b31702'


def stage(name,detail):
    line=f'{now()} | {name} | {detail}'
    print(line,flush=True)
    with (OUT/'timings.log').open('a',encoding='utf-8') as f:f.write(line+'\n')


def verify_json_packet(root,expected):
    records=[check_file(root/'artifact-manifest.json',expected)]
    for entry in read_json(root/'artifact-manifest.json')['files']:
        path=(root/entry['path']).resolve();path.relative_to(root.resolve())
        records.append(check_file(path,entry['sha256']))
    return records


def read_lines(path):
    with path.open(encoding='utf-8-sig') as f:return [json.loads(line) for line in f]


def fixture_gate():
    stage('fixtures','Run accepted P0 suite plus P1 label/feature/readiness fixtures before market parsing')
    suite=unittest.TestSuite()
    for folder,pattern in [('t016_p0','test_engine.py'),('t016_p1','test_p1.py')]:
        suite.addTests(unittest.defaultTestLoader.discover(str(WORK/folder),pattern=pattern,top_level_dir=str(WORK)))
    path=OUT/'logs'/('fixtures-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'.log')
    with path.open('w',encoding='utf-8') as f:result=unittest.TextTestRunner(stream=f,verbosity=2).run(suite)
    dump_json(OUT/'fixture-results.json',{'utc':now(),'tests':result.testsRun,'failures':len(result.failures),
        'errors':len(result.errors),'passed':result.wasSuccessful(),'market_rows_read_before_tests':0,'log':str(path)})
    assert result.wasSuccessful() and result.testsRun>=55


def integrity_gate():
    stage('integrity','Fresh full hashes for all seven contracts and accepted packets before labels')
    check_file(OUT/'cohort-protocol.json',FREEZE_SHA)
    protocol=read_json(OUT/'cohort-protocol.json')
    expected=specification(protocol['contracts'])
    assert {k:v for k,v in protocol.items() if k!='frozen_utc'}==expected
    for f in read_json(OUT/'freeze-receipt.json')['files']:check_file(OUT/f['path'],f['sha256'])
    check_file(WORK/'t016_p0/engine.py',protocol['engine_sha256'])
    index=A/'T-008/r3/interface/full_day_startup30/q18_required_subset/dataset_index.q18.v2.3.1.json'
    index_check=check_file(index,INDEX_SHA)
    packets={'P0':verify_json_packet(P0,'0d4ea9391a2a04ae015ac6314f06ac1dd37454524d0b85b86f8ca3ee9bb199bd'),
             'RV023':verify_packet(REVIEW,'acf3cf95f3088a6d15e6eba41a007377135f500dcf18eb5c3e72efe1fb57cb3a'),
             'original_P0':verify_json_packet(A/'T-016/r2-p0','0d4ea9391a2a04ae015ac6314f06ac1dd37454524d0b85b86f8ca3ee9bb199bd')}
    contracts={};bindings=[]
    for member in protocol['contracts']:
        contract,checks=verify_contract(Path(member['contract_file']),member['contract_sha256'],A)
        assert contract['continuity']['max_age_ns']==1_500_000_000
        assert contract['continuity']['max_gap_ns']==2*NS
        contracts[member['date']]=contract;bindings+=checks
    dump_json(OUT/'input-integrity.json',{'finished_utc':now(),'index':index_check,'packets':packets,
        'bindings':bindings,'entry_count':len(bindings),'unique_files':len({x['path'] for x in bindings}),
        'scope':'Current complete local bytes; no raw replay/exchange authentication; no inherited Q18 mask reuse'})
    return protocol,contracts


def check_label_oracle(event,label):
    """Reconcile saved label provenance with a separate first-index calculation."""
    refs=label['future_refs']
    assert len(refs)==10 and [r['k'] for r in refs]==list(range(1,11))
    if not all(r['valid'] for r in refs):
        assert label['label'] is None and label['first_hit_k'] is None
        return
    numerator=event['epsilon2']['numerator'];denominator=event['epsilon2']['denominator']
    q=[event['direction']*(r['mid2']-event['decision_mid2'])*denominator for r in refs]
    hits=[(i+1,'F' if x>=2*numerator else 'A') for i,x in enumerate(q) if x>=2*numerator or x<=-numerator]
    expected=hits[0] if hits else (None,'N')
    assert (label['first_hit_k'],label['label'])==expected


def may_hour_gate(member):
    stage('may-hour','Reproduce accepted P0 May hour first; then validate its new labels')
    directory=Path(member['contract_file']).parent
    segments=read_json(directory/'source_segments.json')
    rows,provenance,boundary=load_restriction(directory,segments)
    day=int(datetime(2025,5,1,tzinfo=timezone.utc).timestamp())*NS
    obs=Observations(rows,segments,day+30*NS,day+3600*NS)
    data=extract(obs,P0_SHA)
    checks={name:data[name]==read_lines(P0/(name+'.jsonl')) for name in ('levels','events','candidates','blocked_cuts')}
    checks['masks']=retrospective_support(obs,data['events'])==read_lines(P0/'support-masks.jsonl')
    assert all(checks.values())
    before=stable_hash(data)
    labels=[label_event(obs,e) for e in data['events']]
    for event,label in zip(data['events'],labels):check_label_oracle(event,label)
    assert stable_hash(data)==before
    dump_lines(OUT/'accepted-may-hour-labels.jsonl',labels)
    dump_json(OUT/'accepted-may-hour-checks.json',{'utc':now(),'checks':checks,'events':len(labels),
        'classes':dict(Counter(l['label'] for l in labels)),'state_unchanged_after_labeling':True,
        'scope':'P1 stage boundary and descriptive labels on the previously accepted exact hour'})
    return {e['event_id']:l for e,l in zip(data['events'],labels)}


def prefix_check(rows,segments,start,end,data,labels):
    watermark_target=start-30*NS+43200*NS
    stop=bisect_right([r['event_ns'] for r in rows],watermark_target)
    obs=Observations(rows[:stop],segments,start,end)
    prefix=extract(obs,P0_SHA)
    common=obs.times[-1]//NS*NS
    for name,key in [('events','decision_ns'),('candidates','decision_ns'),('levels','anchor_ns'),('blocked_cuts','cut_ns')]:
        assert prefix[name]==[x for x in data[name] if x[key]<=common],name
    byid={l['event_id']:l for l in labels}
    compared=0;changed=0
    for event in prefix['events']:
        label=label_event(obs,event)
        if event['decision_ns']+10*NS<=common:
            assert label==byid[event['event_id']];compared+=1
        elif label!=byid[event['event_id']]:changed+=1
    return {'nominal_second':43200,'watermark_ns':obs.times[-1],'common_finalized_cut_ns':common,
        'causal_records_equal':True,'completed_horizon_labels_equal':True,'labels_compared':compared,
        'unfinished_tail_label_changes':changed}


def run_day(member,previous_end,may_labels,example_keys):
    date=member['date'];stage('day-start',date+' fixed full-day extraction and P1 labeling')
    directory=Path(member['contract_file']).parent
    day=int(datetime.fromisoformat(date).replace(tzinfo=timezone.utc).timestamp())*NS
    start,end=day+30*NS,day+86400*NS
    segments=read_json(directory/'source_segments.json')
    rows,provenance,obs=load_day(directory,segments,start,end,'tardis-hyperliquid-'+date+'-btc')
    data=extract(obs,P0_SHA);before=stable_hash(data['events'])
    labels=[label_event(obs,e) for e in data['events']]
    assert stable_hash(data['events'])==before
    for event,label in zip(data['events'],labels):check_label_oracle(event,label)
    masks=retrospective_support(obs,data['events'])
    for mask,label in zip(masks,labels):
        assert all(mask[k]==label[k] for k in ('complete_future_support','censor_reason','first_bad_cut_ns'))
    prefix=prefix_check(rows,segments,start,end,data,labels)
    if date=='2025-05-01':
        byid={e['event_id']:e for e in data['events']}
        for event in read_lines(P0/'events.jsonl'):assert byid[event['event_id']]==event
        for label in labels:
            if label['event_id'] in may_labels:assert label==may_labels[label['event_id']]
    cut_arrays,availability=compact_cuts(obs,data)
    first_cut=int(cut_arrays['cut_ns'][0]);levels={l['anchor_ns']:l for l in data['levels']}
    compact_events=[];population=[];aux={};examples=[]
    xdigest=sha256();zdigest=sha256();targetdigest=sha256()
    next_month=datetime.fromisoformat(date).replace(tzinfo=timezone.utc)
    partition_end=int(next_month.replace(month=next_month.month+1).timestamp())*NS
    for event,label in zip(data['events'],labels):
        t=event['decision_ns'];i=(t-first_cut)//NS;first=i-60
        assert first>=0 and np.all(cut_arrays['valid_depth'][first:i+1])
        level=levels[event['anchor_ns']]
        assert cut_arrays['source_ordinal'][first:i+1].tolist()==event['history_source_ordinals']
        x,z,target=views(cut_arrays['book_units8_counts'][first:i+1],cut_arrays['age_ns'][first:i+1],t,level,event)
        rich=np.concatenate((x,z));assert np.array_equal(x,rich[:len(X_NAMES)])
        assert np.all(cut_arrays['event_ns'][first:i+1]<=cut_arrays['cut_ns'][first:i+1])
        assert int(cut_arrays['cut_ns'][i])==t
        for digest,array in ((xdigest,x),(zdigest,z),(targetdigest,target)):digest.update(array.tobytes())
        level_first=(event['anchor_ns']-60*NS-first_cut)//NS
        level_stop=level_first+60
        assert cut_arrays['source_ordinal'][level_first:level_stop].tolist()==level['source_ordinals']
        dependency_min=min(event['anchor_ns']-60*NS,int(cut_arrays['event_ns'][level_first:level_stop].min()),
                           int(cut_arrays['event_ns'][first:i+1].min()))
        compact={k:v for k,v in event.items() if k not in ('feature_history','history_source_ordinals')}
        compact.update(cohort_protocol_sha256=FREEZE_SHA,date=date,contract_sha256=member['contract_sha256'],
            feature_cut_index_start=first,feature_cut_index_stop=i+1,level_cut_index_start=level_first,
            level_cut_index_stop=level_stop,decision_cut_index=i,dependency_min_ns=dependency_min,
            dependency_max_ns=t+10*NS,feature_vector_sha256=sha256(x.tobytes()).hexdigest(),
            Z_vector_sha256=sha256(z.tobytes()).hexdigest())
        compact_events.append(compact)
        reason=readiness_reason(compact,day,partition_end,previous_end)
        if not label['complete_future_support']:reason='future_support:'+label['censor_reason']
        population.append({'date':date,'role':ROLES[date],'event_id':event['event_id'],'family':event['family'],
            'label':label['label'],'matched_eligible':reason is None,'exclusion':reason,
            'shared_arms':['C','P','R'],'decision_ns':t})
        aux_record={'date':date,'decision_ns':t,'cut_index':i,'source_id':event['source_id'],
            'source_ordinal':event['decision_source_ordinal'],'target':target.tolist(),
            'input_sha256':sha256(x[:len(AUX_INPUT_NAMES)].tobytes()).hexdigest(),
            'dependency_min_ns':min(t-60*NS,int(cut_arrays['event_ns'][first:i+1].min())),
            'dependency_max_ns':t,'population':'past-only, before future support'}
        if t in aux:assert aux[t]==aux_record
        else:aux[t]=aux_record
        key=(event['family'],label['label'] or 'censored')
        if key not in example_keys:
            row=obs.rows[obs.grid[t]['row_index']]
            examples.append({'family':key[0],'label_case':key[1],'selection':'first chronological case in authorized cohort',
                'event':compact,'decision_row':row,'decision_provenance':provenance[row['source_ordinal']],
                'level':level,'label_record':label,'X_first7':x[:7].tolist(),'X_current7':x[420:427].tolist(),
                'current_auxiliary_target':target.tolist()})
            example_keys.add(key)
    dest=OUT/date;dest.mkdir()
    np.savez_compressed(dest/'cuts.npz',**cut_arrays)
    for name,values in [('events',compact_events),('labels',labels),('candidates',data['candidates']),
                        ('levels',data['levels']),('support-masks',masks),('population',population),('auxiliary-current-targets',list(aux.values()))]:
        dump_lines(dest/(name+'.jsonl'),values)
    dump_json(dest/'segments.json',list(obs.segments.values()))
    availability.update(source_rows=len(rows),grid_cuts=len(obs.grid),valid_grid_cuts=int(cut_arrays['valid_bbo'].sum()),
        invalid_grid_by_reason=dict(Counter(p['reason'] for p in obs.grid.values() if not p['valid'])),
        blocked_cut_counts=dict(Counter(x['reason'] for x in data['blocked_cuts'])),
        level_counts=dict(Counter('valid' if x['valid'] else x['reason'] for x in data['levels'])),
        original_segments=len(segments),retained_segments=len(obs.segments),first_event_ns=obs.times[0],
        last_event_ns=obs.times[-1],retained_endpoint_exclusive_ns=obs.end)
    dump_json(dest/'availability.json',availability)
    counts=[]
    for family in ('breakout','rebound'):
        candidates=[c for c in data['candidates'] if c['family']==family]
        group=[l for l in labels if l['family']==family]
        classes={c:sum(l['label']==c for l in group) for c in ('F','A','N')}
        censored=sum(l['label'] is None for l in group)
        rejections=Counter(c['reason'] for c in candidates if c['status']=='rejected')
        matched=[p for p in population if p['family']==family and p['matched_eligible']]
        assert sum(classes.values())+censored==len(group)
        assert len(candidates)==len(group)+sum(rejections.values())
        counts.append({'date':date,'role':ROLES[date],'family':family,'raw_candidates':len(candidates),
            'recorded':len(group),'rejected':sum(rejections.values()),'rejection_reasons':dict(rejections),
            'censored':censored,'censor_reasons':dict(Counter(l['censor_reason'] for l in group if l['label'] is None)),
            'classes':classes,'matched_rows':len(matched),'matched_classes':dict(Counter(p['label'] for p in matched)),
            'readiness_exclusions':dict(Counter(p['exclusion'] for p in population if p['family']==family and not p['matched_eligible']))})
    checks={'prefix':prefix,'same_row_projections':availability['same_row_projection_checks'],
        'all_event_histories_indexed_exactly':True,'all_views_finite':True,'shared_X_equals_R_prefix':True,
        'no_future_cut_in_X':True,'label_oracle_and_support_match':True,'event_state_unchanged_after_labels':True,
        'X_hash_in_event_order':xdigest.hexdigest(),'Z_hash_in_event_order':zdigest.hexdigest(),
        'auxiliary_target_hash_in_event_order':targetdigest.hexdigest(),'auxiliary_deduplicated_cuts':len(aux),
        'zero_predictive_fits':True}
    dump_json(dest/'checks.json',checks);dump_json(dest/'counts.json',counts)
    maximum=max((e['dependency_max_ns'] for e in compact_events),default=end)
    result={'date':date,'counts':counts,'availability':availability,'checks':checks,
            'population':population,'examples':examples,'dependency_max':maximum,'aux_count':len(aux)}
    stage('day-complete',date+f': {len(labels)} recorded; {sum(l["label"] is not None for l in labels)} labeled; '+str(len(aux))+' auxiliary cuts')
    return result


def main():
    if (OUT/'cohort-summary.json').exists() or any((OUT/date).exists() for date in DATES):
        raise FileExistsError('Existing cohort output must be preserved; version any correction')
    fixture_gate();protocol,contracts=integrity_gate()
    may_labels=may_hour_gate(next(c for c in protocol['contracts'] if c['date']=='2025-05-01'))
    counts=[];days=[];population=[];examples=[];example_keys=set();previous_end=None
    for member in protocol['contracts']:
        result=run_day(member,previous_end,may_labels,example_keys)
        counts+=result['counts'];population+=result.pop('population');examples+=result.pop('examples')
        previous_end=result['dependency_max'];days.append(result);del result;gc.collect()
    stage('readiness','Reconcile common populations and class/day adequacy; no fitted models')
    adequacy=[]
    for family in ('breakout','rebound'):
        roles={}
        for role in ('downstream_train','selection','descriptive_evaluation'):
            rows=[p for p in population if p['family']==family and p['role']==role and p['matched_eligible']]
            classes={c:sum(p['label']==c for p in rows) for c in ('F','A','N')}
            roles[role]={'rows':len(rows),'days':len({p['date'] for p in rows}),'classes':classes,
                         'all_three_classes':all(classes.values()),'ordered_population_sha256':stable_hash([p['event_id'] for p in rows])}
        evaluable=all(roles[r]['all_three_classes'] for r in ('downstream_train','selection'))
        adequacy.append({'family':family,'roles':roles,'development_class_ready':evaluable,
            'interpretation':'Data-ready for separately authorized bounded development comparison' if evaluable else 'Not evaluable under frozen class requirements; no rule/date rescue'})
    dump_json(OUT/'actual-examples.json',{'examples':examples,'unavailable_cases':[
        {'family':f,'case':c} for f in ('breakout','rebound') for c in ('F','A','N','censored') if (f,c) not in example_keys]})
    dump_lines(OUT/'matched-population.jsonl',population)
    dump_json(OUT/'comparison-readiness.json',{'protocol_sha256':FREEZE_SHA,'adequacy':adequacy,
        'schema_dimensions':{'X':len(X_NAMES),'Z':len(Z_NAMES),'R':len(X_NAMES)+len(Z_NAMES),'P':len(X_NAMES)+7,'auxiliary_X':len(AUX_INPUT_NAMES)},
        'common_population_sha256':stable_hash(population),'same_C_P_R_population':True,'predictive_fits':0,
        'next_authorization':'After P1 acceptance, authorize BTC development C/P/R comparison on this frozen cohort and proposed39fits within a measured resource budget; explicitly include optional2diagnostics if desired. No new cohort/confirmation/profit scope.',
        'confirmatory_inference':'not evaluable from3exposed dates; no CI computed; optional prior bootstrap/40day heuristic not adopted'})
    dump_json(OUT/'cohort-summary.json',{'utc':now(),'operation':'D035:T016:P1-development-cohort',
        'protocol_sha256':FREEZE_SHA,'dates':DATES,'counts':counts,'days':days,
        'total_recorded':sum(x['recorded'] for x in counts),'total_labeled':sum(sum(x['classes'].values()) for x in counts),
        'total_censored':sum(x['censored'] for x in counts),'predictive_fits':0,'P_and_L_computed':False,
        'interpretation':'Descriptive sampled-label feasibility and matched data readiness only'})
    stage('post-integrity','Rehash all complete bound inputs and accepted P0 packets after extraction')
    post=[]
    for member in protocol['contracts']:
        _,checks=verify_contract(Path(member['contract_file']),member['contract_sha256'],A);post+=checks
    preserved=verify_json_packet(A/'T-016/r2-p0','0d4ea9391a2a04ae015ac6314f06ac1dd37454524d0b85b86f8ca3ee9bb199bd')
    dump_json(OUT/'post-integrity.json',{'utc':now(),'bindings':post,'prior_P0':preserved,'all_unchanged':True})
    dump_json(OUT/'code-identity.json',{'executed_head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=WORK,text=True).strip(),
        'base_P0_commit':'ec39b19cd6ec38d21aac03e26d9461d2c36afa0b','python_version':sys.version,'numpy_version':np.__version__,
        'seed':20260919,'files':[{'path':str(p.relative_to(WORK)),'sha256':file_hash(p)} for folder in ('t016_p0','t016_p1') for p in sorted((WORK/folder).glob('*.py'))]})
    stage('cohort-complete','All seven days and readiness ledgers completed; zero predictive fits and no scientific acceptance conferred')


if __name__=='__main__':main()
