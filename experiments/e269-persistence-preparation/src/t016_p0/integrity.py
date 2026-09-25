"""Fresh complete-file integrity checks; historical source certificates stay distinct."""
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path


def now():
    return datetime.now(timezone.utc).isoformat()


def file_hash(path):
    digest = sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def check_file(path, expected):
    path = Path(path).resolve()
    actual = file_hash(path)
    if actual != expected:
        raise ValueError(f"Integrity mismatch: {path}")
    return {"path": str(path), "sha256": actual, "bytes": path.stat().st_size,
            "checked_utc": now(), "verification": "fresh complete-file SHA256"}


def verify_packet(root, expected_manifest):
    root = Path(root).resolve()
    checked = [check_file(root / "manifest.sha256", expected_manifest)]
    for line in (root / "manifest.sha256").read_text(encoding="utf-8-sig").splitlines():
        digest, name = line.split("  ", 1)
        path = (root / name).resolve()
        path.relative_to(root)
        checked.append(check_file(path, digest))
    return checked


def verify_contract(path, expected, artifacts):
    path = Path(path)
    checked = [check_file(path, expected)]
    contract = read_json(path)
    bindings = {}
    for key in ("acquisition_proof", "policy", "source_acquisition_policy", "receipt_prefix_exclusions", "source_provenance"):
        bindings[str((path.parent / contract[key + "_file"]).resolve())] = contract[key + "_sha256"]
    bindings[str((path.parent / contract["normalizer_source_file"]).resolve())] = contract["normalizer_code_sha256"]
    helper = Path(artifacts) / "T-008/r2/code/producer_interface.py"
    bindings[str(helper)] = contract["reused_producer_code_sha256"]
    cont = contract["continuity"]
    bindings[str(path.parent / cont["source_segments_file"])] = cont["source_segments_sha256"]
    for source in contract["sources"]:
        bindings[str(path.parent / source["file"])] = source["sha256"]
    for name, digest in contract["evidence_files"].items():
        bindings[str(path.parent / name)] = digest
    checked += [check_file(filename, digest) for filename, digest in bindings.items()]
    return contract, checked
