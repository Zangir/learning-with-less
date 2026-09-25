"""Normalize predetermined archived snapshots without inventing observation clocks.

This source-dependent exploratory contract is a candidate for independent review.
No downloads, fits, arbitrary sorts or historical authenticity claims occur here.
"""
from bisect import bisect_right
from datetime import datetime, timezone
import importlib.util
import hashlib
import json
from pathlib import Path
import statistics
from copy import deepcopy
import sys
import time

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "interface/historical_v2_1"
POLICY_PATH = OUT / "policy.json"
NS = 1_000_000_000
MODULE = importlib.util.spec_from_file_location("producer_interface", ROOT / "code/producer_interface.py")
PRODUCER = importlib.util.module_from_spec(MODULE)
MODULE.loader.exec_module(PRODUCER)


def write_json(path, obj):
    PRODUCER.write_json(path, obj)


def read_policy():
    return json.loads(POLICY_PATH.read_text(encoding="utf-8-sig"))


def freeze_schema():
    schema = json.loads((ROOT / "interface/shared_data_contract.schema.json").read_text())
    schema["title"] = "T-008 producer state contract 2.1.0: separate sample age and source gap"
    schema["properties"]["version"] = {"const": "2.1.0"}
    schema["properties"]["purpose"]["enum"].append("historical_hyperliquid_sampled_state_pilot")
    continuity = schema["properties"]["continuity"]
    continuity["required"].append("max_age_ns")
    continuity["properties"]["max_age_ns"] = {"type": "integer", "minimum": 0}
    write_json(OUT / "shared_data_contract.schema.json", schema)
    bound = deepcopy(schema)
    bound["title"] = "T-008 producer state contract 2.1.1: acquisition-bound historical snapshots"
    bound["properties"]["version"] = {"const": "2.1.1"}
    for stem in ("acquisition_chain_verification", "acquisition_proof", "supersedes_contract"):
        bound["required"].extend((stem + "_file", stem + "_sha256"))
        bound["properties"][stem + "_file"] = {"type": "string", "minLength": 1}
        bound["properties"][stem + "_sha256"] = {"type": "string", "pattern": "^[a-f0-9]{64}$"}
    write_json(OUT / "shared_data_contract.v2.1.1.schema.json", bound)
    return schema


