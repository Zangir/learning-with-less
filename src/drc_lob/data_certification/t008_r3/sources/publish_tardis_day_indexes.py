"""Publish immutable complete-day acquisition indexes while later dates download."""
import datetime as dt
import hashlib
import json
from pathlib import Path

BASE = Path(__file__).resolve().parent
PROTOCOL = BASE.parent / "panel_protocol.v3.1.json"

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    protocol = json.loads(PROTOCOL.read_text())
    destination = BASE / "tardis_full_day" / "day_indexes"
    destination.mkdir(exist_ok=True)
    published = []
    for date, role in protocol["roles_Q17"].items():
        output = destination / f"{date}.json"
        if output.exists():
            continue
        sources = []
        for offset in range(0, 1440, 10):
            directory = BASE / ("tardis_hour00" if offset < 60 else "tardis_full_day")
            request_id = date.replace("-", "") + f"_m{offset:04d}"
            successful = []
            for path in sorted(directory.glob(f"{request_id}.attempt*.json")):
                if path.name.endswith(".started.json"):
                    continue
                record = json.loads(path.read_text())
                if record.get("completed"):
                    successful.append((path, record))
            if len(successful) != 1:
                break
            path, record = successful[0]
            if record["protocol_sha256"] != sha(PROTOCOL):
                raise RuntimeError("Mixed protocol in prospective day")
            sources.append({"request_id": request_id, "offset": offset, "record_path": str(path),
                            "record_sha256": sha(path), "compressed_path": record["compressed_path"],
                            "compressed_sha256": record["compressed_sha256"],
                            "decoded_sha256": record["decoded_sha256"],
                            "source_lines": record["source_lines"], "assets": record["assets"]})
        if len(sources) != 144:
            continue
        result = {"schema": "t008-tardis-complete-day-acquisition/3", "date": date, "role": role,
                  "role_Q18": protocol["roles_Q18"][date], "published_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                  "protocol_path": str(PROTOCOL), "protocol_sha256": sha(PROTOCOL),
                  "hour00_preflight_path": str(BASE / "tardis_hour00_preflight.json"),
                  "hour00_preflight_sha256": sha(BASE / "tardis_hour00_preflight.json"),
                  "full_day_preflight_path": str(BASE / "tardis_full_day_preflight.json"),
                  "full_day_preflight_sha256": sha(BASE / "tardis_full_day_preflight.json"),
                  "receipt_partition": "[00:00:00,24:00:00); analytic event boundaries require separate selection",
                  "raw_retention": "gzip source, decoded SHA; no decoded raw copy",
                  "records": sources}
        with output.open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(result, handle, indent=2)
            handle.write("\n")
        published.append({"date": date, "index_path": str(output), "index_sha256": sha(output)})
    print(json.dumps({"published": published}), flush=True)

if __name__ == "__main__":
    main()
