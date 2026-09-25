"""Check small source artifacts and model only the inspected comparison predicate."""
from datetime import datetime, timezone
from pathlib import Path
import ctypes
import hashlib
import json
import time

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "authoritative-sources"
OLD = ROOT.parent / "evidence"
PIN = "bf5f6bceec3ebc36209bef1ad407de98c3550c70"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_once(name, value):
    with (OUT / name).open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")


def inspected_comparison(snapshot, expected):
    """Translate utils.rs comparison branch; omit unrelated spot-coin filtering."""
    snapshot_map = expected.copy()
    for coin, book1 in snapshot.items():
        book2 = snapshot_map.pop(coin, None)
        if book2 is not None:
            for orders1, orders2 in zip(book1, book2):
                # zip stops early; a trailing order does not get a vote.
                for order1, order2 in zip(orders1, orders2):
                    if order1 != order2:
                        return False
        elif book1[0] or book1[1]:
            return False
    return not snapshot_map


def main():
    started = time.monotonic()
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetCurrentProcess.restype = ctypes.c_void_p
    kernel.SetProcessAffinityMask.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
    kernel.SetProcessAffinityMask.restype = ctypes.c_int
    kernel.GetProcessAffinityMask.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_size_t), ctypes.POINTER(ctypes.c_size_t)]
    handle = kernel.GetCurrentProcess()
    assert kernel.SetProcessAffinityMask(handle, 1)
    process_mask, system_mask = ctypes.c_size_t(), ctypes.c_size_t()
    assert kernel.GetProcessAffinityMask(handle, ctypes.byref(process_mask), ctypes.byref(system_mask))
    assert process_mask.value == 1

    comparisons = []
    cases = [("same_orders", ["A"], ["A"]),
             ("missing_trailing_order", ["A"], ["A", "B"]),
             ("extra_trailing_order", ["A", "B"], ["A"]),
             ("empty_observed_side", [], ["A"]),
             ("different_first_order", ["A"], ["B"])]
    for name, actual, expected in cases:
        snapshot, reference = {"BTC": [actual, []]}, {"BTC": [expected, []]}
        comparisons.append({"name": name, "snapshot": snapshot, "expected": reference,
                            "example_comparison_accepts": inspected_comparison(snapshot, reference),
                            "full_equality": snapshot == reference})
    assert [r["example_comparison_accepts"] for r in comparisons] == [True, True, True, True, False]
    write_once("snapshot_validation_counterexamples.json", {
        "created_at_utc": datetime.now(timezone.utc).isoformat(), "seed": 20260919,
        "source_url": f"https://github.com/hyperliquid-dex/order_book_server/blob/{PIN}/server/src/listeners/order_book/utils.rs#L49",
        "source_sha256": sha(OUT / "obs_predec_server_src_listeners_order_book_utils.rs"),
        "code_sha256": sha(Path(__file__)), "affinity_mask": process_mask.value,
        "scope": "Tiny synthetic translation of inspected comparison logic only; provider code was not executed; no market-data or venue-semantic conclusion",
        "cases": comparisons, "all_expected_results_pass": True})

    inventory = []
    old_inventory = json.loads((OLD / "sources_rules_source_inventory.json").read_text())
    for entry in old_inventory:
        p = Path(entry["local_path"])
        assert sha(p) == entry["sha256"] and p.stat().st_size == entry["bytes"], p
        inventory.append(dict(entry, source_use="reused_frozen_primary_source", new_transfer_bytes=0))
    for filename in ("source_README.md", "source_SCHEMA.md", "source_read_data.py", "zenodo_record.json", "sample_manifest.json"):
        p = ROOT.parents[1] / "T-001" / filename
        inventory.append({"id": "ZENODO-" + filename, "local_path": str(p), "bytes": p.stat().st_size,
                          "sha256": sha(p), "url": "https://zenodo.org/records/18184441",
                          "source_use": "reused_publisher_claim_or_acquisition_record", "new_transfer_bytes": 0})
    receipts = [json.loads(p.read_text()) for p in sorted(OUT.glob("*.receipt.json"))]
    for receipt in receipts:
        p = Path(receipt["body_path"])
        assert p.stat().st_size == receipt["body_bytes"] and sha(p) == receipt["body_sha256"]
        inventory.append({"id": receipt["id"], "local_path": str(p), "bytes": receipt["body_bytes"],
                          "sha256": receipt["body_sha256"], "url": receipt["url"],
                          "retrieved_at_utc": receipt["finished_at"], "http_status": receipt["status"],
                          "source_use": "negative_retrieval_evidence" if receipt["status"] != 200 or receipt["id"] == "reading_l1_current"
                          else "merge_constituent_patch_not_revision_date_evidence" if receipt["id"] == "obs_commit_raw_patch"
                          else "pinned_code" if receipt["id"].startswith("obs_predec_") else "current_docs_navigation"})
    write_once("source_inventory.json", inventory)
    pointers = [
        (OLD / "rules_sources/node_20251128_README.md", "- `--batch-by-block`", "Native block wrapper documented before December"),
        (OLD / "rules_sources/order_book_server_20250908_node_data.rs", "pub(crate) struct Batch<E>", "Native local time, block time, height and event vector"),
        (OUT / "obs_predec_server_src_listeners_order_book_utils.rs", '"includeHeightInOutput": true', "Identity snapshot request includes native height"),
        (OUT / "obs_predec_server_src_order_book_multi_book.rs", "let (height, snapshot):", "Height-tagged per-coin two-sided order-array loader"),
        (OLD / "rules_sources/order_book_server_20250908_state.rs", "assert_eq!(order_statuses.block_number()", "Status and diff height equality"),
        (OLD / "rules_sources/order_book_server_20250908_state.rs", "if height > self.height + 1", "No skipped post-checkpoint height"),
        (OLD / "rules_sources/order_book_server_20250908_state.rs", "while let Some(diff) = diffs.pop_front()", "Native diff vector order is consumed"),
        (OUT / "obs_predec_server_src_listeners_order_book_mod.rs", "match t.block_number().cmp", "Cross-stream synchronization uses block number, not comment's timestamp"),
        (OUT / "obs_predec_server_src_listeners_order_book_utils.rs", "for (order1, order2) in orders1.iter().zip", "Order comparison omits equal-side-length check"),
        (OLD / "rules_sources/order_book_server_20250908_node_data.rs", "pub(crate) fn is_inserted_into_book", "Ordinary-open versus triggered insertion predicate"),
        (OLD / "rules_sources/order_book_server_20250908_state.rs", "inner_order.modify_sz(sz)", "Raw New size replaces status size"),
        (OUT / "obs_predec_server_src_types_inner.rs", "fn convert_trigger", "Trigger activation changes timestamp and order representation"),
        (OLD / "rules_sources/order_book_server_20250908_mod.rs", "push_back(oid, order)", "Example's historical append convention"),
    ]
    line_records = []
    for path, needle, meaning in pointers:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
        matching = [i + 1 for i, line in enumerate(lines) if needle in line]
        assert len(matching) == 1, (path, needle, matching)
        line_records.append({"file": str(path), "sha256": sha(path), "line": matching[0],
                             "exact_line": lines[matching[0] - 1], "supports": meaning})
    write_once("pinned_code_line_index.json", line_records)
    write_once("native_input_requirements.json", {
        "schema": "t008-native-participant-evidence-request/4", "seed": 20260919,
        "status": "Evidence requirements only; no acquisition or empirical admission",
        "primary_code_pin": PIN, "line_index_sha256": sha(OUT / "pinned_code_line_index.json"),
        "necessary_package": [
            {"id": "N1", "item": "Authenticated BTC identity checkpoint at a named pre-cut native height H",
             "fields": ["height", "coin", "ordered bid/ask identity arrays", "user or stable identity token", "oid", "limitPx", "sz", "side", "trigger inclusion policy"],
             "binding": "Checkpoint bytes/hash, authoritative custody, actual historical node/binary/config identity, relation to canonical historical state"},
            {"id": "N2", "item": "Contiguous complete native status and visible-diff batches H+1 through the final required closure",
             "fields": ["block_number", "block_time", "events in native vector order", "all relevant activation and lifecycle fields", "empty-block continuity or authoritative no-event witnesses"],
             "binding": "Equal heights across streams; no missing blocks/events; checkpoint-to-first-batch cursor; exact retained byte hashes; fills/cancellations as required for event classification"},
            {"id": "N3", "item": "Versioned collector/exporter transformation or independently verifiable byte/ordinal map",
             "binding": "Every relevant Zenodo row maps to native block and event ordinal; preserve order, sizes and classifications; identify dropped fields, filtering and timestamp conversions"},
            {"id": "N4", "item": "Exact claimed cut/group mapping",
             "binding": "Map original candidate cuts to native terminal states without substituting different cuts. Block identity alone does not identify a transaction or atomic economic action"},
            {"id": "N5", "item": "Separate HF capture-to-native-state binding if original L1 is retained",
             "binding": "HF raw capture must be tied to the actual native height/cursor and sampled state. Alternative: revise the contract to replace the HF-dependent checkpoint premise with N1-N4; do not call that proof of original HF L1"}
        ],
        "offline_effect_if_authenticated_and_complete": "N1-N4 can support identity initialization, relevant lifecycle completeness and native terminal-state correspondence; the exact estimand and source mapping must be reviewed. N5 is required for the original HF-specific L1 assertion.",
        "not_fixed_by_terminal_block_package": [
            "Historical receipt/release time and the original received-feature estimand",
            "I1 processing/visibility semantics at Q16 interior or before-insertion cuts; native vector order must additionally be shown to mean the claimed observer/engine order",
            "Historical FIFO or other priority rules, hypothetical probe placement, counterfactual fills",
            "Transaction/atomic economic grouping within blocks",
            "The truth of the separate HF same-millisecond observation without its own cursor/custody binding"
        ],
        "scope_note": "A regional terminal-state proof can use smaller source support than a full-book proof. Complete-book, online and FIFO premises must be required only by the target estimand."})
    bodies = sum(r["body_bytes"] for r in receipts)
    transport = sum(r["transport_reserve_bytes"] for r in receipts)
    web_reserve = 2 * 1024**2
    charged = bodies + transport + web_reserve
    assert len(receipts) == 11 and bodies == 64354 and charged <= 16 * 1024**2
    write_once("acquisition_accounting.json", {
        "created_at_utc": datetime.now(timezone.utc).isoformat(), "requests": len(receipts),
        "response_body_bytes_all_statuses": bodies, "transport_reserve_bytes": transport,
        "web_calls": 2, "web_reserve_bytes": web_reserve, "new_charged_bytes": charged,
        "baseline_before_r4": 1062571207, "cumulative_with_this_subtask": 1062571207 + charged,
        "documentation_cap_bytes": 16 * 1024**2, "no_market_payload": True,
        "new_direct_documentation_page_requests": 2, "pinned_rust_files": 5,
        "github_metadata_failures": 3, "http200_not_found_pages": 1,
        "all_fetch_affinity_masks": sorted({r["affinity_mask"] for r in receipts}),
        "accounting_scope": "Measured application response bodies, including failures, plus explicit reserves; not NIC metering"})
    script_hash = sha(Path(__file__))
    stamp = datetime.now(timezone.utc).isoformat()
    with (OUT / "timing.log").open("a", encoding="utf-8") as stream:
        stream.write(stamp + " CHECKS source hashes, bounded ledger and comparison-only counterexamples pass\n")
    print(json.dumps({"source_records": len(inventory), "response_body_bytes": bodies,
                      "new_charged_bytes": charged, "code_sha256": script_hash,
                      "counterexamples_passed": True, "affinity_mask": process_mask.value,
                      "elapsed_seconds": time.monotonic() - started}, indent=2), flush=True)


if __name__ == "__main__":
    main()
