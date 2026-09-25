"""Pure finite-law references for E258; importing this module runs no study."""

from fractions import Fraction as F
from itertools import product
from math import ceil, log


CONDITIONS = ("zero", "informative", "shift")
DECISION_THRESHOLDS = (F(1, 5), F(2, 5), F(11, 20), F(7, 10), F(17, 20))
_FLOW = ((F(1, 10), F(13, 20), F(1, 20), F(1, 5)),
         (F(1, 10), F(1, 20), F(13, 20), F(1, 5)))


def _fraction(value):
    return value if isinstance(value, F) else F(str(value))


def _law(condition, c):
    if condition not in CONDITIONS or c not in (0, 1):
        raise ValueError("Expected a declared condition and binary cue.")
    e = F(1, 4) if condition == "zero" else (F(1, 10), F(2, 5))[
        c if condition == "informative" else 1 - c]
    return e, 1 - 2 * e, e


def _survival(h, z):
    if h not in (0, 1, 2) or z not in (0, 1):
        raise ValueError("Expected H in {0,1,2} and binary flow context.")
    return sum(_FLOW[z][h + 1:], F(0))


def _bayes(c, z, condition):
    return sum((p * _survival(h, z) for h, p in enumerate(_law(condition, c))), F(0))


def law_probs(condition, c):
    """P(H=0,1,2 | C=c), as floats; Z and nuisance variables do not enter."""
    return tuple(map(float, _law(condition, c)))


def flow_probs(z):
    """P(J=0,1,2,3 | Z=z), in ascending future-volume order."""
    if z not in (0, 1):
        raise ValueError("Expected binary flow context.")
    return tuple(map(float, _FLOW[z]))


def survival(h, z):
    """Current-rich full-fill probability; does not observe realized J."""
    return float(_survival(h, z))


def bayes(c, z, condition):
    """Exact coarse conditional probability, conditional on the declared law."""
    return float(_bayes(c, z, condition))


def future_volume(k, q, j):
    return (q - 1, q, q + k, q + 2 * k)[j]


def fill_quantity(k, q, h, j):
    return min(q, max(0, future_volume(k, q, j) - k * h))


def full_fill(h, j):
    """For the frozen support, V >= K*H+Q iff J >= H+1."""
    return int(j >= h + 1)


def enumerate_support(condition):
    """Return 384 analytical worlds; no native runs, file writes or sampling.

    Integer numerator/denominator preserve exact masses alongside JSON-ready
    float weights. These are prospective law states, never captured market rows.
    """
    rows = []
    for c, z, k, q, side, h, j in product(
            (0, 1), (0, 1), (2, 4), (2, 3), ("bid", "ask"), range(3), range(4)):
        mass = _law(condition, c)[h] * _FLOW[z][j] / 32
        rows.append(dict(c=c, z=z, k=k, q=q, side=side, h=h, j=j,
                         queue_ahead=k * h, volume=future_volume(k, q, j),
                         filled=fill_quantity(k, q, h, j), y=full_fill(h, j),
                         probability=float(mass), mass_numerator=mass.numerator,
                         mass_denominator=mass.denominator))
    return rows


def project_posterior(posterior, z):
    """Use the same known future-flow decoder for all posterior-based arms."""
    return float(sum((_fraction(p) * _survival(h, z)
                      for h, p in enumerate(posterior)), F(0)))


def simplex_from_fill_probs(p_z0, p_z1):
    """Invert the two-context decoder; do not clip an infeasible direct fit."""
    p0, p1 = _fraction(p_z0), _fraction(p_z1)
    q1 = F(5, 3) * (p1 - p0)
    q0 = (20 * p0 - 4 - q1) / 14
    return tuple(map(float, (q0, q1, 1 - q0 - q1)))


def auxiliary_posterior(counts, alpha=F(1, 2)):
    """Dirichlet posterior from the same C-cell H labels in every output."""
    a = _fraction(alpha)
    counts = tuple(map(_fraction, counts))
    denominator = sum(counts) + len(counts) * a
    return tuple(float((n + a) / denominator) for n in counts)


