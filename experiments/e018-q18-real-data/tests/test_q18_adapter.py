"""Adversarial software fixtures, never market-performance evidence."""
import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from q18_adapter.contracts import implementation_hashes, load_reviewed_grid, review_gate, sha256
from q18_adapter.evaluation import fit_pilot, train_labels
from q18_adapter.features import SECOND, Split, build_dataset, build_split, eligible_indices


def fixture():
    rng = np.random.default_rng(20260919)
    n = 600
    times = np.datetime64("2025-12-01", "ns").astype(np.int64) + np.arange(n) * SECOND
    mid = 90000 + np.cumsum(rng.normal(size=n))
    levels = 1 + np.arange(5)
    return {"times_ns": times, "bid_px": mid[:, None] - levels,
            "ask_px": mid[:, None] + levels, "bid_qty": rng.uniform(.1, 3, (n, 5)),
            "ask_qty": rng.uniform(.1, 3, (n, 5)), "top5_complete": np.ones(n, bool),
            "clock_causal": np.ones(n, bool), "atomic_complete": np.ones(n, bool),
            "release_ns": times.copy(), "certificate_known_ns": times.copy(),
            "segment_id": np.zeros(n, dtype=np.int64)}


def splits(grid):
    t = grid["times_ns"]
    return [Split("train", int(t[0]), int(t[300])),
            Split("evaluation", int(t[300]), int(t[-1] + SECOND))]


class FeatureTests(unittest.TestCase):
    def setUp(self):
        self.grid = fixture()
        self.splits = splits(self.grid)

    def test_exact_common_rows_and_strict_split_containment(self):
        data = build_dataset(self.grid, self.splits)
        np.testing.assert_array_equal(data["train"]["indices"], np.arange(75, 290))
        np.testing.assert_array_equal(data["evaluation"]["indices"], np.arange(375, 590))
        self.assertTrue(all(len(v) == 215 for v in data["train"]["views"].values()))

    def test_one_day_support_is_bounded_and_keeps_exact_guard(self):
        n = 86400
        start = int(self.grid["times_ns"][0])
        grid = {key: np.repeat(values[:1], n, axis=0) for key, values in self.grid.items()}
        grid["times_ns"] = start + np.arange(n, dtype=np.int64) * SECOND
        grid["release_ns"] = grid["times_ns"].copy()
        grid["certificate_known_ns"] = grid["times_ns"].copy()
        eligible = eligible_indices(grid, Split("evaluation", start, start + n * SECOND))
        np.testing.assert_array_equal(eligible, np.arange(75, n - 10))
        oversized = {key: np.concatenate([values, values[-1:]], axis=0) for key, values in grid.items()}
        with self.assertRaisesRegex(ValueError, "at most one UTC day"):
            eligible_indices(oversized, Split("evaluation", start, start + (n+1) * SECOND))

    def test_versioned_forward_guard_does_not_shift_ten_second_target(self):
        g = int(self.grid["times_ns"][100])
        start = self.splits[0].start_ns
        for extra, legacy_admitted in ((250_000_000, False), (500_000_000, False), (500_000_001, True)):
            boundary = Split("train", start, g + 10 * SECOND + extra)
            legacy = build_split(self.grid, boundary)
            revised = build_split(self.grid, boundary, 10 * SECOND)
            self.assertEqual(100 in legacy["indices"], legacy_admitted)
            self.assertIn(100, revised["indices"])
            mid = (self.grid["bid_px"][:, 0] + self.grid["ask_px"][:, 0]) / 2
            at = np.flatnonzero(revised["indices"] == 100)[0]
            self.assertEqual(revised["returns_bps"][at], 10000 * (mid[110] / mid[100] - 1))

    def test_delay_and_history_do_not_shift_target(self):
        data = build_split(self.grid, self.splits[0])
        mid = (self.grid["bid_px"][:, 0] + self.grid["ask_px"][:, 0]) / 2
        np.testing.assert_allclose(data["returns_bps"],
            10000 * (mid[data["indices"] + 10] / mid[data["indices"]] - 1))
        x = data["views"][(55, 5, "20sec")][0]
        self.assertAlmostEqual(x[25], 10000 * (mid[20] / mid[19] - 1))
        self.assertAlmostEqual(x[27], 10000 * (mid[20] / mid[0] - 1))

    def test_own_observation_mid_and_future_mutation(self):
        before = build_split(self.grid, self.splits[0])
        changed = copy.deepcopy(self.grid)
        changed["bid_px"][21:] *= 1.1
        changed["ask_px"][21:] *= 1.1
        after = build_split(changed, self.splits[0])
        np.testing.assert_array_equal(before["views"][(55, 5, "20sec")][0],
                                      after["views"][(55, 5, "20sec")][0])
        self.assertEqual(before["views"][(55, 5, "20sec")][0, 0],
                         10000 * (self.grid["bid_px"][20, 0] /
                         ((self.grid["bid_px"][20, 0] + self.grid["ask_px"][20, 0]) / 2) - 1))

    def test_shallow_view_ignores_hidden_levels(self):
        before = build_split(self.grid, self.splits[0])
        changed = copy.deepcopy(self.grid)
        changed["bid_qty"][:, 1:] *= 100
        changed["ask_qty"][:, 1:] *= 100
        after = build_split(changed, self.splits[0])
        for delay in (0, 55):
            for history in ("instant", "20sec"):
                np.testing.assert_array_equal(before["views"][(delay, 1, history)],
                                              after["views"][(delay, 1, history)])

    def test_instant_masks_history_and_nested_state(self):
        data = build_split(self.grid, self.splits[0])
        for delay in (0, 55):
            a, b = (data["views"][(delay, d, "instant")] for d in (1, 5))
            np.testing.assert_array_equal(a[:, :5], b[:, :5])
            self.assertTrue(np.all(a[:, 5:] == 0))
            self.assertTrue(np.all(b[:, 25:] == 0))

    def test_every_invalid_interior_and_target_endpoint_excludes_common_rows(self):
        for key in ("top5_complete", "clock_causal", "atomic_complete"):
            bad = copy.deepcopy(self.grid)
            bad[key][100] = False
            indices = eligible_indices(bad, self.splits[0])
            self.assertFalse(np.any((indices >= 90) & (indices <= 175)))
            self.assertIn(89, indices)
            self.assertIn(176, indices)

    def test_later_admission_or_certificate_is_not_retroactive(self):
        for key in ("release_ns", "certificate_known_ns"):
            bad = copy.deepcopy(self.grid)
            bad[key][100] += SECOND
            self.assertNotIn(100, eligible_indices(bad, self.splits[0]))

    def test_gap_and_segment_boundary_not_interpolated(self):
        for column in ("times_ns", "segment_id"):
            bad = copy.deepcopy(self.grid)
            bad[column][100:] += SECOND if column == "times_ns" else 1
            indices = eligible_indices(bad, self.splits[0])
            self.assertNotIn(100, indices)
            self.assertIn(175, indices)

    def test_reversed_nan_crossed_and_overlapping_input_rejected(self):
        cases = []
        bad = copy.deepcopy(self.grid); bad["times_ns"][[1, 2]] = bad["times_ns"][[2, 1]]; cases.append(bad)
        bad = copy.deepcopy(self.grid); bad["bid_qty"][100, 4] = np.nan; cases.append(bad)
        bad = copy.deepcopy(self.grid); bad["bid_px"][100, 0] = bad["ask_px"][100, 0]; cases.append(bad)
        for bad in cases:
            with self.assertRaises(ValueError):
                build_dataset(bad, self.splits)
        with self.assertRaises(ValueError):
            build_dataset(self.grid, [self.splits[0], Split("evaluation", self.splits[0].start_ns, self.splits[1].end_ns)])


