"""Offline Q16 execution from a source-supported, hash-bound prospective cohort.

Source support permits computation, not independent scientific acceptance.
The legacy T-008 pilot interface and every frozen result remain unchanged.
"""
from collections import Counter
from copy import deepcopy
from fractions import Fraction
import json
from pathlib import Path
import time

from admission import sha256
from adapter import units
from core import StateCapExceeded, advance, initial_states, labels
from r2_adapter import evaluate_episode
from r2_selector import audit_selection

REQUIRED_PREMISES = (
    "initial_relevant_level", "contiguous_native_actions", "interior_action_order",
    "atomic_action_grouping", "resting_tail_priority", "quantity_domain",
    "execution_cancel_correspondence", "complete_candidate_lineage",
)
EXECUTABLE_PROTOCOL = json.loads(Path(__file__).with_name("prospective_protocol.json").read_text())


class SourceBlocked(ValueError):
    """Missing source evidence is unavailable, never a scientific negative."""


def validate_protocol(protocol):
    """Only source scope is completed at handoff; all executable constants are fixed."""
    if set(protocol) != set(EXECUTABLE_PROTOCOL):
        raise SourceBlocked("Protocol fields differ from the versioned executable specification")
    for key, expected in EXECUTABLE_PROTOCOL.items():
        if key != "scope" and json.dumps(protocol[key], sort_keys=True) != json.dumps(expected, sort_keys=True):
            raise SourceBlocked("Unsupported frozen protocol field: " + key)
    if not isinstance(protocol["scope"], dict) or not protocol["scope"]:
        raise SourceBlocked("Exact preselected source scope is required")


def load_bundle(contract_path, protocol_path):
    contract_path, protocol_path = Path(contract_path), Path(protocol_path)
    contract = json.loads(contract_path.read_text(encoding="utf-8-sig"))
    protocol = json.loads(protocol_path.read_text(encoding="utf-8-sig"))
    if (contract.get("schema") != "q16-offline-source/1"
            or contract.get("producer") != "T-018"
            or contract.get("origin") != "real_native"
            or contract.get("fixture_only") is not False):
        raise SourceBlocked("An explicit real-native T-018 source contract is required")
    if contract.get("protocol_sha256") != sha256(protocol_path):
        raise SourceBlocked("Source contract does not bind the frozen protocol")
    validate_protocol(protocol)
    if contract.get("scope") != protocol.get("scope") or not protocol.get("scope"):
        raise SourceBlocked("Exact preselected source scope is required")
    if contract.get("quantity_domain") not in {
            "all_positive_integer_multiples", "all_legal_sizes_in_integer_grid"}:
        raise SourceBlocked("Inference requires justified integer-domain equality or grid coverage")
    for premise in REQUIRED_PREMISES:
        check = contract.get("premises", {}).get(premise, {})
        if check.get("supported") is not True or not check.get("evidence"):
            raise SourceBlocked("Unsupported premise: " + premise)
        for evidence in check["evidence"]:
            path = contract_path.parent / evidence["file"]
            if sha256(path) != evidence["sha256"]:
                raise SourceBlocked("Evidence digest mismatch: " + premise)
    ref = contract["payload"]
    payload_path = contract_path.parent / ref["file"]
    if sha256(payload_path) != ref["sha256"]:
        raise SourceBlocked("Payload digest mismatch")
    payload = json.loads(payload_path.read_text(encoding="utf-8-sig"))
    if (payload.get("origin") != "real_native" or payload.get("fixture_only") is not False
            or payload.get("clock") != protocol["clock"]
            or payload.get("count_definition") != "positive_size_orders"):
        raise SourceBlocked("Payload observation semantics disagree")
    if payload.get("quantity_quantum") != contract.get("quantity_quantum"):
        raise SourceBlocked("Payload quantum differs from the evidenced domain")
    audit_selection(payload["candidates"], payload["selection"], limit=1000,
                    clock_kind="source_ordinal", specification=protocol["selection"])
    selected = payload["selection"]["selected"]
    if [(e["candidate_id"], e["initial_raw_seq"]) for e in payload["episodes"]] != [
            (e["candidate_id"], e["source_seq"]) for e in selected]:
        raise SourceBlocked("Episodes differ from the complete frozen anchor selection")
    for candidate in payload["candidates"]:
        if candidate["decision"] != candidate["source_seq"]:
            raise SourceBlocked("Offline anchor must bind to its native source ordinal")
    # Hashes preserve bytes; they do not turn an assertion into a market fact.
    return contract, protocol, payload


