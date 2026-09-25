"""Synthetic edge cases for source grouping; fixtures are not market evidence."""
import unittest

from r2_conditional_pilot import decimal8, group_level


def row(seq, label, key=None):
    kind = {'visible_new_order': 'new', 'matched_trade_decrease': 'update',
            'observed_cancel': 'remove', 'zero_quantity_identity_cleanup': 'remove'}[label]
    before = None if kind == 'new' else 0 if label == 'zero_quantity_identity_cleanup' else 10
    result = {'source_diff_row_0based': seq, 'kind': kind, 'observed_label': label,
              'quantity_before_units_1e8_btc': before,
              'quantity_after_units_1e8_btc': 10 if kind == 'new' else 0,
              'candidate_group_time_ns': 100, 'side': 'B', 'price_units_1e8_usd': 100000000,
              'local_order_token': f'oid-{seq}', 'matching_trade_source_row_0based': seq}
    if key:
        result['candidate_taker_price_group_key'] = key
    return result


class CandidateGroupingTests(unittest.TestCase):
    def test_cleanup_transparent_inside_whole_trade_group(self):
        events = group_level([row(1, 'matched_trade_decrease', 'k'),
                              row(2, 'zero_quantity_identity_cleanup'),
                              row(3, 'matched_trade_decrease', 'k'),
                              row(4, 'zero_quantity_identity_cleanup'),
                              row(5, 'visible_new_order')])
        self.assertEqual([event['kind'] for event in events], ['T', 'administrative', 'A'])
        self.assertEqual(len(events[0]['diffs']), 3)
        self.assertEqual(len(events[0]['fills']), 2)

    def test_economic_interleaving_does_not_get_reordered(self):
        events = group_level([row(1, 'matched_trade_decrease', 'k'),
                              row(2, 'observed_cancel'), row(3, 'matched_trade_decrease', 'k')])
        self.assertEqual([event['kind'] for event in events], ['T', 'C', 'T'])
        self.assertEqual([event['candidate_group_noncontiguous'] for event in events], [True, False, True])

    def test_missing_key_rejected_and_exact_grid_preserved(self):
        with self.assertRaisesRegex(ValueError, 'key'):
            group_level([row(1, 'matched_trade_decrease')])
        self.assertEqual(decimal8(1234567890123), '12345.67890123')
        with self.assertRaises(ValueError):
            decimal8(1.0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
