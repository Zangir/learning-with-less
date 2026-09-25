"""Synthetic formula checks only; no accepted packet reads or model operations."""
import json
import unittest

import numpy as np

from t016_p4.metrics import (
    decompose, group_row_weights, profile, profile_loss, standardize, weighting_gap,
)


class ProfileTests(unittest.TestCase):
    def test_half_brier_profile_uses_complete_loss_given_true_class(self):
        result = profile(['F', 'A', 'N'], [[.6, .3, .1], [.2, .7, .1], [.1, .1, .8]])
        self.assertEqual(result['class_order'], ['F', 'A', 'N'])
        self.assertEqual(result['class_counts'], {'F': 1, 'A': 1, 'N': 1})
        for name, expected in zip(('F', 'A', 'N'), (.13, .07, .03)):
            self.assertAlmostEqual(result['ell'][name], expected, places=14)
            self.assertAlmostEqual(result['q'][name], 1 / 3, places=14)
        self.assertAlmostEqual(result['total_half_brier'], .23 / 3, places=14)
        self.assertEqual(result['total_loss'], result['total_half_brier'])

    def test_weighted_conditionals_and_total_reconcile(self):
        result = profile_loss(['F', 'F', 'A', 'N'], [1, 3, 2, 4], [1, 3, 2, 4])
        self.assertEqual(result['q'], {'F': .4, 'A': .2, 'N': .4})
        for label, expected in zip(('F', 'A', 'N'), (2.5, 2., 4.)):
            self.assertAlmostEqual(result['ell'][label], expected, places=14)
        self.assertAlmostEqual(result['total_loss'], 3.)
        self.assertAlmostEqual(sum(result['q'][k] * result['ell'][k] for k in result['q']), 3.)

    def test_rescaling_all_row_weights_does_not_change_endpoint(self):
        first = profile_loss([0, 1, 2], [1, 2, 3], [1, 2, 3])
        second = profile_loss([0, 1, 2], [1, 2, 3], [10, 20, 30])
        for key in ('q', 'ell', 'total_loss'):
            self.assertEqual(first[key], second[key])

    def test_signed_pair_losses_are_supported(self):
        result = profile_loss(['F', 'A', 'N'], [-.1, .2, -.3])
        self.assertAlmostEqual(result['total_loss'], -.2 / 3, places=14)
        self.assertLess(result['ell']['F'], 0)
        self.assertLess(result['ell']['N'], 0)
        json.dumps(result, allow_nan=False)

    def test_missing_and_zero_weight_classes_have_no_imputed_conditional(self):
        absent = profile_loss(['F', 'A'], [.1, .2])
        zero_weight = profile_loss(['F', 'A', 'N'], [.1, .2, .9], [1, 1, 0])
        for result in (absent, zero_weight):
            self.assertEqual(result['q']['N'], 0)
            self.assertIsNone(result['ell']['N'])
            self.assertAlmostEqual(result['total_loss'], .15)
        self.assertEqual(zero_weight['class_counts']['N'], 1)

    def test_empty_nonfinite_misaligned_and_negative_weight_inputs_fail(self):
        cases = (
            ([], [], None), ([0], [], None), ([0], [np.nan], None),
            ([0, 1], [0, 1], [1]), ([0, 1], [0, 1], [1, -1]),
            ([0, 1], [0, 1], [0, 0]), ([0], [1], [np.inf]),
        )
        for labels, losses, weights in cases:
            with self.subTest(labels=labels, losses=losses, weights=weights), self.assertRaises(ValueError):
                profile_loss(labels, losses, weights)


