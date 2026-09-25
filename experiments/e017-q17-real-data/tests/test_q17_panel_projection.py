"""Authored sampled-quote fixtures; no historical observations or model fitting."""
import copy
import unittest
from unittest.mock import patch

import numpy as np

from q17_transfer.features import NS, DAY
from q17_transfer.panel_projection import OFFSETS_NS, project_day, concatenate_days
from q17_transfer.protocol import PROTOCOL


DATE = "2040-01-01"  # Fictional fixture calendar, not a selected empirical date.


def loaded_quotes(offsets=None, date=DATE, disconnects=(), separate_windows=False):
    offsets = np.arange(900, dtype=np.int64) * NS if offsets is None else offsets
    base = int(np.datetime64(date, "ns").astype(np.int64))
    rows = [dict(asset="BTC", source_id="authored-btc", source_ordinal=i,
                 event_ns=base+int(offset), provider_receive_ns=base+int(offset)+10_000_000,
                 bid_prices_units8=[9_999_000_000], ask_prices_units8=[10_001_000_000],
                 bid_sizes_units8=[200_000_000], ask_sizes_units8=[100_000_000])
            for i, offset in enumerate(offsets)]
    boundaries = [0] + [int(np.searchsorted(offsets, cut)) for cut in disconnects] + [len(rows)]
    segments = [dict(segment_id=sid, first_row_index=a, stop_row_index=b,
                     start_ns=rows[a]["event_ns"], end_ns=rows[b-1]["event_ns"]+1,
                     first_source_ordinal=a, last_source_ordinal=b-1)
                for sid, (a, b) in enumerate(zip(boundaries, boundaries[1:]))]
    ranges = segments if separate_windows else [dict(start_ns=rows[0]["event_ns"],
        end_ns=rows[-1]["event_ns"]+1, first_source_ordinal=0, last_source_ordinal=len(rows)-1)]
    windows = [dict(scope="Q17", asset="BTC", source_ids=["authored-btc"],
                    window_id=f"authored-window-{i}", **span) for i, span in enumerate(ranges)]
    return dict(rows=rows, segments=segments, windows=windows)


def without_cut(offsets, cutoff, age_ns):
    # Leave a short source gap: stale data must fail even without an outage.
    return offsets[~((offsets > cutoff-age_ns) & (offsets < cutoff+50_000_000))]


