# Thirty experiments in the LOB programme

**What was tried, what went in, what came out, and what can be claimed**
Evidence frozen at research state revision 187; report generated 25 September 2026.

## Executive view

The programme asks when information hidden by a coarse limit-order-book view is worth reconstructing, and whether that reconstruction improves prediction or decisions over a strong direct learner. The engineering work produced three kinds of evidence: real Hyperliquid adaptations, controlled simulator studies, and validity/source checks that determine whether a scientific comparison is even admissible.

The clearest results are mostly disciplined negatives. Q17 completed on native Hyperliquid BBO data, but better forecast scores did not satisfy the predeclared cross-asset policy-ranking reversal. Q18 completed a receipt-clock depth/history/delay study, but neither ablation produced a consistent freshness crossing. Q16's software and conditional checks are sound, but no eligible real-data episode was admitted, so its mandatory empirical question remains open. In controlled simulation, hidden-queue uncertainty mattered, yet a matched direct predictor equalled the uncertainty-preserving reconstruction at 512 training draws. On sampled BTC L2, an early rich-depth breakout advantage disappeared on later dates. The book-washout pilot showed fast disclosure of inherited orders but remained incomplete after 11 hours.

### How status words are used

- **Valid negative**: the declared test completed and the criterion failed. This is a scientific result within the declared scope.
- **Valid limited/diagnostic**: the computation is correct, but it establishes readiness, feasibility, or a narrow mechanism rather than the headline empirical claim.
- **Invalid or unadmitted input**: the source failed a prerequisite. No outcome from that source counts as evidence for the target claim.
- **Inconclusive**: the observed prefix is valid, but the required decision horizon or denominator is missing.
- **Cancelled/preparation only**: no empirical result was produced.

## One-page status table

| Package | Scientific status | Headline |
|---|---|---|
| E001 | Valid audit | Real BTC first-hour schema/integrity check; no replication claim. |
| Q16 (E016+E266) | Conditional evidence; blocked | Finite checks pass; zero eligible real-data episodes. |
| Q17 (E017+E267) | Completed scoped negative | Forecast gain did not produce the required policy reversal. |
| Q18 (E018+E268) | Completed exploratory negative | Depth/history freshness criterion was not met. |
| E002 | Valid diagnostic | Offline anchor matching improved, but causal timing stayed uncertified. |
| E200 | Limited/open | Event-clock diagnostics valid; complete causal window still open. |
| E201 | Limited/open | Initial state and FIFO/history not certified. |
| E202 | Limited/open | Bounded chronological routes exist; full primary panel not certified. |
| E203 | Limited/open | Paired-view contract scoped; exchange-complete causal pairing open. |
| E204 | Limited/open | Observed-order labels feasible only conditionally; native fills open. |
| E205 | Valid negative | Unmodified ABIDES is unsuitable as an unrestricted generator. |
| E210 | Valid synthetic | Ambiguity matters, but no reconstruction-specific gain. |
| E253 | Valid design | Breakout/rebound protocol fixed; no performance result. |
| E254 | Valid identity negative | One restoration candidate compiles exactly to a direct method. |
| E255 | Valid feasibility | 21 label-blind opportunities extracted from one fixed hour. |
| E256 | Valid readiness | Repaired restricted simulator passed its bounded contract. |
| E257 | Valid data readiness | 4,139 labels prepared; no predictive result yet. |
| E258 | Valid equivalence negative | Direct and distributional outputs coincide at 512 draws. |
| E259 | Valid mixed result | Rich depth helped breakout on three exposed dates only. |
| E260 | Valid novelty negative | No distinct reconstruction contribution survived matched controls. |
| E261 | Valid temporal negative | Earlier rich-depth advantage did not persist on four later dates. |
| E262 | Cancelled | No execution and no scientific result. |
| E263 | Valid triage negative | Three remaining candidates rejected as current paper contributions. |
| E264 | Valid diagnosis | Comparative reversal is mostly class-conditional, not just class mix. |
| E265 | Partial source result | Q17/Q18 sources admitted; Q16 source unavailable. |
| E269 | Preparation only | No eligible retained post-November full-day BTC source. |
| E270 | Source only | One February 2026 BTC day declared and admitted conditionally. |
| E271 | Valid scoped contradiction | Strict breakout persistence conjunction failed on that day. |
| E272 | Review pending | Analytical next-test design; no empirical execution. |
| E273 | Reviewed inconclusive prefix | 11-hour washout valid; 48-hour decision not reached. |

