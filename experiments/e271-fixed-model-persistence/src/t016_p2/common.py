"""Fixed paths, identities and transparent artifact serialization."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import numpy as np

WORK = Path(__file__).resolve().parents[1]
ARTIFACTS = Path(__file__).resolve().parents[2] / 'runtime'
OUT = ARTIFACTS / 'T-016/r4-cpr-comparison'
SOURCE = ARTIFACTS / 'cycle-20260922-0718/frozen-R-027'
REVIEW = ARTIFACTS / 'cycle-20260922-0820/frozen-RV-025'
PACKAGES = Path(__file__).resolve().parents[2] / 'runtime' / 'python-packages'
BASE_COMMIT = 'b884c67448c4a30d57e9ad77756bcb69a6bebe00'
SOURCE_SHA = '15e90836cc3d4a6086b1c359331c66cf303ce95e37295dd3e3546ffac42b9d64'
REVIEW_SHA = '221acc89f50bd0deb683f478eacd7447a265fd858df5d4dcc0e8568d1a5f0cc2'
PROTOCOL_SHA = '9017958555471c87c1c572233682506d1c69a03353bb9ad6b514b18827b31702'
SEED = 20260919


def now():
    return datetime.now(timezone.utc).isoformat()


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def dump(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def stage(name, detail):
    line = f'{now()} | {name} | {detail}'
    print(line, flush=True)
    with (OUT / 'timings.log').open('a', encoding='utf-8') as stream:
        stream.write(line + '\n')


def load_arrays():
    with np.load(OUT / 'prepared-cohort.npz', allow_pickle=False) as archive:
        return {key: archive[key] for key in archive.files}


def verify_json_packet(root, expected):
    assert sha(root / 'artifact-manifest.json') == expected
    records = []
    for entry in read(root / 'artifact-manifest.json')['files']:
        path = (root / entry['path']).resolve()
        path.relative_to(root.resolve())
        assert sha(path) == entry['sha256'] and path.stat().st_size == entry['size_bytes']
        records.append(entry)
    return records
