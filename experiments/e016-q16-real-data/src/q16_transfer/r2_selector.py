"""Prefix-only cohort selection and positive-quantity lifecycle projection.

Selection audits require an independently reconstructed, complete candidate stream.
A signed or hashed list alone cannot establish that candidates were not omitted.
The source-ordinal clock is a diagnostic ordering coordinate, never an exchange or
receipt time. These functions do not certify initial completeness or market FIFO.
"""
from copy import deepcopy
from decimal import Decimal, InvalidOperation

from adapter import units


def _integer(value, name):
    if type(value) is not int or value < 0:
        raise ValueError(f"Nonnegative integer {name} required")
    return value


def _exact_price(value):
    if not isinstance(value, str):
        raise ValueError("Decimal-string physical price required")
    try:
        price = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("Finite positive physical price required") from exc
    if not price.is_finite() or price <= 0:
        raise ValueError("Finite positive physical price required")
    return price


def freeze_anchors(candidates, limit=1000, clock_kind="source_ordinal",
                   specification="first-eligible-accepted-new-in-source-order/1"):
    """Freeze a prefix-selected cohort and retain every candidate's disposition.

    Each accepted/new candidate contains source_seq, candidate_id, decision,
    available, cohort_eligible, eligibility_reasons and past_certificates. Each
    certificate contains ref and available in the declared clock coordinate.
    Eligibility is a producer-supplied *past-only* fact, not inferred from future
    cancellations, ambiguity or enumerator success. Its scientific validity still
    needs reviewed evidence. Extra input fields are never used in selection.
    """
    if type(limit) is not int or not 1 <= limit <= 1000:
        raise ValueError("Frozen cohort limit must be between 1 and 1000")
    if clock_kind not in {"source_ordinal", "producer_availability_ns"}:
        raise ValueError("Declare ordinal diagnostic or producer availability clock")
    if not isinstance(specification, str) or not specification:
        raise ValueError("Predeclared selection specification required")
    ledger, selected, seen = [], [], set()
    previous = -1
    for candidate in candidates:
        seq = _integer(candidate["source_seq"], "source sequence")
        identity = candidate["candidate_id"]
        if seq <= previous:
            raise ValueError("Candidates reversed or duplicated; never sort to repair")
        if not isinstance(identity, str) or not identity or identity in seen:
            raise ValueError("Unique nonempty candidate IDs required")
        decision = _integer(candidate["decision"], "decision coordinate")
        available = _integer(candidate["available"], "candidate availability")
        eligible = candidate["cohort_eligible"]
        reasons = candidate["eligibility_reasons"]
        certificates = candidate["past_certificates"]
        if type(eligible) is not bool or not isinstance(reasons, list):
            raise ValueError("Boolean eligibility and explicit exclusion reasons required")
        if any(not isinstance(r, str) or not r for r in reasons):
            raise ValueError("Exclusion reasons must be nonempty strings")
        if eligible == bool(reasons):
            raise ValueError("Eligible candidates have no exclusions; ineligible ones explain why")
        if not isinstance(certificates, list):
            raise ValueError("Explicit past certificate list required")
        canonical_certificates = []
        for certificate in certificates:
            ref = certificate["ref"]
            maturity = _integer(certificate["available"], "certificate availability")
            if not isinstance(ref, str) or not ref or maturity > decision:
                raise ValueError("Only named certificates available by decision are allowed")
            canonical_certificates.append({"ref": ref, "available": maturity})
        if eligible and (available > decision or not canonical_certificates):
            raise ValueError("Eligible anchors need available observations and past evidence")
        take = eligible and len(selected) < limit
        disposition = ("selected" if take else "ineligible" if not eligible
                       else "not_selected_after_limit")
        ledger.append({"candidate_ordinal": len(ledger), "source_seq": seq,
                       "candidate_id": identity, "decision": decision,
                       "available": available, "cohort_eligible": eligible,
                       "eligibility_reasons": list(reasons),
                       "past_certificates": canonical_certificates,
                       "disposition": disposition,
                       "selected_ordinal": len(selected) if take else None})
        if take:
            selected.append({"candidate_id": identity, "source_seq": seq})
        previous = seq
        seen.add(identity)
    return {"schema": "q16-prefix-selection/1", "clock_kind": clock_kind,
            "specification": specification, "limit": limit,
            "candidate_count": len(ledger), "selected_count": len(selected),
            "selected": selected, "candidate_ledger": ledger,
            "audit_requirement": "Compare against independently reconstructed complete source candidate stream"}


def audit_selection(candidates, frozen, limit=1000, clock_kind="source_ordinal",
                    specification="first-eligible-accepted-new-in-source-order/1"):
    """Reject missing/reversed/substituted candidates or selected-cohort changes."""
    expected = freeze_anchors(candidates, limit=limit, clock_kind=clock_kind,
                              specification=specification)
    if expected != frozen:
        raise ValueError("Frozen selection differs from complete source candidate replay")
    return True