class PanelProjectionTests(unittest.TestCase):
    def assert_schedule_boundaries(self, day):
        groups = day["schedule_rows"]
        self.assertGreater(len(groups), 0)
        np.testing.assert_array_equal(np.diff(day["times"][groups], axis=1), 11*NS)
        self.assertTrue((day["segment_id"][groups] == day["segment_id"][groups[:, :1]]).all())
        self.assertTrue((day["date"][groups] == day["date"][groups[:, :1]]).all())
        self.assertEqual(len(np.unique(groups)), groups.size)

    def test_exact_features_nine_cut_lineage_and_receipt_separation(self):
        loaded = loaded_quotes()
        day, diagnostic = project_day(loaded, "BTC", DATE, "test", "hour00")
        base = loaded["rows"][0]["event_ns"]
        self.assertEqual(day["times"][0], base+21*NS)
        np.testing.assert_allclose(day["X"][0], [1/3, 2, 0, 0, 0])
        expected = np.array([1, 16, 20, 21, 21, 21, 31, 31, 31])
        np.testing.assert_array_equal(day["selected_source_ordinals"][0], expected)
        np.testing.assert_array_equal(day["source_age_ns"][0], [0, 0, 0, 0, 100_000_000, 500_000_000, 0, 100_000_000, 500_000_000])
        np.testing.assert_array_equal(day["provider_receive_ns"], day["selected_event_ns"]+10_000_000)
        self.assertEqual(day["outcome_available_ns"][0], base+32*NS)
        self.assertFalse(diagnostic["actual_release_or_admission_claim"])
        self.assertTrue(diagnostic["retrospective_future_coverage_mask"])
        self.assertEqual(set(diagnostic["source_age_by_offset_ns"]), set(map(str, OFFSETS_NS)))
        self.assert_schedule_boundaries(day)

    def test_short_disconnect_in_separate_metadata_is_not_bridged(self):
        loaded = loaded_quotes(disconnects=(450*NS,))
        self.assertTrue(all("segment_id" not in row for row in loaded["rows"]))
        day, diagnostic = project_day(loaded, "BTC", DATE, "test", "hour00")
        self.assertEqual(diagnostic["segments"], 2)
        base = loaded["rows"][0]["event_ns"]
        self.assertFalse(((day["times"] >= base+439*NS) & (day["times"] < base+471*NS)).any())
        self.assertTrue(((day["times"]-diagnostic["grid_anchor_ns"]) % (11*NS) == 0).all())
        for ordinals in day["selected_source_ordinals"]:
            self.assertTrue((ordinals < 450).all() or (ordinals >= 450).all())
        self.assert_schedule_boundaries(day)

    def test_startup_exclusion_warms_up_from_first_retained_fractional_event(self):
        for first in (30_250_000_000, 35_750_000_000):
            with self.subTest(first_retained_event_ns=first):
                loaded = loaded_quotes(np.arange(first, 900*NS, 500_000_000, dtype=np.int64))
                # Raw ordinals survive exclusion; normalized rows do not reset history.
                for row in loaded["rows"]:
                    row["source_ordinal"] += 99
                for item in loaded["segments"] + loaded["windows"]:
                    item["first_source_ordinal"] += 99
                    item["last_source_ordinal"] += 99
                day, diagnostic = project_day(loaded, "BTC", DATE, "test", "hour00")
                base = int(np.datetime64(DATE, "ns").astype(np.int64))
                anchor = base+(first//NS+21)*NS
                self.assertEqual(diagnostic["grid_anchor_ns"], anchor)
                self.assertEqual(day["times"][0], anchor)
                self.assertTrue((day["times"]-20*NS >= base+30*NS).all())
                self.assertTrue((day["selected_event_ns"] >= base+first).all())
                self.assertTrue((day["selected_source_ordinals"] >= 99).all())
                self.assertTrue(((day["times"]-anchor) % (11*NS) == 0).all())
                self.assert_schedule_boundaries(day)

    def test_large_gap_splits_support_and_preserves_original_grid(self):
        offsets = np.r_[np.arange(300)*NS, np.arange(320, 900)*NS]
        day, diagnostic = project_day(loaded_quotes(offsets), "BTC", DATE, "test", "hour00")
        self.assertEqual(diagnostic["segments"], 2)
        self.assertTrue(((day["times"]-diagnostic["grid_anchor_ns"]) % (11*NS) == 0).all())
        for ordinals in day["selected_source_ordinals"]:
            self.assertTrue((ordinals < 300).all() or (ordinals >= 300).all())
        self.assert_schedule_boundaries(day)

    def test_disconnected_source_windows_never_form_cross_window_schedules(self):
        loaded = loaded_quotes(disconnects=(450*NS,), separate_windows=True)
        day, diagnostic = project_day(loaded, "BTC", DATE, "test", "hour00")
        self.assertEqual(diagnostic["segments"], 2)
        groups = day["schedule_rows"]
        self.assertTrue((day["window_id"][groups] == day["window_id"][groups[:, :1]]).all())
        expected = sum(int((day["segment_id"] == segment).sum())//12 for segment in (1, 2))
        self.assertEqual(len(groups), expected)
        self.assert_schedule_boundaries(day)

    def test_each_of_nine_cut_ages_independently_excludes_stale_decision(self):
        original = np.arange(0, 600*NS, 50_000_000, dtype=np.int64)
        target = 186*NS
        for column, offset in enumerate(OFFSETS_NS):
            with self.subTest(offset=int(offset)):
                offsets = without_cut(original, target+int(offset), 1_600_000_000)
                cuts = target+OFFSETS_NS
                ages = cuts-offsets[np.searchsorted(offsets, cuts, side="right")-1]
                np.testing.assert_array_equal(np.flatnonzero(ages > 1_500_000_000), [column])
                self.assertLessEqual(int(np.diff(offsets).max()), 2*NS)
                loaded = loaded_quotes(offsets)
                day, diagnostic = project_day(loaded, "BTC", DATE, "test", "hour00")
                self.assertNotIn(loaded["rows"][0]["event_ns"]+target, day["times"])
                self.assertEqual(diagnostic["segments"], 1)
                self.assertTrue((day["source_age_ns"] <= 1_500_000_000).all())
                np.testing.assert_array_equal(day["max_input_age_ns"], day["source_age_ns"].max(axis=1))
                self.assert_schedule_boundaries(day)

    def test_inclusive_age_limit_and_stale_gap_do_not_compress_schedule(self):
        original = np.arange(0, 600*NS, 50_000_000, dtype=np.int64)
        target = 186*NS
        fresh = loaded_quotes(without_cut(original, target+100_000_000, 1_500_000_000))
        day, _ = project_day(fresh, "BTC", DATE, "test", "hour00")
        self.assertIn(fresh["rows"][0]["event_ns"]+target, day["times"])
        stale = loaded_quotes(without_cut(original, target+100_000_000, 1_600_000_000))
        day, _ = project_day(stale, "BTC", DATE, "test", "hour00")
        self.assertTrue((np.diff(day["times"]) > 11*NS).any())
        self.assert_schedule_boundaries(day)

    def test_exact_integer_midpoint_labels_include_flat_and_one_unit_directions(self):
        pairs = ((8799999900001, 8800000100001), (8799999900002, 8800000100000))
        self.assertEqual(sum(pairs[0]), sum(pairs[1]))
        self.assertNotEqual(sum(x/1e8 for x in pairs[0]), sum(x/1e8 for x in pairs[1]))
        loaded = loaded_quotes()
        for row in loaded["rows"]:
            bid, ask = pairs[(row["source_ordinal"]//10) % 2]
            row["bid_prices_units8"], row["ask_prices_units8"] = [bid], [ask]
        day, _ = project_day(loaded, "BTC", DATE, "test", "hour00")
        np.testing.assert_array_equal(day["y"], 1)
        loaded["rows"][31]["ask_prices_units8"][0] += 1
        loaded["rows"][42]["ask_prices_units8"][0] -= 1
        day, _ = project_day(loaded, "BTC", DATE, "test", "hour00")
        np.testing.assert_array_equal(day["y"][:3], [2, 0, 1])

    def test_training_cap_is_once_per_day_after_common_mask(self):
        offsets = np.r_[np.arange(0, 1200*NS, 100_000_000, dtype=np.int64),
                        np.arange(43200*NS, 44400*NS, 100_000_000, dtype=np.int64)]
        for target in (86*NS, 43286*NS):
            offsets = without_cut(offsets, target+10_100_000_000, 1_600_000_000)
        loaded = loaded_quotes(offsets, disconnects=(43200*NS,), separate_windows=True)
        with patch.dict(PROTOCOL, training_cap_per_day=100000):
            uncapped, before = project_day(loaded, "BTC", DATE, "train", "full_day")
        with patch.dict(PROTOCOL, training_cap_per_day=7):
            capped, after = project_day(loaded, "BTC", DATE, "train", "full_day")
        indices = np.linspace(0, len(uncapped["times"])-1, 7, dtype=int)
        np.testing.assert_array_equal(capped["times"], uncapped["times"][indices])
        self.assertEqual(len(capped["times"]), 7)
        self.assertEqual(after["opportunities_before_training_cap"], before["opportunities"])
        self.assertEqual(set(capped["segment_id"]), {1, 2})
        self.assertNotIn("schedule_rows", capped)
        for target in (86*NS, 43286*NS):
            self.assertNotIn(loaded["rows"][0]["event_ns"]+target, uncapped["times"])

    def test_concatenated_dates_offset_groups_without_using_previous_tail(self):
        first, _ = project_day(loaded_quotes(), "BTC", DATE, "test", "hour00")
        second, _ = project_day(loaded_quotes(date="2040-01-02"), "BTC", "2040-01-02", "test", "hour00")
        self.assertNotEqual(len(first["times"]) % 12, 0)
        joined = concatenate_days([first, second])
        boundary = len(first["schedule_rows"])
        np.testing.assert_array_equal(joined["schedule_rows"][:boundary], first["schedule_rows"])
        np.testing.assert_array_equal(joined["schedule_rows"][boundary:], second["schedule_rows"]+len(first["times"]))
        self.assert_schedule_boundaries(joined)
        self.assertTrue((np.diff(joined["times"]) > 0).all())
        with self.assertRaisesRegex(ValueError, "chronological"):
            concatenate_days([second, first])
        with self.assertRaisesRegex(ValueError, "chronological"):
            concatenate_days([first, first])

    def test_period_window_bounds_overlap_and_insufficient_schedule_are_rejected(self):
        loaded = loaded_quotes()
        loaded["windows"].append(copy.deepcopy(loaded["windows"][0]))
        with self.assertRaisesRegex(ValueError, "Overlapping"):
            project_day(loaded, "BTC", DATE, "test", "hour00")
        outside = loaded_quotes(np.arange(4000)*NS)
        with self.assertRaisesRegex(ValueError, "outside"):
            project_day(outside, "BTC", DATE, "test", "hour00")
        short = loaded_quotes(np.arange(100)*NS)
        with self.assertRaisesRegex(ValueError, "Unavailable.*schedule"):
            project_day(short, "BTC", DATE, "test", "hour00")


if __name__ == "__main__":
    unittest.main()
