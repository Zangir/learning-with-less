"""Regression checks for prospective source handling; no empirical claims."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from admission import sha256
from prospective import (EXECUTABLE_PROTOCOL, REQUIRED_PREMISES, SourceBlocked, finite_crosscheck,
                         load_bundle, offline_episode, paired_metrics, run_supported, summarize)
from r2_adapter import evaluate_episode
from r2_fixture_proposal import payload
from r2_symbolic import SymbolicQueue
from r2_selector import freeze_anchors


class ProspectiveTests(unittest.TestCase):
    def test_existing_fixture_metrics_and_independent_solver(self):
        episode = payload()["episodes"][0]
        result = evaluate_episode(episode, "1", "synthetic_integration")
        metrics = paired_metrics(result)
        self.assertEqual(metrics["stipulated_costs"]["3"]["volume"], 3)
        self.assertEqual(finite_crosscheck(episode, "1", result)["status"], "matched")

    def test_clock_is_internal_ordinal_not_receipt(self):
        episode = payload()["episodes"][0]
        episode["start_ns"] = 123456789
        episode["initial_action_ordinal"] = 0
        for index, event in enumerate(episode["events"]):
            event["action_ordinal"] = index + 1
        converted = offline_episode(episode)
        self.assertEqual(converted["start_ns"], episode["initial_raw_seq"])
        self.assertNotEqual(converted["start_ns"], episode["start_ns"])
        episode["events"][1]["action_ordinal"] = 1
        with self.assertRaisesRegex(ValueError, "strictly increase"):
            offline_episode(episode)

    def test_missing_outcomes_never_become_negative(self):
        self.assertIsNone(summarize([])["cohort_tightening_fraction_identification_interval"])
        result = summarize([{"status": "unresolved"}, {"status": "censored"}])
        self.assertEqual(result["cohort_tightening_fraction_identification_interval"], ["0", "1"])
        self.assertFalse(result["scientific_negative"])
        result = summarize([{"status": "scored", "metrics": {"extrema_strictly_narrower": True}},
                            {"status": "unresolved"}])
        self.assertEqual(result["cohort_tightening_fraction_identification_interval"], ["1/2", "1"])

    def test_ten_event_counterpart_preserves_default_eight(self):
        episode = payload()["episodes"][0]
        for index in (1, 2):
            event = deepcopy(episode["events"][-1])
            seq = episode["events"][-1]["diffs"][-1]["raw_seq"] + 1
            event.update(kind="A", event_ns=100 + index, available_ns=100 + index, fills=[])
            event["diffs"] = [{"raw_seq": seq, "coin": "BTC", "side": "B", "px": "100",
                               "oid": f"additional-{index}", "raw_book_diff": {"new": {"sz": "1"}}}]
            episode["events"].append(event)
        eight = evaluate_episode(episode, "1", "synthetic_integration")
        ten = evaluate_episode(episode, "1", "synthetic_integration", horizon=10)
        self.assertEqual(eight["economic_events"], 8)
        self.assertEqual(ten["economic_events"], 10)
        self.assertEqual(ten["status"], "scored")
        self.assertEqual(finite_crosscheck(episode, "1", ten)["status"], "matched")
        with self.assertRaises(ValueError):
            SymbolicQueue(0, 1, [("A", 1)] * 9)
        with self.assertRaises(ValueError):
            evaluate_episode(episode, "1", "synthetic_integration", horizon=9)

    def test_fixture_and_missing_source_support_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            protocol = deepcopy(EXECUTABLE_PROTOCOL)
            protocol["scope"] = {"test_only": True}
            p = root / "protocol.json"
            p.write_text(json.dumps(protocol))
            contract = {"schema": "q16-offline-source/1", "producer": "T-018",
                        "origin": "real_native", "fixture_only": False,
                        "protocol_sha256": sha256(p), "scope": protocol["scope"],
                        "quantity_domain": "all_positive_integer_multiples"}
            c = root / "contract.json"
            for mutation, message in (({"fixture_only": True}, "real-native"),
                                      ({"producer": "T-008"}, "real-native"),
                                      ({"protocol_sha256": "wrong"}, "frozen protocol"),
                                      ({"quantity_domain": "observed_gcd"}, "integer-domain"),
                                      ({}, "initial_relevant_level")):
                c.write_text(json.dumps({**deepcopy(contract), **mutation}))
                with self.assertRaisesRegex(SourceBlocked, message):
                    load_bundle(c, p)

    def test_hash_bound_execution_plumbing_in_temporary_test_directory(self):
        # Testing the admission plumbing is not admission of this fixture.
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            protocol = deepcopy(EXECUTABLE_PROTOCOL)
            protocol["scope"] = {"test_only": True}
            p = root / "protocol.json"
            p.write_text(json.dumps(protocol))
            data = payload()
            data.update(origin="real_native", fixture_only=False, clock=protocol["clock"])
            data["selection"] = freeze_anchors(data["candidates"], clock_kind="source_ordinal",
                                               specification=protocol["selection"])
            episode = data["episodes"][0]
            episode["initial_action_ordinal"] = 0
            for index, event in enumerate(episode["events"]):
                event["action_ordinal"] = index + 1
            q = root / "payload.json"
            q.write_text(json.dumps(data))
            evidence = root / "evidence.txt"
            evidence.write_text("Test fixture only: no scientific source assertion")
            ref = {"file": evidence.name, "sha256": sha256(evidence)}
            contract = {"schema": "q16-offline-source/1", "producer": "T-018",
                        "origin": "real_native", "fixture_only": False,
                        "protocol_sha256": sha256(p), "scope": protocol["scope"],
                        "quantity_domain": "all_positive_integer_multiples", "quantity_quantum": "1",
                        "premises": {key: {"supported": True, "evidence": [ref]} for key in REQUIRED_PREMISES},
                        "payload": {"file": q.name, "sha256": sha256(q)}}
            c = root / "contract.json"
            c.write_text(json.dumps(contract))
            result = run_supported(c, p, root / "h8")
            self.assertEqual(result["resolved"], 1)
            self.assertFalse(result["independently_accepted"])
            self.assertEqual(run_supported(c, p, root / "h10", horizon=10)["dispositions"], {"censored": 1})
            with self.assertRaises(FileExistsError):
                run_supported(c, p, root / "h8")
            with self.assertRaises(SourceBlocked):
                run_supported(c, p, root / "h9", horizon=9)
            q.write_text("{}")
            with self.assertRaisesRegex(SourceBlocked, "digest mismatch"):
                load_bundle(c, p)


if __name__ == "__main__":
    unittest.main(verbosity=2)
