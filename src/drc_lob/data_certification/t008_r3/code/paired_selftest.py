"""Focused adversarial checks of source, cut and acquisition integrity semantics."""
import copy
import gzip
import hashlib
import json
from pathlib import Path
import tempfile
import sys
sys.dont_write_bytecode = True
import paired_normalize as N


def run():
    results = []
    date = "2025-12-01"
    base = N.utc_ns(date+"T00:00:00Z")
    def line(ms, asset="BTC", tweak=None):
        data = {"coin": asset, "time": base//1_000_000+ms,
                "levels": [[{"px": str(100-i), "sz": "1", "n": 1} for i in range(20)],
                           [{"px": str(102+i), "sz": "2", "n": 2} for i in range(20)]]}
        if tweak:
            tweak(data)
        return date+"T00:00:00.1234567Z "+json.dumps({"channel": "l2Book", "data": data})
    def normalize(values):
        return N.normalize_lines(((i, 0, i, value) for i,value in enumerate(values)), date, base, base+3600*N.NS, 2*N.NS)
    def rejected(fn):
        try:
            fn()
        except (ValueError, KeyError, OSError):
            return
        raise AssertionError("Expected rejection")
    def check(name, fn):
        fn()
        results.append({"name": name, "passed": True})
    def yes(value):
        assert value
    check("exact_submicrosecond_provider_time", lambda: yes(N.utc_ns(date+"T00:00:00.1234567Z") == base+123456700))
    check("full_depth_conflict_rejected_beyond_top5", lambda: rejected(lambda: normalize([line(0), line(0, tweak=lambda d: d["levels"][0][19].update(sz="3"))])))
    check("inversion_rejected_without_sorting", lambda: rejected(lambda: normalize([line(1), line(0)])))
    check("identical_tie_keeps_first_source_ordinal", lambda: yes(normalize([line(0), line(0), line(1)])[0]["BTC"][0]["source_ordinal"] == 0 and len(normalize([line(0), line(0), line(1)])[2]["BTC"]) == 1))
    check("interleaved_assets_keep_independent_event_order", lambda: yes(len(normalize([line(1), line(0, "ETH"), line(2)])[0]["BTC"]) == 2))
    check("disconnect_splits_even_small_event_gap", lambda: yes(len(normalize([line(0), "", line(100)])[3]["BTC"]) == 2))
    check("disconnect_then_duplicate_still_splits_next_row", lambda: yes(len(normalize([line(0), "", line(0), line(100)])[3]["BTC"]) == 2))
    check("source_gap_splits", lambda: yes(len(normalize([line(0), line(2001)])[3]["BTC"]) == 2))
    check("age_boundary_inclusive_separate_from_gap", lambda: yes(N.asof([base], base+1500000000, 1500000000) == 0 and N.asof([base], base+1500000001, 1500000000) is None))
    check("out_of_event_period_excluded_not_date_relabelled", lambda: yes(normalize([line(-17), line(0)])[5]["BTC"]["before"] == 1))
    check("uncalibrated_receipt_never_admission", lambda: yes(normalize([line(0)])[0]["BTC"][0]["release_ns"] is None and normalize([line(0)])[0]["BTC"][0]["admission_evidence_ns"] is None))
    check("nonpositive_native_count_rejected", lambda: rejected(lambda: normalize([line(0, tweak=lambda d: d["levels"][0][0].update(n=0))])))
    check("disconnect_splits_both_assets", lambda: yes(all(len(x) == 2 for x in normalize([line(0), line(0, "ETH"), "", line(100), line(100, "ETH")])[3].values())))
    check("receipt_inversion_rejected", lambda: rejected(lambda: normalize([line(0).replace('.1234567Z','.9Z'), line(100)])))
    check("request_boundary_does_not_split_stream", lambda: yes(len(N.normalize_lines([(0,0,0,line(0)),(1,1,0,line(100))],date,base,base+3600*N.NS,2*N.NS)[3]["BTC"]) == 1))
    binding_record = {"date": date, "offset": 0, "role": "train", "protocol_sha256": "x",
        "url": 'https://api.tardis.dev/v1/data-feeds/hyperliquid?from='+date+'T00%3A00%3A00.000Z&offset=0&sliceSize=10&compression=gzip&filters=%5B%7B%22channel%22%3A%22l2Book%22%2C%22symbols%22%3A%5B%22BTC%22%2C%22ETH%22%5D%7D%5D',
        "response_headers": {"x-name": "hyperliquid/2025/12/01/00/00", "x-slice-size": "10"}}
    def bind(record):
        return N.verify_policy_binding([record], date, {"Q17":"train","Q18":"train"}, {"roles_Q17":{date:"train"},"roles_Q18":{date:"train"}}, "x", base, base+600*N.NS)
    check("correct_request_binding_passes", lambda: bind(binding_record))
    for key, value in (("date", "2025-11-01"), ("role", "test"), ("protocol_sha256", "wrong"), ("offset", 10)):
        bad = copy.deepcopy(binding_record)
        bad[key] = value
        check("wrong_"+key+"_rejected", lambda bad=bad: rejected(lambda: bind(bad)))
    bad = copy.deepcopy(binding_record)
    bad["response_headers"]["x-name"] = "hyperliquid/2025/12/01/00/10"
    check("wrong_HTTP_response_partition_rejected", lambda: rejected(lambda: bind(bad)))
    with tempfile.TemporaryDirectory(prefix="t008-paired-tests-") as temporary:
        path = Path(temporary)
        rows, _, _, segments, _, _ = normalize([line(ms) for ms in range(0, 240000, 500)])
        policy = {"max_age_ns": 1500000000, "max_gap_ns": 2*N.NS}
        diagnostics, windows, _ = N.audit(rows["BTC"], segments["BTC"], policy, path)
        check("no_future_guard_beyond_last_source", lambda: yes(all(x["cut_ns"]+105*N.NS//10 <= rows["BTC"][-1]["event_ns"] for scope in diagnostics["decisions"].values() for x in scope)))
        check("q18_exact75s_support", lambda: yes(diagnostics["decisions"]["Q18"][0]["cut_ns"] == base+75*N.NS))
        check("q17_exact20s_support", lambda: yes(diagnostics["decisions"]["Q17"][0]["cut_ns"] == base+20*N.NS))
        check("q17_disjoint_schedules_do_not_share_slots", lambda: yes(all(a["last_cut_ns"] < b["first_cut_ns"] for a,b in zip(diagnostics["q17_disjoint_schedule_12x11s"], diagnostics["q17_disjoint_schedule_12x11s"][1:]))))
        check("future_mask_marked_retrospective", lambda: yes("Retrospective" in diagnostics["mask_semantics"]))
        data = (line(0)+"\n").encode()
        compressed = path / "sample.gz"
        compressed.write_bytes(gzip.compress(data, mtime=0))
        record = {"status": 200, "completed": True, "compressed_path": str(compressed), "compressed_bytes": compressed.stat().st_size,
            "compressed_sha256": N.P.sha256(compressed), "decoded_bytes": len(data), "decoded_sha256": hashlib.sha256(data).hexdigest()}
        check("compressed_and_decoded_chain_verified", lambda: yes(N.verify_acquisition(record)["gzip_crc_and_decoded_hash_reverified"]))
        bad = copy.deepcopy(record)
        bad["decoded_sha256"] = "0"*64
        check("decoded_digest_mismatch_rejected", lambda: rejected(lambda: N.verify_acquisition(bad)))
        bad = copy.deepcopy(record)
        bad["compressed_sha256"] = "0"*64
        check("compressed_digest_mismatch_rejected", lambda: rejected(lambda: N.verify_acquisition(bad)))
        normalized = path / "state_rows.jsonl"
        normalized.write_text("tampered\n")
        N.write_json(path / "shared_data_contract.v2.2.0.json", {"sources":[{"file":normalized.name,"sha256":"0"*64}]})
        check("tampered_normalized_bytes_rejected", lambda: rejected(lambda: N.verify_output(path)))
    output = N.ROOT / "interface"
    output.mkdir(exist_ok=True)
    N.write_json(output / "paired_synthetic_checks.json", {"origin": "synthetic_integration", "passed": len(results), "failed": 0, "checks": results})
    print(json.dumps({"passed": len(results), "failed": 0}))


if __name__ == "__main__":
    run()
