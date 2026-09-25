# Simulator selection and mechanism validation

**State experiments:** E-205  
**Execution status:** completed  
**Scientific assessment:** valid

## Research question

- **Q-009:** Does action-relevant hidden ambiguity predict when restoration can help in simulation?
- **Q-010:** Can simulation training reduce the real rich-label budget needed for useful restoration?
- **Q-018:** Can restored lifecycle patterns improve detection of controlled spoofing-like behaviour?

## Hypothesis

- No separate hypothesis was registered for this package.

## Input

Actual simulator-engine traces, paired rich/coarse episodes, and diagnostic modification/history cases.

## Method

Replay matched coarse paths under distinct hidden states and inspect whether native simulator behavior preserves the intended mechanism.

## Output

Matched coarse paths produced different probe fills, while native modification/history defects were identified and repaired in later work.

## Findings

- **R-009:** Calibrated binary mean equals posterior decision control; noisy-label finite-sample gain is known-noise denoising.
- **R-024:** Author reports reproducible actual-engine rich/coarse traces, matched coarse paths with differing probe fills, and native modification/history defects. Suitability and postflight evidence repair await independent review.

## Status

The canonical state assessment is **valid** with execution status **completed**. The headline package conclusion is: Matched coarse paths produced different probe fills, while native modification/history defects were identified and repaired in later work.

## Limitations

The result diagnoses simulator suitability; it is not a real-market profitability result.

## Reproduction

Prepare the non-committed data described in `provenance.json`, use the package `run.py` and frozen `config/` when present, then compare the generated compact outputs with `results/summary.json`. Historical branch and commit bindings are recorded in `provenance.json`; raw market data are intentionally excluded.

## Included artifacts

- [figures/main.png](figures/main.png) ? 202,500 bytes, SHA-256 `70b0c75141f98bfa63d0908ed5d69d6cd6d970b348da699fcb8b2b8151653b15`
- [interactive-explanation.html](interactive-explanation.html) ? 54,774 bytes, SHA-256 `5453428897a3ecfc3a6198f0a253e3a31942da862d79ed1086974bfd4df1d08b`
- [result-paper.pdf](result-paper.pdf) ? 472,548 bytes, SHA-256 `d4829b6b9a4c1e17f8b3dcf92c13f81e6c8584a7701ae33e32b1ebbe9b22016e`
- [results/stage-summary.json](results/stage-summary.json) ? 2,402 bytes, SHA-256 `305f0aefd1cb3c8053cd87a07bf90f08e712414d6d062d5aa68e4ec781dc137f`

Machine-readable state-derived findings are in [results/summary.json](results/summary.json), and sanitized source bindings plus artifact hashes are in [provenance.json](provenance.json).
