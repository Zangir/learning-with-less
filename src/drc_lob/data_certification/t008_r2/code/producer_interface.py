"""T-008 producer-owned state interface and explicitly fictional integration fixtures.

No function issues reviewer approval or turns a raw dump into certified evidence.
"""
from copy import deepcopy
from decimal import Decimal
import hashlib
import json
import math
from pathlib import Path
import sys
import time

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "interface"
ARTIFACTS = ROOT.parents[1]
NS = 1_000_000_000
START = 1764547200 * NS
SCALE = 100_000_000
OLD_HASH = "c4de49bd28c72195bba0c81ca308e8c9aff9af8807b066c20d77beb2af91935c"
ORIGINS = ("synthetic_integration", "exploratory_real", "eligible_empirical")
HORIZONS = {
    "Q17_forecast": {"lookback_ns": 20 * NS, "forward_guard_ns": 10 * NS},
    "Q17_primary_utility": {"lookback_ns": 20 * NS, "forward_guard_ns": 10_100_000_000},
    "Q17_full_latency_grid": {"lookback_ns": 20 * NS, "forward_guard_ns": 10_500_000_000},
    "Q17_scheduling": {"lookback_ns": 20 * NS, "forward_guard_ns": 131_500_000_000,
                       "opportunities": 12, "grid_ns": 11 * NS},
    "Q18": {"lookback_ns": 75 * NS, "forward_guard_ns": 10_500_000_000,
            "label_horizon_ns": 10 * NS, "guard_kind": "adopted_conservative_padding"},
}


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def write_json(path, obj):
    Path(path).write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def units8(value):
    """Representation precision, never a claim about the venue's legal lot quantum."""
    if not isinstance(value, (str, int, Decimal)) or isinstance(value, bool):
        raise ValueError("Exact decimal string/integer required")
    exact = Decimal(str(value)) * SCALE
    if not exact.is_finite() or exact != exact.to_integral_value():
        raise ValueError("Off units8 lattice")
    return int(exact)


def snapshot_row(snapshot, source_id, ordinal, release_ns=None, admission_evidence_ns=None):
    """Normalize observed official l2Book-shaped data without manufacturing clocks."""
    if type(snapshot["time"]) is not int or len(snapshot["levels"]) != 2:
        raise ValueError("Source must supply integer millisecond time and two book sides")
    row = {"source_id": source_id, "source_ordinal": ordinal, "asset": snapshot["coin"],
           "event_ns": int(snapshot["time"]) * 1_000_000, "release_ns": release_ns,
           "admission_evidence_ns": admission_evidence_ns}
    for side, levels in zip(("bid", "ask"), snapshot["levels"]):
        row[side + "_prices_units8"] = [units8(x["px"]) for x in levels]
        row[side + "_sizes_units8"] = [units8(x["sz"]) for x in levels]
        row[side + "_counts"] = [x.get("n") for x in levels]
    return row


def validate_rows(rows, max_gap_ns, depth=5, clock_scope="exchange_time"):
    """Validate sampled state observations; do not infer unseen event continuity."""
    if not rows:
        raise ValueError("Empty rows")
    last_by_asset = {}
    last_ordinal = {}
    max_observed_gap_ns = 0
    for row in rows:
        if row["asset"] not in {"BTC", "ETH", "SOL"}:
            raise ValueError("Unknown asset")
        event = row["event_ns"]
        ordinal = row["source_ordinal"]
        if type(event) is not int or type(ordinal) is not int or ordinal < 0:
            raise ValueError("Noninteger time or ordinal")
        stream_key = (row["source_id"], row["asset"])
        if stream_key in last_by_asset:
            gap = event - last_by_asset[stream_key]
            if gap < 0 or ordinal <= last_ordinal[stream_key]:
                raise ValueError("Source order/event inversion; sorting forbidden")
            if gap > max_gap_ns:
                raise ValueError("Sample gap exceeds declared continuity tolerance")
            max_observed_gap_ns = max(max_observed_gap_ns, gap)
        last_by_asset[stream_key] = event
        last_ordinal[stream_key] = ordinal
        for clock in ("release_ns", "admission_evidence_ns"):
            if row[clock] is not None and type(row[clock]) is not int:
                raise ValueError("Clock must be int ns or null")
            if clock_scope == "observed_receive_time" and row[clock] is None:
                raise ValueError("Actual receipt/evidence clock missing")
        for side in ("bid", "ask"):
            prices = row[side + "_prices_units8"]
            sizes = row[side + "_sizes_units8"]
            counts = row[side + "_counts"]
            if min(len(prices), len(sizes), len(counts)) < depth or len({len(prices), len(sizes), len(counts)}) != 1:
                raise ValueError("Shallow or unequal price/size/count arrays")
            if any(type(x) is not int or x <= 0 for x in prices + sizes):
                raise ValueError("Nonpositive/noninteger units8 values")
            if any(x is not None and (type(x) is not int or x <= 0) for x in counts):
                raise ValueError("Nonpositive/noninteger count")
            if any((a <= b if side == "bid" else a >= b) for a, b in zip(prices, prices[1:])):
                raise ValueError("Level prices not strictly ordered")
        if row["bid_prices_units8"][0] >= row["ask_prices_units8"][0]:
            raise ValueError("Crossed or locked BBO")
    return {"rows": len(rows), "max_observed_gap_ns": max_observed_gap_ns,
            "assets": sorted({r["asset"] for r in rows}), "observed_depth": depth}


