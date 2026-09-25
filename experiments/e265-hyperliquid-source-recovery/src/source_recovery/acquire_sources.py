"""Metered no-auth source acquisition; raw response bytes are always retained."""
from settings import OUT, PRIOR, BASE, bind, now, pin, read, save, sha, stamp
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request

BASE_TRANSFER = 1_065_453_609
BASE_RETENTION = 9_564_717_070
DOCUMENTATION_RESERVE = 16 * 1024**2
TRANSFER_LIMIT = 8 * 1024**3
RETENTION_LIMIT = 12 * 1024**3
FREE_FLOOR = 50 * 1024**3
DEST = OUT / "acquisition"


def fetch(name, url, cap, metadata=False):
    DEST.mkdir(parents=True, exist_ok=True)
    receipt_path = DEST / (name + ".receipt.json")
    if receipt_path.exists():
        old = read(receipt_path)
        if old.get("complete") and sha(old["body"]["path"]) == old["body"]["sha256"]:
            return old
        raise ValueError("Existing incomplete attempt requires a separately named checkpoint")
    receipts = [read(p) for p in DEST.glob("*.receipt.json")]
    prior_charge = sum(r["charged_bytes"] for r in receipts)
    retained = sum(p.stat().st_size for p in OUT.rglob("*") if p.is_file())
    free = shutil.disk_usage(OUT).free
    if BASE_TRANSFER + DOCUMENTATION_RESERVE + prior_charge + cap * 2 > TRANSFER_LIMIT:
        raise RuntimeError("Transfer budget preflight failed")
    if BASE_RETENTION + retained + cap + 64 * 1024**2 > RETENTION_LIMIT or free < FREE_FLOOR + cap:
        raise RuntimeError("Retention/free-space preflight failed")
    started = time.monotonic()
    target = DEST / (name + ".body")
    record = dict(name=name, url=url, started_at=now(), cap_bytes=cap, metadata=metadata,
                  complete=False, received_bytes=0, status=None, headers={}, error=None)
    save(DEST / (name + ".started.json"), record)
    request = urllib.request.Request(url, headers={"Accept-Encoding":"identity" if metadata else "gzip", "User-Agent":"Research-source-audit/1.0"})
    try:
        try:
            response = urllib.request.urlopen(request, timeout=25)
        except urllib.error.HTTPError as error:
            response = error
        with response, target.open("xb") as stream:
            record["status"] = response.status
            record["headers"] = dict(response.headers)
            while True:
                chunk = response.read(min(256*1024, cap-record["received_bytes"]+1))
                if not chunk:
                    record["complete"] = True
                    break
                stream.write(chunk)
                record["received_bytes"] += len(chunk)
                if record["received_bytes"] > cap:
                    raise RuntimeError("Response cap reached; partial raw bytes retained")
    except Exception as error:
        record["error"] = type(error).__name__ + ": " + str(error)
    record["elapsed_seconds"] = time.monotonic()-started
    record["finished_at"] = now()
    record["charged_bytes"] = 2*record["received_bytes"] + 16*1024
    record["body"] = bind(target) if target.exists() else None
    save(receipt_path, record)
    stamp(f"Acquired {name}: HTTP {record['status']}, {record['received_bytes']} bytes, complete={record['complete']}")
    return record


def tardis_url(date, offset, channel):
    query = dict(from_=date+"T00:00:00.000Z", offset=offset,
                 filters=json.dumps([dict(channel=channel, symbols=["BTC","ETH"])], separators=(",", ":")),
                 sliceSize=10, compression="gzip")
    query["from"] = query.pop("from_")
    return "https://api.tardis.dev/v1/data-feeds/hyperliquid?"+urllib.parse.urlencode(query)


def main():
    pin()
    # Availability and byte pilot only. No features, outcomes, or fitted model.
    save(OUT / "bbo_pilot_protocol.json", dict(frozen_at=now(), date="2025-07-01", interval="00:00-00:10 UTC",
        reason="First complete free monthly date after documented on-change BBO channel start 2025-06-26",
        byte_cap=16*1024**2, source_only=True, intended_calendar="Jul2025-Jun2026: 3 train, 1 validation, 8 test; Jul-Sep2026 later transfer",
        all_comparisons_remain_pending_source_validation=True))
    fetch("bbo_20250701_m0000", tardis_url("2025-07-01", 0, "bbo"), 16*1024**2)
    docs = {
        "tardis_hyperliquid": "https://docs.tardis.dev/historical-data-details/hyperliquid.md",
        "tardis_http": "https://docs.tardis.dev/api/http-api-reference.md",
        "tardis_faq": "https://docs.tardis.dev/faq/general.md",
        "bitquery_tree": "https://api.github.com/repos/bitquery/blockchain-cloud-data-dump-sample/git/trees/main?recursive=1",
        "hyperreplay_tree": "https://api.github.com/repos/ConejoCapital/HyperReplay/git/trees/main?recursive=1",
        "dwellir_native_archive": "https://www.dwellir.com/docs/hyperliquid/historical-data",
        "official_l1_schemas": "https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/nodes/l1-data-schemas.md",
    }
    for name, url in docs.items():
        fetch(name, url, 2*1024**2, metadata=True)


if __name__ == "__main__":
    main()
