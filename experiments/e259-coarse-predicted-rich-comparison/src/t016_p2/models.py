"""Frozen estimators and population scaling; no automatic retry or rescue."""
from dataclasses import dataclass
import numpy as np
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.ensemble import HistGradientBoostingClassifier


@dataclass
class PopulationScaler:
    means: np.ndarray
    scales: np.ndarray

    @classmethod
    def from_training(cls, values):
        values = np.asarray(values, dtype=np.float64)
        if values.ndim != 2 or not len(values) or not np.isfinite(values).all():
            raise ValueError('Finite nonempty training matrix required')
        means = values.mean(axis=0)
        scales = values.std(axis=0, ddof=0)
        scales[scales == 0] = 1
        return cls(means, scales)

    def transform(self, values):
        result = (np.asarray(values, dtype=np.float64) - self.means) / self.scales
        if not np.isfinite(result).all():
            raise ValueError('Nonfinite scaled values')
        return result

    def inverse(self, values):
        result = self.means + self.scales * np.asarray(values, dtype=np.float64)
        if not np.isfinite(result).all():
            raise ValueError('Nonfinite inverse-scaled values')
        return result


def make_auxiliary(seed):
    return Ridge(alpha=1, fit_intercept=True, copy_X=True, max_iter=None,
                 tol=1e-4, solver='cholesky', positive=False, random_state=seed)


def make_candidate(candidate, proposal, seed):
    if candidate['model'] == 'multinomial_logistic':
        # With three classes and lbfgs, the pinned runtime uses multinomial loss.
        return LogisticRegression(C=candidate['C'], **proposal['logistic'],
            class_weight=None, random_state=seed, warm_start=False)
    if candidate['model'] == 'histogram_gradient_boosting':
        return HistGradientBoostingClassifier(max_leaf_nodes=candidate['max_leaf_nodes'],
            l2_regularization=candidate['l2_regularization'], **proposal['hgb'],
            loss='log_loss', max_depth=None, categorical_features=None,
            monotonic_cst=None, interaction_cst=None, warm_start=False,
            random_state=seed, class_weight=None)
    raise ValueError('Unknown frozen candidate')