def eligible(window, decision_ns, mode):
    h = HORIZONS[mode]
    return (window["start_ns"] <= decision_ns - h["lookback_ns"]
            and decision_ns + h["forward_guard_ns"] < window["end_ns"])


def validate_contract(contract, directory, requested_origin=None):
    import jsonschema
    jsonschema.validate(contract, json.loads((OUT / "shared_data_contract.schema.json").read_text()))
    if contract.get("schema") != "t008-producer-state/2" or contract.get("version") != "2.0.0":
        raise ValueError("Wrong producer schema/version")
    origin = contract.get("origin")
    if origin not in ORIGINS or (requested_origin is not None and origin != requested_origin):
        raise ValueError("Origin mismatch; synthetic cannot become market evidence")
    if (origin == "synthetic_integration") != contract.get("fixture_only"):
        raise ValueError("Fixture marker and origin disagree")
    if contract["review"]["status"] != "not_issued_by_producer":
        raise ValueError("Producer must not issue reviewer approval")
    for source in contract["sources"]:
        path = Path(directory) / source["file"]
        if sha256(path) != source["sha256"]:
            raise ValueError("Source hash mismatch")
    for scope in ("Q16", "Q17", "Q18"):
        details = contract["scopes"][scope]
        windows = [w for w in contract["windows"] if w["scope"] == scope]
        if details["decision"] == "affirmative" and not windows:
            raise ValueError("Affirmative scope has no windows")
        if details["decision"] == "negative" and windows:
            raise ValueError("Negative scope has windows")
        for window in windows:
            if window["start_ns"] >= window["end_ns"] or window["first_source_ordinal"] > window["last_source_ordinal"]:
                raise ValueError("Invalid half-open interval/source ordinal range")
    return True


