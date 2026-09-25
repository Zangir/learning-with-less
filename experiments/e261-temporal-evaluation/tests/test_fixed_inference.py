"""No-fit guards, pure saved transforms and accepted May-July model replay."""
import hashlib
from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.ensemble._hist_gradient_boosting.binning import _BinMapper
from sklearn.linear_model import LogisticRegression, Ridge, SGDClassifier
from sklearn.preprocessing import MinMaxScaler, StandardScaler

from t016_p2.models import PopulationScaler
from t016_p3 import fixed_inference as fixed


_INFERENCE = None
_REPLAY = None


def inference():
    global _INFERENCE
    if _INFERENCE is None:
        _INFERENCE = fixed.FixedInference()
    return _INFERENCE


def accepted_arrays(name):
    root = fixed.FROZEN_R029
    content = (root / name).read_bytes()
    manifest = json.loads((root / 'artifact-manifest.json').read_text(encoding='utf-8-sig'))
    record = next(row for row in manifest['files'] if row['path'].replace('\\', '/') == name)
    if len(content) != record['size_bytes'] or hashlib.sha256(content).hexdigest() != record['sha256']:
        raise AssertionError('Accepted replay member differs: ' + name)
    with np.load(BytesIO(content), allow_pickle=False) as archive:
        return {name: archive[name] for name in archive.files}


def accepted_replay():
    global _REPLAY
    if _REPLAY is None:
        model = inference()
        data = accepted_arrays('prepared-cohort.npz')
        rows = np.flatnonzero(data['downstream_mask'] & np.isin(
            data['dates'], ['2025-05-01', '2025-06-01', '2025-07-01']))
        attempts = len(model.guard_ledger['attempts'])
        result = model.predict(data['X'][rows], data['Z'][rows], data['families'][rows])
        if len(model.guard_ledger['attempts']) != attempts:
            raise AssertionError('Accepted replay attempted a forbidden fit')
        _REPLAY = data, rows, result
    return _REPLAY


class FitGuardTests(unittest.TestCase):
    def test_estimator_scaler_and_private_binning_calls_are_blocked(self):
        ledger = fixed.install_fit_guards()
        operations = (
            (Ridge(), 'fit'), (LogisticRegression(), 'fit'),
            (HistGradientBoostingClassifier(), 'fit'), (SGDClassifier(), 'partial_fit'),
            (StandardScaler(), 'fit'), (StandardScaler(), 'partial_fit'),
            (MinMaxScaler(), 'fit_transform'), (_BinMapper(), 'fit'),
            (_BinMapper(), 'fit_transform'), (PopulationScaler, 'from_training'),
        )
        for target, method in operations:
            with self.subTest(target=type(target).__name__, method=method):
                previous = len(ledger['attempts'])
                with self.assertRaises(fixed.FitForbiddenError):
                    getattr(target, method)(np.zeros((2, 3)))
                self.assertEqual(len(ledger['attempts']), previous + 1)
                self.assertTrue(ledger['attempts'][-1]['blocked_before_original_call'])
        self.assertEqual(ledger['actual_fit_calls'], 0)

    def test_installation_is_idempotent_and_preserves_attempt_history(self):
        ledger = fixed.install_fit_guards()
        count = len(ledger['attempts'])
        self.assertIs(fixed.install_fit_guards(), ledger)
        self.assertTrue(ledger['installed'])
        self.assertEqual(len(ledger['attempts']), count)
        self.assertTrue(any('_BinMapper.fit' in name for name in ledger['guarded_methods']))
        self.assertIn('t016_p2.models.PopulationScaler.from_training', ledger['guarded_methods'])

    def test_replaced_fit_guard_is_detected_before_inference(self):
        fixed.install_fit_guards()
        with patch.object(Ridge, 'fit', lambda *args, **kwargs: None):
            with self.assertRaises(fixed.FitForbiddenError):
                fixed.install_fit_guards()
        self.assertTrue(fixed.install_fit_guards()['installed'])


