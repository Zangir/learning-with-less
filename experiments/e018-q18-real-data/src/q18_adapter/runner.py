"""Fixed-path entrypoint. No market fit occurs without all reviewed contracts."""
from datetime import datetime, timezone
import json
from pathlib import Path

import numpy as np

from .contracts import load_reviewed_grid, review_gate
from .evaluation import fit_pilot

def run(artifact_directory, shared_path=None):
    artifact = Path(artifact_directory)
    shared = Path(shared_path) if shared_path else artifact.parent / "T-008/shared_data_contract.json"
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    gate = review_gate(shared, artifact / "q18_execution_manifest.json",
                       artifact / "coordinator_review.json", artifact / "protocol.json")
    audit = {"task": "T-011", "experiment": "E-018", "run_id": run_id, "checked_at_utc":
             datetime.now(timezone.utc).isoformat(), "market_fits_this_attempt": 0,
             "prior_results_retained": [name for name in ("results.json", "paired_predictions.npz")
                                        if (artifact / name).exists()], **gate}
    (artifact / "gate_check.json").write_text(json.dumps(audit, indent=2))
    if not gate["admissible"]:
        print(json.dumps({"status": "blocked", "market_fits": 0, "reasons": gate["reasons"]}), flush=True)
        return
    dataset = load_reviewed_grid(gate, artifact)
    result, predictions = fit_pilot(dataset)
    origin = gate["execution"]["origin"]
    counts = {"fit_count": 16, "synthetic_fits": 16 if origin == "synthetic_integration" else 0,
              "market_fits": 0 if origin == "synthetic_integration" else 16}
    result.update(scope="BTC December-1 development adaptation; no replication claim",
                  **counts, origin=origin, task="T-011", experiment="E-018", run_id=run_id,
                  provenance=gate["provenance"], grid_sha256=gate["execution"]["grid_sha256"])
    (artifact / "results.json").write_text(json.dumps(result, indent=2))
    arrays = {f"{model}_{delay}_{depth}_{history}": p for
              (model, (delay, depth, history)), p in predictions.items()}
    arrays["decision_ns"] = dataset["evaluation"]["times_ns"]
    arrays["returns_bps"] = dataset["evaluation"]["returns_bps"]
    np.savez_compressed(artifact / "paired_predictions.npz", **arrays)
    audit["market_fits_this_attempt"] = counts["market_fits"]
    audit["origin"] = origin
    audit["synthetic_fits_this_attempt"] = counts["synthetic_fits"]
    audit["status"] = "development_complete"
    (artifact / "gate_check.json").write_text(json.dumps(audit, indent=2))
    print(json.dumps({"status": "development_complete", "origin": origin, **counts}), flush=True)


if __name__ == "__main__":
    raise SystemExit("Use run(artifact_directory) from the task's fixed-path driver")