def make_schema():
    nonneg = {"type": "integer", "minimum": 0}
    positive = {"type": "integer", "minimum": 1}
    row_properties = {"source_id": {"type": "string", "minLength": 1}, "asset": {"enum": ["BTC", "ETH", "SOL"]},
                      "source_ordinal": nonneg, "event_ns": nonneg,
                      "release_ns": {"type": ["integer", "null"]},
                      "admission_evidence_ns": {"type": ["integer", "null"]}}
    for side in ("bid", "ask"):
        for field in ("prices_units8", "sizes_units8"):
            row_properties[side + "_" + field] = {"type": "array", "minItems": 1, "items": positive}
        row_properties[side + "_counts"] = {"type": "array", "minItems": 1,
                                            "items": {"type": ["integer", "null"], "minimum": 1}}
    row_schema = {"$schema": "https://json-schema.org/draft/2020-12/schema", "title": "T-008 sampled state row v2",
                  "type": "object", "additionalProperties": False,
                  "required": list(row_properties), "properties": row_properties}
    write_json(OUT / "state_row.schema.json", row_schema)
    scope = {"type": "object", "required": ["decision", "reason", "clock_scope", "state_scope", "continuity_scope"],
             "properties": {"decision": {"enum": ["affirmative", "negative"]}, "reason": {"type": "string"},
                            "clock_scope": {"enum": ["exchange_time", "observed_receive_time", "not_certified"]},
                            "state_scope": {"type": "string"}, "continuity_scope": {"type": "string"}}}
    contract_schema = {"$schema": "https://json-schema.org/draft/2020-12/schema", "title": "T-008 producer state contract 2.0.0",
        "type": "object", "required": ["schema", "version", "producer", "origin", "fixture_only", "purpose", "sources", "units", "scopes", "windows", "atomic_cut", "continuity", "review", "horizons"],
        "properties": {"schema": {"const": "t008-producer-state/2"}, "version": {"const": "2.0.0"},
                       "producer": {"const": "T-008"}, "origin": {"enum": list(ORIGINS)}, "fixture_only": {"type": "boolean"},
                       "purpose": {"enum": ["fictional_integration_only", "december_participant_linked_development", "live_hyperliquid_sampled_state_pilot"]},
                       "sources": {"type": "array", "items": {"type": "object", "required": ["source_id", "file", "sha256", "provenance", "rights"]}},
                       "scopes": {"type": "object", "required": ["Q16", "Q17", "Q18"], "properties": {q: scope for q in ("Q16", "Q17", "Q18")}},
                       "windows": {"type": "array", "items": {"type": "object", "required": ["window_id", "scope", "asset", "start_ns", "end_ns", "first_source_ordinal", "last_source_ordinal", "state_depth", "source_ids", "evidence_ids"],
                                      "properties": {"scope": {"enum": ["Q16", "Q17", "Q18"]}, "window_id": {"type": "string", "minLength": 1},
                                                     "asset": {"enum": ["BTC", "ETH", "SOL"]}, "start_ns": nonneg, "end_ns": positive,
                                                     "first_source_ordinal": nonneg, "last_source_ordinal": nonneg, "state_depth": positive,
                                                     "source_ids": {"type": "array", "minItems": 1, "items": {"type": "string"}},
                                                     "evidence_ids": {"type": "array", "minItems": 1, "items": {"type": "string"}}}}},
                       "atomic_cut": {"type": "object", "required": ["kind", "evidence"], "properties": {
                           "kind": {"enum": ["authoritative_snapshot_at_event_time", "documented_atomic_event_envelope", "state_invariant_across_admissible_interleavings"]},
                           "evidence": {"type": "string", "minLength": 1}}},
                       "continuity": {"type": "object", "required": ["kind", "max_gap_ns", "cadence_ns", "observed_max_gap_ns", "all_venue_events_observed"],
                                      "properties": {"kind": {"enum": ["complete_event_stream", "sampled_snapshots"]}, "max_gap_ns": nonneg,
                                                     "cadence_ns": nonneg, "observed_max_gap_ns": nonneg, "all_venue_events_observed": {"type": "boolean"}}},
                       "horizons": {"const": HORIZONS},
                       "review": {"type": "object", "required": ["status"], "properties": {"status": {"const": "not_issued_by_producer"}}}},
        "allOf": [{"if": {"properties": {"origin": {"const": "synthetic_integration"}}},
                   "then": {"properties": {"fixture_only": {"const": True}}},
                   "else": {"properties": {"fixture_only": {"const": False}}}}]}
    write_json(OUT / "shared_data_contract.schema.json", contract_schema)
    return row_schema, contract_schema