## Mandatory Q16-Q18 programme

### E001 -- BTC provenance, schema, timing, and replay audit

**Idea, input, method.** This prerequisite checked whether the available BTC material could support the original Q16-Q18 logic at all. It combined fresh synthetic source checks with a bounded integrity and schema audit of the first real BTC hour, inspecting fields, ordering, timing candidates, and replay assumptions before treating the dump as a market experiment.

**Output, result, status.** The packet is a valid bounded audit, not a replication. It confirmed useful structure in one development hour but left the initial book, the observation clock, and untouched chronological evaluation uncertified. The correct conclusion is "data engineering can proceed under explicit conditions," not "Q16-Q18 worked on real data."

### Q16 -- finite queue ambiguity and real-data completion (E016 + E266)

**Idea, input, method.** Q16 asks whether order-count information shrinks the set of feasible queue states and changes a hypothetical order's execution. Engineers built an exact finite observer/probe model, added cancellation and prefix/conservation checks, applied it to conditional atomic order histories, and then prepared a corrected real-data execution packet for an admitted Hyperliquid source.

**Output, result, status.** The controlled machinery is valid, but the real empirical goal is unfinished. The conditional primary found **0/961** count-tightened cases; a post-run completion found **0/962**. A same-anchor extension yielded **979 exact, 21 censored, 0 unresolved** cases and three positive executions, still with zero count tightening. The final software correction passed **85 tests**, but **0 empirical episodes** were admitted because a qualified native source was absent. This is a valid conditional negative plus a blocked empirical replication, not evidence that counts never matter.

### Q17 -- forecast quality versus decision utility (E017 + E267)

**Idea, input, method.** Q17 tested whether model rankings by forecast quality can disagree with rankings by a quote-decision utility. The final adaptation used **30 native Hyperliquid BBO asset/date contracts**, provider receipt and exchange-event clocks, July-September training, October validation, eight November-June test dates, and later transfer dates. Logistic, histogram-boosting, and MLP streams were fit under frozen policies; **22 fitted streams** completed.

**Output, result, status.** The predeclared eight-contrast joint reversal rule failed. MLP minus logistic macro-F1 was **+0.14210 BTC** and **+0.09708 ETH**; primary argmax utility differences were also positive at **+2.12237** and **+1.80172 bps/opportunity**. Confidence policies tied at zero utility, while scheduling differences were **+0.02596 BTC** and **-0.07094 ETH** with intervals spanning zero. Thus forecasting improved, but the required cross-asset reversal did not appear. This is a completed, independently checked scoped negative, not equivalence and not realized-profit evidence.

### Q18 -- depth, history, and delayed-view factorial (E018 + E268)

**Idea, input, method.** Q18 asked whether deeper levels or longer history retain useful predictive value when observations are delayed. The final exploratory adaptation used **18 admitted sampled-L2 contracts**, receipt-clock observations and targets, BTC and ETH, logistic/HGB/MLP models, depth and history ablations, a 55-second cached-view delay, and **120 fitted estimators** spanning pilot, optimizer, and three-date transfer stages.

**Output, result, status.** The fixed pilot crossing criterion was not met: depth directions were **[0, 0, 0, -1]** across asset/learner cells and history directions were **[0, 0, 0, 0]**. Among 24 later directional contrasts, only **2** met the 1% margin and **6** met 2%; three selected dates cannot support a population noninferiority claim. Absolute losses also showed that a relative ablation gain need not beat the training-prior baseline. This is a completed exploratory negative for the frozen criterion, not proof that depth or history is universally useless.

### E002 -- existing-hour clock-anchor diagnostic

**Idea, input, method.** This diagnostic tried to align event updates with plausible point timestamps inside one existing BTC hour. It applied an offline matching rule to the same **91,868** diff events and compared coverage before and after broadening the candidate anchors.

