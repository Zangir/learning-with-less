"""Read immutable R029/R031 saved outputs; no models, inference or source access.

``input_bindings`` reads manifest metadata only. ``load_all`` is an execution
operation: call it only after the diagnosis code, inputs and protocol are frozen.
"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import numpy as np


ARTIFACTS = (Path(__file__).resolve().parents[2] / 'runtime')
PACKETS = {
    'R029': (ARTIFACTS / 'cycle-20260922-0921/frozen-R-029',
             '9b803d7598f20f8e3e17291de769731806175ec7c4088373090834a0020b8bb0'),
    'R031': (ARTIFACTS / 'cycle-20260922-1122/frozen-R-031',
             '5450d4411bbfc91451b4b60b330c23da0eec5f31fabe628dcf9c26d9083b72c0'),
}
DATES = tuple(f'2025-{month:02d}-01' for month in range(5, 12))
OLD_DATES, LATER_DATES = DATES[:3], DATES[3:]
FAMILIES = ('breakout', 'rebound')
CLASS_ORDER = ('F', 'A', 'N')
REFERENCE_NAMES = ('onehot-F', 'onehot-A', 'onehot-N', 'uniform', 'train-frequency')
PREDICTORS = ('C', 'P', 'R', *REFERENCE_NAMES)
TARGET_NAMES = ('log1p_Qb', 'log1p_Qa', 'log1p_Nb', 'log1p_Na',
                'depth_imbalance', 'Db_bps', 'Da_bps')
ROW_FIELDS = ('event_ids', 'dates', 'families', 'y', 'matched', 'decision_ns',
              'auxiliary', 'targets', 'X_current7', 'source_id', 'source_ordinal',
              'saved_index')
OLD_MEMBERS = (
    'prepared-cohort.npz', 'event-register.jsonl', 'auxiliary-predictions.npz',
    'models/auxiliary-3/predictions.npz', 'models/auxiliary-3/target-scaler.npz',
    'comparison-config.json', 'selection.json', 'reference-results.json',
    'candidate-results.json', 'comparison-summary.json', 'stage-examples.json',
    'verified-model-examples.json',
    *(f'selected-{family}-{arm}.npz' for family in FAMILIES for arm in ('C', 'P', 'R')),
)
LATER_MEMBERS = (
    'extension-protocol.json', 'evaluation-summary.json', 'verified-examples.json',
    *(f'{date}/{name}' for date in LATER_DATES for name in
      ('feature-vectors.npz', 'predictions.npz', 'prediction-identity.json',
       'events.jsonl', 'examples.json')),
)


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def input_bindings():
    """Return exact expected consumed-file identities, without opening data arrays.

    Each item has packet, absolute path, relative_path, sha256 and size_bytes.
    Manifests are themselves pinned anchors, not inferred from their directory.
    """
    bindings = []
    for packet, names in (('R029', OLD_MEMBERS), ('R031', LATER_MEMBERS)):
        root, expected = PACKETS[packet]
        root = root.resolve()
        manifest = root / 'artifact-manifest.json'
        content = manifest.read_bytes()
        _require(hashlib.sha256(content).hexdigest() == expected,
                 'Unexpected accepted manifest: ' + packet)
        entries = json.loads(content.decode('utf-8-sig'))['files']
        members = {r['path'].replace('\\', '/'): r for r in entries}
        _require(len(members) == len(entries), 'Duplicate manifest paths: ' + packet)
        bindings.append({'packet': packet, 'path': str(manifest),
                         'relative_path': 'artifact-manifest.json',
                         'sha256': expected, 'size_bytes': len(content)})
        for name in names:
            path = (root / name).resolve()
            path.relative_to(root)
            entry = members[name]
            bindings.append({'packet': packet, 'path': str(path), 'relative_path': name,
                             'sha256': entry['sha256'], 'size_bytes': entry['size_bytes']})
    return bindings


def _verify(bindings):
    for entry in bindings:
        path = Path(entry['path'])
        _require(path.stat().st_size == entry['size_bytes'], 'Frozen size differs: ' + str(path))
        digest = hashlib.sha256()
        with path.open('rb') as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(block)
        _require(digest.hexdigest() == entry['sha256'], 'Frozen bytes differ: ' + str(path))


def _json(packet, name):
    return json.loads((PACKETS[packet][0] / name).read_text(encoding='utf-8-sig'))


def _lines(packet, name):
    with (PACKETS[packet][0] / name).open(encoding='utf-8-sig') as stream:
        return [json.loads(line) for line in stream if line.strip()]


def _npz(packet, name, keys, current7=False):
    # NPZ members are lazy: the unused 1,464 depth columns stay on disk.
    with np.load(PACKETS[packet][0] / name, allow_pickle=False) as saved:
        result = {key: saved[key] for key in keys}
        if current7:
            x = saved['X']
            _require(x.ndim == 2 and x.shape[1] == 446, 'Unexpected X446 schema')
            result['X_current7'] = x[:, 420:427].copy()
    return result


def _equal(left, right, description):
    _require(np.array_equal(left, right), 'Saved-output join differs: ' + description)


def _probabilities(values, count, description):
    _require(values.shape == (count, 3), 'Probability shape differs: ' + description)
    _require(np.isfinite(values).all(), 'Nonfinite scored probabilities: ' + description)
    _require(np.all((values >= -1e-12) & (values <= 1 + 1e-12)),
             'Probabilities outside unit interval: ' + description)
    _require(np.allclose(values.sum(axis=1), 1, rtol=0, atol=1e-10),
             'Probability rows do not sum to one: ' + description)


def _references(saved):
    result = {}
    for family in FAMILIES:
        daily = saved[family]['train-frequency']['per_day']
        counts = np.array([sum(daily[date]['class_counts'][label]
                               for date in ('2025-02-01', '2025-03-01'))
                           for label in CLASS_ORDER], dtype=np.int64)
        _require(np.all(counts > 0), 'Frozen training reference lacks a class')
        result[family] = {f'onehot-{label}': np.eye(3)[i] for i, label in enumerate(CLASS_ORDER)}
        result[family].update(uniform=np.full(3, 1 / 3),
                              **{'train-frequency': counts / counts.sum()})
    return result


def _reference_rows(families, references):
    values = {name: np.empty((len(families), 3)) for name in REFERENCE_NAMES}
    _require(np.isin(families, FAMILIES).all(), 'Unexpected event family')
    for family in FAMILIES:
        for name in REFERENCE_NAMES:
            values[name][families == family] = references[family][name]
    return values


def _join_register(data, rows, date=None):
    _require(len(rows) == len(data['event_ids']), 'Event register length differs')
    for key, field in (('event_ids', 'event_id'), ('families', 'family'),
                       ('decision_ns', 'decision_ns'), ('dates', 'date')):
        _equal(data[key], np.asarray([r[field] for r in rows]), key + ' register')
    if date is None:
        _equal(data['matched'], np.asarray([r['matched_eligible'] for r in rows]), 'register mask')
        labels = np.array([CLASS_ORDER.index(r['label']) if r['label'] is not None else -1
                           for r in rows])
        _equal(data['y'], labels, 'register labels')
    data['source_id'] = np.asarray([r['source_id'] for r in rows])
    data['source_ordinal'] = np.asarray([r['decision_source_ordinal'] for r in rows], dtype=np.int64)
    data['metadata'] = rows


def _old_days(references):
    keys = ('event_ids', 'dates', 'families', 'y', 'matched', 'decision_ns', 'targets',
            'roles', 'downstream_mask', 'event_to_auxiliary_index', 'auxiliary_event_indices')
    data = _npz('R029', 'prepared-cohort.npz', keys, current7=True)
    count = len(data['event_ids'])
    data['saved_index'] = np.arange(count, dtype=np.int64)
    _join_register(data, _lines('R029', 'event-register.jsonl'))
    unique = data['auxiliary_event_indices']
    inverse = data['event_to_auxiliary_index']
    _require(unique.ndim == inverse.ndim == 1 and len(inverse) == count,
             'Frozen auxiliary mapping dimensions differ')
    _require(np.issubdtype(unique.dtype, np.integer) and np.issubdtype(inverse.dtype, np.integer),
             'Frozen auxiliary mapping is not integer')
    _require(np.all((unique >= 0) & (unique < count)) and len(set(unique.tolist())) == len(unique),
             'Frozen auxiliary representatives are invalid')
    _require(np.all((inverse >= 0) & (inverse < len(unique))), 'Frozen auxiliary inverse is invalid')
    _equal(inverse[unique], np.arange(len(unique)), 'auxiliary representative inverse')
    for key in ('dates', 'decision_ns', 'targets', 'X_current7'):
        _equal(data[key][unique][inverse], data[key], 'auxiliary mapping ' + key)
    full = _npz('R029', 'auxiliary-predictions.npz',
                ('predictions', 'fold', 'auxiliary_event_indices', 'dates'))
    final = _npz('R029', 'models/auxiliary-3/predictions.npz',
                 ('auxiliary_indices', 'common_coordinates', 'true_target', 'dates'))
    _equal(full['auxiliary_event_indices'], unique, 'saved auxiliary representatives')
    _equal(full['dates'], data['dates'][unique], 'saved auxiliary dates')
    final_indices = final['auxiliary_indices']
    expected_final = np.flatnonzero(np.isin(data['dates'][unique], ('2025-04-01', *OLD_DATES)))
    _equal(final_indices, expected_final, 'final auxiliary prediction population')
    _equal(final['dates'], data['dates'][unique][final_indices], 'final auxiliary dates')
    _equal(final['true_target'], data['targets'][unique][final_indices], 'final auxiliary targets')
    _equal(final['common_coordinates'], full['predictions'][final_indices], 'final auxiliary estimates')
    _require(np.all(full['fold'][final_indices] == 2), 'Final auxiliary fold is not frozen fold 3')
    estimates = np.full((len(unique), 7), np.nan)
    estimates[final_indices] = final['common_coordinates']
    data['auxiliary'] = estimates[inverse]
    data['probs'] = {arm: np.full((count, 3), np.nan) for arm in ('C', 'P', 'R')}
    for family in FAMILIES:
        expected = np.flatnonzero(data['downstream_mask'] & (data['families'] == family))
        for arm in ('C', 'P', 'R'):
            selected = _npz('R029', f'selected-{family}-{arm}.npz',
                            ('event_indices', 'probabilities'))
            _equal(selected['event_indices'], expected, family + arm + ' selected event indices')
            _probabilities(selected['probabilities'], len(expected), family + arm)
            data['probs'][arm][expected] = selected['probabilities']
    data['probs'].update(_reference_rows(data['families'], references))
    days = {}
    for date in OLD_DATES:
        mask = data['dates'] == date
        _require(np.all(data['roles'][mask] == 'descriptive_evaluation'), 'Unexpected old date role')
        _equal(data['matched'][mask], data['downstream_mask'][mask], 'old scored mask')
        day = {key: data[key][mask] for key in ROW_FIELDS}
        day['probs'] = {name: values[mask] for name, values in data['probs'].items()}
        day['metadata'] = [row for row, include in zip(data['metadata'], mask) if include]
        day['saved_index_kind'] = 'R029 prepared-cohort global row'
        days[date] = day
    return days


def _later_day(date, references, bindings, protocol):
    keys = ('event_ids', 'families', 'y', 'matched', 'decision_ns', 'targets')
    data = _npz('R031', f'{date}/feature-vectors.npz', keys, current7=True)
    prediction = _npz('R031', f'{date}/predictions.npz',
                      ('event_ids', 'families', 'labels', 'matched', 'decision_ns',
                       'auxiliary', *PREDICTORS))
    for key in ('event_ids', 'families', 'matched', 'decision_ns'):
        _equal(data[key], prediction[key], date + ' prediction ' + key)
    _equal(data['y'], prediction['labels'], date + ' prediction labels')
    count = len(data['event_ids'])
    data.update(dates=np.full(count, date), auxiliary=prediction['auxiliary'],
                saved_index=np.arange(count, dtype=np.int64),
                saved_index_kind='R031 ' + date + ' event row')
    data['probs'] = {name: prediction[name] for name in PREDICTORS}
    expected = _reference_rows(data['families'], references)
    for name in REFERENCE_NAMES:
        _equal(prediction[name], expected[name], date + ' fixed reference ' + name)
    _join_register(data, _lines('R031', f'{date}/events.jsonl'), date=date)
    identity = _json('R031', f'{date}/prediction-identity.json')
    _require(identity['class_order'] == list(CLASS_ORDER), 'Later class order differs')
    _require(identity['objects'] == protocol['objects_and_references'], 'Later object identity differs')
    for field, name in (('features_sha256', f'{date}/feature-vectors.npz'),
                        ('predictions_sha256', f'{date}/predictions.npz'),
                        ('protocol_sha256', 'extension-protocol.json')):
        _require(identity[field] == bindings[('R031', name)]['sha256'], 'Later identity binding differs')
    return data


def _validate_day(date, data):
    count = len(data['event_ids'])
    _require(count > 0 and all(len(data[key]) == count for key in ROW_FIELDS), 'Missing or ragged day')
    _require(len(set(data['event_ids'].tolist())) == count, 'Duplicate event ID in day')
    _require(data['matched'].dtype == np.bool_, 'Matched mask is not saved boolean data')
    _require(np.issubdtype(data['y'].dtype, np.integer), 'Labels are not integers')
    _require(np.isin(data['y'], (-1, 0, 1, 2)).all(), 'Unexpected label code')
    _require(np.all(data['y'][data['matched']] >= 0), 'Censored event entered scored population')
    _require(np.isin(data['families'], FAMILIES).all(), 'Unexpected family')
    _require(np.all(np.diff(data['decision_ns']) >= 0), 'Recorded event order changed')
    start = int(datetime.fromisoformat(date).replace(tzinfo=timezone.utc).timestamp()) * 10**9
    _require(np.all((data['decision_ns'] >= start) & (data['decision_ns'] < start + 86400 * 10**9)),
             'Decision outside saved date')
    _require(np.all(data['dates'] == date), 'Date array differs')
    for key in ('auxiliary', 'targets', 'X_current7'):
        _require(data[key].shape == (count, 7) and np.isfinite(data[key]).all(), 'Invalid ' + key)
    _require(tuple(data['probs']) == PREDICTORS, 'Predictor set or order differs')
    for name in PREDICTORS:
        _probabilities(data['probs'][name][data['matched']], int(data['matched'].sum()), date + name)
        if date in OLD_DATES and name in ('C', 'P', 'R'):
            _require(np.isnan(data['probs'][name][~data['matched']]).all(),
                     'Invented old unscored probabilities')
        else:
            _probabilities(data['probs'][name], count, date + ' all recorded ' + name)


def _populations(days):
    pool = {key: [] for key in ('event_ids', 'dates', 'decision_ns', 'auxiliary', 'targets', 'X_current7')}
    pool.update(member_event_ids=[], matched_event_ids=[])
    scored = {key: [] for key in (*ROW_FIELDS, 'auxiliary_index')}
    scored['probs'] = {name: [] for name in PREDICTORS}
    offset = 0
    for date, data in days.items():
        _, first, inverse = np.unique(data['decision_ns'], return_index=True, return_inverse=True)
        data['auxiliary_mask'] = np.zeros(len(data['event_ids']), dtype=bool)
        data['auxiliary_mask'][first] = True
        data['dedup_index'], data['auxiliary_index'] = inverse, inverse + offset
        for key in ('auxiliary', 'targets', 'X_current7'):
            _equal(data[key][first][inverse], data[key], date + ' same-cut ' + key)
        for key in ('event_ids', 'dates', 'decision_ns', 'auxiliary', 'targets', 'X_current7'):
            pool[key].append(data[key][first])
        for index in range(len(first)):
            member = inverse == index
            pool['member_event_ids'].append(data['event_ids'][member].tolist())
            pool['matched_event_ids'].append(data['event_ids'][member & data['matched']].tolist())
        mask = data['matched']
        for key in (*ROW_FIELDS, 'auxiliary_index'):
            scored[key].append(data[key][mask])
        for name in PREDICTORS:
            scored['probs'][name].append(data['probs'][name][mask])
        offset += len(first)
    for key in ('event_ids', 'dates', 'decision_ns', 'auxiliary', 'targets', 'X_current7'):
        pool[key] = np.concatenate(pool[key])
    for key in (*ROW_FIELDS, 'auxiliary_index'):
        scored[key] = np.concatenate(scored[key])
    scored['probs'] = {name: np.concatenate(parts) for name, parts in scored['probs'].items()}
    _require(len(set(scored['event_ids'].tolist())) == len(scored['event_ids']), 'Cross-date duplicate event ID')
    return scored, pool


def _examples(days):
    examples = []
    for date, data in days.items():
        for family in FAMILIES:
            indices = np.flatnonzero(data['matched'] & (data['families'] == family))
            _require(len(indices) > 0, 'Fixed first-scored example is unavailable')
            index = min(indices, key=lambda i: (int(data['decision_ns'][i]), str(data['event_ids'][i])))
            examples.append({
                'date': date, 'family': family, 'event_id': str(data['event_ids'][index]),
                'decision_ns': int(data['decision_ns'][index]), 'matched': True,
                'selection': 'First scored event per family/date, ordered by decision_ns then event_id',
                'y': int(data['y'][index]), 'label': CLASS_ORDER[int(data['y'][index])],
                'saved_index': int(data['saved_index'][index]), 'saved_index_kind': data['saved_index_kind'],
                'source_id': str(data['source_id'][index]), 'source_ordinal': int(data['source_ordinal'][index]),
                'X_current7': data['X_current7'][index].tolist(),
                'targets': data['targets'][index].tolist(), 'auxiliary': data['auxiliary'][index].tolist(),
                'probabilities': {name: data['probs'][name][index].tolist() for name in PREDICTORS},
                'saved_event_metadata': data['metadata'][index],
            })
    return examples


def load_all():
    """Verify and join seven fixed days after execution freeze; perform no scoring.

    Daily rows retain recorded order and unscored events. Old C/P/R cells absent
    from the frozen selected outputs stay NaN. ``scored`` contains matched rows
    only, with eight identically aligned probability matrices. ``auxiliary_pool``
    includes every unique date/decision cut, even future-censored cuts; its event
    IDs are representatives, while member lists preserve all event relationships.
    Daily ``dedup_index`` is local; ``auxiliary_index`` addresses the global pool.
    """
    bindings = input_bindings()
    _verify(bindings)
    by_name = {(r['packet'], r['relative_path']): r for r in bindings}
    config = _json('R029', 'comparison-config.json')
    _require(config['accepted_proposal']['class_order'] == list(CLASS_ORDER), 'Old class order differs')
    _require(config['schema']['P'][446:] == ['predicted.' + name for name in TARGET_NAMES],
             'Frozen target coordinates differ')
    reference_results = _json('R029', 'reference-results.json')
    references = _references(reference_results)
    scaler = _npz('R029', 'models/auxiliary-3/target-scaler.npz', ('means', 'scales'))
    _require(scaler['means'].shape == scaler['scales'].shape == (7,), 'Target scaler shape differs')
    _require(np.isfinite(scaler['means']).all() and np.isfinite(scaler['scales']).all()
             and np.all(scaler['scales'] > 0), 'Invalid frozen target scaler')
    protocol = _json('R031', 'extension-protocol.json')
    identity = protocol['objects_and_references']
    _require(identity['manifest_sha256'] == PACKETS['R029'][1], 'Later objects use another packet')
    _require(identity['auxiliary']['target_scaler']['sha256'] ==
             by_name[('R029', 'models/auxiliary-3/target-scaler.npz')]['sha256'],
             'Later target scaler differs from the saved training mean')
    for family in FAMILIES:
        frozen = identity['references'][family]
        _require(frozen['training_dates'] == ['2025-02-01', '2025-03-01'], 'Reference training dates differ')
        for name in REFERENCE_NAMES:
            _equal(np.asarray(frozen['probabilities'][name]), references[family][name], 'reference identity')
    days = _old_days(references)
    for date in LATER_DATES:
        days[date] = _later_day(date, references, by_name, protocol)
    _require(tuple(days) == DATES, 'The seven fixed date slots changed')
    for date, data in days.items():
        _validate_day(date, data)
    scored, pool = _populations(days)
    return {
        'days': days, 'scored': scored, 'auxiliary_pool': pool, 'references': references,
        'target_training_mean': scaler['means'], 'target_training_scales': scaler['scales'],
        'examples': _examples(days), 'class_order': list(CLASS_ORDER), 'target_names': list(TARGET_NAMES),
        'original_examples': {
            'R029_stage': _json('R029', 'stage-examples.json'),
            'R029_verified': _json('R029', 'verified-model-examples.json'),
            'R031_verified': _json('R031', 'verified-examples.json'),
            'R031_days': {date: _json('R031', date + '/examples.json') for date in LATER_DATES},
        },
        'accepted_summaries': {
            'R029_reference_results': reference_results,
            'R029_candidate_results': _json('R029', 'candidate-results.json'),
            'R029_comparison_summary': _json('R029', 'comparison-summary.json'),
            'R029_selection': _json('R029', 'selection.json'),
            'R031_evaluation_summary': _json('R031', 'evaluation-summary.json'),
        },
        'bindings': bindings,
    }