def make_fixtures():
    target = OUT / "fixtures"
    target.mkdir(parents=True, exist_ok=True)
    rows = []
    for i in range(3601):
        # A deterministic wiggly tape has no market secrets and no market alpha.
        offset = 0 if i % 180 < 35 else int(1e8 * (3 * math.sin(i / 29) + math.sin(i / 3)))
        mid = 9_000_000_000_000 + offset
        row = {"source_id": "fictional-btc", "source_ordinal": i, "asset": "BTC",
               "event_ns": START + i * NS, "release_ns": START + i * NS,
               "admission_evidence_ns": START + i * NS}
        for side, sign in (("bid", -1), ("ask", 1)):
            row[side + "_prices_units8"] = [mid + sign * (level + 1) * SCALE for level in range(5)]
            row[side + "_sizes_units8"] = [10_000_000 + ((i * 7 + level * 13 + (sign + 1) * 11) % 100) * 1_000_000 for level in range(5)]
            row[side + "_counts"] = [1 + (i + level) % 3 for level in range(5)]
        rows.append(row)
    payload = target / "synthetic_state_rows.jsonl"
    payload.write_text("".join(json.dumps(r, separators=(",", ":")) + "\n" for r in rows), encoding="utf-8")
    evidence = target / "synthetic_evidence.json"
    write_json(evidence, {"origin": "synthetic_integration", "fixture_only": True,
                          "statement": "All rows and state/clock premises are fictional unit-test inputs.", "seed": 20260919})
    scopes = {q: {"decision": "affirmative" if q != "Q16" else "negative",
                  "reason": "Fictional complete-at-cut top-five sampled state" if q != "Q16" else "Snapshot fixture has no queue identities or execution truth",
                  "clock_scope": "exchange_time" if q != "Q16" else "not_certified",
                  "state_scope": {"Q16": "none", "Q17": "bbo_at_snapshot_cuts", "Q18": "top5_at_snapshot_cuts"}[q],
                  "continuity_scope": "sampled_snapshots"} for q in ("Q16", "Q17", "Q18")}
    windows = [{"window_id": "synthetic-btc-" + q.lower(), "scope": q, "asset": "BTC",
                "start_ns": START, "end_ns": START + 3600 * NS + 1, "first_source_ordinal": 0,
                "last_source_ordinal": 3600, "state_depth": 1 if q == "Q17" else 5,
                "source_ids": ["fictional-btc"], "evidence_ids": ["fictional-state-clock-premises"],
                "use": "development", "forward_guard_ns": 10_500_000_000,
                "lookback_ns": (20 if q == "Q17" else 75) * NS} for q in ("Q17", "Q18")]
    contract = {"schema": "t008-producer-state/2", "version": "2.0.0", "producer": "T-008",
                "origin": "synthetic_integration", "fixture_only": True, "purpose": "fictional_integration_only",
                "units": {"time": "UTC Unix ns", "price": "USD per base asset multiplied by 1e8", "size": "base asset multiplied by 1e8", "count": "positive visible order count or null"},
                "sources": [{"source_id": "fictional-btc", "file": payload.name, "sha256": sha256(payload),
                             "provenance": "Deterministic producer-authored synthetic fixture; not a venue observation", "rights": "locally authored fictional data"}],
                "scopes": scopes, "windows": windows, "horizons": HORIZONS,
                "atomic_cut": {"kind": "authoritative_snapshot_at_event_time", "evidence": "synthetic_evidence.json; fictional premise only"},
                "continuity": {"kind": "sampled_snapshots", "max_gap_ns": NS, "cadence_ns": NS,
                               "observed_max_gap_ns": NS, "all_venue_events_observed": False},
                "review": {"status": "not_issued_by_producer"},
                "limitations": ["Not empirical evidence", "No authentic exchange, receipt, priority or fill claim", "Origin must survive projection"]}
    write_json(target / "affirmative_shared_contract.json", contract)
    negative = deepcopy(contract)
    for s in negative["scopes"].values():
        s.update(decision="negative", reason="Fictional negative fixture")
    negative["windows"] = []
    write_json(target / "negative_shared_contract.json", negative)
    exchange = deepcopy(rows[:3])
    for r in exchange:
        r["release_ns"] = None
        r["admission_evidence_ns"] = None
    write_json(target / "exchange_time_unknown_receipt_sample.json", exchange)
    return rows, contract