def matched_auxiliary_direct(counts, z, alpha=F(1, 2)):
    """Direct soft-target mean algebraically equal to posterior projection."""
    a = _fraction(alpha)
    numerator = sum(((_fraction(n) + a) * _survival(h, z)
                     for h, n in enumerate(counts)), F(0))
    return float(numerator / (_fraction(sum(counts)) + len(counts) * a))


def rounded_mean_state(posterior):
    """Nearest latent rank, with an exact half tie sent to the lower rank."""
    mean = sum((h * _fraction(p) for h, p in enumerate(posterior)), F(0))
    return ceil(mean - F(1, 2))


def rounded_auxiliary_mean(counts, alpha=F(1, 2)):
    """Count-based point readout preserves exact ties before float conversion."""
    a = _fraction(alpha)
    denominator = _fraction(sum(counts)) + len(counts) * a
    return rounded_mean_state(tuple((_fraction(n) + a) / denominator for n in counts))


def reference_probability(name, c, z, h, condition):
    """Fraction-valued references; law-aware Bayes is not shift adaptation."""
    if name == "coarse_bayes":
        return _bayes(c, z, condition)
    if name == "current_rich":
        return _survival(h, z)
    if name == "unconditional":
        return F(11, 20)
    if name == "context_only":
        return (F(2, 5), F(7, 10))[z]
    if name == "point_mean":
        return _survival(1, z)
    if name == "source_informative":
        return _bayes(c, z, "informative")
    raise ValueError("Unknown exact-reference name.")


def population_metrics(condition, predictor, log_epsilon=1e-9):
    """Enumerate exact-law risk for predictor(c,z,h), conditional on its fit.

    Brier and decision risks use the supplied probabilities unchanged. Only
    logarithms are clipped. This computes no confidence interval or fit.
    """
    brier, log_score = F(0), 0.0
    decisions = {threshold: F(0) for threshold in DECISION_THRESHOLDS}
    for c, z, h, j in product((0, 1), (0, 1), range(3), range(4)):
        mass = _law(condition, c)[h] * _FLOW[z][j] / 4
        y = full_fill(h, j)
        p = _fraction(predictor(c, z, h))
        if not 0 <= p <= 1:
            raise ValueError("A scoring probability must lie in [0,1].")
        brier += mass * (p - y) ** 2
        clipped = min(1 - log_epsilon, max(log_epsilon, float(p)))
        log_score -= float(mass) * (y * log(clipped) + (1 - y) * log(1 - clipped))
        for threshold in decisions:
            action = int(p > threshold)
            loss = threshold * action * (1 - y) + (1 - threshold) * (1 - action) * y
            decisions[threshold] += mass * loss
    return dict(brier=float(brier), brier_fraction=str(brier), log_score=log_score,
                decision_loss={str(float(t)): float(v) for t, v in decisions.items()},
                decision_loss_fraction={str(float(t)): str(v) for t, v in decisions.items()})


def analytic_references(condition):
    names = ("coarse_bayes", "current_rich", "unconditional", "context_only",
             "point_mean", "source_informative")
    result = {name: population_metrics(condition, lambda c, z, h, name=name:
              reference_probability(name, c, z, h, condition)) for name in names}
    # A constant action is an absolute benchmark, not a trading profit claim.
    result["always_act"] = {str(float(t)): float(t * F(9, 20)) for t in DECISION_THRESHOLDS}
    result["always_abstain"] = {str(float(t)): float((1 - t) * F(11, 20)) for t in DECISION_THRESHOLDS}
    return result


