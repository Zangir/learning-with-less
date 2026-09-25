"""Byte-bounded paired raw acquisition, gated by the frozen root protocol."""
from concurrent.futures import ThreadPoolExecutor
import ctypes
import datetime as dt
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = Path(__file__).resolve().parent
PLAN = BASE / "tardis_hour00_preflight.json"
AUTH = BASE / "tardis_hour00_authorization.json"
OUT = BASE / "tardis_hour00"
LOCK = threading.Lock()
BODY_BYTES = 0
ATTEMPTS = 0
ACTIVE_RESERVE = 0
SEED = 20260919

def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()

def sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

def immutable(path, value):
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, indent=2)
        handle.write("\n")

def retain_bytes():
    return sum(p.stat().st_size for p in BASE.parent.rglob("*") if p.is_file())

def disk_check(plan):
    free = shutil.disk_usage(BASE).free
    retained = retain_bytes()
    if free < plan["physical_free_floor_bytes"]:
        raise RuntimeError("Physical free-space floor")
    if retained + plan["prior_new_retained_bytes"] >= plan["new_retention_cap_bytes"]:
        raise RuntimeError("New retained-byte cap")
    return free, retained

def diagnostics(path):
    digest = hashlib.sha256()
    decoded_bytes = 0
    lines = 0
    blank = []
    assets = {}
    first_receipt = last_receipt = None
    with gzip.open(path, "rb") as handle:
        for line in handle:
            digest.update(line)
            decoded_bytes += len(line)
            ordinal = lines
            lines += 1
            if decoded_bytes > 128 * 1024**2:
                raise RuntimeError("Per-response decoded safety cap")
            if not line.strip():
                blank.append(ordinal)
                continue
            receipt, message = line.split(b" ", 1)
            receipt = receipt.decode("ascii")
            first_receipt = first_receipt or receipt
            last_receipt = receipt
            obj = json.loads(message)
            if obj.get("channel") != "l2Book":
                raise RuntimeError("Unexpected raw channel")
            data = obj["data"]
            coin = data["coin"]
            if coin not in ("BTC", "ETH"):
                raise RuntimeError("Unexpected raw symbol")
            record = assets.setdefault(coin, {"rows": 0, "first_event_ms": data["time"],
                                             "last_event_ms": data["time"]})
            record["rows"] += 1
            record["last_event_ms"] = data["time"]
    return {"decoded_bytes": decoded_bytes, "decoded_sha256": digest.hexdigest(),
            "source_lines": lines, "blank_disconnect_lines": blank, "assets": assets,
            "first_provider_receipt": first_receipt, "last_provider_receipt": last_receipt}

def acquire(request, plan, shared):
    global BODY_BYTES, ATTEMPTS, ACTIVE_RESERVE
    successful = None
    for attempt in range(1, plan["maximum_attempts_per_request"] + 1):
        request_id = request["request_id"]
        basename = f"{request_id}.attempt{attempt}"
        record_path = OUT / f"{basename}.json"
        body_path = OUT / f"{basename}.raw.gz"
        if record_path.exists():
            existing = json.loads(record_path.read_text())
            if existing.get("completed"):
                return existing
            continue
        with LOCK:
            maximum_charged = (BODY_BYTES + ACTIVE_RESERVE + plan["per_response_body_cap_bytes"]
                               + (ATTEMPTS + 1) * plan["transport_reserve_per_attempt_bytes"])
            if maximum_charged > plan["charged_cap_bytes"]:
                raise RuntimeError("Global stage body cap cannot reserve next bounded request")
            free, retained = disk_check(plan)
            ACTIVE_RESERVE += plan["per_response_body_cap_bytes"]
            ATTEMPTS += 1
            began = {"request_id": request_id, "date": request["date"], "offset": request["offset"],
                     "role": request["role"], "url": request["url"], "attempt": attempt,
                     "started_at": now(), "physical_free_bytes": free, "new_r3_retained_bytes": retained,
                     "planned_max_body_bytes": plan["per_response_body_cap_bytes"],
                     "http_transport_reserve_bytes": plan["transport_reserve_per_attempt_bytes"], **shared}
            immutable(OUT / f"{basename}.started.json", began)
        record = dict(began)
        record["received_body_bytes"] = 0
        started = time.monotonic()
        try:
            req = urllib.request.Request(request["url"], headers={"Accept-Encoding": "gzip", "User-Agent": "T008-Research/1"})
            try:
                response = urllib.request.urlopen(req, timeout=45)
            except urllib.error.HTTPError as exc:
                response = exc
            with response, body_path.open("xb") as body:
                record["status"] = response.status
                record["response_headers"] = dict(response.headers)
                length = response.headers.get("Content-Length")
                if length is not None and int(length) > plan["per_response_body_cap_bytes"]:
                    raise RuntimeError("Declared response exceeds bounded request cap")
                while record["received_body_bytes"] < plan["per_response_body_cap_bytes"]:
                    try:
                        chunk = response.read(min(65536, plan["per_response_body_cap_bytes"] - record["received_body_bytes"]))
                    except Exception as read_error:
                        partial = getattr(read_error, "partial", b"")
                        if partial:
                            body.write(partial)
                            record["received_body_bytes"] += len(partial)
                        raise
                    if not chunk:
                        break
                    body.write(chunk)
                    record["received_body_bytes"] += len(chunk)
                if record["received_body_bytes"] == plan["per_response_body_cap_bytes"]:
                    raise RuntimeError("Response body cap reached")
            record["compressed_path"] = str(body_path)
            record["compressed_bytes"] = body_path.stat().st_size
            record["compressed_sha256"] = sha(body_path)
            if record["status"] != 200:
                raise RuntimeError(f"Provider status {record['status']}")
            headers = {name.lower(): value for name, value in record["response_headers"].items()}
            expected_name = ("hyperliquid/" + request["date"].replace("-", "/")
                             + f"/{request['offset'] // 60:02d}/{request['offset'] % 60:02d}")
            if headers.get("x-name") != expected_name or headers.get("x-slice-size") != "10":
                raise RuntimeError("Provider requested partition/slice headers disagree")
            if headers.get("content-encoding") != "gzip":
                raise RuntimeError("Expected gzip source encoding")
            if "content-length" in headers and int(headers["content-length"]) != record["compressed_bytes"]:
                raise RuntimeError("Provider Content-Length disagrees with retained response")
            record["partition_headers_verified"] = True
            record.update(diagnostics(body_path))
            if set(record["assets"]) != {"BTC", "ETH"}:
                raise RuntimeError("Paired assets not present")
            record["completed"] = True
            successful = record
        except Exception as exc:
            record["completed"] = False
            record["error"] = repr(exc)
            if body_path.exists():
                record["compressed_path"] = str(body_path)
                record["compressed_bytes"] = body_path.stat().st_size
                record["compressed_sha256"] = sha(body_path)
        finally:
            record["finished_at"] = now()
            record["elapsed_seconds"] = time.monotonic() - started
            with LOCK:
                BODY_BYTES += record["received_body_bytes"]
                ACTIVE_RESERVE -= plan["per_response_body_cap_bytes"]
                immutable(record_path, record)
                print(json.dumps({"request_id": request_id, "attempt": attempt, "completed": record["completed"],
                                  "body_bytes": record["received_body_bytes"], "stage_body_bytes": BODY_BYTES,
                                  "elapsed_seconds": round(record["elapsed_seconds"], 3), "error": record.get("error")}), flush=True)
        if successful:
            return successful
    return record

