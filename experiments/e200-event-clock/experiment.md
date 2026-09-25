# Causal event-clock and availability certificate

**State experiments:** E-200  
**Execution status:** running  
**Scientific assessment:** valid_in_limited_scope_broader_objective_open

## Research question

- **Q-001:** Do the Q16-Q18 findings survive protocol-documented transfer to real Hyperliquid observations?

## Hypothesis

- No separate hypothesis was registered for this package.

## Input

Historical and live sampled-state routes plus bounded decrement and prefix-ordering fixtures.

## Method

Audit event-clock ordering, trigger-aware prefixes, and availability boundaries before downstream labels are formed.

## Output

Limited clock and ordering behavior was reproduced, but no full real evaluation window was certified.

## Findings

- **R-005:** Independent review reproduced eight unmatched decrements, trigger-aware prefix ordering and inherited/zero-size lifecycle limitations; no real window certified.
- **R-012:** Reviewed historical and live sampled-state routes supported; December1 reconstruction conditional and Q16 inventory unadmitted for native FIFO/counterfactual execution.

## Status

The canonical state assessment is **valid_in_limited_scope_broader_objective_open** with execution status **running**. The headline package conclusion is: Limited clock and ordering behavior was reproduced, but no full real evaluation window was certified.

## Limitations

Inherited orders, zero-size lifecycle semantics, and exchange completeness remain unresolved.

## Reproduction

Prepare the non-committed data described in `provenance.json`, use the package `run.py` and frozen `config/` when present, then compare the generated compact outputs with `results/summary.json`. Historical branch and commit bindings are recorded in `provenance.json`; raw market data are intentionally excluded.

## Included artifacts

- No historical explanation or compact final artifact was available; none was generated retroactively.

Machine-readable state-derived findings are in [results/summary.json](results/summary.json), and sanitized source bindings plus artifact hashes are in [provenance.json](provenance.json).