class EvaluationTests(unittest.TestCase):
    def test_strict_threshold_ties_and_degenerate_labels(self):
        selected, threshold, labels = train_labels(np.arange(100.))
        self.assertAlmostEqual(threshold, 89.1)
        self.assertEqual(labels.sum(), 10)
        _, tied_threshold, tied_labels = train_labels(np.r_[np.zeros(91), np.ones(9)])
        self.assertEqual(tied_threshold, 0.0)
        self.assertEqual(tied_labels.sum(), 9)
        with self.assertRaises(ValueError):
            train_labels(np.zeros(100))

    def test_fits_pairing_train_only_threshold_and_scaler(self):
        grid = fixture()
        dataset = build_dataset(grid, splits(grid))
        # Poison evaluation scale/labels; fitted preprocessing is still checked
        # directly against the untouched common training rows.
        dataset["evaluation"]["returns_bps"] *= 100
        for x in dataset["evaluation"]["views"].values():
            x += 1000
        result, probabilities = fit_pilot(dataset)
        selected, threshold, labels = train_labels(dataset["train"]["returns_bps"])
        self.assertEqual(result["threshold_bps"], threshold)
        self.assertEqual(result["fit_count"], 16)
        self.assertEqual(len(result["source_pilot_contrasts"]), 8)
        self.assertEqual(len(result["factorial_edges"]), 24)
        for fit in result["fits"]:
            if fit["model"] == "logistic":
                np.testing.assert_allclose(fit["scaler_mean"],
                    dataset["train"]["views"][tuple(fit["view"])][selected].mean(axis=0))
        self.assertTrue(all(np.isfinite(p).all() for p in probabilities.values()))


