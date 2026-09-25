"""Freeze the completed direct feed as a sampled-state development source."""
from collections import Counter, defaultdict
from copy import deepcopy
import gzip
import hashlib
import json
from pathlib import Path
import statistics

from producer_interface import HORIZONS, NS, sha256, snapshot_row, validate_contract, validate_rows, write_json

ROOT = Path(__file__).resolve().parents[1]
CAPTURE_ROOT = ROOT
OUT = ROOT / "live"
MAX_AGE = MAX_GAP = 6 * NS
DEPTH = 20
AGE_WORDS = "six seconds"
SOURCE_PREFIX = "official-live-slow-"


def distribution(values):
    ordered = sorted(values)
    return {"n": len(values), "min": min(values), "median": statistics.median(values),
            "p95": ordered[int(.95 * (len(ordered) - 1))], "max": max(values)} if values else {}


def main():
    status = json.loads((CAPTURE_ROOT / "evidence/live_capture_status.json").read_text())
    if status["status"] != "completed":
        raise ValueError("Wait for complete, closed capture; a partial gzip is not a frozen source")
    OUT.mkdir(exist_ok=True)
    raw = CAPTURE_ROOT / "data/live_capture.jsonl.gz"
    rows, receipts, bbo = defaultdict(list), [], defaultdict(list)
    counts, duplicate_rows = Counter(), []
    wire_digest = hashlib.sha256()
    captured_messages = 0
    with gzip.open(raw, "rt", encoding="utf-8") as stream:
        for line in stream:
            record = json.loads(line)
            wire_digest.update(record["wire_text"].encode("utf-8"))
            captured_messages += 1
            message = json.loads(record["wire_text"])
            channel, data = message["channel"], message.get("data", {})
            counts[channel] += 1
            if channel == "bbo":
                bbo[data["coin"]].append(data["time"] * 1_000_000)
            if channel != "l2Book":
                continue
            asset = data["coin"]
            row = snapshot_row(data, SOURCE_PREFIX + asset.lower(), record["source_row_zero_based"],
                               release_ns=record["received_wall_ns"])
            # The wall clock is an observation, not a tiny atomic clock in disguise.
            receipts.append({"asset": asset, "source_ordinal": row["source_ordinal"],
                             "connection_id": record["connection_id"],
                             "event_ns": row["event_ns"], "received_wall_ns": record["received_wall_ns"],
                             "received_monotonic_ns": record["received_monotonic_ns"]})
            if rows[asset] and row["event_ns"] == rows[asset][-1]["event_ns"]:
                previous = rows[asset][-1]
                fields = [k for k in row if k.endswith(("units8", "counts"))]
                if any(row[k] != previous[k] for k in fields):
                    raise ValueError("Conflicting same-time snapshot")
                duplicate_rows.append(row["source_ordinal"])
                continue
            if rows[asset] and row["event_ns"] < rows[asset][-1]["event_ns"]:
                raise ValueError("Event inversion; source order is never repaired by sorting")
            rows[asset].append(row)

    if wire_digest.hexdigest() != status.get("wire_text_sha256_so_far"):
        raise ValueError("Acquisition wire digest mismatch; cannot attach direct-feed provenance")
    if captured_messages != status.get("messages"):
        raise ValueError("Acquisition message count mismatch")
    acquisition_binding = {"status_file": str(CAPTURE_ROOT / "evidence/live_capture_status.json"),
        "status_sha256": sha256(CAPTURE_ROOT / "evidence/live_capture_status.json"),
        "wire_text_sha256": wire_digest.hexdigest(), "verified_messages": captured_messages,
        "raw_compressed_sha256": sha256(raw), "digest_matches_completed_acquisition": True,
        "collector_digest_scope": "wire payload only; outer receipt metadata are retained observations, not acquisition-stage digest authenticated"}

    contract = deepcopy(json.loads((ROOT / "interface/fixtures/affirmative_shared_contract.json").read_text()))
    contract.update(origin="exploratory_real", fixture_only=False,
                    purpose="live_hyperliquid_sampled_state_pilot", sources=[], windows=[])
    contract["atomic_cut"] = {"kind": "authoritative_snapshot_at_event_time",
                              "evidence": "Direct official public WebSocket l2Book response, exact raw wire_text and observed receipt clocks retained"}
    contract["continuity"] = {"kind": "sampled_snapshots", "max_gap_ns": MAX_GAP,
                              "max_age_ns": MAX_AGE, "cadence_ns": 0,
                              "observed_max_gap_ns": 0, "all_venue_events_observed": False}
    contract["limitations"] = [
        "Exploratory sampled-observation forecast adaptation; not December participant-linked replication",
        "No intervening venue-event completeness, queue priority, hypothetical fill or latency calibration",
        "At grid cut g use latest snapshot at or before g only when age is at most " + AGE_WORDS,
        "Nominal ten-second sampled-grid label retains actual endpoint source times; no exact continuous-venue return claim",
        "Direct feed rights limited to local research use; no blanket redistribution license inferred",
        "Single short session does not supply independent-day inference"]
    contract["protocol"] = {"grid_ns": NS, "split": "first_two_thirds_train_final_third_evaluation",
                             "split_by": "common actual source-time range per asset before horizon purges",
                             "clock": "hypothetical exchange-time decisions; measured receipt not used to claim historical availability",
                             "paired_views": "all depth views share the l2Book source and grid; BBO is diagnostic only"}
    contract["source_raw"] = {"file": str(raw), "sha256": sha256(raw),
                               "bytes": raw.stat().st_size, "endpoint": "wss://api.hyperliquid.xyz/ws"}
    contract["acquisition_binding"] = acquisition_binding
    diagnostics = {"origin": "exploratory_real", "counts": counts, "duplicate_source_ordinals": duplicate_rows,
                   "source_sha256": sha256(raw), "assets": {}, "policy_frozen_before_fits": True}
    for scope in ("Q17", "Q18"):
        contract["scopes"][scope]["reason"] = "Complete snapshot-at-cut state under direct official feed semantics; sampled development protocol only"
    contract["scopes"]["Q16"]["reason"] = "Aggregate snapshots contain no queue identity or observed execution ledger"
    for asset, asset_rows in rows.items():
        path = OUT / (asset.lower() + "_state_rows.jsonl")
        with path.open("w", encoding="utf-8") as stream:
            for row in asset_rows:
                stream.write(json.dumps(row, separators=(",", ":")) + "\n")
        source_id = SOURCE_PREFIX + asset.lower()
        contract["sources"].append({"source_id": source_id, "file": path.name, "sha256": sha256(path),
                                     "provenance": "Direct official Hyperliquid WebSocket l2Book; raw capture digest in source_raw",
                                     "rights": "Local research; public API access does not establish redistribution rights"})
        gaps = [b["event_ns"] - a["event_ns"] for a, b in zip(asset_rows, asset_rows[1:])]
        contract["continuity"]["observed_max_gap_ns"] = max(contract["continuity"]["observed_max_gap_ns"], max(gaps, default=0))
        segments, current = [], []
        for row in asset_rows:
            if current and row["event_ns"] - current[-1]["event_ns"] > MAX_GAP:
                segments.append(current)
                current = []
            current.append(row)
        if current:
            segments.append(current)
        split_ns = asset_rows[0]["event_ns"] + 2 * (asset_rows[-1]["event_ns"] - asset_rows[0]["event_ns"]) // 3
        diagnostics["assets"][asset] = {"snapshots": len(asset_rows), "gap_ns": distribution(gaps),
            "first_event_ns": asset_rows[0]["event_ns"], "last_event_ns": asset_rows[-1]["event_ns"],
            "split_ns": split_ns, "segments": len(segments), "gaps_over_policy": sum(g > MAX_GAP for g in gaps),
            "bbo_observations": len(bbo[asset]),
            "bbo_gap_ns": distribution([b - a for a, b in zip(bbo[asset], bbo[asset][1:])])}
        for index, segment in enumerate(segments):
            validate_rows(segment, MAX_GAP, depth=DEPTH)
            for scope, mode in (("Q17", "Q17_full_latency_grid"), ("Q18", "Q18")):
                h = HORIZONS[mode]
                if segment[-1]["event_ns"] - segment[0]["event_ns"] <= h["lookback_ns"] + h["forward_guard_ns"]:
                    continue
                contract["windows"].append({"window_id": f"live-{asset.lower()}-{scope.lower()}-{index}",
                    "scope": scope, "asset": asset, "start_ns": segment[0]["event_ns"],
                    "end_ns": segment[-1]["event_ns"] + 1, "first_source_ordinal": segment[0]["source_ordinal"],
                    "last_source_ordinal": segment[-1]["source_ordinal"], "state_depth": 1 if scope == "Q17" else 5,
                    "source_ids": [source_id], "evidence_ids": ["direct-official-ws-snapshot", "live_policy.json"],
                    "use": "development", "split_ns": split_ns, **h})
    for scope in ("Q17", "Q18"):
        if not any(w["scope"] == scope for w in contract["windows"]):
            contract["scopes"][scope]["decision"] = "negative"
            contract["scopes"][scope]["reason"] = "No segment supports required history and future guard"
    all_gaps = [b["event_ns"] - a["event_ns"] for asset_rows in rows.values()
                for a, b in zip(asset_rows, asset_rows[1:])]
    contract["continuity"]["cadence_ns"] = int(statistics.median(all_gaps)) if all_gaps else 0
    contract["continuity"]["cadence_basis"] = "observed median; not a guaranteed polling interval"
    write_json(OUT / "receipt_provenance.json", receipts)
    write_json(OUT / "acquisition_binding.json", acquisition_binding)
    write_json(OUT / "diagnostics.json", diagnostics)
    validate_contract(contract, OUT, requested_origin="exploratory_real")
    write_json(OUT / "shared_data_contract.live.v2.0.0.json", contract)
    print(json.dumps({"origin": contract["origin"], "windows": len(contract["windows"]),
                      "assets": diagnostics["assets"], "contract_sha256": sha256(OUT / "shared_data_contract.live.v2.0.0.json")}, indent=2))


if __name__ == "__main__":
    main()
