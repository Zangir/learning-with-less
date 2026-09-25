"""Independently bind sampled panel states to frozen protocol and gzip responses.

Integrity reaches the acquired third-party response, not authenticated venue
state, strategy receipt, complete event continuity, or empirical acceptance.
"""
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
import gzip
import hashlib
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .gate import sha256
from .protocol import digest_json

NS = 1_000_000_000
POLICY_SHA256 = "84639e7bee796452cae075f4f349e61e8ff37ac4fd9d32685ba0f111baf3120d"
STARTUP_POLICY_SHA256 = "e5de9c455d3918b11693af0f771de4776f49cd9b2a1f1918000c0179259c8d19"
MAX_NORMALIZED_BYTES = 512 * 1024**2
MAX_ROWS = 1_000_000
MAX_DECODED_BYTES = 4 * 1024**3
MAX_LINE_BYTES = 64 * 1024
MAPPING = {
    "schema": "q17-paired-panel-mapping/1", "producer_versions": ["2.2.0", "2.2.1"],
    "protocol_sha256": POLICY_SHA256, "origin": "exploratory_real",
    "clock": "hypothetical source-event observation; no strategy receipt/admission",
    "source": "Tardis third-party l2Book archive, not independently authenticated",
    "selection": "declared event period, source order, full-payload tie deduplication",
    "continuity": "separate at disconnect markers or event gaps exceeding 2 seconds",
    "max_age_ns": 1_500_000_000, "max_gap_ns": 2_000_000_000,
}
STARTUP_MAPPING = {**MAPPING, "schema": "q17-paired-panel-startup-mapping/1", "producer_versions": ["2.3.0"],
    "protocol_sha256": STARTUP_POLICY_SHA256, "acquisition_protocol_sha256": POLICY_SHA256,
    "startup_exclusion_ns": 30 * NS, "adaptation_class": "SOURCE-QUALITY-INFORMED POST-ACQUISITION PRE-FIT",
    "selection": "receipt prefix excluded first; strict remaining event order/ties before event-period filtering",
    "fit_authorization": "requires exact-input RV011 support and separately frozen consumer amendment"}


def _json(path, expected=None):
    path = Path(path)
    if path.stat().st_size > 16 * 1024**2:
        raise ValueError("JSON evidence exceeds bounded metadata cap")
    if expected is not None and sha256(path) != expected:
        raise ValueError("Evidence checksum mismatch: " + path.name)
    return json.loads(path.read_text(encoding="utf-8"))


def _utc_ns(text):
    if not isinstance(text, str) or not text.endswith("Z"):
        raise ValueError("Provider receipt must be explicit UTC ISO time")
    whole, dot, fraction = text[:-1].partition(".")
    if dot and (not fraction.isdigit() or len(fraction) > 9):
        raise ValueError("Provider receipt exceeds exact nanosecond precision")
    seconds = int(datetime.strptime(whole, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc).timestamp())
    return seconds * NS + int(fraction.ljust(9, "0") or 0)


def _units8(value):
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ValueError("Exact decimal source price/size required")
    scaled = Decimal(value) * 100_000_000
    if not scaled.is_finite() or scaled <= 0 or scaled != scaled.to_integral_value():
        raise ValueError("Positive source price/size on units8 lattice required")
    return int(scaled)


def _raw_row(data, date, ordinal):
    if data["coin"] not in {"BTC", "ETH"} or type(data["time"]) is not int or len(data["levels"]) != 2:
        raise ValueError("Unexpected asset, event clock or book sides")
    row = {"source_id": f"tardis-hyperliquid-{date}-{data['coin'].lower()}",
           "source_ordinal": ordinal, "asset": data["coin"], "event_ns": data["time"] * 1_000_000,
           "release_ns": None, "admission_evidence_ns": None}
    for side, levels in zip(("bid", "ask"), data["levels"]):
        if len(levels) < 5:
            raise ValueError("Source depth must support every normalized top-five level")
        prices = [_units8(level["px"]) for level in levels]
        sizes = [_units8(level["sz"]) for level in levels]
        counts = [level["n"] for level in levels]
        if any(type(n) is not int or n <= 0 for n in counts):
            raise ValueError("Positive native integer counts required")
        if any((a <= b if side == "bid" else a >= b) for a, b in zip(prices, prices[1:])):
            raise ValueError("Full-depth source prices are not strictly ordered")
        for name, values in (("prices_units8", prices), ("sizes_units8", sizes), ("counts", counts)):
            row[side + "_" + name] = values[:5]
    if row["bid_prices_units8"][0] >= row["ask_prices_units8"][0]:
        raise ValueError("Locked/crossed source book")
    return row


