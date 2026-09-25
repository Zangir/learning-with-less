"""Quote-based linear cashflows; equal marginal base quantity, no fill model.

Policy search/tie conventions follow Q17 (MIT; see THIRD_PARTY_LICENSE).
"""
import numpy as np
from .protocol import PROTOCOL


def check_probabilities(probabilities, n):
    p = np.asarray(probabilities, dtype=float)
    if p.shape != (n, 3) or not np.isfinite(p).all() or (p < 0).any() or not np.allclose(p.sum(1), 1):
        raise ValueError("Aligned down/flat/up probabilities required")
    return p


def round_trip(day, probabilities, latency_index, fee_bps):
    p = check_probabilities(probabilities, len(day["times"]))
    if not np.isfinite(fee_bps) or fee_bps < 0:
        raise ValueError("Nonnegative finite fee required")
    side = p.argmax(axis=1)-1
    entry = np.where(side > 0, day["entry_ask"][:, latency_index], day["entry_bid"][:, latency_index])
    exit_ = np.where(side > 0, day["exit_bid"][:, latency_index], day["exit_ask"][:, latency_index])
    ratio = exit_/entry
    value = np.where(side == 0, 0.0, side*(ratio-1)*10000-fee_bps*(1+ratio))
    return value, side, p.max(axis=1)


def best_threshold(scores, values, eligible):
    indices = np.flatnonzero(eligible)
    flat = dict(all_flat=True, threshold=None, validation_mean=0.0, validation_trades=0)
    if not len(indices):
        return flat
    order = indices[np.argsort(-scores[indices], kind="stable")]
    ends = np.r_[np.flatnonzero(scores[order][:-1] != scores[order][1:]), len(order)-1]
    cumulative = np.cumsum(values[order])[ends]
    best = int(np.argmax(cumulative))
    if cumulative[best] <= 0:
        return flat
    end = int(ends[best])
    return dict(all_flat=False, threshold=float(scores[order][end]),
                validation_mean=float(cumulative[best]/len(scores)), validation_trades=end+1)


def threshold_mask(scores, eligible, setting):
    if setting["all_flat"]:
        return np.zeros(len(scores), dtype=bool)
    return eligible & (scores >= setting["threshold"])


def schedule_inputs(day, probabilities, latency_index):
    p = check_probabilities(probabilities, len(day["times"]))
    width = PROTOCOL["schedule_width"]
    if "schedule_rows" in day:
        rows = np.asarray(day["schedule_rows"])
        if rows.ndim != 2 or rows.shape[1] != width or rows.dtype.kind not in "iu" or not len(rows):
            raise ValueError("Complete declared scheduling windows required")
        if (rows < 0).any() or (rows >= len(p)).any() or len(np.unique(rows)) != rows.size:
            raise ValueError("Scheduling windows must use distinct valid rows")
        if not (np.diff(rows, axis=1) == 1).all() or not (np.diff(day["times"][rows], axis=1) == 11_000_000_000).all():
            raise ValueError("Scheduling windows cannot compress gaps")
    else:
        if len(p) < width or not np.all(np.diff(day["times"]) == PROTOCOL["evaluation_stride_seconds"]*1_000_000_000):
            raise ValueError("Scheduling requires contiguous 11-second evaluation opportunities")
        rows = np.arange(len(p)//width*width).reshape(-1, width)
    return p[rows, 2]-p[rows, 0], day["entry_ask"][rows, latency_index]


def schedule_indices(scores, setting):
    if setting["mode"] == "always_buy":
        return np.zeros(len(scores), dtype=int)
    if setting["mode"] == "always_wait":
        return np.full(len(scores), scores.shape[1]-1, dtype=int)
    if setting["mode"] != "threshold":
        raise ValueError("Unknown scheduling policy")
    hit = scores >= setting["threshold"]
    hit[:, -1] = True
    return hit.argmax(axis=1)


def schedule_values(prices, indices, fee_bps):
    if not np.isfinite(prices).all() or (prices <= 0).any() or not np.isfinite(fee_bps) or fee_bps < 0:
        raise ValueError("Positive quote prices and nonnegative fee required")
    twap = prices.mean(axis=1)
    selected = prices[np.arange(len(prices)), indices]
    return (1+fee_bps/10000)*(twap-selected)/twap*10000


def best_schedule(scores, prices):
    if not len(scores):
        raise ValueError("No complete scheduling windows")
    best = dict(mode="always_wait", threshold=None)
    best_value = float(schedule_values(prices, schedule_indices(scores, best), 0).mean())
    for threshold in np.unique(scores)[::-1]:
        candidate = dict(mode="threshold", threshold=float(threshold))
        value = float(schedule_values(prices, schedule_indices(scores, candidate), 0).mean())
        if value > best_value:
            best, best_value = candidate, value
    buy = dict(mode="always_buy", threshold=None)
    value = float(schedule_values(prices, schedule_indices(scores, buy), 0).mean())
    if value > best_value:
        best, best_value = buy, value
    return {**best, "validation_mean": best_value}


def tune(validation, probabilities):
    settings = {}
    for li, ms in enumerate(PROTOCOL["scenario_delays_ms"]):
        scores, prices = schedule_inputs(validation, probabilities, li)
        settings[f"schedule_{ms}"] = best_schedule(scores, prices)
        for fee in PROTOCOL["fees_bps_per_side"]:
            values, side, confidence = round_trip(validation, probabilities, li, fee)
            settings[f"confidence_{ms}_{fee}"] = best_threshold(confidence, values, side != 0)
    return settings


def evaluate(day, probabilities, frozen_settings):
    """All learners share day; confidence denominators include abstentions."""
    from sklearn.metrics import accuracy_score, f1_score, log_loss
    p = check_probabilities(probabilities, len(day["times"]))
    conditions = []
    for li, ms in enumerate(PROTOCOL["scenario_delays_ms"]):
        scores, prices = schedule_inputs(day, p, li)
        chosen = schedule_indices(scores, frozen_settings[f"schedule_{ms}"])
        for fee in PROTOCOL["fees_bps_per_side"]:
            values, side, confidence = round_trip(day, p, li, fee)
            mask = threshold_mask(confidence, side != 0, frozen_settings[f"confidence_{ms}_{fee}"])
            base = dict(delay_ms=ms, fee_bps=fee)
            conditions.extend([
                {**base, "policy": "argmax", "utility_bps": float(values.mean()), "trade_fraction": float((side != 0).mean()), "n": len(values)},
                {**base, "policy": "confidence", "utility_bps": float((values*mask).mean()), "trade_fraction": float(mask.mean()), "n": len(values)},
                {**base, "policy": "scheduling", "utility_bps": float(schedule_values(prices, chosen, fee).mean()), "n": len(prices),
                 "excluded_scheduling_opportunities": len(p)-len(prices)*PROTOCOL["schedule_width"],
                 "always_buy_bps": float(schedule_values(prices, np.zeros(len(prices), int), fee).mean()),
                 "always_wait_bps": float(schedule_values(prices, np.full(len(prices), prices.shape[1]-1, int), fee).mean())}])
    return dict(macro_f1=float(f1_score(day["y"], p.argmax(1), labels=[0, 1, 2], average="macro", zero_division=0)),
                accuracy=float(accuracy_score(day["y"], p.argmax(1))), log_loss=float(log_loss(day["y"], p, labels=[0, 1, 2])),
                multiclass_brier=float(np.mean(np.sum((p-np.eye(3)[day["y"]])**2, axis=1))), conditions=conditions)
