"""No-fit synthetic estimator-state tests; no market files or learned parameters."""
import unittest
from unittest.mock import patch

import numpy as np
from sklearn._loss.loss import HalfMultinomialLoss
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.ensemble._hist_gradient_boosting.binning import _BinMapper
from sklearn.ensemble._hist_gradient_boosting.common import PREDICTOR_RECORD_DTYPE
from sklearn.ensemble._hist_gradient_boosting.predictor import TreePredictor
from sklearn.linear_model import LogisticRegression

from t016_p2.embeddings import check_embedding, embed_coarse_model


def synthetic_logistic():
    model = LogisticRegression(solver="lbfgs")
    model.classes_ = np.array([0, 1, 2])
    model.n_features_in_ = 446
    model.coef_ = np.zeros((3, 446), dtype=np.float64)
    model.coef_[:, 0] = [.2, -.1, .4]
    model.coef_[:, 445] = [-.3, .2, .1]
    model.intercept_ = np.array([.1, -.2, .05])
    model.n_iter_ = np.array([0])
    return model


def synthetic_stump(feature, threshold, left_value, right_value):
    nodes = np.zeros(3, dtype=PREDICTOR_RECORD_DTYPE)
    nodes["count"] = [2, 1, 1]
    nodes["feature_idx"][0] = feature
    nodes["num_threshold"][0] = threshold
    nodes["left"][0], nodes["right"][0] = 1, 2
    nodes["missing_go_to_left"][0] = 1
    nodes["is_leaf"][1:] = 1
    nodes["depth"][1:] = 1
    nodes["value"][1:] = [left_value, right_value]
    return TreePredictor(nodes, np.zeros((0, 8), dtype=np.uint32),
                         np.zeros((0, 8), dtype=np.uint32))


def synthetic_hgb():
    model = HistGradientBoostingClassifier(categorical_features=None, early_stopping=False)
    model.classes_ = np.array([0, 1, 2])
    model.n_features_in_ = model._n_features = 446
    model.n_trees_per_iteration_ = 3
    model._baseline_prediction = np.array([[.1, -.2, .05]])
    model._loss = HalfMultinomialLoss(n_classes=3)
    model._preprocessor = None
    model.is_categorical_ = model._is_categorical_remapped = None
    model._bin_mapper = _BinMapper()
    model._bin_mapper.is_categorical_ = np.zeros(446, dtype=np.uint8)
    model._bin_mapper.bin_thresholds_ = [np.empty(0) for _ in range(446)]
    model._predictors = [
        [synthetic_stump(0, 0., left, right)
         for left, right in zip((.2, -.3, .1), (-.4, .2, .05))],
        [synthetic_stump(445, .5, left, right)
         for left, right in zip((.1, .05, -.15), (-.2, .3, -.1))],
    ]
    return model


def matrices():
    coarse = np.zeros((3, 446), dtype=np.float64)
    coarse[:, 0] = [-1., 0., 1.]
    coarse[:, 445] = [-1., .5, 1.]
    depth = np.full((3, 1464), 12345., dtype=np.float64)
    return coarse, np.concatenate((coarse, depth), axis=1)


