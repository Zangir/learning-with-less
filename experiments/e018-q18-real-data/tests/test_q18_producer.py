"""Adversarial checks against an independently authored producer fixture."""
import copy
import json
from pathlib import Path
import shutil
import tempfile
import unittest

import numpy as np

from q18_adapter.contracts import sha256
from q18_adapter.producer import project_asset, project_panel, read_producer, read_rows

FIXTURE_ROOT = None  # The integration driver supplies the immutable producer fixture.


class ProducerTests(unittest.TestCase):
    def setUp(self):
        if FIXTURE_ROOT is None:
            self.skipTest("Independent T-008 fixture supplied by integration driver")
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in ("affirmative_shared_contract.json", "synthetic_state_rows.jsonl"):
            shutil.copyfile(Path(FIXTURE_ROOT) / name, self.root / name)
        self.path = self.root / "affirmative_shared_contract.json"
        self.contract, self.sources = read_producer(self.path, sha256(self.path), "synthetic_integration")
        self.rows, _ = read_rows(self.sources)

    def test_producer_projection_has_common_rows_and_no_fabricated_receipt(self):
        for row in self.rows["BTC"]:
            row["release_ns"] = None
            row["admission_evidence_ns"] = None
        dataset, grid, audit = project_asset(self.rows["BTC"], self.contract, "BTC")
        self.assertNotIn("release_ns", grid)
        self.assertEqual(len(dataset["evaluation"]["indices"]), 1115)
        self.assertTrue(all(len(x) == 1115 for x in dataset["evaluation"]["views"].values()))
        self.assertFalse(audit["measured_receipt_claim"])

    def test_tampered_payload_and_contract(self):
        with self.assertRaisesRegex(ValueError, "contract hash"):
            read_producer(self.path, "0" * 64, "synthetic_integration")
        with (self.root / "synthetic_state_rows.jsonl").open("a") as stream:
            stream.write("{}\n")
        with self.assertRaisesRegex(ValueError, "payload hash"):
            read_producer(self.path, sha256(self.path), "synthetic_integration")

    def test_origin_negative_units_clock_and_guard_rejected(self):
        with self.assertRaisesRegex(ValueError, "origin mismatch"):
            read_producer(self.path, sha256(self.path), "exploratory_real")
        mutations = [lambda c: c.update(fixture_only=False),
                     lambda c: c["scopes"]["Q18"].update(decision="negative"),
                     lambda c: c["scopes"]["Q18"].update(clock_scope="observed_receive_time"),
                     lambda c: c["units"].update(price="floating_dollars"),
                     lambda c: c["horizons"]["Q18"].update(forward_guard_ns=10_000_000_000)]
        for mutate in mutations:
            changed = copy.deepcopy(self.contract)
            mutate(changed)
            self.path.write_text(json.dumps(changed))
            with self.assertRaises(ValueError):
                read_producer(self.path, sha256(self.path), "synthetic_integration")

    def test_source_inversion_conflicting_ties_and_noninteger_units_rejected(self):
        original = self.rows["BTC"][:4]
        cases = []
        changed = copy.deepcopy(original); changed[2]["event_ns"] = changed[0]["event_ns"]; cases.append(changed)
        changed = copy.deepcopy(original); changed[2]["event_ns"] = changed[1]["event_ns"]; cases.append(changed)
        changed = copy.deepcopy(original); changed[2]["bid_prices_units8"][0] = 1.1; cases.append(changed)
        for changed in cases:
            target = self.root / "invalid.jsonl"
            target.write_text("".join(json.dumps(r) + "\n" for r in changed))
            with self.assertRaises(ValueError):
                read_rows({"fictional-btc": target})

    def test_gap_cannot_be_compressed_into_eligible_history(self):
        rows = self.rows["BTC"]
        gapped = rows[:1000] + rows[1010:]
        dataset, grid, audit = project_asset(gapped, self.contract, "BTC")
        origin = rows[0]["event_ns"]
        decisions = (dataset["train"]["times_ns"] - origin) // 1_000_000_000
        self.assertFalse(np.any((decisions >= 990) & (decisions < 1085)))
        self.assertGreater(audit["grid_stale_rows"], 0)
        self.assertEqual(audit["segments"], 2)

    def test_future_snapshots_do_not_change_past_features(self):
        before, _, _ = project_asset(self.rows["BTC"], self.contract, "BTC")
        changed = copy.deepcopy(self.rows["BTC"])
        for row in changed[500:]:
            for key in ("bid_prices_units8", "ask_prices_units8"):
                row[key] = [v * 2 for v in row[key]]
        after, _, _ = project_asset(changed, self.contract, "BTC")
        for view, values in before["train"]["views"].items():
            np.testing.assert_array_equal(values[:100], after["train"]["views"][view][:100])

    def test_historical_units_and_window_use_require_versioned_panel_rule(self):
        contract = copy.deepcopy(self.contract)
        contract.update(version="2.1.0", asset="BTC")
        contract["units"].update(price="USD per BTC multiplied by 1e8", size="BTC multiplied by 1e8")
        for window in contract["windows"]:
            window["use"] = "prespecified_chronological_split"
        self.path.write_text(json.dumps(contract))
        with self.assertRaises(ValueError):
            read_producer(self.path, sha256(self.path), "synthetic_integration")
        accepted, _ = read_producer(self.path, sha256(self.path), "synthetic_integration",
                                   split_rule="predeclared_three_date_panel")
        self.assertEqual(accepted["origin"], "synthetic_integration")
        self.assertTrue(accepted["fixture_only"])
        contract["version"] = "2.0.0"
        self.path.write_text(json.dumps(contract))
        with self.assertRaises(ValueError):
            read_producer(self.path, sha256(self.path), "synthetic_integration",
                          split_rule="predeclared_three_date_panel")

    def three_date_fixture(self):
        """Clone producer-authored rows; no historical observations or approvals."""
        second = 1_000_000_000
        contract = copy.deepcopy(self.contract)
        template = next(w for w in contract["windows"] if w["scope"] == "Q18")
        contract["windows"] = []
        rows, roles, expected = [], {}, {r: [] for r in ("train", "validation", "evaluation")}
        # The first training segment has only ten eligible rows. Pooling may
        # rescue its sample size; it must never rescue its missing time.
        segments = (("train", "2025-12-08", 0, 96), ("train", "2025-12-08", 180, 140),
                    ("validation", "2025-12-16", 0, 120), ("evaluation", "2025-12-23", 0, 140))
        ordinals = {}
        for number, (role, day, offset, count) in enumerate(segments):
            start = int(np.datetime64(day, "ns").astype(np.int64)) + offset * second
            source_id = f"fictional-btc-{day}"
            ordinal = ordinals.get(source_id, 0)
            for index, original in enumerate(self.rows["BTC"][:count]):
                row = copy.deepcopy(original)
                row.update(source_id=source_id, source_ordinal=ordinal + index,
                           event_ns=start + index * second, release_ns=None, admission_evidence_ns=None)
                rows.append(row)
            window = copy.deepcopy(template)
            window.update(window_id=f"synthetic-panel-{number}", source_ids=[source_id],
                          first_source_ordinal=ordinal, last_source_ordinal=ordinal + count - 1,
                          start_ns=start, end_ns=start + (count - 1) * second + 1,
                          use="prespecified_chronological_split")
            contract["windows"].append(window)
            roles[window["window_id"]] = role
            expected[role].append(np.arange(start + 75 * second, start + (count - 11) * second,
                                           second, dtype=np.int64))
            ordinals[source_id] = ordinal + count
        return rows, contract, roles, {role: np.concatenate(parts) for role, parts in expected.items()}

    def test_three_date_multisegment_panel_preserves_purges_and_role_counts(self):
        rows, contract, roles, expected = self.three_date_fixture()
        dataset, _, _ = project_panel(rows, contract, "BTC", roles)
        np.testing.assert_array_equal(dataset["train"]["times_ns"], expected["train"])
        self.assertEqual(len(dataset["train"]["times_ns"]), 64)
        self.assertEqual(len(expected["validation"]), 34)
        self.assertEqual(len(expected["evaluation"]), 54)
        later = dataset["evaluation"]
        for role in ("validation", "evaluation"):
            np.testing.assert_array_equal(later["times_ns"][later["roles"] == role], expected[role])
        for part in dataset.values():
            self.assertEqual(len(part["views"]), 8)
            self.assertTrue(all(len(x) == len(part["times_ns"]) for x in part["views"].values()))
            for decision in part["times_ns"]:
                self.assertEqual(sum(window["start_ns"] <= decision - 75_000_000_000
                                     and decision + 10_500_000_000 < window["end_ns"]
                                     for window in contract["windows"]), 1)

    def test_three_date_later_mutation_cannot_change_training_rows_or_features(self):
        rows, contract, roles, _ = self.three_date_fixture()
        before, _, _ = project_panel(rows, contract, "BTC", roles)
        changed = copy.deepcopy(rows)
        cutoff = int(np.datetime64("2025-12-16", "ns").astype(np.int64))
        for row in changed:
            if row["event_ns"] >= cutoff:
                for key in ("bid_prices_units8", "ask_prices_units8", "bid_sizes_units8", "ask_sizes_units8"):
                    row[key] = [value * 2 for value in row[key]]
        after, _, _ = project_panel(changed, contract, "BTC", roles)
        for key in ("indices", "times_ns", "returns_bps"):
            np.testing.assert_array_equal(before["train"][key], after["train"][key])
        for view in before["train"]["views"]:
            np.testing.assert_array_equal(before["train"]["views"][view], after["train"]["views"][view])
        self.assertFalse(np.array_equal(before["evaluation"]["views"][(0, 5, "20sec")],
                                        after["evaluation"]["views"][(0, 5, "20sec")]))
