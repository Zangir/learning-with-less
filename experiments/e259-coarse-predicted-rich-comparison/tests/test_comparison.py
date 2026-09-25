"""Small no-fit checks of frozen scoring, chronology and scaling semantics."""
import unittest

import numpy as np

from t016_p2.metrics import (
    CLASS_ORDER,
    align_probabilities,
    assert_chronological_fold,
    encode_labels,
    half_brier,
    reference_predictions,
    score_by_day,
    select_candidate,
)
from t016_p2.models import PopulationScaler


MENU = (
    'logistic-C0.1', 'logistic-C1',
    'hgb-leaf7-l21', 'hgb-leaf7-l20',
    'hgb-leaf15-l21', 'hgb-leaf15-l20',
)


class ClassAlignmentTests(unittest.TestCase):
    def test_class_order_is_f_a_n(self):
        self.assertEqual(CLASS_ORDER, ('F', 'A', 'N'))

    def test_string_and_numeric_labels_have_identical_encoding(self):
        expected = np.array([2, 0, 1, 0])
        np.testing.assert_array_equal(encode_labels(['N', 'F', 'A', 'F']), expected)
        np.testing.assert_array_equal(encode_labels(expected), expected)

    def test_invalid_labels_are_rejected(self):
        for labels in (['F', 'censored'], [-1, 0], [0, 3], [0, 1.5], [np.nan]):
            with self.subTest(labels=labels), self.assertRaises(ValueError):
                encode_labels(labels)

    def test_labels_must_be_a_vector(self):
        with self.assertRaises(ValueError):
            encode_labels([['F', 'A', 'N']])

    def test_string_estimator_columns_are_reordered(self):
        actual = align_probabilities([[.2, .1, .7]], ['A', 'N', 'F'])
        np.testing.assert_array_equal(actual, [[.7, .2, .1]])

    def test_numeric_estimator_columns_are_reordered(self):
        actual = align_probabilities([[.1, .7, .2]], [2, 0, 1])
        np.testing.assert_array_equal(actual, [[.7, .2, .1]])

    def test_missing_duplicate_and_unknown_classes_are_rejected(self):
        for classes in (['F', 'A'], ['F', 'A', 'A'], ['F', 'A', 'unknown']):
            with self.subTest(classes=classes), self.assertRaises(ValueError):
                align_probabilities([[.7, .2, .1]], classes)

    def test_malformed_probability_shape_is_rejected(self):
        for probabilities in ([.7, .2, .1], [[.7, .3]], [[[.7, .2, .1]]]):
            with self.subTest(probabilities=probabilities), self.assertRaises(ValueError):
                align_probabilities(probabilities, CLASS_ORDER)

    def test_invalid_probabilities_are_not_repaired(self):
        invalid = (
            [[.7, .2, np.nan]], [[.7, .2, np.inf]],
            [[1.1, -.1, 0]], [[.7, .2, .2]],
        )
        for probabilities in invalid:
            with self.subTest(probabilities=probabilities), self.assertRaises(ValueError):
                align_probabilities(probabilities, CLASS_ORDER)


