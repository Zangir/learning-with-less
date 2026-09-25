"""Independent no-fit replay of the four fixed later-period evaluation slots.

Only the accepted pure feature view and fit guard are shared with the producer.
Source joins, labels, scaler application, predictions and scores are checked here.
Run explicitly after evaluation; importing this module performs no data reads.
"""
from collections import Counter
from datetime import datetime, timezone
from fractions import Fraction
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import pickle
import time
import traceback

import numpy as np
from threadpoolctl import threadpool_limits
from t016_p1 import features
from t016_p3.common import OUT, FROZEN, WORK, DATES, FAMILIES, ARMS
from t016_p3.fixed_inference import install_fit_guards

NS = 1_000_000_000
CLASSES = ('F', 'A', 'N')
REFERENCES = ('onehot-F', 'onehot-A', 'onehot-N', 'uniform', 'train-frequency')
PAIRS = (('C', 'P'), ('C', 'R'), ('P', 'R'))
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
    saved = rows(dest/'source-row-provenance.jsonl')
    require(len(saved) == len(times), 'Saved source provenance row count')
    for i, record in enumerate(saved):
        require(record['source_ordinal'] == int(ordinals[i]) and record['event_ns'] == int(times[i]), 'Saved provenance order')
        require(record['source_id'] == source_id and record['date'] == member['date'], 'Saved provenance source/date')
        require(record['contract_sha256'] == member['contract_sha256']
                and record['segment_id'] == int(segment_ids[i]), 'Saved provenance contract/segment')
        require(record['physical_line_1_based'] == i+1 and record['source_line_sha256'] == state_hashes[i], 'Saved source line binding')
        equal(record['provenance'], provenance[int(ordinals[i])], 'Saved provenance record')
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
        require(event['source_id'] == 'tardis-hyperliquid-'+member['date']+'-btc'
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


def score_outputs(date,dest,data,probabilities):
    result = []
    for family in FAMILIES:
        mask = (data['families']==family)&data['matched']; ids = data['event_ids'][mask]; y = data['y'][mask]; n = len(y)
        require(np.isin(y,[0,1,2]).all(),'Matched class support')
        losses = {name:.5*(np.sum(p[mask]*p[mask],axis=1)+1)-p[mask][np.arange(n),y]
                  for name,p in probabilities.items()}
        record = {'date':date,'family':family,'n':n,'status':'evaluable' if n else 'unavailable',
            'classes':dict(zip(CLASSES,np.bincount(y,minlength=3).tolist())),
            'event_ids_sha256':sha256('\n'.join(ids).encode()).hexdigest(),
            'scores':{key:float(np.sum(value)/n) if n else None for key,value in losses.items()},'paired':{}}
        for first,second in PAIRS:
            delta = losses[first]-losses[second]
            record['paired'][first+'-'+second] = float(np.sum(delta)/n) if n else None
            pair = arrays(dest/f'paired-{family}-{first}-{second}.npz')
            for key,value in [('event_ids',ids),('labels',y),('first',probabilities[first][mask]),('second',probabilities[second][mask])]:
                exact_array(pair[key],value,'Paired event/probability alignment '+key)
            require(np.allclose(pair['loss_difference'],delta,atol=1e-12,rtol=1e-12),'Independent paired half-Brier differences')
        result.append(record)
    equal(read(dest/'scores.json'),result,'Independent daily half-Brier scores')
    return result


def aggregate_scores(days):
    result = {}
    for family in FAMILIES:
        group = [next((r for r in day.get('scores',[]) if r['family']==family),None) for day in days]
        complete = all(row is not None and row['status']=='evaluable' for row in group)
        record = {'complete_four_dates':complete,'equal_day':None,'pooled_event':None,
                  'paired_equal_day':None,'paired_pooled_event':None}
        if complete:
            total = sum(row['n'] for row in group); record['n'] = total
            for source,prefix in [('scores',''),('paired','paired_')]:
                record[prefix+'equal_day'] = {key:sum(row[source][key] for row in group)/4 for key in group[0][source]}
                record[prefix+'pooled_event'] = {key:sum(row['n']*row[source][key] for row in group)/total for key in group[0][source]}
        result[family] = record
    return result


def main():
    target = OUT/'audit-results.json'
    if target.exists():
        raise FileExistsError('Preserve the existing audit receipt')
    started = time.perf_counter(); receipt = {'status':'failed','dates':DATES,'days':[],'new_fits':0}
    ledger = install_fit_guards()
    try:
        require(ledger['installed'] and not ledger['attempts'] and ledger['actual_fit_calls']==0,'Fresh fit guard ledger')
        protocol = read(OUT/'extension-protocol.json'); protocol_sha = INPUTS[str(OUT/'extension-protocol.json')]
        freeze = read(OUT/'execution-freeze.json')
        require(INPUTS[str(OUT/'execution-freeze.json')] == (OUT/'execution-freeze.sha256').read_text().strip(),'Execution freeze digest')
        for entry in freeze['code']:
            require(digest(WORK/entry['path']) == entry['sha256'] == digest(OUT/'code'/entry['path']),'Executed/frozen code identity')
        summary = read(OUT/'evaluation-summary.json')
        require(protocol['dates'] == summary['dates'] == DATES and [d['date'] for d in summary['days']] == DATES,'Exactly four fixed date slots')
        require(summary['new_fits'] == summary['training_seconds'] == 0,'Evaluation has no training')
        evaluation_guard = read(OUT/'fit-guard-ledger.json')
        require(evaluation_guard['installed'] and not evaluation_guard['attempts'] and evaluation_guard['actual_fit_calls']==0,'Evaluation fit guard attempts zero')
        require(read(OUT/'post-integrity.json')['all_unchanged'],'Evaluation post-integrity receipt')
        models,auxiliary,references = frozen_models(protocol)
        prior = arrays(FROZEN/'prepared-cohort.npz')
        july = prior['dates'] == '2025-07-01'
        require(july.any(),'Accepted July observed block exists')
        previous_end = int(prior['decision_ns'][july].max())+10*NS
        require(protocol['previous_observed_block_max_dependency_ns'] == previous_end,'Frozen actual July predecessor')
        del prior
        checked_days = []
        for member,day in zip(protocol['contracts'],summary['days']):
            date = member['date']; require(date == day['date'],'Contract/date slot alignment'); dest = OUT/date
            equal(read(dest/'day-result.json'),day,'Saved day result')
            if day['status'] == 'unavailable':
                failure = read(dest/'failure.json')
                require(day['reason'] == failure['reason'] and day['traceback'] == failure['traceback']
                        and bool(day['reason']) and bool(day['traceback']) and day['replacement'] is None and day['scores']==[], 'Unavailable exact reason and no replacement')
                receipt['days'].append({'date':date,'status':'unavailable','exact_reason':day['reason'],
                    'checks':'Failure preserved; no successful source/inference claim for this slot'})
                checked_days.append({'date':date,'scores':[]}); continue
            require(day['status']=='evaluable','Known date status')
            cuts = arrays(dest/'cuts.npz'); data = arrays(dest/'feature-vectors.npz')
            cuts['_reason_codes'] = read(dest/'availability.json')['support_reason_codes']
            source = normalized_source(member,cuts,dest)
            events,cohort = labels_and_features(member,dest,cuts,data,protocol_sha,previous_end,protocol['inherited_P0_protocol_sha256'])
            if events:
                previous_end = max(e['dependency_max_ns'] for e in events)
            prediction = arrays(dest/'predictions.npz')
            with threadpool_limits(limits=2):
                probabilities,diagnostics = replay_predictions(data,prediction,models,auxiliary,references)
            ages = np.sort(cuts['age_ns'][cuts['valid_bbo']].astype(float)/NS)
            quantiles = []
            for probability in (0,.5,.9,.99,1):
                position = (len(ages)-1)*probability
                lo,hi = int(np.floor(position)),int(np.ceil(position))
                quantiles.append(float(ages[lo]+(ages[hi]-ages[lo])*(position-lo)) if len(ages) else None)
            diagnostics['valid_grid_asof_age_seconds_quantiles'] = dict(zip(('min','q50','q90','q99','max'),quantiles)) if len(ages) else None
            equal(read(dest/'diagnostics.json'),diagnostics,'Independent reconstruction/range diagnostics')
            scores = score_outputs(date,dest,data,probabilities)
            equal(day['scores'],scores,'Summary daily scores'); equal(day['diagnostics'],diagnostics,'Summary diagnostics')
            identity = read(dest/'prediction-identity.json')
            require(identity['protocol_sha256']==protocol_sha and identity['features_sha256']==INPUTS[str(dest/'feature-vectors.npz')]
                    and identity['predictions_sha256']==INPUTS[str(dest/'predictions.npz')],'Prediction artifact bindings')
            equal(identity['objects'],protocol['objects_and_references'],'Prediction frozen objects')
            receipt['days'].append({'date':date,'status':'passed','source':source,'cohort':cohort,
                'bitwise_probability_replay':True,'auxiliary_range_violations':diagnostics['auxiliary']['range_violation_counts']})
            checked_days.append({'date':date,'scores':scores})
            print(date+' independent audit passed',flush=True)
        equal(summary['aggregate'],aggregate_scores(checked_days),'Independent four-date aggregates')
        require(summary['complete_four_date_evaluation']==(all(d['status']=='evaluable' for d in summary['days'])
                and all(r['complete_four_dates'] for r in aggregate_scores(checked_days).values())),'Honest four-date completeness')
        require(not ledger['attempts'] and ledger['actual_fit_calls']==0,'Audit zero fit attempts')
        install_fit_guards()
        for path,expected in INPUTS.items():
            require(digest(path)==expected,'Audited input unchanged: '+path)
        receipt['status']='passed'
    except Exception as exc:
        receipt.update(error=type(exc).__name__+': '+str(exc),traceback=traceback.format_exc())
        raise
    finally:
        receipt.update(finished_utc=datetime.now(timezone.utc).isoformat(),elapsed_seconds=time.perf_counter()-started,
            checks=dict(CHECKS),fit_guard_ledger=ledger,input_sha256=INPUTS,
            independence={'shared_pure_feature_helper':str(Path(features.__file__)),
                'shared_fit_guard':'t016_p3.fixed_inference.install_fit_guards',
                'not_reused':['FixedInference.predict','score_date','aggregate','diagnostics','label_event','Observations'],
                'source_scope':'Independent normalized state/provenance and saved cut replay; no raw response/exchange authentication',
                'limits':['Shared accepted feature formula code is consistency evidence, not independent formula implementation.',
                          'Frozen pickle prediction replay uses the same estimator runtime; not independent model implementation.',
                          'Unavailable slots are retained with exact recorded failure; their failed computations are not silently retried.',
                          'No scientific acceptance, CI, p-value, participant certification or profitability inference.']})
        target.write_text(json.dumps(receipt,indent=2,allow_nan=False)+'\n',encoding='utf-8')
        print(json.dumps({'status':receipt['status'],'elapsed_seconds':receipt['elapsed_seconds'],'checks':dict(CHECKS)}),flush=True)


if __name__ == '__main__':
    main()
