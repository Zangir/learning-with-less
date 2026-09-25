# Fixed-model BTC August-November evaluation

**State experiments:** E-261  
**Execution status:** completed  
**Scientific assessment:** valid

## Research question

- **Q-019:** Do richer-data adaptations of available MegaProp strategies retain value with restored inputs?

## Hypothesis

- No separate hypothesis was registered for this package.

## Input

Frozen models from the development stage evaluated without refitting on four retained BTC dates from August through November.

## Method

Apply fixed models and event/equal-date aggregation to test temporal persistence of the earlier development result.

## Output

The earlier aggregate rich-depth breakout advantage disappeared; learned breakout arms lost to frequency under event weighting, and rebound frequency won both aggregates.

## Findings

- **R-031:** Reviewed R031/RV029: fixed BTC models lose the earlier aggregate rich-depth breakout advantage on August-November dates. All learned breakout arms lose to frequency under event weighting; rebound frequency wins both aggregates. Next: diagnose class mix and conditional loss using existing predictions, with zero new fits.

## Status

The canonical state assessment is **valid** with execution status **completed**. The headline package conclusion is: The earlier aggregate rich-depth breakout advantage disappeared; learned breakout arms lost to frequency under event weighting, and rebound frequency won both aggregates.

## Limitations

The dates were not a pristine prospective holdout and the result does not establish a general market law.

## Reproduction

Prepare the non-committed data described in `provenance.json`, use the package `run.py` and frozen `config/` when present, then compare the generated compact outputs with `results/summary.json`. Historical branch and commit bindings are recorded in `provenance.json`; raw market data are intentionally excluded.

## Included artifacts

- [result-paper.pdf](result-paper.pdf) — 320,593 bytes, SHA-256 `f175490e8030511d6d132794212e7d541f6b525f299c326d1ff5840cdc5cc1cc`
- [figures/main.png](figures/main.png) — 148,426 bytes, SHA-256 `5e9aecf84b7a0626f86f261264833f069a405de48fe2f22ec6361759ef416038`
- [interactive-explanation.html](interactive-explanation.html) — 16,130 bytes, SHA-256 `6b52a725a75a89e45fe996ccfeabb1b638f4292f64a6ffb3546b80429aa2150e`
- [results/interpretation.json](results/interpretation.json) — 5,989 bytes, SHA-256 `6fab8056b52642558dba9b79b0af8ee0b6ba93c1a216bb9c0b7806b3841d365f`

Machine-readable state-derived findings are in [results/summary.json](results/summary.json), and sanitized source bindings plus artifact hashes are in [provenance.json](provenance.json).
