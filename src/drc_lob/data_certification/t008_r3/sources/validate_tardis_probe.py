"""Offline source-shape diagnostics, without forecasting labels or fitting."""
from collections import Counter
from decimal import Decimal
import hashlib
import json
from pathlib import Path

BASE = Path(__file__).resolve().parent
SOURCE = BASE / "tardis_20251201_0000_0010.raw.jsonl"

def units(text):
    if not isinstance(text, str):
        raise ValueError("Price/size must be decimal text")
    number = Decimal(text) * 100000000
    if number != number.to_integral_exact() or number <= 0:
        raise ValueError("Invalid representational lattice")
    return int(number)

def run():
    seen = {"BTC": {}, "ETH": {}}
    issues = []
    duplicates = []
    gaps = []
    disconnects = []
    prior = {}
    local_prior = None
    receipt_inversions = []
    counts = Counter()
    for ordinal, line in enumerate(SOURCE.read_text().splitlines()):
        if not line.strip():
            disconnects.append(ordinal)
            continue
        local, message = line.split(" ", 1)
        if local_prior is not None and local < local_prior:
            receipt_inversions.append(ordinal)
        local_prior = local
        parsed = json.loads(message)
        data = parsed["data"]
        coin = data["coin"]
        timestamp = data["time"]
        try:
            levels = data["levels"]
            if len(levels) != 2 or any(len(side) != 20 for side in levels):
                raise ValueError("Wrong depth")
            prices = []
            for side_index, side in enumerate(levels):
                p = [units(level["px"]) for level in side]
                for level in side:
                    units(level["sz"])
                    if not isinstance(level["n"], int) or isinstance(level["n"], bool) or level["n"] <= 0:
                        raise ValueError("Invalid order count")
                if any((a <= b if side_index == 0 else a >= b) for a, b in zip(p, p[1:])):
                    raise ValueError("Unordered prices")
                prices.append(p)
            if prices[0][0] >= prices[1][0]:
                raise ValueError("Crossed/locked BBO")
        except Exception as exc:
            issues.append({"source_line_zero_based": ordinal, "error": str(exc)})
        identity = json.dumps(data, sort_keys=True, separators=(",", ":"))
        if timestamp in seen[coin]:
            old_ordinal, old_identity = seen[coin][timestamp]
            duplicates.append({"coin": coin, "event_ms": timestamp, "first_source_line": old_ordinal,
                               "duplicate_source_line": ordinal, "identical_full_depth": identity == old_identity})
        else:
            seen[coin][timestamp] = ordinal, identity
        if coin in prior and timestamp - prior[coin][1] > 2000:
            gaps.append({"coin": coin, "prior_source_line": prior[coin][0], "source_line": ordinal,
                         "event_gap_ms": timestamp-prior[coin][1]})
        prior[coin] = ordinal, timestamp
        counts[coin] += 1
    result = {"source_path": str(SOURCE), "source_sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
              "rows": counts, "shape_lattice_order_issues": issues,
              "same_event_timestamp_duplicates": duplicates, "event_gaps_over_2s": gaps,
              "disconnect_source_lines": disconnects, "receipt_inversion_source_lines": receipt_inversions,
              "interpretation": "Development source diagnostic only; no model outcomes inspected"}
    (BASE / "tardis_development_validation.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))

if __name__ == "__main__":
    run()
