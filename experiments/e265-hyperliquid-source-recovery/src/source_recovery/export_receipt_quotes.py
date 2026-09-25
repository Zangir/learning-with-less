"""Export two clocks and exact top-five states from retained provider raw bytes.

All market arrays are source data, not fitted features or labels. Repeated event
states remain separate receipt observations. No sorting repairs source defects.
"""
from settings import OUT, PRIOR, EXCHANGE, NS, SEED, bind, now, pin, read, save, sha, stamp, utc_ns
from collections import Counter
import gzip
import hashlib
import json
import time
import pyarrow as pa
import pyarrow.parquet as pq

DATES = [f"2025-{month:02d}-01" for month in range(1, 12)]
PREFIX_NS = 30 * NS
MAX_GAP_NS = 2 * NS
DEST = OUT / "receipt_quotes"


def integer8(value):
    """Convert source decimal text exactly; reject rather than round precision."""
    whole, _, frac = value.partition(".")
    if len(frac) > 8 or not whole.isdigit() or (frac and not frac.isdigit()):
        raise ValueError("Expected nonnegative decimal with at most eight places")
    return int(whole) * 100_000_000 + int(frac.ljust(8, "0") or 0)


def project(data):
    sides = data["levels"]
    if len(sides) != 2 or any(len(side) < 5 for side in sides):
        raise ValueError("Missing five-level book")
    result = {}
    for name, levels in zip(("bid", "ask"), sides):
        prices = [integer8(level["px"]) for level in levels]
        sizes = [integer8(level["sz"]) for level in levels]
        counts = [level["n"] for level in levels]
        if any(x <= 0 for x in prices + sizes) or any(not isinstance(n, int) or n < 1 for n in counts):
            raise ValueError("Nonpositive state or invalid count")
        pairs = zip(prices, prices[1:])
        if not all(a > b if name == "bid" else a < b for a, b in pairs):
            raise ValueError("Invalid price-level order")
        for k in range(5):
            for field, values in (("px_e8", prices), ("sz_e8", sizes), ("n", counts)):
                result[f"{name}_{field}_{k}"] = values[k]
    if result["bid_px_e8_0"] >= result["ask_px_e8_0"]:
        raise ValueError("Locked/crossed book")
    return result


