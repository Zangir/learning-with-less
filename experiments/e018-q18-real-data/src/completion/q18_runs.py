"""Frozen Q18 receipt-clock comparisons, with per-fit recoverable checkpoints."""
import importlib.metadata
import json
import pickle
import time
import warnings
from pathlib import Path

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import log_loss
from sklearn.neural_network import MLPClassifier
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

from .receipt_features import sha256, shifted_views
from q17_transfer.pilot import require_fit_runtime


def write(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".partial")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def relative_loss(reduced, full, estimand):
    reduced, full = np.asarray(reduced), np.asarray(full)
    if (full <= 0).any():
        raise ValueError("Positive reference losses required")
    if estimand == "ratio_of_means":
        return float((reduced.mean() - full.mean()) / full.mean())
    if estimand == "mean_of_ratios":
        return float(((reduced - full) / full).mean())
    raise ValueError("Unknown fixed estimand")


def contrast_records(metrics, stage, dates):
    results = []
    models = ("logistic", "hist_gb") if stage == "pilot" else ("logistic", "hist_gb", "mlp")
    for asset in ("BTC", "ETH"):
        for model in models:
            for delay in (0, 55):
                for factor, reduced in (("depth", f"d1/20sec/delay{delay}"),
                                        ("history", f"d5/instant/delay{delay}")):
                    full = f"d5/20sec/delay{delay}"
                    losses = {}
                    for view in (reduced, full):
                        losses[view] = []
                        for date in dates:
                            values = [r["loss"] for r in metrics if r["stage"] == stage
                                      and (r["asset"], r["model"], r["date"], r["view"])
                                      == (asset, model, date, view)]
                            expected = 3 if model == "mlp" else 1
                            if len(values) != expected:
                                raise ValueError("Missing or duplicate fixed model/date stream")
                            losses[view].append(float(np.mean(values)))
                    daily = (np.array(losses[reduced]) - losses[full]) / losses[full]
                    row = dict(stage=stage, asset=asset, model=model, delay=delay, factor=factor,
                               reduced_losses=losses[reduced], full_losses=losses[full],
                               daily_relative_loss=daily.tolist(),
                               relative_loss=relative_loss(losses[reduced], losses[full],
                                   "ratio_of_means" if stage == "pilot" else "mean_of_ratios"))
                    if stage == "transfer":
                        draws = np.random.default_rng(91018).integers(0, 3, (10000, 3))
                        boot = daily[draws].mean(axis=1)
                        upper = float(np.quantile(boot, 1 - .05 / 24))
                        row.update(date_bootstrap95=np.quantile(boot, [.025, .975]).tolist(),
                                   simultaneous_upper=upper,
                                   noninferior_margins=[m for m in (.005, .01, .02) if upper < m])
                    results.append(row)
    return results


