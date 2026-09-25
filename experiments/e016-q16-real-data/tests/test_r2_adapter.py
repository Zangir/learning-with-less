import unittest
from unittest.mock import patch

from r2_adapter import evaluate_episode
from r2_fixture_proposal import payload
from r2_consumer import run_bundle


class ScalableAdapterTests(unittest.TestCase):
    def test_zero_cleanup_and_partial_cancel_exact(self):
        data = payload()
        result = evaluate_episode(data["episodes"][0], "1", "synthetic_integration")
        self.assertEqual(result["status"], "scored")
        self.assertEqual(result["economic_events"], 8)
        self.assertEqual(len(result["lineage"]), 9)
        self.assertEqual(result["truth"]["fill_fraction"], "2/3")
        self.assertTrue(result["truth_path_contained"])
        self.assertEqual(result["lineage"][0]["physical_live_identity_count"], 2)
        self.assertEqual(result["lineage"][0]["observed_positive_count"], 1)

    def test_missing_horizon_is_censored(self):
        episode = payload()["episodes"][0]
        episode["events"] = episode["events"][:4]
        result = evaluate_episode(episode, "1", "synthetic_integration")
        self.assertEqual(result["status"], "censored")
        self.assertNotIn("projections", result)

    def test_unknown_origin_rejected(self):
        with self.assertRaises(ValueError):
            evaluate_episode(payload()["episodes"][0], "1", "real")

    def test_ninth_economic_event_cannot_change_fixed_horizon(self):
        episode = payload()["episodes"][0]
        episode["events"].append({"evidence_refs": []})
        result = evaluate_episode(episode, "1", "synthetic_integration")
        self.assertEqual(result["status"], "scored")
        self.assertEqual(result["economic_events"], 8)

    def test_bundle_retains_failure_and_continues_next_anchor(self):
        data = payload()
        data["episodes"] = [{"episode_id": "invalid"}, data["episodes"][0]]
        with patch('r2_consumer.load_q16_bundle', return_value=({'origin': 'synthetic_integration'}, data)), \
             patch('r2_consumer.sha256', return_value='fixture-digest'), \
             patch('r2_adapter.evaluate_episode', side_effect=[ValueError('FIFO failure'), {'status': 'scored'}]):
            result = run_bundle('fixture-path')
        self.assertEqual(len(result['results']), 2)
        self.assertEqual(result['results'][0]['status'], 'model_invariant_failure')
        self.assertEqual(result['synthetic_episodes_scored'], 1)

    def test_invalid_clock_missing_provenance_and_protected_real_probe(self):
        for issue in ("clock", "provenance", "protected"):
            episode = payload()["episodes"][0]
            if issue == "clock":
                episode["start_ns"] = 0.0
            elif issue == "provenance":
                episode["events"][0]["evidence_refs"] = []
            else:
                episode["probe_cancellable"] = False
            with self.assertRaises(ValueError):
                evaluate_episode(episode, "1", "exploratory_real")


if __name__ == "__main__":
    unittest.main(verbosity=2)
