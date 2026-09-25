"""Fixed thirty-second source-quality adaptation; independent immutable edition.

This module never acquires data or fits models. The parent panel protocol selects
dates and periods before payload inspection. Event time selects the observation;
the provider receipt string remains separate provenance, not measured latency.
"""
from bisect import bisect_right
from copy import deepcopy
import csv
from datetime import datetime, timezone
from decimal import Decimal
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import statistics
import sys
import time
from urllib.parse import parse_qs, urlsplit

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
R2 = ROOT.parent / "r2"
SPEC = importlib.util.spec_from_file_location("t008_r2_producer", R2 / "code/producer_interface.py")
P = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(P)
NS = 1_000_000_000
OFFSETS17 = (-20*NS, -5*NS, -NS, 0, NS//10, NS//2, 10*NS, 101*NS//10, 105*NS//10)
OFFSETS18 = tuple(range(-75*NS, 10*NS+1, NS)) + (105*NS//10,)


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True)+"\n", encoding="utf-8", newline="\n")


def write_jsonl(path, values):
    with Path(path).open("w", encoding="utf-8", newline="\n") as stream:
        for value in values:
            stream.write(json.dumps(value, separators=(",", ":"))+"\n")


def utc_ns(text):
    """Parse fractional ISO time exactly; datetime alone truncates submicroseconds."""
    whole, fraction = text.rstrip("Z").split(".") if "." in text else (text.rstrip("Z"), "")
    if not text.endswith("Z") or len(fraction) > 9 or (fraction and not fraction.isdigit()):
        raise ValueError("Expected UTC ISO timestamp with at most nine decimal places")
    return int(datetime.strptime(whole, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc).timestamp())*NS + int(fraction.ljust(9, "0") or 0)


def verify_acquisition(record):
    """Verify compressed response and decoded bytes, even when only gzip is retained."""
    path = Path(record["compressed_path"])
    if record.get("status") != 200 or record.get("completed") is not True:
        raise ValueError("Acquisition did not complete successfully")
    digest = record.get("compressed_sha256", record.get("body_sha256"))
    size = record.get("compressed_bytes", record.get("received_body_bytes"))
    if path.stat().st_size != size or P.sha256(path) != digest:
        raise ValueError("Compressed acquisition bytes/hash mismatch")
    decoded = hashlib.sha256()
    total = 0
    with gzip.open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1024*1024), b""):
            total += len(block)
            decoded.update(block)
    if total != record["decoded_bytes"] or decoded.hexdigest() != record["decoded_sha256"]:
        raise ValueError("Decoded acquisition bytes/hash mismatch")
    return {"record": deepcopy(record), "compressed_sha256": digest,
            "decoded_sha256": decoded.hexdigest(), "decoded_bytes": total,
            "gzip_crc_and_decoded_hash_reverified": True,
            "authenticity_limit": "Integrity to provider HTTP response; not independent exchange authentication"}


