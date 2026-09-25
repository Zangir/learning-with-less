"""Authored summary fixtures only: no data acquisition, estimators or real dates."""
import copy
import unittest

import numpy as np
from scipy.stats import t

from q17_transfer.paired_statistics import analyze_paired_dates


DATES = [f"authored-date-{i}" for i in range(8)]
ORIGIN = "synthetic_integration"


def summaries(f1_gap=0.05, utility_gaps=(-0.2, -0.2, 0.0)):
    records = []
    for asset in ("BTC", "ETH"):
        for day in DATES:
            for model, seed in (("logistic", 0), ("mlp", 17), ("mlp", 29), ("mlp", 41)):
                shift = (-0.03, 0, 0.03)[(17, 29, 41).index(seed)] if model == "mlp" else 0
                conditions = []
                for policy, gap in zip(("argmax", "confidence", "scheduling"), utility_gaps):
                    conditions.append(dict(policy=policy, fee_bps=5, delay_ms=100,
                        utility_bps=gap + shift if model == "mlp" else 0.0,
                        n=10 if policy == "scheduling" else 120))
                    conditions.append(dict(policy=policy, fee_bps=0, delay_ms=0,
                        utility_bps=100.0 if model == "mlp" else 0.0,
                        n=10 if policy == "scheduling" else 120))
                records.append(dict(asset=asset, date=day, model=model, seed=seed,
                    origin=ORIGIN, macro_f1=0.4 + f1_gap + shift if model == "mlp" else 0.4,
                    accuracy=0.5, log_loss=1.0, multiclass_brier=0.5, conditions=conditions))
    return records


def analyze(records, dates=DATES):
    return analyze_paired_dates(records, dates, origin=ORIGIN)


