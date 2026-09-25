"""Strict, bounded admission of the issued T-008 paired snapshot contract."""
from datetime import date, datetime, timezone
from decimal import Decimal
import gzip
import hashlib
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .contracts import sha256
from .producer import read_rows

POLICY_SHA = "84639e7bee796452cae075f4f349e61e8ff37ac4fd9d32685ba0f111baf3120d"
STARTUP_POLICY_SHA = "e5de9c455d3918b11693af0f771de4776f49cd9b2a1f1918000c0179259c8d19"
UNITS = {"time": "UTC Unix ns", "price": "USD per base asset multiplied by1e8",
         "size": "base asset multiplied by1e8", "count": "positive visible native order count"}
HORIZON = {"lookback_ns": 75_000_000_000, "label_horizon_ns": 10_000_000_000,
           "forward_guard_ns": 10_500_000_000, "guard_kind": "adopted_conservative_padding"}


def _bound(base, name, expected, label):
    if not isinstance(name, str) or not name:
        raise ValueError(f"Missing {label} path")
    path = (base / name).resolve()
    if not isinstance(expected, str) or len(expected) != 64 or sha256(path) != expected:
        raise ValueError(f"{label} hash mismatch")
    return path


def _integer(value):
    return type(value) is int and value >= 0


def _proof(path, contract, development):
    proof = json.loads(path.read_text(encoding="utf-8"))
    if (proof.get("schema") != "t008-tardis-acquisition-proof/1" or proof.get("date") != contract["date"]
            or proof.get("selection_event_start_ns") != contract["selected_event_start_ns"]
            or proof.get("selection_event_end_ns") != contract["selected_event_end_ns"]):
        raise ValueError("Acquisition scope mismatch")
    records = proof.get("records_in_source_order", [])
    if not records:
        raise ValueError("Missing acquisition records")
    midnight = int(datetime.combine(date.fromisoformat(contract["date"]), datetime.min.time(), timezone.utc).timestamp()) * 10**9
    offsets = []
    for item in records:
        record = item["record"]
        if record.get("status") != 200 or record.get("completed") is not True or record.get("at_cap", False):
            raise ValueError("Incomplete acquisition response")
        compressed = record.get("compressed_sha256", record.get("body_sha256"))
        size = record.get("compressed_bytes", record.get("received_body_bytes"))
        raw = _bound(path.parent, record["compressed_path"], compressed, "Compressed response")
        if (raw.stat().st_size != size or item.get("compressed_sha256") != compressed
                or item.get("gzip_crc_and_decoded_hash_reverified") is not True):
            raise ValueError("Acquisition response size or binding mismatch")
        digest, total = hashlib.sha256(), 0
        try:
            with gzip.open(raw, "rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    total += len(chunk)
                    if total > 1024**3:
                        raise ValueError("Decoded response exceeds bounded slice size")
                    digest.update(chunk)
        except (OSError, EOFError) as exc:
            raise ValueError("Invalid gzip acquisition response") from exc
        if (total != record["decoded_bytes"] or total != item["decoded_bytes"]
                or digest.hexdigest() != record["decoded_sha256"] or digest.hexdigest() != item["decoded_sha256"]):
            raise ValueError("Decoded response hash/size mismatch")
        headers = {k.lower(): v for k, v in record.get("response_headers", {}).items()}
        if headers.get("content-encoding") != "gzip" or ("content-length" in headers and int(headers["content-length"]) != size):
            raise ValueError("Acquisition HTTP response metadata mismatch")
        url = urlsplit(record["url"]); query = parse_qs(url.query)
        if (url.scheme != "https" or url.netloc != "api.tardis.dev" or url.path != "/v1/data-feeds/hyperliquid"
                or query.get("from") != [contract["date"] + "T00:00:00.000Z"] or query.get("sliceSize") != ["10"]
                or json.loads(query.get("filters", ["null"])[0]) != [{"channel": "l2Book", "symbols": ["BTC", "ETH"]}]):
            raise ValueError("Acquisition source/date/filter mismatch")
        offset = int(query["offset"][0]); offsets.append(offset)
        if not development and (record.get("date") != contract["date"] or record.get("offset") != offset
                                or record.get("protocol_sha256") != contract.get("source_acquisition_policy_sha256", contract["policy_sha256"])):
            raise ValueError("Acquisition policy binding mismatch")
    expected_offsets = list(range((contract["selected_event_start_ns"] - midnight) // (60 * 10**9),
                                  (contract["selected_event_end_ns"] - midnight) // (60 * 10**9), 10))
    if offsets != expected_offsets:
        raise ValueError("Acquisition slices are not the declared ordered period")
    return proof


def read_paired_contract(path, expected_sha, expected_policy_sha, allow_development=False):
    """Return original contract, source paths, segments and bound provenance; issue no approval."""
    path = Path(path).resolve()
    _bound(path.parent, path.name, expected_sha, "Producer contract")
    contract = json.loads(path.read_text(encoding="utf-8"))
    if (contract.get("schema") != "t008-producer-state/2" or contract.get("version") not in ("2.2.0", "2.2.1", "2.3.0")
            or contract.get("producer") != "T-008"
            or contract.get("purpose") != "historical_paired_hyperliquid_sampled_state_adaptation"):
        raise ValueError("Unsupported paired producer contract")
    origin, role = contract.get("origin"), contract.get("split_roles", {}).get("Q18")
    startup = contract["version"] == "2.3.0"
    fixture = origin == "synthetic_integration"
    if origin not in ("exploratory_real", "synthetic_integration") or contract.get("fixture_only") is not fixture:
        raise ValueError("Invalid origin/fixture boundary")
    development = role == "development" or fixture
    if development and not allow_development:
        raise ValueError("Development or synthetic evidence requires explicit opt-in")
    if not development and contract["version"] not in ("2.2.1", "2.3.0"):
        raise ValueError("Real date roles require provenance-bound producer revision 2.2.1")
    if contract["version"] == "2.2.1":
        old_path = _bound(path.parent, contract["supersedes_contract_file"], contract["supersedes_contract_sha256"], "Superseded contract")
        old = json.loads(old_path.read_text(encoding="utf-8"))
        if old.get("version") != "2.2.0" or any(contract.get(k) != v for k, v in old.items() if k not in ("version", "sources")):
            raise ValueError("Additive provenance revision changes original producer semantics")
        if len(old["sources"]) != len(contract["sources"]) or any(
                any(new.get(k) != v for k, v in prior.items()) for prior, new in zip(old["sources"], contract["sources"])):
            raise ValueError("Additive provenance revision changes original source")
    if contract["version"] != "2.2.0":
        _bound(path.parent, contract["normalizer_source_file"], contract["normalizer_code_sha256"], "Normalizer source")
        for name, digest in contract.get("evidence_files", {}).items():
            _bound(path.parent, name, digest, "Producer evidence")
    if role not in ("train", "validation", "test", "unused", "development") or contract.get("asset") not in ("BTC", "ETH"):
        raise ValueError("Unsupported asset or date role")
    if contract.get("units") != UNITS or contract.get("horizons", {}).get("Q18") != HORIZON:
        raise ValueError("Paired units or fixed Q18 horizons mismatch")
    scope = contract.get("scopes", {}).get("Q18", {})
    if any(scope.get(k) != v for k, v in {"decision": "affirmative", "clock_scope": "exchange_time",
                                        "state_scope": "top5_at_snapshot_cuts", "continuity_scope": "sampled_snapshots"}.items()):
        raise ValueError("Q18 producer scope is not affirmative exchange-time top-five")
    if (contract.get("clock_scope") != "exchange_time" or contract.get("atomic_cut", {}).get("kind") != "authoritative_snapshot_at_event_time"
            or not contract["atomic_cut"].get("evidence") or contract.get("review", {}).get("status") != "not_issued_by_producer"):
        raise ValueError("Unsupported authority, clock or producer review claim")
    if not contract.get("eligibility_mask") or not contract.get("receipt_semantics"):
        raise ValueError("Missing retrospective support or receipt semantics")
    if expected_policy_sha != (STARTUP_POLICY_SHA if startup else POLICY_SHA):
        raise ValueError("Unexpected approved policy hash")
    if contract.get("policy_sha256") is None and development and contract.get("policy_file") is None:
        policy = None
    else:
        if contract.get("policy_sha256") != expected_policy_sha:
            raise ValueError("Producer policy hash mismatch")
        policy_path = _bound(path.parent, contract["policy_file"], expected_policy_sha, "Policy")
        policy = json.loads(policy_path.read_text(encoding="utf-8"))
        schema = "t008-paired-panel-startup-adaptation/3.2" if startup else "t008-paired-panel-protocol/3"
        if policy.get("schema") != schema or policy["roles_Q18"].get(contract["date"]) != role:
            raise ValueError("Producer date role differs from frozen policy")
    exclusions_path = None
    if startup:
        if contract.get("startup_exclusion_ns") != 30_000_000_000 or contract.get("adaptation_class") != "SOURCE-QUALITY-INFORMED POST-ACQUISITION PRE-FIT":
            raise ValueError("Startup exclusion or source-quality qualification mismatch")
        for key in ("adaptation_class", "selection_qualification", "restart_claim", "fit_authorization_gate"):
            if not contract.get(key) or policy is not None and contract[key] != policy[key]:
                raise ValueError("Startup contract does not preserve frozen qualification/gate")
        if not development:
            ancestor_path = _bound(path.parent, contract["source_acquisition_policy_file"], POLICY_SHA, "Original acquisition policy")
            ancestor = json.loads(ancestor_path.read_text(encoding="utf-8-sig"))
            if (contract.get("source_acquisition_policy_sha256") != POLICY_SHA or policy.get("supersedes_policy_sha256") != POLICY_SHA
                    or policy.get("startup_exclusion_ns") != 30_000_000_000
                    or any(policy["roles_" + scope] != ancestor["roles_" + scope] for scope in ("Q17", "Q18"))):
                raise ValueError("Startup policy changes acquisition ancestry, cutoff or roles")
        exclusions_path = _bound(path.parent, contract["receipt_prefix_exclusions_file"], contract["receipt_prefix_exclusions_sha256"], "Receipt-prefix exclusions")
    first, stop = contract["selected_event_start_ns"], contract["selected_event_end_ns"]
    if not _integer(first) or not _integer(stop) or first >= stop:
        raise ValueError("Invalid selected event period")
    midnight = int(datetime.combine(date.fromisoformat(contract["date"]), datetime.min.time(), timezone.utc).timestamp()) * 10**9
    if (startup or not development) and (first != midnight + (30_000_000_000 if startup else 0)
                                       or not development and stop - midnight not in (3600 * 10**9, 86400 * 10**9)):
        raise ValueError("Event period differs from frozen hour00/full-day policy")
    continuity = contract["continuity"]
    if any(continuity.get(k) != v for k, v in {"kind": "sampled_snapshots", "max_age_ns": 1_500_000_000,
              "max_gap_ns": 2_000_000_000, "cadence_ns": 1_000_000_000, "all_venue_events_observed": False}.items()):
        raise ValueError("Paired snapshot continuity policy mismatch")
    segment_path = _bound(path.parent, continuity["source_segments_file"], continuity["source_segments_sha256"], "Source segments")
    segments = json.loads(segment_path.read_text(encoding="utf-8"))
    previous, ids = None, set()
    for segment in segments:
        if any(not _integer(segment.get(k)) for k in ("segment_id", "first_row_index", "stop_row_index", "start_ns", "end_ns", "first_source_ordinal", "last_source_ordinal")):
            raise ValueError("Invalid explicit segment integers")
        if (segment["segment_id"] in ids or not first <= segment["start_ns"] < segment["end_ns"] <= stop
                or segment["first_row_index"] != (previous["stop_row_index"] if previous else 0)
                or segment["stop_row_index"] <= segment["first_row_index"]
                or segment["first_source_ordinal"] > segment["last_source_ordinal"]
                or previous and (segment["start_ns"] < previous["end_ns"] or segment["first_source_ordinal"] <= previous["last_source_ordinal"])):
            raise ValueError("Overlapping or inconsistent explicit source segments")
        ids.add(segment["segment_id"]); previous = segment
    if not segments or segments[-1]["stop_row_index"] > 200000:
        raise ValueError("Missing or oversized segment population")
    proof_path = _bound(path.parent, contract["acquisition_proof_file"], contract["acquisition_proof_sha256"], "Acquisition proof")
    sources = {}
    if len(contract.get("sources", [])) != 1:
        raise ValueError("One normalized asset-date source required")
    for source in contract["sources"]:
        if (not source.get("source_id") or not source.get("provenance") or not source.get("rights")
                or source.get("acquisition_proof_sha256") != contract["acquisition_proof_sha256"]
                or (path.parent / source["acquisition_proof_file"]).resolve() != proof_path):
            raise ValueError("Source provenance/proof binding mismatch")
        payload = _bound(path.parent, source["file"], source["sha256"], "Normalized payload")
        if payload.stat().st_size > 256 * 1024**2:
            raise ValueError("Normalized asset-date payload exceeds memory bound")
        sources[source["source_id"]] = payload
    q18, window_ids = [], set()
    for window in contract["windows"]:
        if any(not _integer(window.get(k)) for k in ("segment_id", "start_ns", "end_ns", "first_source_ordinal", "last_source_ordinal")):
            raise ValueError("Invalid window integers")
        matches = [s for s in segments if s["segment_id"] == window.get("segment_id")
                   and s["start_ns"] <= window["start_ns"] < window["end_ns"] <= s["end_ns"]
                   and s["first_source_ordinal"] <= window["first_source_ordinal"] <= window["last_source_ordinal"] <= s["last_source_ordinal"]]
        if (len(matches) != 1 or window["asset"] != contract["asset"] or set(window["source_ids"]) != set(sources)
                or not window.get("evidence_ids") or window["window_id"] in window_ids):
            raise ValueError("Window crosses explicit source segment or has invalid lineage")
        window_ids.add(window["window_id"])
        if window["scope"] == "Q18":
            if any(window.get(k) != v for k, v in {"state_depth": 5, "lookback_ns": 75_000_000_000,
                   "forward_guard_ns": 10_500_000_000, "max_age_ns": 1_500_000_000, "use": "prespecified_chronological_split"}.items()):
                raise ValueError("Q18 window design mismatch")
            if window["end_ns"] - window["start_ns"] <= 85_500_000_000:
                raise ValueError("Q18 window lacks declared lookback and guard support")
            q18.append(window)
    if not q18:
        raise ValueError("No affirmative Q18 window")
    provenance_name = contract.get("source_provenance_file", "source_provenance.jsonl")
    provenance_sha = contract.get("source_provenance_sha256")
    if provenance_sha is None and not development:
        raise ValueError("Real source provenance requires producer file/hash binding")
    provenance_path = (path.parent / provenance_name).resolve()
    if provenance_sha is not None:
        _bound(path.parent, provenance_name, provenance_sha, "Raw provenance")
    if contract["version"] != "2.2.0" and any(source.get("source_provenance_file") != provenance_name
                                             or source.get("source_provenance_sha256") != provenance_sha for source in contract["sources"]):
        raise ValueError("Source provenance references disagree with contract")
    provenance = {"acquisition_proof": _proof(proof_path, contract, development), "policy": policy,
                  "acquisition_proof_file": proof_path,
                  "source_provenance_file": provenance_path, "source_provenance_sha256": sha256(provenance_path),
                  "producer_bound_provenance": provenance_sha is not None,
                  "contract_file": path, "contract_sha256": expected_sha, "development_only": development}
    if startup:
        provenance.update(receipt_prefix_exclusions_file=exclusions_path,
                          receipt_prefix_exclusions_sha256=contract["receipt_prefix_exclusions_sha256"])
    return contract, sources, segments, provenance

def _receipt_ns(receipt):
    whole, fraction = receipt[:-1].split(".") if "." in receipt else (receipt[:-1], "")
    if not receipt.endswith("Z") or len(fraction) > 9 or fraction and not fraction.isdigit():
        raise ValueError("Invalid native provider receipt timestamp")
    seconds = int(datetime.strptime(whole, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc).timestamp())
    return seconds * 10**9 + int(fraction.ljust(9, "0") or 0)


def _verify_values(row, data):
    for side, levels in zip(("bid", "ask"), data["levels"]):
        for field, key in (("px", "prices_units8"), ("sz", "sizes_units8")):
            exact = [Decimal(level[field]) * 10**8 for level in levels[:5]]
            if any(value <= 0 or value != value.to_integral_value() for value in exact) or [int(value) for value in exact] != row[side + "_" + key]:
                raise ValueError("Normalized top-five values differ from raw message")
        counts = [level["n"] for level in levels[:5]]
        if any(type(count) is not int or count <= 0 for count in counts) or counts != row[side + "_counts"]:
            raise ValueError("Normalized native counts differ from raw message")


def _verify_raw(rows, records, provenance, contract):
    """Receipt exclusion precedes full retained-stream order checks, then event selection."""
    selected = {row["source_ordinal"]: row for row in rows}
    startup = contract["version"] == "2.3.0"
    first, stop = contract["selected_event_start_ns"], contract["selected_event_end_ns"]
    exclusions, excluded_seen = {}, set()
    if startup:
        exclusion_path = provenance["receipt_prefix_exclusions_file"]
        _bound(exclusion_path.parent, exclusion_path.name, provenance["receipt_prefix_exclusions_sha256"], "Receipt-prefix exclusions")
        with exclusion_path.open(encoding="utf-8") as stream:
            for line in stream:
                item = json.loads(line); ordinal = item["source_ordinal"]
                if not _integer(ordinal) or ordinal in exclusions or len(exclusions) >= 200000:
                    raise ValueError("Invalid receipt-prefix exclusion ledger")
                exclusions[ordinal] = item
    ordinal, epoch, matched = 0, 0, set()
    previous, previous_receipt, retained = {}, None, 0
    for chunk_number, item in enumerate(provenance["acquisition_proof"]["records_in_source_order"]):
        record = item["record"]
        path = _bound(provenance["acquisition_proof_file"].parent, record["compressed_path"], item["compressed_sha256"], "Compressed response")
        with gzip.open(path, "rt", encoding="utf-8", newline="") as stream:
            for local_ordinal, line in enumerate(stream):
                current = ordinal; ordinal += 1
                line = line.rstrip("\r\n")
                if not line.strip():
                    epoch += 1
                    continue
                receipt, encoded = line.split(" ", 1)
                receipt_ns = _receipt_ns(receipt)
                envelope = json.loads(encoded); data = envelope["data"]
                if envelope.get("channel") != "l2Book" or data["coin"] not in ("BTC", "ETH") or type(data["time"]) is not int:
                    raise ValueError("Unexpected native source envelope")
                event, payload_sha = data["time"] * 10**6, hashlib.sha256(encoded.encode()).hexdigest()
                identity = {"source_ordinal": current, "chunk_number": chunk_number, "chunk_line_ordinal": local_ordinal,
                            "provider_receipt_text": receipt, "provider_receipt_ns": receipt_ns,
                            "asset": data["coin"], "event_ns": event, "full_payload_sha256": payload_sha}
                if startup and receipt_ns < first:
                    identity["reason"] = "fixed_provider_receipt_prefix_before_UTC_00_00_30"
                    if current in records or current in selected:
                        raise ValueError("Excluded receipt-prefix state reenters analytical support")
                    if exclusions.get(current) != identity:
                        raise ValueError("Receipt-prefix exclusion ledger differs from raw message")
                    excluded_seen.add(current)
                    continue
                # Source ordering is tested even when this event will later fall outside the analytical period.
                old = previous.get(data["coin"])
                if previous_receipt is not None and receipt_ns < previous_receipt:
                    raise ValueError("Provider receipt inversion in retained source stream")
                if old and (event < old[0] or event == old[0] and envelope != old[1]):
                    raise ValueError("Retained raw event inversion or conflicting full-payload tie")
                equal = old is not None and event == old[0]
                previous[data["coin"]] = (event, envelope); previous_receipt = receipt_ns; retained += 1
                included = data["coin"] == contract["asset"] and first <= event < stop
                if included != (current in records) or (included and not equal) != (current in selected):
                    raise ValueError("Raw analytical population or earliest-tie policy differs from normalized source")
                if not included:
                    continue
                raw = records[current]
                if (any(raw.get(key) != value for key, value in identity.items() if key != "asset")
                        or raw["disconnect_epoch"] != epoch
                        or [raw["raw_bid_depth"], raw["raw_ask_depth"]] != [len(levels) for levels in data["levels"]]):
                    raise ValueError("Raw message differs from bound source provenance")
                if current in selected:
                    _verify_values(selected[current], data)
                matched.add(current)
    if len(matched) != len(records) or not set(selected) <= matched or set(exclusions) != excluded_seen:
        raise ValueError("Source provenance or exclusions contain unobserved raw ordinals")
    return {"retained_raw_messages_order_checked": retained, "receipt_prefix_exclusions_verified": len(excluded_seen)}

def read_paired_rows(contract, sources, segments, provenance):
    """Load at most one 200k-row asset-date, preserving disconnect boundaries and raw provenance."""
    if sha256(provenance["source_provenance_file"]) != provenance["source_provenance_sha256"]:
        raise ValueError("Raw provenance changed after admission")
    for source in contract["sources"]:
        if sha256(sources[source["source_id"]]) != source["sha256"]:
            raise ValueError("Normalized payload changed after admission")
    by_asset, audit = read_rows(sources)
    if set(by_asset) != {contract["asset"]}:
        raise ValueError("Normalized rows differ from contract asset")
    rows = by_asset[contract["asset"]]
    if len(rows) != segments[-1]["stop_row_index"]:
        raise ValueError("Explicit segments do not cover normalized rows")
    records, previous_ordinal = {}, -1
    with provenance["source_provenance_file"].open(encoding="utf-8") as stream:
        for line in stream:
            item = json.loads(line); ordinal = item["source_ordinal"]
            if not _integer(ordinal) or ordinal <= previous_ordinal or len(records) >= 200000:
                raise ValueError("Invalid or oversized raw provenance order")
            if any(not _integer(item.get(k)) for k in ("chunk_number", "chunk_line_ordinal", "provider_receipt_ns", "event_ns", "disconnect_epoch", "raw_bid_depth", "raw_ask_depth")):
                raise ValueError("Incomplete native source provenance")
            if (min(item["raw_bid_depth"], item["raw_ask_depth"]) < 5 or len(item.get("full_payload_sha256", "")) != 64
                    or not item.get("provider_receipt_text") or not item.get("provider_receipt_role")):
                raise ValueError("Missing raw payload or provider receipt provenance")
            records[ordinal] = item; previous_ordinal = ordinal
    for segment in segments:
        part = rows[segment["first_row_index"]:segment["stop_row_index"]]
        if (part[0]["event_ns"] != segment["start_ns"] or part[-1]["event_ns"] + 1 != segment["end_ns"]
                or part[0]["source_ordinal"] != segment["first_source_ordinal"] or part[-1]["source_ordinal"] != segment["last_source_ordinal"]):
            raise ValueError("Segment endpoints differ from normalized source rows")
        prior = None
        for row in part:
            raw = records.get(row["source_ordinal"])
            if raw is None or raw["event_ns"] != row["event_ns"] or row.get("release_ns") is not None or row.get("admission_evidence_ns") is not None:
                raise ValueError("Source row/provenance clock mismatch")
            if any(len(row[k]) != 5 or any(type(v) is not int or v <= 0 for v in row[k]) for k in ("bid_counts", "ask_counts")):
                raise ValueError("Positive native top-five counts required")
            if prior and (row["event_ns"] - prior["event_ns"] > 2_000_000_000
                          or raw["disconnect_epoch"] != records[prior["source_ordinal"]]["disconnect_epoch"]):
                raise ValueError("Explicit segment crosses source gap or disconnect")
            prior = row
    audit.update(_verify_raw(rows, records, provenance, contract))
    audit.update(asset=contract["asset"], date=contract["date"], source_segments=len(segments), raw_mapping_verified=True,
                 raw_provenance_rows=len(records), maximum_rows_per_asset_date=200000)
    return rows, audit
