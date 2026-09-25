"""Fixed paired-date Q18 evaluation of already validated producer inputs.

Source admission, protocol hashes, and per-window grid bounds belong to the caller
and existing producer projector. Raw inputs can be loaded one date at a time.
"""
import numpy as np

from .evaluation import fit_pilot, loss_rows, summarize_pairs
from .features import VIEWS
from .integration import decision_metrics, freshness_gate
from .producer import NoEligibleWindow, concatenate_parts, project_window

ASSETS = ("BTC", "ETH")
ROLES = ("train", "validation", "evaluation")
DIAGNOSTIC_ROLE = "conditional_december_diagnostic"


def _join(parts):
    if len(parts) == 1:
        return parts[0]
    joined = concatenate_parts(parts)
    for name in ("dates", "roles", "window_ids"):
        joined[name] = np.concatenate([part[name] for part in parts])
    return joined


def project_dates(rows_by_asset, validated_contracts, date_roles):
    """Project each segment separately, pairing dates rather than asset row times.

    Contracts are lists keyed by asset, each with a unique ISO date. date_roles
    declares three training dates, one diagnostic validation date, and three
    evaluation dates; exact dates and source identities are frozen by the caller.
    Each rows_by_asset value is a row list or a callable accepting one contract.
    A lazy loader's raw date rows are released before loading the next date.
    """
    if set(rows_by_asset) != set(ASSETS) or set(validated_contracts) != set(ASSETS):
        raise ValueError("Exactly paired BTC and ETH inputs required")
    dates = sorted(date_roles)
    if [date_roles[d] for d in dates] != ["train"] * 3 + ["validation"] + ["evaluation"] * 3:
        raise ValueError("Seven dates must have chronological 3/1/3 roles")
    if any(str(np.datetime64(d, "D")) != d for d in dates):
        raise ValueError("Canonical ISO calendar dates required")
    projected = {"datasets": {}, "grids": {}, "audits": {}, "date_counts": {},
                 "date_roles": dict(date_roles), "cross_asset_intersections": {}}
    decisions = {}
    for asset in ASSETS:
        contracts = validated_contracts[asset]
        contract_dates = [contract["date"] for contract in contracts]
        if len(contract_dates) != len(dates) or set(contract_dates) != set(dates):
            raise ValueError("Every declared date requires exactly one contract per asset")
        by_date = {contract["date"]: contract for contract in contracts}
        date_parts, grids, audits, counts = {}, {}, {}, {}
        for date in dates:
            role, contract = date_roles[date], by_date[date]
            source = rows_by_asset[asset]
            rows = source(contract) if callable(source) else source
            windows = [w for w in contract["windows"] if w["scope"] == "Q18" and w["asset"] == asset]
            if not windows or any(a["end_ns"] > b["start_ns"] for a, b in zip(windows, windows[1:])):
                raise ValueError("Nonoverlapping chronological source windows required")
            segments, audits[date] = [], []
            for window in windows:
                key = f"{date}:{window['window_id']}"
                if key in grids:
                    raise ValueError("Duplicate producer window ID")
                try:
                    built, grid, audit = project_window(rows, contract, window, role)
                except NoEligibleWindow as error:
                    audits[date].append({"window_id": window["window_id"], "asset": asset,
                                         "common_rows_by_role": {role: 0},
                                         "status": "no_eligible_support", "reason": str(error)})
                    continue
                part = built[role]
                actual_dates = part["times_ns"].astype("datetime64[ns]").astype("datetime64[D]").astype(str)
                if not np.all(actual_dates == date):
                    raise ValueError("Producer decisions escape their declared calendar date")
                n = len(part["times_ns"])
                part.update(dates=actual_dates, roles=np.full(n, role), window_ids=np.full(n, key))
                segments.append(part)
                grids[key], audits[date] = grid, audits[date] + [audit]
            # Small segments can share a date's sample size, never its missing time.
            if not segments:
                raise ValueError("Each asset/date requires at least 20 common decisions")
            date_parts[date] = _join(segments)
            del rows, segments, built, part
            counts[date] = len(date_parts[date]["times_ns"])
            if counts[date] < 20:
                raise ValueError("Each asset/date requires at least 20 common decisions")
            decisions[(asset, date)] = date_parts[date]["times_ns"]
        train = _join([date_parts.pop(d) for d in dates if date_roles[d] == "train"])
        later = _join([date_parts.pop(d) for d in dates if date_roles[d] != "train"])
        projected["datasets"][asset] = {"train": train, "evaluation": later}
        projected["grids"][asset], projected["audits"][asset] = grids, audits
        projected["date_counts"][asset] = counts
    for date in dates:
        common = np.intersect1d(decisions[("BTC", date)], decisions[("ETH", date)])
        projected["cross_asset_intersections"][date] = {
            "role": date_roles[date], "BTC_rows": len(decisions[("BTC", date)]),
            "ETH_rows": len(decisions[("ETH", date)]), "intersecting_decision_times": len(common),
            "intersection_used_for_fitting": False}
    return projected


