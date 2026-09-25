"""Independently validate frozen study captures before any fit; import no engine."""
from collections import Counter
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from fractions import Fraction
from hashlib import sha256
from itertools import product
import json
from pathlib import Path

ROOT = (Path(__file__).resolve().parents[1] / 'runtime')
ORIGIN = 1735723800000000000
START = datetime(2025, 1, 1, 9, 30)
IDENTITY = ('order_id', 'agent_id', 'symbol', 'is_buy_order', 'limit_price',
            'time_placed', 'tag', 'fill_price')
VISIBLE = ('C', 'Z', 'K', 'Q', 'side')
PROBE = 201
CUTOFF = 403
HORIZON = 503


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return sha256(canonical(value).encode()).hexdigest()


def file_hash(path):
    return sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def iso(offset):
    seconds, fraction = divmod(offset, 10**9)
    result = (START + timedelta(seconds=seconds)).isoformat()
    if fraction:
        result += '.' + (f'{fraction:09d}' if fraction % 1000 else f'{fraction // 1000:06d}')
    return result


def offset_of(timestamp):
    whole, _, fraction = timestamp.partition('.')
    seconds = int(datetime.fromisoformat(whole).replace(tzinfo=timezone.utc).timestamp())
    return seconds * 10**9 + int(fraction.ljust(9, '0') or '0') - ORIGIN


class InvalidCapture(Exception):
    pass


class Audit:
    """Keep pass evidence compact; failed expectations cannot mutate after recording."""
    def __init__(self, name):
        self.name = name
        self.count = 0
        self.chain = sha256()
        self.failures = []

    def check(self, name, actual, expected, sequence=None):
        self.count += 1
        record = dict(check=name, sequence=sequence, actual=actual, expected=expected)
        self.chain.update(canonical(record).encode() + b'\n')
        if actual != expected:
            self.failures.append(deepcopy(record))
            raise InvalidCapture(f'{self.name}: {name}, event {sequence}')

    def summary(self):
        return dict(name=self.name, check_count=self.count, passed=not self.failures,
                    comparison_sha256=self.chain.hexdigest(), failures=self.failures)


def original_request(action, local):
    who, oid, kind = action['participant'], action['order_id'], action['kind']
    if kind in ('LIMIT_ORDER', 'MARKET_ORDER'):
        order = dict(agent_id=who, time_placed=iso(action['at_ns']), symbol='SYNTH',
                     quantity=action['quantity'], is_buy_order=action['side'] == 'bid',
                     order_id=oid, fill_price=None, tag=None)
        if kind == 'LIMIT_ORDER':
            order['limit_price'] = action['price']
        local.setdefault((who, oid), deepcopy(order))
    else:
        order = deepcopy(local[who, oid])
    body = dict(msg=kind, sender=who, order=order)
    if kind == 'MODIFY_ORDER':
        replacement = deepcopy(order)
        replacement['quantity'] = action['quantity']
        for key in IDENTITY:
            if 'new_' + key in action:
                replacement[key] = action['new_' + key]
        if 'new_time_ns' in action:
            replacement['time_placed'] = iso(action['new_time_ns'])
        body['new_order'] = replacement
    return body


