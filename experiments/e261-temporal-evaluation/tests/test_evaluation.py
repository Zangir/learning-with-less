"""Aggregation and failure-policy checks with no estimator or market operation."""
import unittest
from t016_p3.evaluate import aggregate
from t016_p3.common import DATES, FAMILIES


class AggregationTests(unittest.TestCase):
    def rows(self):
        return [{'date':date,'scores':[{'family':family,'status':'evaluable','n':i+1,
            'scores':{'C':i/10,'P':.1},'paired':{'C-P':i/10-.1}}
            for family in FAMILIES]} for i,date in enumerate(DATES)]

    def test_equal_day_and_event_estimands_differ(self):
        result=aggregate(self.rows())['breakout']
        self.assertAlmostEqual(result['equal_day']['C'],.15)
        self.assertAlmostEqual(result['pooled_event']['C'],.2)
        self.assertAlmostEqual(result['paired_equal_day']['C-P'],.05)
        self.assertAlmostEqual(result['paired_pooled_event']['C-P'],.1)

    def test_missing_date_withholds_complete_aggregate(self):
        rows=self.rows();rows[2]['scores']=[]
        for result in aggregate(rows).values():
            self.assertFalse(result['complete_four_dates'])
            self.assertIsNone(result['equal_day'])
            self.assertIsNone(result['pooled_event'])

    def test_missing_family_is_not_silently_reweighted(self):
        rows=self.rows();rows[0]['scores'][1]['status']='unavailable'
        result=aggregate(rows)
        self.assertTrue(result['breakout']['complete_four_dates'])
        self.assertFalse(result['rebound']['complete_four_dates'])

    def test_three_date_list_is_rejected(self):
        with self.assertRaises(ValueError):
            aggregate(self.rows()[:3])


if __name__ == '__main__':
    unittest.main()