def _append_diagnostic(main, part):
    diagnostic = dict(part)
    times = np.asarray(diagnostic["times_ns"])
    n = len(times)
    dates = times.astype("datetime64[ns]").astype("datetime64[D]").astype(str)
    if (not n or times.dtype != np.int64 or np.any(np.diff(times) <= 0)
            or times[0] <= main["times_ns"][-1]
            or not np.all(dates == "2025-12-01")
            or np.asarray(diagnostic["returns_bps"]).shape != (n,)
            or not np.isfinite(diagnostic["returns_bps"]).all()
            or set(diagnostic["views"]) != set(VIEWS)
            or any(x.shape != (n, 30) or not np.isfinite(x).all() for x in diagnostic["views"].values())):
        raise ValueError("Conditional diagnostics require December 1, finite, matched feature rows")
    diagnostic.setdefault("indices", np.arange(n))
    diagnostic.setdefault("window_ids", np.full(n, "conditional_source_supplied_by_caller"))
    diagnostic.update(dates=times.astype("datetime64[ns]").astype("datetime64[D]").astype(str),
                      roles=np.full(n, DIAGNOSTIC_ROLE))
    return _join([main, diagnostic])


def _absolute_by_date(asset, part, probabilities, threshold, prior):
    records = []
    for date in np.unique(part["dates"]):
        mask = part["dates"] == date
        roles = np.unique(part["roles"][mask])
        if len(roles) != 1:
            raise ValueError("A calendar date cannot mix evaluation roles")
        probabilities_date = {key: p[mask] for key, p in probabilities.items()}
        returns = part["returns_bps"][mask]
        truth = np.abs(returns) > threshold
        metrics = decision_metrics({"evaluation": {"returns_bps": returns}},
                                   probabilities_date, threshold, prior)
        for metric in metrics:
            p = (np.full(len(returns), prior) if metric["model"] == "prior" else
                 probabilities_date[(metric["model"], tuple(metric["view"]))])
            records.append({**metric, "asset": asset, "date": date, "role": str(roles[0]),
                            "log_loss": float(loss_rows(truth, p).mean()),
                            "tail_prevalence": float(truth.mean()), "prior_probability": prior})
    return records


def _equal_date_metrics(records, role):
    selected = [row for row in records if row["role"] == role]
    dates = sorted({row["date"] for row in selected})
    out = []
    for model, view in [(m, list(v)) for m in ("logistic", "hist_gb") for v in VIEWS] + [("prior", None)]:
        rows = [r for r in selected if r["model"] == model and r["view"] == view]
        if len(rows) != len(dates):
            raise ValueError("Every view must have every paired date")
        out.append({"model": model, "view": view, "role": role, "dates": dates,
                    "date_count": len(dates), "total_rows": sum(r["rows"] for r in rows),
                    "weighting": "equal_calendar_dates", **{key: float(np.mean([r[key] for r in rows]))
                    for key in ("log_loss", "brier", "mean_alert_cost", "tail_prevalence",
                                "alert_rate", "prior_probability")}})
    return out


