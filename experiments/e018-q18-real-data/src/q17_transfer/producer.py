"""T-008 v2 JSONL projection into origin-labelled Q17 development examples."""
import json
from pathlib import Path
import numpy as np
from .features import build_arrays, NS, DAY
from .gate import sha256
from .protocol import PROTOCOL, digest_json

ORIGINS = {"synthetic_integration", "exploratory_real", "eligible_empirical"}
TRANSFER = {
    "schema": "q17-producer-mapping/2", "source": "t008-producer-state/2", "source_version": ["2.0.0", "2.1.0", "2.1.1"],
    "split": "explicit predeclared date roles; synthetic fallback chronological thirds of one date",
    "model_family": "original prior/logistic/HGB/MLP17,29,41",
    "feature_lookback_ns": 20*NS, "forecast_forward_ns": 10*NS,
    "utility_primary_forward_ns": 10_100_000_000, "utility_fullgrid_forward_ns": 10_500_000_000,
    "schedule": "12 consecutive eligible rows on one global 11-second block grid; restart only after a gap",
    "sampled_observation_model": "last observed snapshot at or before each cut; not unchanged venue state",
    "exchange_clock": "hypothetical access to authoritative snapshot at its source event time; not receipt time",
    "actual_receive_clock": "measured release and admission timestamps only",
    "original_joint_primary": "not evaluated by single-asset, single-test-day pilot",
}


def eligible(window, decision_ns, mode):
    forward = {"forecast": 10*NS, "primary_utility": 10_100_000_000,
               "full_utility": 10_500_000_000, "scheduling": 131_500_000_000}[mode]
    return window["start_ns"] <= decision_ns-20*NS and decision_ns+forward < window["end_ns"]


