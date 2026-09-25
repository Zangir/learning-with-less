"""Origin-safe end-to-end Q18 producer translation, fitting and serialization."""
from datetime import datetime, timezone
import json
from pathlib import Path
import time

import numpy as np

from .contracts import implementation_hashes, sha256
from .evaluation import fit_pilot, loss_rows, summarize_pairs
from .producer import project_asset, project_panel, read_bundle, read_producer, read_rows


def decision_metrics(dataset, probabilities, threshold_bps, prior):
    """Declared forecast-alert cost, not fills or a trading-profit estimate."""
    truth = np.abs(dataset["evaluation"]["returns_bps"]) > threshold_bps
    out = []
    candidates = [(model, list(view), p) for (model, view), p in probabilities.items()]
    candidates += [("prior", None, np.full(len(truth), prior))]
    for model, view, p in candidates:
        alert = p >= 0.1  # False alarm cost1, missed-tail cost9: threshold1/(1+9).
        tp = int(np.sum(alert & truth)); fp = int(np.sum(alert & ~truth))
        fn = int(np.sum(~alert & truth)); tn = int(np.sum(~alert & ~truth))
        out.append({"model": model, "view": view, "rows": len(truth),
                    "brier": float(np.mean((p - truth) ** 2)), "alert_threshold": 0.1,
                    "false_positive_cost": 1, "false_negative_cost": 9,
                    "mean_alert_cost": (fp + 9 * fn) / len(truth),
                    "true_positive": tp, "false_positive": fp, "false_negative": fn, "true_negative": tn,
                    "alert_rate": float(np.mean(alert)), "precision": tp / (tp + fp) if tp + fp else None,
                    "recall": tp / (tp + fn) if tp + fn else None})
    return out


def freshness_gate(results):
    """Descriptive transferred criterion; never revise the original source failure."""
    if set(results) != {"BTC", "ETH"}:
        return {"status": "not_evaluable_missing_asset", "passing_factors": []}
    passing, directions = [], {}
    for factor in ("depth", "history"):
        checks = []
        for asset in ("BTC", "ETH"):
            for model in ("logistic", "hist_gb"):
                gaps = {r["delay"]: r["relative_gap"] for r in results[asset]["source_pilot_contrasts"]
                        if r["model"] == model and r["factor"] == factor}
                checks.append(1 if gaps[0] <= .01 < gaps[55] else -1 if gaps[55] <= .01 < gaps[0] else 0)
        directions[factor] = checks
        if all(x == 1 for x in checks) or all(x == -1 for x in checks):
            passing.append(factor)
    return {"status": "descriptive_pass" if passing else "descriptive_fail",
            "passing_factors": passing, "directions": directions,
            "criterion": "Same-direction1%-gap crossing across2assets and2models",
            "statistical_noninferiority": False}