def fit_panel(projected, origin, diagnostic_parts=None):
    """Fit sixteen fixed models once per asset; never tune on later predictions.

    Optional later conditional-source feature parts share those fitted models.
    Their predictions/metrics are explicitly separate from the three-date primary.
    This pure helper reads/writes no files and does not issue source acceptance.
    """
    if origin not in ("synthetic_integration", "exploratory_real"):
        raise ValueError("Explicit synthetic or exploratory real origin required")
    if set(projected["datasets"]) != set(ASSETS):
        raise ValueError("Exactly paired BTC and ETH datasets required")
    diagnostic_parts = diagnostic_parts or {}
    if not set(diagnostic_parts) <= {"BTC"}:
        raise ValueError("Frozen conditional December diagnostic permits BTC only")
    results, predictions = {}, {}
    for asset in ASSETS:
        dataset = dict(projected["datasets"][asset])
        if asset in diagnostic_parts:
            dataset["evaluation"] = _append_diagnostic(dataset["evaluation"], diagnostic_parts[asset])
        result, probabilities = fit_pilot(dataset)
        part = dataset["evaluation"]
        threshold, prior = result["threshold_bps"], result["prior"]
        all_metrics = _absolute_by_date(asset, part, probabilities, threshold, prior)
        summaries = {}
        for role in ("validation", "evaluation"):
            mask = part["roles"] == role
            expected_dates = sorted(d for d, r in projected["date_roles"].items() if r == role)
            if sorted(np.unique(part["dates"][mask])) != expected_dates:
                raise ValueError("Prediction cohort differs from frozen date roles")
            truth = np.abs(part["returns_bps"][mask]) > threshold
            losses = {key: loss_rows(truth, p[mask]) for key, p in probabilities.items()}
            summaries[role] = summarize_pairs(losses, part["dates"][mask])
        main_metrics = [row for row in all_metrics if row["role"] != DIAGNOSTIC_ROLE]
        result.update(summaries["evaluation"])
        result.update(origin=origin, primary_contrast_role="evaluation_only",
                      prediction_rows=len(part["times_ns"]),
                      evaluation_rows=int(np.sum(part["roles"] == "evaluation")),
                      primary_evaluation_rows=int(np.sum(part["roles"] == "evaluation")),
                      role_counts={role: int(np.sum(part["roles"] == role)) for role in np.unique(part["roles"])},
                      date_counts=projected["date_counts"][asset], contrasts_by_role=summaries,
                      daily_metrics=main_metrics, absolute_metrics_by_date=main_metrics,
                      absolute_metrics_equal_date={role: _equal_date_metrics(main_metrics, role)
                                                   for role in ("validation", "evaluation")},
                      conditional_diagnostic_metrics_by_date=[r for r in all_metrics if r["role"] == DIAGNOSTIC_ROLE],
                      conditional_diagnostic_empirical_admission=False,
                      market_fits=result["fit_count"] if origin == "exploratory_real" else 0,
                      synthetic_fits=result["fit_count"] if origin == "synthetic_integration" else 0,
                      accepted_empirical_fits=0)
        results[asset] = result
        predictions[asset] = {"probabilities": probabilities, "decision_ns": part["times_ns"],
                              "returns_bps": part["returns_bps"], "role": part["roles"],
                              "date": part["dates"], "window_id": part["window_ids"],
                              "source_grid_index": part["indices"]}
    count = sum(r["fit_count"] for r in results.values())
    if count != 32:
        raise ValueError("Fixed paired panel requires exactly 32 fits")
    return {"origin": origin, "fit_count": count,
            "market_fits": count if origin == "exploratory_real" else 0,
            "synthetic_fits": count if origin == "synthetic_integration" else 0,
            "accepted_empirical_fits": 0, "scientific_acceptance": "pending_independent_review",
            "original_source_cross_asset_freshness_primary": "failed_not_overturned",
            "noninferiority": "not_tested", "uncertainty": "Point estimates; no confidence intervals",
            "transferred_descriptive_freshness_gate": freshness_gate(results), "assets": results,
            "date_roles": projected["date_roles"], "date_counts": projected["date_counts"],
            "cross_asset_intersections": projected["cross_asset_intersections"]}, predictions
