"""Synthetic date-panel checks; no source admission or empirical results."""
import copy
import unittest
import weakref
from unittest.mock import patch

import numpy as np

from q18_adapter.features import SECOND, VIEWS
from q18_adapter.panel_evaluation import DIAGNOSTIC_ROLE, fit_panel, project_dates


def fixture():
    rng = np.random.default_rng(20260919)
    dates = [f"2025-{month:02d}-01" for month in range(1, 8)]
    roles = dict(zip(dates, ["train"] * 3 + ["validation"] + ["evaluation"] * 3))
    rows, contracts = {a: [] for a in ("BTC", "ETH")}, {a: [] for a in ("BTC", "ETH")}
    for asset in rows:
        for month, date in enumerate(dates):
            contract = {"date": date, "asset": asset, "windows": [],
                        "continuity": {"max_gap_ns": 2 * SECOND, "max_age_ns": 1_500_000_000}}
            lengths = [96, 126] if month < 3 else [120] if month == 3 else [106 + 20 * (month - 4)]
            ordinal = 0
            source = f"synthetic-{asset}-{date}"
            for segment, count in enumerate(lengths):
                count += 2 if asset == "ETH" else 0
                start = int(np.datetime64(date, "ns").astype(np.int64))
                start += (180 * segment + (asset == "ETH")) * SECOND
                prices = (90000 if asset == "BTC" else 2000) + np.cumsum(rng.normal(0, .5, count))
                for i, mid in enumerate(prices):
                    rows[asset].append({"source_id": source, "source_ordinal": ordinal + i,
                        "asset": asset, "event_ns": start + i * SECOND,
                        "release_ns": None, "admission_evidence_ns": None,
                        "bid_prices_units8": [int(round((mid - k) * 1e8)) for k in range(1, 6)],
                        "ask_prices_units8": [int(round((mid + k) * 1e8)) for k in range(1, 6)],
                        "bid_sizes_units8": [int(v) for v in rng.integers(10_000_000, 300_000_000, 5)],
                        "ask_sizes_units8": [int(v) for v in rng.integers(10_000_000, 300_000_000, 5)]})
                contract["windows"].append({"window_id": f"{source}-{segment}", "scope": "Q18",
                    "asset": asset, "source_ids": [source], "first_source_ordinal": ordinal,
                    "last_source_ordinal": ordinal + count - 1, "start_ns": start,
                    "end_ns": start + (count - 1) * SECOND + 1})
                ordinal += count
            contracts[asset].append(contract)
    return rows, contracts, roles


def fake_fit(dataset):
    """Known unequal-date predictions isolate aggregation without fitted noise."""
    part = dataset["evaluation"]
    probabilities = {}
    for model in ("logistic", "hist_gb"):
        for view in VIEWS:
            p = np.full(len(part["times_ns"]), .99999)
            values = (.1, .5, .9) if view[1:] == (5, "20sec") else (.2, .4, .8)
            for month, value in zip((5, 6, 7), values):
                p[part["dates"] == f"2025-{month:02d}-01"] = value
            probabilities[(model, view)] = p
    return {"fit_count": 16, "threshold_bps": 1., "prior": .1, "fits": [],
            "training_rows": len(dataset["train"]["times_ns"]), "daily_metrics": []}, probabilities