class StandardizationTests(unittest.TestCase):
    def test_fixed_class_weights_apply_to_conditionals(self):
        result = standardize(profile_loss(['F', 'A', 'N'], [.1, .4, .7]),
                             {'F': .2, 'A': .3, 'N': .5})
        self.assertEqual(result['status'], 'evaluable')
        self.assertAlmostEqual(result['value'], .49)
        self.assertAlmostEqual(sum(result['class_components'].values()), result['value'])

    def test_missing_positive_weight_class_withholds_entire_standardization(self):
        result = standardize(profile_loss(['F', 'A'], [.1, .2]), [1 / 3] * 3)
        self.assertEqual(result['status'], 'unavailable')
        self.assertEqual(result['missing_classes'], ['N'])
        self.assertIsNone(result['value'])
        self.assertIsNone(result['class_components'])

    def test_zero_reference_weight_does_not_require_unsupported_class(self):
        result = standardize(profile_loss(['F', 'A'], [1, 3]), [.25, .75, 0])
        self.assertEqual(result['status'], 'evaluable')
        self.assertEqual(result['value'], 2.5)
        self.assertEqual(result['class_components']['N'], 0)

    def test_group_conditionals_are_used_instead_of_averaging_daily_standardized_scores(self):
        labels = ['F', 'A', 'N', 'F', 'F', 'F', 'A', 'N']
        losses = [0, 0, 0, 1, 1, 1, 0, 0]
        weights = group_row_weights(['first'] * 3 + ['second'] * 5)
        result = standardize(profile_loss(labels, losses, weights), [1 / 3] * 3)
        self.assertAlmostEqual(result['value'], 3 / 14, places=14)
        self.assertNotAlmostEqual(result['value'], 1 / 6, places=14)

    def test_reference_weights_are_not_silently_normalized(self):
        record = profile_loss(['F', 'A', 'N'], [.1, .2, .3])
        for weights in ([1, 1, 1], [-.1, .5, .6], [.2, .3, np.nan], {'F': 1}):
            with self.subTest(weights=weights), self.assertRaises(ValueError):
                standardize(record, weights)


class DecompositionTests(unittest.TestCase):
    def assert_reconciles(self, result):
        self.assertEqual(result['status'], 'evaluable')
        self.assertAlmostEqual(result['mix'] + result['within'], result['delta'], places=14)
        self.assertAlmostEqual(sum(result['mix_by_class'].values()), result['mix'], places=14)
        self.assertAlmostEqual(sum(result['within_by_class'].values()), result['within'], places=14)
        self.assertAlmostEqual(result['reconciliation_residual'], 0, places=14)

    def test_pure_class_mix_change(self):
        earlier = profile_loss(['F', 'A', 'N'], [.1, .4, .7])
        later = profile_loss(['F', 'F', 'A', 'N'], [.1, .1, .4, .7])
        result = decompose(earlier, later)
        self.assert_reconciles(result)
        self.assertAlmostEqual(result['mix'], -.075)
        self.assertAlmostEqual(result['within'], 0)
        self.assertAlmostEqual(result['mix_by_class']['F'], .1 / 6)

    def test_pure_conditional_loss_change(self):
        earlier = profile_loss(['F', 'A', 'N'], [.1, .2, .3])
        later = profile_loss(['F', 'A', 'N'], [.2, .4, .6])
        result = decompose(earlier, later)
        self.assert_reconciles(result)
        self.assertAlmostEqual(result['mix'], 0)
        self.assertAlmostEqual(result['within'], .2)

    def test_nonzero_components_can_cancel(self):
        earlier = profile_loss(['F', 'F', 'A', 'N'], [0, 0, 1, 1])
        later = profile_loss(['F', 'A', 'N', 'N'], [0, 1, .5, .5])
        result = decompose(earlier, later)
        self.assert_reconciles(result)
        self.assertEqual(result['delta'], 0)
        self.assertEqual(result['mix'], .25)
        self.assertEqual(result['within'], -.25)

    def test_earlier_conditionals_define_mix_first_reference(self):
        earlier = profile_loss(['F', 'F', 'A', 'N'], [0, 0, 1, 1])
        later = profile_loss(['F', 'A', 'N', 'N'], [0, 1, .5, .5])
        forward, reverse = decompose(earlier, later), decompose(later, earlier)
        self.assert_reconciles(reverse)
        self.assertNotEqual(forward['mix'], -reverse['mix'])
        self.assertEqual(reverse['mix'], -.125)
        self.assertEqual(reverse['within'], .125)

    def test_any_absent_class_withholds_even_when_it_disappears_or_is_absent_both_times(self):
        complete = profile_loss(['F', 'A', 'N'], [.1, .2, .3])
        missing = profile_loss(['F', 'A'], [.1, .2])
        for earlier, later in ((missing, complete), (complete, missing), (missing, missing)):
            result = decompose(earlier, later)
            self.assertEqual(result['status'], 'unavailable')
            self.assertEqual(result['missing_classes'], ['N'])
            self.assertEqual(result['delta'], later['total_loss'] - earlier['total_loss'])
            for key in ('mix', 'within', 'mix_by_class', 'within_by_class', 'reconciliation_residual'):
                self.assertIsNone(result[key])
            json.dumps(result, allow_nan=False)

    def test_signed_pair_loss_components_equal_difference_of_arm_components(self):
        y_e, y_l = ['F', 'F', 'A', 'N'], ['F', 'A', 'N', 'N']
        a_e, a_l = np.array([.3, .5, .2, .1]), np.array([.7, .4, .3, .1])
        b_e, b_l = np.array([.1, .2, .5, .3]), np.array([.4, .2, .2, .2])
        a = decompose(profile_loss(y_e, a_e), profile_loss(y_l, a_l))
        b = decompose(profile_loss(y_e, b_e), profile_loss(y_l, b_l))
        pair = decompose(profile_loss(y_e, a_e - b_e), profile_loss(y_l, a_l - b_l))
        self.assert_reconciles(pair)
        for key in ('delta', 'mix', 'within'):
            self.assertAlmostEqual(pair[key], a[key] - b[key], places=14)
        for key in ('mix_by_class', 'within_by_class'):
            for label in ('F', 'A', 'N'):
                self.assertAlmostEqual(pair[key][label], a[key][label] - b[key][label], places=14)


