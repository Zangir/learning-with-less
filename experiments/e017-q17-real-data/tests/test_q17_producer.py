"""Synthetic consumer mechanics and read-only historical provenance checks.

Set Q17_PRODUCER_FIXTURES to the private T-010/r2/inputs/synthetic snapshot.
Set Q17_HISTORICAL_FIXTURES to the private T-010/r2/inputs/historical snapshot.
No estimators are fitted; provenance admission does not confer scientific acceptance.
"""
import copy
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest

import numpy as np

from q17_transfer.features import DAY, NS, build_arrays
from q17_transfer.gate import sha256
from q17_transfer.policies import schedule_inputs
from q17_transfer.producer import eligible, load_contract, prepare_asset


POSITIVE_SHA256 = "5362a8d120468efce4a1b0abd397b18609ec2ef21cdbbc18067e7216b5d7929e"
PAYLOAD_SHA256 = "af3b8fc2e702dcd4cbe2e59ac8b8df5fb7bd5a90e2283a805969fe6459ca90b2"
HISTORICAL_TRAIN_SHA256 = "b0b540f12c8c7ab75031152091d4a97e6118765880554e03c511b7f5dff02e23"


class ProducerIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        configured = os.environ.get("Q17_PRODUCER_FIXTURES")
        if not configured:
            raise unittest.SkipTest("Q17_PRODUCER_FIXTURES must name the synthetic producer snapshot")
        cls.fixture_root = Path(configured)
        cls.positive = cls.fixture_root / "affirmative_shared_contract.json"
        cls.payload = cls.fixture_root / "synthetic_state_rows.jsonl"
        if sha256(cls.positive) != POSITIVE_SHA256 or sha256(cls.payload) != PAYLOAD_SHA256:
            raise AssertionError("The producer integration fixture differs from its frozen provenance")
        cls.original_contract = json.loads(cls.positive.read_text(encoding="utf-8"))
        cls.original_rows = [json.loads(line) for line in cls.payload.read_text(encoding="utf-8").splitlines()]

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def write_case(self, contract=None, rows=None):
        contract = copy.deepcopy(self.original_contract if contract is None else contract)
        rows = self.original_rows if rows is None else rows
        payload = self.root / "authored_rows.jsonl"
        payload.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
        contract["sources"][0].update(file=payload.name, sha256=sha256(payload))
        path = self.root / "authored_contract.json"
        path.write_text(json.dumps(contract), encoding="utf-8")
        return path

    def load_case(self, contract=None, rows=None):
        return load_contract(self.write_case(contract, rows), "synthetic_integration")

    def test_pinned_positive_prepares_three_classes_and_matched_provenance(self):
        loaded = load_contract(self.positive, "synthetic_integration")
        arrays, diagnostics = prepare_asset(loaded, "BTC")
        self.assertEqual(loaded["producer_sha256"], POSITIVE_SHA256)
        self.assertEqual(diagnostics["origin"], "synthetic_integration")
        self.assertEqual(diagnostics["clock_scope"], "exchange_time")
        self.assertEqual(set(arrays), {"train", "validation", "test"})
        for split, day in arrays.items():
            with self.subTest(split=split):
                self.assertEqual(set(day["y"].tolist()), {0, 1, 2})
                self.assertEqual(day["X"].shape, (len(day["times"]), 5))
                self.assertTrue(np.isfinite(day["X"]).all())
                self.assertTrue((np.diff(day["times"]) > 0).all())
                self.assertEqual(set(day["source_id"]), {"fictional-btc"})
                self.assertTrue((day["feature_source_ordinals"] >= 0).all())
                self.assertTrue((day["exit_source_ordinals"] <= 3600).all())
                if split != "train":
                    groups = day["schedule_rows"]
                    self.assertEqual(groups.shape[1], 12)
                    np.testing.assert_array_equal(np.diff(day["times"][groups], axis=1), 11*NS)
        for frozen in diagnostics["freeze_checks"].values():
            self.assertLessEqual(frozen["evidence_ready_ns"], frozen["next_first_decision_ns"])

    def test_actual_negative_fixture_remains_negative(self):
        with self.assertRaisesRegex(ValueError, "Q17 producer scope is negative"):
            load_contract(self.fixture_root / "negative_shared_contract.json", "synthetic_integration")

    def test_origin_marker_purpose_and_review_cannot_promote_fixture(self):
        for expected in ("exploratory_real", "eligible_empirical", "unknown"):
            with self.subTest(expected=expected), self.assertRaisesRegex(ValueError, "Origin mismatch"):
                load_contract(self.positive, expected)
        cases = (("fixture_only", False, "fixture marker"),
                 ("purpose", "market_observations", "Purpose and origin"),
                 ("review", {"status": "approved"}, "independent review"))
        for field, value, message in cases:
            contract = copy.deepcopy(self.original_contract)
            contract[field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, message):
                self.load_case(contract)

    def test_payload_checksum_is_checked_before_row_admission(self):
        path = self.write_case()
        with (self.root / "authored_rows.jsonl").open("a", encoding="utf-8") as payload:
            payload.write("\n")
        with self.assertRaisesRegex(ValueError, "checksum mismatch"):
            load_contract(path, "synthetic_integration")

    def test_source_binding_is_per_payload_not_global_membership(self):
        contract = copy.deepcopy(self.original_contract)
        other = copy.deepcopy(self.original_rows[1])
        other["source_id"] = "fictional-other"
        other_payload = self.root / "other.jsonl"
        other_payload.write_text(json.dumps(other) + "\n", encoding="utf-8")
        contract["sources"].append(dict(source_id="fictional-other", file=other_payload.name,
                                         sha256=sha256(other_payload)))
        wrong = copy.deepcopy(self.original_rows[0])
        wrong["source_id"] = "fictional-other"
        with self.assertRaisesRegex(ValueError, "Unbound source ID"):
            self.load_case(contract, [wrong])

    def test_same_payload_cannot_be_bound_as_two_sources(self):
        path = self.write_case()
        contract = json.loads(path.read_text())
        duplicate = copy.deepcopy(contract["sources"][0])
        duplicate["source_id"] = "fictional-other"
        contract["sources"].append(duplicate)
        path.write_text(json.dumps(contract), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "One source ID per payload"):
            load_contract(path, "synthetic_integration")

    def test_source_event_and_ordinal_inversions_are_not_sorted_away(self):
        for field, value in (("event_ns", self.original_rows[0]["event_ns"]-1),
                             ("source_ordinal", 0)):
            rows = copy.deepcopy(self.original_rows[:3])
            rows[1][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "inversion"):
                self.load_case(rows=rows)

    def test_version_21_requires_freshness_and_canonical_event_ties(self):
        contract = copy.deepcopy(self.original_contract)
        contract["version"] = "2.1.0"
        for max_age in (None, 0, True):
            if max_age is not None:
                contract["continuity"]["max_age_ns"] = max_age
            with self.subTest(max_age=max_age), self.assertRaisesRegex(ValueError, "freshness limit"):
                self.load_case(contract, self.original_rows[:3])
        contract["continuity"]["max_age_ns"] = NS
        for conflicting in (False, True):
            rows = copy.deepcopy(self.original_rows[:3])
            rows[1] = copy.deepcopy(rows[0])
            rows[1]["source_ordinal"] = 1
            if conflicting:
                rows[1]["bid_prices_units8"][0] += 1
            with self.subTest(conflicting=conflicting), self.assertRaisesRegex(ValueError, "deduplicate"):
                self.load_case(contract, rows)

    def test_exchange_time_does_not_fabricate_receive_clock_support(self):
        rows = copy.deepcopy(self.original_rows)
        for row in rows:
            row["release_ns"] = row["admission_evidence_ns"] = None
        loaded = self.load_case(rows=rows)
        arrays, diagnostics = prepare_asset(loaded, "BTC")
        self.assertEqual(diagnostics["clock_scope"], "exchange_time")
        self.assertGreater(len(arrays["train"]["times"]), 0)
        contract = copy.deepcopy(self.original_contract)
        contract["scopes"]["Q17"]["clock_scope"] = "observed_receive_time"
        with self.assertRaisesRegex(ValueError, "receive/evidence clocks unavailable"):
            self.load_case(contract, rows)

    def test_maximum_age_is_independent_of_gap_tolerance(self):
        contract = copy.deepcopy(self.original_contract)
        contract["version"] = "2.1.0"
        contract["continuity"].update(max_gap_ns=3*NS, max_age_ns=3*NS)
        rows = [row for row in self.original_rows if row["source_ordinal"] != 1231]
        generous, _ = prepare_asset(self.load_case(contract, rows), "BTC")
        decision = self.original_rows[0]["event_ns"] + 1221*NS
        self.assertIn(decision, generous["validation"]["times"])
        location = int(np.flatnonzero(generous["validation"]["times"] == decision)[0])
        self.assertEqual(generous["validation"]["quote_age_ns"][location], 0)
        self.assertEqual(generous["validation"]["max_input_age_ns"][location], 1_500_000_000)
        contract["continuity"]["max_age_ns"] = NS
        strict, diagnostics = prepare_asset(self.load_case(contract, rows), "BTC")
        self.assertNotIn(decision, strict["validation"]["times"])
        self.assertEqual(diagnostics["splits"]["validation"]["segments"], 1)
        self.assertTrue(any(item["reason"] == "stale_feature_or_outcome"
                            for item in diagnostics["splits"]["validation"]["exclusions"]))

    def test_gaps_break_schedules_without_reanchoring_the_eleven_second_grid(self):
        rows = [row for row in self.original_rows if not 1700 <= row["source_ordinal"] <= 1715]
        arrays, diagnostics = prepare_asset(self.load_case(rows=rows), "BTC")
        day = arrays["validation"]
        groups = day["schedule_rows"]
        self.assertEqual(diagnostics["splits"]["validation"]["segments"], 2)
        self.assertEqual(groups.shape[1], 12)
        self.assertTrue((np.diff(day["times"]) > 11*NS).any())
        np.testing.assert_array_equal(np.diff(day["times"][groups], axis=1), 11*NS)
        np.testing.assert_array_equal(np.diff(day["segment_id"][groups], axis=1), 0)
        anchor = self.original_rows[0]["event_ns"] + 1221*NS
        np.testing.assert_array_equal((day["times"]-anchor) % (11*NS), 0)
        probabilities = np.full((len(day["times"]), 3), 1/3)
        scores, prices = schedule_inputs(day, probabilities, 1)
        self.assertEqual(scores.shape, groups.shape)
        self.assertEqual(prices.shape, groups.shape)
        gap = int(np.flatnonzero(np.diff(day["times"]) > 11*NS)[0])
        forged = dict(day, schedule_rows=np.arange(gap-5, gap+7).reshape(1, 12))
        # Missing observations are not a scheduling shortcut, even for impatient clocks.
        with self.assertRaisesRegex(ValueError, "cannot compress gaps"):
            schedule_inputs(forged, probabilities, 1)

    def test_exact_integer_midpoints_preserve_flat_labels(self):
        pairs = ((8799999900001, 8800000100001), (8799999900002, 8800000100000))
        self.assertEqual(sum(pairs[0]), sum(pairs[1]))
        self.assertNotEqual(sum(value/1e8 for value in pairs[0])/2,
                            sum(value/1e8 for value in pairs[1])/2)
        rows = copy.deepcopy(self.original_rows)
        for row in rows:
            bid, ask = pairs[(row["source_ordinal"]//10) % 2]
            row["bid_prices_units8"] = [bid-i*100_000_000 for i in range(5)]
            row["ask_prices_units8"] = [ask+i*100_000_000 for i in range(5)]
        arrays, _ = prepare_asset(self.load_case(rows=rows), "BTC")
        for split, day in arrays.items():
            with self.subTest(split=split):
                np.testing.assert_array_equal(day["y"], 1)

    def test_explicit_date_roles_use_authored_dated_copies(self):
        contract = copy.deepcopy(self.original_contract)
        template = next(window for window in contract["windows"] if window["scope"] == "Q17")
        contract["sources"], contract["windows"] = [], []
        dates = dict(train="2030-01-01", validation="2030-01-02", test="2030-01-03")
        for split, date in dates.items():
            day = int(np.datetime64(date, "ns").astype(np.int64))
            delta = day-template["start_ns"]
            source_id = "authored-fictional-"+split
            rows = copy.deepcopy(self.original_rows)
            for row in rows:
                row["source_id"] = source_id
                for field in ("event_ns", "release_ns", "admission_evidence_ns"):
                    row[field] += delta
            payload = self.root / (split+".jsonl")
            payload.write_text("".join(json.dumps(row)+"\n" for row in rows), encoding="utf-8")
            contract["sources"].append(dict(source_id=source_id, file=payload.name, sha256=sha256(payload),
                                             provenance="Explicitly synthetic dated copy; not a new observation"))
            window = copy.deepcopy(template)
            window.update(window_id=source_id, source_ids=[source_id],
                          start_ns=window["start_ns"]+delta, end_ns=window["end_ns"]+delta)
            contract["windows"].append(window)
        path = self.root / "dated_synthetic_contract.json"
        path.write_text(json.dumps(contract), encoding="utf-8")
        loaded = load_contract(path, "synthetic_integration")
        arrays, diagnostics = prepare_asset(loaded, "BTC", dates)
        self.assertEqual(diagnostics["origin"], "synthetic_integration")
        for split, day in arrays.items():
            date_ns = int(np.datetime64(dates[split], "ns").astype(np.int64))
            self.assertTrue((day["times"]//DAY == date_ns//DAY).all())
            self.assertEqual(set(day["source_id"]), {"authored-fictional-"+split})
        with self.assertRaisesRegex(ValueError, "predeclared chronological date roles"):
            prepare_asset(loaded, "BTC")
        for wrong in (dict(train=dates["test"], validation=dates["validation"], test=dates["train"]),
                      dict(train=dates["train"], validation=dates["train"], test=dates["test"]),
                      {"train": dates["train"]}):
            with self.subTest(roles=wrong), self.assertRaisesRegex(ValueError, "chronological"):
                prepare_asset(loaded, "BTC", wrong)
        with self.assertRaisesRegex(ValueError, "No producer windows"):
            prepare_asset(loaded, "BTC", dict(dates, test="2030-01-04"))


class HistoricalAcquisitionChainTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        configured = os.environ.get("Q17_HISTORICAL_FIXTURES")
        if not configured:
            raise unittest.SkipTest("Q17_HISTORICAL_FIXTURES must name the historical provenance snapshot")
        cls.train = Path(configured) / "2025-12-08" / "shared_data_contract.v2.1.1.json"
        if sha256(cls.train) != HISTORICAL_TRAIN_SHA256:
            raise AssertionError("The historical training contract differs from its frozen provenance")
        cls.original = json.loads(cls.train.read_text(encoding="utf-8"))
        cls.bound_stems = ("acquisition_chain_verification", "acquisition_proof", "supersedes_contract")

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.original_hashes = {self.train: sha256(self.train)}
        for stem in self.bound_stems:
            path = self.train.parent / self.original[stem+"_file"]
            self.original_hashes[path] = sha256(path)
        self.addCleanup(self.assert_original_metadata_unchanged)

    def assert_original_metadata_unchanged(self):
        for path, digest in self.original_hashes.items():
            self.assertEqual(sha256(path), digest, f"Immutable fixture was changed: {path.name}")

    def copy_metadata(self):
        contract = copy.deepcopy(self.original)
        for stem in self.bound_stems:
            source = self.train.parent / contract[stem+"_file"]
            destination = self.root / source.name
            shutil.copyfile(source, destination)
            contract[stem+"_file"] = destination.name
        path = self.root / self.train.name
        path.write_text(json.dumps(contract), encoding="utf-8")
        return path, contract

    def test_actual_historical_training_chain_loads_without_fitting(self):
        loaded = load_contract(self.train, "exploratory_real")
        contract = loaded["contract"]
        self.assertEqual(loaded["producer_sha256"], HISTORICAL_TRAIN_SHA256)
        self.assertEqual(contract["version"], "2.1.1")
        self.assertEqual(contract["date"], "2025-12-08")
        self.assertEqual(contract["split_role"], "train")
        self.assertEqual(loaded["origin"], "exploratory_real")
        self.assertFalse(contract["fixture_only"])
        self.assertGreater(len(loaded["rows"]), 0)
        self.assertEqual({row["source_id"] for row in loaded["rows"]},
                         {contract["sources"][0]["source_id"]})
        self.assertTrue(all(row["release_ns"] is None and row["admission_evidence_ns"] is None
                            for row in loaded["rows"]))

    def test_changed_acquisition_proof_bytes_are_rejected(self):
        path, contract = self.copy_metadata()
        proof = self.root / contract["acquisition_proof_file"]
        proof.write_bytes(proof.read_bytes() + b"\n ")
        with self.assertRaisesRegex(ValueError, "binding checksum mismatch: acquisition_proof"):
            load_contract(path, "exploratory_real")

    def test_rehashed_verification_still_requires_affirmative_checks(self):
        path, contract = self.copy_metadata()
        verification_path = self.root / contract["acquisition_chain_verification_file"]
        verification = json.loads(verification_path.read_text(encoding="utf-8"))
        verification["passed"] = False
        verification_path.write_text(json.dumps(verification), encoding="utf-8")
        contract["acquisition_chain_verification_sha256"] = sha256(verification_path)
        path.write_text(json.dumps(contract), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Acquisition chain verification is incomplete"):
            load_contract(path, "exploratory_real")

    def test_provenance_patch_cannot_change_frozen_normalized_source_or_scope(self):
        for mutation in ("normalized_source", "state_scope"):
            path, contract = self.copy_metadata()
            if mutation == "normalized_source":
                contract["sources"][0]["sha256"] = "0"*64
            else:
                contract["scopes"]["Q17"]["state_scope"] = "complete_bbo"
            path.write_text(json.dumps(contract), encoding="utf-8")
            with self.subTest(mutation=mutation), self.assertRaisesRegex(ValueError, "previously frozen data scope"):
                load_contract(path, "exploratory_real")

    def test_consistently_rehashed_proof_rejects_contradictory_content_range(self):
        path, contract = self.copy_metadata()
        proof_path = self.root / contract["acquisition_proof_file"]
        proof = json.loads(proof_path.read_text(encoding="utf-8"))
        proof["transfer"]["content_range"] = "bytes 0-0/933171200"
        proof_path.write_text(json.dumps(proof), encoding="utf-8")
        contract["acquisition_proof_sha256"] = sha256(proof_path)
        verification_path = self.root / contract["acquisition_chain_verification_file"]
        verification = json.loads(verification_path.read_text(encoding="utf-8"))
        verification["acquisition_proof_sha256"] = contract["acquisition_proof_sha256"]
        verification_path.write_text(json.dumps(verification), encoding="utf-8")
        contract["acquisition_chain_verification_sha256"] = sha256(verification_path)
        path.write_text(json.dumps(contract), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "range transfer"):
            load_contract(path, "exploratory_real")


class TemporalGuardTests(unittest.TestCase):
    def test_freshness_covers_every_feature_label_and_latency_cut(self):
        event = np.arange(4001, dtype=np.int64)*(NS//10)
        full = dict(event_ns=event, available_ns=event.copy(), known_ns=event.copy(),
                    bid=np.full(len(event), 99.), ask=np.full(len(event), 101.),
                    bid_size=np.ones(len(event)), ask_size=np.ones(len(event)))
        baseline = build_arrays(full, "validation", 0, 400*NS)
        self.assertEqual(baseline["times"][0], 21*NS)
        self.assertEqual(baseline["max_input_age_ns"][0], 0)
        cuts = {"present": 210, "lag_1s": 200, "lag_5s": 160, "lag_20s": 10,
                "label_and_exit_0ms": 310, "entry_100ms": 211, "entry_500ms": 215,
                "exit_100ms": 311, "exit_500ms": 315}
        for name, removed in cuts.items():
            with self.subTest(input=name):
                keep = np.arange(len(event)) != removed
                quotes = {field: values[keep] for field, values in full.items()}
                unfiltered = build_arrays(quotes, "validation", 0, 400*NS)
                self.assertEqual(unfiltered["max_input_age_ns"][0], NS//10)
                filtered = build_arrays(quotes, "validation", 0, 400*NS, max_age_ns=NS//20)
                self.assertNotIn(21*NS, filtered["times"])
                self.assertTrue((filtered["max_input_age_ns"] <= NS//20).all())

    def test_horizon_endpoint_is_exclusive_and_lookback_start_inclusive(self):
        decision = 30*NS
        forwards = dict(forecast=10*NS, primary_utility=10_100_000_000,
                        full_utility=10_500_000_000, scheduling=131_500_000_000)
        for mode, forward in forwards.items():
            with self.subTest(mode=mode):
                window = dict(start_ns=decision-20*NS, end_ns=decision+forward)
                self.assertFalse(eligible(window, decision, mode))
                window["end_ns"] += 1
                self.assertTrue(eligible(window, decision, mode))
                window["start_ns"] += 1
                self.assertFalse(eligible(window, decision, mode))
        forecast_only = dict(start_ns=0, end_ns=decision+10*NS+1)
        self.assertTrue(eligible(forecast_only, decision, "forecast"))
        self.assertFalse(eligible(forecast_only, decision, "primary_utility"))
        self.assertFalse(eligible(forecast_only, decision, "full_utility"))
