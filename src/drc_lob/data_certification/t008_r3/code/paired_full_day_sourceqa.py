"""Complete strict full-day source QA without redundant large normalization copies."""
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import time
sys.dont_write_bytecode=True
import paired_normalize as N
from paired_bind_provenance import bind_index


def source_qa(records):
    previous={}
    previous_receipt=None
    counts={asset:{"rows":0,"inversions":0,"equal_identical":0,"equal_conflicting":0,"source_gaps_over_2s":0} for asset in ("BTC","ETH")}
    witnesses=[]
    disconnects=[]
    depths={asset:set() for asset in counts}
    receipt_inversions=0
    for ordinal,chunk,local,line in N.record_lines(records):
        if not line:
            disconnects.append({"source_ordinal":ordinal,"chunk_number":chunk,"chunk_local_ordinal":local})
            continue
        receipt,encoded=line.split(" ",1)
        receipt_ns=N.utc_ns(receipt)
        payload=json.loads(encoded)
        if payload.get("channel")!="l2Book" or payload["data"]["coin"] not in counts:
            raise ValueError("Wrong native channel/asset")
        data=payload["data"]
        asset=data["coin"]
        if type(data["time"]) is not int:
            raise ValueError("Native event time is not integer milliseconds")
        current={"source_ordinal":ordinal,"chunk_number":chunk,"chunk_local_ordinal":local,
            "receipt_text":receipt,"event_ms":data["time"],"full_payload_sha256":hashlib.sha256(encoded.encode()).hexdigest(),"payload":payload}
        if previous_receipt is not None and receipt_ns<previous_receipt:
            receipt_inversions+=1
            witnesses.append({"violation":"provider_receipt_inversion","previous_receipt_ns":previous_receipt,"current":current})
        previous_receipt=receipt_ns
        counts[asset]["rows"]+=1
        depths[asset].add(tuple(len(side) for side in data["levels"]))
        old=previous.get(asset)
        if old:
            delta=data["time"]-old["event_ms"]
            violation="inversions" if delta<0 else "equal_conflicting" if delta==0 and payload!=old["payload"] else None
            if violation:
                counts[asset][violation]+=1
                witnesses.append({"asset":asset,"violation":violation,"delta_ms":delta,"previous":old,"current":current})
            elif delta==0:
                counts[asset]["equal_identical"]+=1
            elif delta>2000:
                counts[asset]["source_gaps_over_2s"]+=1
        previous[asset]=current
    return {"counts":counts,"rejection_witnesses":witnesses,"all_rejection_witnesses_retained":True,
        "provider_receipt_inversions":receipt_inversions,"disconnect_markers":disconnects,
        "observed_raw_depths":{asset:sorted(value) for asset,value in depths.items()},
        "strict_source_order_valid":not witnesses,"receipt_request_ranges_verified":True,
        "scope":"Source-only order/tie/provider-clock QA; does not issue normalized state/feature/model acceptance"}


