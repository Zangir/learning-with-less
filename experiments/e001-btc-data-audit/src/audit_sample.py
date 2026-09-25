"""Inspect real sample integrity and join feasibility before any model fitting."""
from pathlib import Path
from collections import Counter, defaultdict
import gzip
import hashlib
import importlib.util
import json
import time

import numpy as np

CODE = Path(__file__).resolve().parent
ROOT = CODE.parents[0] / "runtime"
DATA = ROOT / "data"
MAX_JSON_LINES = 200_000
SEED = 16029001
np.random.seed(SEED)


def main():
    started = time.monotonic()
    spec = importlib.util.spec_from_file_location("upstream_reader", CODE / "source_read_data.py")
    reader = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reader)
    with gzip.open(DATA / "btc_20251201_00.data.gz", "rb") as stream:
        raw = stream.read()
    assert len(raw) % 54 == 0
    records = np.frombuffer(raw, dtype=reader.RECORD_DTYPE)
    assert records.dtype.itemsize == 54
    print("status records", len(records), flush=True)
    result = dict(seed=SEED, scope="Acquisition/join audit; no forecast, fill probability, or economic claim", source_manifest_sha256=hashlib.sha256((ROOT / "sample_manifest.json").read_bytes()).hexdigest(), max_json_lines=MAX_JSON_LINES)
    ts = records["ts"]
    result["statuses"] = dict(records=len(records), dtype_bytes=records.dtype.itemsize,
        first_utc=str(np.datetime64(int(ts.min()), "ns")), last_utc=str(np.datetime64(int(ts.max()), "ns")),
        timestamp_decreases=int(np.sum(ts[1:] < ts[:-1])), tied_adjacent_timestamp=int(np.sum(ts[1:] == ts[:-1])),
        status_counts={str(int(k)):int(v) for k,v in zip(*np.unique(records["statusId"],return_counts=True))},
        user_count=int(len(np.unique(records["userId"]))), unique_orders=int(len(np.unique(records["oid"]))))
    for status in [1, 2, 5]:
        mask = records["statusId"] == status
        result["statuses"][f"status_{status}_size"] = dict(rows=int(mask.sum()), zero_size=int(np.sum(records["sz"][mask]==0)), equal_original=int(np.sum(records["sz"][mask]==records["origSz"][mask])))
    diffs = []
    keys = Counter()
    kind_counts = Counter()
    coins = Counter()
    with gzip.open(DATA / "book_diffs_20251201_00.gz", "rt") as stream:
        for i, line in enumerate(stream):
            if i >= MAX_JSON_LINES:
                break
            row = json.loads(line)
            keys.update(row.keys())
            coins[row.get("coin")] += 1
            if row.get("coin") == "BTC":
                delta = row["raw_book_diff"]
                kind = delta if isinstance(delta,str) else next(iter(delta))
                kind_counts[kind] += 1
                diffs.append(dict(oid=row["oid"],kind=kind,px=row["px"],side=row["side"],delta=delta))
    print("diff sample",len(diffs),dict(kind_counts),flush=True)
    order_ids = np.array(sorted({row["oid"] for row in diffs}), dtype=np.uint64)
    mask = np.isin(records["oid"],order_ids)
    status_by_oid = defaultdict(list)
    for row in records[mask]:
        status_by_oid[int(row["oid"])].append((int(row["statusId"]),int(row["ts"]),int(row["sz"]),int(row["origSz"])))
    candidate_time = []
    joins = Counter()
    first_seen = {}
    for diff in diffs:
        first_seen.setdefault(diff["oid"],diff["kind"])
        events = status_by_oid[diff["oid"]]
        wanted = [r for r in events if r[0]==1] if diff["kind"]=="new" else [r for r in events if r[0] in {2,5,7,10,11,12,13,14,16}] if diff["kind"]=="remove" else []
        joins[(diff["kind"], len(wanted))] += 1
        if len(wanted)==1:
            candidate_time.append(wanted[0][1])
    matched_ts=np.asarray(candidate_time,dtype=np.int64)
    result["book_diffs_prefix"] = dict(lines_inspected=sum(coins.values()), coins=dict(coins), keys=dict(keys),
        btc_rows=len(diffs), kinds=dict(kind_counts), unique_orders=len(order_ids),
        first_seen_kind_counts=dict(Counter(first_seen.values())),
        status_join_candidate_counts={f"{k[0]}/{k[1]}":v for k,v in joins.items()},
        candidate_time_count=len(candidate_time), candidate_time_decreases=int(np.sum(np.diff(matched_ts)<0)),
        candidate_first_utc=str(np.datetime64(int(matched_ts.min()),"ns")) if len(matched_ts) else None,
        candidate_last_utc=str(np.datetime64(int(matched_ts.max()),"ns")) if len(matched_ts) else None,
        join_is_not_certified_event_clock=True)
    trade_coins=Counter();trade_keys=Counter();btc_times=[];trade_orders=set()
    with gzip.open(DATA / "trades_20251201_00.gz", "rt") as stream:
        for i,line in enumerate(stream):
            if i>=MAX_JSON_LINES:
                break
            row=json.loads(line);trade_coins[row.get("coin")]+=1;trade_keys.update(row.keys())
            if row.get("coin")=="BTC":
                btc_times.append(row.get("time"))
                for side in row.get("side_info",[]):trade_orders.add(side.get("oid"))
    result["trades_prefix"] = dict(lines_inspected=sum(trade_coins.values()),btc_rows=trade_coins["BTC"],
        keys=dict(trade_keys),first_time=btc_times[0] if btc_times else None,last_time=btc_times[-1] if btc_times else None,
        unique_btc_orders=len(trade_orders), btc_order_overlap_diff_prefix=len(trade_orders & set(map(int,order_ids))))
    result["seconds"] = time.monotonic()-started
    (ROOT / "sample_audit.json").write_text(json.dumps(result,indent=2))
    print(json.dumps(result,indent=2),flush=True)


if __name__ == "__main__":
    main()
