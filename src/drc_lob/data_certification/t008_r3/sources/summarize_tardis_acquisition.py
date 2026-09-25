"""Verify frozen acquisition bindings and report measured source-only resources."""
from collections import defaultdict
import ctypes
import datetime as dt
import hashlib
import json
import os
from pathlib import Path

BASE = Path(__file__).resolve().parent
if os.name == "nt":
    kernel = ctypes.windll.kernel32
    kernel.GetCurrentProcess.restype = ctypes.c_void_p
    kernel.SetProcessAffinityMask.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
    kernel.SetProcessAffinityMask.restype = ctypes.c_int
    if not kernel.SetProcessAffinityMask(kernel.GetCurrentProcess(), 1):
        raise RuntimeError("Unable to enforce one-CPU affinity")

def sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()

def main():
    summary = {"created_at": dt.datetime.now(dt.timezone.utc).isoformat(), "stages": {}, "dates": {}, "errors": []}
    dates = defaultdict(lambda: {"requests": 0, "compressed_bytes": 0, "decoded_bytes": 0,
                                  "source_lines": 0, "disconnect_markers": 0, "BTC_rows": 0, "ETH_rows": 0})
    for stage in ("tardis_hour00", "tardis_full_day"):
        index_path = BASE / stage / "acquisition_index.json"
        index = json.loads(index_path.read_text())
        request_plan = json.loads(Path(index["preflight_path"]).read_text())
        planned = {r["request_id"]: r for r in request_plan["requests"]}
        stage_summary = {key: index[key] for key in ("request_count", "completed_count", "received_body_bytes_all_attempts",
                         "transport_reserve_bytes", "attempts_all", "started_at", "finished_at")}
        stage_summary["index_sha256"] = sha(index_path)
        stage_summary["elapsed_seconds"] = (dt.datetime.fromisoformat(index["finished_at"]) - dt.datetime.fromisoformat(index["started_at"])).total_seconds()
        stage_summary["charged_bytes"] = index["received_body_bytes_all_attempts"] + index["transport_reserve_bytes"]
        summary["stages"][stage] = stage_summary
        assert sha(Path(index["preflight_path"])) == index["preflight_sha256"]
        assert sha(Path(index["authorization_path"])) == index["authorization_sha256"]
        assert sha(Path(index["protocol_path"])) == index["protocol_sha256"]
        attempts = [json.loads(p.read_text()) for p in (BASE / stage).glob("*.attempt*.json") if not p.name.endswith(".started.json")]
        assert sum(r["received_body_bytes"] for r in attempts) == index["received_body_bytes_all_attempts"]
        assert len(attempts) == index["attempts_all"]
        for entry in index["requests"]:
            record_path = Path(entry["record_path"])
            assert sha(record_path) == entry["record_sha256"]
            record = json.loads(record_path.read_text())
            req = planned[record["request_id"]]
            if not record["completed"]:
                summary["errors"].append({"request_id": record["request_id"], "error": record.get("error")})
                continue
            body = Path(record["compressed_path"])
            headers = {key.lower(): value for key, value in record["response_headers"].items()}
            expected = "hyperliquid/" + req["date"].replace("-", "/") + f"/{req['offset']//60:02d}/{req['offset']%60:02d}"
            assert record["url"] == req["url"] and record["date"] == req["date"] and record["offset"] == req["offset"]
            assert headers.get("x-name") == expected and headers.get("x-slice-size") == "10"
            assert headers.get("content-encoding") == "gzip"
            assert record["compressed_bytes"] == body.stat().st_size
            if "content-length" in headers:
                assert int(headers["content-length"]) == record["compressed_bytes"]
            assert sha(body) == record["compressed_sha256"]
            row = dates[record["date"]]
            row["requests"] += 1
            row["compressed_bytes"] += record["compressed_bytes"]
            row["decoded_bytes"] += record["decoded_bytes"]
            row["source_lines"] += record["source_lines"]
            row["disconnect_markers"] += len(record["blank_disconnect_lines"])
            for coin in ("BTC", "ETH"):
                row[f"{coin}_rows"] += record["assets"][coin]["rows"]
    summary["dates"] = dict(dates)
    summary["verified_complete_paired_dates"] = sum(row["requests"] == 144 for row in dates.values())
    summary["panel_charged_bytes"] = sum(row["charged_bytes"] for row in summary["stages"].values())
    summary["cumulative_charged_bytes"] = 360575932 + summary["panel_charged_bytes"]
    summary["conservative_accounting"] = "Measured response bodies plus64KiB perattempt HTTPreserve; baseline includes r2,development,metadata and2MiB webdocumentationreserve; not NIC measurement"
    summary["integrity_scope"] = "Fresh compressed SHA checks and frozenrecord/request/header/plan bindings; decoded SHA originally computed throughgzip EOF and independentlycheckedbynormalizer"
    output = BASE / "paired_panel_acquisition_summary.json"
    with output.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(summary, handle, indent=2)
        handle.write("\n")
    print(json.dumps(summary, indent=2))

if __name__ == "__main__":
    main()