def acquisition_proof(path, date, split, policy):
    """Require the acquisition stage's exact member and byte chain, not a label."""
    import lz4.frame
    path = Path(path).resolve()
    sources = ROOT / "sources"
    ledger_path = sources / "acquisition_probe_ledger.json"
    ledger = json.loads(ledger_path.read_text())
    expected_url = ("https://huggingface.co/datasets/" + policy["source_repository"]
                    + "/resolve/" + policy["source_revision"] + "/data_202512.tar")
    if (ledger["revision"] != policy["source_revision"] or ledger["dataset"] != policy["source_repository"]
            or ledger["url"] != expected_url):
        raise ValueError("Acquisition source repository/revision/URL differs from frozen policy")
    if date == "2025-12-01" and split == "development_preflight_only":
        record_path = sources / "paired_hour00_acquisition_result.json"
        record = json.loads(record_path.read_text())
    else:
        record_path = sources / "historical_holdout_acquisition_result.json"
        matches = [r for r in json.loads(record_path.read_text()) if r["date"] == date.replace("-", "")]
        if len(matches) != 1 or matches[0]["predeclared_role"] != split or policy["split_by_date"].get(date) != split:
            raise ValueError("No unique acquired member with predeclared date/split")
        record = matches[0]
    expected_path = (sources / ("btc_" + date.replace("-", "") + "_00.jsonl")).resolve()
    if path != expected_path or ("jsonl_path" in record and path != Path(record["jsonl_path"]).resolve()):
        raise ValueError("Input path is not the acquisition record's immutable member")
    member = record["member"]
    expected_member = "data/" + date.replace("-", "") + "/0/l2Book/BTC.lz4"
    if member["path"] != expected_member or member["size"] != record["compressed_bytes"]:
        raise ValueError("Acquired tar member/path/size mismatch")
    compressed = Path(record.get("compressed_path", path.with_suffix(".lz4"))).resolve()
    if compressed != expected_path.with_suffix(".lz4"):
        raise ValueError("Compressed member path differs from acquisition")
    if (path.stat().st_size != record["decompressed_bytes"] or PRODUCER.sha256(path) != record["decompressed_sha256"]
            or compressed.stat().st_size != record["compressed_bytes"] or PRODUCER.sha256(compressed) != record["compressed_sha256"]):
        raise ValueError("Acquisition compressed/decompressed SHA-256 or size mismatch")
    transfers = [r for r in ledger["transfers"] if r.get("sha256") == record["compressed_sha256"]
                 and r.get("range_start") == member["data_offset"] and r.get("body_bytes_consumed") == member["size"]
                 and r.get("status") == 206]
    if len(transfers) != 1:
        raise ValueError("No unique verified range transfer binds acquired compressed member")
    transfer = transfers[0]
    expected_range = f"bytes {member['data_offset']}-{member['data_offset']+member['size']-1}/933171200"
    if transfer["content_range"] != expected_range:
        raise ValueError("Transfer content range does not bind member offset")
    decoder = lz4.frame.LZ4FrameDecompressor()
    decoded = decoder.decompress(compressed.read_bytes(), max_length=128*1024*1024)
    if not decoder.eof or hashlib.sha256(decoded).hexdigest() != record["decompressed_sha256"]:
        raise ValueError("Compressed archive does not decode to the bound JSONL bytes")
    return {"schema": "t008-immutable-acquisition-proof/1", "source_repository": ledger["dataset"],
            "source_revision": ledger["revision"], "source_url": ledger["url"], "record": record,
            "transfer": transfer, "acquisition_record_source": str(record_path),
            "acquisition_record_sha256_at_verification": PRODUCER.sha256(record_path),
            "acquisition_ledger_source": str(ledger_path), "acquisition_ledger_sha256_at_verification": PRODUCER.sha256(ledger_path),
            "verified_compressed_to_decompressed_bytes": True,
            "authenticity_limit": "Integrity to pinned third-party acquisition, not exchange authentication"}


def bind_acquisition(output, proof):
    output = Path(output)
    proof_path = output / "acquisition_proof.json"
    if proof_path.exists():
        frozen = json.loads(proof_path.read_text())
        for key in ("source_repository", "source_revision", "source_url", "record", "transfer"):
            if frozen[key] != proof[key]:
                raise ValueError("Frozen acquisition proof differs from current verified source")
    else:
        write_json(proof_path, proof)
    contract = json.loads((output / "shared_data_contract.json").read_text())
    if contract["sources"][0]["raw_sha256"] != proof["record"]["decompressed_sha256"]:
        raise ValueError("Issued contract raw SHA does not bind acquisition proof")
    summary = json.loads((output / "summary.json").read_text())
    if (summary["raw_records"] != proof["record"]["records"]
            or summary["actual_first_event_ns"] != proof["record"]["first_exchange_ms"] * 1_000_000
            or summary["actual_last_event_ns"] != proof["record"]["last_exchange_ms"] * 1_000_000):
        raise ValueError("Acquisition record count/event bounds differ from normalized evidence")
    verification = {"schema": "t008-acquisition-chain-verification/1", "origin": "exploratory_real", "passed": True,
                    "contract_sha256": PRODUCER.sha256(output / "shared_data_contract.json"),
                    "acquisition_proof_sha256": PRODUCER.sha256(proof_path), "raw_sha256": proof["record"]["decompressed_sha256"],
                    "compressed_sha256": proof["record"]["compressed_sha256"], "source_revision": proof["source_revision"],
                    "policy_sha256": PRODUCER.sha256(POLICY_PATH), "compressed_and_decompressed_bytes_reverified": True,
                    "lz4_decode_reverified": True, "member_path_date_role_transfer_range_reverified": True,
                    "issued_contract_bytes_preserved": True, "normalizer_code_sha256": PRODUCER.sha256(__file__)}
    write_json(output / "acquisition_chain_verification.json", verification)
    return verification