class ProjectionTests(unittest.TestCase):
    def setUp(self):
        self.rows, self.contracts, self.roles = fixture()

    def test_segment_containment_and_paired_dates_without_forced_asset_rows(self):
        panel = project_dates(self.rows, self.contracts, self.roles)
        self.assertEqual(list(panel["date_counts"]["BTC"].values()), [50, 50, 50, 34, 20, 40, 60])
        self.assertEqual(list(panel["date_counts"]["ETH"].values()), [54, 54, 54, 36, 22, 42, 62])
        self.assertEqual(panel["cross_asset_intersections"]["2025-05-01"]["intersecting_decision_times"], 19)
        self.assertFalse(panel["cross_asset_intersections"]["2025-05-01"]["intersection_used_for_fitting"])
        for asset, dataset in panel["datasets"].items():
            windows = {f"{c['date']}:{w['window_id']}": w for c in self.contracts[asset] for w in c["windows"]}
            for part in dataset.values():
                self.assertEqual(set(part["views"]), set(VIEWS))
                self.assertTrue(all(len(x) == len(part["times_ns"]) for x in part["views"].values()))
                for t, key in zip(part["times_ns"], part["window_ids"]):
                    self.assertGreaterEqual(t - 75 * SECOND, windows[key]["start_ns"])
                    self.assertLess(t + 10_500_000_000, windows[key]["end_ns"])

    def test_missing_duplicate_wrong_date_and_role_order_rejected(self):
        bad = copy.deepcopy(self.contracts)
        bad["ETH"].pop()
        with self.assertRaises(ValueError):
            project_dates(self.rows, bad, self.roles)
        bad = copy.deepcopy(self.contracts)
        bad["BTC"].append(bad["BTC"][0])
        with self.assertRaises(ValueError):
            project_dates(self.rows, bad, self.roles)
        roles = dict(self.roles)
        roles["2025-02-01"], roles["2025-05-01"] = "evaluation", "train"
        with self.assertRaises(ValueError):
            project_dates(self.rows, self.contracts, roles)
        bad = copy.deepcopy(self.contracts)
        bad["BTC"][0]["date"], bad["BTC"][1]["date"] = bad["BTC"][1]["date"], bad["BTC"][0]["date"]
        with self.assertRaisesRegex(ValueError, "calendar date"):
            project_dates(self.rows, bad, self.roles)

    def test_twenty_rows_required_per_date_not_pooled_across_dates(self):
        bad = copy.deepcopy(self.contracts)
        window = bad["BTC"][4]["windows"][0]
        window["last_source_ordinal"] -= 1
        with self.assertRaisesRegex(ValueError, "Each asset/date"):
            project_dates(self.rows, bad, self.roles)

    def test_zero_eligible_segments_are_audited_before_date_minimum(self):
        short = self.contracts["BTC"][0]["windows"][0]
        short["last_source_ordinal"] = 40
        short["end_ns"] = short["start_ns"] + 40 * SECOND + 1
        panel = project_dates(self.rows, self.contracts, self.roles)
        self.assertEqual(panel["date_counts"]["BTC"]["2025-01-01"], 40)
        self.assertEqual(panel["audits"]["BTC"]["2025-01-01"][0]["status"], "no_eligible_support")
        # A long but unsupported segment is also empty, without joining its gaps.
        source = short["source_ids"][0]
        for row in self.rows["BTC"]:
            if row["source_id"] == source and row["source_ordinal"] <= 40:
                row["event_ns"] = short["start_ns"] + row["source_ordinal"] * 3 * SECOND
        short["end_ns"] = short["start_ns"] + 120 * SECOND + 1
        panel = project_dates(self.rows, self.contracts, self.roles)
        self.assertEqual(panel["date_counts"]["BTC"]["2025-01-01"], 40)
        self.assertEqual(panel["audits"]["BTC"]["2025-01-01"][0]["status"], "no_eligible_support")
        short["start_ns"] += SECOND
        with self.assertRaisesRegex(ValueError, "exceed declared"):
            project_dates(self.rows, self.contracts, self.roles)

    def test_later_mutations_leave_training_features_and_rows_unchanged(self):
        before = project_dates(self.rows, self.contracts, self.roles)
        changed = copy.deepcopy(self.rows)
        cutoff = int(np.datetime64("2025-04-01", "ns").astype(np.int64))
        for rows in changed.values():
            for row in rows:
                if row["event_ns"] >= cutoff:
                    row["bid_sizes_units8"] = [v * 10 for v in row["bid_sizes_units8"]]
        after = project_dates(changed, self.contracts, self.roles)
        for asset in before["datasets"]:
            a, b = before["datasets"][asset]["train"], after["datasets"][asset]["train"]
            np.testing.assert_array_equal(a["returns_bps"], b["returns_bps"])
            np.testing.assert_array_equal(a["times_ns"], b["times_ns"])
            for view in VIEWS:
                np.testing.assert_array_equal(a["views"][view], b["views"][view])

    def test_lazy_loads_each_date_once_and_releases_raw_rows_before_next_load(self):
        class Rows(list):
            pass

        references, calls = [], []

        def loader(asset):
            def load(contract):
                self.assertTrue(all(ref() is None for ref in references))
                source_ids = {source for w in contract["windows"] for source in w["source_ids"]}
                rows = Rows(row for row in self.rows[asset] if row["source_id"] in source_ids)
                references.append(weakref.ref(rows))
                calls.append((asset, contract["date"]))
                return rows
            return load

        lazy = project_dates({asset: loader(asset) for asset in self.rows}, self.contracts, self.roles)
        self.assertEqual(len(calls), 14)
        self.assertEqual(len(set(calls)), 14)
        self.assertTrue(all(ref() is None for ref in references))
        direct = project_dates(self.rows, self.contracts, self.roles)
        self.assertEqual(lazy["date_counts"], direct["date_counts"])
        for asset in self.rows:
            for role in ("train", "evaluation"):
                for view in VIEWS:
                    np.testing.assert_array_equal(lazy["datasets"][asset][role]["views"][view],
                                                  direct["datasets"][asset][role]["views"][view])