def run_producer(contract_path, protocol_path, output_directory):
    output = Path(output_directory)
    output.mkdir(parents=True, exist_ok=True)
    protocol_path = Path(protocol_path)
    protocol = json.loads(protocol_path.read_text())
    if protocol.get("schema") != "q18-consumer-protocol/2":
        raise ValueError("Unknown consumer protocol")
    if protocol.get("implementation_sha256") != implementation_hashes():
        raise ValueError("Executing implementation differs from frozen protocol")
    expected = {"target_ns": 10_000_000_000, "forward_guard_ns": 10_500_000_000,
                "lookback_ns": 75_000_000_000, "grid_ns": 1_000_000_000,
                "seed": 20260919,
                "alert_threshold": .1, "false_positive_cost": 1, "false_negative_cost": 9}
    if any(protocol.get(key) != value for key, value in expected.items()):
        raise ValueError("Consumer protocol differs from implemented fixed design")
    if protocol.get("split_rule") not in ("first_two_thirds_train_final_third_development", "predeclared_three_date_panel"):
        raise ValueError("Unknown chronological split rule")
    origin = protocol["origin"]
    if origin == "eligible_empirical":
        raise ValueError("Independent acceptance is separate; this runner executes exploratory or synthetic evidence")
    start = time.perf_counter()
    if protocol["split_rule"] == "predeclared_three_date_panel":
        contract, sources = read_bundle(contract_path, protocol["producer_contract_sha256"], origin)
        if contract["bundle_window_roles"] != protocol["window_roles"]["BTC"]:
            raise ValueError("Source bundle differs from frozen window roles")
    else:
        contract, sources = read_producer(contract_path, protocol["producer_contract_sha256"], origin)
    rows, source_audit = read_rows(sources)
    available = sorted({w["asset"] for w in contract["windows"] if w["scope"] == "Q18"})
    if available != protocol["assets"]:
        raise ValueError("Producer asset cohort differs from frozen protocol")
    results, audits = {}, {}
    for asset in available:
        if protocol["split_rule"] == "predeclared_three_date_panel":
            dataset, grids, audit = project_panel(rows[asset], contract, asset, protocol["window_roles"][asset])
        else:
            dataset, grid, audit = project_asset(rows[asset], contract, asset)
            grids = {"development": grid}
        result, probabilities = fit_pilot(dataset)
        result["prediction_rows"] = result["evaluation_rows"]
        result["primary_evaluation_rows"] = result["evaluation_rows"]
        result["forecast_decision_metrics"] = decision_metrics(dataset, probabilities, result["threshold_bps"], result["prior"])
        result["origin"] = origin
        result["scientific_acceptance"] = "pending_independent_review"
        result["market_fits"] = result["fit_count"] if origin == "exploratory_real" else 0
        result["synthetic_fits"] = result["fit_count"] if origin == "synthetic_integration" else 0
        if "roles" in dataset["evaluation"]:
            part = dataset["evaluation"]
            labels = (np.abs(part["returns_bps"]) > result["threshold_bps"]).astype(int)
            dates = part["times_ns"].astype("datetime64[ns]").astype("datetime64[D]").astype(str)
            result["contrasts_by_role"] = {}
            result["forecast_decision_metrics_by_role"] = {}
            for role in ("validation", "evaluation"):
                mask = part["roles"] == role
                paired = {key: loss_rows(labels[mask], p[mask]) for key, p in probabilities.items()}
                result["contrasts_by_role"][role] = summarize_pairs(paired, dates[mask])
                result["forecast_decision_metrics_by_role"][role] = decision_metrics(
                    {"evaluation": {"returns_bps": part["returns_bps"][mask]}},
                    {key: p[mask] for key, p in probabilities.items()}, result["threshold_bps"], result["prior"])
            result["combined_later_dates_diagnostic_contrasts"] = result["source_pilot_contrasts"]
            result["source_pilot_contrasts"] = result["contrasts_by_role"]["evaluation"]["source_pilot_contrasts"]
            result["factorial_edges"] = result["contrasts_by_role"]["evaluation"]["factorial_edges"]
            result["primary_contrast_role"] = "evaluation_only"
            result["combined_later_dates_diagnostic_decision_metrics"] = result["forecast_decision_metrics"]
            result["forecast_decision_metrics"] = result["forecast_decision_metrics_by_role"]["evaluation"]
            result["role_counts"] = {r: int(np.sum(part["roles"] == r)) for r in ("validation", "evaluation")}
            result["primary_evaluation_rows"] = result["role_counts"]["evaluation"]
            result["evaluation_rows"] = result["primary_evaluation_rows"]
        arrays = {f"{model}_{delay}_{depth}_{history}": p for (model, (delay, depth, history)), p in probabilities.items()}
        arrays.update(decision_ns=dataset["evaluation"]["times_ns"], returns_bps=dataset["evaluation"]["returns_bps"])
        if "roles" in dataset["evaluation"]:
            arrays["role"] = dataset["evaluation"]["roles"]
        np.savez_compressed(output / f"{asset}_predictions.npz", **arrays)
        for role, grid in grids.items():
            np.savez_compressed(output / f"{asset}_{role}_observation_grid.npz", **grid)
        results[asset], audits[asset] = result, audit
        print(json.dumps({"asset": asset, "origin": origin, "fits": result["fit_count"],
                          "train_rows": result["training_rows"], "evaluation_rows": result["evaluation_rows"]}), flush=True)
    total = sum(r["fit_count"] for r in results.values())
    report = {"task": "T-011", "experiment": "E-018", "revision": "r2", "origin": origin,
              "purpose": contract["purpose"], "completed_at_utc": datetime.now(timezone.utc).isoformat(),
              "seconds": time.perf_counter() - start, "fit_count": total,
              "synthetic_fits": total if origin == "synthetic_integration" else 0,
              "market_fits": total if origin == "exploratory_real" else 0,
              "exploratory_real_fits": total if origin == "exploratory_real" else 0,
              "accepted_empirical_fits": 0, "scientific_acceptance": "pending_independent_review",
              "original_source_cross_asset_freshness_primary": "failed_not_overturned",
              "exact_original_feature_reproduction": False, "noninferiority": "not_tested",
              "source_audit": source_audit, "projection_audits": audits, "assets": results,
              "transferred_descriptive_freshness_gate": freshness_gate(results),
              "provenance": {"producer_contract": str(Path(contract_path).resolve()),
                             "producer_contract_sha256": sha256(contract_path),
                             "protocol_sha256": sha256(protocol_path),
                             "implementation_sha256": implementation_hashes(),
                             "original_producer_contracts": contract.get("source_contracts", []),
                             "source_authenticity": contract.get("source_authenticity", "not_stated"),
                             "sources": contract["sources"]},
              "limitations": ["Sampled snapshot observation process, not full event replay",
                              "Exchange-time hypothetical observer; no measured receive-latency claim",
                              "Rebuilt representation; original feature builder absent",
                              ("One fixed train, validation and evaluation date; no multi-date uncertainty estimate"
                               if protocol["split_rule"] == "predeclared_three_date_panel" else
                               "Single-date chronological development evaluation; no independent-date inference"),
                              "Forecast alert cost is not market profit, fill simulation or trading utility"]
                              + contract.get("limitations", [])}
    (output / "results.json").write_text(json.dumps(report, indent=2))
    return report