def _check_contract(contract, base, expected_origin):
    startup = contract.get("version") == "2.3.0"
    if (contract.get("schema") != "t008-producer-state/2" or contract.get("version") not in MAPPING["producer_versions"] + ["2.3.0"]
            or contract.get("producer") != "T-008"):
        raise ValueError("Unsupported paired producer contract")
    if expected_origin != "exploratory_real" or contract.get("origin") != expected_origin or contract.get("fixture_only") is not False:
        raise ValueError("Origin mismatch: panel cannot promote fixtures or confer empirical admission")
    if contract.get("purpose") != "historical_paired_hyperliquid_sampled_state_adaptation":
        raise ValueError("Unexpected panel purpose")
    if contract.get("review", {}).get("status") != "not_issued_by_producer":
        raise ValueError("Producer cannot issue independent review")
    scope = contract["scopes"]["Q17"]
    if any(scope.get(key) != value for key, value in {
            "decision": "affirmative", "clock_scope": "exchange_time",
            "state_scope": "bbo_at_snapshot_cuts", "continuity_scope": "sampled_snapshots"}.items()):
        raise ValueError("Q17 requires affirmative, limited sampled-state exchange-time scope")
    if (contract.get("clock_scope") != "exchange_time"
            or contract.get("source_authenticity") != "third_party_not_independently_authenticated"
            or contract["atomic_cut"].get("kind") != "authoritative_snapshot_at_event_time"
            or contract["atomic_cut"].get("authority_scope") != "claimed_by_third_party_archive_only"
            or not contract["atomic_cut"].get("evidence")):
        raise ValueError("Source authority or clock scope was promoted")
    continuity = contract["continuity"]
    if (continuity.get("kind") != "sampled_snapshots" or continuity.get("all_venue_events_observed") is not False
            or continuity.get("max_age_ns") != MAPPING["max_age_ns"]
            or continuity.get("max_gap_ns") != MAPPING["max_gap_ns"]):
        raise ValueError("Frozen freshness/gap/continuity policy mismatch")
    units = {"time": "UTC Unix ns", "price": "USD per base asset multiplied by1e8",
             "size": "base asset multiplied by1e8", "count": "positive visible native order count"}
    if contract.get("units") != units:
        raise ValueError("Unexpected exact unit declaration")
    for name, forward in (("Q17_forecast", 10 * NS), ("Q17_primary_utility", 10_100_000_000),
                          ("Q17_full_latency_grid", 10_500_000_000), ("Q17_scheduling", 131_500_000_000)):
        horizon = contract["horizons"][name]
        if horizon.get("lookback_ns") != 20 * NS or horizon.get("forward_guard_ns") != forward:
            raise ValueError("Q17 horizon mismatch")
    if contract["horizons"]["Q17_scheduling"].get("opportunities") != 12 or contract["horizons"]["Q17_scheduling"].get("grid_ns") != 11 * NS:
        raise ValueError("Q17 scheduling definition mismatch")
    policy_hash = STARTUP_POLICY_SHA256 if startup else POLICY_SHA256
    if contract.get("policy_sha256") != policy_hash or not contract.get("policy_file"):
        raise ValueError("Contract is not bound to its exact frozen panel protocol")
    policy = _json(base / contract["policy_file"], policy_hash)
    date, asset = contract["date"], contract["asset"]
    if asset not in {"BTC", "ETH"} or date not in policy["roles_Q17"]:
        raise ValueError("Date/asset is outside frozen panel")
    if any(contract["split_roles"].get(scope) != policy["roles_" + scope][date] for scope in ("Q17", "Q18")):
        raise ValueError("Date role differs from frozen panel")
    start, end = contract["selected_event_start_ns"], contract["selected_event_end_ns"]
    midnight = _utc_ns(date + "T00:00:00Z")
    if (type(start) is not int or type(end) is not int or start != midnight + (30 * NS if startup else 0)
            or end - midnight not in (3600 * NS, 86400 * NS)):
        raise ValueError("Only frozen hour00 or full-day event periods are supported")
    if startup:
        ancestor = _json(base / contract["source_acquisition_policy_file"], POLICY_SHA256)
        if (contract.get("source_acquisition_policy_sha256") != POLICY_SHA256
                or policy.get("supersedes_policy_sha256") != POLICY_SHA256
                or policy.get("startup_exclusion_ns") != 30 * NS or contract.get("startup_exclusion_ns") != 30 * NS
                or contract.get("adaptation_class") != STARTUP_MAPPING["adaptation_class"]
                or any(policy["roles_" + scope] != ancestor["roles_" + scope] for scope in ("Q17", "Q18"))
                or any(contract.get(key) != policy.get(key) for key in ("selection_qualification", "restart_claim", "fit_authorization_gate"))):
            raise ValueError("Startup adaptation ancestry, fixed cutoff or qualification mismatch")
    return policy


