"""Clarify the Windows text-byte counter while preserving executed captures."""
import gzip
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
results = []
for directory in (ROOT, ROOT / "fast_live"):
    status_path = directory / "evidence/live_capture_status.json"
    status = json.loads(status_path.read_text())
    assert status["status"] == "completed"
    decoded_bytes = records = crlf_records = 0
    wire = hashlib.sha256()
    with gzip.open(directory / "data/live_capture.jsonl.gz", "rb") as stream:
        for line in stream:
            decoded_bytes += len(line)
            records += 1
            crlf_records += line.endswith(b"\r\n")
            wire.update(json.loads(line)["wire_text"].encode("utf-8"))
    assert records == status["messages"]
    assert wire.hexdigest() == status["wire_text_sha256_so_far"]
    assert decoded_bytes - status["uncompressed_envelope_bytes"] == crlf_records
    results.append({"route": status["route"], "status_sha256": hashlib.sha256(status_path.read_bytes()).hexdigest(),
        "messages": records, "wire_digest_matches": True, "gzip_read_through_eof": True,
        "status_uncompressed_envelope_bytes": status["uncompressed_envelope_bytes"],
        "actual_decompressed_file_bytes": decoded_bytes, "crlf_records": crlf_records,
        "counter_interpretation": "Serialized UTF-8 NDJSON length before platform newline translation",
        "accounting_impact": "No change to separately counted market wire_text/application bytes or physical retained bytes",
        "future_fix": "Repository collectors set newline='\\n'; executed collector artifact bytes remain preserved"})
output = {"schema": "t008-capture-metadata-erratum/1", "origin": "exploratory_real",
          "scope": "metadata counter interpretation only; no market data changed", "captures": results}
(ROOT / "evidence/capture_metadata_erratum.json").write_text(json.dumps(output, indent=2) + "\n")
print(json.dumps(output, indent=2))
