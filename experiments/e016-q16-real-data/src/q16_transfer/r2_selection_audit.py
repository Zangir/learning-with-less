"""Independent raw-source replay of the frozen selection before any outcomes."""
import gzip
import json
from pathlib import Path

from adapter import units
from admission import sha256
from r2_selector import audit_selection

BASE = (Path(__file__).resolve().parents[2] / 'runtime')
OUT = BASE / "T-009/r2"


def run():
    frozen = json.loads((OUT / "selection_frozen.json").read_text())
    manifest = json.loads((BASE / "T-001/sample_manifest.json").read_text())
    entry = next(row for row in manifest["files"] if row["archive"] == "book_diffs_202512.tar")
    source = BASE / "T-001/data" / entry["file"]
    if sha256(source) != frozen["input_sha256"]:
        raise ValueError("Input identity changed")
    candidates, eligible = [], 0
    with gzip.open(source, "rt") as stream:
        for seq, line in enumerate(stream):
            row = json.loads(line)
            change = row["raw_book_diff"]
            if row["coin"] != "BTC" or not isinstance(change, dict) or "new" not in change:
                continue
            positive = units(change["new"]["sz"], "0.00000001") > 0
            candidates.append({"candidate_id": f"anchor_{len(candidates) + 1:04d}", "source_seq": seq,
                "decision": seq, "available": seq, "cohort_eligible": positive,
                "eligibility_reasons": [] if positive else ["nonpositive new"],
                "past_certificates": [{"ref": "raw-observation-prefix", "available": seq}]})
            eligible += int(positive)
            if eligible == 1000:
                break
    if seq != frozen["cutoff_raw_seq"]:
        raise ValueError("Producer selection cutoff does not equal predeclared source replay cutoff")
    audit_selection(candidates, frozen["mechanical_selection"], limit=1000, clock_kind="source_ordinal")
    result = {"passed": True, "independent_source_replay": True, "candidate_count": len(candidates),
              "selected_count": eligible, "cutoff_raw_seq": seq,
              "selection_sha256": sha256(OUT / "selection_frozen.json"),
              "origin": "exploratory_real", "scientific_scope": "positive BTC observed-new source prefix only",
              "future_cancellation_fill_or_state_cap_used": False,
              "venue_queue_completeness_established": False}
    (OUT / "selection_audit.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    run()