def main():
    affinity=ctypes.windll.kernel32.SetProcessAffinityMask
    affinity.argtypes=(wintypes.HANDLE,ctypes.c_size_t)
    if not affinity(wintypes.HANDLE(-1),2):raise OSError("OneCPU affinity unavailable")
    started=time.perf_counter()
    root=N.ROOT
    out=root/"interface/full_day"
    qa_out=out/"source_qa"
    qa_out.mkdir()
    policy_path=root/"panel_protocol.v3.1.json"
    policy=json.loads(policy_path.read_text(encoding="utf-8-sig"))
    budget={"recorded_at":datetime.now(timezone.utc).isoformat(),"decision":"Finish current July1 strict materialization then source-only QA for remaining dates",
        "reason":"Retain all raw data and completed strict evidence while reserving the12GiB retention budget for complete24 amended full-day contracts",
        "scientific_effect":"Strict required design already not_evaluable because February/March required training dates violate the frozen strict source-order rule; no admissible strict fit is removed",
        "preserved_original_runner_file":"../paired_full_day.original.executed.py",
        "preserved_original_runner_sha256":N.P.sha256(root/"interface/paired_full_day.original.executed.py"),
        "normalized_dates_expected":["2025-01-01","2025-04-01","2025-05-01","2025-06-01","2025-07-01"],
        "remaining_status_rule":"Distinguish source_QA_valid_but_contract_not_materialized_due_retention from actual source failure"}
    N.write_json(out/"retention_execution_decision.json",budget)
    complete=set()
    summaries=[]
    provenance=[]
    failures=[]
    unmaterialized=[]
    statuses=[]
    while len(complete)<len(policy["roles_Q17"]):
        for date in policy["roles_Q17"]:
            index_path=root/"sources/tardis_full_day/day_indexes"/(date+".json")
            if date in complete or not index_path.exists():continue
            source_index=json.loads(index_path.read_text())
            if source_index["protocol_sha256"]!=N.P.sha256(policy_path) or len(source_index["records"])!=144:
                raise ValueError("Full-day source index policy/count mismatch")
            records=[]
            for entry in source_index["records"]:
                p=Path(entry["record_path"])
                if N.P.sha256(p)!=entry["record_sha256"]:raise ValueError("Record hash changed")
                record=json.loads(p.read_text())
                N.verify_acquisition(record)
                records.append(record)
            roles={q:policy["roles_"+q][date] for q in ("Q17","Q18")}
            midnight=N.utc_ns(date+"T00:00:00Z")
            N.verify_policy_binding(records,date,roles,policy,N.P.sha256(policy_path),midnight,midnight+86400*N.NS)
            qa=source_qa(records)
            qa.update(date=date,split_roles=roles,acquisition_index_file=str(index_path),acquisition_index_sha256=N.P.sha256(index_path),
                acquisition_records_verified=144,compressed_and_decoded_hashes_reverified=True,qa_code_sha256=N.P.sha256(__file__))
            qa_path=qa_out/(date+".json")
            N.write_json(qa_path,qa)
            summary_path=out/date/"paired_summary.json"
            if summary_path.exists():
                summary=json.loads(summary_path.read_text())
                for asset in ("BTC","ETH"):N.verify_output(out/date/asset)
                summaries.append(summary)
                status="normalized_contract_available"
            elif not qa["strict_source_order_valid"]:
                failures.append({"date":date,"split_roles":roles,"status":"unavailable_under_frozen_strict_policy","source_qa_file":str(qa_path),"source_qa_sha256":N.P.sha256(qa_path)})
                status="unavailable_under_frozen_strict_policy"
            else:
                unmaterialized.append({"date":date,"split_roles":roles,"status":"source_QA_valid_but_contract_not_materialized_due_retention","source_qa_file":str(qa_path),"source_qa_sha256":N.P.sha256(qa_path)})
                status="source_QA_valid_but_contract_not_materialized_due_retention"
            for asset in ("BTC","ETH"):
                statuses.append({"date":date,"asset":asset,"split_roles":roles,"status":status,"individual_asset_counts":qa["counts"][asset],"source_qa_file":str(qa_path),"source_qa_sha256":N.P.sha256(qa_path)})
            provenance.append({"date":date,"acquisition_index_file":str(index_path),"acquisition_index_sha256":N.P.sha256(index_path),"source_qa_file":str(qa_path),"source_qa_sha256":N.P.sha256(qa_path)})
            complete.add(date)
            print(json.dumps({"date":date,"status":status,"strict_source_order_valid":qa["strict_source_order_valid"]}),flush=True)
        if len(complete)<len(policy["roles_Q17"]):time.sleep(10)
    result={"schema":"t008-paired-dataset-index/3","version":"2.2.0","origin":"exploratory_real","stage":"full_day_strict_with_retention_scoped_materialization",
        "policy_file":str(policy_path),"policy_sha256":N.P.sha256(policy_path),"acquisition_indexes":provenance,"dates":summaries,
        "contracts":[asset for day in summaries for asset in day["assets"]],"unavailable_dates":failures,"unmaterialized_dates":unmaterialized,
        "status":"not_evaluable_required_training_source_failures","model_fits":0,"source_qa_code_sha256":N.P.sha256(__file__),
        "retention_decision_file":"retention_execution_decision.json","retention_decision_sha256":N.P.sha256(out/"retention_execution_decision.json"),
        "elapsed_seconds":time.perf_counter()-started}
    index_path=out/"dataset_index.v2.2.0.json"
    N.write_json(index_path,result)
    bound=bind_index(index_path)
    N.write_json(out/"asset_date_status.v2.2.1.json",{"dataset_index_file":str(bound),"dataset_index_sha256":N.P.sha256(bound),"entries":statuses})
    print(json.dumps({"status":"complete","index":str(bound),"sha256":N.P.sha256(bound),"elapsed_seconds":result["elapsed_seconds"]}),flush=True)


if __name__=="__main__":main()
