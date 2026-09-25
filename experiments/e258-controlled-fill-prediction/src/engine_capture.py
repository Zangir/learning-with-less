"""Execute a restricted native ABIDES mechanism and a delivered participant feed."""
from copy import deepcopy
from pathlib import Path
import hashlib
import json
import os
import sys

ROOT=(Path(__file__).resolve().parents[1] / 'runtime')
VARIANT=os.environ.get('T012_ENGINE_VARIANT','patched')
assert VARIANT in ('upstream','patched')
SEED=20260919
os.environ.update(OMP_NUM_THREADS='2',OPENBLAS_NUM_THREADS='2',MKL_NUM_THREADS='2')
import numpy as np
import pandas as pd
import pandas.io.json
pandas.io.json.json_normalize=pd.json_normalize
sys.path.insert(0,str(ROOT/'source'/VARIANT))
from Kernel import Kernel
from agent.Agent import Agent
from agent.ExchangeAgent import ExchangeAgent
from message.Message import Message
from util.order.Order import Order
from util.order.LimitOrder import LimitOrder
from util.order.MarketOrder import MarketOrder
import util.util as util

util.silent_mode=True
START=pd.Timestamp('2025-01-01 09:30:00')
SYMBOL='SYNTH'


def serial(value):
    if isinstance(value,dict): return {str(k):serial(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)): return [serial(v) for v in value]
    if isinstance(value,pd.Timestamp): return value.isoformat()
    if isinstance(value,Order): return serial(value.__dict__)
    if isinstance(value,np.generic): return value.item()
    return value


def save(relative,value):
    path=ROOT/relative
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(serial(value),indent=2)+'\n',encoding='utf-8')


def snapshot(book):
    return [dict(side=side,price=o.limit_price,order_id=o.order_id,participant=o.agent_id,
                 quantity=o.quantity,queue_position=i,time_placed_ns=o.time_placed.value)
            for side,levels in [('bid',book.bids),('ask',book.asks)]
            for level in levels for i,o in enumerate(level)]


def aggregate(rows):
    levels={}
    for row in rows:
        key=row['side'],row['price']
        levels[key]=levels.get(key,0)+row['quantity']
    return [dict(side=s,price=p,quantity=q) for (s,p),q in sorted(levels.items(),
            key=lambda item:(item[0][0],-item[0][1] if item[0][0]=='bid' else item[0][1]))]