class SavedTransformTests(unittest.TestCase):
    def test_existing_scaler_transforms_without_recomputing_moments(self):
        ledger = fixed.install_fit_guards()
        previous = len(ledger['attempts'])
        scaler = PopulationScaler(np.array([2., 7., 4.]), np.array([1., 1., 2.]))
        means, scales = scaler.means.copy(), scaler.scales.copy()
        actual = scaler.transform([[1., 7., 2.], [3., 9., 8.]])
        np.testing.assert_array_equal(actual, [[-1., 0., -1.], [1., 2., 2.]])
        np.testing.assert_array_equal(scaler.inverse(actual), [[1., 7., 2.], [3., 9., 8.]])
        np.testing.assert_array_equal(scaler.means, means)
        np.testing.assert_array_equal(scaler.scales, scales)
        self.assertEqual(len(ledger['attempts']), previous)

    def test_inverse_preserves_first_four_log_coordinates(self):
        scaler = PopulationScaler(np.array([2., 3., 4., 5., .2, 10., 12.]),
                                  np.array([1., 2., 3., 4., .1, 2., 3.]))
        expected = [[3., 5., 7., 9., .3, 12., 15.]]
        np.testing.assert_allclose(scaler.inverse(np.ones((1, 7))), expected, rtol=0, atol=1e-15)


class FrozenIdentityTests(unittest.TestCase):
    def test_fixed_identity_has_six_selected_objects_and_last_auxiliary(self):
        identity = inference().identity
        self.assertEqual(identity['manifest_sha256'], fixed.MANIFEST_SHA256)
        self.assertEqual(identity['execution_commit'], fixed.EXECUTION_COMMIT)
        self.assertEqual(identity['class_order'], ['F', 'A', 'N'])
        self.assertEqual(len(identity['selected_models']), 6)
        for name, record in identity['selected_models'].items():
            expected = 'hgb-leaf7-l20' if name == 'rebound-R' else 'hgb-leaf7-l21'
            self.assertEqual(record['candidate'], expected)
            self.assertEqual(record['estimator']['path'], 'models/' + name + '-' + expected + '/estimator.pkl')
            self.assertEqual(record['scaler']['path'], 'scalers/' + name + '.npz')
        self.assertEqual(identity['auxiliary']['fit_id'], 'auxiliary-3')
        self.assertEqual(identity['auxiliary']['training_dates'], ['2025-01-01', '2025-02-01', '2025-03-01'])
        self.assertEqual(identity['new_fits'], 0)
        json.dumps(identity, allow_nan=False)

    def test_pickle_loading_requires_guards_already_installed(self):
        original = fixed.pickle.loads
        calls = []

        def checked_load(content):
            self.assertTrue(fixed.install_fit_guards()['installed'])
            calls.append(1)
            return original(content)

        with patch.object(fixed.pickle, 'loads', side_effect=checked_load):
            model = fixed.FixedInference()
        self.assertEqual(len(calls), 7)
        self.assertEqual(len(model.models), 6)

    def test_unbound_manifest_rejected_before_any_pickle_load(self):
        with tempfile.TemporaryDirectory(prefix='t016-e261-bad-manifest-') as directory:
            (Path(directory) / 'artifact-manifest.json').write_text('{"files":[]}', encoding='utf-8')
            with patch.object(fixed.pickle, 'loads') as loader:
                with self.assertRaises(ValueError):
                    fixed.FixedInference(directory)
                loader.assert_not_called()

    def test_saved_scaler_moments_are_read_only_and_shared_prefixes_identical(self):
        model = inference()
        for family in fixed.FAMILIES:
            coarse = model.scalers[(family, 'C')]
            for arm in ('C', 'P', 'R'):
                scaler = model.scalers[(family, arm)]
                self.assertFalse(scaler.means.flags.writeable)
                self.assertFalse(scaler.scales.flags.writeable)
                np.testing.assert_array_equal(coarse.means, scaler.means[:446])
                np.testing.assert_array_equal(coarse.scales, scaler.scales[:446])


