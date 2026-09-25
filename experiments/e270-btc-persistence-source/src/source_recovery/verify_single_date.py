"""Independent serialization, lineage, segment and source-grid checks for E270."""
from settings import BASE, NS, bind, now, pin, read, save, sha
from single_date_source import OUT, DATE, stamp
from pathlib import Path
import json
import time
import numpy as np
import pyarrow.parquet as pq


def main():
    proc = pin()
    started = time.monotonic()
    contract = read(OUT / "BTC/shared_data_contract.E270.json")
    dest = OUT / "BTC"
    original = BASE / f"T-018/r1/q18_later/normalized/{DATE}/BTC.parquet"
    old_contract = read(original.with_suffix(".contract.json"))
    assert sha(original) == old_contract["parquet"]["sha256"]
    # The earlier parser used string arithmetic; this export used Decimal.
    prior = {r["source_ordinal"]:r for r in pq.read_table(original).to_pylist()}
    rows = []
    with (dest/"state_rows.jsonl").open(encoding="utf-8") as stream:
        for raw in stream:
            r = json.loads(raw)
            p = prior[r["source_ordinal"]]
            assert r["event_ns"] == p["event_ns"]
            assert r["release_ns"] is None and r["admission_evidence_ns"] is None
            assert r["source_id"] == contract["sources"][0]["source_id"] and r["asset"] == "BTC"
            for side in ("bid","ask"):
                for key,old in (("prices_units8","px_e8"),("sizes_units8","sz_e8"),("counts","n")):
                    assert r[f"{side}_{key}"] == [p[f"{side}_{old}_{k}"] for k in range(5)]
            rows.append(r)
    ordinals = [r["source_ordinal"] for r in rows]
    times = np.array([r["event_ns"] for r in rows],dtype=np.int64)
    assert all(a<b for a,b in zip(ordinals,ordinals[1:])) and np.all(np.diff(times)>0)
    ledger = read(dest/"duplicate_ledger.json")
    removed = {r["duplicate_source_ordinal"] for r in ledger}
    assert set(prior)-set(ordinals) == removed
    assert len(prior) == len(rows)+len(ledger)
    provenance = {}
    with (dest/"source_provenance.jsonl").open(encoding="utf-8") as stream:
        for raw in stream:
            p = json.loads(raw)
            assert p["source_ordinal"] not in provenance
            old = prior[p["source_ordinal"]]
            assert p["provider_receipt_ns"] == old["receipt_ns"] and p["event_ns"] == old["event_ns"]
            assert p["raw_bid_depth"] >= 5 and p["raw_ask_depth"] >= 5
            provenance[p["source_ordinal"]] = p
    assert set(provenance) == set(prior)
    for duplicate in ledger:
        a = provenance[duplicate["retained_source_ordinal"]]
        b = provenance[duplicate["duplicate_source_ordinal"]]
        assert a["event_ns"] == b["event_ns"]
        assert a["full_payload_sha256"] == b["full_payload_sha256"]
    segments = read(dest/"source_segments.json")
    expected_parts = []
    first = 0
    for i in range(1,len(rows)):
        if times[i]-times[i-1]>2*NS or provenance[ordinals[i]]["disconnect_epoch"] != provenance[ordinals[i-1]]["disconnect_epoch"]:
            expected_parts.append((first,i));first=i
    expected_parts.append((first,len(rows)))
    assert expected_parts == [(s["first_row_index"],s["stop_row_index"]) for s in segments]
    for s in segments:
        assert s["start_ns"] == rows[s["first_row_index"]]["event_ns"]
        assert s["end_ns"] == rows[s["stop_row_index"]-1]["event_ns"]+1
    cuts = np.arange(contract["selected_event_start_ns"],contract["selected_event_end_ns"],NS,dtype=np.int64)
    indices = np.searchsorted(times,cuts,side="right")-1
    support = np.zeros(len(cuts),dtype=bool)
    for s in segments:
        within = (cuts>=s["start_ns"]) & (cuts<s["end_ns"])
        chosen = indices[within]
        assert np.all((chosen>=s["first_row_index"]) & (chosen<s["stop_row_index"]))
        support[within] = cuts[within]-times[chosen] <= 1_500_000_000
    import csv
    with (dest/"grid_audit.csv").open(encoding="utf-8") as stream:
        actual = list(csv.DictReader(stream))
    assert len(actual) == len(cuts)
    for i,r in enumerate(actual):
        assert int(r["cut_ns"]) == cuts[i]
        assert (r["supported"]=="True") == support[i]
    bound = []
    for key in ("acquisition_proof","policy","source_acquisition_policy","receipt_prefix_exclusions","source_provenance"):
        p = (dest/contract[key+"_file"]).resolve()
        assert sha(p) == contract[key+"_sha256"];bound.append(bind(p))
    for name,digest in contract["evidence_files"].items():
        assert sha(dest/name) == digest;bound.append(bind(dest/name))
    assert sha(dest/contract["sources"][0]["file"]) == contract["sources"][0]["sha256"]
    preserved = []
    for entry in read(OUT/"preservation-before.json"):
        assert sha(entry["path"]) == entry["sha256"]
        preserved.append(entry)
    save(OUT/"producer_verification.json",dict(at=now(),elapsed_seconds=time.monotonic()-started,
        state_rows_compared=len(rows),all_30_fields_match_independent_prior_parser=True,
        receipt_rows_preserved=len(provenance),identical_duplicate_rows=len(ledger),
        segment_boundaries_reconstructed=len(segments),source_grid_cuts_checked=len(cuts),
        supported_grid_cuts=int(support.sum()),contract=bind(dest/"shared_data_contract.E270.json"),
        prior_dual_clock_input=bind(original),bound_files=bound,preserved_inputs=preserved,
        cpu_affinity=proc.cpu_affinity(),peak_working_set_bytes=proc.memory_info().peak_wset,
        scope="Producer cross-checks only; exact-source independent review still required; zero strategy execution"))
    stamp(f"Independent parser parity and source-grid verification passed for {len(rows)} rows and {len(cuts)} cuts")


if __name__ == "__main__":
    main()