def likelihood_certificate(posterior, successes_by_z, totals_by_z, tolerance=1e-6):
    """Independent objective/KKT diagnostic for a supplied Y-only posterior.

    This evaluates, but never optimizes or fits, the frozen likelihood with
    one success and one failure added in each Z cell. Convexity makes the
    simplex-vertex directional inequalities sufficient up to the tolerance.
    """
    q = tuple(map(float, posterior))
    probabilities = [sum(q[h] * survival(h, z) for h in range(3)) for z in (0, 1)]
    gradient, nll = [0.0] * 3, 0.0
    for z, p in enumerate(probabilities):
        if not 0 < p < 1:
            raise ValueError("The supplied posterior projects outside the log-score domain.")
        successes = float(successes_by_z[z]) + 1
        failures = float(totals_by_z[z] - successes_by_z[z]) + 1
        nll -= successes * log(p) + failures * log(1 - p)
        coefficient = failures / (1 - p) - successes / p
        for h in range(3):
            gradient[h] += coefficient * survival(h, z)
    average_gradient = sum(p * g for p, g in zip(q, gradient))
    directions = [g - average_gradient for g in gradient]
    feasible = abs(sum(q) - 1) <= tolerance and min(q) >= -tolerance and max(q) <= 1 + tolerance
    return dict(probabilities=probabilities, augmented_nll=nll, gradient=gradient,
                vertex_directional_derivatives=directions, simplex_feasible=feasible,
                kkt_pass=feasible and min(directions) >= -tolerance,
                tolerance=tolerance)


def verify_exact_identities():
    """Optional prospective arithmetic checks; caller decides when to execute."""
    expected_brier = {"zero": F(9, 40), "informative": F(2169, 10000), "shift": F(2169, 10000)}
    for condition in CONDITIONS:
        worlds = enumerate_support(condition)
        assert len(worlds) == 384
        assert sum((F(w["mass_numerator"], w["mass_denominator"]) for w in worlds), F(0)) == 1
        assert all(w["y"] == int(w["filled"] == w["q"]) for w in worlds)
        assert all(sum((h * p for h, p in enumerate(_law(condition, c))), F(0)) == 1 for c in (0, 1))
        references = analytic_references(condition)
        assert F(references["coarse_bayes"]["brier_fraction"]) == expected_brier[condition]
        assert F(references["current_rich"]["brier_fraction"]) == F(113, 800)
        assert F(references["unconditional"]["brier_fraction"]) == F(99, 400)
        assert F(references["context_only"]["brier_fraction"]) == F(9, 40)
        assert F(references["point_mean"]["brier_fraction"]) == F(99, 400)
    assert F(analytic_references("shift")["source_informative"]["brier_fraction"]) == F(2493, 10000)
    for posterior in ((1, 0, 0), (0, 1, 0), (0, 0, 1), (F(1, 10), F(4, 5), F(1, 10))):
        p = [sum((_fraction(q) * _survival(h, z) for h, q in enumerate(posterior)), F(0)) for z in (0, 1)]
        assert simplex_from_fill_probs(*p) == tuple(map(float, posterior))
    assert rounded_mean_state((F(1, 2), F(1, 2), 0)) == 0
    assert rounded_mean_state((0, F(1, 2), F(1, 2))) == 1
    assert likelihood_certificate((F(1, 4), F(1, 2), F(1, 4)), (7, 13), (18, 18))["kkt_pass"]
    assert not likelihood_certificate((F(1, 2), 0, F(1, 2)), (7, 13), (18, 18))["kkt_pass"]
    trial, epsilon = [0.2, 0.5, 0.3], 1e-6
    gradient = likelihood_certificate(trial, (7, 13), (18, 18))["gradient"]
    for h in (0, 1):
        plus, minus = trial.copy(), trial.copy()
        plus[h] += epsilon
        plus[2] -= epsilon
        minus[h] -= epsilon
        minus[2] += epsilon
        difference = (likelihood_certificate(plus, (7, 13), (18, 18))["augmented_nll"]
                      - likelihood_certificate(minus, (7, 13), (18, 18))["augmented_nll"]) / (2 * epsilon)
        assert abs(difference - (gradient[h] - gradient[2])) < 1e-6
    return True
