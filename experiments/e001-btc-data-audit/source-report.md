# T-001: Hyperliquid replication readiness

## Outcome and scope

The December 2025 Hyperliquid dataset was located and a real, aligned first-hour subset was acquired and integrity-checked. The original Q16, Q17, and Q18 software checks executed successfully. The mandatory real-market replications remain **blocked at replay validation**; they are not completed empirical experiments. Initial-state and event-clock repair remain active follow-up work. The observed prefix does not prove that all subsequent windows are unusable or that repair is impossible.

The execution directory is `<external research-artifact directory>`. There is no Git worktree or local base commit: the coordinator explicitly authorized this external artifact directory in place of the skill's worktree default because the source location is a non-Git private snapshot and repository initialization is prohibited. No repository was initialized, no source code was changed, and nothing was pushed. Source repository commits are preserved in `baseline_checks.json` and the original `anon experiments/SOURCES.json`.

## Source protocols and mandatory experiment status

| Experiment | Original protocol | Real-data transfer | Current status |
|---|---|---|---|
| E016 / Q16 | Exact finite FIFO belief-state enumeration. Identical atomic add/cancel/trade event types and quantities in both arms; one arm additionally sees order counts. Existing noncancellable size-1 probe. Seed 16029001, 1,000 histories, eight events, 100,000-state cap. Follow-up adds partial fills and five seeds across three simulated generators. | Preserve the information ablation, exact quantity lattice, queue ordering, and truth-in-feasible-set checks on initialized real queue episodes. Declare any-fill/full-fill/fill-fraction target. Do not select only orders that later avoid cancellation without explicitly limiting the estimand. | Planned, blocked by initial queue completeness and event/trade semantics. No real fill-ambiguity estimate produced. |
| E017 / Q17 | Deribit BTC/ETH 10-second midpoint direction, five past-only L1 features, prior/logistic/HGB/MLP; MLP seeds 17/29/41. January–March training, April policy selection, eight held-out dates. Three policies: argmax, validation-tuned confidence, causal scheduling. Original primary is a joint cross-asset/cross-policy ranking reversal, which failed. | Preserve models, direction target, feature causality, validation-only policy selection, and matched policy comparisons. Replace inverse-contract utility with declared linear-perpetual cash flows. Historical exchange event time is not a measured receive-time or latency clock. | Planned, blocked by quote reconstruction, causal clock/tie ordering, and independent-day acquisition. No Hyperliquid model fitted. |
| E018 / Q18 | Depth 1/5 × instantaneous/20-second history × delay 0/55 seconds. Binary label: absolute future 10-second return above training-only 90th percentile. Logistic/HGB freshness pilot: 32 fits across two assets; separate MLP iteration-cap diagnostic. | Preserve tail target, common eligible rows, own-observation normalization, and paired view/model comparisons. Effective delayed lookback is 75 seconds. Exact original feature builder is absent from transferred Q18 source, so a rebuilt feature representation must be labeled an adaptation. | Planned, blocked by validated five-level state and clock; no Hyperliquid sufficiency or noninferiority result. |

Volume versus count is a controlled information ablation. Because an exchange L2 feed can itself include order counts, a count advantage is not automatically evidence of L2-to-L3 reconstruction. Wallet addresses are pseudonymous participant identifiers, not legal-person identities. None of the three baseline protocols uses wallet identities as its primary tested intervention.

## Verified data and acquisition