**Output, result, status.** Candidate matches rose from **90,083 to 91,860**, adding **1,777** anchors. Eight updates remained unmatched and one retained ordering inversion measured **182.854823 ms**. The result is valid offline feasibility evidence, but offline matching does not prove that the information was causally available at decision time.

### E200 -- causal event-clock and availability certificate

**Idea, input, method.** E200 separated exchange-event time, provider receipt time, and downstream availability. Historical and live sampled-state routes were replayed with trigger-aware prefixes so that a feature could be admitted only when its supporting message was actually available under the declared clock.

**Output, result, status.** Independent review reproduced **eight unmatched decrements**, prefix-ordering behavior, and inherited/zero-size lifecycle limits. The route is useful in a limited diagnostic scope, but no complete Q16-Q18 window was certified and provider receipt time remains uncalibrated as strategy availability. The broader certificate is open.

### E201 -- initial state and historical matching-rule certificate

**Idea, input, method.** E201 asked whether a starting book plus archived changes identifies a valid historical order path. It compared sampled snapshots, lifecycle transitions, and matching assumptions, while explicitly separating aggregate state agreement from order-level FIFO and participant truth.

**Output, result, status.** Snapshot-compatible routes were constructed, but agreement with sampled states does not certify a unique hidden path, FIFO priority, receipt chronology, or counterfactual fills. The limited engineering result is valid; the initial-state and native matching certificate required for Q16 remains open.

### E202 -- chronological day blocks and data-budget feasibility

**Idea, input, method.** E202 mapped which contiguous day/hour blocks could be consumed without crossing recorded gaps, unsupported endpoints, or storage/transfer limits. It tied each proposed block to the same clock, startup, and segment rules used by the downstream experiments.

**Output, result, status.** Bounded historical and live routes were shown to be operationally possible, and exact limited input subsets were documented. However, the full primary panels and all their causal support were not certified. This is a valid planning and feasibility result, with the broader objective still open.

### E203 -- paired causal coarse/rich observation contract

**Idea, input, method.** This experiment specified how coarse and rich views must be paired: identical decision cutoff, target, support, and event population, with richer fields withheld rather than allowing different rows or future-supported selection to leak into one arm.

**Output, result, status.** The contract works for the scoped sampled routes and prevents several easy comparison errors. It does not authenticate exchange completeness or identify a unique order-level path, and a fully admitted real coarse/rich paired panel remains unavailable. The result is a valid limited contract, not a model comparison.

### E204 -- observed-order labels and execution-model feasibility

**Idea, input, method.** E204 examined whether observed orders can supply queue/fill labels for downstream execution questions. It separated recorded lifecycle evidence from hypothetical inserted-order outcomes and required explicit source, ownership, cutoff, and censoring rules.

**Output, result, status.** Conditional label routes were documented, but sampled snapshots could not certify native FIFO or counterfactual fills. No participant-linked real execution panel was admitted. The feasibility analysis is valid, while the headline empirical execution-model objective remains open.

## Controlled mechanisms, strategy extraction, and matched comparisons

### E205 -- simulator selection and mechanism validation

**Idea, input, method.** E205 selected pinned ABIDES as a restricted diagnostic engine and exercised real kernel/exchange paths for multi-unit insertions, cancellations, FIFO matching, partial fills, and modifications. Five primary episodes, replays, and holdout prefixes produced **12 native runs**; a matched pair kept the aggregate depth path fixed while changing which hidden order was cancelled.

**Output, result, status.** The matched coarse path **3, 6, 9, 6, 2** produced probe fills **3 versus 1**, proving action-relevant ambiguity. The audit also exposed two native defects: non-head modification corrupts queue identity and incoming history overstates matched volume. Postflight validation recorded **386/394 passing checks**, with the eight failures explained by those defects. The accepted outcome is a valid negative: unmodified ABIDES is unsuitable as an unrestricted rich-label generator, though useful in a narrow diagnostic scope.

### E210 -- controlled simulation of action-relevant ambiguity

**Idea, input, method.** This synthetic control studied a known binary law in which different hidden states can share a coarse observation but imply different actions. Direct posterior prediction, restricted summaries, and reconstruction-style representations were compared under the same information and known response law.

