# Fixed labels and seven-date BTC development cohort

**State experiments:** E-257  
**Execution status:** completed  
**Scientific assessment:** valid

## Research question

- **Q-019:** Do richer-data adaptations of available MegaProp strategies retain value with restored inputs?

## Hypothesis

- No separate hypothesis was registered for this package.

## Input

Seven fixed BTC dates and prospectively defined breakout/rebound opportunity and censoring rules.

## Method

Extract events, apply fixed outcome labels, build matched feature views, and audit all cohort counts without fitting strategy models.

## Output

4,160 opportunities yielded 4,139 sampled labels and 21 censored events.

## Findings

- **R-027:** P1 data-readiness accepted:4160 BTC opportunities yield4139 sampled outcome labels and21 censored events. Independent review reproduced source, events, labels and matched features. Counts are not strategy performance. Next: exactly39 frozen development fits comparing coarse, predicted-depth and true-depth inputs; three exposed evaluation dates support descriptive results only.

## Status

The canonical state assessment is **valid** with execution status **completed**. The headline package conclusion is: 4,160 opportunities yielded 4,139 sampled labels and 21 censored events.

## Limitations

Counts establish data readiness only; three evaluation dates were already exposed and do not support pristine holdout claims.

## Reproduction

Prepare the non-committed data described in `provenance.json`, use the package `run.py` and frozen `config/` when present, then compare the generated compact outputs with `results/summary.json`. Historical branch and commit bindings are recorded in `provenance.json`; raw market data are intentionally excluded.

## Included artifacts

- [figures/main.png](figures/main.png) ? 125,841 bytes, SHA-256 `e010a12541172039375da2d9af54c5adbe99d438f01e24eb8e244530705fec33`
- [interactive-explanation.html](interactive-explanation.html) ? 338 bytes, SHA-256 `8c6609fca03035dc3cd1fa8dfe2a126a0a959983b38c3c915212001b2f0e81cd`
- [result-paper.pdf](result-paper.pdf) ? 228,492 bytes, SHA-256 `9146c238843415a4e4e113a5edeb99e3ffbf22fb3f6745d808d032f5a99916fb`
- [results/cohort-summary.json](results/cohort-summary.json) ? 39,576 bytes, SHA-256 `822a456cc86b91c05f650b7d4ec1db2b327e46b14bf7106b5332e1bff77b1987`

Machine-readable state-derived findings are in [results/summary.json](results/summary.json), and sanitized source bindings plus artifact hashes are in [provenance.json](provenance.json).
