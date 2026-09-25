# Label-blind breakout/rebound extraction audit

**State experiments:** E-255  
**Execution status:** completed  
**Scientific assessment:** valid

## Research question

- **Q-019:** Do richer-data adaptations of available MegaProp strategies retain value with restored inputs?

## Hypothesis

- No separate hypothesis was registered for this package.

## Input

One fixed source hour containing 24 raw event candidates.

## Method

Apply the frozen label-blind extractor and audit source bounds, causal prefixes, exclusions, and deterministic replay.

## Output

Twenty-one recorded events remained from 24 raw candidates. No labels were fit and no performance claim was made.

## Findings

- **R-025:** Author reports21 recorded events from24 raw candidates in one fixed hour; deterministic freeze, source bounds and causal prefix checks await independent review. No labels, fitting or performance claims.

## Status

The canonical state assessment is **valid** with execution status **completed**. The headline package conclusion is: Twenty-one recorded events remained from 24 raw candidates. No labels were fit and no performance claim was made.

## Limitations

One hour is a bounded feasibility check and cannot establish event prevalence or strategy quality.

## Reproduction

Prepare the non-committed data described in `provenance.json`, use the package `run.py` and frozen `config/` when present, then compare the generated compact outputs with `results/summary.json`. Historical branch and commit bindings are recorded in `provenance.json`; raw market data are intentionally excluded.

## Included artifacts

- [figures/main.png](figures/main.png) ? 111,275 bytes, SHA-256 `e9caed4a85c89d5de7dcb72fea3383b3857f95ae7b0e0637e1106fd7512b3492`
- [interactive-explanation.html](interactive-explanation.html) ? 374 bytes, SHA-256 `49716d40911ea6e69868e89881685ff7f7197a22a436e632e3579a8af74ec91a`
- [result-paper.pdf](result-paper.pdf) ? 206,949 bytes, SHA-256 `871547d0bb8a24ab6c5dc8a67426aa98d2bfc4ef1b4f26fb91ca69008ce0460c`
- [results/stage-summary.json](results/stage-summary.json) ? 1,459 bytes, SHA-256 `d7c3a3835bcb359fb486a29fe5a3bcd96c71f399efa3a9715a3191bf46724793`

Machine-readable state-derived findings are in [results/summary.json](results/summary.json), and sanitized source bindings plus artifact hashes are in [provenance.json](provenance.json).
