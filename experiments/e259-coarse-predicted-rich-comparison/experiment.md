# BTC coarse, predicted-rich, and observed-rich development comparison

**State experiments:** E-259  
**Execution status:** completed  
**Scientific assessment:** valid

## Research question

- **Q-019:** Do richer-data adaptations of available MegaProp strategies retain value with restored inputs?

## Hypothesis

- No separate hypothesis was registered for this package.

## Input

The frozen 39-fit development panel over three exposed BTC evaluation dates.

## Method

Compare coarse, predicted-depth, and observed-depth inputs for breakout and rebound decisions under fixed model families.

## Output

Observed depth improved the fitted coarse breakout arm on all three dates; every learned rebound arm lost to the frequency baseline.

## Findings

- **R-029:** Reviewed BTC result: observed depth improves the fitted coarse breakout arm on all three exposed dates. Every learned rebound arm loses to the training-frequency baseline. Learned summaries provide smaller, aggregation-sensitive gains. Next: zero-fit evaluation of the fixed selected models on all four retained August–November dates, with prior exposure disclosed.

## Status

The canonical state assessment is **valid** with execution status **completed**. The headline package conclusion is: Observed depth improved the fitted coarse breakout arm on all three dates; every learned rebound arm lost to the frequency baseline.

## Limitations

The dates were development-exposed, gains were aggregation-sensitive, and the result was descriptive.

## Reproduction

Prepare the non-committed data described in `provenance.json`, use the package `run.py` and frozen `config/` when present, then compare the generated compact outputs with `results/summary.json`. Historical branch and commit bindings are recorded in `provenance.json`; raw market data are intentionally excluded.

## Included artifacts

- [result-paper.pdf](result-paper.pdf) — 315,701 bytes, SHA-256 `384f47ccdc2215cb5bd86a1d8a04274387ce1c926deac0d95b3500bd57e46e85`
- [figures/main.png](figures/main.png) — 129,363 bytes, SHA-256 `c812eb57b27bb912b5d0e1d3bc380061af4ce63cb9e2a5cba27ef3da647b1365`
- [interactive-explanation.html](interactive-explanation.html) — 13,674 bytes, SHA-256 `04ed7fb2aa3d9aea2c158c5ef9174cc2653bfeb25d73624bb221cd7053868989`
- [results/stage-summary.json](results/stage-summary.json) — 4,034 bytes, SHA-256 `6e82713a4c4fbf4a20d388934154f10cf5424a92c2a8419c5feb0df2b092eba3`
- [results/paired-results.json](results/paired-results.json) — 5,037 bytes, SHA-256 `5280d6ba1914f546b8c675bc5d34cf1c23408fc15aa8c7f65ad362e0d5ca7a3d`

Machine-readable state-derived findings are in [results/summary.json](results/summary.json), and sanitized source bindings plus artifact hashes are in [provenance.json](provenance.json).
