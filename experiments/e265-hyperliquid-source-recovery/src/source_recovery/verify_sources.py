"""Independent row-lineage checks and temporal/decimal boundary fixtures."""
from settings import OUT, NS, bind, now, pin, read, save, sha, stamp, utc_ns
from export_receipt_quotes import integer8
from export_native_bbo import project as bbo_project
from bisect import bisect_right
import gzip
import hashlib
import json
from pathlib import Path
import time
import pyarrow.parquet as pq


def fixtures():
    assert integer8("0.00000001") == 1
    assert integer8("90123.50") == 9_012_350_000_000
    for bad in ("-1", "0.000000001", "NaN", "1e3"):
        try:
            integer8(bad)
        except ValueError:
            pass
        else:
            raise AssertionError("Decimal must reject rather than round")
    assert utc_ns("2025-07-01T00:00:00.123456789Z") % NS == 123456789
    # The observation has happened at the exchange but has not arrived yet.
    event, receipt, cut = [0,900], [0,1100], 1000
    assert bisect_right(event,cut)-1 == 1
    assert bisect_right(receipt,cut)-1 == 0
    assert bisect_right([0,900,900],900)-1 == 2
    try:
        bbo_project(dict(bbo=[dict(px="100",sz="1",n=1),dict(px="99",sz="1",n=1)]))
    except ValueError:
        pass
    else:
        raise AssertionError("Crossed BBO must not be admitted")
    return dict(exact_decimal_conversion=True, invalid_precision_rejected=True,
                nanosecond_receipt_preserved=True, receipt_event_counterexample=True,
                ordered_ties_preserved=True, crossed_quote_rejected=True)


def independent_row_check(contract_path, native=False):
    contract = read(contract_path)
    path = contract["parquet"]["path"]
    assert sha(path) == contract["parquet"]["sha256"]
    table = pq.read_table(path)
    count = table.num_rows
    indices = sorted(set((0,count//4,count//2,3*count//4,count-1)))
    lineage = read(contract["raw_manifest" if native else "raw_sources"]["path"])
    by_offset = {r["offset"]: r for r in lineage}
    receipts = []
    for index in indices:
        row = table.slice(index,1).to_pylist()[0]
        origin = by_offset[row["slice_offset_minutes"]]
        source = origin["raw" if native else "compressed"]["path"]
        with gzip.open(source,"rb") as stream:
            for line_number,line in enumerate(stream):
                if line_number == row["slice_line_ordinal"]:
                    break
            else:
                raise ValueError("Missing source line")
        expected_hash = hashlib.sha256(line).digest() if native else hashlib.sha256(line).hexdigest()
        assert row["raw_line_sha256"] == expected_hash
        receipt, text = line.decode().split(" ",1)
        data = json.loads(text)["data"]
        assert data["coin"] == contract["asset"]
        assert utc_ns(receipt) == row["receipt_ns"]
        assert int(data["time"])*1_000_000 == row["event_ns"]
        if native:
            for side, level in zip(("bid","ask"),data["bbo"]):
                # Independent Decimal route checks the fast fixed-point parser.
                from decimal import Decimal
                assert int(Decimal(level["px"])*100_000_000) == row[side+"_px_e8"]
                assert int(Decimal(level["sz"])*100_000_000) == row[side+"_sz_e8"]
        else:
            from decimal import Decimal
            for side,levels in zip(("bid","ask"),data["levels"]):
                for k,level in enumerate(levels[:5]):
                    assert int(Decimal(level["px"])*100_000_000) == row[f"{side}_px_e8_{k}"]
                    assert int(Decimal(level["sz"])*100_000_000) == row[f"{side}_sz_e8_{k}"]
        receipts.append(dict(output_row=index, source_offset=row["slice_offset_minutes"],
                             source_line=row["slice_line_ordinal"], matched=True))
    return dict(contract=bind(contract_path), rows=count, sampled_lineage_checks=receipts)


def main():
    pin()
    start=time.monotonic()
    result=dict(at=now(),fixtures=fixtures(),checks=[])
    for path in sorted((OUT/"receipt_quotes").glob("*/*.contract.json")):
        result["checks"].append(independent_row_check(path))
    for path in sorted((OUT/"q18_later/normalized").glob("*/*.contract.json")):
        result["checks"].append(independent_row_check(path))
    for path in sorted((OUT/"bbo_native/normalized").glob("*/*.contract.json")):
        result["checks"].append(independent_row_check(path, native=True))
    result["elapsed_seconds"]=time.monotonic()-start
    result["review_scope"]="Engineering verification by source owner; independent scientific review remains required"
    save(OUT/"source_verification.json",result)
    stamp(f"Source verification: {len(result['checks'])} contracts, exact sampled row lineage and boundary fixtures passed")


if __name__ == "__main__":
    main()