class RestrictedExchange(ExchangeAgent):
    """An explicit supported-input boundary around the native exchange, not a matcher."""
    def __init__(self):
        super().__init__(0,'RestrictedExchange','Exchange',START,START+pd.Timedelta(100000,'ns'),
                         [SYMBOL],book_freq=None,pipeline_delay=0,computation_delay=0,
                         stream_history=1000,log_orders=False,random_state=np.random.RandomState(SEED))
        self.log_to_file=False
        self.events=[]
        self.active=None
        self.seen_ids=set()

    def permit(self,body):
        kind=body['msg']
        order=body['order']
        if kind not in ('LIMIT_ORDER','CANCEL_ORDER','MODIFY_ORDER'):
            return None,'UNSUPPORTED_OPERATION'
        if body['sender']!=order.agent_id:
            return None,'OWNER_MISMATCH'
        if order.symbol!=SYMBOL:
            return None,'UNSUPPORTED_SYMBOL'
        if kind=='LIMIT_ORDER':
            if type(order.quantity) is not int or order.quantity<=0:
                return None,'INVALID_QUANTITY'
            if type(order.limit_price) is not int or order.limit_price<=0:
                return None,'INVALID_PRICE'
            if order.order_id in self.seen_ids:
                return None,'REUSED_ORDER_ID'
            self.seen_ids.add(order.order_id)
            return deepcopy(body),None
        book=self.order_books[SYMBOL]
        found=[o for side in (book.bids,book.asks) for level in side for o in level if o.order_id==order.order_id]
        if len(found)!=1:
            return None,'ORDER_NOT_UNIQUELY_LIVE'
        live=found[0]
        identity=('order_id','agent_id','symbol','is_buy_order','limit_price','time_placed','tag','fill_price')
        if any(getattr(order,key)!=getattr(live,key) for key in identity):
            return None,'LIVE_IDENTITY_MISMATCH'
        clean=dict(msg=kind,sender=body['sender'],order=deepcopy(live))
        if kind=='MODIFY_ORDER':
            if sum(order.order_id in entry for entry in book.history)!=1:
                return None,'ORDER_HISTORY_UNAVAILABLE'
            new=body['new_order']
            if any(getattr(new,key)!=getattr(live,key) for key in identity):
                return None,'AMENDMENT_IDENTITY_CHANGE'
            if type(new.quantity) is not int or not 0<new.quantity<live.quantity:
                return None,'AMENDMENT_NOT_STRICT_REDUCTION'
            clean['new_order']=deepcopy(live)
            clean['new_order'].quantity=new.quantity
        return clean,None

    def logOrderBookSnapshots(self,symbol):
        raise RuntimeError('Legacy pandas archive APIs are outside the supported output contract')

    def receiveMessage(self,currentTime,msg):
        self.currentTime=currentTime
        self.setComputationDelay(0)
        book=self.order_books[SYMBOL]
        event=dict(sequence=len(self.events),timestamp_ns=currentTime.value,offset_ns=currentTime.value-START.value,
                   message_uniq=msg.uniq,input=serial(deepcopy(msg.body)),before=snapshot(book),outgoing=[],
                   before_history=serial(deepcopy(book.history)),
                   before_last_update_ns=None if book.last_update_ts is None else book.last_update_ts.value)
        self.active=event
        accepted,reason=self.permit(msg.body)
        event.update(accepted=reason is None,rejection=reason,actual_input=serial(deepcopy(accepted)))
        if reason is None:
            super().receiveMessage(currentTime,Message(accepted))
        else:
            self.sendMessage(msg.body['sender'],Message(dict(msg='ORDER_REJECTED',
                order_id=msg.body['order'].order_id,reason=reason)))
        event.update(after=snapshot(book),native_history=serial(deepcopy(book.history)),
                     after_last_update_ns=None if book.last_update_ts is None else book.last_update_ts.value)
        event['l2']=aggregate(event['after'])
        # Public packets travel through the same kernel; the observer has no backstage pass.
        self.sendMessage(1,Message(dict(msg='COARSE_BOOK',sequence=event['sequence'],
            exchange_ns=event['offset_ns'],publish_ns=self.currentTime.value-START.value,
            levels=deepcopy(event['l2']))))
        self.events.append(event)
        self.active=None

    def sendMessage(self,recipientID,msg):
        if self.active is not None:
            self.active['outgoing'].append(dict(recipient=recipientID,message_uniq=msg.uniq,
                                                body=serial(deepcopy(msg.body))))
        super().sendMessage(recipientID,msg)


class ScriptedParticipant(Agent):
    def __init__(self,identifier,actions,stream):
        super().__init__(identifier,f'SyntheticParticipant{identifier}','SyntheticScript',
                         np.random.RandomState(stream+identifier),log_to_file=False)
        self.actions=actions
        self.orders={}
        self.receipts=[]
        self.observations=[]
        self.submissions=[]

    def kernelStarting(self,startTime):
        for t in sorted({a['at_ns'] for a in self.actions}):
            self.setWakeup(startTime+pd.Timedelta(t,'ns'))

    def wakeup(self,currentTime):
        super().wakeup(currentTime)
        for a in self.actions:
            if START+pd.Timedelta(a['at_ns'],'ns')!=currentTime: continue
            kind=a['kind']
            oid=a['order_id']
            if kind in ('LIMIT_ORDER','MARKET_ORDER'):
                if kind=='LIMIT_ORDER':
                    order=LimitOrder(self.id,currentTime,SYMBOL,a['quantity'],a['side']=='bid',a['price'],order_id=oid)
                else:
                    order=MarketOrder(self.id,currentTime,SYMBOL,a['quantity'],a['side']=='bid',order_id=oid)
                self.orders.setdefault(oid,deepcopy(order))
            else:
                order=deepcopy(self.orders[oid])
            body=dict(msg=kind,sender=self.id,order=order)
            if kind=='MODIFY_ORDER':
                new=deepcopy(order)
                new.quantity=a['quantity']
                for key in ('limit_price','is_buy_order','agent_id','symbol','order_id','tag','fill_price'):
                    if 'new_'+key in a: setattr(new,key,a['new_'+key])
                if 'new_time_ns' in a:
                    new.time_placed=START+pd.Timedelta(a['new_time_ns'],'ns')
                body['new_order']=new
                # Requests may be rejected; the old local copy is deliberately allowed to be stale.
            submitted=body.get('new_order',order)
            self.submissions.append(dict(sent_ns=currentTime.value-START.value,kind=kind,
                own_order_id=submitted.order_id,quantity=submitted.quantity,
                side='bid' if submitted.is_buy_order else 'ask',price=getattr(submitted,'limit_price',None)))
            self.sendMessage(0,Message(body))

    def receiveMessage(self,currentTime,msg):
        super().receiveMessage(currentTime,msg)
        if msg.body['msg']=='COARSE_BOOK':
            assert self.id==1
            self.observations.append(dict(delivery_ns=currentTime.value-START.value,
                                          payload=serial(deepcopy(msg.body))))
        else:
            self.receipts.append(dict(timestamp_ns=currentTime.value,delivery_ns=currentTime.value-START.value,
                                      message_uniq=msg.uniq,body=serial(deepcopy(msg.body))))


