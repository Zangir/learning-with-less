"""Audit frozen ABIDES captures without importing or running the simulator."""
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path


ROOT = (Path(__file__).resolve().parents[1] / 'runtime')
START_NS = 1735723800000000000
CHECKS = []


def read(relative):
    return json.loads((ROOT / relative).read_text(encoding='utf-8-sig'))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode()


def check(episode, sequence, name, observed, expected):
    # Evidence must remember the present, even when the ledger moves on.
    CHECKS.append(dict(episode=episode, sequence=sequence, name=name,
                       observed=deepcopy(observed), expected=deepcopy(expected),
                       passed=observed == expected))


def state_rows(ledger):
    ordered = sorted(ledger.values(), key=lambda o: (
        0 if o['side'] == 'bid' else 1,
        -o['price'] if o['side'] == 'bid' else o['price'], o['priority']))
    positions = Counter()
    rows = []
    for order in ordered:
        row = {key: order[key] for key in
               ('side', 'price', 'order_id', 'participant', 'quantity', 'time_placed_ns')}
        key = row['side'], row['price']
        row['queue_position'] = positions[key]
        positions[key] += 1
        rows.append(row)
    return rows


def aggregate(rows):
    levels = Counter()
    for row in rows:
        levels[row['side'], row['price']] += row['quantity']
    return [dict(side=side, price=price, quantity=quantity)
            for (side, price), quantity in sorted(
                levels.items(), key=lambda item: (
                    item[0][0], -item[0][1] if item[0][0] == 'bid' else item[0][1]))]


def order_fields(order):
    return dict(order_id=order['order_id'], participant=order['agent_id'],
                quantity=order['quantity'], side='bid' if order['is_buy_order'] else 'ask',
                price=order['limit_price'])


def action_fields(event):
    body, offset = event['input'], event['offset_ns'] - 1
    order = body['order']
    action = dict(at_ns=offset, participant=body['sender'], kind=body['msg'],
                  order_id=order['order_id'])
    if body['msg'] == 'LIMIT_ORDER':
        action.update(quantity=order['quantity'], side='bid' if order['is_buy_order'] else 'ask',
                      price=order['limit_price'])
    elif body['msg'] == 'MODIFY_ORDER':
        action['quantity'] = body['new_order']['quantity']
    return action


