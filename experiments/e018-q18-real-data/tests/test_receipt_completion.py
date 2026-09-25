"""Authored clock and nesting invariants; these fixtures are not market evidence."""
import unittest
import numpy as np
from completion.receipt_features import NS, build_q18_cache, shifted_views, validate_rows


def quotes():
    n = 500
    rows = dict(event_ns=np.arange(n, dtype=np.int64) * NS,
                receipt_ns=np.arange(n, dtype=np.int64) * NS + NS // 4,
                source_ordinal=np.arange(n, dtype=np.int64),
                segment_id=np.zeros(n, dtype=np.int64))
    mid = 100_00000000 + np.arange(n, dtype=np.int64) * 1000000
    for k in range(5):
        rows[f"bid_px_e8_{k}"] = mid - (k + 1) * 1000000
        rows[f"ask_px_e8_{k}"] = mid + (k + 1) * 1000000
        rows[f"bid_sz_e8_{k}"] = np.full(n, 2_00000000, dtype=np.int64)
        rows[f"ask_sz_e8_{k}"] = np.full(n, 1_00000000, dtype=np.int64)
    return rows


class ReceiptFeatureTests(unittest.TestCase):
    def test_receipt_selects_past_quote_and_future_received_target(self):
        cache, _ = build_q18_cache(quotes(), "1970-01-01", 5)
        self.assertEqual(cache["times"][0], 21 * NS)
        self.assertEqual(cache["source_ordinal"][0], 20)
        self.assertEqual(cache["label_end_ns"][0], 30 * NS + NS // 4)
        self.assertEqual(cache["outcome_available_ns"][0], 31 * NS + NS // 4)

    def test_exact_delay_and_own_mid_normalization(self):
        cache, _ = build_q18_cache(quotes(), "1970-01-01", 11)
        views, targets, keep = shifted_views(cache)
        np.testing.assert_array_equal(targets, cache["returns"][keep])
        np.testing.assert_array_equal(views["d5/20sec/delay55"][0], cache["d5_own"][0])
        self.assertEqual(cache["times"][keep[0]] - cache["times"][0], 55 * NS)
        np.testing.assert_array_equal(views["d1/instant/delay0"][:, :5],
                                      views["d5/instant/delay0"][:, :5])
        self.assertTrue((views["d1/instant/delay55"][:, 5:] == 0).all())

    def test_future_changes_do_not_leak_into_prefix(self):
        rows = quotes()
        before, _ = build_q18_cache(rows, "1970-01-01", 5)
        for side in ("bid", "ask"):
            for k in range(5):
                rows[f"{side}_px_e8_{k}"][22:] += 10_00000000
        after, _ = build_q18_cache(rows, "1970-01-01", 5)
        np.testing.assert_array_equal(before["d5_own"][0], after["d5_own"][0])
        self.assertNotEqual(before["returns"][0], after["returns"][0])

    def test_segment_break_prevents_delayed_or_target_bridge(self):
        rows = quotes()
        rows["segment_id"][250:] = 1
        cache, _ = build_q18_cache(rows, "1970-01-01", 5)
        views, _, keep = shifted_views(cache)
        t = cache["times"][keep]
        self.assertFalse(((t >= 250 * NS) & (t < 326 * NS)).any())
        self.assertTrue(all(len(x) == len(keep) for x in views.values()))

    def test_shallow_timing_does_not_reveal_deeper_changes(self):
        rows = quotes()
        for side in ("bid", "ask"):
            rows[f"{side}_px_e8_0"][:] = rows[f"{side}_px_e8_0"][0]
        # Keep deeper levels ordered while only quantities change.
        for side in ("bid", "ask"):
            for k in range(1, 5):
                rows[f"{side}_px_e8_{k}"][:] = rows[f"{side}_px_e8_{k}"][0]
        rows["bid_sz_e8_4"][::2] += 1000000
        cache, _ = build_q18_cache(rows, "1970-01-01", 5)
        np.testing.assert_array_equal(cache["d1_own"][:, 28], 20)
        np.testing.assert_array_equal(cache["d1_own"][:, 29], 0)
        self.assertTrue((cache["d5_own"][:, 29] == 20).all())

    def test_inversions_and_undeclared_gaps_fail(self):
        for key in ("event_ns", "receipt_ns", "source_ordinal"):
            rows = quotes()
            rows[key][10] = rows[key][8]
            with self.assertRaisesRegex(ValueError, "inversion"):
                validate_rows(rows)
        rows = quotes()
        rows["receipt_ns"][10:] += 5 * NS
        with self.assertRaisesRegex(ValueError, "gap"):
            validate_rows(rows)

    def test_pilot_and_transfer_estimands_are_distinct(self):
        from completion.q18_runs import relative_loss
        self.assertAlmostEqual(relative_loss([2, 12], [1, 10], "ratio_of_means"), 3 / 11)
        self.assertAlmostEqual(relative_loss([2, 12], [1, 10], "mean_of_ratios"), .6)


if __name__ == "__main__":
    unittest.main()
