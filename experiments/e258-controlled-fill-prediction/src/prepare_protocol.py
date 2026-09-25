"""Freeze a finite three-state queue family before running native outcomes."""
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
from itertools import product
from pathlib import Path
import json
import random
import shutil

ROOT=(Path(__file__).resolve().parents[1] / 'runtime')
ACCEPTED=ROOT.parent.parent/'cycle-20260922-0718/frozen-R-026'
REVIEW=ROOT.parent.parent/'cycle-20260922-0820/frozen-RV-024'
CODE=Path(__file__).parent
BASE_SEED=20260919
random.seed(BASE_SEED)


def save(name,value):
    path=ROOT/name
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8')


def h_weights(condition,c):
    e={'zero':[.25,.25],'informative':[.1,.4],'shift':[.4,.1]}[condition][c]
    return [e,1-2*e,e]


def flow_weights(z):
    return [[.1,.65,.05,.2],[.1,.05,.65,.2]][z]


def actions(m):
    c,z,k,q,side,h,j=[m[key] for key in ['C','Z','K','Q','side','H','J']]
    price=10000
    sign=-1 if side=='bid' else 1
    opposite='ask' if side=='bid' else 'bid'
    def add(t,who,oid,quantity,p=price,s=side):
        return dict(at_ns=t,participant=who,kind='LIMIT_ORDER',order_id=oid,quantity=int(quantity),side=s,price=p)
    def cancel(t,oid):
        return dict(at_ns=t,participant=2,kind='CANCEL_ORDER',order_id=oid)
    cancelled=[(401,402),(401,403),(403,404)][h]
    return [add(50,2,301,c+1,price+sign*10),cancel(80,301),
            add(90,2,302,z+1,price+sign*20),add(100,2,401,k),add(150,2,402,k),
            add(200,1,201,q),add(250,2,403,k),add(300,2,404,k),
            cancel(350,cancelled[0]),cancel(400,cancelled[1]),
            add(500,3,501,[q-1,q,q+k,q+2*k][j],price,opposite)]


