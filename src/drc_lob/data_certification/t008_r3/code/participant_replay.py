"""Reconstruct late top-20/count states from frozen source order, without clock repair."""
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import gzip, hashlib, json, os, platform, random, resource, time

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT/'T-008/r3/participant'
OLD = ROOT/'T-008/r2/december'
RAW = ROOT/'T-001/data/book_diffs_20251201_00.gz'
SEED = 20260919
random.seed(SEED)
os.sched_setaffinity(0, {min(os.sched_getaffinity(0))})
resource.setrlimit(resource.RLIMIT_AS, (4*1024**3, 4*1024**3))
START = time.monotonic()


def units(value):
    whole, _, fraction = value.partition('.')
    assert len(fraction) <= 8
    return int(whole)*100000000+int((fraction+'00000000')[:8])


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024**2), b''):
            h.update(chunk)
    return h.hexdigest()


def mark(note):
    record = dict(utc=datetime.now(timezone.utc).isoformat(), note=note,
                  elapsed_s=time.monotonic()-START,
                  peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    print(json.dumps(record), flush=True)
    with (OUT/'timing.log').open('a') as stream:
        stream.write(json.dumps(record)+'\n')


def main():
    records = [json.loads(line) for line in (OLD/'candidate_group_states.jsonl').read_text().splitlines()]
    groups = {r['last_diff_row_0based']: r for r in records
              if r['source_order_cut_unambiguous_under_candidate_anchors']
              and r['next_anchor_time_ns'] is not None}
    assert len(groups) == 3203
    old_counts = {r['time_ns']: r['top5_counts'] for r in
                  map(json.loads, (OLD/'candidate_group_counts.jsonl').read_text().splitlines())}
    active = {}
    volume = [Counter(), Counter()]
    count = [Counter(), Counter()]
    stats = Counter()
    last_row = max(groups)
    temporary = OUT/'replayed_top20.jsonl.tmp'
    mark('Independent raw-source replay to frozen late group cuts begins')
    with gzip.open(RAW, 'rb') as stream, temporary.open('w') as output:
        for ordinal, line in enumerate(stream):
            if ordinal > last_row:
                break
            if b'"BTC"' not in line:
                continue
            row = json.loads(line)
            if row['coin'] != 'BTC':
                continue
            stats['btc_rows'] += 1
            oid = row['oid']
            side = int(row['side'] == 'A')
            price = units(row['px'])
            old = active.get(oid)
            raw = row['raw_book_diff']
            kind = 'remove' if raw == 'remove' else next(iter(raw))
            stats[kind] += 1
            if old is not None:
                assert old[:2] == (side, price)
                if old[2] > 0:
                    volume[side][price] -= old[2]
                    count[side][price] -= 1
                if kind == 'update':
                    assert old[2] == units(raw['update']['origSz'])
                    stats['original_size_assertions'] += 1
            elif kind != 'new':
                stats['inherited_first_seen'] += 1
            if kind == 'remove':
                active.pop(oid, None)
            else:
                quantity = units(raw[kind]['sz' if kind == 'new' else 'newSz'])
                active[oid] = (side, price, quantity)
                if quantity > 0:
                    volume[side][price] += quantity
                    count[side][price] += 1
            if ordinal in groups:
                source = groups[ordinal]
                top = []
                for s in (0, 1):
                    prices = sorted((p for p, q in volume[s].items() if q > 0), reverse=(s == 0))[:20]
                    top.append([[p, volume[s][p], count[s][p]] for p in prices])
                assert all(len(v) == 20 for v in top)
                assert [[x[:2] for x in v[:5]] for v in top] == source['top5_observed_plus_known_inherited']
                assert [[x[2] for x in v[:5]] for v in top] == old_counts[source['candidate_block_time_ns']]
                assert all(q > 0 and n > 0 for v in top for _, q, n in v)
                state = dict(candidate_time_ns=source['candidate_block_time_ns'],
                             source_first_row=source['first_diff_row_0based'],
                             source_last_row=ordinal,
                             closure_witness_time_ns=source['next_anchor_time_ns'],
                             closure_witness_source_row=source['next_anchor_row_0based'],
                             top20_price_quantity_count=top,
                             q17_clearing_region=source['bbo_region_price_condition'],
                             q18_clearing_region=source['strict_region_price_condition'],
                             origin='exploratory_real', admitted=False)
                output.write(json.dumps(state, separators=(',', ':'))+'\n')
                stats['closed_states'] += 1
            if stats['btc_rows'] % 1000000 == 0:
                mark(f"Replayed {stats['btc_rows']} BTC lifecycle rows")
    assert stats['closed_states'] == len(groups)
    target = OUT/'replayed_top20.jsonl'
    assert not target.exists()
    temporary.replace(target)
    result = dict(seed=SEED, counters=dict(stats),
                  original_clock_candidates_reused_not_independently_authenticated=True,
                  independent_top5_quantity_count_matches=len(groups),
                  all_scopes_admitted=False, code_sha256=sha(Path(__file__)),
                  inputs={str(p): sha(p) for p in (RAW, OLD/'candidate_group_states.jsonl', OLD/'candidate_group_counts.jsonl')},
                  output_sha256=sha(target), runtime_s=time.monotonic()-START,
                  peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                  python=platform.python_version(), platform=platform.platform(), cpu_affinity=sorted(os.sched_getaffinity(0)))
    (OUT/'replay_summary.json').write_text(json.dumps(result, indent=2)+'\n')
    mark('Replay complete; frozen top-five quantities and counts all match')


if __name__ == '__main__':
    main()
