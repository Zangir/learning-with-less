"""Fail closed on absent, negative, stale or unreviewed certificates.

This is the proposed T-010 adapter interface, not a certificate issued by T-008.
Hashes provide integrity and review binding, not cryptographic authentication.
"""
import hashlib
import json
from pathlib import Path
from datetime import datetime, timezone
from .protocol import PROTOCOL, LABEL_SPEC, digest_json

REQUIRED = ("bbo_price_complete", "bbo_size_complete", "event_clock_certified",
            "availability_causal", "atomic_tie_order_certified", "continuous_coverage",
            "admission_uses_only_available_evidence", "no_retrospective_sort")
PILOT_START_NS = int(datetime(2025, 12, 1, tzinfo=timezone.utc).timestamp())*1_000_000_000
PILOT_END_NS = PILOT_START_NS+3600*1_000_000_000


def implementation_sha256():
    root = Path(__file__).parent
    return digest_json({p.name: sha256(p) for p in sorted(root.glob("*.py"))})


def sha256(path):
    hasher = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024*1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def inspect_shared_contract(path):
    """Read the actual T-008 contract without promoting pending scope to consent."""
    path = Path(path)
    if not path.is_file():
        return {"admitted": False, "reason": "T-008 shared contract absent"}
    contract = json.loads(path.read_text(encoding="utf-8"))
    scope = contract.get("scopes", {}).get("Q17", {})
    version = str(contract.get("version", ""))
    windows = contract.get("admissible_windows", [])
    matching = [w for w in windows if isinstance(w, dict) and w.get("scope") == "Q17"
                and w.get("asset") == "BTC" and w.get("date") == "2025-12-01"
                and isinstance(w.get("window_id"), str) and w["window_id"]
                and type(w.get("start_ns")) is int and type(w.get("end_ns")) is int
                and w["start_ns"] <= PILOT_START_NS and w["end_ns"] >= PILOT_END_NS] if isinstance(windows, list) else []
    admitted = (contract.get("contract_id") == "T-008-shared-data" and bool(version)
                and contract.get("status") == "certified"
                and "pending" not in version.lower() and scope.get("admissible") is True
                and len(matching) > 0)
    return dict(admitted=admitted, contract_sha256=sha256(path), version=version,
                status=contract.get("status"), q17_scope=scope,
                matching_windows=matching,
                reason="candidate scope; separate label/review required" if admitted else scope.get("reason", "No certified full-hour Q17 BTC development window"))


def require_certificates(data_certificate, label_certificate, coordinator_review):
    paths = [Path(x) for x in (data_certificate, label_certificate, coordinator_review)]
    missing = [str(p) for p in paths if not p.is_file()]
    if missing:
        raise ValueError("Missing affirmative certificates/review: " + ", ".join(missing))
    data, labels, review = [json.loads(p.read_text(encoding="utf-8")) for p in paths]
    if data.get("schema_version") != "q17-input-certificate/1" or data.get("issuer") != "T-008" or data.get("status") != "affirmative":
        raise ValueError("Unsupported or non-affirmative data certificate")
    shared = Path(data.get("shared_contract_file", ""))
    if not shared.is_absolute():
        shared = paths[0].parent / shared
    if not shared.is_file() or sha256(shared) != data.get("shared_contract_sha256") or not inspect_shared_contract(shared)["admitted"]:
        raise ValueError("T-008 shared contract has no matching affirmative Q17 window certificate")
    matched = [w for w in inspect_shared_contract(shared)["matching_windows"] if w["window_id"] == data.get("window_id")]
    if len(matched) != 1:
        raise ValueError("Data certificate must name one matching Q17 window")
    if any(data.get("assertions", {}).get(k) is not True for k in REQUIRED):
        raise ValueError("Incomplete affirmative BBO/event/availability assertions")
    if data.get("availability_kind") not in {"actual_receipt", "causal_delayed_release"}:
        raise ValueError("Offline join is not a causal availability clock")
    if data.get("purpose") != "december1_development" or data.get("asset") != "BTC" or data.get("date") != "2025-12-01":
        raise ValueError("This bounded runner admits only December 1 BTC development")
    if labels.get("schema_version") != "q17-label-certificate/1" or labels.get("status") != "affirmative" or labels.get("issuer") != "T-008":
        raise ValueError("Unsupported or non-affirmative label certificate")
    if labels.get("data_certificate_sha256") != sha256(paths[0]) or labels.get("label_spec_sha256") != digest_json(LABEL_SPEC):
        raise ValueError("Label certificate does not bind these data and target semantics")
    if review.get("schema_version") != "q17-coordinator-review/1" or review.get("status") != "approved" or review.get("reviewer_role") != "coordinator":
        raise ValueError("Affirmative coordinator review required")
    expected = {"data_certificate_sha256": sha256(paths[0]), "label_certificate_sha256": sha256(paths[1]),
                "protocol_sha256": digest_json(PROTOCOL), "implementation_sha256": implementation_sha256()}
    if any(review.get(k) != v for k, v in expected.items()):
        raise ValueError("Review is stale or binds a different protocol/certificate")
    payload = Path(data["data_file"])
    if not payload.is_absolute():
        payload = paths[0].parent / payload
    if not payload.is_file() or sha256(payload) != data.get("data_sha256"):
        raise ValueError("Certified BBO payload missing or checksum changed")
    return {"data_file": payload, "data": data, "window": matched[0], "review": review,
            "review_sha256": sha256(paths[2]), "shared_contract_sha256": sha256(shared), **expected}
