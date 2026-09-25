"""E271 independent source, label, frozen-prediction and score audit.
Derived source/feature checks preserve the accepted E261 audit definitions.
Explicit invocation only; this module does not execute or load models on import.
"""
from collections import Counter
from datetime import datetime, timezone
from fractions import Fraction
from hashlib import sha256
from io import BytesIO
import json
import math
from pathlib import Path
import pickle
import time
import traceback

import numpy as np
from threadpoolctl import threadpool_limits
from t016_p1 import features
from t016_p3.fixed_inference import install_fit_guards

FROZEN = (Path(__file__).resolve().parents[2] / 'runtime')
FAMILIES = ('breakout', 'rebound')
ARMS = ('C', 'P', 'R')

NS = 1_000_000_000
CLASSES = ('F', 'A', 'N')
REFERENCES = ('onehot-F', 'onehot-A', 'onehot-N', 'uniform', 'train-frequency')
CHECKS = Counter()
INPUTS = {}


def require(condition, message):
    if not condition:
        raise AssertionError(message)
    CHECKS['assertions'] += 1


def digest(path):
    h = sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def bound(path):
    path = Path(path)
    INPUTS[str(path)] = digest(path)
    return path


def read(path):
    return json.loads(bound(path).read_text(encoding='utf-8-sig'))


def rows(path):
    with bound(path).open(encoding='utf-8-sig') as stream:
        return [json.loads(line) for line in stream if line.strip()]


def arrays(path):
    with np.load(bound(path), allow_pickle=False) as archive:
        return {name: archive[name] for name in archive.files}


