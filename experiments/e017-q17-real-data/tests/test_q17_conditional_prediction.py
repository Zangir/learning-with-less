"""Authored placeholder-only prediction guards; no archive data or real fits."""
import copy
import hashlib
import json
import pickle
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from q17_transfer import conditional_prediction as prediction


class PredictionOnlyEstimator:
    classes_ = np.array([0, 1, 2])
    calls = 0

    def fit(self, *args, **kwargs):
        raise AssertionError("Training has no cameo in this projection")

    def predict_proba(self, X):
        type(self).calls += 1
        return np.tile([0.45, 0.2, 0.35], (len(X), 1))


class ReorderedEstimator(PredictionOnlyEstimator):
    classes_ = np.array([2, 1, 0])


def write(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


def amendment_fixture():
    return dict(schema="q17-reviewed-source-amendment/1", base_predeclaration_sha256=prediction.BASE_PREDECLARATION_SHA256,
        provider_protocol_sha256=prediction.STARTUP_POLICY_SHA256, period="hour00", startup_exclusion_ns=30_000_000_000,
        adaptation_class="SOURCE-QUALITY-INFORMED POST-ACQUISITION PRE-FIT", model_policy_constants_unchanged=True,
        input_index_sha256="a"*64, consumer_amendment_sha256="b"*64,
        review=dict(review_id="RV-011", reviewer_task="T-013", decision="supported_exact_hour00_inputs",
            scope="limited_descriptive_hour00", input_index_sha256="a"*64,
            provider_protocol_sha256=prediction.STARTUP_POLICY_SHA256, sha256="c"*64,
            contract_sha256_set=[hashlib.sha256(str(i).encode()).hexdigest() for i in range(24)]))


class ConditionalPredictionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.participant, self.models = self.root/"authored_participant", self.root/"authored_models"
        self.participant.mkdir()
        self.models.mkdir()
        self.amendment = amendment_fixture()
        self.context = dict(origin="exploratory_real", asset="BTC", period="hour00",
            roles={**prediction.LEARNING_ROLES, "2025-05-01": "test", "2026-01-01": "test"},
            freeze_checks={"train": dict(evidence_ready_ns=1740787200000000000, next_first_decision_ns=1743465600000000000),
                           "validation": dict(evidence_ready_ns=1743469200000000000, next_first_decision_ns=1746057600000000000)},
            reviewed_source_amendment=copy.deepcopy(self.amendment))
        labels = np.arange(16, dtype=np.int8) % 3
        bid = np.full((16, 3), 8_700_000_000_000, dtype=np.int64)
        ask = bid+100_000_000
        delta = (labels.astype(np.int64)-1)[:, None]*100_000_000
        self.day = dict(times=np.arange(16, dtype=np.int64)*11_000_000_000+1764550623000000000,
            X=np.arange(80).reshape(16, 5)/100, y=labels,
            delays_ms=np.array([0, 100, 500]), schedule_rows=np.arange(12).reshape(1, 12),
            origin=np.array("exploratory_real"), scope=np.array("conditional_offline_under_P1_P2_L1_L2_P4"),
            empirical_admission=np.array(False), online_admission=np.array(False),
            entry_bid_units8=bid, entry_ask_units8=ask, exit_bid_units8=bid+delta, exit_ask_units8=ask+delta)
        for name in ("entry_bid", "entry_ask", "exit_bid", "exit_ask"):
            self.day[name] = self.day[name+"_units8"]/100_000_000
        self.rows = dict(assumption_ids=prediction.PREMISES, conditional_offline_only=True,
            rows=[dict(decision_ns=int(t), feature_vector=X.tolist(), label_id=int(y))
                  for t, X, y in zip(self.day["times"], self.day["X"], labels)])
        self.manifest = dict(assumption_ids=prediction.PREMISES, source_contract_sha256=prediction.CONTRACT_SHA256,
            origin="exploratory_real", new_fits=0, empirical_admission=False, online_admission=False)
        settings = {f"schedule_{ms}": dict(mode="always_wait", threshold=None) for ms in (0, 100, 500)}
        settings.update({f"confidence_{ms}_{fee}": dict(all_flat=False, threshold=0.4)
                         for ms in (0, 100, 500) for fee in (0, 1, 5)})
        self.policies = [dict(origin="exploratory_real", model=name, seed=seed, settings=copy.deepcopy(settings))
                         for name, seed in prediction.STREAMS]
        for name, seed in prediction.STREAMS:
            (self.models/f"model_{name}_{seed}.pkl").write_bytes(pickle.dumps(PredictionOnlyEstimator()))
        self.seal_participant()
        self.seal_models()
        PredictionOnlyEstimator.calls = 0

    def seal_participant(self):
        np.savez_compressed(self.participant/"matched_arrays.npz", **self.day)
        write(self.participant/"decision_rows.json", self.rows)
        self.manifest["files"] = [dict(path=name, sha256=prediction.sha256(self.participant/name))
                                   for name in ("matched_arrays.npz", "decision_rows.json")]
        write(self.participant/"manifest.json", self.manifest)
        self.participant_hash = prediction.sha256(self.participant/"manifest.json")

    def seal_models(self):
        write(self.models/"run_context.json", self.context)
        write(self.models/"frozen_policies.json", self.policies)
        self.hashes = {path.name: prediction.sha256(path) for path in self.models.iterdir()}

    def invoke(self, output=None, expected_amendment=None):
        with patch.object(prediction, "PARTICIPANT_SHA256", self.participant_hash), \
                patch("q17_transfer.policies.tune", side_effect=AssertionError("No policy tuning")) as tune, \
                patch("q17_transfer.pilot.tune", side_effect=AssertionError("No policy tuning")), \
                patch("q17_transfer.pilot.fit_evaluate", side_effect=AssertionError("No fitting")):
            result = prediction.apply_conditional_prediction(self.participant, self.models, output or self.root/"output",
                self.hashes, self.amendment if expected_amendment is None else expected_amendment)
            tune.assert_not_called()
            return result

    def test_six_predictions_all_conditions_preserve_labels_and_do_not_fit(self):
        result = self.invoke()
        self.assertEqual(PredictionOnlyEstimator.calls, 6)
        self.assertEqual((result["new_fits"], result["policy_tuning_calls"], result["condition_records"]), (0, 0, 162))
        self.assertFalse(result["online_admission"] or result["empirical_admission"] or result["observed_fills"])
        self.assertEqual(result["assumption_ids"], prediction.PREMISES)
        self.assertEqual(result["provenance"]["model_hashes"], self.hashes)
        for record in result["records"]:
            self.assertEqual((record["origin"], record["asset"], record["date"]), ("exploratory_real", "BTC", "2025-12-01"))
            self.assertEqual(len(record["conditions"]), 27)
            self.assertEqual({c["n"] for c in record["conditions"] if c["policy"] == "scheduling"}, {1})
        with np.load(self.root/"output"/"probabilities.npz", allow_pickle=False) as saved:
            np.testing.assert_array_equal(saved["times"], self.day["times"])
            np.testing.assert_array_equal(saved["y"], self.day["y"])
        self.assertTrue((self.root/"output"/"manifest.json").is_file())

    def test_equal_integer_midpoints_remain_flat_despite_float_midpoint_difference(self):
        for name, price in (("entry_bid", 8799999900001), ("entry_ask", 8800000100001),
                            ("exit_bid", 8799999900002), ("exit_ask", 8800000100000)):
            self.day[name+"_units8"][0, 0] = price
            self.day[name] = self.day[name+"_units8"]/100_000_000
        self.day["y"][0] = 1
        self.rows["rows"][0]["label_id"] = 1
        self.seal_participant()
        self.assertNotEqual((self.day["entry_bid"][0, 0]+self.day["entry_ask"][0, 0])/2,
                            (self.day["exit_bid"][0, 0]+self.day["exit_ask"][0, 0])/2)
        self.invoke()
        with np.load(self.root/"output"/"probabilities.npz", allow_pickle=False) as saved:
            self.assertEqual(saved["y"][0], 1)

    def test_future_training_and_post_december_learning_evidence_rejected(self):
        original = copy.deepcopy(self.context)
        for mutation in (lambda c: c["roles"].update({"2025-12-08": "train"}),
                         lambda c: c["freeze_checks"]["validation"].update(evidence_ready_ns=prediction.DECEMBER_START_NS,
                                                                          next_first_decision_ns=prediction.DECEMBER_START_NS+1)):
            self.context = copy.deepcopy(original)
            mutation(self.context)
            self.seal_models()
            with self.assertRaisesRegex(ValueError, "January|before December"):
                self.invoke()
        self.assertEqual(PredictionOnlyEstimator.calls, 0)

    def test_synthetic_wrong_asset_and_full_day_contexts_rejected(self):
        for key, value in (("origin", "synthetic_integration"), ("asset", "ETH"), ("period", "full_day")):
            original = self.context[key]
            self.context[key] = value
            self.seal_models()
            with self.assertRaisesRegex(ValueError, "real BTC hour00"):
                self.invoke()
            self.context[key] = original
        self.assertEqual(PredictionOnlyEstimator.calls, 0)

    def test_missing_mismatched_or_plan_only_review_rejected(self):
        for amendment in (None, {}, {**self.amendment, "input_index_sha256": "d"*64},
                          {**self.amendment, "review": {**self.amendment["review"], "decision": "plan_only"}}):
            self.context["reviewed_source_amendment"] = amendment
            self.seal_models()
            with self.assertRaisesRegex(ValueError, "reviewed|unsupported"):
                self.invoke(expected_amendment=amendment if amendment else {})
        self.assertEqual(PredictionOnlyEstimator.calls, 0)

    def test_all_model_seeds_and_policy_seeds_required(self):
        missing = self.hashes.pop("model_mlp_41.pkl")
        with self.assertRaisesRegex(ValueError, "All six frozen model"):
            self.invoke()
        self.hashes["model_mlp_41.pkl"] = missing
        self.policies[-1]["seed"] = 29
        self.seal_models()
        with self.assertRaisesRegex(ValueError, "All six real frozen policies"):
            self.invoke()
        self.assertEqual(PredictionOnlyEstimator.calls, 0)

    def test_changed_pickle_rejected_before_deserialization(self):
        (self.models/"model_mlp_41.pkl").write_bytes(b"corrupt pickle")
        with patch.object(prediction.pickle, "loads", side_effect=AssertionError("Must verify all hashes first")):
            with self.assertRaisesRegex(ValueError, "Checksum mismatch"):
                self.invoke()

    def test_participant_hash_tamper_rejected(self):
        for name in ("manifest.json", "matched_arrays.npz"):
            path = self.participant/name
            original = path.read_bytes()
            path.write_bytes(original+b" ")
            with self.assertRaisesRegex(ValueError, "checksum|Checksum"):
                self.invoke()
            path.write_bytes(original)
        self.assertEqual(PredictionOnlyEstimator.calls, 0)

    def test_resealed_changed_times_labels_and_admission_fail_semantics(self):
        original = {name: value.copy() for name, value in self.day.items()}
        for field in ("times", "y", "online_admission"):
            self.day = {name: value.copy() for name, value in original.items()}
            if field == "online_admission":
                self.day[field] = np.array(True)
            else:
                self.day[field][0] += 1
            self.seal_participant()
            with self.assertRaisesRegex(ValueError, "decisions|labels|admission"):
                self.invoke()
        self.assertEqual(PredictionOnlyEstimator.calls, 0)

    def test_changed_premise_and_class_column_order_rejected(self):
        self.manifest["assumption_ids"] = prediction.PREMISES[:-1]
        self.seal_participant()
        with self.assertRaisesRegex(ValueError, "premise"):
            self.invoke()
        self.manifest["assumption_ids"] = prediction.PREMISES
        self.seal_participant()
        (self.models/"model_prior_0.pkl").write_bytes(pickle.dumps(ReorderedEstimator()))
        self.seal_models()
        with self.assertRaisesRegex(ValueError, "class columns"):
            self.invoke()
        self.assertEqual(PredictionOnlyEstimator.calls, 0)

    def test_fresh_output_and_all_frozen_policy_scenarios_required(self):
        output = self.root/"existing_output"
        output.mkdir()
        (output/"keep.txt").write_text("existing evidence", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Fresh"):
            self.invoke(output=output)
        self.policies[0]["settings"].pop("confidence_500_5")
        self.seal_models()
        with self.assertRaisesRegex(ValueError, "Every frozen policy"):
            self.invoke()
        self.assertEqual(PredictionOnlyEstimator.calls, 0)


if __name__ == "__main__":
    unittest.main()
