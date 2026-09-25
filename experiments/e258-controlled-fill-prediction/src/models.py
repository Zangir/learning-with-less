"""Frozen E258 estimators; this module performs no fits at import time.

Training rows contain ``features={C,Z,K,Q,side}``, ``H`` and ``Y``. The caller
supplies rows in their frozen training order; only the first ``n`` are used.
``fit_log(record)`` is called BEFORE each of six learned invocations, so an
interrupted or failed fit still consumes an invocation. Both C optimizations
belong to the single distribution-Y invocation. Completed diagnostics are also
retained in the returned JSON-serializable bundle.

Point-Y selection maximizes exact rational Beta-augmented likelihood, equivalent
to minimizing the specified NLL; exact ties choose the lowest H. Distribution-Y
uses an exact rational inverse of the independent Beta estimates when feasible.
Otherwise its convex optimum lies on one of three edges; each edge uses endpoint
derivative tests or 80 deterministic derivative bisections. All candidates,
brackets and objectives are retained. Nonfinite/infeasible output is fatal.
Canonical decoded tables are shared by each algebraic identity pair so machine
roundoff cannot create a spurious decision difference at a strict threshold.
No prediction API accepts an evaluation condition. Source condition is recorded
as provenance only. Probabilities are never clipped here; evaluation alone clips
them for logarithmic scores according to the frozen protocol.
"""

from datetime import datetime, timezone
from fractions import Fraction
import math
import time

import numpy as np


SURVIVAL_UNITS = ((90, 25, 20), (90, 85, 20))
SURVIVAL = np.asarray(SURVIVAL_UNITS, dtype=float) / 100
FIT_NAMES = (
    "unconditional_y", "direct_y", "point_y", "distribution_y",
    "current_rich_y", "queue_auxiliary_h",
)
MODEL_NAMES = (
    "unconditional_y", "direct_y", "point_y", "distribution_y",
    "direct_compiled_y", "current_rich_y", "distribution_h", "point_mean_h",
    "direct_soft_h", "known_mean_point",
)
RECONSTRUCTION_NAMES = (
    "point_y", "distribution_y", "distribution_h", "point_mean_h",
    "known_mean_point",
)


def _bit(value, name):
    if type(value) is not int or value not in (0, 1):
        raise ValueError(f"{name} must be an integer bit")
    return value


def _rank(value):
    if type(value) is not int or value not in (0, 1, 2):
        raise ValueError("H must be an integer in {0,1,2}")
    return value


def _counts(rows, coordinates, shape):
    successes = np.zeros(shape, dtype=int)
    totals = np.zeros(shape, dtype=int)
    for row in rows:
        index = tuple(row["features"][key] if key in ("C", "Z") else row[key]
                      for key in coordinates)
        successes[index] += row["Y"]
        totals[index] += 1
    return successes, totals


def _beta_table(rows, coordinates, shape):
    successes, totals = _counts(rows, coordinates, shape)
    return ((successes + 1) / (totals + 2)).tolist()


def _point_y(rows):
    successes, totals = _counts(rows, ("C", "Z"), (2, 2))
    selected, diagnostics = [], []
    for c in (0, 1):
        likelihoods, nll = [], []
        for h in (0, 1, 2):
            likelihood, objective = Fraction(1), 0.0
            for z in (0, 1):
                probability = Fraction(SURVIVAL_UNITS[z][h], 100)
                success = int(successes[c, z]) + 1
                failure = int(totals[c, z] - successes[c, z]) + 1
                likelihood *= probability ** success * (1 - probability) ** failure
                objective -= success * math.log(float(probability))
                objective -= failure * math.log1p(-float(probability))
            likelihoods.append(likelihood)
            nll.append(objective)
        # Ties get a queue rank, not a floating-point coin toss.
        best = max(range(3), key=lambda h: likelihoods[h])
        selected.append(best)
        diagnostics.append(dict(C=c, selected_h=best, nll_by_h=nll,
                                tied_optima=sum(x == likelihoods[best] for x in likelihoods)))
    return dict(h_by_c=selected, diagnostics=diagnostics)


