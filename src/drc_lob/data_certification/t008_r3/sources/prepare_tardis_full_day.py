"""Freeze the already declared full-day expansion after a bounded byte pilot."""
import datetime as dt
import hashlib
import json
from pathlib import Path
import shutil
import urllib.parse

BASE = Path(__file__).resolve().parent
PROTOCOL = BASE.parent / "panel_protocol.v3.1.json"
EXPECTED = "84639e7bee796452cae075f4f349e61e8ff37ac4fd9d32685ba0f111baf3120d"
HOUR_INDEX = BASE / "tardis_hour00" / "acquisition_index.json"

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def write(path, value):
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, indent=2)
        handle.write("\n")

assert sha(PROTOCOL) == EXPECTED
protocol = json.loads(PROTOCOL.read_text())
hour = json.loads(HOUR_INDEX.read_text())
assert hour["completed_count"] == hour["request_count"] == 72
requests = []
for date, role in protocol["roles_Q17"].items():
    for offset in range(60, 1440, 10):
        params = {"from": date + "T00:00:00.000Z", "offset": offset, "sliceSize": 10,
                  "filters": json.dumps([{"channel": "l2Book", "symbols": ["BTC", "ETH"]}], separators=(",", ":")),
                  "compression": "gzip"}
        requests.append({"request_id": date.replace("-", "") + f"_m{offset:04d}", "date": date,
                         "offset": offset, "role": role, "role_Q18": protocol["roles_Q18"][date],
                         "url": protocol["endpoint"] + "?" + urllib.parse.urlencode(params)})
preflight = {"stage": "full_day_remaining", "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    "protocol_path": str(PROTOCOL), "protocol_sha256": EXPECTED,
    "reuse_hour00_index_path": str(HOUR_INDEX), "reuse_hour00_index_sha256": sha(HOUR_INDEX),
    "conservative_charged_baseline_before_stage": 390292584,
    "charged_cap_bytes": 2 * 1024**3, "cap_includes_http_reserves": True,
    "per_response_body_cap_bytes": 4 * 1024**2, "transport_reserve_per_attempt_bytes": 65536,
    "maximum_attempts_per_request": 2,
    "expected_body_bytes": 23 * hour["received_body_bytes_all_attempts"],
    "expected_http_reserve_bytes": 1656 * 65536, "request_count": 1656,
    "physical_free_bytes": shutil.disk_usage(BASE).free, "physical_free_floor_bytes": 50 * 1024**3,
    "prior_new_retained_bytes": 158144847, "new_retention_cap_bytes": 12 * 1024**3,
    "new_r3_retained_bytes": sum(p.stat().st_size for p in BASE.parent.rglob("*") if p.is_file()),
    "global_transfer_cap_bytes": 8 * 1024**3, "io_threads": 2, "cpu_affinity_cores": 1,
    "seed": 20260919, "initial_tmux_timeout_seconds": 3600,
    "hour00_elapsed_seconds": (dt.datetime.fromisoformat(hour["finished_at"]) - dt.datetime.fromisoformat(hour["started_at"])).total_seconds(),
    "expansion_selection": "Frozen full-day estimand/calendar precede first-hour acquisition; expansion triggered only by measured bytes/time/rate/resource fit, without model or label outcomes",
    "raw_retention": "gzip source and streamed decoded digest; no separate decoded copy",
    "acquisition_code_path": str(BASE / "acquire_tardis_panel.py"),
    "acquisition_code_sha256": sha(BASE / "acquire_tardis_panel.py"),
    "execution_entry_path": str(BASE / "acquire_tardis_full_day.py"),
    "execution_entry_sha256": sha(BASE / "acquire_tardis_full_day.py"),
    "requests": requests}
assert preflight["physical_free_bytes"] > preflight["physical_free_floor_bytes"]
assert preflight["conservative_charged_baseline_before_stage"] + preflight["charged_cap_bytes"] < preflight["global_transfer_cap_bytes"]
assert len(requests) == 1656
preflight_path = BASE / "tardis_full_day_preflight.json"
write(preflight_path, preflight)
write(BASE / "tardis_full_day_authorization.json", {
    "recorded_at": dt.datetime.now(dt.timezone.utc).isoformat(), "authorizer": "root and coordinator",
    "operation": "cycle1808:T-008:data-r3-reviewed-continuation", "protocol_sha256": EXPECTED,
    "preflight_sha256": sha(preflight_path),
    "authorization": "1656 remaining fixed-date paired BTC/ETH10minute slices;2GiBtotal stagecap includingallattemptHTTPreserves;4MiBbodycap;max2attempts;2IOthreads1CPU;1hinitialtmuxlimit;retainonlygzipanddecodedSHA"})
print(json.dumps({"preflight_sha256": sha(preflight_path), "request_count": len(requests),
                  "physical_free_bytes": preflight["physical_free_bytes"],
                  "expected_charged_bytes": preflight["expected_body_bytes"] + preflight["expected_http_reserve_bytes"]}))
