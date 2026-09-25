"""Feature diagnostics under explicit participant-reconstruction premises; never admission."""
import json
from pathlib import Path

import numpy as np

from .contracts import sha256
from .features import FORWARD_GUARD_NS, SECOND, Split, build_split

PREMISES = {"P1", "P2", "L1", "L2", "P4"}


def project_conditional(path, expected_sha256):
    path = Path(path)
    if sha256(path) != expected_sha256:
        raise ValueError("Conditional contract hash mismatch")
    contract = json.loads(path.read_text())
    if (contract.get("schema") != "t008-participant-conditional/3"
            or contract.get("empirical_admission") is not False
            or contract["scopes"]["Q18"]["decision"] != "conditional_diagnostic"
            or contract["atomic_cut"]["kind"] != "conditional_terminal_group_reconstruction"
            or set(contract["atomic_cut"]["assumption_ids"]) != PREMISES
            or contract["mask_semantics"]["online_admission"] is not False):
        raise ValueError("Unsupported conditional scope or missing premises")
    for name, digest in contract["input_sha256"].items():
        if sha256(name) != digest:
            raise ValueError("Conditional input hash mismatch")
    for evidence in contract["files"].values():
        if sha256(evidence["path"]) != evidence["sha256"]:
            raise ValueError("Conditional supporting evidence hash mismatch")
    rows = [json.loads(line) for line in Path(contract["files"]["required_cut_states.jsonl"]["path"]).read_text().splitlines()]
    cuts = {row["cut_ns"]: row for row in rows}
    if len(cuts) != len(rows):
        raise ValueError("Duplicate conditional support cuts")
    window = next(w for w in contract["windows"] if w["scope"] == "Q18")
    decisions = np.array(window["decision_ns"], dtype=np.int64)
    required = {int(g + offset * SECOND) for g in decisions for offset in range(-75, 11)}
    required.update(int(g + FORWARD_GUARD_NS) for g in decisions)
    if not required <= set(cuts):
        raise ValueError("Missing required conditional support cut")
    for cut in required:
        row = cuts[cut]
        if (row["admitted"] is not False or row["candidate_event_ns"] > cut
                or not row["local_checkpoint_coverage"]["5"]["state_covered_under_local_checkpoint_premises"]
                or row["measured_release_ns"] is not None or row["measured_admission_ns"] is not None):
            raise ValueError("Conditional support does not preserve declared scope")
    times = np.arange(int(decisions[0]) - 75 * SECOND, int(decisions[-1]) + 10 * SECOND + 1,
                      SECOND, dtype=np.int64)
    selected = [cuts[int(cut)] for cut in times]
    # These arithmetic masks mean "under the premises", never an admission vote.
    grid = {"times_ns": times, "clock_scope": np.array("exchange_time"),
            "source_event_ns": np.array([row["candidate_event_ns"] for row in selected], dtype=np.int64),
            "source_ordinal": np.array([row["candidate_state_index"] for row in selected], dtype=np.int64),
            "segment_id": np.zeros(len(times), dtype=np.int64),
            "top5_complete": np.ones(len(times), dtype=bool), "atomic_complete": np.ones(len(times), dtype=bool),
            "past_only_selection": np.ones(len(times), dtype=bool),
            "guard_supported": np.array([int(cut + FORWARD_GUARD_NS) in required for cut in times], dtype=bool)}
    for key, side, column in (("bid_px", 0, 0), ("ask_px", 1, 0), ("bid_qty", 0, 1), ("ask_qty", 1, 1)):
        grid[key] = np.array([[entry[column] / 100_000_000 for entry in row["top5_price_quantity_count"][side]]
                             for row in selected])
    part = build_split(grid, Split("conditional_december_diagnostic", window["start_ns"], window["end_ns"]))
    if not np.array_equal(part["times_ns"], decisions):
        raise ValueError("Consumer decisions disagree with frozen conditional cut cohort")
    # Saved evidence cannot masquerade as the exchange-time empirical grid type.
    grid["clock_scope"] = np.array("conditional_exchange_time")
    grid["empirical_admission"] = np.array(False)
    grid["assumption_ids"] = np.array(sorted(PREMISES))
    grid["closure_witness_ns"] = np.array([row["closure_witness_time_ns"] for row in selected], dtype=np.int64)
    part["diagnostic_only"] = True
    part["assumption_ids"] = sorted(PREMISES)
    audit = {"schema": "q18-conditional-feature-diagnostics/1", "origin": contract["origin"],
             "decisions": len(decisions), "required_cuts": len(required), "views": len(part["views"]),
             "market_fits": 0, "empirical_admission": False, "scientific_acceptance": False,
             "clock_scope": "conditional_exchange_time", "assumption_ids": sorted(PREMISES),
             "conditional_premises": contract["conditional_premises"],
             "contract_sha256": expected_sha256,
             "future_closure_required_cuts": sum(cuts[t]["closure_witness_time_ns"] > t for t in required),
             "source_age_max_ns": int((times - grid["source_event_ns"]).max()),
             "feature_and_label_diagnostics_only": True,
             "target_horizon_ns": 10 * SECOND, "forward_guard_ns": FORWARD_GUARD_NS,
             "returns_bps_min": float(part["returns_bps"].min()), "returns_bps_max": float(part["returns_bps"].max()),
             "limitations": contract["unknowns"] + ["Retrospective conditional coverage is not online causal admission",
                 "No supported independent training period in this contract; no label threshold is learned here"]}
    return part, grid, audit