def issue_bound_contract(output):
    output = Path(output)
    contract = json.loads((output / "shared_data_contract.json").read_text())
    contract["version"] = "2.1.1"
    for stem, name in (("acquisition_chain_verification", "acquisition_chain_verification.json"),
                       ("acquisition_proof", "acquisition_proof.json"), ("supersedes_contract", "shared_data_contract.json")):
        contract[stem + "_file"] = name
        contract[stem + "_sha256"] = PRODUCER.sha256(output / name)
    import jsonschema
    jsonschema.validate(contract, json.loads((OUT / "shared_data_contract.v2.1.1.schema.json").read_text()))
    write_json(output / "shared_data_contract.v2.1.1.json", contract)
    q18 = json.loads((output / "q18_producer_manifest.json").read_text())
    q18.update(version="2.1.1", canonical_contract_file="shared_data_contract.v2.1.1.json",
               canonical_contract_sha256=PRODUCER.sha256(output / "shared_data_contract.v2.1.1.json"),
               acquisition_chain_verification_file=contract["acquisition_chain_verification_file"],
               acquisition_chain_verification_sha256=contract["acquisition_chain_verification_sha256"],
               acquisition_proof_file=contract["acquisition_proof_file"], acquisition_proof_sha256=contract["acquisition_proof_sha256"])
    write_json(output / "q18_producer_manifest.v2.1.1.json", q18)
    summary = json.loads((output / "summary.json").read_text())
    summary.update(contract_file=str(output / "shared_data_contract.v2.1.1.json"),
                   contract_sha256=PRODUCER.sha256(output / "shared_data_contract.v2.1.1.json"),
                   acquisition_proof_sha256=contract["acquisition_proof_sha256"],
                   acquisition_chain_verification_sha256=contract["acquisition_chain_verification_sha256"])
    write_json(output / "summary.v2.1.1.json", summary)
    return summary


