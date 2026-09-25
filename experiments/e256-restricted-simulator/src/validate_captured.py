"""Independently audit saved restricted-engine traces; never import ABIDES."""
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

ROOT = (Path(__file__).resolve().parents[1] / 'runtime')
START_NS = 1735723800000000000
IDENTITY = ('order_id', 'agent_id', 'symbol', 'is_buy_order', 'limit_price', 'time_placed', 'tag', 'fill_price')
CHECKS = []


def read(name):
    return json.loads((ROOT / name).read_text(encoding='utf-8-sig'))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def nanoseconds(iso):
    whole, _, fraction = iso.partition('.')
    seconds = int(datetime.fromisoformat(whole).replace(tzinfo=timezone.utc).timestamp())
    return seconds * 1_000_000_000 + int(fraction.ljust(9, '0') or '0')


def check(group, name, observed, expected, sequence=None):
    # Today's evidence should not quietly become tomorrow's ledger.
    CHECKS.append(dict(group=group, sequence=sequence, name=name, observed=deepcopy(observed),
                       expected=deepcopy(expected), passed=observed == expected))


def rows(ledger):
    orders = sorted(ledger.values(), key=lambda o: (
        0 if o['raw']['is_buy_order'] else 1,
        -o['raw']['limit_price'] if o['raw']['is_buy_order'] else o['raw']['limit_price'], o['priority']))
    positions, result = Counter(), []
    for entry in orders:
        order = entry['raw']
        side = 'bid' if order['is_buy_order'] else 'ask'
        price = order['limit_price']
        result.append(dict(side=side, price=price, order_id=order['order_id'], participant=order['agent_id'],
                           quantity=order['quantity'], queue_position=positions[side, price],
                           time_placed_ns=entry['time_placed_ns']))
        positions[side, price] += 1
    return result


def aggregate(state):
    levels = Counter()
    for row in state:
        levels[row['side'], row['price']] += row['quantity']
    return [dict(side=side, price=price, quantity=quantity)
            for (side, price), quantity in sorted(levels.items(), key=lambda item:
                (item[0][0], -item[0][1] if item[0][0] == 'bid' else item[0][1]))]


def decision(body, ledger, seen, history):
    """The declared adapter policy, evaluated against independently reconstructed live state."""
    kind, order = body['msg'], body['order']
    if kind not in ('LIMIT_ORDER', 'CANCEL_ORDER', 'MODIFY_ORDER'):
        return None, 'UNSUPPORTED_OPERATION'
    if body['sender'] != order['agent_id']:
        return None, 'OWNER_MISMATCH'
    if order['symbol'] != 'SYNTH':
        return None, 'UNSUPPORTED_SYMBOL'
    if kind == 'LIMIT_ORDER':
        if type(order['quantity']) is not int or order['quantity'] <= 0:
            return None, 'INVALID_QUANTITY'
        if type(order['limit_price']) is not int or order['limit_price'] <= 0:
            return None, 'INVALID_PRICE'
        if order['order_id'] in seen:
            return None, 'REUSED_ORDER_ID'
        return deepcopy(body), None
    entry = ledger.get(order['order_id'])
    if entry is None:
        return None, 'ORDER_NOT_UNIQUELY_LIVE'
    live = entry['raw']
    if any(order.get(key) != live.get(key) for key in IDENTITY):
        return None, 'LIVE_IDENTITY_MISMATCH'
    clean = dict(msg=kind, sender=body['sender'], order=deepcopy(live))
    if kind == 'MODIFY_ORDER':
        if sum(str(order['order_id']) in h for h in history) != 1:
            return None, 'ORDER_HISTORY_UNAVAILABLE'
        replacement = body['new_order']
        if any(replacement.get(key) != live.get(key) for key in IDENTITY):
            return None, 'AMENDMENT_IDENTITY_CHANGE'
        quantity = replacement['quantity']
        if type(quantity) is not int or not 0 < quantity < live['quantity']:
            return None, 'AMENDMENT_NOT_STRICT_REDUCTION'
        clean['new_order'] = deepcopy(live)
        clean['new_order']['quantity'] = quantity
    return clean, None


