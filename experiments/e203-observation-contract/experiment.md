# Paired causal coarse/rich observation contract

**State experiments:** E-203  
**Execution status:** running  
**Scientific assessment:** valid_in_limited_scope_broader_objective_open

## Research question

- **Q-006:** Which genuinely richer components improve which downstream decisions?
- **Q-007:** Does an explicit observation operator improve restoration under changing feed resolution?

## Hypothesis

- No separate hypothesis was registered for this package.

## Input

Candidate coarse and rich views derived from the same bounded event sources.

## Method

Define and audit a paired observation contract so every coarse/rich comparison uses causally aligned rows.

## Output

A limited contract path was documented, but no broad real window was certified for a final comparison.

## Findings

- **R-005:** Independent review reproduced eight unmatched decrements, trigger-aware prefix ordering and inherited/zero-size lifecycle limitations; no real window certified.
- **R-012:** Reviewed historical and live sampled-state routes supported; December1 reconstruction conditional and Q16 inventory unadmitted for native FIFO/counterfactual execution.

## Status

The canonical state assessment is **valid_in_limited_scope_broader_objective_open** with execution status **running**. The headline package conclusion is: A limited contract path was documented, but no broad real window was certified for a final comparison.

## Limitations

The contract inherits source-clock, initial-state, and completeness limitations.

## Reproduction

Prepare the non-committed data described in `provenance.json`, use the package `run.py` and frozen `config/` when present, then compare the generated compact outputs with `results/summary.json`. Historical branch and commit bindings are recorded in `provenance.json`; raw market data are intentionally excluded.

## Included artifacts

- No historical explanation or compact final artifact was available; none was generated retroactively.

Machine-readable state-derived findings are in [results/summary.json](results/summary.json), and sanitized source bindings plus artifact hashes are in [provenance.json](provenance.json).
