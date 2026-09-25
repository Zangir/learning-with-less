"""Focused invariant tests. Fixtures are constructed, never market evidence."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from adapter import adapt_episode, units
from admission import AdmissionBlocked, REQUIRED_CHECKS, load_admitted, sha256
from core import State, StateCapExceeded, advance, initial_states, labels, transition
import run_pilot


def fixture():
    def diff(seq, oid, change):
        return {"raw_seq": seq, "coin": "BTC", "side": "B", "px": "100",
                "oid": oid, "raw_book_diff": change}

    def event(kind, rows, fills=()):
        seq = rows[-1]["raw_seq"]
        return {"kind": kind, "event_ns": seq * 10, "available_ns": seq * 10,
                "evidence_refs": ["synthetic-fixture"], "diffs": rows, "fills": list(fills)}

    return {"episode_id": "constructed-partial-and-cancel", "coin": "BTC", "side": "B",
            "px": "100", "probe_id": "p", "probe_cancellable": True,
            "initial": [{"oid": "a", "sz": "2"}, {"oid": "p", "sz": "3"}],
            "start_ns": 0, "initial_available_ns": 0, "initial_raw_seq": 0,
            "horizon_complete": True, "events": [
                event("T", [diff(1, "a", "remove"), diff(2, "p", {"update": {"origSz": "3", "newSz": "2"}})],
                      [{"oid": "a", "sz": "2"}, {"oid": "p", "sz": "1"}]),
                event("C", [diff(3, "p", {"update": {"origSz": "2", "newSz": "1"}})]),
                event("A", [diff(4, "b", {"new": {"sz": "2"}})]),
                event("T", [diff(5, "p", "remove")], [{"oid": "p", "sz": "1"}]),
                event("A", [diff(6, "c", {"new": {"sz": "1"}})]),
                event("C", [diff(7, "b", "remove")]),
                event("A", [diff(8, "d", {"new": {"sz": "1"}})]),
                event("T", [diff(9, "c", "remove")], [{"oid": "c", "sz": "1"}]),
            ]}


class EngineTests(unittest.TestCase):
    def test_initial_cardinality_and_preflight(self):
        self.assertEqual(len(initial_states(8, 1)), 128)
        for total in (18, 10**12):
            with self.assertRaises(StateCapExceeded):
                initial_states(total, 1)

    def test_transition_cap_never_truncates(self):
        with self.assertRaises(StateCapExceeded):
            advance(initial_states(5, 1), "A", 1, cap=2)

    def test_unit_probe_original_cancellation_rule(self):
        state = State(((1, True),))
        self.assertEqual(transition(state, "C", 1, False), set())
        self.assertEqual(transition(state, "C", 1, True), {State((), 0, 1)})

    def test_partial_is_not_full(self):
        self.assertEqual(labels({State(((2, True),), 1)}, 3),
                         {"any_fill": [1], "full_fill": [0], "fill_fraction": ["1/3"]})

    def test_exact_lattice_and_float_rejection(self):
        self.assertEqual(units("0.12345678", "0.00000001"), 12345678)
        for value, quantum in [("0.000015", "0.00001"), (0.1, "0.1"),
                               ("NaN", "1"), ("1", "0"), ("-1", "1")]:
            with self.assertRaises(ValueError):
                units(value, quantum)


class AdapterTests(unittest.TestCase):
    def test_cancelled_probe_retained_and_targets_distinct(self):
        result = adapt_episode(fixture(), "1")
        self.assertEqual(result["status"], "scored")
        self.assertEqual(result["cancelled_units"], 1)
        self.assertEqual(result["truth"], {"any_fill": [1], "full_fill": [0], "fill_fraction": ["2/3"]})
        self.assertEqual(result["observations"][0]["quantity_units"], 3)
        self.assertEqual(len(result["observations"]), 8)
        self.assertNotIn("oid", str(result))

    def test_censor_incomplete_horizon(self):
        episode = fixture()
        episode["events"] = episode["events"][:2]
        result = adapt_episode(episode, "1")
        self.assertEqual(result["status"], "censored")
        self.assertNotIn("truth", result)

    def test_fifo_rejection(self):
        episode = fixture()
        episode["events"][0]["diffs"].reverse()
        with self.assertRaisesRegex(ValueError, "FIFO"):
            adapt_episode(episode, "1")

    def test_unknown_order_rejection(self):
        episode = fixture()
        episode["events"][0]["diffs"][0]["oid"] = "unknown"
        with self.assertRaisesRegex(ValueError, "Unknown"):
            adapt_episode(episode, "1")

    def test_update_old_quantity_reconciliation(self):
        episode = fixture()
        episode["events"][0]["diffs"][1]["raw_book_diff"]["update"]["origSz"] = "4"
        with self.assertRaisesRegex(ValueError, "preceding state"):
            adapt_episode(episode, "1")

    def test_execution_ledger_reconciliation(self):
        episode = fixture()
        episode["events"][0]["fills"][0]["sz"] = "1"
        with self.assertRaisesRegex(ValueError, "Execution ledger"):
            adapt_episode(episode, "1")

    def test_no_clock_sort_or_future_initialization(self):
        for key in ("clock", "initial", "sequence"):
            episode = fixture()
            if key == "clock":
                episode["events"][1]["event_ns"] = 1
            elif key == "initial":
                episode["initial_available_ns"] = 1
            else:
                episode["events"][1]["diffs"][0]["raw_seq"] = 1
            with self.assertRaises(ValueError):
                adapt_episode(episode, "1")

    def test_reject_invented_or_combined_event_types(self):
        for kind in ("unknown", "C", "A"):
            episode = fixture()
            episode["events"][0]["kind"] = kind
            with self.assertRaises(ValueError):
                adapt_episode(episode, "1")

    def test_reject_level_switch_and_non_lattice(self):
        episode = fixture()
        episode["events"][0]["diffs"][0]["px"] = "101"
        with self.assertRaises(ValueError):
            adapt_episode(episode, "1")
        with self.assertRaises(ValueError):
            adapt_episode(fixture(), "2")

    def test_invalid_price_rejected(self):
        for value in ("NaN", "Infinity", "broken"):
            episode = fixture()
            episode["events"][0]["diffs"][0]["px"] = value
            with self.assertRaises(ValueError):
                adapt_episode(episode, "1")


class AdmissionTests(unittest.TestCase):
    def test_malformed_configuration_replaces_stale_success(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            output = directory / "pilot_result.json"
            for malformed in ("[]", "{broken"):
                output.write_text('{"status":"development_pilot_only","scored_real_episodes":999}')
                (directory / "pilot_config.json").write_text(malformed)
                with patch.object(run_pilot, "HERE", directory), patch.object(run_pilot, "OUTPUT", output):
                    run_pilot.main()
                result = json.loads(output.read_text())
                self.assertEqual(result["status"], "blocked")
                self.assertEqual(result["scored_real_episodes"], 0)

    def test_missing_certificate_is_blocked(self):
        with self.assertRaises(AdmissionBlocked):
            load_admitted({})

    def test_digest_scope_and_explicit_checks(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            config = {key: str(directory / (key + ".json")) for key in
                      ("contract_path", "coordinator_review_path", "episodes_path")}
            Path(config["episodes_path"]).write_text(json.dumps([fixture()]))
            contract = {"schema_version": "q16-admission-v1", "version": "test-only",
                        "issuer_task": "T-008", "decision": "affirmative", "quantity_quantum": "1",
                        "scope": {"experiment": "E-016", "coin": "BTC", "use": "development_pilot",
                                  "start_ns": 0, "end_ns": 100},
                        "checks": {key: {"passed": True, "evidence": "synthetic-test"} for key in REQUIRED_CHECKS},
                        "episodes_sha256": sha256(config["episodes_path"])}
            def save_and_review(candidate):
                Path(config["contract_path"]).write_text(json.dumps(candidate))
                review = {"decision": "approved", "role": "coordinator", "review_evidence": "test-only",
                          "contract_sha256": sha256(config["contract_path"])}
                Path(config["coordinator_review_path"]).write_text(json.dumps(review))
            save_and_review(contract)
            self.assertEqual(len(load_admitted(config)[1]), 1)
            for key in REQUIRED_CHECKS:
                candidate = copy.deepcopy(contract)
                candidate["checks"][key]["passed"] = False
                save_and_review(candidate)
                with self.assertRaises(AdmissionBlocked):
                    load_admitted(config)
            candidate = copy.deepcopy(contract)
            candidate["scope"]["end_ns"] = 30
            save_and_review(candidate)
            with self.assertRaises(AdmissionBlocked):
                load_admitted(config)
            save_and_review(contract)
            Path(config["coordinator_review_path"]).write_text('{"decision":"approved"}')
            with self.assertRaises(AdmissionBlocked):
                load_admitted(config)
            save_and_review(contract)
            Path(config["episodes_path"]).write_text("[]")
            with self.assertRaises(AdmissionBlocked):
                load_admitted(config)


if __name__ == "__main__":
    unittest.main(verbosity=2)
