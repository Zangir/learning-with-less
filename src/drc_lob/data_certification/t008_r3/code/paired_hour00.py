"""Fixed twelve-date first-hour normalization; no acquisition or model fits."""
import json
from pathlib import Path
import sys
import time
import os
sys.dont_write_bytecode = True
import paired_normalize as N
from paired_source_audit import inspect


def main():
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        affinity = ctypes.windll.kernel32.SetProcessAffinityMask
        affinity.argtypes = (wintypes.HANDLE, ctypes.c_size_t)
        if not affinity(wintypes.HANDLE(-1), 2):
            raise OSError("Could not enforce one logical CPU for normalizer")
    started = time.perf_counter()
    policy_path = N.ROOT / "panel_protocol.v3.1.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8-sig"))
    index_path = N.ROOT / "sources/tardis_hour00/acquisition_index.json"
    index = json.loads(index_path.read_text())
    if index["protocol_sha256"] != N.P.sha256(policy_path) or index["completed_count"] != 72:
        raise ValueError("Incomplete or differently declared acquisition index")
    records = []
    for entry in index["requests"]:
        path = Path(entry["record_path"])
        if not entry["completed"] or N.P.sha256(path) != entry["record_sha256"]:
            raise ValueError("Acquisition record hash/completion mismatch")
        records.append(json.loads(path.read_text()))
    out = N.ROOT / "interface/hour00"
    if (out / "dataset_index.v2.2.0.json").exists():
        raise ValueError("Immutable hour00 index already exists")
    out.mkdir(exist_ok=True)
    N.emit_schema(N.ROOT / "interface")
    summaries, failures = [], []
    for date in policy["roles_Q17"]:
        selected = [record for record in records if record["date"] == date]
        roles = {scope: policy["roles_"+scope][date] for scope in ("Q17", "Q18")}
        try:
            if (out / date / "paired_summary.json").exists():
                result = json.loads((out / date / "paired_summary.json").read_text())
                if any(json.loads(Path(asset["contract_file"]).read_text())["policy_sha256"] != N.P.sha256(policy_path) for asset in result["assets"]):
                    raise ValueError("Existing preserved date uses a different policy")
            else:
                result = N.build_day(selected, date, roles, policy, out / date, policy_path=policy_path)
            checks = [N.verify_output(out / date / asset) for asset in ("BTC", "ETH")]
            if not (out / date / "readback_verification.json").exists():
                N.write_json(out / date / "readback_verification.json", checks)
            summaries.append(result)
            print(json.dumps({"date": date,"paired_counts": {q: data["count"] for q,data in result["paired_common_cuts"].items()},"readback":True}), flush=True)
        except ValueError as exc:
            rejection = {"date":date,"split_roles":roles,"status":"unavailable_under_frozen_strict_policy","reason":str(exc),"source_order_audit":inspect(selected)}
            failures.append(rejection)
            N.write_json(out / (date+".unavailable.json"), rejection)
            print(json.dumps({"date":date,"status":"unavailable","reason":str(exc)}),flush=True)
    result = {"schema":"t008-paired-dataset-index/3", "version":"2.2.0", "origin":"exploratory_real", "stage":"hour00",
        "policy_file":str(policy_path), "policy_sha256":N.P.sha256(policy_path), "acquisition_index_file":str(index_path),
        "acquisition_index_sha256":N.P.sha256(index_path), "normalizer_code_sha256":N.P.sha256(N.__file__),
        "runner_code_sha256":N.P.sha256(__file__), "dates":summaries,
        "contracts":[asset for day in summaries for asset in day["assets"]], "unavailable_dates":failures,
        "status":"all_dates_ready" if not failures else "partial_dates_unavailable_under_frozen_policy",
        "model_fits":0, "elapsed_seconds":time.perf_counter()-started,
        "source_scope":"Third-party archived full snapshots; paired first-hour period adaptation, independent review pending"}
    N.write_json(out / "dataset_index.v2.2.0.json", result)
    print(json.dumps({"status":"complete", "index_sha256":N.P.sha256(out / "dataset_index.v2.2.0.json"),"elapsed_seconds":result["elapsed_seconds"]}), flush=True)


if __name__ == "__main__":
    main()
