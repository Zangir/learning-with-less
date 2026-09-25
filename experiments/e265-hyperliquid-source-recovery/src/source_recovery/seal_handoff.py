"""Seal completed source evidence without changing the packet under RV030 review."""
from settings import OUT, EXCHANGE, bind, now, pin, read, save, sha, stamp
from acquire_sources import BASE_RETENTION
from pathlib import Path
from datetime import datetime
import importlib.metadata
import shutil
import subprocess
import time
import zipfile


def main():
    proc = pin()
    started = time.monotonic()
    old = OUT / "receipt_source_review_packet.v1.json"
    assert sha(old) == "3a59a979ae8dd3b425fdaeb56bae2d2c70d98d179b413f106200b354adbe6a17"
    frozen = read(old)["files"]
    assert len(frozen) == 71
    for entry in frozen:
        actual = bind(entry["path"])
        assert all(actual[key] == entry[key] for key in ("bytes", "sha256")), entry["path"]
    assert not subprocess.check_output(["git", "status", "--porcelain"], text=True).strip()
    assert read(OUT / "visual_inspection.json")["passed"]
    assert read(OUT / "visual_inspection.json")["pdf"] == bind(OUT / "report.pdf")
    assert int((OUT / "logs/report.exit").read_text()) == 0
    code = OUT / "code"
    code.mkdir(exist_ok=True)
    for path in Path(__file__).parent.glob("*.py"):
        shutil.copy2(path, code / path.name)
    versions = {name: importlib.metadata.version(name)
                for name in ("pyarrow", "numpy", "pandas", "matplotlib", "psutil")}
    save(code / "runtime_versions.json", versions)
    (code / "requirements.txt").write_text("\n".join(f"{name}=={version}" for name, version in versions.items()) + "\n")
    with zipfile.ZipFile(OUT / "overleaf_source.zip", "w", zipfile.ZIP_DEFLATED) as archive:
        for name in ("report.tex", "main_figure.png", "main_figure.svg", "source_availability.csv",
                     "comparison_completion.csv"):
            archive.write(OUT / name, name)
    jobs = []
    for path in sorted((OUT / "logs").glob("*.exit")):
        exit_code = int(path.read_text())
        disposition = "successful"
        if exit_code:
            assert path.stem == "report-attempt1" and exit_code == 1
            disposition = "superseded: pdfLaTeX font unavailable; installed XeLaTeX succeeded"
        jobs.append(dict(job=path.stem, exit_code=exit_code, disposition=disposition,
                         terminal_evidence=bind(path), log=bind(path.with_suffix(".log"))))
    save(OUT / "job_terminal_evidence.final.json", jobs)
    current = sum(p.stat().st_size for p in OUT.rglob("*") if p.is_file())
    resource = read(OUT / "resource_accounting.json")
    resource.update(at=now(), t018_current_retained_bytes=current, finalization_reserve_bytes=8*1024**2,
                    cumulative_retained_with_finalization_reserve=BASE_RETENTION+current+8*1024**2,
                    free_C_bytes=shutil.disk_usage(OUT).free,
                    sampled_acquisition_memory=read(OUT / "resource_monitor_summary.json"),
                    finalizer_rss_bytes=proc.memory_info().rss)
    assert resource["cumulative_retained_with_finalization_reserve"] <= 12*1024**3
    assert resource["free_C_bytes"] >= 50*1024**3
    save(OUT / "resource_accounting.final.json", resource)
    finalization = dict(at=now(), git_revision=subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        frozen_receipt_packet_unchanged=True, frozen_entries_verified=len(frozen),
        source_contracts=58, producer_source_defects=0,
        independent_admission="Pending independent review; no model outcomes asserted",
        task_wall_minutes=(datetime.fromisoformat(now())-datetime.fromisoformat("2026-09-22T09:04:31+00:00")).total_seconds()/60,
        code=sorted(p.name for p in code.iterdir()), no_push=True)
    save(OUT / "finalization.json", finalization)
    packet_names = ("Q16.source_checkpoint.json", "Q17.source_contract.json", "Q18.source_contract.json",
        "source_verification.json", "source_availability.csv", "comparison_completion.csv",
        "report.pdf", "report.tex", "main_figure.png", "main_figure.svg", "overleaf_source.zip",
        "bbo_native/normalized_manifest.json", "q18_later/manifest.json", "native_alternatives.json",
        "job_terminal_evidence.final.json", "resource_accounting.final.json", "visual_inspection.json",
        "finalization.json", "timing_summary.json")
    save(OUT / "source_admission_packet.v2.json", dict(revision="native-and-later-source-v2", at=now(),
        source_status="Producer validated; independent review pending", previous_packet=bind(old),
        files=[bind(OUT / name) for name in packet_names],
        contract_files=[bind(row["contract_path"]) for row in read(OUT / "source_availability.json")],
        confidentiality="Private raw L4 bytes and original extracts are local only; no participant identities in report or code"))
    stamp("Final report visually inspected; frozen receipt packet unchanged; source evidence sealing started")
    # A manifest cannot eat its own tail: its own hash belongs in the exchange receipt.
    excluded = {"all_artifacts_manifest.v2.json", "logs/finalization.log", "logs/finalization.exit"}
    files = [bind(p) for p in sorted(OUT.rglob("*"))
             if p.is_file() and p.relative_to(OUT).as_posix() not in excluded]
    manifest = OUT / "all_artifacts_manifest.v2.json"
    save(manifest, dict(at=now(), files=files, excluded=sorted(excluded),
        exclusions_reason="Self reference and the currently running finalizer's terminal receipt; all source/report evidence included"))
    ready = dict(at=now(), task="T-018", experiment="E-265", state="source_recovery_handoff_ready",
        packet=bind(OUT / "source_admission_packet.v2.json"), full_manifest=bind(manifest),
        independent_review="Pending; receipt-v1 remains unchanged under RV030",
        Q16="Recoverable external checkpoint: no relevant resting snapshot or certified native action order/grouping",
        resource=bind(OUT / "resource_accounting.final.json"), finalization=bind(OUT / "finalization.json"))
    save(EXCHANGE / "review-ready-source.v2.json", ready)
    status = read(EXCHANGE / "status.json")
    status.update(at=now(), state="source_handoff_ready_Q16_external_checkpoint", jobs=[],
        next_step="Independent review of exact v2 packet; Q17/Q18 consumer execution under their owners; Q16 awaits the exact source/access package", ready=ready)
    save(EXCHANGE / "status.json", status)
    print(f"Sealed {len(files)} retained files in {time.monotonic()-started:.2f}s; packet: {ready['packet']['sha256']}", flush=True)


if __name__ == "__main__":
    main()
