"""Execute the predeclared paired Hyperliquid period adaptation, without acquisition."""
import json
from pathlib import Path
import numpy as np
from .gate import sha256, implementation_sha256
from .protocol import PROTOCOL, digest_json
from .pilot import fit_evaluate, require_fit_runtime, write_json, development_contrasts
from .policies import evaluate
from .panel_projection import project_day, concatenate_days, OFFSETS_NS
from .paired_statistics import analyze_paired_dates

PROVIDER_PROTOCOL_SHA256 = "84639e7bee796452cae075f4f349e61e8ff37ac4fd9d32685ba0f111baf3120d"
PREDECLARATION_SHA256 = "b662415bee9b9869c33bdba184fbb499dd64b7e4e2b084f9e271777f9e0d0462"
ROLES = {"2025-01-01": "train", "2025-02-01": "train", "2025-03-01": "train",
         "2025-04-01": "validation", **{f"2025-{month:02}-01": "test" for month in range(5, 12)},
         "2026-01-01": "test"}


def run_panel(bindings, predeclaration, output_dir, period, reviewed_amendment=None):
    """Fit each asset once per period; retain every date, model and scenario.

    Invoke only in a detached, two-CPU/eight-GiB bounded job. The eight-date
    inference uses per-date summaries; pooled output is merely descriptive.
    """
    from .panel_contract import load_panel_contract
    from threadpoolctl import threadpool_limits
    require_fit_runtime()
    np.random.seed(PROTOCOL["new_pilot_seed"])
    if period not in {"hour00", "full_day"} or sha256(predeclaration) != PREDECLARATION_SHA256:
        raise ValueError("Period or immutable consumer predeclaration mismatch")
    plan = json.loads(Path(predeclaration).read_text(encoding="utf-8"))
    if plan["roles"] != ROLES or plan["provider_protocol_sha256"] != PROVIDER_PROTOCOL_SHA256:
        raise ValueError("Frozen date roles or provider protocol mismatch")
    if plan["source_protocol_sha256"] != digest_json(PROTOCOL) or plan["source_protocol"] != PROTOCOL:
        raise ValueError("Model, feature, seed or policy constants changed after the consumer freeze")
    keys = [(b["asset"], b["date"]) for b in bindings]
    if len(keys) != len(set(keys)) or set(keys) != {(a, d) for a in ("BTC", "ETH") for d in ROLES}:
        raise ValueError("Exactly the fixed 24 asset/date contract bindings are required")
    amendment = None
    provider_hash, startup = PROVIDER_PROTOCOL_SHA256, 0
    if reviewed_amendment is not None:
        from .panel_review import require_reviewed_amendment
        amendment = require_reviewed_amendment(reviewed_amendment, bindings, period, PREDECLARATION_SHA256)
        provider_hash, startup = amendment["provider_protocol_sha256"], amendment["startup_exclusion_ns"]
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    if any(root.iterdir()):
        raise ValueError("Fresh panel output directory required")
    write_json(root/"input_bindings.json", dict(period=period, origin="exploratory_real",
        bindings=bindings, predeclaration_sha256=PREDECLARATION_SHA256,
        implementation_sha256=implementation_sha256(), source_protocol_sha256=digest_json(PROTOCOL),
        reviewed_source_amendment=amendment))
    projected, diagnostics, unavailable, verification = {}, [], [], []
    for binding in sorted(bindings, key=lambda b: (b["asset"], b["date"])):
        asset, date = binding["asset"], binding["date"]
        print(f"verify/project {period} {asset} {date}", flush=True)
        loaded = load_panel_contract(binding["path"], expected_sha256=binding["sha256"])
        contract = loaded["contract"]
        if (contract["asset"] != asset or contract["date"] != date
                or contract["split_roles"]["Q17"] != ROLES[date]
                or contract["policy_sha256"] != provider_hash):
            raise ValueError("Contract differs from frozen asset/date/role/protocol")
        expected_start = int(np.datetime64(date, "ns").astype(np.int64))
        expected_end = expected_start+(3600 if period == "hour00" else 86400)*1_000_000_000
        if contract["selected_event_start_ns"] != expected_start+startup or contract["selected_event_end_ns"] != expected_end:
            raise ValueError("Contract does not cover the declared period selection")
        verification.append(dict(asset=asset, date=date, **loaded["acquisition_verification"]))
        try:
            day, diagnostic = project_day(loaded, asset, date, ROLES[date], period)
        except ValueError as error:
            if not str(error).startswith("Unavailable "):
                raise
            unavailable.append(dict(asset=asset, date=date, reason=str(error)))
            continue
        projected[(asset, date)] = day
        diagnostics.append(diagnostic)
        np.savez_compressed(root/f"examples_{asset}_{date}.npz", **day, origin=np.array("exploratory_real"))
        del loaded
    write_json(root/"acquisition_verification.json", verification)
    write_json(root/"projection_diagnostics.json", diagnostics)
    write_json(root/"unavailable.json", unavailable)
    paired = []
    for date in ROLES:
        days = [projected.get((asset, date)) for asset in ("BTC", "ETH")]
        paired.append(dict(date=date, role=ROLES[date], eligible_intersection=None if any(d is None for d in days)
            else int(len(np.intersect1d(days[0]["times"], days[1]["times"]))),
            asset_counts={a: None if d is None else len(d["times"]) for a, d in zip(("BTC", "ETH"), days)},
            synchronous_exchange_event_claim=False))
    write_json(root/"paired_cut_intersections.json", paired)
    records, summaries, samples = [], [], []
    test_dates = [date for date, role in ROLES.items() if role == "test"]
    if amendment is not None:
        # D019 admission is for a complete design, not a convenient surviving arm.
        for asset in ("BTC", "ETH"):
            if any((asset, date) not in projected for date in ROLES):
                continue
            role_arrays = {role: concatenate_days([projected[(asset, date)] for date, r in ROLES.items()
                if r == role]) for role in ("train", "validation", "test")}
            if set(role_arrays["train"]["y"].tolist()) != {0, 1, 2}:
                unavailable.append(dict(asset=asset, reason="pooled_training_missing_source_class"))
            for before, after in (("train", "validation"), ("validation", "test")):
                if int(role_arrays[before]["outcome_available_ns"].max()) > int(role_arrays[after]["times"].min()):
                    unavailable.append(dict(asset=asset, reason="outcome_support_not_mature_before_next_role"))
        if unavailable:
            output = analyze_paired_dates([], test_dates)
            output.update(period=period, actual_model_fits=0, model_fits=[], unavailable=unavailable,
                predeclaration_sha256=PREDECLARATION_SHA256, provider_protocol_sha256=provider_hash,
                reviewed_source_amendment=amendment, per_date_contrasts=[])
            write_json(root/"paired_date_results.json", output)
            write_json(root/"story_samples.json", [])
            write_json(root/"unavailable.json", unavailable)
            return output
    for asset in ("BTC", "ETH"):
        if any((asset, date) not in projected for date, role in ROLES.items() if role != "test"):
            unavailable.append(dict(asset=asset, reason="training_or_validation_date_unavailable"))
            continue
        present_tests = [date for date in test_dates if (asset, date) in projected]
        if not present_tests:
            unavailable.append(dict(asset=asset, reason="all_test_dates_unavailable"))
            continue
        arrays = {role: concatenate_days([projected[(asset, date)] for date, r in ROLES.items()
            if r == role and (asset, date) in projected]) for role in ("train", "validation", "test")}
        if set(arrays["train"]["y"].tolist()) != {0, 1, 2}:
            unavailable.append(dict(asset=asset, reason="pooled_training_missing_source_class"))
            continue
        checks = {}
        for before, after in (("train", "validation"), ("validation", "test")):
            ready, first = int(arrays[before]["outcome_available_ns"].max()), int(arrays[after]["times"].min())
            if ready > first:
                raise ValueError("Outcome support not mature before next role")
            checks[before] = dict(evidence_ready_ns=ready, next_first_decision_ns=first)
        context = dict(origin="exploratory_real", asset=asset, period=period, roles=ROLES,
            scope="Pooled descriptive summaries for fixed period; paired-date inference is separate",
            independent_test_days=0, selected_test_date_clusters=len(present_tests),
            feature_clock_scope="exchange_time_sampled_counterfactual", historical_receipt_claim=False,
            computation_latency_modeled=False, observed_fills=False, freeze_checks=checks,
            reviewed_source_amendment=amendment,
            original_joint_primary="failed and not re-evaluated; adapted rule in paired_date_results.json",
            provenance=dict(input_bindings_sha256=sha256(root/"input_bindings.json"),
                provider_protocol_sha256=provider_hash, predeclaration_sha256=PREDECLARATION_SHA256,
                implementation_sha256=implementation_sha256()))
        with threadpool_limits(limits=2):
            summary = fit_evaluate(arrays, root/asset, context)
        summaries.append(dict(asset=asset, actual_model_fits=summary["actual_model_fits"]))
        frozen = json.loads((root/asset/"frozen_policies.json").read_text())
        cursor = 0
        for date in present_tests:
            day = projected[(asset, date)]
            length = len(day["times"])
            probabilities = {}
            for policy in frozen:
                name, seed = policy["model"], policy["seed"]
                with np.load(root/asset/f"probabilities_{name}_{seed}.npz", allow_pickle=False) as archive:
                    p = archive["evaluation"][cursor:cursor+length]
                probabilities[f"{name}_{seed}"] = p
                records.append(dict(origin="exploratory_real", period=period, asset=asset, date=date,
                    model=name, seed=seed, **evaluate(day, p, policy["settings"])))
            np.savez_compressed(root/f"probabilities_{asset}_{date}.npz", **probabilities,
                                origin=np.array("exploratory_real"))
            for index in sorted({0, length//2, length-1}):
                samples.append(dict(asset=asset, date=date, index=index, decision_ns=int(day["times"][index]),
                    source_id=str(day["source_id"][index]), window_id=str(day["window_id"][index]),
                    segment_id=int(day["segment_id"][index]),
                    feature_values=day["X"][index].tolist(), label=int(day["y"][index]),
                    offsets_ns=OFFSETS_NS.tolist(), selected_event_ns=day["selected_event_ns"][index].tolist(),
                    selected_source_ordinals=day["selected_source_ordinals"][index].tolist(),
                    source_age_ns=day["source_age_ns"][index].tolist(),
                    probabilities={key: p[index].tolist() for key, p in probabilities.items()},
                    entry_bid=day["entry_bid"][index].tolist(), entry_ask=day["entry_ask"][index].tolist(),
                    exit_bid=day["exit_bid"][index].tolist(), exit_ask=day["exit_ask"][index].tolist(),
                    observed_fills=False, selection="fixed first/middle/last, not outcome-selected"))
            cursor += length
    output = analyze_paired_dates(records, test_dates)
    output.update(period=period, model_fits=summaries, actual_model_fits=sum(s["actual_model_fits"] for s in summaries),
        unavailable=unavailable, estimator="MLP seed endpoint mean minus logistic within asset/date; equal date weights",
        predeclaration_sha256=PREDECLARATION_SHA256, provider_protocol_sha256=provider_hash,
        reviewed_source_amendment=amendment,
        per_date_contrasts=[dict(asset=asset, date=date, **development_contrasts([r for r in records
            if r["asset"] == asset and r["date"] == date])) for asset in ("BTC", "ETH") for date in test_dates
            if any(r["asset"] == asset and r["date"] == date for r in records)])
    write_json(root/"paired_date_results.json", output)
    write_json(root/"story_samples.json", samples)
    write_json(root/"unavailable.json", unavailable)
    return output
