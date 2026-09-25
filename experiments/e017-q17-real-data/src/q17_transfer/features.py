"""As-of features with separate availability and event clocks, in nanoseconds."""
import numpy as np
from .protocol import PROTOCOL

NS = 1_000_000_000
DAY = 86400 * NS


def build_arrays(quotes, split, block_start_ns, block_end_ns, grid_anchor_ns=None, max_age_ns=None, apply_training_cap=True):
    """Consume one certified continuous interval, preserving its supplied order.

    known_ns is the latest evidence availability used to admit each BBO state.
    All rows must be atomic final states, certified before available_ns. This
    function checks mechanics; independent certificates establish their truth.
    Block end is exclusive. No historical timestamp repair is performed here.
    """
    if split not in {"train", "validation", "test"}:
        raise ValueError("Unknown split")
    keys = ("event_ns", "available_ns", "known_ns", "bid", "ask", "bid_size", "ask_size")
    q = {k: np.asarray(quotes[k]) for k in keys}
    lengths = {len(v) for v in q.values()}
    if len(lengths) != 1 or min(lengths) < 2 or any(v.ndim != 1 for v in q.values()):
        raise ValueError("Aligned nonempty one-dimensional quote columns required")
    event, available, known = (q[k] for k in keys[:3])
    if any(v.dtype.kind not in "iu" for v in (event, available, known)):
        raise ValueError("Integer nanosecond timestamps required")
    if any(np.any(v[1:] < v[:-1]) for v in (event, available)):
        raise ValueError("Timestamp inversion; do not sort anomalies away")
    if np.any(known > available) or np.any(event > available):
        raise ValueError("Availability cannot precede event or admission evidence")
    bid, ask, bs, az = (q[k].astype(float) for k in keys[3:])
    if not np.isfinite(np.c_[bid, ask, bs, az]).all() or not (
        (bid > 0).all() and (ask > bid).all() and (bs > 0).all() and (az > 0).all()
    ):
        raise ValueError("Invalid, missing, locked or crossed BBO")
    if block_end_ns <= block_start_ns or block_start_ns // DAY != (block_end_ns - 1) // DAY:
        raise ValueError("Block must stay within one UTC date")
    step = PROTOCOL["train_stride_seconds" if split == "train" else "evaluation_stride_seconds"]
    first = int(np.searchsorted(event, block_start_ns, side="left"))
    if first == len(event):
        raise ValueError("No events in declared block")
    start = (max(int(event[first]), int(available[first]), block_start_ns) // NS + 21) * NS
    if grid_anchor_ns is not None:
        start = grid_anchor_ns + max(0, (start-grid_anchor_ns+step*NS-1)//(step*NS))*step*NS
    stop = min(int(event[-1]), int(available[-1]), block_end_ns) - 11 * NS
    times = np.arange(start, stop, step * NS, dtype=np.int64)
    if apply_training_cap and split == "train" and len(times) > PROTOCOL["training_cap_per_day"]:
        times = times[np.linspace(0, len(times)-1, PROTOCOL["training_cap_per_day"], dtype=int)]
    if not len(times):
        raise ValueError("Insufficient certified interval coverage")

    def asof(clock, cutoffs):
        index = np.searchsorted(clock, cutoffs, side="right") - 1
        if (index < 0).any() or (clock[index] > cutoffs).any():
            raise ValueError("Unavailable as-of quote")
        return index

    i = asof(available, times)
    mid = (bid + ask) / 2
    x = [(bs[i]-az[i])/(bs[i]+az[i]), (ask[i]-bid[i])/mid[i]*10000]
    feature_indices = [i]
    for lookback in PROTOCOL["lookbacks_seconds"]:
        lag = asof(available, times-lookback*NS)
        feature_indices.append(lag)
        x.append((mid[i]/mid[lag]-1)*10000)
    present, future = asof(event, times), asof(event, times+10*NS)
    entry = np.column_stack([asof(event, times+ms*1_000_000) for ms in PROTOCOL["scenario_delays_ms"]])
    exit_ = np.column_stack([asof(event, times+10*NS+ms*1_000_000) for ms in PROTOCOL["scenario_delays_ms"]])
    used = np.concatenate([v.ravel() for v in [*feature_indices, present, future, entry, exit_]])
    # Boundary guards keep yesterday's dragons out of today's split.
    if (event[used] < block_start_ns).any() or (event[used] >= block_end_ns).any():
        raise ValueError("Lookback/target quote crosses the declared block boundary")
    # The next event supplies a conservative watermark for completed outcomes.
    # Seeing an old quote alone cannot prove that nothing changed before cutoff.
    watermark = asof(event, times+10*NS+500_000_000)+1
    if (watermark >= len(event)).any():
        raise ValueError("Outcome completeness watermark unavailable")
    ages = [times-event[i], times-event[present], times+10*NS-event[future]]
    ages.extend(times-lag*NS-event[index] for lag, index in zip(PROTOCOL["lookbacks_seconds"], feature_indices[1:]))
    ages.extend(times+ms*1_000_000-event[entry[:, j]] for j, ms in enumerate(PROTOCOL["scenario_delays_ms"]))
    ages.extend(times+10*NS+ms*1_000_000-event[exit_[:, j]] for j, ms in enumerate(PROTOCOL["scenario_delays_ms"]))
    max_age = np.max(np.column_stack(ages), axis=1)
    result = dict(times=times, X=np.column_stack(x), y=(np.sign(mid[future]-mid[present])+1).astype(np.int8),
                outcome_available_ns=available[watermark],
                feature_indices=np.column_stack(feature_indices), label_indices=np.c_[present, future],
                entry_indices=entry, exit_indices=exit_, max_input_age_ns=max_age,
                entry_bid=bid[entry], entry_ask=ask[entry], exit_bid=bid[exit_], exit_ask=ask[exit_])
    if max_age_ns is not None:
        keep = max_age <= max_age_ns
        if not keep.any():
            raise ValueError("Insufficient fresh feature/target support")
        result = {key: value[keep] for key, value in result.items()}
    return result
