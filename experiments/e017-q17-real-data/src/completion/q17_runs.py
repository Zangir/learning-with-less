"""Original Q17 comparisons on a new frozen native-BBO receipt calendar."""
import json
import pickle
import time
import warnings
from pathlib import Path

import numpy as np
from scipy.stats import spearmanr
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import f1_score
from sklearn.neural_network import MLPClassifier
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

from q17_transfer.panel_projection import concatenate_days
from q17_transfer.paired_statistics import analyze_paired_dates
from q17_transfer.pilot import require_fit_runtime
from q17_transfer.policies import tune, evaluate, round_trip
from q17_transfer.protocol import model_specs
from .q17_receipt import control_probabilities
from .q18_runs import write
from .receipt_features import sha256


def rankings(records, dates):
    output = []
    models = ["prior", "logistic", "hist_gb", "mlp"]
    for asset in ("BTC", "ETH"):
        for date in dates:
            selected = {m: [r for r in records if (r["asset"], r["date"], r["model"]) == (asset, date, m)] for m in models}
            f1 = [float(np.mean([r["macro_f1"] for r in selected[m]])) for m in models]
            for policy in ("argmax", "confidence", "scheduling"):
                utility = [float(np.mean([c["utility_bps"] for r in selected[m] for c in r["conditions"]
                           if (c["policy"], c["fee_bps"], c["delay_ms"]) == (policy, 5, 100)])) for m in models]
                pairs = [(f1[i] - f1[j], utility[i] - utility[j]) for i in range(4) for j in range(i)]
                comparable = [(a, b) for a, b in pairs if a != 0 and b != 0]
                output.append(dict(asset=asset, date=date, policy=policy, models=models, macro_f1=f1,
                    utility_bps=utility, spearman=float(spearmanr(f1, utility).statistic)
                    if len(set(f1)) > 1 and len(set(utility)) > 1 else None,
                    reversed_pairs=sum(a * b < 0 for a, b in comparable),
                    comparable_pairs=len(comparable), tied_pairs=6 - len(comparable)))
    return output


def followup_specs():
    yield "logistic", 0, make_pipeline(StandardScaler(), LogisticRegression(C=1, max_iter=500))
    yield "hist_gb", 91018, HistGradientBoostingClassifier(max_iter=100, max_leaf_nodes=15,
        l2_regularization=1, early_stopping=False, random_state=91018)
    for seed in (91017, 91029, 91041):
        yield "mlp", seed, make_pipeline(StandardScaler(), MLPClassifier(hidden_layer_sizes=(24,),
            max_iter=400, early_stopping=False, batch_size=256, random_state=seed))


def scenario_metrics(day, p):
    f1 = float(f1_score(day["y"], p.argmax(1), average="macro", labels=[0, 1, 2], zero_division=0))
    rows = []
    for policy in ("argmax", "fixed_confidence"):
        mask = np.ones(len(p), dtype=bool) if policy == "argmax" else p.max(1) >= .6
        for j, delay in enumerate((0, 100, 500)):
            for fee in (0, 5):
                value, side, _ = round_trip(day, p, j, fee)
                for fill in (.25, .5, 1):
                    for adverse in (0, 1, 5):
                        utility = fill * np.where(mask & (side != 0), value - adverse, 0)
                        rows.append(dict(policy=policy, delay_ms=delay, fee_bps=fee, fill_fraction=fill,
                            adverse_selection_bps=adverse, macro_f1=f1,
                            trades=int(np.sum(mask & (side != 0))), n=len(p), utility_bps=float(utility.mean())))
    return rows


