"""Freeze real observed-new anchors before outcome joins; never infer completeness.

This is an exploratory lifecycle diagnostic, not the eight-atomic-event Q16
estimand. Source order is an observation ordinal, not a fabricated event clock.
"""
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal
import gzip
import hashlib
import json
import os
from pathlib import Path
import platform
import resource
import struct
import time

from r2_selector import freeze_anchors

BASE = (Path(__file__).resolve().parents[2] / 'runtime')
OUT = BASE / "T-009/r2"
SOURCE = BASE / "T-001"
LIMIT = 1000
SCALE = 100000000
STATUS_RECORD = struct.Struct("<QIBBBIIQIiBBBBBBBII")
START = time.monotonic()


def units(value):
    result = Decimal(value) * SCALE
    if result != result.to_integral_value():
        raise ValueError("Nonintegral canonical quantity; no rounding")
    return int(result)


def decoded(value):
    return (value & 0x1fffffff) * 10 ** (8 - (value >> 29))


def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1048576), b""):
            h.update(chunk)
    return h.hexdigest()


def save(name, value):
    (OUT / name).write_text(json.dumps(value, indent=2) + "\n")


def stamp(message):
    row = {"time": datetime.now(timezone.utc).isoformat(), "seconds": time.monotonic() - START,
           "message": message}
    print(json.dumps(row), flush=True)
    with (OUT / "extraction_timing.jsonl").open("a") as stream:
        stream.write(json.dumps(row) + "\n")


