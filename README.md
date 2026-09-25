# Learning with Less: Machine Learning from Partial Market Information

Anonymized code, results, and paper for double-blind review. This repository accompanies the
submission of the same title and contains the full experiment programme behind its three
studies (Q16 reconstruction value, Q17 forecast-to-decision, Q18 information sufficiency).

- `paper/` — the paper source (`main.tex`, `sections/`, `figures/`, `references.bib`) and
  compiled `main.pdf`.
- `experiments/` — thirty curated experiment packages; see `experiments/INDEX.md`. Each package
  has its question, method, compact results, figures, and provenance. The real-data studies are
  `e016`/`e017`/`e018`; the reconstruction-vs-prediction diagnostics are `e259`/`e261`/`e264`/`e271`.
- `src/` — shared parsing, reconstruction, feature and evaluation code imported by packages.
- `metadata/` — machine-readable experiment inventory.

All numbers reported in the paper are regenerated from staged result files. Raw market dumps
are not redistributed; each package ships checksums and acquisition instructions, plus a
license-clean smoke fixture so its entry point runs without the restricted data.

Author and institution identifiers have been removed for anonymous review.
