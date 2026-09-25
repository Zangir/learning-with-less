# Existing-hour clock-anchor feasibility diagnostic

**State experiments:** E-002  
**Execution status:** completed  
**Scientific assessment:** valid

## Research question

- **Q-001:** Do the Q16-Q18 findings survive protocol-documented transfer to real Hyperliquid observations?

## Hypothesis

- No separate hypothesis was registered for this package.

## Input

The same 91,868 BTC diff events evaluated under alternative offline point-timestamp candidate rules.

## Method

Recompute candidate availability after relaxing the original clock anchor while holding the event sample fixed.

## Output

Candidate coverage rose from 90,083 to 91,860, adding 1,777 candidates.

## Findings

- **R-003:** Offline point-timestamp candidates rise from90083 to91860 on the same91868 BTC diff events;1777additional candidates.

## Status

The canonical state assessment is **valid** with execution status **completed**. The headline package conclusion is: Candidate coverage rose from 90,083 to 91,860, adding 1,777 candidates.

## Limitations

This is a feasibility diagnostic, not evidence that the additional timestamps are causally available for trading.

## Reproduction

Prepare the non-committed data described in `provenance.json`, use the package `run.py` and frozen `config/` when present, then compare the generated compact outputs with `results/summary.json`. Historical branch and commit bindings are recorded in `provenance.json`; raw market data are intentionally excluded.

## Included artifacts

- [source-report.md](source-report.md) — 4,673 bytes, SHA-256 `e2786ce12ad9309997a8279bc8af2436095752560b88e3828f60f7262ac16c21`
- [figures/main.png](figures/main.png) — 107,871 bytes, SHA-256 `24ecdcbb70b1529c6f5ca2f01e27093ce17d02e2adcb6e2f44494b7da23f2d91`
- [results/clock-coverage.json](results/clock-coverage.json) — 2,642 bytes, SHA-256 `493e3fd1b4aa496755b2ede1d86fe0f9b52c2eef95890c5802a804ee7e30f0ac`

Machine-readable state-derived findings are in [results/summary.json](results/summary.json), and sanitized source bindings plus artifact hashes are in [provenance.json](provenance.json).
