"""Specify missing source evidence using frozen actual cuts, without replay."""
from pathlib import Path
from datetime import datetime, timezone
from ctypes import wintypes
import csv
import ctypes
import hashlib
import json
import struct
import time

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT.parents[1]
OUT = ROOT / 'holdings'
START = time.monotonic()
kernel = ctypes.WinDLL('kernel32', use_last_error=True)
kernel.GetCurrentProcess.restype = wintypes.HANDLE
kernel.SetProcessAffinityMask.argtypes = (wintypes.HANDLE, ctypes.c_size_t)
assert kernel.SetProcessAffinityMask(kernel.GetCurrentProcess(), 1)


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def rows(path):
    with path.open(encoding='utf-8') as stream:
        return [json.loads(line) for line in stream]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def bind(path):
    return {'path': str(path), 'bytes': path.stat().st_size, 'sha256': sha(path)}


def save(name, value):
    with (OUT / name).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write('\n')


headers = []
for path in sorted((BASE / 'T-001/data').glob('*.gz')):
    with path.open('rb') as stream:
        header = stream.read(10)
        flags = header[3]
        extra = b''
        name = b''
        comment = b''
        if flags & 4:
            length = struct.unpack('<H', stream.read(2))[0]
            assert length <= 65535
            extra = stream.read(length)
        for bit, target in ((8, 'name'), (16, 'comment')):
            field = bytearray()
            if flags & bit:
                while True:
                    byte = stream.read(1)
                    if byte == b'\0':
                        break
                    assert byte and len(field) < 4096
                    field.extend(byte)
            if target == 'name':
                name = bytes(field)
            else:
                comment = bytes(field)
        headers.append({'filename': path.name, 'flags': flags, 'mtime_seconds': struct.unpack('<I', header[4:8])[0],
            'original_name': name.decode('utf-8', errors='replace'), 'extra_bytes': len(extra),
            'comment_bytes': len(comment), 'inspected_header_bytes': stream.tell(),
            'native_block_or_checkpoint_identifier': False})
save('gzip_header_metadata.json', {'files': headers, 'interpretation': 'Compression filenames/mtime are packaging metadata, not an original book checkpoint or native block correspondence.'})

paths = {
    'q16_after': BASE / 'T-009/r3/q16_required_cuts.csv',
    'q16_before': BASE / 'T-009/r3/q16_before_insertion_cuts.csv',
    'q16_extension': ROOT.parent / 'r3/participant/q16_extension_events.v3.jsonl',
    'q17_q18': ROOT.parent / 'r3/participant/required_cut_states.jsonl',
    'groups': ROOT.parent / 'r2/december/candidate_group_states.jsonl',
    'contract': ROOT.parent / 'r3/participant/conditional_contract.v3.json',
}
with paths['q16_after'].open(newline='', encoding='utf-8') as stream:
    after = list(csv.DictReader(stream))
with paths['q16_before'].open(newline='', encoding='utf-8') as stream:
    before = list(csv.DictReader(stream))
