"""Run the authorized single-window P0 after amendment/fixture/integrity gates.

Parameters are fixed here and in the pre-extraction amendment. No CLI options,
outcome label creation, training, market acquisition, or scope search is offered.
"""
from bisect import bisect_right
from collections import Counter
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import random
import subprocess
import sys
import unittest

from t016_p0.engine import NS, Observations, bbo_projection, extract, retrospective_support, stable_hash
from t016_p0.integrity import check_file, file_hash, now, read_json, verify_contract, verify_packet

random.seed(20260919)
ARTIFACTS = Path(__file__).resolve().parents[2] / 'runtime'
OUT = ARTIFACTS / "T-016/r2-p0"
AUTHOR = ARTIFACTS / "cycle-20260922-0314/frozen-R-023"
REVIEW = ARTIFACTS / "cycle-20260922-0415/frozen-RV-021"
WORK = Path(__file__).resolve().parents[1]
DAY = 1746057600 * NS
START, END = DAY + 30 * NS, DAY + 3600 * NS
AUTHOR_MANIFEST = "d17f6f7aab3eccd89e0a9f0c5f4b527895620eadc267edc9cf0005cee36eee5c"
REVIEW_MANIFEST = "5467ab074fb9c6a4688232bb06b43770b42ed5d8f1bcef31d89d4e59f56c9813"
AMENDMENT_HASH = "07613fea21abfb4fb58ce33e2be54cafde66ec9938ae7c08944561e08aa55405"


def write_json(name, value):
    (OUT / name).write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_lines(name, values):
    with (OUT / name).open("w", encoding="utf-8") as stream:
        for value in values:
            stream.write(json.dumps(value, sort_keys=True, ensure_ascii=False) + "\n")


def stage(name, detail):
    stamp = now()
    with (OUT / "timings.log").open("a", encoding="utf-8") as stream:
        stream.write(f"{stamp} | {name} | {detail}\n")
    print(stamp, name, detail, flush=True)


def load_restriction(directory, segments):
    """Parse only retained in-window states; later data is integrity-hashed, not analyzed."""
    states, boundary = [], None
    segment_index = 0
    with (directory / "state_rows.jsonl").open("rb") as stream:
        for index, raw in enumerate(stream):
            row = json.loads(raw)
            if row["event_ns"] >= END:
                boundary = {"physical_line_1_based": index + 1, "event_ns": row["event_ns"],
                            "source_ordinal": row["source_ordinal"], "reason": "half_open_restriction"}
                break
            if row["event_ns"] < START:
                continue
            while index >= segments[segment_index]["stop_row_index"]:
                segment_index += 1
            segment = segments[segment_index]
            assert segment["first_row_index"] <= index < segment["stop_row_index"]
            assert row["asset"] == "BTC"
            assert row["source_id"] == "tardis-hyperliquid-2025-05-01-btc"
            assert row["release_ns"] is None and row["admission_evidence_ns"] is None
            row = {**row, "segment_id": segment["segment_id"], "physical_line_1_based": index + 1,
                   "source_line_sha256": sha256(raw).hexdigest()}
            states.append(row)
    wanted = {r["source_ordinal"] for r in states}
    provenance = {}
    if wanted:
        last = max(wanted)
        with (directory / "source_provenance.jsonl").open("rb") as stream:
            for line, raw in enumerate(stream, 1):
                row = json.loads(raw)
                if row["source_ordinal"] > last:
                    break
                if row["source_ordinal"] in wanted:
                    assert row["source_ordinal"] not in provenance
                    provenance[row["source_ordinal"]] = {**row, "provenance_line_1_based": line,
                        "provenance_line_sha256": sha256(raw).hexdigest()}
    assert set(provenance) == wanted
    for row in states:
        record = provenance[row["source_ordinal"]]
        assert record["event_ns"] == row["event_ns"]
        row["disconnect_epoch"] = record["disconnect_epoch"]
    return states, provenance, boundary