def public_own_receipt(receipt):
    """Own lifecycle information is separate from the anonymous depth feed."""
    body=receipt['body']
    result=dict(delivery_ns=receipt['delivery_ns'],kind=body['msg'])
    if body['msg']=='ORDER_REJECTED':
        result.update(own_order_id=body['order_id'],reason=body['reason'])
    else:
        order=body.get('order',body.get('new_order'))
        result.update(own_order_id=order['order_id'],quantity=order['quantity'],
                      side='bid' if order['is_buy_order'] else 'ask',price=order['limit_price'],
                      fill_price=order.get('fill_price'))
    return result


def run_episode(spec,suffix,prefix=False):
    np.random.seed(SEED)
    Order.order_id,Order._order_ids,Message.uniq=0,set(),0
    cutoff=spec.get('cutoff_ns')
    actions=[a for a in spec['actions'] if not prefix or a['at_ns']<=cutoff]
    assert len(actions)<=128
    assert len({a['order_id'] for a in actions if a['kind']=='LIMIT_ORDER'})<=64
    exchange=RestrictedExchange()
    agents=[exchange]+[ScriptedParticipant(i,[a for a in actions if a['participant']==i],spec['stream_seed']) for i in range(1,4)]
    latency=[[1]*4 for _ in range(4)]
    latency[0][1]=2
    kernel=Kernel('T012 restricted native mechanism',random_state=np.random.RandomState(spec['stream_seed']))
    kernel.runner(agents=agents,startTime=START,stopTime=START+pd.Timedelta(100000,'ns'),
                  defaultComputationDelay=0,agentLatency=latency,latencyNoise=[1.0],skip_log=True,
                  seed=SEED,oracle=None,log_dir=str(ROOT/'native-logs'/f'{VARIANT}-{spec["name"]}-{suffix}'))
    observer=agents[1]
    own=[public_own_receipt(r) for r in observer.receipts]
    admissible=dict(coarse=[r for r in observer.observations if cutoff is None or r['delivery_ns']<=cutoff],
                    own_receipts=[r for r in own if cutoff is None or r['delivery_ns']<=cutoff],
                    own_submissions=[r for r in observer.submissions if cutoff is None or r['sent_ns']<=cutoff])
    return dict(name=spec['name'],split=spec['split'],variant=VARIANT,events=exchange.events,
                receipts={str(a.id):a.receipts for a in agents[1:]},observations=observer.observations,
                submissions=observer.submissions,cutoff_ns=cutoff,admissible=admissible)


def main():
    protocol=json.loads((ROOT/'protocol.json').read_text())
    frozen=json.loads((ROOT/'freeze.json').read_text())
    for rel,expected in frozen['sha256'].items():
        assert hashlib.sha256((ROOT/rel).read_bytes()).hexdigest()==expected,rel
    provenance=json.loads((ROOT/'source-provenance.json').read_text())
    for row in provenance['upstream_files' if VARIANT=='upstream' else 'patched_files']:
        assert hashlib.sha256((ROOT/'source'/VARIANT/row['path']).read_bytes()).hexdigest()==row['sha256']
    count=0
    for spec in protocol['episodes']:
        if VARIANT=='upstream':
            if not spec.get('upstream_control'): continue
            save(f'controls/{spec["name"]}.json',run_episode(spec,'control'))
            count+=1
            continue
        for suffix in ('first','replay'):
            episode=run_episode(spec,suffix)
            filename=spec['name']+('' if suffix=='first' else '-replay')
            save(f'episodes/{filename}.json',episode)
            count+=1
        if spec.get('cutoff_ns') is not None:
            save(f'episodes/{spec["name"]}-prefix.json',run_episode(spec,'prefix',prefix=True))
            count+=1
    save(f'{VARIANT}-run-receipt.json',dict(variant=VARIANT,engine_runs=count,completed=True,seed=SEED,
         native_source_modified=VARIANT=='patched',private_metadata_excluded_from_admissible=True))
    assert count==protocol['run_counts'][VARIANT]
    print(json.dumps(dict(variant=VARIANT,completed_engine_runs=count)),flush=True)


if __name__=='__main__':
    main()