def stable(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def equal(actual, expected, context):
    if isinstance(expected, dict):
        require(isinstance(actual, dict) and set(actual) == set(expected), context + ': fields')
        for key in expected:
            equal(actual[key], expected[key], context + '/' + str(key))
    elif isinstance(expected, (list, tuple)):
        require(isinstance(actual, (list, tuple)) and len(actual) == len(expected), context + ': length')
        for i, (a, e) in enumerate(zip(actual, expected)):
            equal(a, e, context + '/' + str(i))
    elif isinstance(expected, (float, np.floating)):
        require(actual is not None and np.isclose(actual, expected, atol=1e-12, rtol=1e-12), context + ': value')
    else:
        require(actual == expected, context + ': value')


def exact_array(actual, expected, context):
    actual, expected = np.asarray(actual), np.asarray(expected)
    require(actual.shape == expected.shape and np.array_equal(actual, expected), context + ': array')
    if actual.dtype.kind == expected.dtype.kind == 'f':
        require(actual.dtype == expected.dtype and actual.tobytes() == expected.tobytes(), context + ': bitwise')


def normalized_source(member, cuts, dest):
    """Replay normalized files and their provenance, without raw response decoding."""
    path = Path(member['contract_file'])
    contract = read(path)
    require(INPUTS[str(path)] == member['contract_sha256'], 'Contract hash')
    directory = path.parent
    segments = read(directory / contract['continuity']['source_segments_file'])
    require(INPUTS[str(directory / contract['continuity']['source_segments_file'])]
            == contract['continuity']['source_segments_sha256'], 'Source segment metadata hash')
    require(contract['asset'] == 'BTC' and contract['date'] == member['date'], 'Contract date/asset')
    require(contract['continuity']['max_age_ns'] == 1_500_000_000
            and contract['continuity']['max_gap_ns'] == 2 * NS, 'Frozen source support rules')
    start, end = contract['selected_event_start_ns'], contract['selected_event_end_ns']
    source_id = contract['sources'][0]['source_id']
    require(source_id == member['source_id'], 'Exact declared source identity')
    state_path = bound(directory / contract['sources'][0]['file'])
    require(INPUTS[str(state_path)] == contract['sources'][0]['sha256'], 'Normalized source hash')
    times, ordinals, books, segment_ids, state_hashes = [], [], [], [], []
    source_index, segment_index = {}, 0
    with state_path.open('rb') as stream:
        for index, raw in enumerate(stream):
            row = json.loads(raw)
            while index >= segments[segment_index]['stop_row_index']:
                segment_index += 1
            segment = segments[segment_index]
            t, ordinal = row['event_ns'], row['source_ordinal']
            require(type(t) is int and type(ordinal) is int, 'Exact source time/ordinal')
            require(start <= t < end and segment['start_ns'] <= t < segment['end_ns'], 'Source period/segment')
            require(segment['first_row_index'] <= index < segment['stop_row_index'], 'Physical source segment join')
            require(row['source_id'] == source_id and row['asset'] == 'BTC', 'Source identity')
            require(row['release_ns'] is None and row['admission_evidence_ns'] is None, 'No strategy receipt calibration')
            book = [value for side in ('bid', 'ask') for field in ('prices_units8', 'sizes_units8', 'counts')
                    for value in row[side + '_' + field][:5]]
            require(len(book) == 30 and all(type(v) is int and v > 0 for v in book), 'Exact positive top-five source')
            require(all(a > b for a, b in zip(book[:4], book[1:5]))
                    and all(a < b for a, b in zip(book[15:19], book[16:20])) and book[0] < book[15], 'Source price ordering')
            if times:
                require(t > times[-1] and ordinal > ordinals[-1], 'Strict normalized source order')
                require(segment['segment_id'] != segment_ids[-1] or t - times[-1] <= 2 * NS, 'Unsegmented source gap')
            source_index[ordinal] = index
            times.append(t); ordinals.append(ordinal); books.append(book); segment_ids.append(segment['segment_id'])
            state_hashes.append(sha256(raw).hexdigest())
    require(len(times) == segments[-1]['stop_row_index'] and times[0] == contract['actual_first_event_ns']
            and times[-1] == contract['actual_last_event_ns'], 'Complete physical source rows/endpoints')
    provenance_path = bound(directory / contract['source_provenance_file'])
    require(INPUTS[str(provenance_path)] == contract['source_provenance_sha256'], 'Source provenance hash')
    provenance, epochs = {}, {}
    with provenance_path.open('rb') as stream:
        for line, raw in enumerate(stream, 1):
            item = json.loads(raw); ordinal = item['source_ordinal']
            if ordinal not in source_index:
                continue
            require(ordinal not in provenance, 'Unique normalized provenance')
            i = source_index[ordinal]
            require(item['event_ns'] == times[i], 'Source/provenance event join')
            epochs[i] = item['disconnect_epoch']
            provenance[ordinal] = {**item, 'provenance_line_1_based': line, 'provenance_line_sha256': sha256(raw).hexdigest()}
    require(len(provenance) == len(times), 'Complete normalized source provenance')
    for i in range(1, len(times)):
        require(segment_ids[i] != segment_ids[i-1] or epochs[i] == epochs[i-1], 'Unsegmented disconnect')
    expected_segments = []
    for segment in segments:
        lo, hi = segment['first_row_index'], segment['stop_row_index']
        if hi > lo:
            require(times[lo] == segment['start_ns'] and times[hi-1]+1 == segment['end_ns']
                    and ordinals[lo] == segment['first_source_ordinal']
                    and ordinals[hi-1] == segment['last_source_ordinal'], 'Exact segment endpoints/ordinals')
            expected_segments.append({'segment_id': segment['segment_id'], 'start_ns': times[lo],
                'first_source_ordinal': ordinals[lo], 'end_ns': min(times[hi-1]+1, end, segment['end_ns']),
                'last_source_ordinal': ordinals[hi-1]})
    equal(read(dest/'segments.json'), expected_segments, 'Retained source segments')
    times, ordinals, books, segment_ids = map(np.asarray, (times, ordinals, books, segment_ids))
    expected_cuts = np.arange(((start+NS-1)//NS)*NS, min(end, int(times[-1])+1), NS, dtype=np.int64)
    exact_array(cuts['cut_ns'], expected_cuts, 'Complete integer cut grid')
    index = np.searchsorted(times, expected_cuts, side='right')-1
    present = index >= 0
    for name, source in [('event_ns', times), ('source_ordinal', ordinals), ('source_row_index', np.arange(len(times))), ('segment_id', segment_ids)]:
        expected = np.full(len(index), -1, dtype=np.int64); expected[present] = source[index[present]]
        exact_array(cuts[name], expected, 'As-of ' + name)
    age = np.full(len(index), -1, dtype=np.int64); age[present] = expected_cuts[present]-times[index[present]]
    exact_array(cuts['age_ns'], age, 'As-of age')
    cut_books = np.zeros((len(index), 30), dtype=np.int64); cut_books[present] = books[index[present]]
    exact_array(cuts['book_units8_counts'], cut_books, 'Cut book/source join')
    ends = {s['segment_id']: s['end_ns'] for s in expected_segments}
    valid = np.array([i >= 0 and t < ends[int(segment_ids[i])] and t-int(times[i]) <= 1_500_000_000
                      for t, i in zip(expected_cuts, index)], dtype=bool)
    exact_array(cuts['valid_bbo'], valid, 'BBO source support')
    exact_array(cuts['valid_depth'], valid, 'Depth-five source support')
    codes = read(dest/'availability.json')['support_reason_codes']
    reasons = ['supported' if ok else ('stale_asof' if i >= 0 and t < ends[int(segment_ids[i])] else 'outside_retained_support')
               for t, i, ok in zip(expected_cuts, index, valid)]
    require([codes[int(k)] for k in cuts['support_reason_code']] == reasons, 'Cut support reason codes')
    reference = read(dest/'source-provenance-reference.json')
    require(reference['path'] == str(provenance_path.resolve())
            and reference['sha256'] == INPUTS[str(provenance_path)]
            and reference['size_bytes'] == provenance_path.stat().st_size,
            'Exact original source provenance reference')
    require(reference['source_id'] == source_id and reference['contract_sha256'] == member['contract_sha256']
            and reference['normalized_rows'] == len(times), 'Complete provenance-reference scope')
    return {'normalized_rows': len(times), 'provenance_rows': len(provenance), 'cuts': len(index),
            'valid_cuts': int(valid.sum()), 'segments': len(expected_segments), 'raw_response_replay': False}


def labels_and_features(member, dest, cuts, data, protocol_sha, previous_end, p0_sha):
    events, labels, population = [rows(dest/(name+'.jsonl')) for name in ('events', 'labels', 'population')]
    levels = {r['anchor_ns']: r for r in rows(dest/'levels.jsonl')}
    masks = rows(dest/'support-masks.jsonl')
    ids = [e['event_id'] for e in events]
    require(len(ids) == len(set(ids)) and ids == [r['event_id'] for r in labels]
            == [r['event_id'] for r in population] == [r['event_id'] for r in masks], 'Full recorded event joins')
    n = len(events)
    require(data['X'].shape == (n,446) and data['Z'].shape == (n,1464) and data['targets'].shape == (n,7), 'Feature dimensions')
    for field, values in [('event_ids', ids), ('families', [e['family'] for e in events]), ('decision_ns', [e['decision_ns'] for e in events])]:
        exact_array(data[field], np.asarray(values, dtype=data[field].dtype), 'Feature row '+field)
    day = int(datetime.fromisoformat(member['date']).replace(tzinfo=timezone.utc).timestamp())*NS
    dt = datetime.fromisoformat(member['date']).replace(tzinfo=timezone.utc)
    month_end = int(dt.replace(month=dt.month+1).timestamp())*NS
    require(all(a['decision_ns'] <= b['decision_ns'] for a,b in zip(events,events[1:])), 'Chronological event order')
    if events and previous_end is not None:
        require(min(e['dependency_min_ns'] for e in events)-previous_end >= 130*NS, 'Observed-block dependency embargo')
    lookup = {int(t): i for i,t in enumerate(cuts['cut_ns'])}
    used_levels, auxiliary, slots, last_recorded = set(), {}, set(), {}
    for j,(event,label,pop,mask) in enumerate(zip(events,labels,population,masks)):
        t, anchor = event['decision_ns'], event['anchor_ns']
        lo, hi, i = [event[k] for k in ('feature_cut_index_start','feature_cut_index_stop','decision_cut_index')]
        ll, lh = event['level_cut_index_start'], event['level_cut_index_stop']
        require(hi-lo == 61 and hi == i+1 and lookup[t] == i and int(cuts['cut_ns'][lo]) == t-60*NS, 'Exact 61-cut feature index')
        require(lh-ll == 60 and int(cuts['cut_ns'][ll]) == anchor-60*NS and int(cuts['cut_ns'][lh-1]) == anchor-NS, 'Exact frozen level cuts')
        sid = event['segment_id']; level = levels[anchor]
        require(np.all(cuts['valid_depth'][lo:hi]) and np.all(cuts['segment_id'][lo:hi] == sid)
                and np.all(cuts['event_ns'][lo:hi] <= cuts['cut_ns'][lo:hi]), 'Past-only feature support')
        require(np.all(cuts['valid_bbo'][ll:lh]) and np.all(cuts['segment_id'][ll:lh] == sid), 'Past level support')
        require(event['source_id'] == member['source_id']
                and event['contract_sha256'] == member['contract_sha256']
                and event['extension_protocol_sha256'] == protocol_sha and event['date'] == member['date']
                and event['protocol_sha256'] == p0_sha, 'Event source bindings')
        require(event['family'] in FAMILIES and event['side'] in ('resistance','support'), 'Known event family/side')
        require(event['event_id'] == stable([event['protocol_sha256'],t,anchor,event['family'],event['side']]), 'Stable event ID')
        require(event['decision_source_ordinal'] == int(cuts['source_ordinal'][i]), 'Decision ordinal')
        current_mid = int(cuts['book_units8_counts'][i,0])+int(cuts['book_units8_counts'][i,15])
        require(event['decision_mid2'] == current_mid and anchor == t//(60*NS)*(60*NS), 'Decision midpoint/minute anchor')
        if anchor not in used_levels:
            mids = [int(b[0])+int(b[15]) for b in cuts['book_units8_counts'][ll:lh]]
            spreads = sorted(2*(int(b[15])-int(b[0])) for b in cuts['book_units8_counts'][ll:lh])
            epsilon = max(Fraction(mids[-1],10000), Fraction(spreads[29]+spreads[30],2))
            require(level['valid'] and level['resistance_mid2'] == max(mids) and level['support_mid2'] == min(mids)
                    and Fraction(**{k:level['epsilon2'][k] for k in ('numerator','denominator')}) == epsilon
                    and max(mids)-min(mids) >= 4*epsilon, 'Independent frozen level')
            exact_array(level['source_ordinals'], cuts['source_ordinal'][ll:lh], 'Level source ordinals')
            exact_array(level['cut_ns'], cuts['cut_ns'][ll:lh], 'Level cut times')
            used_levels.add(anchor)
        require(event['epsilon2'] == level['epsilon2'] and event['level_mid2'] == level[event['side']+'_mid2'], 'Event/level threshold join')
        history = []
        for q in range(lo,hi):
            book = cuts['book_units8_counts'][q]
            history.append({key:int(cuts[key][q]) for key in ('cut_ns','source_ordinal','event_ns','age_ns')} |
                {'bbo':[int(book[k]) for k in (0,15,5,20,10,25)]+[int(cuts['age_ns'][q])]})
        require(stable(history) == event['feature_history_sha256'], 'Exact indexed source history hash')
        x,z,target = features.views(cuts['book_units8_counts'][lo:hi],cuts['age_ns'][lo:hi],t,level,event)
        for field,array,hash_key in [('X',x,'feature_vector_sha256'),('Z',z,'Z_vector_sha256'),('targets',target,'current_target_sha256')]:
            exact_array(data[field][j], array, 'Reconstructed '+field)
            require(sha256(array.tobytes()).hexdigest() == event[hash_key], 'Recorded '+field+' vector hash')
        actual_times = cuts['event_ns'][ll:lh].tolist()+cuts['event_ns'][lo:hi].tolist()
        actual_times += [ref['event_ns'] for ref in label['future_refs'] if 'event_ns' in ref]
        dependency_min = min(anchor-60*NS,*actual_times)
        dependency_max = max(t+10*NS,*actual_times)
        require(event['dependency_min_ns'] == dependency_min and event['dependency_max_ns'] == dependency_max, 'Exact dependency union')
        outward = 1 if event['side'] == 'resistance' else -1
        direction = outward if event['family'] == 'breakout' else -outward
        require(event['direction'] == direction, 'Frozen event direction')
        num,den = event['epsilon2']['numerator'],event['epsilon2']['denominator']
        previous_mid = int(cuts['book_units8_counts'][i-1,0])+int(cuts['book_units8_counts'][i-1,15])
        before = outward*(previous_mid-event['level_mid2'])*den
        current = outward*(current_mid-event['level_mid2'])*den
        trigger = before <= num < current if event['family']=='breakout' else before < -num and -num <= current <= num
        require(trigger,'Independent recorded opportunity trigger')
        slot = (event['family'],event['side'],anchor)
        require(slot not in slots and (event['family'] not in last_recorded or t-last_recorded[event['family']]>=10*NS), 'Recorded-only slot/cooldown')
        slots.add(slot); last_recorded[event['family']] = t
        refs, failures, hits = label['future_refs'], [], []
        require(len(refs) == 10, 'Full ten-cut horizon retained after early hit')
        for k,ref in enumerate(refs,1):
            cut = t+k*NS; q = lookup.get(cut)
            reason = 'outside_retained_support' if q is None else (
                None if cuts['valid_bbo'][q] else cuts['_reason_codes'][int(cuts['support_reason_code'][q])])
            if reason is None and int(cuts['segment_id'][q]) != sid:
                reason = 'segment_change'
            require(ref['k'] == k and ref['cut_ns'] == cut and ref['valid'] == (reason is None) and ref['reason'] == reason, 'Future cut support oracle')
            if q is not None:
                for field in ('source_ordinal','event_ns','age_ns','segment_id'):
                    if int(cuts[field][q]) >= 0:
                        require(ref[field] == int(cuts[field][q]), 'Future source '+field)
                if cuts['valid_bbo'][q]:
                    mid = int(cuts['book_units8_counts'][q,0])+int(cuts['book_units8_counts'][q,15])
                    require(ref['mid2'] == mid, 'Future midpoint comes from source cut')
                    movement = direction*(mid-current_mid)*den
                    if movement >= 2*num or movement <= -num:
                        hits.append((k,'F' if movement >= 2*num else 'A'))
            if reason is not None:
                failures.append((cut,reason))
        expected_label = None if failures else (hits[0][1] if hits else 'N')
        first_hit = hits[0][0] if not failures and hits else None
        require(label['label'] == expected_label and label['first_hit_k'] == first_hit
                and label['first_hit_cut_ns'] == (t+first_hit*NS if first_hit else None), 'Independent first-hit integer label')
        for field,value in [('complete_future_support',not failures),('censor_reason',failures[0][1] if failures else None),('first_bad_cut_ns',failures[0][0] if failures else None)]:
            require(label[field] == value and mask[field] == value, 'Full horizon '+field)
        readiness = 'dependency_crosses_partition' if dependency_min < day or dependency_max >= month_end else None
        if readiness is None and previous_end is not None and dependency_min-previous_end < 130*NS:
            readiness = 'dependency_embargo_130s'
        reason = readiness
        if failures:
            reason = 'future_support:'+failures[0][1]
        require(pop['matched_eligible'] == (reason is None) and pop['exclusion'] == reason
                and pop['shared_arms'] == ['C','P','R'] and pop['label'] == expected_label
                and pop['family'] == event['family'] and pop['date'] == member['date']
                and pop['role'] == 'fixed_later_evaluation' and pop['readiness_exclusion'] == readiness
                and pop['support_exclusion'] == ('future_support:'+failures[0][1] if failures else None), 'Common C/P/R population')
        require(data['matched'][j] == (reason is None) and int(data['y'][j]) == (-1 if expected_label is None else CLASSES.index(expected_label))
                and str(data['labels'][j]) == (expected_label or ''), 'Feature label/mask vectors')
        if t in auxiliary:
            prior = auxiliary[t]
            exact_array(data['X'][prior,:440],x[:440], 'Same-cut auxiliary input deduplication')
            exact_array(data['targets'][prior],target,'Same-cut target deduplication')
        else:
            auxiliary[t] = j
    aux_records = rows(dest/'auxiliary-current-targets.jsonl')
    require([r['decision_ns'] for r in aux_records] == list(auxiliary), 'Full auxiliary pool before future filtering')
    for record in aux_records:
        j = auxiliary[record['decision_ns']]; event = events[j]
        require(record['source_id'] == event['source_id'] and record['source_ordinal'] == event['decision_source_ordinal']
                and record['cut_index'] == event['decision_cut_index'] and record['date'] == member['date'], 'Auxiliary source join')
        exact_array(np.asarray(record['target'],dtype='<f8'),data['targets'][j],'Saved auxiliary target')
        require(record['input_sha256'] == sha256(data['X'][j,:440].tobytes()).hexdigest()
                and record['dependency_max_ns'] == event['decision_ns'], 'Auxiliary input/past binding')
    checks = read(dest/'checks.json')
    for field,key in [('X','X_hash_in_event_order'),('Z','Z_hash_in_event_order'),('targets','target_hash_in_event_order')]:
        require(sha256(data[field].tobytes()).hexdigest() == checks[key], 'Aggregate feature vector hash')
    candidates = rows(dest/'candidates.jsonl'); counts = read(dest/'counts.json')
    for family in FAMILIES:
        group = [r for r in candidates if r['family']==family]
        recorded = [r for r in events if r['family']==family]
        record = next(r for r in counts if r['family']==family)
        require(record['recorded'] == len(recorded) and record['raw_candidates'] == len(group)
                and record['rejected']+record['recorded'] == len(group), 'Candidate/recorded reconciliation')
        equal(record['classes'],{name:sum(r['family']==family and r['label']==name for r in labels) for name in CLASSES}, 'Class reconciliation')
        require(record['censored'] == sum(r['family']==family and r['label'] is None for r in labels)
                and record['matched_rows'] == int(((data['families']==family)&data['matched']).sum()), 'Censor/matched reconciliation')
    return events, {'recorded_events': n, 'matched': int(data['matched'].sum()), 'censored': int((data['y']<0).sum()),
                    'deduplicated_past_eligible_auxiliary': len(auxiliary), 'reconstructed_vectors': n*3}


def frozen_models(protocol):
    identity = protocol['objects_and_references']
    manifest_path = FROZEN/'artifact-manifest.json'
    manifest = read(manifest_path)
    require(INPUTS[str(manifest_path)] == protocol['accepted_R029_manifest'] == identity['manifest_sha256'], 'Frozen object packet')
    members = {r['path'].replace('\\','/'):r for r in manifest['files']}
    def content(record):
        path = FROZEN/record['path']; payload = bound(path).read_bytes(); original = members[record['path']]
        require(len(payload) == record['size_bytes'] == original['size_bytes']
                and sha256(payload).hexdigest() == record['sha256'] == original['sha256'], 'Verified object bytes')
        return payload
    def scaler(record,width):
        with np.load(BytesIO(content(record)),allow_pickle=False) as a:
            means,scales = a['means'].copy(),a['scales'].copy()
        require(means.shape == scales.shape == (width,) and np.isfinite(means).all()
                and np.isfinite(scales).all() and (scales>0).all(), 'Saved finite scaler')
        return means,scales
    def model(record,width):
        estimator = pickle.loads(content(record['estimator']))
        require(estimator.n_features_in_ == width and estimator.get_params() == record['parameters'], 'Saved model identity')
        return estimator
    for record in identity['files']:
        content(record)
    selected = read(FROZEN/'selection.json')
    aux = identity['auxiliary']; models = {}
    for family in FAMILIES:
        for arm,width in [('C',446),('P',453),('R',1910)]:
            name = family+'-'+arm; record = identity['selected_models'][name]
            require(selected[name]['status'] == 'evaluable' and selected[name]['refit'] is False
                    and selected[name]['selected'] == record['candidate'], 'Frozen selected candidate')
            estimator = model(record,width)
            exact_array(estimator.classes_,[0,1,2],'Frozen classifier classes')
            models[(family,arm)] = (estimator,scaler(record['scaler'],width))
    reference_results = read(FROZEN/'reference-results.json')
    references = {}
    for family in FAMILIES:
        daily = reference_results[family]['train-frequency']['per_day']
        counts = [sum(daily[date]['class_counts'][label] for date in ('2025-02-01','2025-03-01')) for label in CLASSES]
        constants = {name:[int(i==k) for i in range(3)] for k,name in enumerate(REFERENCES[:3])}
        constants.update(uniform=[1/3]*3,**{'train-frequency':[n/sum(counts) for n in counts]})
        equal(identity['references'][family]['probabilities'],constants,'Independent frozen reference vector')
        references[family] = constants
    helper_record = members['code/t016_p1/features.py']
    require(digest(Path(features.__file__)) == helper_record['sha256'], 'Accepted reused view helper identity')
    return models,(model(aux,440),scaler(aux['input_scaler'],440),scaler(aux['target_scaler'],7)),references


def replay_predictions(data, saved, models, auxiliary, references):
    n = len(data['event_ids']); x,z = data['X'],data['Z']; families = data['families']
    for field in ('event_ids','families','labels','matched','decision_ns'):
        exact_array(saved[field],data['y'] if field == 'labels' else data[field],'Prediction row '+field)
    estimator,(means,scales),(target_means,target_scales) = auxiliary
    standardized = estimator.predict((x[:,:440]-means)/scales) if n else np.empty((0,7))
    common = target_means+target_scales*standardized
    exact_array(saved['auxiliary_standardized'],standardized,'Independent auxiliary standardized replay')
    exact_array(saved['auxiliary'],common,'Independent common-coordinate inversion')
    full = {'C':x,'P':np.column_stack((x,common)),'R':np.column_stack((x,z))}
    output = {key:np.empty((n,3)) for key in (*ARMS,*REFERENCES)}
    covariates = {}
    for family in FAMILIES:
        mask = families == family; covariates[family] = {}
        for arm in ARMS:
            model,(mean,scale) = models[(family,arm)]
            transformed = (full[arm][mask]-mean)/scale
            if mask.any():
                output[arm][mask] = model.predict_proba(transformed)
            absolute = np.abs(transformed)
            covariates[family][arm] = {'recorded_rows':int(mask.sum()),
                'coordinate_fraction_abs_above3':float(np.count_nonzero(absolute>3)/absolute.size) if absolute.size else None,
                'coordinate_fraction_abs_above5':float(np.count_nonzero(absolute>5)/absolute.size) if absolute.size else None,
                'max_abs':float(np.max(absolute)) if absolute.size else None}
        for name in REFERENCES:
            output[name][mask] = references[family][name]
    for name,value in output.items():
        require(np.isfinite(value).all() and np.all((value>=0)&(value<=1))
                and np.allclose(value.sum(axis=1),1,atol=1e-12,rtol=0),'Probability simplex '+name)
        exact_array(saved[name],value,'Frozen prediction bitwise replay '+name)
    _,indices = np.unique(data['decision_ns'],return_index=True)
    target,estimate = data['targets'][indices],common[indices]
    violations = np.column_stack((estimate[:,:4]<0,np.abs(estimate[:,4])>1,estimate[:,5:]<0))
    def errors(prediction):
        difference = prediction-target
        return (np.sqrt(np.sum(difference*difference,axis=0)/len(indices)).tolist(),
                (np.sum(np.abs(difference),axis=0)/len(indices)).tolist()) if len(indices) else (None,None)
    rmse,mae = errors(estimate); base_rmse,base_mae = errors(target_means)
    diag = {'covariates':covariates,'auxiliary':{'population':'All deduplicated recorded past-eligible cuts before future support',
        'n':len(indices),'target_names':features.TARGET_NAMES,'rmse':rmse,'mae':mae,
        'training_mean_rmse':base_rmse,'training_mean_mae':base_mae,'range_violation_counts':violations.sum(axis=0).tolist(),
        'range_violation_any':int(violations.any(axis=1).sum()),'nonfinite_predictions':int((~np.isfinite(estimate)).any(axis=1).sum()),'clipping':False}}
    return output,diag


METHODS = (*ARMS, *REFERENCES)
CONTRASTS = {
    'P-C': ('P', 'C'), 'R-C': ('R', 'C'), 'R-P': ('R', 'P'),
    'C-frequency': ('C', 'train-frequency'),
    'P-frequency': ('P', 'train-frequency'),
    'R-frequency': ('R', 'train-frequency'),
    'frequency-uniform': ('train-frequency', 'uniform'),
}


def sign(value):
    if value is None:
        return 'unavailable'
    return 'positive' if value > 0 else ('negative' if value < 0 else 'zero')


def numeric(actual, expected, context):
    """Arithmetic reproducibility tolerance never determines a scientific sign."""
    if expected is None:
        require(actual is None, context + ': missing value')
    else:
        require(actual is not None and np.isfinite(actual)
                and math.isclose(float(actual), float(expected), rel_tol=1e-12, abs_tol=1e-12),
                context + ': arithmetic residual')


def independent_profile(labels, values, fixed):
    """Scalar summation oracle; no producer profile or scoring function is called."""
    n = len(labels)
    counts = {name: sum(int(y) == k for y in labels) for k, name in enumerate(CLASSES)}
    if not n:
        return {'n': 0, 'status': 'unavailable', 'class_counts': counts,
                'raw_mean': None, 'total_loss': None,
                'q': {name: None for name in CLASSES},
                'ell': {name: None for name in CLASSES},
                'standardized': {'status': 'unavailable', 'value': None,
                    'missing_classes': [name for name, weight in zip(CLASSES, fixed) if weight > 0],
                    'class_components': None, 'reference_weights': dict(zip(CLASSES, fixed))}}
    ell = {}
    for k, name in enumerate(CLASSES):
        local = [float(v) for y, v in zip(labels, values) if int(y) == k]
        ell[name] = math.fsum(local) / len(local) if local else None
    missing = [name for name, weight in zip(CLASSES, fixed) if weight > 0 and ell[name] is None]
    components = None if missing else {
        name: float(weight * ell[name]) if weight > 0 else 0.
        for name, weight in zip(CLASSES, fixed)}
    mean = math.fsum(float(v) for v in values) / n
    return {'n': n, 'status': 'evaluable', 'class_counts': counts,
            'raw_mean': mean, 'total_loss': mean,
            'q': {name: counts[name] / n for name in CLASSES}, 'ell': ell,
            'standardized': {'status': 'unavailable' if missing else 'evaluable',
                'value': None if missing else math.fsum(components.values()),
                'missing_classes': missing, 'class_components': components,
                'reference_weights': dict(zip(CLASSES, fixed))}}


def audit_profile(actual, expected, context):
    """Check endpoint support and values separately from exact sign agreement."""
    require(actual['equal_day'] == actual['pooled_event'] == actual['raw_mean'],
            context + ': exact one-date endpoint identity')
    if not expected['n']:
        require(actual.get('status') == 'unavailable', context + ': empty family status')
        require(actual.get('raw_mean') is None and actual.get('total_loss') is None,
                context + ': no empty-family score')
        return
    require(actual['n'] == expected['n'] and actual['class_counts'] == expected['class_counts'],
            context + ': full class support')
    for name in CLASSES:
        numeric(actual['q'][name], expected['q'][name], context + '/q/' + name)
        numeric(actual['ell'][name], expected['ell'][name], context + '/ell/' + name)
    numeric(actual['raw_mean'], expected['raw_mean'], context + '/raw_mean')
    numeric(actual['total_loss'], expected['total_loss'], context + '/total_loss')
    standardized, oracle = actual['standardized'], expected['standardized']
    require(standardized['status'] == oracle['status']
            and standardized['missing_classes'] == oracle['missing_classes'],
            context + ': exact fixed-mixture availability')
    equal(standardized['reference_weights'], oracle['reference_weights'], context + '/reference_weights')
    numeric(standardized['value'], oracle['value'], context + '/standardized')
    if oracle['class_components'] is None:
        require(standardized['class_components'] is None, context + ': unavailable components')
    else:
        for name in CLASSES:
            numeric(standardized['class_components'][name], oracle['class_components'][name],
                    context + '/standardized_component/' + name)


def score_evidence(data, probabilities, evaluation, references, dest=None):
    """Audit all eight methods on the identical ordered family event population."""
    result = {}
    require(set(evaluation['families']) == set(FAMILIES), 'Both declared families retained')
    for family in FAMILIES:
        mask = (data['families'] == family) & data['matched']
        ids, labels = data['event_ids'][mask], data['y'][mask]
        n = len(labels)
        require(len(ids) == len(set(ids.tolist())) and np.isin(labels, [0, 1, 2]).all(),
                'Unique ordered common event IDs and evaluable labels: ' + family)
        losses = {name: np.asarray([
            .5 * math.fsum((float(v) - int(k == int(label))) ** 2 for k, v in enumerate(row))
            for row, label in zip(probabilities[name][mask], labels)], dtype=np.float64)
            for name in METHODS}
        losses.update({name: losses[first] - losses[second]
                       for name, (first, second) in CONTRASTS.items()})
        family_result = evaluation['families'][family]
        counts = dict(zip(CLASSES, np.bincount(labels, minlength=3).tolist()))
        ids_hash = sha256('\n'.join(ids).encode()).hexdigest()
        require(family_result['n'] == n and family_result['class_counts'] == counts,
                'Saved complete family population and support: ' + family)
        require(family_result['ordered_event_ids_sha256'] == ids_hash,
                'Saved ordered family event IDs: ' + family)
        require(family_result['missing_classes'] == [name for name in CLASSES if counts[name] == 0],
                'Saved family missing support flags: ' + family)
        if dest is not None:
            saved_losses = arrays(Path(dest) / ('losses-' + family + '.npz'))
            require(set(saved_losses) == {'event_ids', 'labels', *losses},
                    'Complete saved loss archive fields: ' + family)
            exact_array(saved_losses['event_ids'], ids, 'Loss archive ordered event IDs: ' + family)
            exact_array(saved_losses['labels'], labels, 'Loss archive labels: ' + family)
            for name, oracle in losses.items():
                values = saved_losses[name]
                require(values.dtype == np.dtype('float64') and values.shape == (n,)
                        and np.isfinite(values).all(), 'Saved finite float64 loss vector: ' + family + '/' + name)
                require(np.allclose(values, oracle, rtol=1e-12, atol=1e-12),
                        'Independent per-event scalar loss oracle: ' + family + '/' + name)
        actual = family_result['profiles']
        require(set(actual) == set(losses), 'All methods and seven contrasts retained: ' + family)
        profiles = {}
        for name, values in losses.items():
            profile = independent_profile(labels, values, references[family]['train-frequency'])
            audit_profile(actual[name], profile, family + '/' + name)
            profiles[name] = profile
        # A single date gets one vote, even when two endpoint names are printed.
        result[family] = {
            'n': n, 'class_counts': counts, 'event_ids_sha256': ids_hash,
            'methods_share_ordered_ids': True, 'profiles': profiles,
            'saved_per_event_loss_vectors_checked': dest is not None,
            'one_date_equal_day_equals_pooled': True,
            'one_date_common_weight': 1 / n if n else None,
            'independent_loss_formula': '0.5 * math.fsum((p_k - int(k == y)) ** 2)',
            'independent_reduction': 'math.fsum(values) / n',
        }
    profile = result['breakout']['profiles']['R-C']
    independent = {'raw': profile['raw_mean'],
                   'fixed_class': profile['standardized']['value'],
                   'favorable_conditional': profile['ell']['F']}
    components = {}
    require(set(evaluation['joint']['components']) == set(independent), 'Exactly three joint components')
    for name, value in independent.items():
        saved = evaluation['joint']['components'][name]
        producer = saved['value']
        require(saved['status'] == ('unavailable' if producer is None else 'evaluable')
                and saved['sign'] == sign(producer), 'Saved exact component sign/status: ' + name)
        require((producer is None) == (value is None), 'Joint support availability: ' + name)
        numeric(producer, value, 'Joint arithmetic: ' + name)
        agreement = sign(producer) == sign(value)
        components[name] = {
            'producer_value': producer, 'audit_value': value,
            'producer_float64_hex': None if producer is None else float(producer).hex(),
            'audit_float64_hex': None if value is None else float(value).hex(),
            'producer_sign': sign(producer), 'audit_sign': sign(value),
            'sign_agreement': agreement,
            'status': 'evaluable' if value is not None and agreement else 'unavailable',
            'reason': ('missing_support' if value is None else
                       None if agreement else 'audit_sign_disagreement_pending_numerical_review'),
            'classification_tolerance': None,
        }
    return result, components


def run_audit(*, member, protocol, evaluation, protocol_sha, previous_end, p0_sha,
              dest, output_path, preflight_gate=None):
    """Run only after the new E271 declaration and input freeze are sealed.

    The caller owns the declared gate and solver guard. Seven saved fitted
    objects may be deserialized here; fitting is guarded before any such load.
    All failures preserve their exact receipt, and an existing receipt is never
    silently replaced. Sign disagreement is a result, not a failed assertion.
    """
    global CHECKS, INPUTS
    dest, output_path = Path(dest), Path(output_path)
    if output_path.exists():
        raise FileExistsError('Preserve the issued E271 audit receipt')
    CHECKS, INPUTS = Counter(), {}
    started = time.perf_counter()
    ledger = install_fit_guards()
    receipt = {'status': 'failed', 'started_utc': datetime.now(timezone.utc).isoformat(),
               'operation': 'D056:T016:E271-fixed-persistence', 'scientific_acceptance': False}
    try:
        if preflight_gate is not None:
            preflight_gate()
        require(member['date'] == '2026-02-01'
                and member['source_id'] == 'tardis-hyperliquid-2026-02-01-btc-e270',
                'Exact released date and source identity')
        cuts = arrays(dest / 'cuts.npz')
        data = arrays(dest / 'feature-vectors.npz')
        cuts['_reason_codes'] = read(dest / 'availability.json')['support_reason_codes']
        source = normalized_source(member, cuts, dest)
        events, cohort = labels_and_features(member, dest, cuts, data, protocol_sha, previous_end, p0_sha)
        models, auxiliary, references = frozen_models(protocol)
        saved = arrays(dest / 'predictions.npz')
        with threadpool_limits(limits=2):
            probabilities, diagnostics = replay_predictions(data, saved, models, auxiliary, references)
        profiles, components = score_evidence(data, probabilities, evaluation, references, dest=dest)
        require(not ledger['attempts'] and ledger['actual_fit_calls'] == 0, 'Audit zero fit attempts')
        install_fit_guards()
        for path, expected in INPUTS.items():
            require(digest(path) == expected, 'Audited input unchanged: ' + path)
        receipt.update(status='passed', source=source, cohort=cohort,
                       bitwise_probability_replay=True, families=profiles,
                       components=components,
                       all_component_signs_agree=all(c['sign_agreement'] for c in components.values()),
                       diagnostics=diagnostics,
                       exact_dependency_max_ns=max((e['dependency_max_ns'] for e in events), default=None))
    except Exception as exc:
        receipt.update(error=type(exc).__name__ + ': ' + str(exc), traceback=traceback.format_exc())
        raise
    finally:
        receipt.update(finished_utc=datetime.now(timezone.utc).isoformat(),
                       elapsed_seconds=time.perf_counter() - started, checks=dict(CHECKS),
                       fit_guard_ledger=ledger, input_sha256=INPUTS,
                       independence={
                           'shared_pure_feature_helper': str(Path(features.__file__)),
                           'shared_fit_guard': 't016_p3.fixed_inference.install_fit_guards',
                           'source_checks_origin': 't016_p3.audit; source identity and provenance storage adapted only',
                           'not_reused': ['FixedInference.predict', 'half_brier', 'profile_loss',
                                          'standardize', 'label_event', 'Observations'],
                           'limits': [
                               'Shared accepted feature formulas are consistency evidence, not independent formulas.',
                               'Saved-object replay uses the same estimator runtime, not an independent model implementation.',
                               'No raw response replay or exchange completeness/receipt calibration claim.',
                               'Engineer self-audit does not confer independent result acceptance.',
                           ],
                       })
        output_path.write_text(json.dumps(receipt, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    return receipt