def prefix_checks(rows, segments, full, full_masks):
    output = []
    times = [r["event_ns"] for r in rows]
    for second in (900, 1800, 2700):
        stop = bisect_right(times, DAY + second * NS)
        obs = Observations(rows[:stop], segments, START, END)
        prefix = extract(obs, AMENDMENT_HASH)
        watermark = obs.times[-1]
        common = watermark // NS * NS
        checks = {}
        for name, key in (("events", "decision_ns"), ("candidates", "decision_ns"),
                          ("blocked_cuts", "cut_ns"), ("levels", "anchor_ns")):
            expected = [r for r in full[name] if r[key] <= common]
            checks[name] = expected == prefix[name]
            assert checks[name], (second, name)
        masks = retrospective_support(obs, prefix["events"])
        full_by_id = {m["event_id"]: m for m in full_masks}
        changed = []
        for mask in masks:
            reference = full_by_id[mask["event_id"]]
            if mask != reference:
                assert mask["decision_ns"] + 10 * NS > watermark
                assert not mask["complete_future_support"]
                changed.append(mask["event_id"])
        output.append({"nominal_prefix_second": second, "prefix_rows": stop,
            "observed_watermark_ns": watermark, "common_finalized_cut_ns": common,
            "causal_records_equal": checks, "prefix_recorded_events": len(prefix["events"]),
            "retrospective_mask_changes": len(changed), "changed_event_ids": changed,
            "nonexistent_tail_cuts_compared": False})
    return output


