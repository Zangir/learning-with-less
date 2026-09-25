"""Pure fixed-output profiles and descriptive decompositions; no model operations.

Class conditionals refer to the complete per-event loss given the observed label,
not to marginal one-vs-rest Brier components. Group standardization consumes the
profile formed with the original endpoint's row weights, never daily standardized
losses averaged afterward.
"""
from collections.abc import Mapping

import numpy as np

from t016_p2.metrics import CLASS_ORDER, encode_labels, half_brier


def _class_vector(values, name, allow_none=False):
    if isinstance(values, Mapping):
        if set(values) != set(CLASS_ORDER):
            raise ValueError(name + ' must contain exactly F/A/N')
        values = [values[label] for label in CLASS_ORDER]
    if len(values) != 3:
        raise ValueError(name + ' must have three entries')
    result = []
    for value in values:
        if value is None and allow_none:
            result.append(None)
        elif value is None or not np.isfinite(float(value)):
            raise ValueError(name + ' must contain finite values')
        else:
            result.append(float(value))
    return result


def _profile_values(record):
    q = np.asarray(_class_vector(record['q'], 'Class fractions'))
    ell = _class_vector(record['ell'], 'Conditional losses', allow_none=True)
    total = float(record['total_loss'])
    if np.any(q < 0) or not np.isclose(q.sum(), 1, rtol=0, atol=1e-12):
        raise ValueError('Class fractions must be nonnegative and sum to one')
    if not np.isfinite(total) or any(q[k] > 0 and ell[k] is None for k in range(3)):
        raise ValueError('Positive class mass requires a finite conditional loss')
    represented = sum(q[k] * ell[k] for k in range(3) if ell[k] is not None)
    if not np.isclose(represented, total, rtol=1e-12, atol=1e-12):
        raise ValueError('Profile total does not reconcile with its class conditionals')
    return q, ell, total


def profile_loss(y, losses, row_weights=None):
    """Weighted q, E[loss|class] and total for arbitrary finite signed row losses.

    Finite nonnegative row weights are normalized to unit total. A class with no
    positive weighted support has ell=None, even if zero-weight rows exist.
    """
    labels = encode_labels(y)
    losses = np.asarray(losses, dtype=np.float64)
    if losses.ndim != 1 or len(losses) != len(labels) or not len(labels):
        raise ValueError('Nonempty labels and aligned scalar row losses required')
    if not np.isfinite(losses).all():
        raise ValueError('Row losses must be finite')
    weights = np.ones(len(labels)) if row_weights is None else np.asarray(row_weights, dtype=np.float64)
    if weights.shape != losses.shape or not np.isfinite(weights).all() or np.any(weights < 0):
        raise ValueError('Row weights must be aligned, finite and nonnegative')
    weight_sum = float(weights.sum())
    if not np.isfinite(weight_sum) or weight_sum <= 0:
        raise ValueError('Row weights require a finite positive total')
    weights = weights / weight_sum
    q, ell = {}, {}
    for k, name in enumerate(CLASS_ORDER):
        rows = labels == k
        mass = float(weights[rows].sum())
        q[name] = mass
        ell[name] = float(np.dot(weights[rows] / mass, losses[rows])) if mass > 0 else None
    total = float(np.dot(weights, losses))
    result = {'class_order': list(CLASS_ORDER), 'n': len(labels),
              'class_counts': dict(zip(CLASS_ORDER, np.bincount(labels, minlength=3).tolist())),
              'q': q, 'ell': ell, 'total_loss': total, 'input_weight_sum': weight_sum}
    _profile_values(result)
    return result


def profile(y, probabilities, row_weights=None):
    """Profile per-event half-scaled multiclass Brier in fixed F/A/N column order."""
    result = profile_loss(y, half_brier(y, probabilities), row_weights)
    result['total_half_brier'] = result['total_loss']
    return result


