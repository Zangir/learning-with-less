"""Receipt-clock Q18 cache, with an explicit reconstructed 30-slot view."""
import hashlib
import json
from pathlib import Path

import numpy as np

NS = 1_000_000_000


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1048576), b""):
            h.update(block)
    return h.hexdigest()


def load_receipt_contract(binding):
    """Verify a producer's exact source packet; review acceptance is separate."""
    import pyarrow.parquet as pq
    path = Path(binding["path"])
    if sha256(path) != binding["sha256"]:
        raise ValueError("Receipt contract hash mismatch")
    contract = json.loads(path.read_text(encoding="utf-8-sig"))
    if (contract["schema"] != "t018-dual-clock-l2/1" or contract["defects"]
            or contract["producer_source_status"] != "eligible_pending_independent_review"):
        raise ValueError("Invalid or unsupported producer source")
    for key in ("parquet", "raw_sources"):
        item = contract[key]
        if sha256(item["path"]) != item["sha256"]:
            raise ValueError(f"Receipt {key} binding mismatch")
    fields = ["event_ns", "receipt_ns", "source_ordinal", "segment_id"]
    fields += [f"{side}_{kind}_e8_{k}" for side in ("bid", "ask")
               for kind in ("px", "sz") for k in range(5)]
    table = pq.read_table(contract["parquet"]["path"], columns=fields)
    rows = {key: table[key].to_numpy() for key in fields}
    if len(rows["receipt_ns"]) != contract["rows"]:
        raise ValueError("Source row count mismatch")
    validate_rows(rows)
    return rows, contract


def validate_rows(rows):
    n = len(rows["receipt_ns"])
    if n < 2 or any(len(x) != n for x in rows.values()):
        raise ValueError("Aligned nonempty source arrays required")
    for key in ("event_ns", "receipt_ns", "segment_id", "source_ordinal"):
        x = rows[key]
        if x.dtype.kind not in "iu" or np.any(np.diff(x) < 0):
            raise ValueError(f"Source inversion: {key}; sorting is forbidden")
    if np.any(np.diff(rows["source_ordinal"]) == 0):
        raise ValueError("Duplicate source ordinal")
    for side in ("bid", "ask"):
        p = np.column_stack([rows[f"{side}_px_e8_{k}"] for k in range(5)])
        q = np.column_stack([rows[f"{side}_sz_e8_{k}"] for k in range(5)])
        if (p <= 0).any() or (q <= 0).any():
            raise ValueError("Nonpositive book")
        if not (np.diff(p, axis=1) * (1 if side == "ask" else -1) > 0).all():
            raise ValueError("Invalid depth ordering")
    if (rows["bid_px_e8_0"] >= rows["ask_px_e8_0"]).any():
        raise ValueError("Locked/crossed book")
    links = np.diff(rows["segment_id"]) == 0
    if any(np.any(links & (np.diff(rows[k]) > 2 * NS)) for k in ("receipt_ns", "event_ns")):
        raise ValueError("Undeclared source gap")


