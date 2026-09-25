"""Explicit fail-closed handoff between T-008, coordinator review, and Q18."""
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile

import numpy as np

from .features import FORWARD_GUARD_NS, Split, build_dataset


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def implementation_hashes():
    root = Path(__file__).resolve().parent
    return {path.name: sha256(path) for path in sorted(root.glob("*.py"))}


def review_gate(shared_path, execution_path, review_path, protocol_path):
    """Review files must be supplied by the coordinator, never self-approved."""
    paths = {"shared_contract": Path(shared_path), "execution_manifest": Path(execution_path),
             "coordinator_review": Path(review_path), "protocol": Path(protocol_path)}
    reasons = [f"Missing {key}: {path.name}" for key, path in paths.items() if not path.is_file()]
    if reasons:
        return {"admissible": False, "reasons": reasons}
    try:
        shared, execution, review, protocol = [json.loads(paths[k].read_text(encoding="utf-8-sig"))
            for k in ("shared_contract", "execution_manifest", "coordinator_review", "protocol")]
    except (ValueError, OSError) as error:
        return {"admissible": False, "reasons": [f"Unreadable contract: {error}"]}
    scope = shared.get("scopes", {}).get("Q18", {})
    if shared.get("status") != "certified" or not shared.get("version") or "pending" in shared["version"]:
        reasons.append("T-008 shared contract is not versioned certified evidence")
    if scope.get("admissible") is not True:
        reasons.append("T-008 Q18 scope is not affirmative")
    for flag in ("full_top5", "causal_availability", "atomic_order", "continuous_windows"):
        if scope.get(flag) is not True:
            reasons.append(f"Uncertified Q18 requirement: {flag}")
    if execution.get("schema") != "q18-execution-v1" or execution.get("experiment_id") != "E-018":
        reasons.append("Unknown execution manifest schema/experiment")
    if execution.get("shared_contract_sha256") != sha256(shared_path):
        reasons.append("Execution manifest does not bind current T-008 contract")
    if execution.get("protocol_sha256") != sha256(protocol_path):
        reasons.append("Execution manifest does not bind frozen adapter protocol")
    if execution.get("development_only") is not True or execution.get("asset") != "BTC":
        reasons.append("This bounded runner only admits BTC development")
    if execution.get("clock") != "certified_causal_release_grid":
        reasons.append("Unsupported clock; retrospective candidate joins are forbidden")
    origin = execution.get("origin")
    if origin not in ("synthetic_integration", "eligible_empirical"):
        reasons.append("Legacy path requires an explicit synthetic or reviewed empirical origin")
    if any(record.get("origin") != origin for record in (shared, review, protocol)):
        reasons.append("Origin mismatch across evidence chain")
    if origin == "synthetic_integration":
        if review.get("role") != "fixture_issuer" or review.get("fixture_only") is not True:
            reasons.append("Synthetic integration requires an explicitly fictional fixture record")
    elif review.get("status") != "approved" or review.get("role") != "coordinator":
        reasons.append("Affirmative coordinator review is required")
    for key, path in (("shared_contract_sha256", shared_path),
                      ("execution_manifest_sha256", execution_path), ("protocol_sha256", protocol_path)):
        if review.get(key) != sha256(path):
            reasons.append(f"Coordinator review hash mismatch: {key}")
    if not review.get("reviewed_at_utc") or not review.get("review_id"):
        reasons.append("Coordinator review identity/time missing")
    if not shared.get("admissible_windows"):
        reasons.append("No admissible windows")
    if execution.get("splits") != protocol.get("splits"):
        reasons.append("Execution split boundaries differ from the frozen protocol")
    if protocol.get("implementation_sha256") != implementation_hashes():
        reasons.append("Executing implementation differs from the frozen protocol")
    return {"admissible": not reasons, "reasons": reasons,
            "execution": execution, "shared": shared,
            "provenance": {**{key + "_sha256": sha256(path) for key, path in paths.items()},
                           "implementation_sha256": implementation_hashes()}}


def load_reviewed_grid(gate, manifest_directory):
    if not gate.get("admissible"):
        raise ValueError("Real training gate is closed")
    execution = gate["execution"]
    path = (Path(manifest_directory) / execution["grid_file"]).resolve()
    if sha256(path) != execution["grid_sha256"]:
        raise ValueError("Grid digest mismatch")
    with ZipFile(path) as archive:
        if sum(member.file_size for member in archive.infolist()) > 64 * 1024 * 1024:
            raise ValueError("Grid exceeds bounded 64 MiB uncompressed budget")
    with np.load(path, allow_pickle=False) as archive:
        grid = {key: archive[key].copy() for key in archive.files}
    splits = [Split(**s) for s in execution["splits"]]
    dataset = build_dataset(grid, splits)
    windows = gate["shared"]["admissible_windows"]
    for split in dataset.values():
        for time_ns in split["times_ns"]:
            if not any(w.get("asset") == "BTC" and w.get("full_top5") is True
                       and w["start_ns"] <= int(time_ns) - 75_000_000_000
                       and int(time_ns) + FORWARD_GUARD_NS < w["end_ns"] for w in windows):
                raise ValueError("Example escapes coordinator-reviewed full-top-five window")
    return dataset