class PairedStatisticsTests(unittest.TestCase):
    def test_constant_endpoint_means_pass_and_preserve_origin(self):
        rows = summaries()
        result = analyze(rows)
        self.assertTrue(result["adapted_joint_rule_passed"])
        self.assertEqual(result["passing_policies"], ["argmax", "confidence"])
        self.assertEqual(result["status"], "evaluated")
        self.assertEqual(result["origin"], ORIGIN)
        self.assertEqual(result["original_source_primary"], "failed and not re-evaluated")
        self.assertFalse(result["independence_guarantee"])
        self.assertTrue(result["seed_is_not_an_independent_date"])
        self.assertEqual(len(result["contrasts"]), 8)
        self.assertEqual(len(result["matched_counts"]), 16)
        self.assertEqual(result["records"], rows)
        for c in result["contrasts"]:
            expected = 0.05 if c["metric"] == "macro_f1" else (0 if c["metric"] == "scheduling" else -0.2)
            self.assertAlmostEqual(c["mean"], expected)
            self.assertEqual(c["negative_dates"], 8 if expected < 0 else 0)

    def test_absent_forecast_advantage_cannot_be_rescued_by_utilities(self):
        result = analyze(summaries(f1_gap=-0.01, utility_gaps=(-0.2, -0.2, -0.2)))
        self.assertFalse(result["forecast_gate"])
        self.assertFalse(result["adapted_joint_rule_passed"])
        self.assertEqual(len(result["passing_policies"]), 3)

    def test_two_different_asset_policy_sets_do_not_pass_joint_rule(self):
        rows = summaries()
        for row in rows:
            if row["asset"] == "ETH" and row["model"] == "mlp":
                for c in row["conditions"]:
                    if (c["fee_bps"], c["delay_ms"]) == (5, 100):
                        if c["policy"] == "confidence":
                            c["utility_bps"] = 0.0
                        elif c["policy"] == "scheduling":
                            c["utility_bps"] = -0.2
        result = analyze(rows)
        self.assertEqual(result["passing_policies"], ["argmax"])
        self.assertFalse(result["adapted_joint_rule_passed"])

    def test_all_abstain_confidence_tie_does_not_supply_second_policy(self):
        rows = summaries(utility_gaps=(-0.2, 0.0, 0.0))
        for row in rows:
            for c in row["conditions"]:
                if c["policy"] == "confidence":
                    c.update(utility_bps=0.0, trade_fraction=0.0)
        result = analyze(rows)
        self.assertEqual(result["passing_policies"], ["argmax"])
        self.assertFalse(result["adapted_joint_rule_passed"])
        self.assertTrue(all(c["mean"] == 0 for c in result["contrasts"] if c["metric"] == "confidence"))

    def test_incomplete_dates_asset_or_seed_is_not_evaluable(self):
        rows = summaries()
        cases = [(rows[:-8], DATES[:-1]),
                 ([r for r in rows if r["asset"] == "BTC"], DATES),
                 ([r for r in rows if r["seed"] != 41], DATES),
                 ([r for r in rows if r["date"] != DATES[-1]], DATES)]
        # Keep the short-calendar case's rows inside its declared panel.
        cases[0] = ([r for r in rows if r["date"] in DATES[:-1]], DATES[:-1])
        for sample, dates in cases:
            with self.subTest(n=len(sample), dates=len(dates)):
                result = analyze(sample, dates)
                self.assertEqual(result["status"], "not_evaluable")
                self.assertIsNone(result["adapted_joint_rule_passed"])
                self.assertIsNone(result["forecast_gate"])
                self.assertTrue(result["missing_evidence"])
                self.assertEqual(result["contrasts"], [])

    def test_missing_primary_condition_is_not_evaluable(self):
        rows = summaries()
        rows[0]["conditions"] = rows[0]["conditions"][1:]
        self.assertEqual(analyze(rows)["status"], "not_evaluable")

    def test_duplicate_dates_records_and_conditions_are_rejected(self):
        rows = summaries()
        with self.assertRaisesRegex(ValueError, "distinct"):
            analyze(rows, DATES[:-1] + [DATES[0]])
        with self.assertRaisesRegex(ValueError, "Duplicate.*record"):
            analyze(rows + [copy.deepcopy(rows[0])])
        rows[0]["conditions"].append(copy.deepcopy(rows[0]["conditions"][0]))
        with self.assertRaisesRegex(ValueError, "Duplicate.*condition"):
            analyze(rows)

    def test_unrecognized_seed_or_origin_is_rejected(self):
        for field, value, message in (("seed", 99, "seed"), ("origin", "exploratory_real", "origin")):
            rows = summaries()
            rows[1][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, message):
                analyze(rows)

    def test_nonfinite_forecast_or_utility_is_rejected(self):
        for metric in ("macro_f1", "accuracy", "log_loss", "multiclass_brier"):
            rows = summaries()
            rows[0][metric] = float("nan")
            with self.subTest(metric=metric), self.assertRaisesRegex(ValueError, "Finite"):
                analyze(rows)
        rows = summaries()
        rows[0]["conditions"][1]["utility_bps"] = float("inf")
        with self.assertRaisesRegex(ValueError, "Finite"):
            analyze(rows)

    def test_unmatched_primary_denominators_are_rejected(self):
        for index in (0, 2, 4):
            rows = summaries()
            rows[1]["conditions"][index]["n"] += 1
            with self.subTest(condition=index), self.assertRaisesRegex(ValueError, "Different eligible"):
                analyze(rows)

    def test_optional_descriptive_models_are_retained_without_changing_gate(self):
        rows = summaries()
        for model, seed in (("prior", 0), ("hist_gb", 17)):
            extra = copy.deepcopy(rows[0])
            extra.update(model=model, seed=seed)
            rows.append(extra)
        result = analyze(rows)
        self.assertTrue(result["adapted_joint_rule_passed"])
        self.assertEqual(result["records"], rows)

    def test_shared_bootstrap_matches_direct_source_arithmetic_reproducibly(self):
        rows = summaries()
        for row in rows:
            if row["model"] == "mlp":
                i = DATES.index(row["date"])
                offset = (i - 3.5) * 0.001 * (1 if row["asset"] == "BTC" else 2)
                row["macro_f1"] += offset
                for c in row["conditions"]:
                    c["utility_bps"] += offset
        result = analyze(rows)
        self.assertEqual(result, analyze(rows))
        indices = np.random.default_rng(17029001).integers(0, 8, size=(10000, 8))
        alpha = 0.05 / 8
        for contrast in result["contrasts"]:
            values = np.asarray(contrast["day_values"])
            bounds = np.quantile(values[indices].mean(axis=1), [alpha / 2, 1 - alpha / 2])
            radius = float(t.ppf(1 - alpha / 2, 7) * values.std(ddof=1) / np.sqrt(8))
            self.assertEqual(contrast["bootstrap_lower"], float(bounds[0]))
            self.assertEqual(contrast["bootstrap_upper"], float(bounds[1]))
            self.assertEqual(contrast["lower"], float(min(bounds[0], values.mean() - radius)))
            self.assertEqual(contrast["upper"], float(max(bounds[1], values.mean() + radius)))


if __name__ == "__main__":
    unittest.main()
