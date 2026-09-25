"""Scalable exact outcome projection after lifecycle-to-positive-queue validation."""
from fractions import Fraction

from adapter import units
from r2_selector import project_episode
from r2_symbolic import SymbolicQueue

ORIGINS = {"synthetic_integration", "exploratory_real", "eligible_empirical"}


def evaluate_episode(physical_episode, quantum, origin, timeout_ms=2000, horizon=8):
    if origin not in ORIGINS:
        raise ValueError("Explicit producer origin required")
    if origin != "synthetic_integration" and physical_episode["probe_cancellable"] is not True:
        raise ValueError("Observed real cohort retains cancellations; protected probe is a synthetic comparator")
    if (type(physical_episode["start_ns"]) is not int
            or type(physical_episode["initial_available_ns"]) is not int):
        raise ValueError("Initial clocks must be integer nanoseconds")
    projected = project_episode(physical_episode, quantum, horizon=horizon)
    if any(not physical_episode["events"][row["source_event_ordinal"]].get("evidence_refs")
           for row in projected["lineage"]):
        raise ValueError("Every consumed economic/administrative classification requires evidence references")
    episode = projected["episode"]
    initial, probe_id = episode["initial"], episode["probe_id"]
    if not initial or initial[-1]["oid"] != probe_id:
        raise ValueError("Positive probe must be a new tail order")
    if episode["initial_available_ns"] > episode["start_ns"]:
        raise ValueError("Initial evidence is unavailable at the declared decision")
    probe = units(initial[-1]["sz"], quantum)
    ahead = [units(row["sz"], quantum) for row in initial[:-1]]
    counts = [len(initial)]
    events, cancel_origins = [], {}
    origins = {row["oid"]: i for i, row in enumerate(initial)}
    for row in projected["lineage"]:
        if row["economic_event_ordinal"] is not None:
            counts.append(row["observed_positive_count"])
    for index, event in enumerate(episode["events"]):
        kind = event["kind"]
        # Projection already reconciled individual trade legs and FIFO ordering.
        summary = next(row for row in projected["lineage"] if row["economic_event_ordinal"] == index)
        events.append((kind, summary["economic_quantity_units"]))
        if kind == "A":
            origins[event["diffs"][0]["oid"]] = len(origins)
        elif kind == "C":
            cancel_origins[index] = origins[event["diffs"][0]["oid"]]
    result = {"origin": origin, "episode_id": episode["episode_id"],
              "scope": "Q16-compatible integer FIFO model with declared cancellation policy",
              "count_definition": projected["count_definition"], "lineage": projected["lineage"],
              "economic_events": len(events), "probe_units": probe,
              "cohort_cancellation_selection": "none", "quantity_quantum": quantum}
    if not episode["horizon_complete"]:
        return {**result, "status": "censored", "reason": f"Incomplete {horizon}-economic-event horizon"}
    if len(events) != horizon:
        raise ValueError("Unexpected economic horizon")
    arguments = dict(ahead=sum(ahead), probe=probe, events=events,
                     probe_cancellable=episode["probe_cancellable"], timeout_ms=timeout_ms,
                     horizon=horizon)
    volume = SymbolicQueue(**arguments)
    count = SymbolicQueue(**arguments, counts=counts)
    witnesses = {"volume": volume.check_truth(ahead, cancel_origins),
                 "count": count.check_truth(ahead, cancel_origins)}
    if any(w["status"] not in {"contained", "unknown"} for w in witnesses.values()):
        return {**result, "status": "invalid_source_or_model",
                "reason": "True path contradicts the queue model or has an invalid solver status",
                "witnesses": witnesses}
    if any(w["status"] != "contained" for w in witnesses.values()):
        return {**result, "status": "unresolved", "reason": "True path containment not certified",
                "witnesses": witnesses}
    projections = {"volume": volume.project(enumerate_limit=0), "count": count.project(enumerate_limit=0)}
    if any(p["status"] not in {"exact", "unresolved"} for p in projections.values()):
        return {**result, "status": "invalid_source_or_model",
                "reason": "Source-model projection is infeasible or has an invalid solver status",
                "projections": projections}
    if any(p["status"] != "exact" for p in projections.values()):
        return {**result, "status": "unresolved", "projections": projections}
    narrow, wide = projections["count"], projections["volume"]
    if not (wide["minimum_fill_units"] <= narrow["minimum_fill_units"]
            <= narrow["maximum_fill_units"] <= wide["maximum_fill_units"]):
        raise ValueError("Count projection violates nesting")
    truth = witnesses["count"]["truth_states"][-1]
    result.update(status="scored", projections=projections,
                  truth_path_contained=True, observed_counts=counts,
                  observed_events=[{"kind": k, "quantity_units": q} for k, q in events],
                  truth={"filled_units": truth["filled"], "cancelled_units": truth["cancelled"],
                         "fill_fraction": str(Fraction(truth["filled"], probe))})
    return result
