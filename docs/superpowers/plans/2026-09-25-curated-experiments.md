# Curated Experiment Repository Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve every current implementation branch under `old/*`, curate the completed and materially attempted LOB experiments into a stable package layout on the default branch, add the requested explanation artifacts and overview report, and push the verified result.

**Architecture:** Historical branches remain immutable provenance. The default branch contains one compact package per executed experiment under `experiments/`, reusable code under `src/drc_lob/`, and a generated catalogue/report derived from the accepted state record. Large raw data, coordinator internals, duplicate frozen evidence, credentials, and private third-party manuscripts stay outside Git.

**Tech Stack:** Git worktrees, Python 3, JSON/CSV, pytest, LaTeX, Plotly/offline HTML, GitHub private repository.

**Spec:** Local `AGENTS.md` section `Experiment repository structure` plus the user instruction delivered on 2026-09-25.

## Global Constraints

- The GitHub repository is private, but credentials, raw dumps, internal coordinator state, messaging receipts, absolute local paths, and unneeded private manuscripts remain excluded.
- The repository default branch is `master`; this is the requested final `main` destination.
- Every current local implementation branch is archived to a collision-free remote ref below `old/` before worktree cleanup.
- Existing historical experiments are not forced to receive newly generated explanation files.
- Existing explanation PDFs/HTML files are reused. The shared Q16-Q18 explanation PDF is deliberately copied into all three packages and labelled as shared.
- New experiment packages must contain `explanation-paper.pdf` and `interactive-explanation.html` before being considered complete.
- Complex experiment implementations may use package-local `src/`; shared reusable code belongs under `src/drc_lob/`.
- Fixed seeds and source/protocol versions must be recorded when present in the evidence.
- The temporary `research-artifacts` junction is removed only after the curated packages and report are verified.

---

### Task 1: Freeze branch and artifact inventory

**Files:**
- Create: `metadata/archive-branches.json`
- Create: `metadata/experiment-inventory.json`

**Interfaces:**
- Consumes: local Git refs, worktree registry, research state revision 187, task artifacts `T-001` through `T-024`.
- Produces: deterministic source mapping used by every later packaging step.

- [ ] Export every current local branch name, head SHA, worktree path, and proposed `old/<name>` remote ref.
- [ ] Export every executed/materially attempted experiment with task IDs, result IDs, review IDs, scientific status, source commit, and selected compact artifacts.
- [ ] Strip absolute local paths, task URLs, chat IDs, and coordinator-only fields from committed metadata.
- [ ] Validate that all referenced source commits exist and all selected files are readable.
- [ ] Commit the inventory with a detailed metadata-only commit.

### Task 2: Record durable repository rules

**Files:**
- Modify locally: `AGENTS.md`
- Create: `REPOSITORY_STRUCTURE.md`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: the approved package convention.
- Produces: local agent instructions and a tracked contributor-facing structure description.

- [ ] Add the exact experiment-package convention to local `AGENTS.md`.
- [ ] Describe the same neutral repository structure in `REPOSITORY_STRUCTURE.md` without conversation history.
- [ ] Ignore raw datasets, generated caches, coordinator state, temporary receipts, and local artifact junctions while allowing curated experiment results.
- [ ] Verify the local `AGENTS.md` remains ignored and the tracked structure document contains no private local paths.
- [ ] Commit the tracked structure and ignore rules.

### Task 3: Curate source implementations

**Files:**
- Create: `src/drc_lob/`
- Create: `experiments/<experiment-id>-<short-name>/run.py`
- Create as needed: `experiments/<experiment-id>-<short-name>/src/`
- Create as needed: `experiments/<experiment-id>-<short-name>/tests/`
- Create as needed: `experiments/<experiment-id>-<short-name>/config/`

**Interfaces:**
- Consumes: immutable source commits listed in `metadata/archive-branches.json`.
- Produces: importable/re-runnable implementations without merging obsolete branch trees verbatim.

- [ ] Copy only final task-owned code for Q16, Q17, Q18, data certification, controlled mechanisms, breakout/rebound, source recovery, Q16 empirical checks, and BTC washout.
- [ ] Keep task-specific source inside its package; move code reused by multiple packages under `src/drc_lob/`.
- [ ] Preserve third-party licences and exact requirement files where applicable.
- [ ] Add minimal `run.py` entry points only when the historical implementation already supports a truthful run path; otherwise document the exact historical command in `experiment.md`.
- [ ] Run the available unit tests in isolated groups and record unsupported environments instead of weakening tests.
- [ ] Commit source curation separately from generated results.

