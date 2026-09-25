# Initial-state and matching-rule certificate

**State experiments:** E-201  
**Execution status:** running  
**Scientific assessment:** valid_in_limited_scope_broader_objective_open

## Research question

- **Q-001:** Do the Q16-Q18 findings survive protocol-documented transfer to real Hyperliquid observations?

## Hypothesis

- No separate hypothesis was registered for this package.

## Input

Bounded replay fixtures and sampled historical states with known missing initial-book context.

## Method

Test whether replay and matching assumptions are sufficient to initialize queue state without inventing unseen orders.

## Output

The audit reproduced unmatched decrements and documented conditional reconstruction routes; native FIFO was not admitted.

## Findings

- **R-005:** Independent review reproduced eight unmatched decrements, trigger-aware prefix ordering and inherited/zero-size lifecycle limitations; no real window certified.
- **R-012:** Reviewed historical and live sampled-state routes supported; December1 reconstruction conditional and Q16 inventory unadmitted for native FIFO/counterfactual execution.

## Status

The canonical state assessment is **valid_in_limited_scope_broader_objective_open** with execution status **running**. The headline package conclusion is: The audit reproduced unmatched decrements and documented conditional reconstruction routes; native FIFO was not admitted.

## Limitations

Unknown initial state and undocumented venue matching behavior block counterfactual execution claims.

## Reproduction

Prepare the non-committed data described in `provenance.json`, use the package `run.py` and frozen `config/` when present, then compare the generated compact outputs with `results/summary.json`. Historical branch and commit bindings are recorded in `provenance.json`; raw market data are intentionally excluded.

## Included artifacts

- No historical explanation or compact final artifact was available; none was generated retroactively.

Machine-readable state-derived findings are in [results/summary.json](results/summary.json), and sanitized source bindings plus artifact hashes are in [provenance.json](provenance.json).
