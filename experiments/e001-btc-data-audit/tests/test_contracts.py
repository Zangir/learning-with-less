"""Independent arithmetic and leakage guards for the intended real-data adapters."""
import json
from pathlib import Path
import unittest
import numpy as np
from hyperliquid_contracts import (decode_fixed_units, linear_round_trip,
    fixed_base_schedule_values, require_replay_evidence, chronological_masks)


class Contracts(unittest.TestCase):
    def test_exact_price_and_size_encoding(self):
        encoded = np.array([(2 << 29) | 9654321, (5 << 29) | 123], dtype=np.uint32)
        self.assertEqual(decode_fixed_units(encoded).tolist(), [965432100000, 12300])
        with self.assertRaises(ValueError):
            decode_fixed_units(encoded, decimals=2)

    def test_linear_long_short_and_flat_against_cash_flows(self):
        day = {"entry_ask":np.array([[101.],[99.],[100.]]), "entry_bid":np.array([[100.],[98.],[99.]]),
               "exit_bid":np.array([[103.],[96.],[101.]]), "exit_ask":np.array([[104.],[97.],[102.]])}
        probabilities=np.eye(3)[[2,0,1]]
        actual, _, _ = linear_round_trip(day, probabilities, 0, 5)
        expected=np.array([((103-101)-.0005*(101+103))/101*10000,
                           ((98-97)-.0005*(98+97))/98*10000, 0])
        np.testing.assert_allclose(actual,expected,atol=1e-10,rtol=0)

    def test_fixed_base_schedule_uses_arithmetic_price(self):
        prices=np.array([[100.,110.,90.]])
        np.testing.assert_allclose(fixed_base_schedule_values(prices,np.array([2])), [1000.])

    def test_uncertified_replay_is_rejected(self):
        with self.assertRaisesRegex(ValueError,"initial_state_verified"):
            require_replay_evidence({})
        require_replay_evidence(dict(initial_state_verified=True,event_time_verified=True,
                                    event_order_verified=True,trade_status_semantics_verified=True))

    def test_split_containment_and_no_shuffling(self):
        dates=np.array(["2025-12-01T00:00:00", "2025-12-01T00:02:00", "2025-12-14T23:59:55",
                        "2025-12-15T00:00:00", "2025-12-15T00:02:00", "2025-12-22T00:02:00"],dtype="datetime64[ns]")
        masks=chronological_masks(dates.astype(np.int64))
        self.assertEqual(masks["train"].tolist(),[False,True,False,False,False,False])
        self.assertEqual(np.where(masks["validation"])[0].tolist(),[4])
        self.assertEqual(np.where(masks["test"])[0].tolist(),[5])
        with self.assertRaises(ValueError):
            chronological_masks(dates.astype(np.int64)[::-1])


if __name__ == "__main__":
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Contracts))
    Path(__file__).with_name("contract_tests.json").write_text(json.dumps(dict(tests=result.testsRun,passed=result.wasSuccessful(),failures=len(result.failures),errors=len(result.errors)),indent=2))
    raise SystemExit(0 if result.wasSuccessful() else 1)
