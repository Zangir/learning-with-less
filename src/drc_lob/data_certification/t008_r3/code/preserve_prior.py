"""Verify frozen earlier revisions without rewriting their evidence."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = {
    "r1": "efba8426b13af1820b7308f3578a39ca38a4e030bc0ee69f10ab5a350cf389d8",
    "r2": "e234b2342c53cf01c9857231d6c413abc8ac1e3223122e9f12547df93f772d4a",
}


def sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main():
    started = time.monotonic()
    results = {}
    for revision, directory in (("r1", ROOT.parent), ("r2", ROOT.parent / "r2")):
        manifest_path = directory / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        actual = sha(manifest_path)
        checks = {name: sha(directory / name) == expected
                  for name, expected in manifest["artifact_sha256"].items()}
        results[revision] = {
            "manifest_sha256": actual,
            "expected_manifest_sha256": EXPECTED[revision],
            "manifest_preserved": actual == EXPECTED[revision],
            "files_checked": len(checks),
            "artifact_bytes": sum((directory / name).stat().st_size for name in checks),
            "failures": [name for name, passed in checks.items() if not passed],
        }
    passed = all(r["manifest_preserved"] and not r["failures"] for r in results.values())
    result = {"schema": "t008-prior-preservation/3", "checked_at_utc": datetime.now(timezone.utc).isoformat(),
              "passed": passed, "results": results, "elapsed_seconds": time.monotonic() - started,
              "code_sha256": sha(Path(__file__))}
    output = ROOT / "evidence/prior_preservation.json"
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    assert passed


if __name__ == "__main__":
    main()
