"""Package and document the already-completed T-023 replay prefix."""
from __future__ import annotations

import csv
import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path


OUT = (Path(__file__).resolve().parents[1] / 'runtime')
WORKTREE = Path(__file__).resolve().parents[1]
CODE = WORKTREE / "experiments/t023-book-washout-mini"
INPUT = (Path(__file__).resolve().parents[1] / 'runtime' / 'input')
LIMIT = 4 * 1024**3


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path: Path, value) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def git(*args: str) -> str:
    return subprocess.check_output(["git", "-C", str(WORKTREE), *args], text=True).strip()


def fmt_int(value) -> str:
    return f"{int(value):,}"


def main() -> None:
    manifest_path = OUT / "manifest.json"
    if not manifest_path.exists():
        raise SystemExit("Replay manifest does not exist; preserve the running job and finalize only after it exits.")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    with (OUT / "hourly_metrics.csv").open(encoding="utf-8", newline="") as source:
        rows = list(csv.DictReader(source))
    if [int(row["hour"]) for row in rows] != list(range(len(rows))):
        raise ValueError("Hourly CSV is not an exact chronological prefix")

    tar_index = json.loads((OUT / "tar_index.json").read_text(encoding="utf-8"))
    members = sorted(tar_index["members"], key=lambda item: int(item["hour"]))
    target_payload = sum(int(member["size"]) for member in members)
    fixed_overhead = 512 + 512 * len(tar_index["headers"])
    transfer = fixed_overhead
    ceiling_hours = 0
    for member in members:
        if transfer + int(member["size"]) > LIMIT:
            break
        transfer += int(member["size"])
        ceiling_hours += 1

    code_out = OUT / "code"
    code_out.mkdir(exist_ok=True)
    names = ["probe.py", "replay.py", "test_replay.py", "plot_result.py", "finalize_result.py", "verify_result.py", "run.sh", "launch.sh"]
    for name in names:
        shutil.copy2(CODE / name, code_out / name)

    ranges = [json.loads(line) for line in (OUT / "ranges.jsonl").read_text(encoding="utf-8").splitlines() if line]
    range_valid = all(
        item.get("status") == 206
        and item.get("verified_length") is True
        and int(item["requested_bytes"]) == int(item["received_bytes"])
        for item in ranges
    )
    source_inputs = {}
    for name in ["source-discovery.json", "README.md", "SCHEMA.md", "read_data.py"]:
        path = INPUT / name
        source_inputs[name] = {"bytes": path.stat().st_size, "sha256": sha256(path)}

    total_update = sum(int(row["legacy_update"]) for row in rows)
    total_remove = sum(int(row["legacy_remove"]) for row in rows)
    manifest.update(
        provenance={
            "worktree": str(WORKTREE),
            "branch": git("branch", "--show-current"),
            "base_commit": "ed62f2a4ccebc7ad559ba0c185954401d5311cb8",
            "implementation_commit": git("rev-parse", "HEAD"),
        },
        source_inputs=source_inputs,
        range_receipts={
            "file": "ranges.jsonl",
            "sha256": sha256(OUT / "ranges.jsonl"),
            "records": len(ranges),
            "all_exact_206_ranges_length_verified": range_valid,
        },
        protocol_feasibility={
            "target_member_count": len(members),
            "target_compressed_payload_bytes": target_payload,
            "target_payload_gib": target_payload / 1024**3,
            "range_ceiling_bytes": LIMIT,
            "largest_chronological_prefix_within_ceiling_hours": ceiling_hours,
            "prefix_transfer_bytes_including_probe_and_tar_headers": transfer,
            "full_48_hours_fit_range_ceiling": target_payload + fixed_overhead <= LIMIT,
        },
        metrics={
            "btc_events": sum(int(row["btc_events"]) for row in rows),
            "new_events": sum(int(row["new_events"]) for row in rows),
            "update_events": sum(int(row["update_events"]) for row in rows),
            "remove_events": sum(int(row["remove_events"]) for row in rows),
            "first_seen_legacy_update": total_update,
            "first_seen_legacy_remove": total_remove,
            "first_seen_legacy_total": total_update + total_remove,
            "transition_anomaly_events": sum(int(row["anomaly_events"]) for row in rows),
            "tracked_live_orders_at_checkpoint": int(rows[-1]["tracked_live_orders"]) if rows else 0,
            "ever_seen_oids_at_checkpoint": int(rows[-1]["ever_seen_oids"]) if rows else 0,
        },
    )

    environment = """# T-023 execution environment

- Controller: Windows 11 `10.0.26200`, PowerShell.
- Replay: Ubuntu on WSL2, Linux `5.15.133.1-microsoft-standard-WSL2`, Python `3.12.3`.
- Replay packages: `requests==2.34.2`, `orjson==3.12.0`, `pyroaring==1.1.0`.
- Plotting: Windows Python `3.14.7`, `matplotlib==3.11.2`, `plotly==7.0.0`.
- CPU constraint: replay process affinity limited to two logical CPUs; parsing is causally sequential.
- Memory constraint: 8 GiB address-space limit.
- Random seed: none; no sampling or randomness was used.
- Detached runner: tmux session `drc-lob-q16-washout-mini`, protected by a one-hour `timeout` wrapper.
- Network: exact HTTP byte ranges with `Accept-Encoding: identity`; every accepted response required status 206, exact `Content-Range`, and exact byte length.
- Integrity: tar headers were checksum-validated by Python's `tarfile`; each completed gzip member was read to EOF, which validates its gzip CRC and uncompressed size. SHA-256 receipts are retained for headers, compressed members, and uncompressed JSONL.

Run `run.sh` inside WSL from a fresh output directory. Parameters are frozen in `replay.py`; the script intentionally accepts no command-line arguments.
"""
    (OUT / "ENVIRONMENT.md").write_text(environment, encoding="utf-8")

    last = manifest.get("last_legacy_discovery")
    last_text = (
        f"hour {last['hour']} (`{rows[int(last['hour'])]['hour_start_utc']}` file), member line {fmt_int(last['member_line'])}, "
        f"BTC event {fmt_int(last['btc_event_in_hour'])}, OID `{last['oid']}`, first seen as `{last['kind']}`"
        if last else "none in the completed prefix"
    )
    decision = manifest["operational_decision"]
    completed = int(manifest["completed_hours"])
    rows_md = "\n".join(
        f"| {row['hour']} | {fmt_int(row['btc_events'])} | {fmt_int(row['legacy_update'])} | "
        f"{fmt_int(row['legacy_remove'])} | {float(row['legacy_per_million_btc_events']):,.2f} | "
        f"{fmt_int(row['tracked_live_orders'])} | {fmt_int(row['anomaly_events'])} |"
        for row in rows
    )
    report = f"""# T-023 · BTC unknown-initial-book washout mini-experiment

**Assignment:** T-023 · **Experiment:** E-273 · **Question:** Q-026 · **Hypothesis:** H-027

## ELI5

Imagine entering a cinema after the film has started. Everyone you see enter is known from their arrival. A person already seated becomes detectable only when they move seats or leave. Someone who stays perfectly still remains invisible. Replaying order-book changes from an empty map works the same way: a first `new` is known, while a first `update` or `remove` reveals an order that was resting before replay began. A quiet period can show that no additional old orders moved during that period, but it cannot prove that no motionless old orders remain.

## What was actually run

The run used Zenodo record 18184441, DOI `10.5281/zenodo.18184441`, file `book_diffs_202512.tar`. It selected BTC and began at the predeclared `2025-12-01 00:00 UTC` boundary. Tar headers were fetched and checksum-validated to locate all 48 fixed hourly members. Each processed member was fetched by its exact byte range, hashed, decompressed alone, replayed in source order, and accepted only after gzip EOF/CRC validation. Raw member bytes were deleted after verified processing.

The run completed **{completed}/48 whole hours**, through **{manifest['achieved_end_exclusive']}** exclusive. It processed **{fmt_int(manifest['metrics']['btc_events'])} BTC events** and transferred **{fmt_int(manifest['transfer_bytes'])} bytes**. The active-time/resource stop was recorded as `{manifest.get('stop_reason')}`. No sampling or randomness was used.

## Result

| UTC hour index | BTC events | legacy by update | legacy by remove | legacy / million | live tracked | anomalies |
|---:|---:|---:|---:|---:|---:|---:|
{rows_md}

Across the completed prefix, **{fmt_int(total_update + total_remove)}** legacy OIDs were first revealed: **{fmt_int(total_update)}** by update and **{fmt_int(total_remove)}** by remove. The last discovery was {last_text}. The longest zero-discovery run was **{manifest['longest_zero_discovery_run_complete_hours']} complete hour(s)**. These are finite-prefix descriptions.

The predeclared 24-hour warm-up plus 24-hour holdout decision is **{decision.upper()}**. A pass requires all holdout hours 24–47 and zero first-seen legacy OIDs there; this run did not reach the holdout. No pass or rejection of H-027 is inferred from the observed prefix.

The frozen transfer ceiling independently prevents the full test: the 48 selected compressed members total **{fmt_int(target_payload)} bytes ({target_payload / 1024**3:.3f} GiB)** before tar-header/probe traffic, exceeding the **4 GiB** ceiling. At most **{ceiling_hours} chronological hours** fit even if runtime were unlimited.

## Certainty limits

- **Full-book mathematical certainty:** not certified. A silent initial order can remain unchanged beyond the observed prefix and never appear in a diff.
- **Finite-window operational convergence:** not decided because the completed prefix ends before hour 24 and the complete holdout was not observed.
- **Top-of-book or price-band evidence:** not claimed. No initial snapshot or external price-band certificate was introduced.

The source documentation reports complete monthly book diffs, but the records contain no event timestamps or block identifiers. This run therefore relies on hourly filenames and source line order for causal replay and cannot independently certify timestamp continuity or block atomicity. The last discovery is located by file hour and line position, never by an invented intra-hour timestamp.
"""
    (OUT / "REPORT.md").write_text(report, encoding="utf-8")

    handoff = f"""# T-023 handoff

## Supported conclusion

The verified chronological prefix contains continued first-seen legacy-order discoveries and therefore demonstrates that empty-state replay is not immediately a known book. The achieved horizon is **{completed} complete hour(s)** and does not include the predeclared holdout. Consequently, E-273 does **not** decide whether a 24-hour warm-up is operationally clean. It also cannot produce a deterministic full-book certificate because unchanged initial orders are observationally silent.

The frozen protocol cannot be completed within its own transfer ceiling: all 48 selected members require **{target_payload / 1024**3:.3f} GiB** of compressed payload, excluding range receipts, while the ceiling is 4 GiB. The preserved checkpoint is exact only through hour {completed - 1 if completed else 'none'}; any interrupted next member was discarded and is not counted.

## Next concrete action

For a successor evaluation of H-027, add tested checkpoint resume, raise the range budget above the measured fixed-window payload (recommend at least 4.5 GiB), and allow enough runtime for all 48 members. Resume from the verified hour-{completed} checkpoint and withhold a pass unless hours 24–47 are all processed with zero legacy discoveries. An initial exchange snapshot would be required for a stronger full-book certificate.

## Evidence map

- `manifest.json`: IDs, source provenance, exact processed ranges/hashes, resource accounting, metrics, limitations, and completion state.
- `hourly_metrics.csv`: one row per complete gzip-verified hour.
- `record_examples.json`: compact records with original field names and replay classifications.
- `legacy_by_hour.png` and `legacy_by_hour.html`: fixed-window visualization; unobserved hours are visually distinct from zeros.
- `ranges.jsonl`, `tar_index.json`, `processed_members.json`: transport and archive receipts.
- `checkpoint.json`, `seen_oids.roaring`, `live_orders.json`: exact end-of-prefix replay state.
- `code/` and `ENVIRONMENT.md`: implementation and execution environment.
"""
    (OUT / "HANDOFF.md").write_text(handoff, encoding="utf-8")

    artifact_names = [
        "hourly_metrics.csv", "record_examples.json", "ranges.jsonl", "tar_index.json",
        "processed_members.json", "checkpoint.json", "seen_oids.roaring", "live_orders.json",
        "ENVIRONMENT.md", "REPORT.md", "HANDOFF.md", "legacy_by_hour.png", "legacy_by_hour.html",
    ]
    artifact_names.extend(f"code/{name}" for name in names)
    manifest["artifacts"] = {
        name: {"bytes": (OUT / name).stat().st_size, "sha256": sha256(OUT / name)}
        for name in artifact_names if (OUT / name).exists()
    }
    manifest["retained_bytes_after_packaging"] = sum(
        path.stat().st_size for path in OUT.rglob("*") if path.is_file()
    )
    manifest["packaged_utc"] = datetime.now(timezone.utc).isoformat()
    atomic_json(manifest_path, manifest)
    with (OUT / "timing.log").open("a", encoding="utf-8") as timing:
        timing.write(f"{datetime.now(timezone.utc).isoformat()} Packaged manifest, reports, environment, and code\n")
    print(json.dumps({"completed_hours": completed, "decision": decision, "target_payload": target_payload,
                      "ceiling_hours": ceiling_hours, "range_receipts_valid": range_valid}, indent=2))


if __name__ == "__main__":
    main()
