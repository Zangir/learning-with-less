"""Rehydrate accepted P1 arrays without source parsing, preprocessing fits or models."""
from hashlib import sha256
from pathlib import Path
from time import perf_counter
import json

import numpy as np
from t016_p1 import features

SOURCE = (Path(__file__).resolve().parents[2] / 'runtime')
MANIFEST_SHA = '15e90836cc3d4a6086b1c359331c66cf303ce95e37295dd3e3546ffac42b9d64'
PROTOCOL_SHA = '9017958555471c87c1c572233682506d1c69a03353bb9ad6b514b18827b31702'
CLASS_NAMES = ('F', 'A', 'N')
CLASS_CODES = {name: index for index, name in enumerate(CLASS_NAMES)}
NS = 1_000_000_000


def _file_hash(path):
    digest = sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def _stable(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def load_cohort(source=SOURCE):
    """Load the exact frozen packet; an optional path permits a relocated byte-identical copy.

    Returned event arrays preserve accepted day/file order, including January and
    censored rows. Only ``downstream_mask`` selects the 3,724 C/P/R rows. Auxiliary
    arrays preserve the independent pre-future-support pool; no learned transform
    is applied here. This function writes nothing and never opens a live source.
    """
    started = perf_counter()
    source = Path(source).resolve()
    manifest_path = source / 'artifact-manifest.json'
    _require(_file_hash(manifest_path) == MANIFEST_SHA, 'Frozen R027 manifest identity differs')
    manifest = json.loads(manifest_path.read_text(encoding='utf-8-sig'))
    members = {entry['path'].replace('\\', '/'): entry for entry in manifest['files']}
    _require(len(members) == len(manifest['files']), 'Duplicate packet member paths')
    inspected = {}

    def bound(name):
        path = (source / name).resolve()
        path.relative_to(source)
        expected = members[name]
        actual = _file_hash(path)
        _require(actual == expected['sha256'], 'Frozen input hash differs: ' + name)
        _require(path.stat().st_size == expected['size_bytes'], 'Frozen input size differs: ' + name)
        inspected[name] = {'path': str(path), 'sha256': actual, 'size_bytes': expected['size_bytes']}
        return path

    def read(name):
        return json.loads(bound(name).read_text(encoding='utf-8-sig'))

    def lines(name):
        with bound(name).open(encoding='utf-8-sig') as stream:
            return [json.loads(line) for line in stream if line.strip()]

    protocol = read('cohort-protocol.json')
    _require(inspected['cohort-protocol.json']['sha256'] == PROTOCOL_SHA, 'Wrong cohort protocol')
    identities, readiness, summary = [read(name + '.json') for name in ('code-identity', 'comparison-readiness', 'cohort-summary')]
    helper = Path(features.__file__).resolve()
    helper_identity = next(r['sha256'] for r in identities['files'] if r['path'].replace('\\', '/') == 't016_p1/features.py')
    _require(_file_hash(helper) == helper_identity, 'Accepted view helper bytes differ')
    schema = protocol['schema']
    for name, actual in (('X', features.X_NAMES), ('Z_extra_history', features.Z_NAMES),
                         ('auxiliary_inputs', features.AUX_INPUT_NAMES), ('auxiliary_targets', features.TARGET_NAMES)):
        _require(schema[name] == actual, 'Accepted schema order differs: ' + name)
    _require((len(schema['X']), len(schema['Z_extra_history']), len(schema['auxiliary_inputs'])) == (446, 1464, 440), 'Wrong matrix widths')
    dates = [f'2025-{month:02d}-01' for month in range(1, 8)]
    _require(protocol['dates'] == summary['dates'] == dates, 'Changed date scope')
    events, labels, population, auxiliary_records = [], [], [], []
    x_rows, z_rows, target_rows, auxiliary_event_indices, event_to_auxiliary = [], [], [], [], []
    for date in dates:
        prefix = date + '/'
        day_events, day_labels, day_population = [lines(prefix + name + '.jsonl') for name in ('events', 'labels', 'population')]
        levels = {row['anchor_ns']: row for row in lines(prefix + 'levels.jsonl')}
        day_aux = lines(prefix + 'auxiliary-current-targets.jsonl')
        checks = read(prefix + 'checks.json')
        event_ids = [row['event_id'] for row in day_events]
        _require(event_ids == [r['event_id'] for r in day_labels] == [r['event_id'] for r in day_population], date + ': row order differs')
        _require(len(set(event_ids)) == len(event_ids), date + ': duplicate event IDs')
        _require(all(a['decision_ns'] <= b['decision_ns'] for a, b in zip(day_events, day_events[1:])), date + ': nonchronological events')
        contract = next(member for member in protocol['contracts'] if member['date'] == date)
        day_digests = [sha256() for _ in range(3)]
        cut_to_event = {}
        with np.load(bound(prefix + 'cuts.npz'), allow_pickle=False) as archive:
            cuts = {name: archive[name] for name in archive.files}
        for event, label, member in zip(day_events, day_labels, day_population):
            index = len(events)
            lo, hi, decision = event['feature_cut_index_start'], event['feature_cut_index_stop'], event['decision_cut_index']
            _require(hi - lo == 61 and hi == decision + 1 and int(cuts['cut_ns'][decision]) == event['decision_ns'], 'Invalid 61-cut history')
            _require(int(cuts['cut_ns'][lo]) == event['decision_ns'] - 60 * NS, 'Incorrect first feature cut')
            _require(np.all(cuts['valid_depth'][lo:hi]) and np.all(cuts['segment_id'][lo:hi] == event['segment_id']), 'Invalid past feature support')
            _require(np.all(cuts['event_ns'][lo:hi] <= cuts['cut_ns'][lo:hi]), 'Future source row in feature history')
            _require(event['contract_sha256'] == contract['contract_sha256'] and event['cohort_protocol_sha256'] == PROTOCOL_SHA, 'Event source/protocol binding differs')
            _require(event['source_id'] == f'tardis-hyperliquid-{date}-btc', 'Wrong date/source join')
            _require(member['shared_arms'] == ['C', 'P', 'R'] and member['role'] == protocol['roles'][date], 'Changed arm population/role')
            _require(member['label'] == label['label'] and member['family'] == label['family'] == event['family'], 'Label/family join differs')
            _require(label['complete_future_support'] == (label['label'] is not None), 'Censor/label inconsistency')
            _require(not member['matched_eligible'] or label['label'] in CLASS_NAMES, 'Matched row lacks F/A/N label')
            x, z, target = features.views(cuts['book_units8_counts'][lo:hi], cuts['age_ns'][lo:hi],
                                          event['decision_ns'], levels[event['anchor_ns']], event)
            _require((x.shape, z.shape, target.shape) == ((446,), (1464,), (7,)), 'Rehydrated view shape differs')
            _require(all(np.isfinite(values).all() for values in (x, z, target)), 'Nonfinite rehydrated feature')
            _require(sha256(x.tobytes()).hexdigest() == event['feature_vector_sha256'], 'Saved X hash differs')
            _require(sha256(z.tobytes()).hexdigest() == event['Z_vector_sha256'], 'Saved Z hash differs')
            for digest, values in zip(day_digests, (x, z, target)):
                digest.update(values.tobytes())
            key = event['decision_ns']
            if key in cut_to_event:
                previous = cut_to_event[key]
                _require(np.array_equal(x[:440], x_rows[previous][:440]) and np.array_equal(target, target_rows[previous]), 'Duplicate auxiliary cut differs')
            else:
                cut_to_event[key] = index
            events.append(event); labels.append(label); population.append(member)
            x_rows.append(x); z_rows.append(z); target_rows.append(target)
        _require([r['decision_ns'] for r in day_aux] == list(cut_to_event), date + ': auxiliary pool changed/order differs')
        cut_to_auxiliary = {}
        for record in day_aux:
            index = cut_to_event[record['decision_ns']]
            event = events[index]
            _require(record['date'] == date and record['source_id'] == event['source_id']
                     and record['source_ordinal'] == event['decision_source_ordinal'], 'Auxiliary source join differs')
            _require(record['cut_index'] == event['decision_cut_index'] and record['dependency_max_ns'] == event['decision_ns']
                     and record['dependency_min_ns'] <= event['decision_ns'] - 60 * NS, 'Auxiliary past/current dependency differs')
            _require(record['population'] == 'past-only, before future support', 'Auxiliary pool includes future filtering')
            _require(sha256(x_rows[index][:440].tobytes()).hexdigest() == record['input_sha256'], 'Saved auxiliary input hash differs')
            _require(np.array_equal(np.asarray(record['target'], dtype='<f8'), target_rows[index]), 'Saved current target differs')
            cut_to_auxiliary[record['decision_ns']] = len(auxiliary_records)
            auxiliary_records.append(record); auxiliary_event_indices.append(index)
        event_to_auxiliary.extend(cut_to_auxiliary[event['decision_ns']] for event in day_events)
        for digest, key in zip(day_digests, ('X_hash_in_event_order', 'Z_hash_in_event_order', 'auxiliary_target_hash_in_event_order')):
            _require(digest.hexdigest() == checks[key], date + ': aggregate vector hash differs')
        _require(len(day_aux) == checks['auxiliary_deduplicated_cuts'], date + ': auxiliary count differs')
        del cuts
    _require(population == lines('matched-population.jsonl'), 'Global population differs from day order')
    _require(_stable(population) == readiness['common_population_sha256'], 'Global matched-population hash differs')
    event_ids = np.asarray([r['event_id'] for r in events])
    _require(len(set(event_ids.tolist())) == len(events), 'Cross-day duplicate event IDs')
    y = np.asarray([CLASS_CODES[r['label']] if r['label'] is not None else -1 for r in labels], dtype=np.int8)
    role_array = np.asarray([r['role'] for r in population])
    matched = np.asarray([r['matched_eligible'] for r in population], dtype=np.bool_)
    downstream = matched & (role_array != 'auxiliary_warmup')
    _require(len(events) == summary['total_recorded'] == 4160 and int((y < 0).sum()) == summary['total_censored'] == 21, 'Accepted full event/censor counts differ')
    _require(len(auxiliary_records) == 4160 and int(downstream.sum()) == 3724, 'Accepted auxiliary/downstream population differs')
    for detail in readiness['adequacy']:
        for role, expected in detail['roles'].items():
            selected = [r for r in population if r['family'] == detail['family'] and r['role'] == role and r['matched_eligible']]
            _require(_stable([r['event_id'] for r in selected]) == expected['ordered_population_sha256'], 'Role/family population hash differs')
            _require(len(selected) == expected['rows'], 'Role/family row count differs')
    x = np.stack(x_rows); z = np.stack(z_rows); targets = np.stack(target_rows)
    aux_indices = np.asarray(auxiliary_event_indices, dtype=np.int64)
    examples = read('actual-examples.json')
    may_labels = lines('accepted-may-hour-labels.jsonl')
    may_examples = {}
    for row in may_labels:
        may_examples.setdefault(row['family'], row['event_id'])
    for name, record in inspected.items():
        _require(_file_hash(source / name) == record['sha256'], 'Input changed during rehydration: ' + name)
    return {'X': x, 'Z': z, 'targets': targets, 'auxiliary_X': x[:, :440], 'y': y,
            'event_ids': event_ids, 'dates': np.asarray([r['date'] for r in population]),
            'families': np.asarray([r['family'] for r in population]), 'roles': role_array,
            'decision_ns': np.asarray([r['decision_ns'] for r in events], dtype=np.int64),
            'matched': matched, 'downstream_mask': downstream, 'events': events, 'labels': labels,
            'population': population, 'event_to_auxiliary_index': np.asarray(event_to_auxiliary, dtype=np.int64),
            'auxiliary': {'X': x[aux_indices, :440], 'targets': targets[aux_indices],
                          'dates': np.asarray([r['date'] for r in auxiliary_records]),
                          'decision_ns': np.asarray([r['decision_ns'] for r in auxiliary_records], dtype=np.int64),
                          'event_indices': aux_indices, 'records': auxiliary_records},
            'examples': examples, 'prior_may_hour_examples': may_examples, 'protocol': protocol,
            'metadata': {'source': str(source), 'manifest_sha256': MANIFEST_SHA, 'protocol_sha256': PROTOCOL_SHA,
                         'helper_sha256': helper_identity, 'ordered_event_ids_sha256': _stable(event_ids.tolist()),
                         'rows': len(events), 'matched_rows_including_warmup': int(matched.sum()),
                         'downstream_rows': int(downstream.sum()), 'auxiliary_rows': len(auxiliary_records),
                         'auxiliary_censored_cases': int((y[aux_indices] < 0).sum()),
                         'class_order': list(CLASS_NAMES), 'input_identities': inspected,
                         'rehydration_seconds': perf_counter() - started, 'fits': 0}}


def example_snippets(cohort):
    """Return fixed prior-example identities and feature snippets, never predictions."""
    lookup = {event_id: index for index, event_id in enumerate(cohort['event_ids'].tolist())}
    selections = [('R027:' + row['family'] + ':' + row['label_case'], row['event']['event_id'])
                  for row in cohort['examples']['examples']]
    selections += [('accepted-May-hour:first-' + family, event_id)
                   for family, event_id in cohort['prior_may_hour_examples'].items()]
    output = []
    for name, event_id in selections:
        index = lookup[event_id]
        event, label = cohort['events'][index], cohort['labels'][index]
        output.append({'name': name, 'event_id': event_id, 'row_index': index,
            'date': str(cohort['dates'][index]), 'family': str(cohort['families'][index]),
            'role': str(cohort['roles'][index]), 'matched': bool(cohort['matched'][index]),
            'downstream_eligible': bool(cohort['downstream_mask'][index]), 'label': label['label'],
            'source_id': event['source_id'], 'source_ordinal': event['decision_source_ordinal'],
            'contract_sha256': event['contract_sha256'], 'decision_ns': event['decision_ns'],
            'dependency_interval_ns': [event['dependency_min_ns'], event['dependency_max_ns']],
            'feature_sha256': event['feature_vector_sha256'], 'Z_sha256': event['Z_vector_sha256'],
            'X_first7': cohort['X'][index, :7].tolist(), 'X_current7': cohort['X'][index, 420:427].tolist(),
            'auxiliary_current_target': cohort['targets'][index].tolist(),
            'selection_expression': 'row = np.flatnonzero(cohort["event_ids"] == ' + repr(event_id) + ')[0]'})
    return output
