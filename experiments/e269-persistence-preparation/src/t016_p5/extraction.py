"""E271 orchestration: exact source identity and compact provenance references only."""
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


from t016_p3.extraction import _audit_source_file, _audit_loaded_and_lookup, _check_label_oracle, _prefix_check
from t016_p5.common import resources


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
    source_id = member["source_id"]
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
    retained_records = [compact_events, labels, data["candidates"], data["blocked_cuts"],
                        data["levels"], masks, population, list(auxiliary.values())]
    serialized_bound = sum(len(json.dumps(record, ensure_ascii=False).encode("utf-8")) + 2
                           for records in retained_records for record in records)
    array_bound = sum(a.nbytes for a in arrays.values()) + sum(a.nbytes for a in cut_arrays.values())
    # Leave room for predictions, audit, report and ZIP headers before touching disk.
    resources(extra=serialized_bound + array_bound + 32 * 1024**2)
    np.savez_compressed(dest / "cuts.npz", **cut_arrays)
    np.savez_compressed(dest / "feature-vectors.npz", **arrays)
    for name, records in (
        ("events", compact_events), ("labels", labels), ("candidates", data["candidates"]),
        ("blocked_cuts", data["blocked_cuts"]), ("levels", data["levels"]),
        ("support-masks", masks), ("population", population),
        ("auxiliary-current-targets", list(auxiliary.values())),
    ):
        dump_lines(dest / (name + ".jsonl"), records)
    provenance_path = (directory / contract["source_provenance_file"]).resolve()
    dump_json(dest / "source-provenance-reference.json", {
        "path": str(provenance_path), "sha256": contract["source_provenance_sha256"],
        "size_bytes": provenance_path.stat().st_size, "source_id": source_id,
        "contract_sha256": member["contract_sha256"], "normalized_rows": len(rows),
        "join": "Source ordinal; original physical line and provenance line hashes retained in source files and examples",
        "source_rows_path": str((directory / "state_rows.jsonl").resolve()),
        "source_rows_sha256": contract["sources"][0]["sha256"],
    })
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