### Task 4: Build self-contained experiment packages

**Files:**
- Create: `experiments/INDEX.md`
- Create for each package: `experiment.md`
- Create for each package: `provenance.json`
- Create as applicable: `results/summary.json`, compact CSV files, and `figures/`

**Interfaces:**
- Consumes: accepted/qualified result records and independent review decisions.
- Produces: one reviewable package for every executed or materially attempted experiment.

- [ ] Write each experiment's question, hypothesis, inputs, method, outputs, findings, status, limitations, and reproduction path.
- [ ] Preserve accepted negatives, inconclusive results, invalid cohorts, superseded revisions, and cancelled work as distinct statuses.
- [ ] Copy only compact, claim-supporting metrics and figures; include source hashes and original result/review IDs.
- [ ] Generate `experiments/INDEX.md` with status, headline result, package path, and historical `old/*` source branch.
- [ ] Validate every index link and every JSON file.
- [ ] Commit experiment narratives/results separately from source code.

### Task 5: Reuse existing explanation packages

**Files:**
- Create as available: `experiments/*/explanation-paper.pdf`
- Create as available: `experiments/*/interactive-explanation.html`
- Create as available: `experiments/*/explanation-source/`

**Interfaces:**
- Consumes: existing rendered explanation artifacts only.
- Produces: package-local explanation files without fabricating missing historical explainers.

- [ ] Copy the existing shared Q16-Q18 explanation PDF into the Q16, Q17, and Q18 packages.
- [ ] Add a package note and provenance hash stating that the PDF is intentionally shared.
- [ ] Copy existing self-contained interactive explanations only when they genuinely explain the corresponding experiment.
- [ ] Copy the BTC washout interactive HTML and its static preview into E-273.
- [ ] Do not generate explanation files for historical packages that lack them.
- [ ] Verify PDF hashes, render representative pages, and open/test copied HTML controls.
- [ ] Commit explanation artifacts separately.

### Task 6: Create the all-experiments brief

**Files:**
- Create: `reports/all-experiments-brief/main.tex`
- Create: `reports/all-experiments-brief/all-experiments-brief.pdf`
- Create: `reports/all-experiments-brief/report-source.md`
- Create: `reports/all-experiments-brief/figures/`

**Interfaces:**
- Consumes: curated experiment metadata and accepted result summaries.
- Produces: a concise narrative report covering every packaged experiment.

- [ ] Write two compact paragraphs per experiment: input/question/method, then output/result/status.
- [ ] Lead with a one-page status table and highlight Q16-Q18 plus the most informative broader results.
- [ ] Include concrete measured counts where supported and avoid turning invalid/inconclusive evidence into negatives.
- [ ] Compile the LaTeX source to PDF.
- [ ] Render every page to PNG and inspect for clipping, overlap, missing glyphs, unreadable tables, and broken references.
- [ ] Commit the report source, final PDF, and only the figures required to rebuild it.

### Task 7: Verify and archive-push historical branches

**Files:**
- Update: `metadata/archive-branches.json` with push receipts.

**Interfaces:**
- Consumes: immutable local branch heads.
- Produces: remote `old/*` refs preserving every implementation branch.

- [ ] Scan all branch trees and curated files for credentials and oversized blobs.
- [ ] Push each local implementation branch SHA to its declared `refs/heads/old/<name>` destination without rewriting local worktrees.
- [ ] Fetch the remote and verify every archive ref resolves to the expected SHA.
- [ ] Record remote verification in `metadata/archive-branches.json` and commit the receipt update.

### Task 8: Integrate and push the default branch

**Files:**
- All curated repository files from Tasks 1-7.

**Interfaces:**
- Consumes: verified `feat/curated-experiments`.
- Produces: updated `origin/master` and a clean removable integration worktree.

- [ ] Run JSON validation, link checks, unit tests, secret scan, large-file scan, PDF extraction/render checks, and HTML smoke checks.
- [ ] Confirm the integration worktree is clean and all intended commits are present.
- [ ] In the integration branch, run `git pull --rebase origin master` and repeat affected checks.
- [ ] Push `feat/curated-experiments` for auditability.
- [ ] Fast-forward or merge the verified integration branch into local `master` without touching unrelated untracked local reports.
- [ ] Run `git pull --rebase origin master`, then push `master`.
- [ ] Fetch and verify `origin/master` equals the intended final commit.
- [ ] Remove the temporary project-local `research-artifacts` junction without deleting its external target.
- [ ] Recommend removing the completed integration worktree after anon-author has inspected the pushed repository.