def _verify_additive_binding(contract, base):
    previous = _json(base / contract["supersedes_contract_file"], contract["supersedes_contract_sha256"])
    stripped = deepcopy(contract)
    for key in ("supersedes_contract_file", "supersedes_contract_sha256", "source_provenance_file", "source_provenance_sha256", "evidence_files"):
        stripped.pop(key)
    stripped["version"] = "2.2.0"
    for source in stripped["sources"]:
        source.pop("source_provenance_file")
        source.pop("source_provenance_sha256")
    if previous.get("version") != "2.2.0" or stripped != previous:
        raise ValueError("Provenance binding patch changes previously frozen contract scope")
    return _verify_bound_evidence(contract, base)


def _verify_bound_evidence(contract, base):
    evidence_names = {"eligibility_diagnostics.json", "clock_diagnostics.json", "grid_audit.csv",
                      "q17_required_cut_audit.csv", "q18_endpoint_audit.csv", "duplicate_ledger.json"}
    if set(contract["evidence_files"]) != evidence_names:
        raise ValueError("Required bound eligibility/clock audit files are missing")
    for name, digest in contract["evidence_files"].items():
        if (base / name).stat().st_size > MAX_NORMALIZED_BYTES or sha256(base / name) != digest:
            raise ValueError("Bound eligibility/clock audit checksum mismatch")
    source = contract["sources"][0]
    provenance = base / contract["source_provenance_file"]
    if (source["source_provenance_sha256"] != contract["source_provenance_sha256"]
            or (base / source["source_provenance_file"]).resolve() != provenance.resolve()
            or provenance.stat().st_size > MAX_NORMALIZED_BYTES or sha256(provenance) != contract["source_provenance_sha256"]):
        raise ValueError("Bound source receipt provenance checksum mismatch")
    return provenance


def _record_check(item, contract, policy_path):
    record = item["record"]
    parsed = urlsplit(record["url"])
    query = parse_qs(parsed.query, strict_parsing=True)
    if (parsed.scheme != "https" or parsed.netloc != "api.tardis.dev" or parsed.path != "/v1/data-feeds/hyperliquid"
            or parsed.fragment or query.get("from") != [contract["date"] + "T00:00:00.000Z"]
            or query.get("offset") != [str(record["offset"])] or query.get("sliceSize") != ["10"]
            or query.get("compression") != ["gzip"]
            or json.loads(query.get("filters", ["null"])[0]) != [{"channel": "l2Book", "symbols": ["BTC", "ETH"]}]):
        raise ValueError("Acquisition endpoint/date/filter/offset binding failed")
    if (record.get("date") != contract["date"] or record.get("role") != contract["split_roles"]["Q17"]
            or record.get("protocol_sha256") != POLICY_SHA256 or record.get("status") != 200
            or record.get("completed") is not True or item.get("gzip_crc_and_decoded_hash_reverified") is not True):
        raise ValueError("Acquisition role/protocol/completion binding failed")
    if sha256(record["protocol_path"]) != POLICY_SHA256 or Path(record["protocol_path"]).resolve() != policy_path.resolve():
        raise ValueError("Acquisition protocol path/hash mismatch")
    for stem in ("preflight", "authorization"):
        evidence = _json(record[stem + "_path"], record[stem + "_sha256"])
        if evidence.get("protocol_sha256") != POLICY_SHA256:
            raise ValueError("Acquisition preflight/authorization protocol mismatch")
    compressed = Path(record["compressed_path"])
    if (compressed.stat().st_size != record["compressed_bytes"] or compressed.stat().st_size > MAX_NORMALIZED_BYTES
            or sha256(compressed) != record["compressed_sha256"]
            or item["compressed_sha256"] != record["compressed_sha256"]
            or item["decoded_sha256"] != record["decoded_sha256"] or item["decoded_bytes"] != record["decoded_bytes"]):
        raise ValueError("Compressed response checksum/length or proof binding mismatch")
    headers = {key.lower(): value for key, value in record.get("response_headers", {}).items()}
    if (headers.get("content-encoding") != "gzip" or headers.get("x-slice-size") != "10"
            or int(headers.get("content-length", -1)) != record["compressed_bytes"]
            or record.get("received_body_bytes") != record["compressed_bytes"]):
        raise ValueError("HTTP response headers/body length mismatch")
    return record


