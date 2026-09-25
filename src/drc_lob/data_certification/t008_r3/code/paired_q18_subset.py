"""Freeze the exact fourteen-contract Q18 full-day subset without copying data."""
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys
import time
sys.dont_write_bytecode=True
import jsonschema
import paired_startup30_normalize as N


def main():
    affinity=ctypes.windll.kernel32.SetProcessAffinityMask
    affinity.argtypes=(wintypes.HANDLE,ctypes.c_size_t)
    if not affinity(wintypes.HANDLE(-1),1):raise OSError("OneCPU affinity unavailable")
    started=time.perf_counter()
    root=N.ROOT
    dataset=root/"interface/full_day_startup30"
    out=dataset/"q18_required_subset"
    if out.exists():raise ValueError("Task-scoped subset already exists")
    policy_path=root/"panel_protocol.v3.2.startup30.json"
    policy=json.loads(policy_path.read_text(encoding="utf-8-sig"))
    schema_path=root/"interface/shared_data_contract.v2.3.0.schema.json"
    schema=json.loads(schema_path.read_text())
    decision=root.parents[1]/"full-day-scope-20260921/decision.md"
    contracts=[]
    dates=[]
    paths={policy_path,root/"panel_protocol.v3.1.json",schema_path,decision,
        root/"sources/source_manifest.json",root/"sources/tardis_full_day/acquisition_index.json",
        root/"interface/paired_startup30_synthetic_checks.json",root/"interface/paired_synthetic_checks.json"}
    for date,role in policy["roles_Q18"].items():
        if role=="unused":continue
        directory=dataset/date
        summary_path=directory/"paired_summary.json"
        summary=json.loads(summary_path.read_text())
        checks=json.loads((directory/"readback_verification.json").read_text())
        if len(checks)!=2 or not all(item["passed"] for item in checks):raise ValueError("Required date lacks completed paired readback")
        for asset in summary["assets"]:
            contract_path=Path(asset["contract_file"])
            contract=json.loads(contract_path.read_text())
            jsonschema.validate(contract,schema)
            if N.P.sha256(contract_path)!=asset["contract_sha256"] or contract["split_roles"]["Q18"]!=role:
                raise ValueError("Required contract hash/role mismatch")
            contracts.append(asset)
        dates.append({"date":date,"Q18_role":role,"paired_summary_file":str(summary_path),
            "paired_summary_sha256":N.P.sha256(summary_path),"paired_Q18_eligible_cuts":summary["paired_common_cuts"]["Q18"]["count"],
            "readback_file":str(directory/"readback_verification.json"),"readback_sha256":N.P.sha256(directory/"readback_verification.json")})
        paths.update(path for path in directory.rglob("*") if path.is_file())
        source_index_path=root/"sources/tardis_full_day/day_indexes"/(date+".json")
        paths.add(source_index_path)
        source_index=json.loads(source_index_path.read_text())
        for entry in source_index["records"]:
            record_path=Path(entry["record_path"])
            if N.P.sha256(record_path)!=entry["record_sha256"]:raise ValueError("Source record binding changed")
            paths.add(record_path)
            paths.add(Path(entry["compressed_path"]))
    if len(contracts)!=14 or len(dates)!=7:raise ValueError("Q18 requires exactly fourteen paired asset/date contracts")
    witness_path=root/"interface/full_day/source_qa/2026-01-01.json"
    paths.add(witness_path)
    witness=json.loads(witness_path.read_text())
    out.mkdir()
    source_copy=out/"executed_source"
    source_copy.mkdir()
    for name in ("paired_startup30_normalize.py","paired_startup30_full_day.py","paired_startup30_selftest.py","paired_source_audit.py","paired_q18_subset.py"):
        shutil.copyfile(root/"code"/name,source_copy/name)
    shutil.copyfile(root.parent/"r2/code/producer_interface.py",source_copy/"producer_interface.r2.executed.py")
    index={"schema":"t008-task-required-input-subset/1","version":"2.3.0","task_scope":"Q18",
        "stage":"full_day_startup30_required_roles","origin":"exploratory_real","fixture_only":False,
        "status":"required_inputs_constructed_independent_RV013_review_pending","contracts":contracts,"dates":dates,
        "required_role_counts":{"train_dates":3,"validation_dates":1,"test_dates":3,"paired_asset_date_contracts":14},
        "policy_file":str(policy_path),"policy_sha256":N.P.sha256(policy_path),"schema_file":str(schema_path),"schema_sha256":N.P.sha256(schema_path),
        "scope_decision_file":str(decision),"scope_decision_sha256":N.P.sha256(decision),
        "excluded_date_failures":[{"date":"2026-01-01","Q18_role":"unused","source_qa_file":str(witness_path),
            "source_qa_sha256":N.P.sha256(witness_path),"event_inversions":sum(item["inversions"] for item in witness["counts"].values()),
            "reason":"Three interior event-time reversals survive the fixed startup exclusion; full Q17 eight-date variant is not_evaluable under unchanged policy"}],
        "fit_gate":"No full-day fits before independent RV013 support for these exact fourteen inputs and downstream frozen class/support checks",
        "adaptation_class":policy["adaptation_class"],"model_fits":0,
        "all_evidence_referenced_in_place":True,"full_inventory_is_not_Q18_required_input_set":True}
    index_path=out/"dataset_index.q18.v2.3.0.json"
    N.write_json(index_path,index)
    paths.update(path for path in out.rglob("*") if path.is_file())
    files=[]
    for ordinal,path in enumerate(sorted(paths)):
        files.append({"path":str(path),"size_bytes":path.stat().st_size,"sha256":N.P.sha256(path)})
        if ordinal%250==0:print(json.dumps({"files_hashed":ordinal+1,"total_files":len(paths)}),flush=True)
    manifest={"schema":"t008-q18-full-day-review-manifest/1","created_at":datetime.now(timezone.utc).isoformat(),
        "task_scope":"Q18","dataset_index_file":str(index_path),"dataset_index_sha256":N.P.sha256(index_path),
        "files":files,"file_count":len(files),"total_bound_bytes":sum(item["size_bytes"] for item in files),
        "no_market_data_copies_created":True,"model_fits":0,"review_status":"exact_input_RV013_pending", "elapsed_seconds":time.perf_counter()-started}
    manifest_path=out/"review_manifest.json"
    N.write_json(manifest_path,manifest)
    print(json.dumps({"status":"complete","index_sha256":N.P.sha256(index_path),"manifest_sha256":N.P.sha256(manifest_path),
        "files":len(files),"elapsed_seconds":manifest["elapsed_seconds"]}),flush=True)


if __name__=="__main__":main()
