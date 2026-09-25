"""Check invariants established by the independently re-read source streams."""
from datetime import datetime, timezone
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
data = json.loads((root / "evidence/clock_forensics.json").read_text())
checks = {
    "legacy_missing_eight_preserved": len(data["missing_updates"]) == 8,
    "legacy_182854823_ns_inversion_preserved": data["clock_reversals"][0]["backward_ns"] == 182854823,
    "exact_insertion_rule_keeps_91860_direct_candidates": data["diagnostic_point_candidates"] == 91860,
    "zero_diagnostic_inversions_without_sorting": not data["diagnostic_remaining_reversals"],
    "eight_orders_are_reduce_only": all(c["all_statuses_reduce_only"] for c in data["quantity_checks"]),
    "no_single_block_fill_aggregate_resolves_missing": all(not c["same_timestamp_aggregate_matches"] for c in data["quantity_checks"]),
    "quantity_chains_and_terminal_quantities_agree": all(not c["book_chain_errors"] and c["terminal_matches_book_quantity"] for c in data["quantity_checks"]),
    "unexplained_remainder_exactly_equals_missing_reduction": all(c["original_minus_terminal_minus_trades_units_1e8_btc"] == c["missing_reduction_units_1e8_btc"] for c in data["quantity_checks"]),
    "all_target_prices_and_sides_agree": all(c["all_status_sides_match"] and c["all_status_prices_match"] and c["all_trade_prices_match"] and c["all_trades_opposite_aggressor"] for c in data["quantity_checks"]),
    "full_status_and_trade_streams_monotone": data["status_stream"]["timestamp_reversals"] == data["trade_stream"]["timestamp_reversals"] == 0,
    "receipt_time_remains_unavailable": data["receipt_time_available"] is False,
}
missing_contexts = [c for c in data["anomalous_contexts"] if c["row"]["diagnostic_clock_bounds_ns"] is None]
checks["eight_equal_neighbor_candidates_are_kept_distinct_from_direct_clocks"] = len(missing_contexts) == 8 and all(c["order_constrained_interval_ns"][0] == c["order_constrained_interval_ns"][1] for c in missing_contexts)
assert all(checks.values()), checks
out = dict(checks=checks, passed=len(checks), checked_utc=datetime.now(timezone.utc).isoformat(),
           scan_seconds=data["seconds"], peak_rss_kib=data["max_rss_kib"])
(root / "evidence/clock_verification.json").write_text(json.dumps(out, indent=2) + "\n")
print(json.dumps(out, indent=2))
