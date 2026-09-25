"""Supplementary saved-capture audit of raw deliveries, ordering and cutoffs."""
from copy import deepcopy
from pathlib import Path
from datetime import datetime,timezone
import hashlib
import json

ROOT=(Path(__file__).resolve().parents[1] / 'runtime')
ORIGIN=1735723800000000000
CHECKS=[]


def check(capture,name,actual,expected):
    CHECKS.append(dict(capture=capture,name=name,actual=deepcopy(actual),expected=deepcopy(expected),passed=actual==expected))


def own_receipt(r):
    b=r['body']
    clean=dict(delivery_ns=r['delivery_ns'],kind=b['msg'])
    if b['msg']=='ORDER_REJECTED':
        clean.update(own_order_id=b['order_id'],reason=b['reason'])
    else:
        o=b['new_order'] if b['msg']=='ORDER_MODIFIED' else b['order']
        clean.update(own_order_id=o['order_id'],quantity=o['quantity'],side='bid' if o['is_buy_order'] else 'ask',
                     price=o['limit_price'],fill_price=o['fill_price'])
    return clean


def timestamp_ns(iso):
    whole,fraction=(iso.split('.')+[''])[:2]
    return int(datetime.fromisoformat(whole).replace(tzinfo=timezone.utc).timestamp())*10**9+int((fraction+'000000000')[:9])


def main():
    protocol=json.loads((ROOT/'protocol.json').read_text())
    specs={s['name']:s for s in protocol['episodes']}
    paths=sorted((ROOT/'episodes').glob('*.json'))+sorted((ROOT/'controls').glob('*.json'))
    for path in paths:
        ep=json.loads(path.read_text())
        label=path.relative_to(ROOT).as_posix()
        spec=specs[ep['name']]
        receipts={str(i):[] for i in range(1,4)}
        packets,submissions=[],[]
        for e in ep['events']:
            for m in e['outgoing']:
                rcv=m['recipient']
                delivery=e['offset_ns']+(2 if rcv==1 else 1)
                if m['body']['msg']=='COARSE_BOOK':
                    check(label,f'feed_recipient_{e["sequence"]}',rcv,1)
                    packets.append((delivery,m['message_uniq'],dict(delivery_ns=delivery,payload=m['body'])))
                else:
                    receipts[str(rcv)].append(dict(timestamp_ns=ORIGIN+delivery,delivery_ns=delivery,
                                                    message_uniq=m['message_uniq'],body=m['body']))
            if e['input']['sender']==1:
                body=e['input']
                order=body['new_order'] if body['msg']=='MODIFY_ORDER' else body['order']
                submissions.append(dict(sent_ns=e['offset_ns']-1,kind=body['msg'],own_order_id=order['order_id'],
                    quantity=order['quantity'],side='bid' if order['is_buy_order'] else 'ask',price=order.get('limit_price')))
            matching=[a for a in spec['actions'] if a['at_ns']==e['offset_ns']-1
                      and a['participant']==e['input']['sender'] and a['kind']==e['input']['msg']
                      and a['order_id']==e['input']['order']['order_id']]
            check(label,f'one_frozen_input_{e["sequence"]}',len(matching),1)
            if 'new_time_ns' in matching[0]:
                check(label,f'exact_requested_amendment_timestamp_{e["sequence"]}',
                      timestamp_ns(e['input']['new_order']['time_placed'])-ORIGIN,matching[0]['new_time_ns'])
        for recipient in receipts:
            receipts[recipient].sort(key=lambda r:(r['delivery_ns'],r['message_uniq']))
        packets.sort(key=lambda p:(p[0],p[1]))
        check(label,'raw_private_receipts_exact_payload_delivery_and_tie_order',ep['receipts'],receipts)
        check(label,'raw_public_deliveries_exact_payload_delivery_and_tie_order',ep['observations'],[p[2] for p in packets])
        check(label,'raw_own_submissions_actual_send_order',ep['submissions'],submissions)
        cutoff=ep['cutoff_ns']
        rebuilt=dict(coarse=[p for p in ep['observations'] if cutoff is None or p['delivery_ns']<=cutoff],
            own_receipts=[own_receipt(r) for r in ep['receipts']['1'] if cutoff is None or r['delivery_ns']<=cutoff],
            own_submissions=[s for s in ep['submissions'] if cutoff is None or s['sent_ns']<=cutoff])
        check(label,'admissible_reconstructed_from_actual_raw_arrays',ep['admissible'],rebuilt)
        if path.stem.endswith('-prefix'):
            check(label,'prefix_has_no_future_sends',all(e['offset_ns']-1<=cutoff for e in ep['events']),True)
    check('packet','capture_count',len(paths),32)
    failures=[r for r in CHECKS if not r['passed']]
    result=dict(stage='Postflight coverage extension; no engine runs, no change to frozen primary checker',
        scope='Raw transport/order and own availability, including seven prefix captures; exact requested timestamp amendment',
        source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        input_sha256={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
        checks=CHECKS,check_count=len(CHECKS),failed_checks=failures,
        native_history_limit='Primary validator covers incoming per-match quantities; complete native-history reconstruction is not claimed. Canonical lifecycle truth uses independently checked states and paired notifications.')
    (ROOT/'boundary-audit.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(checks=len(CHECKS),failures=len(failures),engine_runs=0)))
    assert not failures


if __name__=='__main__':main()
