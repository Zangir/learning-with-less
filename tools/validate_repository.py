"""Validate the curated research repository before publication."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ROOT / "metadata" / "experiment-inventory.json"
ARCHIVE_RECEIPT = ROOT / "metadata" / "archive-branches.json"
SOURCE_CURATION = ROOT / "metadata" / "source-curation.json"
PACKAGE_ARTIFACTS = ROOT / "metadata" / "package-artifacts.json"
INDEX = ROOT / "experiments" / "INDEX.md"
REPORT = ROOT / "reports" / "all-experiments-brief" / "all-experiments-brief.pdf"
MAX_TRACKED_FILE_BYTES = 95 * 1024 * 1024

TEXT_SUFFIXES = {
    ".cfg",
    ".csv",
    ".html",
    ".ini",
    ".json",
    ".md",
    ".py",
    ".tex",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}

FORBIDDEN_TEXT_PATTERNS = {
    "Windows user path": re.compile(r"(?i)[A-Z]:[\\/]Users[\\/](?!<user>)"),
    # Keep the sentinel split so this validator does not report its own rule.
    "macOS user path": re.compile(r"/" + r"Users/(?!<user>/)"),
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "GitHub token": re.compile(r"\b(?:ghp|github_pat)_[A-Za-z0-9_]{20,}\b"),
    "OpenAI token": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    "AWS access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
}


class LocalReferenceParser(HTMLParser):
    """Collect resource and navigation references from a packaged HTML file."""

    def __init__(self) -> None:
        super().__init__()
        self.references: list[tuple[str, str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        for key, value in attrs:
            if key in {"src", "href"} and value:
                self.references.append((tag, key, value))


def load_json(path: Path) -> object:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    errors: list[str] = []

    inventory = load_json(INVENTORY)
    if not isinstance(inventory, dict):
        errors.append("experiment inventory must be a JSON object")
        inventory = {}

    records = inventory.get("experiments", [])
    expected_packages = {
        ROOT / record["package"]
        for record in records
        if isinstance(record, dict) and isinstance(record.get("package"), str)
    }
    actual_packages = {path for path in (ROOT / "experiments").iterdir() if path.is_dir()}

    if inventory.get("package_count") != len(expected_packages):
        errors.append(
            "metadata package_count does not match the unique package paths "
            f"({inventory.get('package_count')} != {len(expected_packages)})"
        )
    if actual_packages != expected_packages:
        missing = sorted(str(path.relative_to(ROOT)) for path in expected_packages - actual_packages)
        extra = sorted(str(path.relative_to(ROOT)) for path in actual_packages - expected_packages)
        errors.append(f"package directory mismatch; missing={missing}, extra={extra}")

    index_text = INDEX.read_text(encoding="utf-8") if INDEX.exists() else ""
    if not index_text:
        errors.append("experiments/INDEX.md is missing or empty")

    for package in sorted(expected_packages):
        for required in ("experiment.md", "provenance.json"):
            if not (package / required).is_file():
                errors.append(f"{package.relative_to(ROOT)}/{required} is missing")
        if package.name not in index_text:
            errors.append(f"{package.name} is not referenced by experiments/INDEX.md")

        for json_path in package.rglob("*.json"):
            try:
                load_json(json_path)
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                errors.append(f"invalid JSON in {json_path.relative_to(ROOT)}: {exc}")

    source_curation = load_json(SOURCE_CURATION)
    source_package_refs: set[Path] = set()
    if isinstance(source_curation, dict):
        for record in source_curation.get("packages", []):
            if isinstance(record, dict) and isinstance(record.get("package"), str):
                source_package_refs.add(ROOT / record["package"])
        for record in source_curation.get("shared_source", []):
            if not isinstance(record, dict):
                continue
            for package_ref in record.get("consumer_packages", []):
                if isinstance(package_ref, str):
                    source_package_refs.add(ROOT / package_ref)
    if source_package_refs != expected_packages:
        missing = sorted(str(path.relative_to(ROOT)) for path in expected_packages - source_package_refs)
        extra = sorted(str(path.relative_to(ROOT)) for path in source_package_refs - expected_packages)
        errors.append(f"source-curation package mismatch; missing={missing}, extra={extra}")

    artifact_manifest = load_json(PACKAGE_ARTIFACTS)
    if not isinstance(artifact_manifest, dict):
        errors.append("package-artifacts manifest must be a JSON object")
        artifact_manifest = {}
    artifact_records = artifact_manifest.get("artifacts", [])
    if artifact_manifest.get("artifact_count") != len(artifact_records):
        errors.append(
            "package-artifacts artifact_count does not match its records "
            f"({artifact_manifest.get('artifact_count')} != {len(artifact_records)})"
        )
    for record in artifact_records:
        if not isinstance(record, dict):
            errors.append("package-artifacts contains a non-object record")
            continue
        path = ROOT / "experiments" / record.get("package", "") / record.get("path", "")
        if not path.is_file():
            errors.append(f"manifested artifact is missing: {path.relative_to(ROOT)}")
            continue
        if path.stat().st_size != record.get("size_bytes"):
            errors.append(f"manifested artifact size mismatch: {path.relative_to(ROOT)}")
        if sha256(path) != record.get("sha256"):
            errors.append(f"manifested artifact hash mismatch: {path.relative_to(ROOT)}")

    shared_explainers = [
        ROOT / "experiments" / package / "explanation-paper.pdf"
        for package in ("e016-q16-real-data", "e017-q17-real-data", "e018-q18-real-data")
    ]
    shared_interactives = [
        ROOT / "experiments" / package / "interactive-explanation.html"
        for package in ("e016-q16-real-data", "e017-q17-real-data", "e018-q18-real-data")
    ]
    for path in shared_explainers + shared_interactives:
        if not path.is_file():
            errors.append(f"required existing explanation artifact is missing: {path.relative_to(ROOT)}")
    if all(path.is_file() for path in shared_explainers):
        hashes = {sha256(path) for path in shared_explainers}
        if len(hashes) != 1:
            errors.append("Q16-Q18 shared explanation-paper.pdf copies are not byte-identical")

    for html_path in sorted((ROOT / "experiments").glob("*/interactive-explanation.html")):
        parser = LocalReferenceParser()
        parser.feed(html_path.read_text(encoding="utf-8", errors="replace"))
        for tag, key, reference in parser.references:
            parsed = urlsplit(reference)
            if key == "src" and parsed.scheme in {"http", "https"}:
                errors.append(
                    f"external HTML resource dependency in {html_path.relative_to(ROOT)}: {reference}"
                )
                continue
            if parsed.scheme or reference.startswith(("data:", "mailto:", "javascript:", "#")):
                continue
            if not parsed.path:
                continue
            target = html_path.parent / unquote(parsed.path)
            if not target.exists():
                errors.append(
                    f"broken local HTML reference in {html_path.relative_to(ROOT)}: {reference}"
                )

    if not REPORT.is_file():
        errors.append("concise all-experiments PDF report is missing")

    archive = load_json(ARCHIVE_RECEIPT)
    archive_text = json.dumps(archive, sort_keys=True)
    if archive_text.count("old/") < 21 or "old/master-pre-curation" not in archive_text:
        errors.append("archive receipt does not contain all expected old/* references")

    ignored_roots = {".git", ".venv", "__pycache__"}
    for path in ROOT.rglob("*"):
        if not path.is_file() or any(part in ignored_roots for part in path.parts):
            continue
        relative = path.relative_to(ROOT)
        size = path.stat().st_size
        if size >= MAX_TRACKED_FILE_BYTES:
            errors.append(f"oversized tracked candidate: {relative} ({size} bytes)")
        if path.suffix.lower() not in TEXT_SUFFIXES or size > 5 * 1024 * 1024:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for label, pattern in FORBIDDEN_TEXT_PATTERNS.items():
            if pattern.search(text):
                errors.append(f"{label} found in {relative}")

    if errors:
        print("Repository validation failed:")
        for error in errors:
            print(f"- {error}")
        return 1

    print(
        "Repository validation passed: "
        f"{len(expected_packages)} packages, Q16-Q18 explanations, "
        "archive receipt, concise report, JSON, size and confidentiality checks."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