def build_q18_cache(rows, date, stride_seconds):
    """As-of received states and received ten-second labels on a fixed cache grid.

    Timing slots are seconds since the last own-prefix price/quantity change,
    capped at 20, and the number of those changes in (u-20s,u]. This is a
    documented reconstruction because the original views.py was not released.
    """
    validate_rows(rows)
    if stride_seconds not in (5, 11):
        raise ValueError("Original five/eleven-second cache grid required")
    clock, segment = rows["receipt_ns"], rows["segment_id"]
    day = int(np.datetime64(date, "ns").astype(np.int64))
    end = day + 86400 * NS
    if clock[0] < day or clock[-1] >= end:
        raise ValueError("Receipt observations cross date")
    anchor = (int(clock[0]) // NS + 21) * NS
    bid = np.column_stack([rows[f"bid_px_e8_{k}"] for k in range(5)]) / 1e8
    ask = np.column_stack([rows[f"ask_px_e8_{k}"] for k in range(5)]) / 1e8
    bq = np.column_stack([rows[f"bid_sz_e8_{k}"] for k in range(5)]) / 1e8
    aq = np.column_stack([rows[f"ask_sz_e8_{k}"] for k in range(5)]) / 1e8
    mid = (bid[:, 0] + ask[:, 0]) / 2
    chunks, exclusions = [], []
    boundaries = np.r_[0, np.flatnonzero(np.diff(segment)) + 1, len(clock)]
    for first, stop in zip(boundaries, boundaries[1:]):
        t = clock[first:stop]
        earliest = (int(t[0]) // NS + 21) * NS
        start = anchor + max(0, (earliest - anchor + stride_seconds * NS - 1)
                             // (stride_seconds * NS)) * stride_seconds * NS
        times = np.arange(start, min(int(t[-1]), end) - 11 * NS,
                          stride_seconds * NS, dtype=np.int64)
        if not len(times):
            exclusions.append({"segment": int(segment[first]), "reason": "short_history_target_support"})
            continue
        current = np.searchsorted(t, times, side="right") - 1 + first
        future = np.searchsorted(t, times + 10 * NS, side="right") - 1 + first
        lagged = [np.searchsorted(t, times - lag * NS, side="right") - 1 + first
                  for lag in (1, 5, 20)]
        if min(np.min(i) for i in [current, future, *lagged]) < first or np.any(future + 1 >= stop):
            raise ValueError("Incomplete within-segment observation support")
        part = dict(times=times, returns=10000 * (mid[future] / mid[current] - 1),
                    segment_id=np.full(len(times), segment[first]),
                    source_ordinal=rows["source_ordinal"][current],
                    observation_ns=clock[current], label_end_ns=clock[future],
                    outcome_available_ns=clock[future + 1])
        for depth in (1, 5):
            x = np.zeros((len(times), 30))
            features = np.stack((10000 * (bid[current, :depth] / mid[current, None] - 1),
                                 10000 * (ask[current, :depth] / mid[current, None] - 1),
                                 np.log1p(bq[current, :depth]), np.log1p(aq[current, :depth]),
                                 (bq[current, :depth] - aq[current, :depth]) /
                                 (bq[current, :depth] + aq[current, :depth])), axis=2)
            x[:, :5 * depth] = features.reshape(len(times), 5 * depth)
            for column, indices in enumerate(lagged, 25):
                x[:, column] = 10000 * (mid[current] / mid[indices] - 1)
            prefix = np.column_stack([v[first:stop, :depth] for v in (bid, ask, bq, aq)])
            changed = np.r_[False, np.any(prefix[1:] != prefix[:-1], axis=1)]
            changes = t[changed]
            left = np.searchsorted(changes, times - 20 * NS, side="right")
            right = np.searchsorted(changes, times, side="right")
            x[:, 28] = 20
            exists = right > left
            x[exists, 28] = (times[exists] - changes[right[exists] - 1]) / NS
            x[:, 29] = right - left
            part[f"d{depth}_own"] = x
        chunks.append(part)
    if not chunks:
        raise ValueError("No eligible Q18 cache rows")
    cache = {key: np.concatenate([part[key] for part in chunks]) for key in chunks[0]}
    if not np.isfinite(np.column_stack([cache["returns"], cache["d5_own"]])).all():
        raise ValueError("Nonfinite Q18 cache")
    return cache, {"date": date, "stride_seconds": stride_seconds, "anchor_ns": anchor,
                   "rows": len(cache["times"]), "excluded_segments": exclusions,
                   "observation_clock": "provider_receipt", "label_clock": "provider_receipt",
                   "representation": "reconstructed-receipt-prefix-v2", "source_review": "pending"}


def shifted_views(cache):
    """Exact cache matching: every retained view uses the same fixed target."""
    times = cache["times"]
    prior = np.searchsorted(times, times - 55 * NS, side="right") - 1
    safe = np.maximum(prior, 0)
    keep = np.flatnonzero((prior >= 0) & (times[safe] == times - 55 * NS)
                         & (cache["segment_id"][safe] == cache["segment_id"]))
    views = {}
    for delay in (0, 55):
        indices = keep if delay == 0 else prior[keep]
        for depth in (1, 5):
            for history in ("instant", "20sec"):
                x = cache[f"d{depth}_own"][indices].copy()
                if history == "instant":
                    x[:, 25:] = 0
                views[f"d{depth}/{history}/delay{delay}"] = x
    if not len(keep):
        raise ValueError("No exact within-segment delayed cache matches")
    return views, cache["returns"][keep], keep
