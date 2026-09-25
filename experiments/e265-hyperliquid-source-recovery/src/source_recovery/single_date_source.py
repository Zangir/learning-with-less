"""E270 source-only validation of one frozen retained BTC sampled-L2 day."""
from settings import BASE, NS, SEED, bind, now, pin, read, save, sha, utc_ns
from pathlib import Path
from bisect import bisect_right
import csv
import hashlib
import importlib.util
import json
import shutil
import sys
import time
import traceback
from urllib.parse import parse_qs, urlsplit

OUT = BASE / "T-018/r3-single-date-source"
DATE = "2026-02-01"
CAP = 256 * 1024**2
sys.dont_write_bytecode = True


def stamp(note):
    line = now() + " " + note
    print(line, flush=True)
    with (OUT / "timing.log").open("a", encoding="utf-8") as stream:
        stream.write(line + "\n")


def lines(path, values):
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for value in values:
            stream.write(json.dumps(value, separators=(",", ":")) + "\n")
    if sum(p.stat().st_size for p in OUT.rglob("*") if p.is_file()) > CAP:
        raise MemoryError("New retained source allocation exceeded")


def normalizer():
    origins = (("r3/code/paired_startup30_normalize.py", "baaa8e779a9eb1cbd8aa63ade9e81a3f2b981efc3a3bcc46f3a71fd42cf5d946"),
               ("r2/code/producer_interface.py", "198f2739168fea742e6c94a34cb1728f62cc738b1056e5a48e1fb7ac40ab0eb0"))
    bindings = []
    for name, digest in origins:
        origin = BASE / "T-008" / name
        assert sha(origin) == digest
        target = OUT / "code/vendor/T-008" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(origin, target)
        bindings.append(dict(original=bind(origin), executed=bind(target)))
    save(OUT / "normalizer-bindings.json", bindings)
    spec = importlib.util.spec_from_file_location("e270_exact_startup30", bindings[0]["executed"]["path"])
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fixtures(N):
    base = utc_ns(DATE + "T00:00:00Z")
    def line(event_ms, receipt_ms, change_deep=False):
        data = dict(coin="BTC", time=base//1_000_000+event_ms,
                    levels=[[dict(px=str(100-i), sz="1", n=1) for i in range(20)],
                            [dict(px=str(102+i), sz="2", n=2) for i in range(20)]])
        if change_deep:
            data["levels"][0][10]["n"] = 2
        receipt = f"{DATE}T00:00:{receipt_ms//1000:02d}.{receipt_ms%1000:03d}Z"
        return receipt + " " + json.dumps(dict(channel="l2Book", data=data))
    def run(values):
        return N.normalize_lines(((i, 0, i, value) for i, value in enumerate(values)),
                                 DATE, base+30*NS, base+86400*NS, 2*NS)
    checks = []
    result = run([line(29000,29000), line(28000,29001), line(31000,31001)])
    assert len(result[-1]) == 2 and result[0]["BTC"][0]["source_ordinal"] == 2
    checks.append("Receipt-prefix inversions excluded before event-order checks; no prefix state carried")
    for name, values in (("Late old event inversion rejected before event-window filtering", [line(29000,31000),line(28000,32000)]),
                         ("Conflicting full-payload tie beyond top five rejected", [line(31000,31001),line(31000,32000,True)])):
        try:
            run(values)
        except ValueError:
            checks.append(name)
        else:
            raise AssertionError(name)
    result = run([line(31000,31001),line(31000,31002),line(33000,33001),"",line(35001,35002)])
    assert len(result[0]["BTC"]) == 3 and len(result[2]["BTC"]) == 1
    assert result[3]["BTC"] == [(0,2),(2,3)]
    checks += ["Identical full-payload duplicate collapsed with lineage", "Exactly2s gap retained; >2s gap and disconnect split segments"]
    assert N.asof([base],base+1_500_000_000,1_500_000_000) == 0
    assert N.asof([base],base+1_500_000_001,1_500_000_000) is None
    checks.append("Freshness includes1.5s and rejects1.5s+1ns")
    save(OUT / "source-fixtures.json", dict(origin="synthetic_integration", passed=len(checks), checks=checks))