class WeightingTests(unittest.TestCase):
    def test_equal_day_and_pooled_weights_preserve_row_order(self):
        dates = ['first', 'second', 'first', 'first']
        np.testing.assert_allclose(group_row_weights(dates), [1 / 6, .5, 1 / 6, 1 / 6])
        np.testing.assert_array_equal(group_row_weights(dates, 'pooled'), [.25] * 4)

    def test_weighting_gap_and_each_date_contribution_reconcile(self):
        result = weighting_gap({'first': .2, 'second': .8}, {'first': 3, 'second': 1})
        self.assertAlmostEqual(result['pooled'], .35)
        self.assertAlmostEqual(result['equal_day'], .5)
        self.assertAlmostEqual(result['gap'], -.15)
        self.assertAlmostEqual(result['per_date']['first']['contribution'], .05)
        self.assertAlmostEqual(result['per_date']['second']['contribution'], -.2)
        self.assertAlmostEqual(sum(row['contribution'] for row in result['per_date'].values()), result['gap'])
        self.assertAlmostEqual(result['reconciliation_residual'], 0)

    def test_group_profiles_match_the_two_original_endpoint_weights(self):
        dates = ['first', 'first', 'first', 'second']
        labels, losses = ['F', 'A', 'N', 'F'], [.2, .2, .2, .8]
        equal = profile_loss(labels, losses, group_row_weights(dates))
        pooled = profile_loss(labels, losses, group_row_weights(dates, 'pooled'))
        gap = weighting_gap({'first': .2, 'second': .8}, {'first': 3, 'second': 1})
        self.assertAlmostEqual(equal['total_loss'], gap['equal_day'])
        self.assertAlmostEqual(pooled['total_loss'], gap['pooled'])

    def test_equal_counts_or_identical_daily_loss_remove_gap(self):
        for means, counts in (({'a': .1, 'b': .9}, {'a': 2, 'b': 2}),
                              ({'a': .7, 'b': .7}, {'a': 1, 'b': 9})):
            result = weighting_gap(means, counts)
            self.assertAlmostEqual(result['gap'], 0)
            self.assertAlmostEqual(result['reconciliation_residual'], 0)

    def test_invalid_or_missing_date_support_is_not_silently_reweighted(self):
        for means, counts in (({}, {}), ({'a': .2}, {'b': 1}),
                              ({'a': .2, 'b': .4}, {'a': 1, 'b': 0}),
                              ({'a': np.nan}, {'a': 1}), ({'a': .2}, {'a': 1.5})):
            with self.subTest(means=means, counts=counts), self.assertRaises(ValueError):
                weighting_gap(means, counts)
        for dates in ([], [['a']], ['a', None]):
            with self.subTest(dates=dates), self.assertRaises(ValueError):
                group_row_weights(dates)
        with self.assertRaises(ValueError):
            group_row_weights(['a'], 'outcome_selected')


if __name__ == '__main__':
    unittest.main()