def _reconstruct(items, contract, policy_path, rows):
    """Replay source order without trusting the producer's normalization code."""
    ordinal = epoch = total_decoded = selected = 0
    previous = {}
    previous_receipt = None
    provenance, raw_provenance, starts, epochs, checks = [], [], [], [], []
    prefix_exclusions = []
    start, end = contract["selected_event_start_ns"], contract["selected_event_end_ns"]
    midnight = _utc_ns(contract["date"] + "T00:00:00Z")
    startup = contract["version"] == "2.3.0"
    for chunk, item in enumerate(items):
        record = _record_check(item, contract, policy_path)
        hasher, size, local = hashlib.sha256(), 0, 0
        with gzip.open(record["compressed_path"], "rb") as stream:
            while True:
                raw = stream.readline(MAX_LINE_BYTES + 1)
                if not raw:
                    break
                if len(raw) > MAX_LINE_BYTES:
                    raise ValueError("Archive line exceeds bounded maximum")
                hasher.update(raw)
                size += len(raw)
                total_decoded += len(raw)
                if total_decoded > MAX_DECODED_BYTES:
                    raise ValueError("Decoded response exceeds bounded daily cap")
                text = raw.decode("utf-8").rstrip("\r\n")
                if not text.strip():
                    epoch += 1
                else:
                    receipt, encoded = text.split(" ", 1)
                    receipt_ns = _utc_ns(receipt)
                    slice_start = midnight + record["offset"] * 60 * NS
                    if not slice_start <= receipt_ns < slice_start + 600 * NS:
                        raise ValueError("Provider receipt falls outside acquired slice partition")
                    if startup and receipt_ns < start:
                        excluded = json.loads(encoded)["data"]
                        prefix_exclusions.append({"source_ordinal": ordinal, "chunk_number": chunk,
                            "chunk_line_ordinal": local, "provider_receipt_text": receipt,
                            "provider_receipt_ns": receipt_ns, "asset": excluded["coin"],
                            "event_ns": excluded["time"] * 1_000_000,
                            "full_payload_sha256": hashlib.sha256(encoded.encode()).hexdigest(),
                            "reason": "fixed_provider_receipt_prefix_before_UTC_00_00_30"})
                        ordinal += 1
                        local += 1
                        continue
                    if previous_receipt is not None and receipt_ns < previous_receipt:
                        raise ValueError("Provider receipt inversion across source rows/slices")
                    previous_receipt = receipt_ns
                    envelope = json.loads(encoded)
                    if envelope.get("channel") != "l2Book":
                        raise ValueError("Unexpected raw archive channel")
                    row = _raw_row(envelope["data"], contract["date"], ordinal)
                    old = previous.get(row["asset"])
                    equal = old is not None and row["event_ns"] == old[0]
                    if old and (row["event_ns"] < old[0] or (equal and old[1] != envelope)):
                        raise ValueError("Raw source inversion or conflicting full-payload event tie")
                    previous[row["asset"]] = row["event_ns"], envelope
                    if row["asset"] == contract["asset"] and start <= row["event_ns"] < end:
                        if len(raw_provenance) >= MAX_ROWS:
                            raise ValueError("Raw in-period provenance exceeds bounded row cap")
                        raw_provenance.append({"source_ordinal": ordinal, "chunk_number": chunk,
                            "chunk_line_ordinal": local, "provider_receipt_text": receipt,
                            "provider_receipt_ns": receipt_ns,
                            "provider_receipt_role": "provider archive collection timestamp, uncalibrated; not release/admission",
                            "event_ns": row["event_ns"], "disconnect_epoch": epoch,
                            "raw_bid_depth": len(envelope["data"]["levels"][0]),
                            "raw_ask_depth": len(envelope["data"]["levels"][1]),
                            "full_payload_sha256": hashlib.sha256(encoded.encode()).hexdigest()})
                    if row["asset"] == contract["asset"] and start <= row["event_ns"] < end and not equal:
                        if selected >= len(rows) or row != rows[selected]:
                            raise ValueError("Normalized row does not exactly reproduce acquired raw snapshot")
                        if not selected or epoch != epochs[-1] or row["event_ns"] - rows[selected - 1]["event_ns"] > MAPPING["max_gap_ns"]:
                            starts.append(selected)
                        epochs.append(epoch)
                        provenance.append({"source_ordinal": ordinal, "chunk_number": chunk,
                            "chunk_line_ordinal": local, "event_ns": row["event_ns"],
                            "provider_receipt_text": receipt, "provider_receive_ns": receipt_ns,
                            "disconnect_epoch": epoch, "full_payload_sha256": hashlib.sha256(encoded.encode()).hexdigest()})
                        selected += 1
                ordinal += 1
                local += 1
        if size != record["decoded_bytes"] or hasher.hexdigest() != record["decoded_sha256"] or local != record["source_lines"]:
            raise ValueError("Independently decoded response hash/length/line count mismatch")
        checks.append({"compressed_sha256": record["compressed_sha256"], "decoded_sha256": hasher.hexdigest(),
                       "decoded_bytes": size, "source_lines": local, "offset": record["offset"]})
    if selected != len(rows):
        raise ValueError("Normalized payload has extra or missing source rows")
    segments = []
    for sid, (first, stop) in enumerate(zip(starts, starts[1:] + [selected])):
        segments.append({"segment_id": sid, "first_row_index": first, "stop_row_index": stop,
            "start_ns": rows[first]["event_ns"], "end_ns": rows[stop - 1]["event_ns"] + 1,
            "first_source_ordinal": rows[first]["source_ordinal"], "last_source_ordinal": rows[stop - 1]["source_ordinal"]})
    return provenance, segments, checks, raw_provenance, prefix_exclusions


