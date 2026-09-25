"""Check ambiguity retention and exact quantity matching for clock diagnostics."""
import json
from pathlib import Path
import unittest
from clock_coverage import units, update_candidate


class Candidates(unittest.TestCase):
    def test_exact_decimal_subtraction(self):
        self.assertEqual(units("0.2086")-units("0.2076"),100000)
        with self.assertRaises(ValueError):units("0.000000001")

    def test_mismatched_multiplicity_retains_interval(self):
        candidate,source=update_candidate([300,100],0,1)
        self.assertEqual(candidate,(100,300))
        self.assertEqual(source,"exact_size_trade_interval")

    def test_equal_multiplicity_uses_declared_ordinal(self):
        candidate,source=update_candidate([300,100],1,2)
        self.assertEqual(candidate,(300,300))
        self.assertEqual(source,"equal_multiplicity_trade_ordinal")

    def test_missing_size_match_remains_missing(self):
        candidate,source=update_candidate([],0,1)
        self.assertIsNone(candidate)
        self.assertEqual(source,"missing_exact_size_trade")


if __name__=="__main__":
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Candidates))
    Path(__file__).with_name("clock_tests.json").write_text(json.dumps(dict(tests=result.testsRun,passed=result.wasSuccessful(),failures=len(result.failures),errors=len(result.errors)),indent=2))
    raise SystemExit(0 if result.wasSuccessful() else 1)
