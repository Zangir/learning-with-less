"""Offline diagnostics for the bounded Hyperliquid historical L2 member."""
import collections
import csv
import datetime as dt
from decimal import Decimal
import json
from pathlib import Path
import statistics

ROOT = Path(__file__).resolve().parent
INPUT = ROOT / 'btc_20251201_09.jsonl'

def outer_ns(value):
    """Preserve all nine source fractional digits; timezone is a declared UTC assumption."""
    main, fraction = value.split('.')
    seconds = int(dt.datetime.fromisoformat(main).replace(tzinfo=dt.timezone.utc).timestamp())
    return seconds * 1_000_000_000 + int(fraction.ljust(9, '0'))

def run():
    rows = [json.loads(line) for line in INPUT.read_text().splitlines()]
    clocks = [row['raw']['data']['time'] for row in rows]
    outer = [outer_ns(row['time']) for row in rows]
    delta = [b-a for a,b in zip(clocks, clocks[1:])]
    outer_delta = [b-a for a,b in zip(outer, outer[1:])]
    lag = [o-t*1_000_000 for o,t in zip(outer, clocks)]
    errors = collections.Counter()
    samples, ties = [], []
    for index, row in enumerate(rows):
        data = row['raw']['data']
        if row['raw']['channel'] != 'l2Book' or data['coin'] != 'BTC':
            errors['unexpected_channel_or_coin'] += 1
        bids, asks = data['levels']
        for side, levels in [('bid', bids), ('ask', asks)]:
            if len(levels) != 20:
                errors['non20levels'] += 1
            for level in levels:
                if Decimal(level['sz']) <= 0:
                    errors['nonpositive_size'] += 1
                if not isinstance(level['n'], int) or level['n'] <= 0:
                    errors['invalid_count'] += 1
            prices = [Decimal(level['px']) for level in levels]
            if any((b >= a if side == 'bid' else b <= a) for a,b in zip(prices, prices[1:])):
                errors['unordered_prices'] += 1
        if Decimal(bids[0]['px']) >= Decimal(asks[0]['px']):
            errors['locked_or_crossed'] += 1
        if index and clocks[index] <= clocks[index-1]:
            ties.append({'previous_row':index-1,'row':index,'exchange_time_ms':clocks[index],
                         'same_raw_snapshot':rows[index-1]['raw']==row['raw'],
                         'previous_outer_time':rows[index-1]['time'],'outer_time':row['time']})
        if index in [0, len(rows)//2, len(rows)-1]:
            samples.append({'source_row_0based':index,'exchange_time_ms':clocks[index],
                            'exchange_time_utc':dt.datetime.fromtimestamp(clocks[index]/1000,dt.timezone.utc).isoformat(),
                            'outer_time_as_recorded':row['time'],'bid_price_usdc_per_btc':bids[0]['px'],
                            'bid_size_btc':bids[0]['sz'],'bid_order_count':bids[0]['n'],
                            'ask_price_usdc_per_btc':asks[0]['px'],'ask_size_btc':asks[0]['sz'],
                            'ask_order_count':asks[0]['n']})
    result = {'origin':'exploratory_real_data_diagnostic','admission_status':'uncertified_candidate',
              'records':len(rows),'first_exchange_time_ms':clocks[0],'last_exchange_time_ms':clocks[-1],
              'first_exchange_time_utc':samples[0]['exchange_time_utc'],'last_exchange_time_utc':samples[-1]['exchange_time_utc'],
              'event_interval_ms':{'min':min(delta),'median':statistics.median(delta),'max':max(delta),
              'count_gt1000':sum(x>1000 for x in delta),'count_gt2000':sum(x>2000 for x in delta),
              'nonincreasing':sum(x<=0 for x in delta)},
              'outer_interval_ns':{'min':min(outer_delta),'median':statistics.median(outer_delta),'max':max(outer_delta),
              'nonincreasing':sum(x<=0 for x in outer_delta)},
              'outer_minus_event_ns_descriptive_only':{'min':min(lag),'median':statistics.median(lag),'max':max(lag)},
              'outer_clock_timezone_assumption':'UTC inferred from archive naming and matching epoch; not calibrated receipt evidence',
              'schema_errors':dict(errors),'ties':ties,'sample_rows':samples,
              'limitations':['No original blockheight, per-order identities, or all-change completeness certificate.',
              'Mirror README does not define outer time or collector clock calibration.',
              'Each record initializes displayed top20; intermediate book changes are not observable.',
              'Pinned member hash verified; full933171200-byte archive SHA not verified.']}
    (ROOT/'candidate_snapshot_diagnostics.json').write_text(json.dumps(result,indent=2))
    (ROOT/'tie_diagnostics.json').write_text(json.dumps(ties,indent=2))
    with (ROOT/'candidate_sample_rows.csv').open('w',newline='',encoding='utf-8') as handle:
        writer=csv.DictWriter(handle,fieldnames=samples[0]);writer.writeheader();writer.writerows(samples)
    print(json.dumps({k:v for k,v in result.items() if k not in ['sample_rows','limitations']},indent=2))

if __name__ == '__main__':
    run()
