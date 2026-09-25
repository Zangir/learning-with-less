"""Frozen, bounded diagnostic of the unmodified ABIDES kernel and exchange."""
from pathlib import Path
from copy import deepcopy
import hashlib
import importlib.metadata
import json
import os
import random
import sys
import time

ROOT = (Path(__file__).resolve().parents[1] / 'runtime')
SOURCE = ROOT / 'source/abides'
SEED = 20260919
SYMBOL = 'SYNTH'
random.seed(SEED)
os.environ.update(OMP_NUM_THREADS='2', OPENBLAS_NUM_THREADS='2', MKL_NUM_THREADS='2')
import numpy as np
import pandas as pd
import pandas.io.json

# A relocated import gets an address label; matching logic gets no house renovation.
pandas.io.json.json_normalize = pd.json_normalize
sys.path.insert(0, str(SOURCE))
from Kernel import Kernel
from agent.Agent import Agent
from agent.ExchangeAgent import ExchangeAgent
from message.Message import Message
from util.order.Order import Order
from util.order.LimitOrder import LimitOrder
import util.util as util

util.silent_mode = True
START = pd.Timestamp('2025-01-01 09:30:00')


def serial(value):
    if isinstance(value, dict):
        return {str(k): serial(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [serial(v) for v in value]
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, Order):
        return serial(value.__dict__)
    if isinstance(value, np.generic):
        return value.item()
    return value


def encoded(value):
    return json.dumps(serial(value), sort_keys=True, separators=(',', ':')).encode()


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def save(name, value):
    (ROOT / name).write_text(json.dumps(serial(value), indent=2) + '\n', encoding='utf-8')


def snapshot(book):
    return [dict(side=side, price=o.limit_price, order_id=o.order_id,
                 participant=o.agent_id, quantity=o.quantity, queue_position=position,
                 time_placed_ns=o.time_placed.value)
            for side, levels in [('bid', book.bids), ('ask', book.asks)]
            for level in levels for position, o in enumerate(level)]


def coarse(rows):
    """Causal L2 view: price and total visible quantity, no identities or counts."""
    totals = {}
    for row in rows:
        key = row['side'], row['price']
        totals[key] = totals.get(key, 0) + row['quantity']
    return [dict(side=s, price=p, quantity=q) for (s, p), q in
            sorted(totals.items(), key=lambda kv: (kv[0][0], -kv[0][1] if kv[0][0] == 'bid' else kv[0][1]))]


class ObservedExchange(ExchangeAgent):
    """Passive capture around native methods; all orders still traverse Kernel."""
    def __init__(self):
        super().__init__(0, 'Exchange', 'Exchange', START, START + pd.Timedelta(10000, 'ns'),
                         [SYMBOL], book_freq=None, pipeline_delay=0, computation_delay=0,
                         stream_history=100, log_orders=False, random_state=np.random.RandomState(SEED))
        self.log_to_file = False
        self.events = []
        self.active = None

    def receiveMessage(self, currentTime, msg):
        book = self.order_books[SYMBOL]
        event = dict(sequence=len(self.events), timestamp_ns=currentTime.value,
                     offset_ns=currentTime.value - START.value, message_uniq=msg.uniq,
                     input=serial(deepcopy(msg.body)), before=snapshot(book), outgoing=[])
        self.active = event
        super().receiveMessage(currentTime, msg)
        event.update(after=snapshot(book), native_history=serial(deepcopy(book.history)))
        event['l2'] = coarse(event['after'])
        self.events.append(event)
        self.active = None

    def sendMessage(self, recipientID, msg):
        if self.active is not None:
            self.active['outgoing'].append(dict(recipient=recipientID, message_uniq=msg.uniq,
                                                body=serial(deepcopy(msg.body))))
        super().sendMessage(recipientID, msg)


class ScriptedParticipant(Agent):
    def __init__(self, identifier, actions, stream_seed):
        super().__init__(identifier, f'Participant{identifier}', 'SyntheticScript',
                         np.random.RandomState(stream_seed + identifier), log_to_file=False)
        self.actions = actions
        self.orders = {}
        self.receipts = []

    def kernelStarting(self, startTime):
        for offset in sorted({a['at_ns'] for a in self.actions}):
            self.setWakeup(startTime + pd.Timedelta(offset, 'ns'))

    def wakeup(self, currentTime):
        super().wakeup(currentTime)
        for a in self.actions:
            if START + pd.Timedelta(a['at_ns'], 'ns') != currentTime:
                continue
            kind = a['kind']
            if kind == 'LIMIT_ORDER':
                order = LimitOrder(self.id, currentTime, SYMBOL, a['quantity'],
                                   a['side'] == 'bid', a['price'], order_id=a['order_id'])
                self.orders[order.order_id] = deepcopy(order)
                body = dict(msg=kind, sender=self.id, order=order)
            else:
                order = deepcopy(self.orders[a['order_id']])
                body = dict(msg=kind, sender=self.id, order=order)
                if kind == 'MODIFY_ORDER':
                    replacement = deepcopy(order)
                    replacement.quantity = a['quantity']
                    body['new_order'] = replacement
                    self.orders[order.order_id] = deepcopy(replacement)
            self.sendMessage(0, Message(body))

    def receiveMessage(self, currentTime, msg):
        super().receiveMessage(currentTime, msg)
        self.receipts.append(dict(timestamp_ns=currentTime.value, message_uniq=msg.uniq,
                                  body=serial(deepcopy(msg.body))))


def run_episode(spec, suffix, prefix=None):
    np.random.seed(SEED)
    Order.order_id, Order._order_ids, Message.uniq = 0, set(), 0
    actions = [a for a in spec['actions'] if prefix is None or a['at_ns'] <= prefix]
    exchange = ObservedExchange()
    agents = [exchange] + [ScriptedParticipant(i, [a for a in actions if a['participant'] == i],
                                               spec['stream_seed']) for i in range(1, 4)]
    kernel = Kernel('T012 actual ABIDES diagnostic', random_state=np.random.RandomState(spec['stream_seed']))
    kernel.runner(agents=agents, startTime=START, stopTime=START + pd.Timedelta(10000, 'ns'),
                  defaultComputationDelay=0, defaultLatency=1, latencyNoise=[1.0],
                  skip_log=True, seed=SEED, oracle=None,
                  log_dir=str(ROOT / 'native-logs' / f'{spec["name"]}-{suffix}'))
    return dict(name=spec['name'], split=spec['split'], events=exchange.events,
                receipts={str(a.id): a.receipts for a in agents[1:]})


def validate_episode(episode):
    checks, trades = [], []
    expected_state = {}

    def check(event, name, observed, expected):
        checks.append(dict(sequence=event['sequence'], name=name, observed=observed,
                           expected=expected, passed=observed == expected))

    for event in episode['events']:
        inp, before, after = event['input'], event['before'], event['after']
        order, kind = inp['order'], inp['msg']
        oid = str(order['order_id'])
        notifications = [o['body'] for o in event['outgoing']]
        fills = [n['order'] for n in notifications if n['msg'] == 'ORDER_EXECUTED']
        check(event, 'execution_messages_paired', len(fills) % 2, 0)
        eligible = [deepcopy(r) for r in before if r['side'] != ('bid' if order['is_buy_order'] else 'ask')]
        volume = 0
        if kind == 'LIMIT_ORDER':
            expected_state[oid] = dict(quantity=order['quantity'], participant=order['agent_id'],
                                       price=order['limit_price'], side='bid' if order['is_buy_order'] else 'ask')
        for j in range(0, len(fills), 2):
            incoming, resting = fills[j:j+2]
            q = incoming['quantity']
            volume += q
            check(event, f'pair_{j//2}_quantity', q, resting['quantity'])
            check(event, f'pair_{j//2}_incoming_id', incoming['order_id'], order['order_id'])
            check(event, f'pair_{j//2}_opposite_sides', incoming['is_buy_order'] != resting['is_buy_order'], True)
            check(event, f'pair_{j//2}_same_fill_price', incoming['fill_price'], resting['fill_price'])
            check(event, f'pair_{j//2}_price_time_priority', resting['order_id'], eligible[0]['order_id'])
            check(event, f'pair_{j//2}_resting_price', incoming['fill_price'], eligible[0]['price'])
            check(event, f'pair_{j//2}_within_limit', incoming['fill_price'] <= order['limit_price']
                  if order['is_buy_order'] else incoming['fill_price'] >= order['limit_price'], True)
            eligible[0]['quantity'] -= q
            if eligible[0]['quantity'] == 0:
                eligible.pop(0)
            expected_state[oid]['quantity'] -= q
            expected_state[str(resting['order_id'])]['quantity'] -= q
            trades.append(dict(episode=episode['name'], sequence=event['sequence'],
                               timestamp_ns=event['timestamp_ns'], trade_index=j//2,
                               aggressor_order=order['order_id'], resting_order=resting['order_id'],
                               resting_participant=resting['agent_id'], quantity=q, price=incoming['fill_price']))
        if kind == 'LIMIT_ORDER':
            expected_volume = sum(r['quantity'] for r in before) + order['quantity'] - 2 * volume
        elif kind == 'CANCEL_ORDER':
            cancelled = [n['order'] for n in notifications if n['msg'] == 'ORDER_CANCELLED']
            check(event, 'cancel_ack_count', len(cancelled), 1)
            actual_cancel = sum(o['quantity'] for o in cancelled)
            check(event, 'cancel_residual', actual_cancel, expected_state[oid]['quantity'])
            expected_state[oid]['quantity'] = 0
            expected_volume = sum(r['quantity'] for r in before) - actual_cancel
        else:
            old_quantity = expected_state[oid]['quantity']
            expected_state[oid]['quantity'] = inp['new_order']['quantity']
            expected_volume = sum(r['quantity'] for r in before) + inp['new_order']['quantity'] - old_quantity
        check(event, 'visible_volume_conservation', sum(r['quantity'] for r in after), expected_volume)
        check(event, 'unique_live_order_ids', len({r['order_id'] for r in after}), len(after))
        check(event, 'positive_live_quantities', all(r['quantity'] > 0 for r in after), True)
        expected = {k: v for k, v in expected_state.items() if v['quantity'] > 0}
        observed = {str(r['order_id']): {k: r[k] for k in ('quantity', 'participant', 'price', 'side')} for r in after}
        check(event, 'per_order_lifecycle_conservation', observed, expected)
        bids, asks = [r['price'] for r in after if r['side'] == 'bid'], [r['price'] for r in after if r['side'] == 'ask']
        check(event, 'uncrossed_book', not bids or not asks or max(bids) < min(asks), True)
        if fills:
            native = next(h[oid] for h in event['native_history'] if oid in h)
            check(event, 'native_incoming_history_matches_executions',
                  sum(t[1] for t in native['transactions']), volume)
    return dict(name=episode['name'], checks=checks, trades=trades,
                failed=[c for c in checks if not c['passed']])


def main():
    started = time.perf_counter()
    protocol = json.loads((ROOT / 'protocol.json').read_text())
    frozen = json.loads((ROOT / 'freeze.json').read_text())
    for rel, sha in frozen['sha256'].items():
        assert hashlib.sha256((ROOT / rel).read_bytes()).hexdigest() == sha, rel
    source_manifest = json.loads((ROOT / 'source-slice.json').read_text())
    for item in source_manifest['files']:
        assert hashlib.sha256((SOURCE / item['path']).read_bytes()).hexdigest() == item['sha256']
    episodes, validation, replays = [], [], []
    for spec in protocol['episodes']:
        first = run_episode(spec, 'first')
        second = run_episode(spec, 'replay')
        episodes.append(first)
        validation.append(validate_episode(first))
        replays.append(dict(name=spec['name'], first_sha256=digest(first), replay_sha256=digest(second),
                            identical=first == second))
        save(f'episodes/{spec["name"]}.json', first)
        save(f'episodes/{spec["name"]}-replay.json', second)
    pair = [e for e in episodes if e['name'].startswith('holdout_cancel_')]
    paths = [[dict(sequence=e['sequence'], timestamp_ns=e['timestamp_ns'], l2=e['l2']) for e in p['events']] for p in pair]
    probe_fills = [sum(t['quantity'] for v in validation if v['name'] == p['name']
                       for t in v['trades'] if t['resting_order'] == 201) for p in pair]
    causal = []
    for spec in protocol['episodes']:
        if not spec['name'].startswith('holdout_cancel_'):
            continue
        truncated = run_episode(spec, 'prefix', prefix=400)
        full = next(e for e in episodes if e['name'] == spec['name'])
        same = truncated['events'] == full['events'][:4]
        causal.append(dict(name=spec['name'], prefix_events=4, identical=same,
                           prefix_sha256=digest(truncated['events'])))
        save(f'episodes/{spec["name"]}-prefix.json', truncated)
    failures = [dict(episode=v['name'], **c) for v in validation for c in v['failed']]
    save('validation.json', validation)
    save('replay.json', replays)
    save('causality.json', causal)
    save('trades.json', [t for v in validation for t in v['trades']])
    save('runtime-environment.json', dict(python=sys.version, platform=sys.platform,
          packages={p: importlib.metadata.version(p) for p in ('numpy', 'pandas', 'scipy', 'tqdm')},
          compatibility_alias='pandas.io.json.json_normalize = pandas.json_normalize',
          matching_source_modified=False))
    summary = dict(seed=SEED, engine_runs=12, recorded_exchange_actions=sum(len(e['events']) for e in episodes),
                   checks=sum(len(v['checks']) for v in validation), failed_checks=failures,
                   deterministic_replay=all(r['identical'] for r in replays),
                   causal_prefix=all(c['identical'] for c in causal),
                   identical_coarse_paths=paths[0] == paths[1], probe_fills=probe_fills,
                   runtime_seconds=time.perf_counter() - started, learned_model_fitted=False)
    save('summary.json', summary)
    assert summary['deterministic_replay'] and summary['causal_prefix'] and summary['identical_coarse_paths']
    assert probe_fills == [3, 1]
    allowed = set(protocol['anticipated_failed_checks'])
    assert failures and all(f"{f['episode']}:{f['sequence']}:{f['name']}" in allowed for f in failures)
    assert {f"{f['episode']}:{f['sequence']}:{f['name']}" for f in failures} == allowed
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == '__main__':
    main()
