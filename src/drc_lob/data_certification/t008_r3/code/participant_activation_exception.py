"""Explain unmatched exact-size insertion without inventing activation semantics."""
from pathlib import Path
from participant_q16 import RECORD, decode, token, sha
import gzip, json

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT/'T-008/r3/participant'
OLD = ROOT/'T-008/r2/december'
audit = json.loads((OUT/'activation_correspondence.json').read_text())
missing = {r['local_order_token']: r for r in audit['evidence'] if not r['matching_status_candidates']}
all_events = list(map(json.loads, (OLD/'identity_candidate_events.v2.jsonl').read_text().splitlines()))
events = [r for r in all_events
          if r['local_order_token'] in missing]
lo, hi = min(r['candidate_group_time_ns'] for r in events), max(r['candidate_group_time_ns'] for r in events)
rows = []
ordinal = 0
with gzip.open(ROOT/'T-001/data/btc_20251201_00.data.gz','rb') as stream:
    for chunk in iter(lambda: stream.read(RECORD.size*32768), b''):
        for record in RECORD.iter_unpack(chunk):
            if lo-1000000000 <= record[0] <= hi+1000000000 and token(record[7]) in missing:
                rows.append(dict(status_source_row=ordinal, time_ns=record[0], status_id=record[3],
                    side='A' if record[4] else 'B', price_units8=decode(record[5]), quantity_units8=decode(record[6]),
                    original_quantity_units8=decode(record[18]), triggered=record[10], is_trigger=record[11],
                    reduce_only=record[14], order_type_id=record[15], tif_id=record[16]))
            ordinal += 1
birth = next(r for r in events if r['kind']=='new')
taker_legs = [r for r in all_events if r.get('candidate_taker_token')==birth['local_order_token']
              and r['candidate_group_time_ns']==birth['candidate_group_time_ns']
              and r['source_diff_row_0based']<birth['source_diff_row_0based']]
total = sum(r['quantity_before_units_1e8_btc']-r['quantity_after_units_1e8_btc'] for r in taker_legs)
assert len(rows)==1
gap = rows[0]['quantity_units8']-birth['quantity_after_units_1e8_btc']
result = dict(events=events, status_rows=rows, code_sha256=sha(Path(__file__)),
              prior_same_group_taker_trade_source_rows=[r['matching_trade_source_row_0based'] for r in taker_legs],
              prior_same_group_taker_size_units8=total, status_minus_visible_size_units8=gap,
              arithmetic_reconciles=total==gap,
              explanation='The size difference is tested against earlier same-group maker rows whose candidate taker token is this order. Exact reconciliation supports aggressor-then-resting residual interpretation, not native action/priority certification.')
(OUT/'activation_exception.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
