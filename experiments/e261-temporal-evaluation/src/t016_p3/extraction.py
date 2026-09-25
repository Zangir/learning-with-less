"""Date-local E261 extraction using unchanged P0/P1 rules; no fitting or import I/O."""
from bisect import bisect_right
from collections import Counter
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path

import numpy as np

from t016_p0.engine import AGE, GAP, NS, Observations, extract, retrospective_support, row_validity, stable_hash
from t016_p0.integrity import check_file, read_json
from t016_p1.cohort_io import compact_cuts, dump_json, dump_lines, load_day
from t016_p1.features import AUX_INPUT_NAMES, X_NAMES, Z_NAMES, readiness_reason, views
from t016_p1.labels import label_event
from t016_p1.specification import P0_SHA

CLASS_ORDER = ("F", "A", "N")
FAMILIES = ("breakout", "rebound")


def _audit_source_file(directory, member, contract, segments, start, end, source_id):
    """Check every normalized physical line, including any line load_day might skip."""
    assert contract["asset"] == "BTC" and contract["date"] == member["date"]
    assert (contract["selected_event_start_ns"], contract["selected_event_end_ns"]) == (start, end)
    assert contract["continuity"]["max_age_ns"] == AGE
    assert contract["continuity"]["max_gap_ns"] == GAP
    assert len(contract["sources"]) == 1
    source = contract["sources"][0]
    assert source["file"] == "state_rows.jsonl" and source["source_id"] == source_id
    assert segments and len({s["segment_id"] for s in segments}) == len(segments)
    expected_index = 0
    for segment in segments:
        assert segment["first_row_index"] == expected_index
        assert segment["stop_row_index"] > expected_index
        assert start <= segment["start_ns"] < segment["end_ns"] <= end
        if "row_count" in segment:
            assert segment["row_count"] == segment["stop_row_index"] - expected_index
        expected_index = segment["stop_row_index"]

    digest, segment_index, count = sha256(), 0, 0
    previous_time = previous_ordinal = first_time = last_time = None
    segment_audits, max_gap = [], 0
    with (directory / "state_rows.jsonl").open("rb") as stream:
        for index, raw in enumerate(stream):
            digest.update(raw)
            value = json.loads(raw)
            assert index < expected_index, "Source has rows outside declared segment coverage"
            while index >= segments[segment_index]["stop_row_index"]:
                segment_index += 1
            segment = segments[segment_index]
            stamp, ordinal = value["event_ns"], value["source_ordinal"]
            assert type(stamp) is int and type(ordinal) is int
            assert start <= stamp < end, "Normalized contract contains an out-of-window row"
            assert value["asset"] == "BTC" and value["source_id"] == source_id
            assert value["release_ns"] is None and value["admission_evidence_ns"] is None
            assert row_validity(value, 5) is None, "Malformed normalized top-five row"
            if previous_time is not None:
                assert stamp > previous_time and ordinal > previous_ordinal
                gap = stamp - previous_time
                max_gap = max(max_gap, gap)
                if index > segment["first_row_index"]:
                    assert gap <= GAP, "Unsegmented normalized source gap"
            if index == segment["first_row_index"]:
                assert stamp == segment["start_ns"]
                assert ordinal == segment["first_source_ordinal"]
            if index == segment["stop_row_index"] - 1:
                assert stamp + 1 == segment["end_ns"]
                assert ordinal == segment["last_source_ordinal"]
                segment_audits.append({
                    **segment, "rows_checked": segment["stop_row_index"] - segment["first_row_index"],
                    "exact_start_end_ordinals": True,
                })
            if first_time is None:
                first_time = stamp
            last_time, previous_time, previous_ordinal = stamp, stamp, ordinal
            count += 1
    assert count == expected_index and len(segment_audits) == len(segments)
    assert count > 0, "No normalized observations in the fixed date contract"
    assert digest.hexdigest() == source["sha256"].lower()
    assert first_time == contract["actual_first_event_ns"]
    assert last_time == contract["actual_last_event_ns"]
    return {
        "scope": "Current normalized-file consumer audit; no raw replay, exchange authentication or RV013 admission claim",
        "date": member["date"], "contract_sha256": member["contract_sha256"],
        "source_id": source_id, "source_sha256": digest.hexdigest(),
        "physical_rows_checked": count, "declared_segment_rows": expected_index,
        "actual_first_event_ns": first_time, "actual_last_event_ns": last_time,
        "restriction_start_ns": start, "restriction_end_ns": end,
        "max_observed_adjacent_gap_ns": max_gap, "strict_time_and_ordinal_order": True,
        "all_normalized_rows_inside_restriction": True, "all_top_five_rows_valid": True,
        "all_segment_ranges_contiguous_and_complete": True, "segments": segment_audits,
    }


