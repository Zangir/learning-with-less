"""Normalize the frozen BBO source calendar as each acquired day completes."""
from settings import OUT, NS, SEED, bind, now, pin, read, save, sha, stamp, utc_ns
from acquire_bbo_panel import DATES, DEST
from export_receipt_quotes import integer8
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
import time
import pyarrow as pa
import pyarrow.parquet as pq


def project(data):
    bid, ask = data["bbo"]
    values = {}
    for name, level in (("bid", bid), ("ask", ask)):
        values[name+"_px_e8"] = integer8(level["px"])
        values[name+"_sz_e8"] = integer8(level["sz"])
        values[name+"_n"] = level["n"]
        if any(values[name+suffix] <= 0 for suffix in ("_px_e8", "_sz_e8", "_n")):
            raise ValueError("Nonpositive quote")
        if not isinstance(level["n"], int):
            raise ValueError("Noninteger order count")
    if values["bid_px_e8"] >= values["ask_px_e8"]:
        raise ValueError("Locked/crossed BBO")
    return values


def export_day(date, proc):
    start = time.monotonic()
    index_path = DEST / "day_indexes" / f"{date}.json"
    index = read(index_path)
    expected_protocol = bind(DEST / "protocol.json")["sha256"]
    assert index["protocol_sha256"] == expected_protocol
    assert [r["offset"] for r in index["records"]] == list(range(0,1440,10))
    day = DEST / "normalized" / date
    day.mkdir(parents=True, exist_ok=True)
    midnight = utc_ns(date+"T00:00:00Z")
    rows = {asset: [] for asset in ("BTC", "ETH")}
    counters = {asset: Counter() for asset in rows}
    previous = {}
    ordinal = 0
    segment = 0
    defects = []
    markers = []
    lineage = []
    peak = proc.memory_info().rss
    for record in index["records"]:
        assert record["complete"] and record["status"] == 200
        assert record["protocol_sha256"] == expected_protocol
        assert sha(record["raw"]["path"]) == record["raw"]["sha256"]
        decoded = hashlib.sha256()
        decoded_size = 0
        with gzip.open(record["raw"]["path"], "rb") as stream:
            for line_number, line in enumerate(stream):
                decoded.update(line)
                decoded_size += len(line)
                current = ordinal
                ordinal += 1
                if not line.strip():
                    markers.append(dict(source_ordinal=current, slice_offset_minutes=record["offset"], slice_line_ordinal=line_number))
                    segment += 1
                    previous = {}
                    continue
                receipt_text, message = line.decode().split(" ", 1)
                recv = utc_ns(receipt_text)
                assert midnight+record["offset"]*60*NS <= recv < midnight+(record["offset"]+10)*60*NS
                payload = json.loads(message)
                assert payload["channel"] == "bbo"
                data = payload["data"]
                asset = data["coin"]
                assert asset in rows
                counters[asset]["raw_rows"] += 1
                if recv < midnight+30*NS:
                    counters[asset]["receipt_prefix_excluded"] += 1
                    continue
                event = int(data["time"])*1_000_000
                try:
                    quote = project(data)
                except (ValueError, TypeError, KeyError) as error:
                    defects.append(dict(asset=asset, ordinal=current, kind="invalid_quote", detail=str(error)))
                    continue
                old = previous.get(asset)
                if old:
                    if event < old[0]:
                        defects.append(dict(asset=asset, ordinal=current, kind="event_inversion", backward_ns=old[0]-event))
                    if recv < old[1]:
                        defects.append(dict(asset=asset, ordinal=current, kind="receipt_inversion"))
                    if event == old[0]:
                        counters[asset]["event_ties"] += 1
                        if quote != old[2]:
                            counters[asset]["nonidentical_event_ties"] += 1
                    counters[asset]["maximum_event_silence_ns"] = max(counters[asset]["maximum_event_silence_ns"],event-old[0])
                    counters[asset]["maximum_receipt_silence_ns"] = max(counters[asset]["maximum_receipt_silence_ns"],recv-old[1])
                previous[asset] = (event, recv, quote)
                if not midnight+30*NS <= event < midnight+86400*NS:
                    counters[asset]["event_period_excluded"] += 1
                    continue
                row = dict(event_ns=event, receipt_ns=recv, source_ordinal=current, segment_id=segment,
                           slice_offset_minutes=record["offset"], slice_line_ordinal=line_number,
                           raw_line_sha256=hashlib.sha256(line).digest())
                row.update(quote)
                rows[asset].append(row)
        assert decoded.hexdigest() == record["decoded_sha256"]
        assert decoded_size == record["decoded_bytes"]
        lineage.append(dict(offset=record["offset"], raw=record["raw"], decoded_sha256=decoded.hexdigest(),
                            decoded_bytes=decoded_size, url=record["url"], headers=record["headers"]))
        peak = max(peak, proc.memory_info().rss)
        if peak > 7*1024**3:
            raise MemoryError("Leave assignment memory headroom for parallel acquisition")
    save(day / "source_manifest.json", lineage)
    save(day / "disconnects.json", markers)
    contracts = []
    for asset, values in rows.items():
        table = pa.Table.from_pylist(values)
        output = day / f"{asset}.parquet"
        pq.write_table(table, output, compression="zstd", row_group_size=65536)
        assert table.equals(pq.read_table(output))
        segments = []
        for row in values:
            if not segments or segments[-1]["segment_id"] != row["segment_id"]:
                segments.append(dict(segment_id=row["segment_id"], first_row=len(segments), rows=0,
                    first_event_ns=row["event_ns"], first_receipt_ns=row["receipt_ns"]))
            segments[-1]["rows"] += 1
            segments[-1]["last_event_ns"] = row["event_ns"]
            segments[-1]["last_receipt_ns"] = row["receipt_ns"]
        offset = 0
        for item in segments:
            item["first_row"] = offset
            offset += item["rows"]
        bad = [d for d in defects if d["asset"] == asset]
        contract = dict(schema="t018-native-bbo/1", asset=asset, date=date, seed=SEED,
            source="Tardis archive of Hyperliquid native bbo channel", depth=1, order_counts="Observed n on bid/ask",
            provider_receipt_provenance="Provider documents message-arrival localTimestamp; raw timestamp retained exactly; independent clock calibration unavailable",
            observation_clock="receipt_ns for features and grid", endpoint_clock="event_ns for labels and quote endpoints",
            grid="Consumer original 5s train and 11s evaluation; build separately per continuous segment; twenty-second history and ten-second +0/100/500ms endpoints",
            continuity="Native on-change BBO; absence of a change is not missing history. Split only on explicit disconnect. Never cross segments. Endpoint support bounded by last actual event and receipt.",
            timestamp_ties="Preserve source order, original right-asof chooses last source row at equal timestamp. No inferred interior exchange order within a millisecond.",
            prefix="Fixed first 30s of receipt day excluded, validate remaining before in-day event filtering",
            normalized_units="Exact decimal integer scale 1e8; ns timestamps; Hyperliquid linear base-asset sizes and USD quote prices",
            supported_estimand="Received L1 forecast/policy observations and exogenous historical quote outcomes, subject to provider collection and event-timestamp claims",
            unavailable_claims=["Every intra-block price change", "physical receipt-clock calibration", "actual order fills", "participant identity", "passive FIFO"],
            source_status="eligible_pending_independent_review" if not bad else "invalid",
            comparison_status="Not run here; source invalidity is not a scientific negative", rows=len(values),
            counters=dict(counters[asset]), defects=bad, segments=segments,
            parquet=bind(output), raw_manifest=bind(day / "source_manifest.json"),
            source_index=bind(index_path), protocol_sha256=expected_protocol)
        target = day / f"{asset}.contract.json"
        save(target, contract)
        contracts.append(bind(target))
    summary = dict(date=date, rows={a:len(v) for a,v in rows.items()}, seconds=time.monotonic()-start,
        peak_rss_bytes=peak, defects=defects, contracts=contracts, source_protocol_sha256=expected_protocol)
    save(day / "validation.json", summary)
    stamp(f"Native BBO export {date}: rows={summary['rows']}, defects={len(defects)}, {summary['seconds']:.2f}s")
    return summary


def main():
    proc = pin()
    start = time.monotonic()
    results = []
    for date in DATES:
        index = DEST / "day_indexes" / f"{date}.json"
        while not index.exists():
            if time.monotonic()-start > 3500:
                save(DEST / "normalization_checkpoint.json", dict(at=now(), next_date=date, complete=results, reason="One-hour job bound"))
                return
            time.sleep(30)
        validation = DEST / "normalized" / date / "validation.json"
        result = read(validation) if validation.exists() else export_day(date, proc)
        results.append(result)
        save(DEST / "normalization_progress.json", dict(at=now(), pid=proc.pid, elapsed_seconds=time.monotonic()-start, days=results))
    save(DEST / "normalized_manifest.json", dict(at=now(), days=results, elapsed_seconds=time.monotonic()-start,
        cpu_affinity=proc.cpu_affinity(), protocol=bind(DEST / "protocol.json"), source_status="Pending independent review"))


if __name__ == "__main__":
    main()
