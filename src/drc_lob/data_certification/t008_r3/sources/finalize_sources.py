"""Freeze a source-only handoff after all requests and independent checks finish."""
import datetime as dt
import hashlib
import json
from pathlib import Path

BASE = Path(__file__).resolve().parent

def sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()

def write(path, value):
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, indent=2)
        handle.write("\n")

summary = json.loads((BASE / "paired_panel_acquisition_summary.json").read_text())
hour = json.loads((BASE / "tardis_hour00" / "acquisition_index.json").read_text())
full = json.loads((BASE / "tardis_full_day" / "acquisition_index.json").read_text())
full_plan = json.loads((BASE / "tardis_full_day_preflight.json").read_text())
bindings = []
for kind, source, expected in (
    ("hour00 executed", BASE / "acquire_tardis_panel.hour00.executed.py", hour["acquisition_code_sha256"]),
    ("full_day executed", BASE / "acquire_tardis_panel.full_day.executed.py", full["acquisition_code_sha256"]),
    ("full_day original code path", BASE / "acquire_tardis_panel.py", full_plan["acquisition_code_sha256"]),
    ("full_day entry point", BASE / "acquire_tardis_full_day.py", full_plan["execution_entry_sha256"]),
):
    actual = sha(source)
    assert actual == expected
    bindings.append({"kind": kind, "path": str(source), "sha256": actual, "matches_recorded_execution": True})
bindings.append({"kind": "future-only affinity fix; not used for these payloads", "path": str(BASE / "acquire_tardis_panel.future_affinity.py"),
                 "sha256": sha(BASE / "acquire_tardis_panel.future_affinity.py"), "matches_recorded_execution": False})
