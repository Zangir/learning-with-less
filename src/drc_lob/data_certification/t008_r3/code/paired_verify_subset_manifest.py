"""Verify every active member of the corrected immutable Q18 review packet."""
import ctypes
from ctypes import wintypes
import hashlib
import json
from pathlib import Path
import time

ROOT=Path(__file__).resolve().parents[1]


def sha(path):
    digest=hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda:stream.read(1048576),b""):digest.update(block)
    return digest.hexdigest()


def main():
    affinity=ctypes.windll.kernel32.SetProcessAffinityMask
    affinity.argtypes=(wintypes.HANDLE,ctypes.c_size_t)
    if not affinity(wintypes.HANDLE(-1),1):raise OSError("OneCPU affinity unavailable")
    started=time.perf_counter()
    directory=ROOT/"interface/full_day_startup30/q18_required_subset"
    manifest_path=directory/"review_manifest.v2.3.1.json"
    manifest=json.loads(manifest_path.read_text())
    failures=[]
    for entry in manifest["files"]:
        path=Path(entry["path"])
        if path.stat().st_size!=entry["size_bytes"] or sha(path)!=entry["sha256"]:
            failures.append(str(path))
    index=json.loads(Path(manifest["dataset_index_file"]).read_text())
    previous=json.loads((directory/"dataset_index.q18.v2.3.0.json").read_text())
    same=index["contracts"]==previous["contracts"] and index["dates"]==previous["dates"]
    result={"passed":not failures and same,"active_members_verified":len(manifest["files"]),"failures":failures,
        "manifest_sha256":sha(manifest_path),"dataset_index_sha256":sha(manifest["dataset_index_file"]),
        "all_fourteen_contracts_and_dates_unchanged":same,"elapsed_seconds":time.perf_counter()-started,
        "verification_code_sha256":sha(__file__),"superseded_stale_manifest_not_revalidated_as_authoritative":True}
    output=directory/"binding_verification.v2.3.1.json"
    if output.exists():raise ValueError("Verification artifact already exists")
    output.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n")
    print(json.dumps(result),flush=True)
    if not result["passed"]:raise ValueError("Corrected manifest verification failed")


if __name__=="__main__":main()
