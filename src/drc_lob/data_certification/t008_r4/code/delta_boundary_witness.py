"""Expose one exact inherited-order boundary witness without account identifiers."""
from pathlib import Path
from datetime import datetime, timezone
from ctypes import wintypes
import ctypes
import gzip
import hashlib
import json
import struct
import time

START = time.monotonic()
ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT.parents[1]
kernel = ctypes.WinDLL('kernel32', use_last_error=True)
kernel.GetCurrentProcess.restype = wintypes.HANDLE
kernel.SetProcessAffinityMask.argtypes = (wintypes.HANDLE, ctypes.c_size_t)
assert kernel.SetProcessAffinityMask(kernel.GetCurrentProcess(), 1)
probe = json.loads((ROOT / 'holdings/bounded_schema_boundary_probe.json').read_text())
target = probe['first_btc_nonnew_first_appearance']
status_target = probe['status_prefix']['matched_order_records'][0]
with gzip.open(BASE / 'T-001/data/book_diffs_20251201_00.gz', 'rb') as stream:
    prefix = [stream.readline() for _ in range(target['source_ordinal_zero_based'] + 1)]
raw_diff = prefix[-1]
diff = json.loads(raw_diff)
assert hashlib.sha256(raw_diff).hexdigest() == target['row_sha256']
assert hashlib.sha256(str(diff['oid']).encode()).hexdigest()[:20] == target['order_token']
assert not any(json.loads(line)['oid'] == diff['oid'] for line in prefix[:-1])
with gzip.open(BASE / 'T-001/data/btc_20251201_00.data.gz', 'rb') as stream:
    raw_status_prefix = stream.read((status_target['source_ordinal_zero_based'] + 1) * 54)
status = raw_status_prefix[-54:]
assert hashlib.sha256(status).hexdigest() == status_target['raw_record_sha256']
assert struct.unpack_from('<Q', status, 23)[0] == diff['oid']


def fixed_1e8(offset):
    encoded = struct.unpack_from('<I', status, offset)[0]
    return (encoded & 0x1fffffff) * 10 ** (8 - (encoded >> 29))


first_status_ns = struct.unpack_from('<Q', raw_status_prefix, 0)[0]
event_ns = struct.unpack_from('<Q', status, 0)[0]
result = {
    'schema': 't008-r4-nonidentifying-inherited-boundary/1', 'seed': 20260919,
    'asset': diff['coin'], 'local_order_token': target['order_token'],
    'diff': {'file': 'T-001/data/book_diffs_20251201_00.gz', 'local_ordinal_zero_based': target['source_ordinal_zero_based'],
        'raw_row_sha256': target['row_sha256'], 'side': diff['side'], 'price_usd': diff['px'],
        'operation': diff['raw_book_diff'], 'quantity_field_present': False,
        'no_prior_appearance_in_all_preceding_raw_rows': True},
    'matched_status': {'file': 'T-001/data/btc_20251201_00.data.gz',
        'local_ordinal_zero_based': status_target['source_ordinal_zero_based'],
        'decompressed_byte_offset': status_target['source_ordinal_zero_based'] * 54,
        'raw_record_sha256': status_target['raw_record_sha256'], 'status_id': status[13],
        'status_label_under_retained_schema': 'canceled', 'event_ns': event_ns,
        'event_utc': '2025-11-30T23:59:59.867476878Z',
        'first_retained_status_event_ns': first_status_ns,
        'recorded_creation_age_ms': struct.unpack_from('<I', status, 31)[0],
        'side': 'A' if status[14] else 'B', 'price_units_1e8_usd': fixed_1e8(15),
        'status_size_units_1e8_btc': fixed_1e8(19), 'original_size_units_1e8_btc': fixed_1e8(50),
        'is_trigger': bool(status[40]), 'triggered': bool(status[39])},
    'checks': {'side_and_price_agree': ('A' if status[14] else 'B') == diff['side'] and fixed_1e8(15) == int(float(diff['px'])) * 100000000,
        'status_is_at_first_retained_timestamp': event_ns == first_status_ns,
        'recorded_creation_age_positive': struct.unpack_from('<I', status, 31)[0] > 0,
        'only_hashed_local_order_token_exposed': True},
    'interpretation': 'At the first retained status timestamp, the flat diff removes an identity absent from its entire preceding raw prefix and the matched cancellation has a positive recorded age. Under the retained status schema this is an inherited lifecycle, so an empty initial resting book is not established. This does not rule out a separate valid local checkpoint later.',
    'limits': 'Recorded status size is not relabeled as an independently observed initial-book quantity. Millisecond creation age does not give exact nanosecond creation time. Source exporter mapping and native block binding remain unproved.',
    'elapsed_seconds': time.monotonic() - START, 'cpu_affinity_mask': 1,
    'code_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
}
assert all(result['checks'].values())
with (ROOT / 'holdings/initial_boundary_witness.json').open('x', encoding='utf-8') as stream:
    json.dump(result, stream, indent=2, sort_keys=True)
    stream.write('\n')
with (ROOT / 'holdings/timing.log').open('a', encoding='utf-8') as stream:
    stream.write(datetime.now(timezone.utc).isoformat() + ' Exact nonidentifying initial boundary witness verified.\n')
print(json.dumps(result['matched_status'], indent=2), flush=True)
