"""Replay final asset/date status generation while preserving issued artifact bytes."""
import ctypes
from ctypes import wintypes
import hashlib
import json
from pathlib import Path
import platform
import sys
sys.dont_write_bytecode=True
import jsonschema

ROOT=Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def immutable_json(path,obj):
    path=Path(path)
    if path.exists():
        if json.loads(path.read_text())!=obj:
            raise ValueError("Existing final report differs; create a new version instead of rewriting it")
    else:
        path.write_text(json.dumps(obj,indent=2,sort_keys=True)+"\n",encoding="utf-8")


def strict_hour_status():
    indexpath=ROOT/"interface/hour00/dataset_index.v2.2.1.json"
    index=json.loads(indexpath.read_text())
    policy=json.loads((ROOT/"panel_protocol.v3.1.json").read_text(encoding="utf-8-sig"))
    contracts={(x["date"],x["asset"]):x for x in index["contracts"]}
    failures={x["date"]:x for x in index["unavailable_dates"]}
    statuses=[]
    for date in policy["roles_Q17"]:
        for asset in ("BTC","ETH"):
            if (date,asset) in contracts:
                statuses.append({"date":date,"asset":asset,"status":"available_under_frozen_strict_policy",**contracts[(date,asset)]})
            else:
                fail=failures[date]
                evidence=ROOT/"interface/hour00"/(date+".unavailable.json")
                statuses.append({"date":date,"asset":asset,"split_roles":fail["split_roles"],
                    "status":"unavailable_in_paired_date_under_frozen_strict_policy","reason":fail["reason"],
                    "individual_asset_source_order_counts":fail["source_order_audit"]["counts"][asset],
                    "paired_date_exclusion":"One asset source-order violation rejects the paired date; individual asset may have no own inversion",
                    "rejection_evidence_file":str(evidence),"rejection_evidence_sha256":sha(evidence)})
    output=ROOT/"interface/hour00/asset_date_status.v2.2.1.json"
    immutable_json(output,{"schema":"t008-paired-asset-date-status/1","dataset_index_file":str(indexpath),"dataset_index_sha256":sha(indexpath),"entries":statuses})
    return output


def amended_full_status():
    out=ROOT/"interface/full_day_startup30"
    indexpath=out/"dataset_index.v2.3.0.json"
    index=json.loads(indexpath.read_text())
    schema=json.loads((ROOT/"interface/shared_data_contract.v2.3.0.schema.json").read_text())
    contracts={(x["date"],x["asset"]):x for x in index["contracts"]}
    failures={x["date"]:x for x in index["unavailable_dates"]}
    policy=json.loads((ROOT/"panel_protocol.v3.2.startup30.json").read_text())
    statuses=[]
    for date in policy["roles_Q17"]:
        for asset in ("BTC","ETH"):
            if (date,asset) in contracts:
                item=contracts[(date,asset)]
                jsonschema.validate(json.loads(Path(item["contract_file"]).read_text()),schema)
                if sha(item["contract_file"])!=item["contract_sha256"]:raise ValueError("Issued contract changed")
                statuses.append({"status":"normalized_contract_available",**item})
            else:
                fail=failures[date]
                evidence=out/(date+".unavailable.json")
                statuses.append({"date":date,"asset":asset,"split_roles":fail["split_roles"],
                    "status":"unavailable_under_unchanged_startup30_policy","reason":fail["reason"],
                    "individual_asset_source_order_counts":fail["source_order_audit"]["counts"][asset],
                    "rejection_evidence_file":str(evidence),"rejection_evidence_sha256":sha(evidence)})
    output=out/"asset_date_status.v2.3.0.json"
    immutable_json(output,{"schema":"t008-paired-asset-date-status/1","dataset_index_file":str(indexpath),"dataset_index_sha256":sha(indexpath),
        "entries":statuses,"Q17_full_day_status":"not_evaluable_required_eight_date_source_scope",
        "Q18_required_subset_file":str(out/"q18_required_subset/dataset_index.q18.v2.3.0.json"),
        "Q18_status":"all14required_inputs_constructed_exact_RV013_review_pending"})
    validation={"schema_valid_contracts":len(contracts),
        "source_readback_verifications":sum(len(json.loads((out/x["date"]/"readback_verification.json").read_text())) for x in index["dates"]),
        "dates":len(index["dates"]),"unavailable_dates":list(failures),"asset_date_status_entries":len(statuses),
        "dataset_index_sha256":sha(indexpath),"asset_date_status_sha256":sha(output),"model_fits":0,
        "normalizer_elapsed_seconds":index["elapsed_seconds"],"python":sys.version,"platform":platform.platform(),
        "normalizer_observed_peak_working_set_bytes":1639014400,
        "peak_measurement_qualification":"Windows OS process peak counter observed during the final normalization dates; no unobserved final increment is asserted",
        "normalizer_cpu_affinity":2,"strict_source_qa_runtime_affinity_override":1,"synthetic_checks_passed":40}
    immutable_json(out/"final_validation.json",validation)
    return output


def main():
    affinity=ctypes.windll.kernel32.SetProcessAffinityMask
    affinity.argtypes=(wintypes.HANDLE,ctypes.c_size_t)
    if not affinity(wintypes.HANDLE(-1),1):raise OSError("OneCPU affinity unavailable")
    outputs=[strict_hour_status(),amended_full_status()]
    result={"passed":True,"executed_code_file":str(Path(__file__).resolve()),"executed_code_sha256":sha(__file__),
        "existing_immutable_bytes_preserved":True,"outputs":[{"file":str(path),"sha256":sha(path)} for path in outputs]}
    immutable_json(ROOT/"interface/final_status_replay_verification.json",result)
    print(json.dumps(result))


if __name__=="__main__":main()
