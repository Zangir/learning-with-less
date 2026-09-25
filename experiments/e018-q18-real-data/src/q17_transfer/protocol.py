"""Frozen scientific constants. Runtime/library differences remain explicit."""
import hashlib
import json

PROTOCOL = {
    "version": "T-010/E-017/v1",
    "source_code_commit": "7320f9112d8ba1ac6229c1c3ebeca42ce58bfd9e",
    "source_paper_commit": "38ee01b9bb737098e086ab3616a913ac5d129906",
    "new_pilot_seed": 20260919,
    "mlp_seeds": [17, 29, 41],
    "bootstrap_seed": 17029001,
    "fit_packages": {"numpy": "2.3.5", "pandas": "2.3.3", "scipy": "1.16.3", "scikit-learn": "1.8.0",
                     "matplotlib": "3.10.8", "requests": "2.32.4"},
    "horizon_seconds": 10,
    "lookbacks_seconds": [1, 5, 20],
    "train_stride_seconds": 5,
    "evaluation_stride_seconds": 11,
    "training_cap_per_day": 6000,
    "schedule_width": 12,
    "fees_bps_per_side": [0, 1, 5],
    "scenario_delays_ms": [0, 100, 500],
    "primary_fee_bps": 5,
    "primary_delay_ms": 100,
    "target": "sign(event_mid(t+10s)-event_mid(t))+1: down=0, flat=1, up=2",
    "round_trip": "10000*side*(exit/entry-1)-fee_bps*(1+exit/entry); flat=0",
    "scheduling": "10000*(1+fee_bps/10000)*(mean(ask)-selected_ask)/mean(ask)",
    "scheduling_quantity": "one fixed base quantity; equal base quantity per TWAP slot",
    "normalization": "round-trip: entry notional; scheduling: pre-fee arithmetic TWAP notional",
    "freeze_rule": "all outcome evidence must arrive before next block first decision; next-event watermark",
    "eligibility": "common certified uninterrupted BBO interval, all features/labels/delays",
    "availability": "actual receipt or explicit causal delayed release; never offline clock join",
    "scope": "exogenous marginal quote utility, no fills/funding/impact/profit claim",
    "primary_estimand": "MLP minus logistic; seed endpoint means within paired date",
    "original_joint_rule": {
        "assets": ["BTC", "ETH"], "independent_dates": 8,
        "f1_lower_gt": 0.02, "utility_upper_lt_bps": -0.1,
        "required_policies": 2, "required_negative_dates": 6,
        "simultaneous_contrasts": 8, "bootstrap_replicates": 10000,
        "intervals": "Bonferroni percentile bootstrap hull with Bonferroni t(df=7)",
        "original_result": "failed; zero policy families passed on both assets",
    },
    "development_pilot": {
        "date": "2025-12-01", "asset": "BTC", "independent_test_days": 0,
        "blocks_utc": ["00:00-00:20 train", "00:20-00:40 policy selection", "00:40-01:00 evaluation"],
        "status": "proposed conditional diagnostic; all three blocks are development",
        "final_dates": "untouched and unassigned; coordinator must freeze future independent days",
    },
}

LABEL_SPEC = {"version": "q17-label/1", "horizon_ns": 10_000_000_000,
              "clock": "certified exchange event", "lookup": "last atomic final state <= cutoff",
              "classes": ["down", "flat", "up"], "magnitude_threshold": 0,
              "cross_day": False}


def digest_json(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def model_specs():
    """Exact original model settings; import lazily so gating needs no estimator."""
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    from sklearn.dummy import DummyClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.neural_network import MLPClassifier
    yield "prior", 0, DummyClassifier(strategy="prior")
    yield "logistic", 0, make_pipeline(StandardScaler(), LogisticRegression(max_iter=1000, C=1.0))
    yield "hist_gb", 17, HistGradientBoostingClassifier(max_iter=100, max_leaf_nodes=15,
            l2_regularization=1.0, early_stopping=False, random_state=17)
    for seed in PROTOCOL["mlp_seeds"]:
        yield "mlp", seed, make_pipeline(StandardScaler(), MLPClassifier(hidden_layer_sizes=(24,),
            max_iter=400, early_stopping=False, batch_size=256, alpha=0.0001,
            learning_rate_init=0.001, random_state=seed))
