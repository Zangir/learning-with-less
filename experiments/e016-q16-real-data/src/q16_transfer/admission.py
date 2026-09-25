"""Fail-closed admission of a versioned, externally reviewed Q16 ledger."""
import hashlib
import json
from pathlib import Path

REQUIRED_CHECKS = (
    "complete_initial_level", "fifo_priority", "atomic_event_semantics",
    "exact_historical_quantity_lattice", "trade_status_conservation",
    "source_order_and_ties", "causal_admission", "cohort_without_future_selection",
)


class AdmissionBlocked(ValueError):
    pass


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_admitted(config):
    try:
        return _load_admitted(config)
    except AdmissionBlocked:
        raise
    except (ValueError, KeyError, TypeError, AttributeError, OSError) as exc:
        raise AdmissionBlocked("Malformed or unreadable admission evidence: " + str(exc)) from exc


def _load_admitted(config):
    missing = [key for key in ("contract_path", "coordinator_review_path", "episodes_path")
               if not config.get(key) or not Path(config[key]).is_file()]
    if missing:
        raise AdmissionBlocked("Missing required evidence paths: " + ", ".join(missing))
    contract = json.loads(Path(config["contract_path"]).read_text(encoding="utf-8-sig"))
    review = json.loads(Path(config["coordinator_review_path"]).read_text(encoding="utf-8-sig"))
    if contract.get("schema_version") != "q16-admission-v1" or not contract.get("version"):
        raise AdmissionBlocked("Missing versioned q16-admission-v1 contract")
    if contract.get("issuer_task") != "T-008" or contract.get("decision") != "affirmative":
        raise AdmissionBlocked("T-008 has not affirmatively certified this scope")
    if (review.get("decision") != "approved" or review.get("role") != "coordinator"
            or review.get("contract_sha256") != sha256(config["contract_path"])
            or not review.get("review_evidence")):
        raise AdmissionBlocked("Coordinator review must approve this exact contract hash")
    scope = contract.get("scope", {})
    if scope.get("experiment") != "E-016" or scope.get("coin") != "BTC" or scope.get("use") != "development_pilot":
        raise AdmissionBlocked("Contract scope is not the frozen E-016 BTC pilot")
    for key in REQUIRED_CHECKS:
        check = contract.get("checks", {}).get(key, {})
        if check.get("passed") is not True or not check.get("evidence"):
            raise AdmissionBlocked("Uncertified prerequisite: " + key)
    if contract.get("episodes_sha256") != sha256(config["episodes_path"]):
        raise AdmissionBlocked("Certified episode bytes do not match")
    episodes = json.loads(Path(config["episodes_path"]).read_text(encoding="utf-8-sig"))
    if len(episodes) > 1000 or len({e["episode_id"] for e in episodes}) != len(episodes):
        raise AdmissionBlocked("Duplicate episodes or >1000 preselected candidates")
    start, end = scope.get("start_ns"), scope.get("end_ns")
    if type(start) is not int or type(end) is not int or start >= end:
        raise AdmissionBlocked("Exact certified interval required")
    for episode in episodes:
        if not start <= episode["start_ns"] < end:
            raise AdmissionBlocked("Episode starts outside certified interval")
        if any(not start <= event["event_ns"] < end or event["available_ns"] >= end
               for event in episode["events"]):
            raise AdmissionBlocked("Episode horizon/release outside certified interval")
    return contract, episodes
