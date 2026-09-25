"""T-023: bounded, chronological BTC replay. All run parameters are frozen below."""
import csv
import gzip
import hashlib
import json
import os
import re
try:
    import resource
except ImportError:  # Windows has no POSIX resource module.
    resource = None
import shutil
import signal
import sys
import tarfile
import time
from collections import Counter
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from pathlib import Path

import orjson
import requests
from pyroaring import BitMap64

OUT = (Path(__file__).resolve().parents[1] / 'runtime')
URL = 'https://zenodo.org/api/records/18184441/files/book_diffs_202512.tar/content'
TOTAL = 49555435520
TRANSFER_LIMIT = 4 * 1024**3
START = datetime(2025, 12, 1, tzinfo=timezone.utc)
STARTED = time.time()
OUT.mkdir(parents=True, exist_ok=True)
TASK_START = STARTED
DEADLINE = TASK_START + 18 * 60  # Leave two minutes for bounded result packaging.


def atomic_json(path, obj):
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_bytes(orjson.dumps(obj, option=orjson.OPT_INDENT_2))
    tmp.replace(path)


class StopRun(Exception):
    pass


def guard():
    if time.time() >= DEADLINE:
        raise StopRun('active time budget reached')
    if shutil.disk_usage(OUT.parent).free < 50 * 1024**3:
        raise StopRun('50 GiB free-space floor')


class Transport:
    def __init__(self):
        self.session = requests.Session()
        self.transferred = 512 if (OUT / 'probe_header.bin').exists() else 0
        self.records = []

    def get(self, offset, size, path=None):
        guard()
        if self.transferred + size > TRANSFER_LIMIT:
            raise StopRun('4 GiB range-transfer ceiling')
        entry = dict(offset=offset, end_inclusive=offset+size-1, requested_bytes=size,
                     received_bytes=0, started_utc=datetime.now(timezone.utc).isoformat())
        digest = hashlib.sha256()
        data = bytearray() if path is None else None
        fh = path.open('wb') if path else None
        try:
            with self.session.get(URL, headers={'Range': f'bytes={offset}-{offset+size-1}',
                                               'Accept-Encoding': 'identity'},
                                  stream=True, timeout=(10, 20)) as response:
                entry.update(status=response.status_code, content_range=response.headers.get('Content-Range'),
                             etag=response.headers.get('ETag'), last_modified=response.headers.get('Last-Modified'))
                if response.status_code != 206 or response.headers.get('Content-Range') != f'bytes {offset}-{offset+size-1}/{TOTAL}':
                    raise StopRun('server did not honor exact byte range: ' + str(entry))
                for chunk in response.iter_content(1024 * 1024):
                    self.transferred += len(chunk)
                    entry['received_bytes'] += len(chunk)
                    digest.update(chunk)
                    if fh:
                        fh.write(chunk)
                    else:
                        data.extend(chunk)
                    guard()
                if entry['received_bytes'] != size:
                    raise StopRun('short range response')
                entry['verified_length'] = True
        finally:
            if fh:
                fh.close()
            entry['sha256_received'] = digest.hexdigest()
            self.records.append(entry)
            with (OUT / 'ranges.jsonl').open('a') as log:
                log.write(json.dumps(entry) + '\n')
        return bytes(data) if data is not None else entry


