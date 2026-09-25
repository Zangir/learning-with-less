# BTC unknown-initial-book washout

**State experiments:** E-273  
**Execution status:** reviewed_terminal_prefix  
**Scientific assessment:** inconclusive_independently_reviewed

## Research question

- **Q-001:** Do the Q16-Q18 findings survive protocol-documented transfer to real Hyperliquid observations?
- **Q-026:** Can an unknown initial BTC book state wash out under causal L4 event replay?

## Hypothesis

- **H-027:** After a fixed 24-hour BTC warm-up from 2025-12-01, no legacy order first appears through update or removal during the following 24-hour holdout.

## Input

Real BTC book-diff events from Zenodo record 18184441, December 2025, replayed causally from an empty initial book.

## Method

Track order IDs first observed through update/remove as legacy orders and test whether none first appear after a 24-hour warm-up during a 24-hour holdout.

## Output

Eleven complete hours covered 32,633,820 events and revealed 11,328 legacy order IDs; 148 were still first discovered in hour 10. Observed-lifecycle coverage reached 99.92985%, but true live-book completeness is unidentified.

## Findings

- **R-044:** In 11 complete chronological BTC hours, 11,328 OIDs first appeared through update/remove and 148 were still first revealed in hour 10; the 24+24-hour decision and true full-book completeness remain unidentified.

## Status

The canonical state assessment is **inconclusive_independently_reviewed** with execution status **reviewed_terminal_prefix**. The headline package conclusion is: Eleven complete hours covered 32,633,820 events and revealed 11,328 legacy order IDs; 148 were still first discovered in hour 10. Observed-lifecycle coverage reached 99.92985%, but true live-book completeness is unidentified.

## Limitations

Only 11 of the required 48 hours completed, so H027 is inconclusive; silent initial orders can remain unobservable.

## Reproduction

Prepare the non-committed data described in `provenance.json`, use the package `run.py` and frozen `config/` when present, then compare the generated compact outputs with `results/summary.json`. Historical branch and commit bindings are recorded in `provenance.json`; raw market data are intentionally excluded.

## Included artifacts

- [figures/main.png](figures/main.png) — 302,199 bytes, SHA-256 `382dfbaaf490e3b0ff2960cfeee890a18a89c74632363a7ae18f3d2d02026133`
- [interactive-explanation.html](interactive-explanation.html) — 4,308,155 bytes, SHA-256 `b4729b2702d5de089328d56c559f3618424aa59cf547d1e3a3274e9e263bf23b`
- [results/knowledge-coverage-by-hour.csv](results/knowledge-coverage-by-hour.csv) — 2,243 bytes, SHA-256 `2e7ecd5da68411bd993f8ea4c8f3b9f1276bb60636c16c0268ce44a445cec623`

Machine-readable state-derived findings are in [results/summary.json](results/summary.json), and sanitized source bindings plus artifact hashes are in [provenance.json](provenance.json).
