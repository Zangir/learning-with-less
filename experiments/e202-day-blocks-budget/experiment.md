# Chronological day blocks and data-budget feasibility

**State experiments:** E-202  
**Execution status:** running  
**Scientific assessment:** valid_in_limited_scope_broader_objective_open

## Research question

- **Q-001:** Do the Q16-Q18 findings survive protocol-documented transfer to real Hyperliquid observations?
- **Q-004:** Which conclusions survive chronological shifts, latency and compute-matched controls?

## Hypothesis

- No separate hypothesis was registered for this package.

## Input

Available historical/live source routes, chronological block metadata, and bounded acquisition constraints.

## Method

Check whether valid day blocks can be selected without crossing unsupported gaps and whether the planned data budget is feasible.

## Output

Historical and live routes were supported only in limited scope; the broader chronological objective remained open.

## Findings

- **R-005:** Independent review reproduced eight unmatched decrements, trigger-aware prefix ordering and inherited/zero-size lifecycle limitations; no real window certified.
- **R-012:** Reviewed historical and live sampled-state routes supported; December1 reconstruction conditional and Q16 inventory unadmitted for native FIFO/counterfactual execution.

## Status

The canonical state assessment is **valid_in_limited_scope_broader_objective_open** with execution status **running**. The headline package conclusion is: Historical and live routes were supported only in limited scope; the broader chronological objective remained open.

## Limitations

A feasible acquisition path does not itself certify source completeness, causal availability, or model validity.

## Reproduction

Prepare the non-committed data described in `provenance.json`, use the package `run.py` and frozen `config/` when present, then compare the generated compact outputs with `results/summary.json`. Historical branch and commit bindings are recorded in `provenance.json`; raw market data are intentionally excluded.

## Included artifacts

- No historical explanation or compact final artifact was available; none was generated retroactively.

Machine-readable state-derived findings are in [results/summary.json](results/summary.json), and sanitized source bindings plus artifact hashes are in [provenance.json](provenance.json).
