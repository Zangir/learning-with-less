"""Indexed, deterministic X/Z views and current auxiliary targets; no fit calls."""
import math
import numpy as np
from t016_p0.engine import NS

HISTORY_FIELDS = ['bid_offset_bps', 'ask_offset_bps', 'log1p_bid_btc', 'log1p_ask_btc',
                  'log1p_bid_count', 'log1p_ask_count', 'asof_age_seconds']
COMMON_FIELDS = ['utc_sin', 'utc_cos', 'grid_seconds', 'max_asof_age_seconds',
                 *[f'return_{lag}s_bps' for lag in (1, 5, 10, 30, 60)],
                 'bbo_imbalance', 'spread_bps', 'freshness', 'return_1s_population_std_bps']
EVENT_FIELDS = ['resistance_distance_bps', 'support_distance_bps', 'epsilon_bps',
                'is_resistance', 'is_breakout', 'is_rebound']
X_NAMES = [f'lag{lag}.{field}' for lag in range(60, -1, -1) for field in HISTORY_FIELDS] + COMMON_FIELDS + EVENT_FIELDS
AUX_INPUT_NAMES = X_NAMES[:-len(EVENT_FIELDS)]
Z_NAMES = [f'lag{lag}.{side}{level}.{field}' for lag in range(60, -1, -1)
           for side in ('bid', 'ask') for level in range(2, 6)
           for field in ('offset_bps', 'log1p_btc', 'log1p_count')]
TARGET_NAMES = ['log1p_Qb', 'log1p_Qa', 'log1p_Nb', 'log1p_Na', 'depth_imbalance', 'Db_bps', 'Da_bps']
RAW_BOOK_FIELDS = [f'{side}.{field}.{level}' for side in ('bid', 'ask')
                   for field in ('price_units8', 'size_units8', 'count') for level in range(1, 6)]


def raw_book(row):
    return [v for side in ('bid', 'ask') for key in ('prices_units8', 'sizes_units8', 'counts')
            for v in row[side + '_' + key][:5]]


def views(history_books, ages_ns, decision_ns, level, event):
    """The caller supplies exactly61 past/current rows; no label/mask parameter exists."""
    b = np.asarray(history_books, dtype=np.float64).reshape(61, 2, 3, 5)
    ages = np.asarray(ages_ns, dtype=np.float64)
    assert ages.shape == (61,) and np.all((ages >= 0) & (ages <= 1.5 * NS))
    prices, sizes, counts = b[:, :, 0, :] / 1e8, b[:, :, 1, :] / 1e8, b[:, :, 2, :]
    assert np.all(prices > 0) and np.all(sizes > 0) and np.all(counts > 0)
    mids = (prices[:, 0, 0] + prices[:, 1, 0]) / 2
    current = mids[-1]
    coarse = np.column_stack((10000 * (prices[:, 0, 0] / current - 1),
        10000 * (prices[:, 1, 0] / current - 1), np.log1p(sizes[:, 0, 0]),
        np.log1p(sizes[:, 1, 0]), np.log1p(counts[:, 0, 0]), np.log1p(counts[:, 1, 0]), ages / NS))
    phase = (decision_ns // NS % 86400) * 2 * math.pi / 86400
    common = [math.sin(phase), math.cos(phase), 1., 1.5,
        *[10000 * (current / mids[-1-lag] - 1) for lag in (1, 5, 10, 30, 60)],
        (sizes[-1, 0, 0]-sizes[-1, 1, 0])/(sizes[-1, 0, 0]+sizes[-1, 1, 0]),
        10000*(prices[-1, 1, 0]-prices[-1, 0, 0])/current,
        1-ages[-1]/(1.5*NS), np.std(10000*(mids[1:]/mids[:-1]-1), ddof=0)]
    eps = level['epsilon2']['numerator'] / level['epsilon2']['denominator'] / 2e8
    contextual = [10000*(current-level[key]/2e8)/current for key in ('resistance_mid2', 'support_mid2')]
    contextual += [10000*eps/current, float(event['side']=='resistance'),
                   float(event['family']=='breakout'), float(event['family']=='rebound')]
    x = np.concatenate((coarse.ravel(), common, contextual)).astype('<f8')
    z = np.stack((10000*(prices[:, :, 1:]/current-1), np.log1p(sizes[:, :, 1:]),
                  np.log1p(counts[:, :, 1:])), axis=-1).ravel().astype('<f8')
    q = sizes[-1, :, 1:].sum(axis=1)
    n = counts[-1, :, 1:].sum(axis=1)
    distances = np.array([current-prices[-1, 0, 1:], prices[-1, 1, 1:]-current])*10000/current
    weighted = (sizes[-1, :, 1:]*distances).sum(axis=1)/q
    target = np.array([*np.log1p(q), *np.log1p(n), (q[0]-q[1])/(q[0]+q[1]), *weighted], dtype='<f8')
    assert len(x)==len(X_NAMES) and len(z)==len(Z_NAMES)
    assert all(np.isfinite(a).all() for a in (x,z,target))
    return x, z, target


def inverse_target_scaling(predictions, means, scales):
    """L1 coordinates stay log-size/log-count and raw imbalance/distance after inversion."""
    return np.asarray(means) + np.asarray(scales) * np.asarray(predictions)


def embed_coarse_coefficients(coefficients, rich_width):
    coefficients = np.asarray(coefficients)
    if rich_width < coefficients.shape[-1]:
        raise ValueError('Rich layout must include every coarse column')
    result = np.zeros((*coefficients.shape[:-1], rich_width), dtype=coefficients.dtype)
    result[..., :coefficients.shape[-1]] = coefficients
    return result


def readiness_reason(event, partition_start, partition_end, earlier_dependency_end=None):
    if event['dependency_min_ns'] < partition_start or event['dependency_max_ns'] >= partition_end:
        return 'dependency_crosses_partition'
    if earlier_dependency_end is not None and event['dependency_min_ns'] - earlier_dependency_end < 130 * NS:
        return 'dependency_embargo_130s'
    return None
