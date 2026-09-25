"""Apply reviewed earlier models to sealed conditional rows; never fit or tune."""
import hashlib
import io
import json
import pickle
from pathlib import Path

import numpy as np

from .gate import sha256
from .panel_review import STARTUP_POLICY_SHA256
from .pilot import development_contrasts, require_fit_runtime, write_json
from .policies import evaluate
from .protocol import PROTOCOL, digest_json

PARTICIPANT_SHA256 = "b85f1df6981f93b9315374e8149cbab66a2321d6efd1909f5325c3cebabcd706"
CONTRACT_SHA256 = "21a6393bb664c757cfcc52d393198b003e4bac06c6bbaf52884535411727612e"
BASE_PREDECLARATION_SHA256 = "b662415bee9b9869c33bdba184fbb499dd64b7e4e2b084f9e271777f9e0d0462"
SOURCE_PROTOCOL_SHA256 = "f8cf7d876a1e877eb615cb0f2d4b753e212bf596a2aca1bbbc0c58acd2c96021"
PREMISES = ["P1", "P2", "L1", "L2", "P4"]
STREAMS = [("prior", 0), ("logistic", 0), ("hist_gb", 17), ("mlp", 17), ("mlp", 29), ("mlp", 41)]
LEARNING_ROLES = {"2025-01-01": "train", "2025-02-01": "train", "2025-03-01": "train", "2025-04-01": "validation"}
DECEMBER_START_NS = 1764547200000000000


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _bound_bytes(path, expected):
    value = Path(path).read_bytes()
    _require(hashlib.sha256(value).hexdigest() == expected, "Checksum mismatch: "+Path(path).name)
    return value


def _participant(root):
    manifest = json.loads(_bound_bytes(root/"manifest.json", PARTICIPANT_SHA256))
    _require(manifest["assumption_ids"] == PREMISES and manifest["source_contract_sha256"] == CONTRACT_SHA256,
             "Conditional premise or source binding changed")
    _require(manifest["origin"] == "exploratory_real" and manifest["new_fits"] == 0
             and manifest["empirical_admission"] is False and manifest["online_admission"] is False,
             "Participant must remain conditional and unadmitted")
    files = {item["path"]: item["sha256"] for item in manifest["files"]}
    for name, digest in files.items():
        _require((root/name).resolve().is_relative_to(root.resolve()), "Manifest path escapes participant directory")
        _require(sha256(root/name) == digest, "Participant artifact checksum mismatch: "+name)
    with np.load(io.BytesIO(_bound_bytes(root/"matched_arrays.npz", files["matched_arrays.npz"])), allow_pickle=False) as saved:
        day = {name: saved[name] for name in saved.files}
    rows = json.loads(_bound_bytes(root/"decision_rows.json", files["decision_rows.json"]))
    _require(rows["assumption_ids"] == PREMISES and rows["conditional_offline_only"] is True,
             "Conditional row premises missing")
    expected_times = np.arange(16, dtype=np.int64)*11_000_000_000+1764550623000000000
    _require(np.array_equal(day["times"], expected_times) and np.array_equal(day["times"], [r["decision_ns"] for r in rows["rows"]]),
             "Exactly the 16 frozen participant decisions required")
    _require(day["X"].shape == (16, 5) and np.isfinite(day["X"]).all()
             and np.array_equal(day["X"], [r["feature_vector"] for r in rows["rows"]]), "Participant features changed")
    _require(day["origin"].item() == "exploratory_real" and day["scope"].item() == "conditional_offline_under_P1_P2_L1_L2_P4"
             and day["empirical_admission"].item() is False and day["online_admission"].item() is False,
             "Conditional array scope or admission changed")
    _require(np.array_equal(day["delays_ms"], [0, 100, 500])
             and np.array_equal(day["schedule_rows"], np.arange(12).reshape(1, 12)), "Frozen quote scenarios or one-window schedule changed")
    for name in ("entry_bid", "entry_ask", "exit_bid", "exit_ask"):
        exact = day[name+"_units8"]
        _require(exact.shape == (16, 3) and exact.dtype.kind in "iu" and (exact > 0).all()
                 and np.array_equal(day[name], exact/100_000_000), "Exact quote units changed")
    present = [int(b)+int(a) for b, a in zip(day["entry_bid_units8"][:, 0], day["entry_ask_units8"][:, 0])]
    future = [int(b)+int(a) for b, a in zip(day["exit_bid_units8"][:, 0], day["exit_ask_units8"][:, 0])]
    labels = [(after > before)-(after < before)+1 for before, after in zip(present, future)]
    _require(day["y"].dtype.kind in "iu" and np.array_equal(day["y"], labels)
             and np.array_equal(day["y"], [r["label_id"] for r in rows["rows"]]), "Exact integer participant labels changed")
    return day, files


