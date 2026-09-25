"""Constructed software tests; these contain no certified market observations."""
import copy
import unittest

from adapter import adapt_episode
from r2_selector import PositiveLifecycle, audit_selection, freeze_anchors, project_episode


def candidates(count=6):
    return [{"source_seq": i * 3, "candidate_id": f"constructed-{i}",
             "decision": i * 3, "available": i * 3,
             "cohort_eligible": i != 1,
             "eligibility_reasons": ["no_past_completeness_certificate"] if i == 1 else [],
             "past_certificates": [{"ref": "constructed-prefix-fact", "available": 0}]}
            for i in range(count)]


def event(seq, oid, change, kind="C", fills=()):
    return {"kind": kind, "event_ns": seq * 10, "available_ns": seq * 10,
            "evidence_refs": ["constructed-lifecycle-test"], "fills": list(fills),
            "diffs": [{"raw_seq": seq, "coin": "BTC", "side": "B", "px": "100",
                       "oid": oid, "raw_book_diff": change}]}


def episode():
    rows = [event(1, "p", {"update": {"origSz": "2", "newSz": "0"}}),
            event(2, "p", "remove")]
    for i, oid in enumerate(["a", "b", "c"]):
        rows += [event(3 + i * 2, oid, {"new": {"sz": "1"}}, "A"),
                 event(4 + i * 2, oid, "remove")]
    rows.append(event(9, "d", {"new": {"sz": "1"}}, "A"))
    return {"episode_id": "constructed-zero-cleanup", "coin": "BTC", "side": "B",
            "px": "100", "probe_id": "p", "probe_cancellable": True,
            "initial": [{"oid": "z", "sz": "0"}, {"oid": "p", "sz": "2"}],
            "start_ns": 0, "initial_available_ns": 0, "initial_raw_seq": 0,
            "horizon_complete": True, "events": rows}


class SelectionTests(unittest.TestCase):
    def test_first_eligible_source_order_all_dispositions_retained(self):
        stream = candidates()
        frozen = freeze_anchors(stream, limit=3)
        self.assertEqual([r["candidate_id"] for r in frozen["selected"]],
                         ["constructed-0", "constructed-2", "constructed-3"])
        self.assertEqual([r["disposition"] for r in frozen["candidate_ledger"]],
                         ["selected", "ineligible", "selected", "selected",
                          "not_selected_after_limit", "not_selected_after_limit"])
        self.assertTrue(audit_selection(stream, frozen, limit=3))

    def test_audit_rejects_reversed_missing_substituted_candidates(self):
        stream = candidates()
        for mutation in ("reverse", "remove", "substitute", "selected_only"):
            frozen = freeze_anchors(stream, limit=3)
            if mutation == "reverse":
                frozen["candidate_ledger"].reverse()
            elif mutation == "remove":
                del frozen["candidate_ledger"][1]
            elif mutation == "substitute":
                frozen["candidate_ledger"][2]["candidate_id"] = "different"
            else:
                frozen["selected"].reverse()
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                audit_selection(stream, frozen, limit=3)

    def test_complete_stream_catches_omission_before_hashing(self):
        complete = candidates()
        omitted = freeze_anchors(complete[1:], limit=3)
        with self.assertRaisesRegex(ValueError, "complete source"):
            audit_selection(complete, omitted, limit=3)

    def test_specification_and_limit_bound_by_independent_audit_arguments(self):
        stream = candidates()
        for frozen in (freeze_anchors(stream, limit=2),
                       freeze_anchors(stream, limit=3, specification="other-policy")):
            with self.assertRaises(ValueError):
                audit_selection(stream, frozen, limit=3)

    def test_source_reversal_not_repaired_by_sorting(self):
        stream = candidates()
        stream[1], stream[2] = stream[2], stream[1]
        with self.assertRaisesRegex(ValueError, "never sort"):
            freeze_anchors(stream)

    def test_duplicate_identity_rejected(self):
        stream = candidates()
        stream[2]["candidate_id"] = stream[0]["candidate_id"]
        with self.assertRaisesRegex(ValueError, "Unique"):
            freeze_anchors(stream)

    def test_future_evidence_cannot_make_eligible(self):
        for field in ("available", "certificate"):
            stream = candidates()
            if field == "available":
                stream[0]["available"] = 1
            else:
                stream[0]["past_certificates"][0]["available"] = 1
            with self.subTest(field=field), self.assertRaises(ValueError):
                freeze_anchors(stream)

    def test_cancellations_and_cap_outcomes_not_read(self):
        stream = candidates(1205)
        frozen = freeze_anchors(stream)
        changed = copy.deepcopy(stream)
        for row in changed:
            row["future_cancelled"] = row["source_seq"] % 2 == 0
            row["enumeration_cap_success"] = False
            row["future_ambiguity"] = 0.9
        self.assertEqual(freeze_anchors(changed), frozen)
        self.assertEqual(frozen["selected_count"], 1000)
        self.assertEqual(frozen["candidate_count"], 1205)

    def test_suffix_change_does_not_replace_first_anchors(self):
        stream = candidates()
        frozen = freeze_anchors(stream, limit=2)
        stream[-1]["cohort_eligible"] = False
        stream[-1]["eligibility_reasons"] = ["past_only_exclusion"]
        self.assertEqual(freeze_anchors(stream, limit=2)["selected"], frozen["selected"])

    def test_no_eligible_candidates_is_valid_empty_cohort(self):
        stream = [candidates()[1]]
        frozen = freeze_anchors(stream)
        self.assertEqual(frozen["selected_count"], 0)
        self.assertEqual(frozen["candidate_count"], 1)

    def test_clock_coordinate_is_explicit(self):
        stream = candidates()
        self.assertEqual(freeze_anchors(stream)["clock_kind"], "source_ordinal")
        frozen = freeze_anchors(stream, clock_kind="producer_availability_ns")
        self.assertTrue(audit_selection(stream, frozen, clock_kind="producer_availability_ns"))