def admit(body, ledger, accepted_ids):
    kind, old = body['msg'], body['order']
    if kind not in ('LIMIT_ORDER', 'CANCEL_ORDER', 'MODIFY_ORDER'):
        return None, 'UNSUPPORTED_OPERATION'
    if body['sender'] != old['agent_id']:
        return None, 'OWNER_MISMATCH'
    if old['symbol'] != 'SYNTH':
        return None, 'UNSUPPORTED_SYMBOL'
    if kind == 'LIMIT_ORDER':
        if type(old['quantity']) is not int or old['quantity'] <= 0:
            return None, 'INVALID_QUANTITY'
        if type(old['limit_price']) is not int or old['limit_price'] <= 0:
            return None, 'INVALID_PRICE'
        if old['order_id'] in accepted_ids:
            return None, 'REUSED_ORDER_ID'
        return deepcopy(body), None
    entry = ledger.get(old['order_id'])
    if entry is None:
        return None, 'ORDER_NOT_UNIQUELY_LIVE'
    live = entry['order']
    if any(old[key] != live[key] for key in IDENTITY):
        return None, 'LIVE_IDENTITY_MISMATCH'
    clean = dict(msg=kind, sender=body['sender'], order=deepcopy(live))
    if kind == 'MODIFY_ORDER':
        # The bounded history cannot age out; membership comes from accepted inputs.
        assert old['order_id'] in accepted_ids
        new = body['new_order']
        if any(new[key] != live[key] for key in IDENTITY):
            return None, 'AMENDMENT_IDENTITY_CHANGE'
        if type(new['quantity']) is not int or not 0 < new['quantity'] < live['quantity']:
            return None, 'AMENDMENT_NOT_STRICT_REDUCTION'
        clean['new_order'] = deepcopy(live)
        clean['new_order']['quantity'] = new['quantity']
    return clean, None


def ordered_rows(ledger):
    entries = sorted(ledger.values(), key=lambda entry: (
        not entry['order']['is_buy_order'],
        -entry['order']['limit_price'] if entry['order']['is_buy_order'] else entry['order']['limit_price'],
        entry['priority']))
    counts, result = Counter(), []
    for entry in entries:
        o = entry['order']
        side = 'bid' if o['is_buy_order'] else 'ask'
        price = o['limit_price']
        result.append(dict(side=side, price=price, order_id=o['order_id'], participant=o['agent_id'],
                           quantity=o['quantity'], queue_position=counts[side, price],
                           time_placed_ns=ORIGIN + offset_of(o['time_placed'])))
        counts[side, price] += 1
    return result


def aggregate(rows):
    levels = Counter()
    for row in rows:
        levels[row['side'], row['price']] += row['quantity']
    return [dict(side=s, price=p, quantity=q) for (s, p), q in sorted(levels.items(),
            key=lambda pair: (pair[0][0], -pair[0][1] if pair[0][0] == 'bid' else pair[0][1]))]


def apply_request(clean, ledger, accepted_ids, sequence):
    kind, order = clean['msg'], clean['order']
    oid, notifications, matches = order['order_id'], [], []
    if kind == 'LIMIT_ORDER':
        accepted_ids.add(oid)
        residual = order['quantity']
        opposite = sorted((entry for entry in ledger.values()
                           if entry['order']['is_buy_order'] != order['is_buy_order']),
                          key=lambda entry: (entry['order']['limit_price'] if order['is_buy_order']
                                             else -entry['order']['limit_price'], entry['priority']))
        for entry in opposite:
            resting = entry['order']
            price = resting['limit_price']
            crosses = price <= order['limit_price'] if order['is_buy_order'] else price >= order['limit_price']
            if not residual or not crosses:
                break
            quantity = min(residual, resting['quantity'])
            incoming_fill, resting_fill = deepcopy(order), deepcopy(resting)
            for filled in (incoming_fill, resting_fill):
                filled.update(quantity=quantity, fill_price=price)
                notifications.append(dict(recipient=filled['agent_id'], body=dict(msg='ORDER_EXECUTED', order=filled)))
            matches.append(quantity)
            residual -= quantity
            resting['quantity'] -= quantity
            if not resting['quantity']:
                del ledger[resting['order_id']]
        if residual:
            live = deepcopy(order)
            live['quantity'] = residual
            ledger[oid] = dict(order=live, priority=sequence)
            notifications.append(dict(recipient=live['agent_id'], body=dict(msg='ORDER_ACCEPTED', order=deepcopy(live))))
    elif kind == 'CANCEL_ORDER':
        cancelled = ledger.pop(oid)['order']
        notifications.append(dict(recipient=cancelled['agent_id'], body=dict(msg='ORDER_CANCELLED', order=deepcopy(cancelled))))
    else:
        ledger[oid]['order'] = deepcopy(clean['new_order'])
        notifications.append(dict(recipient=order['agent_id'], body=dict(msg='ORDER_MODIFIED', new_order=deepcopy(clean['new_order']))))
    return notifications, matches


