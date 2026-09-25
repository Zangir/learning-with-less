"""Freeze and acquire a native BBO-change calendar without inspecting outcomes."""
from settings import OUT, NS, SEED, bind, now, pin, read, save, stamp, utc_ns
from acquire_sources import tardis_url, BASE_RETENTION, BASE_TRANSFER, DOCUMENTATION_RESERVE
from concurrent.futures import ThreadPoolExecutor
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import threading
import time
import urllib.error
import urllib.request

DEST = OUT / "bbo_native"
DATES = [f"2025-{m:02d}-01" for m in range(7,13)] + [f"2026-{m:02d}-01" for m in range(1,10)]
PAYLOAD_CAP = 16 * 1024**2
PANEL_CAP = 768 * 1024**2
LOCK = threading.Lock()
TOTAL = 0
RESERVED = 0


def acquire(date, offset, protocol_hash, channel="bbo"):
    global TOTAL, RESERVED
    folder = DEST / "raw" / date
    folder.mkdir(parents=True, exist_ok=True)
    receipt_path = folder / f"m{offset:04d}.json"
    if receipt_path.exists():
        record = read(receipt_path)
        if record["complete"] and record["status"] == 200:
            return record
        raise ValueError("Preserved incomplete slice requires a new explicit attempt")
    with LOCK:
        if TOTAL + RESERVED + PAYLOAD_CAP > PANEL_CAP:
            raise RuntimeError("Frozen panel transfer allocation exceeded")
        RESERVED += PAYLOAD_CAP
    start = time.monotonic()
    url = tardis_url(date, offset, channel)
    raw = folder / f"m{offset:04d}.raw.gz"
    record = dict(date=date, offset=offset, url=url, started_at=now(), status=None,
                  complete=False, received_bytes=0, protocol_sha256=protocol_hash)
    try:
        req = urllib.request.Request(url, headers={"Accept-Encoding":"gzip", "User-Agent":"Research-source-audit/1.0"})
        try:
            response = urllib.request.urlopen(req, timeout=30)
        except urllib.error.HTTPError as error:
            response = error
        with response, raw.open("xb") as output:
            record["status"] = response.status
            record["headers"] = dict(response.headers)
            while True:
                data = response.read(min(256*1024, PAYLOAD_CAP-record["received_bytes"]+1))
                if not data:
                    record["complete"] = True
                    break
                output.write(data)
                record["received_bytes"] += len(data)
                if record["received_bytes"] > PAYLOAD_CAP:
                    raise RuntimeError("Slice body cap exceeded")
        if record["status"] != 200:
            raise RuntimeError(f"HTTP {record['status']}; no retry without checkpoint")
        if record["headers"].get("Content-Encoding", "").lower() != "gzip":
            raise ValueError("Requested compressed source was not gzip")
        expect = "hyperliquid/"+date.replace("-", "/")+f"/{offset//60:02d}/{offset%60:02d}"
        if record["headers"].get("x-name") != expect or record["headers"].get("x-slice-size") != "10":
            raise ValueError("Remote partition mismatch")
        digest = hashlib.sha256()
        decoded = 0
        with gzip.open(raw, "rb") as stream:
            for chunk in iter(lambda: stream.read(1024*1024), b""):
                decoded += len(chunk)
                if decoded > 128*1024**2:
                    raise ValueError("Decoded bound exceeded")
                digest.update(chunk)
        record["decoded_bytes"] = decoded
        record["decoded_sha256"] = digest.hexdigest()
        record["raw"] = bind(raw)
    except Exception as error:
        record["complete"] = False
        record["error"] = type(error).__name__+": "+str(error)
    finally:
        with LOCK:
            TOTAL += record["received_bytes"]
            RESERVED -= PAYLOAD_CAP
        record["charged_bytes"] = 2*record["received_bytes"] + 16*1024
        record["finished_at"] = now()
        record["elapsed_seconds"] = time.monotonic()-start
        if raw.exists():
            record["raw"] = bind(raw)
        save(receipt_path, record)
    if not record["complete"]:
        raise RuntimeError(f"Source checkpoint required: {receipt_path}")
    return record