**Output, result, status.** The calibrated binary mean and the posterior decision control coincide; a restricted summary incurs **0.075 regret**, while apparent noisy-label gains reduce to known-noise denoising or symmetry. The result is valid in its synthetic scope: ambiguity can matter, but it did not isolate a restoration-specific advantage.

### E253 -- breakout/rebound protocol and claim-specific feasibility

**Idea, input, method.** E253 translated the strategy catalogue's priority breakout/rebound ideas into a prospective protocol: minute-frozen levels, label-blind opportunity extraction, causal histories, cooldown/state rules, future-support censoring, and separate claims for descriptive prediction, participant information, and executable strategy value.

**Output, result, status.** Review accepted the design after a deterministic "record-only consumes state" amendment. The package establishes a reproducible question and prevents descriptive sampled-L2 evidence from being promoted into a participant or profit claim. It is a valid design result with no predictive-performance outcome.

### E254 -- direct/restoration matched-method identity

**Idea, input, method.** E254 asked whether one proposed reconstruction pipeline was genuinely different from direct learning. For a fixed retrospective monotone robust-loss candidate, the structured computation was algebraically compiled into a direct predictor with matched inputs, supervision, objective, and output.

**Output, result, status.** The compiled methods were exactly identical for the declared candidate, so the candidate cannot support an exclusive reconstruction contribution. This is a valid candidate-specific identity negative; it does not prove that every latent-variable or distributional method can be compiled away.

### E255 -- label-blind breakout/rebound extraction audit

**Idea, input, method.** The amended E253 extractor was run on the fixed BTC hour 1 May 2025. It consumed **6,426 rows**, built minute-frozen support/resistance levels, checked 61-cut histories, and applied slot/cooldown state before any future label or model was inspected.

**Output, result, status.** From **24 raw candidates**, it recorded **21 opportunities: 10 breakout and 11 rebound**; two were rejected by consumed slots and one by cooldown. All 21 happened to have full retrospective ten-cut support. This is valid extraction feasibility only: no labels, fitting, accuracy, P&L, or strategy advantage was claimed.

### E256 -- restricted simulator repair and delivered-feed validation

**Idea, input, method.** E256 applied two explicit local repairs to pinned ABIDES, restricted the allowed operations, and forced anonymous depth plus own-order information to reach a participant through the actual kernel. Replays, prefixes, private-ID relabeling, delivery cutoffs, and an independent ledger checker tested the observation boundary.

**Output, result, status.** The frozen suite completed **32 engine runs and 2,052 comparisons** with zero repaired-engine/delivery failures; **554** supplemental boundary comparisons also passed. Two indistinguishable delivered histories still led to fills **3 versus 1**. The accepted result is bounded mechanism readiness and non-identifiability, not recoverability, market realism, or learner performance.

### E257 -- fixed labels and seven-date BTC cohort audit

**Idea, input, method.** E257 expanded the label-blind protocol to seven exposed BTC sampled-L2 dates, producing matched breakout/rebound histories, ten-cut F/A/N outcomes, censored cases, and the three planned views: coarse C, predicted-summary P, and observed-rich R.

**Output, result, status.** The frozen cohort contained **4,160 opportunities**, **4,139 labels**, and **21 censored events**. Independent review reproduced sources, events, labels, and feature alignment. This is a valid data-readiness result with zero predictive fits; counts alone say nothing about strategy quality.

### E258 -- point versus distributional fill prediction

**Idea, input, method.** E258 used the repaired native simulator to compare a point queue reconstruction, a distribution over hidden queues, and matched direct fill prediction. The known finite law generated **2,816 statistical episodes** plus exhaustive support diagnostics; the complete run used **3,212 native executions, 652,510 checks, and 24 fit invocations**.

**Output, result, status.** At **512 training episodes**, ordinary direct prediction and outcome-supervised distributional reconstruction were exactly equal in every visible cell and made identical decisions at all five thresholds. Rich queue labels improved finite prediction, but an equally supervised direct soft-target control matched that benefit. An unobservable conditional shift harmed both cue-dependent methods. This is a valid equivalence negative for reconstruction-specific advantage, while confirming that uncertainty itself can matter.