def run(protocol_path, cache_root, output_root):
    require_fit_runtime()
    np.random.seed(20260919)
    plan_path, cache_root, root = Path(protocol_path), Path(cache_root), Path(output_root)
    plan = json.loads(plan_path.read_text())
    plan_hash = sha256(plan_path)
    if plan_hash != plan_path.with_suffix(".sha256").read_text().strip():
        raise ValueError("Prospective plan changed")
    cache_manifest = json.loads((cache_root / "manifest.json").read_text())
    if cache_manifest["protocol_sha256"] != plan_hash:
        raise ValueError("Cache protocol mismatch")
    root.mkdir(exist_ok=True)
    (root / "models").mkdir(exist_ok=True)
    started = time.monotonic()
    metrics, fits = [], []
    provenance = dict(protocol_sha256=plan_hash, cache_manifest_sha256=sha256(cache_root / "manifest.json"),
                      source_review="pending", scientific_acceptance="pending independent review",
                      package_versions={name: importlib.metadata.version(name) for name in
                                        ("numpy", "scipy", "scikit-learn", "pandas")})
    write(root / "provenance.json", provenance)

    def checkpoint_fit(asset, stage, view, name, seed, budget, model, x, y, threshold, evaluation):
        key = f"{asset}_{stage}_{view.replace('/', '_')}_{name}_{seed}_{budget}"
        packet = root / "models" / f"{key}.json"
        model_path = packet.with_suffix(".pkl")
        prediction_path = packet.with_suffix(".npz")
        spec = dict(asset=asset, stage=stage, view=view, model=name, seed=seed, budget=budget,
                    threshold=threshold, train_rows=len(y), protocol_sha256=plan_hash)
        if packet.exists():
            saved = json.loads(packet.read_text())
            if saved["spec"] != spec or saved["model_sha256"] != sha256(model_path) or saved["predictions_sha256"] != sha256(prediction_path):
                raise ValueError("Checkpoint binding mismatch")
            fits.append(saved["fit"])
            metrics.extend(saved["metrics"])
            print(f"reuse completed {key}", flush=True)
            return pickle.loads(model_path.read_bytes())
        print(f"fit start {key} rows={len(y)}", flush=True)
        begin = time.monotonic()
        with warnings.catch_warnings(record=True) as caught, threadpool_limits(limits=2):
            warnings.simplefilter("always")
            model.fit(x, y)
        if list(model.classes_) != [0, 1]:
            raise ValueError("Both training target classes required")
        terminal = model[-1] if hasattr(model, "steps") else model
        fit = dict(**spec, seconds=time.monotonic() - begin,
                   warnings=[str(w.message) for w in caught],
                   iterations=int(np.asarray(getattr(terminal, "n_iter_", 0)).max()),
                   training_loss=float(terminal.loss_) if hasattr(terminal, "loss_") else None)
        local_metrics, predictions = [], {}
        for date, xx, ret in evaluation:
            yy = (np.abs(ret) > threshold).astype(int)
            probability = model.predict_proba(xx)
            local_metrics.append(dict(asset=asset, stage=stage, view=view, model=name, seed=seed,
                                      budget=budget, date=date, n=len(yy), loss=float(log_loss(yy, probability, labels=[0, 1])),
                                      tail_prevalence=float(yy.mean())))
            predictions[f"p_{date}"] = probability
            predictions[f"y_{date}"] = yy
        model_path.write_bytes(pickle.dumps(model))
        np.savez_compressed(prediction_path, **predictions)
        write(packet, dict(spec=spec, fit=fit, metrics=local_metrics,
                           model_sha256=sha256(model_path), predictions_sha256=sha256(prediction_path)))
        fits.append(fit)
        metrics.extend(local_metrics)
        write(root / "progress.json", dict(elapsed_seconds=time.monotonic() - started,
                                           completed_fits=len(fits), latest=key))
        print(f"fit done {key} seconds={fit['seconds']:.3f} iterations={fit['iterations']}", flush=True)
        return model

    for asset in ("BTC", "ETH"):
        caches, shifted = {}, {}
        for binding in cache_manifest["files"]:
            if binding["asset"] != asset:
                continue
            if sha256(binding["path"]) != binding["sha256"]:
                raise ValueError("Cache hash mismatch")
            with np.load(binding["path"], allow_pickle=False) as z:
                caches[binding["date"]] = {k: z[k] for k in z.files}
            shifted[binding["date"]] = shifted_views(caches[binding["date"]])
        train_dates, dev_dates, transfer_dates = (plan["dates"][k] for k in ("train", "development", "transfer"))
        ret = np.concatenate([shifted[d][1] for d in train_dates])
        selected = np.linspace(0, len(ret) - 1, min(18000, len(ret)), dtype=int)
        threshold = float(np.quantile(np.abs(ret[selected]), .9))
        y = (np.abs(ret[selected]) > threshold).astype(int)
        for stage, dates in (("pilot", dev_dates), ("transfer", transfer_dates)):
            for date in dates:
                yy = (np.abs(shifted[date][1]) > threshold).astype(int)
                metrics.append(dict(asset=asset, stage=stage, date=date, view="prior", model="prior", seed=0,
                                    budget=0, n=len(yy), loss=float(log_loss(yy, np.full(len(yy), y.mean()), labels=[0, 1]))))
        for view in shifted[train_dates[0]][0]:
            x = np.concatenate([shifted[d][0][view] for d in train_dates])[selected]
            evaluation = [(d, shifted[d][0][view], shifted[d][1]) for d in dev_dates]
            logistic = checkpoint_fit(asset, "pilot", view, "logistic", 0, 500,
                make_pipeline(StandardScaler(), LogisticRegression(C=1, max_iter=500)), x, y, threshold, evaluation)
            checkpoint_fit(asset, "pilot", view, "hist_gb", 18029001, 100,
                HistGradientBoostingClassifier(max_iter=100, max_leaf_nodes=15, l2_regularization=1,
                                               early_stopping=False, random_state=18029001), x, y, threshold, evaluation)
            later = [(d, shifted[d][0][view], shifted[d][1]) for d in transfer_dates]
            reused = {}
            for date, xx, rr in later:
                yy = (np.abs(rr) > threshold).astype(int)
                p = logistic.predict_proba(xx)
                metrics.append(dict(asset=asset, stage="transfer", date=date, view=view, model="logistic", seed=0,
                                    budget=500, n=len(yy), loss=float(log_loss(yy, p, labels=[0, 1])),
                                    reused_pilot_estimator=True))
                reused[f"p_{date}"], reused[f"y_{date}"] = p, yy
            np.savez_compressed(root / f"{asset}_transfer_{view.replace('/', '_')}_logistic_reuse.npz", **reused)
            checkpoint_fit(asset, "transfer", view, "hist_gb", 91018, 100,
                HistGradientBoostingClassifier(max_iter=100, max_leaf_nodes=15, l2_regularization=1,
                                               early_stopping=False, random_state=91018), x, y, threshold, later)
            for seed in (91017, 91029, 91041):
                checkpoint_fit(asset, "transfer", view, "mlp", seed, 400,
                    make_pipeline(StandardScaler(), MLPClassifier(hidden_layer_sizes=(24,), max_iter=400,
                        early_stopping=False, batch_size=256, random_state=seed)), x, y, threshold, later)
        own_returns = np.concatenate([caches[d]["returns"] for d in train_dates])
        ix = np.linspace(0, len(own_returns) - 1, min(30000, len(own_returns)), dtype=int)
        threshold = float(np.quantile(np.abs(own_returns[ix]), .9))
        y = (np.abs(own_returns[ix]) > threshold).astype(int)
        for view in ("d1_own", "d5_own"):
            x = np.concatenate([caches[d][view] for d in train_dates])[ix]
            evaluation = [(d, caches[d][view], caches[d]["returns"]) for d in dev_dates]
            for seed in (18, 19, 20):
                for budget in (60, 600):
                    checkpoint_fit(asset, "optimizer", view, "mlp", seed, budget,
                        make_pipeline(StandardScaler(), MLPClassifier(hidden_layer_sizes=(24,), max_iter=budget,
                            early_stopping=False, random_state=seed)), x, y, threshold, evaluation)
    contrasts = contrast_records(metrics, "pilot", plan["dates"]["development"])
    contrasts += contrast_records(metrics, "transfer", plan["dates"]["transfer"])
    directions = {}
    for factor in ("depth", "history"):
        directions[factor] = []
        for asset in ("BTC", "ETH"):
            for model in ("logistic", "hist_gb"):
                z = {r["delay"]: r["relative_loss"] for r in contrasts if
                     (r["stage"], r["asset"], r["model"], r["factor"]) == ("pilot", asset, model, factor)}
                directions[factor].append(1 if z[0] <= .01 < z[55] else -1 if z[55] <= .01 < z[0] else 0)
    optimizer = []
    for asset in ("BTC", "ETH"):
        for budget in (60, 600):
            loss = {v: float(np.mean([r["loss"] for r in metrics if
                    (r["stage"], r["asset"], r["budget"], r["view"]) == ("optimizer", asset, budget, v)]))
                    for v in ("d1_own", "d5_own")}
            optimizer.append(dict(asset=asset, budget=budget, **loss, shallow_minus_deep=loss["d1_own"] - loss["d5_own"]))
    result = dict(**provenance, unique_fits=len(fits), reused_logistic_streams=16, fits=fits,
                  daily_metrics=metrics, contrasts=contrasts, optimizer_contrasts=optimizer,
                  pilot_directions=directions, pilot_gate_passed=any(all(v == s for v in ds)
                    for ds in directions.values() for s in (-1, 1)), elapsed_seconds=time.monotonic() - started)
    if len(fits) != 120:
        raise ValueError("Missing fixed fit")
    write(root / "results.json", result)
    return result
