import unittest
import numpy as np
from completion.q17_receipt import NS, project_native, control_probabilities


def quotes():
    t = np.arange(800, dtype=np.int64) * NS
    mid = 100_00000000 + (np.arange(len(t)) % 7) * 1000000
    return dict(event_ns=t, receipt_ns=t + NS // 4, source_ordinal=np.arange(len(t)),
                segment_id=np.zeros(len(t), dtype=np.int64), bid_px_e8=mid - 1000000,
                ask_px_e8=mid + 1000000, bid_sz_e8=np.full(len(t), 2_00000000),
                ask_sz_e8=np.full(len(t), 1_00000000))


class Q17ReceiptTests(unittest.TestCase):
    def test_observations_and_labels_use_distinct_clocks(self):
        day, _ = project_native(quotes(), "1970-01-01", "test")
        self.assertEqual(day["feature_source_ordinals"][0, 0], 20)
        self.assertEqual(day["label_source_ordinals"][0, 0], 21)
        self.assertTrue((day["feature_receipt_ns"][:, 0] <= day["times"]).all())
        self.assertTrue((day["outcome_available_ns"] > day["times"] + 10.5 * NS).all())

    def test_disconnects_prevent_schedule_bridge(self):
        rows = quotes()
        rows["segment_id"][400:] = 1
        day, _ = project_native(rows, "1970-01-01", "test")
        self.assertTrue((np.diff(day["segment_id"][day["schedule_rows"]], axis=1) == 0).all())
        self.assertTrue((np.diff(day["times"][day["schedule_rows"]], axis=1) == 11 * NS).all())

    def test_on_change_silence_is_not_a_synthetic_disconnect(self):
        rows = quotes()
        keep = np.r_[np.arange(200), np.arange(210, 800)]
        rows = {key: x[keep] for key, x in rows.items()}
        day, audit = project_native(rows, "1970-01-01", "test")
        self.assertTrue(((day["times"] >= 200 * NS) & (day["times"] < 210 * NS)).any())
        self.assertEqual(audit["excluded_segments"], [])

    def test_original_controls_are_reproducible_and_label_oracle_is_explicit(self):
        day, _ = project_native(quotes(), "1970-01-01", "test")
        p = control_probabilities(day, "random", 17, "BTC", "1970-01-01")
        np.testing.assert_array_equal(p, control_probabilities(day, "random", 17, "BTC", "1970-01-01"))
        self.assertFalse(np.array_equal(p, control_probabilities(day, "random", 29, "BTC", "1970-01-01")))
        np.testing.assert_array_equal(control_probabilities(day, "oracle", 0, "BTC", "1970-01-01").argmax(1), day["y"])

    def test_transfer_keeps_abstention_denominator_and_linear_fee_basis(self):
        from completion.q17_runs import scenario_metrics
        day = dict(times=np.arange(3), y=np.array([2, 2, 1]),
                   entry_bid=np.full((3, 3), 100.), entry_ask=np.full((3, 3), 100.),
                   exit_bid=np.full((3, 3), 110.), exit_ask=np.full((3, 3), 110.))
        p = np.array([[.1, .1, .8], [.2, .3, .5], [.1, .8, .1]])
        records = scenario_metrics(day, p)
        self.assertEqual(len(records), 108)
        row = next(r for r in records if (r["policy"], r["delay_ms"], r["fee_bps"],
                   r["fill_fraction"], r["adverse_selection_bps"]) == ("fixed_confidence", 100, 5, .5, 1))
        self.assertEqual(row["trades"], 1)
        self.assertAlmostEqual(row["utility_bps"], .5 * (1000 - 5 * 2.1 - 1) / 3)


if __name__ == "__main__":
    unittest.main()
