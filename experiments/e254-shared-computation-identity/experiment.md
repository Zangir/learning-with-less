# Shared computation and matched-method identity

**State experiments:** E-254  
**Execution status:** completed  
**Scientific assessment:** valid_in_declared_exact_scope

## Research question

- **Q-002:** When does inference of hidden order structure improve decisions over strong direct prediction and privileged-information training?
- **Q-016:** Can one shared restoration layer support downstream tasks it was not trained to solve?
- **Q-025:** When does restoration earn its end-to-end compute and latency cost?

## Hypothesis

- No separate hypothesis was registered for this package.

## Input

A fixed retrospective monotone robust-loss candidate and matched direct/restoration computation graphs.

## Method

Compile both routes into concrete algorithms and check exact identity under the declared fixed candidate.

## Output

The direct and restoration compilers were exactly identical in the declared scope.

## Findings

- **R-022:** Author reports exact direct/restoration compiler identity for a fixed retrospective monotone robust-loss candidate; scientific acceptance pending.

## Status

The canonical state assessment is **valid_in_declared_exact_scope** with execution status **completed**. The headline package conclusion is: The direct and restoration compilers were exactly identical in the declared scope.

## Limitations

This candidate-specific identity does not prove all restoration architectures redundant.

## Reproduction

Prepare the non-committed data described in `provenance.json`, use the package `run.py` and frozen `config/` when present, then compare the generated compact outputs with `results/summary.json`. Historical branch and commit bindings are recorded in `provenance.json`; raw market data are intentionally excluded.

## Included artifacts

- [figures/main.png](figures/main.png) ? 228,446 bytes, SHA-256 `1bcc76bd09869593c919bff8194ae5c854e307a2c3a0aa00ff721a8596b2f738`
- [interactive-explanation.html](interactive-explanation.html) ? 24,449 bytes, SHA-256 `f0f5515a16cab175fb2a855d2599bd97a3e95abe68fba37b3bfff74e23501d24`
- [result-paper.pdf](result-paper.pdf) ? 487,360 bytes, SHA-256 `48fd03678dc29d3c83579d73b031244217be3318178023604ac80bcfaca6d196`
- [results/candidate-spec.md](results/candidate-spec.md) ? 9,157 bytes, SHA-256 `05ab838fc28c184fdb6471643458c689baafbc439027ca69a7ac53c0e7471f00`
- [results/exact-checks.json](results/exact-checks.json) ? 1,778 bytes, SHA-256 `5aa2a92142146f2685744c114ef7b736a13ecca8bd69e2571acca11fb5c3b14c`
- [results/primary-queries.csv](results/primary-queries.csv) ? 4,339 bytes, SHA-256 `817f9129070c9abb8842a0fa1238a7b1805999953db2f11a0c31c923a9e52cab`
- [results/synthetic-examples.csv](results/synthetic-examples.csv) ? 143 bytes, SHA-256 `1a04ac54c0f47be9b4e9f20bb371900b3c0ab874dd9e01dce4499a619e5e6ab0`

Machine-readable state-derived findings are in [results/summary.json](results/summary.json), and sanitized source bindings plus artifact hashes are in [provenance.json](provenance.json).
