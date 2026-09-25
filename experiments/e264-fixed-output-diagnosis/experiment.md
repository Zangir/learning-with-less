# Fixed-output diagnosis of reconstruction and prediction

**State experiments:** E-264  
**Execution status:** completed  
**Scientific assessment:** valid

## Research question

- **Q-019:** Do richer-data adaptations of available MegaProp strategies retain value with restored inputs?

## Hypothesis

- No separate hypothesis was registered for this package.

## Input

Saved predictions and outcomes from the fixed BTC models; no new fits.

## Method

Decompose class mix, conditional loss, weighting, and auxiliary relationships to explain the temporal reversal.

## Output

The descriptive diagnosis was accepted and localized how aggregation and class mix affected the apparent benefit.

## Findings

- **R-034:** valid_descriptive_diagnosis

## Status

The canonical state assessment is **valid** with execution status **completed**. The headline package conclusion is: The descriptive diagnosis was accepted and localized how aggregation and class mix affected the apparent benefit.

## Limitations

It is post hoc, uses previously exposed outputs, and does not establish causality.

## Reproduction

Prepare the non-committed data described in `provenance.json`, use the package `run.py` and frozen `config/` when present, then compare the generated compact outputs with `results/summary.json`. Historical branch and commit bindings are recorded in `provenance.json`; raw market data are intentionally excluded.

## Included artifacts

- [figures/main.png](figures/main.png) ? 111,975 bytes, SHA-256 `80c90968f351d2550dbefe62bcf7d7af4bc10ba22cae9be922b373178cb9fe87`
- [interactive-explanation.html](interactive-explanation.html) ? 64,517 bytes, SHA-256 `459fb31ab857568b68035089f363bf82fa4d19b6c32515e79f8022ae86941aae`
- [result-paper.pdf](result-paper.pdf) ? 446,023 bytes, SHA-256 `fc37e21b4a6f201c5a0709a67d40699bbe91ba98d60767dc6664775a13919b9b`
- [results/decompositions.csv](results/decompositions.csv) ? 13,422 bytes, SHA-256 `271cc34c4e5e0de84fd9110fab1594ccaf39a0239991555d106e7f821b4ee9dd`
- [results/figure-source.json](results/figure-source.json) ? 610,068 bytes, SHA-256 `e94e7b1f7363f505949d1834a75fec272e3799f1cbb9cf17a02039af98f64476`
- [results/group-metrics.csv](results/group-metrics.csv) ? 23,241 bytes, SHA-256 `5e598a5104fef5951c64c349b4eb3abbf0c91e3230ec65f39982b29ee39b74ee`

Machine-readable state-derived findings are in [results/summary.json](results/summary.json), and sanitized source bindings plus artifact hashes are in [provenance.json](provenance.json).