class LifecycleTests(unittest.TestCase):
    def test_zero_update_preserves_identity_and_cleanup_is_administrative(self):
        state = PositiveLifecycle([{"oid": "p", "sz": "2"}], "1")
        reduction = state.project(episode()["events"][0])
        self.assertEqual(reduction["observed_positive_count"], 0)
        self.assertEqual(reduction["physical_live_identity_count"], 1)
        self.assertEqual(reduction["economic_quantity_units"], 2)
        cleanup = state.project(episode()["events"][1])
        self.assertIsNone(cleanup["event"])
        self.assertEqual(cleanup["physical_live_identity_count"], 0)
        self.assertEqual(cleanup["lineage"][0]["action"], "administrative_zero_cleanup")
        self.assertEqual(state.economic_events, 1)

    def test_projection_executes_original_adapter_without_unknown_identity_error(self):
        physical_episode = episode()
        frozen_before = copy.deepcopy(physical_episode)
        projected = project_episode(physical_episode, "1")
        self.assertEqual(physical_episode, frozen_before)
        self.assertEqual(len(projected["lineage"]), 9)
        self.assertEqual(len(projected["episode"]["events"]), 8)
        self.assertFalse(projected["initial_completeness_certified_by_projection"])
        result = adapt_episode(projected["episode"], "1")
        self.assertEqual(result["status"], "scored")
        self.assertEqual(result["cancelled_units"], 2)
        self.assertEqual(result["truth"]["fill_fraction"], ["0"])

    def test_eight_physical_events_can_be_only_seven_economic_events(self):
        source = episode()
        source["events"] = source["events"][:8]
        projected = project_episode(source, "1")
        self.assertFalse(projected["episode"]["horizon_complete"])
        self.assertEqual(adapt_episode(projected["episode"], "1")["status"], "censored")

    def test_existing_censoring_is_never_overridden(self):
        source = episode()
        source["horizon_complete"] = False
        projected = project_episode(source, "1")
        self.assertFalse(projected["episode"]["horizon_complete"])

    def test_administrative_clock_inversion_not_hidden_by_projection(self):
        source = episode()
        source["events"][1]["event_ns"] = 0
        with self.assertRaisesRegex(ValueError, "Clock inversion"):
            project_episode(source, "1")

    def test_administrative_scope_violation_not_hidden_by_projection(self):
        for key, value in [("coin", "ETH"), ("side", "A"), ("px", "101"),
                           ("px", "NaN"), ("px", "Infinity"), ("px", "0"),
                           ("px", "broken"), ("px", 100.0)]:
            source = episode()
            source["events"][1]["diffs"][0][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                project_episode(source, "1")

    def test_equal_exact_price_spelling_is_preserved(self):
        source = episode()
        source["events"][1]["diffs"][0]["px"] = "100.000000000"
        self.assertEqual(len(project_episode(source, "1")["episode"]["events"]), 8)

    def test_unknown_cleanup_is_not_assumed_known_zero(self):
        state = PositiveLifecycle([], "1")
        with self.assertRaisesRegex(ValueError, "Unknown lifecycle"):
            state.project(event(1, "missing", "remove"))

    def test_zero_reactivation_requires_explicit_priority_model(self):
        state = PositiveLifecycle([{"oid": "z", "sz": "0"}], "1")
        with self.assertRaisesRegex(ValueError, "reactivation"):
            state.project(event(1, "z", {"update": {"origSz": "0", "newSz": "1"}}, "A"))
        self.assertEqual(state.physical, {"z": 0})
        self.assertEqual(state.last_seq, 0)

    def test_initial_zero_identity_does_not_block_fifo(self):
        state = PositiveLifecycle([{"oid": "z", "sz": "0"}, {"oid": "p", "sz": "2"}], "1")
        projected = state.project(event(1, "p", "remove", "T", [{"oid": "p", "sz": "2"}]))
        self.assertEqual(projected["observed_positive_count"], 0)
        self.assertEqual(projected["physical_live_identity_count"], 1)

    def test_fifo_violation_and_unreconciled_fill_fail_without_mutation(self):
        for test_event in (event(1, "b", "remove", "T", [{"oid": "b", "sz": "2"}]),
                           event(1, "a", "remove", "T", [{"oid": "a", "sz": "1"}])):
            state = PositiveLifecycle([{"oid": "a", "sz": "2"}, {"oid": "b", "sz": "2"}], "1")
            with self.assertRaises(ValueError):
                state.project(test_event)
            self.assertEqual(state.physical, {"a": 2, "b": 2})
            self.assertEqual(state.last_seq, 0)

    def test_multileg_trade_retains_fifo_and_cleanup_lineage(self):
        state = PositiveLifecycle([{"oid": "a", "sz": "2"}, {"oid": "z", "sz": "0"},
                                   {"oid": "b", "sz": "1"}], "1")
        grouped = event(1, "a", "remove", "T", [{"oid": "a", "sz": "2"},
                                                   {"oid": "b", "sz": "1"}])
        grouped["diffs"] += event(2, "z", "remove")["diffs"]
        grouped["diffs"] += event(3, "b", "remove")["diffs"]
        result = state.project(grouped)
        self.assertEqual([r["raw_seq"] for r in result["event"]["diffs"]], [1, 3])
        self.assertEqual(len(result["lineage"]), 3)
        self.assertEqual(result["economic_quantity_units"], 3)


if __name__ == "__main__":
    unittest.main()