### E259 -- frozen 39-fit BTC coarse/predicted/rich comparison

**Idea, input, method.** E259 fit **39 frozen models** on the seven-date cohort: C used 446 coarse inputs, P added seven predicted depth summaries, and R added 1,464 observed extra-depth coordinates. Selection used April; May-July were already exposed descriptive evaluation dates with identical events and labels across arms.

**Output, result, status.** On breakout, equal-day half-Brier was **C 0.27818, P 0.27212, R 0.26354**, versus frequency **0.27443**; R was best. On rebound it was **C 0.28531, P 0.28372, R 0.28881**, while frequency won at **0.27053**. The mixed result is valid but descriptive: observed depth helped breakout on three dates, whereas no learned rebound arm beat the simple frequency reference.

### E260 -- rich-label adaptation novelty and identifiability challenge

**Idea, input, method.** E260 combined exact finite-law analysis with targeted literature review to ask whether rich hidden-state labels give reconstruction a unique adaptation advantage after an invisible conditional shift. It compared equally informed direct soft targets, structured counts, label-acquisition costs, and response-kernel identification.

**Output, result, status.** No distinct reconstruction contribution survived. The indistinguishable-world example gives a minimax excess-Brier lower bound of **0.0081** without target labels, while **656 exact direct/structured count-kernel equalities** show that the tested rich-label update can be compiled into a matched direct learner. Zero new fits were run. This is a valid scoped novelty negative; information acquisition may still be useful, but requires real access/cost evidence and a distinct method.

### E261 -- fixed-model August-November temporal evaluation

**Idea, input, method.** E261 froze the E259 models and performed zero-fit evaluation on four later BTC dates, retaining the original feature transforms, event rules, equal-day primary, pooled-event sensitivity, and frequency/uniform references.

**Output, result, status.** Across **3,384 recorded and 3,382 scored events**, the earlier rich-depth breakout advantage disappeared. Equal-day breakout losses were **C 0.28486, P 0.28604, R 0.28804, frequency 0.28771**; pooled, every learned arm lost to frequency. Rebound frequency also won both aggregates. This is a valid temporal negative, not proof that depth has no information.

### E262 -- mandatory participant checkpoint

**Idea, input, method.** E262 was intended to perform a bounded follow-up on participant holdings, supplying the participant-linked checkpoint that sampled aggregate books cannot provide.

**Output, result, status.** The experiment was cancelled before execution. It produced no result and must not appear as a failed hypothesis test. Its value is bookkeeping: the missing participant-evidence dependency remains explicit.

### E263 -- contribution triage across the remaining architecture

**Idea, input, method.** E263 challenged three residual paper directions: robustness to known observation operators, constrained valid-path generation, and selective risk/fallback. It compared each proposed mechanism with close primary prior art and used accepted E261 outputs for bounded arithmetic stress tests, without new model fitting.

**Output, result, status.** All three candidates were rejected as current paper contributions because none supplied a distinct algorithm, theorem, or established empirical phenomenon beyond existing work. The negative is valid and useful: the mechanisms may remain engineering components, but they should not be sold as the ICLR contribution without a new discriminator.

### E264 -- fixed-output diagnosis of reconstruction and prediction

**Idea, input, method.** E264 read only frozen May-November predictions and labels, using zero fits or new inference, to separate changes in class mixture from changes in class-conditional model loss. It retained **4,790 scored events** and the original earlier/later weighting schemes.

**Output, result, status.** Breakout R-minus-C changed from **-0.014638** in May-July to **+0.003179** in August-November under equal-day weighting; after fixed-class-mixture standardization it still changed from **-0.011565 to +0.009808**. Class composition explains much of R's absolute loss change, but less of its deterioration relative to C; the comparative reversal is mainly class-conditional. This is a valid diagnosis, not a causal explanation.

## Source closure, persistence, and the next decision

### E265 -- recover and admit real Hyperliquid inputs

**Idea, input, method.** E265 searched retained holdings for exact source contracts that could be admitted without silently changing the Q16-Q18 protocols. It bound hashes, clocks, segment rules, consumer protocols, and provider limitations before any fitted result could count.