def submission(body, sent_ns):
    order = body['new_order'] if body['msg'] == 'MODIFY_ORDER' else body['order']
    return dict(sent_ns=sent_ns, kind=body['msg'], own_order_id=order['order_id'],
                quantity=order['quantity'], side='bid' if order['is_buy_order'] else 'ask',
                price=order.get('limit_price'))


def own_receipt(receipt):
    body = receipt['body']
    result = dict(delivery_ns=receipt['delivery_ns'], kind=body['msg'])
    if body['msg'] == 'ORDER_REJECTED':
        result.update(own_order_id=body['order_id'], reason=body['reason'])
    else:
        o = body['new_order'] if body['msg'] == 'ORDER_MODIFIED' else body['order']
        result.update(own_order_id=o['order_id'], quantity=o['quantity'],
                      side='bid' if o['is_buy_order'] else 'ask', price=o['limit_price'], fill_price=o['fill_price'])
    return result


def features_from_admissible(admissible, audit):
    sends = admissible['own_submissions']
    audit.check('one_actual_probe_submission', len(sends), 1)
    own = sends[0]
    audit.check('probe_submission_contract', [own['sent_ns'], own['kind'], own['own_order_id'], own['price']],
                [200, 'LIMIT_ORDER', PROBE, 10000])
    side, q = own['side'], own['quantity']
    audit.check('visible_side_domain', side in ('bid', 'ask'), True)
    audit.check('visible_probe_quantity_domain', q in (2, 3), True)
    direction = -1 if side == 'bid' else 1

    def level_at(delivery, price):
        packets = [r for r in admissible['coarse'] if r['delivery_ns'] == delivery]
        audit.check(f'one_feature_packet_{delivery}', len(packets), 1)
        levels = [r for r in packets[0]['payload']['levels'] if r['side'] == side and r['price'] == price]
        audit.check(f'one_feature_level_{delivery}', len(levels), 1)
        return levels[0]['quantity']

    c = level_at(53, 10000 + direction * 10) - 1
    z = level_at(93, 10000 + direction * 20) - 1
    k = level_at(103, 10000)
    audit.check('visible_feature_domains', [c in (0, 1), z in (0, 1), k in (2, 4)], [True] * 3)
    return dict(C=c, Z=z, K=k, Q=q, side=side)