class ProperScoreTests(unittest.TestCase):
    def test_perfect_wrong_and_uniform_score_scale(self):
        actual = half_brier(['F', 'A', 'N'], [[1, 0, 0], [1, 0, 0], [1 / 3] * 3])
        np.testing.assert_allclose(actual, [0, 1, 1 / 3], rtol=0, atol=1e-15)

    def test_nontrivial_half_brier_is_per_row(self):
        probabilities = [[.7, .2, .1], [.1, .8, .1], [.1, .3, .6]]
        expected = [.07, .03, .13]
        for labels in (['F', 'A', 'N'], [0, 1, 2]):
            with self.subTest(labels=labels):
                np.testing.assert_allclose(half_brier(labels, probabilities), expected,
                                           rtol=0, atol=1e-15)

    def test_label_probability_row_mismatch_is_rejected(self):
        with self.assertRaises(ValueError):
            half_brier(['F', 'A'], [[1, 0, 0]])

    def test_equal_day_score_does_not_pool_unequal_day_sizes(self):
        result = score_by_day(
            ['F', 'F', 'F', 'A'], [[1, 0, 0]] * 4,
            ['2025-05-01'] * 3 + ['2025-06-01'],
        )
        self.assertEqual(result['per_day']['2025-05-01']['n'], 3)
        self.assertEqual(result['per_day']['2025-06-01']['n'], 1)
        self.assertEqual(result['per_day']['2025-05-01']['half_brier'], 0)
        self.assertEqual(result['per_day']['2025-06-01']['half_brier'], 1)
        self.assertEqual(result['equal_day_half_brier'], .5)
        self.assertNotEqual(result['equal_day_half_brier'], .25)

    def test_class_counts_include_zero_classes(self):
        result = score_by_day(['F', 'F', 'A'], [[1, 0, 0]] * 3, ['2025-04-01'] * 3)
        self.assertEqual(result['per_day']['2025-04-01']['class_counts'],
                         {'F': 2, 'A': 1, 'N': 0})

    def test_one_vs_rest_components_are_unhalved_binary_scores(self):
        day = score_by_day(['A'], [[1, 0, 0]], ['2025-05-01'])['per_day']['2025-05-01']
        self.assertEqual(day['one_vs_rest_brier'], {'F': 1, 'A': 1, 'N': 0})
        self.assertEqual(.5 * sum(day['one_vs_rest_brier'].values()), day['half_brier'])

    def test_nontrivial_components_recover_daily_primary_score(self):
        result = score_by_day(['F', 'A', 'N'],
                              [[.7, .2, .1], [.1, .8, .1], [.1, .3, .6]],
                              ['2025-07-01'] * 3)
        day = result['per_day']['2025-07-01']
        self.assertAlmostEqual(.5 * sum(day['one_vs_rest_brier'].values()),
                               day['half_brier'], places=15)

    def test_empty_or_misaligned_dates_are_rejected(self):
        with self.assertRaises(ValueError):
            score_by_day(['F'], [[1, 0, 0]], [])
        with self.assertRaises(ValueError):
            score_by_day([], np.empty((0, 3)), [])


class AbsoluteReferenceTests(unittest.TestCase):
    def test_exact_reference_menu_and_fixed_columns(self):
        predictions = reference_predictions(['F', 'A', 'N'], 2)
        self.assertEqual(set(predictions),
                         {'onehot-F', 'onehot-A', 'onehot-N', 'uniform', 'train-frequency'})
        for index, label in enumerate(CLASS_ORDER):
            expected = np.tile(np.eye(3)[index], (2, 1))
            np.testing.assert_array_equal(predictions[f'onehot-{label}'], expected)
        np.testing.assert_allclose(predictions['uniform'], np.full((2, 3), 1 / 3))

    def test_training_frequency_uses_unit_event_counts(self):
        predictions = reference_predictions(['F', 'F', 'A', 'N', 'N', 'N'], 4)
        expected = np.tile([1 / 3, 1 / 6, 1 / 2], (4, 1))
        np.testing.assert_array_equal(predictions['train-frequency'], expected)

    def test_reference_encoding_and_requested_length_do_not_change_constants(self):
        string = reference_predictions(['F', 'F', 'A', 'N'], 1)
        numeric = reference_predictions([0, 0, 1, 2], 7)
        for name in string:
            np.testing.assert_array_equal(numeric[name], np.tile(string[name], (7, 1)))

    def test_missing_training_class_prevents_reference_comparison(self):
        with self.assertRaises(ValueError):
            reference_predictions(['F', 'A', 'F'], 2)


class FrozenSelectionTests(unittest.TestCase):
    def test_exact_tie_uses_menu_not_score_insertion_order(self):
        scores = {candidate: .4 for candidate in reversed(MENU)}
        self.assertEqual(select_candidate(scores, MENU), MENU[0])

    def test_best_tie_uses_first_tied_menu_entry(self):
        scores = dict.fromkeys(MENU, .5)
        scores.update({candidate: .2 for candidate in MENU[2:]})
        self.assertEqual(select_candidate(scores, MENU), MENU[2])

    def test_near_tie_is_not_rounded_into_exact_tie(self):
        scores = dict.fromkeys(MENU, .4)
        # Exact ties do not need a fuzzy committee.
        scores[MENU[-1]] = np.nextafter(.4, -np.inf)
        self.assertEqual(select_candidate(scores, MENU), MENU[-1])

    def test_record_menu_preserves_frozen_priority(self):
        self.assertEqual(select_candidate(dict.fromkeys(MENU, .3),
                                          [{'id': candidate} for candidate in MENU]), MENU[0])

    def test_any_missing_required_score_withholds_selection(self):
        for absent in MENU:
            scores = {candidate: .3 for candidate in MENU if candidate != absent}
            with self.subTest(absent=absent):
                self.assertIsNone(select_candidate(scores, MENU))

    def test_any_failed_required_score_withholds_selection(self):
        for failed_value in (None, np.nan, np.inf, -np.inf):
            scores = dict.fromkeys(MENU, .3)
            scores[MENU[-1]] = failed_value
            with self.subTest(failed_value=failed_value):
                self.assertIsNone(select_candidate(scores, MENU))


