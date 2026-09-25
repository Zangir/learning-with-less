"""Materialize fixed diagnostic and seeded scenarios before any engine execution."""
from copy import deepcopy
from pathlib import Path
import json
import random

ROOT=(Path(__file__).resolve().parents[1] / 'runtime')
SEED=20260919
random.seed(SEED)


def add(t,who,oid,q,side='bid',price=10000,kind='LIMIT_ORDER'):
    return dict(at_ns=t,participant=who,kind=kind,order_id=oid,quantity=q,side=side,price=price)


def cancel(t,who,oid):
    return dict(at_ns=t,participant=who,kind='CANCEL_ORDER',order_id=oid)


def modify(t,who,oid,q,**changes):
    return dict(at_ns=t,participant=who,kind='MODIFY_ORDER',order_id=oid,quantity=q,**changes)


def episode(name,seed,actions,split='diagnostic',cutoff=None,control=False):
    return dict(name=name,stream_seed=seed,split=split,actions=actions,
                cutoff_ns=cutoff,upstream_control=control)


def main():
    episodes=[
      episode('diagnostic_nonhead',20263001,[add(100,1,101,4),add(200,2,102,3),modify(300,2,102,2)],control=True),
      episode('diagnostic_single_partial',20263002,[add(100,2,101,3,'ask'),add(200,1,102,4)],control=True),
      episode('diagnostic_multi_match',20263003,[add(100,1,101,4),add(100,2,102,3),add(200,3,103,6,'ask')],control=True)]
    rejects=[add(100,1,101,8),add(200,2,102,5),modify(250,2,102,3),
             modify(300,2,102,4),modify(310,2,102,3),modify(320,2,102,0),
             modify(330,2,102,2,new_limit_price=9990),modify(340,2,102,2,new_is_buy_order=False),
             modify(350,2,102,2,new_order_id=999),modify(360,2,102,2,new_time_ns=999),
             modify(370,2,102,2,new_tag='unsupported'),add(380,2,102,2),
             add(390,3,103,1,'ask',kind='MARKET_ORDER'),add(400,3,104,0),
             add(410,3,105,1,price=0),add(500,3,106,9,'ask'),
             modify(600,2,102,1),cancel(700,2,102),cancel(800,2,102),modify(900,2,102,1)]
    episodes.append(episode('diagnostic_rejections',20263004,rejects))
    for index,(name,target) in enumerate([('ahead',202),('behind',203)]):
        episodes.append(episode(f'legacy_cancel_{name}',20263010+index,
            [add(100,2,202,3),add(200,1,201,3),add(300,2,203,3),cancel(400,2,target),add(500,3,204,4,'ask')],
            cutoff=403))
    generated=[]
    for i,seed in enumerate([20261001,20261002,20262001,20262002]):
        rng=random.Random(seed)
        side='bid' if i%2==0 else 'ask'
        opposite='ask' if side=='bid' else 'bid'
        price=rng.choice([10000,10100,10200])
        worse=price-10 if side=='bid' else price+10
        a,p,b,tail=rng.randint(2,6),rng.randint(2,5),rng.randint(2,6),rng.randint(2,4)
        target=202 if i%2==0 else 203
        remaining=p+(b-1 if target==202 else a)
        take=p+1 if i<2 else remaining+1
        actions=[add(100,2,205,tail,side,worse),add(100,2,202,a,side,price),
                 add(200,1,201,p,side,price),add(300,2,203,b,side,price),modify(350,2,203,b-1),
                 cancel(400,2,target),add(500,3,204,take,opposite,worse),cancel(600,1,201)]
        if i==3:
            actions.insert(6,add(402,1,206,1,'ask',10300))
        split='generation_development' if i<2 else 'generation_check'
        name=f'seeded_{"development" if i<2 else "check"}_{seed}'
        episodes.append(episode(name,seed,actions,split=split,cutoff=403))
        generated.append(dict(name=name,seed=seed,side=side,price=price,ahead=a,probe=p,behind=b,
                              worse_level=tail,cancel_id=target,aggressive_quantity=take))
    relabel=deepcopy(episodes[-1])
    relabel['name']+='_relabel'
    relabel['split']='metamorphic_check'
    relabel['private_relabel_of']=episodes[-1]['name']
    relabel['stream_seed']=20262003
    for action in relabel['actions']:
        if action['participant']!=1: action['order_id']+=10000
    episodes.append(relabel)
    protocol=dict(operation='D034:T012:restricted-simulator',assignment='E256',seed=SEED,
      upstream_revision='c4bf157678928934417aba6073eb0651aeaf6d15',
      mechanism=dict(native_patch_lines=2,symbol='SYNTH',observer_participant=1,participants=3,
        clock_origin='2025-01-01T09:30:00',clock_timezone='synthetic naive',units='ns; integer cents/shares',
        latency_matrix_ns=[[1,2,1,1],[1,1,1,1],[1,1,1,1],[1,1,1,1]],
        computation_delay_ns=0,pipeline_delay_ns=0,stream_history=1000,book_freq=None,
        max_requests_per_episode=128,max_unique_limit_ids_per_episode=64,
        supported=['positive integer-priced/quantity LIMIT_ORDER','cancel live residual',
                   'strict positive same-price quantity reduction versus current live residual; preserve identity/time/priority'],
        prohibited=['MARKET_ORDER','repricing','quantity increase/equality/zero','identity/time/tag/fill-price amendment',
                    'duplicate or reused accepted IDs','non-live cancellation/modification'],
        honest_owner_assumption=True,native_legacy_archive='disabled and guarded against invocation'),
      observation=dict(feed_keys=['msg','sequence','exchange_ns','publish_ns','levels'],
        level_keys=['side','price','quantity'],delivery_record_keys=['delivery_ns','payload'],
        feed_type='COARSE_BOOK',publication='one immutable all-price-level snapshot after every request, including explicit rejection',
        public_sequence='exchange processing ordinal, including tied events; not global Message.uniq',
        predictor_input='admissible only: coarse packets and separate sanitized own receipts delivered by cutoff, plus actual own submissions sent by cutoff',
        excluded=['scenario/seed/split','other order/participant IDs','global Message.uniq','queue/order counts',
                  'future inputs','rich state/native history'],
        cutoff_rule='delivery_ns <= cutoff after every tied delivery at that timestamp',
        prefix_rule='remove actions sent after cutoff; drain kernel; then filter actual receipt times and already-sent own submissions',
        inflight_boundary='seeded_check_20262002 and relabel: own send402, exchange/publication403, delivery405; only own send is available at403',
        no_kernel_stop_time_filter=True),
      generation=dict(development_seeds=[20261001,20261002],check_seeds=[20262001,20262002],
        diagnostic_seeds=[20263001,20263002,20263003,20263004,20263010,20263011],
        relabel_check_seed=20262003,fitting=False,no_statistical_holdout_claim=True,
        generated_parameters=generated),
      required_results=dict(patched_all_invariants=True,upstream_control_detects_nonhead_and_history=True,
        legacy_pair_identical_admissible_prefix=True,legacy_probe_fills=[3,1],
        replays_equal=True,prefixes_equal=True,private_relabel_observations_equal=True,
        no_unsupported_request_changes_book_or_history=True),
      run_counts=dict(upstream=3,patched=2*len(episodes)+sum(e['cutoff_ns'] is not None for e in episodes)),
      resources=dict(CPU=2,logical_cpus=[8,9],aggregate_memory_bytes=8*1024**3,watchdog_seconds=3600,
        max_engine_runs=32,software_download_cap_bytes=256*1024**2,retained_cap_bytes=1024**3,free_disk_floor_bytes=50*1024**3),
      exclusions=['calibrated population economics','inventories/risk','fees/funding','impact calibration','venue matching equivalence',
                  'malicious owners','learner fitting','inferred recoverability','Hyperliquid correspondence','Q16/Q17/Q18 replication','paper novelty'],
      episodes=episodes)
    assert sum(protocol['run_counts'].values())==32
    (ROOT/'protocol.json').write_text(json.dumps(protocol,indent=2)+'\n')
    print(json.dumps(dict(episodes=len(episodes),run_counts=protocol['run_counts'],seeded=generated),indent=2))


if __name__=='__main__':
    main()
