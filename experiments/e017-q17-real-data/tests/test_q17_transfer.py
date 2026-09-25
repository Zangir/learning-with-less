"""Invariant checks use authored quotes only; no empirical metric is implied."""
import json
import tempfile
import unittest
from pathlib import Path
import numpy as np
from q17_transfer.features import build_arrays, NS
from q17_transfer.gate import (REQUIRED, require_certificates, sha256, inspect_shared_contract,
                               implementation_sha256, PILOT_START_NS, PILOT_END_NS)
from q17_transfer.protocol import PROTOCOL, LABEL_SPEC, digest_json, model_specs
from q17_transfer.pilot import development_contrasts, run_development
from q17_transfer.policies import (round_trip, best_threshold, threshold_mask, schedule_values,
                                   best_schedule, schedule_indices, schedule_inputs, tune, evaluate)


def fixture():
    t = np.arange(401, dtype=np.int64)*NS
    mid = 100+np.arange(len(t))*0.01
    return dict(event_ns=t, available_ns=t+NS//4, known_ns=t.copy(),
                bid=mid-0.1, ask=mid+0.1, bid_size=np.ones(len(t))*2, ask_size=np.ones(len(t)))


class FeatureTests(unittest.TestCase):
    def test_separate_clocks_and_exact_features(self):
        q = fixture()
        a = build_arrays(q, "validation", 0, 401*NS)
        self.assertEqual(a["times"][0], 21*NS)
        self.assertEqual(a["feature_indices"][0].tolist(), [20, 19, 15, 0])
        self.assertEqual(a["label_indices"][0].tolist(), [21, 31])
        np.testing.assert_allclose(a["X"][0], [1/3, 0.2/100.2*10000,
            (100.2/100.19-1)*10000, (100.2/100.15-1)*10000, (100.2/100-1)*10000])
        self.assertEqual(a["X"].shape[1], 5)

    def test_future_quotes_cannot_change_past_features(self):
        q = fixture()
        before = build_arrays(q, "validation", 0, 401*NS)
        q["bid"][22:] += 30; q["ask"][22:] += 30
        after = build_arrays(q, "validation", 0, 401*NS)
        np.testing.assert_array_equal(before["X"][0], after["X"][0])

    def test_inversion_rejected_without_sorting(self):
        for clock in ("event_ns", "available_ns"):
            q = fixture(); q[clock][30] = q[clock][28]
            with self.assertRaisesRegex(ValueError, "inversion"):
                build_arrays(q, "validation", 0, 401*NS)

    def test_future_admission_and_crossed_quotes_rejected(self):
        q = fixture(); q["known_ns"][20] = 40*NS
        with self.assertRaisesRegex(ValueError, "evidence"):
            build_arrays(q, "validation", 0, 401*NS)
        q = fixture(); q["bid"][20] = q["ask"][20]
        with self.assertRaisesRegex(ValueError, "BBO"):
            build_arrays(q, "validation", 0, 401*NS)

    def test_ties_take_final_supplied_state(self):
        q = fixture(); q["event_ns"][22] = 21*NS; q["available_ns"][21:23] = 21*NS
        q["known_ns"][22] = 21*NS
        a = build_arrays(q, "validation", 0, 401*NS)
        self.assertEqual(a["feature_indices"][0, 0], 22)
        self.assertEqual(a["label_indices"][0, 0], 22)

    def test_block_guards_and_strides(self):
        q = fixture(); a = build_arrays(q, "train", 100*NS, 200*NS)
        self.assertTrue((a["times"] >= 121*NS).all())
        self.assertTrue((a["times"]+10.5*NS < 200*NS).all())
        np.testing.assert_array_equal(np.diff(a["times"]), 5*NS)
        with self.assertRaisesRegex(ValueError, "UTC date"):
            build_arrays(q, "test", 0, 86401*NS)

    def test_later_blocks_with_causal_delayed_release(self):
        for delay in (2, 60):
            q = fixture(); q["available_ns"] = q["event_ns"]+delay*NS
            a = build_arrays(q, "validation", 100*NS, 300*NS)
            self.assertEqual(a["times"][0], (121+delay)*NS)
            self.assertTrue((q["event_ns"][a["feature_indices"]] >= 100*NS).all())
            self.assertTrue((a["outcome_available_ns"] > a["times"]+10*NS).all())