def load_contract(path, expected_origin):
    """Producer affirmation allows scoped diagnostics, never issues review acceptance."""
    path = Path(path)
    contract = json.loads(path.read_text(encoding="utf-8"))
    if contract.get("schema") != "t008-producer-state/2" or contract.get("version") not in TRANSFER["source_version"] or contract.get("producer") != "T-008":
        raise ValueError("Unsupported producer schema; legacy negative contracts remain unadmitted")
    origin = contract.get("origin")
    if expected_origin not in ORIGINS or origin != expected_origin:
        raise ValueError("Origin mismatch: no synthetic-to-market promotion")
    if contract.get("fixture_only") is not (origin == "synthetic_integration"):
        raise ValueError("Origin and fixture marker disagree")
    purpose = contract.get("purpose")
    if (purpose == "fictional_integration_only") != (origin == "synthetic_integration"):
        raise ValueError("Purpose and origin disagree")
    if contract.get("review", {}).get("status") != "not_issued_by_producer":
        raise ValueError("Producer cannot issue independent review")
    scope = contract["scopes"]["Q17"]
    if scope.get("decision") != "affirmative":
        raise ValueError("Q17 producer scope is negative: "+str(scope.get("reason")))
    if scope.get("clock_scope") not in {"exchange_time", "observed_receive_time"}:
        raise ValueError("Unsupported clock scope")
    if scope.get("state_scope") not in {"bbo_at_snapshot_cuts", "bbo_complete_event_stream", "complete_bbo"}:
        raise ValueError("No declared authoritative BBO scope")
    if contract["atomic_cut"].get("kind") not in {"authoritative_snapshot_at_event_time", "documented_atomic_event_envelope", "state_invariant_across_admissible_interleavings"} or not contract["atomic_cut"].get("evidence"):
        raise ValueError("Atomic cut and evidence reference required")
    continuity = contract["continuity"]
    if continuity.get("kind") not in {"sampled_snapshots", "complete_event_stream"} or scope["continuity_scope"] != continuity["kind"]:
        raise ValueError("Unsupported/inconsistent continuity scope")
    if type(continuity.get("max_gap_ns")) is not int or continuity["max_gap_ns"] <= 0:
        raise ValueError("Positive declared gap tolerance required")
    if contract["version"] in {"2.1.0", "2.1.1"} and (type(continuity.get("max_age_ns")) is not int or continuity["max_age_ns"] <= 0):
        raise ValueError("Separate positive freshness limit required")
    units = contract["units"].copy()
    if contract.get("asset") == "BTC" and units.get("price") == "USD per BTC multiplied by 1e8" and units.get("size") == "BTC multiplied by 1e8":
        units.update(price="USD per base asset multiplied by 1e8", size="base asset multiplied by 1e8")
    if units != {"count": "positive visible order count or null", "price": "USD per base asset multiplied by 1e8", "size": "base asset multiplied by 1e8", "time": "UTC Unix ns"}:
        raise ValueError("Unsupported exact unit declaration")
    h = contract["horizons"]
    if h["Q17_forecast"]["forward_guard_ns"] != 10*NS or h["Q17_primary_utility"]["forward_guard_ns"] != 10_100_000_000 or h["Q17_full_latency_grid"]["forward_guard_ns"] != 10_500_000_000:
        raise ValueError("Forecast and utility horizon definitions do not match")
    windows = [w for w in contract["windows"] if w["scope"] == "Q17"]
    if not windows or len({w["window_id"] for w in windows}) != len(windows):
        raise ValueError("Distinct Q17 windows required")
    if contract["version"] == "2.1.1":
        verify_acquisition_chain(path, contract)
    rows = []
    seen = set()
    total_bytes = 0
    for source in contract["sources"]:
        payload = path.parent/source["file"]
        total_bytes += payload.stat().st_size
        if total_bytes > 512*1024**2 or sha256(payload) != source["sha256"]:
            raise ValueError("Source checksum mismatch or payload exceeds bounded cap")
        if payload.resolve() in seen:
            raise ValueError("One source ID per payload required")
        seen.add(payload.resolve())
        with payload.open(encoding="utf-8") as stream:
            for line in stream:
                row = json.loads(line)
                if row["source_id"] != source["source_id"]:
                    raise ValueError("Unbound source ID")
                rows.append(row)
                if len(rows) > 1_000_000:
                    raise ValueError("Bounded pilot supports at most one million snapshots")
    validate_rows(rows, scope["clock_scope"])
    if contract["version"] in {"2.1.0", "2.1.1"}:
        seen_events = set()
        for row in rows:
            key = row["source_id"], row["asset"], row["event_ns"]
            if key in seen_events:
                raise ValueError("Producer 2.1 must deduplicate identical ties and reject conflicting ties")
            seen_events.add(key)
    return dict(contract=contract, contract_path=path, rows=rows, windows=windows,
                origin=origin, producer_sha256=sha256(path), mapping_sha256=digest_json(TRANSFER))