**Output, result, status.** The source gate admitted an **18-contract Q18** sampled-L2 subset and a **30-contract Q17** native-BBO subset; the broader packet contained 58 contracts including the already reviewed Q18 subset. No qualified Q16 order-level source was found. This is a partial source result: it enables Q17/Q18 and documents why Q16 remains blocked, but it is not itself a model finding.

### E269 -- prospective fixed-model persistence preparation

**Idea, input, method.** E269 froze a rule to select the earliest retained full-day BTC sampled-L2 date after 1 November 2025, preserving prior exclusions and fixed E259/E261 models. It inspected only the bounded retained catalogue and metadata, without opening outcomes or fitting anything.

**Output, result, status.** The inventory contained **12 acquisition day indexes and 11 normalized BTC dates**, but no eligible retained date under the rule; January 2026 had a known inversion and the December dates were already excluded. No source, labels, predictions, or scores were selected. This is valid preparation/source-feasibility evidence, not a negative persistence result.

### E270 -- one declared BTC persistence source

**Idea, input, method.** E270 supplied a separately declared source after E269's null selection: the retained Hyperliquid BTC sampled-L2 day **1 February 2026**, with exact bytes, event-time consumer rules, gaps, freshness, and prior-exposure qualifications.

**Output, result, status.** The day was accepted only as a source for the unchanged persistence protocol. It does not establish receipt-time availability, exchange completeness, native L4/FIFO, or an untouched holdout. This is a valid source-only result; scientific scoring occurs in E271.

### E271 -- fixed-model persistence on one admitted BTC day

**Idea, input, method.** E271 applied the frozen C/P/R models to the admitted 1 February 2026 day with zero refits. The strict breakout claim required R-minus-C loss to be positive in three views: raw events, a fixed training-class mixture, and favorable-class events.

**Output, result, status.** All components were evaluable over **880 breakout** and **865 rebound** events. Breakout R-minus-C was **+0.000582 raw**, **-0.013367 under the frozen class mixture**, and **+0.016674 given favorable events**. The negative middle component contradicts the strict conjunction. This is a complete scoped scientific negative for that day, not a population test or profit claim.

### E272 -- information-value estimand and discriminating next test

**Idea, input, method.** E272 proposed a conditional frozen-score estimand to separate information value from model/reconstruction quality and designed the smallest next test that could distinguish the remaining claims.

**Output, result, status.** No empirical run was authorized or performed. The analytical packet argues for a scoped no-go on an immediate real-data information claim, but its exact identities and source attribution were still awaiting review at revision 187. It is a review-pending design, not accepted evidence.

### E273 -- BTC unknown-initial-book washout mini-experiment

**Idea, input, method.** E273 replayed real December BTC order diffs from an empty book. A first-seen `new` order was known from birth; an order first seen through `update` or `remove` was treated as inherited from the unknown initial state. The planned decision required 24 hours of warm-up followed by 24 hours with no newly revealed inherited orders.

**Output, result, status.** The independently reviewed prefix processed **11 complete hours and 32,633,820 events**, discovering **11,328 inherited order IDs**; **148** were still first revealed in the eleventh hour. Among all IDs that appeared, observed-lifecycle coverage reached **99.929849%**, with zero transition anomalies, but the true fraction of the full live book known is unidentifiable. The 48-hour decision was not reached. This is valid real-data prefix evidence and an inconclusive experiment, not a pass or failure of the washout hypothesis.

## Cross-experiment interpretation

Five patterns survive the individual qualifications. First, better intermediate reconstruction or forecast scores do not automatically improve the decision that matters: Q17, E258, and the BTC strategy chain all show why the downstream comparator must be explicit. Second, hidden queue uncertainty can be decision-relevant even when exact hidden-state recovery is impossible; E205/E256 establish the ambiguity and E258 shows that direct prediction can preserve the relevant uncertainty. Third, strong-looking development gains are fragile: E259's rich-depth breakout result reversed in E261 and stayed reversed after E264's class-mix control. Fourth, valid negative results are productive: Q17, Q18, E260, E261, E263, and E271 eliminate specific claims without implying universal impossibility. Fifth, validity engineering is part of the science: Q16 remains open because the required source was not admitted, while E273 remains inconclusive because the planned horizon was not completed.