extension = rows(paths['q16_extension'])
cuts = rows(paths['q17_q18'])
groups = rows(paths['groups'])
selected = [groups[r['candidate_state_index']] for r in cuts]
contract = read(paths['contract'])
interval_start = min(w['start_ns'] for w in contract['windows'])
interval_end = max(w['end_ns'] for w in contract['windows'])
group_range = [row for row in groups if interval_start <= row['candidate_block_time_ns'] <= interval_end]
q16_times = [int(row['candidate_group_time_ns']) for row in after]
q16_ordinals = [int(row['source_last_row_0based']) for row in after]
level_positions = {(row['coin'], row['side'], row['price_units_1e8_usd'], row['source_last_row_0based']) for row in after}
prices = {(row['coin'], row['side'], row['price_units_1e8_usd']) for row in after}
required = {
    'Q17_Q18': {'distinct_query_cuts': len(cuts), 'candidate_window_start_ns': interval_start,
        'candidate_window_end_ns': interval_end, 'start_utc': '2025-12-01T00:56:36.743120300Z',
        'end_utc': '2025-12-01T00:59:59.674110002Z',
        'candidate_group_count_in_interval': len(group_range),
        'minimum_selected_group_first_raw_diff_ordinal': min(r['first_diff_row_0based'] for r in selected),
        'maximum_selected_group_last_raw_diff_ordinal': max(r['last_diff_row_0based'] for r in selected),
        'closure_witness_max_raw_diff_ordinal': max(r['next_anchor_row_0based'] for r in selected)},
    'Q16': {'after_requests': len(after), 'before_requests': len(before), 'unique_level_source_positions': len(level_positions),
        'unique_side_price_levels': len(prices), 'first_after_source_ordinal': min(q16_ordinals),
        'last_after_source_ordinal': max(q16_ordinals), 'first_after_candidate_ns': min(q16_times), 'last_after_candidate_ns': max(q16_times),
        'extension_rows': len(extension), 'extension_first_source_ordinal': min(r['source_diff_row_0based'] for r in extension),
        'extension_last_source_ordinal': max(r['source_diff_row_0based'] for r in extension),
        'extension_last_closure_witness_ordinal': max(r['closure_witness_source_row'] for r in extension)},
}
save('minimum_source_request.json', {
    'schema': 't008-r4-minimum-missing-source/1', 'seed': 20260919, 'required_cut_bindings': {k: bind(v) for k, v in paths.items()},
    'measured_existing_cut_scope': required,
    'status': 'No new market acquisition requested; exact decisive source endpoint/object not identified in retained holdings.',
    'minimum_metadata_first': {
        'purpose': 'Identify original exporter, omitted native fields, file boundary meaning, and checkpoint/map location before acquiring market bytes.',
        'required': ['Original collection/export code or producer record binding the exact three Zenodo members to native node records and documenting every flattening/filter step.',
            'A manifest locating a native checkpoint and contiguous block/sequence envelopes for the required interval, including content lengths and immutable identities.'],
        'suggested_if_located_metadata_body_cap_bytes': 262144,
        'cap_is_budget_not_measured_remote_size': True,
        'external_messages_authorized': False},
    'minimum_decisive_market_bundle_if_available': [
        {'id': 'S1', 'premises': ['P1', 'L2'], 'need': 'An independently attributable full resting-order checkpoint at a declared native block before the earliest required cut, or a scoped checkpoint with an explicit proof covering every required price region. Bind order identity, side, price, positive remaining size, and native checkpoint identifier; retain dormant/conditional-state distinction.'},
        {'id': 'S2', 'premises': ['P1', 'P2', 'P4'], 'need': 'Contiguous original block envelopes from checkpoint through the last required cut and its closing witness, with native block/sequence identity, parent or continuity linkage, event timestamp semantics, and original diff/status/fill membership. Bind every used native element to exact archived source ordinal and raw-row digest; preserve source order and activation/re-entry records.'},
        {'id': 'S3', 'premises': ['L1'], 'need': 'Native checkpoint or snapshot-to-block correspondence identifying whether a snapshot is pre-state or post-state. Same millisecond and aggregate equality are insufficient to assign an exact nanosecond or interior cut.'},
        {'id': 'S4', 'premises': ['I1', 'Q16 priority'], 'need': 'For the unchanged original tagged-order Q16 estimand, historical deployed priority semantics plus native within-price processing order/priority keys and unchanged tagged-order identity at all before/after positions. No replacement by terminal-group cut or counterfactual new insertion.'},
        {'id': 'S5', 'premises': ['original clock estimand'], 'need': 'Preserve the exact clock required by each original task. A candidate exchange-time offline route must remain an explicit adaptation when original features use a receive clock; do not relabel source availability.'},
    ],
    'remote_market_compressed_bytes': None,
    'remote_market_bytes_unknown_reason': 'No native checkpoint/envelope object catalog or content lengths are retained; a finite acquisition request cannot honestly be measured yet.',
    'not_decisive_substitutes': ['Additional flat Zenodo hours', 'A whole-month archive download', 'More aggregate L2 snapshots without native participant correspondence', 'More same-archive arithmetic matches', 'Current code semantics without historical deployment/export binding'],
    'no_positive_contract_revision': True,
})
assert len(after) == 8895 and len(before) == 1000 and len(level_positions) == 2339 and len(prices) == 128
save('minimum_source_verification.json', {'actual_cut_cardinality_checks_passed': True, 'cpu_affinity_mask': 1,
    'code': bind(Path(__file__)), 'elapsed_seconds': time.monotonic() - START,
    'seed': 20260919, 'all_outputs_are_requirements_or_metadata_not_reconstructed_states': True})
with (OUT / 'timing.log').open('a', encoding='utf-8') as stream:
    stream.write(datetime.now(timezone.utc).isoformat() + ' Minimum source scope bound to actual cuts; no acquisition request issued.\n')
print(json.dumps(required, indent=2), flush=True)
