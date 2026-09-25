"""Configured T-019 entry point; run inside the documented bounded tmux job."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import resource
import time

from prospective import SourceBlocked, run_supported

ARTIFACTS = (Path(__file__).resolve().parents[2] / 'runtime')
CONTRACT = ARTIFACTS / "inputs/source-contract.json"
PROTOCOL = ARTIFACTS / "protocol.json"
SEED = 20260919


def main():
    started = time.monotonic()
    checkpoint = {"task": "T-019", "experiment": "E-266", "seed": SEED,
                  "started_utc": datetime.now(timezone.utc).isoformat(), "pid": os.getpid(),
                  "cpu_affinity": sorted(os.sched_getaffinity(0)),
                  "independent_acceptance": False, "summaries": {}}
    try:
        for horizon in (8, 10):
            remaining = max(0, 3000 - (time.monotonic() - started))
            checkpoint["summaries"][str(horizon)] = run_supported(
                CONTRACT, PROTOCOL, ARTIFACTS / f"empirical-h{horizon}",
                wall_seconds=remaining, horizon=horizon)
        statuses = {summary["cohort_status"] for summary in checkpoint["summaries"].values()}
        if "invalid_source_or_model" in statuses:
            checkpoint.update(status="invalid_source_or_model_cohort", scientific_negative=False,
                              next_step="Resolve retained source/model contradictions before any cohort inference")
        elif "empty_cohort" in statuses:
            checkpoint.update(status="no_eligible_cohort", scientific_negative=False)
        elif "valid_with_missing_outcomes" in statuses:
            checkpoint["status"] = "source_supported_computation_with_missing_outcomes_pending_review"
        else:
            checkpoint["status"] = "source_supported_computation_complete_pending_review"
    except (SourceBlocked, OSError, ValueError, KeyError, TypeError) as exc:
        checkpoint.update(status="recoverable_source_or_configuration_block", reason=str(exc),
                          scientific_negative=False,
                          next_step="Bind a qualified T-018 native source handoff and immutable interval protocol; rerun in a fresh output revision")
    checkpoint.update(elapsed_seconds=time.monotonic() - started,
                      peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                      ended_utc=datetime.now(timezone.utc).isoformat())
    (ARTIFACTS / "execution-checkpoint.json").write_text(json.dumps(checkpoint, indent=2) + "\n")
    print(json.dumps(checkpoint, indent=2), flush=True)
    if checkpoint["status"] == "invalid_source_or_model_cohort":
        return 3
    return 0 if checkpoint["status"].startswith("source_supported") else 2


if __name__ == "__main__":
    raise SystemExit(main())