def run(plan_path, cache_root, output_root):
    versions = require_fit_runtime()
    np.random.seed(20260919)
    path, cache_root, root = Path(plan_path), Path(cache_root), Path(output_root)
    plan = json.loads(path.read_text())
    plan_hash = sha256(path)
    if plan_hash != path.with_suffix(".sha256").read_text().strip():
        raise ValueError("Frozen Q17 plan mismatch")
    manifest = json.loads((cache_root / "manifest.json").read_text())
    if manifest["protocol_sha256"] != plan_hash:
        raise ValueError("Q17 cache protocol mismatch")
    root.mkdir(exist_ok=True)
    (root / "models").mkdir(exist_ok=True)
    started = time.monotonic()
    primary, controls, transfer, fits = [], [], [], []
    provenance = dict(protocol_sha256=plan_hash, cache_manifest_sha256=sha256(cache_root / "manifest.json"),
                      package_versions=versions, source_review="pending", scientific_acceptance="pending independent review",
                      observation_clock="provider_receipt", label_clock="exchange_event", observed_fills=False,
                      utility="native linear entry-notional cashflow; base-quantity TWAP")
    write(root / "provenance.json", provenance)

    def fitted(stage, asset, name, seed, estimator, train):
        key = f"{asset}_{stage}_{name}_{seed}"
        model_path = root / "models" / f"{key}.pkl"
        training_path = model_path.with_suffix(".training.json")
        if training_path.exists():
            record = json.loads(training_path.read_text())
            if record["protocol_sha256"] != plan_hash or record["model_sha256"] != sha256(model_path):
                raise ValueError("Q17 training checkpoint mismatch")
            model = pickle.loads(model_path.read_bytes())
            fits.append(record)
            return key, model
        begin = time.monotonic()
        print(f"fit start {key} rows={len(train['y'])}", flush=True)
        with warnings.catch_warnings(record=True) as caught, threadpool_limits(limits=2):
            warnings.simplefilter("always")
            estimator.fit(train["X"], train["y"])
        notes, repairs = [str(w.message) for w in caught], []
        if stage == "primary" and name == "mlp" and any("converg" in note.lower() for note in notes):
            original_path = model_path.with_suffix(".original.pkl")
            original_path.write_bytes(pickle.dumps(estimator))
            repairs.append(dict(original_sha256=sha256(original_path), original_warnings=notes, iteration_cap=[400, 800]))
            estimator.set_params(mlpclassifier__max_iter=800)
            with warnings.catch_warnings(record=True) as caught, threadpool_limits(limits=2):
                warnings.simplefilter("always")
                estimator.fit(train["X"], train["y"])
            notes = [str(w.message) for w in caught]
        if list(estimator.classes_) != [0, 1, 2]:
            raise ValueError("Q17 missing training class")
        model_path.write_bytes(pickle.dumps(estimator))
        record = dict(asset=asset, stage=stage, model=name, seed=seed, train_rows=len(train["y"]),
            seconds=time.monotonic() - begin, warnings=notes, repairs=repairs,
            model_sha256=sha256(model_path), protocol_sha256=plan_hash)
        write(training_path, record)
        fits.append(record)
        print(f"fit done {key} seconds={record['seconds']:.3f} repairs={len(repairs)}", flush=True)
        return key, estimator

    for asset in ("BTC", "ETH"):
        days = {}
        for binding in manifest["files"]:
            if binding["asset"] != asset:
                continue
            if sha256(binding["path"]) != binding["sha256"]:
                raise ValueError("Q17 cache hash mismatch")
            with np.load(binding["path"], allow_pickle=False) as z:
                days[binding["date"]] = {key: z[key] for key in z.files}
        train = concatenate_days([days[d] for d in plan["dates"]["train"]])
        validation_date = plan["dates"]["validation"][0]
        validation = days[validation_date]
        if set(train["y"].tolist()) != {0, 1, 2}:
            raise ValueError("Three training classes required before any fit")
        for name, seed, model in model_specs():
            key, model = fitted("primary", asset, name, seed, model, train)
            pv = model.predict_proba(validation["X"])
            policy_path = root / "models" / f"{key}.policies.json"
            settings = json.loads(policy_path.read_text()) if policy_path.exists() else tune(validation, pv)
            write(policy_path, settings)
            probabilities = {"validation": pv}
            for date in plan["dates"]["test"]:
                day = days[date]
                p = model.predict_proba(day["X"])
                probabilities[date] = p
                primary.append(dict(origin="exploratory_real", asset=asset, date=date, model=name,
                                    seed=seed, **evaluate(day, p, settings)))
            np.savez_compressed(root / "models" / f"{key}.probabilities.npz", **probabilities)
            write(root / "progress.json", dict(elapsed_seconds=time.monotonic() - started,
                completed_training_streams=len(fits), latest=key, primary_records=len(primary), transfer_records=len(transfer)))
        for name, seed in [("random", s) for s in (17, 29, 41)] + [("oracle", 0)]:
            pv = control_probabilities(validation, name, seed, asset, validation_date)
            settings = tune(validation, pv)
            write(root / "models" / f"{asset}_{name}_{seed}.policies.json", settings)
            probabilities = {"validation": pv}
            for date in plan["dates"]["test"]:
                p = control_probabilities(days[date], name, seed, asset, date)
                probabilities[date] = p
                controls.append(dict(origin="exploratory_real", asset=asset, date=date, model=name, seed=seed,
                    clairvoyant=name == "oracle", **evaluate(days[date], p, settings)))
            np.savez_compressed(root / "models" / f"{asset}_{name}_{seed}.probabilities.npz", **probabilities)
        for name, seed, model in followup_specs():
            key, model = fitted("transfer", asset, name, seed, model, train)
            probabilities = {}
            for date in plan["dates"]["transfer"]:
                p = model.predict_proba(days[date]["X"])
                probabilities[date] = p
                transfer.extend(dict(asset=asset, date=date, model=name, seed=seed, **r)
                                for r in scenario_metrics(days[date], p))
            np.savez_compressed(root / "models" / f"{key}.probabilities.npz", **probabilities)
            write(root / "progress.json", dict(elapsed_seconds=time.monotonic() - started,
                completed_training_streams=len(fits), latest=key, primary_records=len(primary), transfer_records=len(transfer)))
    result = analyze_paired_dates(primary, plan["dates"]["test"])
    result.update(**provenance, fits=fits, selected_training_streams=len(fits),
                  actual_fits=len(fits) + sum(len(f["repairs"]) for f in fits),
                  controls=controls, descriptive_rankings=rankings(primary, plan["dates"]["test"]))
    fields = ("asset", "policy", "delay_ms", "fee_bps", "fill_fraction", "adverse_selection_bps")
    comparisons = []
    for cell in sorted({tuple(row[k] for k in fields) for row in transfer}):
        selected = [row for row in transfer if tuple(row[k] for k in fields) == cell]
        differences, f1s = [], []
        for date in plan["dates"]["transfer"]:
            def avg(model, metric):
                return float(np.mean([r[metric] for r in selected if r["date"] == date and r["model"] == model]))
            differences.append(avg("mlp", "utility_bps") - avg("logistic", "utility_bps"))
            f1s.append(avg("mlp", "macro_f1") - avg("logistic", "macro_f1"))
        comparisons.append(dict(zip(fields, cell), daily_utility_difference=differences,
            mlp_minus_logistic_utility=float(np.mean(differences)), mlp_minus_logistic_f1=float(np.mean(f1s)),
            opposite_mean_directions=bool(np.mean(differences) * np.mean(f1s) < 0)))
    result.update(transfer_metrics=transfer, transfer_comparisons=comparisons,
                  elapsed_seconds=time.monotonic() - started,
                  transfer_scope="Fixed uncalibrated fill/adverse scenarios; no native fill or queue inference")
    if len(fits) != 22 or len(primary) != 96 or len(controls) != 64 or len(transfer) != 3240:
        raise ValueError("Missing fixed Q17 comparison")
    write(root / "results.json", result)
    return result
