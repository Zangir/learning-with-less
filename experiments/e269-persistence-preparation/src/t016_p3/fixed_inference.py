"""Verified R029 inference only: fixed objects, scalers, references and fit guards."""
from datetime import datetime, timezone
import hashlib
import importlib
import inspect
import json
from pathlib import Path
import pickle
import sys

import numpy as np
from sklearn.base import BaseEstimator
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.ensemble._hist_gradient_boosting.binning import _BinMapper
from sklearn.linear_model import Ridge
from sklearn.utils.discovery import all_estimators

from t016_p2.metrics import CLASS_ORDER, align_probabilities
from t016_p2.models import PopulationScaler


ARTIFACTS = (Path(__file__).resolve().parents[2] / 'runtime')
FROZEN_R029 = ARTIFACTS / 'cycle-20260922-0921/frozen-R-029'
MANIFEST_SHA256 = '9b803d7598f20f8e3e17291de769731806175ec7c4088373090834a0020b8bb0'
EXECUTION_COMMIT = '30fb8a00c199a2e74a98851d4292cf3b8b6819e6'
PACKAGES = (Path(__file__).resolve().parents[2] / 'runtime' / 'python-packages')
FAMILIES = ('breakout', 'rebound')
WIDTHS = {'C': 446, 'P': 453, 'R': 1910}
_GUARD_LEDGER = None
_GUARDED = {}


class FitForbiddenError(RuntimeError):
    """A fit-like operation was stopped before its original implementation ran."""


def _guard(method):
    def forbidden(*args, **kwargs):
        _GUARD_LEDGER['attempts'].append({
            'method': method, 'utc': datetime.now(timezone.utc).isoformat(),
            'blocked_before_original_call': True,
        })
        raise FitForbiddenError('E261 is inference-only; forbidden operation: ' + method)
    return forbidden


def install_fit_guards():
    """Block public estimator fitting, private bin fitting and new scaler moments.

    Discovery imports sklearn classes, without constructing or fitting models.
    Public estimators plus registered private subclasses and their mixins are
    covered. Reinstallation checks that no previously installed guard was removed.
    The returned live ledger includes intentional blocked unit-test probes; a
    fresh inference process must have no attempts. No original fit is delegated.
    """
    global _GUARD_LEDGER
    if _GUARD_LEDGER is not None:
        if not _GUARD_LEDGER['installed']:
            raise FitForbiddenError('Fit-guard installation did not complete')
        for (cls, name), installed in _GUARDED.items():
            if inspect.getattr_static(cls, name) is not installed:
                raise FitForbiddenError('An installed fit guard was replaced: ' + cls.__name__ + '.' + name)
        return _GUARD_LEDGER
    _GUARD_LEDGER = {'installed': False, 'guarded_methods': [], 'attempts': [], 'actual_fit_calls': 0}
    classes = {cls for _, cls in all_estimators()} | {_BinMapper}
    pending, visited = [BaseEstimator], set()
    while pending:
        cls = pending.pop()
        if cls in visited:
            continue
        visited.add(cls)
        pending.extend(cls.__subclasses__())
        if cls.__module__.startswith('sklearn.'):
            classes.add(cls)
    classes |= {base for cls in list(classes) for base in cls.__mro__
                if base.__module__.startswith('sklearn.')}
    operations = [(cls, name) for cls in sorted(classes, key=lambda c: (c.__module__, c.__name__))
                  for name in ('fit', 'fit_transform', 'partial_fit', 'fit_predict')
                  if inspect.getattr_static(cls, name, None) is not None]
    operations.append((PopulationScaler, 'from_training'))
    for cls, name in operations:
        original = inspect.getattr_static(cls, name)
        identifier = cls.__module__ + '.' + cls.__qualname__ + '.' + name
        replacement = _guard(identifier)
        if isinstance(original, classmethod):
            replacement = classmethod(replacement)
        elif isinstance(original, staticmethod):
            replacement = staticmethod(replacement)
        setattr(cls, name, replacement)
        _GUARDED[(cls, name)] = inspect.getattr_static(cls, name)
        _GUARD_LEDGER['guarded_methods'].append(identifier)
    _GUARD_LEDGER['installed'] = True
    return _GUARD_LEDGER


def _digest(content):
    return hashlib.sha256(content).hexdigest()


def _read_json(content):
    return json.loads(content.decode('utf-8-sig'))