def acquisition(N, declaration):
    index_path = Path(declaration["raw_index"]["path"])
    assert sha(index_path) == declaration["raw_index"]["sha256"]
    index = read(index_path)
    assert [r["offset"] for r in index["records"]] == list(range(0,1440,10))
    records, proofs = [], []
    for item in index["records"]:
        r = item["receipt"]
        u = urlsplit(r["url"])
        q = parse_qs(u.query)
        offset = item["offset"]
        assert u.scheme == "https" and u.netloc == "api.tardis.dev" and u.path == "/v1/data-feeds/hyperliquid"
        assert q["from"] == [DATE+"T00:00:00.000Z"] and q["offset"] == [str(offset)]
        assert q["sliceSize"] == ["10"] and q["compression"] == ["gzip"]
        assert json.loads(q["filters"][0]) == [dict(channel="l2Book",symbols=["BTC","ETH"])]
        assert r["date"] == DATE and r["complete"] and r["status"] == 200
        assert r["headers"]["x-name"] == "hyperliquid/2026/02/01/"+f"{offset//60:02d}/{offset%60:02d}"
        assert r["headers"]["x-slice-size"] == "10"
        assert int(r["headers"]["Content-Length"]) == r["received_bytes"]
        assert r["protocol_sha256"] == sha(BASE / "T-018/r1/q18_later/protocol.json")
        adapted = dict(date=DATE, offset=offset, status=200, completed=True,
            compressed_path=item["compressed_path"], compressed_sha256=item["compressed_sha256"],
            compressed_bytes=r["received_bytes"], decoded_sha256=item["decoded_sha256"], decoded_bytes=r["decoded_bytes"])
        proof = N.verify_acquisition(adapted)
        proof["original_receipt"] = r
        proofs.append(proof)
        records.append(adapted)
    save(OUT / "acquisition_proof.json", dict(new_download_bytes=0, mode="Retained exact-source reuse",
        original_index=bind(index_path), new_declaration=bind(OUT/"source-request-declaration.json"), partitions=proofs))
    return records


def grid(rows, segments, start, end, destination):
    events = [r["event_ns"] for r in rows]
    valid, missing, stale = 0, 0, 0
    with destination.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(("cut_ns","segment_id","supported","source_ordinal","source_event_ns","age_ns","reason"))
        sid = 0
        for cut in range(start,end,NS):
            while sid < len(segments) and cut >= segments[sid]["end_ns"]:
                sid += 1
            if sid == len(segments) or cut < segments[sid]["start_ns"]:
                writer.writerow((cut,"",False,"","","","outside_actual_segment_endpoints"))
                missing += 1
                continue
            index = bisect_right(events,cut)-1
            s = segments[sid]
            assert s["first_row_index"] <= index < s["stop_row_index"]
            age = cut-events[index]
            supported = age <= 1_500_000_000
            valid += supported
            stale += not supported
            writer.writerow((cut,sid,supported,rows[index]["source_ordinal"],events[index],age,"" if supported else "age_above1.5s"))
    return dict(grid_cuts=valid+missing+stale,supported=valid,outside_segments=missing,stale=stale,
                scope="Source freshness only; no strategy events, features, labels or model execution")


