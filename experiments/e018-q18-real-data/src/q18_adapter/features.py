"""Rebuilt Q18 representation v1; an adaptation, not the absent source builder."""
from dataclasses import dataclass
from itertools import product

import numpy as np

SECOND = 1_000_000_000
LOOKBACK = 75
HORIZON = 10
FORWARD_GUARD_NS = 10_500_000_000  # Legacy common padding, not a longer target.
VIEWS = tuple(product((0, 55), (1, 5), ("instant", "20sec")))


@dataclass(frozen=True)
class Split:
    name: str
    start_ns: int
    end_ns: int  # Exclusive, including the target endpoint.


def validate_grid(grid):
    """Validate an already certified one-second book grid without repairing it."""
    times = np.asarray(grid["times_ns"])
    if times.dtype != np.int64 or times.ndim != 1 or not 86 <= len(times) <= 86400:
        raise ValueError("Expected 86..86400 int64 nanosecond grid rows (at most one UTC day)")
    if np.any(np.diff(times) <= 0):
        raise ValueError("Grid order violation; sorting is forbidden")
    for key in ("bid_px", "ask_px", "bid_qty", "ask_qty"):
        values = np.asarray(grid[key])
        if values.shape != (len(times), 5) or not np.isfinite(values).all():
            raise ValueError(f"Invalid five-level array: {key}")
        if np.any(values <= 0):
            raise ValueError(f"Nonpositive occupied level: {key}")
    if np.any(np.diff(grid["bid_px"], axis=1) >= 0):
        raise ValueError("Bids must be strictly decreasing")
    if np.any(np.diff(grid["ask_px"], axis=1) <= 0):
        raise ValueError("Asks must be strictly increasing")
    if np.any(grid["bid_px"][:, 0] >= grid["ask_px"][:, 0]):
        raise ValueError("Locked/crossed book")
    clock_scope = str(grid.get("clock_scope", "observed_receive_time"))
    if clock_scope not in ("exchange_time", "observed_receive_time"):
        raise ValueError("Unsupported observation clock")
    flags = ["top5_complete", "atomic_complete"]
    columns = ["segment_id"]
    if clock_scope == "exchange_time":
        flags += ["past_only_selection"]
        columns += ["source_event_ns", "source_ordinal"]
    else:
        flags += ["clock_causal"]
        columns += ["release_ns", "certificate_known_ns"]
    for key in flags:
        if np.asarray(grid[key]).shape != times.shape or grid[key].dtype != np.bool_:
            raise ValueError(f"Boolean certification mask required: {key}")
    for key in columns:
        if np.asarray(grid[key]).shape != times.shape or grid[key].dtype != np.int64:
            raise ValueError(f"int64 provenance column required: {key}")
    return times


def eligible_indices(grid, split, forward_guard_ns=FORWARD_GUARD_NS):
    """Require every second in [g-75,g+10] inside one certified segment/split."""
    times = validate_grid(grid)
    if forward_guard_ns not in (10_000_000_000, FORWARD_GUARD_NS):
        raise ValueError("Only versioned ten-second or legacy ten-and-a-half-second guard")
    valid = grid["top5_complete"] & grid["atomic_complete"]
    if str(grid.get("clock_scope", "observed_receive_time")) == "exchange_time":
        valid &= grid["past_only_selection"] & (grid["source_event_ns"] <= times)
    else:
        valid &= (grid["clock_causal"] & (grid["release_ns"] <= times)
                  & (grid["certificate_known_ns"] <= times))
    bad = np.r_[0, np.cumsum(~valid)]
    # A single broken link spoils the window: no time travel by interpolation.
    broken = ((np.diff(times) != SECOND)
              | (np.diff(grid["segment_id"]) != 0))
    links = np.r_[0, np.cumsum(broken)]
    g = np.arange(LOOKBACK, len(times) - HORIZON)
    lo, hi = g - LOOKBACK, g + HORIZON
    keep = ((bad[hi + 1] == bad[lo]) & (links[hi] == links[lo])
            & (times[lo] >= split.start_ns) & (times[g] + forward_guard_ns < split.end_ns))
    if "guard_supported" in grid:
        if grid["guard_supported"].dtype != np.bool_ or grid["guard_supported"].shape != times.shape:
            raise ValueError("Boolean fractional-guard support required")
        keep &= grid["guard_supported"][g]
    return g[keep]


def state_features(grid, depth):
    """Five slots/level: own-mid bid/ask bps, log base sizes, level imbalance."""
    mid = (grid["bid_px"][:, 0] + grid["ask_px"][:, 0]) / 2
    bid, ask = grid["bid_qty"][:, :depth], grid["ask_qty"][:, :depth]
    active = np.stack((
        10000 * (grid["bid_px"][:, :depth] / mid[:, None] - 1),
        10000 * (grid["ask_px"][:, :depth] / mid[:, None] - 1),
        np.log1p(bid), np.log1p(ask), (bid - ask) / (bid + ask)), axis=2)
    values = np.zeros((len(mid), 25), dtype=np.float64)
    values[:, :5 * depth] = active.reshape(len(mid), 5 * depth)
    return values


def build_split(grid, split, forward_guard_ns=FORWARD_GUARD_NS):
    """Fixed decision targets; all state/history move together to u=g-delay."""
    indices = eligible_indices(grid, split, forward_guard_ns)
    mid = (grid["bid_px"][:, 0] + grid["ask_px"][:, 0]) / 2
    returns = 10000 * (mid[indices + HORIZON] / mid[indices] - 1)
    views = {}
    for delay, depth, history in VIEWS:
        u = indices - delay
        state = state_features(grid, depth)
        x = np.zeros((len(indices), 30), dtype=np.float64)
        x[:, :25] = state[u]
        if history == "20sec":
            for column, lag in enumerate((1, 5, 20), start=25):
                x[:, column] = 10000 * (mid[u] / mid[u - lag] - 1)
            observed = np.concatenate([grid[k][:, :depth] for k in
                                       ("bid_px", "ask_px", "bid_qty", "ask_qty")], axis=1)
            changed = np.r_[False, np.any(observed[1:] != observed[:-1], axis=1)]
            for row, current in enumerate(u):
                past_changes = np.flatnonzero(changed[current - 19:current + 1])
                x[row, 28] = 20 if not len(past_changes) else 19 - past_changes[-1]
                x[row, 29] = len(past_changes)
        if not np.isfinite(x).all():
            raise ValueError("Nonfinite derived feature")
        views[(delay, depth, history)] = x
    return {"indices": indices, "times_ns": grid["times_ns"][indices],
            "returns_bps": returns, "views": views}


def build_dataset(grid, splits, forward_guard_ns=FORWARD_GUARD_NS):
    if len(splits) != 2 or [s.name for s in splits] != ["train", "evaluation"]:
        raise ValueError("Bounded pilot requires train then evaluation")
    if not (splits[0].start_ns < splits[0].end_ns <= splits[1].start_ns < splits[1].end_ns):
        raise ValueError("Overlapping or reversed splits")
    built = {s.name: build_split(grid, s, forward_guard_ns) for s in splits}
    if any(len(part["indices"]) < 20 for part in built.values()):
        raise ValueError("Fewer than 20 common eligible rows in a split; no fit")
    return built
