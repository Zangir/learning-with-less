"""Source-clock-only assessment of a proposed uniform event-time prefix exclusion.

No normalized panel, model, threshold, return or performance value is produced.
"""
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path
import ctypes,gzip,hashlib,json,os,sys,time
from ctypes import wintypes

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'clock_adaptation'
OUT.mkdir(exist_ok=True)
sys.path.insert(0,str(ROOT/'code'))
from verify_provider_chain import iso_ns,sha
kernel=ctypes.WinDLL('kernel32',use_last_error=True)
kernel.GetCurrentProcess.restype=wintypes.HANDLE
kernel.SetProcessAffinityMask.argtypes=(wintypes.HANDLE,ctypes.c_size_t)
assert kernel.SetProcessAffinityMask(kernel.GetCurrentProcess(),2)
START=time.monotonic()
index_path=ROOT/'sources/tardis_hour00/acquisition_index.json'
index=json.loads(index_path.read_text())
previous={}; kept_previous={}; result={}; witnesses=[]
for item in index['requests']:
    record=json.loads(Path(item['record_path']).read_text())
    date=record['date'];start=iso_ns(date+'T00:00:00Z');end=start+3600*1000000000;warm=start+30*1000000000
    with gzip.open(record['compressed_path'],'rb') as stream:
        for source_line,line in enumerate(stream):
            if not line.strip():continue
            receipt,body=line.split(b' ',1)
            r=json.loads(body);data=r['data'];asset=data['coin'];key=(date,asset)
            stats=result.setdefault(key,Counter())
            stats['raw_rows']+=1
            event=data['time']*1000000;received=iso_ns(receipt.decode())
            payload=hashlib.sha256(json.dumps(data,sort_keys=True,separators=(',',':')).encode()).hexdigest()
            prior=previous.get(key)
            if prior and event<prior[0]:
                stats['raw_event_inversions']+=1
                witnesses.append(dict(date=date,asset=asset,request_id=record['request_id'],source_line=source_line,
                    previous_event_ns=prior[0],event_ns=event,delta_ns=event-prior[0],provider_receipt_ns=received,
                    both_events_inside_fixed_prefix=prior[0]<warm and event<warm))
            previous[key]=(event,payload)
            if not start<=event<end:stats['outside_declared_event_hour']+=1;continue
            if event<warm:stats['prefix_rows_excluded_in_proposal']+=1;continue
            stats['retained_rows_if_proposal_accepted']+=1
            stats['retained_provider_receipt_before_30s']+=received<warm
            stats.setdefault('first_retained_event_ns',event)
            stats['last_retained_event_ns']=event
            prior=kept_previous.get(key)
            if prior:
                stats['retained_event_inversions']+=event<prior[0]
                stats['retained_conflicting_equal_timestamp']+=event==prior[0] and payload!=prior[1]
                stats['retained_identical_equal_timestamp']+=event==prior[0] and payload==prior[1]
                stats['retained_event_gaps_over_2s']+=event-prior[0]>2000000000
                stats['retained_max_event_gap_ns']=max(stats['retained_max_event_gap_ns'],event-prior[0])
            kept_previous[key]=(event,payload)
result=dict(schema='t008-clock-only-prefix-assessment/1',created_utc=datetime.now(timezone.utc).isoformat(),
    proposed_prefix_seconds=30,clock='exchange event timestamp selection; provider receipt retained separately',
    input_index_sha256=sha(index_path),source_protocol_sha256=index['protocol_sha256'],
    no_normalized_outputs=True,no_model_fits=True,no_outcome_statistics=True,
    results={date+' '+asset:dict(stats) for (date,asset),stats in result.items()},inversion_witnesses=witnesses,
    elapsed_s=time.monotonic()-START,cpu_affinity_mask=2,code_sha256=sha(Path(__file__)))
target=OUT/'first_hour_clock_assessment.json'
with target.open('x') as stream:json.dump(result,stream,indent=2);stream.write('\n')
print(json.dumps(dict(date_asset_pairs=len(result['results']),raw_inversions=len(witnesses),
    all_witnesses_inside_30s=all(r['both_events_inside_fixed_prefix'] for r in witnesses),
    retained_inversions=sum(r.get('retained_event_inversions',0) for r in result['results'].values()),
    retained_conflicts=sum(r.get('retained_conflicting_equal_timestamp',0) for r in result['results'].values()),
    elapsed_s=result['elapsed_s'],sha256=sha(target)),indent=2))
