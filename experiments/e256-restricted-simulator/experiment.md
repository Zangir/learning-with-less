# Restricted simulator repair and delivered-feed validation

**State experiments:** E-256  
**Execution status:** completed  
**Scientific assessment:** valid

## Research question

- **Q-009:** Does action-relevant hidden ambiguity predict when restoration can help in simulation?
- **Q-010:** Can simulation training reduce the real rich-label budget needed for useful restoration?
- **Q-018:** Can restored lifecycle patterns improve detection of controlled spoofing-like behaviour?

## Hypothesis

- No separate hypothesis was registered for this package.

## Input

Repaired restricted-simulator episodes, actual participant-delivery cutoffs, and matched delivered inputs.

## Method

Independently reconstruct the repaired mechanics and compare fills under hidden states that share delivered observations.

## Output

The two local repairs and delivery cutoffs were supported; identical delivered inputs still produced fills of 3 versus 1.

## Findings

- **R-026:** Restricted simulator readiness accepted: independent reconstruction supports the two local native repairs and actual participant-delivery cutoffs. Identical delivered inputs can still lead to fills3 versus1. This is ambiguity, not recoverability. Next: a frozen controlled study comparing direct prediction, point reconstruction and uncertainty-preserving reconstruction.

## Status

The canonical state assessment is **valid** with execution status **completed**. The headline package conclusion is: The two local repairs and delivery cutoffs were supported; identical delivered inputs still produced fills of 3 versus 1.

## Limitations

The result establishes ambiguity, not recoverability or real-market execution quality.

## Reproduction

Prepare the non-committed data described in `provenance.json`, use the package `run.py` and frozen `config/` when present, then compare the generated compact outputs with `results/summary.json`. Historical branch and commit bindings are recorded in `provenance.json`; raw market data are intentionally excluded.

## Included artifacts

- [figures/main.png](figures/main.png) ? 200,534 bytes, SHA-256 `5819e29ec5bd6cf82c6ed8d4fd469582cfc83a799d1714a17110d6cc40acb3d1`
- [interactive-explanation.html](interactive-explanation.html) ? 33,775 bytes, SHA-256 `a093e060d57ce34bffba2b60b13484a1c06d7f088a35a8f75771b032ba95a2d1`
- [result-paper.pdf](result-paper.pdf) ? 436,014 bytes, SHA-256 `f71c303e5114ed1d4963e481adfe976391d9caf54f68a69a68a2f569f28fde82`
- [results/stage-summary.json](results/stage-summary.json) ? 2,968 bytes, SHA-256 `755aa9524d641afc9258a513515375817168ba71ba693a846c9fbab4da7edbb3`

Machine-readable state-derived findings are in [results/summary.json](results/summary.json), and sanitized source bindings plus artifact hashes are in [provenance.json](provenance.json).