def consumer_fixtures(rows, contract):
    """Produce explicit legacy projections, with fictional review markers throughout."""
    import numpy as np
    target = OUT / "fixtures"
    arr = {"event_ns": np.array([r["event_ns"] for r in rows], dtype=np.int64)}
    arr.update(available_ns=arr["event_ns"].copy(), known_ns=arr["event_ns"].copy())
    for field, key in (("bid", "bid_prices_units8"), ("ask", "ask_prices_units8"),
                       ("bid_size", "bid_sizes_units8"), ("ask_size", "ask_sizes_units8")):
        arr[field] = np.array([r[key][0] / SCALE for r in rows])
    np.savez_compressed(target / "q17_synthetic_bbo.npz", **arr)
    grid = {"times_ns": arr["event_ns"], "release_ns": arr["event_ns"].copy(),
            "certificate_known_ns": arr["event_ns"].copy(), "segment_id": np.zeros(len(rows), dtype=np.int64)}
    for key in ("top5_complete", "clock_causal", "atomic_complete"):
        grid[key] = np.ones(len(rows), bool)
    for field, key in (("bid_px", "bid_prices_units8"), ("ask_px", "ask_prices_units8"),
                       ("bid_qty", "bid_sizes_units8"), ("ask_qty", "ask_sizes_units8")):
        grid[field] = np.array([[v / SCALE for v in r[key]] for r in rows])
    np.savez_compressed(target / "q18_synthetic_grid.npz", **grid)
    q18 = {"schema": "q18-producer-v2", "producer": "T-008", "version": "2.0.0", "origin": "synthetic",
           "evidence_origin": "synthetic_integration", "fixture_only": True, "status": "scoped_ready",
           "asset": "BTC", "clock_scope": "exchange_time", "source_kind": "synthetic_fixture",
           "source_provenance": {"description": "T-008 synthetic complete-at-cut snapshots",
                                 "source_files": contract["sources"], "timestamp_semantics": "Fictional exchange UTC ns; no historical receive-time claim",
                                 "admission_rule": "Past-only last observed state; fixture has one exact row per second"},
           "scopes": {"Q18": {"admissible": True, "top5_complete_at_cuts": True, "state_cut_validated": True, "past_only_selection": True}},
           "grid_file": "q18_synthetic_grid.npz", "grid_sha256": sha256(target / "q18_synthetic_grid.npz"),
           "units": {"times_ns": "UTC Unix nanoseconds", "prices": "USD per BTC", "quantities": "BTC"},
           "windows": [w for w in contract["windows"] if w["scope"] == "Q18"],
           "limitations": ["All data and positive state premises are synthetic", "No market approval or empirical result"]}
    write_json(target / "q18_producer_manifest.json", q18)
    return arr, grid


