"""Bind D019 execution to an exact-input RV011 review and consumer amendment."""
import json
from pathlib import Path
from .gate import sha256

STARTUP_POLICY_SHA256 = "e5de9c455d3918b11693af0f771de4776f49cd9b2a1f1918000c0179259c8d19"


def require_reviewed_amendment(binding, contracts, period, base_predeclaration_sha256):
    """A plan-only verdict or a review for a different input set cannot authorize fitting."""
    path = Path(binding["path"])
    if sha256(path) != binding["sha256"]:
        raise ValueError("Consumer amendment checksum mismatch")
    amendment = json.loads(path.read_text(encoding="utf-8"))
    if (amendment.get("schema") != "q17-reviewed-source-amendment/1"
            or amendment.get("base_predeclaration_sha256") != base_predeclaration_sha256
            or amendment.get("provider_protocol_sha256") != STARTUP_POLICY_SHA256
            or amendment.get("period") != period or period != "hour00"
            or amendment.get("startup_exclusion_ns") != 30_000_000_000
            or amendment.get("adaptation_class") != "SOURCE-QUALITY-INFORMED POST-ACQUISITION PRE-FIT"
            or amendment.get("model_policy_constants_unchanged") is not True):
        raise ValueError("Amendment does not bind the authorized separate hour00 adaptation")
    index_path = Path(amendment["input_index_file"])
    if sha256(index_path) != amendment["input_index_sha256"]:
        raise ValueError("Reviewed input index checksum mismatch")
    index = json.loads(index_path.read_text(encoding="utf-8"))
    expected = sorted((c["asset"], c["date"], c["contract_sha256"]) for c in index["contracts"])
    actual = sorted((c["asset"], c["date"], c["sha256"]) for c in contracts)
    if len(expected) != 24 or actual != expected or index["policy_sha256"] != STARTUP_POLICY_SHA256:
        raise ValueError("Amendment requires the exact reviewed 24-contract input set")
    review = amendment["review"]
    if (review.get("review_id") != "RV-011" or review.get("reviewer_task") != "T-013"
            or review.get("decision") != "supported_exact_hour00_inputs"
            or review.get("scope") != "limited_descriptive_hour00"
            or review.get("input_index_sha256") != amendment["input_index_sha256"]
            or review.get("provider_protocol_sha256") != STARTUP_POLICY_SHA256
            or review.get("contract_sha256_set") != sorted(c[2] for c in expected)):
        raise ValueError("RV011 must explicitly support this exact limited input scope")
    review_path = Path(review["file"])
    if sha256(review_path) != review["sha256"]:
        raise ValueError("Independent review artifact checksum mismatch")
    review_text = review_path.read_text(encoding="utf-8")
    if amendment["input_index_sha256"] not in review_text or STARTUP_POLICY_SHA256 not in review_text:
        raise ValueError("Independent review artifact must identify exact source policy and inputs")
    return {**amendment, "consumer_amendment_sha256": binding["sha256"]}
