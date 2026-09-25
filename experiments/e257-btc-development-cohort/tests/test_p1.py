"""Independent deterministic P1 fixtures; never open a market file or fit a model."""
import copy
import math
import unittest

import numpy as np

from t016_p0.engine import NS, Observations, OpportunityState
from t016_p1.features import (
    AUX_INPUT_NAMES, EVENT_FIELDS, TARGET_NAMES, X_NAMES, Z_NAMES,
    embed_coarse_coefficients, inverse_target_scaling, raw_book,
    readiness_reason, views,
)
from t016_p1.labels import label_event


def synthetic_row(time_ns, ordinal, mid2=20000, depth=5, segment=0):
    bid = (mid2 - 2) // 2
    ask = mid2 - bid
    return {
        "event_ns": time_ns, "source_ordinal": ordinal, "segment_id": segment,
        "source_id": "synthetic-p1-fixture", "disconnect_epoch": 0,
        "bid_prices_units8": [bid - i for i in range(depth)],
        "ask_prices_units8": [ask + i for i in range(depth)],
        "bid_sizes_units8": [100 + i for i in range(depth)],
        "ask_sizes_units8": [200 + i for i in range(depth)],
        "bid_counts": [10 + i for i in range(depth)],
        "ask_counts": [20 + i for i in range(depth)],
    }


def make_observations(rows, end=200 * NS):
    segments = [{"segment_id": sid, "start_ns": 0, "end_ns": 300 * NS}
                for sid in sorted({item["segment_id"] for item in rows})]
    return Observations(rows, segments, 0, end)


def frozen_event(family="breakout", side="resistance", mid2=20000,
                 numerator=200, denominator=1, second=100):
    direction = 1 if side == "resistance" else -1
    if family == "rebound":
        direction = -direction
    return {
        "event_id": "synthetic-event", "decision_ns": second * NS,
        "family": family, "side": side, "direction": direction,
        "segment_id": 0, "decision_mid2": mid2, "level_mid2": mid2 - 2000,
        "epsilon2": {"numerator": numerator, "denominator": denominator},
        "status": "recorded", "frozen_features": [1, 2, 3],
    }


def path_observations(event, signed_moves=None, last_k=11):
    signed_moves = signed_moves or {}
    return make_observations([
        synthetic_row(event["decision_ns"] + k * NS, k + 1,
                      event["decision_mid2"] + event["direction"] * signed_moves.get(k, 0))
        for k in range(last_k + 1)
    ])


