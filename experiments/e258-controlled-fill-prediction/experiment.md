# Fill prediction: point versus distributional reconstruction

**State experiments:** E-258  
**Execution status:** completed  
**Scientific assessment:** valid

## Research question

- **Q-009:** Does action-relevant hidden ambiguity predict when restoration can help in simulation?
- **Q-010:** Can simulation training reduce the real rich-label budget needed for useful restoration?
- **Q-018:** Can restored lifecycle patterns improve detection of controlled spoofing-like behaviour?

## Hypothesis

- No separate hypothesis was registered for this package.

## Input

Controlled hidden-queue episodes with informative and shifted conditions and fixed training sizes.

## Method

Compare direct prediction, point reconstruction, and uncertainty-preserving outputs under matched information and compute.

## Output

Hidden-queue uncertainty mattered, but reconstruction had no isolated advantage; at 512 draws direct and distribution-Y outputs coincided.

## Findings

- **R-028:** Reviewed controlled result: hidden-queue uncertainty matters, but reconstruction shows no isolated advantage over matched direct prediction. At512 training draws direct and distribution-Y outputs coincide. A conditional shift invisible in the observation marginal harms both. Next: prior-art and identifiability analysis of limited rich-label adaptation before another empirical sweep.

## Status

The canonical state assessment is **valid** with execution status **completed**. The headline package conclusion is: Hidden-queue uncertainty mattered, but reconstruction had no isolated advantage; at 512 draws direct and distribution-Y outputs coincided.

## Limitations

The study is controlled rather than empirical, and an observation-invisible conditional shift harmed both approaches.

## Reproduction

Prepare the non-committed data described in `provenance.json`, use the package `run.py` and frozen `config/` when present, then compare the generated compact outputs with `results/summary.json`. Historical branch and commit bindings are recorded in `provenance.json`; raw market data are intentionally excluded.

## Included artifacts

- [result-paper.pdf](result-paper.pdf) — 635,492 bytes, SHA-256 `376866745c26d96d04e2a53c79cd228f81029dc18a17cffee36af91a424ba62b`
- [figures/main.png](figures/main.png) — 315,527 bytes, SHA-256 `b56e41d14d44d456cb07de5e74e0b46b2b1e756d1b34dc4bfce397ee151eb762`
- [interactive-explanation.html](interactive-explanation.html) — 4,308,292 bytes, SHA-256 `8946a6d456e8579e85aa1b73fc7218b811a3ea2372463f460c86eeca931ac65a`
- [results/stage-summary.json](results/stage-summary.json) — 1,033 bytes, SHA-256 `aba23a2cd514d82562ce697100b89f1dc309257d30e765f3af066db27b79c060`
- [results/metrics.csv](results/metrics.csv) — 15,968 bytes, SHA-256 `b4e22c7c5a8ffb8cb0726ca81a6a4d37a1d3a6d1334bf2598d1f8599a72eac6e`

Machine-readable state-derived findings are in [results/summary.json](results/summary.json), and sanitized source bindings plus artifact hashes are in [provenance.json](provenance.json).