def fixed_identity(root=FROZEN_R029):
    """Bind consumed frozen members only; full packet verification is the caller's gate."""
    root = Path(root).resolve()
    manifest_bytes = (root / 'artifact-manifest.json').read_bytes()
    if _digest(manifest_bytes) != MANIFEST_SHA256:
        raise ValueError('Unexpected frozen R029 manifest')
    entries = _read_json(manifest_bytes)['files']
    members = {entry['path'].replace('\\', '/'): entry for entry in entries}
    if len(members) != len(entries):
        raise ValueError('Duplicate frozen member paths')
    consumed = {}

    def bind(name):
        path = (root / name).resolve()
        path.relative_to(root)
        record = members[name]
        content = path.read_bytes()
        if len(content) != record['size_bytes'] or _digest(content) != record['sha256']:
            raise ValueError('Frozen input differs: ' + name)
        consumed[name] = {'path': name, 'sha256': record['sha256'], 'size_bytes': record['size_bytes']}
        return content

    freeze = _read_json(bind('execution-freeze.json'))
    selection = _read_json(bind('selection.json'))
    config = _read_json(bind('comparison-config.json'))
    references = _read_json(bind('reference-results.json'))
    runtime = _read_json(bind('runtime-identity.json'))
    if freeze['execution_commit'] != EXECUTION_COMMIT:
        raise ValueError('Unexpected accepted execution commit')
    if config['accepted_proposal']['class_order'] != list(CLASS_ORDER):
        raise ValueError('Frozen class order differs')
    plan = {row['fit_id']: row for row in config['fit_plan']}
    expected_arms = {family + '-' + arm for family in FAMILIES for arm in WIDTHS}
    if set(selection) != expected_arms:
        raise ValueError('Frozen six-arm selection differs')

    def object_record(identifier, scaler_names):
        prefix = 'models/' + identifier + '/'
        fit = _read_json(bind(prefix + 'fit.json'))
        estimator_name = prefix + 'estimator.pkl'
        bind(estimator_name)
        if (fit['status'] != 'evaluable' or fit['fit_id'] != identifier
                or fit['parameters'] != plan[identifier]['parameters']
                or consumed[estimator_name]['sha256'] != fit['estimator_sha256']):
            raise ValueError('Frozen fitted-object receipt differs: ' + identifier)
        for name in scaler_names.values():
            bind(name)
        return {'fit_id': identifier, 'parameters': fit['parameters'],
                'estimator': consumed[estimator_name], 'fit_receipt': consumed[prefix + 'fit.json'],
                **{name: consumed[path] for name, path in scaler_names.items()}}

    models = {}
    for family in FAMILIES:
        for arm in WIDTHS:
            name = family + '-' + arm
            selected = selection[name]
            if selected['status'] != 'evaluable' or selected['refit'] is not False:
                raise ValueError('Fixed selection is not evaluable: ' + name)
            candidate = selected['selected']
            record = object_record(name + '-' + candidate, {'scaler': 'scalers/' + name + '.npz'})
            record.update(family=family, arm=arm, candidate=candidate, input_width=WIDTHS[arm])
            models[name] = record
    auxiliary = object_record('auxiliary-3', {
        'input_scaler': 'models/auxiliary-3/input-scaler.npz',
        'target_scaler': 'models/auxiliary-3/target-scaler.npz',
    })
    auxiliary['training_dates'] = plan['auxiliary-3']['fold']['train']
    if auxiliary['training_dates'] != ['2025-01-01', '2025-02-01', '2025-03-01']:
        raise ValueError('Fixed auxiliary must be the accepted January-March object')
    auxiliary['target_coordinates'] = config['schema']['P'][446:]
    fixed_references = {}
    for family in FAMILIES:
        daily = references[family]['train-frequency']['per_day']
        counts = [sum(daily[day]['class_counts'][label] for day in ('2025-02-01', '2025-03-01'))
                  for label in CLASS_ORDER]
        if not all(count > 0 for count in counts):
            raise ValueError('Accepted training reference lacks a class')
        constants = {f'onehot-{label}': np.eye(3)[k].tolist() for k, label in enumerate(CLASS_ORDER)}
        constants.update(uniform=[1 / 3] * 3,
                         **{'train-frequency': [count / sum(counts) for count in counts]})
        fixed_references[family] = {'training_dates': ['2025-02-01', '2025-03-01'],
                                    'class_counts': dict(zip(CLASS_ORDER, counts)), 'probabilities': constants}
    return {'root': str(root), 'manifest_sha256': MANIFEST_SHA256,
            'execution_commit': EXECUTION_COMMIT, 'class_order': list(CLASS_ORDER),
            'selected_models': models, 'auxiliary': auxiliary, 'references': fixed_references,
            'runtime': {'versions': runtime['versions'], 'executable_sha256': runtime['executable_sha256']},
            'files': [consumed[name] for name in sorted(consumed)], 'new_fits': 0}


def _verified_bytes(root, record):
    path = (Path(root) / record['path']).resolve()
    path.relative_to(Path(root).resolve())
    content = path.read_bytes()
    if _digest(content) != record['sha256'] or len(content) != record['size_bytes']:
        raise ValueError('Frozen member changed before consumption: ' + record['path'])
    return content


def _load_scaler(root, record, width):
    from io import BytesIO
    with np.load(BytesIO(_verified_bytes(root, record)), allow_pickle=False) as values:
        if set(values.files) != {'means', 'scales'}:
            raise ValueError('Unexpected frozen scaler fields')
        means, scales = values['means'].copy(), values['scales'].copy()
    if (means.shape != (width,) or scales.shape != (width,) or not np.isfinite(means).all()
            or not np.isfinite(scales).all() or np.any(scales <= 0)):
        raise ValueError('Invalid saved scaler')
    means.flags.writeable = False
    scales.flags.writeable = False
    return PopulationScaler(means, scales)


