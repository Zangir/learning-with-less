# Repository structure

The default branch contains the curated, reviewable form of the research programme. Historical implementation branches are preserved under `old/` for provenance, but their complete working trees are not the canonical project layout.

## Experiment packages

Each executed or materially attempted experiment has a package under:

```text
experiments/<experiment-id>-<short-name>/
```

Packages use the following files when the relevant material exists:

```text
experiment.md                  Question, inputs, method, findings and limitations
run.py                         Shortest truthful entry point
src/                           Experiment-specific implementation for complex runs
config/                        Frozen non-secret settings and path templates
tests/                         Meaningful correctness and reproducibility checks
figures/                       Selected compact figures
results/                       Accepted machine-readable summaries
provenance.json                Sources, hashes, seed, protocol and source commit
explanation-paper.pdf          Accessible narrative explanation
interactive-explanation.html  Offline interactive explanation
```

Historical experiments are not backfilled with newly generated explanation files. Existing explanation files are copied into their corresponding packages. The Q16-Q18 explanation paper is intentionally shared across those three packages and identified as shared in their provenance.

[`experiments/INDEX.md`](experiments/INDEX.md) is the canonical catalogue. It distinguishes accepted evidence, scientific negatives, inconclusive runs, invalid cohorts, cancelled work and superseded revisions.

## Shared implementation

Reusable parsing, reconstruction, feature and evaluation code belongs under `src/drc_lob/`. Package-local `run.py` files may import it. Code specific to one experiment remains in that package's optional `src/` directory.

## Data and generated artifacts

Git contains compact inputs needed to understand or verify a claim: source identifiers, schemas, hashes, small result tables, selected figures and final reports. The repository excludes raw market dumps, large checkpoints, caches, duplicate frozen evidence, internal coordinator state, messaging receipts, credentials and machine-specific absolute paths.

Large or restricted inputs are represented by acquisition instructions and checksums. A package must state clearly when its source data cannot be redistributed.

## Historical branches

Historical branch heads are mirrored under `old/<original-name>`. They preserve implementation history and exact commits. New work should use the curated default-branch packages rather than extending those branches unless an experiment explicitly resumes from one of them.

## Reports

The concise programme overview is stored under `reports/all-experiments-brief/`. It summarizes the input, output, result and scientific status of every packaged experiment and links back to the package-level evidence.