def validate_capture(spec, episode, audit):
    cutoff = spec['cutoff_ns']
    audit.check('fixed_delivery_cutoff', cutoff, CUTOFF)
    audit.check('capture_identity', [episode['name'], episode['split'], episode['variant'], episode['cutoff_ns']],
                [spec['name'], spec['split'], 'patched', cutoff])
    actions = [a for a in spec['actions'] if not spec.get('prefix', False) or a['at_ns'] <= cutoff]
    actions = [a for _, a in sorted(enumerate(actions), key=lambda pair:
                                   (pair[1]['at_ns'], pair[1]['participant'], pair[0]))]
    audit.check('bounded_request_count', len(actions) <= 128, True)
    audit.check('bounded_unique_limit_ids', len({a['order_id'] for a in actions if a['kind'] == 'LIMIT_ORDER'}) <= 64, True)
    audit.check('one_event_per_frozen_request', len(episode['events']), len(actions))
    ledger, local, accepted_ids = {}, {}, set()
    expected_receipts = {str(i): [] for i in range(1, 4)}
    expected_observations, expected_submissions, cutoff_rows = [], [], []
    history, last_update, message_ids = [{}], None, set()
    for index, (action, event) in enumerate(zip(actions, episode['events'])):
        request = original_request(action, local)
        at = action['at_ns'] + 1
        audit.check('exact_frozen_request', event['input'], request, index)
        audit.check('event_clock_and_sequence', [event['sequence'], event['offset_ns'], event['timestamp_ns']],
                    [index, at, ORIGIN + at], index)
        audit.check('inside_exchange_window', 0 < at < 100000, True, index)
        audit.check('independent_before_book', event['before'], ordered_rows(ledger), index)
        audit.check('native_history_continuity_only', event['before_history'], history, index)
        audit.check('last_update_continuity', event['before_last_update_ns'], last_update, index)
        clean, reason = admit(request, ledger, accepted_ids)
        audit.check('independent_admission', [event['accepted'], event['rejection'], event['actual_input']],
                    [reason is None, reason, clean], index)
        if reason is None:
            notifications, matches = apply_request(clean, ledger, accepted_ids, index)
            last_update = ORIGIN + at
        else:
            notifications = [dict(recipient=request['sender'], body=dict(msg='ORDER_REJECTED',
                                  order_id=request['order']['order_id'], reason=reason))]
            matches = []
            audit.check('rejection_history_preserved', event['native_history'], history, index)
        after = ordered_rows(ledger)
        audit.check('independent_after_book', event['after'], after, index)
        audit.check('live_unique_positive_integer_orders',
                    [len({r['order_id'] for r in event['after']}) == len(event['after']),
                     all(type(r['quantity']) is int and r['quantity'] > 0 for r in event['after'])], [True, True], index)
        audit.check('live_volume_conservation', sum(r['quantity'] for r in event['after']),
                    sum(r['quantity'] for r in after), index)
        audit.check('last_update_result', event['after_last_update_ns'], last_update, index)
        levels = aggregate(after)
        audit.check('exact_anonymous_aggregation', event['l2'], levels, index)
        if matches:
            oid = str(request['order']['order_id'])
            entries = [h[oid] for h in event['native_history'] if oid in h]
            audit.check('unique_incoming_history_entry', len(entries), 1, index)
            audit.check('incoming_per_match_history', entries[0]['transactions'], [[iso(at), q] for q in matches], index)
        history = deepcopy(event['native_history'])
        feed = dict(msg='COARSE_BOOK', sequence=index, exchange_ns=at, publish_ns=at, levels=levels)
        notifications.append(dict(recipient=1, body=feed))
        audit.check('exact_all_outgoing_bodies_and_recipients',
                    [dict(recipient=m['recipient'], body=m['body']) for m in event['outgoing']], notifications, index)
        ids = [event['message_uniq']] + [m['message_uniq'] for m in event['outgoing']]
        audit.check('unique_message_identities', len(set(ids)) == len(ids) and not (set(ids) & message_ids), True, index)
        message_ids.update(ids)
        audit.check('outgoing_native_tie_order', [m['message_uniq'] for m in event['outgoing']],
                    sorted(m['message_uniq'] for m in event['outgoing']), index)
        for expected, actual in zip(notifications, event['outgoing']):
            recipient, body = expected['recipient'], expected['body']
            delivery = at + (2 if recipient == 1 else 1)
            if body['msg'] == 'COARSE_BOOK':
                expected_observations.append((delivery, actual['message_uniq'], dict(delivery_ns=delivery, payload=body)))
            else:
                expected_receipts[str(recipient)].append(dict(timestamp_ns=ORIGIN + delivery, delivery_ns=delivery,
                                                             message_uniq=actual['message_uniq'], body=body))
        if request['sender'] == 1:
            expected_submissions.append(submission(request, action['at_ns']))
        if at <= cutoff:
            cutoff_rows = deepcopy(after)
    for rows in expected_receipts.values():
        rows.sort(key=lambda r: (r['delivery_ns'], r['message_uniq']))
    expected_observations.sort(key=lambda record: record[:2])
    expected_observations = [record[2] for record in expected_observations]
    audit.check('all_private_receipts_payload_routing_time_and_order', episode['receipts'], expected_receipts)
    audit.check('all_public_deliveries_payload_time_and_order', episode['observations'], expected_observations)
    audit.check('actual_own_sends', episode['submissions'], expected_submissions)
    admissible = dict(coarse=[r for r in expected_observations if r['delivery_ns'] <= cutoff],
                      own_receipts=[own_receipt(r) for r in expected_receipts['1'] if r['delivery_ns'] <= cutoff],
                      own_submissions=[r for r in expected_submissions if r['sent_ns'] <= cutoff])
    audit.check('admissible_from_independent_raw_delivery', episode['admissible'], admissible)
    features = features_from_admissible(admissible, audit)
    audit.check('visible_metadata_is_only_an_audit_crosscheck', features,
                {key: spec['metadata'][key] for key in VISIBLE})
    probe = [r for r in cutoff_rows if r['order_id'] == PROBE]
    audit.check('unique_probe_at_cutoff', len(probe), 1)
    probe = probe[0]
    audit.check('unaltered_unfilled_probe_at_cutoff',
                [probe['participant'], probe['side'], probe['price'], probe['quantity'], probe['time_placed_ns']],
                [1, features['side'], 10000, features['Q'], ORIGIN + 200])
    ahead = [r for r in cutoff_rows if r['side'] == probe['side'] and
             (r['price'] > probe['price'] if probe['side'] == 'bid' else r['price'] < probe['price'])]
    audit.check('no_better_price_before_probe', ahead, [])
    ahead = sum(r['quantity'] for r in cutoff_rows if r['side'] == probe['side'] and
                r['price'] == probe['price'] and r['queue_position'] < probe['queue_position'])
    h, remainder = divmod(ahead, features['K'])
    audit.check('queue_rank_support', [remainder, h in (0, 1, 2)], [0, True])
    audit.check('hidden_queue_metadata_crosscheck', h, spec['metadata']['H'])
    own_executions = [r for r in expected_receipts['1'] if r['body']['msg'] == 'ORDER_EXECUTED'
                      and r['body']['order']['order_id'] == PROBE]
    audit.check('no_probe_fill_at_or_before_forecast', any(r['delivery_ns'] <= cutoff for r in own_executions), False)
    fill = sum(r['body']['order']['quantity'] for r in own_executions if r['delivery_ns'] <= HORIZON)
    audit.check('bounded_probe_filled_quantity', 0 <= fill <= features['Q'], True)
    audit.check('no_probe_amendment_or_cancellation',
                [a for a in actions if a['participant'] == 1 and a['kind'] != 'LIMIT_ORDER'], [])
    future = [a for a in actions if a['at_ns'] > cutoff]
    if spec.get('prefix', False):
        audit.check('prefix_has_no_future_sends', future, [])
        audit.check('prefix_has_no_future_probe_fill', fill, 0)
    else:
        audit.check('one_future_flow_action', len(future), 1)
        future = future[0]
        j = spec['metadata']['J']
        audit.check('future_category_support', j in range(4), True)
        q, k = features['Q'], features['K']
        volume = [q - 1, q, q + k, q + 2 * k][j]
        audit.check('future_native_flow_contract',
                    [future['at_ns'], future['participant'], future['kind'], future['quantity'], future['price'], future['side']],
                    [500, 3, 'LIMIT_ORDER', volume, 10000, 'ask' if features['side'] == 'bid' else 'bid'])
        audit.check('independent_fill_algebra', fill, min(q, max(0, volume - ahead)))
        audit.check('binary_full_fill_algebra', int(fill == q), int(volume >= ahead + q))
        audit.check('future_probe_execution_delivery', [r['delivery_ns'] for r in own_executions], [HORIZON] * len(own_executions))
    return dict(features=features, labels=dict(H=h, A=ahead, fill=fill, Y=int(fill == features['Q'])),
                admissible_sha256=digest(admissible))


