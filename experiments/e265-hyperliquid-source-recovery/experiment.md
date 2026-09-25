# Recover and admit real Hyperliquid inputs

**State experiments:** E-265  
**Execution status:** source_candidate_found_pending_protocol_admission  
**Scientific assessment:** source_location_resolved_candidate_not_yet_admitted

## Research question

- **Q-001:** Do the Q16-Q18 findings survive protocol-documented transfer to real Hyperliquid observations?

## Hypothesis

- No separate hypothesis was registered for this package.

## Input

Retained Hyperliquid source inventories spanning sampled-L2, native BBO, and receipt/event metadata.

## Method

Recover exact contracts, bind hashes and temporal semantics, and independently admit only supported subsets for Q17 and Q18.

## Output

Exact Q18 and Q17 source prerequisites were supported in scope; a qualified native Q16 source remained unavailable.

## Findings

- **R-032:** exact_Q18_source_prerequisite_supported
- **R-038:** exact_Q17_source_prerequisite_supported

## Status

The canonical state assessment is **source_location_resolved_candidate_not_yet_admitted** with execution status **source_candidate_found_pending_protocol_admission**. The headline package conclusion is: Exact Q18 and Q17 source prerequisites were supported in scope; a qualified native Q16 source remained unavailable.

## Limitations

Admission applies only to the bound contracts and semantics and does not accept downstream model claims.

## Reproduction

Prepare the non-committed data described in `provenance.json`, use the package `run.py` and frozen `config/` when present, then compare the generated compact outputs with `results/summary.json`. Historical branch and commit bindings are recorded in `provenance.json`; raw market data are intentionally excluded.

## Included artifacts

- [result-paper.pdf](result-paper.pdf) — 145,116 bytes, SHA-256 `84223f3166512be8c9be6f194bce56071d44f62df5146d02fcb0a619c4f4226f`
- [figures/main.png](figures/main.png) — 103,076 bytes, SHA-256 `3cb22c708fcccb3ce5401d43ec985046681a1d439e21da1694a23ff7c9d02652`

Machine-readable state-derived findings are in [results/summary.json](results/summary.json), and sanitized source bindings plus artifact hashes are in [provenance.json](provenance.json).
