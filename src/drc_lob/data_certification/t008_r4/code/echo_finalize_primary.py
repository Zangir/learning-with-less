"""Freeze only the completed small authoritative-source evidence subbundle."""
from datetime import datetime, timezone
from pathlib import Path
import ctypes
import hashlib
import json
import shutil

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "authoritative-sources"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_once(name, value):
    with (OUT / name).open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")


def main():
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetCurrentProcess.restype = ctypes.c_void_p
    kernel.SetProcessAffinityMask.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
    assert kernel.SetProcessAffinityMask(kernel.GetCurrentProcess(), 1)
    assert not (OUT / "manifest.json").exists()
    now = datetime.now(timezone.utc)
    first = (OUT / "timing.log").read_text().splitlines()[0].split(" START ")[0]
    start = datetime.fromisoformat(first.replace("Z", "+00:00"))
    fetch = [json.loads((OUT / f"fetch_batch{batch}.log").read_text().splitlines()[-1])
             for batch in ("01", "02", "03")]
    write_once("timing_summary.json", {
        "started_at_utc": first, "finished_at_utc": now.isoformat(),
        "wall_seconds": (now - start).total_seconds(), "fetch_jobs": fetch,
        "fetch_total_seconds": sum(record["elapsed_seconds"] for record in fetch),
        "comparison_checks_seconds": json.loads((OUT / "checks.log").read_text())["elapsed_seconds"]})
    write_once("web_research_record.json", {
        "call_count": 2, "unmetered_web_reserve_bytes": 2097152,
        "search": "Two queries restricted to official Hyperliquid documentation and repository names; current node README used for navigation only",
        "open": "Two pinned GitHub source-directory opens both failed; no evidentiary claim",
        "third_party_search_results_used": False})
    with (OUT / "timing.log").open("a", encoding="utf-8") as stream:
        stream.write(now.isoformat() + " COMPLETE source-only findings and evidence freeze; no further acquisition\n")
    paths = sorted(path for path in OUT.rglob("*") if path.is_file())
    paths += sorted((ROOT / "code").glob("echo_*.py"))
    records = [{"path": str(path), "sha256": sha(path), "bytes": path.stat().st_size}
               for path in paths]
    write_once("manifest.json", {
        "schema": "t008-primary-source-subbundle/4", "role": "Engineer",
        "operation": "cycle1919:T008:participant-premises-and-reviewed-source-story",
        "created_at_utc": now.isoformat(), "seed": 20260919,
        "base_commit": "7f24deedd0e9dd56d6a1771bb8da7c8ca5f0a551",
        "empirical_admission": False, "prior_bytes_modified": False,
        "new_market_payload_bytes": 0, "files": records,
        "listed_file_count": len(records), "listed_bytes": sum(r["bytes"] for r in records),
        "new_charged_transfer_bytes": 2882402,
        "physical_free_bytes": shutil.disk_usage(ROOT).free,
        "root_preflight_sha256": sha(ROOT / "evidence/resource_preflight.json"),
        "tmux_sessions_used": ["drc-lob-t008-r4-primary-sources", "drc-lob-t008-r4-primary-checks"],
        "tmux_sessions_remaining": [], "finalizer_affinity_mask": 1})
    print(json.dumps({"manifest_sha256": sha(OUT / "manifest.json"),
                      "findings_sha256": sha(OUT / "findings.md"), "listed_files": len(records),
                      "wall_seconds": (now - start).total_seconds()}, indent=2))


if __name__ == "__main__":
    main()
