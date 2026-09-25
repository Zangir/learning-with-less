"""Independent post-acquisition metadata checks of all preserved first-hour records."""
import hashlib
import json
from pathlib import Path

BASE = Path(__file__).resolve().parent
PLAN = json.loads((BASE / "tardis_hour00_preflight.json").read_text())
INDEX = json.loads((BASE / "tardis_hour00" / "acquisition_index.json").read_text())
by_id = {row["request_id"]: row for row in PLAN["requests"]}
errors = []
for entry in INDEX["requests"]:
    path = Path(entry["record_path"])
    record = json.loads(path.read_text())
    request = by_id[entry["request_id"]]
    headers = {k.lower(): v for k, v in record["response_headers"].items()}
    expected_name = "hyperliquid/" + request["date"].replace("-", "/") + f"/00/{request['offset']:02d}"
    checks = {"record_hash": hashlib.sha256(path.read_bytes()).hexdigest() == entry["record_sha256"],
              "url": record["url"] == request["url"], "status": record["status"] == 200,
              "partition": headers.get("x-name") == expected_name,
              "slice_size": headers.get("x-slice-size") == "10", "gzip": headers.get("content-encoding") == "gzip",
              "length": int(headers["content-length"]) == record["compressed_bytes"],
              "retained_bytes": Path(record["compressed_path"]).stat().st_size == record["compressed_bytes"],
              "retained_hash": hashlib.sha256(Path(record["compressed_path"]).read_bytes()).hexdigest() == record["compressed_sha256"]}
    if not all(checks.values()):
        errors.append({"request_id": entry["request_id"], "checks": checks})
result = {"checked_requests": len(INDEX["requests"]), "all_pass": not errors, "errors": errors,
          "immutable_hour_index_sha256": hashlib.sha256((BASE / "tardis_hour00" / "acquisition_index.json").read_bytes()).hexdigest()}
with (BASE / "tardis_hour00_header_audit.json").open("x", encoding="utf-8", newline="\n") as handle:
    json.dump(result, handle, indent=2)
print(json.dumps(result))
