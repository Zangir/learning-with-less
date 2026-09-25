"""Conservative candidate-time coverage on the frozen T-001 prefix, not book replay."""
from pathlib import Path
from collections import Counter, defaultdict
from decimal import Decimal
import gzip
import hashlib
import importlib.util
import json
import sys
import time
import numpy as np

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1] / "runtime"
INPUT = ROOT / "input" / "T-001"
MAX_DIFF_LINES = 200_000
SEED = 16029001
np.random.seed(SEED)
TERMINAL = {2,4,5,7,10,11,12,13,14,16}


def units(text):
    value = Decimal(text) * 100_000_000
    if value != value.to_integral_value():
        raise ValueError("Source size exceeds exact eight-decimal lattice")
    return int(value)


def bounds(values):
    return (min(values), max(values)) if values else None


def update_candidate(times, ordinal, book_count):
    """Ordinal matching only when complete observed multiplicities agree."""
    if not times:
        return None, "missing_exact_size_trade"
    ordered = sorted(times)
    if len(ordered) == book_count:
        return (ordered[ordinal], ordered[ordinal]), "equal_multiplicity_trade_ordinal"
    return bounds(ordered), "exact_size_trade_interval"


def main():
    start = time.monotonic()
    rows = []
    with gzip.open(INPUT / "data/book_diffs_20251201_00.gz", "rt") as stream:
        for raw_index, line in enumerate(stream):
            if raw_index >= MAX_DIFF_LINES:
                break
            record = json.loads(line)
            if record["coin"] != "BTC":
                continue
            delta=record["raw_book_diff"]
            kind=delta if isinstance(delta,str) else next(iter(delta))
            fill=units(delta["update"]["origSz"])-units(delta["update"]["newSz"]) if kind=="update" else None
            if kind=="update" and fill<=0:
                raise ValueError("Nonpositive update reduction requires separate semantics")
            rows.append((raw_index,int(record["oid"]),kind,fill))
    needed = {r[1] for r in rows}
    spec=importlib.util.spec_from_file_location("frozen_reader", INPUT / "source_read_data.py")
    reader=importlib.util.module_from_spec(spec);spec.loader.exec_module(reader)
    with gzip.open(INPUT / "data/btc_20251201_00.data.gz", "rb") as stream:
        raw=stream.read()
    records=np.frombuffer(raw,dtype=reader.RECORD_DTYPE)
    selected=records[np.isin(records["oid"],np.array(sorted(needed),dtype=np.uint64))]
    status=defaultdict(list)
    for r in selected:
        status[int(r["oid"])].append((int(r["statusId"]),int(r["ts"]),(int(r["sz"]) & 0x1FFFFFFF)==0))
    del records, selected, raw
    trades=defaultdict(list);trade_lines=0;btc_trades=0
    with gzip.open(INPUT / "data/trades_20251201_00.gz", "rt") as stream:
        for line in stream:
            trade_lines+=1
            record=json.loads(line)
            if record["coin"]!="BTC":
                continue
            btc_trades+=1
            relevant=[int(side["oid"]) for side in record["side_info"] if int(side["oid"]) in needed]
            if not relevant:
                continue
            stamp=int(np.datetime64(record["time"],"ns").astype(np.int64))
            qty=units(record["sz"])
            for oid in relevant:
                trades[(oid,qty)].append(stamp)
    print("inputs",len(rows),trade_lines,btc_trades,flush=True)
    book_counts=Counter((oid,fill) for _,oid,kind,fill in rows if kind=="update")
    ordinals=Counter();sources=Counter();by_kind=defaultdict(Counter)
    candidates=[];summary_rows=[]
    for raw_index,oid,kind,fill in rows:
        events=status[oid]
        if kind=="new":
            candidate=bounds([t for sid,t,_ in events if sid==1]);source="open_status"
        elif kind=="remove":
            zero=[t for sid,t,iszero in events if sid!=1 and iszero]
            terminal=[t for sid,t,_ in events if sid in TERMINAL]
            candidate=bounds(zero or terminal);source="zero_size_status" if zero else "terminal_status"
        else:
            key=(oid,fill)
            candidate,source=update_candidate(trades[key],ordinals[key],book_counts[key]);ordinals[key]+=1
        candidates.append(candidate);sources[source]+=1
        by_kind[kind]["rows"]+=1
        if candidate is not None:
            by_kind[kind]["bounded"]+=1
            if candidate[0]==candidate[1]:by_kind[kind]["point_candidate"]+=1
            if candidate[1]-candidate[0]<=100_000_000:by_kind[kind]["width_at_most_100ms"]+=1
        summary_rows.append((raw_index,kind,source,candidate))
    anchored=[(i,c[0]) for i,c in enumerate(candidates) if c is not None and c[0]==c[1]]
    reversals=[]
    for (prev_i,prev_t),(curr_i,curr_t) in zip(anchored,anchored[1:]):
        if curr_t<prev_t:
            reversals.append(dict(previous_raw_line=rows[prev_i][0],current_raw_line=rows[curr_i][0],
                                  previous_kind=rows[prev_i][2],current_kind=rows[curr_i][2],
                                  backward_ns=prev_t-curr_t,
                                  previous_utc=str(np.datetime64(prev_t,"ns")),current_utc=str(np.datetime64(curr_t,"ns"))))
    previous=json.loads((INPUT / "sample_audit.json").read_text())["book_diffs_prefix"]
    assert len(rows)==previous["btc_rows"]
    assert [r[0] for r in rows]==sorted(r[0] for r in rows)
    total_point=sum(v["point_candidate"] for v in by_kind.values())
    out=dict(task="T-006",seed=SEED,scope="Candidate-time coverage diagnostic on first 200000 original interleaved diff lines; no replay, model, or historical receipt-time certification",
        inspiration_repository="https://github.com/daojingzhai/public-trader-identity",inspiration_commit="7fd7616b8a3af5193ff9efe9d5b27e4bae7c3135",
        implementation_changes=["Exact decimal size lattice replaces float32 matching","Same frozen BTC prefix, full acquired hour trades/statuses only; adjacent hours unavailable","No broad unmatched-size trade fallback","No removal/demotion/sorting of inconsistent diff events","No cleaned clock or synthetic block labels"],
        input_manifest_sha256=hashlib.sha256((INPUT/"sample_manifest.json").read_bytes()).hexdigest(),
        original_diff_lines=MAX_DIFF_LINES,btc_diff_rows=len(rows),trade_lines=trade_lines,btc_trade_rows=btc_trades,
        by_kind={k:dict(v) for k,v in by_kind.items()},sources=dict(sources),
        point_candidate_rows=total_point,point_candidate_rate=total_point/len(rows),
        naive_point_candidate_rows=previous["candidate_time_count"],
        naive_point_candidate_rate=previous["candidate_time_count"]/len(rows),
        additional_point_candidates=total_point-previous["candidate_time_count"],
        remaining_clock_reversals=reversals,raw_diff_order_preserved=True,
        initial_state_verified=False,event_clock_certified=False,receipt_clock_available=False,
        limitations=["Point candidate is a matching result, not independent timestamp ground truth","Equal-size multiplicity/ordinal join assumes stream correspondence; no adjacent-hour evidence","No full snapshot or within-block atomic order certification","Full-hour retrospective matching cannot establish live data availability"],
        seconds=time.monotonic()-start)
    (ROOT/"clock_coverage.json").write_text(json.dumps(out,indent=2))
    print(json.dumps(out,indent=2),flush=True)


if __name__=="__main__":
    main()
