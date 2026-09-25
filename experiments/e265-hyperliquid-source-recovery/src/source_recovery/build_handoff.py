"""Compile source availability, exact consumer contracts and measured resources."""
from settings import OUT, PRIOR, EXCHANGE, SEED, bind, now, pin, read, save, stamp
from acquire_sources import BASE_RETENTION, BASE_TRANSFER, DOCUMENTATION_RESERVE
import csv
from datetime import datetime, timezone
from pathlib import Path
import shutil
import subprocess


def contracts():
    sources = []
    for kind, folder in (("receipt_l2",OUT/"receipt_quotes"),
                         ("later_l2",OUT/"q18_later/normalized"),
                         ("native_bbo",OUT/"bbo_native/normalized")):
        for path in sorted(folder.glob("*/*.contract.json")):
            c = read(path)
            sources.append(dict(kind=kind, contract_path=str(path), contract=c))
    return sources


def main():
    pin()
    assert (OUT/"bbo_native/normalized_manifest.json").exists(), "BBO jobs unfinished"
    assert (OUT/"q18_later/manifest.json").exists(), "Later-depth jobs unfinished"
    records=contracts()
    assert len(records)==58, len(records)
    available=[]
    for r in records:
        c=r["contract"]
        available.append(dict(source=r["kind"],date=c["date"],asset=c["asset"],rows=c["rows"],
            source_status=c.get("source_status",c.get("producer_source_status")),defects=len(c["defects"]),
            contract_path=r["contract_path"],contract_sha256=bind(r["contract_path"])["sha256"],
            parquet_path=c["parquet"]["path"],parquet_sha256=c["parquet"]["sha256"],
            parquet_bytes=c["parquet"]["bytes"]))
    with (OUT/"source_availability.csv").open("w",newline="",encoding="utf-8") as stream:
        writer=csv.DictWriter(stream,fieldnames=list(available[0]))
        writer.writeheader();writer.writerows(available)
    save(OUT/"source_availability.json",available)
    premises=("initial_relevant_level","contiguous_native_actions","interior_action_order",
        "atomic_action_grouping","resting_tail_priority","quantity_domain",
        "execution_cancel_correspondence","complete_candidate_lineage")
    save(OUT/"Q16.source_checkpoint.json",dict(schema="q16-offline-source-checkpoint/1",producer="T-018",
        empirical_admission=False,scientific_result="unavailable, not a negative",payload=None,
        required_horizons=[8,10],premises={p:dict(supported=False,reason="No complete native source packet obtained") for p in premises},
        achieved_source_progress="Block-tagged actual diff/status/fill sample parsed and retained; no source-order/checkpoint certificate",
        alternative=bind(OUT/"native_alternatives.json"),mac_access=bind(OUT/"mac_access.json"),
        next_asset="Relevant-price resting checkpoint at or before height1075858800, contiguous native actions through1075858999 including empty-block evidence, action/source-order map and applicable priority/quantity rules; an analogous source-chosen interval is acceptable",
        access_alternatives=["Restore existing configured Mac research access and identify dataset root",
            "Supply authorized no-cost Dwellir/native-provider snapshot+replay export; native archive coverage is advertised but no unauthenticated endpoint or price is known"],
        acquisition_status="Ownership retained at this exact recoverable checkpoint"))
    bbo=[r for r in available if r["source"]=="native_bbo"]
    l2=[r for r in available if r["source"]!="native_bbo"]
    save(OUT/"Q17.source_contract.json",dict(schema="q17-source-contract/1",producer="T-018",source="native_bbo",
        receipt_clock="Provider-claimed contemporaneous local arrival timestamp, exactly preserved; not archive fetch time; physical calibration unverified",
        feature_and_grid_clock="receipt_ns",label_and_endpoint_clock="event_ns",price_scale=100_000_000,
        quantity_scale=100_000_000,contract_type="Hyperliquid linear perpetual",
        required_fields=["bid_px_e8","ask_px_e8","bid_sz_e8","ask_sz_e8","event_ns","receipt_ns","segment_id","source_ordinal"],
        optional_fields=["bid_n","ask_n"],protocol=bind(OUT/"bbo_native/protocol.json"),inputs=bbo,
        past_support_seconds=20,future_support_seconds=10.5,cache_spacing_train_seconds=5,cache_spacing_eval_seconds=11,
        schedule_opportunities=12,schedule_spacing_seconds=11,
        admission="All listed data source-valid at producer" if not any(r["defects"] for r in bbo) else "Some listed data invalid; required panel may be unavailable",
        review_status="Pending independent review; this does not assert model results or coordinator acceptance",
        consumer_rule="Freeze adaptation and cohort before fitting; no cross-segment schedules/history/labels; last-source right-asof at ordered timestamp ties; source on-change silence is not a fixed-cadence gap"))
    save(OUT/"Q18.source_contract.json",dict(schema="q18-source-contract/1",producer="T-018",source="native-format sampled l2Book",
        required_fields="Top-five bid/ask prices and quantities, event_ns, receipt_ns, source ordinal/changes and discontinuities",
        order_counts_required=False,counts_status="Actually observed auxiliary n columns retained; not part of the required original Q18 representation",
        timing_slots="Consumer reconstruction must explicitly define own-prefix timing; imported original views.py is absent",
        intervention="55s shift of cached view including its history; own-time midpoint normalization; target remains future10s at g",
        semantics="Provider arrival timestamp retained; original quote feature builder reconstruction remains a separate consumer qualification",
        inputs=l2,later_protocol=bind(OUT/"q18_later/protocol.json"),
        preservation="Accepted prior freshness result and old event-time contracts unchanged; new source fields do not authorize a redundant rerun",
        required_history_seconds=20,total_shifted_lookback_seconds=75,cache_train_seconds=5,cache_eval_seconds=11,
        review_status="Pending independent source review; model/representation review remains separate"))
    receipts=[read(p) for p in (OUT/"acquisition").glob("*.receipt.json")]
    for folder in (OUT/"bbo_native/raw",OUT/"q18_later/raw"):
        receipts += [read(p) for p in folder.glob("*/*.json")]
    retained=sum(p.stat().st_size for p in OUT.rglob("*") if p.is_file())
    measured=sum(r["received_bytes"] for r in receipts)
    charge=sum(r["charged_bytes"] for r in receipts)
    resource=dict(at=now(),baseline_retained_bytes=BASE_RETENTION,baseline_charged_transfer_bytes=BASE_TRANSFER,
        new_response_body_bytes=measured,new_charged_transfer_bytes=charge,documentation_reserve_bytes=DOCUMENTATION_RESERVE,
        cumulative_charged_transfer_bytes=BASE_TRANSFER+charge+DOCUMENTATION_RESERVE,
        t018_current_retained_bytes=retained,finalization_reserve_bytes=32*1024**2,
        cumulative_retained_with_finalization_reserve=BASE_RETENTION+retained+32*1024**2,
        free_C_bytes=shutil.disk_usage(OUT).free,transfer_cap=8*1024**3,retention_cap=12*1024**3,
        cpu_affinity=[0,1],memory_cap=8*1024**3,model_fits=0,accounting="Response bytes plus2x transfer charge and16KiB/request; documentation reserve covers unmetered web search/view responses; not NIC metering")
    assert resource["cumulative_charged_transfer_bytes"]<=resource["transfer_cap"]
    assert resource["cumulative_retained_with_finalization_reserve"]<=resource["retention_cap"]
    assert resource["free_C_bytes"]>=50*1024**3
    save(OUT/"resource_accounting.json",resource)
    sessions=[]
    for path in sorted((OUT/"logs").glob("*.exit")):
        sessions.append(dict(job=path.stem,exit_code=int(path.read_text()),terminal_evidence=bind(path),log=bind(path.with_suffix(".log"))))
    save(OUT/"job_terminal_evidence.json",sessions)
    save(OUT/"handoff_summary.json",dict(at=now(),task="T-018",experiment="E-265",seed=SEED,
        source_contracts=len(records),bbo_rows=sum(r["rows"] for r in bbo),l2_rows=sum(r["rows"] for r in l2),
        source_defects=sum(r["defects"] for r in available),q16_empirical_episodes=0,
        empirical_finding="Not evaluated by source owner; supplied input contracts enable distinct consumer runs",
        git_revision=subprocess.check_output(["git","rev-parse","HEAD"],text=True).strip()))
    stamp("All source inputs compiled into per-consumer handoff; resource totals checked")


if __name__ == "__main__":
    main()
