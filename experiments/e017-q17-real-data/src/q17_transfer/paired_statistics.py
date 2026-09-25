"""Source-style paired-date inference for an explicitly frozen adapted panel."""
import math
from numbers import Real

import numpy as np
from scipy.stats import t


ASSETS = ("BTC", "ETH")
POLICIES = ("argmax", "confidence", "scheduling")
SEEDS = {"logistic": (0,), "mlp": (17, 29, 41), "prior": (0,), "hist_gb": (17,)}
FORECAST_METRICS = ("macro_f1", "accuracy", "log_loss", "multiclass_brier")


def _interval(values, indices):
    values = np.asarray(values, dtype=float)
    alpha = 0.05 / 8
    quantiles = np.quantile(values[indices].mean(axis=1), [alpha / 2, 1 - alpha / 2])
    center = float(values.mean())
    radius = float(t.ppf(1 - alpha / 2, 7) * values.std(ddof=1) / np.sqrt(8))
    return dict(mean=center, lower=float(min(quantiles[0], center - radius)),
                upper=float(max(quantiles[1], center + radius)),
                bootstrap_lower=float(quantiles[0]), bootstrap_upper=float(quantiles[1]),
                t_radius=radius, day_values=values.tolist(),
                negative_dates=int(np.sum(values < 0)))


def _finite(value):
    return isinstance(value, Real) and not isinstance(value, bool) and math.isfinite(value)


def analyze_paired_dates(records, selected_dates, origin="exploratory_real"):
    """Analyze evaluate-shaped summaries; malformed evidence raises ValueError.

    Incomplete panels return not_evaluable with a null gate, never a failed test.
    Date selection, provenance admission and model fitting belong to the caller.
    """
    dates, records = list(selected_dates), list(records)
    if not all(isinstance(day, str) and day for day in dates) or len(set(dates)) != len(dates):
        raise ValueError("Selected dates must be distinct nonempty strings")
    if origin not in {"exploratory_real", "synthetic_integration", "eligible_empirical"}:
        raise ValueError("Explicit supported evidence origin required")
    output = dict(origin=origin, status="not_evaluable", adapted_joint_rule_passed=None,
                  original_source_primary="failed and not re-evaluated", forecast_gate=None,
                  passing_policies=None, contrasts=[], records=records, selected_dates=dates,
                  date_cluster_count=len(dates), bootstrap_seed=17029001,
                  bootstrap_replicates=10000, simultaneous_family=8, familywise_alpha=0.05,
                  primary_fee_bps=5, primary_delay_ms=100, independence_guarantee=False,
                  seed_is_not_an_independent_date=True, row_is_not_an_independent_date=True,
                  accepted_scientific_claims=[], missing_evidence=[], matched_counts=[],
                  interpretation="Failed adapted joint rule is not equivalence or a decisive null; "
                                 "quote utilities do not establish realized fills or profit.")
    missing = output["missing_evidence"]
    if len(dates) != 8:
        missing.append("Exactly eight selected date clusters are required")
    lookup, primary = {}, {}
    for row in records:
        asset, day, model, seed = (row[k] for k in ("asset", "date", "model", "seed"))
        key = (asset, day, model, seed)
        if asset not in ASSETS or day not in dates or model not in SEEDS:
            raise ValueError("Unexpected asset, date or model outside the declared panel")
        if type(seed) is not int or seed not in SEEDS[model]:
            raise ValueError("Unexpected model seed")
        if key in lookup:
            raise ValueError("Duplicate asset/date/model/seed record")
        if row.get("origin") != origin:
            raise ValueError("Record origin does not match analysis origin")
        if any(not _finite(row.get(metric)) for metric in FORECAST_METRICS):
            raise ValueError("Finite forecast metrics required")
        conditions = {}
        for condition in row["conditions"]:
            setting = tuple(condition[k] for k in ("policy", "fee_bps", "delay_ms"))
            if setting in conditions:
                raise ValueError("Duplicate policy/fee/delay condition")
            if setting[0] not in POLICIES or setting[1] not in (0, 1, 5) or setting[2] not in (0, 100, 500):
                raise ValueError("Unexpected policy/fee/delay condition")
            metrics = ("utility_bps", "trade_fraction", "always_buy_bps", "always_wait_bps")
            if "utility_bps" not in condition or any(not _finite(condition[m]) for m in metrics if m in condition):
                raise ValueError("Finite utility metrics required")
            if type(condition.get("n")) is not int or condition["n"] <= 0:
                raise ValueError("Positive integer matched denominator required")
            conditions[setting] = condition
        lookup[key] = row
        primary[key] = {p: conditions[(p, 5, 100)] for p in POLICIES if (p, 5, 100) in conditions}
        if model in ("logistic", "mlp") and len(primary[key]) != 3:
            missing.append(f"Missing primary condition: {asset}/{day}/{model}/{seed}")
    for asset in ASSETS:
        for day in dates:
            keys = [(asset, day, m, s) for m in ("logistic", "mlp") for s in SEEDS[m]]
            absent = [key for key in keys if key not in lookup]
            missing.extend("Missing stream: " + "/".join(map(str, key)) for key in absent)
            if absent or any(len(primary[key]) != 3 for key in keys):
                continue
            counts = {p: {primary[key][p]["n"] for key in keys} for p in POLICIES}
            if any(len(ns) != 1 for ns in counts.values()) or counts["argmax"] != counts["confidence"]:
                raise ValueError("Different eligible opportunities across matched models/policies")
            output["matched_counts"].append(dict(asset=asset, date=day,
                opportunities=next(iter(counts["argmax"])), scheduling_windows=next(iter(counts["scheduling"]))))
    if missing:
        return output
    # One date draw for every contrast: seeds do not grow extra calendar days.
    indices = np.random.default_rng(17029001).integers(0, 8, size=(10000, 8))
    for asset in ASSETS:
        for metric in ("macro_f1", *POLICIES):
            values = []
            for day in dates:
                keys = [(asset, day, "mlp", seed) for seed in SEEDS["mlp"]]
                baseline = (asset, day, "logistic", 0)
                if metric == "macro_f1":
                    value = np.mean([lookup[key][metric] for key in keys]) - lookup[baseline][metric]
                else:
                    value = np.mean([primary[key][metric]["utility_bps"] for key in keys]) - primary[baseline][metric]["utility_bps"]
                values.append(float(value))
            contrast = dict(asset=asset, metric=metric, **_interval(values, indices))
            contrast["criterion_passed"] = (contrast["lower"] > 0.02 if metric == "macro_f1"
                else contrast["upper"] < -0.1 and contrast["negative_dates"] >= 6)
            output["contrasts"].append(contrast)
    forecast = all(c["criterion_passed"] for c in output["contrasts"] if c["metric"] == "macro_f1")
    passing = [p for p in POLICIES if all(c["criterion_passed"] for c in output["contrasts"] if c["metric"] == p)]
    output.update(status="evaluated", forecast_gate=forecast, passing_policies=passing,
                  adapted_joint_rule_passed=bool(forecast and len(passing) >= 2))
    return output