def validate_episode(spec, captured):
    name = spec['name']
    ledger, derived_trades = {}, []
    ordered_actions = [a for _, a in sorted(enumerate(spec['actions']),
                       key=lambda item: (item[1]['at_ns'], item[1]['participant'], item[0]))]
    check(name, None, 'frozen_actions_processed_once_in_declared_order',
          [action_fields(e) for e in captured['events']], ordered_actions)
    expected_receipts = []
    for sequence, event in enumerate(captured['events']):
        body, order = event['input'], event['input']['order']
        oid, kind = order['order_id'], body['msg']
        check(name, sequence, 'processing_sequence', event['sequence'], sequence)
        check(name, sequence, 'timestamp_offset', event['timestamp_ns'], START_NS + event['offset_ns'])
        check(name, sequence, 'independent_before_state', event['before'], state_rows(ledger))
        expected_matches, expected_ack = [], []
        if kind == 'LIMIT_ORDER':
            check(name, sequence, 'new_order_identity_not_live', oid in ledger, False)
            side = 'bid' if order['is_buy_order'] else 'ask'
            remaining = order['quantity']
            candidates = sorted((o for o in ledger.values() if o['side'] != side),
                                key=lambda o: (o['price'] if side == 'bid' else -o['price'], o['priority']))
            for resting in candidates:
                crosses = resting['price'] <= order['limit_price'] if side == 'bid' else resting['price'] >= order['limit_price']
                if remaining == 0 or not crosses:
                    break
                quantity = min(remaining, resting['quantity'])
                expected_matches.append(dict(
                    aggressor_order=oid, aggressor_participant=order['agent_id'],
                    resting_order=resting['order_id'], resting_participant=resting['participant'],
                    quantity=quantity, price=resting['price']))
                remaining -= quantity
                resting['quantity'] -= quantity
                if resting['quantity'] == 0:
                    del ledger[resting['order_id']]
            if remaining:
                ledger[oid] = dict(order_id=oid, participant=order['agent_id'], side=side,
                                   price=order['limit_price'], quantity=remaining,
                                   time_placed_ns=START_NS + ordered_actions[sequence]['at_ns'], priority=sequence)
                expected_ack.append(dict(kind='ORDER_ACCEPTED', order_id=oid,
                                         participant=order['agent_id'], quantity=remaining,
                                         side=side, price=order['limit_price']))
        elif kind == 'CANCEL_ORDER':
            cancelled = ledger.pop(oid)
            expected_ack.append(dict(kind='ORDER_CANCELLED', **{key: cancelled[key] for key in
                                ('order_id', 'participant', 'quantity', 'side', 'price')}))
        elif kind == 'MODIFY_ORDER':
            replacement = body['new_order']
            previous = ledger[oid]
            check(name, sequence, 'quantity_only_modification_contract',
                  {k: order_fields(replacement)[k] for k in ('order_id', 'participant', 'side', 'price')},
                  {k: previous[k] for k in ('order_id', 'participant', 'side', 'price')})
            previous['quantity'] = replacement['quantity']
            expected_ack.append(dict(kind='ORDER_MODIFIED', **{key: previous[key] for key in
                                ('order_id', 'participant', 'quantity', 'side', 'price')}))
        else:
            raise ValueError(f'Undeclared captured message {kind}')

        outgoing = event['outgoing']
        fills = [message for message in outgoing if message['body']['msg'] == 'ORDER_EXECUTED']
        check(name, sequence, 'paired_execution_count', len(fills), 2 * len(expected_matches))
        actual_matches = []
        for match_index in range(len(fills) // 2):
            incoming_message, resting_message = fills[2*match_index:2*match_index+2]
            incoming, resting = incoming_message['body']['order'], resting_message['body']['order']
            check(name, sequence, f'pair_{match_index}_equal_quantity', incoming['quantity'], resting['quantity'])
            check(name, sequence, f'pair_{match_index}_equal_price', incoming['fill_price'], resting['fill_price'])
            check(name, sequence, f'pair_{match_index}_opposite_sides', incoming['is_buy_order'] != resting['is_buy_order'], True)
            actual_matches.append(dict(aggressor_order=incoming['order_id'],
                                       aggressor_participant=incoming['agent_id'],
                                       resting_order=resting['order_id'], resting_participant=resting['agent_id'],
                                       quantity=incoming['quantity'], price=incoming['fill_price']))
        check(name, sequence, 'independent_price_time_matching_and_quantities', actual_matches, expected_matches)
        derived_trades.extend(dict(sequence=sequence, **deepcopy(match)) for match in actual_matches)

        actual_ack = []
        for message in outgoing:
            notification = message['body']
            announced = notification.get('order', notification.get('new_order'))
            check(name, sequence, f'message_{message["message_uniq"]}_owner_delivery',
                  message['recipient'], announced['agent_id'])
            if notification['msg'] != 'ORDER_EXECUTED':
                actual_ack.append(dict(kind=notification['msg'], **order_fields(announced)))
            expected_receipts.append(dict(recipient=message['recipient'], message_uniq=message['message_uniq'],
                                          timestamp_ns=event['timestamp_ns'] + 1, body=notification))
        check(name, sequence, 'lifecycle_acknowledgments', actual_ack, expected_ack)

        after = event['after']
        check(name, sequence, 'visible_volume_conservation', sum(o['quantity'] for o in after),
              sum(o['quantity'] for o in ledger.values()))
        check(name, sequence, 'unique_live_order_ids', len({o['order_id'] for o in after}), len(after))
        check(name, sequence, 'positive_integer_live_quantities',
              all(type(o['quantity']) is int and o['quantity'] > 0 for o in after), True)
        check(name, sequence, 'reconstructed_order_state', after, state_rows(ledger))
        check(name, sequence, 'causal_L2_aggregation_of_actual_state', event['l2'], aggregate(after))
        if fills:
            native = next(h[str(oid)] for h in event['native_history'] if str(oid) in h)
            check(name, sequence, 'native_incoming_history_matches_executions',
                  sum(t[1] for t in native['transactions']), sum(m['quantity'] for m in expected_matches))

    actual_receipts = [dict(recipient=int(participant), **receipt)
                       for participant, receipts in captured['receipts'].items() for receipt in receipts]
    key = lambda receipt: (receipt['recipient'], receipt['message_uniq'])
    check(name, None, 'receipts_exact_payload_identity_and_one_ns_delivery',
          sorted(actual_receipts, key=key), sorted(expected_receipts, key=key))
    check(name, None, 'receipt_message_delivered_exactly_once',
          len({key(receipt) for receipt in actual_receipts}), len(actual_receipts))
    return derived_trades


def main():
    protocol, frozen = read('protocol.json'), read('freeze.json')
    for relative, expected_hash in frozen['sha256'].items():
        check('provenance', None, relative, sha(ROOT / relative), expected_hash)
    episodes, trades = {}, {}
    for spec in protocol['episodes']:
        name = spec['name']
        episode = read(f'episodes/{name}.json')
        episodes[name] = episode
        trades[name] = validate_episode(spec, episode)
        check(name, None, 'complete_capture_replay_equality', read(f'episodes/{name}-replay.json'), episode)
    original_replays = read('replay.json')
    for replay in original_replays:
        name = replay['name']
        check(name, None, 'saved_canonical_replay_hash',
              hashlib.sha256(canonical(episodes[name])).hexdigest(), replay['first_sha256'])
    lifecycle = episodes['development_lifecycle']['events'][:3]
    check('development_lifecycle', None, 'same_timestamp_tie_ids',
          [e['input']['order']['order_id'] for e in lifecycle], [101, 102, 103])
    check('development_lifecycle', None, 'same_timestamp_tie_delivery',
          [e['offset_ns'] for e in lifecycle], [101, 101, 101])
    check('development_lifecycle', None, 'same_timestamp_message_creation_order',
          [e['message_uniq'] for e in lifecycle], [0, 1, 2])
    pair_names = ['holdout_cancel_ahead', 'holdout_cancel_behind']
    paths, probe_fills, own_prefix_receipts = [], [], []
    for name in pair_names:
        episode = episodes[name]
        prefix = read(f'episodes/{name}-prefix.json')
        check(name, None, 'complete_event_prefix_equality', prefix['events'], episode['events'][:4])
        check(name, None, 'prefix_receipts_match_available_full_receipts', prefix['receipts'],
              {p: [r for r in receipts if r['timestamp_ns'] <= START_NS+402]
               for p, receipts in episode['receipts'].items()})
        paths.append([dict(sequence=e['sequence'], timestamp_ns=e['timestamp_ns'], l2=e['l2'])
                      for e in episode['events']])
        probe_fills.append(sum(t['quantity'] for t in trades[name] if t['resting_order'] == 201))
        own_prefix_receipts.append([r for r in episode['receipts']['1'] if r['timestamp_ns'] <= START_NS+401])
    check('holdout_pair', None, 'identical_entire_L2_paths', paths[0], paths[1])
    check('holdout_pair', None, 'declared_L2_volumes',
          [sum(level['quantity'] for level in event['l2']) for event in paths[0]], [3, 6, 9, 6, 2])
    check('holdout_pair', None, 'identical_probe_submission',
          episodes[pair_names[0]]['events'][1]['input'], episodes[pair_names[1]]['events'][1]['input'])
    check('holdout_pair', None, 'identical_probe_receipts_before_forecast_cutoff',
          own_prefix_receipts[0], own_prefix_receipts[1])
    check('holdout_pair', None, 'probe_fills', probe_fills, [3, 1])

    original_validation = read('validation.json')
    aliased = [dict(episode=v['name'], sequence=c['sequence'], name=c['name'],
                    observed=c['observed'], saved_expected=c['expected'])
               for v in original_validation for c in v['checks']
               if c['passed'] != (c['observed'] == c['expected'])]
    original_summary = read('summary.json')
    omitted = [dict(episode=f['episode'], sequence=f['sequence'], name=f['name'])
               for f in original_summary['failed_checks']
               if f"{f['episode']}:{f['sequence']}:{f['name']}" not in protocol['anticipated_failed_checks']]
    failures = [check for check in CHECKS if not check['passed']]
    structural = {'visible_volume_conservation', 'unique_live_order_ids', 'reconstructed_order_state'}
    unexpected = [c for c in failures if not (
        c['name'] == 'native_incoming_history_matches_executions' or
        (c['episode'] == 'diagnostic_nonhead_modify' and c['sequence'] == 2 and c['name'] in structural))]
    inputs = ['protocol.json', 'freeze.json', 'validation.json', 'summary.json',
              'replay.json', 'causality.json', 'engine.exit']
    inputs += [str(path.relative_to(ROOT)).replace('\\', '/')
               for path in sorted((ROOT / 'episodes').glob('*.json'))]
    output = dict(
        stage='Postflight analysis of existing frozen captures; no simulator import or execution',
        validator_sha256=sha(Path(__file__)), input_sha256={name: sha(ROOT/name) for name in inputs},
        original_engine_exit=int((ROOT/'engine.exit').read_text().strip()),
        original_failed_checks_preserved=len(original_summary['failed_checks']),
        original_unanticipated_history_instance=omitted,
        original_mutable_expected_records=dict(count=len(aliased), records=aliased,
            cause='check() retained nested expected_state dictionaries; later ledger mutations changed saved expected payloads after passed was computed'),
        checks=CHECKS, failed_checks=failures, additional_unexplained_failures=unexpected,
        check_count=len(CHECKS), passed_check_count=sum(c['passed'] for c in CHECKS),
        interpretation='Original execution remains nonzero. Postflight outcomes are separate diagnostic evidence, not a rerun, retrospective prespecification, or market-realism validation.')
    (ROOT/'postflight-validation.json').write_text(json.dumps(output, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({key: output[key] for key in
          ('original_engine_exit', 'check_count', 'passed_check_count')}) +
          f'; native/structural failures={len(failures)}; unexplained={len(unexpected)}; aliased_original_records={len(aliased)}')
    if unexpected:
        raise SystemExit('Postflight found additional unexplained discrepancies; inspect retained output.')


if __name__ == '__main__':
    main()
