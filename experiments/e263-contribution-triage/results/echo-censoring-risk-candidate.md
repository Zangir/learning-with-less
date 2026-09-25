# Candidate C: decision-risk control with censored horizons and delayed labels

**Recommendation: NO-GO as a present contribution candidate.** The admitted records support a small deterministic completion-bound audit. They do not establish a new risk-control theorem, an identifiable prospective risk target under arbitrary temporal shift, or a separation from equally informed direct predictors. Combining known missing-outcome bounds, delayed updates and selective fallback is not a sufficient novelty claim. This author-side mathematical/source review is not coordinator acceptance.

## 1. Admitted population and the missing result

D-041 authorizes contribution triage only. Accepted R031/RV029 concern four previously exposed BTC dates and conditional third-party normalized sampled-L2 inputs. There are 3,384 recorded events, 3,382 supported/scored events and two censored records. Admission does not authenticate exchange completeness, publication latency, participant identity or a pristine holdout. The aggregate later-period reversal is descriptive; it is not itself a population shift certificate.

Let R=1 mean a past-eligible event was recorded under the frozen slot/cooldown rule, S=1 mean the entire ten-cut future horizon is supported, and X denote information available at the decision. Three targets must remain separate:

- The accepted target is loss on R=1,S=1, with equal-day weighting primary and pooled-event weighting a sensitivity.
- A new completion target could average loss over all R=1, assigning censored rows a hypothetical label from a complete one-second horizon. This must be defined explicitly; it is not an amendment of the accepted estimand.
- Future deployment risk, all candidate events, or all calendar opportunities requires further population and source assumptions. The two censored recorded events do not count opportunities excluded by missing past support, recording rules or source gaps.

P1 requires all ten future cuts even after an early threshold hit. This is not automatically ordinary right-censored survival data: it is a first-hit categorical label with a stricter full-horizon support gate. “Pending because the horizon has not ended” differs from “permanently unsupported under the admitted contract.” In a retrospective replay the former can resolve after the prescribed ten cuts; the latter cannot be converted into an observed label merely by waiting. Actual release/admission timestamps are null, so ten seconds is not an authenticated real-world delivery latency.

A prospective gate must use X and already mature labels. Feeding the eventual S flag into the decision is future leakage. An online controller also cannot update at an early hit if its label contract still requires the remaining horizon. No conditional independence between missingness and outcome, positive observation propensity, or bound on future conditional-label drift is established by R031.

The missing result would have to be a nontrivial, implementable guarantee for a precisely declared prospective or recorded-completion loss under justified source assumptions, with better informativeness or computational cost than existing partial-identification/sequential controls using identical information. No such result is currently specified.

## 2. Deterministic completion bounds are useful but routine

For half-scaled three-class Brier loss,

`ell(p,y) = 0.5 * (sum_k p_k^2 + 1) - p_y`, with `0 <= ell <= 1`.

On a fixed day with n scored and m censored recorded rows, every hypothetical completion satisfies

`sum_observed ell / (n+m) <= R_complete <= (sum_observed ell + m) / (n+m)`.

For two fixed predictors, write Delta_day for their supported-row mean loss difference. Since each missing paired loss lies in [-1,1], the four-day equal-weighted completion difference lies in

`mean_day[n/(n+m) * Delta_day] +/- mean_day[m/(n+m)]`.

This is the root's proposed arithmetic audit, and it is valid without independence, missing-at-random assumptions, model replay or new fitting. It is an outer identification interval on fixed records, not a confidence interval, a future-risk guarantee or a novel theorem. It also does not alter the original supported-only result.

From the accepted counts, breakout has one missing row among 1,750 records, in October's 361 records; rebound has one among 1,634, in August's 669. Consequently the individual-loss interval widths are 1/1750 and 1/1634 for pooled weighting, and 1/1444 and 1/2676 for equal-day weighting. These same quantities are the corresponding generic paired-interval half-widths. This small missing mass limits how much these two rows can change the recorded-population summaries; it does not bound the effect of unrecorded opportunities or a future outage.

Using saved probabilities can tighten each missing paired term: it equals `a - (p_y-q_y)`, where `a=0.5*(sum p^2-sum q^2)`. Minimize/maximize over admissible labels. A supported partial path may reduce that label set. However, overlapping horizons can couple feasible labels across rows, so summing independent row extrema need not be sharp. A claim of sharpness requires a common source-compatible path attaining the joint extrema. None of this adds information to a reconstruction arm that a direct arm cannot receive.

## 3. Two distinct indistinguishable-world failures