def main():
    if (OUT / "p0-summary.json").exists():
        raise FileExistsError("A P0 result already exists; preserve it and explicitly version any correction")
    stage("fixtures", "Run implementation boundary tests before any market-row parsing")
    tests = unittest.defaultTestLoader.discover(str(WORK / "t016_p0"), pattern="test_engine.py", top_level_dir=str(WORK))
    fixture_log = OUT / "logs" / ("fixtures-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + ".log")
    with fixture_log.open("w", encoding="utf-8") as stream:
        result = unittest.TextTestRunner(stream=stream, verbosity=2).run(tests)
    write_json("fixture-results.json", {"run_utc": now(), "tests": result.testsRun,
        "failures": len(result.failures), "errors": len(result.errors), "passed": result.wasSuccessful(),
        "kind": "executed software fixtures, synthetic and not market evidence", "market_rows_read_before_tests": 0,
        "log": str(fixture_log)})
    if not result.wasSuccessful() or result.testsRun < 12:
        raise RuntimeError("Fixture gate failed")
    stage("integrity", "Fresh complete hashes for frozen packets and every directly bound consumer input")
    amendment = check_file(OUT / "protocol-amendment.json", AMENDMENT_HASH)
    freeze = read_json(OUT / "amendment-freeze-receipt.json")
    freeze_checks = [check_file(OUT / f["path"], f["sha256"]) for f in freeze["files"]]
    protocol = read_json(OUT / "protocol-amendment.json")
    packets = {"frozen_author": verify_packet(AUTHOR, AUTHOR_MANIFEST),
               "frozen_review": verify_packet(REVIEW, REVIEW_MANIFEST),
               "original_r1": verify_packet(ARTIFACTS / "T-016/r1", AUTHOR_MANIFEST)}
    contract_path = Path(protocol["source_contract"])
    contract, inputs = verify_contract(contract_path, protocol["source_contract_sha256"], ARTIFACTS)
    write_json("input-integrity.json", {"finished_utc": now(), "amendment": amendment,
        "freeze_checks": freeze_checks, "packets": packets, "direct_contract_inputs": inputs,
        "scope": "All listed consumer files freshly hashed in full; no independent raw exchange/archive replay or authentication"})
    assert contract["continuity"]["max_age_ns"] == 1_500_000_000
    assert contract["continuity"]["max_gap_ns"] == 2 * NS
    stage("extraction", "Begin the single fixed one-hour label-blind extraction after all gates passed")
    segments = read_json(contract_path.parent / contract["continuity"]["source_segments_file"])
    rows, provenance, boundary = load_restriction(contract_path.parent, segments)
    obs = Observations(rows, segments, START, END)
    output = extract(obs, AMENDMENT_HASH)
    masks = retrospective_support(obs, output["events"])
    prefixes = prefix_checks(rows, segments, output, masks)
    projections = 0
    for point in obs.grid.values():
        if point["valid"]:
            row = obs.rows[point["row_index"]]
            assert point["source_ordinal"] == row["source_ordinal"]
            assert point["bbo"] == bbo_projection(row, point["age_ns"])
            # Independently index each observed side instead of copying a cached coarse vector.
            assert point["bbo"][:6] == [row["bid_prices_units8"][0], row["ask_prices_units8"][0],
                row["bid_sizes_units8"][0], row["ask_sizes_units8"][0], row["bid_counts"][0], row["ask_counts"][0]]
            projections += 1
    for name in ("levels", "candidates", "events", "blocked_cuts"):
        write_lines(name + ".jsonl", output[name])
    write_lines("grid.jsonl", obs.grid.values())
    write_lines("support-masks.jsonl", masks)
    write_lines("source-row-provenance.jsonl", [{"source_ordinal": r["source_ordinal"],
        "state_line_1_based": r["physical_line_1_based"], "state_line_sha256": r["source_line_sha256"],
        **provenance[r["source_ordinal"]]} for r in rows])
    write_json("restricted-segments.json", list(obs.segments.values()))
    write_json("prefix-checks.json", prefixes)
    rejected = [c for c in output["candidates"] if c["status"] == "rejected"]
    summary = {"created_utc": now(), "scope": "one-hour P0 feasibility only; no price outcome labels",
        "protocol_sha256": AMENDMENT_HASH, "contract_sha256": protocol["source_contract_sha256"],
        "restriction_ns": [START, END], "source_rows_retained": len(rows),
        "first_retained_event_ns": obs.times[0] if rows else None,
        "last_retained_event_ns": obs.times[-1] if rows else None,
        "retained_endpoint_exclusive_ns": obs.end, "first_excluded_boundary_witness": boundary,
        "grid_cuts": len(obs.grid), "valid_grid_cuts": projections,
        "level_anchors": len(output["levels"]), "valid_level_anchors": sum(x["valid"] for x in output["levels"]),
        "level_rejections": dict(Counter(x["reason"] for x in output["levels"] if not x["valid"])),
        "blocked_cuts": len(output["blocked_cuts"]),
        "raw_candidates": len(output["candidates"]), "recorded_events": len(output["events"]),
        "recorded_by_family": dict(Counter(e["family"] for e in output["events"])),
        "rejected_candidates": len(rejected), "rejection_reasons": dict(Counter(c["reason"] for c in rejected)),
        "complete_future_support_events": sum(m["complete_future_support"] for m in masks),
        "censored_support_events": sum(not m["complete_future_support"] for m in masks),
        "same_row_projection_checks": projections, "prefix_checks_passed": True,
        "future_price_labels_generated": 0, "fits": 0, "outcome_metrics_computed": False}
    assert summary["raw_candidates"] == summary["recorded_events"] + summary["rejected_candidates"]
    write_json("p0-summary.json", summary)
    sampled = []
    for family in ("breakout", "rebound"):
        event = next((e for e in output["events"] if e["family"] == family), None)
        if event is None:
            sampled.append({"family": family, "status": "no recorded event available in the fixed window"})
        else:
            ordinal = event["decision_source_ordinal"]
            row = next(r for r in rows if r["source_ordinal"] == ordinal)
            sampled.append({"family": family, "status": "actual recorded P0 opportunity; no outcome label",
                "event": event, "decision_row": row, "decision_provenance": provenance[ordinal],
                "level": next(l for l in output["levels"] if l["anchor_ns"] == event["anchor_ns"]),
                "support_mask": next(m for m in masks if m["event_id"] == event["event_id"])})
    write_json("actual-examples.json", sampled)
    stage("post-integrity", "Rehash all directly bound inputs and prior packets to verify preservation")
    _, post = verify_contract(contract_path, protocol["source_contract_sha256"], ARTIFACTS)
    prior = verify_packet(ARTIFACTS / "T-016/r1", AUTHOR_MANIFEST)
    write_json("post-integrity.json", {"completed_utc": now(), "direct_contract_inputs": post,
                                      "original_r1": prior, "all_unchanged": True})
    write_json("code-identity.json", {"base_commit": "ed62f2a4ccebc7ad559ba0c185954401d5311cb8",
        "executed_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=WORK, text=True).strip(),
        "executed_files": [{"path": str(p.relative_to(WORK)), "sha256": file_hash(p)}
                           for p in sorted((WORK / "t016_p0").glob("*.py"))],
        "python_version": sys.version, "stochastic_diagnostic": False, "seed": 20260919})
    stage("p0-complete", "Fixed P0 extraction and consumer invariants finished; no scientific acceptance conferred")
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    main()
