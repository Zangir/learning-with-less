"""Bounded, unauthenticated metadata retrieval for the T-008 r3 source search."""
import datetime as dt
import hashlib
import json
from pathlib import Path
import shutil
import urllib.error
import urllib.request

BASE = Path(__file__).resolve().parent
LIMIT = 1048576
LEDGER = BASE / "metadata_ledger.json"

def stamp():
    return dt.datetime.now(dt.timezone.utc).isoformat()

def fetch(name, url, cap=65536):
    ledger = json.loads(LEDGER.read_text()) if LEDGER.exists() else {
        "operation": "cycle1808:T-008:data-r3-reviewed-continuation",
        "authorization": "root authorized metadata bodies <=1 MiB, no market payload",
        "created_at": stamp(), "cap_bytes": LIMIT, "records": [],
        "web_research_bytes": "unmeasured; root documentation reserve required",
    }
    charged = sum(x.get("received_body_bytes", 0) for x in ledger["records"])
    if charged + cap > LIMIT:
        raise RuntimeError("Metadata budget would exceed authorization")
    record = {"name": name, "url": url, "started_at": stamp(),
              "planned_max_body_bytes": cap, "free_bytes": shutil.disk_usage(BASE).free}
    if record["free_bytes"] < 50 * 1024**3:
        raise RuntimeError("Physical free-space floor")
    ledger["records"].append(record)
    LEDGER.write_text(json.dumps(ledger, indent=2))
    req = urllib.request.Request(url, headers={"User-Agent": "T008-Research-Metadata/1", "Accept-Encoding": "identity"})
    try:
        response = urllib.request.urlopen(req, timeout=25)
    except urllib.error.HTTPError as exc:
        response = exc
    with response:
        record["http_status"] = response.status
        record["response_headers"] = dict(response.headers)
        body = response.read(cap)
        record["received_body_bytes"] = len(body)
        record["body_sha256"] = hashlib.sha256(body).hexdigest()
        record["truncated_at_cap"] = len(body) == cap
        (BASE / name).write_bytes(body)
    record["finished_at"] = stamp()
    ledger["total_body_bytes"] = sum(x.get("received_body_bytes", 0) for x in ledger["records"])
    LEDGER.write_text(json.dumps(ledger, indent=2))
    print(json.dumps({key: record[key] for key in ("name", "http_status", "received_body_bytes", "truncated_at_cap")}), flush=True)
    return body

def head(name, url):
    ledger = json.loads(LEDGER.read_text())
    record = {"name": name, "url": url, "method": "HEAD", "started_at": stamp(),
              "planned_max_body_bytes": 0, "received_body_bytes": 0}
    ledger["records"].append(record)
    LEDGER.write_text(json.dumps(ledger, indent=2))
    request = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "T008-Research-Metadata/1"})
    try:
        response = urllib.request.urlopen(request, timeout=15)
    except urllib.error.HTTPError as exc:
        response = exc
    with response:
        record["http_status"] = response.status
        record["response_headers"] = dict(response.headers)
    record["finished_at"] = stamp()
    LEDGER.write_text(json.dumps(ledger, indent=2))
    print(json.dumps(record), flush=True)
    return record

if __name__ == "__main__":
    fetch("hf_gionuibk_root.json", "https://huggingface.co/api/datasets/gionuibk/hyperliquidL2Book-v2/tree/main?recursive=false&expand=false")
    fetch("hf_gionuibk_catalog.json", "https://huggingface.co/datasets/gionuibk/hyperliquidL2Book-v2/raw/main/catalog.json")
    fetch("hf_gionuibk_refs.json", "https://huggingface.co/api/datasets/gionuibk/hyperliquidL2Book-v2/refs")
