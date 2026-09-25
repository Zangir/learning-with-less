# Fixed-model persistence on one admitted BTC day

**State experiments:** E-271  
**Execution status:** completed  
**Scientific assessment:** valid_scoped_contradiction

## Research question

- **Q-019:** Do richer-data adaptations of available MegaProp strategies retain value with restored inputs?

## Hypothesis

- No separate hypothesis was registered for this package.

## Input

The admitted BTC 2026-02-01 source and previously frozen breakout/rebound models, with zero new fits.

## Method

Evaluate raw, fixed-class, and favorable-class contrasts plus constant-action baselines on the admitted day.

## Output

The strict joint persistence condition was contradicted: raw and favorable-class contrasts were positive, fixed-class contrast was -0.01337, and uniform beat every learned breakout arm on observed-event loss.

## Findings

- **R-042:** The strict joint breakout persistence condition is contradicted on BTC2026-02-01 because the fixed-class contrast is negative while raw and favorable-class contrasts are positive. Uniform beats all learned breakout arms on observed-event loss; no general information-value or deployment conclusion.

## Status

The canonical state assessment is **valid_scoped_contradiction** with execution status **completed**. The headline package conclusion is: The strict joint persistence condition was contradicted: raw and favorable-class contrasts were positive, fixed-class contrast was -0.01337, and uniform beat every learned breakout arm on observed-event loss.

## Limitations

This is one source-exposed day without significance, calibrated latency, profit, or population-persistence claims.

## Reproduction

Prepare the non-committed data described in `provenance.json`, use the package `run.py` and frozen `config/` when present, then compare the generated compact outputs with `results/summary.json`. Historical branch and commit bindings are recorded in `provenance.json`; raw market data are intentionally excluded.

## Included artifacts

- [result-paper.pdf](result-paper.pdf) — 151,755 bytes, SHA-256 `d5459d269d6ab560a0588fc20bfff1a0dfa44712d81d403596bb9419baf51fb8`
- [figures/main.png](figures/main.png) — 221,846 bytes, SHA-256 `69a2d39b5de5333db0a3b7f211939c7537187d7b6e1b6c3e41ce4da1bb6e0d5c`
- [results/main-plot-data.csv](results/main-plot-data.csv) — 11,713 bytes, SHA-256 `b1ef81a12ea0e2b111593b2466fed09b178b6187437037458e87fff9d1d08e1f`
- [results/evaluation.json](results/evaluation.json) — 90,470 bytes, SHA-256 `160d4526dcd95865b21fbc8c518598c3a46772a787a6328c4e31f2d68e7e15a6`

Machine-readable state-derived findings are in [results/summary.json](results/summary.json), and sanitized source bindings plus artifact hashes are in [provenance.json](provenance.json).
