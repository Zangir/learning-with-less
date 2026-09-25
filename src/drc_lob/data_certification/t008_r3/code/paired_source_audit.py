"""Read-only source ordering audit, retaining exact rejection witnesses."""
import hashlib
import json
import sys
sys.dont_write_bytecode = True
import paired_normalize as N


def inspect(records):
    previous = {}
    counts = {asset:{"rows":0,"inversions":0,"equal_identical":0,"equal_conflicting":0} for asset in ("BTC","ETH")}
    witnesses = []
    for ordinal, chunk, local, line in N.record_lines(records):
        if not line:
            continue
        receipt, encoded = line.split(" ",1)
        payload = json.loads(encoded)
        data = payload["data"]
        asset = data["coin"]
        current = {"source_ordinal":ordinal,"chunk_number":chunk,"chunk_local_ordinal":local,
            "receipt_text":receipt,"event_ms":data["time"],"full_payload_sha256":hashlib.sha256(encoded.encode()).hexdigest(),"payload":payload}
        counts[asset]["rows"] += 1
        old = previous.get(asset)
        if old:
            delta = current["event_ms"]-old["event_ms"]
            violation = "inversions" if delta < 0 else "equal_conflicting" if delta == 0 and payload != old["payload"] else None
            if violation:
                counts[asset][violation] += 1
                if len(witnesses) < 20:
                    witnesses.append({"asset":asset,"violation":violation,"delta_ms":delta,"previous":old,"current":current})
            elif delta == 0:
                counts[asset]["equal_identical"] += 1
        previous[asset] = current
    return {"counts":counts,"rejection_witnesses":witnesses,"strict_source_order_valid":not witnesses,
        "interpretation":"Diagnostic counts in preserved source order; no sorting, repairs, period substitutions or model outcomes"}
