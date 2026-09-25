"""Exact first-sampled-hit labels, separate from accepted opportunity state."""
from fractions import Fraction
from t016_p0.engine import NS


def label_event(observations, event):
    direction = event['direction']
    expected = (1 if event['side'] == 'resistance' else -1)
    if event['family'] == 'rebound':
        expected = -expected
    epsilon = Fraction(event['epsilon2']['numerator'], event['epsilon2']['denominator'])
    if direction not in (-1, 1) or direction != expected or epsilon <= 0:
        raise ValueError('Invalid frozen event direction or epsilon')
    refs, failures = [], []
    for k in range(1, 11):
        cut = event['decision_ns'] + k * NS
        point = observations.grid.get(cut, {'valid': False, 'reason': 'outside_retained_support'})
        reason = point['reason'] if not point['valid'] else None
        if reason is None and point['segment_id'] != event['segment_id']:
            reason = 'segment_change'
        ref = {'k': k, 'cut_ns': cut, 'valid': reason is None, 'reason': reason}
        for key in ('source_ordinal', 'event_ns', 'age_ns', 'segment_id', 'mid2'):
            if key in point:
                ref[key] = point[key]
        refs.append(ref)
        if reason:
            failures.append(ref)
    result = {'event_id': event['event_id'], 'decision_ns': event['decision_ns'],
              'family': event['family'], 'label': None, 'first_hit_k': None,
              'first_hit_cut_ns': None, 'complete_future_support': not failures,
              'censor_reason': failures[0]['reason'] if failures else None,
              'first_bad_cut_ns': failures[0]['cut_ns'] if failures else None,
              'future_refs': refs}
    if failures:
        return result
    # An early hit does not grant the remaining observations a day off.
    result['label'] = 'N'
    for ref in refs:
        movement = direction * (ref['mid2'] - event['decision_mid2'])
        favorable, adverse = movement >= 2 * epsilon, movement <= -epsilon
        if favorable and adverse:
            raise ValueError('Impossible simultaneous barrier hit')
        if favorable or adverse:
            result.update(label='F' if favorable else 'A', first_hit_k=ref['k'],
                          first_hit_cut_ns=ref['cut_ns'])
            break
    return result