def discover(net):
    members = {}
    headers = []
    offset = 0
    while offset < TOTAL and len(members) < 48:
        b = net.get(offset, 512)
        if b == bytes(512):
            break
        info = tarfile.TarInfo.frombuf(b, 'utf-8', 'strict')  # Also verifies tar checksum.
        row = dict(name=info.name, header_offset=offset, data_offset=offset+512,
                   size=info.size, type=info.type.decode('ascii'), header_sha256=hashlib.sha256(b).hexdigest())
        headers.append(row)
        match = re.search(r'(2025120[12])/ex(\d+)\.gz$', info.name)
        if match and info.isfile():
            hour = (int(match[1][-2:])-1)*24 + int(match[2])
            if not 0 <= int(match[2]) < 24 or hour in members:
                raise StopRun('duplicate or invalid target hour')
            members[hour] = dict(row, hour=hour)
            print('DISCOVER', hour, info.name, info.size, flush=True)
        offset += 512 + ((info.size + 511) // 512) * 512
        atomic_json(OUT / 'tar_index.json', dict(headers=headers, next_header_offset=offset,
                                                members=sorted(members.values(), key=lambda x: x['hour'])))
    return members


class Book:
    def __init__(self):
        self.seen = BitMap64()
        self.live = {}
        self.examples = []
        self.example_kinds = Counter()
        self.last_legacy = None

    def apply(self, rec, hour, line, counts):
        oid = rec['oid']
        diff = rec['raw_book_diff']
        kind = 'remove' if diff == 'remove' else next(iter(diff))
        if kind not in ('new', 'update', 'remove'):
            raise ValueError('unknown raw_book_diff')
        counts['btc_events'] += 1
        counts[kind + '_events'] += 1
        unseen = oid not in self.seen
        previous = self.live.get(oid)
        anomalies = []
        legacy = unseen and kind != 'new'
        if legacy:
            counts['legacy_' + kind] += 1
            self.last_legacy = dict(hour=hour, member_line=line, btc_event_in_hour=counts['btc_events'], oid=oid, kind=kind)
        if previous and (previous[1], previous[2], previous[3]) != (rec['side'], rec['px'], rec['user']):
            anomalies.append('identity_changed')
        if kind == 'new':
            if not unseen:
                anomalies.append('duplicate_new_live' if previous else 'new_after_remove')
            else:
                self.live[oid] = (diff['new']['sz'], rec['side'], rec['px'], rec['user'])
        elif kind == 'update':
            if not unseen and previous is None:
                anomalies.append('update_after_remove')
            else:
                if previous and Decimal(previous[0]) != Decimal(diff['update']['origSz']):
                    anomalies.append('origSz_mismatch')
                self.live[oid] = (diff['update']['newSz'], rec['side'], rec['px'], rec['user'])
        elif previous:
            del self.live[oid]
        elif not unseen:
            anomalies.append('remove_after_remove')
        self.seen.add(oid)
        if anomalies:
            counts['anomaly_events'] += 1
            for anomaly in anomalies:
                counts[anomaly] += 1
        label = ('legacy_' if legacy else '') + kind
        # A handful of receipts is enough; the archive is not a souvenir shop.
        if self.example_kinds[label] < 2 or (anomalies and self.example_kinds['anomaly'] < 8):
            self.examples.append(dict(hour=hour, member_line=line, classification=label, anomalies=anomalies, record=rec))
            self.example_kinds[label] += 1
            if anomalies:
                self.example_kinds['anomaly'] += 1
        return legacy

    def checkpoint(self, completed_hours):
        # Keep the previous checkpoint until the replacement is fully serialized.
        data = self.seen.serialize()
        (OUT / 'seen_oids.roaring.tmp').write_bytes(data)
        atomic_json(OUT / 'live_orders.json', {str(k): v for k, v in self.live.items()})
        (OUT / 'seen_oids.roaring.tmp').replace(OUT / 'seen_oids.roaring')
        atomic_json(OUT / 'checkpoint.json', dict(completed_hours=completed_hours,
                    next_hour=completed_hours, seen_count=len(self.seen), live_count=len(self.live),
                    seen_sha256=hashlib.sha256(data).hexdigest(),
                    live_sha256=hashlib.sha256((OUT/'live_orders.json').read_bytes()).hexdigest(),
                    last_legacy=self.last_legacy, checkpoint_basis='complete gzip-CRC-verified hourly members'))


FIELDS = ['hour','hour_start_utc','btc_events','new_events','update_events','remove_events',
          'legacy_update','legacy_remove','legacy_total','legacy_per_million_btc_events',
          'tracked_live_orders','ever_seen_oids','anomaly_events','duplicate_new_live','new_after_remove',
          'update_after_remove','remove_after_remove','origSz_mismatch','identity_changed',
          'all_asset_lines','cumulative_transfer_bytes','member_seconds']


def main():
    if resource is not None:
        resource.setrlimit(resource.RLIMIT_AS, (8*1024**3, 8*1024**3))
    os.sched_setaffinity(0, sorted(os.sched_getaffinity(0))[:2])
    net = Transport()
    book = Book()
    rows = []
    members = {}
    stop_reason = None
    partial = None
    raw = OUT / 'transient_member.gz'
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(StopRun('termination signal')))
    try:
        members = discover(net)
        for hour in range(48):
            guard()
            if hour not in members:
                raise StopRun(f'missing target member {hour}')
            member = members[hour]
            begun = time.time()
            print('FETCH', hour, member['name'], member['size'], flush=True)
            transfer = net.get(member['data_offset'], member['size'], raw)
            member['compressed_sha256'] = transfer['sha256_received']
            counts = Counter()
            partial = dict(hour=hour, member_line=0, status='in_progress')
            uncompressed_hash = hashlib.sha256()
            with gzip.open(raw, 'rb') as stream:
                for line_number, line in enumerate(stream, 1):
                    uncompressed_hash.update(line)
                    rec = orjson.loads(line)
                    if rec['coin'] == 'BTC':
                        book.apply(rec, hour, line_number, counts)
                    if line_number % 100000 == 0:
                        partial.update(member_line=line_number, btc_events=counts['btc_events'])
                        guard()
                counts['all_asset_lines'] = line_number
            # Reaching EOF through gzip verifies its CRC and size before committing the hour.
            member.update(gzip_crc_verified=True, uncompressed_sha256=uncompressed_hash.hexdigest())
            counts['legacy_total'] = counts['legacy_update'] + counts['legacy_remove']
            row = {key: counts[key] for key in FIELDS}
            row.update(hour=hour, hour_start_utc=(START+timedelta(hours=hour)).isoformat(),
                       legacy_per_million_btc_events=1e6*counts['legacy_total']/max(1,counts['btc_events']),
                       tracked_live_orders=len(book.live), ever_seen_oids=len(book.seen),
                       cumulative_transfer_bytes=net.transferred, member_seconds=time.time()-begun)
            book.checkpoint(hour+1)
            rows.append(row)
            with (OUT / 'hourly_metrics.csv').open('w', newline='') as out:
                writer = csv.DictWriter(out, fieldnames=FIELDS)
                writer.writeheader()
                writer.writerows(rows)
            atomic_json(OUT / 'record_examples.json', book.examples)
            atomic_json(OUT / 'processed_members.json', [members[x] for x in range(hour+1)])
            raw.unlink()
            partial = None
            print('HOUR', json.dumps(row), flush=True)
    except (StopRun, Exception) as exc:
        stop_reason = f'{type(exc).__name__}: {exc}'
        print('STOP', stop_reason, flush=True)
    finally:
        if raw.exists():
            # An interrupted member is not included in hourly metrics or the committed checkpoint.
            raw.unlink()
        if not (OUT / 'hourly_metrics.csv').exists():
            with (OUT / 'hourly_metrics.csv').open('w', newline='') as out:
                csv.DictWriter(out, fieldnames=FIELDS).writeheader()
        checkpoint = json.loads((OUT/'checkpoint.json').read_text()) if (OUT/'checkpoint.json').exists() else None
        holdout = sum(r['legacy_total'] for r in rows if r['hour'] >= 24)
        longest = run = 0
        for row in rows:
            run = run + 1 if row['legacy_total'] == 0 else 0
            longest = max(longest,run)
        manifest = dict(assignment_id='T-023', experiment_id='E-273', question_id='Q-026', hypothesis_id='H-027',
          source=dict(record=18184441,doi='10.5281/zenodo.18184441',url=URL,file='book_diffs_202512.tar',
                      archive_bytes=TOTAL,published_md5='350656ae19550b14d2e1ebe025b25dc7',full_archive_hash_verified=False),
          requested_window=['2025-12-01T00:00:00Z','2025-12-03T00:00:00Z'],
          completed_hours=len(rows), achieved_end_exclusive=(START+timedelta(hours=len(rows))).isoformat(),
          completion_state='complete' if len(rows)==48 else 'incomplete_chronological_prefix',
          stop_reason=stop_reason, discarded_partial_member=partial,
          operational_decision=('fail' if holdout else 'pass' if len(rows)==48 else 'incomplete'),
          holdout_legacy_discoveries=holdout, btc_events=sum(r['btc_events'] for r in rows),
          legacy_total=sum(r['legacy_total'] for r in rows), anomaly_events=sum(r['anomaly_events'] for r in rows),
          last_legacy_discovery=checkpoint['last_legacy'] if checkpoint else None,
          longest_zero_discovery_run_complete_hours=longest, transfer_bytes=net.transferred,
          transfer_accounting='HTTP response body bytes; includes 512-byte probe, index, failed/partial ranges; excludes transport headers',
          runtime_seconds=time.time()-STARTED, task_elapsed_seconds=time.time()-TASK_START,
          peak_rss_bytes=(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024
                          if resource is not None else None),
          full_book_certificate=False, top_of_book_certificate=False, price_band_certificate=False,
          seed=None, cpu_affinity=sorted(os.sched_getaffinity(0)), memory_limit_bytes=8*1024**3,
          checkpoint=checkpoint, processed_members=[members[x] for x in range(len(rows))],
          limitations=['Silent initial orders are not identifiable from the finite diff prefix.',
                       'No intra-hour timestamps or block IDs; source file order is assumed causal.',
                       'Publisher completeness claim is not an independent continuity certificate.',
                       'Anomalous new/update of previously removed OIDs is logged and not reinserted; duplicate new is ignored.',
                       'origSz mismatch is logged; supplied newSz becomes tracked size.',
                       'Zero-discovery run is a finite-window hourly description, not full-book proof.'])
        manifest['retained_bytes_at_replay_end'] = sum(p.stat().st_size for p in OUT.rglob('*') if p.is_file())
        atomic_json(OUT/'manifest.json', manifest)
        print('FINAL', json.dumps({k:v for k,v in manifest.items() if k not in ('processed_members','limitations','checkpoint')}), flush=True)


if __name__ == '__main__':
    main()
