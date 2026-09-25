"""Synthetic tamper probes over read-only acquired inputs; never alter market files."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys
from unittest.mock import patch

sys.dont_write_bytecode = True
OUT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("historical", OUT.parents[1] / "code/historical_snapshot_contract.py")
h = importlib.util.module_from_spec(spec)
spec.loader.exec_module(h)
policy = h.read_policy()
raw = h.ROOT / "sources/btc_20251208_00.jsonl"
compressed = raw.with_suffix(".lz4")
ledger = h.ROOT / "sources/acquisition_probe_ledger.json"
record = h.ROOT / "sources/historical_holdout_acquisition_result.json"
results = []


def expect_rejected(name, fn):
    try:
        fn()
    except ValueError as error:
        results.append({"name": name, "passed": True, "error": str(error)})
        return
    results.append({"name": name, "passed": False, "error": "Input unexpectedly admitted"})


def mutate_digest(target):
    original = h.PRODUCER.sha256
    def altered(path):
        return "0" * 64 if Path(path).resolve() == target.resolve() else original(path)
    with patch.object(h.PRODUCER, "sha256", side_effect=altered):
        h.acquisition_proof(raw, "2025-12-08", "train", policy)


def mutate_json(target, mutation):
    original = Path.read_text
    altered = json.loads(original(target))
    mutation(altered)
    def read(self, *args, **kwargs):
        return json.dumps(altered) if self.resolve() == target.resolve() else original(self, *args, **kwargs)
    with patch.object(Path, "read_text", read):
        h.acquisition_proof(raw, "2025-12-08", "train", policy)


expect_rejected("unknown_source_path", lambda: h.normalize_file(OUT / "fabricated.jsonl", "2025-12-08", "train", policy, OUT / "must_not_be_created"))
expect_rejected("raw_byte_digest_tamper", lambda: mutate_digest(raw))
expect_rejected("compressed_byte_digest_tamper", lambda: mutate_digest(compressed))
expect_rejected("pinned_revision_tamper", lambda: mutate_json(ledger, lambda obj: obj.update(revision="0"*40)))
expect_rejected("member_path_tamper", lambda: mutate_json(record, lambda obj: obj[0]["member"].update(path="data/20251209/0/l2Book/BTC.lz4")))
expect_rejected("role_tamper", lambda: mutate_json(record, lambda obj: obj[0].update(predeclared_role="test")))
expect_rejected("wrong_split_request", lambda: h.acquisition_proof(raw, "2025-12-08", "test", policy))
def alter_transfer(obj):
    for transfer in obj["transfers"]:
        if transfer.get("range_start") == 252875776:
            transfer["sha256"] = "0" * 64
expect_rejected("transfer_digest_tamper", lambda: mutate_json(ledger, alter_transfer))
for date, role in policy["split_by_date"].items():
    proof = h.acquisition_proof(h.ROOT / "sources" / ("btc_"+date.replace("-", "")+"_00.jsonl"), date, role, policy)
    contract = json.loads((OUT / date / "shared_data_contract.v2.1.1.json").read_text())
    okay = contract["version"] == "2.1.1" and proof["record"]["decompressed_sha256"] == contract["sources"][0]["raw_sha256"]
    for stem in ("acquisition_chain_verification", "acquisition_proof", "supersedes_contract"):
        okay = okay and h.PRODUCER.sha256(OUT / date / contract[stem+"_file"]) == contract[stem+"_sha256"]
    results.append({"name": date+"_real_chain_and_explicit_contract_bindings", "passed": okay})
assert not (OUT / "must_not_be_created").exists()
report = {"origin": "synthetic_integration_and_readonly_real_integrity_checks", "passed": sum(r["passed"] for r in results),
          "failed": sum(not r["passed"] for r in results), "actual_data_modified": False, "checks": results}
(OUT / "provenance_regressions.json").write_text(json.dumps(report, indent=2)+"\n")
print(json.dumps(report, indent=2))
assert report["failed"] == 0
