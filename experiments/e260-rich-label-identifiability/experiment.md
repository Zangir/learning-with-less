# Rich-label adaptation novelty and identifiability challenge

**State experiments:** E-260  
**Execution status:** completed  
**Scientific assessment:** valid

## Research question

- **Q-002:** When does inference of hidden order structure improve decisions over strong direct prediction and privileged-information training?
- **Q-003:** Which properties of observation coarsening and hidden-state ambiguity govern decision value?
- **Q-023:** Which missing components explain the gap between restored and true-rich decisions?

## Hypothesis

- No separate hypothesis was registered for this package.

## Input

Accepted controlled and BTC comparison outputs plus the tested rich-label reconstruction candidate.

## Method

Check whether reconstruction contributes beyond an equally informed direct predictor and whether the candidate is scientifically distinct.

## Output

No distinct advantage over matched direct prediction was found for the tested candidate.

## Findings

- **R-030:** Reviewed R030/RV028: the tested rich-label reconstruction candidate has no distinct advantage over equally informed direct prediction. Information acquisition remains a conditional question. Next: triage genuinely different candidates in the remaining architecture; no new model fits.

## Status

The canonical state assessment is **valid** with execution status **completed**. The headline package conclusion is: No distinct advantage over matched direct prediction was found for the tested candidate.

## Limitations

The negative is candidate-specific; the value of acquiring richer labels remains conditional.

## Reproduction

Prepare the non-committed data described in `provenance.json`, use the package `run.py` and frozen `config/` when present, then compare the generated compact outputs with `results/summary.json`. Historical branch and commit bindings are recorded in `provenance.json`; raw market data are intentionally excluded.

## Included artifacts

- [result-paper.pdf](result-paper.pdf) — 261,835 bytes, SHA-256 `d6e75c9d47d411a784acadeaf2527b5c69864842cc6c2adadcae1029264c8a2e`
- [figures/main.png](figures/main.png) — 128,857 bytes, SHA-256 `99ab92913137042f758470939a0f180588c8ad1c33189d9573c264cbafecc9c4`
- [interactive-explanation.html](interactive-explanation.html) — 4,319,225 bytes, SHA-256 `e1879cac11e21e242e4833bb7c304c2ae0929f613c1ca491aab74b45fac2fe48`
- [results/exact-checks.json](results/exact-checks.json) — 3,467 bytes, SHA-256 `d793a3dc2b778549af56a10a6e20d168c6ee208b19dcfd46a3860015e7befeb1`
- [results/figure-data.json](results/figure-data.json) — 5,101 bytes, SHA-256 `13ae2323ee8bfc22be4f58d0984cd4d401a945a0995cacd5faaf3e5df4639fe6`

Machine-readable state-derived findings are in [results/summary.json](results/summary.json), and sanitized source bindings plus artifact hashes are in [provenance.json](provenance.json).
