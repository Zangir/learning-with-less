"""Independent synthetic invariants; no market files or outcome labels are used."""
import copy
import unittest

from t016_p0.engine import (
    AGE, GAP, NS, Observations, OpportunityState, detect, extract,
    retrospective_support, row_validity,
)


def candidate(second, side="resistance", family="rebound", anchor=120,
              past_rejection=None, **extra):
    return {
        "family": family, "side": side, "anchor_ns": anchor * NS,
        "decision_ns": second * NS, "past_rejection": past_rejection, **extra,
    }


def row(event_ns, ordinal, mid2=21000, segment_id=0, depth=5):
    """Synthetic integer prices: midpoint 105, spread 1, epsilon 1."""
    bid = (mid2 - 100) // 2
    ask = (mid2 + 100) // 2
    return {
        "event_ns": event_ns, "source_ordinal": ordinal,
        "segment_id": segment_id, "disconnect_epoch": 0,
        "source_id": "synthetic-fixture-only",
        "bid_prices_units8": [bid - 10 * i for i in range(depth)],
        "ask_prices_units8": [ask + 10 * i for i in range(depth)],
        "bid_sizes_units8": [100 + i for i in range(depth)],
        "ask_sizes_units8": [200 + i for i in range(depth)],
        "bid_counts": [10 + i for i in range(depth)],
        "ask_counts": [20 + i for i in range(depth)],
    }


def observations(rows, start=0, end=200 * NS, segments=None):
    if segments is None:
        segments = [{"segment_id": sid, "start_ns": 0, "end_ns": 400 * NS}
                    for sid in sorted({r["segment_id"] for r in rows})]
    return Observations(rows, segments, start, end)


def witness_rows(last_second=142):
    # Extremes freeze the minute level; the three later touches are the RV021 witness.
    mids = {60: 22000, 61: 20000, 120: 21900, 125: 20100, 131: 20100}
    return [row(t * NS, t + 1, mids.get(t, 21000))
            for t in range(60, last_second + 1)]