def offline_episode(source_episode):
    """Map source ordinals into legacy internal coordinates, never into receipts."""
    episode = deepcopy(source_episode)
    anchor = episode["initial_raw_seq"]
    episode["start_ns"] = episode["initial_available_ns"] = anchor
    last_action = episode["initial_action_ordinal"]
    if type(last_action) is not int or last_action < 0 or type(anchor) is not int or anchor < 0:
        raise ValueError("Nonnegative native anchor/action ordinals are required")
    for event in episode["events"]:
        action = event["action_ordinal"]
        if type(action) is not int or action <= last_action:
            raise ValueError("Native atomic action ordinals must strictly increase")
        rows = event["diffs"]
        if not rows or min(row["raw_seq"] for row in rows) <= anchor:
            raise ValueError("Event fragments must follow the frozen anchor")
        coordinate = max(row["raw_seq"] for row in rows)
        event["event_ns"] = event["available_ns"] = coordinate
        last_action = action
    return episode


def finite_crosscheck(episode, quantum, result):
    """Independent exhaustive check only when original units permit enumeration."""
    initial = [row for row in episode["initial"] if units(row["sz"], quantum) > 0]
    ahead = sum(units(row["sz"], quantum) for row in initial[:-1])
    try:
        volume = initial_states(ahead, result["probe_units"], cap=100000)
        count = {state for state in volume if len(state.queue) == result["observed_counts"][0]}
        for index, event in enumerate(result["observed_events"]):
            volume = advance(volume, event["kind"], event["quantity_units"])
            count = {state for state in advance(count, event["kind"], event["quantity_units"])
                     if len(state.queue) == result["observed_counts"][index + 1]}
        for arm, states in (("volume", volume), ("count", count)):
            if not states:
                raise ValueError("Empty exhaustive outcome set")
            projection = result["projections"][arm]
            fills = [state.filled for state in states]
            if [min(fills), max(fills)] != [projection["minimum_fill_units"],
                                           projection["maximum_fill_units"]]:
                raise ValueError("Independent exhaustive/SMT extrema mismatch")
            for endpoint in ("any_fill", "full_fill"):
                if labels(states, result["probe_units"])[endpoint] != projection[endpoint]:
                    raise ValueError("Independent exhaustive/SMT endpoint mismatch")
        if not count <= volume:
            raise ValueError("Independent exhaustive nesting failure")
        return {"status": "matched", "arms": 2}
    except StateCapExceeded:
        return {"status": "not_enumerable_at_original_units", "arms": 0}


def paired_metrics(result):
    volume, count = (result["projections"][arm] for arm in ("volume", "count"))
    probe = result["probe_units"]
    width = lambda p: Fraction(p["maximum_fill_units"] - p["minimum_fill_units"], probe)
    metrics = {
        "volume_fill_ambiguous": volume["fill_ambiguous"],
        "count_fill_ambiguous": count["fill_ambiguous"],
        "extrema_strictly_narrower": width(count) < width(volume),
        "full_fill_set_strictly_narrower": set(count["full_fill"]) < set(volume["full_fill"]),
        "any_fill_set_strictly_narrower": set(count["any_fill"]) < set(volume["any_fill"]),
        "volume_width": str(width(volume)), "count_width": str(width(count)),
        "width_reduction": str(width(volume) - width(count)),
    }
    # These are the paper's stipulated costs, not a P&L simulator.
    realized_full = result["truth"]["filled_units"] == probe
    metrics["stipulated_costs"] = {}
    for fallback in EXECUTABLE_PROTOCOL["fallback_costs"]:
        costs = {arm: (0 if realized_full else EXECUTABLE_PROTOCOL["incomplete_execution_cost"])
                 if p["full_fill"] == [1] else fallback
                 for arm, p in (("volume", volume), ("count", count))}
        metrics["stipulated_costs"][str(fallback)] = {
            **costs, "reduction": costs["volume"] - costs["count"]}
    return metrics


