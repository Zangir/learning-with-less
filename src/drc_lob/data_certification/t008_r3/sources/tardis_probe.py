"""One pre-authorized development slice; no prospective holdout is inspected."""
import datetime as dt
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import statistics
import urllib.error
import urllib.parse
import urllib.request

BASE = Path(__file__).resolve().parent
CAP = 2 * 1024**2
SEED = 20260919
PARAMS = {"from": "2025-12-01T00:00:00.000Z", "offset": 0,
          "filters": json.dumps([{"channel": "l2Book", "symbols": ["BTC", "ETH"]}], separators=(",", ":")),
          "sliceSize": 10, "compression": "gzip"}
URL = "https://api.tardis.dev/v1/data-feeds/hyperliquid?" + urllib.parse.urlencode(PARAMS)

def stamp():
    return dt.datetime.now(dt.timezone.utc).isoformat()

def sha(body):
    return hashlib.sha256(body).hexdigest()

def plan():
    return {"operation": "cycle1808:T-008:data-r3-reviewed-continuation", "created_at": stamp(),
            "purpose": "Development source/schema/cadence probe on already inspected December 1 interval; not new holdout",
            "source": "Third-party Tardis raw websocket archive claiming direct Hyperliquid capture",
            "url": URL, "requested": PARAMS, "auth": "none", "paid_access": False,
            "market_body_cap_bytes": CAP, "expected_body_bytes": 500000,
            "http_transport_reserve_bytes": 65536, "cumulative_prior_charged_bytes": 356470107,
            "global_transfer_cap_bytes": 8 * 1024**3, "new_retention_cap_bytes": 12 * 1024**3,
            "free_bytes": shutil.disk_usage(BASE).free, "physical_free_floor_bytes": 50 * 1024**3,
            "decode_cap_bytes": 100 * 1024**2, "seed": SEED,
            "provenance_limits": ["Provider claim, no cryptographic exchange authenticity",
                                  "Local timestamp provenance is provider collection; uncalibrated latency",
                                  "Clock cadence will not be extrapolated across dates without validation"]}

def run():
    preflight_path = BASE / "tardis_development_preflight.json"
    preflight = json.loads(preflight_path.read_text())
    approval = BASE / "tardis_development_authorization.json"
    if not approval.exists():
        raise RuntimeError("Root authorization record required before market transfer")
    if preflight["url"] != URL or preflight["market_body_cap_bytes"] != CAP:
        raise RuntimeError("Preflight mismatch")
    if shutil.disk_usage(BASE).free < 50 * 1024**3:
        raise RuntimeError("Free-space floor")
    record = {"started_at": stamp(), "url": URL, "request_headers": {"Accept-Encoding": "gzip"},
              "preflight_sha256": sha(preflight_path.read_bytes()),
              "authorization_sha256": sha(approval.read_bytes()),
              "code_sha256": sha(Path(__file__).read_bytes()), "received_body_bytes": 0}
    output = BASE / "tardis_development_acquisition.json"
    output.write_text(json.dumps(record, indent=2))
    req = urllib.request.Request(URL, headers={"User-Agent": "T008-Research/1", "Accept-Encoding": "gzip"})
    try:
        try:
            response = urllib.request.urlopen(req, timeout=45)
        except urllib.error.HTTPError as exc:
            response = exc
        with response:
            record["status"] = response.status
            record["response_headers"] = dict(response.headers)
            chunks = []
            while record["received_body_bytes"] < CAP:
                chunk = response.read(min(65536, CAP - record["received_body_bytes"]))
                if not chunk:
                    break
                chunks.append(chunk)
                record["received_body_bytes"] += len(chunk)
                output.write_text(json.dumps(record, indent=2))
            body = b"".join(chunks)
            record["body_sha256"] = sha(body)
            record["at_cap"] = len(body) == CAP
            (BASE / "tardis_20251201_0000_0010.raw.gz").write_bytes(body)
        if record["status"] != 200 or record["at_cap"]:
            raise RuntimeError("Non-success response or body cap reached")
        raw = gzip.decompress(body) if body[:2] == b"\x1f\x8b" else body
        if len(raw) > preflight["decode_cap_bytes"]:
            raise RuntimeError("Decode cap exceeded")
        raw_path = BASE / "tardis_20251201_0000_0010.raw.jsonl"
        raw_path.write_bytes(raw)
        record["decoded_bytes"] = len(raw)
        record["decoded_sha256"] = sha(raw)
        times = {"BTC": [], "ETH": []}
        shapes = {"BTC": set(), "ETH": set()}
        channels = {}
        blank = 0
        for line in raw.splitlines():
            if not line.strip():
                blank += 1
                continue
            local, message = line.split(b" ", 1)
            msg = json.loads(message)
            channel = msg.get("channel")
            channels[channel] = channels.get(channel, 0) + 1
            if channel != "l2Book":
                continue
            data = msg["data"]
            coin = data["coin"]
            if coin not in times:
                raise RuntimeError("Unrequested asset")
            times[coin].append(data["time"])
            shapes[coin].add(tuple(len(side) for side in data["levels"]))
        diagnostics = {"channels": channels, "blank_disconnect_markers": blank, "assets": {}}
        for coin, values in times.items():
            gaps = [b-a for a, b in zip(values, values[1:])]
            diagnostics["assets"][coin] = {"rows": len(values), "first_event_ms": values[0] if values else None,
                "last_event_ms": values[-1] if values else None, "shapes": sorted(shapes[coin]),
                "min_gap_ms": min(gaps) if gaps else None, "median_gap_ms": statistics.median(gaps) if gaps else None,
                "max_gap_ms": max(gaps) if gaps else None, "negative_gaps": sum(g < 0 for g in gaps)}
        (BASE / "tardis_development_diagnostics.json").write_text(json.dumps(diagnostics, indent=2))
        record["completed"] = True
    except Exception as exc:
        record["error"] = repr(exc)
        raise
    finally:
        record["finished_at"] = stamp()
        output.write_text(json.dumps(record, indent=2))

if __name__ == "__main__":
    run()
