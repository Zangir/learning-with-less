"""Read-only consistency checks for the packaged T-023 evidence."""
from __future__ import annotations

import csv
import hashlib
import json
import shutil
from pathlib import Path


OUT = (Path(__file__).resolve().parents[1] / 'runtime')
LIMIT = 4 * 1024**3
RETAINED_LIMIT = 512 * 1024**2


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    required = [
        "manifest.json", "hourly_metrics.csv", "record_examples.json", "legacy_by_hour.png",
        "legacy_by_hour.html", "REPORT.md", "HANDOFF.md", "ENVIRONMENT.md", "ranges.jsonl",
        "tar_index.json", "processed_members.json", "checkpoint.json", "seen_oids.roaring",
        "live_orders.json", "run.log", "timing.log", "code/replay.py", "code/plot_result.py",
    ]
    missing = [name for name in required if not (OUT / name).is_file()]
    assert not missing, f"missing required artifacts: {missing}"

    manifest = json.loads((OUT / "manifest.json").read_text(encoding="utf-8"))
    checkpoint = json.loads((OUT / "checkpoint.json").read_text(encoding="utf-8"))
    processed = json.loads((OUT / "processed_members.json").read_text(encoding="utf-8"))
    with (OUT / "hourly_metrics.csv").open(encoding="utf-8", newline="") as source:
        rows = list(csv.DictReader(source))
    ranges = [json.loads(line) for line in (OUT / "ranges.jsonl").read_text(encoding="utf-8").splitlines() if line]

    completed = int(manifest["completed_hours"])
    assert completed == len(rows) == len(processed) == int(checkpoint["completed_hours"])
    assert [int(row["hour"]) for row in rows] == list(range(completed))
    assert manifest["completion_state"] == ("complete" if completed == 48 else "incomplete_chronological_prefix")
    assert manifest["operational_decision"] in ({"pass", "fail"} if completed == 48 else {"fail", "incomplete"})
    assert all(member["gzip_crc_verified"] is True for member in processed)
    assert all(item["status"] == 206 and item["verified_length"] is True for item in ranges)
    assert all(int(item["requested_bytes"]) == int(item["received_bytes"]) for item in ranges)
    assert int(manifest["transfer_bytes"]) == 512 + sum(int(item["received_bytes"]) for item in ranges)
    assert int(manifest["transfer_bytes"]) <= LIMIT

    range_by_offset = {int(item["offset"]): item for item in ranges}
    for member in processed:
        receipt = range_by_offset[int(member["data_offset"])]
        assert int(receipt["received_bytes"]) == int(member["size"])
        assert receipt["sha256_received"] == member["compressed_sha256"]

    assert sha256(OUT / "seen_oids.roaring") == checkpoint["seen_sha256"]
    assert sha256(OUT / "live_orders.json") == checkpoint["live_sha256"]
    if rows:
        assert int(rows[-1]["ever_seen_oids"]) == int(checkpoint["seen_count"])
        assert int(rows[-1]["tracked_live_orders"]) == int(checkpoint["live_count"])
    for row in rows:
        assert int(row["btc_events"]) == sum(int(row[f"{kind}_events"]) for kind in ("new", "update", "remove"))
        assert int(row["legacy_total"]) == int(row["legacy_update"]) + int(row["legacy_remove"])
    assert int(manifest["metrics"]["btc_events"]) == sum(int(row["btc_events"]) for row in rows)
    assert int(manifest["metrics"]["first_seen_legacy_total"]) == sum(int(row["legacy_total"]) for row in rows)
    assert manifest["full_book_certificate"] is False
    assert manifest["top_of_book_certificate"] is False
    assert manifest["price_band_certificate"] is False
    assert manifest["protocol_feasibility"]["full_48_hours_fit_range_ceiling"] is False

    for name, receipt in manifest["artifacts"].items():
        path = OUT / name
        assert path.stat().st_size == int(receipt["bytes"]), name
        assert sha256(path) == receipt["sha256"], name

    png = (OUT / "legacy_by_hour.png").read_bytes()
    assert png.startswith(b"\x89PNG\r\n\x1a\n") and len(png) > 10_000
    retained = sum(path.stat().st_size for path in OUT.rglob("*") if path.is_file())
    assert retained <= RETAINED_LIMIT
    assert shutil.disk_usage(OUT).free >= 50 * 1024**3
    print(json.dumps({
        "status": "PASS",
        "completed_hours": completed,
        "operational_decision": manifest["operational_decision"],
        "range_receipts": len(ranges),
        "transfer_bytes": manifest["transfer_bytes"],
        "retained_bytes": retained,
        "checkpoint_hashes_match": True,
        "artifact_hashes_match": True,
    }, indent=2))


if __name__ == "__main__":
    main()