Primary record: [An Open Book, Zenodo 18184441](https://zenodo.org/records/18184441), DOI 10.5281/zenodo.18184441, version 1.0, published 25 March 2026. The API metadata specifies CC-BY-4.0. The full deposit is approximately 195.3 GB. BTC's main status archive is 19,268,354,932 bytes, the book-diff archive is 49,555,435,520 bytes, and December trades are 6,694,522,880 bytes. Rejected-order data are separate, although the main status archive also contains several rejection categories; it must not be treated as exclusively successful placements.

The source README, schema, and Python reader were downloaded and their MD5 hashes exactly matched the deposit. HTTP byte ranges were empirically verified with 206 responses. Archive member order is not chronological: the first book-diff member was hour 22 and the first trade member was hour 1. TAR headers were inspected by bounded ranges to locate hour 0. The BTC compressed TAR starts with hour 0, so a bounded 76 MiB prefix was enough to extract its first member.

| Acquired member | Compressed bytes | Decoded bytes | Integrity |
|---|---:|---:|---|
| `20251201/btc_00.data.gz` | 71,745,554 | 425,660,292 | SHA-256 saved, whole gzip CRC passed |
| `20251201/ex0.gz` | 178,711,491 | 1,567,764,086 | SHA-256 saved, whole gzip CRC passed |
| `20251201/0.gz` | 41,102,773 | 249,813,653 | SHA-256 saved, whole gzip CRC passed |

Total retained compressed data are 291,559,818 bytes, with 2,243,238,031 decoded bytes processed without saving the expanded streams. Transfer accounting conservatively bounds the two acquisition attempts at 310,599,605 bytes. The initial 256 MiB limit correctly halted while obtaining trades; the coordinator approved a 384 MiB total cap before completing that member. This transfer number is an explicit upper bound, including an abandoned read, rather than an exact network-byte measurement. The published full-archive MD5 was not and cannot be verified from these subsets. A full SHA-256 for each retained member and byte-range provenance appear in `sample_manifest.json`.

## Real-data audit findings

The complete status member contains 7,882,598 records of 54 bytes and 5,391,631 distinct orders. Status timestamps are nondecreasing; 7,845,046 adjacent pairs share timestamps. The filename's hour does not exactly define the event interval: the earliest event is 2025-11-30 23:59:59.867476878 UTC, while the latest is 2025-12-01 00:59:59.774857692 UTC. Split assignment must use validated event time rather than archive path labels.

The first 200,000 book-diff lines contain 91,868 BTC changes over 46,959 order IDs. Of these IDs, 1,627 first appear as a removal and 138 as a size update. Thus starting this prefix with an empty book omits pre-existing orders. This identifies incomplete initialization at the prefix, not the prevalence of incomplete queues over the month.

The raw diff objects have no timestamp, block height, or sequence field. A preliminary kind-and-order-ID join matches exactly one `open` status for each of 45,194 new events and one terminal status for each of 44,889 removals. However, the matched times decrease once along the diff stream. The 1,785 size updates were deliberately left unassigned by this simple join. The count `update/0` in `sample_audit.json` means that the implemented naive join supplies no clock candidate; it is not proof that no timestamp can be recovered from other streams.

Among 102,148 `filled` statuses, 4,227 have nonzero packed `sz`. The source documentation also qualifies size semantics. Trade joins and quantity conservation must establish partial/full-fill behavior before these fields become labels. The trade-prefix audit read 200,000 lines, including 35,814 BTC executions, through approximately 00:15:47 UTC. These prefixes cover different durations and are not treated as aligned equal-sized event samples.

The official [L1 data schema](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/nodes/l1-data-schemas) describes applying order statuses to a time-ordered L4 checkpoint generated from an ABCI state. The [historical-data page](https://hyperliquid.gitbook.io/hyperliquid-docs/historical-data) documents public historical sources, with requester-pays S3 access and possible missing data. No paid acquisition was started. T-005 is investigating public checkpoint and clock repair possibilities separately.

Minimum replay acceptance is a verified starting checkpoint, or independently certified complete relevant price levels; validated update/trade/status relationships; explicit timestamp and within-block order semantics; and aggregate, quantity-conservation, and crossed-book checks. Retrospectively sorting inconsistent timestamps is not an acceptable silent repair.

## Fresh checks and implemented adapter components

The checks in `baseline_checks.json` are new executions on original synthetic fixtures, not reuse of stored results and not real-data replications:

- Q16: 1,000 histories; 59 volume-ambiguous, 19 count-ambiguous, 40 strictly narrowed; no ground truth excluded. The independent Z3 comparison was not rerun because Z3 is absent locally.
- Q17: all eight invariant groups passed on 7,000 synthetic quote rows.
- Q18: unchanged development runner completed 32 synthetic fits and 16 contrasts, and rejected nonfinite input. The source's separate optimization diagnostic was not rerun.
- Total baseline-check duration: 24.16 seconds. The real-data audit took 10.58 seconds. Five new adapter tests passed in 0.05 seconds.

`hyperliquid_contracts.py` contains scoped transfer components, not a complete replay or training pipeline. It decodes packed prices/sizes into exact integer units, implements linear-contract long/short/flat utility and fixed-base scheduling cost, rejects uncertified replay evidence, and applies chronological split containment. The linear utility uses:

```python
ratio = exit_price / entry
values = np.where(side != 0, side * (ratio - 1) * 10000 - fee_bps * (1 + ratio), 0.0)
```

This follows the [Hyperliquid linear perpetual contract specification](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/contract-specifications) and a declared proportional-fee scenario. It is exogenous quote-based price-taking utility: no inferred historical fill, funding, finite-size market impact, realized return, or trade recommendation is asserted. Fixed-base TWAP comparison is explicit; it differs from the original inverse-contract scheduling estimand.

The provisional chronological split helper uses December 1–14 training, 15–21 validation, and 22–31 test, excluding rows whose 75-second feature lookback or 10.5-second target/execution window crosses a split boundary. This is an implementation candidate requiring a frozen experimental protocol and data-coverage verification before use; it does not confer independent-day evidence on the single acquired hour.

## Resource and continuation notes

All executed checks used CPU. The entire three-stream month would require roughly 75.5 GB compressed before rejected orders or derived outputs. Decoded streams can be much larger; keep hourly streaming and explicit disk quotas rather than expanding a month. Local physical disk free space is about 210 GB according to the independent integration audit; WSL's virtual capacity is not the physical budget. Heavy work should use the verified HPC Slurm route rather than the login node. No month download, GPU job, or full-day training was launched.

Used tmux sessions: `drc-lob-hyperliquid-sample`, `drc-lob-baseline-smoke`, and `drc-lob-hyperliquid-audit`. Each had a one-hour process limit, captured logs, and ended after its bounded command completed. No T-001 session remains. Unrelated sessions were neither attached nor stopped.

The next mandatory execution step is the data repair gate, followed by three separately recorded real-data experiments. Preserve the failure evidence, acquisition manifests, seeds, training-only transformations, validation-only policy choices, and independent date-cluster evaluation. A repaired first-hour pipeline remains a plumbing test; it is not a publication result or the completed monthly replication.
