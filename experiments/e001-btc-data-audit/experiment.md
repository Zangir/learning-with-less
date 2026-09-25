# Bounded BTC source, schema, timing, and replay audit

**State experiments:** E-001  
**Execution status:** completed  
**Scientific assessment:** valid

## Research question

- **Q-001:** Do the Q16-Q18 findings survive protocol-documented transfer to real Hyperliquid observations?

## Hypothesis

- No separate hypothesis was registered for this package.

## Input

A bounded real BTC first-hour sample plus synthetic contract fixtures and source metadata.

## Method

Audit provenance, schema, event fields, timing semantics, and baseline replay assumptions before any scientific replication.

## Output

A reproducibility gate for later experiments; it does not itself reproduce a market result.

## Findings

- **R-001:** Fresh original synthetic checks and bounded real BTC first-hour integrity/schema audit; not market replications.

## Status

The canonical state assessment is **valid** with execution status **completed**. The headline package conclusion is: A reproducibility gate for later experiments; it does not itself reproduce a market result.

## Limitations

The real-data check is deliberately bounded and cannot certify later windows or participant-level semantics.

## Reproduction

Prepare the non-committed data described in `provenance.json`, use the package `run.py` and frozen `config/` when present, then compare the generated compact outputs with `results/summary.json`. Historical branch and commit bindings are recorded in `provenance.json`; raw market data are intentionally excluded.

## Included artifacts

- [source-report.md](source-report.md) — 12,063 bytes, SHA-256 `b298e85ffcbc7d8248e057463af41495c1ab0c68e8dd02c16a35a6628e6cd098`
- [results/sample-audit.json](results/sample-audit.json) — 2,596 bytes, SHA-256 `197b6b0f08e069dc8d99e3ec0fd009ef443c81d87ac87346e17af78b8acd2c6e`
- [results/baseline-checks.json](results/baseline-checks.json) — 4,005 bytes, SHA-256 `f4a7a6b41b94f81e96494117a5de15a5c63edf6508460a5c0be90ca71fc52df7`
- [results/replication-plan.json](results/replication-plan.json) — 2,357 bytes, SHA-256 `0f0bdb57731e89af1729e5fc39821af3231c24edfadeb4619ac80ced7f299da3`

Machine-readable state-derived findings are in [results/summary.json](results/summary.json), and sanitized source bindings plus artifact hashes are in [provenance.json](provenance.json).