def verify_acquisition_chain(path, contract):
    """Bind normalized state to the acquisition-time archive member and raw bytes."""
    bound = {}
    for stem in ("acquisition_chain_verification", "acquisition_proof", "supersedes_contract"):
        file = Path(path).parent/contract[stem+"_file"]
        if sha256(file) != contract[stem+"_sha256"]:
            raise ValueError("Acquisition binding checksum mismatch: "+stem)
        bound[stem] = json.loads(file.read_text(encoding="utf-8"))
    verification, proof, previous = (bound[k] for k in ("acquisition_chain_verification", "acquisition_proof", "supersedes_contract"))
    stripped = {k: v for k, v in contract.items() if not any(k.startswith(stem+"_") for stem in bound)}
    stripped["version"] = previous["version"]
    if stripped != previous or previous["version"] != "2.1.0":
        raise ValueError("Acquisition patch changes previously frozen data scope")
    if (verification.get("schema") != "t008-acquisition-chain-verification/1"
            or verification.get("origin") != contract["origin"]
            or any(verification.get(k) is not True for k in ("passed", "compressed_and_decompressed_bytes_reverified",
                "lz4_decode_reverified", "member_path_date_role_transfer_range_reverified", "issued_contract_bytes_preserved"))
            or proof.get("schema") != "t008-immutable-acquisition-proof/1"
            or proof.get("verified_compressed_to_decompressed_bytes") is not True):
        raise ValueError("Acquisition chain verification is incomplete")
    record, transfer = proof["record"], proof["transfer"]
    sources = contract["sources"]
    if len(sources) != 1:
        raise ValueError("One acquired member per historical contract required")
    source = sources[0]
    if (verification["contract_sha256"] != contract["supersedes_contract_sha256"]
            or verification["acquisition_proof_sha256"] != contract["acquisition_proof_sha256"]
            or verification["policy_sha256"] != contract["policy_sha256"]
            or verification["source_revision"] != proof["source_revision"] or source["source_revision"] != proof["source_revision"]
            or source["raw_sha256"] != record["decompressed_sha256"] or verification["raw_sha256"] != record["decompressed_sha256"]
            or verification["compressed_sha256"] != record["compressed_sha256"]):
        raise ValueError("Acquisition hashes or source revision disagree")
    if (record["date"] != contract["date"].replace("-", "") or record["predeclared_role"] != contract["split_role"]
            or proof["source_repository"] != "asiletto81/hl_btc"
            or record["member"]["path"] != "data/"+record["date"]+"/0/l2Book/BTC.lz4"
            or proof["source_url"] != "https://huggingface.co/datasets/"+proof["source_repository"]+"/resolve/"+proof["source_revision"]+"/data_202512.tar"):
        raise ValueError("Acquisition member date, role or pinned URL mismatch")
    for filename, hash_key, size_key in ((record["jsonl_path"], "decompressed_sha256", "decompressed_bytes"),
                                       (record["compressed_path"], "compressed_sha256", "compressed_bytes")):
        file = Path(filename)
        if file.stat().st_size != record[size_key] or sha256(file) != record[hash_key]:
            raise ValueError("Acquired compressed or raw bytes changed")
    if Path(source["raw_file"]).resolve() != Path(record["jsonl_path"]).resolve():
        raise ValueError("Normalized source raw path differs from acquisition")
    if (transfer["status"] != 206 or transfer["sha256"] != record["compressed_sha256"]
            or transfer["range_start"] != record["member"]["data_offset"]
            or transfer["body_bytes_consumed"] != record["compressed_bytes"]
            or transfer["content_range"] != f"bytes {record['member']['data_offset']}-{record['member']['data_offset']+record['member']['size']-1}/933171200"
            or record["member"]["size"] != record["compressed_bytes"]):
        raise ValueError("Acquisition range transfer does not bind archive member")


def validate_rows(rows, clock_scope):
    previous = {}
    for row in rows:
        event, ordinal = row["event_ns"], row["source_ordinal"]
        if type(event) is not int or type(ordinal) is not int or ordinal < 0:
            raise ValueError("Integer source event time and ordinal required")
        key = row["source_id"], row["asset"]
        if key in previous and (event < previous[key][0] or ordinal <= previous[key][1]):
            raise ValueError("Source order/event inversion: sorting is forbidden")
        previous[key] = event, ordinal
        for side in ("bid", "ask"):
            prices, sizes = row[side+"_prices_units8"], row[side+"_sizes_units8"]
            if not prices or len(prices) != len(sizes) or any(type(v) is not int or v <= 0 for v in prices+sizes):
                raise ValueError("Positive integer units8 BBO price/size arrays required")
            if any((a <= b if side == "bid" else a >= b) for a, b in zip(prices, prices[1:])):
                raise ValueError("Unordered levels")
        if row["bid_prices_units8"][0] >= row["ask_prices_units8"][0]:
            raise ValueError("Locked/crossed BBO")
        for name in ("release_ns", "admission_evidence_ns"):
            if row[name] is not None and type(row[name]) is not int:
                raise ValueError("Receipt/evidence clocks must be integer or null")
        if clock_scope == "observed_receive_time":
            if row["release_ns"] is None or row["admission_evidence_ns"] is None:
                raise ValueError("Measured receive/evidence clocks unavailable")
            if max(event, row["admission_evidence_ns"]) > row["release_ns"]:
                raise ValueError("Data not admitted by measured release")