def legacy_gate_fixtures(contract):
    """Fictional legacy reviews test gates, never authenticate actual data/people."""
    target = OUT / "fixtures"
    sys.path.insert(0, str(ARTIFACTS / "T-010/code"))
    sys.path.insert(0, str(ARTIFACTS / "T-011/code"))
    sys.path.insert(0, str(ARTIFACTS / "T-009/code"))
    from q17_transfer import gate as q17gate
    from q17_transfer.protocol import LABEL_SPEC, PROTOCOL, digest_json
    from q18_adapter.contracts import implementation_hashes
    from admission import REQUIRED_CHECKS
    marker = {"origin": "synthetic_integration", "fixture_only": True,
              "issuer_context": "FICTIONAL reviewer fixture for software integration; no approval of market data"}
    shared = {"contract_id": "T-008-shared-data", "version": "2.0.0-synthetic-legacy-projection",
              "status": "certified", **marker,
              "canonical_producer_file": "affirmative_shared_contract.json",
              "canonical_producer_sha256": sha256(target / "affirmative_shared_contract.json"),
              "scopes": {"Q17": {"admissible": True},
                         "Q18": {"admissible": True, "full_top5": True, "causal_availability": True,
                                 "atomic_order": True, "continuous_windows": True}},
              "admissible_windows": [{**w, "date": "2025-12-01", "full_top5": w["scope"] == "Q18"} for w in contract["windows"]]}
    write_json(target / "synthetic_legacy_shared.json", shared)
    data = {"schema_version": "q17-input-certificate/1", "issuer": "T-008", "status": "affirmative", **marker,
            "shared_contract_file": "synthetic_legacy_shared.json", "shared_contract_sha256": sha256(target / "synthetic_legacy_shared.json"),
            "window_id": "synthetic-btc-q17", "assertions": dict.fromkeys(q17gate.REQUIRED, True),
            "availability_kind": "causal_delayed_release", "purpose": "december1_development", "asset": "BTC", "date": "2025-12-01",
            "data_file": "q17_synthetic_bbo.npz", "data_sha256": sha256(target / "q17_synthetic_bbo.npz")}
    write_json(target / "q17_synthetic_data_certificate.json", data)
    labels = {"schema_version": "q17-label-certificate/1", "issuer": "T-008", "status": "affirmative", **marker,
              "data_certificate_sha256": sha256(target / "q17_synthetic_data_certificate.json"), "label_spec_sha256": digest_json(LABEL_SPEC)}
    write_json(target / "q17_synthetic_labels_certificate.json", labels)
    write_json(target / "q17_synthetic_review.json", {"schema_version": "q17-coordinator-review/1", "status": "approved",
               "reviewer_role": "coordinator", **marker, "data_certificate_sha256": sha256(target / "q17_synthetic_data_certificate.json"),
               "label_certificate_sha256": sha256(target / "q17_synthetic_labels_certificate.json"),
               "protocol_sha256": digest_json(PROTOCOL), "implementation_sha256": q17gate.implementation_sha256()})
    protocol = json.loads((ARTIFACTS / "T-011/protocol.json").read_text())
    protocol.update(marker)
    protocol["implementation_sha256"] = implementation_hashes()
    write_json(target / "q18_synthetic_protocol.json", protocol)
    execution = {"schema": "q18-execution-v1", "experiment_id": "E-018", **marker,
                 "shared_contract_sha256": sha256(target / "synthetic_legacy_shared.json"),
                 "protocol_sha256": sha256(target / "q18_synthetic_protocol.json"), "development_only": True,
                 "asset": "BTC", "clock": "certified_causal_release_grid", "splits": protocol["splits"],
                 "grid_file": "q18_synthetic_grid.npz", "grid_sha256": sha256(target / "q18_synthetic_grid.npz")}
    write_json(target / "q18_synthetic_execution.json", execution)
    write_json(target / "q18_synthetic_review.json", {"status": "approved", "role": "coordinator", **marker,
               "shared_contract_sha256": sha256(target / "synthetic_legacy_shared.json"),
               "protocol_sha256": sha256(target / "q18_synthetic_protocol.json"),
               "execution_manifest_sha256": sha256(target / "q18_synthetic_execution.json"),
               "reviewed_at_utc": "2026-09-21T00:00:00Z", "review_id": "fictional-fixture-not-a-person"})
    def diff(seq, oid, change):
        return {"raw_seq": seq, "coin": "BTC", "side": "B", "px": "100", "oid": oid, "raw_book_diff": change}
    def event(kind, fragments, fills=()):
        t = START + fragments[-1]["raw_seq"] * 10_000_000
        return {"kind": kind, "event_ns": t, "available_ns": t, "evidence_refs": ["fictional-atomic-event"],
                "diffs": fragments, "fills": list(fills)}
    ep = {"episode_id": "producer-synthetic-cancellable", "coin": "BTC", "side": "B", "px": "100",
          "probe_id": "p", "probe_cancellable": True, "initial": [{"oid": "a", "sz": "2"}, {"oid": "p", "sz": "3"}],
          "start_ns": START, "initial_available_ns": START, "initial_raw_seq": 0, "anchor_source_ordinal": 0,
          "horizon_complete": True, "events": [
              event("T", [diff(1, "a", "remove"), diff(2, "p", {"update": {"origSz": "3", "newSz": "2"}})], [{"oid": "a", "sz": "2"}, {"oid": "p", "sz": "1"}]),
              event("C", [diff(3, "p", {"update": {"origSz": "2", "newSz": "1"}})]),
              event("A", [diff(4, "b", {"new": {"sz": "2"}})]),
              event("T", [diff(5, "p", "remove")], [{"oid": "p", "sz": "1"}]),
              event("A", [diff(6, "c", {"new": {"sz": "1"}})]),
              event("C", [diff(7, "b", "remove")]),
              event("A", [diff(8, "d", {"new": {"sz": "1"}})]),
              event("T", [diff(9, "c", "remove")], [{"oid": "c", "sz": "1"}])], **marker}
    write_json(target / "q16_synthetic_episodes.json", [ep])
    q16 = {"schema_version": "q16-admission-v1", "version": "2.0.0-synthetic-projection", "issuer_task": "T-008", "decision": "affirmative", **marker,
           "scope": {"experiment": "E-016", "coin": "BTC", "use": "development_pilot", "start_ns": START, "end_ns": START+NS},
           "checks": {key: {"passed": True, "evidence": "Fictional producer fixture premise; no historical claim"} for key in REQUIRED_CHECKS},
           "episodes_sha256": sha256(target / "q16_synthetic_episodes.json"),
           "projection": {"positive_queue": "size > 0 only", "shadow_identity": "retained to explicit remove",
                          "cleanup_is_economic_event": False, "quantity_quantum": "1", "quantum_is_historical_claim": False}}
    write_json(target / "q16_synthetic_contract.json", q16)
    write_json(target / "q16_synthetic_review.json", {"decision": "approved", "role": "coordinator", **marker,
               "contract_sha256": sha256(target / "q16_synthetic_contract.json"), "review_evidence": "FICTIONAL SOFTWARE FIXTURE ONLY"})


