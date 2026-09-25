"""Seal E270 evidence without altering earlier source or preparation packets."""
from settings import BASE, bind, now, pin, read, save, sha
from single_date_source import OUT, stamp
from pathlib import Path
from datetime import datetime
import importlib.metadata
import shutil
import subprocess
import zipfile


def main():
    pin()
    assert not (OUT/"artifact-manifest.json").exists(), "This packet is already sealed"
    assert not subprocess.check_output(["git","status","--porcelain"],text=True).strip()
    assert read(OUT/"visual-inspection.json")["pdf"] == bind(OUT/"report.pdf")
    assert read(OUT/"visual-inspection.json")["passed"]
    revision = subprocess.check_output(["git","rev-parse","HEAD"],text=True).strip()
    for entry in read(OUT/"preservation-before.json"):
        assert sha(entry["path"]) == entry["sha256"]
    save(OUT/"preservation-after.json",read(OUT/"preservation-before.json"))
    code=OUT/"code"
    for name in ("single_date_source.py","verify_single_date.py","report_single_date.py","seal_single_date.py","settings.py"):
        shutil.copy2(Path(__file__).parent/name,code/name)
    save(code/"runtime-versions.json",{name:importlib.metadata.version(name) for name in ("psutil","numpy","pyarrow","matplotlib")})
    with zipfile.ZipFile(OUT/"overleaf-source.zip","w",zipfile.ZIP_DEFLATED) as archive:
        for name in ("report.tex","main_figure.png","main_figure.svg","coverage_by_hour.csv"):
            archive.write(OUT/name,name)
    jobs=[]
    for name in ("normalization","verification","report"):
        path=OUT/f"logs/{name}.exit"
        assert int(path.read_text()) == 0
        jobs.append(dict(job=name,exit_code=0,exit=bind(path),log=bind(path.with_suffix('.log'))))
    save(OUT/"job-terminal-evidence.json",jobs)
    actual=sum(p.stat().st_size for p in OUT.rglob('*') if p.is_file())
    reserve=8*1024**2
    cumulative=11805294767+actual+reserve
    assert actual+reserve <= 256*1024**2
    assert cumulative+512*1024**2 <= 12*1024**3
    free=shutil.disk_usage(Path.cwd()).free
    assert free>=50*1024**3
    save(OUT/"resource-final.json",dict(at=now(),continued_retained_upper_bound_bytes=11805294767,
        new_retained_bytes_before_seal=actual,finalization_reserve_bytes=reserve,
        cumulative_retained_upper_bound_bytes=cumulative,q16_reserved_bytes=512*1024**2,
        capacity_remaining_after_q16_reserve_bytes=12*1024**3-cumulative-512*1024**2,
        new_network_charge_bytes=0,cumulative_charged_transfer_bytes=2254224507,
        free_C_bytes=free,cpu_affinity=[0,1],aggregate_memory_cap_bytes=8*1024**3,
        normalization_peak_working_set=read(OUT/"normalization_terminal.json")["peak_working_set_bytes"],
        verifier_peak_working_set=read(OUT/"producer_verification.json")["peak_working_set_bytes"],
        jobs_run_sequentially=True,failed_attempt_bytes=0,old_counters_reset=False))
    d=read(OUT/"source-request-declaration.json")
    final=dict(at=now(),operation=d["operation"],task="T018",experiment="E270",candidate="BTC2026-02-01",
        outcome="source_valid_pending_independent_review",strategy_execution_enabled=False,
        scientific_persistence_result=None,network_acquisition_bytes=0,source_rows=156889,
        source_contract=bind(OUT/"BTC/shared_data_contract.E270.json"),declaration=bind(OUT/"source-request-declaration.json"),
        revision=revision,branch="feat/t018-source-recovery",no_push=True,
        q16_checkpoint_preserved=True,closed_E269_null_selection_preserved=True,
        elapsed_minutes_since_recorded_request=(datetime.fromisoformat(now())-datetime.fromisoformat(d["frozen_utc"])).total_seconds()/60,
        owned_sessions=["drc-lob-t018-e270-source","drc-lob-t018-e270-verification","drc-lob-t018-e270-report","drc-lob-t018-e270-seal"],
        next_gate="Exact-source independent audit, then a separately authorized coordinator execution release")
    save(OUT/"final-status.json",final)
    stamp("E270 report visually inspected; source evidence and preserved earlier packets ready to seal")
    excluded={"artifact-manifest.json","artifact-manifest.sha256","logs/seal.log","logs/seal.exit"}
    files=[bind(p) for p in sorted(OUT.rglob('*')) if p.is_file() and p.relative_to(OUT).as_posix() not in excluded]
    proof=read(OUT/"acquisition_proof.json")
    raw=[dict(path=p["record"]["compressed_path"],bytes=p["record"]["compressed_bytes"],sha256=p["compressed_sha256"])
         for p in proof["partitions"]]
    manifest=OUT/"artifact-manifest.json"
    save(manifest,dict(schema="t018-e270-source-review-packet/1",at=now(),operation=d["operation"],
        outcome=final["outcome"],files=files,external_raw_sources_already_accounted=raw,
        excludes=sorted(excluded),exclusion_reason="Self reference and the active seal job's terminal receipt; closure receipt follows in owned exchange"))
    digest=sha(manifest)
    (OUT/"artifact-manifest.sha256").write_text(digest+'  artifact-manifest.json\n',encoding='utf-8')
    exchange=BASE/"mandatory-completion-exchange/T-018"
    ready=dict(at=now(),operation=d["operation"],outcome=final["outcome"],packet=bind(manifest),
        declaration=final["declaration"],contract=final["source_contract"],report=bind(OUT/"report.pdf"),
        resources=bind(OUT/"resource-final.json"),Q16="D046 checkpoint unchanged and retains first priority; no new path received",
        execution_enabled=False,new_network_bytes=0)
    save(exchange/"E270-review-ready.json",ready)
    status=read(exchange/"status.json")
    status.update(at=now(),state="E270_source_review_ready_Q16_path_checkpoint_retained",jobs=[],E270=ready,
        next_step="Independent E270 exact-source review; Q16 first on concrete source arrival; no strategy execution released")
    save(exchange/"status.json",status)
    print(f"Sealed {len(files)} local artifacts and144 existing raw bindings; manifest SHA256 {digest}",flush=True)


if __name__ == "__main__":
    main()