def _distribution_y(rows):
    successes, totals = _counts(rows, ("C", "Z"), (2, 2))
    posterior, decoded, diagnostics = [], [], []
    for c in (0, 1):
        success = successes[c].astype(float) + 1
        failure = (totals[c] - successes[c]).astype(float) + 1

        def objective(probability):
            probability = np.asarray(probability, dtype=float)
            return float(-np.sum(success * np.log(probability)
                                 + failure * np.log1p(-probability)))

        independent = [Fraction(int(successes[c, z]) + 1, int(totals[c, z]) + 2)
                       for z in (0, 1)]
        q1 = (independent[1] - independent[0]) / Fraction(3, 5)
        q0 = (independent[0] - Fraction(1, 5) - q1 / 20) / Fraction(7, 10)
        inverse = [q0, q1, 1 - q0 - q1]
        feasible = all(q >= 0 for q in inverse)
        candidates = []
        for h in (0, 1, 2):
            q = [float(index == h) for index in (0, 1, 2)]
            probability = SURVIVAL[:, h].tolist()
            candidates.append(dict(kind="vertex", vertex=h, q=q, probabilities=probability,
                                   objective=objective(probability)))
        for first, second in ((0, 1), (0, 2), (1, 2)):
            origin = SURVIVAL[:, first]
            direction = SURVIVAL[:, second] - origin

            def derivative(t):
                probability = origin + t * direction
                return float(np.sum((failure / (1 - probability) - success / probability)
                                    * direction))

            d0, d1 = derivative(0.0), derivative(1.0)
            left, right, iterations = 0.0, 1.0, 0
            if d0 >= 0:
                left = right = 0.0
            elif d1 <= 0:
                left = right = 1.0
            else:
                for _ in range(80):
                    midpoint = (left + right) / 2
                    slope = derivative(midpoint)
                    if slope > 0:
                        right = midpoint
                    elif slope < 0:
                        left = midpoint
                    else:
                        left = right = midpoint
                    iterations += 1
            t = (left + right) / 2
            q = [0.0, 0.0, 0.0]
            q[first], q[second] = 1 - t, t
            probability = (origin + t * direction).tolist()
            candidates.append(dict(kind="edge", vertices=[first, second], t=t, q=q,
                                   probabilities=probability, objective=objective(probability),
                                   endpoint_derivatives=[d0, d1], bracket=[left, right],
                                   bracket_derivatives=[derivative(left), derivative(right)],
                                   bisection_iterations=iterations))
        if feasible:
            selected = dict(kind="independent_beta_feasible", q=[float(q) for q in inverse],
                            q_exact=[str(q) for q in inverse],
                            probabilities=[float(p) for p in independent],
                            objective=objective([float(p) for p in independent]))
            candidates.append(selected)
        else:
            selected = min(candidates, key=lambda candidate: candidate["objective"])
        q, probability = selected["q"], selected["probabilities"]
        if (not all(math.isfinite(value) for value in q + probability)
                or min(q) < 0 or max(q) > 1 or abs(sum(q) - 1) > 1e-12):
            raise RuntimeError(f"Distribution-Y returned invalid values: {selected}")
        posterior.append(q)
        decoded.append(probability)
        diagnostics.append(dict(C=c, independent_beta=[str(p) for p in independent],
                                inverse_q_exact=[str(q) for q in inverse],
                                independent_beta_feasible=feasible,
                                selected_kind=selected["kind"], selected_objective=selected["objective"],
                                candidates=candidates))
    return dict(q_by_c=posterior, decoded_by_cz=decoded, diagnostics=diagnostics)


def _queue_auxiliary(rows):
    counts = [[0, 0, 0], [0, 0, 0]]
    for row in rows:
        counts[row["features"]["C"]][row["H"]] += 1
    posterior, point, direct_soft = [], [], []
    for c in (0, 1):
        numerators = [2 * count + 1 for count in counts[c]]
        denominator = sum(numerators)
        posterior.append([value / denominator for value in numerators])
        mean_numerator = numerators[1] + 2 * numerators[2]
        point.append(0 if 2 * mean_numerator <= denominator else
                     1 if 2 * mean_numerator <= 3 * denominator else 2)
        # Every C-matched rich row supplies both Z queries to the direct control.
        direct_soft.append([
            sum(numerators[h] * SURVIVAL_UNITS[z][h] for h in (0, 1, 2))
            / (100 * denominator) for z in (0, 1)
        ])
    return dict(counts_by_c=counts, q_by_c=posterior, rounded_mean_h_by_c=point,
                direct_soft_by_cz=direct_soft)


