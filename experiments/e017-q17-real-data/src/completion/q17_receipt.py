"""Native on-change BBO projection for the separately frozen Q17 calendar."""
import hashlib
import json
from pathlib import Path

import numpy as np

from q17_transfer.features import NS, build_arrays
from .receipt_features import sha256


def load_native_contract(binding, provider_protocol_sha256):
    import pyarrow.parquet as pq
    if sha256(binding["path"]) != binding["sha256"]:
        raise ValueError("Native BBO contract hash mismatch")
    contract = json.loads(Path(binding["path"]).read_text())
    if (contract["schema"] != "t018-native-bbo/1" or contract["defects"]
            or contract["source_status"] != "eligible_pending_independent_review"
            or contract["protocol_sha256"] != provider_protocol_sha256):
        raise ValueError("Native BBO source not eligible under frozen protocol")
    for key in ("parquet", "raw_manifest", "source_index"):
        if sha256(contract[key]["path"]) != contract[key]["sha256"]:
            raise ValueError(f"Native source binding mismatch: {key}")
    columns = ["event_ns", "receipt_ns", "source_ordinal", "segment_id",
               "bid_px_e8", "ask_px_e8", "bid_sz_e8", "ask_sz_e8"]
    table = pq.read_table(contract["parquet"]["path"], columns=columns)
    rows = {key: table[key].to_numpy() for key in columns}
    if len(rows["event_ns"]) != contract["rows"]:
        raise ValueError("Native source row count mismatch")
    return rows, contract


def project_native(rows, date, split):
    """No silence filter: unchanged on-change BBO is still the current quote."""
    day = int(np.datetime64(date, "ns").astype(np.int64))
    end = day + 86400 * NS
    segment = rows["segment_id"]
    if any(len(v) != len(segment) for v in rows.values()) or len(segment) < 2:
        raise ValueError("Aligned native source arrays required")
    if np.any(np.diff(segment) < 0) or np.any(np.diff(rows["source_ordinal"]) <= 0):
        raise ValueError("Native source order violation")
    if any(np.any((rows[k] < day) | (rows[k] >= end)) for k in ("event_ns", "receipt_ns")):
        raise ValueError("Native source crosses UTC date")
    stride = (5 if split == "train" else 11) * NS
    anchor = (max(int(rows["event_ns"][0]), int(rows["receipt_ns"][0])) // NS + 21) * NS
    boundaries = np.r_[0, np.flatnonzero(np.diff(segment)) + 1, len(segment)]
    chunks, exclusions = [], []
    for first, stop in zip(boundaries, boundaries[1:]):
        if stop - first < 2:
            exclusions.append(dict(segment_id=int(segment[first]), reason="fewer_than_two_quotes"))
            continue
        q = dict(event_ns=rows["event_ns"][first:stop], available_ns=rows["receipt_ns"][first:stop],
                 known_ns=rows["receipt_ns"][first:stop],
                 bid=rows["bid_px_e8"][first:stop] / 1e8, ask=rows["ask_px_e8"][first:stop] / 1e8,
                 bid_size=rows["bid_sz_e8"][first:stop] / 1e8, ask_size=rows["ask_sz_e8"][first:stop] / 1e8)
        try:
            built = build_arrays(q, split, day, end, grid_anchor_ns=anchor, apply_training_cap=False)
        except ValueError as error:
            if str(error) != "Insufficient certified interval coverage":
                raise
            exclusions.append(dict(segment_id=int(segment[first]), reason="short_history_target_support"))
            continue
        sums = rows["bid_px_e8"][first:stop] + rows["ask_px_e8"][first:stop]
        a, b = built["label_indices"].T
        built["y"] = ((sums[b] > sums[a]).astype(np.int8) - (sums[b] < sums[a]).astype(np.int8) + 1)
        for stem in ("feature", "label", "entry", "exit"):
            indices = built[stem + "_indices"]
            built[stem + "_source_ordinals"] = rows["source_ordinal"][first:stop][indices]
            built[stem + "_event_ns"] = q["event_ns"][indices]
            built[stem + "_receipt_ns"] = q["available_ns"][indices]
        built["segment_id"] = np.full(len(a), segment[first])
        built["date"] = np.full(len(a), date)
        chunks.append(built)
    if not chunks:
        raise ValueError("No eligible native Q17 decisions")
    joined = {key: np.concatenate([part[key] for part in chunks]) for key in chunks[0]}
    if np.any(np.diff(joined["times"]) <= 0):
        raise ValueError("Decision inversion or overlap across segments")
    before = len(joined["times"])
    if split == "train" and before > 6000:
        ix = np.linspace(0, before - 1, 6000, dtype=int)
        joined = {key: value[ix] for key, value in joined.items()}
    if split != "train":
        breaks = np.r_[0, np.flatnonzero((np.diff(joined["times"]) != stride)
                         | (np.diff(joined["segment_id"]) != 0)) + 1, len(joined["times"])]
        joined["schedule_rows"] = np.concatenate([np.arange(a, a + (b - a) // 12 * 12).reshape(-1, 12)
                                                   for a, b in zip(breaks, breaks[1:])])
        if not len(joined["schedule_rows"]):
            raise ValueError("No complete disjoint Q17 schedule")
    diagnostic = dict(date=date, split=split, before_cap=before, rows=len(joined["times"]),
                      schedules=len(joined.get("schedule_rows", [])), excluded_segments=exclusions,
                      anchor_ns=anchor, retrospective_support_mask=True, source_review="pending",
                      observation_clock="provider_receipt", label_clock="exchange_event",
                      label_counts={str(c): int((joined["y"] == c).sum()) for c in range(3)},
                      primary_entry_same_event_fraction=float(np.mean(joined["entry_event_ns"][:, 0]
                                                                   == joined["entry_event_ns"][:, 1])))
    return joined, diagnostic


def control_probabilities(day, model, seed, asset, date):
    if model == "oracle":
        return np.eye(3)[day["y"]]
    if model != "random" or seed not in (17, 29, 41):
        raise ValueError("Unknown original control")
    token = f"{seed}/{asset}/{date}".encode()
    rng = np.random.default_rng(int.from_bytes(hashlib.sha256(token).digest()[:8], "big"))
    return rng.dirichlet(np.ones(3), size=len(day["y"]))