def verify_policy_binding(records, date, roles, policy, policy_hash, start_ns, end_ns):
    midnight = utc_ns(date+"T00:00:00Z")
    for scope in ("Q17", "Q18"):
        if roles[scope] != policy["roles_"+scope][date]:
            raise ValueError("Requested role differs from frozen source protocol")
    expected_offsets = list(range((start_ns-midnight)//(60*NS), (end_ns-midnight)//(60*NS), 10))
    if [record["offset"] for record in records] != expected_offsets:
        raise ValueError("Acquired slices do not cover the predeclared ordered period")
    for record in records:
        query = parse_qs(urlsplit(record["url"]).query)
        expected_remote_partition = "hyperliquid/"+date.replace("-", "/")+f"/{record['offset']//60:02d}/{record['offset']%60:02d}"
        if (record["date"] != date or record["role"] != roles["Q17"] or record["protocol_sha256"] != policy_hash
                or urlsplit(record["url"]).netloc != "api.tardis.dev"
                or urlsplit(record["url"]).path != "/v1/data-feeds/hyperliquid"
                or query.get("from") != [date+"T00:00:00.000Z"]
                or query.get("offset") != [str(record["offset"])]
                or query.get("sliceSize") != ["10"]
                or query.get("compression") != ["gzip"]
                or record["response_headers"].get("x-name") != expected_remote_partition
                or record["response_headers"].get("x-slice-size") != "10"
                or json.loads(query["filters"][0]) != [{"channel": "l2Book", "symbols": ["BTC", "ETH"]}]):
            raise ValueError("Acquisition date/role/filter/offset/HTTP partition/source/protocol binding failed")


def record_lines(records):
    ordinal = 0
    for chunk_number, record in enumerate(records):
        with gzip.open(record["compressed_path"], "rt", encoding="utf-8", newline="") as stream:
            for local_ordinal, line in enumerate(stream):
                if line.strip() and "date" in record:
                    receipt = utc_ns(line.split(" ", 1)[0])
                    boundary = utc_ns(record["date"]+"T00:00:00Z")+record["offset"]*60*NS
                    if not boundary <= receipt < boundary+600*NS:
                        raise ValueError("Provider receipt falls outside the requested HTTP archive slice")
                yield ordinal, chunk_number, local_ordinal, line.rstrip("\r\n")
                ordinal += 1


def normalize_lines(lines, date, start_ns, end_ns, max_gap_ns):
    """Keep source order and verify full depth before projecting a common top five."""
    rows = {asset: [] for asset in ("BTC", "ETH")}
    provenance = {asset: [] for asset in rows}
    duplicates = {asset: [] for asset in rows}
    segments = {asset: [] for asset in rows}
    previous = {}
    segment_first = {asset: 0 for asset in rows}
    retained_epoch = {}
    epoch = 0
    disconnects = []
    excluded = {asset: {"before": 0, "after": 0} for asset in rows}
    previous_receipt = None
    prefix_exclusions = []
    prefix_end = utc_ns(date+"T00:00:00Z")+30*NS
    for ordinal, chunk_number, local_ordinal, line in lines:
        if not line.strip():
            epoch += 1
            disconnects.append({"source_ordinal": ordinal, "chunk_number": chunk_number,
                                "chunk_line_ordinal": local_ordinal, "disconnect_epoch": epoch})
            continue
        receipt, encoded = line.split(" ", 1)
        receipt_ns = utc_ns(receipt)
        if receipt_ns < prefix_end:
            prefix_payload = json.loads(encoded)
            prefix_exclusions.append({"source_ordinal":ordinal,"chunk_number":chunk_number,"chunk_line_ordinal":local_ordinal,
                "provider_receipt_text":receipt,"provider_receipt_ns":receipt_ns,"asset":prefix_payload["data"]["coin"],
                "event_ns":prefix_payload["data"]["time"]*1_000_000,"full_payload_sha256":hashlib.sha256(encoded.encode()).hexdigest(),
                "reason":"fixed_provider_receipt_prefix_before_UTC_00_00_30"})
            continue
        if previous_receipt is not None and receipt_ns < previous_receipt:
            raise ValueError("Provider receipt inversion across source rows/slices")
        previous_receipt = receipt_ns
        envelope = json.loads(encoded)
        if envelope.get("channel") != "l2Book":
            raise ValueError(f"Unexpected channel at source ordinal {ordinal}")
        data = envelope["data"]
        asset = data["coin"]
        if asset not in rows:
            raise ValueError("Asset differs from predeclared BTC/ETH source filter")
        source_id = f"tardis-hyperliquid-{date}-{asset.lower()}"
        row = P.snapshot_row(data, source_id, ordinal)
        P.validate_rows([row], max_gap_ns, depth=5)
        if any(x is None for side in ("bid", "ask") for x in row[side+"_counts"]):
            raise ValueError("Expected positive native order counts on every supplied level")
        event = row["event_ns"]
        old = previous.get(asset)
        if old and event < old["event_ns"]:
            raise ValueError(f"Source event inversion at ordinal {ordinal}; sorting forbidden")
        if old and event == old["event_ns"] and envelope != old["payload"]:
            raise ValueError(f"Conflicting full-depth equal-time payload at ordinal {ordinal}")
        equal = bool(old and event == old["event_ns"])
        previous[asset] = {"event_ns": event, "payload": envelope}
        if not start_ns <= event < end_ns:
            excluded[asset]["before" if event < start_ns else "after"] += 1
            continue
        provenance[asset].append({"source_ordinal": ordinal, "chunk_number": chunk_number,
            "chunk_line_ordinal": local_ordinal, "provider_receipt_text": receipt,
            "provider_receipt_ns": receipt_ns, "provider_receipt_role": "provider archive collection timestamp, uncalibrated; not release/admission",
            "event_ns": event, "disconnect_epoch": epoch, "raw_bid_depth": len(data["levels"][0]),
            "raw_ask_depth": len(data["levels"][1]), "full_payload_sha256": hashlib.sha256(encoded.encode()).hexdigest()})
        if equal:
            if not rows[asset] or rows[asset][-1]["event_ns"] != event:
                raise ValueError("Equal-time retained observation has no earlier in-period row")
            duplicates[asset].append({"event_ns": event, "retained_source_ordinal": rows[asset][-1]["source_ordinal"],
                "duplicate_source_ordinal": ordinal, "reason": "identical_full_native_payload"})
            continue
        if rows[asset] and (event-rows[asset][-1]["event_ns"] > max_gap_ns or retained_epoch[asset] != epoch):
            segments[asset].append((segment_first[asset], len(rows[asset])))
            segment_first[asset] = len(rows[asset])
        for side in ("bid", "ask"):
            for field in ("prices_units8", "sizes_units8", "counts"):
                row[side+"_"+field] = row[side+"_"+field][:5]
        rows[asset].append(row)
        retained_epoch[asset] = epoch
    for asset in rows:
        if rows[asset]:
            segments[asset].append((segment_first[asset], len(rows[asset])))
    return rows, provenance, duplicates, segments, disconnects, excluded, prefix_exclusions


def asof(events, cut, max_age_ns):
    index = bisect_right(events, cut)-1
    return index if index >= 0 and cut-events[index] <= max_age_ns else None


def describe(values):
    if not values:
        return {"count": 0, "minimum": None, "median": None, "mean": None, "maximum": None}
    return {"count": len(values), "minimum": min(values), "median": statistics.median(values),
            "mean": statistics.mean(values), "maximum": max(values)}


def audit(rows, segments, policy, output):
    """Future coverage is a retrospective mask, though each asof selection is past-only."""
    ages = {"all_valid_1s_cuts": [], "Q17_required_cuts": [], "Q18_required_cuts": []}
    eligible = {"Q17": [], "Q18": []}
    same = {"100ms": {"same": 0, "total": 0}, "500ms": {"same": 0, "total": 0},
            "10s_to_10.1s": {"same": 0, "total": 0}, "10s_to_10.5s": {"same": 0, "total": 0}}
    windows, segment_records = [], []
    valid_grid = 0
    grid_count = 0
    max_age = policy["max_age_ns"]
    with (output / "grid_audit.csv").open("w", newline="", encoding="utf-8") as grid_stream, \
            (output / "q17_required_cut_audit.csv").open("w", newline="", encoding="utf-8") as q17_stream, \
            (output / "q18_endpoint_audit.csv").open("w", newline="", encoding="utf-8") as q18_stream:
        grid = csv.writer(grid_stream)
        q17 = csv.writer(q17_stream)
        q18 = csv.writer(q18_stream)
        grid.writerow(["cut_ns", "segment_id", "valid", "source_ordinal", "snapshot_event_ns", "asof_age_ns"])
        q17.writerow(["decision_ns", "segment_id", "offset_ns", "cut_ns", "source_ordinal", "snapshot_event_ns", "asof_age_ns"])
        q18.writerow(["decision_ns", "segment_id", "history_first_event_ns", "decision_event_ns", "label_event_ns", "guard_event_ns", "maximum_support_age_ns"])
        for sid, (first, stop) in enumerate(segments):
            part = rows[first:stop]
            events = [row["event_ns"] for row in part]
            begin, end = events[0], events[-1]+1
            segment_records.append({"segment_id": sid, "first_row_index": first, "stop_row_index": stop,
                "start_ns": begin, "end_ns": end, "first_source_ordinal": part[0]["source_ordinal"],
                "last_source_ordinal": part[-1]["source_ordinal"]})
            local_eligible = {"Q17": 0, "Q18": 0}
            for cut in range(((begin+NS-1)//NS)*NS, end, NS):
                index = asof(events, cut, max_age)
                grid_count += 1
                if index is None:
                    grid.writerow([cut, sid, False, "", "", ""])
                else:
                    age = cut-events[index]
                    grid.writerow([cut, sid, True, part[index]["source_ordinal"], events[index], age])
                    ages["all_valid_1s_cuts"].append(age)
                    valid_grid += 1
                for scope, offsets in (("Q17", OFFSETS17), ("Q18", OFFSETS18)):
                    if cut+offsets[0] < begin or cut+offsets[-1] >= end:
                        continue
                    indices = [asof(events, cut+offset, max_age) for offset in offsets]
                    if any(index is None for index in indices):
                        continue
                    local_eligible[scope] += 1
                    eligible[scope].append({"cut_ns": cut, "segment_id": sid})
                    selected_ages = [cut+offset-events[index] for offset, index in zip(offsets, indices)]
                    ages[scope+"_required_cuts"].extend(selected_ages)
                    if scope == "Q17":
                        for offset, index, age in zip(offsets, indices, selected_ages):
                            q17.writerow([cut, sid, offset, cut+offset, part[index]["source_ordinal"], events[index], age])
                        for label, a, b in (("100ms", 3, 4), ("500ms", 3, 5), ("10s_to_10.1s", 6, 7), ("10s_to_10.5s", 6, 8)):
                            same[label]["same"] += int(indices[a] == indices[b])
                            same[label]["total"] += 1
                    else:
                        q18.writerow([cut, sid, events[indices[0]], events[indices[75]], events[indices[85]], events[indices[-1]], max(selected_ages)])
            for scope, lookback in (("Q17", 20*NS), ("Q18", 75*NS)):
                if local_eligible[scope]:
                    windows.append({"window_id": f"{part[0]['source_id']}-{scope}-{sid}", "scope": scope,
                        "asset": part[0]["asset"], "start_ns": begin, "end_ns": end,
                        "first_source_ordinal": part[0]["source_ordinal"], "last_source_ordinal": part[-1]["source_ordinal"],
                        "state_depth": 1 if scope == "Q17" else 5, "source_ids": [part[0]["source_id"]],
                        "evidence_ids": ["acquisition-proof", "full-depth-validation", "source-segments", "required-cut-audit"],
                        "segment_id": sid, "lookback_ns": lookback, "forward_guard_ns": 105*NS//10,
                        "max_age_ns": max_age, "use": "prespecified_chronological_split",
                        "eligibility_rule": "Every required task cut must pass same-segment past-only asof freshness; final mask is retrospective"})
    qualified = {(row["cut_ns"], row["segment_id"]) for row in eligible["Q17"]}
    schedules = [{"first_cut_ns": row["cut_ns"], "last_cut_ns": row["cut_ns"]+121*NS, "segment_id": row["segment_id"]}
        for row in eligible["Q17"] if row["cut_ns"] % (11*NS) == 0
        and all((row["cut_ns"]+i*11*NS, row["segment_id"]) in qualified for i in range(12))]
    disjoint = []
    for row in schedules:
        if not disjoint or row["first_cut_ns"] > disjoint[-1]["last_cut_ns"]:
            disjoint.append(row)
    for item in same.values():
        item["rate"] = item["same"]/item["total"] if item["total"] else None
    result = {"grid_cuts": grid_count, "valid_grid_cuts": valid_grid,
        "counts": {scope: len(values) for scope, values in eligible.items()}, "decisions": eligible,
        "q17_schedule_12x11s": schedules, "q17_disjoint_schedule_12x11s": disjoint,
        "grid_anchor": "UTC Unix epoch; consumers retain declared protocol grid",
        "mask_semantics": "Retrospective future coverage/freshness mask; not known online at decision",
        "does_not_certify_consumer_features_or_fits": True}
    write_json(output / "eligibility_diagnostics.json", result)
    write_json(output / "source_segments.json", segment_records)
    write_json(output / "clock_diagnostics.json", {"age_units": "nanoseconds", "ages": {key: describe(value) for key, value in ages.items()},
        "same_source_observation_rates": same, "Q17_required_offsets_ns": OFFSETS17,
        "Q18_required_offsets_ns": OFFSETS18, "Q18_full_support_evidence": "Every integer-second support cut is retained in grid_audit.csv; fractional guard in endpoint audit",
        "same_observation_interpretation": "100/500ms offsets may select identical archived observations; this does not measure actual execution latency"})
    return result, windows, segment_records


def build_day(records, date, roles, policy, output, start_ns=None, end_ns=None, policy_path=None):
    """Normalize one predeclared paired period; immutable output must not already exist."""
    output = Path(output)
    if output.exists():
        raise ValueError("Output already exists; issue a new version rather than overwrite frozen bytes")
    started = time.perf_counter()
    midnight = utc_ns(date+"T00:00:00Z")
    start_ns = midnight if start_ns is None else start_ns
    end_ns = midnight+3600*NS if end_ns is None else end_ns
    if policy_path is not None:
        ancestor_path = ROOT / policy["supersedes_policy_file"]
        if P.sha256(ancestor_path) != policy["supersedes_policy_sha256"] or policy["startup_exclusion_ns"] != 30*NS:
            raise ValueError("Startup policy ancestry or fixed cutoff mismatch")
        ancestor = json.loads(ancestor_path.read_text(encoding="utf-8-sig"))
        if any(policy["roles_"+scope] != ancestor["roles_"+scope] for scope in ("Q17","Q18")):
            raise ValueError("Startup adaptation cannot change calendar or roles")
        verify_policy_binding(records, date, roles, ancestor, P.sha256(ancestor_path), midnight, end_ns)
        if start_ns != midnight+30*NS:
            raise ValueError("Analytical start must exclude exactly the fixed thirty-second prefix")
    proofs = [verify_acquisition(record) for record in records]
    raw_rows, provenance, duplicates, segments, disconnects, excluded, prefix_exclusions = normalize_lines(record_lines(records), date, start_ns, end_ns, policy["max_gap_ns"])
    output.mkdir(parents=True)
    (output / "executed_paired_normalize.py").write_bytes(Path(__file__).read_bytes())
    proof_path = output / "acquisition_proof.json"
    write_json(proof_path, {"schema": "t008-tardis-acquisition-proof/1", "date": date,
        "records_in_source_order": proofs, "selection_event_start_ns": start_ns, "selection_event_end_ns": end_ns,
        "receipt_partition_warning": "HTTP archive slices use provider receipt time; event-time period is selected explicitly without extending source support"})
    write_json(output / "disconnect_markers.json", disconnects)
    write_jsonl(output / "receipt_prefix_exclusions.jsonl", prefix_exclusions)
    summaries = []
    eligibility = {}
    for asset in ("BTC", "ETH"):
        target = output / asset
        target.mkdir()
        rows = raw_rows[asset]
        if not rows:
            write_json(target / "unavailable.json", {"asset": asset, "date": date, "reason": "No in-period observations", "excluded": excluded[asset]})
            continue
        write_jsonl(target / "state_rows.jsonl", rows)
        write_jsonl(target / "source_provenance.jsonl", provenance[asset])
        write_json(target / "duplicate_ledger.json", duplicates[asset])
        diagnostics, windows, segment_records = audit(rows, segments[asset], policy, target)
        eligibility[asset] = diagnostics
        gaps = [b["event_ns"]-a["event_ns"] for a,b in zip(rows, rows[1:])]
        source = {"source_id": rows[0]["source_id"], "file": "state_rows.jsonl", "sha256": P.sha256(target / "state_rows.jsonl"),
            "provenance": "Tardis third-party archive claiming directly collected Hyperliquid l2Book WebSocket messages; not independently authenticated exchange export",
            "rights": "Public first-day samples used for local research; no redistribution rights independently certified",
            "acquisition_proof_file": "../acquisition_proof.json", "acquisition_proof_sha256": P.sha256(proof_path)}
        contract = {"schema": "t008-producer-state/2", "version": "2.2.0", "producer": "T-008", "origin": "exploratory_real",
            "fixture_only": False, "purpose": "historical_paired_hyperliquid_sampled_state_adaptation", "asset": asset, "date": date,
            "split_roles": roles, "sources": [source], "units": {"time": "UTC Unix ns", "price": "USD per base asset multiplied by1e8",
                "size": "base asset multiplied by1e8", "count": "positive visible native order count"},
            "policy_file": str(policy_path) if policy_path else None, "policy_sha256": P.sha256(policy_path) if policy_path else None,
            "scopes": {scope: {"decision": "affirmative" if scope != "Q16" and diagnostics["counts"][scope] else "negative",
                "reason": "Source-dependent sampled snapshot observations for exploratory aggregate analysis" if scope != "Q16" else "No participant identity, FIFO, atomic group or fill allocation proof",
                "clock_scope": "exchange_time" if scope != "Q16" else "not_certified", "state_scope": "none" if scope == "Q16" else "bbo_at_snapshot_cuts" if scope == "Q17" else "top5_at_snapshot_cuts",
                "continuity_scope": "sampled_snapshots"} for scope in ("Q16", "Q17", "Q18")},
            "windows": windows, "horizons": P.HORIZONS,
            "atomic_cut": {"kind": "authoritative_snapshot_at_event_time", "authority_scope": "claimed_by_third_party_archive_only",
                "evidence": "A complete native l2Book-shaped message supplies both sides at data.time; snapshot authority remains conditional on provider collection claim"},
            "continuity": {"kind": "sampled_snapshots", "max_gap_ns": policy["max_gap_ns"], "max_age_ns": policy["max_age_ns"],
                "cadence_ns": NS, "cadence_role": "consumer audit grid, not native source cadence", "observed_max_gap_ns": max(gaps, default=0),
                "all_venue_events_observed": False, "source_segments_file": "source_segments.json", "source_segments_sha256": P.sha256(target / "source_segments.json"),
                "gap_policy": "Split successive source gaps exceeding policy and every blank disconnect marker; all cuts must stay in one segment"},
            "review": {"status": "not_issued_by_producer"}, "clock_scope": "exchange_time", "source_authenticity": "third_party_not_independently_authenticated",
            "receipt_semantics": "Provider receipt is separate uncalibrated provenance; release_ns and admission_evidence_ns are null",
            "actual_first_event_ns": rows[0]["event_ns"], "actual_last_event_ns": rows[-1]["event_ns"],
            "selected_event_start_ns": start_ns, "selected_event_end_ns": end_ns,
            "acquisition_proof_file": "../acquisition_proof.json", "acquisition_proof_sha256": P.sha256(proof_path),
            "normalizer_code_sha256": P.sha256(__file__), "reused_producer_code_sha256": P.sha256(R2 / "code/producer_interface.py"),
            "normalizer_source_file": "../executed_paired_normalize.py",
            "eligibility_mask": "Final future coverage/freshness population is retrospective; past-only feature selection is separate",
            "limitations": ["Cross-month paired period adaptation; original source claims and full-day criterion remain distinct",
                "No historical release/admission latency calibration", "No complete venue-event continuity, FIFO, identities or counterfactual fills",
                "All eight Q18 views derive from this same top-five L2 stream", "No model fits or scientific acceptance issued by producer"]}
        contract.update(version="2.3.0", adaptation_class="SOURCE-QUALITY-INFORMED POST-ACQUISITION PRE-FIT",
            startup_exclusion_ns=30*NS, source_acquisition_policy_file=str(ancestor_path), source_acquisition_policy_sha256=P.sha256(ancestor_path),
            source_provenance_file="source_provenance.jsonl", source_provenance_sha256=P.sha256(target / "source_provenance.jsonl"),
            receipt_prefix_exclusions_file="../receipt_prefix_exclusions.jsonl", receipt_prefix_exclusions_sha256=P.sha256(output / "receipt_prefix_exclusions.jsonl"),
            selection_qualification=policy["selection_qualification"], restart_claim=policy["restart_claim"], fit_authorization_gate=policy["fit_authorization_gate"])
        contract["sources"][0].update(source_provenance_file="source_provenance.jsonl",source_provenance_sha256=contract["source_provenance_sha256"])
        contract["evidence_files"] = {name:P.sha256(target / name) for name in ("eligibility_diagnostics.json","clock_diagnostics.json","grid_audit.csv","q17_required_cut_audit.csv","q18_endpoint_audit.csv","duplicate_ledger.json")}
        write_json(target / "shared_data_contract.v2.3.0.json", contract)
        summary = {"asset": asset, "date": date, "split_roles": roles, "rows": len(rows), "raw_in_period_rows": len(provenance[asset]),
            "duplicates": len(duplicates[asset]), "segments": len(segments[asset]), "excluded_by_event_period": excluded[asset],
            "gap_ns": describe(gaps), "Q17_eligible_cuts": diagnostics["counts"]["Q17"], "Q18_eligible_cuts": diagnostics["counts"]["Q18"],
            "Q17_schedules_overlapping": len(diagnostics["q17_schedule_12x11s"]), "Q17_schedules_disjoint": len(diagnostics["q17_disjoint_schedule_12x11s"]),
            "contract_file": str(target / "shared_data_contract.v2.3.0.json"), "contract_sha256": P.sha256(target / "shared_data_contract.v2.3.0.json"),
            "state_rows_sha256": source["sha256"], "actual_first_event_ns": rows[0]["event_ns"], "actual_last_event_ns": rows[-1]["event_ns"]}
        summary["provider_receipt_diagnostics"] = {"inversions": 0, "first_ns": provenance[asset][0]["provider_receipt_ns"],
            "last_ns": provenance[asset][-1]["provider_receipt_ns"], "exact_slice_range_verified": policy_path is not None,
            "interpretation": "Provider metadata ordering and request partition consistency, not latency calibration"}
        summary["observed_raw_depths"] = sorted({(row["raw_bid_depth"], row["raw_ask_depth"]) for row in provenance[asset]})
        write_json(target / "summary.json", summary)
        summaries.append(summary)
    pairing = {}
    if len(eligibility) == 2:
        for scope in ("Q17", "Q18"):
            cuts = sorted(set(x["cut_ns"] for x in eligibility["BTC"]["decisions"][scope]) & set(x["cut_ns"] for x in eligibility["ETH"]["decisions"][scope]))
            pairing[scope] = {"count": len(cuts), "cut_ns": cuts}
    result = {"date": date, "split_roles": roles, "assets": summaries, "paired_common_cuts": pairing,
        "pairing_semantics": "Matched calendar cuts, each asset separately satisfies source age; not synchronous venue event assertion",
        "disconnect_markers": len(disconnects), "prefix_excluded_raw_messages":len(prefix_exclusions),
        "adaptation_class":"SOURCE-QUALITY-INFORMED POST-ACQUISITION PRE-FIT", "elapsed_seconds": time.perf_counter()-started, "model_fits": 0}
    write_json(output / "paired_summary.json", result)
    return result


def verify_output(asset_output):
    """Recheck emitted payloads against the bound contract and raw source provenance."""
    target = Path(asset_output)
    contract_path = target / "shared_data_contract.v2.3.0.json"
    contract = json.loads(contract_path.read_text())
    source = contract["sources"][0]
    if P.sha256(target / source["file"]) != source["sha256"]:
        raise ValueError("Normalized state hash mismatch")
    for filename, digest in ((contract["acquisition_proof_file"], contract["acquisition_proof_sha256"]),
                             (contract["source_provenance_file"], contract["source_provenance_sha256"]),
                             (contract["receipt_prefix_exclusions_file"], contract["receipt_prefix_exclusions_sha256"]),
                             (contract["continuity"]["source_segments_file"], contract["continuity"]["source_segments_sha256"]),
                             (contract["normalizer_source_file"], contract["normalizer_code_sha256"])):
        if P.sha256(target / filename) != digest:
            raise ValueError("Contract evidence hash mismatch")
    rows = [json.loads(line) for line in (target / source["file"]).read_text().splitlines()]
    segments = json.loads((target / contract["continuity"]["source_segments_file"]).read_text())
    provenance = {row["source_ordinal"]: row for row in (json.loads(line) for line in (target / "source_provenance.jsonl").read_text().splitlines())}
    for segment in segments:
        part = rows[segment["first_row_index"]:segment["stop_row_index"]]
        P.validate_rows(part, contract["continuity"]["max_gap_ns"], depth=5)
        if segment["start_ns"] != part[0]["event_ns"] or segment["end_ns"] != part[-1]["event_ns"]+1:
            raise ValueError("Segment boundary differs from source observations")
        for row in part:
            if row["release_ns"] is not None or row["admission_evidence_ns"] is not None or provenance[row["source_ordinal"]]["event_ns"] != row["event_ns"]:
                raise ValueError("Clock/provenance readback failed")
    return {"passed": True, "rows_verified": len(rows), "segments_verified": len(segments), "contract_sha256": P.sha256(contract_path)}


def emit_schema(output):
    """Extend the reviewed v2 shape without claiming inherited scientific approval."""
    schema = json.loads((R2 / "interface/shared_data_contract.schema.json").read_text())
    schema["title"] = "T-008 fixed thirty-second startup adaptation producer contract2.3.0"
    schema["properties"]["version"] = {"const": "2.3.0"}
    schema["properties"]["purpose"] = {"const": "historical_paired_hyperliquid_sampled_state_adaptation"}
    for key in ("asset", "date", "split_roles", "acquisition_proof_file", "acquisition_proof_sha256", "eligibility_mask", "receipt_semantics"):
        schema["required"].append(key)
    schema["properties"]["split_roles"] = {"type": "object", "required": ["Q17", "Q18"], "properties": {
        scope: {"enum": ["train", "validation", "test", "unused", "development"]} for scope in ("Q17", "Q18")}}
    schema["properties"]["continuity"]["required"].extend(["max_age_ns", "source_segments_file", "source_segments_sha256"])
    schema["properties"]["continuity"]["properties"]["max_age_ns"] = {"type": "integer", "minimum": 0}
    schema["required"].extend(["startup_exclusion_ns","source_provenance_file","source_provenance_sha256","source_acquisition_policy_file","source_acquisition_policy_sha256","receipt_prefix_exclusions_file","receipt_prefix_exclusions_sha256","adaptation_class","selection_qualification","fit_authorization_gate"])
    Path(output).mkdir(parents=True, exist_ok=True)
    write_json(Path(output) / "shared_data_contract.v2.3.0.schema.json", schema)
    return schema