def recorded_times(result):
    return [event["decision_ns"] // NS for event in result["events"]]


class OpportunityStateTests(unittest.TestCase):
    def setUp(self):
        self.state = OpportunityState()

    def process(self, *items):
        return self.state.process(list(items))

    def test_rv021_recorded_only_witness(self):
        first = self.process(candidate(120))[0]
        rejected = self.process(candidate(125, "support"))[0]
        self.assertEqual(first["status"], "recorded")
        self.assertEqual(rejected["reason"], "cooldown")
        self.assertNotIn(("rebound", "support", 120 * NS), self.state.slots)
        self.assertEqual(self.state.last_recorded, {"rebound": 120 * NS})
        third = self.process(candidate(131, "support"))[0]
        self.assertEqual(third["status"], "recorded")

    def test_exact_ten_seconds_passes_and_one_nanosecond_early_does_not(self):
        self.process(candidate(120))
        early = candidate(130, "support")
        early["decision_ns"] -= 1
        self.assertEqual(self.process(early)[0]["reason"], "cooldown")
        self.assertEqual(self.process(candidate(130, "support"))[0]["status"], "recorded")
        self.assertEqual(self.state.last_recorded["rebound"], 130 * NS)

    def test_used_slot_precedes_cooldown_and_does_not_refresh_clock(self):
        self.process(candidate(120))
        self.assertEqual(self.process(candidate(125))[0]["reason"], "used_slot")
        self.assertEqual(self.process(candidate(130))[0]["reason"], "used_slot")
        self.assertEqual(self.state.last_recorded["rebound"], 120 * NS)
        self.assertEqual(self.process(candidate(131, "support"))[0]["status"], "recorded")

    def test_every_past_rejection_precedes_slots_and_cooldown(self):
        for reason in ("source:stale_asof", "feature:missing_depth", "level:unsupported"):
            with self.subTest(reason=reason):
                state = OpportunityState()
                state.process([candidate(120)])
                before = (state.slots.copy(), state.last_recorded.copy())
                result = state.process([candidate(125, past_rejection=reason)])[0]
                self.assertEqual(result["reason"], reason)
                self.assertEqual((state.slots, state.last_recorded), before)
                state.process([candidate(129, "support", past_rejection=reason)])
                self.assertEqual(state.process([candidate(130, "support")])[0]["status"], "recorded")

    def test_invalid_first_event_leaves_slot_and_clock_unset(self):
        self.process(candidate(120, past_rejection="feature:missing_depth"))
        self.assertEqual(self.state.slots, set())
        self.assertEqual(self.state.last_recorded, {})
        self.assertEqual(self.process(candidate(121))[0]["status"], "recorded")

    def test_ambiguity_rejects_whole_group_independent_of_order(self):
        for sides in (("resistance", "support"), ("support", "resistance")):
            with self.subTest(sides=sides):
                state = OpportunityState()
                result = state.process([candidate(120, side) for side in sides])
                self.assertEqual([r["reason"] for r in result], ["two_sided_ambiguity"] * 2)
                self.assertEqual(state.slots, set())
                self.assertEqual(state.last_recorded, {})
                self.assertEqual(state.process([candidate(121)])[0]["status"], "recorded")

    def test_ambiguity_precedes_used_slot(self):
        self.process(candidate(100))
        before = (self.state.slots.copy(), self.state.last_recorded.copy())
        results = self.process(candidate(120), candidate(120, "support"))
        self.assertEqual([r["reason"] for r in results], ["two_sided_ambiguity"] * 2)
        self.assertEqual((self.state.slots, self.state.last_recorded), before)

    def test_past_invalid_candidate_is_removed_before_ambiguity(self):
        results = self.process(candidate(120, past_rejection="feature:missing_depth"),
                               candidate(120, "support"))
        by_side = {r["side"]: r for r in results}
        self.assertEqual(by_side["resistance"]["reason"], "feature:missing_depth")
        self.assertEqual(by_side["support"]["status"], "recorded")

    def test_future_censor_flag_cannot_refund_slot_or_cooldown(self):
        self.process(candidate(120, complete_future_support=False))
        self.assertEqual(self.process(candidate(125, "support"))[0]["reason"], "cooldown")
        self.assertEqual(self.process(candidate(131))[0]["reason"], "used_slot")
        self.assertEqual(self.process(candidate(131, "support"))[0]["status"], "recorded")

    def test_families_have_independent_state(self):
        first = self.process(candidate(120, family="breakout"))[0]
        second = self.process(candidate(121, family="rebound"))[0]
        self.assertEqual((first["status"], second["status"]), ("recorded", "recorded"))
        self.assertEqual(self.state.last_recorded, {"breakout": 120 * NS, "rebound": 121 * NS})

    def test_anchor_change_does_not_reset_family_cooldown(self):
        self.process(candidate(179))
        self.assertEqual(self.process(candidate(180, anchor=180))[0]["reason"], "cooldown")
        self.assertNotIn(("rebound", "resistance", 180 * NS), self.state.slots)
        self.assertEqual(self.process(candidate(189, anchor=180))[0]["status"], "recorded")


class GeometryTests(unittest.TestCase):
    level = {"resistance_mid2": 22000, "support_mid2": 20000,
             "epsilon2": {"numerator": 200, "denominator": 1}}

    def families(self, before, now, side="resistance"):
        return [r["family"] for r in detect(before, now, self.level) if r["side"] == side]

    def test_breakout_strict_current_and_inclusive_previous_boundary(self):
        self.assertEqual(self.families(22000, 22200), [])
        self.assertEqual(self.families(22200, 22201), ["breakout"])

    def test_touch_edges_inclusive_but_previous_inner_edge_strict(self):
        self.assertEqual(self.families(21799, 21800), ["rebound"])
        self.assertEqual(self.families(21799, 22200), ["rebound"])
        self.assertEqual(self.families(21800, 22000), [])

    def test_jump_through_band_is_breakout_not_touch(self):
        self.assertEqual(self.families(21799, 22201), ["breakout"])

    def test_support_geometry_is_sign_reversed(self):
        self.assertEqual(self.families(20201, 20200, "support"), ["rebound"])
        self.assertEqual(self.families(19800, 19799, "support"), ["breakout"])
        self.assertEqual(self.families(20000, 19800, "support"), [])


class ObservationSupportTests(unittest.TestCase):
    def test_age_boundary_and_exact_asof_selection(self):
        obs = observations([row(0, 1), row(2 * NS, 2)])
        at_boundary = obs.lookup(AGE)
        self.assertTrue(at_boundary["valid"])
        self.assertEqual(at_boundary["source_ordinal"], 1)
        self.assertEqual(obs.lookup(AGE + 1)["reason"], "stale_asof")
        self.assertEqual(obs.lookup(2 * NS)["source_ordinal"], 2)

    def test_exact_native_gap_passes_larger_unsegmented_gap_rejects(self):
        observations([row(0, 1), row(GAP, 2)])
        with self.assertRaisesRegex(ValueError, "Unsegmented native gap"):
            observations([row(0, 1), row(GAP + 1, 2)])

    def test_order_ordinal_and_disconnect_invariants_fail_closed(self):
        cases = ([row(NS, 2), row(0, 1)],
                 [row(0, 1), row(NS, 1)],
                 [row(0, 1), row(0, 2)])
        for rows in cases:
            with self.subTest(rows=rows), self.assertRaisesRegex(ValueError, "ordering failed"):
                observations(rows)
        disconnected = [row(0, 1), row(NS, 2)]
        disconnected[-1]["disconnect_epoch"] = 1
        with self.assertRaisesRegex(ValueError, "Unsegmented disconnect"):
            observations(disconnected)

    def test_restriction_and_actual_endpoint_prevent_extrapolation(self):
        rows = [row(29 * NS, 1), row(30 * NS, 2), row(31 * NS, 3)]
        obs = observations(rows, start=30 * NS, end=31 * NS)
        self.assertEqual([r["source_ordinal"] for r in obs.rows], [2])
        self.assertTrue(obs.lookup(30 * NS)["valid"])
        self.assertFalse(obs.lookup(30 * NS + 1)["valid"])
        self.assertFalse(obs.lookup(31 * NS)["valid"])
        self.assertEqual(obs.segments[0]["end_ns"], 30 * NS + 1)

    def test_segment_change_blocks_history_even_when_each_cut_valid(self):
        obs = observations([row(0, 1, segment_id=0), row(NS, 2, segment_id=1)])
        self.assertTrue(obs.lookup(0)["valid"])
        self.assertTrue(obs.lookup(NS)["valid"])
        points, reason, bad_cut = obs.history([0, NS])
        self.assertEqual((points, reason, bad_cut), ([], "segment_change", NS))

    def test_native_gap_between_segments_is_not_filled(self):
        obs = observations([row(0, 1, segment_id=0), row(4 * NS, 2, segment_id=1)])
        self.assertEqual(obs.lookup(NS)["reason"], "outside_retained_support")
        self.assertFalse(obs.lookup(3 * NS)["valid"])

    def test_bbo_validity_does_not_override_missing_common_depth(self):
        obs = observations([row(0, 1, depth=1), row(NS, 2)])
        self.assertTrue(obs.lookup(0)["valid"])
        self.assertEqual(obs.lookup(0)["depth_rejection"], "missing_depth")
        self.assertEqual(obs.history([0], require_depth=True)[1], "missing_depth")
        self.assertIsNone(obs.history([0], require_depth=False)[1])

    def test_malformed_depth_prices_are_rejected(self):
        item = row(0, 1)
        item["bid_prices_units8"][2] = item["bid_prices_units8"][1]
        self.assertIsNone(row_validity(item, 1))
        self.assertEqual(row_validity(item, 5), "unordered_depth")

    def test_bbo_projection_is_same_row_with_expected_units(self):
        obs = observations([row(0, 7), row(NS, 8)])
        selected = obs.lookup(NS // 2)
        self.assertEqual(selected["source_ordinal"], 7)
        self.assertEqual(selected["bbo"], [10450, 10550, 100, 200, 10, 20, NS // 2])

    def test_valid_frozen_level_does_not_certify_later_feature_history(self):
        rows = witness_rows(179)
        rows[100] = row(160 * NS, 161, depth=1)
        obs = observations(rows)
        self.assertTrue(obs.level(120 * NS)["valid"])
        points, reason, bad_cut = obs.history(range(119 * NS, 180 * NS, NS),
                                               require_depth=True)
        self.assertEqual((points, reason, bad_cut), ([], "missing_depth", 160 * NS))

    def test_full_future_horizon_respects_half_open_hour_endpoint(self):
        rows = [row(t * NS, t + 1) for t in range(3580, 3601)]
        segments = [{"segment_id": 0, "start_ns": 3500 * NS, "end_ns": 3700 * NS}]
        obs = observations(rows, start=30 * NS, end=3600 * NS, segments=segments)
        events = [{"event_id": str(t), "decision_ns": t * NS, "segment_id": 0}
                  for t in (3589, 3590)]
        masks = retrospective_support(obs, events)
        self.assertTrue(masks[0]["complete_future_support"])
        self.assertEqual(len(masks[0]["future_support_refs"]), 10)
        self.assertFalse(masks[1]["complete_future_support"])
        self.assertEqual(masks[1]["first_bad_cut_ns"], 3600 * NS)
        self.assertNotIn(3600 * NS, obs.grid)

    def test_prefix_watermark_does_not_claim_nonexistent_tail_cut(self):
        prefix_rows = [row(98_600_000_000, 1), row(99_600_000_000, 2)]
        short = observations(prefix_rows, start=98 * NS)
        long = observations(prefix_rows + [row(100_200_000_000, 3)], start=98 * NS)
        self.assertNotIn(100 * NS, short.grid)
        self.assertIn(100 * NS, long.grid)
        self.assertEqual(long.grid[100 * NS]["source_ordinal"], 2)
        self.assertEqual(long.grid[100 * NS]["age_ns"], 400_000_000)
        for cut in short.grid:
            self.assertEqual(short.grid[cut], long.grid[cut])


class ExtractionIntegrationTests(unittest.TestCase):
    def test_raw_geometry_produces_exact_rv021_witness(self):
        result = extract(observations(witness_rows()), "synthetic-protocol-sha")
        self.assertEqual(recorded_times(result), [120, 131])
        candidates = [(r["decision_ns"] // NS, r["family"], r["side"], r["reason"])
                      for r in result["candidates"]]
        self.assertEqual(candidates, [
            (120, "rebound", "resistance", None),
            (125, "rebound", "support", "cooldown"),
            (131, "rebound", "support", None),
        ])
        level = next(r for r in result["levels"] if r["anchor_ns"] == 120 * NS)
        self.assertEqual((level["resistance_mid2"], level["support_mid2"]), (22000, 20000))
        self.assertEqual(level["epsilon2"]["numerator"], 200)
        self.assertEqual(level["cut_ns"], list(range(60 * NS, 120 * NS, NS)))
        for event in result["events"]:
            self.assertEqual(len(event["feature_history"]), 61)
            self.assertEqual(event["feature_history"][-1]["cut_ns"], event["decision_ns"])
            self.assertEqual(event["history_source_ordinals"],
                             [p["source_ordinal"] for p in event["feature_history"]])

    def test_invalid_common_depth_history_does_not_consume_initial_slot(self):
        rows = witness_rows()
        rows[0] = row(60 * NS, 61, 22000, depth=1)
        result = extract(observations(rows), "synthetic-protocol-sha")
        self.assertEqual(recorded_times(result), [125])
        reasons = {c["decision_ns"] // NS: c["reason"] for c in result["candidates"]}
        self.assertEqual(reasons, {120: "feature:missing_depth", 125: None, 131: "used_slot"})

    def test_source_row_alone_never_becomes_strategy_event(self):
        result = extract(observations([row(30_425_000_000, 99)], start=30 * NS), "synthetic")
        self.assertEqual(result["events"], [])
        self.assertEqual(result["candidates"], [])

    def test_future_masks_separate_from_prefix_causal_events(self):
        short_obs = observations(witness_rows(126))
        long_obs = observations(witness_rows(142))
        short = extract(short_obs, "synthetic-protocol-sha")
        long = extract(long_obs, "synthetic-protocol-sha")
        for key in ("events", "candidates", "blocked_cuts"):
            cut_key = "cut_ns" if key == "blocked_cuts" else "decision_ns"
            finalized = [r for r in long[key] if r[cut_key] <= 126 * NS]
            self.assertEqual(short[key], finalized)
        before = copy.deepcopy(short)
        short_masks = retrospective_support(short_obs, short["events"])
        long_masks = retrospective_support(long_obs, short["events"])
        self.assertFalse(short_masks[0]["complete_future_support"])
        self.assertTrue(long_masks[0]["complete_future_support"])
        self.assertEqual(short, before)
        self.assertEqual(recorded_times(short), [120])
        self.assertEqual(short["candidates"][-1]["reason"], "cooldown")

    def test_future_price_changes_leave_finalized_prefix_unchanged(self):
        original = witness_rows()
        modified = copy.deepcopy(original)
        for index, item in enumerate(modified):
            if item["event_ns"] > 126 * NS:
                modified[index] = row(item["event_ns"], item["source_ordinal"], 24000)
        old = extract(observations(original), "synthetic-protocol-sha")
        new = extract(observations(modified), "synthetic-protocol-sha")
        for key in ("events", "candidates"):
            self.assertEqual([r for r in old[key] if r["decision_ns"] <= 126 * NS],
                             [r for r in new[key] if r["decision_ns"] <= 126 * NS])
        # Masks inspect source support, never the magnitude or direction of future prices.
        common = [r for r in old["events"] if r["decision_ns"] <= 126 * NS]
        self.assertEqual(retrospective_support(observations(original), common),
                         retrospective_support(observations(modified), common))


if __name__ == "__main__":
    unittest.main()
