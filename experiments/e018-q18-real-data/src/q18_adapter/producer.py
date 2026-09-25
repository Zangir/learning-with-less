"""T-008 v2 sampled-state projection with explicit exchange-time semantics."""
import json
from pathlib import Path

import numpy as np

from .contracts import sha256
from .features import FORWARD_GUARD_NS, SECOND, Split, build_dataset, build_split

ORIGINS = ("synthetic_integration", "exploratory_real", "eligible_empirical")
UNITS = {"time": "UTC Unix ns", "price": "USD per base asset multiplied by 1e8",
         "size": "base asset multiplied by 1e8", "count": "positive visible order count or null"}
PRICE_KEYS = ("bid_prices_units8", "ask_prices_units8")
SIZE_KEYS = ("bid_sizes_units8", "ask_sizes_units8")


class NoEligibleWindow(ValueError):
    """Valid source support is too short or incomplete for a Q18 example."""


def verify_acquisition(path, contract):
    """Bind normalized scope to preserved acquisition bytes without claiming authenticity."""
    documents = {}
    for stem in ("acquisition_chain_verification", "acquisition_proof", "supersedes_contract"):
        target = path.parent / contract[stem + "_file"]
        if sha256(target) != contract[stem + "_sha256"]:
            raise ValueError("Acquisition evidence hash mismatch")
        documents[stem] = json.loads(target.read_text())
    verification, proof = documents["acquisition_chain_verification"], documents["acquisition_proof"]
    if (verification.get("schema") != "t008-acquisition-chain-verification/1"
            or proof.get("schema") != "t008-immutable-acquisition-proof/1"
            or verification.get("origin") != "exploratory_real"):
        raise ValueError("Unsupported acquisition evidence")
    flags = ("passed", "compressed_and_decompressed_bytes_reverified", "lz4_decode_reverified",
             "member_path_date_role_transfer_range_reverified", "issued_contract_bytes_preserved")
    if any(verification.get(key) is not True for key in flags):
        raise ValueError("Acquisition verification failed")
    old = documents["supersedes_contract"]
    if old.get("version") != "2.1.0" or any(contract.get(key) != value for key, value in old.items() if key != "version"):
        raise ValueError("Acquisition revision changes preserved producer semantics")
    if (verification["contract_sha256"] != contract["supersedes_contract_sha256"]
            or verification["acquisition_proof_sha256"] != contract["acquisition_proof_sha256"]
            or verification["policy_sha256"] != contract["policy_sha256"]
            or sha256(contract["policy_file"]) != contract["policy_sha256"]):
        raise ValueError("Acquisition proof/policy chain mismatch")
    record = proof["record"]
    if (record["date"] != contract["date"].replace("-", "")
            or record["predeclared_role"] != contract["split_role"]
            or record["first_exchange_ms"] * 1_000_000 != contract["actual_first_event_ns"]
            or record["last_exchange_ms"] * 1_000_000 != contract["actual_last_event_ns"]):
        raise ValueError("Acquisition date/role/event bounds mismatch")
    if len(contract["sources"]) != 1:
        raise ValueError("Historical acquisition requires one source member per date")
    source = contract["sources"][0]
    if (source["raw_sha256"] != record["decompressed_sha256"]
            or source["source_revision"] != proof["source_revision"]
            or verification["source_revision"] != proof["source_revision"]
            or verification["raw_sha256"] != record["decompressed_sha256"]
            or verification["compressed_sha256"] != record["compressed_sha256"]):
        raise ValueError("Acquisition raw-source binding mismatch")
    for kind, name in (("compressed", "compressed_path"), ("decompressed", "jsonl_path")):
        raw = Path(record[name])
        if raw.stat().st_size != record[kind + "_bytes"] or sha256(raw) != record[kind + "_sha256"]:
            raise ValueError("Acquired payload bytes changed")
    transfer = proof["transfer"]
    if (transfer["status"] != 206 or transfer["sha256"] != record["compressed_sha256"]
            or transfer["body_bytes_consumed"] != record["member"]["size"]
            or transfer["range_start"] != record["member"]["data_offset"]):
        raise ValueError("Acquisition range transfer mismatch")