def prepare_asset(loaded, asset, split_dates=None):
    """Build matched source-style arrays, excluding unsupported intervals without filling gaps."""
    contract = loaded["contract"]
    windows = [w for w in loaded["windows"] if w["asset"] == asset]
    if not windows:
        raise ValueError("No Q17 window for asset")
    if any(w.get("use") not in {"development", "prespecified_chronological_split"} or w["state_depth"] < 1 for w in windows):
        raise ValueError("This bounded runner admits development BBO only")
    for w in windows:
        if w["end_ns"] <= w["start_ns"] or not w["source_ids"] or not w["evidence_ids"]:
            raise ValueError("Invalid supported window")
    ordered = sorted(windows, key=lambda w: w["start_ns"])
    if any(a["end_ns"] > b["start_ns"] for a, b in zip(ordered, ordered[1:])):
        raise ValueError("Overlapping certificates would duplicate examples")
    start, end = ordered[0]["start_ns"], ordered[-1]["end_ns"]
    if split_dates is None:
        if loaded["origin"] != "synthetic_integration" or start//DAY != (end-1)//DAY:
            raise ValueError("Real pilots require predeclared chronological date roles")
        bounds = [start, (start+(end-start)//3)//NS*NS, (start+2*(end-start)//3)//NS*NS, end]
        blocks = list(zip(("train", "validation", "test"), bounds, bounds[1:]))
    else:
        roles = ("train", "validation", "test")
        if set(split_dates) != set(roles) or not (split_dates["train"] < split_dates["validation"] < split_dates["test"]):
            raise ValueError("Distinct chronological train/validation/test dates required")
        blocks = []
        for split in roles:
            day = int(np.datetime64(split_dates[split], "ns").astype(np.int64))
            matching = [w for w in ordered if w["start_ns"]//DAY == day//DAY and (w["end_ns"]-1)//DAY == day//DAY]
            if not matching:
                raise ValueError("No producer windows on predeclared "+split+" date")
            blocks.append((split, matching[0]["start_ns"], matching[-1]["end_ns"]))
    clock_scope = contract["scopes"]["Q17"]["clock_scope"]
    max_gap = contract["continuity"]["max_gap_ns"]
    arrays, diagnostics = {}, {"origin": loaded["origin"], "asset": asset, "blocks": blocks,
        "clock_scope": clock_scope, "observation_model": TRANSFER["sampled_observation_model"], "splits": {}}
    for split, left, right in blocks:
        chunks, excluded, cursor = [], [], 0
        stride = PROTOCOL["train_stride_seconds" if split == "train" else "evaluation_stride_seconds"]*NS
        anchor = (left//NS+21)*NS
        for window in ordered:
            lo, hi = max(left, window["start_ns"]), min(right, window["end_ns"])
            if hi <= lo:
                continue
            rows = [r for r in loaded["rows"] if r["asset"] == asset and r["source_id"] in window["source_ids"]
                    and window["first_source_ordinal"] <= r["source_ordinal"] <= window["last_source_ordinal"]
                    and lo <= r["event_ns"] < hi]
            if len({r["source_id"] for r in rows}) > 1:
                raise ValueError("One ordered source per certified window required")
            cuts = [0]+[i for i in range(1, len(rows)) if rows[i]["event_ns"]-rows[i-1]["event_ns"] > max_gap]+[len(rows)]
            for a, b in zip(cuts, cuts[1:]):
                part = rows[a:b]
                if len(part) < 2:
                    excluded.append(dict(window=window["window_id"], reason="short_segment", rows=len(part))); continue
                event = np.array([r["event_ns"] for r in part], dtype=np.int64)
                # This explicitly declared information set is not a fabricated receipt feed.
                model_clock = event.copy() if clock_scope == "exchange_time" else np.array([r["release_ns"] for r in part], dtype=np.int64)
                known = event.copy() if clock_scope == "exchange_time" else np.array([r["admission_evidence_ns"] for r in part], dtype=np.int64)
                quotes = dict(event_ns=event, available_ns=model_clock, known_ns=known,
                    **{field: np.array([r[side+"_"+column][0]/1e8 for r in part]) for field, side, column in (
                        ("bid", "bid", "prices_units8"), ("ask", "ask", "prices_units8"),
                        ("bid_size", "bid", "sizes_units8"), ("ask_size", "ask", "sizes_units8"))})
                try:
                    built = build_arrays(quotes, split, lo, hi, grid_anchor_ns=anchor)
                except ValueError as error:
                    if "Insufficient" not in str(error):
                        raise
                    excluded.append(dict(window=window["window_id"], reason="insufficient_feature_target_support", rows=len(part))); continue
                max_age = contract["continuity"].get("max_age_ns", max_gap)
                fresh = built["max_input_age_ns"] <= max_age
                if not fresh.all():
                    excluded.append(dict(window=window["window_id"], reason="stale_feature_or_outcome", rows=int((~fresh).sum())))
                    built = {k: v[fresh] for k, v in built.items()}
                if not len(built["times"]):
                    continue
                # Compare exact doubled midpoints: binary floats must not invent direction.
                midpoint_sums = [r["bid_prices_units8"][0]+r["ask_prices_units8"][0] for r in part]
                built["y"] = np.array([(midpoint_sums[b] > midpoint_sums[a])-(midpoint_sums[b] < midpoint_sums[a])+1
                    for a, b in built["label_indices"]], dtype=np.int8)
                if not all(eligible(window, int(t), "full_utility") for t in built["times"]):
                    raise ValueError("Full 10.5-second outcome support missing")
                ordinals = np.array([r["source_ordinal"] for r in part], dtype=np.int64)
                built["feature_source_ordinals"] = ordinals[built["feature_indices"]]
                built["label_source_ordinals"] = ordinals[built["label_indices"]]
                built["entry_source_ordinals"] = ordinals[built["entry_indices"]]
                built["exit_source_ordinals"] = ordinals[built["exit_indices"]]
                built["segment_id"] = np.full(len(built["times"]), cursor, dtype=np.int64)
                built["source_id"] = np.full(len(built["times"]), part[0]["source_id"])
                built["window_id"] = np.full(len(built["times"]), window["window_id"])
                built["quote_age_ns"] = built["times"]-event[built["feature_indices"][:, 0]]
                chunks.append(built); cursor += 1
        if not chunks:
            raise ValueError(f"No eligible {asset}/{split} feature/target rows")
        joined = {k: np.concatenate([chunk[k] for chunk in chunks]) for k in chunks[0]}
        if not (np.diff(joined["times"]) > 0).all():
            raise ValueError("Duplicate or inverted decisions")
        if split == "train" and len(joined["times"]) > PROTOCOL["training_cap_per_day"]:
            sample = np.linspace(0, len(joined["times"])-1, PROTOCOL["training_cap_per_day"], dtype=int)
            joined = {k: v[sample] for k, v in joined.items()}
        if split != "train":
            groups = []
            cuts = np.r_[0, np.flatnonzero((np.diff(joined["times"]) != stride) | (np.diff(joined["segment_id"]) != 0))+1, len(joined["times"])]
            for a, b in zip(cuts, cuts[1:]):
                groups.extend(np.arange(a, a+(b-a)//12*12).reshape(-1, 12))
            joined["schedule_rows"] = np.array(groups, dtype=np.int64).reshape(-1, 12)
            if not len(groups):
                raise ValueError(f"No complete scheduling window in {asset}/{split}; forecast-only diagnostics remain possible")
        arrays[split] = joined
        diagnostics["splits"][split] = dict(opportunities=len(joined["times"]), label_counts={str(k): int((joined["y"] == k).sum()) for k in (0, 1, 2)},
            scheduling_windows=len(joined.get("schedule_rows", [])), segments=cursor, exclusions=excluded,
            max_quote_age_ns=int(joined["quote_age_ns"].max()), max_input_age_ns=int(joined["max_input_age_ns"].max()))
    freezes = {}
    for a, b in (("train", "validation"), ("validation", "test")):
        ready, first = int(arrays[a]["outcome_available_ns"].max()), int(arrays[b]["times"].min())
        if ready > first:
            raise ValueError("Outcome evidence not mature before next block")
        freezes[a] = dict(evidence_ready_ns=ready, next_first_decision_ns=first)
    diagnostics["freeze_checks"] = freezes
    return arrays, diagnostics
