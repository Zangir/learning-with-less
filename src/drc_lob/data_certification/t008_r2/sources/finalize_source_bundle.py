"""Finalize source-only provenance after bounded acquisitions end."""
import datetime as dt
import hashlib
import json
import platform
from pathlib import Path
import shutil
import lz4

ROOT=Path(__file__).resolve().parent
assert (ROOT/'historical_splits_probe.exit').read_text().strip()=='0'
acq=json.loads((ROOT/'acquisition_probe_ledger.json').read_text())
metadata=json.loads((ROOT/'metadata_transfer_ledger.json').read_text())
fixed=json.loads((ROOT/'historical_holdout_acquisition_result.json').read_text())
assert {r['date']for r in fixed}=={'20251208','20251216','20251223'}
market_bytes=sum(r.get('body_bytes_consumed',0)for r in acq['transfers'])
metadata_bytes=sum(r.get('bytes',0)for r in metadata)
free=shutil.disk_usage(Path.cwd()).free
assert free>=50*2**30
files=[]
for path in sorted(ROOT.rglob('*')):
    if path.is_file() and path.name!='source_manifest.json' and '__pycache__' not in path.parts:
        data=path.read_bytes();files.append({'path':str(path.relative_to(ROOT)),'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()})
result={'task':'T-008','revision':'r2','subtask':'free snapshot route and bounded historical acquisition','role':'Engineer','origin':'exploratory_real_data_diagnostic','scientific_acceptance':'separate parent contract and independent review','worktree':str(Path.cwd()),'base_commit':'f86f0bdf3daf41599582f6bd2d3a97547964c7ef','source_code_changes_in_repo':False,'source_url':acq['url'],'source_revision':acq['revision'],'license_declared_by_publisher':'MIT; redistribution provenance not independently authenticated','market_response_body_bytes':market_bytes,'metadata_response_body_bytes':metadata_bytes,'local_downloader_total_body_bytes':market_bytes+metadata_bytes,'prior_cumulative_baseline_bytes':310599605,'baseline_plus_source_body_bytes':310599605+market_bytes+metadata_bytes,'wire_accounting_limitation':'TLS, HTTPheaders, unconsumed redirect/errorbodies and web research tool traffic are not measurable here. Do not call these counts total wiretraffic. All application marketbody reads, including incidental header overread and overlap, are counted.','free_disk_bytes_at_finalize':free,'retained_bundle_bytes_excluding_manifest':sum(x['bytes']for x in files),'python':platform.python_version(),'lz4_version':lz4.__version__,'threads':'one sequential downloader, one bounded diagnostic at a time','memory':'range payload≤4MiB/member; decompression capped128MiB/member; no training','sessions_created':['drc-lob-t008-r2-source-probe','drc-lob-t008-r2-historical-splits'],'sessions_still_running':[],'fixed_dates':fixed,'files':files,'created_utc':dt.datetime.now(dt.timezone.utc).isoformat()}
(ROOT/'source_manifest.json').write_text(json.dumps(result,indent=2))
print(json.dumps({k:result[k]for k in ['market_response_body_bytes','metadata_response_body_bytes','local_downloader_total_body_bytes','baseline_plus_source_body_bytes','free_disk_bytes_at_finalize','retained_bundle_bytes_excluding_manifest']},indent=2))
