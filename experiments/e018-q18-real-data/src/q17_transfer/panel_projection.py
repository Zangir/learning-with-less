"""Frozen paired-period projection; sampled source cuts remain explicit."""
import numpy as np
from .features import NS, DAY, build_arrays
from .protocol import PROTOCOL

OFFSETS_NS = np.array([-20*NS, -5*NS, -NS, 0, 100_000_000, 500_000_000,
                       10*NS, 10_100_000_000, 10_500_000_000], dtype=np.int64)


def distribution(values):
    values = np.asarray(values)
    return dict(n=int(values.size), minimum=float(values.min()), median=float(np.median(values)),
                p95=float(np.quantile(values, .95)), maximum=float(values.max()))


def project_day(loaded, asset, date, split, period):
    """Project one asset/date, retaining the same grid across disconnected segments.

    The provider contract is validated upstream. Equal-clock model availability
    here is a declared counterfactual information set, never a measured release.
    """
    if period not in {"hour00", "full_day"} or split not in {"train", "validation", "test"}:
        raise ValueError("Unknown declared period or date role")
    day = int(np.datetime64(date, "ns").astype(np.int64))
    end = day + (3600*NS if period == "hour00" else DAY)
    windows = sorted([w for w in loaded["windows"] if w["asset"] == asset and w["scope"] == "Q17"],
                     key=lambda w: w["start_ns"])
    if not windows or any(w["start_ns"] < day or w["end_ns"] > end for w in windows):
        raise ValueError("Producer windows outside fixed date/period")
    if any(a["end_ns"] > b["start_ns"] for a, b in zip(windows, windows[1:])):
        raise ValueError("Overlapping windows duplicate observations")
    anchor = (windows[0]["start_ns"]//NS+21)*NS
    stride = PROTOCOL["train_stride_seconds" if split == "train" else "evaluation_stride_seconds"]*NS
    segment_by_ordinal = {}
    for certified in loaded["segments"]:
        for row in loaded["rows"][certified["first_row_index"]:certified["stop_row_index"]]:
            ordinal = row["source_ordinal"]
            if ordinal in segment_by_ordinal:
                raise ValueError("Overlapping declared source segments")
            segment_by_ordinal[ordinal] = certified["segment_id"]
    chunks, exclusions, segment = [], [], 0
    for window in windows:
        rows = [r for r in loaded["rows"] if r["asset"] == asset and r["source_id"] in window["source_ids"]
                and window["first_source_ordinal"] <= r["source_ordinal"] <= window["last_source_ordinal"]
                and window["start_ns"] <= r["event_ns"] < window["end_ns"]]
        if len({r["source_id"] for r in rows}) > 1:
            raise ValueError("One source identity per window required")
        boundaries = [0]+[i for i in range(1, len(rows)) if rows[i]["event_ns"]-rows[i-1]["event_ns"] > 2*NS
            or segment_by_ordinal[rows[i]["source_ordinal"]] != segment_by_ordinal[rows[i-1]["source_ordinal"]]]+[len(rows)]
        for a, b in zip(boundaries, boundaries[1:]):
            part = rows[a:b]
            segment += 1
            if len(part) < 2:
                exclusions.append(dict(segment=segment, reason="fewer_than_two_source_states", rows=len(part)))
                continue
            event = np.array([r["event_ns"] for r in part], dtype=np.int64)
            quotes = dict(event_ns=event, available_ns=event.copy(), known_ns=event.copy(),
                **{field: np.array([r[side+"_"+column][0]/1e8 for r in part]) for field, side, column in (
                    ("bid", "bid", "prices_units8"), ("ask", "ask", "prices_units8"),
                    ("bid_size", "bid", "sizes_units8"), ("ask_size", "ask", "sizes_units8"))})
            try:
                built = build_arrays(quotes, split, window["start_ns"], window["end_ns"],
                                     grid_anchor_ns=anchor, apply_training_cap=False)
            except ValueError as error:
                if "Insufficient" not in str(error):
                    raise
                exclusions.append(dict(segment=segment, reason="insufficient_history_or_forward_support", rows=len(part)))
                continue
            keep = built["max_input_age_ns"] <= 1_500_000_000
            exclusions.append(dict(segment=segment, reason="stale_cut", rows=int((~keep).sum())))
            built = {k: v[keep] for k, v in built.items()}
            if not len(built["times"]):
                continue
            sums = [r["bid_prices_units8"][0]+r["ask_prices_units8"][0] for r in part]
            built["y"] = np.array([(sums[j] > sums[i])-(sums[j] < sums[i])+1
                                   for i, j in built["label_indices"]], dtype=np.int8)
            ordinals = np.array([r["source_ordinal"] for r in part], dtype=np.int64)
            for stem in ("feature", "label", "entry", "exit"):
                built[stem+"_source_ordinals"] = ordinals[built[stem+"_indices"]]
            cuts = built["times"][:, None]+OFFSETS_NS
            indices = np.searchsorted(event, cuts, side="right")-1
            built["selected_event_ns"] = event[indices]
            built["selected_source_ordinals"] = ordinals[indices]
            built["source_age_ns"] = cuts-event[indices]
            if (built["source_age_ns"] < 0).any() or (built["source_age_ns"] > 1_500_000_000).any():
                raise ValueError("Cut-level age verification disagrees with common mask")
            receipts = [r.get("provider_receive_ns", r.get("local_receive_ns")) for r in part]
            if all(type(t) is int for t in receipts):
                built["provider_receive_ns"] = np.array(receipts, dtype=np.int64)[indices]
            built["segment_id"] = np.full(len(cuts), segment, dtype=np.int64)
            built["source_id"] = np.full(len(cuts), part[0]["source_id"])
            built["date"] = np.full(len(cuts), date)
            built["window_id"] = np.full(len(cuts), window["window_id"])
            chunks.append(built)
    if not chunks:
        raise ValueError(f"Unavailable {asset}/{date}: no eligible decisions")
    joined = {k: np.concatenate([c[k] for c in chunks]) for k in chunks[0]}
    if not (np.diff(joined["times"]) > 0).all():
        raise ValueError("Duplicate or inverted decisions")
    before_cap = len(joined["times"])
    if split == "train" and before_cap > PROTOCOL["training_cap_per_day"]:
        sample = np.linspace(0, before_cap-1, PROTOCOL["training_cap_per_day"], dtype=int)
        joined = {k: v[sample] for k, v in joined.items()}
    if split != "train":
        breaks = np.r_[0, np.flatnonzero((np.diff(joined["times"]) != stride)
            | (np.diff(joined["segment_id"]) != 0))+1, len(joined["times"])]
        groups = [np.arange(a, a+(b-a)//12*12).reshape(-1, 12) for a, b in zip(breaks, breaks[1:])]
        joined["schedule_rows"] = np.concatenate(groups, axis=0)
        if not len(joined["schedule_rows"]):
            raise ValueError(f"Unavailable {asset}/{date}: no complete disjoint schedule")
    ages, selected = joined["source_age_ns"], joined["selected_event_ns"]
    diagnostics = dict(asset=asset, date=date, role=split, period=period, grid_anchor_ns=anchor,
        source_rows=sum(1 for r in loaded["rows"] if r["asset"] == asset), segments=segment,
        opportunities_before_training_cap=before_cap, opportunities=len(ages),
        label_counts={str(k): int((joined["y"] == k).sum()) for k in range(3)},
        scheduling_windows=len(joined.get("schedule_rows", [])), exclusions=exclusions,
        source_age_by_offset_ns={str(offset): distribution(ages[:, j]) for j, offset in enumerate(OFFSETS_NS)},
        actual_label_endpoint_interval_ns=distribution(selected[:, 6]-selected[:, 3]),
        observation_shifts={str(delay): dict(entry_same_event_fraction=float(np.mean(selected[:, j] == selected[:, 3])),
            exit_same_event_fraction=float(np.mean(selected[:, j+3] == selected[:, 6])),
            entry_event_shift_ns=distribution(selected[:, j]-selected[:, 3]),
            exit_event_shift_ns=distribution(selected[:, j+3]-selected[:, 6]))
            for j, delay in ((4, 100), (5, 500))},
        repeated_current_event_fraction=float(np.mean(np.diff(selected[:, 3]) == 0)) if len(ages)>1 else 0,
        actual_release_or_admission_claim=False, retrospective_future_coverage_mask=True)
    if "provider_receive_ns" in joined:
        diagnostics["uncalibrated_provider_receive_minus_event_ns"] = distribution(joined["provider_receive_ns"]-selected)
    return joined, diagnostics


def concatenate_days(days):
    """Concatenate fixed dates, offsetting schedules without bridging midnight."""
    if not days:
        raise ValueError("No declared dates")
    joined = {k: np.concatenate([day[k] for day in days]) for k in days[0] if k != "schedule_rows"}
    if not (np.diff(joined["times"]) > 0).all():
        raise ValueError("Date order must remain strictly chronological")
    if "schedule_rows" in days[0]:
        offsets = np.cumsum([0]+[len(day["times"]) for day in days[:-1]])
        joined["schedule_rows"] = np.concatenate([day["schedule_rows"]+offset for day, offset in zip(days, offsets)])
    return joined
