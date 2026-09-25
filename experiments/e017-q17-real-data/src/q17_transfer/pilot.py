"""Conditional December 1 adapter; no CLI, acquisition, or implicit execution."""
import hashlib
import json
import pickle
import time
import warnings
import zipfile
import importlib.metadata
from pathlib import Path
import numpy as np
from .gate import require_certificates, sha256
from .features import build_arrays, NS
from .protocol import PROTOCOL, model_specs
from .policies import tune, evaluate


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False)+"\n", encoding="utf-8")


def run_development(data_certificate, label_certificate, coordinator_review, output_dir):
    """Six streams, up to three repair fits, after affirmative payload-bound review.

    All three time blocks remain inspected development data. This function
    intentionally does not compute the eight-independent-day primary gate.
    Run in a detached, one-hour-limited session with at most two CPU threads.
    """
    checked = require_certificates(data_certificate, label_certificate, coordinator_review)
    require_fit_runtime()
    from threadpoolctl import threadpool_limits
    with threadpool_limits(limits=2):
        return _run_development(checked, output_dir)


def require_fit_runtime():
    versions = {name: importlib.metadata.version(name) for name in PROTOCOL["fit_packages"]}
    if versions != PROTOCOL["fit_packages"]:
        raise ValueError("Fitting requires original pinned packages; current runtime does not match the source fit environment")
    return versions


def _run_development(checked, output_dir):
    np.random.seed(PROTOCOL["new_pilot_seed"])
    with zipfile.ZipFile(checked["data_file"]) as archive:
        if sum(item.file_size for item in archive.infolist()) > 512*1024*1024:
            raise ValueError("Bounded pilot payload exceeds 512 MiB decoded cap")
    with np.load(checked["data_file"], allow_pickle=False) as payload:
        quotes = {k: payload[k] for k in payload.files}
    if (quotes["event_ns"] < checked["window"]["start_ns"]).any() or (quotes["event_ns"] > checked["window"]["end_ns"]).any():
        raise ValueError("Payload event extent exceeds the certified window")
    day_start = int(np.datetime64("2025-12-01", "ns").astype(np.int64))
    if int(quotes["event_ns"][0]) > day_start or int(quotes["event_ns"][-1]) < day_start+3599*NS:
        raise ValueError("Frozen three-block pilot needs whole first-hour coverage; propose a new reviewed protocol for shorter coverage")
    arrays = {split: build_arrays(quotes, split, day_start+i*1200*NS, day_start+(i+1)*1200*NS)
              for i, split in enumerate(("train", "validation", "test"))}
    if set(arrays["train"]["y"].tolist()) != {0, 1, 2}:
        raise ValueError("All three source-protocol training labels required")
    freezes = {}
    for before, after in (("train", "validation"), ("validation", "test")):
        ready = int(arrays[before]["outcome_available_ns"].max())
        cutoff = int(arrays[after]["times"].min())
        if ready > cutoff:
            raise ValueError("Outcome evidence matures after next block decision; new reviewed block design required")
        freezes[before] = dict(evidence_ready_ns=ready, next_first_decision_ns=cutoff)
    fixture = checked["data"].get("fixture_metadata", {}).get("origin")
    context = dict(origin="synthetic_integration" if fixture else "eligible_empirical",
                   scope="December 1 development only; no independent-day inference",
                   provenance={k: v for k, v in checked.items() if k.endswith("sha256")},
                   freeze_checks=freezes, feature_clock_scope="declared_availability")
    return fit_evaluate(arrays, output_dir, context)


