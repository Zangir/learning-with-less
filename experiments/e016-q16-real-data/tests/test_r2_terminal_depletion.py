"""Finite-oracle checks for the narrowly guarded terminal-depletion shortcut."""
import random
import unittest
from unittest.mock import patch

from core import advance, initial_states
from r2_symbolic import SymbolicQueue


def finite_fills(ahead, probe, events, counts=None, cancellable=True):
    states = initial_states(ahead, probe)
    if counts is not None:
        states = {state for state in states if len(state.queue) == counts[0]}
    for step, (kind, quantity) in enumerate(events, 1):
        states = advance(states, kind, quantity, probe_cancellable=cancellable)
        if counts is not None:
            states = {state for state in states if len(state.queue) == counts[step]}
    return sorted({state.filled for state in states})


class TerminalDepletionTests(unittest.TestCase):
    def assert_oracle(self, ahead, probe, events, counts=None):
        queue = SymbolicQueue(ahead, probe, events, counts=counts)
        # A successful shortcut must not secretly buy a larger solver budget.
        with patch.object(queue, '_extreme', side_effect=AssertionError('Unexpected SMT call')):
            result = queue.project(enumerate_limit=0)
        expected = finite_fills(ahead, probe, events, counts)
        self.assertEqual(result['backend'], 'exact_terminal_depletion_v1')
        self.assertEqual(result['fill_values'], expected)
        self.assertEqual(result['status'], 'exact' if expected else 'infeasible')
        if expected:
            self.assertEqual(result['minimum_fill_units'], min(expected))
            self.assertEqual(result['maximum_fill_units'], max(expected))
        return result

    def test_gapped_volume_set_and_count_full_deletions(self):
        events = [('C', 2), ('C', 2), ('T', 6)]
        self.assertEqual(self.assert_oracle(6, 4, events)['fill_values'], [0, 2, 4])
        self.assertEqual(self.assert_oracle(6, 4, events, [4, 3, 2, 0])['fill_values'], [4])

    def test_equal_probe_cancellation_can_be_ambiguous(self):
        self.assertEqual(self.assert_oracle(4, 2, [('C', 2), ('T', 4)], [3, 2, 0])['fill_values'], [0, 2])

    def test_no_cancellations_and_empty_ahead(self):
        self.assertEqual(self.assert_oracle(0, 3, [('T', 3)], [1, 0])['fill_values'], [3])

    def test_infeasible_initial_mass_count(self):
        self.assertEqual(self.assert_oracle(1, 2, [('T', 3)], [3, 0])['status'], 'infeasible')

    def test_nonprobe_cancellation_cannot_use_missing_volume(self):
        self.assertEqual(self.assert_oracle(2, 2, [('C', 3), ('T', 1)])['status'], 'infeasible')

    def test_deleting_every_count_before_positive_trade_is_infeasible(self):
        self.assertEqual(self.assert_oracle(3, 2, [('C', 2), ('T', 3)], [1, 0, 0])['status'], 'infeasible')

    def test_partial_count_reduction_falls_back(self):
        events, counts = [('C', 1), ('T', 5)], [2, 2, 0]
        queue = SymbolicQueue(3, 3, events, counts)
        self.assertIsNone(queue._terminal_depletion_values())
        result = queue.project(enumerate_limit=8)
        self.assertEqual(result['backend'], 'exact_integer_smt_group_compression_v1')
        self.assertEqual(result['fill_values'], finite_fills(3, 3, events, counts))

    def test_protected_source_probe_falls_back(self):
        events = [('C', 1), ('T', 3)]
        queue = SymbolicQueue(3, 1, events, probe_cancellable=False)
        self.assertIsNone(queue._terminal_depletion_values())
        result = queue.project(enumerate_limit=2)
        self.assertEqual(result['backend'], 'exact_integer_smt_group_compression_v1')
        self.assertEqual(result['fill_values'], finite_fills(3, 1, events, cancellable=False))

    def test_add_earlier_trade_and_nonterminal_depletion_fall_back(self):
        examples = [(1, 1, [('A', 2), ('T', 4)]),
                    (3, 2, [('C', 1), ('T', 1)]),
                    (3, 2, [('T', 1), ('C', 1), ('T', 3)])]
        for ahead, probe, events in examples:
            with self.subTest(events=events):
                queue = SymbolicQueue(ahead, probe, events)
                self.assertIsNone(queue._terminal_depletion_values())
                result = queue.project(enumerate_limit=8)
                self.assertEqual(result['fill_values'], finite_fills(ahead, probe, events))

    def test_known_partial_probe_path_is_contained(self):
        events = [('C', 2), ('C', 2), ('T', 6)]
        queue = SymbolicQueue(6, 4, events)
        truth = queue.check_truth([2, 4], {0: 0, 1: 2})
        self.assertEqual(truth['status'], 'contained')
        self.assertEqual(truth['truth_states'][-1]['filled'], 2)
        self.assertIn(2, queue.project()['fill_values'])

    def test_seven_cancel_large_quantity_case_needs_no_solver(self):
        cancellations = [68996000, 68996000, 172491000, 17248000,
                         114994000, 68996000, 172492000]
        events = [('C', quantity) for quantity in cancellations] + [('T', 13000)]
        for counts in (None, [8, 7, 6, 5, 4, 3, 2, 1, 0]):
            queue = SymbolicQueue(615230000, 68996000, events, counts=counts, timeout_ms=1)
            with patch.object(queue, '_extreme', side_effect=AssertionError('Unexpected SMT call')):
                result = queue.project()
            self.assertEqual(result['fill_values'], [0])
            self.assertEqual(result['status'], 'exact')

    def test_bounded_seeded_finite_oracle_cases(self):
        rng = random.Random(20260919)
        for case in range(48):
            ahead, probe = rng.randrange(7), rng.randint(1, 4)
            cancellations = [rng.randint(1, 3) for _ in range(rng.randrange(4))]
            terminal = ahead + probe - sum(cancellations)
            if terminal <= 0:
                cancellations = []
                terminal = ahead + probe
            events = [('C', quantity) for quantity in cancellations] + [('T', terminal)]
            initial_count = rng.randint(max(1, len(cancellations)), max(1, len(cancellations), ahead + 2))
            counts = [initial_count - step for step in range(len(cancellations) + 1)] + [0]
            with self.subTest(case=case, arm='volume'):
                self.assert_oracle(ahead, probe, events)
            with self.subTest(case=case, arm='count'):
                self.assert_oracle(ahead, probe, events, counts)


if __name__ == '__main__':
    unittest.main(verbosity=2)
