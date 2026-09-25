"""Run source components unchanged; write results only to this artifact directory."""
from pathlib import Path
import importlib.util
import json
import os
import platform
import sys
import time

sys.dont_write_bytecode = True
os.environ.setdefault("OMP_NUM_THREADS", "2")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "2")
os.environ.setdefault("MKL_NUM_THREADS", "2")
ROOT = Path(__file__).resolve().parents[1] / "runtime"
SOURCE = Path(__file__).resolve().parents[1] / "external" / "anon-experiments"


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    started = time.monotonic()
    result = dict(scope="Fresh software checks on original synthetic fixtures; not real-market replications", python=sys.version, platform=platform.platform(), source_snapshot_commits=json.loads((SOURCE / "SOURCES.json").read_text()))
    output = ROOT / "baseline_checks"
    (output / "logs").mkdir(parents=True, exist_ok=True)
    q16 = load(SOURCE / "Q16/code/count_probe.py", "source_count_probe")
    q16.P = output
    q16.run(seed=16029001, n=1000)
    q16_out = json.loads((output / "logs/count_probe.json").read_text())
    result["Q16"] = {k:v for k,v in q16_out.items() if k!="records"}
    print("Q16 passed",flush=True)
    sys.path.insert(0, str(SOURCE / "Q17/code"))
    q17 = load(SOURCE / "Q17/code/sanity.py", "source_q17_sanity")
    result["Q17"] = q17.smoke()
    print("Q17 passed",flush=True)
    q18 = load(SOURCE / "Q18/code/smoke.py", "source_q18_smoke")
    result["Q18"] = q18.smoke()
    print("Q18 passed",flush=True)
    result["seconds"] = time.monotonic()-started
    (ROOT / "baseline_checks.json").write_text(json.dumps(result,indent=2))
    print(json.dumps({k:v for k,v in result.items() if k!="source_snapshot_commits"},indent=2),flush=True)


if __name__ == "__main__":
    main()
