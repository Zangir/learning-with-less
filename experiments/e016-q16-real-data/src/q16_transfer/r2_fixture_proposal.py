"""Consumer-authored fixture proposal for producer adoption; no issuer approval."""
import json
from pathlib import Path

from r2_selector import freeze_anchors
from test_adapter import fixture


def payload():
    episode = fixture()
    episode["candidate_id"] = "fixture-anchor-1"
    episode["events"][0]["diffs"][0]["raw_book_diff"] = {"update": {"origSz": "2", "newSz": "0"}}
    for event in episode["events"][1:]:
        for row in event["diffs"]:
            row["raw_seq"] += 1
    episode["events"].insert(1, {"kind": "administrative", "event_ns": 21, "available_ns": 21,
        "evidence_refs": ["synthetic-zero-cleanup"], "fills": [], "diffs": [{"raw_seq": 3,
        "coin": "BTC", "side": "B", "px": "100", "oid": "a", "raw_book_diff": "remove"}]})
    candidates = [{"candidate_id": "fixture-anchor-1", "source_seq": 0, "decision": 0,
                   "available": 0, "cohort_eligible": True, "eligibility_reasons": [],
                   "past_certificates": [{"ref": "fictional-complete-initial-level", "available": 0}]}]
    return {"origin": "synthetic_integration", "authored_by": "T-009",
            "status": "consumer_proposal_pending_producer_adoption",
            "quantity_quantum": "1", "count_definition": "positive_size_orders",
            "candidates": candidates,
            "selection": freeze_anchors(candidates, clock_kind="producer_availability_ns"),
            "episodes": [episode]}


if __name__ == "__main__":
    root = (Path(__file__).resolve().parents[2] / 'runtime')
    (root / "q16_fixture_proposal.json").write_text(json.dumps(payload(), indent=2) + "\n")