def main():
    global TOTAL
    proc = pin()
    started = time.monotonic()
    DEST.mkdir(exist_ok=True)
    protocol = DEST / "protocol.json"
    if not protocol.exists():
        save(protocol, dict(schema="t018-native-bbo-prospective/1", frozen_at=now(), seed=SEED,
            dates=DATES, train=DATES[:3], validation=DATES[3:4], test=DATES[4:12], later_transfer=DATES[12:],
            source="Tardis raw archive of native Hyperliquid on-change BBO WebSocket messages",
            selection="First fifteen complete monthly free dates after documented channel inception; roles chronological; no model/label/outcome inspection",
            old_panels="All old sampled-L2 panels preserved; new source and calendar",
            fields="Best bid/ask exact price, quantity, order count, provider receipt timestamp, native event timestamp, raw ordinal, disconnect markers",
            prefix="Fixed 30s at start of UTC day before order validation; record exclusions; no sorting",
            continuity="Blank disconnect marker begins new segment; two-clock monotonicity required within segment. On-change silence is not itself a gap.",
            observation="Receipt features/opportunities, exchange-clock labels and quote endpoints; provider says local timestamp is arrival timestamp; clock calibration not asserted",
            source_bounds="Full UTC receipt day, in-day event support only; consumer cannot cross discontinuities or use prehistory outside retained segment",
            max_compressed_bytes=PANEL_CAP, max_body_per_slice=PAYLOAD_CAP,
            expected_requests=len(DATES)*144, concurrency=2, max_runtime_seconds=3600,
            result_status="Source availability/admission only; no fitted models or scientific findings"))
    protocol_hash = bind(protocol)["sha256"]
    existing = list((DEST / "raw").glob("*/*.json"))
    TOTAL = sum(read(p)["received_bytes"] for p in existing)
    retained = sum(p.stat().st_size for p in OUT.rglob("*") if p.is_file())
    # Reserve a full additional compressed panel and its smaller columnar export.
    if BASE_RETENTION + retained + PANEL_CAP + 1200*1024**2 > 12*1024**3:
        raise RuntimeError("Insufficient retention for frozen raw+normalized allocation")
    if BASE_TRANSFER + DOCUMENTATION_RESERVE + 2*PANEL_CAP + len(DATES)*144*16384 > 8*1024**3:
        raise RuntimeError("Transfer preflight failed")
    if shutil.disk_usage(OUT).free < 50*1024**3 + PANEL_CAP:
        raise RuntimeError("Physical free-space floor failed")
    save(DEST / "preflight.json", dict(at=now(), current_t018_bytes=retained, baseline_retained=BASE_RETENTION,
        raw_reserve=PANEL_CAP, normalized_reserve=1200*1024**2, free_C_bytes=shutil.disk_usage(OUT).free,
        pid=proc.pid, cpu_affinity=proc.cpu_affinity(), protocol_sha256=protocol_hash))
    with ThreadPoolExecutor(max_workers=2) as pool:
        for date in DATES:
            records = list(pool.map(lambda offset: acquire(date, offset, protocol_hash), range(0,1440,10)))
            save(DEST / "day_indexes" / f"{date}.json", dict(date=date, protocol_sha256=protocol_hash, records=records))
            stamp(f"BBO native acquisition {date}: {len(records)} slices, {sum(r['received_bytes'] for r in records)} bytes")
            save(DEST / "progress.json", dict(at=now(), pid=proc.pid, last_complete_date=date,
                total_received_bytes=TOTAL, elapsed_seconds=time.monotonic()-started,
                all_complete=date==DATES[-1], protocol_sha256=protocol_hash))
    save(DEST / "acquisition_complete.json", dict(at=now(), elapsed_seconds=time.monotonic()-started,
        total_received_bytes=TOTAL, dates=DATES, protocol_sha256=protocol_hash))


if __name__ == "__main__":
    main()