def _compare_jsonl(path, expected_rows, message):
    with path.open("rb") as stream:
        for expected in expected_rows:
            line = stream.readline(MAX_LINE_BYTES + 1)
            if not line or len(line) > MAX_LINE_BYTES or json.loads(line) != expected:
                raise ValueError(message)
        if stream.read(1):
            raise ValueError(message + ": extra rows")


def load_panel_contract(path, expected_origin="exploratory_real", *, expected_sha256=None):
    """Load one asset/date; optionally require the externally frozen index hash.

Returned rows gain independently recovered provider provenance only after byte
projection verification. Null release/admission fields remain null: clocks do
not earn promotions just by wearing a timestamp.
"""
    path = Path(path)
    contract = _json(path, expected_sha256)
    base = path.parent
    _check_contract(contract, base, expected_origin)
    if len(contract["sources"]) != 1:
        raise ValueError("One normalized source per dated asset contract required")
    provenance_path = _verify_additive_binding(contract, base) if contract["version"] == "2.2.1" else None
    startup = contract["version"] == "2.3.0"
    if startup:
        provenance_path = _verify_bound_evidence(contract, base)
        for stem, digest_key in (("receipt_prefix_exclusions", "receipt_prefix_exclusions_sha256"),
                                 ("normalizer_source", "normalizer_code_sha256")):
            bound = base / contract[stem + "_file"]
            if bound.stat().st_size > MAX_NORMALIZED_BYTES or sha256(bound) != contract[digest_key]:
                raise ValueError("Startup exclusion/normalizer evidence checksum mismatch")
    source = contract["sources"][0]
    expected_source = f"tardis-hyperliquid-{contract['date']}-{contract['asset'].lower()}"
    if source.get("source_id") != expected_source:
        raise ValueError("Source ID/date/asset mismatch")
    payload = base / source["file"]
    if payload.stat().st_size > MAX_NORMALIZED_BYTES or sha256(payload) != source["sha256"]:
        raise ValueError("Normalized payload checksum mismatch or bounded cap exceeded")
    rows = []
    with payload.open("rb") as stream:
        while True:
            line = stream.readline(MAX_LINE_BYTES + 1)
            if not line:
                break
            if len(line) > MAX_LINE_BYTES or len(rows) >= MAX_ROWS:
                raise ValueError("Normalized payload row/line cap exceeded")
            row = json.loads(line)
            if row.get("release_ns") is not None or row.get("admission_evidence_ns") is not None:
                raise ValueError("Provider receipt cannot become release/admission evidence")
            rows.append(row)
    if not rows:
        raise ValueError("Empty normalized source")
    for field, row in (("actual_first_event_ns", rows[0]), ("actual_last_event_ns", rows[-1])):
        if contract.get(field) != row["event_ns"]:
            raise ValueError("Contract source endpoints disagree with normalized rows")
    proof_path = base / contract["acquisition_proof_file"]
    if (source.get("acquisition_proof_sha256") != contract["acquisition_proof_sha256"]
            or (base / source["acquisition_proof_file"]).resolve() != proof_path.resolve()):
        raise ValueError("Source/contract acquisition proof binding mismatch")
    proof = _json(proof_path, contract["acquisition_proof_sha256"])
    if (proof.get("schema") != "t008-tardis-acquisition-proof/1" or proof.get("date") != contract["date"]
            or proof.get("selection_event_start_ns") != contract["selected_event_start_ns"]
            or proof.get("selection_event_end_ns") != contract["selected_event_end_ns"]):
        raise ValueError("Acquisition proof date/event period mismatch")
    items = proof["records_in_source_order"]
    minutes = (contract["selected_event_end_ns"] - _utc_ns(contract["date"] + "T00:00:00Z")) // (60 * NS)
    if [item["record"]["offset"] for item in items] != list(range(0, minutes, 10)):
        raise ValueError("Acquisition slices must cover the declared ordered period exactly")
    acquisition_policy = contract["source_acquisition_policy_file"] if startup else contract["policy_file"]
    provenance, segments, checks, raw_provenance, prefix_exclusions = _reconstruct(items, contract, base / acquisition_policy, rows)
    if provenance_path is not None:
        _compare_jsonl(provenance_path, raw_provenance, "Bound receipt provenance does not reproduce raw archive metadata")
    if startup:
        _compare_jsonl(base / contract["receipt_prefix_exclusions_file"], prefix_exclusions,
                      "Fixed receipt-prefix exclusions do not reproduce raw archive metadata")
    declared = _json(base / contract["continuity"]["source_segments_file"], contract["continuity"]["source_segments_sha256"])
    if declared != segments:
        raise ValueError("Source segments do not reproduce disconnect/gap boundaries")
    windows = [window for window in contract["windows"] if window["scope"] == "Q17"]
    if not windows or len({window["window_id"] for window in windows}) != len(windows) or len({w["segment_id"] for w in windows}) != len(windows):
        raise ValueError("Distinct Q17 windows/segments required")
    for window in windows:
        sid = window["segment_id"]
        if type(sid) is not int or not 0 <= sid < len(segments):
            raise ValueError("Q17 window references absent segment")
        if (window["asset"] != contract["asset"] or window["source_ids"] != [expected_source]
                or any(window[key] != segments[sid][key] for key in ("start_ns", "end_ns", "first_source_ordinal", "last_source_ordinal"))
                or window.get("max_age_ns") != MAPPING["max_age_ns"]
                or window.get("lookback_ns") != 20 * NS or window.get("forward_guard_ns") != 10_500_000_000
                or window.get("use") != "prespecified_chronological_split" or window.get("state_depth") != 1):
            raise ValueError("Q17 window exceeds verified sampled-state segment/scope")
    for row, info in zip(rows, provenance):
        row.update(provider_receive_ns=info["provider_receive_ns"], provider_receipt_text=info["provider_receipt_text"])
    return {"contract": contract, "contract_path": path, "rows": rows, "windows": windows,
            "origin": expected_origin, "producer_sha256": sha256(path), "mapping_sha256": digest_json(STARTUP_MAPPING if startup else MAPPING),
            "segments": segments, "provider_provenance": provenance,
            "acquisition_verification": {"records": checks, "normalized_rows_reconstructed": len(rows),
                "independent_gzip_decode": True, "source_authentication": "not_independently_authenticated",
                "original_source_full_day_criterion": "distinct from this Hyperliquid period adaptation",
                "empirical_admission": False, "startup_receipt_prefix_excluded": len(prefix_exclusions),
                "adaptation_class": STARTUP_MAPPING["adaptation_class"] if startup else "original strict sampled-period protocol",
                "fit_authorization": "not issued by loader; exact-input review required for startup adaptation"}}
