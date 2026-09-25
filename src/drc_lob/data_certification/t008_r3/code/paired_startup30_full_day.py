"""Process immutable complete-day indexes as acquisition publishes them."""
import ctypes
from ctypes import wintypes
import json
from pathlib import Path
import sys
import time
sys.dont_write_bytecode = True
import paired_startup30_normalize as N
from paired_source_audit import inspect


def main():
    affinity = ctypes.windll.kernel32.SetProcessAffinityMask
    affinity.argtypes = (wintypes.HANDLE, ctypes.c_size_t)
    if not affinity(wintypes.HANDLE(-1), 2):
        raise OSError("Could not enforce one logical CPU")
    started = time.perf_counter()
    policy_path = N.ROOT / "panel_protocol.v3.2.startup30.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8-sig"))
    source_indexes = N.ROOT / "sources/tardis_full_day/day_indexes"
    out = N.ROOT / "interface/full_day_startup30"
    if out.exists():
        raise ValueError("Full-day stage already exists; preserve issued evidence")
    out.mkdir()
    completed, summaries, failures, provenance = set(), [], [], []
    while len(completed) < len(policy["roles_Q17"]):
        for date in policy["roles_Q17"]:
            index_path = source_indexes / (date+".json")
            if date in completed or not index_path.exists():
                continue
            index = json.loads(index_path.read_text())
            if index["date"] != date or index["protocol_sha256"] != policy["supersedes_policy_sha256"] or len(index["records"]) != 144:
                raise ValueError("Complete-day index binding mismatch")
            records = []
            for entry in index["records"]:
                record_path = Path(entry["record_path"])
                if N.P.sha256(record_path) != entry["record_sha256"]:
                    raise ValueError("Full-day acquisition record hash mismatch")
                records.append(json.loads(record_path.read_text()))
            roles = {scope:policy["roles_"+scope][date] for scope in ("Q17","Q18")}
            try:
                result = N.build_day(records,date,roles,policy,out / date,
                    start_ns=N.utc_ns(date+"T00:00:00Z")+30*N.NS,
                    end_ns=N.utc_ns(date+"T00:00:00Z")+86400*N.NS,policy_path=policy_path)
                checks = [N.verify_output(out / date / asset) for asset in ("BTC","ETH")]
                N.write_json(out / date / "readback_verification.json",checks)
                summaries.append(result)
                print(json.dumps({"date":date,"status":"normalized","paired_counts":{q:x["count"] for q,x in result["paired_common_cuts"].items()}}),flush=True)
            except ValueError as exc:
                rejection = {"date":date,"split_roles":roles,"status":"unavailable_under_frozen_strict_policy","reason":str(exc),"source_order_audit":inspect(records)}
                failures.append(rejection)
                N.write_json(out / (date+".unavailable.json"),rejection)
                print(json.dumps({"date":date,"status":"unavailable","reason":str(exc)}),flush=True)
            completed.add(date)
            provenance.append({"date":date,"acquisition_index_file":str(index_path),"acquisition_index_sha256":N.P.sha256(index_path)})
        if len(completed) < len(policy["roles_Q17"]):
            time.sleep(10)
    result = {"schema":"t008-paired-dataset-index/3","version":"2.3.0","origin":"exploratory_real","stage":"full_day_startup30",
        "policy_file":str(policy_path),"policy_sha256":N.P.sha256(policy_path),"acquisition_indexes":provenance,
        "normalizer_code_sha256":N.P.sha256(N.__file__),"runner_code_sha256":N.P.sha256(__file__),"dates":summaries,
        "contracts":[asset for day in summaries for asset in day["assets"]],"unavailable_dates":failures,
        "status":"all_dates_ready" if not failures else "partial_dates_unavailable_under_frozen_policy",
        "model_fits":0,"elapsed_seconds":time.perf_counter()-started,
        "source_scope":"Third-party archived full snapshots; source-quality-informed post-acquisition pre-fit fixed30s full-day adaptation; own exact-input review pending",
        "adaptation_class":policy["adaptation_class"],"fit_authorization_gate":policy["fit_authorization_gate"],
        "source_acquisition_policy_sha256":policy["supersedes_policy_sha256"]}
    index_path = out / "dataset_index.v2.3.0.json"
    N.write_json(index_path,result)
    output = index_path
    print(json.dumps({"status":"complete","index":str(output),"sha256":N.P.sha256(output),"elapsed_seconds":result["elapsed_seconds"]}),flush=True)


if __name__ == "__main__":
    main()