def normalize_records(records, source_id, policy, expected_date):
    """Preserve source order; collapse only equal-time identical full-depth data."""
    rows, provenance, duplicates, segments = [], [], [], []
    segment_start = 0
    previous_data = None
    last_event = None
    for ordinal, item in enumerate(records):
        if item.get("ver_num") != 1 or item.get("raw", {}).get("channel") != "l2Book":
            raise ValueError(f"Unexpected envelope at source ordinal {ordinal}")
        data = item["raw"]["data"]
        if data["coin"] != policy["asset"]:
            raise ValueError(f"Unexpected asset at source ordinal {ordinal}")
        row = PRODUCER.snapshot_row(data, source_id, ordinal)
        event = row["event_ns"]
        date = datetime.fromtimestamp(event // NS, tz=timezone.utc).date().isoformat()
        if date != expected_date:
            raise ValueError(f"Actual event date {date} differs from predeclared date {expected_date}")
        # Validate complete supplied depth before taking the common top-five view.
        PRODUCER.validate_rows([row], policy["max_gap_ns"], depth=5)
        provenance.append({"source_ordinal": ordinal, "outer_timestamp_text": item.get("time"),
                           "outer_timestamp_role": "untrusted exporter metadata; never receipt/admission clock",
                           "event_ns": event, "raw_bid_depth": len(row["bid_prices_units8"]),
                           "raw_ask_depth": len(row["ask_prices_units8"])})
        if last_event is not None:
            if event < last_event:
                raise ValueError(f"Event inversion at source ordinal {ordinal}; no sorting permitted")
            if event == last_event:
                if data != previous_data:
                    raise ValueError(f"Conflicting same-time full-depth snapshot at source ordinal {ordinal}")
                duplicates.append({"event_ns": event, "retained_source_ordinal": rows[-1]["source_ordinal"],
                                   "duplicate_source_ordinal": ordinal, "reason": "identical_full_depth_payload"})
                continue
            if event - last_event > policy["max_gap_ns"]:
                segments.append((segment_start, len(rows)))
                segment_start = len(rows)
        for key in ("bid_prices_units8", "ask_prices_units8", "bid_sizes_units8", "ask_sizes_units8", "bid_counts", "ask_counts"):
            row[key] = row[key][:5]
        rows.append(row)
        previous_data = data
        last_event = event
    if rows:
        segments.append((segment_start, len(rows)))
    return rows, provenance, duplicates, segments


def asof_index(events, cutoff, max_age_ns):
    i = bisect_right(events, cutoff) - 1
    if i < 0 or cutoff - events[i] > max_age_ns:
        return None
    return i


def audit_grid(rows, segments, policy):
    """Audit every wall-clock cut, retaining stale cuts instead of compressing gaps."""
    audit, eligible = [], {"Q17": [], "Q18": []}
    windows = []
    for segment_id, (first, stop) in enumerate(segments):
        part = rows[first:stop]
        events = [r["event_ns"] for r in part]
        start, end = events[0], events[-1] + 1
        base_window = {"asset": policy["asset"], "start_ns": start, "end_ns": end,
                       "first_source_ordinal": part[0]["source_ordinal"], "last_source_ordinal": part[-1]["source_ordinal"],
                       "source_ids": [part[0]["source_id"]], "evidence_ids": ["validated-source-order-and-sample-gaps"],
                       "segment_id": segment_id, "max_age_ns": policy["max_age_ns"],
                       "forward_guard_ns": policy["forward_guard_ns"], "use": "prespecified_chronological_split",
                       "eligibility_rule": "Every required cut must independently satisfy past-only asof age; interval endpoints alone do not admit a row"}
        cuts = range(((start + NS - 1) // NS) * NS, end, NS)
        for cut in cuts:
            index = asof_index(events, cut, policy["max_age_ns"])
            item = {"cut_ns": cut, "segment_id": segment_id, "valid": index is not None,
                    "source_ordinal": None if index is None else part[index]["source_ordinal"],
                    "snapshot_event_ns": None if index is None else events[index],
                    "asof_age_ns": None if index is None else cut - events[index],
                    "reason": None if index is not None else "max_age_exceeded"}
            audit.append(item)
            if cut + policy["forward_guard_ns"] >= end:
                continue
            if cut - 20 * NS >= start:
                required_q17 = [-20*NS, -5*NS, -NS, 0, 100_000_000, 500_000_000,
                                10*NS, 10_100_000_000, 10_500_000_000]
                if all(asof_index(events, cut+d, policy["max_age_ns"]) is not None for d in required_q17):
                    eligible["Q17"].append({"cut_ns": cut, "segment_id": segment_id})
            if cut - 75 * NS >= start:
                required_q18 = list(range(-75*NS, 10*NS + 1, NS)) + [policy["forward_guard_ns"]]
                if all(asof_index(events, cut+d, policy["max_age_ns"]) is not None for d in required_q18):
                    eligible["Q18"].append({"cut_ns": cut, "segment_id": segment_id})
        for scope, depth, lookback in (("Q17", 1, 20*NS), ("Q18", 5, 75*NS)):
            if any(x["segment_id"] == segment_id for x in eligible[scope]):
                windows.append({**base_window, "window_id": f"{part[0]['source_id']}-{scope.lower()}-{segment_id}",
                                "scope": scope, "state_depth": depth, "lookback_ns": lookback})
    scheduling = []
    qualified = {(r["cut_ns"], r["segment_id"]) for r in eligible["Q17"]}
    for decision in eligible["Q17"]:
        cut, segment = decision["cut_ns"], decision["segment_id"]
        if cut % (11*NS) == 0 and all((cut + k*11*NS, segment) in qualified for k in range(12)):
            scheduling.append({"first_cut_ns": cut, "last_cut_ns": cut+121*NS, "segment_id": segment})
    return audit, eligible, scheduling, windows


def normalize_file(path, date, split, policy, output):
    path, output = Path(path), Path(output)
    proof = acquisition_proof(path, date, split, policy)
    output.mkdir(parents=True, exist_ok=True)
    with path.open(encoding="utf-8-sig") as stream:
        rows, provenance, duplicates, segments = normalize_records(
            (json.loads(line) for line in stream if line.strip()), f"hf-btc-{date}-00", policy, date)
    if not rows:
        raise ValueError("Archive member contains no snapshots")
    audit, eligible, scheduling, windows = audit_grid(rows, segments, policy)
    def jsonl(name, objects):
        p = output / name
        p.write_text("".join(json.dumps(x, separators=(",", ":")) + "\n" for x in objects), encoding="utf-8")
        return p
    rowfile = jsonl("state_rows.jsonl", rows)
    jsonl("source_provenance.jsonl", provenance)
    jsonl("grid_audit.jsonl", audit)
    write_json(output / "duplicate_ledger.json", duplicates)
    write_json(output / "eligibility_diagnostics.json", {"origin": "exploratory_real", "counts": {q: len(v) for q, v in eligible.items()},
               "decisions": eligible, "q17_schedule_12x11s": scheduling,
               "grid_anchor": "UTC Unix epoch; diagnostic only; consumer fixed protocol retains its declared grid anchor",
               "does_not_certify_consumer_features_or_fits": True})
    max_gap = max((b["event_ns"]-a["event_ns"] for a,b in zip(rows, rows[1:])), default=0)
    source_gaps_ms = [(b["event_ns"]-a["event_ns"])/1_000_000 for a,b in zip(rows,rows[1:])]
    write_json(output / "source_cadence_diagnostics.json", {"origin": "exploratory_real", "unit": "milliseconds",
               "native_source_cadence": {"count": len(source_gaps_ms), "minimum": min(source_gaps_ms, default=0),
                                         "median": statistics.median(source_gaps_ms) if source_gaps_ms else None,
                                         "mean": statistics.mean(source_gaps_ms) if source_gaps_ms else None,
                                         "maximum": max(source_gaps_ms, default=0)},
               "consumer_grid_cadence_ms": 1000,
               "clarification": "contract continuity.cadence_ns is the consumer grid cadence, not native source cadence"})
    scopes = {q: {"decision": "affirmative" if q != "Q16" and eligible[q] else "negative",
                  "reason": "Source-dependent sampled state at cuts; conditional on archive provenance, suitable for exploratory review" if q != "Q16" else "Snapshots do not establish identity, FIFO or observed trade allocation",
                  "clock_scope": "exchange_time" if q != "Q16" else "not_certified", "state_scope": {"Q16": "none", "Q17": "bbo_at_snapshot_cuts", "Q18": "top5_at_snapshot_cuts"}[q],
                  "continuity_scope": "sampled_snapshots"} for q in ("Q16", "Q17", "Q18")}
    source = {"source_id": rows[0]["source_id"], "file": rowfile.name, "sha256": PRODUCER.sha256(rowfile),
              "provenance": "HF asiletto81/hl_btc at pinned revision; uploader claims original Hyperliquid S3 l2Book archive; not authenticated exchange export",
              "rights": "Publicly downloadable third-party archive; no independent exchange redistribution licence verification",
              "raw_file": str(path.resolve()), "raw_sha256": PRODUCER.sha256(path), "source_revision": policy["source_revision"]}
    contract = {"schema": "t008-producer-state/2", "version": "2.1.0", "producer": "T-008", "origin": "exploratory_real", "fixture_only": False,
                "purpose": "historical_hyperliquid_sampled_state_pilot", "asset": policy["asset"], "date": date, "split_role": split,
                "policy_file": str(POLICY_PATH), "policy_sha256": PRODUCER.sha256(POLICY_PATH), "sources": [source],
                "units": {"time": "UTC Unix ns", "price": "USD per BTC multiplied by 1e8", "size": "BTC multiplied by 1e8", "count": "positive visible order count or null"},
                "scopes": scopes, "windows": windows, "horizons": PRODUCER.HORIZONS,
                "atomic_cut": {"kind": "authoritative_snapshot_at_event_time", "evidence": "Every l2Book source message supplies both ordered sides at its raw.data.time; authority is conditional on the third-party archive claim, not independently authenticated"},
                "continuity": {"kind": "sampled_snapshots", "max_gap_ns": policy["max_gap_ns"], "max_age_ns": policy["max_age_ns"],
                               "cadence_ns": NS, "observed_max_gap_ns": max_gap, "all_venue_events_observed": False,
                               "gap_policy": "split when raw successive timestamp gap>2s; max-age separately enforced at every required decision cut"},
                "review": {"status": "not_issued_by_producer"}, "clock_scope": "exchange_time",
                "source_authenticity": "not_independently_authenticated", "actual_first_event_ns": rows[0]["event_ns"], "actual_last_event_ns": rows[-1]["event_ns"],
                "limitations": ["Separate BTC historical sampled-state pilot, not December1 participant-linked mandatory transfer", "No measured historical receipt or admission clock", "Sampled state, not full event continuity, fill truth or venue FIFO", "Per-cut age and source segment constraints must survive each consumer translation", "Exploratory producer scope requires independent scientific review"]}
    write_json(output / "shared_data_contract.json", contract)
    q18 = {"schema": "q18-producer-v2", "producer": "T-008", "version": "2.1.0", "origin": "real", "evidence_origin": "exploratory_real", "fixture_only": False,
           "status": "scoped_ready" if eligible["Q18"] else "not_ready", "asset": "BTC", "clock_scope": "exchange_time",
           "source_kind": "third_party_archived_l2_snapshots", "source_provenance": {"description": source["provenance"], "source_files": [source],
                            "timestamp_semantics": "raw.data.time integer UTC Unix milliseconds converted exactly to ns; outer.time is provenance-only",
                            "admission_rule": "past-only asof; max_age1.5s; split source gaps>2s; no historical receipt claim"},
           "scopes": {"Q18": {"admissible": bool(eligible["Q18"]), "top5_complete_at_cuts": True, "state_cut_validated": True, "past_only_selection": True}},
           "state_rows_file": str(rowfile.resolve()), "state_rows_sha256": PRODUCER.sha256(rowfile),
           "canonical_contract_file": "shared_data_contract.json", "canonical_contract_sha256": PRODUCER.sha256(output / "shared_data_contract.json"),
           "units": {"event_ns": "UTC Unix nanoseconds", "prices_units8": "USD per BTC multiplied by 1e8", "sizes_units8": "BTC multiplied by 1e8"},
           "windows": [w for w in windows if w["scope"] == "Q18"], "continuity": contract["continuity"], "date": date, "split_role": split,
           "limitations": contract["limitations"]}
    write_json(output / "q18_producer_manifest.json", q18)
    summary = {"date": date, "split_role": split, "origin": "exploratory_real", "raw_records": len(provenance), "normalized_rows": len(rows),
               "identical_ties_collapsed": len(duplicates), "source_segments": len(segments), "source_max_gap_ns": max_gap,
               "grid_cuts": len(audit), "grid_valid": sum(x["valid"] for x in audit), "q17_eligible_diagnostic_cuts": len(eligible["Q17"]),
               "q18_eligible_diagnostic_cuts": len(eligible["Q18"]), "q17_complete_schedule_windows": len(scheduling),
               "actual_first_event_ns": rows[0]["event_ns"], "actual_last_event_ns": rows[-1]["event_ns"], "contract_file": str(output / "shared_data_contract.json"),
               "contract_sha256": PRODUCER.sha256(output / "shared_data_contract.json"), "raw_sha256": source["raw_sha256"]}
    write_json(output / "summary.json", summary)
    write_json(output / "sample_rows.json", [{"units": contract["units"], **r} for r in (rows[0], rows[len(rows)//2], rows[-1])])
    bind_acquisition(output, proof)
    return summary


def run_self_tests(policy):
    results = []
    t = 1765152000000  # Actual 2025-12-08 UTC midnight, fictional book values.
    def raw(offset, price="100"):
        levels = [[{"px": str(int(price)-i), "sz": "1", "n": 1} for i in range(5)],
                  [{"px": str(int(price)+2+i), "sz": "2", "n": 1} for i in range(5)]]
        return {"time": "outer-time-not-a-clock", "ver_num": 1, "raw": {"channel": "l2Book", "data": {"coin": "BTC", "time": t+offset, "levels": levels}}}
    def check(name, fn):
        try:
            fn()
            results.append({"name": name, "passed": True})
        except Exception as exc:
            results.append({"name": name, "passed": False, "error": repr(exc)})
    def assert_that(value):
        assert value
    def rejected(values):
        try:
            normalize_records(values, "synthetic", policy, "2025-12-08")
        except ValueError:
            return
        raise AssertionError("Expected rejection")
    check("conflicting_same_time_reject", lambda: rejected([raw(0), raw(0, "101")]))
    check("source_inversion_reject", lambda: rejected([raw(1), raw(0)]))
    check("identical_tie_preserves_earliest", lambda: assert_that(normalize_records([raw(0), raw(0), raw(1)], "synthetic", policy, "2025-12-08")[2][0]["retained_source_ordinal"] == 0))
    rows, provenance, duplicates, segments = normalize_records([raw(0), raw(1800), raw(3801)], "synthetic", policy, "2025-12-08")
    check("age_and_gap_are_separate", lambda: assert_that(len(segments) == 2 and asof_index([rows[0]["event_ns"],rows[1]["event_ns"]], rows[0]["event_ns"]+1_600_000_000, policy["max_age_ns"]) is None))
    check("unknown_receipt_and_outer_metadata_preserved", lambda: assert_that(rows[0]["release_ns"] is None and rows[0]["admission_evidence_ns"] is None and provenance[0]["outer_timestamp_text"] == "outer-time-not-a-clock"))
    check("age_boundary_inclusive", lambda: assert_that(asof_index([0], 1_500_000_000, policy["max_age_ns"]) == 0 and asof_index([0], 1_500_000_001, policy["max_age_ns"]) is None))
    audit, eligible, scheduling, windows = audit_grid(rows, segments, policy)
    check("grid_never_extends_past_last_actual_source", lambda: assert_that(all(x["cut_ns"] <= rows[-1]["event_ns"] for x in audit)))
    check("short_fragments_yield_no_admissible_window", lambda: assert_that(not windows and not scheduling))
    result = {"origin": "synthetic_integration", "passed": sum(x["passed"] for x in results), "failed": sum(not x["passed"] for x in results), "checks": results}
    write_json(OUT / "synthetic_checks.json", result)
    assert result["failed"] == 0, result
    return result


def verify_normalized_output(output, schema):
    """Read back emitted bytes; bind raw/normalized data and all window boundaries."""
    import jsonschema
    output = Path(output)
    contract = json.loads((output / "shared_data_contract.json").read_text())
    jsonschema.validate(contract, schema)
    source = contract["sources"][0]
    assert PRODUCER.sha256(source["raw_file"]) == source["raw_sha256"]
    assert PRODUCER.sha256(output / source["file"]) == source["sha256"]
    assert PRODUCER.sha256(POLICY_PATH) == contract["policy_sha256"]
    rows = [json.loads(x) for x in (output / source["file"]).read_text().splitlines()]
    row_schema = json.loads((ROOT / "interface/state_row.schema.json").read_text())
    validator = jsonschema.Draft202012Validator(row_schema)
    for row in rows:
        validator.validate(row)
        assert row["release_ns"] is None and row["admission_evidence_ns"] is None
    assert all(a["event_ns"] < b["event_ns"] and a["source_ordinal"] < b["source_ordinal"] for a,b in zip(rows,rows[1:]))
    by_ordinal = {r["source_ordinal"]: r for r in rows}
    for window in contract["windows"]:
        first = by_ordinal[window["first_source_ordinal"]]
        last = by_ordinal[window["last_source_ordinal"]]
        assert window["start_ns"] == first["event_ns"]
        assert window["end_ns"] == last["event_ns"] + 1
    audit = [json.loads(x) for x in (output / "grid_audit.jsonl").read_text().splitlines()]
    for cut in audit:
        assert cut["cut_ns"] <= rows[-1]["event_ns"]
        if cut["valid"]:
            source_row = by_ordinal[cut["source_ordinal"]]
            assert cut["snapshot_event_ns"] == source_row["event_ns"]
            assert 0 <= cut["cut_ns"] - source_row["event_ns"] <= contract["continuity"]["max_age_ns"]
    result = {"origin": "exploratory_real", "readback_passed": True, "state_rows_validated": len(rows),
              "grid_cuts_validated": len(audit), "window_boundaries_validated": len(contract["windows"]),
              "raw_and_normalized_hashes_validated": True, "null_receipt_clocks_preserved": True,
              "contract_sha256": PRODUCER.sha256(output / "shared_data_contract.json"),
              "policy_sha256": contract["policy_sha256"], "no_market_fits_or_scientific_acceptance": True}
    write_json(output / "readback_verification.json", result)
    return result


def main():
    started = time.perf_counter()
    policy = read_policy()
    schema = freeze_schema()
    checks = run_self_tests(policy)
    summaries, missing, failures = [], [], []
    for date, split in policy["split_by_date"].items():
        source = ROOT / "sources" / ("btc_" + date.replace("-", "") + "_00.jsonl")
        if not source.exists():
            missing.append(str(source))
            continue
        output = OUT / date
        try:
            proof = acquisition_proof(source, date, split, policy)
            existing = output / "shared_data_contract.json"
            if existing.exists():
                frozen = json.loads(existing.read_text())
                if (frozen["sources"][0]["raw_sha256"] != PRODUCER.sha256(source)
                        or frozen["policy_sha256"] != PRODUCER.sha256(POLICY_PATH)):
                    raise ValueError("Previously issued candidate has changed source/policy bytes; create a new version")
                summary = json.loads((output / "summary.json").read_text())
            else:
                summary = normalize_file(source, date, split, policy, output)
            verify_normalized_output(output, schema)
            bind_acquisition(output, proof)
            summary = issue_bound_contract(output)
            summaries.append(summary)
        except Exception as exc:
            failures.append({"source": str(source), "error": type(exc).__name__ + ": " + str(exc)})
    result = {"task": "T-008/r2/historical_snapshots", "policy_sha256": PRODUCER.sha256(POLICY_PATH), "origin": "exploratory_real",
              "status": "ready_for_consumer_integration_and_independent_review" if len(summaries) == 3 and not failures else "awaiting_sources_or_rejected_candidate",
              "summaries": summaries, "missing": missing, "failures": failures, "synthetic_checks": checks,
              "elapsed_seconds": time.perf_counter()-started, "model_fits": 0, "actual_review_approvals": 0}
    write_json(OUT / "run_result.json", result)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