**Selective observation, even without temporal shift.** Consider eight recorded rows with identical visible X. The first four have S=1 and Y=F; the last four have S=0. World W0 assigns F to all four missing labels; W1 assigns A. The complete observed archive `(X,S,SY)` is identical. A predictor assigning probability one to F has supported-row Brier loss zero in both worlds, but hypothetical full-record loss is zero in W0 and 1/2 in W1. The missing-mass bound is attained. This is a mathematical witness, not a reconstruction of the two actual censored R031 paths.

The same construction applies to selective acceptance: a rule that accepts the indistinguishable censored stratum cannot infer its loss from the supported stratum. A small overall missing fraction does not imply a small missing fraction inside a selected subgroup. An inverse-propensity estimate would require justified conditional ignorability and positive, known or controlled observation probabilities; fitting a censoring classifier alone does not supply those conditions.

**A new block before delayed labels arrive.** Two worlds share the full observed past and the same future X sequence. During the next D predictions, no outcomes have arrived. All labels in that block are F in one world and A in the other. Any causal gate/predictor has identical actions in both worlds throughout the block. For any nonempty set of accepted binary F/A classifications, the two worlds' error fractions sum to one, so worst-world accepted error is at least 1/2. If fallback incurs known loss kappa<1/2, a rule accepting a fraction rho has worst-world total loss at least `rho/2 + (1-rho)*kappa`. It cannot certify total loss <=kappa uniformly while maintaining rho>0. This does not deny long-run adaptive coverage after feedback; it rules out a stronger nontrivial pre-feedback guarantee without restrictions linking the new block to the past.

Unchanged feature marginals do not exclude this second world pair. A source-age or covariate-drift alarm therefore cannot by itself certify conditional decision risk. Full prediction sets or universal fallback may satisfy a safety-style target, but their cost/coverage must be charged explicitly rather than presented as useful selective performance.

## 4. Closest primary comparators

The following are substantive overlaps, not an exhaustive priority certification. No quoted theorem is imported as a validated project guarantee.

