"""Freeze the participant sub-bundle and its additive acquisition provenance."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib,json

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'r3/participant'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
sources=[ROOT/'r2/sources/paired_hour00_acquisition_result.json',ROOT/'r2/sources/acquisition_probe_ledger.json',
         ROOT/'r2/sources/source_manifest.json',ROOT/'r2/sources/hf_hl_btc_readme.txt',
         ROOT/'r2/sources/btc_20251201_00.lz4',ROOT/'r2/sources/btc_20251201_00.jsonl']
record=json.loads(sources[0].read_text())
assert record['compressed_sha256']==sha(sources[-2])
assert record['decompressed_sha256']==sha(sources[-1])
binding=dict(schema='t008-participant-provenance-binding/3',origin='exploratory_real',
    attribution='Pinned third-party archive claiming Hyperliquid collection; no official-S3 or exchange-authentication assertion.',
    conditional_contract_sha256=sha(OUT/'conditional_contract.v3.json'),
    source_files={str(p):dict(sha256=sha(p),bytes=p.stat().st_size) for p in sources},
    observed_digest_links_checked=True,full_remote_archive_hash_not_locally_verified=True)
(OUT/'participant_provenance_binding.v3.json').write_text(json.dumps(binding,indent=2)+'\n')
now=datetime.now(timezone.utc)
first=(OUT/'timing.log').read_text().splitlines()[0].split(' START')[0]
elapsed=(now-datetime.fromisoformat(first)).total_seconds()
timing=dict(start=first,completed_utc=now.isoformat(),elapsed_seconds=elapsed,
    phases=dict(raw_replay_seconds=json.loads((OUT/'replay_summary.json').read_text())['runtime_s'],
                activation_priority_seconds=json.loads((OUT/'q16_observable_summary.json').read_text())['runtime_s'],
                extension_seconds=json.loads((OUT/'q16_extension_contract.v3.json').read_text())['runtime_s']),
    sessions=['drc-lob-t008-r3-participant','drc-lob-t008-r3-q16','drc-lob-t008-r3-q16-extension'],all_participant_sessions_ended=True,
    independent_provider_followup_excluded_from_this_subbundle=True)
(OUT/'timing_summary.json').write_text(json.dumps(timing,indent=2)+'\n')
files=[p for p in OUT.iterdir() if p.is_file() and p.name not in {'manifest.json','manifest.sha256'}]
code=[p for p in (ROOT/'r3/code').glob('participant_*.py') if 'provider' not in p.name]
manifest=dict(schema='t008-participant-subbundle/3',created_utc=now.isoformat(),
    empirical_admission=False,files={str(p):dict(sha256=sha(p),bytes=p.stat().st_size) for p in files+code},
    report_integration='report.md and main_figure assets supplied to parent T008 clean PDF assembly',
    r1_r2_not_modified=True)
(OUT/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
(OUT/'manifest.sha256').write_text(sha(OUT/'manifest.json')+'\n')
print(json.dumps(dict(files=len(files+code),manifest_sha256=sha(OUT/'manifest.json'),elapsed_seconds=elapsed),indent=2))