def _audit_loaded_and_lookup(rows, provenance, obs, arrays, source_audit):
    """Independent searchsorted check of compact cut joins and supported ages."""
    assert len(rows) == source_audit["physical_rows_checked"]
    assert len(provenance) == len(rows)
    assert [r["physical_line_1_based"] for r in rows] == list(range(1, len(rows) + 1))
    assert len({r["source_ordinal"] for r in rows}) == len(rows)
    epoch_sets = {}
    for row in rows:
        witness = provenance[row["source_ordinal"]]
        assert witness["event_ns"] == row["event_ns"]
        assert witness["disconnect_epoch"] == row["disconnect_epoch"]
        epoch_sets.setdefault(row["segment_id"], set()).add(row["disconnect_epoch"])
    assert all(len(epochs) == 1 for epochs in epoch_sets.values())
    times = np.array([r["event_ns"] for r in rows], dtype=np.int64)
    ordinals = np.array([r["source_ordinal"] for r in rows], dtype=np.int64)
    sids = np.array([r["segment_id"] for r in rows], dtype=np.int64)
    assert np.all(np.diff(times) > 0) and np.all(np.diff(ordinals) > 0)
    indices = np.searchsorted(times, arrays["cut_ns"], side="right") - 1
    expected_valid = np.zeros(len(indices), dtype=bool)
    selected = indices >= 0
    valid_indices = indices[selected]
    assert np.array_equal(arrays["source_ordinal"][selected], ordinals[valid_indices])
    assert np.array_equal(arrays["source_row_index"][selected], valid_indices)
    assert np.array_equal(arrays["event_ns"][selected], times[valid_indices])
    assert np.array_equal(arrays["segment_id"][selected], sids[valid_indices])
    ages = arrays["cut_ns"][selected] - times[valid_indices]
    assert np.array_equal(arrays["age_ns"][selected], ages)
    assert np.all(ages >= 0)
    starts = np.array([obs.segments[int(sid)]["start_ns"] for sid in sids[valid_indices]], dtype=np.int64)
    ends = np.array([obs.segments[int(sid)]["end_ns"] for sid in sids[valid_indices]], dtype=np.int64)
    cuts = arrays["cut_ns"][selected]
    expected_valid[selected] = (ages <= AGE) & (cuts >= starts) & (cuts < ends)
    assert np.array_equal(arrays["valid_bbo"], expected_valid)
    assert np.array_equal(arrays["valid_depth"], expected_valid)
    assert np.all(arrays["source_ordinal"][~selected] == -1)
    assert not np.any(arrays["valid_bbo"][~selected])
    assert obs.end == min(obs.restriction_end, int(times[-1]) + 1)
    return {
        "normalized_rows_joined": len(rows), "unique_source_ordinals": len(rows),
        "physical_lines_complete": True, "provenance_event_and_epoch_equal": True,
        "constant_epoch_per_segment": True, "searchsorted_cuts_checked": len(indices),
        "searchsorted_source_joins_equal": True, "independent_support_mask_equal": True,
        "valid_ages_inclusive_0_to_1500000000_ns": True,
    }


