"""Adapt certified atomic Hyperliquid ledger episodes to Q16 observations.

Raw diffs alone cannot determine event kind or a complete queue. Certification
and review are checked by admission.py; this module checks the ledger itself.
"""
from decimal import Decimal, InvalidOperation
from fractions import Fraction

from core import State, advance, check_truth, initial_states, labels


def units(value, quantum):
    if not isinstance(value, str) or not isinstance(quantum, str):
        raise ValueError("Decimal strings required; floats would hide rounding")
    try:
        number, lot = Decimal(value), Decimal(quantum)
        if not number.is_finite() or not lot.is_finite() or lot <= 0 or number < 0:
            raise ValueError("Invalid exact quantity")
        ratio = Fraction(number) / Fraction(lot)
    except (InvalidOperation, ZeroDivisionError) as exc:
        raise ValueError("Invalid exact quantity") from exc
    if ratio.denominator != 1:
        raise ValueError("Quantity is not on the declared exact lattice")
    return ratio.numerator


def adapt_episode(episode, quantum, cap=100000):
    """Retain cancellations; censor incomplete eight-event observation windows."""
    if episode["coin"] != "BTC" or episode["side"] not in {"A", "B"}:
        raise ValueError("Frozen pilot scope is one BTC price level")
    try:
        price = Decimal(episode["px"])
        if not price.is_finite() or price <= 0:
            raise ValueError("Finite positive price required")
    except InvalidOperation as exc:
        raise ValueError("Invalid price string") from exc
    if episode["probe_cancellable"] is not True:
        raise ValueError("Real cohort must include cancellable orders")
    if len(episode["events"]) > 8:
        raise ValueError("Eight-event horizon is frozen")
    probe_id = episode["probe_id"]
    book = [(row["oid"], units(row["sz"], quantum)) for row in episode["initial"]]
    if not book or book[-1][0] != probe_id:
        raise ValueError("Probe must be a newly accepted tail order")
    if len({oid for oid, _ in book}) != len(book) or any(q <= 0 for _, q in book):
        raise ValueError("Initial queue IDs must be unique and sizes positive")
    probe = book[-1][1]
    volume = initial_states(sum(q for _, q in book[:-1]), probe, cap)
    count = {state for state in volume if len(state.queue) == len(book)}
    truth = State(tuple((q, oid == probe_id) for oid, q in book))
    check_truth(truth, count, volume, probe)
    initial_time = episode["start_ns"]
    if type(initial_time) is not int or type(episode["initial_available_ns"]) is not int:
        raise ValueError("Integer nanosecond clocks required")
    if episode["initial_available_ns"] > initial_time:
        raise ValueError("Initial state unavailable at decision time")
    previous_time, previous_seq = initial_time, episode["initial_raw_seq"]
    previous_available = episode["initial_available_ns"]
    if type(previous_seq) is not int:
        raise ValueError("Integer source sequence required")
    used_ids = {oid for oid, _ in book}
    observations, max_states = [], len(volume)
    for event in episode["events"]:
        kind = event["kind"]
        if kind not in {"A", "C", "T"} or not event.get("evidence_refs"):
            raise ValueError("Certified event classification/provenance required")
        now, available = event["event_ns"], event["available_ns"]
        if type(now) is not int or type(available) is not int:
            raise ValueError("Integer nanosecond clocks required")
        if now < previous_time or available < max(now, previous_available):
            raise ValueError("Clock inversion or invalid release; never sort to repair")
        fragments = event["diffs"]
        if not fragments or (kind in {"A", "C"} and len(fragments) != 1):
            raise ValueError("A/C affects one order; T uses certified atomic grouping")
        before_book = list(book)
        filled, cancelled, quantity = truth.filled, truth.cancelled, 0
        trade_legs = []
        for row in fragments:
            seq = row["raw_seq"]
            if type(seq) is not int or seq <= previous_seq:
                raise ValueError("Raw order reversed or reused; no sorting allowed")
            previous_seq = seq
            try:
                row_price = Decimal(row["px"])
                if not row_price.is_finite():
                    raise ValueError("Finite price required")
            except InvalidOperation as exc:
                raise ValueError("Invalid fragment price string") from exc
            if (row["coin"], row["side"], row_price) != (
                    episode["coin"], episode["side"], price):
                raise ValueError("Fragment outside the certified price level")
            oid, change = row["oid"], row["raw_book_diff"]
            if kind == "A":
                if not isinstance(change, dict) or set(change) != {"new"} or oid in used_ids:
                    raise ValueError("Addition must be a fresh order")
                q = units(change["new"]["sz"], quantum)
                if q <= 0:
                    raise ValueError("Zero-size addition")
                used_ids.add(oid)
                book.append((oid, q))
                quantity += q
                continue
            indexes = [i for i, (key, _) in enumerate(book) if key == oid]
            if not indexes:
                raise ValueError("Unknown order: initialization or continuity failure")
            index = indexes[0]
            old = book[index][1]
            if change == "remove":
                new = 0
            elif isinstance(change, dict) and set(change) == {"update"}:
                old_field = units(change["update"]["origSz"], quantum)
                new = units(change["update"]["newSz"], quantum)
                if old_field != old:
                    raise ValueError("Update quantity disagrees with preceding state")
            else:
                raise ValueError("Reduction requires update/remove diff")
            delta = old - new
            if delta <= 0:
                raise ValueError("Non-reduction needs an explicit priority/reset model")
            if kind == "T" and index != 0:
                raise ValueError("Trade violates FIFO queue order")
            if kind == "T":
                trade_legs.append((oid, delta))
                filled += delta if oid == probe_id else 0
            else:
                cancelled += delta if oid == probe_id else 0
            book[index:index + 1] = [(oid, new)] if new else []
            quantity += delta
        if kind == "T":
            declared = [(leg["oid"], units(leg["sz"], quantum)) for leg in event["fills"]]
            if declared != trade_legs:
                raise ValueError("Execution ledger does not reconcile with exact reductions")
            # Multiple maker fragments form one T, not extra information for either arm.
        elif event.get("fills"):
            raise ValueError("Add/cancel event cannot also contain executions")
        expected_volume = sum(q for _, q in before_book) + (quantity if kind == "A" else -quantity)
        if sum(q for _, q in book) != expected_volume:
            raise ValueError("Level quantity conservation failed")
        truth = State(tuple((q, oid == probe_id) for oid, q in book), filled, cancelled)
        volume = advance(volume, kind, quantity, cap, probe_cancellable=True)
        count = advance(count, kind, quantity, cap, probe_cancellable=True)
        count = {state for state in count if len(state.queue) == len(book)}
        check_truth(truth, count, volume, probe)
        max_states = max(max_states, len(volume))
        observations.append({"kind": kind, "quantity_units": quantity,
                             "volume_units": sum(q for _, q in book),
                             "order_count": len(book), "event_ns": now,
                             "available_ns": available})
        previous_time, previous_available = now, available
    complete = len(observations) == 8 and episode["horizon_complete"] is True
    if not complete:
        return {"episode_id": episode["episode_id"], "status": "censored",
                "reason": "Incomplete eight-event horizon; no ambiguity score",
                "observed_events": len(observations), "max_states": max_states}
    return {"episode_id": episode["episode_id"], "status": "scored",
            "volume": labels(volume, probe), "count": labels(count, probe),
            "truth": labels({truth}, probe), "cancelled_units": truth.cancelled,
            "probe_units": probe, "max_states": max_states,
            "volume_state_count": len(volume), "count_state_count": len(count),
            "observations": observations}
