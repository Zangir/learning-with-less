"""Validate and freeze a T-008 artifact bundle after report inspection."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
REPO = Path.cwd()
def read(path):
    return json.loads((ROOT/path).read_text(encoding="utf-8-sig"))
def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()
def write(name,value):
    (ROOT/name).write_text(json.dumps(value,indent=2)+"\n",encoding="utf-8")
contract=read("shared_data_contract.json")
clock=read("evidence/clock_forensics.json")
replay=read("evidence/replay_audit.json")
budget=read("independent_day_acquisition_plan.json")
sources=read("evidence/sources_rules_source_inventory.json")
checks={
 "identical_versioned_contract": (ROOT/"shared_data_contract.json").read_bytes()==(ROOT/"shared_data_contract.v1.0.0.json").read_bytes(),
 "mandatory_scopes_independently_closed": all(contract["scopes"][q]["admissible"] is False for q in ["Q16","Q17","Q18"]),
 "empty_explicit_window_artifact": read("admissible_windows.json")["windows"]==[],
 "empty_csv_has_only_header": len((ROOT/"admissible_windows.csv").read_text().splitlines())==1,
 "separate_evaluation_gate": contract["evaluation_readiness"]["final_validation_or_test_ready"] is False,
 "all_three_frozen_inputs_match": all(r["matches_frozen"] for r in read("evidence/input_integrity.json")["files"]),
 "clock_code_matches_executed": digest(ROOT/"code/clock_forensics.py")==clock["code_sha256"],
 "replay_code_matches_executed": digest(ROOT/"code/replay_certificate.py")==replay["code_sha256"],
 "all_six_trigger_tests_pass": read("evidence/clock_adversarial_tests.json")["passed"]==6,
 "all_twelve_clock_invariants_pass": read("evidence/clock_verification.json")["passed"]==12,
 "all_nine_replay_model_checks_pass": read("evidence/replay_adversarial_tests.json")["passed"]==9,
 "all_nine_replay_invariants_pass": read("evidence/replay_verification.json")["passed"]==9,
 "all_source_snapshot_hashes_match": all(digest(Path(r["local_path"]))==r["sha256"] for r in sources),
 "budget_reconciles": budget["cap_bytes"]-budget["prior_transfer_conservative_upper_bound_bytes"]==budget["remaining_bytes"]==92053579,
 "retained_legacy_anomalies": len(clock["clock_reversals"])==1 and len(clock["missing_updates"])==8,
 "trigger_diagnostic_unsorted_zero_reversals": not clock["diagnostic_remaining_reversals"],
 "exactly_three_sanitized_samples": len((ROOT/"sample_rows.csv").read_text().splitlines())==4,
 "pdf_compiled_without_overfull_boxes": (ROOT/"report.pdf").stat().st_size>0 and "Overfull" not in (ROOT/"report-build/report.log").read_text(errors="replace"),
}
public_files=["report.md","report.tex","index.html","sample_rows.csv","main_figure_data.json"]
checks["no_account_addresses_in_public_outputs"]=all(not re.search(r"0x[0-9a-fA-F]{40}",(ROOT/p).read_text(encoding="utf-8-sig")) for p in public_files)
repo_matches={}
for artifact in sorted((ROOT/"code").glob("*.py")):
    tracked=REPO/"experiments/t008"/artifact.name
    if not tracked.exists():
        continue
    original=artifact.read_text(encoding="utf-8-sig").replace("\r\n","\n").strip()
    actual=tracked.read_text(encoding="utf-8-sig").replace("\r\n","\n").strip()
    if artifact.name=="replay_certificate.py":
        original=re.sub(r"BASE = Path\('[^']+'\)", "BASE = Path(__file__).resolve().parents[2]", original, count=1)
    repo_matches[artifact.name]=original==actual
checks["repository_code_matches_except_documented_portable_base"]=all(repo_matches.values())
assert all(checks.values()), {k:v for k,v in checks.items() if not v}
write("evidence/bundle_validation.json",{"checked_utc":datetime.now(timezone.utc).isoformat(),"checks":checks,"passed":len(checks),"failed":0,
 "repository_comparison":repo_matches,"manual_visual_inspection":"Final main PNG and all three compiled PDF pages inspected; no clipping, overlapping text or orphan table.",
 "portable_revision_note":"The committed replay file replaces the executed absolute BASE with Path(__file__).resolve().parents[2]; scientific logic is otherwise identical. Executed artifact source/hash is retained."})
commit=subprocess.check_output(["git","rev-parse","HEAD"],text=True).strip()
status=subprocess.check_output(["git","status","--porcelain"],text=True).strip()
events=[]
for line in (ROOT/"timing.log").read_text(encoding="utf-8-sig").splitlines():
    first,_,note=line.partition(" ")
    try:stamp=datetime.fromisoformat(first.replace("Z","+00:00"))
    except ValueError:continue
    events.append((stamp,note))
now=datetime.now(timezone.utc)
start=events[0][0]
markers=[(start,"Setup and frozen-evidence inspection")]
for stamp,note in events:
    if note.startswith("INPUTS"):markers.append((stamp,"Parallel clock/replay/source investigation and budget plan"))
    elif note.startswith("CONTRACT"):markers.append((stamp,"Contract/report integration and independent review"))
    elif note.startswith("PACKAGE"):markers.append((stamp,"Final PDF inspection, code and bundle validation"))
sections=[]
for i,(stamp,name) in enumerate(markers):
    stop=markers[i+1][0] if i+1<len(markers) else now
    sections.append({"section":name,"start_utc":stamp.isoformat(),"end_utc":stop.isoformat(),"seconds":(stop-stamp).total_seconds()})
timing={"start_utc":start.isoformat(),"completed_utc":now.isoformat(),"recorded_workflow_seconds":(now-start).total_seconds(),
 "sections":sections,"events":[{"utc":t.isoformat(),"note":n} for t,n in events],
 "final_clock_scan_seconds":clock["seconds"],"final_replay_scan_seconds":replay["environment"]["wall_seconds"],
 "clock_all_three_scans_seconds":sum(read(p)["seconds"] for p in ["evidence/clock_forensics_initial.json","evidence/clock_forensics_flags.json","evidence/clock_forensics.json"]),
 "replay_all_scans_and_probe_seconds":read("evidence/replay_audit_initial_zero_classification.json")["environment"]["wall_seconds"]+replay["environment"]["wall_seconds"]+read("evidence/replay_inherited_probe.json")["wall_seconds"],
 "parallel_durations_not_additive":True,"initial_read_only_workspace_setup_before_timing_file":"not separately timed"}
write("timing_summary.json",timing)
sessions=["drc-lob-t008-clock-forensics","drc-lob-t008-replay","drc-lob-t008-replay-probe","drc-lob-t008-report"]
out={"task":"T-008","title":"Certify Hyperliquid event time and replay state","role":"Engineer",
 "experiment_ids":["E-200","E-201","E-202","E-203","E-204"],"status":"completed_diagnostic_with_precise_blocker",
 "scientific_acceptance":"engineer evidence; coordinator/reviewer acceptance separate",
 "worktree":str(REPO),"branch":"feat/t008-data-certification","base_commit":"ed62f2a4ccebc7ad559ba0c185954401d5311cb8",
 "code_revision":commit,"working_tree_clean":not status,"pushed":False,
 "code_only_commits":["f06c951","c4ad313","02f5516",commit],
 "executed_code_provenance":"Exact executed sources remain under code/ with hashes in evidence. Committed replay BASE is normalized to bundle-relative path; all other scientific logic matches.",
 "inputs":read("evidence/input_integrity.json"),"seed":20260919,
 "resources":{"cpu_threads_per_scan":1,"max_concurrent_scans":2,"max_memory_per_scan_gib":3,"timeout_seconds":3600,"gpu_used":False,
 "clock_max_rss_kib":clock["max_rss_kib"],"replay_max_rss_kib":replay["environment"]["memory_peak_KiB"]},
 "labels_and_exclusions":{"split":"development_only","sample":"actual timestamps include Nov30, not clipped to filename","predictive_windows":[],"direct_clock_candidates":91860,"retrospective_neighbor_inferences":8,
 "fill_label":"Only independently matched executions; unmatched size reductions retain separate class",
 "excluded_claims":["certified full venue book","certified live availability","exact FIFO rank","completed real Q16/Q17/Q18","final validation/test performance"]},
 "new_market_data_bytes":0,"nonmarket_retained_source_bytes":sum(r["bytes"] for r in sources),"remaining_acquisition_bytes":92053579,
 "main_outputs":["shared_data_contract.v1.0.0.json","shared_data_contract.json","admissible_windows.json","independent_day_acquisition_plan.json","report.md","report.pdf","report.tex","main_figure.png","main_figure.svg","main_figure_data.json","index.html","sample_rows.csv"],
 "checks":checks,"limitations":["Missing initial checkpoint or proven regional completeness","No original block/receipt envelopes in flat export","Prefix-only candidate clock matching","Historical mainnet priority-fee activation unverified","Retrospective endpoint price condition is not an admitted window"],
 "tmux_sessions":[{"name":s,"state":"completed_absent_at_handoff"} for s in sessions],
 "timing_summary":"timing_summary.json","public_export_caution":"Raw source snapshots can contain public example addresses and author metadata; use sanitized report, figure and samples externally.",
 "artifact_sha256":{}}
for p in sorted(ROOT.rglob("*")):
    if not p.is_file():continue
    relative=p.relative_to(ROOT).as_posix()
    if "__pycache__" in relative or relative.startswith("report-build/") or relative in ["manifest.json","manifest.sha256"]:continue
    out["artifact_sha256"][relative]=digest(p)
write("manifest.json",out)
(ROOT/"manifest.sha256").write_text(digest(ROOT/"manifest.json")+"  manifest.json\n")
print(json.dumps({"checks_passed":len(checks),"artifact_files":len(out["artifact_sha256"]),"code_revision":commit,"clean":not status,"recorded_minutes":(now-start).total_seconds()/60},indent=2))