def main():
    global BODY_BYTES, ATTEMPTS
    if os.name == "nt":
        ctypes.windll.kernel32.SetProcessAffinityMask(ctypes.windll.kernel32.GetCurrentProcess(), 1)
    plan = json.loads(PLAN.read_text())
    auth = json.loads(AUTH.read_text())
    if auth["preflight_sha256"] != sha(PLAN):
        raise RuntimeError("Root authorization is not bound to this preflight")
    protocol_path = Path(plan["protocol_path"])
    if sha(protocol_path) != plan["protocol_sha256"] or auth["protocol_sha256"] != plan["protocol_sha256"]:
        raise RuntimeError("Protocol digest mismatch")
    OUT.mkdir(exist_ok=True)
    previous = [json.loads(p.read_text()) for p in OUT.glob("*.attempt*.json") if not p.name.endswith(".started.json")]
    BODY_BYTES = sum(r["received_body_bytes"] for r in previous)
    ATTEMPTS = len(previous)
    shared = {"preflight_path": str(PLAN), "preflight_sha256": sha(PLAN),
              "authorization_path": str(AUTH), "authorization_sha256": sha(AUTH),
              "protocol_path": str(protocol_path), "protocol_sha256": plan["protocol_sha256"],
              "acquisition_code_sha256": sha(Path(__file__)), "seed": SEED}
    started = now()
    with ThreadPoolExecutor(max_workers=2) as pool:
        records = list(pool.map(lambda request: acquire(request, plan, shared), plan["requests"]))
    free, retained = disk_check(plan)
    result = {"started_at": started, "finished_at": now(), **shared,
              "request_count": len(records), "completed_count": sum(r["completed"] for r in records),
              "requests": [{"request_id": r["request_id"], "record_path": str(OUT / f"{r['request_id']}.attempt{r['attempt']}.json"),
                            "record_sha256": sha(OUT / f"{r['request_id']}.attempt{r['attempt']}.json"),
                            "completed": r["completed"]} for r in records],
              "received_body_bytes_all_attempts": BODY_BYTES, "attempts_all": ATTEMPTS,
              "transport_reserve_bytes": ATTEMPTS * plan["transport_reserve_per_attempt_bytes"],
              "physical_free_bytes_at_finish": free, "new_r3_retained_bytes_at_finish": retained,
              "retained_payload_form": "compressed source and decoded digest; decoded raw bytes not separately retained"}
    immutable(OUT / "acquisition_index.json", result)
    print(json.dumps({"finished": result["finished_at"], "completed": result["completed_count"],
                      "requests": result["request_count"], "body_bytes": BODY_BYTES}), flush=True)

if __name__ == "__main__":
    main()