class UtilityTests(unittest.TestCase):
    def test_linear_cashflow_long_short_flat_and_fees(self):
        day = dict(times=np.arange(3), entry_ask=np.full((3, 1), 100.), entry_bid=np.full((3, 1), 100.),
                   exit_bid=np.full((3, 1), 110.), exit_ask=np.full((3, 1), 90.))
        values, _, _ = round_trip(day, np.eye(3)[[2, 0, 1]], 0, 5)
        np.testing.assert_allclose(values, [989.5, 990.5, 0])
        # Quote cashflow = side*q*(exit-entry) - fee*q*(entry+exit).
        self.assertAlmostEqual(values[0], (110-100-.0005*(100+110))/100*10000)

    def test_spread_and_flat_price_cost(self):
        day = dict(times=np.arange(3), entry_ask=np.full((3, 1), 101.), entry_bid=np.full((3, 1), 99.),
                   exit_bid=np.full((3, 1), 99.), exit_ask=np.full((3, 1), 101.))
        v, _, _ = round_trip(day, np.eye(3), 0, 5)
        self.assertLess(v[0], 0); self.assertLess(v[2], 0); self.assertEqual(v[1], 0)

    def test_confidence_ties_abstention_and_opportunity_denominator(self):
        scores = np.array([.9, .8, .8, .7]); values = np.array([4., 2., -2., -9.])
        setting = best_threshold(scores, values, np.ones(4, bool))
        self.assertEqual(setting["threshold"], .9)
        self.assertEqual(setting["validation_mean"], 1.)
        self.assertEqual(setting["validation_trades"], 1)
        flat = best_threshold(scores, -np.ones(4), np.ones(4, bool))
        self.assertTrue(flat["all_flat"])
        self.assertFalse(threshold_mask(scores, np.ones(4, bool), flat).any())

    def test_linear_schedule_cost_and_benchmark(self):
        prices = np.array([[90., 100., 110.]])
        np.testing.assert_allclose(schedule_values(prices, np.array([0]), 5), [1000.5])
        np.testing.assert_allclose(schedule_values(prices, np.array([1]), 5), [0.])
        self.assertAlmostEqual(schedule_values(prices, np.array([0]), 5)[0], (100*1.0005-90*1.0005)/100*10000)

    def test_schedule_causal_first_hit_and_ties(self):
        scores = np.array([[-.2, .5, .9], [.1, .2, .3]])
        setting = dict(mode="threshold", threshold=.4)
        np.testing.assert_array_equal(schedule_indices(scores, setting), [1, 2])
        scores[0, 2] = -999
        self.assertEqual(schedule_indices(scores, setting)[0], 1)
        self.assertEqual(best_schedule(scores, np.ones((2, 3))*100)["mode"], "always_wait")

    def test_schedule_preserves_windows_and_drops_only_tail(self):
        a = build_arrays(fixture(), "test", 0, 401*NS)
        p = np.full((len(a["times"]), 3), 1/3)
        scores, prices = schedule_inputs(a, p, 0)
        self.assertEqual(scores.shape, (len(p)//12, 12))
        a["times"][20] += NS
        with self.assertRaisesRegex(ValueError, "contiguous"):
            schedule_inputs(a, p, 0)

    def test_matched_evaluation_and_frozen_policy(self):
        a = build_arrays(fixture(), "test", 0, 401*NS)
        p = np.tile([.1, .1, .8], (len(a["times"]), 1))
        settings = tune(a, p); frozen = json.dumps(settings, sort_keys=True)
        result = evaluate(a, p, settings)
        self.assertEqual(json.dumps(settings, sort_keys=True), frozen)
        self.assertEqual(len(result["conditions"]), 27)
        self.assertTrue(all(c["n"] == (len(p)//12 if c["policy"] == "scheduling" else len(p)) for c in result["conditions"]))

    def test_original_models_and_seeds(self):
        specs = list(model_specs())
        self.assertEqual([(n, s) for n, s, _ in specs], [("prior", 0), ("logistic", 0), ("hist_gb", 17), ("mlp", 17), ("mlp", 29), ("mlp", 41)])
        self.assertEqual(specs[-1][2].get_params()["mlpclassifier__hidden_layer_sizes"], (24,))

    def test_seed_metrics_are_averaged_and_counts_matched(self):
        records = []
        for name, seed, value in (("logistic", 0, 1.), ("mlp", 17, 2.), ("mlp", 29, 3.), ("mlp", 41, 4.)):
            records.append(dict(model=name, seed=seed, macro_f1=value, accuracy=value, log_loss=value, multiclass_brier=value,
                conditions=[dict(policy="argmax", delay_ms=100, fee_bps=5, utility_bps=value, n=30)]))
        result = development_contrasts(records)
        self.assertEqual(result["macro_f1"], 2.)
        self.assertEqual(result["conditions"][0]["difference_bps"], 2.)
        records[-1]["conditions"][0]["n"] = 29
        with self.assertRaisesRegex(ValueError, "Different eligible"):
            development_contrasts(records)


class CertificateTests(unittest.TestCase):
    def test_missing_gate_stops_before_fitting(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "Missing"):
                require_certificates(Path(tmp)/"data", Path(tmp)/"labels", Path(tmp)/"review")
            with self.assertRaisesRegex(ValueError, "Missing"):
                run_development(Path(tmp)/"data", Path(tmp)/"labels", Path(tmp)/"review", Path(tmp)/"output")
            self.assertFalse((Path(tmp)/"output").exists())

    def test_hash_review_negative_assertion_and_payload_gates(self):
        # These are isolated authored test objects, never scientific certificates.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); payload = root/"quotes.npz"; payload.write_bytes(b"test fixture")
            d, l, r = [root/name for name in ("data.json", "labels.json", "review.json")]
            shared = root/"shared.json"
            shared.write_text(json.dumps(dict(contract_id="T-008-shared-data", version="fixture-1", status="certified",
                scopes={"Q17": {"admissible": True}}, admissible_windows=[dict(window_id="synthetic-fixture", scope="Q17", asset="BTC",
                    date="2025-12-01", start_ns=PILOT_START_NS, end_ns=PILOT_END_NS)])), encoding="utf-8")
            data = dict(schema_version="q17-input-certificate/1", issuer="T-008", status="affirmative",
                        window_id="synthetic-fixture",
                        shared_contract_file="shared.json", shared_contract_sha256=sha256(shared),
                        assertions={k: True for k in REQUIRED}, availability_kind="causal_delayed_release",
                        purpose="december1_development", asset="BTC", date="2025-12-01", data_file="quotes.npz", data_sha256=sha256(payload))
            def write(path, obj):
                path.write_text(json.dumps(obj), encoding="utf-8")
            write(d, data)
            labels = dict(schema_version="q17-label-certificate/1", issuer="T-008", status="affirmative",
                          data_certificate_sha256=sha256(d), label_spec_sha256=digest_json(LABEL_SPEC))
            write(l, labels)
            review = dict(schema_version="q17-coordinator-review/1", status="approved", reviewer_role="coordinator",
                          implementation_sha256=implementation_sha256(),
                          data_certificate_sha256=sha256(d), label_certificate_sha256=sha256(l), protocol_sha256=digest_json(PROTOCOL))
            write(r, review)
            self.assertEqual(require_certificates(d, l, r)["data_file"], payload)
            review["protocol_sha256"] = "stale"; write(r, review)
            with self.assertRaisesRegex(ValueError, "stale"):
                require_certificates(d, l, r)
            review["protocol_sha256"] = digest_json(PROTOCOL); write(r, review)
            payload.write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "checksum"):
                require_certificates(d, l, r)
            data["assertions"]["availability_causal"] = False; write(d, data)
            with self.assertRaisesRegex(ValueError, "assertions"):
                require_certificates(d, l, r)

    def test_pending_shared_contract_is_not_admission(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/"shared.json"
            path.write_text(json.dumps(dict(contract_id="T-008-shared-data", version="0.1-pending",
                scopes={"Q17": {"admissible": False, "reason": "BBO not certified"}}, admissible_windows=[])), encoding="utf-8")
            self.assertFalse(inspect_shared_contract(path)["admitted"])

    def test_revoked_unrelated_and_short_windows_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/"shared.json"
            window = dict(window_id="fixture", scope="Q17", asset="BTC", date="2025-12-01", start_ns=PILOT_START_NS, end_ns=PILOT_END_NS)
            contract = dict(contract_id="T-008-shared-data", version="1.0", status="revoked",
                            scopes={"Q17": {"admissible": True}}, admissible_windows=[window])
            path.write_text(json.dumps(contract)); self.assertFalse(inspect_shared_contract(path)["admitted"])
            contract["status"] = "certified"; window["scope"] = "Q18"
            path.write_text(json.dumps(contract)); self.assertFalse(inspect_shared_contract(path)["admitted"])
            window["scope"] = "Q17"; window["end_ns"] = PILOT_END_NS-1
            path.write_text(json.dumps(contract)); self.assertFalse(inspect_shared_contract(path)["admitted"])
            contract["admissible_windows"] = ["unsupported schema"]
            path.write_text(json.dumps(contract)); self.assertFalse(inspect_shared_contract(path)["admitted"])


if __name__ == "__main__":
    unittest.main()