def fit_models(rows, n, condition, fit_log):
    """Fit six frozen estimators; ``condition`` is source provenance, never a feature."""
    if type(n) is not int or n <= 0 or len(rows) < n:
        raise ValueError("Training size must be positive and available in the frozen pool")
    training = list(rows[:n])
    for row in training:
        _bit(row["features"]["C"], "C")
        _bit(row["features"]["Z"], "Z")
        _bit(row["Y"], "Y")
        _rank(row["H"])
    bundle = dict(source_condition=condition, n=n, fit_records=[])

    def invoke(name, operation):
        record = dict(model=name, source_condition=condition, n=n, status="started",
                      started_at_utc=datetime.now(timezone.utc).isoformat())
        fit_log(dict(record))
        started = time.perf_counter()
        try:
            value = operation()
        except Exception as error:
            record.update(status="failed", runtime_seconds=time.perf_counter() - started,
                          error=f"{type(error).__name__}: {error}")
            raise RuntimeError(f"Learned invocation failed; attempt already logged: {record}") from error
        record.update(status="completed", runtime_seconds=time.perf_counter() - started)
        bundle["fit_records"].append(record)
        return value

    bundle["unconditional_y"] = invoke(
        "unconditional_y", lambda: (sum(row["Y"] for row in training) + 1) / (n + 2))
    bundle["direct_y"] = invoke(
        "direct_y", lambda: _beta_table(training, ("C", "Z"), (2, 2)))
    bundle["point_y"] = invoke("point_y", lambda: _point_y(training))
    bundle["distribution_y"] = invoke("distribution_y", lambda: _distribution_y(training))
    bundle["current_rich_y"] = invoke(
        "current_rich_y", lambda: _beta_table(training, ("H", "Z"), (3, 2)))
    bundle["queue_auxiliary_h"] = invoke("queue_auxiliary_h", lambda: _queue_auxiliary(training))
    bundle["direct_compiled_y"] = [list(p) for p in bundle["distribution_y"]["decoded_by_cz"]]
    return bundle


def predict_models(bundle, features, current_h):
    """Return all fill-probability readouts; only current-rich uses ``current_h``."""
    c, z = _bit(features["C"], "C"), _bit(features["Z"], "Z")
    current_h = _rank(current_h)
    auxiliary = bundle["queue_auxiliary_h"]
    return {
        "unconditional_y": float(bundle["unconditional_y"]),
        "direct_y": float(bundle["direct_y"][c][z]),
        "point_y": float(SURVIVAL[z, bundle["point_y"]["h_by_c"][c]]),
        "distribution_y": float(bundle["distribution_y"]["decoded_by_cz"][c][z]),
        "direct_compiled_y": float(bundle["direct_compiled_y"][c][z]),
        "current_rich_y": float(bundle["current_rich_y"][current_h][z]),
        "distribution_h": float(auxiliary["direct_soft_by_cz"][c][z]),
        "point_mean_h": float(SURVIVAL[z, auxiliary["rounded_mean_h_by_c"][c]]),
        "direct_soft_h": float(auxiliary["direct_soft_by_cz"][c][z]),
        "known_mean_point": float(SURVIVAL[z, 1]),
    }


def reconstruction_predictions(bundle, features):
    """Return defined H distributions and their mean ranks; no outcome argument."""
    c = _bit(features["C"], "C")
    auxiliary = bundle["queue_auxiliary_h"]

    def point(h):
        return [float(index == h) for index in (0, 1, 2)]

    distributions = {
        "point_y": point(bundle["point_y"]["h_by_c"][c]),
        "distribution_y": list(bundle["distribution_y"]["q_by_c"][c]),
        "distribution_h": list(auxiliary["q_by_c"][c]),
        "point_mean_h": point(auxiliary["rounded_mean_h_by_c"][c]),
        "known_mean_point": point(1),
    }
    return {name: dict(probabilities=q, mean_rank=q[1] + 2 * q[2])
            for name, q in distributions.items()}
