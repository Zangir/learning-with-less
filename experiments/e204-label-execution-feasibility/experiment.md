# Observed-order labels and execution-model feasibility

**State experiments:** E-204  
**Execution status:** running  
**Scientific assessment:** valid_in_limited_scope_broader_objective_open

## Research question

- **Q-017:** Does restored queue uncertainty improve calibrated fill and cancellation predictions?
- **Q-019:** Do richer-data adaptations of available MegaProp strategies retain value with restored inputs?
- **Q-020:** Does restoration help an adverse-selection decision beyond improving fill prediction?

## Hypothesis

- No separate hypothesis was registered for this package.

## Input

Bounded lifecycle events, observed decrements, and candidate execution labels from sampled-state routes.

## Method

Audit whether observed events support fill/cancellation labels and counterfactual execution without adding unobserved queue facts.

## Output

Observed-order feasibility was supported only in a limited route; native FIFO and counterfactual execution were not admitted.

## Findings

- **R-005:** Independent review reproduced eight unmatched decrements, trigger-aware prefix ordering and inherited/zero-size lifecycle limitations; no real window certified.
- **R-012:** Reviewed historical and live sampled-state routes supported; December1 reconstruction conditional and Q16 inventory unadmitted for native FIFO/counterfactual execution.

## Status

The canonical state assessment is **valid_in_limited_scope_broader_objective_open** with execution status **running**. The headline package conclusion is: Observed-order feasibility was supported only in a limited route; native FIFO and counterfactual execution were not admitted.

## Limitations

Sampled states cannot identify every hidden order lifecycle or venue matching rule.

## Reproduction

Prepare the non-committed data described in `provenance.json`, use the package `run.py` and frozen `config/` when present, then compare the generated compact outputs with `results/summary.json`. Historical branch and commit bindings are recorded in `provenance.json`; raw market data are intentionally excluded.

## Included artifacts

- No historical explanation or compact final artifact was available; none was generated retroactively.

Machine-readable state-derived findings are in [results/summary.json](results/summary.json), and sanitized source bindings plus artifact hashes are in [provenance.json](provenance.json).
