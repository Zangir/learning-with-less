"""Proper scores, fixed references and full-menu one-time selection."""
import numpy as np

CLASS_ORDER = ('F', 'A', 'N')


def encode_labels(y):
    values = np.asarray(y)
    if values.ndim != 1:
        raise ValueError('Labels must be a vector')
    if values.dtype.kind in 'OUS':
        try:
            encoded = np.array([CLASS_ORDER.index(str(v)) for v in values], dtype=np.int64)
        except ValueError as exc:
            raise ValueError('Only F/A/N labels are evaluable') from exc
    else:
        if not np.isfinite(values).all() or not np.isin(values, (0, 1, 2)).all():
            raise ValueError('Only encoded F/A/N labels are evaluable')
        encoded = values.astype(np.int64)
    return encoded


def align_probabilities(proba, classes):
    classes = encode_labels(classes)
    p = np.asarray(proba, dtype=np.float64)
    if len(classes) != 3 or set(classes) != {0, 1, 2} or p.ndim != 2 or p.shape[1] != 3:
        raise ValueError('All three classes must occur exactly once')
    p = p[:, [int(np.flatnonzero(classes == k)[0]) for k in range(3)]]
    if not np.isfinite(p).all() or np.any(p < 0) or np.any(p > 1):
        raise ValueError('Probabilities must be finite and inside [0,1]')
    if not np.allclose(p.sum(axis=1), 1, rtol=0, atol=1e-12):
        raise ValueError('Probability rows must sum to one without repair')
    return p


def half_brier(y, proba):
    y = encode_labels(y)
    p = align_probabilities(proba, (0, 1, 2))
    if len(y) != len(p):
        raise ValueError('Rows and labels must align')
    return .5 * np.square(p - np.eye(3)[y]).sum(axis=1)


def score_by_day(y, proba, dates):
    y = encode_labels(y)
    p = align_probabilities(proba, (0, 1, 2))
    losses = half_brier(y, p)
    dates = np.asarray(dates)
    if len(dates) != len(y) or not len(y):
        raise ValueError('A nonempty date is required for every row')
    per_day = {}
    for day in sorted(set(dates.tolist())):
        mask = dates == day
        per_day[str(day)] = {
            'n': int(mask.sum()), 'half_brier': float(losses[mask].mean()),
            'class_counts': dict(zip(CLASS_ORDER, np.bincount(y[mask], minlength=3).tolist())),
            'one_vs_rest_brier': dict(zip(CLASS_ORDER, np.square(p[mask] - np.eye(3)[y[mask]]).mean(axis=0).tolist())),
            'half_brier_by_observed_class': {name: float(losses[mask & (y == k)].mean())
                if np.any(mask & (y == k)) else None for k, name in enumerate(CLASS_ORDER)}}
    return {'per_day': per_day, 'equal_day_half_brier': float(np.mean([v['half_brier'] for v in per_day.values()]))}


def reference_predictions(train_y, n):
    y = encode_labels(train_y)
    if not len(y) or set(y) != {0, 1, 2} or n < 0:
        raise ValueError('Three training classes and a nonnegative row count required')
    constants = {f'onehot-{name}': np.eye(3)[k] for k, name in enumerate(CLASS_ORDER)}
    constants.update({'uniform': np.full(3, 1 / 3), 'train-frequency': np.bincount(y, minlength=3) / len(y)})
    return {name: np.tile(value, (n, 1)) for name, value in constants.items()}


def select_candidate(scores, menu):
    identifiers = [m['id'] if isinstance(m, dict) else m for m in menu]
    if not identifiers or any(scores.get(k) is None or not np.isfinite(scores[k]) for k in identifiers):
        return None
    # The frozen order gets the tie; floating-point near-ties do not get a vote.
    return min(identifiers, key=lambda k: scores[k])


def assert_chronological_fold(train_dates, predict_dates):
    training, prediction = sorted(set(train_dates)), sorted(set(predict_dates))
    if not training or not prediction or training[-1] >= prediction[0]:
        raise ValueError('Auxiliary training must strictly precede every predicted date')
