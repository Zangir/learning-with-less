# Controlled action-relevant ambiguity simulation

**State experiments:** E-210  
**Execution status:** completed  
**Scientific assessment:** valid_in_controlled_synthetic_scope

## Research question

- **Q-009:** Does action-relevant hidden ambiguity predict when restoration can help in simulation?

## Hypothesis

- **H-010:** At matched observable distributions and latent reconstruction difficulty, increasing ambiguity that changes the preferred action increases the advantage of distributional restoration; increasing decision-irrelevant ambiguity does not.

## Input

Synthetic populations with matched observables, controlled latent ambiguity, and fixed decision losses.

## Method

Compare direct, point-restoration, and posterior/distributional decisions while separating action-relevant from irrelevant ambiguity.

## Output

Restricted summaries incurred 0.075 regret, but matched direct and posterior coordinates were equal; no restoration-specific advantage was isolated.

## Findings

- **R-009:** Calibrated binary mean equals posterior decision control; noisy-label finite-sample gain is known-noise denoising.
- **R-014:** Author reports matched direct/posterior coordinate equality; restricted-summary regret.075 and correct-symmetry sample-efficiency gains; no restoration-specific benefit.

## Status

The canonical state assessment is **valid_in_controlled_synthetic_scope** with execution status **completed**. The headline package conclusion is: Restricted summaries incurred 0.075 regret, but matched direct and posterior coordinates were equal; no restoration-specific advantage was isolated.

## Limitations

The evidence is synthetic and mechanism-specific, and the broader ambiguity hypothesis remains inconclusive.

## Reproduction

Prepare the non-committed data described in `provenance.json`, use the package `run.py` and frozen `config/` when present, then compare the generated compact outputs with `results/summary.json`. Historical branch and commit bindings are recorded in `provenance.json`; raw market data are intentionally excluded.

## Included artifacts

- [result-paper.pdf](result-paper.pdf) — 589,681 bytes, SHA-256 `08f1775b311f0f4aa9d5451df58380d57511f7e2644e9c74edd54eae82961eb5`
- [figures/main.png](figures/main.png) — 354,513 bytes, SHA-256 `6d74877da3ff78c688bc0ec031b7f506242554ddb8f3cf1b618a5382ed6b83eb`
- [interactive-explanation.html](interactive-explanation.html) — 4,306,695 bytes, SHA-256 `7152a9e9fa066033f4cbabba64b4105f441b0861ca62d6e33a5a23deb45f46f3`
- [results/finite-summary.csv](results/finite-summary.csv) — 1,356 bytes, SHA-256 `82ecf45ed2a790b8436f184ba4c68792c5825c7e7edbdce3380c14a4f63ded72`
- [results/paired-differences.csv](results/paired-differences.csv) — 980 bytes, SHA-256 `bc15ed70048c44fe9507a03ac1aaf31f8ac594f885d937b54f1277be7689a54a`

Machine-readable state-derived findings are in [results/summary.json](results/summary.json), and sanitized source bindings plus artifact hashes are in [provenance.json](provenance.json).
