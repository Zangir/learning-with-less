"""Guard the fixed-cohort boundary; synthetic fixtures are not market evidence."""
from copy import deepcopy
import unittest

from r2_conditional_pilot import group_level
from r3_horizon_completion import extend_episode, validate_membership, validate_rows
from test_r2_conditional_pilot import row


class ExtensionBoundaryTests(unittest.TestCase):
    def test_membership_and_order_cannot_change(self):
        original = [{'episode_id':'a','initial_raw_seq':1}, {'episode_id':'b','initial_raw_seq':2}]
        inventory = [{'episode_id':'a','anchor_source_seq':1}, {'episode_id':'b','anchor_source_seq':2}]
        validate_membership(original, inventory)
        for changed in (inventory[::-1], inventory[:1], inventory+[inventory[0]]):
            with self.assertRaises(ValueError):
                validate_membership(original, changed)

    def test_source_time_scope_and_whole_group_closure(self):
        base = [{'source_diff_row_0based':1}]
        extension = [dict(source_diff_row_0based=seq, candidate_group_time_ns=20, side='B',
                          price_units_1e8_usd=100, closure_witness_source_row=4,
                          closure_witness_time_ns=30) for seq in (2,3)]
        validate_rows(base,extension,{('B',100)},10,20)
        for key,value in [('source_diff_row_0based',1),('candidate_group_time_ns',10),
                          ('side','A'),('closure_witness_source_row',3),('closure_witness_time_ns',20)]:
            changed=deepcopy(extension)
            changed[0][key]=value
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_rows(base,changed,{('B',100)},10,20)

    def test_prefix_unchanged_and_complete_eighth_trade_retained(self):
        rows=[row(seq,'visible_new_order') for seq in range(20,90,10)]
        rows += [row(90,'matched_trade_decrease','trade-k'),row(91,'matched_trade_decrease','trade-k'),
                 row(100,'observed_cancel')]
        original={'episode_id':'anchor','initial_raw_seq':10, 'initial':[{'oid':'probe','sz':'0.00000010'}],
                  'events':group_level(rows[:2]), 'horizon_complete':False}
        untouched=deepcopy(original)
        result=extend_episode(original,rows,200)
        self.assertEqual(original,untouched)
        self.assertTrue(result['horizon_complete'])
        self.assertEqual(len(result['events']),8)
        self.assertEqual([d['raw_seq'] for d in result['events'][-1]['diffs']],[90,91])
        self.assertEqual(result['initial'],original['initial'])
        altered=deepcopy(original)
        altered['events'][0]['diffs'][0]['raw_book_diff']['new']['sz']='1'
        with self.assertRaisesRegex(ValueError,'prefix'):
            extend_episode(altered,rows,200)


if __name__=='__main__':
    unittest.main(verbosity=2)