def export_day(date, index, proc):
    started = time.monotonic()
    day = DEST / date
    day.mkdir(parents=True, exist_ok=True)
    midnight = utc_ns(date + "T00:00:00Z")
    records = index["records"]
    if [r["offset"] for r in records] != list(range(0, 1440, 10)):
        raise ValueError("Missing or out-of-order archive partitions")
    rows = {asset: [] for asset in ("BTC", "ETH")}
    previous = {}
    epoch = 0
    next_segment = Counter()
    counters = {asset: Counter() for asset in rows}
    defects = []
    lineage = []
    ordinal = 0
    peak_rss = proc.memory_info().rss
    receipt_previous = None
    for item in records:
        raw_path = item["compressed_path"]
        if sha(raw_path) != item["compressed_sha256"]:
            raise ValueError("Compressed source hash mismatch")
        decoded_hash = hashlib.sha256()
        nbytes = 0
        with gzip.open(raw_path, "rb") as stream:
            for line_number, line in enumerate(stream):
                decoded_hash.update(line)
                nbytes += len(line)
                raw_ordinal = ordinal
                ordinal += 1
                if not line.strip():
                    epoch += 1
                    continue
                receipt_text, payload = line.decode("utf-8").split(" ", 1)
                recv = utc_ns(receipt_text)
                if not midnight + item["offset"] * 60 * NS <= recv < midnight + (item["offset"] + 10) * 60 * NS:
                    raise ValueError("Source receipt outside requested partition")
                message = json.loads(payload)
                if message.get("channel") != "l2Book":
                    raise ValueError("Unexpected source channel")
                data = message["data"]
                asset = data["coin"]
                if asset not in rows:
                    raise ValueError("Unexpected asset")
                counters[asset]["raw_rows"] += 1
                if recv < midnight + PREFIX_NS:
                    counters[asset]["receipt_prefix_excluded"] += 1
                    continue
                event = int(data["time"]) * 1_000_000
                # Keep observation order honest: clocks do not get a sorting spa.
                full_hash = hashlib.sha256(json.dumps(message, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
                projected = project(data)
                old = previous.get(asset)
                if receipt_previous is not None and recv < receipt_previous:
                    defects.append(dict(kind="receipt_inversion", asset=asset, ordinal=raw_ordinal))
                receipt_previous = recv
                if old:
                    if event < old[0]:
                        defects.append(dict(kind="event_inversion", asset=asset, ordinal=raw_ordinal,
                                            backward_ns=old[0]-event))
                    if event == old[0]:
                        counters[asset]["repeated_event_timestamp"] += 1
                        if full_hash != old[3]:
                            defects.append(dict(kind="conflicting_event_tie", asset=asset, ordinal=raw_ordinal))
                    if epoch != old[2] or event-old[0] > MAX_GAP_NS or recv-old[1] > MAX_GAP_NS:
                        next_segment[asset] += 1
                previous[asset] = (event, recv, epoch, full_hash)
                if not midnight + PREFIX_NS <= event < midnight + 86400 * NS:
                    counters[asset]["event_period_excluded"] += 1
                    continue
                row = dict(event_ns=event, receipt_ns=recv, source_ordinal=raw_ordinal,
                           slice_offset_minutes=item["offset"], slice_line_ordinal=line_number,
                           segment_id=next_segment[asset], raw_line_sha256=hashlib.sha256(line).hexdigest())
                row.update(projected)
                rows[asset].append(row)
        if decoded_hash.hexdigest() != item["decoded_sha256"]:
            raise ValueError("Decoded source hash mismatch")
        lineage.append(dict(offset=item["offset"], compressed=bind(raw_path),
                            decoded_sha256=decoded_hash.hexdigest(), decoded_bytes=nbytes))
        peak_rss = max(peak_rss, proc.memory_info().rss)
        if peak_rss > 8 * 1024**3:
            raise MemoryError("Assignment memory cap exceeded")
    save(day / "source_manifest.json", lineage)
    contracts = []
    for asset in rows:
        values = rows[asset]
        table = pa.Table.from_pylist(values)
        destination = day / f"{asset}.parquet"
        pq.write_table(table, destination, compression="zstd")
        back = pq.read_table(destination)
        if not table.equals(back):
            raise ValueError("Parquet round-trip mismatch")
        bad = [d for d in defects if d["asset"] == asset]
        contract = dict(schema="t018-dual-clock-l2/1", asset=asset, date=date,
            source="Tardis raw Hyperliquid l2Book archive", source_level="sampled native-format L2",
            observation_clock="provider receipt_ns; authentic retained provider record, not archive fetch time",
            endpoint_clock="exchange event_ns", source_authentication="HTTPS provider provenance, no independent exchange attestation",
            normalization="Exact source decimal integer scale 1e8, top five prices/sizes plus counts; ns timestamps",
            duplicate_policy="Retain every receipt observation including equal identical event states; reject conflicting ties",
            prefix_policy="Fixed receipt and event UTC prefix of 30 seconds excluded; validation before event filtering",
            segment_policy="Disconnect marker or >2s gap in event or receipt clock; no row-level outcome filter",
            q17_requirement="Consumer uses receipt for grid/features and event for labels/quote endpoints; respect support and history within segments",
            q18_requirement="Consumer freezes explicit observation convention and own-clock normalization; 55s means cached-view shift",
            not_supported=["L4 identity/FIFO", "atomic economic events", "participant labels", "measured strategy latency", "every exchange change"],
            producer_source_status="eligible_pending_independent_review" if not bad else "invalid",
            review_status="pending", rows=len(values), source_counters=dict(counters[asset]),
            first_event_ns=values[0]["event_ns"], last_event_ns=values[-1]["event_ns"],
            first_receipt_ns=values[0]["receipt_ns"], last_receipt_ns=values[-1]["receipt_ns"],
            segments=1+max(row["segment_id"] for row in values), defects=bad,
            raw_sources=bind(day / "source_manifest.json"), parquet=bind(destination),
            original_source_index_sha256=hashlib.sha256(json.dumps(index, sort_keys=True).encode()).hexdigest(),
            seed=SEED, fits=0)
        save(day / f"{asset}.contract.json", contract)
        contracts.append(bind(day / f"{asset}.contract.json"))
    result = dict(date=date, seconds=time.monotonic()-started, peak_rss_bytes=peak_rss,
                  rows={a:len(v) for a,v in rows.items()}, contracts=contracts, defects=defects)
    save(day / "validation.json", result)
    stamp(f"Receipt export {date}: {result['rows']}, defects={len(defects)}, seconds={result['seconds']:.2f}")
    return result


def main():
    proc = pin()
    started = time.monotonic()
    DEST.mkdir(exist_ok=True)
    save(DEST / "protocol.json", dict(frozen_at=now(), dates=DATES, seed=SEED,
        source_only=True, outcomes_inspected=False, prefix_ns=PREFIX_NS,
        reason="Restore original receipt observation semantics from retained source bytes; prior event-clock panels unchanged",
        script=bind(__file__)))
    results = []
    for date in DATES:
        index = read(PRIOR / f"r3/sources/tardis_full_day/day_indexes/{date}.json")
        results.append(export_day(date, index, proc))
        save(DEST / "progress.json", dict(pid=proc.pid, started_at=now(), elapsed_seconds=time.monotonic()-started, completed=results))
    save(DEST / "manifest.json", dict(task="T-018", revision=1, completed_at=now(),
        elapsed_seconds=time.monotonic()-started, cpu_affinity=proc.cpu_affinity(),
        source_status="pending_independent_review", days=results, script=bind(__file__)))


if __name__ == "__main__":
    main()
