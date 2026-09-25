"""Minimal real-data contracts required by the Q16/Q17/Q18 venue transfer."""
import numpy as np


def decode_fixed_units(encoded, decimals=7):
    """Decode packed prices/sizes into exact integer units, avoiding float32 loss."""
    values = np.asarray(encoded, dtype=np.uint32)
    source_decimals = values >> 29
    if np.any(source_decimals > decimals):
        raise ValueError("Requested units would round source precision")
    return (values & 0x1FFFFFFF).astype(np.int64) * 10 ** (decimals - source_decimals.astype(np.int64))


def linear_round_trip(day, probabilities, latency_index, fee_bps):
    """Price-taking linear-perpetual PnL normalized by entry notional, not fills."""
    side = probabilities.argmax(axis=1) - 1
    entry = np.where(side > 0, day["entry_ask"][:, latency_index], day["entry_bid"][:, latency_index])
    exit_price = np.where(side > 0, day["exit_bid"][:, latency_index], day["exit_ask"][:, latency_index])
    ratio = exit_price / entry
    values = np.where(side != 0, side * (ratio - 1) * 10000 - fee_bps * (1 + ratio), 0.0)
    return values, side, probabilities.max(axis=1)


def fixed_base_schedule_values(prices, indices):
    """Cost saving against equal-base TWAP; common proportional fees cancel."""
    reference = prices.mean(axis=1)
    selected = prices[np.arange(len(prices)), indices]
    return (1 - selected / reference) * 10000


def require_replay_evidence(evidence):
    """Do not train quote/depth models on a guessed book or retrospectively sorted clock."""
    required = ["initial_state_verified", "event_time_verified", "event_order_verified", "trade_status_semantics_verified"]
    missing = [key for key in required if evidence.get(key) is not True]
    if missing:
        raise ValueError("Replay not certified: " + ", ".join(missing))


def chronological_masks(times_ns, horizon_ns=10_500_000_000, history_ns=75_000_000_000):
    """Fixed December day blocks, with explicit lookback/target containment."""
    times = np.asarray(times_ns, dtype=np.int64)
    if np.any(np.diff(times) < 0):
        raise ValueError("Input time order violation; do not sort after observing outcomes")
    boundaries = [np.datetime64(date, "ns").astype(np.int64) for date in
                  ["2025-12-01", "2025-12-15", "2025-12-22", "2026-01-01"]]
    return {name: (times - history_ns >= boundaries[i]) & (times + horizon_ns < boundaries[i + 1])
            for i, name in enumerate(["train", "validation", "test"])}
