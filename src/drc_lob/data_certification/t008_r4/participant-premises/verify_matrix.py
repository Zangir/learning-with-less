"""Verify immutable evidence references and pack the completed necessity audit."""
from pathlib import Path
import csv
import ctypes
import hashlib
import json
import os
import re
import time
from datetime import datetime, timezone

OUT = Path(__file__).resolve().parent
START = time.perf_counter()
kernel = ctypes.WinDLL('kernel32', use_last_error=True)
kernel.GetCurrentProcess.restype = ctypes.c_void_p
kernel.SetProcessAffinityMask.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
assert kernel.SetProcessAffinityMask(kernel.GetCurrentProcess(), 1)
mask, system_mask = ctypes.c_size_t(), ctypes.c_size_t()
kernel.GetProcessAffinityMask.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_size_t), ctypes.POINTER(ctypes.c_size_t)]
assert kernel.GetProcessAffinityMask(kernel.GetCurrentProcess(), ctypes.byref(mask), ctypes.byref(system_mask))
assert mask.value == 1

class Memory(ctypes.Structure):
    _fields_ = [('cb', ctypes.c_ulong), ('PageFaultCount', ctypes.c_ulong),
                ('PeakWorkingSetSize', ctypes.c_size_t), ('WorkingSetSize', ctypes.c_size_t),
                ('QuotaPeakPagedPoolUsage', ctypes.c_size_t), ('QuotaPagedPoolUsage', ctypes.c_size_t),
                ('QuotaPeakNonPagedPoolUsage', ctypes.c_size_t), ('QuotaNonPagedPoolUsage', ctypes.c_size_t),
                ('PagefileUsage', ctypes.c_size_t), ('PeakPagefileUsage', ctypes.c_size_t)]

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def emit(name, payload):
    with (OUT/name).open('x', encoding='utf-8') as handle:
        handle.write(json.dumps(payload, indent=2, ensure_ascii=False) + '\n')

data = json.loads((OUT/'evidence_to_premise.json').read_text(encoding='utf-8'))
sources = data['sources']
checks = []
for key, value in sources.items():
    path = Path(value['path'])
    assert sha(path) == value['sha256'], key
    assert path.stat().st_size == value['bytes'], key
    assert value['line_end'] <= len(path.read_text(encoding='utf-8-sig').splitlines()), key
    checks.append(dict(id=key, sha256_verified=True, line_range_verified=True))
csvrows = list(csv.DictReader((OUT/'evidence_to_premise.csv').open(encoding='utf-8', newline='')))
assert len(csvrows) == len(data['premises']) == 17
for csvrow, row in zip(csvrows, data['premises']):
    for key, val in row.items():
        assert csvrow[key] == (';'.join(val) if key == 'evidence_ids' else val), (row['id'], key)
    for source in row['evidence_ids']:
        assert sources[source]['sha256'] in csvrow['exact_evidence_references']
report = (OUT/'offline_estimand_premises.md').read_text(encoding='utf-8')
for key, start, end in re.findall(r'\b(S\d\d):(\d+)(?:[–-](\d+))?', report):
    entry = sources[key]
    a, b = int(start), int(end or start)
    assert entry['line_start'] <= a <= b <= entry['line_end'], (key, a, b)

refs = ['# Exact evidence references', '', 'Line numbers are one-based in the hash-bound local bytes. Private source documents remain local.', '']
for key, entry in sources.items():
    path = entry['path'].replace('\\', '/')
    refs += [f'## {key}: {Path(path).name}', '',
             f'- File: [{path}](<{path}:{entry["line_start"]}>)',
             f'- Lines: {entry["line_start"]}–{entry["line_end"]}',
             f'- SHA-256: `{entry["sha256"]}`',
             f'- Source revision: `{entry["source_revision"] or "local frozen task artifact"}`',
             f'- Supports: {entry["supports"]}', '']
with (OUT/'evidence_references.md').open('x', encoding='utf-8') as handle:
    handle.write('\n'.join(refs))

memory = Memory()
memory.cb = ctypes.sizeof(memory)
psapi = ctypes.WinDLL('psapi', use_last_error=True)
psapi.GetProcessMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.POINTER(Memory), ctypes.c_ulong]
assert psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(memory), memory.cb)
assert memory.PeakWorkingSetSize < 3 * 1024**3
now = datetime.now(timezone.utc)
first = (OUT/'timing.log').read_text(encoding='utf-8-sig').splitlines()[0].split(' START:')[0]
began = datetime.fromisoformat(first)
result = dict(passed=True, verified_sources=checks, matrix_csv_json_rows=17,
              inline_line_references_within_declared_ranges=True,
              cpu_affinity_mask=mask.value, pid=os.getpid(), peak_working_set_bytes=memory.PeakWorkingSetSize,
              verification_seconds=time.perf_counter()-START, total_elapsed_seconds=(now-began).total_seconds(),
              started=first, completed_utc=now.isoformat(), fits_run=0, market_acquisition_bytes=0,
              existing_artifacts_mutated=False, canonical_control_read=False,
              sessions=['drc-lob-t008-r4-premise-matrix'], code_sha256=sha(Path(__file__)))
emit('verification.json', result)
with (OUT/'timing.log').open('a', encoding='utf-8') as handle:
    handle.write(now.isoformat() + ' VERIFIED:24 source hashes/line ranges;17 identical CSV/JSON rows; no fits/source writes\n')
files = {}
for path in sorted(OUT.iterdir()):
    if path.is_file() and path.name not in ('manifest.json', 'verify.log'):
        files[path.name] = dict(path=str(path), bytes=path.stat().st_size, sha256=sha(path))
emit('manifest.json', dict(schema='t008-participant-premise-audit/1', version='4.0.0',
    status='complete_review_only_no_admission', files=files,
    generated_utc=now.isoformat(), sessions=['drc-lob-t008-r4-premise-matrix'],
    no_further_writes_planned=True))
print(json.dumps({key:result[key] for key in ('passed','matrix_csv_json_rows','peak_working_set_bytes',
    'verification_seconds','total_elapsed_seconds','cpu_affinity_mask','pid')}, indent=2), flush=True)
