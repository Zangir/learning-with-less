# Declared BTC persistence source

**State experiments:** E-270  
**Execution status:** completed  
**Scientific assessment:** valid_source_only

## Research question

- **Q-019:** Do richer-data adaptations of available MegaProp strategies retain value with restored inputs?

## Hypothesis

- No separate hypothesis was registered for this package.

## Input

One retained BTC sampled-L2 source for 2026-02-01, reusing bytes previously bound for Q18.

## Method

Declare and validate the exact source, event-time window, exclusions, and consumer constraints before evaluation.

## Output

The day-specific source was accepted in exact scope; no strategy outputs were produced at this stage.

## Findings

- **R-041:** One declared BTC 2026-02-01 sampled-L2 source reuses retained Q18 raw bytes; exact event-clock consumer export awaits independent admission. No new strategy outputs or Q16 completion.

## Status

The canonical state assessment is **valid_source_only** with execution status **completed**. The headline package conclusion is: The day-specific source was accepted in exact scope; no strategy outputs were produced at this stage.

## Limitations

Receipt availability is not calibrated, the source was previously exposed, and admission does not imply model validity.

## Reproduction

Prepare the non-committed data described in `provenance.json`, use the package `run.py` and frozen `config/` when present, then compare the generated compact outputs with `results/summary.json`. Historical branch and commit bindings are recorded in `provenance.json`; raw market data are intentionally excluded.

## Included artifacts

- [result-paper.pdf](result-paper.pdf) — 72,091 bytes, SHA-256 `adee3fbea0c62a7c08692eed56f7bc91ba86df350f4b1d98450939736bc4e142`
- [figures/main.png](figures/main.png) — 45,196 bytes, SHA-256 `acca966b822a57234318438cfbfea9790f4184370d71de7f46e9031ae0fe4337`

Machine-readable state-derived findings are in [results/summary.json](results/summary.json), and sanitized source bindings plus artifact hashes are in [provenance.json](provenance.json).