def fit_evaluate(arrays, output_dir, context):
    """Shared full fitting path; origin and exact dependency guard are mandatory."""
    require_fit_runtime()
    if context.get("origin") not in {"synthetic_integration", "exploratory_real", "eligible_empirical"}:
        raise ValueError("Explicit evidence origin required")
    np.random.seed(PROTOCOL["new_pilot_seed"])
    if set(arrays["train"]["y"].tolist()) != {0, 1, 2}:
        raise ValueError("All three source-protocol training labels required")
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    if any(root.iterdir()):
        raise ValueError("Fresh result directory required; do not overwrite previous evidence")
    rows = {split: {"n": len(a["times"]), "times_sha256": hashlib.sha256(a["times"].tobytes()).hexdigest()}
            for split, a in arrays.items()}
    write_json(root/"run_context.json", context)
    write_json(root/"matched_rows.json", {"origin": context["origin"], "splits": rows})
    for split, a in arrays.items():
        np.savez_compressed(root/f"{split}_examples.npz", **a, origin=np.array(context["origin"]))
    trained, frozen, predictions = [], [], {}
    for name, seed, model in model_specs():
        started = time.monotonic()
        print(f"fit start {context['origin']} {name} seed={seed} train_n={len(arrays['train']['y'])}", flush=True)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            model.fit(arrays["train"]["X"], arrays["train"]["y"])
        notes = [str(w.message) for w in caught]
        repairs = []
        if name == "mlp" and any("converg" in note.lower() for note in notes):
            original = root/f"original_{name}_{seed}.pkl"
            original.write_bytes(pickle.dumps(model))
            repairs.append(dict(original_warnings=notes, original_sha256=sha256(original), iteration_cap=[400, 800]))
            model.set_params(mlpclassifier__max_iter=800)
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                model.fit(arrays["train"]["X"], arrays["train"]["y"])
            notes = [str(w.message) for w in caught]
        if list(model.classes_) != [0, 1, 2]:
            raise ValueError("Probability class columns changed")
        p = model.predict_proba(arrays["validation"]["X"])
        settings = tune(arrays["validation"], p)
        frozen.append(dict(origin=context["origin"], model=name, seed=seed, settings=settings))
        predictions[(name, seed)] = model.predict_proba(arrays["test"]["X"])
        np.savez_compressed(root/f"probabilities_{name}_{seed}.npz", validation=p, evaluation=predictions[(name, seed)], origin=np.array(context["origin"]))
        (root/f"model_{name}_{seed}.pkl").write_bytes(pickle.dumps(model))
        trained.append(dict(origin=context["origin"], model=name, seed=seed, seconds=time.monotonic()-started, warnings=notes, repairs=repairs))
        write_json(root/"training.json", trained)
        print(f"fit done {name} seed={seed} seconds={trained[-1]['seconds']:.3f} repairs={len(repairs)}", flush=True)
    write_json(root/"training.json", trained)
    write_json(root/"frozen_policies.json", frozen)
    results = [{"origin": context["origin"], "model": f["model"], "seed": f["seed"],
                **evaluate(arrays["test"], predictions[(f["model"], f["seed"])], f["settings"])} for f in frozen]
    total_fits = len(trained)+sum(len(r["repairs"]) for r in trained)
    output = dict(origin=context["origin"], scope=context["scope"], independent_test_days=context.get("independent_test_days", 0),
                  actual_model_fits=total_fits, real_model_fits=0 if context["origin"] == "synthetic_integration" else total_fits,
                  synthetic_model_fits=total_fits if context["origin"] == "synthetic_integration" else 0,
                  observed_fills=False, accepted_scientific_claims=[], records=results,
                  descriptive_mlp_minus_logistic=development_contrasts(results),
                  provenance=context["provenance"],
                  package_versions={name: importlib.metadata.version(name) for name in PROTOCOL["fit_packages"]},
                  rows=rows, freeze_checks=context["freeze_checks"], computation_latency_modeled=False,
                  feature_clock_scope=context["feature_clock_scope"],
                  original_joint_primary=context.get("original_joint_primary", "not_evaluable_single_asset_single_test_day"))
    write_json(root/"development_metrics.json", output)
    return output


def development_contrasts(records):
    """Average seed metrics, never probabilities or purported independent dates."""
    mlp = [r for r in records if r["model"] == "mlp"]
    logistic = [r for r in records if r["model"] == "logistic"]
    if sorted(r["seed"] for r in mlp) != [17, 29, 41] or len(logistic) != 1:
        raise ValueError("Matched source seeds and one logistic result required")
    baseline = logistic[0]
    output = {k: float(np.mean([r[k] for r in mlp])-baseline[k])
              for k in ("macro_f1", "accuracy", "log_loss", "multiclass_brier")}
    output["conditions"] = []
    for c in baseline["conditions"]:
        key = (c["policy"], c["delay_ms"], c["fee_bps"])
        matched = [next(x for x in r["conditions"] if (x["policy"], x["delay_ms"], x["fee_bps"]) == key) for r in mlp]
        if any(x["n"] != c["n"] for x in matched):
            raise ValueError("Different eligible opportunities across models")
        output["conditions"].append(dict(policy=key[0], delay_ms=key[1], fee_bps=key[2],
            difference_bps=float(np.mean([x["utility_bps"] for x in matched])-c["utility_bps"]), n=c["n"]))
    return output