class GateTests(unittest.TestCase):
    def test_missing_and_pending_contracts_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertFalse(review_gate(*(root / p for p in ("s", "e", "r", "p")))["admissible"])
        with self.assertRaises(ValueError):
            load_reviewed_grid({"admissible": False}, ".")

    def test_hash_bound_affirmative_contract_and_coordinator_review(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            grid = fixture()
            boundaries = [vars(s) for s in splits(grid)]
            np.savez(root / "grid.npz", **grid)
            shared = {"version": "1.0.0", "status": "certified", "origin": "synthetic_integration", "scopes": {"Q18":
                dict.fromkeys(("admissible", "full_top5", "causal_availability", "atomic_order", "continuous_windows"), True)},
                "admissible_windows": [{"asset": "BTC", "full_top5": True,
                    "start_ns": int(grid["times_ns"][0]), "end_ns": int(grid["times_ns"][-1] + SECOND)}]}
            (root / "s").write_text(json.dumps(shared))
            (root / "p").write_text(json.dumps({"splits": boundaries, "origin": "synthetic_integration",
                                                "implementation_sha256": implementation_hashes()}))
            execution = {"schema": "q18-execution-v1", "experiment_id": "E-018", "asset": "BTC",
                "origin": "synthetic_integration",
                "development_only": True, "clock": "certified_causal_release_grid", "splits": boundaries,
                "shared_contract_sha256": sha256(root / "s"), "protocol_sha256": sha256(root / "p"),
                "grid_file": "grid.npz", "grid_sha256": sha256(root / "grid.npz")}
            (root / "e").write_text(json.dumps(execution))
            review = {"status": "fixture", "role": "fixture_issuer", "review_id": "SYNTHETIC-ONLY",
                "origin": "synthetic_integration", "fixture_only": True,
                "reviewed_at_utc": datetime.now(timezone.utc).isoformat(),
                "shared_contract_sha256": sha256(root / "s"), "execution_manifest_sha256": sha256(root / "e"),
                "protocol_sha256": sha256(root / "p")}
            (root / "r").write_text(json.dumps(review))
            args = [root / p for p in ("s", "e", "r", "p")]
            gate = review_gate(*args)
            self.assertTrue(gate["admissible"], gate["reasons"])
            self.assertEqual(len(load_reviewed_grid(gate, root)["train"]["indices"]), 215)
            original_bytes = {name: (root / name).read_bytes() for name in ("s", "p", "e", "r", "grid.npz")}
            for name in ("p", "e", "r"):
                (root / name).write_text("{}")
                self.assertFalse(review_gate(*args)["admissible"])
                (root / name).write_bytes(original_bytes[name])
            (root / "grid.npz").write_bytes(b"tampered")
            with self.assertRaisesRegex(ValueError, "digest mismatch"):
                load_reviewed_grid(gate, root)
            (root / "grid.npz").write_bytes(original_bytes["grid.npz"])
            narrowed = copy.deepcopy(gate)
            narrowed["shared"]["admissible_windows"][0]["start_ns"] += SECOND
            with self.assertRaisesRegex(ValueError, "escapes"):
                load_reviewed_grid(narrowed, root)
            short = copy.deepcopy(gate)
            last = int(load_reviewed_grid(gate, root)["evaluation"]["times_ns"][-1])
            short["shared"]["admissible_windows"][0]["end_ns"] = last + 10_250_000_000
            with self.assertRaisesRegex(ValueError, "escapes"):
                load_reviewed_grid(short, root)
            # Even consistently rehashed review files cannot bless stale code hashes.
            stale = {"splits": boundaries, "implementation_sha256": {"features.py": "outdated"}}
            (root / "p").write_text(json.dumps(stale))
            execution["protocol_sha256"] = sha256(root / "p")
            (root / "e").write_text(json.dumps(execution))
            review["protocol_sha256"] = sha256(root / "p")
            review["execution_manifest_sha256"] = sha256(root / "e")
            (root / "r").write_text(json.dumps(review))
            stale_gate = review_gate(*args)
            self.assertFalse(stale_gate["admissible"])
            self.assertIn("Executing implementation differs from the frozen protocol", stale_gate["reasons"])
            for name in ("p", "e", "r"):
                (root / name).write_bytes(original_bytes[name])
            # A later edit invalidates approval, including a pending downgrade.
            shared["status"] = "investigation_in_progress"
            (root / "s").write_text(json.dumps(shared))
            self.assertFalse(review_gate(*args)["admissible"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