class FixedReferencesAndInputsTests(unittest.TestCase):
    def test_training_frequency_reuses_only_frozen_family_counts(self):
        model = inference()
        families = np.array(['rebound', 'breakout', 'rebound'])
        result = model.reference_probabilities(families)
        breakout = np.array([230, 87, 358]) / 675
        rebound = np.array([44, 276, 277]) / 597
        np.testing.assert_array_equal(result['train-frequency'], np.stack([rebound, breakout, rebound]))
        self.assertEqual(set(result), {'onehot-F', 'onehot-A', 'onehot-N', 'uniform', 'train-frequency'})
        for number, label in enumerate(('F', 'A', 'N')):
            np.testing.assert_array_equal(result['onehot-' + label], np.tile(np.eye(3)[number], (3, 1)))
        np.testing.assert_array_equal(result['uniform'], np.full((3, 3), 1 / 3))

    def test_empty_population_is_supported_without_model_prediction(self):
        model = inference()
        with patch.object(model.auxiliary_model, 'predict', side_effect=AssertionError('empty prediction call')):
            result = model.predict(np.empty((0, 446)), np.empty((0, 1464)), [])
        for arm in ('C', 'P', 'R'):
            self.assertEqual(result[arm].shape, (0, 3))
        self.assertEqual(result['aux_prediction'].shape, (0, 7))
        self.assertEqual(result['class_order'], ('F', 'A', 'N'))

    def test_unknown_family_and_wrong_width_fail_before_prediction(self):
        model = inference()
        with patch.object(model.auxiliary_model, 'predict', side_effect=AssertionError('invalid prediction call')):
            with self.assertRaises(ValueError):
                model.predict(np.zeros((1, 446)), np.zeros((1, 1464)), ['unknown'])
            with self.assertRaises(ValueError):
                model.predict(np.zeros((1, 445)), np.zeros((1, 1464)), ['breakout'])
            with self.assertRaises(ValueError):
                model.predict(np.zeros((2, 446)), np.zeros((1, 1464)), ['breakout'])

    def test_nonfinite_inputs_are_rejected_without_dropping_rows(self):
        model = inference()
        X, Z = np.zeros((1, 446)), np.zeros((1, 1464))
        X[0, 0] = np.nan
        with patch.object(model.auxiliary_model, 'predict', side_effect=AssertionError('invalid prediction call')):
            with self.assertRaises(ValueError):
                model.predict(X, Z, ['breakout'])
            X[0, 0], Z[0, 0] = 0, np.inf
            with self.assertRaises(ValueError):
                model.predict(X, Z, ['breakout'])


class AcceptedOutputReplayTests(unittest.TestCase):
    def test_six_selected_may_july_probability_arrays_replay_bitwise(self):
        data, rows, result = accepted_replay()
        self.assertEqual(len(rows), 1408)
        self.assertEqual(result['class_order'], ('F', 'A', 'N'))
        np.testing.assert_array_equal(result['families'], data['families'][rows])
        for family in fixed.FAMILIES:
            local = data['families'][rows] == family
            for arm in ('C', 'P', 'R'):
                saved = accepted_arrays('selected-' + family + '-' + arm + '.npz')
                keep = np.isin(data['dates'][saved['event_indices']],
                               ['2025-05-01', '2025-06-01', '2025-07-01'])
                np.testing.assert_array_equal(rows[local], saved['event_indices'][keep])
                np.testing.assert_array_equal(result[arm][local], saved['probabilities'][keep])

    def test_auxiliary_uses_final_fixed_object_and_common_coordinate_inverse(self):
        data, rows, result = accepted_replay()
        saved = accepted_arrays('auxiliary-predictions.npz')
        auxiliary_rows = data['event_to_auxiliary_index'][rows]
        np.testing.assert_array_equal(saved['fold'][auxiliary_rows], np.full(len(rows), 2))
        np.testing.assert_allclose(result['aux_prediction'], saved['predictions'][auxiliary_rows],
                                   rtol=1e-12, atol=1e-12)
        scaler = inference().auxiliary_target_scaler
        np.testing.assert_array_equal(result['aux_prediction'],
                                      scaler.means + scaler.scales * result['aux_standardized'])

    def test_fixed_replay_preserves_probability_validity(self):
        _, _, result = accepted_replay()
        for arm in ('C', 'P', 'R'):
            values = result[arm]
            self.assertTrue(np.isfinite(values).all())
            self.assertTrue(((values >= 0) & (values <= 1)).all())
            np.testing.assert_allclose(values.sum(axis=1), 1, rtol=0, atol=1e-12)
        self.assertEqual(inference().guard_ledger['actual_fit_calls'], 0)


if __name__ == '__main__':
    unittest.main()