def standardize(record, weights):
    """Apply fixed class-reference probabilities to this endpoint-weighted profile."""
    _, ell, _ = _profile_values(record)
    weights = np.asarray(_class_vector(weights, 'Reference weights'))
    if np.any(weights < 0) or not np.isclose(weights.sum(), 1, rtol=0, atol=1e-12):
        raise ValueError('Reference weights must be nonnegative and sum to one')
    missing = [name for k, name in enumerate(CLASS_ORDER) if weights[k] > 0 and ell[k] is None]
    result = {'status': 'unavailable' if missing else 'evaluable', 'value': None,
              'class_components': None, 'missing_classes': missing,
              'reference_weights': dict(zip(CLASS_ORDER, weights.tolist()))}
    if not missing:
        components = {name: float(weights[k] * ell[k]) if weights[k] > 0 else 0.
                      for k, name in enumerate(CLASS_ORDER)}
        result.update(value=float(sum(components.values())), class_components=components)
    return result


def decompose(earlier, later):
    """Class mix first, earlier reference: delta = mix + within, class by class.

    E264 conservatively requires every class conditional in both groups, including
    a class that disappears. Missing support is not invited to impersonate zero.
    Raw later-minus-earlier total remains available when decomposition is withheld.
    """
    q_e, ell_e, total_e = _profile_values(earlier)
    q_l, ell_l, total_l = _profile_values(later)
    missing_e = [name for k, name in enumerate(CLASS_ORDER) if ell_e[k] is None]
    missing_l = [name for k, name in enumerate(CLASS_ORDER) if ell_l[k] is None]
    missing = [name for name in CLASS_ORDER if name in missing_e or name in missing_l]
    result = {'status': 'unavailable' if missing else 'evaluable', 'delta': total_l - total_e,
              'mix': None, 'within': None, 'mix_by_class': None, 'within_by_class': None,
              'missing_classes': missing, 'missing_by_group': {'earlier': missing_e, 'later': missing_l},
              'reconciliation_residual': None}
    if missing:
        return result
    mix = {name: float((q_l[k] - q_e[k]) * ell_e[k]) for k, name in enumerate(CLASS_ORDER)}
    within = {name: float(q_l[k] * (ell_l[k] - ell_e[k])) for k, name in enumerate(CLASS_ORDER)}
    mix_total, within_total = float(sum(mix.values())), float(sum(within.values()))
    result.update(mix=mix_total, within=within_total, mix_by_class=mix, within_by_class=within,
                  reconciliation_residual=float(result['delta'] - mix_total - within_total))
    return result


def group_row_weights(dates, weighting='equal_day'):
    """Preserve input row order; caller supplies the frozen group's exact date set."""
    dates = np.asarray(dates)
    if dates.ndim != 1 or not len(dates) or not all(isinstance(day, str) and day for day in dates):
        raise ValueError('Nonempty date-string vector required')
    if weighting == 'pooled':
        return np.full(len(dates), 1 / len(dates), dtype=np.float64)
    if weighting != 'equal_day':
        raise ValueError('Only equal_day and pooled endpoint weights are permitted')
    unique, inverse, counts = np.unique(dates, return_inverse=True, return_counts=True)
    return 1. / (len(unique) * counts[inverse])


def weighting_gap(daily_means, daily_counts):
    """Exact descriptive pooled-minus-equal-day gap and fixed per-date terms."""
    if not daily_means or set(daily_means) != set(daily_counts):
        raise ValueError('Matching nonempty date-keyed mean/count mappings required')
    dates = sorted(daily_means)
    means = np.asarray([daily_means[day] for day in dates], dtype=np.float64)
    counts = np.asarray([daily_counts[day] for day in dates], dtype=np.float64)
    if (not np.isfinite(means).all() or not np.isfinite(counts).all()
            or np.any(counts <= 0) or np.any(counts != np.floor(counts))):
        raise ValueError('Every fixed date requires a finite mean and positive integer count')
    n = float(counts.sum())
    if not np.isfinite(n):
        raise ValueError('Total count must be finite')
    pooled_weights, equal_weight = counts / n, 1 / len(dates)
    pooled, equal = float(np.dot(pooled_weights, means)), float(means.mean())
    contributions = (pooled_weights - equal_weight) * means
    per_date = {day: {'n': int(counts[k]), 'mean_loss': float(means[k]),
                     'pooled_weight': float(pooled_weights[k]), 'equal_day_weight': equal_weight,
                     'contribution': float(contributions[k])} for k, day in enumerate(dates)}
    return {'status': 'evaluable', 'pooled': pooled, 'equal_day': equal, 'gap': pooled - equal,
            'per_date': per_date, 'reconciliation_residual': float(pooled - equal - contributions.sum())}