The current evidence therefore favors a paper framed around **when richer information changes a decision under matched direct controls**, rather than around reconstruction quality alone. A credible next empirical contribution needs a newly admitted information channel, a predeclared decision estimand, matched supervision/compute, and an evaluation period that is both chronologically supported and not selected from its outcomes.

## Artifact map

| Package path | State evidence |
|---|---|
| `experiments/e001-btc-data-provenance-schema-timing-and-replay-audit/` | R001 / RV001 |
| `experiments/e016-q16-real-data/` | R006, R013, R015, R016, R035, R039 |
| `experiments/e017-q17-real-data/` | R007, R011, R018, R037 / RV036 |
| `experiments/e018-q18-real-data/` | R008, R010, R017, R019, R036 / RV034 |
| `experiments/e002-existing-hour-clock-anchor-feasibility-diagnostic/` | R003 / RV002 |
| `experiments/e200-causal-event-clock-and-availability-certificate/` | R005, R012 |
| `experiments/e201-initial-state-and-historical-matching-rule-certificate/` | R005, R012 |
| `experiments/e202-chronological-day-blocks-and-data-budget-feasibility/` | R005, R012 |
| `experiments/e203-paired-causal-coarse-rich-observation-contract/` | R005, R012 |
| `experiments/e204-observed-order-labels-and-execution-model-feasibility/` | R005, R012 |
| `experiments/e205-simulator-selection-and-mechanism-validation/` | R009, R024 / RV022 |
| `experiments/e210-controlled-simulation-of-action-relevant-ambiguity/` | R009, R014 |
| `experiments/e253-breakout-rebound-protocol-and-claim-specific-feasibility/` | R023 / RV021 |
| `experiments/e254-shared-computation-concrete-algorithm-or-matched-method-identity/` | R022 / RV020 |
| `experiments/e255-label-blind-breakout-rebound-extraction-audit/` | R025 / RV023 |
| `experiments/e256-restricted-simulator-repair-and-delivered-feed-validation/` | R026 / RV024 |
| `experiments/e257-fixed-labels-and-seven-date-btc-development-cohort-audit/` | R027 / RV025 |
| `experiments/e258-controlled-fill-prediction-point-versus-distributional-reconstruction/` | R028 / RV026 |
| `experiments/e259-frozen39-fit-btc-coarse-predicted-rich-development-comparison/` | R029 / RV027 |
| `experiments/e260-rich-label-adaptation-novelty-and-identifiability-challenge/` | R030 / RV028 |
| `experiments/e261-fixed-model-btc-august-november-temporal-evaluation/` | R031 / RV029 |
| `experiments/e262-mandatory-participant-checkpoint-bounded-holdings-follow-up/` | No result; cancelled |
| `experiments/e263-contribution-triage-across-the-remaining-architecture/` | R033 / RV031 |
| `experiments/e264-fixed-output-diagnosis-of-reconstruction-and-prediction/` | R034 / RV032 |
| `experiments/e265-recover-and-admit-real-hyperliquid-inputs/` | R032, R038 / RV030, RV035 |
| `experiments/e269-prepare-one-prospective-fixed-model-persistence-check/` | R040 / RV038 |
| `experiments/e270-supply-one-declared-btc-persistence-source/` | R041 / RV039 |
| `experiments/e271-fixed-model-persistence-on-one-admitted-btc-day/` | R042 / RV040 |
| `experiments/e272-information-value-estimand-and-discriminating-next-test/` | R043 / RV041 pending |
| `experiments/e273-btc-unknown-initial-book-washout-mini-experiment/` | R044 / RV042 |

## Evidence boundary

This report is a narrative index of revision 187, not a replacement for the package manifests. Numbers are drawn from accepted or explicitly pending state records and their frozen reports. "Hyperliquid" identifies the declared source/adaptation; provider archives are not independently attested exchange histories, and project shorthand "L4" is not a universal market-data standard. Raw dumps, private manuscripts, messaging receipts, and internal coordinator state are intentionally outside the curated repository.
