"""Exact Q16 outcome projection using bounded queue compression and integer SMT.

This represents all positive integer initial compositions, with no volume cap.
It does not assume fill values between the reported extrema are attainable.
Solver timeout/unknown is an unresolved episode, never an empirical score.

Requires z3-solver==4.16.0.0. The finite enumerator remains the source comparator.
"""
from dataclasses import dataclass
from fractions import Fraction
import time

import z3


@dataclass(frozen=True)
class Event:
    kind: str
    quantity: int


def _positive(value, name, zero=False):
    if type(value) is not int or value < (0 if zero else 1):
        raise ValueError(f"{name} must be an exact {'nonnegative' if zero else 'positive'} integer")


class SymbolicQueue:
    """A history's exact hypothesis set in the source integer-lattice model.

    At most C+T initial orders are special: every cancellation target and the
    last initial order touched by each trade, even if that order is fully used.
    Intervening groups are unchanged or consumed in full. A group's positive
    integer mass M and count N have a positive composition exactly when M>=N>0.
    Empty groups and unused special slots both have zero mass/count.

    Therefore every finite queue path has a compressed witness. Conversely,
    expanding any model's groups into positive compositions produces a valid
    queue path with identical fills and observed counts. This is an existential
    compression, not a sample or a relaxation of FIFO.
    """

    def __init__(self, ahead, probe, events, counts=None, probe_cancellable=True,
                 timeout_ms=2000, horizon=8):
        _positive(ahead, "ahead", zero=True)
        _positive(probe, "probe")
        _positive(timeout_ms, "timeout_ms")
        self.events = tuple(e if isinstance(e, Event) else Event(*e) for e in events)
        if horizon not in {8, 10} or len(self.events) > horizon:
            raise ValueError("History exceeds the declared eight- or ten-event horizon")
        for event in self.events:
            if event.kind not in {"A", "C", "T"}:
                raise ValueError("Atomic A/C/T kind required")
            _positive(event.quantity, "event quantity")
        if type(probe_cancellable) is not bool:
            raise ValueError("probe_cancellable must be a bool")
        if counts is not None:
            if len(counts) != len(self.events) + 1:
                raise ValueError("Counts must include the initial and every post-event count")
            for count in counts:
                _positive(count, "observed positive-size order count", zero=True)
        self.ahead, self.probe = ahead, probe
        self.counts = tuple(counts) if counts is not None else None
        self.timeout_ms = timeout_ms
        self.probe_cancellable = probe_cancellable
        self.special_count = sum(e.kind != "A" for e in self.events)
        self.group_indices = set(range(0, 2 * self.special_count + 1, 2))
        self.probe_index = 2 * self.special_count + 1
        self.add_slots = {}
        for index, event in enumerate(self.events):
            if event.kind == "A":
                self.add_slots[index] = self.probe_index + 1 + len(self.add_slots)
        self.width = self.probe_index + 1 + len(self.add_slots)
        self.q = [[z3.Int(f"q_{t}_{i}") for i in range(self.width)]
                  for t in range(len(self.events) + 1)]
        self.n = {i: z3.Int(f"n_{i}") for i in self.group_indices}
        self.filled = [z3.Int(f"filled_{t}") for t in range(len(self.q))]
        self.cancelled = [z3.Int(f"cancelled_{t}") for t in range(len(self.q))]
        self.cancel_target = {}
        self.constraints = []
        add = self.constraints.append
        for row in self.q:
            self.constraints.extend(q >= 0 for q in row)
        add(z3.Sum(self.q[0][:self.probe_index]) == ahead)
        add(self.q[0][self.probe_index] == probe)
        for i in range(self.probe_index + 1, self.width):
            add(self.q[0][i] == 0)
        for i, number in self.n.items():
            add(number >= 0)
            add(number <= self.q[0][i])
            add((number == 0) == (self.q[0][i] == 0))
        for j in range(self.special_count):
            absent = self.q[0][2 * j + 1] == 0
            add(z3.Implies(absent, self.q[0][2 * j + 2] == 0))
            if j + 1 < self.special_count:
                add(z3.Implies(absent, self.q[0][2 * j + 3] == 0))
        add(self.filled[0] == 0)
        add(self.cancelled[0] == 0)
        for t, event in enumerate(self.events):
            before, after = self.q[t], self.q[t + 1]
            quantity = event.quantity
            if event.kind == "A":
                slot = self.add_slots[t]
                for i in range(self.width):
                    add(after[i] == (quantity if i == slot else before[i]))
                add(self.filled[t + 1] == self.filled[t])
                add(self.cancelled[t + 1] == self.cancelled[t])
            elif event.kind == "C":
                target = z3.Int(f"cancel_target_{t}")
                self.cancel_target[t] = target
                candidates = [i for i in range(self.width)
                              if i not in self.group_indices
                              and (probe_cancellable or i != self.probe_index)]
                add(z3.Or([z3.And(target == i, before[i] >= quantity)
                           for i in candidates]))
                for i in range(self.width):
                    add(after[i] == before[i] - z3.If(target == i, quantity, 0))
                add(self.filled[t + 1] == self.filled[t])
                add(self.cancelled[t + 1] == self.cancelled[t]
                    + z3.If(target == self.probe_index, quantity, 0))
            else:
                add(z3.Sum(before) >= quantity)
                used = []
                for i in range(self.width):
                    prefix = z3.Sum(before[:i]) if i else z3.IntVal(0)
                    take = z3.If(prefix >= quantity, 0,
                                 z3.If(prefix + before[i] <= quantity,
                                       before[i], quantity - prefix))
                    used.append(take)
                    add(after[i] == before[i] - take)
                    if i in self.group_indices:
                        # A boundary order gets its own seat; groups travel whole.
                        add(z3.Or(after[i] == 0, after[i] == before[i]))
                add(self.filled[t + 1] == self.filled[t] + used[self.probe_index])
                add(self.cancelled[t + 1] == self.cancelled[t])
        for t in range(len(self.q)):
            add(self.filled[t] >= 0)
            add(self.cancelled[t] >= 0)
            add(self.filled[t] + self.cancelled[t]
                + self.q[t][self.probe_index] == probe)
            if counts is not None:
                order_count = z3.Sum([
                    z3.If(self.q[t][i] > 0, self.n[i] if i in self.n else 1, 0)
                    for i in range(self.width)])
                add(order_count == counts[t])
        total_trade = sum(e.quantity for e in self.events if e.kind == "T")
        total_cancel = sum(e.quantity for e in self.events if e.kind == "C")
        self.analytic_minimum = max(0, min(total_trade - ahead, probe - total_cancel))
        self.analytic_maximum = min(probe, max(0, total_trade - ahead + total_cancel))
        add(self.filled[-1] >= self.analytic_minimum)
        add(self.filled[-1] <= self.analytic_maximum)

    def _solver(self):
        solver = z3.Solver()
        solver.set(timeout=self.timeout_ms, random_seed=20260919, threads=1)
        solver.add(self.constraints)
        return solver

    def feasible_fill(self, value):
        """Exact membership: True, False, or None if the solver is unresolved."""
        _positive(value, "fill", zero=True)
        solver = self._solver()
        solver.add(self.filled[-1] == value)
        result = solver.check()
        return True if result == z3.sat else False if result == z3.unsat else None

    def _extreme(self, maximize):
        endpoint = self.analytic_maximum if maximize else self.analytic_minimum
        solver = self._solver()
        solver.add(self.filled[-1] == endpoint)
        if solver.check() == z3.sat:
            return endpoint, "sat", None
        optimizer = z3.Optimize()
        optimizer.set(timeout=self.timeout_ms)
        optimizer.add(self.constraints)
        objective = (optimizer.maximize if maximize else optimizer.minimize)(self.filled[-1])
        result = optimizer.check()
        if result != z3.sat:
            return None, str(result), optimizer.reason_unknown() if result == z3.unknown else None
        lower, upper = objective.lower(), objective.upper()
        if not z3.is_int_value(lower) or not z3.is_int_value(upper) or lower.as_long() != upper.as_long():
            return None, "unknown", "Optimizer did not certify a finite exact optimum"
        return lower.as_long(), "sat", None

    def _terminal_depletion_values(self):
        """Exact fill set for C* followed by a trade that empties the level.

        Volume-only worlds assign a subset of whole C events to the probe.
        Other cancellations can each consume a separate initial ahead order.
        If every C removes exactly one visible order, the probe is either
        untouched or deleted by one C whose quantity equals its original size.
        None means the shortcut does not apply; an empty list is infeasible.
        """
        if (not self.probe_cancellable or not self.events or self.events[-1].kind != "T"
                or any(event.kind != "C" for event in self.events[:-1])):
            return None
        cancellations = [event.quantity for event in self.events[:-1]]
        total_cancel = sum(cancellations)
        if self.events[-1].quantity != self.ahead + self.probe - total_cancel:
            return None
        if self.counts is None:
            sums = {0}
            for quantity in cancellations:
                sums |= {value + quantity for value in sums}
            return sorted({self.probe - value for value in sums
                           if value <= self.probe and total_cancel - value <= self.ahead})
        if (self.counts[-1] != 0 or any(self.counts[i + 1] != self.counts[i] - 1
                                       for i in range(len(cancellations)))):
            return None
        values = []
        for probe_deleted in (False, True):
            if probe_deleted and self.probe not in cancellations:
                continue
            mass = self.ahead - total_cancel + (self.probe if probe_deleted else 0)
            number = self.counts[0] - 1 - len(cancellations) + int(probe_deleted)
            if (mass == number == 0) or (number > 0 and mass >= number):
                values.append(0 if probe_deleted else self.probe)
        return sorted(values)

    def project(self, enumerate_limit=0):
        """Return exact extrema/ambiguity, with a finite fill set only if bounded.

        enumerate_limit bounds additional membership queries, never queue states.
        None for fill_values means unenumerated, not that every interior value is
        feasible. The exact extrema suffice for the source ambiguity estimand.
        """
        _positive(enumerate_limit, "enumerate_limit", zero=True)
        started = time.monotonic()
        result = {
            "backend": "exact_integer_smt_group_compression_v1",
            "z3_version": z3.get_version_string(),
            "probe_units": self.probe,
            "special_initial_slots": self.special_count,
            "aggregate_initial_groups": len(self.group_indices),
            "timeout_ms_per_query": self.timeout_ms,
            "fill_values": None,
            "interior_values_assumed_feasible": False,
        }
        terminal_values = self._terminal_depletion_values()
        if terminal_values is not None:
            result.update(backend="exact_terminal_depletion_v1",
                          resolution_method="cancellation_subsets" if self.counts is None
                          else "single_order_deletions_and_residual_composition",
                          fill_values=terminal_values)
            if not terminal_values:
                result.update(status="infeasible", reason="No terminal-depletion history matches observations")
            else:
                low, high = terminal_values[0], terminal_values[-1]
                result.update(status="exact", minimum_fill_units=low, maximum_fill_units=high,
                              fill_fraction_bounds=[str(Fraction(low, self.probe)), str(Fraction(high, self.probe))],
                              fill_fraction=[str(Fraction(value, self.probe)) for value in terminal_values],
                              fill_ambiguous=low != high,
                              any_fill=sorted({int(value > 0) for value in terminal_values}),
                              full_fill=sorted({int(value == self.probe) for value in terminal_values}))
            result["elapsed_seconds"] = time.monotonic() - started
            return result
        low, status, reason = self._extreme(False)
        if status == "unsat":
            result.update(status="infeasible", reason="No source-model history matches observations")
        elif status != "sat":
            result.update(status="unresolved", reason=reason)
        else:
            high, status, reason = self._extreme(True)
            if status == "unsat":
                result.update(status="infeasible", reason="Contradictory feasible-minimum/infeasible-maximum queries")
            elif status != "sat":
                result.update(status="unresolved", reason=reason or "Inconsistent extrema query")
            else:
                result.update(
                    status="exact",
                    minimum_fill_units=low,
                    maximum_fill_units=high,
                    fill_fraction_bounds=[str(Fraction(low, self.probe)),
                                          str(Fraction(high, self.probe))],
                    fill_ambiguous=low != high,
                    any_fill=([0] if low == 0 else []) + ([1] if high > 0 else []),
                    full_fill=([0] if low < self.probe else []) + ([1] if high == self.probe else []),
                )
                if high - low + 1 <= enumerate_limit:
                    values = []
                    for value in range(low, high + 1):
                        feasible = self.feasible_fill(value)
                        if feasible is None:
                            result["fill_set_reason"] = "Membership timeout; extrema remain exact"
                            break
                        if feasible:
                            values.append(value)
                    else:
                        result["fill_values"] = values
                        result["fill_fraction"] = [str(Fraction(value, self.probe)) for value in values]
        result["elapsed_seconds"] = time.monotonic() - started
        return result

    def check_truth(self, initial_ahead, cancel_origins):
        """Check a fully identified concrete path as an explicit SMT witness.

        Initial ahead origins are 0..N-1; the probe is N; additions in event
        order receive N+1, N+2, ... . cancel_origins maps each C event index to
        its actual target origin. No origin/identity is supplied to inference.
        Every step's FIFO queue, fills, cancellations and counts is bound in this
        extra witness query. Returned truth states use the finite core's shape.
        """
        for value in initial_ahead:
            _positive(value, "initial ahead order")
        if sum(initial_ahead) != self.ahead:
            raise ValueError("Truth ahead volume differs from the observed volume")
        if set(cancel_origins) != set(self.cancel_target):
            raise ValueError("One concrete origin is required for each cancellation")
        probe_origin = len(initial_ahead)
        quantities = {i: value for i, value in enumerate(initial_ahead)}
        quantities[probe_origin] = self.probe
        order = list(quantities)
        added_origins = {}
        special = set()
        filled, cancelled = 0, 0
        traces = [(dict(quantities), filled, cancelled)]
        for t, event in enumerate(self.events):
            if event.kind == "A":
                origin = probe_origin + 1 + len(added_origins)
                added_origins[t] = origin
                order.append(origin)
                quantities[origin] = event.quantity
            elif event.kind == "C":
                origin = cancel_origins[t]
                if quantities.get(origin, 0) < event.quantity:
                    raise ValueError("Invalid truth cancellation target/quantity")
                if origin == probe_origin and not self.probe_cancellable:
                    raise ValueError("Truth cancels a protected source probe")
                if origin < probe_origin:
                    special.add(origin)
                quantities[origin] -= event.quantity
                cancelled += event.quantity if origin == probe_origin else 0
            else:
                remaining = event.quantity
                last_initial = None
                for origin in order:
                    used = min(remaining, quantities[origin])
                    if used and origin < probe_origin:
                        last_initial = origin
                    quantities[origin] -= used
                    remaining -= used
                    filled += used if origin == probe_origin else 0
                if remaining:
                    raise ValueError("Truth trade exceeds positive volume")
                if last_initial is not None:
                    special.add(last_initial)
            traces.append((dict(quantities), filled, cancelled))
        if len(special) > self.special_count:
            raise AssertionError("Boundary representation proof violated")
        mapping = {}
        selected = sorted(special)
        cursor = 0
        for origin in range(probe_origin):
            if cursor < len(selected) and selected[cursor] == origin:
                mapping[origin] = 2 * cursor + 1
                cursor += 1
            else:
                mapping[origin] = 2 * cursor
        mapping[probe_origin] = self.probe_index
        for t, origin in added_origins.items():
            mapping[origin] = self.add_slots[t]
        solver = self._solver()
        for i, variable in self.n.items():
            solver.add(variable == sum(slot == i for slot in mapping.values()))
        truth_states = []
        for t, (quantities, filled, cancelled) in enumerate(traces):
            for i in range(self.width):
                solver.add(self.q[t][i] == sum(q for origin, q in quantities.items()
                                               if mapping[origin] == i))
            solver.add(self.filled[t] == filled, self.cancelled[t] == cancelled)
            truth_states.append({"queue": [(q, origin == probe_origin)
                                           for origin, q in quantities.items() if q > 0],
                                 "filled": filled, "cancelled": cancelled})
        for t, origin in cancel_origins.items():
            solver.add(self.cancel_target[t] == mapping[origin])
        result = solver.check()
        return {"status": "contained" if result == z3.sat else str(result),
                "reason": solver.reason_unknown() if result == z3.unknown else None,
                "distinguished_initial_origins": len(special),
                "truth_states": truth_states}
