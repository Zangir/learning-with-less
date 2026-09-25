"""Exact, deterministic clock diagnostics. Source event order is never sorted away."""
from pathlib import Path
from collections import Counter, defaultdict
from decimal import Decimal
from datetime import datetime, timezone
import gzip
import hashlib
import json
import os
import platform
import random
try:
    import resource
except ImportError:  # Windows has no POSIX resource module.
    resource = None
import struct
import time

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT.parent / "T-001"
OUTPUT = ROOT / "evidence"
SEED = 20260919
PREFIX = 200_000
TERMINAL = {2, 4, 5, 7, 10, 11, 12, 13, 14, 16}
RECORD = struct.Struct("<QI?B?IIQIi?????BBII")
assert RECORD.size == 54
random.seed(SEED)


def mark(note):
    line = f"{datetime.now(timezone.utc).isoformat()} {note}"
    print(line, flush=True)
    with (ROOT / "logs" / "clock_timing.log").open("a") as out:
        out.write(line + "\n")


def units(text):
    value = Decimal(text) * 100_000_000
    assert value == value.to_integral_value()
    return int(value)


def decode_units(encoded):
    return (encoded & 0x1FFFFFFF) * 10 ** (8 - (encoded >> 29))


def ns(text):
    body, dot, fraction = text.rstrip("Z").partition(".")
    seconds = int(datetime.fromisoformat(body).replace(tzinfo=timezone.utc).timestamp())
    return seconds * 1_000_000_000 + int((fraction + "000000000")[:9])