def match_and_apply(clean, ledger, seen, sequence, placement_ns):
    """Independent flat ledger; priority comes from frozen arrivals, never native queue position."""
    kind, order = clean['msg'], clean['order']
    oid, matches, acknowledgments = order['order_id'], [], []
    if kind == 'LIMIT_ORDER':
        seen.add(oid)
        residual = order['quantity']
        candidates = sorted((entry for entry in ledger.values()
                             if entry['raw']['is_buy_order'] != order['is_buy_order']),
                            key=lambda entry: (
                                entry['raw']['limit_price'] if order['is_buy_order'] else -entry['raw']['limit_price'],
                                entry['priority']))
        for entry in candidates:
            resting = entry['raw']
            price = resting['limit_price']
            crosses = price <= order['limit_price'] if order['is_buy_order'] else price >= order['limit_price']
            if not residual or not crosses:
                break
            quantity = min(residual, resting['quantity'])
            incoming_fill, resting_fill = deepcopy(order), deepcopy(resting)
            for fill in (incoming_fill, resting_fill):
                fill.update(quantity=quantity, fill_price=price)
            matches.append((incoming_fill, resting_fill))
            residual -= quantity
            resting['quantity'] -= quantity
            if resting['quantity'] == 0:
                del ledger[resting['order_id']]
        if residual:
            live = deepcopy(order)
            live['quantity'] = residual
            ledger[oid] = dict(raw=live, priority=sequence, time_placed_ns=placement_ns)
            acknowledgments.append(dict(msg='ORDER_ACCEPTED', order=deepcopy(live)))
    elif kind == 'CANCEL_ORDER':
        acknowledgments.append(dict(msg='ORDER_CANCELLED', order=deepcopy(ledger.pop(oid)['raw'])))
    else:
        ledger[oid]['raw'] = deepcopy(clean['new_order'])
        acknowledgments.append(dict(msg='ORDER_MODIFIED', new_order=deepcopy(clean['new_order'])))
    return matches, acknowledgments


def public_receipt(receipt):
    body = receipt['body']
    result = dict(delivery_ns=receipt['delivery_ns'], kind=body['msg'])
    if body['msg'] == 'ORDER_REJECTED':
        result.update(own_order_id=body['order_id'], reason=body['reason'])
    else:
        order = body.get('order', body.get('new_order'))
        result.update(own_order_id=order['order_id'], quantity=order['quantity'],
                      side='bid' if order['is_buy_order'] else 'ask', price=order['limit_price'],
                      fill_price=order.get('fill_price'))
    return result


def own_submission(event):
    body = event['input']
    order = body['new_order'] if body['msg'] == 'MODIFY_ORDER' else body['order']
    return dict(sent_ns=event['offset_ns']-1, kind=body['msg'], own_order_id=order['order_id'],
                quantity=order['quantity'], side='bid' if order['is_buy_order'] else 'ask',
                price=order.get('limit_price'))


def compare_action(group, event, action):
    body, order = event['input'], event['input']['order']
    sequence = event['sequence']
    check(group, 'frozen_action_dispatch',
          [event['offset_ns'], body['sender'], body['msg'], order['order_id']],
          [action['at_ns']+1, action['participant'], action['kind'], action['order_id']], sequence)
    if action['kind'] in ('LIMIT_ORDER', 'MARKET_ORDER'):
        check(group, 'frozen_submitted_quantity_side', [order['quantity'], order['is_buy_order']],
              [action['quantity'], action['side'] == 'bid'], sequence)
        if action['kind'] == 'LIMIT_ORDER':
            check(group, 'frozen_submitted_price', order['limit_price'], action['price'], sequence)
    if action['kind'] == 'MODIFY_ORDER':
        replacement = body['new_order']
        check(group, 'frozen_requested_reduction', replacement['quantity'], action['quantity'], sequence)
        for key in ('limit_price', 'is_buy_order', 'agent_id', 'symbol', 'order_id', 'tag', 'fill_price'):
            if 'new_'+key in action:
                check(group, 'frozen_requested_'+key, replacement[key], action['new_'+key], sequence)