| Primary source | Relevant existing result and remaining mismatch |
|---|---|
| [Tchetgen Tchetgen and Wirth, A general instrumental variable framework for regression analysis with outcome missing not at random (2017), Section 6](https://pmc.ncbi.nlm.nih.gov/articles/PMC5569006/) | States assumption-free binary-mean bounds whose width equals missing mass, then considers stronger restrictions. The bounded-loss decomposition above is the same elementary partial-identification mechanism, derived directly here; no instrumental variable is admitted for this project. |
| [Gibbs and Candes, Adaptive Conformal Inference Under Distribution Shift, NeurIPS 2021](https://papers.nips.cc/paper/2021/file/0d441de75945e5acbc865406fc9a2559-Paper.pdf) | Online error feedback adapts coverage under changing distributions. Long-run coverage is different from decision loss on accepted predictions, worst-window risk, or risk on permanently unlabelled cases. A model-agnostic wrapper is already the baseline. |
| [Farinhas et al., Non-Exchangeable Conformal Risk Control, 2024 version, Section 3](https://arxiv.org/html/2310.01262v2) | Controls bounded monotone loss with an explicit total-variation penalty for non-exchangeability. Time weighting alone does not certify a small unknown penalty. Arbitrary action/fallback loss is not automatically monotone in a threshold. |
| [Zhao et al., Conformalized Interactive Imitation Learning: Handling Expert Shift & Intermittent Feedback, ICLR 2025, Section 3](https://arxiv.org/html/2410.08852v2) | Proposes intermittent quantile tracking, with updates scaled by the observation probability. Thus intermittent-label online calibration is already explicit prior work. Its probabilistic observation model is not evidence of positivity or ignorability for source outages. This memo uses the method as prior-art overlap, not as an independently audited finite-sample certificate. |
| [Davidov et al., Conformalized Survival Analysis for General Right-Censored Data, ICLR 2025](https://proceedings.iclr.cc/paper_files/paper/2025/file/f49d76cf84df83a611883c621c96d2d9-Paper-Conference.pdf) | Develops lower predictive survival bounds under a right-censoring model; conditional independent censoring and i.i.d. limits are explicit. An F/A/N label withheld after any unsupported cut does not inherit these assumptions or its survival target. |
| [Joulani, Gyorgy and Szepesvari, Online Learning under Delayed Feedback, ICML 2013](https://proceedings.mlr.press/v28/joulani13.pdf) | Gives general reductions from non-delayed to delayed online learning. Delayed feedback by itself is not a new learning architecture; permanent loss of labels is a different identification issue. |
| [El Halabi and Brandt, Adaptive Conformal Inference Under Delayed Feedback: Coverage Guarantees and a Delay-to-Memory Diagnostic, preprint 7 September 2026](https://arxiv.org/html/2609.07251v1) | Explicitly studies forecast-horizon delay, interleaved ACI recursions and delay-dependent coverage bounds. It is recent unreviewed primary work, sufficient to defeat a claim that adding horizon-aware ACI updates is untouched territory; it does not establish validity for our censored source. |
| [Bai, Fang and Chen, Risk-Controlling Predictive Sets for Time-Series Events Under Selective Observation with Finite-Sample Guarantees, Axioms, 21 September 2026](https://www.mdpi.com/2075-1680/15/9/706) | Particularly close: selective-label non-identification, predictable inverse-inclusion losses, martingale risk certificates and a separately certified deployment-drift envelope. Assumptions 1–2 require conditional ignorability and a positive inclusion floor; future certification needs additional drift evidence. Our archive supplies neither randomized audits nor that envelope. This source's stated combination already overlaps the broad candidate. |

The final source's publisher text was accessible through indexed primary-page retrieval, including its assumptions and non-identification theorem; direct page opens failed. The 2017 missing-outcome paper's Section 6 and metadata were likewise retrieved from indexed primary manuscript text; direct PMC opening encountered a browser check. Other listed sources were inspected in primary PDF or author HTML form. The review did not audit every proof or empirical result. Contemporary primary work strengthens the no-go conclusion, but the elementary counterexamples and older overlap already suffice; rejection does not rest on accepting a new paper's theorem on authority.

## 5. Fair controls, endpoints and smallest future gate

All risk wrappers must receive the same causal X, frozen base predictions, matured labels, partial-path constraints, censoring information available at each timestamp, drift assumptions, calibration budget and compute. Apply the same wrapper to direct C, predicted-summary P, observed-depth R, and the fixed-frequency reference when their source information is matched. A richer R predictor must be identified as a richer-information comparison. Give a direct control every reconstructed deterministic feature available to P. No risk-control advantage is intrinsically reconstruction-specific.

Mandatory simple controls are the bounded completion interval, a fixed calibrated threshold when its calibration assumptions are valid, an appropriate delayed/intermittent online method, the same source-age/gap rule, and always-fallback. Count fallback cost. A guarantee for unconditional error mass is not a guarantee for conditional error among accepted cases: report both the accepted mass and its denominator. No execution/PnL claim follows from F/A/N.

If this candidate were separately reopened, the smallest distinguishing test is **a finite proof fixture before any fitted pilot**: four time-indexed decisions, two delayed or permanently unobserved binary labels, an explicit filtration, and all four label completions. Add the two entirely unobserved shifted-block worlds above. Use fixed probability vectors and a fixed bounded action/fallback loss. Exhaustively verify the claimed certificate and causal update ordering, then compare its bound width and acceptance against the elementary completion bound and a direct wrapper with identical inputs. No source replay, fit, simulator episode or market acquisition is necessary for that gate.

The primary endpoint would be valid worst-completion risk at a predeclared acceptance/fallback cost; secondary endpoints are bound width, nontrivial acceptance, update work and memory. Report pending and permanently missing counts separately. Finite-record bounds require no sampling approximation. Any later empirical uncertainty analysis must use justified temporal units; 3,384 dependent events and repeated mask/seed variants are not independent market replicates.

**Kill criterion:** reject if the bound fails on either indistinguishable-world construction, silently assumes future S or independent censoring, becomes useful only after an unsupported drift/propensity restriction, or reduces to known bounded-loss completion plus a delayed-feedback wrapper with no demonstrable strict improvement. Equality between reconstructed and direct implementations rules out a reconstruction-specific advantage; it does not by itself reject a distinct risk-control theorem that helps both. General Candidate C needs a substantive difference from the closest existing risk-control comparators. The current candidate already fails that distinct-result gate; no new experiment is recommended merely to keep it active.

## 6. Review provenance and resources

Read-only inputs and SHA-256:

- `cycle-20260922-1222/D-041.md`: `ef24c828e4bb3b0be795a7864401b6624a9f441f2d53a8c9d19f0509700451e2`.
- `cycle-20260922-1122/frozen-R-031/report.md`: `960294c9b6060427c1bdea12f8443d1189af1b528e861d082b8472b8ad822030`.
- `cycle-20260922-1222/frozen-RV-029/report.md`: `342954dec8c755166f17488e112f2bb2bce1b06ebc5150f3e62e0f5ce8cda2c7`.

The scoped reports were read rather than rerunning their evidence. Only this memo was written in the artifact packet. No canonical control, hidden participant source, fitted model, native simulator or external market data was accessed. New fits and native episodes: zero. No repository code, root report or PDF was edited. No tmux sessions were created or used. Timing began at 12:34:54 +04:00 on 2026-09-22; source review and core derivation completed at 12:38:48. Final memo timing is recorded in the closing message and the temporary `t012-r9-echo-censoring-review-timing.txt` log.