def main():
    protocol = read(ROOT / 'protocol.json')
    specifications = protocol['episodes']
    global_audit = Audit('study_structure')
    summaries, rows_by_name, support_cells, support_worlds = [], {}, {}, []
    failure, total_checks, written_rows = None, 0, 0
    reference = None
    partial = ROOT / 'validated_rows.partial.jsonl'
    try:
        global_audit.check('native_episode_count', len(specifications), 3212)
        global_audit.check('unique_episode_names', len({s['name'] for s in specifications}), len(specifications))
        global_audit.check('frozen_run_accounting', protocol['run_counts'],
                           dict(statistical=2816, support=384, diagnostic=12, total=3212))
        statistical = [s for s in specifications if s['metadata']['role'] not in ('support', 'diagnostic')]
        global_audit.check('statistical_population_counts',
                           sorted(Counter((s['metadata']['condition'], s['metadata']['role']) for s in statistical).items()),
                           sorted(((p['condition'], p['role']), p['n']) for p in protocol['populations']))
        global_audit.check('independent_statistical_group_ids',
                           len({s['metadata']['group_id'] for s in statistical}), 2816)
        generation_seeds = [s['metadata']['generation_seed'] for s in statistical]
        global_audit.check('distinct_recorded_statistical_generation_seeds', len(set(generation_seeds)), 2816)
        statistical_groups = {s['metadata']['group_id'] for s in statistical}
        other_groups = {s['metadata']['group_id'] for s in specifications
                        if s['metadata']['role'] in ('support', 'diagnostic')}
        global_audit.check('no_support_diagnostic_group_enters_statistical_pools', sorted(statistical_groups & other_groups), [])
        native_seeds = [s['stream_seed'] + component for s in specifications for component in range(4)]
        global_audit.check('distinct_declared_kernel_participant_seeds', len(set(native_seeds)), len(native_seeds))
        global_audit.check('generation_and_kernel_participant_seed_domains_disjoint',
                           sorted(set(generation_seeds) & set(native_seeds)), [])
        global_audit.check('feature_target_contract',
                           [protocol['observations']['cutoff_ns'], protocol['observations']['horizon_ns'],
                            protocol['observations']['probe_order_id'], protocol['observations']['statistic']],
                           [CUTOFF, HORIZON, PROBE, list(VISIBLE)])
        frozen = read(ROOT / 'freeze.json')
        for relative, expected in frozen['sha256'].items():
            global_audit.check('frozen_identity:' + relative, file_hash(ROOT / relative), expected)
        provenance = read(ROOT / 'source-provenance.json')
        for source in provenance['patched_files']:
            global_audit.check('native_source_identity:' + source['path'],
                               file_hash(ROOT / 'source' / 'patched' / source['path']), source['sha256'])
        native_summary = read(ROOT / 'native-summary.json')
        global_audit.check('completed_native_execution_receipt',
                           [native_summary['completed'], native_summary['engine_runs'], native_summary['protocol_sha256']],
                           [True, 3212, file_hash(ROOT / 'protocol.json')])
        receipts = [json.loads(line) for line in (ROOT / 'native-executions.jsonl').read_text().splitlines()]
        global_audit.check('complete_native_execution_names_and_ordinals',
                           [(r['name'], r['ordinal']) for r in receipts],
                           [(s['name'], i + 1) for i, s in enumerate(specifications)])
        native_hashes = {r['name']: r['sha256'] for r in receipts}
        expected_files = {s['name'] + '.json' for s in specifications}
        global_audit.check('capture_inventory', sorted(p.name for p in (ROOT / 'episodes').glob('*.json')), sorted(expected_files))
        with partial.open('w', encoding='utf-8') as output:
            for spec in specifications:
                path = ROOT / 'episodes' / (spec['name'] + '.json')
                audit = Audit(spec['name'])
                try:
                    episode = read(path)
                    audit.check('native_execution_capture_digest', file_hash(path), native_hashes[spec['name']])
                    derived = validate_capture(spec, episode, audit)
                finally:
                    summaries.append(dict(**audit.summary(), capture_sha256=file_hash(path)))
                    total_checks += audit.count
                record = dict(name=spec['name'], metadata=deepcopy(spec['metadata']), **derived,
                              capture_sha256=summaries[-1]['capture_sha256'])
                rows_by_name[spec['name']] = record
                role = spec['metadata']['role']
                if role != 'diagnostic':
                    output.write(canonical(record) + '\n')
                    written_rows += 1
                if role == 'support':
                    cell = tuple(derived['features'][key] for key in VISIBLE)
                    world = cell + (derived['labels']['H'], spec['metadata']['J'])
                    support_worlds.append(world)
                    if cell in support_cells:
                        global_audit.check('complete_transcript_sufficiency:' + spec['name'],
                                           derived['admissible_sha256'], support_cells[cell])
                    else:
                        support_cells[cell] = derived['admissible_sha256']
                if len(summaries) % 128 == 0:
                    print(f'Validated {len(summaries)}/{len(specifications)} saved captures', flush=True)
        expected_worlds = list(product((0, 1), (0, 1), (2, 4), (2, 3), ('bid', 'ask'), range(3), range(4)))
        global_audit.check('complete_unique_native_support', sorted(support_worlds), sorted(expected_worlds))
        global_audit.check('validated_statistical_and_support_row_count', written_rows, 3200)
        global_audit.check('visible_support_cell_count', len(support_cells), 32)
        global_audit.check('visible_transcript_cells_distinct', len(set(support_cells.values())), 32)
        validate_relations(specifications, rows_by_name, global_audit)
        reference = exact_reference(protocol, rows_by_name, global_audit)
    except (InvalidCapture, KeyError, ValueError, OSError, AssertionError) as exc:
        failure = dict(type=type(exc).__name__, message=str(exc))
    result = dict(stage='Independent pre-fit validity gate; no native engine or model import',
                  validator_sha256=file_hash(Path(__file__)), protocol_sha256=file_hash(ROOT / 'protocol.json'),
                  freeze_sha256=file_hash(ROOT / 'freeze.json'), captures=summaries,
                  structure=global_audit.summary(), check_count=total_checks + global_audit.count,
                  completed_captures=len(summaries), valid=failure is None, failure=failure,
                  validated_row_count=written_rows,
                  validated_rows_sha256=file_hash(partial) if failure is None else None,
                  exact_reference=reference,
                  native_history_scope='Incoming per-match quantities and rejection preservation; no complete history oracle.',
                  dataset_scope='Only statistical/support rows; diagnostics excluded; audit metadata separate from observed features.')
    (ROOT / 'study-validation.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    if failure:
        raise SystemExit('Validity gate failed; retain partial rows and inspect study-validation.json.')
    partial.replace(ROOT / 'validated_rows.jsonl')
    print(json.dumps(dict(valid=True, captures=len(summaries), checks=result['check_count'])))


def validate_relations(specifications, rows, audit):
    """Check fresh diagnostic executions without admitting them as statistical rows."""
    diagnostics = [spec for spec in specifications if spec['metadata']['role'] == 'diagnostic']
    audit.check('diagnostic_capture_count', len(diagnostics), 12)
    audit.check('diagnostic_relation_counts', dict(Counter(s['relation']['kind'] for s in diagnostics)),
                dict(replay=4, prefix=4, relabel=4))
    for spec in diagnostics:
        relation = spec['relation']
        parent = relation['source']
        kind = relation['kind']
        captured = read(ROOT / 'episodes' / (spec['name'] + '.json'))
        original = read(ROOT / 'episodes' / (parent + '.json'))
        if kind == 'replay':
            for key in ('events', 'receipts', 'observations', 'submissions', 'cutoff_ns', 'admissible'):
                audit.check('replay:' + spec['name'] + ':' + key, captured[key], original[key])
        elif kind == 'prefix':
            audit.check('prefix_flag:' + spec['name'], spec.get('prefix'), True)
            audit.check('prefix_events:' + spec['name'], captured['events'],
                        [e for e in original['events'] if e['offset_ns'] <= CUTOFF + 1])
            audit.check('prefix_admissible:' + spec['name'], captured['admissible'], original['admissible'])
        elif kind == 'relabel':
            for key in ('observations', 'submissions', 'admissible'):
                audit.check('relabel:' + spec['name'] + ':' + key, captured[key], original[key])
            audit.check('relabel_labels:' + spec['name'], rows[spec['name']]['labels'], rows[parent]['labels'])
        else:
            raise InvalidCapture('Unknown frozen diagnostic relation: ' + str(kind))


def exact_reference(protocol, rows, audit):
    """Weight exhaustive native-checked labels; do not call the model decoder."""
    law = protocol['law']
    audit.check('frozen_hidden_conditional_parameters', law['e'],
                dict(zero=[0.25, 0.25], informative=[0.1, 0.4], shift=[0.4, 0.1]))
    flow = [[Fraction(str(p)) for p in row] for row in law['J_probabilities']]
    audit.check('frozen_future_probability_mass', [str(sum(row)) for row in flow], ['1', '1'])
    audit.check('frozen_future_probabilities', [[str(p) for p in row] for row in flow],
                [['1/10', '13/20', '1/20', '1/5'], ['1/10', '1/20', '13/20', '1/5']])
    support = {}
    for row in rows.values():
        if row['metadata']['role'] == 'support':
            key = tuple(row['features'][field] for field in VISIBLE) + (row['labels']['H'], row['metadata']['J'])
            support[key] = row['labels']['Y']
    survival = {}
    for c, z, k, q, side, h in product((0, 1), (0, 1), (2, 4), (2, 3), ('bid', 'ask'), range(3)):
        value = sum(flow[z][j] * support[c, z, k, q, side, h, j] for j in range(4))
        if (z, h) in survival:
            audit.check('native_survival_nuisance_invariance:' + str((c, z, k, q, side, h)),
                        str(value), str(survival[z, h]))
        survival[z, h] = value
    audit.check('independently_derived_survival_kernel',
                [[str(survival[z, h]) for h in range(3)] for z in range(2)],
                [['9/10', '1/4', '1/5'], ['9/10', '17/20', '1/5']])
    result = []
    for condition in ('zero', 'informative', 'shift'):
        for c, z in product((0, 1), (0, 1)):
            e = Fraction(str(law['e'][condition][c]))
            hidden = [e, 1 - 2 * e, e]
            audit.check(f'queue_probability_mass:{condition}:{c}:{z}',
                        [str(sum(hidden)), all(p > 0 for p in hidden)], ['1', True])
            p = sum(hidden[h] * survival[z, h] for h in range(3))
            rich_risk = sum(hidden[h] * survival[z, h] * (1 - survival[z, h]) for h in range(3))
            result.append(dict(condition=condition, C=c, Z=z, probability=float(p), exact_probability=str(p),
                               irreducible_coarse_brier=float(p * (1 - p)), current_rich_brier=float(rich_risk),
                               posterior_H=[float(v) for v in hidden]))
    return dict(method='Exact rational joint-law weighting of all 384 independently native-checked support labels',
                survival=[[float(survival[z, h]) for h in range(3)] for z in range(2)], cells=result,
                shift_scope='Shift-law reference has external law knowledge; it is not deployed adaptation.')


if __name__ == '__main__':
    main()