def run_supported(contract_path, protocol_path, output_dir, wall_seconds=3000, horizon=None):
    """Preserve all dispositions and checkpoint each completed episode."""
    started = time.monotonic()
    contract, protocol, payload = load_bundle(contract_path, protocol_path)
    horizon = protocol["horizon"] if horizon is None else horizon
    if horizon not in {protocol["horizon"], protocol.get("secondary_horizon")} or horizon not in {8, 10}:
        raise SourceBlocked("Requested horizon was not frozen in the source-bound protocol")
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    checkpoint = output_dir / "results.jsonl"
    if checkpoint.exists():
        raise FileExistsError("Result revision already exists; retain it and use a new output revision")
    results = []
    with checkpoint.open("x", encoding="utf-8") as stream:
        for episode in payload["episodes"]:
            tick = time.monotonic()
            row = {"candidate_id": episode["candidate_id"]}
            if tick - started > wall_seconds:
                row.update(status="not_run_wall_budget")
            else:
                try:
                    converted = offline_episode(episode)
                    result = evaluate_episode(converted, payload["quantity_quantum"],
                                              "exploratory_real", timeout_ms=2000,
                                              horizon=horizon)
                    row.update(result)
                    if row["status"] == "scored":
                        row["metrics"] = paired_metrics(row)
                        row["independent_enumeration"] = finite_crosscheck(
                            converted, payload["quantity_quantum"], row)
                except (ValueError, KeyError, TypeError) as exc:
                    row.update(status="invalid_source_or_model", reason=str(exc))
            row.update(elapsed_seconds=time.monotonic() - tick,
                       evidence_scope="source_supported_pending_independent_review",
                       quantity_domain=contract["quantity_domain"],
                       clock="native_action_ordinal_offline")
            stream.write(json.dumps(row) + "\n")
            stream.flush()
            results.append(row)
            print(json.dumps({"completed": len(results), "status": row["status"]}), flush=True)
    summary = summarize(results, horizon=horizon)
    summary.update(contract_sha256=sha256(contract_path), protocol_sha256=sha256(protocol_path),
                   elapsed_seconds=time.monotonic() - started,
                   source_scope=contract["scope"], independently_accepted=False,
                   quantity_domain=contract["quantity_domain"],
                   exact_market_domain=contract["quantity_domain"] == "all_positive_integer_multiples",
                   domain_limit=("Integer-grid coverage alone establishes a conservative model; "
                                 "tightening in that model need not equal tightening over legal exchange worlds"),
                   seed=20260919, results_sha256=sha256(checkpoint))
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    return summary


def summarize(results, horizon=8):
    scored = [row for row in results if row["status"] == "scored"]
    total, resolved = len(results), len(scored)
    missing_statuses = {"censored", "unresolved", "not_run_wall_budget"}
    invalid = sum(row["status"] not in missing_statuses | {"scored"} for row in results)
    defined = bool(total) and not invalid
    cohort_status = ("invalid_source_or_model" if invalid else "empty_cohort" if not total else
                     "valid_with_missing_outcomes" if resolved < total else "valid_fully_resolved")
    narrowed = sum(row["metrics"]["extrema_strictly_narrower"] for row in scored)
    return {
        "selected": total, "resolved": resolved,
        "cohort_status": cohort_status, "comparison_defined": defined,
        "invalid_anchors": invalid,
        "dispositions": dict(Counter(row["status"] for row in results)),
        "strict_extrema_tightening_resolved": narrowed,
        "resolved_count_scope": "Per-anchor diagnostics only when the cohort is invalid",
        "cohort_tightening_fraction_identification_interval":
            [str(Fraction(narrowed, total)), str(Fraction(narrowed + total - resolved, total))]
            if defined else None,
        "interval_scope": ("Worst-case missing-outcome bounds, not a population confidence interval"
                           if defined else "Undefined comparison: invalid source/model or no selected anchors"),
        "sampling_uncertainty": "No iid interval: anchors can overlap; finite-cohort description only",
        "original_unit_probe_equivalence": False,
        "full_support_tightening_claimed": False,
        "horizon": horizon,
        "original_supplementary_horizon_matches": horizon == 10,
        "scientific_negative": False if not defined or not resolved else None,
    }
