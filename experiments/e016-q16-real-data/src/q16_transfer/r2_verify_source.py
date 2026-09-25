"""Compare scalable outcomes against all 1,000 frozen original source histories."""
import hashlib
import json
from pathlib import Path
import resource
import time

from r2_symbolic import SymbolicQueue

ROOT = (Path(__file__).resolve().parents[2] / 'runtime')


def run():
    started = time.monotonic()
    source = ROOT / "original_baseline/logs/count_probe.json"
    original = json.loads(source.read_text())
    rows = []
    for record in original["records"]:
        queue = record["initial"][0]
        ahead = sum(q for q, tag in queue if not tag)
        events = [tuple(event["event"]) for event in record["events"]]
        counts = [len(queue)] + [event["observed_count"] for event in record["events"]]
        results = {}
        for arm, observed_counts, source_key in (("volume", None, "volume_only_fill_set"),
                                                  ("count", counts, "count_fill_set")):
            result = SymbolicQueue(ahead, 1, events, counts=observed_counts,
                                   probe_cancellable=False, timeout_ms=2000).project(enumerate_limit=2)
            expected = record["events"][-1][source_key]
            if result["status"] == "exact" and result["fill_values"] != expected:
                raise AssertionError((record["trial"], arm, expected, result))
            results[arm] = {"status": result["status"], "expected": expected,
                            "actual": result.get("fill_values"), "seconds": result["elapsed_seconds"]}
        rows.append({"trial": record["trial"], **results})
        if len(rows) % 50 == 0:
            print(json.dumps({"histories": len(rows), "seconds": time.monotonic() - started}), flush=True)
    exact = sum(row[arm]["status"] == "exact" for row in rows for arm in ("volume", "count"))
    result = {"origin": "synthetic_integration", "source_seed": 16029001,
              "source_comparator": "unchanged exhaustive source run saved in accepted r1",
              "input_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
              "histories": len(rows), "terminal_arm_comparisons": len(rows) * 2,
              "exact_comparisons": exact, "unresolved_comparisons": len(rows) * 2 - exact,
              "mismatches": 0, "all_passed": exact == len(rows) * 2,
              "elapsed_seconds": time.monotonic() - started,
              "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
              "rows": rows}
    (ROOT / "r2/symbolic_source_parity.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k != "rows"}, indent=2), flush=True)


if __name__ == "__main__":
    run()
