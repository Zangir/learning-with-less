"""Independent clock-only check of exact frozen v3.2 receipt-first prefix rule."""
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path
import ctypes,gzip,hashlib,json,sys,time
from ctypes import wintypes

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'clock_adaptation'
sys.path.insert(0,str(ROOT/'code'))
from verify_provider_chain import iso_ns,sha
kernel=ctypes.WinDLL('kernel32',use_last_error=True)
kernel.GetCurrentProcess.restype=wintypes.HANDLE
kernel.SetProcessAffinityMask.argtypes=(wintypes.HANDLE,ctypes.c_size_t)
assert kernel.SetProcessAffinityMask(kernel.GetCurrentProcess(),2)
START=time.monotonic()
policy_path=ROOT/'panel_protocol.v3.2.startup30.json'
assert sha(policy_path)=='e5de9c455d3918b11693af0f771de4776f49cd9b2a1f1918000c0179259c8d19'
index_path=ROOT/'sources/tardis_hour00/acquisition_index.json'
index=json.loads(index_path.read_text())
raw_previous={};validation_previous={};results={};witnesses=[]
for item in index['requests']:
    record=json.loads(Path(item['record_path']).read_text())
    date=record['date'];start=iso_ns(date+'T00:00:00Z');end=start+3600000000000;warm=start+30000000000
    with gzip.open(record['compressed_path'],'rb') as stream:
        for source_line,line in enumerate(stream):
            if not line.strip():continue
            receipt,body=line.split(b' ',1);r=json.loads(body);data=r['data'];asset=data['coin'];key=(date,asset)
            stats=results.setdefault(key,Counter());stats['raw_rows']+=1
            event=data['time']*1000000;received=iso_ns(receipt.decode())
            payload=hashlib.sha256(json.dumps(data,sort_keys=True,separators=(',',':')).encode()).hexdigest()
            previous=raw_previous.get(key)
            if previous and event<previous[0]:
                stats['raw_inversions']+=1
                witnesses.append(dict(date=date,asset=asset,request_id=record['request_id'],source_line=source_line,
                    previous_event_ns=previous[0],event_ns=event,delta_ns=event-previous[0],
                    previous_provider_receipt_ns=previous[2],provider_receipt_ns=received,
                    both_provider_receipts_inside_fixed_prefix=received<warm and previous[2]<warm))
            raw_previous[key]=(event,payload,received)
            if received<warm:
                stats['excluded_provider_receipt_prefix_rows']+=1
                stats['prefix_receipt_rows_with_event_at_or_after30s']+=event>=warm
                continue
            stats['strictly_validated_remaining_rows']+=1
            previous=validation_previous.get(key)
            if previous:
                stats['remaining_source_inversions']+=event<previous[0]
                stats['remaining_conflicting_equal_timestamp']+=event==previous[0] and payload!=previous[1]
                stats['remaining_identical_equal_timestamp']+=event==previous[0] and payload==previous[1]
            validation_previous[key]=(event,payload)
            if not warm<=event<end:
                stats['boundary_event_rows_validated_then_excluded']+=1
                continue
            stats['analytical_rows_if_review_accepts']+=1
            stats.setdefault('first_analytical_event_ns',event)
            stats['last_analytical_event_ns']=event
result=dict(schema='t008-clock-only-receipt-prefix-assessment/1',created_utc=datetime.now(timezone.utc).isoformat(),
    exact_policy_sha256=sha(policy_path),input_index_sha256=sha(index_path),
    validation_order='Provider receipt prefix excluded first; event ordering/full-depth ties checked on every remaining message before analytical event-window filter.',
    raw_disconnect_evidence='Blank markers retained in raw input; this clock-only counter pass does not emit segments or erase source markers.',
    no_normalized_outputs=True,no_fits=True,no_outcome_statistics=True,
    results={date+' '+asset:dict(stats) for (date,asset),stats in results.items()},inversion_witnesses=witnesses,
    elapsed_s=time.monotonic()-START,cpu_affinity_mask=2,code_sha256=sha(Path(__file__)))
target=OUT/'receipt_prefix_clock_assessment.v3.2.json'
with target.open('x') as stream:json.dump(result,stream,indent=2);stream.write('\n')
print(json.dumps(dict(pairs=len(results),raw_inversions=len(witnesses),
    remaining_inversions=sum(r.get('remaining_source_inversions',0) for r in results.values()),
    remaining_conflicts=sum(r.get('remaining_conflicting_equal_timestamp',0) for r in results.values()),
    boundary_rows_validated=sum(r.get('boundary_event_rows_validated_then_excluded',0) for r in results.values()),
    elapsed_s=result['elapsed_s'],sha256=sha(target)),indent=2),flush=True)
