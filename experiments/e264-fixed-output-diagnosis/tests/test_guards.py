"""Forbidden operations must stop before learning or solving."""
import unittest
import pickle
import numpy as np
from t016_p2.models import PopulationScaler
from t016_p4.guards import install_guards

class GuardTests(unittest.TestCase):
    def test_solver_is_blocked(self):
        ledger=install_guards()
        with self.assertRaises(RuntimeError):np.linalg.solve(np.eye(1),np.ones(1))
        self.assertEqual(ledger['solver_calls'],0)
    def test_saved_model_loading_is_blocked(self):
        ledger=install_guards()
        with self.assertRaises(RuntimeError):pickle.loads(b'no object is read')
        self.assertEqual(ledger['model_inference_calls'],0)
    def test_scaler_learning_is_blocked(self):
        ledger=install_guards()
        with self.assertRaises(RuntimeError):PopulationScaler.from_training(np.ones((2,1)))
        self.assertEqual(ledger['fit_guard']['actual_fit_calls'],0)