def read_producer(path, expected_sha256, expected_origin, split_rule=None):
    """Read immutable producer evidence, without issuing independent acceptance."""
    path = Path(path)
    if sha256(path) != expected_sha256:
        raise ValueError("Producer contract hash mismatch")
    contract = json.loads(path.read_text(encoding="utf-8-sig"))
    if contract.get("schema") != "t008-producer-state/2" or contract.get("version") not in ("2.0.0", "2.1.0", "2.1.1"):
        raise ValueError("Unsupported producer schema; legacy negative evidence stays negative")
    origin = contract.get("origin")
    if origin not in ORIGINS or origin != expected_origin:
        raise ValueError("Producer origin mismatch")
    if contract.get("fixture_only") is not (origin == "synthetic_integration"):
        raise ValueError("Fixture marker disagrees with origin")
    allowed_units = [UNITS]
    if contract["version"] in ("2.1.0", "2.1.1") and contract.get("asset") == "BTC":
        allowed_units.append({**UNITS, "price": "USD per BTC multiplied by 1e8", "size": "BTC multiplied by 1e8"})
    if contract.get("producer") != "T-008" or contract.get("units") not in allowed_units:
        raise ValueError("Unknown producer or units")
    scope = contract.get("scopes", {}).get("Q18", {})
    if scope.get("decision") != "affirmative":
        raise ValueError("Producer Q18 decision is negative")
    if scope.get("clock_scope") != "exchange_time":
        raise ValueError("This projection requires explicitly scoped exchange-time forecasting")
    if scope.get("state_scope") != "top5_at_snapshot_cuts":
        raise ValueError("Full top-five snapshot scope is required")
    if contract["atomic_cut"]["kind"] != "authoritative_snapshot_at_event_time" or not contract["atomic_cut"]["evidence"]:
        raise ValueError("Snapshot-cut evidence missing")
    continuity = contract["continuity"]
    if continuity["kind"] != "sampled_snapshots" or continuity["all_venue_events_observed"] is not False:
        raise ValueError("Unsupported continuity interpretation")
    if type(continuity["max_gap_ns"]) is not int or continuity["max_gap_ns"] <= 0:
        raise ValueError("Positive snapshot gap/staleness tolerance required")
    horizon = contract["horizons"]["Q18"]
    if (horizon["lookback_ns"], horizon["label_horizon_ns"], horizon["forward_guard_ns"]) != (
            75 * SECOND, 10 * SECOND, FORWARD_GUARD_NS):
        raise ValueError("Q18 horizon/guard disagreement")
    windows = [w for w in contract["windows"] if w["scope"] == "Q18"]
    allowed_use = {"development"}
    if split_rule == "predeclared_three_date_panel":
        allowed_use.add("prespecified_chronological_split")
    if not windows or any(w["state_depth"] < 5 or w["forward_guard_ns"] != FORWARD_GUARD_NS
                          or w["lookback_ns"] != 75 * SECOND or w.get("use") not in allowed_use for w in windows):
        raise ValueError("No conforming development windows")
    sources = {}
    for source in contract["sources"]:
        source_path = path.parent / source["file"]
        if sha256(source_path) != source["sha256"]:
            raise ValueError("Producer payload hash mismatch")
        if source_path.stat().st_size > 256 * 1024 ** 2:
            raise ValueError("Payload exceeds bounded consumer budget")
        sources[source["source_id"]] = source_path
    if any(not set(w["source_ids"]) <= set(sources) or not w["evidence_ids"] for w in windows):
        raise ValueError("Window source/evidence references missing")
    if contract["version"] == "2.1.1":
        verify_acquisition(path, contract)
    return contract, sources