def run():
    manifest = json.loads((SOURCE / "sample_manifest.json").read_text())
    paths = {}
    for entry in manifest["files"]:
        path = SOURCE / "data" / entry["file"]
        if sha(path) != entry["sha256"]:
            raise ValueError("Frozen source digest mismatch")
        paths[entry["archive"]] = path
    diff_path = paths["book_diffs_202512.tar"]
    stamp("Verified all three source digests; begin source-prefix-only selection")
    selected, ledger, book = {}, [], {}
    levels = defaultdict(dict)
    seen_inherited = Counter()
    with gzip.open(diff_path, "rt") as stream:
        for seq, line in enumerate(stream):
            row = json.loads(line)
            if row["coin"] != "BTC":
                continue
            oid, side, px, change = row["oid"], row["side"], row["px"], row["raw_book_diff"]
            key = (side, units(px))
            if isinstance(change, dict) and "new" in change:
                q = units(change["new"]["sz"])
                before = list(levels[key].values())
                ledger.append({"candidate_id": f"anchor_{len(ledger) + 1:04d}", "source_seq": seq,
                               "decision": seq, "available": seq,
                               "cohort_eligible": q > 0,
                               "eligibility_reasons": [] if q > 0 else ["nonpositive new"],
                               "eligibility_basis": "positive observed BTC new; exploratory scope only",
                               "past_certificates": [{"ref": "raw-observation-prefix", "available": seq}],
                               "side": side, "price_usdc_per_btc": px, "initial_units_1e8_btc": q,
                               "observed_ahead_volume_units_1e8_btc": sum(before),
                               "observed_ahead_positive_count": len(before),
                               "past_inherited_rows_at_level": seen_inherited[key],
                               "venue_queue_completeness": False})
                book[oid] = (key, q)
                if q > 0:
                    levels[key][oid] = q
                    selected[oid] = ledger[-1]
                if len(selected) == LIMIT:
                    break
            elif change == "remove":
                old = book.pop(oid, None)
                if old is None:
                    seen_inherited[key] += 1
                levels[key].pop(oid, None)
            else:
                new = units(change["update"]["newSz"])
                old = book.get(oid)
                if old is None:
                    seen_inherited[key] += 1
                else:
                    book[oid] = (key, new)
                    if new > 0:
                        levels[key][oid] = new
                    else:
                        levels[key].pop(oid, None)
    frozen = {"task": "T-009", "origin": "exploratory_real_diagnostic", "seed": 20260919,
              "clock_kind": "source_ordinal", "scope": "first <=1000 positive BTC new observations",
              "selection_only_uses_current_or_past_rows": True,
              "future_trade_status_or_lifecycle_joins_started": False,
              "mechanical_selection": freeze_anchors(ledger, limit=LIMIT, clock_kind="source_ordinal"),
              "cutoff_raw_seq": seq, "candidate_ledger": ledger,
              "selected_candidate_ids": [row["candidate_id"] for row in selected.values()],
              "input_sha256": sha(diff_path), "quantity_representation": "1e-8 BTC, not certified venue lot"}
    save("selection_frozen.json", frozen)
    selection_hash = sha(OUT / "selection_frozen.json")
    stamp(f"SELECTION FROZEN: {len(selected)} anchors through raw ordinal {seq}; outcome joins start afterward")
    states = {oid: {"size": None, "positive_remove_quantity": 0, "decrements": 0,
                    "physical_zero_cleanup": 0, "zero_updates": 0, "events": [],
                    "statuses": [], "trades": [], "arithmetic_errors": []} for oid in selected}
    with gzip.open(diff_path, "rt") as stream:
        for seq, line in enumerate(stream):
            row = json.loads(line)
            oid = row.get("oid")
            if row.get("coin") != "BTC" or oid not in states:
                continue
            state, change = states[oid], row["raw_book_diff"]
            if change == "remove":
                kind = "remove"
                old = state["size"]
                if old is None:
                    state["arithmetic_errors"].append("remove_without_identity")
                elif old == 0:
                    state["physical_zero_cleanup"] += 1
                else:
                    state["positive_remove_quantity"] += old
                state["size"] = None
            elif "new" in change:
                kind = "new"
                if state["size"] is not None:
                    state["arithmetic_errors"].append("duplicate_new")
                state["size"] = units(change["new"]["sz"])
            else:
                kind = "update"
                old, new = units(change["update"]["origSz"]), units(change["update"]["newSz"])
                if state["size"] != old:
                    state["arithmetic_errors"].append("old_size_mismatch")
                state["decrements"] += old - new
                state["zero_updates"] += int(new == 0)
                state["size"] = new
            state["events"].append({"raw_seq": seq, "kind": kind, "raw_book_diff": change})
    stamp("Full diff lifecycle pass done; zero identities preserved until explicit removal")
    with gzip.open(paths["btc_orders_202512.tar.xz"], "rb") as stream:
        ordinal = 0
        while chunk := stream.read(54 * 50000):
            if len(chunk) % 54:
                raise ValueError("Truncated status records")
            for item in STATUS_RECORD.iter_unpack(chunk):
                if item[7] in states:
                    states[item[7]]["statuses"].append({"raw_status_seq": ordinal, "event_ns": item[0],
                        "status_id": item[3], "remaining_field_units": decoded(item[6]),
                        "is_trigger": bool(item[11]), "reduce_only": bool(item[14])})
                ordinal += 1
    stamp("Status join complete; recorded execution join begins")
    with gzip.open(paths["trades_2025_12.tar"], "rt") as stream:
        for seq, line in enumerate(stream):
            row = json.loads(line)
            if row["coin"] != "BTC":
                continue
            for leg in row["side_info"]:
                oid = leg["oid"]
                if oid in states:
                    states[oid]["trades"].append({"raw_trade_seq": seq, "event_time": row["time"],
                        "quantity_units": units(row["sz"]), "price": row["px"],
                        "opposite_aggressor_side": row["side"] != selected[oid]["side"]})
    rows, summaries = [], Counter()
    cancel_ids = {2, 7, 10, 11, 12, 13, 14, 16}
    for oid, anchor in selected.items():
        state = states[oid]
        q = anchor["initial_units_1e8_btc"]
        traded = sum(trade["quantity_units"] for trade in state["trades"])
        terminal = state["statuses"][-1]["status_id"] if state["statuses"] else None
        removed = state["size"] is None
        if state["arithmetic_errors"] or traded > q:
            category = "inconsistent_or_unresolved"
        elif not removed:
            category = "right_censored_at_archive_end"
        elif terminal in cancel_ids:
            category = "cancelled_after_recorded_partial_execution" if traded else "cancelled_without_recorded_execution"
        elif traded == q:
            category = "recorded_full_execution"
        else:
            category = "other_terminal_or_unresolved"
        summaries[category] += 1
        rows.append({**anchor, **state, "observed_recorded_execution_units": traded,
                     "terminal_status_id": terminal, "outcome_category": category,
                     "all_recorded_legs_maker_consistent": all(t["opposite_aggressor_side"] for t in state["trades"]),
                     "size_decrements_minus_recorded_executions": state["decrements"] - traded})
    save("observed_lifecycles.json", {"origin": "exploratory_real_diagnostic", "selection_sha256": selection_hash,
         "scope": "selected actual observed orders through acquired archive end, not Q16's eight atomic events",
         "labels_are_not_counterfactual_probe_fills": True, "rows": rows})
    summary = {"origin": "exploratory_real_diagnostic", "selected_anchors": len(rows),
               "selection_sha256": selection_hash, "categories": dict(summaries),
               "orders_with_zero_update": sum(bool(r["zero_updates"]) for r in rows),
               "physical_zero_cleanups": sum(r["physical_zero_cleanup"] for r in rows),
               "arithmetic_error_orders": sum(bool(r["arithmetic_errors"]) for r in rows),
               "orders_with_recorded_execution": sum(r["observed_recorded_execution_units"] > 0 for r in rows),
               "eligible_q16_episodes": 0, "q16_ambiguity_estimated": False,
               "source_manifest_sha256": sha(SOURCE / "sample_manifest.json"),
               "python": platform.python_version(), "cpu_affinity": sorted(os.sched_getaffinity(0)),
               "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
               "elapsed_seconds": time.monotonic() - START}
    save("extraction_summary.json", summary)
    stamp("Exploratory extraction complete; Q16 eligibility remains zero")
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    run()
