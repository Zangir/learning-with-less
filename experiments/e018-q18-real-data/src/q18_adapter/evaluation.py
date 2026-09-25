"""Bounded paired logistic/HGB evaluation; no inferential certification."""
import time
import warnings

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

from .features import VIEWS

SEED = 20260919


def train_labels(returns_bps):
    selected = np.linspace(0, len(returns_bps) - 1, min(18000, len(returns_bps)), dtype=int)
    threshold = float(np.quantile(np.abs(returns_bps[selected]), 0.9))
    labels = (np.abs(returns_bps[selected]) > threshold).astype(int)
    if len(np.unique(labels)) != 2:
        raise ValueError("Training tail target has one class; no fit")
    return selected, threshold, labels


def loss_rows(labels, probabilities):
    p = np.clip(probabilities, np.finfo(float).eps, 1 - np.finfo(float).eps)
    return -(labels * np.log(p) + (1 - labels) * np.log1p(-p))


def summarize_pairs(losses, dates):
    """All 12 paired factorial edges/model plus the source pilot's 8 contrasts."""
    dates = np.asarray(dates)
    unique_dates = np.unique(dates)
    mean = lambda values: float(np.mean([values[dates == d].mean() for d in unique_dates]))
    source, edges = [], []
    for model in ("logistic", "hist_gb"):
        for key in VIEWS:
            delay, depth, history = key
            pairs = []
            if depth == 1:
                pairs.append(("depth", (delay, 5, history)))
            if history == "instant":
                pairs.append(("history", (delay, depth, "20sec")))
            if delay == 55:
                pairs.append(("delay", (0, depth, history)))
            for factor, reference in pairs:
                a, b = losses[(model, key)], losses[(model, reference)]
                if a.shape != b.shape or len(a) != len(dates):
                    raise ValueError("Unpaired losses")
                edges.append({"model": model, "factor": factor, "view": list(key),
                              "reference": list(reference), "paired_rows": len(a),
                              "mean_date_loss_difference": mean(a - b)})
        for delay in (0, 55):
            full = mean(losses[(model, (delay, 5, "20sec"))])
            for factor, depth, history in (("depth", 1, "20sec"), ("history", 5, "instant")):
                reduced = mean(losses[(model, (delay, depth, history))])
                source.append({"model": model, "delay": delay, "factor": factor,
                               "reduced_loss": reduced, "full_loss": full,
                               "relative_gap": (reduced - full) / full})
    return {"source_pilot_contrasts": source, "factorial_edges": edges,
            "material_gap": 0.01, "original_cross_asset_gate": "not_evaluable_one_asset",
            "noninferiority": "not_tested",
            "uncertainty": "Point estimates; no confidence intervals"}


def fit_pilot(dataset):
    """16 fits on one asset. Call only after the external real-data gate, or on fixtures."""
    np.random.seed(SEED)
    train, evaluation = dataset["train"], dataset["evaluation"]
    selected, threshold, labels = train_labels(train["returns_bps"])
    target = (np.abs(evaluation["returns_bps"]) > threshold).astype(int)
    dates = evaluation["times_ns"].astype("datetime64[ns]").astype("datetime64[D]").astype(str)
    prior = float(labels.mean())
    losses, fits, metrics, probabilities = {}, [], [], {}
    prior_loss = loss_rows(target, np.full(len(target), prior))
    for date in np.unique(dates):
        mask = dates == date
        metrics.append({"date": date, "model": "prior", "n": int(mask.sum()),
                        "log_loss": float(prior_loss[mask].mean()),
                        "tail_prevalence": float(target[mask].mean())})
    for key in VIEWS:
        for model in ("logistic", "hist_gb"):
            estimator = (make_pipeline(StandardScaler(), LogisticRegression(C=1, max_iter=500,
                         random_state=SEED)) if model == "logistic" else
                         HistGradientBoostingClassifier(max_iter=100, max_leaf_nodes=15,
                         l2_regularization=1, early_stopping=False, random_state=SEED))
            start = time.perf_counter()
            with threadpool_limits(limits=2), warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                estimator.fit(train["views"][key][selected], labels)
                probability = estimator.predict_proba(evaluation["views"][key])[:, 1]
            if not np.isfinite(probability).all():
                raise ValueError("Nonfinite probability")
            loss = loss_rows(target, probability)
            losses[(model, key)] = loss
            probabilities[(model, key)] = probability
            fits.append({"model": model, "view": list(key), "rows": len(labels),
                         "seconds": time.perf_counter() - start, "threshold_bps": threshold,
                         "warnings": [str(w.message) for w in caught],
                         "scaler_mean": estimator[0].mean_.tolist() if model == "logistic" else None})
            for date in np.unique(dates):
                mask = dates == date
                metrics.append({"date": date, "model": model, "view": list(key),
                                "n": int(mask.sum()), "log_loss": float(loss[mask].mean())})
    result = {"seed": SEED, "fit_count": len(fits), "training_rows": len(labels),
              "evaluation_rows": len(target), "threshold_bps": threshold, "prior": prior,
              "fits": fits, "daily_metrics": metrics, **summarize_pairs(losses, dates)}
    return result, probabilities
