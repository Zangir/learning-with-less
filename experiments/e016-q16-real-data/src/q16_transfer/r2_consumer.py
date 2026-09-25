"""Q16 projection of the shared T-008 producer contract, preserving evidence origin."""
import json
from pathlib import Path

from admission import sha256
from r2_selector import audit_selection, freeze_anchors


class ScopeBlocked(ValueError):
    pass


def load_q16_bundle(contract_path, review_path=None):
    path = Path(contract_path)
    contract = json.loads(path.read_text())
    scope = contract.get("scopes", {}).get("Q16", {})
    if scope.get("admissible") is False or scope.get("decision") == "negative":
        raise ScopeBlocked("Producer explicitly denies Q16: " + str(scope.get("reasons", scope.get("reason"))))
    if contract.get("schema_version") == "q16-admission-v1":
        return _synthetic_producer_projection(path, contract)
    if contract.get("schema") != "t008-producer-state/2" or contract.get("producer") != "T-008":
        raise ScopeBlocked("Expected current shared producer interface")
    origin = contract.get("origin")
    if origin not in {"synthetic_integration", "exploratory_real", "eligible_empirical"}:
        raise ScopeBlocked("Unknown evidence origin")
    if scope.get("decision") != "affirmative":
        raise ScopeBlocked("No affirmative Q16 scope")
    if origin == "synthetic_integration":
        if contract.get("fixture_only") is not True or contract.get("purpose") != "fictional_integration_only":
            raise ScopeBlocked("Synthetic evidence must remain an explicit fixture")
    else:
        if contract.get("fixture_only") is not False:
            raise ScopeBlocked("Fixture evidence cannot become real evidence")
    payload_ref = contract["q16_payload"]
    payload_path = path.parent / payload_ref["file"]
    if payload_ref["sha256"] != sha256(payload_path):
        raise ScopeBlocked("Q16 payload hash mismatch")
    payload = json.loads(payload_path.read_text())
    if payload.get("origin") != origin:
        raise ScopeBlocked("Payload/contract origin mismatch")
    if payload.get("count_definition") != "positive_size_orders":
        raise ScopeBlocked("Physical lifecycle count is not the positive queue count")
    if origin == "eligible_empirical":
        if not review_path:
            raise ScopeBlocked("Independent coordinator review is required for empirical admission")
        review = json.loads(Path(review_path).read_text())
        if (review.get("role") != "coordinator" or review.get("decision") != "approved"
                or review.get("contract_sha256") != sha256(path)
                or review.get("scope") != "Q16" or not review.get("evidence")
                or review.get("origin") != "eligible_empirical" or review.get("fixture_only") is not False):
            raise ScopeBlocked("Review does not approve this exact Q16 contract")
    audit_selection(payload["candidates"], payload["selection"], limit=1000,
                    clock_kind="producer_availability_ns")
    selected = payload["selection"]["selected"]
    episodes = payload["episodes"]
    if [(e["candidate_id"], e["initial_raw_seq"]) for e in episodes] != [
            (a["candidate_id"], a["source_seq"]) for a in selected]:
        raise ScopeBlocked("Episode list differs from frozen anchors; no survivor replacement")
    candidates = {candidate["candidate_id"]: candidate for candidate in payload["candidates"]}
    for episode in episodes:
        candidate = candidates[episode["candidate_id"]]
        if (candidate["decision"] != episode["start_ns"]
                or candidate["available"] > episode["start_ns"]
                or episode["initial_available_ns"] != max([candidate["available"]] +
                    [e["available"] for e in candidate["past_certificates"]])):
            raise ScopeBlocked("Episode initial decision/evidence does not match frozen candidate lineage")
    return contract, payload


def _synthetic_producer_projection(path, contract):
    """Consume T-008's published Q16 fixture without fabricating a real review.

    The producer's separate Q16 ledger uses its declared legacy projection shape.
    Deriving a single constructed anchor is only permitted for synthetic fixtures;
    empirical origin must use the complete source-candidate interface above.
    """
    if (contract.get("origin") != "synthetic_integration" or contract.get("fixture_only") is not True
            or contract.get("issuer_task") != "T-008" or contract.get("decision") != "affirmative"):
        raise ScopeBlocked("Legacy projection is allowed only for labelled producer synthetic fixtures")
    episode_path = path.parent / "q16_synthetic_episodes.json"
    if sha256(episode_path) != contract["episodes_sha256"]:
        raise ScopeBlocked("Producer synthetic episode digest mismatch")
    episodes = json.loads(episode_path.read_text())
    candidates = []
    scope = contract["scope"]
    for episode in episodes:
        if episode.get("origin") != "synthetic_integration" or episode.get("fixture_only") is not True:
            raise ScopeBlocked("Synthetic projection contains a conflicting episode origin")
        if not scope["start_ns"] <= episode["start_ns"] < scope["end_ns"]:
            raise ScopeBlocked("Fixture starts outside the producer interval")
        if any(not scope["start_ns"] <= e["event_ns"] < scope["end_ns"] for e in episode["events"]):
            raise ScopeBlocked("Fixture event outside producer interval")
        identity = episode["episode_id"]
        episode["candidate_id"] = identity
        candidates.append({"candidate_id": identity, "source_seq": episode["anchor_source_ordinal"],
            "decision": episode["start_ns"], "available": episode["initial_available_ns"],
            "cohort_eligible": True, "eligibility_reasons": [],
            "past_certificates": [{"ref": "producer-authored-fictional-initial-state",
                                   "available": episode["initial_available_ns"]}]})
    payload = {"origin": "synthetic_integration", "quantity_quantum": contract["projection"]["quantity_quantum"],
               "count_definition": "positive_size_orders", "candidates": candidates,
               "selection": freeze_anchors(candidates, clock_kind="producer_availability_ns"),
               "episodes": episodes,
               "selection_lineage_scope": "constructed fixture list only; empirical extraction audit is separate"}
    return contract, payload


def run_bundle(contract_path, review_path=None, timeout_ms=2000):
    from r2_adapter import evaluate_episode
    contract, payload = load_q16_bundle(contract_path, review_path)
    origin = contract["origin"]
    results = []
    for episode in payload["episodes"]:
        try:
            result = evaluate_episode(episode, payload["quantity_quantum"], origin, timeout_ms)
        except ValueError as exc:
            result = {"episode_id": episode["episode_id"], "origin": origin,
                      "status": "model_invariant_failure", "reason": str(exc)}
        results.append(result)
    scored = sum(row["status"] == "scored" for row in results)
    return {"origin": origin, "contract_sha256": sha256(contract_path),
            "synthetic_episodes_scored": scored if origin == "synthetic_integration" else 0,
            "exploratory_real_episodes_scored": scored if origin == "exploratory_real" else 0,
            "eligible_empirical_episodes_scored": scored if origin == "eligible_empirical" else 0,
            "results": results,
            "real_replication_complete": False,
            "note": "An eligible development batch alone does not complete untouched-day evaluation"}
