"""Checks for information masking and count-free conservation boundaries."""
import unittest
from unittest.mock import patch
import time

from core import State, StateCapExceeded, initial_states
from r4_controlled import evaluate_case, observed_step
from r4_conservation import conservation_bounds


class ControlledTests(unittest.TestCase):
    def test_negative_kind_does_not_leak_into_masked_observer(self):
        states = initial_states(2, 2)
        for policy in (False, True):
            self.assertEqual(observed_step(states, ('C', 2), 'signed_delta', policy),
                             observed_step(states, ('T', 2), 'signed_delta', policy))

    def test_count_can_reject_partial_probe_cancellation(self):
        states = {s for s in initial_states(4, 2) if len(s.queue) == 3}
        wide = observed_step(states, ('C', 1), 'rich', True)
        narrow = observed_step(states, ('C', 1), 'rich', True, 2)
        self.assertTrue(any(s.cancelled == 1 for s in wide))
        self.assertTrue(all(s.cancelled == 0 for s in narrow))

    def test_late_cancel_cannot_expose_an_earlier_trade(self):
        bounds = conservation_bounds(5, 2, [('T', 1), ('C', 5)])
        self.assertGreater(bounds['aggregate_upper'], 0)
        self.assertEqual(bounds['chronological_upper'], 0)

    def test_count_filter_and_state_cap_do_not_return_truncated_bound(self):
        states = {State(((2, False), (2, True)))}
        self.assertEqual(len(observed_step(states, ('C', 2), 'rich', False, 1)), 1)
        with self.assertRaises(StateCapExceeded):
            observed_step(states, ('C', 2), 'signed_delta', True, cap=1)

    def test_cap_failure_retains_rows_without_blocking_other_views(self):
        case = {'case_id': 'cap-test', 'family': 'fixture', 'ahead': 2, 'probe': 2,
                'events': [('C', 2), ('T', 2)], 'counts': [2, 1, 0], 'source_ref': {}}

        def capped(states, event, view, cancellable, count=None):
            if view == 'rich' and not cancellable:
                raise StateCapExceeded('Injected cap')
            return observed_step(states, event, view, cancellable, count)

        with patch('r4_controlled.observed_step', capped):
            rows = evaluate_case(case, time.monotonic() + 60)
        self.assertEqual(len(rows), 8)
        self.assertEqual(sum(r['status'] == 'unscored' for r in rows), 2)
        self.assertEqual(sum(r['status'] == 'exact' for r in rows), 6)


if __name__ == '__main__':
    unittest.main()
