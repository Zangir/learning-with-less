"""Freeze the visually checked source-only publication, excluding build clutter."""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "source-publication"
NAMES = ["report.pdf", "report.tex", "explanation.md", "main_figure.png", "main_figure.svg",
         "index.html", "figure_data.json", "required_roles.csv", "reviewed_Q18_coverage.csv",
         "nonidentifying_provenance_rows.csv", "generation_checks.json"]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    assert not (OUT / "manifest.json").exists(), "Frozen publications are not overwritten."
    checks = json.loads((OUT / "generation_checks.json").read_text())
    assert checks["passed"] and checks["raw_response_pairs_freshly_verified"] == 3
    assert checks["code_sha256"] == digest(ROOT / "code/source_publication.py")
    result = {
        "schema": "t008-reviewed-source-publication/4", "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "Source-only RV013 exact Q18 required inputs and unchanged RV011 hour00; no model acceptance",
        "scientific_metrics_recomputed": False, "participant_admission": False, "external_publication": False,
        "visual_inspection": "All three PDF pages and figure inspected; no clipping or overlap",
        "privacy_review": "Public data/text contain no participant account/order identifiers or private filesystem paths",
        "review": "Internal peer check against frozen source reviews passed; independent T013 review requested",
        "generator": {"repository_path": "experiments/t008_r4/code/source_publication.py", "sha256": checks["code_sha256"]},
        "artifacts": {name: {"bytes": (OUT/name).stat().st_size, "sha256": digest(OUT/name)} for name in NAMES},
    }
    (OUT / "manifest.json").write_text(json.dumps(result, indent=2)+"\n", encoding="utf-8")
    print(json.dumps({"manifest_sha256": digest(OUT/"manifest.json"), "pdf_sha256": digest(OUT/"report.pdf"),
                      "figure_sha256": digest(OUT/"main_figure.png"), "files": len(NAMES)}))


if __name__ == "__main__":
    main()
