"""Build an explicit, fail-closed handoff from the T-008 evidence bundle."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json

ROOT = Path(__file__).resolve().parents[1]
E = ROOT / "evidence"
def read(name):
    return json.loads((E / name).read_text(encoding="utf-8-sig"))
def write(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
clock = read("clock_forensics.json")
replay = read("replay_audit.json")
budget = json.loads((ROOT/"independent_day_acquisition_plan.json").read_text())
manifest = json.loads((ROOT.parent/"T-001"/"sample_manifest.json").read_text())
scope_reasons = {
    "Q16": ["No initialized complete price-level queue or admitted regional completeness proof",
            "No verified December engine rank rule / full atomic event order",
            "Size decreases without trades cannot be interpreted as probe fills",
            "Observed-new population is not the complete venue queue"],
    "Q17": ["No authoritative BBO checkpoint or admitted complete better-price-region certificate",
            "No fully validated atomic state cuts and past-only release rule for selected windows"],
    "Q18": ["No authoritative top-five checkpoint or admitted certificate covering every better price",
            "No validated clock/state window spanning 75-second lookback and 10.5-second forward guard"]
}
scopes = {q: {"admissible": False, "status": "not_certified", "window_count": 0,
               "windows_file": "admissible_windows.json", "reasons": reasons}
          for q,reasons in scope_reasons.items()}
contract = {
    "contract_id": "T-008-shared-data", "version": "1.0.0",
    "status": "completed_diagnostic_no_mandatory_scope_certified",
    "review_status": "engineer_evidence_for_independent_coordinator_review",
    "created_utc": datetime.now(timezone.utc).isoformat(),
    "task": "T-008", "experiment_ids": ["E-200","E-201","E-202","E-203","E-204"],
    "seed": 20260919, "asset": "BTC", "split_role": "development_only",
    "development_date": "2025-12-01", "use_actual_record_times": True,
    "input_provenance": {"record": manifest["record"], "frozen_manifest": "../T-001/sample_manifest.json",
        "manifest_sha256": hashlib.sha256((ROOT.parent/"T-001/sample_manifest.json").read_bytes()).hexdigest(),
        "sha256_reverified": True, "integrity_evidence": "evidence/input_integrity.json",
        "status_first_ns": clock["status_stream"]["first_timestamp_ns"],
        "status_last_ns": clock["status_stream"]["last_timestamp_ns"],
        "trade_first_ns": clock["trade_stream"]["first_timestamp_ns"],
        "trade_last_ns": clock["trade_stream"]["last_timestamp_ns"],
        "diff_event_time_bounds": None,
        "diff_event_time_bounds_reason": "Flat diff rows have no native event/receipt/block fields."},
    "initial_state_verified": False, "event_time_verified": False, "event_order_verified": False,
    "trade_status_semantics_verified": False, "receipt_clock_available": False,
    "scopes": scopes, "admissible_windows": [],
    "evaluation_readiness": {"independent_day_panel_available": False,
        "final_validation_or_test_ready": False,
        "reason": "December 1 is inspected development. Independent-day readiness is separate from state-window admission."},
    "diagnostic_permission": {
        "allowed": ["offline observed-lifecycle structural and quantity audit",
                    "source-ordinal-aware candidate-clock diagnostics",
                    "synthetic adversarial tests of completeness assumptions"],
        "not_allowed": ["true queue fill outcomes", "venue-wide L2/L3 reconstruction",
                        "causal predictive features or historical latency claims",
                        "real-market Q16/Q17/Q18 completion claims"]},
    "time_contract": {
        "exchange_clock": "Status ts and trade time are source-reported L1 event/block time in Unix nanoseconds, not receipt time.",
        "source_order": "Preserve original sequence. Clock raw_diff_index/raw_status_index/raw_trade_index and public sample zero_based_row are zero-based; status byte offset = raw_status_index * 54. Replay source_row_1based, first_diff_source_row_1based and source_row sample fields are one-based. Convert explicitly, never infer the base.",
        "ties": "Equal timestamps do not establish consensus/atomic ordering; no synthetic block identity is emitted.",
        "visible_new_rule": "(status=open and not isTrigger and tif!=Ioc) or (isTrigger and status=triggered)",
        "visible_new_rule_source": "https://github.com/hyperliquid-dex/order_book_server/blob/bf5f6bceec3ebc36209bef1ad407de98c3550c70/server/src/types/node_data.rs#L46",
        "rule_status": "Dated September 2025 illustrative implementation, empirically checked on retained prefix; not consensus-engine proof.",
        "prefix_btc_rows": clock["prefix_btc_rows"],
        "legacy_direct_point_candidates": 91860,
        "legacy_unmatched_updates": len(clock["missing_updates"]),
        "legacy_clock_reversals": len(clock["clock_reversals"]),
        "trigger_aware_clock_reversals": len(clock["diagnostic_remaining_reversals"]),
        "same_neighbor_order_inferences": 8,
        "same_neighbor_caveat": "Conditional on correct neighboring anchors and chronological source order; next anchor/full-hour matching is retrospective. These eight are not direct trade matches.",
        "observation_availability": None,
        "causal_release_certified": False,
        "retrospective_smoothing_applied": False,
        "full_hour_clock_validated": False
    },
    "quantity_contract": {
        "canonical_adapter_size_unit": "1e-8 BTC integer", "canonical_adapter_price_unit": "1e-8 USD per BTC integer",
        "artifact_lattices": {"clock_forensics.json": "1e-8 size and price units",
            "replay_audit.json": "1e-7 size and price lattice; fields labeled px_scaled_1e7 where scaled",
            "conversion": "Multiply replay 1e-7 integer values by 10 for canonical 1e-8 units; decimal-string outputs retain their stated physical units."},
        "packed_decode": "(encoded & 0x1fffffff) * 10**(8 - (encoded >> 29))",
        "decimal_conversion": "Decimal(source_string) * 100000000, require integral result",
        "update_label": "size_change; execution only when independently matched to a trade",
        "unmatched_prefix_updates": 8, "all_eight_reduce_only": True,
        "mechanism": "reduce-only-associated nontrade-or-unmatched reductions; automatic resizing not independently proven",
        "zero_size": "Preserve zero-sized order identity until explicit remove; do not count zero quantity as positive visible depth.",
        "terminal_status": "Distinguish cancellations, filled, triggered and residual quantity; do not assume any terminal status means a trade."
    },
    "replay_evidence": {"file":"evidence/replay_audit.json",
        "all_coin_diff_rows": replay["diff"]["all_coin_diff_rows"],
        "btc_diff_rows": replay["diff"]["btc_diffs"],
        "first_seen_remove": replay["diff"]["first_remove"],
        "first_seen_update": replay["diff"]["first_update"],
        "full_book_claim": False,
        "restricted_cohort_is_venue_book": False,
        "crossed_book_absence_is_completeness_proof": False},
    "certification_rules": [
        "Admit each scope independently; Q16 rank uncertainty alone must not reject otherwise valid Q17/Q18 state.",
        "For the proposed checkpoint-free trade-through route, admission requires strict-price clearing, complete atomic replay/activation, all better-price coverage, no unknown events, and a causal inclusion rule. Other rigorous completeness proofs remain possible.",
        "Warm-up elapsed time and high candidate coverage are insufficient.",
        "A null/empty window list means not certified, not a theorem that no future reconstruction is possible."
    ],
    "historical_matching_rules": "evidence/sources_rules.json",
    "independent_day_acquisition_plan": "independent_day_acquisition_plan.json",
    "remaining_acquisition_bytes": budget["remaining_bytes"],
    "smallest_viable_data": budget["minimum_viable_requirements"],
    "external_publication": "Use sanitized report/sample_rows/main figure only; raw source snapshots may contain public example account identifiers."
}
windows = {"contract_id": contract["contract_id"], "contract_version": contract["version"],
           "status": "no_windows_certified", "windows": [], "scopes": scopes,
           "not_a_claim_of_global_impossibility": True}
write(ROOT/"shared_data_contract.json",contract)
write(ROOT/"shared_data_contract.v1.0.0.json",contract)
write(ROOT/"admissible_windows.json",windows)
(ROOT/"admissible_windows.csv").write_text("scope,start_event_ns,end_event_ns,source_start_row,source_end_row,certificate_id\n")
print("Wrote version 1.0.0 contract and explicit empty admissible-window artifacts.")