class EmbeddingTests(unittest.TestCase):
    def setUp(self):
        self.lr_patch = patch.object(LogisticRegression, "fit", side_effect=AssertionError("Fit forbidden"))
        self.hgb_patch = patch.object(HistGradientBoostingClassifier, "fit", side_effect=AssertionError("Fit forbidden"))
        self.lr_fit = self.lr_patch.start()
        self.hgb_fit = self.hgb_patch.start()

    def tearDown(self):
        self.lr_fit.assert_not_called()
        self.hgb_fit.assert_not_called()
        self.lr_patch.stop()
        self.hgb_patch.stop()

    def test_logistic_copy_uses_full_rich_layout_and_zero_depth_coefficients(self):
        model = synthetic_logistic()
        original = model.coef_.copy()
        embedded, description = embed_coarse_model(model)
        self.assertEqual(embedded.n_features_in_, 1910)
        self.assertEqual(model.n_features_in_, 446)
        self.assertEqual(embedded.coef_.shape, (3, 1910))
        np.testing.assert_array_equal(model.coef_, original)
        np.testing.assert_array_equal(embedded.coef_[:, :446], original)
        np.testing.assert_array_equal(embedded.coef_[:, 446:], np.zeros((3, 1464)))
        self.assertEqual(description["added_depth_nonzero_coefficients"], 0)
        result = check_embedding(model, *matrices())
        self.assertTrue(result["passed"])
        self.assertLessEqual(result["max_abs_probability_difference"], 1e-10)
        self.assertEqual(result["embedding"]["fit_calls"], 0)

    def test_tree_embedding_preserves_branch_equality_and_known_logits(self):
        model = synthetic_hgb()
        coarse, rich = matrices()
        embedded, description = embed_coarse_model(model)
        expected_logits = np.array([[.4, -.45, 0.], [.4, -.45, 0.], [-.5, .3, 0.]])
        exp_values = np.exp(expected_logits - expected_logits.max(axis=1, keepdims=True))
        expected_probabilities = exp_values / exp_values.sum(axis=1, keepdims=True)
        np.testing.assert_allclose(model.predict_proba(coarse), expected_probabilities, atol=1e-14, rtol=0)
        np.testing.assert_allclose(embedded.predict_proba(rich), expected_probabilities, atol=1e-14, rtol=0)
        self.assertEqual((model.n_features_in_, model._n_features), (446, 446))
        self.assertEqual((embedded.n_features_in_, embedded._n_features), (1910, 1910))
        self.assertEqual(description["used_coarse_feature_indices"], [0, 445])
        self.assertEqual((description["tree_count"], description["node_count"]), (6, 18))
        for before_iteration, after_iteration in zip(model._predictors, embedded._predictors):
            for before, after in zip(before_iteration, after_iteration):
                np.testing.assert_array_equal(before.nodes, after.nodes)
                self.assertFalse(np.shares_memory(before.nodes, after.nodes))
        self.assertTrue(check_embedding(model, coarse, rich)["passed"])

    def test_arbitrary_added_depth_cannot_change_embedded_probabilities(self):
        coarse, rich = matrices()
        for factory in (synthetic_logistic, synthetic_hgb):
            with self.subTest(factory=factory.__name__):
                model = factory()
                embedded, _ = embed_coarse_model(model)
                first = embedded.predict_proba(rich)
                changed = rich.copy()
                changed[:, 446:] *= -1000.
                np.testing.assert_array_equal(first, embedded.predict_proba(changed))
                self.assertTrue(check_embedding(model, coarse, changed)["passed"])

    def test_prefix_misalignment_is_not_hidden_by_matching_predictions(self):
        coarse, rich = matrices()
        rich[0, 20] = 1e-7  # This unused coefficient still belongs to the required shared schema.
        with self.assertRaisesRegex(ValueError, "shared-X prefix"):
            check_embedding(synthetic_logistic(), coarse, rich)

    def test_invalid_shape_dtype_and_nonfinite_values_fail(self):
        coarse, rich = matrices()
        for bad_coarse, bad_rich in ((coarse[:0], rich[:0]), (coarse, rich[:-1]),
                                     (coarse.astype(np.float32), rich), (coarse, rich[:, :-1])):
            with self.subTest(shape=bad_rich.shape), self.assertRaises(ValueError):
                check_embedding(synthetic_logistic(), bad_coarse, bad_rich)
        rich[0, -1] = np.inf
        with self.assertRaisesRegex(ValueError, "Nonfinite"):
            check_embedding(synthetic_logistic(), coarse, rich)

    def test_tree_feature_outside_prefix_is_rejected(self):
        model = synthetic_hgb()
        model._predictors[0][0].nodes["feature_idx"][0] = 446
        with self.assertRaisesRegex(ValueError, "non-coarse feature"):
            embed_coarse_model(model)

    def test_unsupported_categorical_tree_is_rejected(self):
        model = synthetic_hgb()
        model._predictors[0][0].nodes["is_categorical"][0] = 1
        with self.assertRaisesRegex(ValueError, "Categorical tree"):
            embed_coarse_model(model)

    def test_probability_failure_is_reported_not_accepted(self):
        model = synthetic_logistic()
        coarse, rich = matrices()
        probabilities = model.predict_proba(coarse)
        changed = probabilities.copy()
        changed[:, 0] += 1e-8
        changed[:, 1] -= 1e-8
        fake = unittest.mock.Mock()
        fake.predict_proba.return_value = changed
        with patch("t016_p2.embeddings.embed_coarse_model", return_value=(fake, {"fit_calls": 0})):
            result = check_embedding(model, coarse, rich)
        self.assertFalse(result["passed"])
        self.assertGreater(result["max_abs_probability_difference"], 1e-10)


if __name__ == "__main__":
    unittest.main()