def run_checks(rows, contract, schemas):
    import jsonschema
    import numpy as np
    results = []
    def check(name, f):
        try:
            detail = f()
            results.append({"name": name, "passed": True, "detail": detail})
        except Exception as exc:
            results.append({"name": name, "passed": False, "error": type(exc).__name__ + ": " + str(exc)})
    def reject(f):
        try:
            f()
        except ValueError as exc:
            return str(exc)
        raise AssertionError("Expected fail-closed rejection")
    def assert_true(value):
        assert value
        return True
    target = OUT / "fixtures"
    check("producer_schema", lambda: jsonschema.validate(contract, schemas[1]))
    validator = jsonschema.Draft202012Validator(schemas[0])
    def validate_all_rows():
        for row in rows:
            validator.validate(row)
        return {"rows": len(rows)}
    check("all_3601_state_row_schema", validate_all_rows)
    check("producer_affirmative_source_integrity", lambda: validate_contract(contract, target))
    check("producer_sampled_state_invariants", lambda: validate_rows(rows, NS))
    check("producer_negative", lambda: validate_contract(json.loads((target / "negative_shared_contract.json").read_text()), target))
    tamper = deepcopy(contract); tamper["sources"][0]["sha256"] = "0" * 64
    check("source_hash_tamper_rejected", lambda: reject(lambda: validate_contract(tamper, target)))
    check("origin_laundering_rejected", lambda: reject(lambda: validate_contract(contract, target, "exploratory_real")))
    inversion = deepcopy(rows[:3]); inversion[2]["event_ns"] = inversion[0]["event_ns"]
    check("event_inversion_rejected_without_sort", lambda: reject(lambda: validate_rows(inversion, NS)))
    check("gap_rejected", lambda: reject(lambda: validate_rows([rows[0], rows[2]], NS)))
    unknown = json.loads((target / "exchange_time_unknown_receipt_sample.json").read_text())
    check("exchange_scope_allows_truthful_unknown_receipt", lambda: validate_rows(unknown, NS))
    check("receive_scope_rejects_missing_receipt", lambda: reject(lambda: validate_rows(unknown, NS, clock_scope="observed_receive_time")))
    check("off_lattice_rejected", lambda: reject(lambda: units8("0.000000001")))
    check("units8_exact", lambda: assert_true(units8("0.00123456") == 123456))
    check("float_quantity_rejected", lambda: reject(lambda: units8(0.1)))
    official_shape = {"coin": "BTC", "time": START // 1_000_000,
                      "levels": [[{"px": "89999", "sz": "0.1", "n": 2}], [{"px": "90001", "sz": "0.2", "n": 3}]]}
    check("official_l2_shape_exact_normalization", lambda: assert_true(snapshot_row(official_shape, "synthetic", 0)["bid_prices_units8"] == [8_999_900_000_000]))
    decision = START + 100 * NS
    for end_delta in (10_000_000_000, 10_250_000_000, 10_500_000_000):
        check(f"q18_boundary_{end_delta}_rejected", lambda d=end_delta: assert_true(not eligible({"start_ns": START, "end_ns": decision+d}, decision, "Q18")))
    check("q18_guard_plus_one_ns_admitted", lambda: assert_true(eligible({"start_ns": START, "end_ns": decision+10_500_000_001}, decision, "Q18")))
    check("q17_single_guard_not_schedule_guard", lambda: assert_true(not eligible({"start_ns": START, "end_ns": decision+120*NS}, decision, "Q17_scheduling")))
    old = ARTIFACTS / "T-008/shared_data_contract.v1.0.0.json"
    check("actual_v1_negative_bytes_preserved", lambda: assert_true(sha256(old) == OLD_HASH))
    sys.path.insert(0, str(ARTIFACTS / "T-010/code"))
    sys.path.insert(0, str(ARTIFACTS / "T-011/code"))
    from q17_transfer.gate import inspect_shared_contract, require_certificates
    from q17_transfer.features import build_arrays
    from q18_adapter.contracts import review_gate, load_reviewed_grid
    from q18_adapter.features import Split, build_dataset
    from admission import load_admitted
    from adapter import adapt_episode
    check("q17_r1_actual_v1_negative_rejected", lambda: assert_true(not inspect_shared_contract(old)["admitted"]))
    check("q17_r1_canonical_v2_requires_explicit_translation", lambda: assert_true(not inspect_shared_contract(target / "affirmative_shared_contract.json")["admitted"]))
    check("q17_r1_synthetic_positive_chain", lambda: assert_true(require_certificates(
        target / "q17_synthetic_data_certificate.json", target / "q17_synthetic_labels_certificate.json",
        target / "q17_synthetic_review.json")["data"]["origin"] == "synthetic_integration"))
    q18args = [target / f for f in ("q18_synthetic_execution.json", "q18_synthetic_review.json", "q18_synthetic_protocol.json")]
    check("q18_r1_actual_v1_negative_rejected", lambda: assert_true(not review_gate(old, *q18args)["admissible"]))
    check("q18_r1_synthetic_positive_chain", lambda: assert_true(review_gate(target / "synthetic_legacy_shared.json", *q18args)["admissible"]))
    check("q18_r1_synthetic_full_grid_loading", lambda: {k: len(v["times_ns"]) for k, v in load_reviewed_grid(
        review_gate(target / "synthetic_legacy_shared.json", *q18args), target).items()})
    q16config = {"contract_path": target / "q16_synthetic_contract.json", "coordinator_review_path": target / "q16_synthetic_review.json", "episodes_path": target / "q16_synthetic_episodes.json"}
    check("q16_r1_actual_v1_negative_rejected", lambda: reject(lambda: load_admitted({**q16config, "contract_path": old})))
    check("q16_r1_synthetic_positive_chain", lambda: assert_true(load_admitted(q16config)[0]["origin"] == "synthetic_integration"))
    check("q16_r1_synthetic_episode", lambda: assert_true(adapt_episode(load_admitted(q16config)[1][0], "1")["status"] == "scored"))
    with np.load(target / "q17_synthetic_bbo.npz", allow_pickle=False) as f:
        bbo = {k: f[k] for k in f.files}
    check("q17_actual_feature_path_on_producer_projection", lambda: {"rows": len(build_arrays(bbo, "validation", START, START+3601*NS)["times"]), "origin": "synthetic_integration"})
    def check_classes():
        counts = {}
        for i, name in enumerate(("train", "validation", "test")):
            values = build_arrays(bbo, name, START+i*1200*NS, START+(i+1)*1200*NS)
            labels, numbers = np.unique(values["y"], return_counts=True)
            assert labels.tolist() == [0, 1, 2], (name, labels)
            counts[name] = dict(zip(map(str, labels.tolist()), numbers.tolist()))
        return counts
    check("q17_three_classes_in_each_chronological_third", check_classes)
    with np.load(target / "q18_synthetic_grid.npz", allow_pickle=False) as f:
        grid = {k: f[k] for k in f.files}
    check("q18_actual_feature_path_on_producer_projection", lambda: {k: len(v["times_ns"]) for k, v in build_dataset(grid, [Split("train", START, START+2400*NS), Split("evaluation", START+2400*NS, START+3601*NS)]).items()})
    result = {"origin": "synthetic_integration", "fixture_only": True, "seed": 20260919,
              "counts": {"passed": sum(x["passed"] for x in results), "failed": sum(not x["passed"] for x in results)},
              "checks": results, "scientific_claim": "Software integration only; zero market observations/fits/approvals", "pending": ["Consumer owners integrate r2 gates with current producer interface", "Producer cannot issue independent review"]}
    write_json(OUT / "tests.json", result)
    assert result["counts"]["failed"] == 0, result
    return result


if __name__ == "__main__":
    started = time.perf_counter()
    OUT.mkdir(parents=True, exist_ok=True)
    schemas = make_schema()
    rows, contract = make_fixtures()
    consumer_fixtures(rows, contract)
    legacy_gate_fixtures(contract)
    result = run_checks(rows, contract, schemas)
    result["elapsed_seconds"] = time.perf_counter() - started
    write_json(OUT / "tests.json", result)
    print(json.dumps({"counts": result["counts"], "elapsed_seconds": result["elapsed_seconds"]}))