write(BASE / "executed_code_bindings.json", bindings)
observations = [json.loads(line) for line in (BASE / "full_day_resource_observations.jsonl").read_text().splitlines() if line.strip()]
last = observations[-1]
rows = summary["dates"]
btc_rows = sum(row["BTC_rows"] for row in rows.values())
eth_rows = sum(row["ETH_rows"] for row in rows.values())
decoded = sum(row["decoded_bytes"] for row in rows.values())
compressed = sum(row["compressed_bytes"] for row in rows.values())
table = "\n".join(f"| {date} | {row['BTC_rows']:,} | {row['ETH_rows']:,} | {row['compressed_bytes']:,} | {row['disconnect_markers']} |" for date, row in rows.items())
handoff = f"""# T-008 r3 paired-source handoff

Role: Engineer source helper. Operation `cycle1808:T-008:data-r3-reviewed-continuation`. Existing worktree/base `feat/t008-data-certification` / `f20c8eaf7b2b98faeae00584491f204175228aeb`. Seed 20260919. Earlier r1/r2 source bytes are unchanged.

## Concrete result

The frozen Tardis raw archive supplies **12 complete receipt-partition days for both BTC and ETH**, selected before acquisition under `panel_protocol.v3.1.json`. There are **1,728 successful ten-minute paired requests**, zero failed attempts and zero retries. The complete raw source inventory contains **{btc_rows:,} BTC** and **{eth_rows:,} ETH** snapshots, **{compressed:,} compressed bytes**, and **{decoded:,} decoded bytes**. Decoded panel files were streamed through gzip EOF and hashed, then discarded; the original gzip responses remain retained. This inventory is source availability and byte integrity, not a scientific verdict on every raw row or continuous venue state.

The exact calendar is January–November 1, 2025 plus January 1, 2026. Q17 roles are January–March training, April validation, and May–November plus January 2026 testing. Q18 uses the same training/validation and May–July tests. Previously inspected December dates are excluded. This is a declared Hyperliquid/calendar adaptation; it is not the original venue/year benchmark. Full-day expansion was frozen before first-hour outcomes and triggered only by measured acquisition resources.

## Raw source inventory

| UTC receipt date | BTC raw rows | ETH raw rows | Compressed bytes | Blank disconnect markers |
|---|---:|---:|---:|---:|
{table}

Per-date indexes in `tardis_full_day/day_indexes` bind all 144 ordered request records, including reused first-hour slices. `tardis_hour00/acquisition_index.json` SHA-256 is `{sha(BASE / 'tardis_hour00' / 'acquisition_index.json')}`. `tardis_full_day/acquisition_index.json` SHA-256 is `{sha(BASE / 'tardis_full_day' / 'acquisition_index.json')}`. Each request binds the exact URL, protocol/preflight/authorization/code digests, response headers, compressed file hash and decoded hash. The independent acquisition summary freshly checks all retained compressed hashes, immutable record hashes, planned URLs, source partition headers, slice sizes and supplied Content-Length values. Its error list is empty.

## Semantics and limitations

This is a third-party archive claiming direct Hyperliquid WebSocket collection, not official S3 provenance or cryptographic exchange authenticity. The [provider HTTP specification](https://docs.tardis.dev/api/http-api-reference) documents receipt-based slices and blank disconnect markers. Raw native `l2Book` snapshots preserve prices, sizes and order counts; unlike provider-normalized CSV, the acquisition does not reconstruct or remove crossed levels. Exchange event milliseconds and provider collection receipt timestamps remain distinct. Receipt dates do not prove event dates or calibrated operational availability.

The development probe verified positive, strictly ordered, uncrossed full-depth snapshots on the exact 1e-8 representational lattice and disclosed identical duplicates and a disconnect. The panel normalizer separately checks all rows. In particular, startup event-time inversions found by normalization are preserved in the raw source; acquisition success does not override strict rejection or independently approve a later startup-handling protocol. All observation-age, gap, label-support, counterfactual and scientific-admission claims belong to the explicit normalized contracts and their review.

## Resources, accounting and code correction

The first-hour acquisition took **{summary['stages']['tardis_hour00']['elapsed_seconds']:.3f} seconds**. The full-day expansion took **{summary['stages']['tardis_full_day']['elapsed_seconds']/60:.3f} minutes** ({summary['stages']['tardis_full_day']['elapsed_seconds']:.3f} seconds). Panel charge is **{summary['panel_charged_bytes']:,} bytes**: measured response bodies plus 64 KiB per-request HTTP reserve. Including the r2 baseline, development probe, metadata and documentation reserve, cumulative charged bytes are **{summary['cumulative_charged_bytes']:,}** ({summary['cumulative_charged_bytes']/1024**3:.6f} GiB of 8 GiB). This is a conservative accounting convention, not NIC measurement or a proven packet-byte bound.

The downloader used two I/O threads. An initial ctypes affinity call lacked pointer signatures and silently failed; initial one-CPU affinity was requested but not enforced. The actual OS mask was corrected to 1 at 2026-09-21 14:33:34 UTC and independently verified thereafter. Before correction, average CPU use cannot establish an instantaneous cap. Last retained resource observation at {last['observed_at_utc']} records {last['cpu_seconds']:.3f} CPU seconds and {last['peak_working_set_bytes']:,} bytes peak working set observed by that time; this is not represented as a post-exit maximum. Exact executed code and the future-only corrected version are separately hashed in `executed_code_bindings.json`. The full-day preflight's original code path still resolves to the exact executed code. Python/OpenSSL/OS details are in `source_runtime.json`.

Used tmux sessions: `drc-lob-t008-r3-tardis-probe`, `drc-lob-t008-r3-tardis-hour00`, `drc-lob-t008-r3-tardis-full-day`, and `drc-lob-t008-r3-source-audit`; all completed. No paid source, signup, external publication or Git push was used. Source and workstation provenance remain local/private. The parent task owns the consolidated clean PDF, normalized input contracts and scientific handoff.
"""
with (BASE / "source_handoff.md").open("x", encoding="utf-8", newline="\n") as handle:
    handle.write(handoff)
with (BASE / "timing.log").open("a", encoding="utf-8", newline="\n") as handle:
    handle.write(dt.datetime.now(dt.timezone.utc).isoformat() + " Complete: all1728requests and independentcompressed/header/provenanceaudit passed; immutable sourcehandoff frozen.\n")
manifest_files = []
for path in sorted(BASE.rglob("*")):
    if path.is_file() and "__pycache__" not in path.parts and path.name != "source_manifest.json":
        manifest_files.append({"path": str(path.relative_to(BASE)), "bytes": path.stat().st_size, "sha256": sha(path)})
manifest = {"created_at": dt.datetime.now(dt.timezone.utc).isoformat(), "root": str(BASE),
            "scope": "Source artifacts only; excludes this manifest and disposable __pycache__; all listed files freshly hashed",
            "files": manifest_files, "listed_file_count": len(manifest_files),
            "exact_listed_retained_bytes": sum(row["bytes"] for row in manifest_files)}
write(BASE / "source_manifest.json", manifest)
print(json.dumps({"manifest_sha256": sha(BASE / "source_manifest.json"), "files": len(manifest_files),
                  "retained_listed_bytes": manifest["exact_listed_retained_bytes"], "BTC_rows": btc_rows,
                  "ETH_rows": eth_rows, "decoded_bytes": decoded, "compressed_bytes": compressed}))