def execute(proc):
    d = read(OUT / "source-request-declaration.json")
    assert d["date"] == DATE and d["asset"] == "BTC" and not d["execution_enabled"]
    N = normalizer()
    fixtures(N)
    stamp("Frozen source request and inherited normalizer verified; checking all144 retained HTTP partitions")
    records = acquisition(N,d)
    base = utc_ns(DATE+"T00:00:00Z")
    start,end = base+30*NS,base+86400*NS
    stamp("All compressed/decoded hashes, CRCs, request and receipt partitions verified; strict normalization starts")
    rows, provenance, duplicates, parts, disconnects, excluded, prefix = N.normalize_lines(N.record_lines(records),DATE,start,end,2*NS)
    # Both assets share the retained wire files; only BTC is supplied to this cohort.
    rows,provenance,duplicates,parts = rows["BTC"],provenance["BTC"],duplicates["BTC"],parts["BTC"]
    assert rows
    for row in rows:
        row["source_id"] = d["source_id"]
    segments = []
    for sid,(first,stop) in enumerate(parts):
        N.P.validate_rows(rows[first:stop],2*NS,depth=5)
        segments.append(dict(segment_id=sid,first_row_index=first,stop_row_index=stop,
            start_ns=rows[first]["event_ns"],end_ns=rows[stop-1]["event_ns"]+1,
            first_source_ordinal=rows[first]["source_ordinal"],last_source_ordinal=rows[stop-1]["source_ordinal"]))
    dest = OUT / "BTC"
    dest.mkdir(exist_ok=True)
    lines(dest/"state_rows.jsonl",rows)
    lines(dest/"source_provenance.jsonl",provenance)
    lines(OUT/"receipt_prefix_exclusions.jsonl",prefix)
    save(dest/"duplicate_ledger.json",duplicates)
    save(dest/"source_segments.json",segments)
    save(OUT/"disconnects.json",disconnects)
    save(OUT/"event_window_exclusions.json",excluded)
    readback = 0
    with (dest/"state_rows.jsonl").open(encoding="utf-8") as stream:
        for expected,raw in zip(rows,stream,strict=True):
            assert json.loads(raw) == expected
            readback += 1
    freshness = grid(rows,segments,start,end,dest/"grid_audit.csv")
    gaps = [dict(before_source_ordinal=a["source_ordinal"],after_source_ordinal=b["source_ordinal"],gap_ns=b["event_ns"]-a["event_ns"])
            for a,b in zip(rows,rows[1:]) if b["event_ns"]-a["event_ns"] > 2*NS]
    save(dest/"gaps.json",gaps)
    summary = dict(at=now(),producer_outcome="source_valid_pending_independent_review",date=DATE,
        partitions=len(records),rows=len(rows),provenance_rows=len(provenance),identical_duplicates=len(duplicates),
        receipt_prefix_exclusions_BTC=sum(p["asset"]=="BTC" for p in prefix),event_window_exclusions_BTC=excluded["BTC"],
        source_segments=len(segments),disconnect_markers=len(disconnects),gaps_above2s=len(gaps),
        first_event_ns=rows[0]["event_ns"],last_event_ns=rows[-1]["event_ns"],
        first_receipt_ns=provenance[0]["provider_receipt_ns"],last_receipt_ns=provenance[-1]["provider_receipt_ns"],
        depth_min=min(min(p["raw_bid_depth"],p["raw_ask_depth"]) for p in provenance),
        roundtrip_rows=readback,grid=freshness,peak_working_set_bytes=proc.memory_info().peak_wset,
        cpu_affinity=proc.cpu_affinity(),seed=SEED,strategy_outcomes_computed=0,new_network_bytes=0)
    assert summary["peak_working_set_bytes"] < 8*1024**3
    save(OUT/"source_validation.json",summary)
    evidence = ("duplicate_ledger.json","grid_audit.csv","gaps.json")
    contract = dict(schema="t008-producer-state/2",version="E270-source-only-1",asset="BTC",date=DATE,
        producer="T018",experiment="E270",purpose="One declared sampled-L2 persistence input; no empirical release",
        clock_scope="exchange_time",origin="exploratory_real",fixture_only=False,
        selected_event_start_ns=start,selected_event_end_ns=end,
        actual_first_event_ns=rows[0]["event_ns"],actual_last_event_ns=rows[-1]["event_ns"],
        startup_exclusion_ns=30*NS,execution_enabled=False,review=dict(status="not_issued_by_producer"),
        acquisition_proof_file="../acquisition_proof.json",acquisition_proof_sha256=sha(OUT/"acquisition_proof.json"),
        policy_file="../source-request-declaration.json",policy_sha256=sha(OUT/"source-request-declaration.json"),
        source_acquisition_policy_file=str(BASE/"T-018/r1/q18_later/protocol.json"),source_acquisition_policy_sha256=sha(BASE/"T-018/r1/q18_later/protocol.json"),
        receipt_prefix_exclusions_file="../receipt_prefix_exclusions.jsonl",receipt_prefix_exclusions_sha256=sha(OUT/"receipt_prefix_exclusions.jsonl"),
        source_provenance_file="source_provenance.jsonl",source_provenance_sha256=sha(dest/"source_provenance.jsonl"),
        normalizer_source_file="../code/vendor/T-008/r3/code/paired_startup30_normalize.py",normalizer_code_sha256=sha(Path(N.__file__)),
        reused_producer_code_sha256=sha(BASE/"T-008/r2/code/producer_interface.py"),
        supply_wrapper=bind(__file__),sources=[dict(file="state_rows.jsonl",sha256=sha(dest/"state_rows.jsonl"),source_id=d["source_id"])],
        continuity=dict(kind="sampled_snapshots",all_venue_events_observed=False,cadence_ns=NS,max_age_ns=1_500_000_000,
            max_gap_ns=2*NS,source_segments_file="source_segments.json",source_segments_sha256=sha(dest/"source_segments.json")),
        evidence_files={name:sha(dest/name) for name in evidence},units=dict(price="USD per BTC *1e8",size="BTC *1e8",count="positive visible native order count",time="UTC Unix nanoseconds"),
        exposure=d["exposure"],limitations=["Provider provenance only; no exchange authentication or calibrated latency",
            "Full receipt-day request does not imply every exchange event or every grid cut observed",
            "No Q16 native-order proof or downstream strategy outcome supplied"],
        consumer_binding="Use the contract's exact source_id as load_day source_id; row and provenance schemas and event/segment/freshness policy unchanged")
    save(dest/"shared_data_contract.E270.json",contract)
    stamp(f"BTC source normalization complete: {len(rows)} unique rows, {len(duplicates)} duplicate receipts, {len(segments)} segments")


def main():
    proc = pin()
    started = time.monotonic()
    try:
        execute(proc)
    except Exception as error:
        save(OUT/"source_failure.json",dict(at=now(),producer_outcome="invalid_or_unavailable",
            error_type=type(error).__name__,reason=str(error),traceback=traceback.format_exc(),
            candidate=DATE,substitution_attempted=False,execution_enabled=False))
        raise
    finally:
        save(OUT/"normalization_terminal.json",dict(at=now(),elapsed_seconds=time.monotonic()-started,
            peak_working_set_bytes=proc.memory_info().peak_wset,cpu_affinity=proc.cpu_affinity(),
            source_failure=(OUT/"source_failure.json").exists(),strategy_execution=False))


if __name__ == "__main__":
    main()