class FixedInference:
    """Reuse seven verified fitted objects; no target, date or label influences inference."""

    def __init__(self, root=FROZEN_R029):
        self.guard_ledger = install_fit_guards()
        self.identity = fixed_identity(root)
        self.root = Path(root).resolve()
        if _digest(Path(sys.executable).read_bytes()) != self.identity['runtime']['executable_sha256']:
            raise ValueError('Python executable differs from accepted runtime')
        for distribution, version in self.identity['runtime']['versions'].items():
            module = importlib.import_module('sklearn' if distribution == 'scikit-learn' else distribution)
            if module.__version__ != version:
                raise ValueError('Runtime version differs: ' + distribution)
            Path(module.__file__).resolve().relative_to(PACKAGES.resolve())
        self.models, self.scalers = {}, {}
        for record in self.identity['selected_models'].values():
            key = record['family'], record['arm']
            # The fitting door is locked before a saved object enters the room.
            model = pickle.loads(_verified_bytes(self.root, record['estimator']))
            if (not isinstance(model, HistGradientBoostingClassifier)
                    or model.get_params() != record['parameters']
                    or model.n_features_in_ != record['input_width']
                    or not np.array_equal(model.classes_, [0, 1, 2])):
                raise ValueError('Saved selected model state differs: ' + record['fit_id'])
            self.models[key] = model
            self.scalers[key] = _load_scaler(self.root, record['scaler'], record['input_width'])
        for family in FAMILIES:
            coarse = self.scalers[(family, 'C')]
            for arm in ('P', 'R'):
                other = self.scalers[(family, arm)]
                if not (np.array_equal(coarse.means, other.means[:446])
                        and np.array_equal(coarse.scales, other.scales[:446])):
                    raise ValueError('Frozen family scalers disagree on shared X')
        auxiliary = self.identity['auxiliary']
        self.auxiliary_model = pickle.loads(_verified_bytes(self.root, auxiliary['estimator']))
        if (not isinstance(self.auxiliary_model, Ridge)
                or self.auxiliary_model.get_params() != auxiliary['parameters']
                or self.auxiliary_model.n_features_in_ != 440
                or self.auxiliary_model.coef_.shape != (7, 440)):
            raise ValueError('Saved auxiliary state differs')
        self.auxiliary_input_scaler = _load_scaler(self.root, auxiliary['input_scaler'], 440)
        self.auxiliary_target_scaler = _load_scaler(self.root, auxiliary['target_scaler'], 7)

    @staticmethod
    def _families(families):
        values = np.asarray(families)
        if values.ndim != 1 or not np.isin(values, FAMILIES).all():
            raise ValueError('Families must be a vector containing breakout/rebound only')
        return values

    def reference_probabilities(self, families):
        families = self._families(families)
        names = ('onehot-F', 'onehot-A', 'onehot-N', 'uniform', 'train-frequency')
        outputs = {name: np.empty((len(families), 3), dtype=np.float64) for name in names}
        for family in FAMILIES:
            rows = families == family
            for name in names:
                outputs[name][rows] = self.identity['references'][family]['probabilities'][name]
        return outputs

    def predict(self, X, Z, families):
        install_fit_guards()
        X, Z = np.asarray(X, dtype=np.float64), np.asarray(Z, dtype=np.float64)
        families = self._families(families)
        n = len(families)
        if X.shape != (n, 446) or Z.shape != (n, 1464):
            raise ValueError('Expected matching X446/Z1464/family rows')
        if not np.isfinite(X).all() or not np.isfinite(Z).all():
            raise ValueError('Inference inputs must be finite; no row removal or imputation')
        outputs = {arm: np.empty((n, 3), dtype=np.float64) for arm in WIDTHS}
        standardized = np.empty((n, 7), dtype=np.float64)
        common = np.empty((n, 7), dtype=np.float64)
        if n:
            standardized = self.auxiliary_model.predict(self.auxiliary_input_scaler.transform(X[:, :440]))
            if standardized.shape != (n, 7) or not np.isfinite(standardized).all():
                raise ValueError('Invalid frozen auxiliary output')
            common = self.auxiliary_target_scaler.inverse(standardized)
            views = {'C': X, 'P': np.column_stack((X, common)), 'R': np.column_stack((X, Z))}
            for family in FAMILIES:
                rows = families == family
                if not rows.any():
                    continue
                for arm in WIDTHS:
                    key = family, arm
                    model = self.models[key]
                    outputs[arm][rows] = align_probabilities(
                        model.predict_proba(self.scalers[key].transform(views[arm][rows])), model.classes_)
        outputs.update(aux_prediction=common, aux_standardized=standardized,
                       class_order=CLASS_ORDER, families=families.copy())
        return outputs
