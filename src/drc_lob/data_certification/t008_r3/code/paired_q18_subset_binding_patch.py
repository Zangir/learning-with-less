"""Add immutable decision-source binding while preserving the issued data packet."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import sys
sys.dont_write_bytecode=True

ROOT=Path(__file__).resolve().parents[1]
EXPECTED_DECISION="66dbd0ae67fd335c5d543696f05cd6b9c9c6e6235bf2f66af53ee3eb73e3a6b3"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path,value):
    if Path(path).exists():raise ValueError("Additive packet version already exists")
    Path(path).write_text(json.dumps(value,indent=2,sort_keys=True)+"\n",encoding="utf-8")


def main():
    out=ROOT/"interface/full_day_startup30/q18_required_subset"
    previous_index_path=out/"dataset_index.q18.v2.3.0.json"
    previous_manifest_path=out/"review_manifest.json"
    previous_index=json.loads(previous_index_path.read_text())
    previous_manifest=json.loads(previous_manifest_path.read_text())
    decision=ROOT/"input-records/D023-full-day-scope.md"
    if sha(decision)!=EXPECTED_DECISION or previous_index["scope_decision_sha256"]!=EXPECTED_DECISION:
        raise ValueError("Decision snapshot does not preserve the originally bound bytes")
    archived_source=out/"executed_source/paired_q18_subset.py"
    if sha(archived_source)!=sha(ROOT/"code/paired_q18_subset.py"):
        raise ValueError("Exact original executed packaging source was not preserved")
    source_copy=out/"executed_source/paired_q18_subset_binding_patch.py"
    if source_copy.exists():raise ValueError("Patch source archive already exists")
    shutil.copyfile(__file__,source_copy)
    index=deepcopy(previous_index)
    index.update(version="2.3.1",scope_decision_file=str(decision),scope_decision_sha256=sha(decision),
        supersedes_index_file=previous_index_path.name,supersedes_index_sha256=sha(previous_index_path),
        additive_binding_correction="The live coordinator decision path changed after packaging. The exact original decision bytes are now bound at an immutable local snapshot. All14contracts and analytical inputs are unchanged.")
    if index["contracts"]!=previous_index["contracts"] or index["dates"]!=previous_index["dates"]:
        raise ValueError("Metadata-only correction changed analytical inputs")
    index_path=out/"dataset_index.q18.v2.3.1.json"
    write(index_path,index)
    obsolete_paths={str(Path(previous_index["scope_decision_file"])),str(previous_index_path)}
    files=[entry for entry in previous_manifest["files"] if str(Path(entry["path"])) not in obsolete_paths]
    for path in (decision,index_path,source_copy):
        files.append({"path":str(path),"size_bytes":path.stat().st_size,"sha256":sha(path)})
    files.sort(key=lambda entry:entry["path"])
    manifest={"schema":"t008-q18-full-day-review-manifest/1","version":"2.3.1","task_scope":"Q18",
        "dataset_index_file":str(index_path),"dataset_index_sha256":sha(index_path),"files":files,"file_count":len(files),
        "total_bound_bytes":sum(entry["size_bytes"] for entry in files),"no_market_data_copies_created":True,"model_fits":0,
        "review_status":"exact_input_RV013_pending","contracts_identical_to_v2_3_0":True,
        "scope_decision_snapshot_sha256":sha(decision),"packaging_patch_code_sha256":sha(source_copy),
        "superseded_artifacts":[{"file":str(previous_index_path),"sha256":sha(previous_index_path)},
            {"file":str(previous_manifest_path),"sha256":sha(previous_manifest_path),"status":"preserved_stale_external_binding_evidence_not_authoritative"}],
        "unchanged_input_bindings_carried_forward":len(files)-3,
        "binding_correction":"The mutable coordinator decision and superseded index are excluded from active review members. The preserved original snapshot and new authoritative index replace them; the original manifest is retained as failed-binding evidence."}
    manifest_path=out/"review_manifest.v2.3.1.json"
    write(manifest_path,manifest)
    print(json.dumps({"index":str(index_path),"index_sha256":sha(index_path),"manifest":str(manifest_path),
        "manifest_sha256":sha(manifest_path),"contracts_unchanged":14,"files":len(files),"snapshot_sha256":sha(decision)}))


if __name__=="__main__":main()