class PositiveLifecycle:
    """Keep physical identities after zero updates; emit positive A/C/T only.

    Input events use the existing adapter's normalized event/diff shape. Rows must
    already belong to one certified price level. Explicit zero-size cleanup is
    administrative and does not consume an economic-event horizon position.
    """

    def __init__(self, initial, quantum, initial_raw_seq=0):
        self.quantum = quantum
        self.last_seq = _integer(initial_raw_seq, "initial raw sequence")
        self.physical = {}
        for row in initial:
            if row["oid"] in self.physical:
                raise ValueError("Duplicate initial lifecycle identity")
            self.physical[row["oid"]] = units(row["sz"], quantum)
        self.used_ids = set(self.physical)
        self.economic_events = 0

    def project(self, event):
        """Apply one atomic source event and return projection plus full lineage."""
        physical, used = dict(self.physical), set(self.used_ids)
        fragments, lineage, trade_legs = [], [], []
        last_seq, quantity = self.last_seq, 0
        kind = event.get("kind")
        if not event.get("diffs"):
            raise ValueError("Source event requires lifecycle fragments")
        for row in event["diffs"]:
            seq = _integer(row["raw_seq"], "raw sequence")
            if seq <= last_seq:
                raise ValueError("Raw lifecycle sequence reversed or reused")
            last_seq = seq
            oid, change = row["oid"], row["raw_book_diff"]
            old = physical.get(oid)
            positive_before = [key for key, value in physical.items() if value > 0]
            if isinstance(change, dict) and set(change) == {"new"}:
                if oid in used:
                    raise ValueError("New lifecycle identity must not have been used")
                new = units(change["new"]["sz"], self.quantum)
                if new and kind != "A":
                    raise ValueError("Positive new quantity requires an A classification")
                physical[oid] = new
                used.add(oid)
                delta = new
                action = "economic_add" if delta else "administrative_zero_new"
            else:
                if old is None:
                    raise ValueError("Unknown lifecycle identity; no completeness inferred")
                if change == "remove":
                    new = 0
                    del physical[oid]
                elif isinstance(change, dict) and set(change) == {"update"}:
                    if units(change["update"]["origSz"], self.quantum) != old:
                        raise ValueError("Lifecycle origSz disagrees with preceding quantity")
                    new = units(change["update"]["newSz"], self.quantum)
                    physical[oid] = new
                else:
                    raise ValueError("Unknown lifecycle diff")
                delta = old - new
                if delta < 0:
                    raise ValueError("Size increase/reactivation needs explicit priority/reset model")
                if delta == 0 and old > 0:
                    raise ValueError("Positive no-op update outside declared event domain")
                action = ("economic_reduction" if delta else
                          "administrative_zero_cleanup" if change == "remove"
                          else "administrative_zero_update")
                if delta and kind not in {"C", "T"}:
                    raise ValueError("Positive reduction needs C/T classification")
                if delta and kind == "T":
                    if positive_before[0] != oid:
                        raise ValueError("Trade violates positive FIFO order")
                    trade_legs.append((oid, delta))
            if delta:
                fragments.append(deepcopy(row))
                quantity += delta
            lineage.append({"raw_seq": seq, "action": action,
                            "old_units": old, "new_units": new,
                            "economic_quantity_units": delta})
        if quantity and kind in {"A", "C"} and len(fragments) != 1:
            raise ValueError("Atomic A/C changes one positive order")
        declared = [(leg["oid"], units(leg["sz"], self.quantum))
                    for leg in event.get("fills", [])]
        if declared != trade_legs:
            raise ValueError("Execution ledger disagrees with positive reductions")
        projected = None
        if quantity:
            projected = deepcopy(event)
            projected["diffs"] = fragments
            self.economic_events += 1
        self.physical, self.used_ids, self.last_seq = physical, used, last_seq
        return {"event": projected, "lineage": lineage,
                "economic_event_ordinal": self.economic_events - 1 if quantity else None,
                "economic_quantity_units": quantity,
                "observed_positive_count": sum(q > 0 for q in physical.values()),
                "physical_live_identity_count": len(physical),
                "observed_positive_volume_units": sum(physical.values())}

def project_episode(episode, quantum, horizon=8):
    """Project a physical lifecycle episode before applying the exact Q16 adapter.

    Initial zero identities are retained privately. Every source fragment receives
    a lineage entry; projection stops after the predeclared economic horizon.
    """
    if type(horizon) is not int or horizon not in {8, 10}:
        raise ValueError("Q16 supports the original eight-event or supplementary ten-event horizon")
    price = _exact_price(episode["px"])
    state = PositiveLifecycle(episode["initial"], quantum, episode["initial_raw_seq"])
    projected = deepcopy(episode)
    projected["initial"] = [deepcopy(row) for row in episode["initial"]
                            if units(row["sz"], quantum) > 0]
    projected["events"], lineage = [], []
    previous_time = episode["start_ns"]
    previous_available = episode["initial_available_ns"]
    for source_event_ordinal, event in enumerate(episode["events"]):
        now, available = event["event_ns"], event["available_ns"]
        if (type(now) is not int or type(available) is not int or now < previous_time
                or available < max(now, previous_available)):
            raise ValueError("Clock inversion in physical event stream; never omit to repair")
        for row in event["diffs"]:
            row_price = _exact_price(row["px"])
            if ((row["coin"], row["side"], row_price)
                    != (episode["coin"], episode["side"], price)):
                raise ValueError("Physical fragment outside the declared positive price level")
        result = state.project(event)
        lineage.append({"source_event_ordinal": source_event_ordinal,
                        **{key: value for key, value in result.items() if key != "event"}})
        if result["event"] is not None:
            projected["events"].append(result["event"])
        previous_time, previous_available = now, available
        if len(projected["events"]) == horizon:
            break
    projected["horizon_complete"] = (len(projected["events"]) == horizon
                                      and episode["horizon_complete"] is True)
    return {"episode": projected, "lineage": lineage,
            "count_definition": "positive-size identities at this price level",
            "administrative_cleanup_consumes_horizon": False,
            "initial_completeness_certified_by_projection": False}