def _check_label_oracle(event, label):
    refs = label["future_refs"]
    assert len(refs) == 10 and [r["k"] for r in refs] == list(range(1, 11))
    assert [r["cut_ns"] for r in refs] == [event["decision_ns"] + k * NS for k in range(1, 11)]
    failures = [ref for ref in refs if not ref["valid"]]
    assert label["complete_future_support"] == (not failures)
    if failures:
        assert label["label"] is None and label["first_hit_k"] is None and label["first_hit_cut_ns"] is None
        assert label["first_bad_cut_ns"] == failures[0]["cut_ns"]
        assert label["censor_reason"] == failures[0]["reason"]
        return
    numerator = event["epsilon2"]["numerator"]
    denominator = event["epsilon2"]["denominator"]
    assert numerator > 0 and denominator > 0
    signed = [event["direction"] * (ref["mid2"] - event["decision_mid2"]) * denominator for ref in refs]
    favorable = [k + 1 for k, value in enumerate(signed) if value >= 2 * numerator]
    adverse = [k + 1 for k, value in enumerate(signed) if value <= -numerator]
    first_f, first_a = min(favorable, default=11), min(adverse, default=11)
    assert first_f != first_a or first_f == 11
    expected = "N" if min(first_f, first_a) == 11 else ("F" if first_f < first_a else "A")
    expected_k = None if expected == "N" else min(first_f, first_a)
    assert (label["label"], label["first_hit_k"]) == (expected, expected_k)
    assert label["first_hit_cut_ns"] == (None if expected_k is None else event["decision_ns"] + expected_k * NS)


def _prefix_check(rows, segments, start, end, data, labels):
    target = start - 30 * NS + 43200 * NS
    stop = bisect_right([row["event_ns"] for row in rows], target)
    if not stop:
        return {"available": False, "reason": "No source rows before fixed noon prefix", "nominal_second": 43200}
    obs = Observations(rows[:stop], segments, start, end)
    prefix = extract(obs, P0_SHA)
    common = obs.times[-1] // NS * NS
    for name, key in (("events", "decision_ns"), ("candidates", "decision_ns"),
                      ("levels", "anchor_ns"), ("blocked_cuts", "cut_ns")):
        assert prefix[name] == [record for record in data[name] if record[key] <= common], name
    full_labels = {label["event_id"]: label for label in labels}
    nonnull = censored = tail_changes = 0
    for event in prefix["events"]:
        label = label_event(obs, event)
        if event["decision_ns"] + 10 * NS <= common:
            assert label == full_labels[event["event_id"]]
            nonnull += int(label["label"] is not None)
            censored += int(label["label"] is None)
        else:
            tail_changes += int(label != full_labels[event["event_id"]])
    return {
        "available": True, "nominal_second": 43200, "watermark_ns": obs.times[-1],
        "common_finalized_cut_ns": common, "causal_records_equal": True,
        "finalized_horizon_records_equal": nonnull + censored,
        "finalized_nonnull_labels_equal": nonnull, "finalized_censored_records_equal": censored,
        "unfinished_tail_label_changes": tail_changes,
    }


