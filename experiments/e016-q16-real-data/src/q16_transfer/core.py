"""Exact finite FIFO information ablation; no market-data assumptions here."""
from dataclasses import dataclass
from fractions import Fraction


class StateCapExceeded(RuntimeError):
    """The entire episode is unscored; a truncated set is never a bound."""


@dataclass(frozen=True, order=True)
class State:
    queue: tuple[tuple[int, bool], ...]
    filled: int = 0
    cancelled: int = 0


def compositions(total):
    if total == 0:
        yield ()
    else:
        for first in range(1, total + 1):
            for tail in compositions(total - first):
                yield (first,) + tail


def initial_states(ahead, probe, cap=100000):
    if type(ahead) is not int or ahead < 0 or type(probe) is not int or probe < 1:
        raise ValueError("Nonnegative ahead volume and positive integer probe required")
    # Count before allocating: the combinatorial dragon does not get a head start.
    if ahead > cap.bit_length() or (ahead and 2 ** (ahead - 1) > cap):
        raise StateCapExceeded(f"Initial volume {ahead} requires 2^(V-1) states; cap={cap}")
    return {State(tuple((q, False) for q in c) + ((probe, True),))
            for c in compositions(ahead)}


def transition(state, kind, quantity, probe_cancellable=True):
    if type(quantity) is not int or quantity <= 0 or kind not in {"A", "C", "T"}:
        raise ValueError("Atomic A/C/T event with positive integer quantity required")
    queue = state.queue
    if kind == "A":
        return {State(queue + ((quantity, False),), state.filled, state.cancelled)}
    if kind == "C":
        result = set()
        for i, (q, tagged) in enumerate(queue):
            if q < quantity or (tagged and not probe_cancellable):
                continue
            replacement = ((q - quantity, tagged),) if q > quantity else ()
            result.add(State(queue[:i] + replacement + queue[i + 1:], state.filled,
                             state.cancelled + (quantity if tagged else 0)))
        return result
    if quantity > sum(q for q, _ in queue):
        return set()
    remaining, filled, after = quantity, state.filled, []
    for q, tagged in queue:
        used = min(q, remaining)
        remaining -= used
        filled += used if tagged else 0
        if q > used:
            after.append((q - used, tagged))
    return {State(tuple(after), filled, state.cancelled)}


def advance(states, kind, quantity, cap=100000, probe_cancellable=True):
    result = set()
    for state in states:
        result.update(transition(state, kind, quantity, probe_cancellable))
        if len(result) > cap:
            raise StateCapExceeded(f"Transition state cap exceeded: {cap}")
    return result


def labels(states, probe):
    return {
        "any_fill": sorted({int(s.filled > 0) for s in states}),
        "full_fill": sorted({int(s.filled == probe) for s in states}),
        "fill_fraction": sorted({str(Fraction(s.filled, probe)) for s in states},
                                key=Fraction),
    }


def check_truth(truth, count, volume, probe):
    if truth not in count or not count <= volume:
        raise ValueError("Truth excluded or count/volume nesting violated")
    for state in volume:
        remainder = sum(q for q, tagged in state.queue if tagged)
        if state.filled + state.cancelled + remainder != probe:
            raise ValueError("Tagged quantity conservation violated")