def validate(spec, episode, group):
    ledger, seen, history, trades = {}, set(), [{}], []
    expected_receipts, expected_observations = [], []
    actions = [a for _, a in sorted(enumerate(spec['actions']),
               key=lambda item: (item[1]['at_ns'], item[1]['participant'], item[0]))]
    check(group, 'action_count', len(episode['events']), len(actions))
    last_update = None
    for index, (event, action) in enumerate(zip(episode['events'], actions)):
        compare_action(group, event, action)
        check(group, 'consecutive_event_sequence', event['sequence'], index, index)
        check(group, 'absolute_exchange_timestamp', event['timestamp_ns'], START_NS+event['offset_ns'], index)
        check(group, 'independent_before_state', event['before'], rows(ledger), index)
        check(group, 'history_continuity', event['before_history'], history, index)
        check(group, 'last_update_continuity', event['before_last_update_ns'], last_update, index)
        clean, reason = decision(event['input'], ledger, seen, history)
        check(group, 'independent_admission', event['accepted'], reason is None, index)
        check(group, 'rejection_reason', event['rejection'], reason, index)
        check(group, 'canonical_live_native_request', event['actual_input'], clean, index)
        if reason is None:
            matches, expected_ack = match_and_apply(clean, ledger, seen, index, START_NS+action['at_ns'])
            last_update = event['timestamp_ns']
        else:
            matches = []
            expected_ack = [dict(msg='ORDER_REJECTED', order_id=event['input']['order']['order_id'], reason=reason)]
            check(group, 'rejection_preserves_native_history', event['native_history'], history, index)
            check(group, 'rejection_preserves_ordered_book', event['after'], event['before'], index)
        check(group, 'native_last_update_contract', event['after_last_update_ns'], last_update, index)

        outgoing = event['outgoing']
        fills = [message['body'] for message in outgoing if message['body']['msg'] == 'ORDER_EXECUTED']
        expected_fills = [dict(msg='ORDER_EXECUTED', order=order) for pair in matches for order in pair]
        check(group, 'independent_price_fifo_partial_executions', fills, expected_fills, index)
        actual_ack = [message['body'] for message in outgoing
                      if message['body']['msg'] not in ('ORDER_EXECUTED', 'COARSE_BOOK')]
        check(group, 'exact_lifecycle_acknowledgments', actual_ack, expected_ack, index)
        for pair_index in range(0, len(fills)-1, 2):
            incoming, resting = fills[pair_index]['order'], fills[pair_index+1]['order']
            trades.append(dict(sequence=index, aggressor_order=incoming['order_id'],
                               resting_order=resting['order_id'], resting_participant=resting['agent_id'],
                               quantity=incoming['quantity'], price=incoming['fill_price']))
        state = event['after']
        check(group, 'visible_volume_conservation', sum(row['quantity'] for row in state),
              sum(entry['raw']['quantity'] for entry in ledger.values()), index)
        check(group, 'unique_live_order_ids', len({row['order_id'] for row in state}), len(state), index)
        check(group, 'positive_integer_live_quantities',
              all(type(row['quantity']) is int and row['quantity'] > 0 for row in state), True, index)
        check(group, 'independent_ordered_state', state, rows(ledger), index)
        check(group, 'coarse_aggregate', event['l2'], aggregate(state), index)
        if matches:
            oid = str(clean['order']['order_id'])
            native = next(entry[oid] for entry in event['native_history'] if oid in entry)
            check(group, 'native_per_match_incoming_history',
                  [[nanoseconds(timestamp), quantity] for timestamp, quantity in native['transactions']],
                  [[event['timestamp_ns'], pair[0]['quantity']] for pair in matches], index)
        history = deepcopy(event['native_history'])

        expected_feed = dict(msg='COARSE_BOOK', sequence=index, exchange_ns=event['offset_ns'],
                             publish_ns=event['offset_ns'], levels=aggregate(state))
        feed = [message for message in outgoing if message['body']['msg'] == 'COARSE_BOOK']
        check(group, 'one_anonymous_feed_per_event',
              [dict(recipient=m['recipient'], body=m['body']) for m in feed],
              [dict(recipient=1, body=expected_feed)], index)
        expected_observations.append(dict(delivery_ns=event['offset_ns']+2, payload=expected_feed))
        for message in outgoing:
            if message['body']['msg'] == 'COARSE_BOOK':
                continue
            recipient = message['recipient']
            body = message['body']
            owner = event['input']['sender'] if body['msg'] == 'ORDER_REJECTED' else body.get('order', body.get('new_order'))['agent_id']
            check(group, f'notification_{message["message_uniq"]}_owner', recipient, owner, index)
            delivery = event['offset_ns'] + (2 if recipient == 1 else 1)
            expected_receipts.append(dict(recipient=recipient, timestamp_ns=START_NS+delivery,
                                          delivery_ns=delivery, message_uniq=message['message_uniq'], body=body))

    actual_receipts = [dict(recipient=int(p), **receipt)
                       for p, receipts in episode['receipts'].items() for receipt in receipts]
    receipt_key = lambda item: (item['recipient'], item['message_uniq'])
    check(group, 'private_receipts_exact_once_payload_and_directed_latency',
          sorted(actual_receipts, key=receipt_key), sorted(expected_receipts, key=receipt_key))
    check(group, 'unique_private_receipt_identities', len({receipt_key(r) for r in actual_receipts}), len(actual_receipts))
    check(group, 'actual_delivered_feed_exact_payload_sequence_and_latency', episode['observations'], expected_observations)
    submitted = [own_submission(event) for event in episode['events'] if event['input']['sender'] == 1]
    check(group, 'own_submissions_come_from_actual_sends', episode['submissions'], submitted)
    cutoff = spec.get('cutoff_ns')
    expected_admissible = dict(
        coarse=[r for r in expected_observations if cutoff is None or r['delivery_ns'] <= cutoff],
        own_submissions=[r for r in submitted if cutoff is None or r['sent_ns'] <= cutoff],
        own_receipts=[public_receipt(r) for r in episode['receipts']['1'] if cutoff is None or r['delivery_ns'] <= cutoff])
    check(group, 'admissible_feature_allowlist_and_delivery_cutoff', episode['admissible'], expected_admissible)
    check(group, 'declared_cutoff', episode['cutoff_ns'], cutoff)
    return trades


