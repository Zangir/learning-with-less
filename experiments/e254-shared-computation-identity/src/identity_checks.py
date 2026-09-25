"""Exact software checks for E-254; no fitting, stochastic pilot or benchmark."""
from dataclasses import asdict, dataclass
from fractions import Fraction as F
from itertools import product
from pathlib import Path
import csv
import hashlib
import json
import os
import resource
import time

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Fixture:
    name: str
    depth: int
    steps: int
    initial_ahead: tuple
    trades: int


FIXTURES = (
    Fixture("primary", 4, 4, (1, 2), 3),
    Fixture("forced_trades", 3, 3, (0,), 3),
    Fixture("single_path", 2, 2, (1,), 2),
    Fixture("all_cancellations", 3, 3, (1,), 0),
    Fixture("empty_support", 2, 2, (0, 1), 3),
)


def enumerate_histories(fixture):
    """Independent brute-force oracle; deliberately does not call transitions."""
    histories = []
    for initial in fixture.initial_ahead:
        for labels in product(("T", "Ca", "Cb"), repeat=fixture.steps):
            if labels.count("T") != fixture.trades:
                continue
            ahead, behind, service = initial, fixture.depth - initial, [0]
            states = [(ahead, behind, 0)]
            trades, legal = 0, True
            for label in labels:
                increment = 0
                if label == "Ca" and ahead:
                    ahead -= 1
                elif label == "Cb" and behind:
                    behind -= 1
                elif label == "T" and ahead + behind:
                    trades += 1
                    if ahead:
                        ahead -= 1
                    else:
                        behind -= 1
                        increment = 1
                else:
                    legal = False
                    break
                service.append(service[-1] + increment)
                states.append((ahead, behind, trades))
            if legal:
                histories.append({"initial_ahead": initial, "events": labels,
                                  "service": service, "states": states})
    return histories


def transitions(state):
    ahead, behind, trades = state
    if ahead + behind:
        yield "T", (max(0, ahead - 1), behind - (ahead == 0), trades + 1), int(ahead == 0)
    if ahead:
        yield "Ca", (ahead - 1, behind, trades), 0
    if behind:
        yield "Cb", (ahead, behind - 1, trades), 0


def compile_envelopes(fixture):
    """Shared direct/restoration compiler: sufficient-state DAG and min/max plus."""
    layers = [{(a, fixture.depth - a, 0) for a in fixture.initial_ahead}]
    edges = []
    for _ in range(fixture.steps):
        current_edges = [(state, target, label, weight)
                         for state in sorted(layers[-1])
                         for label, target, weight in transitions(state)]
        edges.append(current_edges)
        layers.append({edge[1] for edge in current_edges})
    viable = [set() for _ in layers]
    viable[-1] = {state for state in layers[-1] if state[2] == fixture.trades}
    for t in reversed(range(fixture.steps)):
        viable[t] = {source for source, target, _, _ in edges[t] if target in viable[t + 1]}
    if not viable[0]:
        return None
    lows = [{state: 0 for state in layers[0]}]
    highs = [{state: 0 for state in layers[0]}]
    for t, current_edges in enumerate(edges):
        lower, upper = {}, {}
        for source, target, _, weight in current_edges:
            low = lows[t][source] + weight
            high = highs[t][source] + weight
            lower[target] = min(lower.get(target, low), low)
            upper[target] = max(upper.get(target, high), high)
        lows.append(lower)
        highs.append(upper)
    return {
        "lower": [min(lows[t][state] for state in viable[t]) for t in range(len(layers))],
        "upper": [max(highs[t][state] for state in viable[t]) for t in range(len(layers))],
        "unpruned_lower": [min(layer.values()) for layer in lows],
        "nodes": sum(map(len, layers)), "edges": sum(map(len, edges)),
        "viable_nodes": sum(map(len, viable)),
    }


def loss(service, size, kind):
    shortfall = F(size - min(size, service), size)
    if kind == "linear":
        return shortfall
    if kind == "square":
        return shortfall ** 2
    return F(shortfall > 0)


def action(post_loss, cross_loss):
    # Exact ties cross; floating-point diplomacy is unnecessary here.
    return "post" if post_loss < cross_loss else "cross"


def write_json(name, data):
    (ROOT / name).write_text(json.dumps(data, indent=2) + "\n")