class ChronologyTests(unittest.TestCase):
    def test_all_three_frozen_auxiliary_folds_are_chronological(self):
        folds = (
            (['2025-01-01'], ['2025-02-01']),
            (['2025-01-01', '2025-02-01'], ['2025-03-01']),
            (['2025-01-01', '2025-02-01', '2025-03-01'],
             ['2025-04-01', '2025-05-01', '2025-06-01', '2025-07-01']),
        )
        for training, prediction in folds:
            with self.subTest(training=training, prediction=prediction):
                self.assertIsNone(assert_chronological_fold(training, prediction))

    def test_repeated_unsorted_dates_do_not_change_guard(self):
        self.assertIsNone(assert_chronological_fold(
            ['2025-02-01', '2025-01-01', '2025-02-01'],
            ['2025-04-01', '2025-03-01', '2025-03-01']))

    def test_same_day_overlap_and_future_training_are_rejected(self):
        for training in (['2025-03-01'], ['2025-02-01', '2025-03-01'], ['2025-04-01']):
            with self.subTest(training=training), self.assertRaises(ValueError):
                assert_chronological_fold(training, ['2025-03-01'])

    def test_empty_fold_members_are_rejected(self):
        for training, prediction in (([], ['2025-02-01']), (['2025-01-01'], [])):
            with self.subTest(training=training, prediction=prediction), self.assertRaises(ValueError):
                assert_chronological_fold(training, prediction)


class PopulationScalingTests(unittest.TestCase):
    def test_population_moments_and_zero_variance_scale(self):
        scaler = PopulationScaler.from_training([[1, 7, 2], [3, 7, 6]])
        np.testing.assert_array_equal(scaler.means, [2, 7, 4])
        np.testing.assert_array_equal(scaler.scales, [1, 1, 2])
        np.testing.assert_array_equal(scaler.transform([[1, 7, 2], [3, 7, 6]]),
                                      [[-1, 0, -1], [1, 0, 1]])

    def test_evaluation_transform_preserves_training_moments(self):
        scaler = PopulationScaler.from_training([[1, 7, 2], [3, 7, 6]])
        means, scales = scaler.means.copy(), scaler.scales.copy()
        evaluation = [[11, 9, 20], [-3, 8, -8]]
        transformed = scaler.transform(evaluation)
        np.testing.assert_array_equal(scaler.means, means)
        np.testing.assert_array_equal(scaler.scales, scales)
        np.testing.assert_allclose(scaler.inverse(transformed), evaluation, rtol=0, atol=1e-15)

    def test_fold_specific_standardized_targets_invert_to_common_coordinates(self):
        first = PopulationScaler.from_training([[2, 4], [4, 6]])
        second = PopulationScaler.from_training([[12, 14], [16, 18]])
        common = np.array([[4, 6]])
        self.assertFalse(np.array_equal(first.transform(common), second.transform(common)))
        np.testing.assert_array_equal(first.inverse(first.transform(common)), common)
        np.testing.assert_array_equal(second.inverse(second.transform(common)), common)

    def test_inverse_retains_log_coordinates_for_first_four_targets(self):
        means = np.array([2., 3., 4., 5., .2, 10., 12.])
        scales = np.array([1., 2., 3., 4., .1, 2., 3.])
        scaler = PopulationScaler.from_training(np.stack([means - scales, means + scales]))
        standardized_prediction = np.ones((1, 7))
        expected_common_coordinates = (means + scales)[None, :]
        np.testing.assert_allclose(scaler.inverse(standardized_prediction),
                                   expected_common_coordinates, rtol=0, atol=1e-14)

    def test_invalid_training_matrices_are_rejected(self):
        for values in ([], [1, 2], [[1, np.nan]], [[np.inf, 1]]):
            with self.subTest(values=values), self.assertRaises(ValueError):
                PopulationScaler.from_training(values)


if __name__ == '__main__':
    unittest.main()