def main():
    protocol = read('protocol.json')
    frozen = read('freeze.json')
    for relative, expected in frozen['sha256'].items():
        check('provenance', relative, sha(ROOT/relative), expected)
    expected_patched_runs = 2*len(protocol['episodes']) + sum(s.get('cutoff_ns') is not None for s in protocol['episodes'])
    expected_controls = sum(s.get('upstream_control', False) for s in protocol['episodes'])
    check('provenance', 'frozen_run_counts', protocol['run_counts'],
          dict(upstream=expected_controls, patched=expected_patched_runs))
    for variant, expected_runs in protocol['run_counts'].items():
        receipt = read(f'{variant}-run-receipt.json')
        check('provenance', variant+'_completed_engine_runs',
              [receipt['variant'], receipt['engine_runs'], receipt['completed']], [variant, expected_runs, True])
    generation = protocol['generation']
    development, independent_check, diagnostic = (set(generation[key]) for key in
                                                  ('development_seeds', 'check_seeds', 'diagnostic_seeds'))
    independent_check.add(generation['relabel_check_seed'])
    check('generation', 'disjoint_role_group_generation_seeds',
          bool(development & independent_check or development & diagnostic or independent_check & diagnostic), False)
    all_episodes, all_trades, replay_rows, prefix_rows = {}, {}, [], []
    for spec in protocol['episodes']:
        name = spec['name']
        path = f'episodes/{name}.json'
        episode = read(path)
        all_episodes[name] = episode
        all_trades[name] = validate(spec, episode, 'patched/'+name)
        replay = read(f'episodes/{name}-replay.json')
        check('replay/'+name, 'complete_capture_equality', replay, episode)
        replay_rows.append(dict(name=name, identical=replay == episode))
        if spec.get('cutoff_ns') is not None:
            prefix = read(f'episodes/{name}-prefix.json')
            selected = [event for event in episode['events'] if event['offset_ns'] <= spec['cutoff_ns']+1]
            check('prefix/'+name, 'complete_available_event_prefix', prefix['events'], selected)
            check('prefix/'+name, 'actual_delivered_feature_prefix', prefix['admissible'], episode['admissible'])
            prefix_rows.append(dict(name=name, cutoff_ns=spec['cutoff_ns'],
                                    identical_admissible=prefix['admissible'] == episode['admissible']))
        if spec.get('upstream_control'):
            validate(spec, read(f'controls/{name}.json'), 'upstream/'+name)

    def probe_fills(name):
        return sum(t['quantity'] for t in all_trades[name] if t['resting_order'] == 201)

    # Named frozen requirements are mandatory; absent generic pair metadata cannot skip them.
    names = ['legacy_cancel_ahead', 'legacy_cancel_behind']
    left, right = (all_episodes[name] for name in names)
    fills = [probe_fills(name) for name in names]
    check('legacy_pair', 'equal_admissible_delivered_inputs', left['admissible'], right['admissible'])
    check('legacy_pair', 'equal_full_delivered_anonymous_feed', left['observations'], right['observations'])
    check('legacy_pair', 'expected_probe_fills', fills, protocol['required_results']['legacy_probe_fills'])
    check('legacy_pair', 'forecast_cutoff_is_delivered_cancellation',
          [left['cutoff_ns'], right['cutoff_ns'], left['admissible']['coarse'][-1]['delivery_ns']], [403, 403, 403])
    own_submissions = [[event['input'] for event in episode['events']
                       if event['input']['msg'] == 'LIMIT_ORDER' and event['input']['order']['order_id'] == 201]
                      for episode in (left, right)]
    check('legacy_pair', 'identical_own_probe_submission', own_submissions[0], own_submissions[1])
    pair_results = [dict(name='legacy_cancel_pair', episodes=names, probe_order_id=201,
                         probe_fills=fills, equal_admissible=left['admissible'] == right['admissible'])]
    relabel_results = []
    for spec in protocol['episodes']:
        if 'private_relabel_of' not in spec:
            continue
        original, relabeled = all_episodes[spec['private_relabel_of']], all_episodes[spec['name']]
        group = 'relabel/'+spec['name']
        check(group, 'full_delivered_feed_invariant', relabeled['observations'], original['observations'])
        check(group, 'admissible_features_invariant', relabeled['admissible'], original['admissible'])
        check(group, 'probe_fill_invariant', probe_fills(spec['name']), probe_fills(spec['private_relabel_of']))
        relabel_results.append(dict(name=spec['name'], source=spec['private_relabel_of'],
                                     same_feed=relabeled['observations'] == original['observations'],
                                     same_admissible=relabeled['admissible'] == original['admissible']))
    check('relabel', 'declared_private_relabel_check_executed', len(relabel_results), 1)
    for name in ('seeded_check_20262002', 'seeded_check_20262002_relabel'):
        episode = all_episodes[name]
        boundary = [event for event in episode['events'] if event['input']['order']['order_id'] == 206]
        check('inflight/'+name, 'one_own_inflight_request', len(boundary), 1)
        event = boundary[0]
        sequence = event['sequence']
        submitted = [s for s in episode['admissible']['own_submissions'] if s['own_order_id'] == 206]
        delivered = [o for o in episode['observations'] if o['payload']['sequence'] == sequence]
        check('inflight/'+name, 'own_send_known_by_cutoff', [s['sent_ns'] for s in submitted], [402])
        check('inflight/'+name, 'source_time_precedes_delivery_cutoff_boundary',
              [event['offset_ns'], delivered[0]['payload']['publish_ns'], delivered[0]['delivery_ns'], episode['cutoff_ns']],
              [403, 403, 405, 403])
        check('inflight/'+name, 'undelivered_publication_excluded',
              any(o['payload']['sequence'] == sequence for o in episode['admissible']['coarse']), False)
        check('inflight/'+name, 'undelivered_acceptance_excluded',
              any(r['own_order_id'] == 206 for r in episode['admissible']['own_receipts']), False)

    failures = [item for item in CHECKS if not item['passed']]
    patched_failures = [item for item in failures if not item['group'].startswith('upstream/')]
    control_failures = [item for item in failures if item['group'].startswith('upstream/')]
    for spec in protocol['episodes']:
        if spec.get('upstream_control'):
            check('control_reproduction/'+spec['name'], 'native_defect_still_observed',
                  any(item['group'] == 'upstream/'+spec['name'] for item in control_failures), True)
    allowed_control_failures = {
        ('upstream/diagnostic_nonhead', 2, 'visible_volume_conservation'),
        ('upstream/diagnostic_nonhead', 2, 'unique_live_order_ids'),
        ('upstream/diagnostic_nonhead', 2, 'independent_ordered_state'),
        ('upstream/diagnostic_single_partial', 1, 'native_per_match_incoming_history'),
        ('upstream/diagnostic_multi_match', 2, 'native_per_match_incoming_history'),
    }
    observed_control_keys = {(item['group'], item['sequence'], item['name']) for item in control_failures}
    check('control_reproduction', 'exact_known_native_defect_locations',
          sorted(observed_control_keys), sorted(allowed_control_failures))
    failures = [item for item in CHECKS if not item['passed']]
    patched_failures = [item for item in failures if not item['group'].startswith('upstream/')]
    inputs = ['protocol.json', 'freeze.json', 'upstream-run-receipt.json', 'patched-run-receipt.json']
    inputs += [str(path.relative_to(ROOT)).replace('\\', '/') for folder in ('episodes', 'controls')
               for path in sorted((ROOT/folder).glob('*.json'))]
    output = dict(stage='Independent reconstruction of saved r6 captures; no engine import or execution',
                  validator_sha256=sha(Path(__file__)), input_sha256={name: sha(ROOT/name) for name in inputs},
                  checks=CHECKS, check_count=len(CHECKS), passed_check_count=sum(c['passed'] for c in CHECKS),
                  failed_checks=failures, patched_or_delivery_failures=patched_failures,
                  upstream_control_failures=control_failures, replays=replay_rows, prefixes=prefix_rows,
                  pair_results=pair_results, private_relabel_results=relabel_results,
                  scope='Finite witnessed scripts only; upstream defects remain in controls; no realism, learning or general proof.')
    (ROOT/'validation.json').write_text(json.dumps(output, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(dict(checks=len(CHECKS), patched_or_delivery_failures=len(patched_failures),
                          upstream_control_failures=len(control_failures))))
    if patched_failures:
        raise SystemExit('Restricted validation failed; inspect retained validation.json.')


if __name__ == '__main__':
    main()