def _context(context, expected_amendment):
    _require(context.get("origin") == "exploratory_real" and context.get("asset") == "BTC"
             and context.get("period") == "hour00", "Earlier real BTC hour00 models required")
    roles = context.get("roles", {})
    _require({date: role for date, role in roles.items() if role != "test"} == LEARNING_ROLES,
             "Models must train January–March and select policies in April only")
    for role in ("train", "validation"):
        check = context.get("freeze_checks", {}).get(role, {})
        _require(0 < check.get("evidence_ready_ns", 0) <= check.get("next_first_decision_ns", 0) < DECEMBER_START_NS,
                 "Learning evidence must mature before December 1")
    amendment = context.get("reviewed_source_amendment")
    _require(isinstance(expected_amendment, dict) and bool(expected_amendment) and amendment == expected_amendment,
             "Exact reviewed source amendment required")
    review = amendment.get("review", {})
    _require(amendment.get("schema") == "q17-reviewed-source-amendment/1"
             and amendment.get("base_predeclaration_sha256") == BASE_PREDECLARATION_SHA256
             and amendment.get("provider_protocol_sha256") == STARTUP_POLICY_SHA256
             and amendment.get("period") == "hour00" and amendment.get("startup_exclusion_ns") == 30_000_000_000
             and amendment.get("adaptation_class") == "SOURCE-QUALITY-INFORMED POST-ACQUISITION PRE-FIT"
             and amendment.get("model_policy_constants_unchanged") is True
             and review.get("review_id") == "RV-011" and review.get("reviewer_task") == "T-013"
             and review.get("decision") == "supported_exact_hour00_inputs"
             and review.get("scope") == "limited_descriptive_hour00"
             and review.get("provider_protocol_sha256") == STARTUP_POLICY_SHA256
             and review.get("input_index_sha256") == amendment.get("input_index_sha256")
             and len(set(review.get("contract_sha256_set", []))) == 24,
             "Unreviewed or unsupported D019 source provenance")
    for digest in (amendment.get("consumer_amendment_sha256"), amendment.get("input_index_sha256"), review.get("sha256")):
        _require(isinstance(digest, str) and len(digest) == 64 and set(digest) <= set("0123456789abcdef"), "Missing reviewed provenance digest")


def apply_conditional_prediction(participant_dir, model_dir, output_dir, expected_model_hashes, expected_amendment):
    """Run only after reviewed fitting, in the exact runtime with the external resource guard.

    Expected model hashes and amendment are caller-frozen trusted bindings. Pickles
    are executable artifacts; their bytes are checked before deserialization.
    """
    require_fit_runtime()
    _require(digest_json(PROTOCOL) == SOURCE_PROTOCOL_SHA256, "Frozen source protocol changed")
    np.random.seed(PROTOCOL["new_pilot_seed"])
    participant, models, output = map(Path, (participant_dir, model_dir, output_dir))
    _require(not output.exists() or not any(output.iterdir()), "Fresh prediction output directory required")
    names = {f"model_{name}_{seed}.pkl" for name, seed in STREAMS} | {"run_context.json", "frozen_policies.json"}
    _require(set(expected_model_hashes) == names, "All six frozen model streams and context/policy hashes required")
    context = json.loads(_bound_bytes(models/"run_context.json", expected_model_hashes["run_context.json"]))
    _context(context, expected_amendment)
    policies = json.loads(_bound_bytes(models/"frozen_policies.json", expected_model_hashes["frozen_policies.json"]))
    _require(len(policies) == 6 and {(p["model"], p["seed"]) for p in policies} == set(STREAMS)
             and all(p.get("origin") == "exploratory_real" for p in policies), "All six real frozen policies required")
    settings = {(p["model"], p["seed"]): p["settings"] for p in policies}
    keys = {f"schedule_{ms}" for ms in (0, 100, 500)} | {f"confidence_{ms}_{fee}" for ms in (0, 100, 500) for fee in (0, 1, 5)}
    _require(all(set(value) == keys for value in settings.values()), "Every frozen policy scenario required")
    day, participant_files = _participant(participant)
    model_bytes = {name: _bound_bytes(models/name, expected_model_hashes[name]) for name in names if name.endswith(".pkl")}
    output.mkdir(parents=True, exist_ok=True)
    records, probabilities = [], {}
    for name, seed in STREAMS:
        model = pickle.loads(model_bytes[f"model_{name}_{seed}.pkl"])
        _require(list(model.classes_) == [0, 1, 2], "Probability class columns changed")
        p = model.predict_proba(day["X"])
        result = evaluate(day, p, settings[(name, seed)])
        _require(len(result["conditions"]) == 27, "All 27 frozen conditions required")
        probabilities[f"{name}_{seed}"] = p
        records.append(dict(origin="exploratory_real", asset="BTC", date="2025-12-01", model=name, seed=seed, **result))
    np.savez_compressed(output/"probabilities.npz", **probabilities, times=day["times"], y=day["y"],
                        origin=np.array("exploratory_real"), empirical_admission=np.array(False), online_admission=np.array(False))
    result = dict(schema="q17-conditional-prediction/1", origin="exploratory_real", new_fits=0, policy_tuning_calls=0,
        scope="Conditional development projection: 16 rows, one scheduling window; no independent-date or generalization inference",
        assumption_ids=PREMISES, empirical_admission=False, online_admission=False, observed_fills=False,
        independent_test_days=0, rows=16, disjoint_scheduling_windows=1, model_streams=6, condition_records=162,
        feature_clock_scope="conditional offline reconstruction with future closure witnesses; no receipt clock",
        utility_scope="hypothetical marginal quote cashflows only", records=records,
        descriptive_mlp_minus_logistic=development_contrasts(records), reviewed_source_amendment=expected_amendment,
        provenance=dict(participant_manifest_sha256=PARTICIPANT_SHA256, conditional_contract_sha256=CONTRACT_SHA256,
            matched_arrays_sha256=participant_files["matched_arrays.npz"], model_hashes=expected_model_hashes,
            implementation_sha256=sha256(__file__), policies_implementation_sha256=sha256(Path(__file__).with_name("policies.py")),
            source_protocol_sha256=digest_json(PROTOCOL), probabilities_sha256=sha256(output/"probabilities.npz")))
    for filename, digest in expected_model_hashes.items():
        _require(sha256(models/filename) == digest, "Model inputs changed during prediction")
    write_json(output/"summary.json", result)
    write_json(output/"manifest.json", {"files": [{"path": path.name, "sha256": sha256(path)}
               for path in sorted(output.iterdir())], "new_fits": 0, "empirical_admission": False, "online_admission": False})
    return result
