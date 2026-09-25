"""Freeze the explicitly authorized calendar and bounded first-hour requests."""
import datetime as dt
import hashlib
import json
from pathlib import Path
import shutil
import urllib.parse

BASE = Path(__file__).resolve().parent
PROTOCOL = BASE.parent / "panel_protocol.v3.1.json"
EXPECTED = "84639e7bee796452cae075f4f349e61e8ff37ac4fd9d32685ba0f111baf3120d"

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def write(path, value):
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, indent=2)
        handle.write("\n")

if sha(PROTOCOL) != EXPECTED:
    raise RuntimeError("Exact authorized protocol hash mismatch")
protocol = json.loads(PROTOCOL.read_text())
metadata_path = BASE / "metadata_ledger.json"
metadata = json.loads(metadata_path.read_text())
metadata_freeze = BASE / "metadata_ledger.frozen.json"
with metadata_freeze.open("xb") as handle:
    handle.write(metadata_path.read_bytes())
requests = []
for date, role in protocol["roles_Q17"].items():
    for offset in (0, 10, 20, 30, 40, 50):
        params = {"from": date + "T00:00:00.000Z", "offset": offset, "sliceSize": 10,
                  "filters": json.dumps([{"channel": "l2Book", "symbols": ["BTC", "ETH"]}], separators=(",", ":")),
                  "compression": "gzip"}
        requests.append({"request_id": date.replace("-", "") + f"_m{offset:04d}", "date": date,
                         "offset": offset, "role": role, "role_Q18": protocol["roles_Q18"][date],
                         "url": protocol["endpoint"] + "?" + urllib.parse.urlencode(params)})
metadata_reserve = len(metadata["records"]) * 65536
preflight = {"stage": "hour00", "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    "protocol_path": str(PROTOCOL), "protocol_sha256": EXPECTED,
    "metadata_ledger_path": str(metadata_freeze), "metadata_ledger_sha256": sha(metadata_freeze),
    "metadata_body_bytes": metadata["total_body_bytes"], "metadata_http_reserve_bytes": metadata_reserve,
    "development_probe_body_bytes": 550781, "development_probe_http_reserve_bytes": 65536,
    "documentation_tool_reserve_bytes": 2 * 1024**2,
    "prior_r2_charge_bytes": 356470107,
    "conservative_charged_baseline_before_stage": (356470107 + metadata["total_body_bytes"]
        + metadata_reserve + 550781 + 65536 + 2 * 1024**2),
    "charged_cap_bytes": 256 * 1024**2, "cap_includes_http_reserves": True,
    "per_response_body_cap_bytes": 4 * 1024**2, "transport_reserve_per_attempt_bytes": 65536,
    "maximum_attempts_per_request": 2, "expected_body_bytes": 550781 * 6 * 12,
    "expected_http_reserve_bytes": 72 * 65536, "request_count": 72,
    "physical_free_bytes": shutil.disk_usage(BASE).free, "physical_free_floor_bytes": 50 * 1024**3,
    "prior_new_retained_bytes": 158144847, "new_retention_cap_bytes": 12 * 1024**3,
    "new_r3_retained_bytes": sum(p.stat().st_size for p in BASE.parent.rglob("*") if p.is_file()),
    "global_transfer_cap_bytes": 8 * 1024**3, "io_threads": 2, "cpu_affinity_cores": 1,
    "seed": 20260919, "initial_tmux_timeout_seconds": 3600,
    "raw_retention": "gzip source and streamed decoded digest; no separate full decoded copy",
    "requests": requests}
if preflight["physical_free_bytes"] < preflight["physical_free_floor_bytes"]:
    raise RuntimeError("Physical free floor")
if preflight["conservative_charged_baseline_before_stage"] + preflight["charged_cap_bytes"] > preflight["global_transfer_cap_bytes"]:
    raise RuntimeError("Global transfer cap")
preflight_path = BASE / "tardis_hour00_preflight.json"
write(preflight_path, preflight)
write(BASE / "tardis_hour00_authorization.json", {
    "recorded_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    "authorizer": "root within explicit coordinator panel authorization",
    "operation": "cycle1808:T-008:data-r3-reviewed-continuation",
    "protocol_sha256": EXPECTED, "preflight_sha256": sha(preflight_path),
    "authorization": "72 fixed hour00 paired BTC/ETH requests, 256MiB total including64KiB reserve perattempt,4MiB responsebodycap,atmost2attempts,2IOthreads on1CPU; full-day expansion separate preflight"})
print(json.dumps({"preflight_sha256": sha(preflight_path), "request_count": len(requests),
                  "physical_free_bytes": preflight["physical_free_bytes"],
                  "charged_baseline": preflight["conservative_charged_baseline_before_stage"]}))