def main():
    assert not (ROOT/'freeze.json').exists(), 'Protocol cannot replace an existing freeze.'
    for path,expected in [(ACCEPTED,'2d82c71c2a5a2f04524ab235b9c7e415ffc8308386d67e63841522efa9df80ad'),
                          (REVIEW,'530ed85a3b872f2a0894150b1c7f74fd37957a7734093127112a3d28ff23420f')]:
        assert sha256((path/'manifest.json').read_bytes()).hexdigest()==expected
        manifest=json.loads((path/'manifest.json').read_text())
        entries=manifest['files']
        if isinstance(entries,dict): entries=[dict(path=k,**v) for k,v in entries.items()]
        for row in entries:
            f=path/row['path']
            assert f.stat().st_size==row['bytes'] and sha256(f.read_bytes()).hexdigest()==row['sha256']
    if not (ROOT/'preservation-before.json').exists():
        save('preservation-before.json',[dict(path=str(p.relative_to(ROOT.parent)).replace('\\','/'),bytes=p.stat().st_size,
            sha256=sha256(p.read_bytes()).hexdigest()) for p in sorted(ROOT.parent.rglob('*'))
            if p.is_file() and ROOT not in p.parents])
    for variant in ['upstream','patched']:
        shutil.copytree(ACCEPTED/'source'/variant,ROOT/'source'/variant,dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    for name in ['source-provenance.json','native-repair.diff']:
        shutil.copy2(ACCEPTED/name,ROOT/name)
    inherited=(ACCEPTED/'code/engine_capture.py').read_text()
    adjusted=inherited.replace('r6-restricted-simulator','r7-controlled-fill-study')
    if not (CODE/'engine_capture.py').exists():
        (CODE/'engine_capture.py').write_text(adjusted,encoding='utf-8')
    assert (CODE/'engine_capture.py').read_text()==adjusted
    resource=(ACCEPTED/'code/resource_guard.py').read_text().replace('r6-restricted-simulator','r7-controlled-fill-study')
    if not (CODE/'resource_guard.py').exists():
        (CODE/'resource_guard.py').write_text(resource,encoding='utf-8')
    specs=[]
    pools=[('zero','train',512),('zero','selection',128),('zero','test',512),
           ('informative','train',512),('informative','selection',128),('informative','test',512),('shift','test',512)]
    seeds=[]
    for domain,(condition,role,n) in enumerate(pools,1):
        for i in range(n):
            seed=100000000+domain*100000+i
            rng=random.Random(seed)
            c,z,k,q,side=rng.randrange(2),rng.randrange(2),rng.choice([2,4]),rng.choice([2,3]),rng.choice(['bid','ask'])
            h=rng.choices([0,1,2],weights=h_weights(condition,c))[0]
            j=rng.choices([0,1,2,3],weights=flow_weights(z))[0]
            m=dict(condition=condition,role=role,group_id=f'{condition}-{role}-{i:04}',row_index=i,
                   generation_seed=seed,C=c,Z=z,K=k,Q=q,side=side,H=h,J=j)
            specs.append(dict(name=m['group_id'],stream_seed=200000000+len(specs)*10,
                split=role,cutoff_ns=403,metadata=m,actions=actions(m)))
            seeds.append(seed)
    support=[]
    for i,(c,z,k,q,side,h,j) in enumerate(product(range(2),range(2),[2,4],[2,3],['bid','ask'],range(3),range(4))):
        m=dict(condition='support',role='support',group_id=f'support-{i:03}',row_index=i,
               generation_seed=None,C=c,Z=z,K=k,Q=q,side=side,H=h,J=j)
        spec=dict(name=m['group_id'],stream_seed=200000000+len(specs)*10,split='support',cutoff_ns=403,metadata=m,actions=actions(m))
        specs.append(spec);support.append(spec)
    for i in [0,100,200,383]:
        for kind in ['replay','prefix','relabel']:
            original=support[i]
            spec=deepcopy(original)
            spec['name']=f'{original["name"]}-{kind}'
            spec['split']='diagnostic'
            spec['metadata']['role']='diagnostic'
            spec['metadata']['group_id']=original['name']
            spec['relation']=dict(kind=kind,source=original['name'])
            spec['prefix']=kind=='prefix'
            spec['stream_seed']=200000000+len(specs)*10
            if kind=='relabel':
                for action in spec['actions']:
                    if action['participant']!=1:action['order_id']+=10000
            specs.append(spec)
    assert len(specs)==3212 and len(seeds)==len(set(seeds))==2816
    protocol=dict(task='T-012',experiment='E258',operation='D036:T012:controlled-fill-study',base_seed=BASE_SEED,
        created_at=datetime.now(timezone.utc).isoformat(),native_parent_commit='9b61af0592104876e8a2d26ac8ae2787282d4241',
        accepted_author_manifest='2d82c71c2a5a2f04524ab235b9c7e415ffc8308386d67e63841522efa9df80ad',
        accepted_review_manifest='530ed85a3b872f2a0894150b1c7f74fd37957a7734093127112a3d28ff23420f',
        mechanism=json.loads((ACCEPTED/'protocol.json').read_text())['mechanism'],
        law=dict(H=[0,1,2],queue_ahead='K*H',e=dict(zero=[.25,.25],informative=[.1,.4],shift=[.4,.1]),
            H_probability='[e,1-2e,e]',C=[0,1],Z=[0,1],K=[2,4],Q=[2,3],side=['bid','ask'],
            public_contexts_independent_uniform=True,J=[0,1,2,3],V=['Q-1','Q','Q+K','Q+2*K'],
            J_probabilities=[flow_weights(0),flow_weights(1)],J_independent_of_H_C_given_Z=True,
            shift='cue-queue conditional association swap only; all public marginals and future-flow law fixed'),
        observations=dict(cutoff_ns=403,horizon_ns=503,probe_order_id=201,tie_rule='all channel deliveries<=403 and own sends<=403',
            fields='full admissible coarse/own-receipts/own-submissions; no metadata',statistic=['C','Z','K','Q','side'],
            label='binary full original probe fill by own receipt horizon503',rich='current queue rank H at exchange403; never future volume',
            sufficiency_required='all 384 support worlds share exact admissible transcript within each statistic cell'),
        populations=[dict(condition=c,role=r,n=n) for c,r,n in pools],training_sizes=[128,512],
        selection_policy='selection role diagnostic only; no parameter/model/calibration choice or early stopping from its outcomes',
        fitting=dict(max_total_invocations=24,planned_invocations=24,learned_calls_per_bundle=6,
            bundles=4,train_only=True,point_tie='lowest H',posterior_mean_round_tie='lower integer',
            direct_pseudocount=[1,1],queue_prior=[.5,.5,.5],probability_clip_for_log_only=1e-9,
            optimizer=dict(method='Exact unconstrained interior inverse or minimum over three convex triangle edges',
                edge_bisection_iterations=80,independent_vertex_directional_tolerance=1e-6),
            main_supervision='Y only: direct/point-Y/distribution-Y/unconditional; rich adds current H input',
            auxiliary_supervision='H labels: shared categorical reconstruction yields point/distribution/matched-direct-soft',
            downstream='fixed known survival decoder; no learned downstream or auxiliary stacking'),
        evaluation=dict(primary='Brier',secondary='log loss',calibration_bins=[0,.2,.4,.6,.8,1],
            costs=[.2,.4,.55,.7,.85],decision='act iff p>c; ties abstain',loss='c*a*(1-Y)+(1-c)*(1-a)*Y',
            reconstruction=['squared mean rank error','categorical Brier when defined'],bootstrap_replicates=1000,
            bootstrap_seed=202609190,confidence=.95,statistical_unit='independent sampled episode group',
            uncertainty='test sampling conditional on frozen fits; nested training sizes not independent training replicates',
            exact_population='enumerate fixed law; distinguish irreducible Bayes risk from estimator excess',
            shifted_references='both stale source-law and true shifted-law; latter granted inaccessible environmental knowledge'),
        run_counts=dict(statistical=2816,support=384,diagnostic=12,total=3212),
        resources=dict(cpu=2,logical_cpus=[8,9],memory_bytes=8*1024**3,watchdog_seconds=3600,max_native_episodes=4096,
            max_learned_fit_invocations=24,retained_limit_bytes=1024**3,free_disk_floor_bytes=50*1024**3,downloaded_bytes=0),
        stop_on=['native capture/label/delivery/source validity failure','fit failure','resource or fit/run limit'],episodes=specs)
    save('protocol.json',protocol)
    save('preparation.json',dict(accepted_inputs_verified=True,source_reused=True,downloaded_bytes=0,
        source_changes='engine_capture ROOT path only; native patch remains exactly two previously accepted lines',
        source_provenance_context='copied provenance file retains its r6 preparation timestamp and earlier accepted-review identities',
        specification_count=len(specs),native_executed=False,learned_fits=0))
    print(json.dumps(dict(specifications=len(specs),statistical=len(seeds),native_executed=False)))


if __name__=='__main__':main()
