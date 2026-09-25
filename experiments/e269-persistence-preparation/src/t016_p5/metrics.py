"""Declared one-day profiles and strict conjunction; no sign tolerance."""
import numpy as np
from t016_p2.metrics import half_brier, CLASS_ORDER
from t016_p4.metrics import profile_loss, standardize
from t016_p5.common import METHODS, PAIRS

def sign(value):
    return 'unavailable' if value is None else ('positive' if value > 0 else 'negative' if value < 0 else 'zero')

def component(value):
    return {'value': value, 'float64_hex': None if value is None else float(value).hex(),
            'sign': sign(value), 'status': 'unavailable' if value is None else 'evaluable'}

def joint_verdict(components):
    values = [row['value'] for row in components.values() if row['status'] == 'evaluable']
    if any(v <= 0 for v in values):
        return 'contradicted_on_this_day'
    if len(values) == 3 and all(v > 0 for v in values):
        return 'holds_on_this_day_only'
    return 'unavailable'

def score_family(data, probabilities, family, weights):
    mask = (data['families'] == family) & data['matched']
    y = data['y'][mask]
    ids = data['event_ids'][mask]
    losses = {name: half_brier(y, probabilities[name][mask]) for name in METHODS}
    losses.update({name: losses[a]-losses[b] for name,(a,b) in PAIRS.items()})
    profiles = {}
    for name, values in losses.items():
        if len(y):
            row = profile_loss(y, values)
            row['raw_mean'] = float(values.mean())
            row['standardized'] = standardize(row, weights)
            row['status'] = 'evaluable'
        else:
            row = {'status':'unavailable', 'n':0, 'class_counts':dict.fromkeys(CLASS_ORDER,0),
                   'q':dict.fromkeys(CLASS_ORDER,None), 'ell':dict.fromkeys(CLASS_ORDER,None),
                   'raw_mean':None, 'total_loss':None,
                   'standardized':{'status':'unavailable','value':None,'missing_classes':list(CLASS_ORDER)}}
        row['equal_day'] = row['pooled_event'] = row['raw_mean']
        row['one_day_same_weighting'] = True
        profiles[name] = row
    import hashlib
    return {'n':len(y), 'ordered_event_ids_sha256':hashlib.sha256('\n'.join(ids).encode()).hexdigest(),
            'class_counts':dict(zip(CLASS_ORDER,np.bincount(y,minlength=3).tolist())),
            'profiles':profiles, 'missing_classes':[k for k in CLASS_ORDER if profiles['C']['class_counts'][k]==0]}, losses

def make_joint(breakout):
    p = breakout['profiles']['R-C']
    components = {'raw':component(p['raw_mean']), 'fixed_class':component(p['standardized']['value']),
                  'favorable_conditional':component(p['ell']['F'])}
    return {'components':components, 'verdict':joint_verdict(components),
            'missing_classes':breakout['missing_classes'], 'sign_tolerance':None,
            'scope':'One declared day only; pending numerical audit and independent A6 review'}