def iso(stamp):
    seconds, nano = divmod(stamp, 1_000_000_000)
    return datetime.fromtimestamp(seconds, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S") + f".{nano:09d}Z"


def safe_diff(raw, index):
    delta = raw["raw_book_diff"]
    kind = delta if isinstance(delta, str) else next(iter(delta))
    out = dict(raw_diff_index=index, oid=int(raw["oid"]), kind=kind,
               side=raw["side"], price_usd=raw["px"])
    if kind == "new":
        out["new_size_units_1e8_btc"] = units(delta["new"]["sz"])
    elif kind == "update":
        out["original_size_units_1e8_btc"] = units(delta["update"]["origSz"])
        out["new_size_units_1e8_btc"] = units(delta["update"]["newSz"])
        out["reduction_units_1e8_btc"] = out["original_size_units_1e8_btc"] - out["new_size_units_1e8_btc"]
    return out


def visible_insertion_candidates(events):
    """Official example-server predicate, frozen before the data month; not engine proof."""
    return [s["timestamp_ns"] for s in events if
            (s["status_id"] == 1 and not s["is_trigger"] and s["tif_id"] != 2)
            or (s["is_trigger"] and s["status_id"] == 9)]


def main():
    started = time.monotonic()
    mark("prefix_start")
    rows = []
    with gzip.open(INPUT / "data/book_diffs_20251201_00.gz", "rt") as stream:
        for index, line in enumerate(stream):
            if index >= PREFIX:
                break
            raw = json.loads(line)
            if raw["coin"] == "BTC":
                rows.append(safe_diff(raw, index))
    needed = {r["oid"] for r in rows}
    status = defaultdict(list)
    status_stats = Counter()
    previous_status_ns = None
    with gzip.open(INPUT / "data/btc_20251201_00.data.gz", "rb") as stream:
        offset = 0
        while chunk := stream.read(RECORD.size * 32768):
            assert len(chunk) % RECORD.size == 0
            for r in RECORD.iter_unpack(chunk):
                ts, oid = r[0], r[7]
                if previous_status_ns is not None:
                    status_stats["timestamp_reversals"] += int(ts < previous_status_ns)
                    status_stats["adjacent_ties"] += int(ts == previous_status_ns)
                else:
                    status_stats["first_timestamp_ns"] = ts
                previous_status_ns = ts
                if oid in needed:
                    status[oid].append(dict(raw_status_index=offset, timestamp_ns=ts,
                        timestamp_utc=iso(ts), status_id=r[3], side="A" if r[4] else "B",
                        price_units_1e8_usd=decode_units(r[5]), size_units_1e8_btc=decode_units(r[6]),
                        original_size_units_1e8_btc=decode_units(r[18]),
                        creation_age_ms=r[8], triggered=r[10], is_trigger=r[11],
                        has_children=r[12], is_position_tpsl=r[13], reduce_only=r[14],
                        order_type_id=r[15], tif_id=r[16]))
                offset += 1
        status_stats["records"] = offset
        status_stats["last_timestamp_ns"] = previous_status_ns
    mark(f"status_scan_done rows={offset} relevant={sum(map(len, status.values()))}")
    trades = defaultdict(list)
    trade_stats = Counter()
    previous_trade_ns = None
    with gzip.open(INPUT / "data/trades_20251201_00.gz", "rt") as stream:
        for index, line in enumerate(stream):
            raw = json.loads(line)
            stamp = ns(raw["time"])
            if previous_trade_ns is not None:
                trade_stats["timestamp_reversals"] += int(stamp < previous_trade_ns)
                trade_stats["adjacent_ties"] += int(stamp == previous_trade_ns)
            else:
                trade_stats["first_timestamp_ns"] = stamp
            previous_trade_ns = stamp
            if raw["coin"] != "BTC":
                continue
            trade_stats["btc_rows"] += 1
            for side in raw["side_info"]:
                oid = int(side["oid"])
                if oid in needed:
                    trades[oid].append(dict(raw_trade_index=index, timestamp_ns=stamp,
                        timestamp_utc=iso(stamp), price_usd=raw["px"],
                        size_units_1e8_btc=units(raw["sz"]), aggressor_side=raw["side"]))
        trade_stats["records"] = index + 1
        trade_stats["last_timestamp_ns"] = previous_trade_ns
    mark(f"trade_scan_done rows={index + 1}")
    exact = defaultdict(list)
    for oid, events in trades.items():
        for trade in events:
            exact[(oid, trade["size_units_1e8_btc"])].append(trade["timestamp_ns"])
    book_counts = Counter((r["oid"], r.get("reduction_units_1e8_btc")) for r in rows if r["kind"] == "update")
    ordinals = Counter()
    missing, reversals = [], []
    previous = None
    sources = Counter()
    for row in rows:
        oid, kind = row["oid"], row["kind"]
        events = status[oid]
        if kind == "new":
            values = [r["timestamp_ns"] for r in events if r["status_id"] == 1]
            source = "open_status"
        elif kind == "remove":
            zero = [r["timestamp_ns"] for r in events if r["status_id"] != 1 and r["size_units_1e8_btc"] == 0]
            terminal = [r["timestamp_ns"] for r in events if r["status_id"] in TERMINAL]
            values = zero or terminal
            source = "zero_size_status" if zero else "terminal_status"
        else:
            key = (oid, row["reduction_units_1e8_btc"])
            values = sorted(exact[key])
            source = "missing_exact_size_trade" if not values else "exact_size_trade_interval"
            if values and len(values) == book_counts[key]:
                values = [values[ordinals[key]]]
                source = "equal_multiplicity_trade_ordinal"
            ordinals[key] += 1
        sources[source] += 1
        row["legacy_clock_source"] = source
        row["legacy_clock_bounds_ns"] = [min(values), max(values)] if values else None
        if not values:
            missing.append(row)
        elif min(values) == max(values):
            if previous and values[0] < previous["legacy_clock_bounds_ns"][0]:
                reversals.append(dict(previous=previous, current=row,
                    backward_ns=previous["legacy_clock_bounds_ns"][0] - values[0]))
            previous = row
    assert len(missing) == 8 and len(reversals) == 1
    diagnostic_rows = []
    substitutions = []
    for row in rows:
        diagnostic = dict(row)
        if row["kind"] == "new":
            stamps = visible_insertion_candidates(status[row["oid"]])
            diagnostic["diagnostic_clock_bounds_ns"] = [min(stamps), max(stamps)] if stamps else None
            has_trigger = any(s["is_trigger"] for s in status[row["oid"]])
            diagnostic["diagnostic_clock_source"] = "trigger_status_for_conditional_order" if has_trigger else "nontrigger_non_ioc_open"
            if has_trigger or diagnostic["diagnostic_clock_bounds_ns"] != row["legacy_clock_bounds_ns"]:
                substitutions.append(diagnostic)
        else:
            diagnostic["diagnostic_clock_bounds_ns"] = row["legacy_clock_bounds_ns"]
            diagnostic["diagnostic_clock_source"] = row["legacy_clock_source"]
        diagnostic_rows.append(diagnostic)
    diagnostic_reversals = []
    previous = None
    for row in diagnostic_rows:
        bound = row["diagnostic_clock_bounds_ns"]
        if bound and bound[0] == bound[1]:
            if previous and bound[0] < previous["diagnostic_clock_bounds_ns"][0]:
                diagnostic_reversals.append(dict(previous=previous, current=row))
            previous = row
    contexts = []
    for index, row in enumerate(diagnostic_rows):
        if row["diagnostic_clock_bounds_ns"] is None or row in substitutions:
            before = next((r for r in reversed(diagnostic_rows[:index]) if r["diagnostic_clock_bounds_ns"]), None)
            after = next((r for r in diagnostic_rows[index + 1:] if r["diagnostic_clock_bounds_ns"]), None)
            # These are order-constrained candidates; receipt time is still absent.
            contexts.append(dict(row=row, previous_anchor=before, next_anchor=after,
                order_constrained_interval_ns=[before["diagnostic_clock_bounds_ns"][0], after["diagnostic_clock_bounds_ns"][1]] if before and after else None))
    selected = {r["oid"] for r in missing}
    for reversal in reversals:
        selected.update([reversal["previous"]["oid"], reversal["current"]["oid"]])
    mark(f"legacy_reproduced missing={len(missing)} reversals={len(reversals)} targets={len(selected)}")
    full_diffs = defaultdict(list)
    selected_tokens = [str(oid).encode() for oid in selected]
    with gzip.open(INPUT / "data/book_diffs_20251201_00.gz", "rb") as stream:
        for index, line in enumerate(stream):
            if any(token in line for token in selected_tokens):
                raw = json.loads(line)
                if raw["coin"] == "BTC" and int(raw["oid"]) in selected:
                    full_diffs[int(raw["oid"])].append(safe_diff(raw, index))
    mark(f"full_diff_scan_done rows={index + 1}")
    lifecycles = {str(oid): dict(diffs=full_diffs[oid], statuses=status[oid], trades=trades[oid])
                  for oid in sorted(selected)}
    quantity_checks = []
    for missing_row in missing:
        oid = missing_row["oid"]
        lifecycle = lifecycles[str(oid)]
        group_sums = Counter()
        for trade in trades[oid]:
            group_sums[trade["timestamp_ns"]] += trade["size_units_1e8_btc"]
        previous_quantity = None
        book_chain_errors = []
        for diff in full_diffs[oid]:
            if diff["kind"] == "new":
                previous_quantity = diff["new_size_units_1e8_btc"]
            elif diff["kind"] == "update":
                if previous_quantity is not None and previous_quantity != diff["original_size_units_1e8_btc"]:
                    book_chain_errors.append(diff["raw_diff_index"])
                previous_quantity = diff["new_size_units_1e8_btc"]
        total_trades = sum(t["size_units_1e8_btc"] for t in trades[oid])
        start_quantity = full_diffs[oid][0]["new_size_units_1e8_btc"]
        terminal_quantity = status[oid][-1]["size_units_1e8_btc"]
        quantity_checks.append(dict(raw_diff_index=missing_row["raw_diff_index"],
            all_statuses_reduce_only=all(s["reduce_only"] for s in status[oid]),
            all_status_sides_match=all(s["side"] == missing_row["side"] for s in status[oid]),
            all_status_prices_match=all(s["price_units_1e8_usd"] == units(missing_row["price_usd"]) for s in status[oid]),
            all_trade_prices_match=all(units(t["price_usd"]) == units(missing_row["price_usd"]) for t in trades[oid]),
            all_trades_opposite_aggressor=all(t["aggressor_side"] != missing_row["side"] for t in trades[oid]),
            book_chain_errors=book_chain_errors, terminal_matches_book_quantity=terminal_quantity == previous_quantity,
            original_minus_terminal_minus_trades_units_1e8_btc=start_quantity-terminal_quantity-total_trades,
            missing_reduction_units_1e8_btc=missing_row["reduction_units_1e8_btc"],
            whole_hour_trade_count=len(trades[oid]), total_trades_units_1e8_btc=total_trades,
            same_timestamp_aggregate_matches=[dict(timestamp_ns=stamp, sum_units_1e8_btc=value) for stamp, value in group_sums.items() if value == missing_row["reduction_units_1e8_btc"]],
            same_timestamp_aggregate_candidates=[dict(timestamp_ns=stamp, sum_units_1e8_btc=value) for stamp, value in group_sums.items()]))
    out = dict(task="T-008", experiment_ids=["E-200", "E-201"], seed=SEED,
        raw_ordinals="All source row indices are zero-based; status byte offset = raw_status_index * 54.",
        units={"size": "integer multiples of 1e-8 BTC", "timestamp_ns": "Unix nanoseconds", "price_usd": "USD per BTC decimal string"},
        scope="Frozen first 200000 interleaved diff rows, full acquired-hour statuses/trades and full-hour anomaly diff lifecycles",
        prefix_btc_rows=len(rows), sources=dict(sources), missing_updates=missing, clock_reversals=reversals,
        diagnostic_trigger_substitutions=substitutions, diagnostic_remaining_reversals=diagnostic_reversals,
        diagnostic_point_candidates=sum(bool(r["diagnostic_clock_bounds_ns"]) and r["diagnostic_clock_bounds_ns"][0] == r["diagnostic_clock_bounds_ns"][1] for r in diagnostic_rows),
        insertion_rule_source="https://github.com/hyperliquid-dex/order_book_server/blob/bf5f6bceec3ebc36209bef1ad407de98c3550c70/server/src/types/node_data.rs#L41-L46",
        insertion_rule_caveat="Example reconstruction server logic, not core engine or December deployment attestation",
        anomalous_contexts=contexts, quantity_checks=quantity_checks,
        full_diff_rows=index + 1, status_stream=dict(status_stats), trade_stream=dict(trade_stats),
        lifecycles=lifecycles, receipt_time_available=False, initial_state_certified=False,
        source_manifest_sha256=hashlib.sha256((INPUT / "sample_manifest.json").read_bytes()).hexdigest(),
        code_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        environment=dict(python=platform.python_version(), platform=platform.platform(), cpu_affinity=list(os.sched_getaffinity(0))),
        seconds=time.monotonic()-started,
        max_rss_kib=(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
                     if resource is not None else None))
    (OUTPUT / "clock_forensics.json").write_text(json.dumps(out, indent=2) + "\n")
    mark(f"done seconds={out['seconds']:.3f} max_rss_kib={out['max_rss_kib']}")


if __name__ == "__main__":
    main()