class LabelBoundaryTests(unittest.TestCase):
    def test_first_hit_inclusive_edges_and_no_hit(self):
        cases = (
            ("favorable_equality", {1: 400}, "F", 1),
            ("adverse_equality", {1: -200}, "A", 1),
            ("neither", {}, "N", None),
            ("strictly_inside", {k: 399 if k % 2 else -199 for k in range(1, 11)}, "N", None),
            ("favorable_first", {1: 400, 2: -200}, "F", 1),
            ("adverse_first", {1: -200, 2: 400}, "A", 1),
            ("last_required_cut", {10: 400}, "F", 10),
            ("after_horizon", {11: 400}, "N", None),
        )
        for name, moves, label, first in cases:
            with self.subTest(name=name):
                event = frozen_event()
                result = label_event(path_observations(event, moves), event)
                self.assertEqual(result["label"], label)
                self.assertEqual(result["first_hit_k"], first)
                expected_cut = None if first is None else (100 + first) * NS
                self.assertEqual(result["first_hit_cut_ns"], expected_cut)
                self.assertTrue(result["complete_future_support"])
                self.assertEqual(len(result["future_refs"]), 10)
                self.assertEqual(result["future_refs"][-1]["cut_ns"], 110 * NS)

    def test_direction_for_every_family_side_combination(self):
        for family, side, direction in (
            ("breakout", "resistance", 1), ("breakout", "support", -1),
            ("rebound", "resistance", -1), ("rebound", "support", 1),
        ):
            for movement, expected in ((400, "F"), (-200, "A")):
                with self.subTest(family=family, side=side, movement=movement):
                    event = frozen_event(family, side)
                    self.assertEqual(event["direction"], direction)
                    obs = path_observations(event, {1: movement})
                    self.assertEqual(obs.grid[101 * NS]["mid2"] - event["decision_mid2"],
                                     direction * movement)
                    self.assertEqual(label_event(obs, event)["label"], expected)

    def test_fractional_epsilon_and_odd_midpoint_are_exact(self):
        for movement, expected in ((2, "N"), (3, "F"), (-1, "N"), (-2, "A")):
            with self.subTest(movement=movement):
                event = frozen_event(mid2=20001, numerator=3, denominator=2)
                obs = path_observations(event, {k: movement for k in range(1, 11)})
                self.assertEqual(obs.grid[100 * NS]["mid2"], 20001)
                self.assertEqual(label_event(obs, event)["label"], expected)

    def test_barriers_are_centered_on_decision_not_level(self):
        event = frozen_event()
        event["level_mid2"] = 10000
        result = label_event(path_observations(event), event)
        self.assertEqual(result["label"], "N")

    def test_full_horizon_required_after_either_early_hit(self):
        for early_movement in (400, -200):
            with self.subTest(early_movement=early_movement):
                event = frozen_event()
                obs = path_observations(event, {1: early_movement}, last_k=9)
                result = label_event(obs, event)
                self.assertFalse(result["complete_future_support"])
                self.assertIsNone(result["label"])
                self.assertIsNone(result["first_hit_k"])
                self.assertIsNone(result["first_hit_cut_ns"])
                self.assertEqual(result["first_bad_cut_ns"], 110 * NS)
                self.assertEqual(len(result["future_refs"]), 10)

    def test_future_segment_change_censors_before_any_class(self):
        event = frozen_event()
        rows = [synthetic_row((100 + k) * NS, k + 1, 20400 if k == 1 else 20000,
                              segment=0 if k < 7 else 1) for k in range(12)]
        result = label_event(make_observations(rows), event)
        self.assertEqual(result["censor_reason"], "segment_change")
        self.assertEqual(result["first_bad_cut_ns"], 107 * NS)
        self.assertIsNone(result["label"])

    def test_future_age_equality_passes_one_nanosecond_stale_censors(self):
        event = frozen_event()
        for offset, complete in ((0, True), (-1, False)):
            with self.subTest(offset=offset):
                times = [100 * NS, 100 * NS + NS // 2 + offset,
                         102 * NS + NS // 2 + offset]
                times.extend(t * NS for t in range(103, 112))
                obs = make_observations([synthetic_row(t, i + 1) for i, t in enumerate(times)])
                self.assertEqual(obs.grid[102 * NS]["age_ns"], 1_500_000_000 - offset)
                result = label_event(obs, event)
                self.assertEqual(result["complete_future_support"], complete)
                if complete:
                    self.assertEqual(result["label"], "N")
                else:
                    self.assertEqual(result["censor_reason"], "stale_asof")
                    self.assertIsNone(result["label"])

    def test_half_open_endpoint_censors_and_never_borrows_later_row(self):
        event = frozen_event()
        rows = [synthetic_row((100 + k) * NS, k + 1) for k in range(12)]
        obs = make_observations(rows, end=110 * NS)
        result = label_event(obs, event)
        self.assertEqual(result["first_bad_cut_ns"], 110 * NS)
        self.assertEqual(result["censor_reason"], "outside_retained_support")
        self.assertIsNone(result["label"])

    def test_future_bbo_invalidity_censors_but_extra_depth_absence_does_not(self):
        event = frozen_event()
        for crossed in (False, True):
            with self.subTest(crossed=crossed):
                rows = [synthetic_row((100 + k) * NS, k + 1, depth=1 if k == 4 else 5)
                        for k in range(12)]
                if crossed:
                    rows[4]["bid_prices_units8"][0] = rows[4]["ask_prices_units8"][0]
                obs = make_observations(rows)
                result = label_event(obs, event)
                if crossed:
                    self.assertEqual(result["censor_reason"], "crossed_or_locked_bbo")
                    self.assertIsNone(result["label"])
                else:
                    self.assertEqual(obs.grid[104 * NS]["depth_rejection"], "missing_depth")
                    self.assertEqual(result["label"], "N")

    def test_invalid_frozen_direction_and_epsilon_fail(self):
        for change in ({"direction": 0}, {"direction": -1},
                       {"epsilon2": {"numerator": 0, "denominator": 1}},
                       {"epsilon2": {"numerator": -1, "denominator": 1}}):
            with self.subTest(change=change):
                event = frozen_event()
                obs = path_observations(event)
                event.update(change)
                with self.assertRaisesRegex(ValueError, "Invalid frozen event"):
                    label_event(obs, event)

    def test_labeling_is_nonmutating_and_censor_does_not_refund_state(self):
        state = OpportunityState()
        first = frozen_event(family="rebound", second=120)
        first.update(anchor_ns=120 * NS, past_rejection=None)
        self.assertEqual(state.process([first])[0]["status"], "recorded")
        before_event = copy.deepcopy(first)
        before_state = (state.slots.copy(), state.last_recorded.copy())
        obs = path_observations(first, last_k=9)
        before_grid = copy.deepcopy(obs.grid)
        self.assertIsNone(label_event(obs, first)["label"])
        self.assertEqual(first, before_event)
        self.assertEqual(obs.grid, before_grid)
        self.assertEqual((state.slots, state.last_recorded), before_state)
        for second, expected in ((125, "cooldown"), (131, None)):
            item = frozen_event(family="rebound", side="support", second=second)
            item.update(anchor_ns=120 * NS, past_rejection=None)
            self.assertEqual(state.process([item])[0]["reason"], expected)

    def test_prefix_label_comparison_requires_whole_common_horizon(self):
        event = frozen_event()
        short = path_observations(event, {1: 400}, last_k=9)
        finalized = path_observations(event, {1: 400}, last_k=10)
        extended = path_observations(event, {1: 400, 11: -200}, last_k=11)
        self.assertIsNone(label_event(short, event)["label"])
        self.assertEqual(label_event(finalized, event), label_event(extended, event))


def feature_fixture():
    unit = 100_000_000
    item = {
        "bid_prices_units8": [p * unit for p in (99, 98, 97, 96, 95)],
        "ask_prices_units8": [p * unit for p in (101, 102, 103, 104, 105)],
        "bid_sizes_units8": [q * unit for q in (1, 1, 2, 3, 4)],
        "ask_sizes_units8": [q * unit for q in (2, 2, 2, 2, 2)],
        "bid_counts": [5, 2, 3, 4, 5], "ask_counts": [6, 6, 7, 8, 9],
    }
    books = [raw_book(copy.deepcopy(item)) for _ in range(61)]
    level = {"resistance_mid2": 204 * unit, "support_mid2": 196 * unit,
             "epsilon2": {"numerator": 2 * unit, "denominator": 1}}
    event = {"family": "breakout", "side": "resistance"}
    return books, [0] * 61, 600 * NS, level, event


class FeatureInformationTests(unittest.TestCase):
    def test_dimensions_and_current_target_coordinate_order(self):
        x, z, target = views(*feature_fixture())
        self.assertEqual((len(x), len(z), len(target)), (446, 1464, 7))
        self.assertEqual((len(X_NAMES), len(Z_NAMES), len(AUX_INPUT_NAMES)), (446, 1464, 440))
        self.assertEqual(TARGET_NAMES, ["log1p_Qb", "log1p_Qa", "log1p_Nb", "log1p_Na",
                                       "depth_imbalance", "Db_bps", "Da_bps"])
        expected = [math.log(11), math.log(9), math.log(15), math.log(31), 1 / 9, 400, 350]
        np.testing.assert_allclose(target, expected, rtol=1e-12, atol=1e-12)
        self.assertAlmostEqual(x[X_NAMES.index("lag0.bid_offset_bps")], -100., places=10)
        self.assertEqual(x[X_NAMES.index("return_60s_bps")], 0.)
        self.assertEqual(x[X_NAMES.index("return_1s_population_std_bps")], 0.)

    def test_extra_depth_cannot_change_coarse_x(self):
        inputs = feature_fixture()
        original_x, original_z, original_target = views(*inputs)
        changed = copy.deepcopy(inputs)
        for book in changed[0]:
            for offset in (0, 15):
                for index in range(1, 5):
                    book[offset + 5 + index] *= 3 if offset == 0 else 2
                    book[offset + 10 + index] += 10
        new_x, new_z, new_target = views(*changed)
        np.testing.assert_array_equal(original_x, new_x)
        self.assertFalse(np.array_equal(original_z, new_z))
        self.assertFalse(np.array_equal(original_target, new_target))

    def test_auxiliary_input_excludes_every_event_and_level_field(self):
        original = feature_fixture()
        changed = copy.deepcopy(original)
        changed[3]["resistance_mid2"] += 500_000_000
        changed[3]["support_mid2"] -= 300_000_000
        changed[3]["epsilon2"]["numerator"] *= 2
        changed[4].update(family="rebound", side="support")
        first_x, _, _ = views(*original)
        second_x, _, _ = views(*changed)
        self.assertFalse(set(AUX_INPUT_NAMES).intersection(EVENT_FIELDS))
        self.assertEqual(X_NAMES[-6:], EVENT_FIELDS)
        np.testing.assert_array_equal(first_x[:440], second_x[:440])
        self.assertFalse(np.array_equal(first_x[440:], second_x[440:]))

    def test_current_auxiliary_targets_do_not_use_earlier_depth(self):
        original = feature_fixture()
        changed = copy.deepcopy(original)
        for book in changed[0][:-1]:
            for offset in (0, 15):
                for index in range(1, 5):
                    book[offset + 5 + index] *= 4
        _, old_z, old_target = views(*original)
        _, new_z, new_target = views(*changed)
        self.assertFalse(np.array_equal(old_z, new_z))
        np.testing.assert_array_equal(old_target, new_target)

    def test_outcome_and_future_support_metadata_do_not_enter_views(self):
        original = feature_fixture()
        changed = copy.deepcopy(original)
        changed[4].update(label="F", complete_future_support=False,
                          censor_reason="stale_asof", future_age_ns=9 * NS)
        for before, after in zip(views(*original), views(*changed)):
            np.testing.assert_array_equal(before, after)

    def test_age_feature_keeps_seconds_and_freshness_boundary(self):
        values = feature_fixture()
        values[1][-1] = 1_500_000_000
        x, _, _ = views(*values)
        self.assertEqual(x[X_NAMES.index("lag0.asof_age_seconds")], 1.5)
        self.assertEqual(x[X_NAMES.index("freshness")], 0.)
        values[1][-1] += 1
        with self.assertRaises(AssertionError):
            views(*values)


class CoordinateAndPurgeTests(unittest.TestCase):
    def test_l1_fold_inversion_restores_common_coordinates(self):
        physical = np.array([math.log(11), math.log(9), math.log(15), math.log(31),
                             1 / 9, 400., 350.])
        first_mean, first_scale = np.zeros(7), np.ones(7)
        second_mean = np.array([10., 1., -5., 2., -.2, 100., 250.])
        second_scale = np.array([2., 3., 1., 4., .5, 20., 5.])
        first = inverse_target_scaling((physical - first_mean) / first_scale,
                                       first_mean, first_scale)
        second = inverse_target_scaling((physical - second_mean) / second_scale,
                                        second_mean, second_scale)
        np.testing.assert_allclose(first, physical, rtol=1e-12, atol=1e-12)
        np.testing.assert_allclose(second, physical, rtol=1e-12, atol=1e-12)
        self.assertAlmostEqual(second[0], math.log(11))  # Inversion does not turn log-size into BTC.
        np.testing.assert_array_equal(inverse_target_scaling([3., -7.], [0., 10.], [1., 1.]),
                                      [3., 3.])

    def test_l2_coefficient_embedding_preserves_logits_for_arbitrary_extra_depth(self):
        coefficients = np.array([[1., -2., .5], [-1., 3., 2.], [0., .25, -.5]])
        original = coefficients.copy()
        intercept = np.array([.3, -.2, .1])
        x = np.array([[1., 2., 3.], [-2., 5., 0.]])
        z = np.array([[1000., -500.], [8000., 1.]])
        embedded = embed_coarse_coefficients(coefficients, 5)
        np.testing.assert_array_equal(embedded[:, 3:], np.zeros((3, 2)))
        np.testing.assert_array_equal(coefficients, original)
        expected = x @ coefficients.T + intercept
        actual = np.concatenate((x, z), axis=1) @ embedded.T + intercept
        np.testing.assert_allclose(actual, expected, rtol=0, atol=1e-12)
        self.assertEqual(embedded.shape, (3, 5))
        with self.assertRaisesRegex(ValueError, "every coarse column"):
            embed_coarse_coefficients(coefficients, 2)

    def test_full_dependency_interval_purge_is_half_open(self):
        event = {"dependency_min_ns": 1000 * NS, "dependency_max_ns": 2000 * NS - 1}
        self.assertIsNone(readiness_reason(event, 1000 * NS, 2000 * NS))
        left = dict(event, dependency_min_ns=1000 * NS - 1)
        right = dict(event, dependency_max_ns=2000 * NS)
        self.assertEqual(readiness_reason(left, 1000 * NS, 2000 * NS), "dependency_crosses_partition")
        self.assertEqual(readiness_reason(right, 1000 * NS, 2000 * NS), "dependency_crosses_partition")

    def test_exact_130_second_embargo_passes_one_nanosecond_short_fails(self):
        event = {"dependency_min_ns": 230 * NS, "dependency_max_ns": 300 * NS,
                 "decision_ns": 290 * NS}
        self.assertIsNone(readiness_reason(event, 0, 1000 * NS, earlier_dependency_end=100 * NS))
        too_close = dict(event, dependency_min_ns=230 * NS - 1)
        self.assertEqual(readiness_reason(too_close, 0, 1000 * NS, earlier_dependency_end=100 * NS),
                         "dependency_embargo_130s")

    def test_accepted_level_range_exactly_four_epsilon_is_admitted(self):
        for minimum, expected_valid in ((19984, True), (19985, False)):
            with self.subTest(minimum=minimum):
                rows = [synthetic_row(t * NS, t + 1, minimum if t == 0 else 20000)
                        for t in range(60)]
                level = make_observations(rows).level(60 * NS)
                self.assertEqual(level["epsilon2"]["numerator"], 4)
                self.assertEqual(level["epsilon2"]["denominator"], 1)
                self.assertEqual(level["valid"], expected_valid)
                if expected_valid:
                    self.assertEqual(level["resistance_mid2"] - level["support_mid2"], 16)
                else:
                    self.assertEqual(level["reason"], "range_below_4epsilon")


if __name__ == "__main__":
    unittest.main()
