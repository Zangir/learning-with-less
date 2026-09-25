# Conditional score information: bounded next-test contract

Status: **proposed and unexecuted**, except the reference exact synthetic arithmetic. Assignment E272/D058 authorizes design and analytical checks only. No empirical release is requested as an automatic consequence of this document.

## Question and hierarchy

Does the fixed rich breakout score S=f_R(X,Z) use information about F/A/N absent from all 446 declared coarse coordinates X? The population half-Brier oracle gain Delta_S is bounded by full-depth Delta_Z. The conditional replacement contrast J is a one-sided witness of beneficial use, not the entire information value. A score can discard useful depth, and a useful association need not make the forecast better than simple references.

This is a known conditional predictive-importance/HRT diagnostic. Neither the question, its Brier identity nor the proposed application is currently an ICLR2027 contribution.

## Gate 0: scientific contract

Before any empirical arrays are read, freeze the exact target population, causal conditioning set, weighting, support selection and exposure status. The primary question uses raw-weighted supported breakout events. A class-standardized law is a separate estimand requiring its own conditional score law. No favorable class or date may be chosen from existing outcome differences. Q16 admission is not needed for this sampled-L2 question, and native truth must not be inferred from it.

Coordinator decision required: select an already retained source/cohort by non-outcome criteria and independent exposure review, or declare that no adequate confirmation cohort exists. February 2026 is already exposed and is exploratory for this newly formulated question. No new market acquisition or expansion of the persistence test follows.

## Gate 1: replacement law and temporal uncertainty

Supply P(S | X, recorded and supported), or Q with an independently justified error envelope. The three score coordinates are one joint simplex-valued object. Conditioning on f_C(X), f_P(X), coarse bins or selected features alone changes the question. A coarsening is admissible for the original target only with a sufficient-conditioning argument; no such argument is available now.

Acceptable grounds could be a known controlled data-generating law, a justified finite sufficient stratum with exact conditional exchangeability, or a specified structural family and a theorem supporting the error claim in the target population. A fitted density, ordinary calibration, matched univariate marginals or failure of a goodness-of-fit test cannot alone establish that claim. Do not silently assume Gaussian residuals, exchangeable rows or independent time blocks.

For the expected-loss bias bound, epsilon is the mean conditional TV error under the target law. It bounds |J_Q-J|, not automatically the type-I error of a whole-sample HRT. A whole-vector randomization p-value needs a corresponding joint exchangeability/error result. Multiplying a one-row guarantee across dependent events is invalid without further work. Conditioning on all future X to obtain a sequence sampler also changes the causal per-event estimand unless equivalence is proved.

A temporal uncertainty contract must justify inference for the chosen target. The inherited 130-second separation removes overlap; it does not establish independence or stationarity. Exact Monte Carlo simulation from Q addresses only simulation variation. If a justified event/block sampling argument is unavailable, only a disclosed finite-cohort exploratory contrast may be reported, with no population information certificate.

**Current gate result: NO-GO.** The scoped accepted evidence supplies neither the conditional law/error certificate nor the required temporal inference assumptions. No nuisance model is selected or fitted in this assignment.

## Gate 2: smallest implementation acceptance fixture

Given a proposed operator, run it on the following known finite synthetic laws before any real-data diagnostic. Keep seed 20260919 for stochastic implementations; exact enumeration is preferable. At most 1,000 atoms, zero fitted models and no native exchange simulation.

| Fixed law / score | Expected conditional J | Required interpretation |
|---|---:|---|
| Binary X=Z=Y; true conditional score is deterministic | 0 | No extra information; marginal replacement falsely gives 1/2 |
| Two coarse bits; Z=Y=XOR(X) | 0 | Easier representation is not new information |
| Constant X; uniform three-class Y=Z; correct one-hot score | 2/3 | Useful signal; Delta_Z=Delta_S=1/3 |
| Same informative law; uniform score | 0 | Insensitive score; depth null is not established |
| Same informative law; cyclic wrong one-hot score | -1/3 | Harmful use; Delta_Z remains 1/3 |
| Deterministic binary null; wrong sampler flips score with probability 1/8 | J_Q=1/8, epsilon=1/8 | The bias-adjusted evidence is zero |

The reference laws and exact calculations are already in analytical-checks.json. Evaluating a subsequently supplied replacement operator is future work. Exact mismatch beyond arithmetic tolerance, incorrect simplex support, marginal replacement or an undeclared conditioning change kills the operator. No law is tuned to the accepted February losses.

Planning estimate: under one minute of calculation; hard cap ten minutes at two CPU equivalents and 8 GiB. Save only the small laws, receipts and discrepancies, below 1 MiB.

## Gate 3: separately authorized score-only diagnostic

Proceed only after Gates 0-2 and independent review pass. Reuse saved, identity-bound X, S and labels from the selected existing cohort. Do not replay sources or refit/reinfer the predictive models. Keep all recorded IDs and support exclusions; score only the predeclared common supported population. If needed retained arrays do not exist, stop and request a distinct capability release rather than generating them implicitly.

The frozen R score is the primary statistic. C and P, including P's deterministic inferred summaries, are X-measurable negative controls under their correct degenerate conditional laws. Uniform and training frequency remain reference losses. A same-information direct or distilled model can receive exactly the same diagnostic; no reconstruction-specific claim is made. No learned ensemble or new threshold is introduced.

Use at most 10,000 existing rows and 199 conditional replacement replicates, stream at most 64 score arrays per batch, and save per-block aggregate differences plus sampler provenance. One primary hypothesis; no class/date/feature-subset search. Predictive fitting, selection and calibration budgets are zero. Any separate nuisance fitting contract must charge every training/selection attempt and use data disjoint from evaluation with justified temporal separation. No nuisance fitting is approved by this design.

Compute accounting: 10,000 x 199 x 3 = 5,970,000 replacement probability coordinates; one 64-replica float64 batch is 15,360,000 bytes, excluding conditioner/model workspace. Cap the diagnostic at one hour, two CPU-hours, 8 GiB aggregate and 32 MiB retained output. The sampler cost is unknown, so this is a hard envelope rather than a measured runtime forecast. Stop if the envelope cannot support the declared law and uncertainty procedure. Do not lower the standard or swap samplers after seeing results.

## Predeclared branches

1. Missing law/error certificate, invalid temporal inference, outcome-exposure incompatibility or failed negative control: **stop; no information conclusion**.
2. Valid population interval for J_Q entirely above +epsilon: **beneficial conditional signal in the frozen rich score** for the declared population. If desired, report the conservative Delta_Z lower bound 3/4 times the square of the positive bias-adjusted lower limit.
3. Valid interval entirely below -epsilon: **harmful use of conditional association**. This is not a no-information result.
4. Otherwise: **inconclusive**. Failure to reject cannot rule out information in unused parts of Z or below the test's sensitivity.

A one-sided significance level, any allocation of error probability between sampler certification and sampling uncertainty, and any confirmation cohort must be frozen by coordinator/reviewer before execution. Zero is the scientific null; no new economically meaningful margin is inferred from the observed contrast. If only exploratory finite-cohort analysis is justified, label it accordingly and do not apply these population-certificate branches.

No branch by itself authorizes model development, extra dates, trading, publication or an ICLR claim. The prerequisite decision is complete even when its answer is no-go.
