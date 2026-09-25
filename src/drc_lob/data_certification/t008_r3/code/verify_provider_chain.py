"""Independent response/header/receipt audit of the retained paired acquisitions.

This read-only audit does not infer exchange authenticity or consumer performance.
It writes a new stage verification only after the stage index is frozen.
"""
from calendar import timegm
from collections import Counter
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import time
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]
NS = 1_000_000_000
POLICY_SHA = "84639e7bee796452cae075f4f349e61e8ff37ac4fd9d32685ba0f111baf3120d"


def sha(path):
    result = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def iso_ns(value):
    assert value.endswith("Z")
    whole, _, fraction = value[:-1].partition(".")
    assert len(fraction) <= 9 and (not fraction or fraction.isdigit())
    return timegm(datetime.strptime(whole, "%Y-%m-%dT%H:%M:%S").timetuple()) * NS + int(fraction.ljust(9, "0") or 0)


def verify_stage(stage):
    began = time.monotonic()
    directory = ROOT / "sources" / ("tardis_" + stage)
    index_path = directory / "acquisition_index.json"
    index = read(index_path)
    policy_path = ROOT / "panel_protocol.v3.1.json"
    policy = read(policy_path)
    assert sha(policy_path) == POLICY_SHA == index["protocol_sha256"]
    preflight_path = Path(index["preflight_path"])
    assert sha(preflight_path) == index["preflight_sha256"]
    plan = read(preflight_path)
    assert iso_ns(policy["frozen_at_utc"].replace("+00:00", "Z")) < iso_ns(index["started_at"].replace("+00:00", "Z"))
    assert index["completed_count"] == index["request_count"] == len(plan["requests"])
    planned = {r["request_id"]: r for r in plan["requests"]}
    assert len(planned) == len(index["requests"])
    previous_receipt = {}
    records = []
    for entry in index["requests"]:
        path = Path(entry["record_path"])
        assert sha(path) == entry["record_sha256"]
        record = read(path)
        request = planned[record["request_id"]]
        assert entry["request_id"] == record["request_id"]
        assert record["url"] == request["url"]
        assert record["protocol_sha256"] == POLICY_SHA
        assert record["date"] == request["date"] and record["offset"] == request["offset"]
        assert record["role"] == policy["roles_Q17"][record["date"]]
        assert record["status"] == 200 and record["completed"] is True
        parsed = urlsplit(record["url"])
        query = parse_qs(parsed.query)
        assert parsed.scheme == "https" and parsed.netloc == "api.tardis.dev"
        assert parsed.path == "/v1/data-feeds/hyperliquid"
        assert query["from"] == [record["date"] + "T00:00:00.000Z"]
        assert query["offset"] == [str(record["offset"])] and query["sliceSize"] == ["10"]
        assert json.loads(query["filters"][0]) == [{"channel": "l2Book", "symbols": ["BTC", "ETH"]}]
        headers = {key.lower(): value for key, value in record["response_headers"].items()}
        expected_name = "hyperliquid/" + record["date"].replace("-", "/") + f"/{record['offset']//60:02}/{record['offset']%60:02}"
        assert headers["x-name"] == expected_name and headers["x-slice-size"] == "10"
        assert headers["content-encoding"] == "gzip"
        compressed = Path(record["compressed_path"])
        assert compressed.stat().st_size == record["compressed_bytes"] == int(headers["content-length"])
        assert sha(compressed) == record["compressed_sha256"]
        start = iso_ns(record["date"] + "T00:00:00Z") + record["offset"] * 60 * NS
        stop = start + 600 * NS
        decoded_digest, decoded_bytes = hashlib.sha256(), 0
        assets, blank = Counter(), 0
        source_lines = 0
        event_outside_receipt_slice = Counter()
        with gzip.open(compressed, "rb") as stream:
            for line in stream:
                source_lines += 1
                decoded_digest.update(line)
                decoded_bytes += len(line)
                if not line.strip():
                    blank += 1
                    continue
                receipt, encoded = line.split(b" ", 1)
                observed = iso_ns(receipt.decode("ascii"))
                assert start <= observed < stop
                date = record["date"]
                assert observed >= previous_receipt.get(date, observed)
                previous_receipt[date] = observed
                envelope = json.loads(encoded)
                assert envelope["channel"] == "l2Book"
                data = envelope["data"]
                assert data["coin"] in ("BTC", "ETH")
                assets[data["coin"]] += 1
                event = data["time"] * 1_000_000
                if not start <= event < stop:
                    event_outside_receipt_slice[data["coin"]] += 1
        assert decoded_bytes == record["decoded_bytes"] and decoded_digest.hexdigest() == record["decoded_sha256"]
        assert source_lines == record["source_lines"] and blank == len(record["blank_disconnect_lines"])
        assert dict(assets) == {a: values["rows"] for a, values in record["assets"].items()}
        records.append({"request_id": record["request_id"], "compressed_bytes": compressed.stat().st_size,
                        "decoded_bytes": decoded_bytes, "source_lines": source_lines, "assets": dict(assets),
                        "disconnects": blank, "event_outside_receipt_slice": dict(event_outside_receipt_slice)})
    result = {"schema": "t008-provider-chain-independent-audit/1", "stage": stage, "passed": True,
              "created_at_utc": datetime.now(timezone.utc).isoformat(), "elapsed_seconds": time.monotonic() - began,
              "index_sha256": sha(index_path), "protocol_sha256": POLICY_SHA, "code_sha256": sha(Path(__file__)),
              "requests_verified": len(records), "records": records,
              "checks": ["Index-to-record immutable hashes", "Fixed policy/date/role/filter/slice request bindings",
                         "Response Content-Length, gzip, x-name and x-slice-size", "Compressed hash and gzip CRC to decoded hash",
                         "Provider receipt monotonicity and exact slice membership at nanosecond precision",
                         "Raw per-asset counts and disconnect markers"],
              "limits": "Third-party response integrity only; no exchange authentication, calibrated availability or numerical model review"}
    target = ROOT / "evidence" / (stage + "_provider_chain_independent.json")
    with target.open("x", encoding="utf-8") as output:
        json.dump(result, output, indent=2)
        output.write("\n")
    print(json.dumps({key: value for key, value in result.items() if key != "records"}, indent=2))


if __name__ == "__main__":
    for stage in ("hour00", "full_day"):
        if ((ROOT / "sources" / ("tardis_" + stage) / "acquisition_index.json").exists()
                and not (ROOT / "evidence" / (stage + "_provider_chain_independent.json")).exists()):
            verify_stage(stage)
