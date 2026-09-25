"""Bind the bounded holdings evidence and its separately sourced requirements."""
from pathlib import Path
from datetime import datetime, timezone
from ctypes import wintypes
import ctypes
import hashlib
import json

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'holdings'
kernel = ctypes.WinDLL('kernel32', use_last_error=True)
kernel.GetCurrentProcess.restype = wintypes.HANDLE
kernel.SetProcessAffinityMask.argtypes = (wintypes.HANDLE, ctypes.c_size_t)
assert kernel.SetProcessAffinityMask(kernel.GetCurrentProcess(), 1)


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def bind(path):
    return {'path': str(path), 'bytes': path.stat().st_size, 'sha256': sha(path)}


def save(name, value):
    # Finalization outputs remain replaceable until this bundle is published.
    with (OUT / name).open('w', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write('\n')


native = ROOT / 'authoritative-sources/native_input_requirements.json'
lines = ROOT / 'authoritative-sources/pinned_code_line_index.json'
assert sha(native) == '366166b7ef7a051b69b83d33ae57cf69beef545342d88f2d67befc41653afc0d'
assert sha(lines) == read(native)['line_index_sha256']
save('native_requirements_binding.json', {
    'schema': 't008-r4-holdings-native-requirements-binding/1',
    'native_evidence': bind(native), 'native_code_line_index': bind(lines),
    'holdings_minimum_source_request': bind(OUT / 'minimum_source_request.json'),
    'historical_code_pin': read(native)['primary_code_pin'],
    'requirements': read(native)['necessary_package'],
    'not_fixed_by_terminal_block_package': read(native)['not_fixed_by_terminal_block_package'],
    'scope': 'Requirements only: no evidence that the retained Zenodo export actually used or preserved this historical native package.',
    'HF_anchor_replacement_is_not_original_HF_L1_proof': True,
})

checked = []
for result_name in ('probe_verification.json', 'minimum_source_verification.json'):
    item = read(OUT / result_name)['code']
    assert sha(Path(item['path'])) == item['sha256']
    checked.append(result_name)
boundary = read(OUT / 'initial_boundary_witness.json')
assert sha(ROOT / 'code/delta_boundary_witness.py') == boundary['code_sha256']
checked.append('initial_boundary_witness.json')
save('boundary_clock_labels.json', {
    'witness': bind(OUT / 'initial_boundary_witness.json'),
    'retained_schema': bind(ROOT.parents[1] / 'T-001/source_SCHEMA.md'),
    'raw_fields': {'ts': boundary['matched_status']['event_ns'],
        'timestampDiff': boundary['matched_status']['recorded_creation_age_ms']},
    'clock_labels': {'ts': 'Recorded status timestamp; retained third-party schema calls this event nanoseconds.',
        'timestampDiff': 'Recorded difference between status timestamp and order timestamp in milliseconds, per retained third-party schema.'},
    'creation_semantics_are_schema_claim_not_independent_native_authentication': True,
    'no_exact_nanosecond_creation_time_inferred': True,
    'boundary_claim': 'Empty initialization is unsupported; no truncation, omitted-event or collector-loss conclusion follows from this witness alone.',
})
for role, item in read(OUT / 'minimum_source_request.json')['required_cut_bindings'].items():
    assert sha(Path(item['path'])) == item['sha256'], role
assert sha(ROOT.parent / 'r3/participant/manifest.json') == 'e361deeeb14f5c59de3e77a19d7650f02b0060785df91a6c614230080b0b9aa6'
comparison = read(OUT / 'independent_snapshot_comparison.json')
assert comparison['common_event_milliseconds'] == comparison['exact_full_payload_matches'] == 715
assert comparison['conflicting_payload_bins'] == 0
assert all(not item['tardis_overlap'] for item in comparison['participant_window_overlap'])
save('final_verification.json', {'executed_code_bindings_verified': checked,
    'actual_cut_input_bindings_verified': True, 'r3_participant_manifest_preserved': True,
    'snapshot_comparison_scope_verified': True, 'authoritative_requirements_hash_verified': True,
    'no_empirical_admission_issued': True, 'new_market_bytes': 0, 'cpu_affinity_mask': 1,
    'finalizer_code': bind(Path(__file__))})

events = (OUT / 'timing.log').read_text(encoding='utf-8-sig').splitlines()
first = datetime.fromisoformat(events[0].split(' ', 1)[0].replace('Z', '+00:00'))
finished = datetime.now(timezone.utc)
probe = read(OUT / 'probe_verification.json')
minimum = read(OUT / 'minimum_source_verification.json')
save('timing_summary.json', {'started_at_utc': first.isoformat(), 'completed_at_utc': finished.isoformat(),
    'elapsed_subtask_seconds': (finished - first).total_seconds(),
    'main_probe_seconds': probe['elapsed_seconds'], 'minimum_source_probe_seconds': minimum['elapsed_seconds'],
    'boundary_probe_seconds': boundary['elapsed_seconds'], 'main_probe_peak_working_set_bytes': probe['peak_working_set_bytes'],
    'phase_timestamps': events, 'resource_policy': 'Windows affinity mask1/core0; bounded probes under3GiB; one-hour detached tmux; no GPU/HPC.',
    'tmux_sessions_created_or_used': ['drc-lob-t008-r4-holdings', 'drc-lob-t008-r4-minimum-source'],
    'sessions_finished': True})
with (OUT / 'timing.log').open('a', encoding='utf-8') as stream:
    stream.write(finished.isoformat() + ' COMPLETE. Evidence, source requirements and executed-code hashes verified; no revised contract.\n')
paths = sorted(p for p in OUT.iterdir() if p.is_file())
paths += sorted((ROOT / 'code').glob('delta_*.py'))
paths = [p for p in paths if p.name not in ('manifest.json', 'manifest.sha256')]
paths += sorted(p for p in (ROOT / 'logs').glob('*delta*')
    if p.name not in ('delta_finalize_holdings.log', 'delta_finalize_holdings.exit'))
save('manifest.json', {'schema': 't008-r4-holdings-manifest/1', 'seed': 20260919,
    'subtask': 'Retained December holdings and minimum native source evidence',
    'files': [bind(path) for path in paths], 'external_evidence_bindings': [bind(native), bind(lines)],
    'conclusion': '715 exact early aggregate source agreements; no necessary participant premise newly discharged; exact native exporter/checkpoint/cursor package absent from inspected holdings.',
    'no_positive_contract': True, 'created_at_utc': finished.isoformat()})
digest = sha(OUT / 'manifest.json')
with (OUT / 'manifest.sha256').open('w', encoding='utf-8') as stream:
    stream.write(digest + '  manifest.json\n')
print(json.dumps({'manifest_sha256': digest, 'elapsed_seconds': (finished-first).total_seconds(),
    'report': str(OUT / 'report.md'), 'verified_file_count': len(paths)}), flush=True)
