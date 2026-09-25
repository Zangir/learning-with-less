"""Adversarial checks specific to fixed receipt-prefix exclusion ordering."""
import json
import sys
import tempfile
from pathlib import Path
sys.dont_write_bytecode = True
import paired_startup30_normalize as N


def main():
    date="2025-02-01"
    base=N.utc_ns(date+"T00:00:00Z")
    def line(event_ms,receipt_ms):
        receipt=f"{date}T00:{receipt_ms//60000:02d}:{receipt_ms//1000%60:02d}.{receipt_ms%1000:03d}Z"
        payload={"channel":"l2Book","data":{"coin":"BTC","time":base//1000000+event_ms,
            "levels":[[{"px":str(100-i),"sz":"1","n":1} for i in range(20)],
                      [{"px":str(102+i),"sz":"2","n":2} for i in range(20)]]}}
        return receipt+" "+json.dumps(payload)
    def norm(lines):
        return N.normalize_lines(((i,0,i,x) for i,x in enumerate(lines)),date,base+30*N.NS,base+3600*N.NS,2*N.NS)
    def rejected(fn):
        try: fn()
        except ValueError: return
        raise AssertionError("Expected strict rejection")
    checks=[]
    def check(name,value):
        assert value
        checks.append({"name":name,"passed":True})
    x=norm([line(29000,29999),line(30000,30000)])
    check("receipt_prefix_excluded_before_order_checks",len(x[-1])==1 and len(x[0]["BTC"])==1)
    check("exact_thirty_second_receipt_included",x[0]["BTC"][0]["event_ns"]==base+30*N.NS)
    x=norm([line(28000,29000),line(27000,29001),line(30500,30501)])
    check("prefix_inversion_not_carried_into_interior",len(x[-1])==2 and x[0]["BTC"][0]["source_ordinal"]==2)
    rejected(lambda:norm([line(29000,31000),line(28000,32000),line(33000,33001)]))
    check("late_old_event_cannot_bypass_remaining_order_checks",True)
    rejected(lambda:norm([line(31000,31001),line(30500,32001)]))
    check("remaining_inversion_still_rejects",True)
    x=norm([line(29999,30001),line(30500,30501),"",line(31000,31001)])
    check("remaining_event_prefix_excluded_after_order_validation",x[5]["BTC"]["before"]==1)
    check("post_prefix_disconnect_preserved",len(x[3]["BTC"])==2)
    x=norm([line(ms,ms+1) for ms in range(30500,240000,500)])
    with tempfile.TemporaryDirectory(prefix="t008-startup30-test-") as tmp:
        diagnostics,windows,_=N.audit(x[0]["BTC"],x[3]["BTC"],{"max_age_ns":1500000000},Path(tmp))
        check("q17_history_rebuilt_from_first_interior_snapshot",diagnostics["decisions"]["Q17"][0]["cut_ns"]==base+51*N.NS)
        check("q18_history_rebuilt_from_first_interior_snapshot",diagnostics["decisions"]["Q18"][0]["cut_ns"]==base+106*N.NS)
        check("no_source_support_from_excluded_prefix",all(w["start_ns"]==base+30500000000 for w in windows))
    result={"origin":"synthetic_integration","passed":len(checks),"failed":0,"checks":checks}
    N.write_json(N.ROOT / "interface/paired_startup30_synthetic_checks.json",result)
    print(json.dumps({"passed":len(checks),"failed":0}))


if __name__=="__main__": main()
