"""Fixed local execution settings for T-018 source recovery."""
from pathlib import Path
import hashlib
import json
import os
import random
from datetime import datetime, timezone

SEED = 20260919
random.seed(SEED)
for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[name] = "2"

BASE = Path(__file__).resolve().parents[2] / "runtime"
OUT = BASE / "T-018/r1"
PRIOR = BASE / "T-008"
EXCHANGE = BASE / "mandatory-completion-exchange/T-018"
NS = 1_000_000_000


def now():
    return datetime.now(timezone.utc).isoformat()


def stamp(note):
    line = now() + " " + note
    print(line, flush=True)
    with (OUT / "timing.log").open("a", encoding="utf-8") as stream:
        stream.write(line + "\n")


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def save(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def bind(path):
    path = Path(path)
    return dict(path=str(path), bytes=path.stat().st_size, sha256=sha(path))


def pin():
    import psutil
    proc = psutil.Process()
    proc.cpu_affinity([0, 1])
    return proc


def utc_ns(value):
    if not value.endswith("Z"):
        raise ValueError("UTC Z suffix required")
    whole, _, fraction = value[:-1].partition(".")
    if len(fraction) > 9 or (fraction and not fraction.isdigit()):
        raise ValueError("Invalid fractional UTC timestamp")
    seconds = int(datetime.strptime(whole, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc).timestamp())
    return seconds * NS + int(fraction.ljust(9, "0") or 0)