def main():
    start = time.perf_counter()
    assert os.sched_getaffinity(0) == {8, 9}
    assert resource.getrlimit(resource.RLIMIT_AS)[0] == 8 * 1024**3
    write_json("fixture-specifications.json", [asdict(f) for f in FIXTURES])
    checks, queries = [], []
    for fixture in FIXTURES:
        histories = enumerate_histories(fixture)
        compiled = compile_envelopes(fixture)
        if not histories:
            assert compiled is None
            checks.append({"fixture": fixture.name, "empty_support_rejected": True})
            continue
        lower = [min(h["service"][t] for h in histories) for t in range(fixture.steps + 1)]
        upper = [max(h["service"][t] for h in histories) for t in range(fixture.steps + 1)]
        assert compiled["lower"] == lower and compiled["upper"] == upper
        if fixture.name == "forced_trades":
            assert compiled["unpruned_lower"] != lower
        checks.append({"fixture": fixture.name, "histories": len(histories), **compiled})
        if fixture.name != "primary":
            continue
        write_json("primary_histories.json", histories)
        for t, size, kind, cross in product(range(5), (1, 2, 3),
                                           ("linear", "square", "miss"), (F(1, 4), F(1, 2), F(3, 4))):
            oracle = max(loss(h["service"][t], size, kind) for h in histories)
            bound = loss(lower[t], size, kind)
            assert oracle == bound
            assert action(oracle, cross) == action(bound, cross)
            assert all(loss(h["service"][t], size, kind) <= bound for h in histories)
            queries.append({"horizon": t, "size": size, "loss": kind,
                            "cross_cost": str(cross), "enumerated_worst_loss": str(oracle),
                            "compiled_bound": str(bound), "action": action(bound, cross),
                            "tie": oracle == cross})
        with (ROOT / "primary_envelopes.csv").open("w", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(("horizon", "minimum_service", "maximum_service"))
            writer.writerows(zip(range(5), lower, upper))
        with (ROOT / "synthetic_examples.csv").open("w", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(("history_index", "initial_ahead_units", "event_labels", "service_units_t0_to_t4"))
            for i, h in enumerate(histories[:3]):
                writer.writerow((i, h["initial_ahead"], " ".join(h["events"]), " ".join(map(str, h["service"]))))
    assert len(queries) == 135
    assert any(row["tie"] for row in queries)
    with (ROOT / "primary_queries.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(queries[0]))
        writer.writeheader()
        writer.writerows(queries)
    signatures = ((0, 2), (1, 1))
    coordinate_minima = tuple(map(min, zip(*signatures)))
    joint_worst = max(sum(2 - s for s in signature) for signature in signatures)
    compressed_joint = sum(2 - s for s in coordinate_minima)
    assert coordinate_minima not in signatures
    assert (joint_worst, compressed_joint) == (2, 3)
    cross = F(1, 2)
    # Same lower service, different crossing regret: an objective boundary.
    crossing_regret = [max(cross - min(cross, loss(s, 2, "linear")) for s in support)
                       for support in ((0,), (0, 2))]
    assert crossing_regret == [F(0), F(1, 2)]
    support, weights = (0, 2), (F(1, 2), F(1, 2))
    expected_losses = (sum(w * loss(s, 2, "linear") for s, w in zip(support, weights)), cross)
    distribution_oracle = min(expected_losses)
    hindsight_oracle = sum(w * min(loss(s, 2, "linear"), cross) for s, w in zip(support, weights))
    assert distribution_oracle == F(1, 2) and hindsight_oracle == F(1, 4)
    write_json("boundary-checks.json", {
        "joint_signature_fixture": signatures, "coordinate_minima": coordinate_minima,
        "actual_joint_worst_loss": joint_worst, "coordinate_bound_joint_loss": compressed_joint,
        "crossing_regret_same_lower_service": list(map(str, crossing_regret)),
        "distribution_specific_best_expected_loss": str(distribution_oracle),
        "expected_hindsight_best_loss": str(hindsight_oracle),
        "scope": "Exact constructed algebraic fixtures; not empirical or queue-history claims."})
    write_json("exact-checks.json", {"fixtures": checks, "primary_queries_checked": len(queries),
               "exact_ties_checked": sum(row["tie"] for row in queries),
               "all_checks_passed": True, "fitted_experiment": False, "benchmark": False,
               "seed": None, "stochastic_process": False})
    write_json("check_metadata.json", {"runtime_seconds": time.perf_counter() - start,
               "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
               "cpu_affinity": sorted(os.sched_getaffinity(0)),
               "address_space_limit_bytes": resource.getrlimit(resource.RLIMIT_AS)[0],
               "code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
               "contract_sha256": hashlib.sha256((ROOT / "candidate-spec.md").read_bytes()).hexdigest(),
               "runtime_interpretation": "Reproducibility only; no comparative timing or speed claim."})
    print(json.dumps({"fixtures": len(checks), "queries": len(queries), "passed": True}), flush=True)


if __name__ == "__main__":
    main()
