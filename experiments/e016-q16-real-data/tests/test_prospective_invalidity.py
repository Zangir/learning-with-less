"""RV033 B1: a contradiction is not a missing outcome in a defined cohort."""
from contextlib import redirect_stdout
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from admission import sha256
from prospective import EXECUTABLE_PROTOCOL, REQUIRED_PREMISES, summarize
from r2_adapter import evaluate_episode
from r2_fixture_proposal import payload
from r2_selector import freeze_anchors
from r2_symbolic import SymbolicQueue
import run_prospective


def write_bundle(root, invalid=False):
    """Reuse the existing software fixture; no empirical source is asserted."""
    protocol = deepcopy(EXECUTABLE_PROTOCOL)
    protocol["scope"] = {"software_fixture_only": "RV033-B1", "empirical": False}
    data = payload()
    data.update(origin="real_native", fixture_only=False, clock=protocol["clock"])
    data["selection"] = freeze_anchors(data["candidates"], clock_kind="source_ordinal",
                                       specification=protocol["selection"])
    episode = data["episodes"][0]
    episode["initial_action_ordinal"] = 0
    for index, event in enumerate(episode["events"]):
        event["action_ordinal"] = index + 1
    if invalid:
        episode["events"][0]["diffs"][0]["raw_book_diff"]["update"]["origSz"] = "999"
    p, q, c = (root / name for name in ("protocol.json", "payload.json", "contract.json"))
    p.write_text(json.dumps(protocol))
    q.write_text(json.dumps(data))
    evidence = root / "evidence.txt"
    evidence.write_text("Software fixture only; no real source or empirical admission")
    ref = {"file": evidence.name, "sha256": sha256(evidence)}
    contract = {"schema": "q16-offline-source/1", "producer": "T-018", "origin": "real_native",
                "fixture_only": False, "protocol_sha256": sha256(p), "scope": protocol["scope"],
                "quantity_domain": "all_positive_integer_multiples", "quantity_quantum": "1",
                "premises": {key: {"supported": True, "evidence": [ref]} for key in REQUIRED_PREMISES},
                "payload": {"file": q.name, "sha256": sha256(q)}}
    c.write_text(json.dumps(contract))
    return c, p


def run_checkpoint(root, contract, protocol):
    with patch.object(run_prospective, "ARTIFACTS", root), \
            patch.object(run_prospective, "CONTRACT", contract), \
            patch.object(run_prospective, "PROTOCOL", protocol), redirect_stdout(io.StringIO()):
        exit_code = run_prospective.main()
    return exit_code, json.loads((root / "execution-checkpoint.json").read_text())


class CohortInvalidityTests(unittest.TestCase):
    def test_invalid_anchor_invalidates_bounds_without_dropping_other_anchors(self):
        rows = [{"status": "scored", "metrics": {"extrema_strictly_narrower": True}},
                {"status": "invalid_source_or_model", "reason": "impossible origSz=999"},
                {"status": "unresolved"}, {"status": "censored"}]
        summary = summarize(rows)
        self.assertEqual(summary["selected"], 4)
        self.assertEqual(summary["resolved"], 1)
        self.assertEqual(summary["invalid_anchors"], 1)
        self.assertEqual(summary["cohort_status"], "invalid_source_or_model")
        self.assertFalse(summary["comparison_defined"])
        self.assertIsNone(summary["cohort_tightening_fraction_identification_interval"])
        self.assertFalse(summary["scientific_negative"])

    def test_truth_unsat_and_unknown_are_distinct(self):
        for witness, expected in (("unsat", "invalid_source_or_model"), ("unknown", "unresolved")):
            with self.subTest(witness=witness), patch.object(SymbolicQueue, "check_truth",
                    return_value={"status": witness, "reason": "RV033-forced-status"}):
                result = evaluate_episode(payload()["episodes"][0], "1", "synthetic_integration")
                self.assertEqual(result["status"], expected)
                self.assertEqual(result["witnesses"]["count"]["status"], witness)
                summary = summarize([result])
                interval = summary["cohort_tightening_fraction_identification_interval"]
                self.assertEqual(interval, ["0", "1"] if witness == "unknown" else None)

    def test_infeasible_projection_invalidates_but_unresolved_remains_missing(self):
        for projection, expected in (("infeasible", "invalid_source_or_model"), ("unresolved", "unresolved")):
            with self.subTest(projection=projection), patch.object(SymbolicQueue, "project",
                    return_value={"status": projection, "reason": "RV033-forced-status"}):
                result = evaluate_episode(payload()["episodes"][0], "1", "synthetic_integration")
                self.assertEqual(result["status"], expected)

    def test_contradictory_extrema_status_is_not_solver_unknown(self):
        queue = SymbolicQueue(2, 1, [("A", 1)])
        with patch.object(queue, "_extreme", side_effect=[(0, "sat", None), (None, "unsat", None)]):
            self.assertEqual(queue.project()["status"], "infeasible")

    def test_exact_reviewed_origsz_failure_is_invalid_end_to_end(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            contract, protocol = write_bundle(root, invalid=True)
            exit_code, checkpoint = run_checkpoint(root, contract, protocol)
            self.assertEqual(exit_code, 3)
            self.assertEqual(checkpoint["status"], "invalid_source_or_model_cohort")
            self.assertFalse(checkpoint["scientific_negative"])
            for horizon in (8, 10):
                summary = checkpoint["summaries"][str(horizon)]
                self.assertEqual(summary["selected"], 1)
                self.assertEqual(summary["invalid_anchors"], 1)
                self.assertIsNone(summary["cohort_tightening_fraction_identification_interval"])
                row = json.loads((root / f"empirical-h{horizon}/results.jsonl").read_text())
                self.assertEqual(row["candidate_id"], "fixture-anchor-1")
                self.assertIn("origSz", row["reason"])

    def test_valid_and_unknown_end_to_end_remain_distinct_from_invalidity(self):
        for unknown in (False, True):
            with self.subTest(unknown=unknown), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                contract, protocol = write_bundle(root)
                if unknown:
                    with patch.object(SymbolicQueue, "check_truth", return_value={"status": "unknown"}):
                        exit_code, checkpoint = run_checkpoint(root, contract, protocol)
                else:
                    exit_code, checkpoint = run_checkpoint(root, contract, protocol)
                self.assertEqual(exit_code, 0)
                self.assertEqual(checkpoint["status"], "source_supported_computation_with_missing_outcomes_pending_review")
                first = checkpoint["summaries"]["8"]
                self.assertEqual(first["dispositions"], {"unresolved": 1} if unknown else {"scored": 1})
                self.assertTrue(first["comparison_defined"])
                self.assertIsNotNone(first["cohort_tightening_fraction_identification_interval"])
                self.assertEqual(checkpoint["summaries"]["10"]["dispositions"], {"censored": 1})

    def test_rehashed_protocol_mutation_cannot_reach_execution(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            contract, protocol = write_bundle(root)
            changed = json.loads(protocol.read_text())
            changed.update(fallback_costs=[2, 4], incomplete_execution_cost=99)
            protocol.write_text(json.dumps(changed))
            bound = json.loads(contract.read_text())
            bound["protocol_sha256"] = sha256(protocol)
            contract.write_text(json.dumps(bound))
            exit_code, checkpoint = run_checkpoint(root, contract, protocol)
            self.assertEqual(exit_code, 2)
            self.assertEqual(checkpoint["summaries"], {})
            self.assertIn("fallback_costs", checkpoint["reason"])
            self.assertFalse((root / "empirical-h8/results.jsonl").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