def read_bundle(path, expected_sha256, expected_origin):
    """Hash-bind original producer contracts; the bundle issues no admission decision."""
    path = Path(path)
    if sha256(path) != expected_sha256:
        raise ValueError("Consumer source bundle hash mismatch")
    bundle = json.loads(path.read_text())
    if bundle.get("schema") != "q18-consumer-source-bundle/1" or len(bundle["contracts"]) != 3:
        raise ValueError("Expected three independently issued date contracts")
    merged, sources, roles = None, {}, {}
    for ref in bundle["contracts"]:
        original = path.parent / ref["file"]
        contract, payloads = read_producer(original, ref["sha256"], expected_origin,
                                          "predeclared_three_date_panel")
        if expected_origin == "exploratory_real" and contract["version"] != "2.1.1":
            raise ValueError("Real historical panel requires acquisition-bound producer revision")
        role = ref["role"]
        if role not in ("train", "validation", "evaluation") or role in roles.values():
            raise ValueError("Date roles must be unique and predeclared")
        if {"test": "evaluation"}.get(contract.get("split_role"), contract.get("split_role")) != role:
            raise ValueError("Consumer role disagrees with producer date role")
        if set(payloads) & set(sources):
            raise ValueError("Repeated source ID across date contracts")
        if merged is None:
            merged = {**contract, "windows": [], "sources": [], "source_contracts": []}
        for key in ("units", "horizons", "source_authenticity", "policy_sha256"):
            if contract.get(key) != merged.get(key):
                raise ValueError("Date contracts disagree on fixed semantics")
        for key in ("kind", "max_age_ns", "max_gap_ns", "all_venue_events_observed"):
            if contract["continuity"].get(key) != merged["continuity"].get(key):
                raise ValueError("Date contracts disagree on continuity policy")
        windows = [w for w in contract["windows"] if w["scope"] == "Q18"]
        for window in windows:
            if window["window_id"] in roles:
                raise ValueError("Repeated window ID")
            roles[window["window_id"]] = role
        merged["windows"].extend(windows)
        merged["sources"].extend(contract["sources"])
        merged["source_contracts"].append({**ref, "file": str(original.resolve()), "date": contract["date"]})
        sources.update(payloads)
    merged["bundle_window_roles"] = roles
    merged["purpose"] = "three-date historical sampled-state forecast pilot"
    return merged, sources


def read_rows(sources):
    rows_by_asset, diagnostics = {}, {"source_rows": 0, "same_time_repeats": 0}
    previous = {}
    for source_id, path in sources.items():
        with path.open(encoding="utf-8") as stream:
            for line in stream:
                row = json.loads(line)
                if row["source_id"] != source_id:
                    raise ValueError("Row source ID mismatch")
                if row["asset"] not in ("BTC", "ETH", "SOL"):
                    raise ValueError("Unknown asset")
                if type(row["event_ns"]) is not int or type(row["source_ordinal"]) is not int:
                    raise ValueError("Integer source time/ordinal required")
                for key in PRICE_KEYS + SIZE_KEYS:
                    if len(row[key]) < 5 or any(type(v) is not int or v <= 0 for v in row[key]):
                        raise ValueError("Positive exact top-five units8 arrays required")
                bid, ask = (row[k] for k in PRICE_KEYS)
                if (any(a <= b for a, b in zip(bid, bid[1:]))
                        or any(a >= b for a, b in zip(ask, ask[1:])) or bid[0] >= ask[0]):
                    raise ValueError("Invalid price ordering or crossed snapshot")
                key = (source_id, row["asset"])
                if key in previous:
                    prior = previous[key]
                    if row["event_ns"] < prior["event_ns"] or row["source_ordinal"] <= prior["source_ordinal"]:
                        raise ValueError("Source event/ordinal inversion; sorting forbidden")
                    if row["event_ns"] == prior["event_ns"]:
                        if any(row[k][:5] != prior[k][:5] for k in PRICE_KEYS + SIZE_KEYS):
                            raise ValueError("Conflicting snapshots at identical event time")
                        diagnostics["same_time_repeats"] += 1
                previous[key] = row
                rows_by_asset.setdefault(row["asset"], []).append(row)
                diagnostics["source_rows"] += 1
                if diagnostics["source_rows"] > 200000:
                    raise ValueError("Bounded source-row limit exceeded")
    return rows_by_asset, diagnostics


