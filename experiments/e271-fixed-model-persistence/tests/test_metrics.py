"""Synthetic support and strict-joint edge cases; no market data or fitted objects."""
import itertools
import unittest
import numpy as np
from t016_p5.common import METHODS
from t016_p5.metrics import component, joint_verdict, score_family, make_joint

class TestPersistence(unittest.TestCase):
    def test_strict_joint_truth_table(self):
        for values in itertools.product((None,-1.,0.,1.),repeat=3):
            components={str(i):component(x) for i,x in enumerate(values)}
            expected=('contradicted_on_this_day' if any(x is not None and x<=0 for x in values)
                      else 'holds_on_this_day_only' if all(x is not None and x>0 for x in values)
                      else 'unavailable')
            self.assertEqual(joint_verdict(components),expected)

    def test_audit_disagreement_withholds_component(self):
        rows={str(i):component(1.) for i in range(3)}
        rows['0']['status']='unavailable'
        self.assertEqual(joint_verdict(rows),'unavailable')
        rows['1']=component(-1.)
        self.assertEqual(joint_verdict(rows),'contradicted_on_this_day')

    def test_missing_class_and_empty_cohort(self):
        for y in ([],[1,2],[0,1,2]):
            n=len(y); data={'families':np.array(['breakout']*n,dtype='U8'),
                'matched':np.ones(n,dtype=bool),'y':np.array(y,dtype=int),'event_ids':np.array(list(map(str,range(n))))}
            p={m:np.full((n,3),1/3) for m in METHODS}
            row,_=score_family(data,p,'breakout',[.2,.3,.5]); joint=make_joint(row)
            self.assertEqual(row['profiles']['C']['equal_day'],row['profiles']['C']['pooled_event'])
            self.assertEqual(joint['verdict'],'unavailable' if not n else 'contradicted_on_this_day')
            if not n or 0 not in y:
                self.assertEqual(joint['components']['fixed_class']['status'],'unavailable')
                self.assertEqual(joint['components']['favorable_conditional']['status'],'unavailable')

if __name__=='__main__': unittest.main()