def run_day(member, dest, protocol_sha):
    """Write one frozen date and return arrays for every recorded opportunity.

    ``dest`` must not exist. The caller owns the pre-execution code/input freeze,
    complete producer bindings and final cross-date embargo audit. An optional
    member['earlier_dependency_end_ns'] applies that predecessor in readiness.
    No date-specific thresholds, outcome-selected examples or model calls occur.
    """
    dest, directory = Path(dest), Path(member["contract_file"]).parent
    dest.mkdir(parents=True, exist_ok=False)
    contract_identity = check_file(Path(member["contract_file"]), member["contract_sha256"])
    contract = read_json(Path(member["contract_file"]))
    date = member["date"]
    calendar_day = datetime.fromisoformat(date).replace(tzinfo=timezone.utc)
    day = int(calendar_day.timestamp()) * NS
    start, end = day + 30 * NS, day + 86400 * NS
    next_month = calendar_day.replace(year=calendar_day.year + 1, month=1) if calendar_day.month == 12 else calendar_day.replace(month=calendar_day.month + 1)
    partition_end = int(next_month.timestamp()) * NS
    source_id = "tardis-hyperliquid-" + date + "-btc"
    segment_path = directory / contract["continuity"]["source_segments_file"]
    segment_identity = check_file(segment_path, contract["continuity"]["source_segments_sha256"])
    segments = read_json(segment_path)
    source_audit = _audit_source_file(directory, member, contract, segments, start, end, source_id)
    source_audit.update(contract_identity=contract_identity, segment_identity=segment_identity)
    dump_json(dest / "source-audit.json", source_audit)
    rows, provenance, obs = load_day(directory, segments, start, end, source_id)
    data = extract(obs, P0_SHA)
    assert all(a["decision_ns"] <= b["decision_ns"] for a, b in zip(data["events"], data["events"][1:]))
    assert len({event["event_id"] for event in data["events"]}) == len(data["events"])
    example_ids = {}
    for event in data["events"]:
        example_ids.setdefault(event["family"], event["event_id"])
    before = stable_hash(data)
    labels = [label_event(obs, event) for event in data["events"]]
    assert stable_hash(data) == before
    masks = retrospective_support(obs, data["events"])
    for event, label, mask in zip(data["events"], labels, masks):
        _check_label_oracle(event, label)
        assert all(mask[key] == label[key] for key in ("complete_future_support", "censor_reason", "first_bad_cut_ns"))
    cut_arrays, availability = compact_cuts(obs, data)
    lookup_audit = _audit_loaded_and_lookup(rows, provenance, obs, cut_arrays, source_audit)
    prefix = _prefix_check(rows, segments, start, end, data, labels)
    levels = {level["anchor_ns"]: level for level in data["levels"]}
    first_cut = int(cut_arrays["cut_ns"][0]) if len(cut_arrays["cut_ns"]) else start
    compact_events, population, examples, auxiliary = [], [], [], {}
    x_rows, z_rows, target_rows = [], [], []
    previous_end = member.get("earlier_dependency_end_ns")
    for event, label in zip(data["events"], labels):
        cut = event["decision_ns"]
        index = (cut - first_cut) // NS
        first, level = index - 60, levels[event["anchor_ns"]]
        assert first >= 0 and np.all(cut_arrays["valid_depth"][first:index + 1])
        assert cut_arrays["source_ordinal"][first:index + 1].tolist() == event["history_source_ordinals"]
        assert int(cut_arrays["cut_ns"][index]) == cut
        assert np.all(cut_arrays["event_ns"][first:index + 1] <= cut_arrays["cut_ns"][first:index + 1])
        assert np.all(cut_arrays["segment_id"][first:index + 1] == event["segment_id"])
        level_first = (event["anchor_ns"] - 60 * NS - first_cut) // NS
        level_stop = level_first + 60
        assert level_first >= 0
        assert cut_arrays["source_ordinal"][level_first:level_stop].tolist() == level["source_ordinals"]
        x, z, target = views(cut_arrays["book_units8_counts"][first:index + 1],
                             cut_arrays["age_ns"][first:index + 1], cut, level, event)
        assert np.array_equal(np.concatenate((x, z))[:len(X_NAMES)], x)
        x_rows.append(x); z_rows.append(z); target_rows.append(target)
        actual_times = cut_arrays["event_ns"][level_first:level_stop].tolist()
        actual_times += cut_arrays["event_ns"][first:index + 1].tolist()
        actual_times += [ref["event_ns"] for ref in label["future_refs"] if "event_ns" in ref]
        compact = {key: value for key, value in event.items() if key not in ("feature_history", "history_source_ordinals")}
        compact.update(
            extension_protocol_sha256=protocol_sha, date=date, contract_sha256=member["contract_sha256"],
            feature_cut_index_start=first, feature_cut_index_stop=index + 1,
            level_cut_index_start=level_first, level_cut_index_stop=level_stop, decision_cut_index=index,
            dependency_min_ns=min(event["anchor_ns"] - 60 * NS, *actual_times),
            dependency_max_ns=max(cut + 10 * NS, *actual_times),
            feature_vector_sha256=sha256(x.tobytes()).hexdigest(),
            Z_vector_sha256=sha256(z.tobytes()).hexdigest(), current_target_sha256=sha256(target.tobytes()).hexdigest(),
        )
        compact_events.append(compact)
        readiness = readiness_reason(compact, day, partition_end, previous_end)
        support_reason = None if label["complete_future_support"] else "future_support:" + label["censor_reason"]
        reason = support_reason or readiness
        member_population = {
            "date": date, "role": "fixed_later_evaluation", "event_id": event["event_id"],
            "family": event["family"], "label": label["label"], "matched_eligible": reason is None,
            "exclusion": reason, "readiness_exclusion": readiness, "support_exclusion": support_reason,
            "shared_arms": ["C", "P", "R"], "decision_ns": cut,
        }
        population.append(member_population)
        auxiliary_record = {
            "date": date, "decision_ns": cut, "cut_index": index, "source_id": source_id,
            "source_ordinal": event["decision_source_ordinal"], "target": target.tolist(),
            "input_sha256": sha256(x[:len(AUX_INPUT_NAMES)].tobytes()).hexdigest(),
            "dependency_min_ns": min(cut - 60 * NS, int(cut_arrays["event_ns"][first:index + 1].min())),
            "dependency_max_ns": cut, "population": "past-only, before future support; inference/diagnostics only",
        }
        if cut in auxiliary:
            assert auxiliary[cut] == auxiliary_record
        else:
            auxiliary[cut] = auxiliary_record
        if event["event_id"] == example_ids[event["family"]]:
            row = obs.rows[obs.grid[cut]["row_index"]]
            examples.append({
                "date": date, "family": event["family"], "available": True,
                "selection": "first chronological recorded past-eligible event per family/date, selected before labels/support",
                "event": compact, "decision_row": row, "decision_provenance": provenance[row["source_ordinal"]],
                "level": level, "label_record": label, "matched_eligible": reason is None, "exclusion": reason,
                "X_first7": x[:7].tolist(), "X_current7": x[420:427].tolist(),
                "current_auxiliary_target": target.tolist(),
            })
    examples += [{"date": date, "family": family, "available": False,
                  "selection": "first chronological recorded past-eligible event per family/date, selected before labels/support",
                  "reason": "No recorded past-eligible event in the fixed date"}
                 for family in FAMILIES if family not in example_ids]
    n = len(compact_events)
    arrays = {
        "X": np.asarray(x_rows, dtype="<f8").reshape(n, len(X_NAMES)),
        "Z": np.asarray(z_rows, dtype="<f8").reshape(n, len(Z_NAMES)),
        "targets": np.asarray(target_rows, dtype="<f8").reshape(n, 7),
        "event_ids": np.array([event["event_id"] for event in compact_events], dtype="U64"),
        "families": np.array([event["family"] for event in compact_events], dtype="U8"),
        "labels": np.array([label["label"] or "" for label in labels], dtype="U1"),
        "y": np.array([CLASS_ORDER.index(label["label"]) if label["label"] is not None else -1 for label in labels], dtype=np.int64),
        "matched": np.array([entry["matched_eligible"] for entry in population], dtype=bool),
        "decision_ns": np.array([event["decision_ns"] for event in compact_events], dtype=np.int64),
    }
    assert all(len(value) == n for value in arrays.values())
    assert np.all(arrays["y"][arrays["matched"]] >= 0)
    np.savez_compressed(dest / "cuts.npz", **cut_arrays)
    np.savez_compressed(dest / "feature-vectors.npz", **arrays)
    for name, records in (
        ("events", compact_events), ("labels", labels), ("candidates", data["candidates"]),
        ("blocked_cuts", data["blocked_cuts"]), ("levels", data["levels"]),
        ("support-masks", masks), ("population", population),
        ("auxiliary-current-targets", list(auxiliary.values())),
    ):
        dump_lines(dest / (name + ".jsonl"), records)
    dump_lines(dest / "source-row-provenance.jsonl", ({
        "date": date, "source_id": source_id, "contract_sha256": member["contract_sha256"],
        "source_ordinal": row["source_ordinal"], "event_ns": row["event_ns"],
        "segment_id": row["segment_id"], "physical_line_1_based": row["physical_line_1_based"],
        "source_line_sha256": row["source_line_sha256"], "provenance": provenance[row["source_ordinal"]],
    } for row in rows))
    dump_json(dest / "segments.json", list(obs.segments.values()))
    availability.update(
        source_rows=len(rows), grid_cuts=len(obs.grid), valid_grid_cuts=int(cut_arrays["valid_bbo"].sum()),
        invalid_grid_by_reason=dict(Counter(point["reason"] for point in obs.grid.values() if not point["valid"])),
        blocked_cut_counts=dict(Counter(point["reason"] for point in data["blocked_cuts"])),
        level_counts=dict(Counter("valid" if level["valid"] else level["reason"] for level in data["levels"])),
        original_segments=len(segments), retained_segments=len(obs.segments),
        first_event_ns=obs.times[0], last_event_ns=obs.times[-1], retained_endpoint_exclusive_ns=obs.end,
    )
    counts = []
    for family in FAMILIES:
        candidates = [item for item in data["candidates"] if item["family"] == family]
        group = [label for label in labels if label["family"] == family]
        classes = {name: sum(label["label"] == name for label in group) for name in CLASS_ORDER}
        censored = sum(label["label"] is None for label in group)
        rejected = Counter(item["reason"] for item in candidates if item["status"] == "rejected")
        matched = [item for item in population if item["family"] == family and item["matched_eligible"]]
        assert sum(classes.values()) + censored == len(group)
        assert len(candidates) == len(group) + sum(rejected.values())
        counts.append({
            "date": date, "family": family, "raw_candidates": len(candidates), "recorded": len(group),
            "rejected": sum(rejected.values()), "rejection_reasons": dict(rejected),
            "censored": censored, "censor_reasons": dict(Counter(label["censor_reason"] for label in group if label["label"] is None)),
            "classes": classes, "matched_rows": len(matched), "matched_classes": dict(Counter(item["label"] for item in matched)),
            "readiness_exclusions": dict(Counter(item["exclusion"] for item in population if item["family"] == family and not item["matched_eligible"])),
        })
    checks = {
        "source_and_lookup": lookup_audit, "prefix": prefix,
        "same_row_projections": availability["same_row_projection_checks"],
        "all_event_histories_indexed_exactly": True, "all_views_finite": True,
        "shared_X_equals_R_prefix": True, "no_future_cut_in_X": True,
        "independent_integer_label_oracle_and_support_match": True,
        "event_state_unchanged_after_labels": True, "all_recorded_rows_retained_in_vectors": True,
        "fixed_example_ids_selected_before_labels": example_ids,
        "X_hash_in_event_order": sha256(arrays["X"].tobytes()).hexdigest(),
        "Z_hash_in_event_order": sha256(arrays["Z"].tobytes()).hexdigest(),
        "target_hash_in_event_order": sha256(arrays["targets"].tobytes()).hexdigest(),
        "cross_date_embargo_predecessor_ns": previous_end,
        "cross_date_embargo_verified_here": previous_end is not None,
        "cross_date_requirement": "Caller verifies actual predecessor dependency max to current dependency min >=130s; no month-end proxy",
        "zero_fit_calls": True,
    }
    for name, value in (("availability", availability), ("counts", counts), ("examples", examples), ("checks", checks)):
        dump_json(dest / (name + ".json"), value)
    summary = {
        "date": date, "status": "extracted", "protocol_sha256": protocol_sha,
        "contract_sha256": member["contract_sha256"], "source_id": source_id,
        "recorded": n, "labeled": int(np.count_nonzero(arrays["y"] >= 0)),
        "censored": int(np.count_nonzero(arrays["y"] < 0)), "matched_rows": int(arrays["matched"].sum()),
        "dependency_min_ns": min((event["dependency_min_ns"] for event in compact_events), default=None),
        "dependency_max_ns": max((event["dependency_max_ns"] for event in compact_events), default=None),
        "counts": counts, "availability": availability, "checks": checks,
        "auxiliary_unique_decision_cuts": len(auxiliary), "examples": examples,
        "source_audit": source_audit, "output_directory": str(dest), "fit_calls": 0,
    }
    dump_json(dest / "summary.json", summary)
    return {**arrays, "summary": summary}