def project_window(rows, contract, window, role=None):
    """As-of sampled observation process, not inferred continuous venue state."""
    asset = window["asset"]
    if len(window["source_ids"]) != 1:
        raise ValueError("One source per certified window required")
    selected = [row for row in rows if row["source_id"] in window["source_ids"]
                and window["first_source_ordinal"] <= row["source_ordinal"] <= window["last_source_ordinal"]]
    if not selected:
        raise ValueError("Empty source window")
    event = np.array([r["event_ns"] for r in selected], dtype=np.int64)
    if event[0] < window["start_ns"] or event[-1] >= window["end_ns"]:
        raise ValueError("Payload cuts exceed declared source window")
    start = ((int(event[0]) + SECOND - 1) // SECOND) * SECOND
    # No invented tail beyond the last actual snapshot cut.
    end = min(int(event[-1]) + 1, window["end_ns"])
    times = np.arange(start, end, SECOND, dtype=np.int64)
    if role is not None and len(times) < 86:
        raise NoEligibleWindow("Fewer than 86 integer support cuts in producer window")
    index = np.searchsorted(event, times, side="right") - 1
    index = np.searchsorted(event, event[index], side="left")
    max_gap = contract["continuity"]["max_gap_ns"]
    max_age = contract["continuity"].get("max_age_ns", max_gap)
    if not 0 < max_age <= max_gap:
        raise ValueError("Snapshot age must be positive and at most the gap tolerance")
    age = times - event[index]
    segment = np.r_[0, np.cumsum(np.diff(event) > max_gap)].astype(np.int64)
    ordinal = np.array([r["source_ordinal"] for r in selected], dtype=np.int64)
    good = age <= max_age
    guard_times = times + FORWARD_GUARD_NS
    guard_index = np.searchsorted(event, guard_times, side="right") - 1
    guard_supported = ((guard_times - event[guard_index] <= max_age)
                       & (segment[guard_index] == segment[index]) & (guard_times < window["end_ns"]))
    grid = {"times_ns": times, "clock_scope": np.array("exchange_time"),
            "source_event_ns": event[index], "source_ordinal": ordinal[index],
            "sample_age_ns": age, "segment_id": segment[index],
            "guard_supported": guard_supported,
            "top5_complete": good.copy(), "atomic_complete": good.copy(),
            "past_only_selection": good.copy()}
    for out, key in zip(("bid_px", "ask_px", "bid_qty", "ask_qty"), PRICE_KEYS + SIZE_KEYS):
        grid[out] = np.array([[r[key][k] / 100_000_000 for k in range(5)] for r in selected])[index]
    split_ns = start + ((end - start) // SECOND * 2 // 3) * SECOND
    if role is None:
        splits = [Split("train", start, split_ns), Split("evaluation", split_ns, end)]
        dataset = build_dataset(grid, splits)
    else:
        splits = [Split(role, start, end)]
        dataset = {role: build_split(grid, splits[0])}
        if not len(dataset[role]["indices"]):
            raise NoEligibleWindow("No eligible rows in declared producer window")
    # Whole examples remain in the producer window, with the independent padding.
    for part in dataset.values():
        g = part["times_ns"]
        if np.any(g - 75 * SECOND < window["start_ns"]) or np.any(g + FORWARD_GUARD_NS >= window["end_ns"]):
            raise ValueError("Example escapes producer-certified support")
    audit = {"asset": asset, "source_rows": len(selected), "grid_rows": len(times),
             "source_first_ns": int(event[0]), "source_last_ns": int(event[-1]),
             "source_max_gap_ns": int(np.diff(event).max()) if len(event) > 1 else 0,
             "split": [vars(s) for s in splits], "window_id": window["window_id"],
             "grid_stale_rows": int((~good).sum()), "segments": int(segment[-1] + 1),
             "unsupported_fractional_guard_rows": int((~guard_supported).sum()),
             "selected_snapshot_age_max_ns": int(age.max()),
             "selected_snapshot_age_p50_ns": float(np.median(age)),
             "max_snapshot_age_ns": max_age, "producer_max_age_ns": max_age,
             "max_gap_ns": max_gap, "equal_time_policy": "earliest source ordinal for identical top-five repeats; conflicting repeats rejected",
             "common_rows_by_role": {name: len(part["indices"]) for name, part in dataset.items()},
             "effective_target_source_horizon_ns": {name: {
                 "min": int((grid["source_event_ns"][part["indices"] + 10] - grid["source_event_ns"][part["indices"]]).min()),
                 "median": float(np.median(grid["source_event_ns"][part["indices"] + 10] - grid["source_event_ns"][part["indices"]])),
                 "max": int((grid["source_event_ns"][part["indices"] + 10] - grid["source_event_ns"][part["indices"]]).max())}
                 for name, part in dataset.items()},
             "clock_scope": "exchange_time", "measured_receipt_claim": False,
             "observation_model": "Latest observed complete snapshot at/before integer-second exchange cut; persist only within declared age tolerance",
             "venue_state_between_cuts_claimed": False,
             "sample_rows": [{k: selected[j][k] for k in ("source_id", "source_ordinal", "asset", "event_ns", "release_ns", "admission_evidence_ns")}
                             for j in sorted({0, len(selected) // 2, len(selected) - 1})]}
    return dataset, grid, audit


def project_asset(rows, contract, asset):
    windows = [w for w in contract["windows"] if w["scope"] == "Q18" and w["asset"] == asset]
    if len(windows) != 1:
        raise ValueError("Fractional development split requires one window per asset")
    return project_window(rows, contract, windows[0])


def concatenate_parts(parts):
    result = {key: np.concatenate([p[key] for p in parts]) for key in ("indices", "times_ns", "returns_bps")}
    if np.any(np.diff(result["times_ns"]) <= 0):
        raise ValueError("Panel decisions must remain chronological")
    result["views"] = {view: np.concatenate([p["views"][view] for p in parts]) for view in parts[0]["views"]}
    return result


def project_panel(rows, contract, asset, window_roles):
    windows = [w for w in contract["windows"] if w["scope"] == "Q18" and w["asset"] == asset]
    if {w["window_id"] for w in windows} != set(window_roles):
        raise ValueError("Frozen date cohort and producer windows disagree")
    parts, audits, grids = {}, {}, {}
    for role in ("train", "validation", "evaluation"):
        chosen = [w for w in windows if window_roles[w["window_id"]] == role]
        if not chosen or any(a["end_ns"] > b["start_ns"] for a, b in zip(chosen, chosen[1:])):
            raise ValueError("Nonoverlapping chronological windows required for every date role")
        role_parts, audits[role] = [], []
        for i, window in enumerate(chosen):
            dataset, grid, audit = project_window(rows, contract, window, role)
            role_parts.append(dataset[role])
            grids[f"{role}_{i}"] = grid
            audits[role].append(audit)
        parts[role] = concatenate_parts(role_parts)
        if len(parts[role]["indices"]) < 20:
            raise ValueError("Insufficient common rows in aggregated date role")
        if len(np.unique(parts[role]["times_ns"].astype("datetime64[ns]").astype("datetime64[D]"))) != 1:
            raise ValueError("Each role must belong to exactly one date")
    if not (parts["train"]["times_ns"][-1] < parts["validation"]["times_ns"][0]
            and parts["validation"]["times_ns"][-1] < parts["evaluation"]["times_ns"][0]):
        raise ValueError("Date panel chronology violated")
    evaluation = concatenate_parts([parts["validation"], parts["evaluation"]])
    evaluation["roles"] = np.concatenate([np.full(len(parts[r]["indices"]), r) for r in ("validation", "evaluation")])
    return {"train": parts["train"], "evaluation": evaluation}, grids, audits
