"""Verify exact admitted bytes and freeze E271 before new extraction or inference."""
import json
import shutil
import subprocess
from pathlib import Path
from t016_p0.integrity import check_file, verify_contract
from t016_p3.fixed_inference import fixed_identity
from t016_p5.common import *

def main():
    assert not (OUT/'execution-declaration.json').exists()
    assert not (OUT/DATE).exists()
    stage('preflight', 'Rehash release, source packet, inherited code, selected objects and runtime; no deserialization')
    release = read(RELEASE)
    assert release['execution_enabled'] is True
    assert release['source_date'] == DATE and release['source_id'] == SOURCE_ID
    assert release['operation'] == 'D056:T016:E271-fixed-persistence'
    checked = {}
    def bind(path, expected=None, size=None):
        path = Path(path).resolve()
        record = check_file(path, expected or sha(path))
        if size is not None:
            assert record['bytes'] == size, str(path)
        prior = checked.get(str(path))
        assert prior is None or prior['sha256'] == record['sha256']
        checked[str(path)] = record
        return record
    bind(RELEASE)
    for entry in release.values():
        if isinstance(entry,dict) and {'path','sha256'} <= entry.keys():
            bind(entry['path'], entry['sha256'],entry.get('bytes'))
    inherited = read(release['inherited_prospective_protocol']['path'])
    assert inherited['selected_date'] is None and inherited['execution_enabled'] is False
    assert inherited['code_origin_commit'] == BASE
    for entry in inherited['inherited_code']:
        bind(WORK/entry['path'],entry['sha256'])
        original = subprocess.check_output(['git','show',BASE+':'+entry['path']],cwd=WORK)
        assert original == (WORK/entry['path']).read_bytes()
    for entry in inherited['inherited_protocols']:
        bind(entry['path'],entry['sha256'])
    admission = read(release['source_admission']['path'])
    assert admission['source_admitted'] is True
    source_manifest = read(release['source_packet_manifest']['path'])
    source_root = Path(release['source_packet_manifest']['path']).parent
    for entry in source_manifest['files'] + source_manifest['external_raw_sources_already_accounted']:
        bind(source_root/entry['path'],entry['sha256'],entry.get('bytes',entry.get('size_bytes')))
    review_root = Path(release['review_manifest']['path']).parent
    review_original = A/'T-013/rv-039-e270-source'
    for entry in read(release['review_manifest']['path'])['files']:
        local = review_root/entry['path']
        bind(local if local.exists() else review_original/entry['path'],entry['sha256'],entry.get('bytes'))
    contract, contract_bindings = verify_contract(Path(release['source_contract']['path']), release['source_contract']['sha256'], A)
    for entry in contract_bindings:
        checked[entry['path']] = entry
    assert contract['execution_enabled'] is False
    assert contract['sources'][0]['source_id'] == SOURCE_ID
    objects = read(release['fixed_object_identity_manifest']['path'])['objects_and_references']
    fresh = fixed_identity(FROZEN)
    assert fresh == objects
    bind(FROZEN/'artifact-manifest.json',objects['manifest_sha256'])
    for entry in objects['files']:
        bind(FROZEN/entry['path'],entry['sha256'],entry['size_bytes'])
    runtime = read(FROZEN/'runtime-identity.json')
    bind(runtime['executable'],runtime['executable_sha256'])
    for entry in runtime['library_files']:
        bind(entry['path'],entry['sha256'])
    # Sealed historical outputs are context and an embargo boundary, never rerun.
    bind(HISTORICAL/'artifact-manifest.json','71b725d72171f98ea51e7dc9a221f817a20416d1c07a916b13aa0b3e2655f7b4')
    for entry in read(HISTORICAL/'artifact-manifest.json')['files']:
        bind(HISTORICAL/entry['path'],entry['sha256'],entry.get('size_bytes',entry.get('bytes')))
    historical_summary = A/'cycle-20260922-1122/frozen-R-031/evaluation-summary.json'
    historical_manifest = historical_summary.parent/'artifact-manifest.json'
    # E264 freezes the earlier result manifest; prove membership before using it.
    def nested_hash(value, target):
        found=[]
        if isinstance(value,dict):
            if value.get('path') and Path(value['path']).resolve()==target.resolve():
                found += [value[k] for k in ('sha256','sha256_observed') if k in value]
            for v in value.values(): found += nested_hash(v,target)
        elif isinstance(value,list):
            for v in value: found += nested_hash(v,target)
        return found
    e264 = read(HISTORICAL/'diagnostic-contract.json')
    hashes = nested_hash(e264,historical_manifest)
    assert hashes and len(set(hashes))==1, 'Missing sealed historical manifest binding'
    bind(historical_manifest,hashes[0])
    hm = read(historical_manifest)
    entry = next(e for e in hm['files'] if Path(e['path']).name=='evaluation-summary.json')
    bind(historical_summary,entry['sha256'],entry.get('size_bytes',entry.get('bytes')))
    previous_end = max(d['extraction']['dependency_max_ns'] for d in read(historical_summary)['days'])
    assert not subprocess.check_output(['git','status','--porcelain'],cwd=WORK,text=True).strip()
    commit = subprocess.check_output(['git','rev-parse','HEAD'],cwd=WORK,text=True).strip()
    code = []
    for directory in ('t016_p0','t016_p1','t016_p2','t016_p3','t016_p4','t016_p5'):
        for path in sorted((WORK/directory).glob('*.py')):
            rel=path.relative_to(WORK).as_posix()
            assert subprocess.check_output(['git','show',commit+':'+rel],cwd=WORK)==path.read_bytes()
            dest=OUT/'code'/rel; dest.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(path,dest)
            code.append({'path':rel,'sha256':sha(path)})
    declaration = {
        'schema':'t016-e271-fixed-persistence/1','operation':release['operation'],'experiment':'E271',
        'frozen_utc':now(),'execution_enabled':True,'execution_commit':commit,'base_commit':BASE,
        'release':checked[str(RELEASE.resolve())], 'source_admission':release['source_admission'],
        'source_member':{'date':DATE,'source_id':SOURCE_ID,'contract_file':release['source_contract']['path'],
                         'contract_sha256':release['source_contract']['sha256'],'earlier_dependency_end_ns':previous_end},
        'previous_observed_block_max_dependency_ns':previous_end,
        'inherited_protocol':release['inherited_prospective_protocol'],
        'unchanged_definitions':inherited['unchanged_definitions'],
        'objects_and_references':objects,'accepted_R029_manifest':objects['manifest_sha256'],
        'methods':list(METHODS),'families':['breakout','rebound'],'class_order':['F','A','N'],'seed':SEED,
        'declared_breakout_claim':inherited['declared_breakout_claim'],
        'support_failure_handling':inherited['support_failure_handling'],
        'raw_endpoint':'np.mean of saved per-event float64 half-Brier; paired means use saved eventwise differences',
        'standardization':'unchanged profile_loss and standardize; exact frozen family training frequencies',
        'one_day_identity':'equal_day and pooled_event are the same raw_mean; not independent confirmations',
        'audit':'Independent source/cut/label reconstruction, fixed-object inference replay, scalar math.fsum loss/sign audit; 1e-12 arithmetic reconciliation only, no sign tolerance',
        'examples':'First chronological recorded past-eligible event per family, selected before labels/support; retain censoring',
        'storage_adaptations':['Exact source_id from admission passed to unchanged load_day',
            'Original sealed state/provenance files referenced by hash and ordinal; no duplicate full export',
            'Conservative full serialization bound before array/JSON writes; no cohort narrowing'],
        'exposure':release['exposure'],'resources':release['resources'],'code':code,
        'complete_file_bindings':list(checked.values()),
        'execution_support':[{'path':p.name,'sha256':sha(p)} for p in sorted(OUT.glob('*.py'))]
                            +[{'path':p.name,'sha256':sha(p)} for p in sorted(OUT.glob('*.sh'))],
        'new_events_before_freeze':0,'new_predictions_before_freeze':0,
        'new_fits':0,'new_market_bytes':0,'acceptance':'Pending independent A6 result review'}
    dump(OUT/'input-integrity.json',{'utc':now(),'all_passed':True,'bindings':list(checked.values()),
                                   'model_or_scaler_deserialization':False})
    dump(OUT/'resource-preflight.json',resources(extra=192*1024**2-sum(p.stat().st_size for p in OUT.rglob('*') if p.is_file())))
    dump(OUT/'execution-declaration.json',declaration)
    (OUT/'execution-declaration.sha256').write_text(sha(OUT/'execution-declaration.json')+'\n',encoding='utf-8')
    stage('declaration-frozen','Exact source, full unchanged consumer, objects, signs, resources and orchestration bound before events')

if __name__ == '__main__':
    main()