class EvaluationTests(unittest.TestCase):
    def setUp(self):
        self.panel = project_dates(*fixture())

    def test_equal_date_losses_and_ratios_exclude_validation_and_conditional_rows(self):
        diagnostics = {}
        for asset, dataset in self.panel["datasets"].items():
            part = dataset["evaluation"]
            part["returns_bps"][:] = 0
            if asset != "BTC":
                continue
            diagnostics[asset] = {"times_ns": int(np.datetime64("2025-12-01", "ns").astype(np.int64))
                                  + np.arange(12, dtype=np.int64) * SECOND,
                                  "returns_bps": np.full(12, 100.),
                                  "views": {view: x[:12].copy() for view, x in part["views"].items()}}
        with patch("q18_adapter.panel_evaluation.fit_pilot", side_effect=fake_fit) as fit:
            report, predictions = fit_panel(self.panel, "synthetic_integration", diagnostics)
        self.assertEqual(fit.call_count, 2)
        self.assertEqual(report["fit_count"], 32)
        self.assertEqual(report["market_fits"], 0)
        full = float(np.mean(-np.log1p(-np.array([.1, .5, .9]))))
        reduced = float(np.mean(-np.log1p(-np.array([.2, .4, .8]))))
        pooled = float(np.average(-np.log1p(-np.array([.1, .5, .9])), weights=[20, 40, 60]))
        for asset, result in report["assets"].items():
            contrast = next(r for r in result["source_pilot_contrasts"]
                            if r["model"] == "logistic" and r["factor"] == "depth" and r["delay"] == 0)
            self.assertAlmostEqual(contrast["full_loss"], full)
            self.assertAlmostEqual(contrast["relative_gap"], (reduced - full) / full)
            self.assertNotAlmostEqual(contrast["full_loss"], pooled)
            absolute = next(r for r in result["absolute_metrics_equal_date"]["evaluation"]
                            if r["model"] == "logistic" and r["view"] == [0, 5, "20sec"])
            self.assertAlmostEqual(absolute["log_loss"], full)
            self.assertAlmostEqual(absolute["brier"], np.mean(np.array([.1, .5, .9]) ** 2))
            self.assertEqual(absolute["date_count"], 3)
            self.assertEqual(len(result["absolute_metrics_by_date"]), 4 * 17)
            self.assertEqual(len(result["conditional_diagnostic_metrics_by_date"]), 17 if asset == "BTC" else 0)
            self.assertFalse(result["conditional_diagnostic_empirical_admission"])
            self.assertEqual(int(np.sum(predictions[asset]["role"] == DIAGNOSTIC_ROLE)), 12 if asset == "BTC" else 0)
            self.assertEqual(set(predictions[asset]["probabilities"]), set(fake_fit(fit.call_args_list[0].args[0])[1]))
        with self.assertRaisesRegex(ValueError, "BTC only"):
            fit_panel(self.panel, "synthetic_integration", {"ETH": diagnostics["BTC"]})
        diagnostics["BTC"]["times_ns"] += 24 * 3600 * SECOND
        with self.assertRaisesRegex(ValueError, "December 1"):
            fit_panel(self.panel, "synthetic_integration", diagnostics)

    def test_actual_fixed_synthetic_fits_keep_thresholds_and_scalers_training_only(self):
        for dataset in self.panel["datasets"].values():
            validation = dataset["evaluation"]["roles"] == "validation"
            dataset["evaluation"]["returns_bps"][validation] = 1e6
            for x in dataset["evaluation"]["views"].values():
                x[validation] += 1e4
        report, predictions = fit_panel(self.panel, "synthetic_integration")
        self.assertEqual(report["fit_count"], report["synthetic_fits"])
        self.assertEqual(report["fit_count"], 32)
        self.assertEqual(report["market_fits"], report["accepted_empirical_fits"])
        self.assertEqual(report["market_fits"], 0)
        for asset, result in report["assets"].items():
            train = self.panel["datasets"][asset]["train"]
            self.assertEqual(result["threshold_bps"], float(np.quantile(np.abs(train["returns_bps"]), .9)))
            for fit in result["fits"]:
                if fit["model"] == "logistic":
                    np.testing.assert_allclose(fit["scaler_mean"], train["views"][tuple(fit["view"])].mean(axis=0))
            self.assertEqual(len(result["source_pilot_contrasts"]), 8)
            self.assertEqual(len(result["factorial_edges"]), 24)
            self.assertTrue(all(np.isfinite(p).all() for p in predictions[asset]["probabilities"].values()))
        self.assertEqual(report["noninferiority"], "not_tested")


if __name__ == "__main__":
    unittest.main(verbosity=2)
