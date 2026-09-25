"""Bounded read-only raw prefix diagnostic; not a book replay or fill estimate."""
from collections import Counter
from decimal import Decimal
import gzip
import itertools
import json
from pathlib import Path
import time

from admission import sha256


def diagnose(sample_root, output):
    started = time.monotonic()
    manifest_path = sample_root / "sample_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    entry = next(row for row in manifest["files"] if row["archive"] == "book_diffs_202512.tar")
    source = sample_root / "data" / entry["file"]
    if sha256(source) != entry["sha256"]:
        raise ValueError("Input digest does not match frozen T-001 manifest")
    kinds, first_seen, precision, samples = Counter(), {}, Counter(), {}
    sizes, updates, raw_lines = [], 0, 0
    with gzip.open(source, "rt", encoding="utf-8") as stream:
        for index, line in enumerate(itertools.islice(stream, 200000)):
            raw_lines += 1
            row = json.loads(line)
            if row["coin"] != "BTC":
                continue
            change = row["raw_book_diff"]
            kind = "remove" if change == "remove" else next(iter(change))
            kinds[kind] += 1
            first_seen.setdefault(row["oid"], kind)
            q = None
            if kind == "new":
                q = Decimal(change["new"]["sz"])
                sizes.append(q)
                precision[-q.as_tuple().exponent] += 1
            elif kind == "update":
                old, new = Decimal(change["update"]["origSz"]), Decimal(change["update"]["newSz"])
                updates += int(old > new >= 0)
            if kind not in samples:
                samples[kind] = {"raw_line_zero_based": index, "coin": row["coin"], "side": row["side"],
                                 "price_usdc_per_btc": row["px"], "kind": kind,
                                 "raw_book_diff": change, "timestamp": None,
                                 "timestamp_note": "Absent in raw diff; not inferred"}
    threshold = {}
    for quantum in ("0.00001", "0.00000001"):
        lot = Decimal(quantum)
        on_grid = [q for q in sizes if q % lot == 0]
        threshold[quantum] = {
            "interpretation": "Illustrative arithmetic only; historical venue lot NOT certified",
            "new_order_count_on_grid": len(on_grid),
            "new_order_count_ge_18_units": sum(q >= 18 * lot for q in on_grid),
            "not_initial_queue_volume": True,
        }
    result = {"scope": "Observed raw-prefix diagnostics only; no real Q16 episode",
              "raw_lines": raw_lines, "btc_rows": sum(kinds.values()), "by_kind": dict(kinds),
              "first_seen_kind": dict(Counter(first_seen.values())),
              "positive_update_reductions": updates, "new_size_decimal_places": dict(precision),
              "illustrative_cap_scale": threshold, "nonidentifying_sample_rows": list(samples.values()),
              "input_file": str(source), "input_sha256": entry["sha256"],
              "input_manifest_sha256": sha256(manifest_path),
              "input_member": entry["member"], "source_record": manifest["record"],
              "seconds": time.monotonic() - started}
    output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    task = (Path(__file__).resolve().parents[2] / 'runtime')
    diagnose(task.parent / "T-001", task / "raw_diagnostics.json")
