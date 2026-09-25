"""Past-only levels/opportunities, with retrospective support kept separate.

This module contains no outcome labels, price barriers, learning or utility code.
Prices use doubled units8, so midpoints and threshold comparisons stay exact.
"""
from bisect import bisect_right
from collections import defaultdict
from fractions import Fraction
from hashlib import sha256
import json

NS = 1_000_000_000
AGE = 1_500_000_000
GAP = 2 * NS


def stable_hash(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def fraction_record(value):
    value = Fraction(value)
    return {"numerator": value.numerator, "denominator": value.denominator,
            "unit": "doubled_units8_price"}


def row_validity(row, depth):
    for side in ("bid", "ask"):
        arrays = [row.get(side + "_" + key, []) for key in
                  ("prices_units8", "sizes_units8", "counts")]
        if any(len(values) < depth for values in arrays):
            return "missing_depth"
        if any(type(v) is not int or v <= 0 for values in arrays for v in values[:depth]):
            return "invalid_level_value"
        prices = arrays[0][:depth]
        if any((a <= b if side == "bid" else a >= b) for a, b in zip(prices, prices[1:])):
            return "unordered_depth"
    if row["bid_prices_units8"][0] >= row["ask_prices_units8"][0]:
        return "crossed_or_locked_bbo"
    return None


def bbo_projection(row, age_ns):
    return [row["bid_prices_units8"][0], row["ask_prices_units8"][0],
            row["bid_sizes_units8"][0], row["ask_sizes_units8"][0],
            row["bid_counts"][0], row["ask_counts"][0], age_ns]


def detect(previous_mid2, current_mid2, level):
    """Raw candidates only. Equality choices are part of the frozen protocol."""
    epsilon = Fraction(level["epsilon2"]["numerator"], level["epsilon2"]["denominator"])
    found = []
    for side, outward, price in (("resistance", 1, level["resistance_mid2"]),
                                  ("support", -1, level["support_mid2"])):
        before, current = outward * (previous_mid2 - price), outward * (current_mid2 - price)
        if before <= epsilon < current:
            found.append({"family": "breakout", "side": side, "direction": outward})
        if before < -epsilon and -epsilon <= current <= epsilon:
            found.append({"family": "rebound", "side": side, "direction": -outward})
    return found


class OpportunityState:
    """Only recorded opportunities may consume a slot or advance a clock."""
    def __init__(self):
        self.slots = set()
        self.last_recorded = {}

    def process(self, candidates):
        if not candidates:
            return []
        assert len({c["decision_ns"] for c in candidates}) == 1
        results, groups = [], defaultdict(list)
        for candidate in candidates:
            if candidate.get("past_rejection"):
                results.append({**candidate, "status": "rejected", "reason": candidate["past_rejection"]})
            else:
                groups[candidate["family"]].append(candidate)
        for family in sorted(groups):
            group = groups[family]
            # A tie is not an invitation to let loop order choose a trade.
            if len({c["side"] for c in group}) > 1:
                results.extend({**c, "status": "rejected", "reason": "two_sided_ambiguity"} for c in group)
                continue
            for candidate in group:
                cut, anchor, side = (candidate[k] for k in ("decision_ns", "anchor_ns", "side"))
                slot = family, side, anchor
                if slot in self.slots:
                    reason = "used_slot"
                elif family in self.last_recorded and cut - self.last_recorded[family] < 10 * NS:
                    reason = "cooldown"
                else:
                    self.slots.add(slot)
                    self.last_recorded[family] = cut
                    results.append({**candidate, "status": "recorded", "reason": None})
                    continue
                results.append({**candidate, "status": "rejected", "reason": reason})
        return sorted(results, key=lambda c: (c["family"], c["side"]))


class Observations:
    """No sort, interpolation, tail extrapolation, or inherited consumer masks."""
    def __init__(self, rows, declared_segments, restriction_start, restriction_end):
        self.start, self.restriction_end = restriction_start, restriction_end
        self.rows = [r for r in rows if restriction_start <= r["event_ns"] < restriction_end]
        self.times = [r["event_ns"] for r in self.rows]
        self.segments = {}
        declared = {s["segment_id"]: s for s in declared_segments}
        previous = None
        for row in self.rows:
            if type(row["event_ns"]) is not int or type(row["source_ordinal"]) is not int:
                raise ValueError("Source time/ordinal must be exact integers")
            sid = row["segment_id"]
            bound = declared[sid]
            if not bound["start_ns"] <= row["event_ns"] < bound["end_ns"]:
                raise ValueError("Row lies outside its inherited source segment")
            if previous:
                if row["event_ns"] <= previous["event_ns"] or row["source_ordinal"] <= previous["source_ordinal"]:
                    raise ValueError("Retained source ordering failed; sorting forbidden")
                if sid == previous["segment_id"] and row["event_ns"] - previous["event_ns"] > GAP:
                    raise ValueError("Unsegmented native gap")
                if sid == previous["segment_id"] and row.get("disconnect_epoch") != previous.get("disconnect_epoch"):
                    raise ValueError("Unsegmented disconnect")
            previous = row
            if sid not in self.segments:
                self.segments[sid] = {"segment_id": sid, "start_ns": row["event_ns"],
                    "first_source_ordinal": row["source_ordinal"]}
            self.segments[sid].update(end_ns=min(row["event_ns"] + 1, restriction_end, bound["end_ns"]),
                                      last_source_ordinal=row["source_ordinal"])
        self.end = min(restriction_end, self.times[-1] + 1) if self.times else restriction_start
        self.grid = {t: self.lookup(t) for t in range(((self.start + NS - 1) // NS) * NS, self.end, NS)}

    def lookup(self, cut):
        record = {"cut_ns": cut, "valid": False, "reason": "outside_retained_support"}
        if cut < self.start or cut >= self.end:
            return record
        i = bisect_right(self.times, cut) - 1
        if i < 0:
            return record
        row = self.rows[i]
        sid = row["segment_id"]
        age = cut - row["event_ns"]
        record.update(row_index=i, source_ordinal=row["source_ordinal"], segment_id=sid,
                      event_ns=row["event_ns"], age_ns=age)
        if not self.segments[sid]["start_ns"] <= cut < self.segments[sid]["end_ns"]:
            return record
        if age > AGE:
            record["reason"] = "stale_asof"
            return record
        record["reason"] = row_validity(row, 1)
        if record["reason"]:
            return record
        record.update(valid=True, depth_rejection=row_validity(row, 5),
                      mid2=row["bid_prices_units8"][0] + row["ask_prices_units8"][0],
                      spread2=2 * (row["ask_prices_units8"][0] - row["bid_prices_units8"][0]),
                      bbo=bbo_projection(row, age))
        return record

    def history(self, cuts, sid=None, require_depth=False):
        records = []
        for cut in cuts:
            record = self.grid.get(cut, {"cut_ns": cut, "valid": False, "reason": "outside_retained_support"})
            if not record["valid"]:
                return [], record["reason"], cut
            if sid is None:
                sid = record["segment_id"]
            if record["segment_id"] != sid:
                return [], "segment_change", cut
            if require_depth and record["depth_rejection"]:
                return [], record["depth_rejection"], cut
            records.append(record)
        return records, None, None

    def level(self, anchor):
        points, reason, bad_cut = self.history(range(anchor - 60 * NS, anchor, NS))
        record = {"anchor_ns": anchor, "valid": False, "reason": reason, "first_bad_cut_ns": bad_cut}
        if reason:
            return record
        mids = [p["mid2"] for p in points]
        spreads = sorted(p["spread2"] for p in points)
        epsilon = max(Fraction(mids[-1], 10000), Fraction(spreads[29] + spreads[30], 2))
        record.update(resistance_mid2=max(mids), support_mid2=min(mids), epsilon2=fraction_record(epsilon),
            segment_id=points[0]["segment_id"], cut_ns=[p["cut_ns"] for p in points],
            source_ordinals=[p["source_ordinal"] for p in points])
        if max(mids) - min(mids) < 4 * epsilon:
            record["reason"] = "range_below_4epsilon"
        else:
            record.update(valid=True, reason=None)
        return record


def extract(observations, protocol_sha256):
    state = OpportunityState()
    levels, candidates, events, blocked = {}, [], [], []
    for cut, current in observations.grid.items():
        anchor = cut // (60 * NS) * (60 * NS)
        if anchor not in levels:
            levels[anchor] = observations.level(anchor)
        level = levels[anchor]
        if not level["valid"]:
            blocked.append({"cut_ns": cut, "reason": "level:" + level["reason"]})
            continue
        trigger, reason, _ = observations.history([cut - NS, cut], sid=level["segment_id"])
        if reason:
            blocked.append({"cut_ns": cut, "reason": "trigger:" + reason})
            continue
        found = detect(trigger[0]["mid2"], trigger[1]["mid2"], level)
        if not found:
            continue
        feature, reason, bad_cut = observations.history(range(cut - 60 * NS, cut + NS, NS),
                                                        sid=level["segment_id"], require_depth=True)
        group = [{**c, "decision_ns": cut, "anchor_ns": anchor,
                  "past_rejection": "feature:" + reason if reason else None,
                  "first_bad_cut_ns": bad_cut} for c in found]
        selected = state.process(group)
        candidates.extend(selected)
        for chosen in selected:
            if chosen["status"] != "recorded":
                continue
            event_id = stable_hash([protocol_sha256, cut, anchor, chosen["family"], chosen["side"]])
            history = [{k: point[k] for k in ("cut_ns", "source_ordinal", "event_ns", "age_ns", "bbo")}
                       for point in feature]
            events.append({**chosen, "event_id": event_id, "protocol_sha256": protocol_sha256,
                "segment_id": level["segment_id"], "source_id": observations.rows[current["row_index"]]["source_id"],
                "decision_source_ordinal": current["source_ordinal"], "decision_mid2": current["mid2"],
                "level_mid2": level[chosen["side"] + "_mid2"], "epsilon2": level["epsilon2"],
                "feature_min_ns": anchor - 60 * NS, "feature_max_ns": cut,
                "history_source_ordinals": [point["source_ordinal"] for point in feature],
                "feature_history": history, "feature_history_sha256": stable_hash(history)})
    return {"levels": list(levels.values()), "candidates": candidates, "events": events,
            "blocked_cuts": blocked}


def retrospective_support(observations, events):
    """Inspect only future support metadata; never future price movements."""
    masks = []
    for event in events:
        cuts = range(event["decision_ns"] + NS, event["decision_ns"] + 11 * NS, NS)
        points, reason, bad_cut = observations.history(cuts, sid=event["segment_id"])
        masks.append({"event_id": event["event_id"], "decision_ns": event["decision_ns"],
            "complete_future_support": reason is None, "censor_reason": reason,
            "first_bad_cut_ns": bad_cut,
            "future_support_refs": [{k: p[k] for k in ("cut_ns", "source_ordinal", "event_ns", "age_ns")}
                                    for p in points]})
    return masks
